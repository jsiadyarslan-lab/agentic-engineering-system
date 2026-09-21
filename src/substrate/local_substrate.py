"""E1 local substrate adapter — the verified local isolation substrate.

This module implements the :class:`substrate.sandbox.SubstrateAdapter`
port against the LOCAL kernel substrate of this execution environment.
The substrate was proven experimentally in the E1 local-substrate
re-evaluation (LOCAL-D01-A-SUPPORTED): 21/21 capability probes and a
23/23 real-sandbox-lifecycle proof (evidence:
``eng-local-substrate-eval/evidence/probe_results.json`` and
``sandbox_lifecycle.json``). The owner accepted the local substrate as
the E1 execution substrate, superseding the previous
"missing external substrate" block.

Mechanisms (all kernel-verified in this environment — the same
primitive set container runtimes are built from):

- **user namespace** with uid/gid identity mapping (0 -> real uid);
- **mount namespace** with slave propagation, ``pivot_root`` into a
  private tmpfs root, and read-only bind mounts for the image roots
  and the granted source tree;
- **writable areas are explicit and bounded**: a size-capped tmpfs
  scratch at ``/tmp`` (the D-13 workspace ceiling) and the artifact
  exit bind at ``/artifacts`` (the workspace custody directory);
- **PID namespace** (the target executes as pid 1), **UTS namespace**
  (isolated hostname), **network namespace** with no interfaces up
  (D-04 = A: network is NONE — outbound connects fail ENETUNREACH);
- **privilege reduction**: capability drop (capset to zero),
  ``PR_SET_NO_NEW_PRIVS``, and a seccomp deny-list blocking the
  privileged escape surface (mount, unshare, setns, ptrace, bpf,
  kexec, module loading, ...);
- **resource limits** (D-13) via rlimits: ``RLIMIT_AS`` (memory),
  ``RLIMIT_NPROC`` (process count), ``RLIMIT_FSIZE`` (per-file
  output), ``RLIMIT_CPU`` (CPU backstop), ``RLIMIT_NOFILE`` (open
  files), ``RLIMIT_CORE`` (0);
- **CPU ceiling** via scheduler affinity pinning to ``vcpu`` CPUs;
- **wall-clock watchdog** in the supervisor plus a hard ``SIGKILL``
  to the whole process group on timeout or output breach;
- **teardown always**: process-group kill, rootfs removal, residue
  attestation, and an orphan check against the ambient uid baseline.

Honest mechanism semantics (D-13 semantics annex, owner-accepted):
memory is enforced as ``RLIMIT_AS`` per process — NOT aggregate
memcg; CPU is enforced as affinity pinning plus an ``RLIMIT_CPU``
backstop — NOT a CFS quota; the process count is enforced as
``RLIMIT_NPROC`` for the real uid with the ambient baseline accounted
— NOT a cgroup pids controller; cgroupfs is read-only in this
environment and NO cgroup control is claimed. ``/proc`` is
intentionally NOT mounted inside the sandbox (the kernel restricts
procfs mounts in this userns configuration; the no-proc posture is
strictly stronger).

This is the ONLY module in the package that creates processes. It is
reachable only through the sandbox manager (request contract, image
allowlist, limits policy, single-execute-per-id) — never directly.
There is no host-execution fallback: if the sandbox cannot be
established, the adapter fails closed with a truthful
``FAILED_TO_START`` record.
"""

from __future__ import annotations

import ctypes
import errno as _errno
import hashlib
import json
import os
import select
import shutil
import signal
import struct
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

try:  # الأمر 005: unix-only — غيابه (Windows) لا يكسر الاستيراد
    import resource
except ImportError:  # pragma: no cover — يُختبر بمحاكاة الحراسة
    resource = None  # type: ignore[assignment]

from substrate.limits import (
    E1_LIMITS_DEFAULTS,
    ExecutionLimits,
    validate_against_defaults,
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
# kernel constants (x86_64; the only supported architecture for this
# substrate — the adapter refuses to run elsewhere)
# ---------------------------------------------------------------------------

CLONE_NEWNS = 0x00020000
CLONE_NEWUTS = 0x04000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000

MS_RDONLY = 1
MS_REMOUNT = 32
MS_BIND = 4096
MS_REC = 16384
MS_SLAVE = 1 << 19
MS_DETACH = 2

PR_SET_NO_NEW_PRIVS = 38
PR_GET_NO_NEW_PRIVS = 39
PR_SET_SECCOMP = 22
PR_GET_SECCOMP = 41
SECCOMP_MODE_FILTER = 2
SYS_seccomp = 317
SYS_pivot_root = 155
SYS_capset = 126
LINUX_CAPABILITY_VERSION_3 = 0x20080522

SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000
AUDIT_ARCH_X86_64 = 0xC000003E
BPF_LD_W_ABS = 0x20
BPF_JMP_JEQ_K = 0x15
BPF_RET_K = 0x06

#: seccomp deny-list (x86_64 syscall numbers): the privileged escape
#: surface. mount(165)/umount2(166)/pivot_root(155)/unshare(272)/
#: setns(308) are the namespace-escape syscalls; the rest block
#: module loading, kexec, bpf, ptrace, perf, and handle-based fs
#: access that bypass the pivot_root containment.
DENIED_SYSCALLS: tuple[int, ...] = (
    101,  # ptrace
    110,  # iopl
    155,  # pivot_root
    161,  # chroot
    165,  # mount
    166,  # umount2
    167,  # swapon
    168,  # swapoff
    169,  # reboot
    174,  # create_module
    175,  # init_module
    176,  # delete_module
    179,  # quotactl
    246,  # kexec_load
    272,  # unshare
    298,  # perf_event_open
    300,  # fanotify_init
    303,  # name_to_handle_at
    304,  # open_by_handle_at
    308,  # setns
    313,  # finit_module
    320,  # kexec_file_load
    321,  # bpf
)

#: Substrate-level open-file ceiling (order §5 "open files"; not a
#: D-13 request knob — requests cannot raise it).
SANDBOX_NOFILE_LIMIT = 256

#: Fixed sandbox hostname (UTS namespace; isolated per sandbox).
SANDBOX_HOSTNAME = "e1-sbx"

#: In-sandbox artifact exit path (bind of the workspace custody dir).
ARTIFACTS_MOUNT = "/artifacts"

#: In-sandbox read-only source tree mount (the granted repository).
WORK_MOUNT = "/work"

#: In-sandbox writable scratch (size = D-13 workspace ceiling).
SCRATCH_MOUNT = "/tmp"

#: Real uid/gid captured at import time of the SUPERVISOR process
#: (never inside the sandbox, where identities are mapped).
#: الأمر 005: os.getuid غير موجود على Windows — الحماية من الانهيار
#: عند الاستيراد، والقيمة -1 لا تُستخدم إلا على منصات مدعومة أصلًا.
_REAL_UID = os.getuid() if hasattr(os, "getuid") else -1
_REAL_GID = os.getgid() if hasattr(os, "getgid") else -1

_SUPPORTED_ARCH = sys.platform.startswith("linux") and os.uname().machine == "x86_64"

_LIBC: ctypes.CDLL | None = None


def _libc() -> ctypes.CDLL:
    """Load libc once (lazy; the only FFI surface in the package)."""
    global _LIBC
    if _LIBC is None:
        _LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
    return _LIBC


def _syscall_err(rc: int) -> OSError:
    code = ctypes.get_errno()
    return OSError(code, os.strerror(code) if code else f"syscall rc={rc}")


# ---------------------------------------------------------------------------
# local image model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocalImage:
    """One locally resolvable execution image.

    ``interpreter`` is an absolute executable path resolvable INSIDE
    the sandbox (its symlink chain must resolve through the bound
    read-only roots). ``entrypoint_aliases`` are the ``command[0]``
    tokens the image answers to (the E1 test-runner contract uses
    ``python``). ``path_entries`` become the PATH value supplied when
    the request permits the PATH environment name.
    """

    name: str
    interpreter: str
    read_only_roots: tuple[str, ...]
    entrypoint_aliases: frozenset[str] = frozenset({"python", "python3"})
    path_entries: tuple[str, ...] = ("/usr/bin", "/bin")

    def __post_init__(self) -> None:
        if not self.name or not self.interpreter.startswith("/"):
            raise ValueError("LocalImage needs a name and absolute interpreter")
        for root in self.read_only_roots:
            if not root.startswith("/"):
                raise ValueError(f"read-only roots must be absolute: {root!r}")


def _maximal_roots(paths: tuple[str, ...]) -> tuple[str, ...]:
    """Keep only roots not contained in another root (minimal cover)."""
    ordered = sorted(set(paths))
    kept: list[str] = []
    for path in ordered:
        if not any(
            other != path and path.startswith(other.rstrip("/") + "/")
            for other in ordered
        ):
            kept.append(path)
    return tuple(kept)


def _symlink_chain_dirs(path: str) -> set[str]:
    """Directories containing every symlink on the resolution chain of
    ``path`` (including intermediate DIRECTORY symlinks).

    Pure path logic — no process is spawned. Resolution mirrors the
    kernel's left-to-right component walk: the first symlink found in
    the current path is recorded (its containing directory must be
    bindable so in-sandbox resolution mirrors the host), and the walk
    continues from the symlink's target.
    """
    dirs: set[str] = set()
    current = os.path.abspath(path)
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        parts = current.strip("/").split("/")
        prefix = "/"
        advanced = False
        for part in parts:
            if not part:
                continue
            prefix = os.path.join(prefix, part)
            if os.path.islink(prefix):
                dirs.add(os.path.dirname(prefix))
                target = os.readlink(prefix)
                current = (
                    os.path.normpath(target)
                    if target.startswith("/")
                    else os.path.normpath(
                        os.path.join(os.path.dirname(prefix), target)
                    )
                )
                advanced = True
                break
        if not advanced:
            break  # no symlink left in the whole path
    return dirs


def _interpreter_roots(interpreter: str) -> tuple[str, ...]:
    """Compute the read-only bind roots that make ``interpreter``
    (and its whole symlink chain, including directory symlinks)
    resolvable inside the sandbox.

    Pure path logic — no process is spawned. Covers: /usr (ELF loader
    and system libraries), the interpreter prefix, the base prefix,
    and every directory containing a symlink on the interpreter's
    resolution chain (uv-style venvs reach their base interpreter
    through a symlinked sibling directory).
    """
    roots: list[str] = ["/usr", os.path.realpath(sys.prefix)]
    try:
        base = os.path.realpath(sys._base_prefix)  # type: ignore[attr-defined]
        if base != os.path.realpath(sys.prefix):
            roots.append(base)
    except AttributeError:  # pragma: no cover - non-CPython
        pass
    roots.extend(sorted(_symlink_chain_dirs(interpreter)))
    roots.append(os.path.dirname(os.path.abspath(interpreter)))
    return _maximal_roots(tuple(roots))


def default_local_images() -> dict[str, LocalImage]:
    """The verified local images derived from the running interpreter.

    The image name records the interpreter family truthfully (no
    container-registry claim): ``local-python-<major>.<minor>``.
    """
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


#: Image name of the E4 git image (the real git binary, /usr-bound).
LOCAL_GIT_IMAGE_NAME = "local-git"

#: Where the real git binary must live for the E4 image to resolve.
_GIT_INTERPRETER = "/usr/bin/git"


def local_git_image() -> LocalImage:
    """The E4 high-impact git image: the REAL ``/usr/bin/git`` binary.

    E4 (order §6) executes real git commits INSIDE this substrate:
    the image interpreter is the host git binary, reached through
    the read-only ``/usr`` bind; the only writable path git can
    touch is the custody-directory bind (``/artifacts``). The image
    is NOT part of :func:`default_local_images` — the caller
    (owner-side harness wiring the E4 engine) registers it
    explicitly with the adapter, keeping E1 default posture
    unchanged. Aliases: the fixed token ``git``; every sandbox
    request commands starts with that alias and is execve'd
    directly (no shell, no caller-controlled argv[0]).
    """
    roots = _interpreter_roots(_GIT_INTERPRETER)
    bin_dir = os.path.dirname(_GIT_INTERPRETER)
    roots = _maximal_roots(tuple(roots) + (bin_dir,))
    return LocalImage(
        name=LOCAL_GIT_IMAGE_NAME,
        interpreter=_GIT_INTERPRETER,
        read_only_roots=roots,
        entrypoint_aliases=frozenset({"git"}),
        path_entries=("/usr/bin", "/bin"),
    )


#: Substrate descriptor for this adapter.
DESCRIPTOR = SubstrateDescriptor(
    name="local-namespace-substrate",
    isolation_class="linux-namespaces",
    network_support="none",
)

#: The declared security posture (evidence-facing, static).
DECLARED_SECURITY_POSTURE: dict[str, object] = {
    "namespaces": ("user", "mount", "pid", "uts", "network"),
    "identity_mapping": "0 -> real uid (single mapping)",
    "rootfs": "private tmpfs + pivot_root, root remounted read-only",
    "readonly": ("/", "/usr", "image roots", WORK_MOUNT),
    "writable": (SCRATCH_MOUNT, ARTIFACTS_MOUNT),
    "proc_mounted": False,
    "no_new_privs": True,
    "capabilities": "dropped (capset to zero)",
    "seccomp": f"deny-list ({len(DENIED_SYSCALLS)} privileged syscalls -> EPERM)",
    "network": "NONE (fresh network namespace, no interface up)",
    "pid1": "the target executes as pid 1 of the sandbox pid namespace",
    "cpu": "affinity pinning + RLIMIT_CPU backstop (NOT CFS quota)",
    "memory": "RLIMIT_AS per process (NOT aggregate memcg)",
    "process_count": "RLIMIT_NPROC with ambient uid baseline accounted",
    "filesystem_size": "tmpfs size cap (ENOSPC) + RLIMIT_FSIZE (EFBIG)",
}


# ---------------------------------------------------------------------------
# low-level syscall helpers (used only inside the forked children)
# ---------------------------------------------------------------------------


def _unshare(flags: int) -> None:
    libc = _libc()
    libc.unshare.restype = ctypes.c_int
    libc.unshare.argtypes = [ctypes.c_int]
    ctypes.set_errno(0)
    if libc.unshare(flags) != 0:
        raise _syscall_err(-1)


def _raw_mount(source: str | None, target: str, fstype: str | None,
               flags: int, data: str | None = None) -> tuple[int, int]:
    libc = _libc()
    libc.mount.restype = ctypes.c_int
    libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                           ctypes.c_ulong, ctypes.c_char_p]
    ctypes.set_errno(0)
    rc = libc.mount(
        source.encode() if isinstance(source, str) else source,
        target.encode(),
        fstype.encode() if fstype else None,
        flags,
        data.encode() if isinstance(data, str) else data,
    )
    return rc, ctypes.get_errno()


def _mount(source: str | None, target: str, fstype: str | None = None,
           flags: int = 0, data: str | None = None) -> None:
    rc, err = _raw_mount(source, target, fstype, flags, data)
    if rc != 0:
        raise OSError(err, os.strerror(err))


def _bind_readonly(source: str, target: str) -> None:
    """Bind-mount ``source`` at ``target`` and remount it read-only."""
    rc, err = _raw_mount(source, target, None, MS_BIND, None)
    if rc != 0:
        raise OSError(err, os.strerror(err))
    rc, err = _raw_mount(None, target, None, MS_BIND | MS_REMOUNT | MS_RDONLY, None)
    if rc != 0:
        raise OSError(err, os.strerror(err))


def _umount2(target: str, flags: int) -> tuple[int, int]:
    libc = _libc()
    libc.umount2.restype = ctypes.c_int
    libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
    ctypes.set_errno(0)
    rc = libc.umount2(target.encode(), flags)
    return rc, ctypes.get_errno()


def _pivot_root(new_root: str, put_old: str) -> None:
    libc = _libc()
    libc.syscall.restype = ctypes.c_long
    libc.syscall.argtypes = [ctypes.c_long, ctypes.c_char_p, ctypes.c_char_p]
    ctypes.set_errno(0)
    rc = libc.syscall(SYS_pivot_root, new_root.encode(), put_old.encode())
    if rc != 0:
        raise _syscall_err(rc)


def _capset_drop_all() -> None:
    libc = _libc()
    header = struct.pack("=II", LINUX_CAPABILITY_VERSION_3, 0)
    data = b"\x00" * 24
    libc.syscall.restype = ctypes.c_long
    libc.syscall.argtypes = [ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
    ctypes.set_errno(0)
    rc = libc.syscall(SYS_capset, header, data)
    if rc != 0:
        raise _syscall_err(rc)


class _SockFilter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8),
                ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16), ("pad", ctypes.c_uint16),
                ("filter", ctypes.POINTER(_SockFilter))]


def _install_seccomp_denylist() -> int:
    """Install NO_NEW_PRIVS + the seccomp deny-list (must never fail
    silently — failures raise and abort the sandbox)."""
    libc = _libc()
    instructions: list[tuple[int, int, int, int]] = [(BPF_LD_W_ABS, 0, 0, 4)]
    n = len(DENIED_SYSCALLS)
    instructions.append((BPF_JMP_JEQ_K, 0, n + 2, AUDIT_ARCH_X86_64))
    instructions.append((BPF_LD_W_ABS, 0, 0, 0))
    for index, syscall_nr in enumerate(DENIED_SYSCALLS):
        jump_true = (n + 1) - (index + 1)
        instructions.append(
            (BPF_JMP_JEQ_K, jump_true if jump_true > 0 else 0, 0, syscall_nr)
        )
    instructions.append((BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW))
    instructions.append(
        (BPF_RET_K, 0, 0, SECCOMP_RET_ERRNO | _errno.EPERM)
    )
    program = (_SockFilter * len(instructions))()
    for index, (code, jt, jf, k) in enumerate(instructions):
        program[index].code, program[index].jt = code, jt
        program[index].jf, program[index].k = jf, k
    fprog = _SockFprog(
        len=len(instructions), pad=0,
        filter=ctypes.cast(program, ctypes.POINTER(_SockFilter)),
    )
    libc.prctl.restype = ctypes.c_int
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                           ctypes.c_ulong, ctypes.c_ulong]
    ctypes.set_errno(0)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise _syscall_err(-1)
    libc.syscall.restype = ctypes.c_long
    libc.syscall.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p]
    ctypes.set_errno(0)
    if libc.syscall(SYS_seccomp, 1, 0, ctypes.byref(fprog)) != 0:
        raise _syscall_err(-1)
    return len(instructions)


# ---------------------------------------------------------------------------
# environment probing (supervisor side; /proc reads only)
# ---------------------------------------------------------------------------


def _count_uid_processes() -> int:
    """Count processes owned by the real uid (ambient baseline)."""
    count = 0
    try:
        entries = os.listdir("/proc")
    except OSError:  # pragma: no cover - /proc always present here
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/status", "r") as handle:
                for line in handle:
                    if line.startswith("Uid:"):
                        if line.split()[1] == str(_REAL_UID):
                            count += 1
                        break
        except OSError:
            continue
    return count


def substrate_capabilities() -> dict[str, object]:
    """Cheap environment self-check for the local substrate.

    Returns a truthful record of the kernel features this adapter
    requires. ``supported`` is True only when every required feature
    is present (used fail-closed by :class:`LocalSubstrateAdapter`).
    """
    capabilities: dict[str, object] = {
        "arch_x86_64_linux": _SUPPORTED_ARCH,
        "real_uid": _REAL_UID,
    }
    try:
        with open("/proc/sys/user/max_user_namespaces", "r") as handle:
            value = int(handle.read().strip())
        capabilities["max_user_namespaces"] = value
        capabilities["user_namespaces_enabled"] = value > 0
    except (OSError, ValueError):
        capabilities["user_namespaces_enabled"] = False
    capabilities["seccomp_self_mode"] = _seccomp_self_mode()
    capabilities["interpreter"] = sys.executable
    capabilities["interpreter_resolvable"] = os.path.isfile(sys.executable)
    capabilities["supported"] = bool(
        _SUPPORTED_ARCH
        and capabilities["user_namespaces_enabled"]
        and capabilities["seccomp_self_mode"] in (1, 2)
        and capabilities["interpreter_resolvable"]
    )
    return capabilities


def _seccomp_self_mode() -> int:
    """Seccomp mode of this process from /proc/self/status.

    (``prctl(PR_GET_SECCOMP)`` is unreliable for reading the mode on
    this kernel; /proc/self/status is the truthful source.)
    """
    try:
        with open("/proc/self/status", "r") as handle:
            for line in handle:
                if line.startswith("Seccomp:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return -1


# ---------------------------------------------------------------------------
# the spawned launcher (fresh single-threaded process)
# ---------------------------------------------------------------------------

#: Environment variable carrying the launcher's JSON configuration.
_LAUNCHER_CONFIG_ENV = "E1_SANDBOX_LAUNCHER_CONFIG"

#: Environment variable carrying the import path for the bootstrap.
_LAUNCHER_PATH_ENV = "E1_SANDBOX_BOOTSTRAP_PATH"

#: Bootstrap code of the launcher process. The supervisor spawns a
#: FRESH interpreter (posix_spawn) instead of forking itself: a fork
#: of a multi-threaded supervisor (e.g. a test runner) inherits thread
#: state on this kernel, which blocks ``unshare(CLONE_NEWUSER)`` with
#: EINVAL. The exec-based spawn resets the process image — the
#: launcher is single-threaded and owns the namespaces cleanly.
_LAUNCHER_BOOTSTRAP_CODE = (
    "import os, sys\n"
    "sys.path.insert(0, os.environ['E1_SANDBOX_BOOTSTRAP_PATH'])\n"
    "from substrate.local_substrate import run_launcher_bootstrap\n"
    "run_launcher_bootstrap()\n"
)


def run_launcher_bootstrap() -> None:
    """Entry point of the spawned LAUNCHER process (never returns).

    Reads the JSON sandbox configuration from the environment, builds
    the sandbox namespaces, forks the sandbox init (which becomes pid
    1 of the new pid namespace and execs the real target), and relays
    the init's exit code. Fail-closed: any error is reported on stderr
    with a ``SANDBOX-INIT-ERROR`` marker and the process exits 125.
    """
    raw = os.environ.get(_LAUNCHER_CONFIG_ENV)
    if not raw:
        os.write(2, b"SANDBOX-INIT-ERROR: launcher config missing\n")
        os._exit(125)
    os.environ.pop(_LAUNCHER_CONFIG_ENV, None)
    os.environ.pop(_LAUNCHER_PATH_ENV, None)
    try:
        config = json.loads(raw)
    except ValueError as error:
        os.write(2, f"SANDBOX-INIT-ERROR: bad launcher config: {error!r}\n".encode())
        os._exit(125)
    try:
        _launcher_sequence(config)
    except BaseException as error:  # noqa: BLE001 - child boundary
        try:
            os.write(2, f"SANDBOX-INIT-ERROR: {error!r}\n".encode())
        except OSError:
            pass
        os._exit(125)
    os._exit(126)  # pragma: no cover - _launcher_sequence never returns


def _launcher_sequence(config: dict) -> None:
    """Launcher-side namespace construction (single-threaded process)."""
    _unshare(CLONE_NEWUSER)
    with open("/proc/self/setgroups", "w") as handle:
        handle.write("deny")
    with open("/proc/self/uid_map", "w") as handle:
        handle.write(f"0 {_REAL_UID} 1\n")
    with open("/proc/self/gid_map", "w") as handle:
        handle.write(f"0 {_REAL_GID} 1\n")
    _unshare(CLONE_NEWUTS)
    _unshare(CLONE_NEWNET)
    _unshare(CLONE_NEWNS)
    _unshare(CLONE_NEWPID)
    libc = _libc()
    libc.sethostname.restype = ctypes.c_int
    libc.sethostname.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    libc.sethostname(SANDBOX_HOSTNAME.encode(), len(SANDBOX_HOSTNAME))
    os.setpgid(0, 0)
    init_pid = os.fork()
    if init_pid != 0:
        # launcher: reap the sandbox init and relay its exit code
        _, status = os.waitpid(init_pid, 0)
        code = (
            os.WEXITSTATUS(status)
            if os.WIFEXITED(status)
            else 128 + os.WTERMSIG(status)
        )
        os._exit(code)
    _sandbox_init(config)


def _sandbox_init(config: dict) -> None:
    """Sandbox-init entry (pid 1 of the new pid namespace; never returns)."""
    current: list[str] = ["start"]
    try:
        _sandbox_init_sequence(
            config, step=lambda label: current.__setitem__(0, label)
        )
    except BaseException as error:  # noqa: BLE001 - child boundary
        try:
            os.write(
                2, f"SANDBOX-INIT-ERROR at {current[0]}: {error!r}\n".encode()
            )
        except OSError:
            pass
        os._exit(125)


def _sandbox_init_sequence(config: dict, step) -> None:
    """Build the sandbox filesystem, drop privileges, exec the target."""
    rootfs_dir: str = config["rootfs_dir"]
    sources_root: str = config["sources_root"]
    artifacts_dir: str = config["artifacts_dir"]
    image_roots: tuple[str, ...] = tuple(config["image_roots"])
    interpreter: str = config["interpreter"]
    command: tuple[str, ...] = tuple(config["command"])
    env_names = frozenset(config["env_names"])
    limits = ExecutionLimits(**config["limits"])
    nproc_limit: int = config["nproc_limit"]
    # 1. private rootfs (tmpfs), propagation isolated
    step("propagation-slave")
    _raw_mount(None, "/", None, MS_REC | MS_SLAVE, None)
    step("rootfs-tmpfs")
    _mount("none", rootfs_dir, "tmpfs", 0, "size=64m,mode=0755")
    # 2. read-only image roots + merged-usr symlinks
    step("rootfs-dirs")
    for relative in ("usr", "dev", "tmp", "old", "work", "artifacts"):
        os.makedirs(os.path.join(rootfs_dir, relative), exist_ok=True)
    step("bind-usr")
    _bind_readonly("/usr", os.path.join(rootfs_dir, "usr"))
    step("merged-usr-symlinks")
    for link, target in (
        ("bin", "usr/bin"), ("lib", "usr/lib"),
        ("lib64", "usr/lib64"), ("sbin", "usr/sbin"),
    ):
        link_path = os.path.join(rootfs_dir, link)
        if not os.path.lexists(link_path):
            os.symlink(target, link_path)
    step("image-roots")
    for root in image_roots:
        if root == "/usr":
            continue
        mount_point = os.path.join(rootfs_dir, root.lstrip("/"))
        os.makedirs(mount_point, exist_ok=True)
        _bind_readonly(root, mount_point)
    # 3. granted source tree, read-only, at /work
    if sources_root:
        step("bind-sources")
        work = os.path.join(rootfs_dir, "work")
        _bind_readonly(sources_root, work)
    # 4. artifact exit: the workspace custody directory, writable
    if artifacts_dir:
        step("bind-artifacts-exit")
        exit_dir = os.path.join(rootfs_dir, "artifacts")
        rc, err = _raw_mount(artifacts_dir, exit_dir, None, MS_BIND, None)
        if rc != 0:
            raise OSError(err, os.strerror(err))
    # 5. minimal /dev (plain binds — the proven-proto pattern: the
    # ro-remount of device-node binds is kernel-denied in this
    # userns and was silently skipped by the verified prototype;
    # device nodes are harmless: writing /dev/null is the point,
    # and mknod stays blocked by the capability drop + seccomp)
    step("dev-binds")
    for device in ("null", "zero", "urandom"):
        target = os.path.join(rootfs_dir, "dev", device)
        with open(target, "wb"):
            pass
        rc, err = _raw_mount(f"/dev/{device}", target, None, MS_BIND, None)
        if rc != 0:
            raise OSError(err, os.strerror(err))
    # 6. pivot into the private root; detach the old root
    step("pivot-root")
    os.chdir(rootfs_dir)
    _pivot_root(".", "old")
    _umount2("old", MS_DETACH)
    try:
        os.rmdir("old")
    except OSError:
        pass
    # 7. writable bounded scratch (D-13 workspace ceiling)
    step("scratch-tmpfs")
    scratch_cap = max(1, limits.max_workspace_bytes // (1024 * 1024))
    _mount("none", SCRATCH_MOUNT, "tmpfs", 0, f"size={scratch_cap}m,mode=0755")
    # 8. the root itself becomes read-only
    step("root-remount-ro")
    _raw_mount(None, "/", None, MS_REMOUNT | MS_RDONLY, None)
    # 9. privilege reduction
    step("capset-drop")
    _capset_drop_all()
    # 10. CPU ceiling: affinity pinning (vcpu CPUs)
    step("affinity-pin")
    available = sorted(os.sched_getaffinity(0))
    pinned = available[: max(1, min(limits.vcpu, len(available)))]
    os.sched_setaffinity(0, set(pinned))
    # 11. resource limits (D-13 local mechanism semantics)
    step("setrlimits")
    if resource is None:  # pragma: no cover — unix-only path by construction
        raise RuntimeError("rlimits require the unix resource module")
    resource.setrlimit(resource.RLIMIT_NOFILE, (SANDBOX_NOFILE_LIMIT,) * 2)
    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_output_bytes,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (nproc_limit, nproc_limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (limits.timeout_seconds,) * 2)
    # 12. syscall restriction (NO_NEW_PRIVS + seccomp deny-list)
    step("seccomp-install")
    _install_seccomp_denylist()
    # 13. environment (names only from the request; values from the image)
    environment: dict[str, str] = {}
    if "PATH" in env_names:
        environment["PATH"] = ":".join(config["path_entries"])
    if "HOME" in env_names:
        environment["HOME"] = SCRATCH_MOUNT
    if "PYTHONDONTWRITEBYTECODE" in env_names:
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # 14. working directory: the granted source tree when mounted,
    # otherwise the writable scratch
    os.chdir(WORK_MOUNT if sources_root else SCRATCH_MOUNT)
    # 15. execute the real target as pid 1 (stdout/stderr are already
    # the supervisor's pipes — inherited through the spawn and fork)
    os.execve(interpreter, [interpreter, *command[1:]], environment)


# ---------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------


def _spawn_launcher(
    *,
    config: dict,
    out_write: int,
    err_write: int,
    out_read: int,
    err_read: int,
) -> int:
    """Spawn the fresh single-threaded launcher process; return its pid.

    The launcher receives the sandbox configuration as a JSON env var
    (never in argv — argv stays the fixed bootstrap shape) and the
    supervisor's pipes as fds 1/2 via spawn file actions. The config
    env var never reaches the sandbox target: the init builds the
    target environment fresh from the request's env NAMES.
    """
    environment = {
        _LAUNCHER_CONFIG_ENV: json.dumps(config),
        _LAUNCHER_PATH_ENV: str(Path(__file__).resolve().parent.parent),
        "PATH": "/usr/bin:/bin",
    }
    return os.posix_spawn(
        sys.executable,
        [sys.executable, "-c", _LAUNCHER_BOOTSTRAP_CODE],
        environment,
        file_actions=[
            (os.POSIX_SPAWN_DUP2, out_write, 1),
            (os.POSIX_SPAWN_DUP2, err_write, 2),
            (os.POSIX_SPAWN_CLOSE, out_read),
            (os.POSIX_SPAWN_CLOSE, err_read),
        ],
    )


class LocalSubstrateAdapter(SubstrateAdapter):
    """The real local substrate: namespace sandbox + rlimits + seccomp.

    Contract obligations (port docstring) are enforced as follows:

    - limits are enforced MECHANICALLY (watchdog kill, rlimits, tmpfs
      caps, affinity, output cap) — validated again adapter-side;
    - at most one execution per sandbox id (adapter-side ledger too);
    - stdout/stderr are bounded and persisted as referenceable
      artifacts (``stdout.txt`` / ``stderr.txt`` in the custody
      directory) plus bounded in-record references;
    - artifacts exit ONLY through the custody-directory bind;
    - teardown always, including on failure;
    - fail closed: any internal error yields a truthful
      ``FAILED_TO_START``/``KILLED`` record — never a fake success.
    """

    def __init__(
        self,
        *,
        images: Mapping[str, LocalImage] | None = None,
        base_dir: Path | str | None = None,
        self_check: bool = True,
    ) -> None:
        # الأمر 005: على منصة غير مدعومة لا انهيار عند الإنشاء — كل
        # طلب تنفيذ يُردّ عليه بسجل فشل صادق (fail-closed لكل طلب).
        if self_check and _SUPPORTED_ARCH:
            capabilities = substrate_capabilities()
            if not capabilities["supported"]:
                raise RuntimeError(
                    "local substrate unsupported in this environment: "
                    f"{capabilities}"
                )
        self._images: dict[str, LocalImage] = dict(
            images if images is not None else default_local_images()
        )
        self._base_dir = Path(base_dir) if base_dir is not None else None
        self._executed_ids: set[str] = set()
        self._active_runs: dict[str, dict[str, object]] = {}
        self._run_evidence: dict[str, dict[str, object]] = {}

    # -- introspection -----------------------------------------------------

    def descriptor(self) -> SubstrateDescriptor:
        return DESCRIPTOR

    @property
    def image_names(self) -> frozenset[str]:
        return frozenset(self._images)

    def declared_posture(self) -> dict[str, object]:
        return dict(DECLARED_SECURITY_POSTURE)

    def execution_evidence(self, sandbox_id: str) -> dict[str, object]:
        """Per-run runtime evidence (observe stats, teardown attestation)."""
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
        if not _SUPPORTED_ARCH:
            return self._failure_record(
                request, SandboxTermination.FAILED_TO_START,
                "local substrate requires linux/x86_64 — "
                "على Windows استخدم WSL2؛ لن يُنفَّذ شيء على المضيف مباشرة",
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
                f"image {request.image!r} is not provided by the local "
                f"substrate (available: {sorted(self._images)})",
            )
        if request.network is not NetworkMode.NONE:
            return self._failure_record(
                request, SandboxTermination.NOT_RUN,
                "local substrate enforces network NONE (D-04=A)",
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

    def _run(
        self,
        request: SandboxRequest,
        image: LocalImage,
        command: tuple[str, ...],
        sources_root: str,
        artifacts_dir: str,
        before: dict[str, tuple[int, int]],
    ) -> SandboxExecutionRecord:
        sandbox_id = request.sandbox_id
        limits = request.limits
        run_dir = Path(
            tempfile.mkdtemp(prefix=f"e1-sbx-{sandbox_id}-", dir=self._base_dir)
        )
        rootfs_dir = run_dir / "rootfs"
        rootfs_dir.mkdir()
        out_read, out_write = os.pipe()
        err_read, err_write = os.pipe()
        uid_baseline = _count_uid_processes()
        nproc_limit = uid_baseline + limits.max_processes
        self._active_runs[sandbox_id] = {"rootfs_dir": str(run_dir)}

        started = time.time()
        launcher_pid = _spawn_launcher(
            config={
                "rootfs_dir": str(rootfs_dir),
                "sources_root": sources_root,
                "artifacts_dir": artifacts_dir,
                "image_roots": list(image.read_only_roots),
                "interpreter": image.interpreter,
                "command": list(command),
                "env_names": sorted(request.env_names),
                "path_entries": list(image.path_entries),
                "limits": {
                    "timeout_seconds": limits.timeout_seconds,
                    "vcpu": limits.vcpu,
                    "memory_bytes": limits.memory_bytes,
                    "max_processes": limits.max_processes,
                    "max_output_bytes": limits.max_output_bytes,
                    "max_artifact_bytes": limits.max_artifact_bytes,
                    "max_workspace_bytes": limits.max_workspace_bytes,
                },
                "nproc_limit": nproc_limit,
            },
            out_write=out_write,
            err_write=err_write,
            out_read=out_read,
            err_read=err_read,
        )

        # ---- supervisor: observe, enforce, collect ----
        os.close(out_write)
        os.close(err_write)
        stdout = b""
        stderr = b""
        termination = SandboxTermination.COMPLETED
        deadline = started + limits.timeout_seconds
        output_cap = limits.max_output_bytes
        observe_samples = 0
        alive_samples = 0
        eof: set[int] = set()
        while len(eof) < 2:
            if time.time() > deadline:
                self._kill_group(launcher_pid)
                termination = SandboxTermination.TIMEOUT
                break
            readable, _, _ = select.select([out_read, err_read], [], [], 0.2)
            observe_samples += 1
            if os.path.exists(f"/proc/{launcher_pid}"):
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
                if fd == out_read:
                    stdout += chunk
                else:
                    stderr += chunk
                if len(stdout) + len(stderr) > output_cap:
                    self._kill_group(launcher_pid)
                    termination = SandboxTermination.LIMIT_BREACH
                    breach = True
                    break
            if breach:
                break
        for fd in (out_read, err_read):
            try:
                os.close(fd)
            except OSError:
                pass
        # reap the launcher (it relays the target's exit code)
        exit_code: int | None = None
        try:
            _, status = os.waitpid(launcher_pid, 0)
            if os.WIFEXITED(status):
                exit_code = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                exit_code = 128 + os.WTERMSIG(status)
        except ChildProcessError:  # pragma: no cover - already reaped
            pass
        duration_ms = int((time.time() - started) * 1000)
        if (
            termination is SandboxTermination.COMPLETED
            and exit_code == 125
            and b"SANDBOX-INIT-ERROR" in stderr
        ):
            termination = SandboxTermination.FAILED_TO_START

        # ---- DESTROY: teardown always + residue attestation ----
        teardown = self._teardown_run(sandbox_id, launcher_pid)

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
        self._run_evidence[sandbox_id] = {
            "sandbox_id": sandbox_id,
            "image": image.name,
            "launcher_pid": launcher_pid,
            "uid_baseline": uid_baseline,
            "nproc_limit": nproc_limit,
            "observe": {
                "samples": observe_samples,
                "alive": alive_samples,
            },
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

    # ---- teardown / evidence helpers ---------------------------------------

    def _kill_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def _teardown_run(self, sandbox_id: str, launcher_pid: int) -> dict[str, object]:
        """Hard teardown: kill residue, remove the rootfs, attest."""
        self._kill_group(launcher_pid)
        run = self._active_runs.get(sandbox_id, {})
        run_dir = run.get("rootfs_dir")
        residue_dead = False
        for _ in range(20):  # bounded wait for pidns power-off semantics
            if not os.path.exists(f"/proc/{launcher_pid}"):
                residue_dead = True
                break
            time.sleep(0.05)
            self._kill_group(launcher_pid)
        members_remaining = 0
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    with open(f"/proc/{entry}/stat", "r") as handle:
                        fields = handle.read().split()
                    if len(fields) > 5 and fields[5] == str(launcher_pid):
                        members_remaining += 1
                except (OSError, IndexError):
                    continue
        except OSError:  # pragma: no cover
            pass
        removed = True
        if run_dir:
            shutil.rmtree(run_dir, ignore_errors=True)
            removed = not os.path.exists(str(run_dir))
        return {
            "proc_gone": residue_dead,
            "pgid_members_remaining": members_remaining,
            "rootfs_removed": removed,
        }

    @staticmethod
    def _snapshot_artifacts(artifacts_dir: str) -> dict[str, tuple[int, int]]:
        """Snapshot the custody directory before execution (name ->
        (size, mtime_ns)) so only run-produced changes are custodied."""
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
        """Hash every artifact this run left in the custody directory."""
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
        """Persist bounded stdout/stderr as referenceable artifacts."""
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
        if active and isinstance(active.get("rootfs_dir"), str):
            shutil.rmtree(str(active["rootfs_dir"]), ignore_errors=True)
        return TeardownEvidence(
            sandbox_id=sandbox_id,
            torn_down=True,
            detail="no active run; teardown is a no-op",
        )


def local_sandbox_manager(
    *, images: Mapping[str, LocalImage] | None = None
) -> SandboxManager:
    """Reference wiring: a sandbox manager with the local substrate.

    The caller still owns allowlisting images and executing requests;
    this helper only registers the real adapter (the production E1
    wiring shown in the documentation).
    """
    adapter = LocalSubstrateAdapter(images=images)
    manager = SandboxManager(substrate=adapter)
    manager.allow_images(frozenset(adapter.image_names))
    return manager


__all__ = [
    "DECLARED_SECURITY_POSTURE",
    "DENIED_SYSCALLS",
    "DESCRIPTOR",
    "LocalImage",
    "LocalSubstrateAdapter",
    "SANDBOX_HOSTNAME",
    "SANDBOX_NOFILE_LIMIT",
    "default_local_images",
    "local_sandbox_manager",
    "substrate_capabilities",
]
