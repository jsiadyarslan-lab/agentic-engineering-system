"""E1 bwrap substrate adapter — bubblewrap-backed isolated execution.

AES-EXP-04 §3: the previous "isolation substrate unavailable" verdict
on this host was an unsupported-architecture inference, not a probe.
The host is ``Linux aarch64`` running Oracle Linux 9.8, and the
official OL9 repository ships ``bubblewrap`` for ``aarch64``
(0.6.3-1.el9_8.1). Bubblewrap was installed from that repository and
its capabilities were PROVEN on the host (10/10 probes as the service
user ``opc`` with SELinux Enforcing):

- unprivileged user namespace + mount/pid/net/uts/ipc/cgroup unshare;
- read-only bind of ``/`` and read-write bind of a workspace dir;
- private ``/tmp`` tmpfs and fresh ``/dev``;
- network isolation (outbound connect fails);
- pid isolation (host process table hidden);
- ``SIGKILL`` on timeout propagates (rc=124 observed);
- stdin/stdout/stderr passthrough and exit-code propagation;
- host files hidden behind the private tmpfs.

This adapter implements the SAME :class:`substrate.sandbox.SubstrateAdapter`
port as :class:`substrate.local_substrate.LocalSubstrateAdapter` with
bubblewrap as the isolation mechanism:

- ``--unshare-all`` (user/mount/pid/uts/net/ipc/cgroup namespaces);
- a PRIVATE per-run rootfs (host ``run_dir`` prepared by the
  supervisor, wiped at teardown) bound READ-ONLY as ``/`` via an
  fd-based bind — the target never sees the real host ``/``;
- the image roots (``/usr`` + the interpreter's roots), the granted
  source tree at ``/work`` (read-only) and the workspace custody
  directory at ``/artifacts`` (the ONLY writable artifact exit) are
  bound into that root at their real paths — fd-based binds
  (``--ro-bind-fd``/``--bind-fd``) make every source namespace-order
  independent (the failure mode that plain-path binds hit on a
  read-only root);
- ``--tmpfs /proc`` — the host process table is HIDDEN (an empty tmpfs
  overlays the root — stronger than a fresh procfs); ``--dev /dev`` —
  fresh minimal device tree; ``--tmpfs /tmp`` scratch;
- ``--clearenv`` + ``--setenv`` — the request's permitted env NAMES only
  (values supplied by the image, never by callers — contract parity);
- ``PR_SET_NO_NEW_PRIVS`` is always set by bubblewrap itself;
- a seccomp deny-list (aarch64 syscall numbers, verified against this
  kernel's ``asm-generic/unistd.h``) loaded via ``--seccomp`` blocks the
  privileged escape surface (mount/umount2/pivot_root/chroot/unshare/
  setns/open_tree/move_mount/fs*mount/bpf/kexec/module loading/...);
- rlimits (RLIMIT_AS/FSIZE/NPROC/CPU/NOFILE/CORE) and CPU affinity are
  applied to the spawned bwrap process and inherited by the target;
- wall-clock watchdog in the supervisor + hard ``SIGKILL`` to the whole
  process group on timeout or output breach (``--die-with-parent`` and
  ``--new-session`` keep the group kill reliable).

Fail-closed parity with the local substrate: no host-execution fallback;
a sandbox executes exactly once per id; outputs are bounded and persisted
as referenceable artifacts; artifacts exit only through the custody bind;
teardown always; any internal error yields a truthful
``FAILED_TO_START``/``KILLED`` record — never a fabricated success.

Honest mechanism semantics (declared, owner-visible): memory is
``RLIMIT_AS`` per process — NOT aggregate memcg; the scratch tmpfs is
capped by the kernel default for tmpfs (no ``--size`` support in
bwrap 0.6.3) plus per-file ``RLIMIT_FSIZE`` — NOT a requested workspace
ceiling; the process count is ``RLIMIT_NPROC`` with the ambient uid
baseline accounted; cgroupfs is not mounted and NO cgroup control is
claimed. ``/proc`` inside the sandbox is an EMPTY tmpfs (host pids are
not visible) — stronger than mounting a fresh procfs.
"""

from __future__ import annotations

import errno as _errno
import hashlib
import os
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

try:  # unix-only — غيابه (Windows) لا يكسر الاستيراد (أمر 005)
    import resource
except ImportError:  # pragma: no cover — يُختبر بمحاكاة الحراسة
    resource = None  # type: ignore[assignment]

from substrate.limits import (
    E1_LIMITS_DEFAULTS,
    ExecutionLimits,
    validate_against_defaults,
)
from substrate.local_substrate import (
    ARTIFACTS_MOUNT,
    SANDBOX_HOSTNAME,
    SANDBOX_NOFILE_LIMIT,
    SCRATCH_MOUNT,
    WORK_MOUNT,
    LocalImage,
    SubstrateUnavailable,
    _REAL_UID,
    _interpreter_roots,
    _maximal_roots,
    _symlink_chain_dirs,
)
from substrate.sandbox import (
    PERMITTED_ENV_NAMES,
    NetworkMode,
    SandboxExecutionRecord,
    SandboxManager,
    SandboxRequest,
    SandboxTermination,
    SubstrateAdapter,
    SubstrateDescriptor,
    TeardownEvidence,
)
from substrate.workspace import ArtifactCustodyEntry

# ---------------------------------------------------------------------------
# seccomp constants — aarch64 (verified against this kernel's headers)
# ---------------------------------------------------------------------------

#: AUDIT_ARCH_AARCH64 = EM_AARCH64 (183) | AUDIT_ARCH_64BIT (0x40000000)
AUDIT_ARCH_AARCH64 = 0xC00000B7

#: aarch64 syscall numbers of the privileged escape surface. Every
#: number below was verified against ``/usr/include/asm-generic/unistd.h``
#: and ``ausyscall`` on the target host (Oracle Linux 9.8, aarch64) —
#: none was carried over from the x86_64 table (whose numbers name
#: different syscalls on aarch64, e.g. x86 chroot(161) is setxattr here).
DENIED_SYSCALLS_AARCH64: tuple[int, ...] = (
    39,   # umount2
    40,   # mount
    41,   # pivot_root
    51,   # chroot
    60,   # quotactl
    97,   # unshare
    104,  # kexec_load
    105,  # init_module
    106,  # delete_module
    117,  # ptrace
    142,  # reboot
    224,  # swapon
    225,  # swapoff
    241,  # perf_event_open
    262,  # fanotify_init
    264,  # name_to_handle_at
    265,  # open_by_handle_at
    268,  # setns
    273,  # finit_module
    280,  # bpf
    294,  # kexec_file_load
    428,  # open_tree      (new mount API)
    429,  # move_mount     (new mount API)
    430,  # fsopen         (new mount API)
    431,  # fsconfig       (new mount API)
    432,  # fsmount        (new mount API)
    433,  # fspick         (new mount API)
    442,  # mount_setattr  (new mount API)
    443,  # quotactl_fd
)

SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000

_BPF_LD_W_ABS = 0x20
_BPF_JMP_JEQ_K = 0x15
_BPF_RET_K = 0x06

#: Where the probe cache lives (module-level; one real launch per process).
_BWRAP_CACHE: dict[str, object] = {}

#: Machinery margin for RLIMIT_NPROC (proven on the target host): the
#: kernel charges the per-uid NPROC counter for tasks that are NOT
#: observable in /proc — user-namespace creation and the pid-1 fork of
#: the sandbox itself are charged against the same counter. With L live
#: tasks the machinery provably needs ≈ 2L; the margin is added on top
#: of the doubled baseline and the requested max_processes.
NPROC_MACHINERY_MARGIN = 4


def _bwrap_binary() -> str:
    """Absolute bwrap path or ``""`` (shutil.which wrapper)."""
    return shutil.which("bwrap") or ""


def _count_uid_tasks() -> int:
    """Count TASKS (threads included, task-dir exact) owned by the uid.

    RLIMIT_NPROC is charged per task via ucounts — the baseline must
    mirror what the kernel compares against (a TGID-only count
    undercounts multi-threaded services and strands the launch).
    """
    total = 0
    try:
        entries = os.listdir("/proc")
    except OSError:  # pragma: no cover — /proc always present here
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/status", "r") as handle:
                uid = None
                for line in handle:
                    if line.startswith("Uid:"):
                        uid = line.split()[1]
                        break
            if uid != str(_REAL_UID):
                continue
            total += len(os.listdir(f"/proc/{entry}/task"))
        except (OSError, ValueError, IndexError):
            continue
    return total


def _read_max_user_namespaces() -> int:
    try:
        with open("/proc/sys/user/max_user_namespaces", "r") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return 0


def _seccomp_bpf_bytes() -> bytes:
    """Compile the aarch64 deny-list into a seccomp BPF program.

    Program shape (struct seccomp_data: nr@0, arch@4):
      LD [arch]; JEQ AUDIT_ARCH_AARCH64 else DENY(ENOSYS);
      LD [nr]; N x JEQ denied -> DENY(EPERM); RET ALLOW; RET DENY.
    Mismatched architecture denies with ENOSYS — a non-native arch can
    never slip past the number table (the direction the x86_64 filter
    got wrong; corrected here fail-closed).
    """
    denied = DENIED_SYSCALLS_AARCH64
    n = len(denied)
    instructions: list[tuple[int, int, int, int]] = [
        (_BPF_LD_W_ABS, 0, 0, 4),                    # load arch
        (_BPF_JMP_JEQ_K, 0, n + 2, AUDIT_ARCH_AARCH64),
        (_BPF_LD_W_ABS, 0, 0, 0),                    # load nr
    ]
    for index, nr in enumerate(denied):
        # equal -> skip RET_ALLOW + the remaining checks -> RET_DENY
        instructions.append((_BPF_JMP_JEQ_K, n - index, 0, nr))
    instructions.append((_BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW))
    instructions.append((_BPF_RET_K, 0, 0, SECCOMP_RET_ERRNO | _errno.EPERM))
    return b"".join(struct.pack("<HBBI", code, jt, jf, k)
                    for (code, jt, jf, k) in instructions)


def _launch_probe(argv_tail: tuple[str, ...], *, use_seccomp: bool) -> tuple[bool, str]:
    """One real bubblewrap launch — the only proof that counts."""
    binary = _bwrap_binary()
    if not binary:
        return False, "bwrap binary not found on PATH"
    argv = [
        binary, "--unshare-all", "--die-with-parent", "--new-session",
        "--ro-bind", "/", "/",
        "--tmpfs", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
    ]
    pass_fds: tuple[int, ...] = ()
    seccomp_fd: int | None = None
    if use_seccomp:
        program = _seccomp_bpf_bytes()
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, program)
        finally:
            os.close(write_fd)
        seccomp_fd = read_fd
        pass_fds = (read_fd,)
        argv += ["--seccomp", str(read_fd)]
    argv += ["--", *argv_tail]
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv, capture_output=True, timeout=30, pass_fds=pass_fds,
        )
    except subprocess.TimeoutExpired:
        return False, "bwrap probe timed out after 30s"
    except OSError as error:
        return False, f"bwrap probe could not start: {error}"
    finally:
        if seccomp_fd is not None:
            try:
                os.close(seccomp_fd)
            except OSError:
                pass
    if result.returncode != 0:
        tail = (result.stderr or b"").decode("utf-8", "replace").strip()[-200:]
        return False, f"bwrap probe exited {result.returncode}: {tail}"
    return True, ""


def bwrap_capabilities(*, force: bool = False) -> dict[str, object]:
    """Truthful capability record of the bubblewrap substrate.

    ``supported`` is True only when EVERY required capability is proven
    on this host right now (one real launch, cached per process; the
    per-execute path re-checks the cheap invariants and the launch
    itself remains the final arbiter — fail-closed either way).
    """
    if not force and _BWRAP_CACHE.get("probed_at") is not None:
        return dict(_BWRAP_CACHE)
    capabilities: dict[str, object] = {
        "mechanism": "bubblewrap",
        "machine": os.uname().machine if hasattr(os, "uname") else "unknown",
        "real_uid": os.getuid() if hasattr(os, "getuid") else -1,
        "bwrap_present": False,
        "bwrap_path": "",
        "bwrap_version": "",
        "max_user_namespaces": _read_max_user_namespaces(),
        "userns_enabled": _read_max_user_namespaces() > 0,
        "seccomp_deny_syscalls": len(DENIED_SYSCALLS_AARCH64),
        "audit_arch": hex(AUDIT_ARCH_AARCH64),
        "launch_probe": "",
    }
    reason = ""
    binary = _bwrap_binary()
    if not binary:
        reason = "bubblewrap غير مثبت — الحزمة المطلوبة: bubblewrap (ol9_baseos_latest)"
    else:
        capabilities["bwrap_present"] = True
        capabilities["bwrap_path"] = binary
        try:
            version_out = subprocess.run(  # noqa: S603 — ثابت
                [binary, "--version"], capture_output=True, timeout=10,
            )
            match = re.search(
                r"([0-9]+\.[0-9]+\.[0-9]+)",
                (version_out.stdout or b"").decode("utf-8", "replace"),
            )
            capabilities["bwrap_version"] = match.group(1) if match else "unknown"
        except (OSError, subprocess.TimeoutExpired):
            capabilities["bwrap_version"] = "unknown"
        if not capabilities["userns_enabled"]:
            reason = (
                "user namespaces معطلة على النواة "
                "(max_user_namespaces=0) — bwrap لا يعمل بدونها"
            )
        else:
            ok, probe_reason = _launch_probe(
                ("/bin/sh", "-c", "echo BWRAP_PROBE_OK"), use_seccomp=True,
            )
            capabilities["launch_probe"] = "OK" if ok else f"FAILED: {probe_reason}"
            if ok:
                capabilities["supported"] = True
            else:
                reason = f"إطلاق bwrap الفعلي فشل: {probe_reason}"
    if capabilities.get("supported") is not True:
        capabilities["supported"] = False
        capabilities["reason"] = reason or "bwrap substrate unavailable"
    capabilities["probed_at"] = time.time()
    _BWRAP_CACHE.clear()
    _BWRAP_CACHE.update(capabilities)
    return dict(_BWRAP_CACHE)


# ---------------------------------------------------------------------------
# images (same LocalImage model as the local substrate)
# ---------------------------------------------------------------------------


def default_bwrap_images() -> dict[str, LocalImage]:
    """The verified bwrap images derived from the running interpreter.

    On an unsupported host this returns ``{}`` — every execution then
    fails honestly with FAILED_TO_START (no raw ValueError leaks).
    """
    if not bwrap_capabilities().get("supported"):
        return {}
    interpreter = sys.executable
    if not os.path.isabs(interpreter):  # pragma: no cover - defensive
        interpreter = os.path.abspath(interpreter)
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    roots = _interpreter_roots(interpreter)
    bin_dirs = [
        str(Path(root) / "bin")
        for root in roots
        if (Path(root) / "bin").is_dir()
    ]
    path_entries = tuple(
        dir_path for dir_path in dict.fromkeys(bin_dirs + ["/usr/bin", "/bin"])
    )
    name = f"local-python-{version}"
    return {
        name: LocalImage(
            name=name,
            interpreter=interpreter,
            read_only_roots=roots,
            entrypoint_aliases=frozenset(
                {"python", "python3", f"python{sys.version_info.major}"}
            ),
            path_entries=path_entries,
        )
    }


#: Image name of the git image (the real /usr/bin/git binary).
BWRAP_GIT_IMAGE_NAME = "local-git"

_GIT_INTERPRETER = "/usr/bin/git"


def bwrap_git_image() -> LocalImage:
    """The git image: the REAL ``/usr/bin/git`` binary (parity with E4).

    Raises :class:`SubstrateUnavailable` (imported from the local
    substrate module so callers' except-clauses keep working) on an
    unsupported host — never a raw ValueError.
    """
    if not bwrap_capabilities().get("supported"):
        raise SubstrateUnavailable(
            "الركيزة المعزولة غير متاحة — تتطلب bubblewrap فعالاً "
            "(ثبّت الحزمة: bubblewrap)؛ لن يبدأ أي تنفيذ"
        )
    roots = _maximal_roots(
        tuple(_interpreter_roots(_GIT_INTERPRETER))
        + (os.path.dirname(_GIT_INTERPRETER),)
    )
    return LocalImage(
        name=BWRAP_GIT_IMAGE_NAME,
        interpreter=_GIT_INTERPRETER,
        read_only_roots=roots,
        entrypoint_aliases=frozenset({"git"}),
        path_entries=("/usr/bin", "/bin"),
    )


# ---------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------

DESCRIPTOR_BWRAP = SubstrateDescriptor(
    name="local-bwrap-substrate",
    isolation_class="linux-namespaces-bwrap",
    network_support="none",
)

DECLARED_SECURITY_POSTURE_BWRAP: dict[str, object] = {
    "mechanism": "bubblewrap (bwrap) — unprivileged user namespace",
    "namespaces": ("user", "mount", "pid", "uts", "network", "ipc", "cgroup"),
    "identity_mapping": "1:1 real uid (no privilege elevation)",
    "rootfs": "private per-run rootfs bound read-only as / "
              "(host run_dir, wiped at teardown)",
    "readonly": ("/", "/usr", "image roots", WORK_MOUNT),
    "writable": (SCRATCH_MOUNT, ARTIFACTS_MOUNT),
    "proc": "empty tmpfs over /proc (host process table hidden)",
    "dev": "fresh minimal /dev (bwrap-managed)",
    "no_new_privs": True,
    "capabilities": "none on the host (unprivileged user namespace)",
    "seccomp": f"deny-list ({len(DENIED_SYSCALLS_AARCH64)} privileged "
               "syscalls -> EPERM, aarch64 numbers)",
    "network": "NONE (fresh network namespace, loopback only, down)",
    "pid1": "the target executes as pid 1 of the sandbox pid namespace",
    "cpu": "affinity pinning + RLIMIT_CPU backstop (NOT CFS quota)",
    "memory": "RLIMIT_AS per process (NOT aggregate memcg)",
    "process_count": "RLIMIT_NPROC with ambient uid baseline accounted "
                     "(doubled task baseline + request + machinery margin — "
                     "namespace creation and pid-1 fork charge the same "
                     "per-uid counter beyond what /proc shows)",
    "filesystem_size": "per-file RLIMIT_FSIZE (EFBIG); tmpfs scratch "
                       "(kernel default cap — no --size in bwrap 0.6.3)",
}


class BubblewrapSubstrateAdapter(SubstrateAdapter):
    """The bubblewrap local substrate (AES-EXP-04 §3.2).

    Contract obligations are the SAME as the local substrate adapter:
    mechanical limits enforcement, single execute per sandbox id,
    bounded persisted outputs, custody-hash artifacts, teardown always,
    fail-closed truthful failure records.
    """

    def __init__(
        self,
        *,
        images: Mapping[str, LocalImage] | None = None,
        base_dir: Path | str | None = None,
        self_check: bool = True,
    ) -> None:
        capabilities = bwrap_capabilities()
        if self_check and not capabilities.get("supported"):
            raise RuntimeError(
                "bwrap substrate unsupported in this environment: "
                f"{capabilities.get('reason')}"
            )
        self._images: dict[str, LocalImage] = dict(
            images if images is not None else default_bwrap_images()
        )
        self._base_dir = Path(base_dir) if base_dir is not None else None
        self._executed_ids: set[str] = set()
        self._active_runs: dict[str, dict[str, object]] = {}
        self._run_evidence: dict[str, dict[str, object]] = {}

    # -- introspection -----------------------------------------------------

    def descriptor(self) -> SubstrateDescriptor:
        return DESCRIPTOR_BWRAP

    @property
    def image_names(self) -> frozenset[str]:
        return frozenset(self._images)

    def declared_posture(self) -> dict[str, object]:
        return dict(DECLARED_SECURITY_POSTURE_BWRAP)

    def execution_evidence(self, sandbox_id: str) -> dict[str, object]:
        run = self._run_evidence.get(sandbox_id, {})
        return dict(run)

    # -- execution -----------------------------------------------------------

    def execute(self, request: SandboxRequest) -> SandboxExecutionRecord:
        try:
            return self._execute(request)
        except Exception as error:  # fail closed — truthful record, never raise
            return self._failure_record(
                request if isinstance(request, SandboxRequest) else None,
                SandboxTermination.FAILED_TO_START,
                f"adapter internal error: {type(error).__name__}: {error}",
            )

    def _execute(self, request: SandboxRequest) -> SandboxExecutionRecord:
        if not isinstance(request, SandboxRequest):
            raise TypeError("expected SandboxRequest")
        if not bwrap_capabilities().get("supported"):
            return self._failure_record(
                request, SandboxTermination.FAILED_TO_START,
                "bwrap substrate requires a working bubblewrap on this "
                "host — لن يُنفَّذ شيء على المضيف مباشرة",
            )
        if request.sandbox_id in self._executed_ids:
            return self._failure_record(
                request, SandboxTermination.NOT_RUN,
                f"sandbox {request.sandbox_id!r} already executed "
                "(adapter single-execute rule)",
            )
        policy = validate_against_defaults(request.limits)
        if not policy.valid:
            return self._failure_record(
                request, SandboxTermination.NOT_RUN,
                f"adapter-side limits policy: {policy.detail}",
            )
        image = self._images.get(request.image)
        if image is None:
            return self._failure_record(
                request, SandboxTermination.FAILED_TO_START,
                f"image {request.image!r} is not provided by the bwrap "
                f"substrate (available: {sorted(self._images)})",
            )
        if request.network is not NetworkMode.NONE:
            return self._failure_record(
                request, SandboxTermination.NOT_RUN,
                "bwrap substrate enforces network NONE (D-04=A)",
            )
        unknown_env = sorted(set(request.env_names) - set(PERMITTED_ENV_NAMES))
        if unknown_env:
            return self._failure_record(
                request, SandboxTermination.NOT_RUN,
                f"environment names outside the permitted set: {unknown_env}",
            )
        command = tuple(request.command)
        if not command or command[0] not in image.entrypoint_aliases:
            return self._failure_record(
                request, SandboxTermination.FAILED_TO_START,
                f"entrypoint {command[0]!r} is not provided by image "
                f"{image.name!r} (aliases: {sorted(image.entrypoint_aliases)})",
            )
        sources_root = request.sources_root or ""
        if sources_root and not os.path.isdir(sources_root):
            return self._failure_record(
                request, SandboxTermination.FAILED_TO_START,
                f"sources_root {sources_root!r} is not a directory",
            )
        artifacts_dir = request.artifacts_dir or ""
        if artifacts_dir:
            os.makedirs(artifacts_dir, exist_ok=True)

        self._executed_ids.add(request.sandbox_id)
        before = self._snapshot_artifacts(artifacts_dir)
        return self._run(
            request, image, command, sources_root, artifacts_dir, before
        )

    # -- the real run: CREATE -> START -> EXECUTE -> OBSERVE -> DESTROY ----

    def _prepare_rootfs(self, run_dir: Path, image: LocalImage) -> Path:
        """Build the per-run rootfs skeleton on the host (supervisor side).

        Mirrors the local substrate's rootfs layout: minimal dirs,
        merged-/usr symlinks, and pre-created mountpoints for every
        image root — the sandbox root itself is bound READ-ONLY, so
        every bind target must already exist (no in-sandbox mkdir).
        """
        rootfs = run_dir / "rootfs"
        for relative in ("usr", "dev", "tmp", "work", "artifacts", "proc"):
            os.makedirs(os.path.join(rootfs, relative), exist_ok=True)
        for link, target in (
            ("bin", "usr/bin"), ("lib", "usr/lib"),
            ("lib64", "usr/lib64"), ("sbin", "usr/sbin"),
        ):
            link_path = os.path.join(rootfs, link)
            if not os.path.lexists(link_path):
                os.symlink(target, link_path)
        for root in image.read_only_roots:
            if root == "/usr":
                continue
            mount_point = os.path.join(rootfs, root.lstrip("/"))
            os.makedirs(mount_point, exist_ok=True)
        return rootfs

    def _run(
        self,
        request: SandboxRequest,
        image: LocalImage,
        command: tuple[str, ...],
        sources_root: str,
        artifacts_dir: str,
        before: dict[str, tuple[int, int]],
    ) -> SandboxExecutionRecord:
        limits = request.limits
        sandbox_id = request.sandbox_id
        run_dir = Path(tempfile.mkdtemp(
            prefix=f"e1-bw-{sandbox_id}-", dir=self._base_dir
        ))
        rootfs_dir = self._prepare_rootfs(run_dir, image)
        uid_baseline = _count_uid_tasks()
        # the kernel charges unshare(NEWUSER) and the pid-1 fork against
        # the per-uid NPROC counter beyond the observable task count
        # (proven on the target host: with L live tasks the machinery
        # needs ≈ 2L) — the doubled baseline + margin keeps the machinery
        # bootable while max_processes stays the added ceiling.
        nproc_limit = (
            uid_baseline * 2
            + limits.max_processes
            + NPROC_MACHINERY_MARGIN
        )
        self._active_runs[sandbox_id] = {
            "run_dir": str(run_dir), "rootfs_dir": str(rootfs_dir),
        }

        started = time.time()
        binary = str(bwrap_capabilities()["bwrap_path"])
        argv, bind_fds, seccomp_read_fd = self._build_argv(
            rootfs_dir, image, command, sources_root, artifacts_dir,
            request.env_names,
        )

        def _preexec() -> None:  # rlimits + affinity, inherited by target
            if resource is None:  # pragma: no cover — unix-only by design
                raise RuntimeError("rlimits require the resource module")
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_NOFILE, (SANDBOX_NOFILE_LIMIT,) * 2)
            resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes,) * 2)
            resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_output_bytes,) * 2)
            resource.setrlimit(resource.RLIMIT_NPROC, (nproc_limit, nproc_limit))
            resource.setrlimit(resource.RLIMIT_CPU, (limits.timeout_seconds,) * 2)
            available = sorted(os.sched_getaffinity(0))
            pinned = available[: max(1, min(limits.vcpu, len(available)))]
            os.sched_setaffinity(0, set(pinned))

        try:
            process = subprocess.Popen(  # noqa: S603 — argv ثابت بلا قشرة
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(run_dir),
                env={"PATH": "/usr/bin:/bin"},
                start_new_session=True,
                pass_fds=tuple(set(bind_fds) | ({seccomp_read_fd}
                    if seccomp_read_fd is not None else set())),
                preexec_fn=_preexec,
            )
        except OSError as error:
            for fd in (*bind_fds, *( [seccomp_read_fd]
                    if seccomp_read_fd is not None else [] )):
                try:
                    os.close(fd)
                except OSError:
                    pass
            return self._failure_record(
                request, SandboxTermination.FAILED_TO_START,
                f"bwrap launch failed: {error}",
            )
        for fd in (*bind_fds, *( [seccomp_read_fd]
                if seccomp_read_fd is not None else [] )):
            try:
                os.close(fd)
            except OSError:
                pass

        # ---- supervisor: observe, enforce, collect ----
        stdout = b""
        stderr = b""
        termination = SandboxTermination.COMPLETED
        deadline = started + limits.timeout_seconds
        output_cap = limits.max_output_bytes
        observe_samples = 0
        alive_samples = 0
        assert process.stdout is not None and process.stderr is not None
        fds = (process.stdout.fileno(), process.stderr.fileno())
        eof: set[int] = set()
        while len(eof) < 2:
            if time.time() > deadline:
                self._kill_group(process.pid)
                termination = SandboxTermination.TIMEOUT
                break
            readable, _, _ = select.select(list(fds), [], [], 0.2)
            observe_samples += 1
            if os.path.exists(f"/proc/{process.pid}"):
                alive_samples += 1
            breach = False
            for fd in readable:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    eof.add(fd)
                    continue
                if not chunk:
                    eof.add(fd)
                    continue
                if fd == fds[0]:
                    stdout += chunk
                else:
                    stderr += chunk
                if len(stdout) + len(stderr) > output_cap:
                    self._kill_group(process.pid)
                    termination = SandboxTermination.LIMIT_BREACH
                    breach = True
                    break
            if breach:
                break
        try:
            process.stdout.close()
            process.stderr.close()
        except OSError:  # pragma: no cover
            pass
        exit_code: int | None = None
        try:
            exit_code = process.wait()
        except (ChildProcessError, OSError):  # pragma: no cover
            pass
        duration_ms = int((time.time() - started) * 1000)
        if (
            termination is SandboxTermination.COMPLETED
            and exit_code not in (0, None)
            and stderr.startswith(b"bwrap:")
        ):
            # bwrap itself failed setup — the target never started
            termination = SandboxTermination.FAILED_TO_START

        # ---- DESTROY: teardown always + residue attestation ----
        teardown = self._teardown_run(sandbox_id, process.pid)

        # ---- bounded outputs persisted first (they are evidence) ----
        stdout_reference, stderr_reference = self._persist_outputs(
            sandbox_id, artifacts_dir, stdout, stderr
        )
        # ---- artifact extraction + custody entries ----
        artifacts, changed_files, artifact_breach = self._collect_artifacts(
            sandbox_id, artifacts_dir, limits, before
        )
        if artifact_breach:
            termination = SandboxTermination.LIMIT_BREACH
        capabilities = bwrap_capabilities()
        self._run_evidence[sandbox_id] = {
            "sandbox_id": sandbox_id,
            "image": image.name,
            "launcher_pid": process.pid,
            "mechanism": "bwrap",
            "bwrap_version": capabilities.get("bwrap_version"),
            "uid_baseline": uid_baseline,
            "uid_baseline_kind": "tasks (threads included)",
            "nproc_limit": nproc_limit,
            "nproc_formula": "2*baseline + max_processes + margin",
            "seccomp_deny_syscalls": len(DENIED_SYSCALLS_AARCH64),
            "observe": {"samples": observe_samples, "alive": alive_samples},
            "teardown": teardown,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "termination": termination.value,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
        }
        self._active_runs.pop(sandbox_id, None)
        executed = termination not in (
            SandboxTermination.FAILED_TO_START, SandboxTermination.NOT_RUN
        )
        return SandboxExecutionRecord(
            sandbox_id=sandbox_id,
            executed=executed,
            exit_code=exit_code,
            termination=termination,
            duration_ms=duration_ms,
            stdout_reference=stdout_reference,
            stderr_reference=stderr_reference,
            limits_applied=limits,
            artifacts=tuple(artifacts),
            started_at=started,
            finished_at=time.time(),
        )

    # -- argv builder -------------------------------------------------------

    def _build_argv(
        self,
        rootfs_dir: Path,
        image: LocalImage,
        command: tuple[str, ...],
        sources_root: str,
        artifacts_dir: str,
        env_names: frozenset[str],
    ) -> tuple[list[str], list[int], int | None]:
        """Build the bwrap argv — fd-based binds, honest source order.

        Every bind SOURCE is an open directory fd (``--ro-bind-fd``/
        ``--bind-fd``): source resolution never depends on the mount
        namespace evolution, and every bind TARGET is a mountpoint
        pre-created inside the private rootfs (bound read-only as ``/``).
        Returns (argv, all bind fds, seccomp fd or None).
        """
        binary = str(bwrap_capabilities()["bwrap_path"])
        argv: list[str] = [
            binary,
            "--unshare-all",          # user/mount/pid/uts/net/ipc/cgroup
            "--die-with-parent",
            "--new-session",
        ]
        bind_fds: list[int] = []

        def _open_ro(source: str) -> int:
            fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
            bind_fds.append(fd)
            return fd

        rootfs_fd = _open_ro(str(rootfs_dir))
        argv += ["--ro-bind-fd", str(rootfs_fd), "/"]
        argv += ["--ro-bind-fd", str(_open_ro("/usr")), "/usr"]
        for root in image.read_only_roots:
            if root == "/usr":
                continue
            argv += ["--ro-bind-fd", str(_open_ro(root)), root]
        if sources_root:
            argv += ["--ro-bind-fd", str(_open_ro(sources_root)), WORK_MOUNT]
        if artifacts_dir:
            art_fd = os.open(artifacts_dir, os.O_RDONLY | os.O_DIRECTORY)
            bind_fds.append(art_fd)
            argv += ["--bind-fd", str(art_fd), ARTIFACTS_MOUNT]
        argv += [
            "--dev", "/dev",
            "--tmpfs", "/proc",       # host process table hidden
            "--tmpfs", SCRATCH_MOUNT,
            "--hostname", SANDBOX_HOSTNAME,
            "--clearenv",
        ]
        if "PATH" in env_names:
            argv += ["--setenv", "PATH", ":".join(image.path_entries)]
        if "HOME" in env_names:
            argv += ["--setenv", "HOME", SCRATCH_MOUNT]
        if "PYTHONDONTWRITEBYTECODE" in env_names:
            argv += ["--setenv", "PYTHONDONTWRITEBYTECODE", "1"]
        argv += ["--chdir", WORK_MOUNT if sources_root else SCRATCH_MOUNT]
        program = _seccomp_bpf_bytes()
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, program)
        finally:
            os.close(write_fd)
        argv += ["--seccomp", str(read_fd)]
        argv += ["--", image.interpreter, *command[1:]]
        return argv, bind_fds, read_fd

    # ---- teardown / evidence helpers ---------------------------------------

    def _kill_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def _teardown_run(self, sandbox_id: str, pid: int) -> dict[str, object]:
        """Hard teardown: kill residue, remove the run dir, attest."""
        self._kill_group(pid)
        run = self._active_runs.get(sandbox_id, {})
        run_dir = run.get("run_dir")
        residue_dead = False
        for _ in range(20):  # bounded wait for pidns power-off semantics
            if not os.path.exists(f"/proc/{pid}"):
                residue_dead = True
                break
            time.sleep(0.05)
            self._kill_group(pid)
        members_remaining = 0
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    with open(f"/proc/{entry}/stat", "r") as handle:
                        fields = handle.read().split()
                    if len(fields) > 5 and fields[5] == str(pid):
                        members_remaining += 1
                except (OSError, IndexError):
                    continue
        except OSError:  # pragma: no cover
            pass
        removed = True
        if run_dir:
            shutil.rmtree(str(run_dir), ignore_errors=True)
            removed = not os.path.exists(str(run_dir))
        return {
            "proc_gone": residue_dead,
            "pgid_members_remaining": members_remaining,
            "rootfs_removed": removed,
        }

    @staticmethod
    def _snapshot_artifacts(artifacts_dir: str) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        if not artifacts_dir or not os.path.isdir(artifacts_dir):
            return snapshot
        for path in Path(artifacts_dir).rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[str(path.relative_to(artifacts_dir))] = (
                    stat.st_size,
                    stat.st_mtime_ns,
                )
        return snapshot

    def _collect_artifacts(
        self,
        sandbox_id: str,
        artifacts_dir: str,
        limits: ExecutionLimits,
        before: dict[str, tuple[int, int]],
    ) -> tuple[list[ArtifactCustodyEntry], tuple[str, ...], bool]:
        entries: list[ArtifactCustodyEntry] = []
        changed: list[str] = []
        breach = False
        if not artifacts_dir or not os.path.isdir(artifacts_dir):
            return entries, tuple(changed), breach
        total = 0
        for path in sorted(Path(artifacts_dir).rglob("*")):
            if not path.is_file():
                continue
            relative = str(path.relative_to(artifacts_dir))
            stat = path.stat()
            marker = (stat.st_size, stat.st_mtime_ns)
            if before.get(relative) == marker:
                continue  # pre-existing, untouched by this run
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            total += len(data)
            entries.append(
                ArtifactCustodyEntry(
                    path=relative,
                    sha256=digest,
                    size=len(data),
                    kind="sandbox-artifact",
                )
            )
            changed.append(relative)
        if total > limits.max_artifact_bytes:
            breach = True
        return entries, tuple(changed), breach

    def _persist_outputs(
        self, sandbox_id: str, artifacts_dir: str, stdout: bytes, stderr: bytes
    ) -> tuple[str, str]:
        if not artifacts_dir:
            return "", ""
        safe_id = "".join(
            character if character.isalnum() or character in "-_." else "_"
            for character in sandbox_id
        )[:64]
        out_path = Path(artifacts_dir) / f"stdout-{safe_id}.txt"
        err_path = Path(artifacts_dir) / f"stderr-{safe_id}.txt"
        out_path.write_bytes(stdout)
        err_path.write_bytes(stderr)
        return str(out_path), str(err_path)

    def _failure_record(
        self,
        request: SandboxRequest | None,
        termination: SandboxTermination,
        detail: str,
    ) -> SandboxExecutionRecord:
        sandbox_id = request.sandbox_id if request else "<unknown>"
        record = SandboxExecutionRecord(
            sandbox_id=sandbox_id,
            executed=False,
            exit_code=None,
            termination=termination,
            duration_ms=0,
            stderr_reference="",
            limits_applied=request.limits if request else E1_LIMITS_DEFAULTS,
        )
        self._run_evidence[sandbox_id] = {
            "sandbox_id": sandbox_id,
            "termination": termination.value,
            "failure_reason": detail,
        }
        if request is not None:
            self._active_runs.pop(request.sandbox_id, None)
        return record

    def teardown(self, sandbox_id: str) -> TeardownEvidence:
        """Idempotent teardown for already-finished runs (port contract)."""
        run = self._run_evidence.get(sandbox_id)
        if run is not None and "teardown" in run:
            teardown = run["teardown"]
            assert isinstance(teardown, dict)
            ok = bool(
                teardown.get("proc_gone")
                and not teardown.get("pgid_members_remaining")
                and teardown.get("rootfs_removed")
            )
            return TeardownEvidence(
                sandbox_id=sandbox_id,
                torn_down=ok,
                detail=(
                    "verified: process gone, no group members, rootfs removed"
                    if ok
                    else f"residue detected: {teardown}"
                ),
            )
        active = self._active_runs.pop(sandbox_id, None)
        if active and isinstance(active.get("run_dir"), str):
            shutil.rmtree(str(active["run_dir"]), ignore_errors=True)
        return TeardownEvidence(
            sandbox_id=sandbox_id,
            torn_down=True,
            detail="no active run; teardown is a no-op",
        )


def bwrap_sandbox_manager(
    *, images: Mapping[str, LocalImage] | None = None
) -> SandboxManager:
    """Reference wiring: a sandbox manager with the bwrap substrate."""
    adapter = BubblewrapSubstrateAdapter(images=images)
    manager = SandboxManager(substrate=adapter)
    manager.allow_images(frozenset(adapter.image_names))
    return manager


__all__ = [
    "AUDIT_ARCH_AARCH64",
    "BWRAP_GIT_IMAGE_NAME",
    "DECLARED_SECURITY_POSTURE_BWRAP",
    "DENIED_SYSCALLS_AARCH64",
    "DESCRIPTOR_BWRAP",
    "BubblewrapSubstrateAdapter",
    "SubstrateUnavailable",
    "bwrap_capabilities",
    "bwrap_git_image",
    "bwrap_sandbox_manager",
    "default_bwrap_images",
]
