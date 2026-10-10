"""E10-RP2.2-R2A2 — BINDING TEST MATRIX (order §2/§3, arbitration on R2A1).

§3 NEGATIVE TESTS (the accreditation demand): with hostile GIT_CONFIG_*
variables planted in the CALLING PROCESS environment — the arbitrator's
exact reproduction set — the pinned push must land ONLY at the SIGNED
repository, proven by REPO CONTENT (refs + object existence + object
counts), never by parsing push output; the attacker repository must
receive no commit and no related objects.

Coverage map (order -> leg):
  §3.2/§3.3 arbiter PoC (GIT_CONFIG_COUNT family)     -> N1
  §3.4 GIT_CONFIG_PARAMETERS (sq-quoted grammar,
        git v2.47.3 config.c:669-719 — probe EP2a)     -> N2
  §3.4 every additional discovered env variable that
        can change URL settings / the command's repo   -> N3 (sweep)
  §2.5 transport policy fail-closed                    -> N4
  §2.2 allowlist policy (unit)                         -> N5
  §3.5 sanitization happens inside the CHILD process
        env itself (does not rely on a clean test env) -> N6 (+N1..N3
        all run with a POLLUTED parent os.environ)
  full-chain property: hostile env can only cause
        fail-closed REFUSAL, never redirection          -> N7

Layering disclosure (order §4.3, same as R2A1): the git_push handler legs
that reach the execution layer use the disclosed permissive scaffold
validator; the approval chain (HMAC + TTL + single-use nonce ledger +
registry) and every git effect are REAL. Direct ``staged_push`` legs are
the push-execution unit under order §3.1's exact setup (source repo +
staging bare via objects/info/alternates + signed repo + attacker repo).
"""
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

sys.path.insert(0, str(HERE))

from e10rp22r2_probes_lib import (  # noqa: E402
    PY, git_out, make_bare, make_repo,
)

from test_e10rp22r2a_matrix import (  # noqa: E402
    _bare_head, _bridge_stack, _call, _gate_v2_keys, _designate,
    _permissive_path_aware,
)

import asyncio  # noqa: E402

from unified.contracts import AgentType, MissionState  # noqa: E402
from unified.execution import ExecutionEngine, ExecutionContext  # noqa: E402
from eoe.push_engine import (  # noqa: E402
    NonceLedger, OwnerApprovalService, PushApprovalRegistry,
    PushRejected, _sanitized_git_env, resolve_push_destination,
    staged_push,
)

# The grammar git 2.47.3 accepts for GIT_CONFIG_PARAMETERS (probe EP2a,
# source: config.c:669-719 parse_config_env_list): sq-quoted tokens,
# old-style 'key=value' — JSON forms are rejected as bogus format.
_PARAMETERS_GRAMMAR = "old-style sq-quoted 'key=value'"


# ================================================================
# helpers
# ================================================================

def _head(repo: str, ref: str = "main") -> str:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify",
                        f"refs/heads/{ref}"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _has_commit(repo: str, sha: str) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "cat-file", "-e",
                        f"{sha}^{{commit}}"], capture_output=True, text=True)
    return r.returncode == 0


def _object_count(repo: str) -> int:
    r = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch-all-objects",
         "--batch-check=%(objectname)"], capture_output=True, text=True)
    return len([ln for ln in r.stdout.splitlines() if ln.strip()])


def _refs(repo: str) -> list:
    r = subprocess.run(["git", "-C", str(repo), "for-each-ref",
                        "--format=%(refname)"], capture_output=True, text=True)
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _fresh_pair(tmp_path, tag: str):
    """Fresh signed/attacker bares for ONE leg — content proves THIS call
    (a bare is never reused across legs)."""
    base = Path(tmp_path)
    signed = make_bare(str(base / f"{tag}-signed.git"))
    attacker = make_bare(str(base / f"{tag}-attacker.git"))
    return signed, attacker


def _assert_only_signed_lands(signed: str, attacker: str, sha: str, *,
                               tag: str):
    """The order's ONLY accepted outcome, by REPO CONTENT (§3.3): the signed
    repository received the commit; the attacker received NO commit and NO
    related objects (empty ref list, cat-file fails, zero objects)."""
    assert _head(signed) == sha, f"[{tag}] signed did not receive the commit"
    assert _has_commit(signed, sha), f"[{tag}] signed lacks the commit object"
    assert _head(attacker) == "", f"[{tag}] ATTACKER received the ref!"
    assert not _has_commit(attacker, sha), f"[{tag}] ATTACKER received objects!"
    assert _object_count(attacker) == 0, (
        f"[{tag}] attacker object store is not empty: "
        f"{_object_count(attacker)} objects"
    )
    assert _refs(attacker) == [], f"[{tag}] attacker has refs: {_refs(attacker)}"


@contextmanager
def _polluted_os_environ(hostile: dict):
    """Plant hostile variables in the CALLING PROCESS os.environ for the
    duration of the wrapped call — exactly the arbitrator's threat model
    (order §3.2: 'قبل تشغيل الدفع، ضع في بيئة العملية: …'). staged_push
    builds its child env from os.environ at call time, so the pollution is
    live for every child it spawns. Restored afterwards; saved values are
    popped (None = was absent)."""
    saved = {}
    for k, v in hostile.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _source_repo(tmp_path):
    src = make_repo(str(Path(tmp_path) / "src-repo"))
    sha = git_out(src, "rev-parse", "HEAD")
    return src, sha


# ================================================================
# N1 — the arbitrator's exact PoC, FIXED code (order §3.2/§3.3)
# ================================================================

def test_R2A2_N1_arbiter_poc_env_injection_neutralized(tmp_path):
    """N1 (§3.2/§3.3, the EXACT demanded setup): source repo + push from a
    staging bare that depends on objects/info/alternates (all inside the
    real staged_push) + signed repo + attacker repo. Before the push, the
    PROCESS environment carries GIT_CONFIG_COUNT=1,
    GIT_CONFIG_KEY_0=url.<attacker>.insteadOf,
    GIT_CONFIG_VALUE_0=<signed-url> — the arbitrator's reproduction set
    (probe EP1/EP3 proved it OBSERVED pre-fix: attacker received, signed
    did not). The ONLY accepted outcome now: the signed repo receives the
    commit, the attacker repo receives no commit and no related objects —
    inspected by repo content, not by comparing output logs."""
    src, sha = _source_repo(tmp_path)
    signed, attacker = _fresh_pair(tmp_path, "n1")
    hostile = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{attacker}.insteadOf",
        "GIT_CONFIG_VALUE_0": str(signed),
    }
    with _polluted_os_environ(hostile):
        out = staged_push(src, str(signed), sha, "main")
    assert out["returncode"] == 0, out["stderr"]
    # argv evidence: the push command used the SIGNED URL, in full
    assert str(signed) in out["argv"]
    assert f"{sha}:refs/heads/main" in out["argv"]
    _assert_only_signed_lands(signed, attacker, sha, tag="N1")


# ================================================================
# N2 — GIT_CONFIG_PARAMETERS (order §3.4)
# ================================================================

def test_R2A2_N2_git_config_parameters_neutralized(tmp_path):
    """N2 (§3.4): repeat the PoC with GIT_CONFIG_PARAMETERS — the second
    env-config channel, grammar discovered by probe EP2a from git v2.47.3
    source (sq-quoted 'key=value'; JSON forms are 'bogus format'). Pre-fix
    probe EP2 proved the reroute OBSERVED; now the push must land only at
    the signed repository."""
    src, sha = _source_repo(tmp_path)
    signed, attacker = _fresh_pair(tmp_path, "n2")
    hostile = {
        "GIT_CONFIG_PARAMETERS": f"'url.{attacker}.insteadOf'='{signed}'",
    }
    with _polluted_os_environ(hostile):
        out = staged_push(src, str(signed), sha, "main")
    assert out["returncode"] == 0, out["stderr"]
    assert str(signed) in out["argv"]
    _assert_only_signed_lands(signed, attacker, sha, tag="N2")


# ================================================================
# N3 — inherited-variable sweep (order §3.4: every additional
#      discovered variable that can change URL settings or the
#      command's repo / object database)
# ================================================================

_SWEEP = pytest.mark.parametrize("var,value_kind", [
    ("GIT_DIR", "hostile_repo"),
    ("GIT_WORK_TREE", "hostile_path"),
    ("GIT_COMMON_DIR", "hostile_repo"),
    ("GIT_OBJECT_DIRECTORY", "hostile_objects"),
    ("GIT_ALTERNATE_OBJECT_DIRECTORIES", "attacker_objects"),
    ("GIT_CONFIG", "rewrite_config"),
    ("GIT_CONFIG_SYSTEM", "rewrite_config"),
    ("GIT_CONFIG_GLOBAL", "rewrite_config"),
    ("GIT_CONFIG_NOSYSTEM", "zero"),
    ("GIT_NAMESPACE", "evil_namespace"),
    ("GIT_SSH_COMMAND", "transport_probe"),
    ("GIT_PROXY_COMMAND", "transport_probe"),
    ("GIT_ASKPASS", "bin_false"),
    ("GIT_TERMINAL_PROMPT", "one"),
    ("HOME", "evil_home_rewrite"),
    ("XDG_CONFIG_HOME", "evil_xdg_rewrite"),
    ("http_proxy", "evil_proxy"),
    ("HTTPS_PROXY", "evil_proxy"),
    ("SSH_AUTH_SOCK", "evil_socket"),
])


@_SWEEP
def test_R2A2_N3_inherited_variable_sweep(tmp_path, var, value_kind):
    """N3 (§3.4): each hostile inherited variable ALONE, through the REAL
    staged_push. Every leg: the push succeeds AND lands ONLY at the signed
    repo (fresh pair), the attacker receives nothing, and transport-command
    probes (GIT_SSH_COMMAND / GIT_PROXY_COMMAND pointing at a marker-writing
    command) never execute — the sanitized child env carries none of them.

    Values are chosen to be REWRITE/REPOINT-capable where the channel allows
    (hostile config files containing url.<attacker>.insteadOf = <signed>,
    hostile HOME/XDG with rewrite configs, GIT_DIR/GIT_OBJECT_DIRECTORY
    pointing at attacker-controlled paths) so a surviving inheritance would
    be OBSERVED as a reroute or a fail-closed break — never silently."""
    src, sha = _source_repo(tmp_path)
    signed, attacker = _fresh_pair(tmp_path, "n3")
    base = Path(tmp_path)

    # hostile rewrite config: reroutes <signed> -> <attacker> if inherited
    rewrite_cfg = base / "n3-evil-rewrite.cfg"
    rewrite_cfg.write_text(f'[url "{attacker}"]\n\tinsteadOf = {signed}\n')
    # hostile HOME / XDG carrying the same rewrite
    evil_home = base / "n3-evil-home"
    (evil_home / ".gitconfig").parent.mkdir(parents=True, exist_ok=True)
    (evil_home / ".gitconfig").write_text(
        f'[url "{attacker}"]\n\tinsteadOf = {signed}\n')
    evil_xdg = base / "n3-evil-xdg"
    (evil_xdg / "git").mkdir(parents=True, exist_ok=True)
    (evil_xdg / "git" / "config").write_text(
        f'[url "{attacker}"]\n\tinsteadOf = {signed}\n')
    hostile_repo = base / "n3-hostile.git"
    hostile_repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", str(hostile_repo)],
                   check=True)

    marker = base / "n3-transport-marker"
    values = {
        "hostile_repo": str(hostile_repo),
        "hostile_path": str(base),
        "hostile_objects": str(hostile_repo / "objects"),
        "attacker_objects": str(Path(attacker) / "objects"),
        "rewrite_config": str(rewrite_cfg),
        "zero": "0",
        "evil_namespace": "evil",
        "transport_probe": f"sh -c 'touch {marker}'",
        "bin_false": "/bin/false",
        "one": "1",
        "evil_home_rewrite": str(evil_home),
        "evil_xdg_rewrite": str(evil_xdg),
        "evil_proxy": "http://127.0.0.1:9/",
        "evil_socket": str(base / "n3-evil-socket"),
    }
    hostile = {var: values[value_kind]}
    with _polluted_os_environ(hostile):
        out = staged_push(src, str(signed), sha, "main")
    assert out["returncode"] == 0, out["stderr"]
    _assert_only_signed_lands(signed, attacker, sha, tag=f"N3:{var}")
    # transport-command probes never ran
    assert not marker.exists(), f"[N3:{var}] transport command executed!"


# ================================================================
# N4 — transport policy fail-closed (order §2.5)
# ================================================================

def test_R2A2_N4_transport_policy_fail_closed(tmp_path):
    """N4 (§2.5): only the LOCAL FILESYSTEM is an accredited transport.
    https/ssh/git-scp-like/file://<host>/relative are ALL refused
    PushRejected fail-closed — and the refusal happens BEFORE any
    subprocess (proven by ordering: a nonexistent SOURCE repo would fail
    rev-parse first if the gate did not precede it; instead the transport
    refusal is what surfaces). file:/// with empty authority IS accredited
    and lands at the signed destination with the argv carrying the exact
    signed URL string."""
    src, sha = _source_repo(tmp_path)
    nonexistent_src = str(Path(tmp_path) / "no-such-repo")
    bad_urls = [
        "https://attacker.example/repo.git",
        "ssh://git@host/repo.git",
        "git@host:repo.git",
        "host:repo.git",
        "file://localhost/tmp/x.git",
        "relative/repo.git",
        "git://host/repo.git",
        "ftp://host/repo.git",
        "rsync://host/repo.git",
    ]
    for url in bad_urls:
        with pytest.raises(PushRejected) as ei:
            staged_push(nonexistent_src, url, sha, "main")
        # the transport refusal — NOT a rev-parse failure of the
        # nonexistent source — proves the gate runs BEFORE any subprocess
        assert "نوع نقل غير معتمد" in str(ei.value) or \
            "وجهة غير مطلقة" in str(ei.value), (url, str(ei.value))
        assert "git dir" not in str(ei.value), (url, str(ei.value))
    # accredited: file:/// with empty authority — lands, argv carries the
    # signed URL string verbatim
    signed, attacker = _fresh_pair(tmp_path, "n4-file")
    file_url = f"file://{signed}"
    out = staged_push(src, file_url, sha, "main")
    assert out["returncode"] == 0, out["stderr"]
    assert file_url in out["argv"]
    _assert_only_signed_lands(signed, attacker, sha, tag="N4:file")
    # accredited: plain absolute path (the canonical resolve output form)
    signed2, attacker2 = _fresh_pair(tmp_path, "n4-path")
    out = staged_push(src, str(signed2), sha, "main")
    assert out["returncode"] == 0, out["stderr"]
    _assert_only_signed_lands(signed2, attacker2, sha, tag="N4:path")


# ================================================================
# N5 — sanitized env policy (unit; order §2.2/§2.3)
# ================================================================

def test_R2A2_N5_sanitized_env_policy_unit(tmp_path):
    """N5 (§2.2/§2.3 unit): with a hostile os.environ — every dangerous
    GIT_* name present with a hostile value, plus HOME/XDG/proxy/socket —
    `_sanitized_git_env()` returns EXACTLY the allowlist (PATH + the
    Windows startup names on nt) plus the three safe overrides with FIXED
    values. No GIT_* other than the safe trio; no HOME/XDG/proxy/askpass;
    GIT_CONFIG_GLOBAL and GIT_CONFIG_SYSTEM are cleaned BEFORE the safe
    value is set (strip-then-set, never inherit-then-modify)."""
    from eoe.push_engine import _SANITIZED_ENV_ALLOWLIST
    rewrite = tmp_path / "n5-evil.cfg"
    hostile = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "url.evil.insteadOf",
        "GIT_CONFIG_VALUE_0": "signed",
        "GIT_CONFIG_PARAMETERS": "'url.evil.insteadOf'='signed'",
        "GIT_CONFIG": str(rewrite),
        "GIT_CONFIG_SYSTEM": str(rewrite),
        "GIT_CONFIG_GLOBAL": str(rewrite),
        "GIT_CONFIG_NOSYSTEM": "0",
        "GIT_DIR": "/hostile",
        "GIT_WORK_TREE": "/hostile",
        "GIT_COMMON_DIR": "/hostile",
        "GIT_OBJECT_DIRECTORY": "/hostile/objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/hostile/objects",
        "GIT_NAMESPACE": "evil",
        "GIT_SSH_COMMAND": "touch /pwned",
        "GIT_PROXY_COMMAND": "touch /pwned",
        "GIT_ASKPASS": "/bin/false",
        "GIT_TERMINAL_PROMPT": "1",
        "GIT_TRACE": "1",
        "HOME": "/hostile-home",
        "XDG_CONFIG_HOME": "/hostile-xdg",
        "http_proxy": "http://127.0.0.1:9/",
        "HTTPS_PROXY": "http://127.0.0.1:9/",
        "SSH_AUTH_SOCK": "/hostile-socket",
    }
    with _polluted_os_environ(hostile):
        env = _sanitized_git_env()
    expected = {n: os.environ[n] for n in _SANITIZED_ENV_ALLOWLIST
                if os.environ.get(n) is not None}
    expected.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    })
    assert env == expected, (sorted(env), sorted(expected))
    # the invariant form of the same statement: NOTHING except the safe
    # trio starts with GIT_ — covers every future GIT_* channel by rule
    unsafe_git = [k for k in env if k.startswith("GIT_")
                  and k not in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL",
                                "GIT_CONFIG_SYSTEM")]
    assert unsafe_git == [], unsafe_git
    for banned in ("HOME", "XDG_CONFIG_HOME", "http_proxy", "HTTPS_PROXY",
                   "SSH_AUTH_SOCK"):
        assert banned not in env, banned


# ================================================================
# N6 — child-process env proof (order §3.5)
# ================================================================

def test_R2A2_N6_child_process_env_dump(tmp_path):
    """N6 (§3.5): the sanitization happens inside the CHILD process
    environment itself and does not depend on the test environment being
    clean. Direct evidence: the SIGNED destination carries a pre-receive
    hook (receiving-side test double, disclosed) that dumps its inherited
    environment to a file while the push runs under a FULLY POLLUTED
    parent os.environ. The dump — the pushing child's env as received by
    receive-pack — contains NONE of the hostile variables and carries the
    three safe values.

    Disclosure: receive-pack adds its OWN receiving-side variables to the
    hook environment (GIT_DIR='.', GIT_QUARANTINE_PATH, GIT_PUSH_CERT*).
    Those are artifacts of the receiving process, not the pushing child's
    inherited env, and are excluded from the must-be-absent set — the
    assertion covers exactly the hostile set planted in the parent."""
    src, sha = _source_repo(tmp_path)
    signed, attacker = _fresh_pair(tmp_path, "n6")
    dump = Path(tmp_path) / "n6-hook-env.txt"
    hooks = Path(signed) / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-receive").write_text(
        "#!/bin/sh\nenv | sort > " + repr(str(dump)) + "\nexit 0\n")
    subprocess.run(["chmod", "+x", str(hooks / "pre-receive")], check=True)

    rewrite_cfg = Path(tmp_path) / "n6-evil.cfg"
    rewrite_cfg.write_text(f'[url "{attacker}"]\n\tinsteadOf = {signed}\n')
    hostile = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{attacker}.insteadOf",
        "GIT_CONFIG_VALUE_0": str(signed),
        "GIT_CONFIG_PARAMETERS": f"'url.{attacker}.insteadOf'='{signed}'",
        "GIT_CONFIG_SYSTEM": str(rewrite_cfg),
        "GIT_CONFIG_GLOBAL": str(rewrite_cfg),
        "GIT_CONFIG": str(rewrite_cfg),
        "GIT_CONFIG_NOSYSTEM": "0",
        "GIT_DIR": str(Path(tmp_path) / "n6-hostile.git"),
        "GIT_WORK_TREE": str(tmp_path),
        "GIT_COMMON_DIR": str(Path(tmp_path) / "n6-hostile.git"),
        "GIT_OBJECT_DIRECTORY": str(Path(tmp_path) / "n6-hostile.git/objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(Path(attacker) / "objects"),
        "GIT_NAMESPACE": "evil",
        "GIT_SSH_COMMAND": "touch /pwned",
        "GIT_PROXY_COMMAND": "touch /pwned",
        "GIT_ASKPASS": "/bin/false",
        "GIT_TERMINAL_PROMPT": "1",
        "HOME": str(Path(tmp_path) / "n6-evil-home"),
        "XDG_CONFIG_HOME": str(Path(tmp_path) / "n6-evil-xdg"),
    }
    with _polluted_os_environ(hostile):
        out = staged_push(src, str(signed), sha, "main")
    assert out["returncode"] == 0, out["stderr"]
    _assert_only_signed_lands(signed, attacker, sha, tag="N6")

    # the dump proves the child env was sanitized — not the test env
    assert dump.exists(), "pre-receive hook did not run/dump"
    dumped = {}
    for ln in dump.read_text().splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            dumped[k] = v

    # Contract: a hostile name is either ENTIRELY ABSENT from the child env,
    # or — for the three safe names only — present with EXACTLY the safe
    # value (strip the inherited value, then set the safe one; §2.3). No
    # planted hostile value may survive in any form.
    safe_values = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    # receiving-side additions by receive-pack (like GIT_DIR='.'): the
    # RECEIVING process adds these to the hook env — they are not inherited
    # values from the pushing child. Disclosed in the docstring.
    receiving_side = {
        "GIT_DIR",                      # receive-pack sets '.' for hooks
        "GIT_QUARANTINE_PATH",          # quarantine object dir (receiving)
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",  # receive-pack points it at the
        # receiving repo's own objects — its VALUE proves it is not our
        # planted hostile value (asserted below)
        "GIT_OBJECT_DIRECTORY",         # receive-pack's quarantine sets it
        # to a tmp_objdir-incoming-* dir inside the RECEIVING repo (its
        # VALUE proves it is not our planted hostile value)
        "GIT_PUSH_CERT", "GIT_PUSH_CERT_NAMES", "GIT_PUSH_CERT_STATUS",
    }
    for name, planted in hostile.items():
        if name in receiving_side and name in dumped:
            # receiving-side addition: must NOT equal the planted hostile
            # value (e.g. receive-pack's alternates point at the SIGNED
            # repo's objects, never the ATTACKER's)
            assert dumped[name] != planted, \
                f"[N6] {name} carries the PLANTED hostile value: {planted!r}"
            continue
        if name in safe_values:
            assert dumped.get(name) == safe_values[name], (
                f"[N6] {name} must be absent-or-safe: got "
                f"{dumped.get(name)!r}")
        else:
            assert name not in dumped, \
                f"[N6] {name} SURVIVED into the child env: {dumped.get(name)!r}"
    # the safe trio is present with the exact safe values (positive proof)
    for k, v in safe_values.items():
        assert dumped.get(k) == v, (k, dumped.get(k))
    assert dumped.get("GIT_CONFIG_NOSYSTEM") == "1"
    # receive-pack's receiving-side artifacts are present as expected
    assert "GIT_DIR" in dumped  # receive-pack sets it to '.' for the hook


# ================================================================
# N7 — full-chain property: hostile env can only cause fail-closed
#      REFUSAL, never redirection (through the real handler chain)
# ================================================================

def test_R2A2_N7_full_chain_fail_closed_not_redirected(tmp_path):
    """N7 (§4 boundary proof through the REAL handler chain): with the
    hostile env-config live at PUSH time, the handler's own destination
    resolution inherits it too — so the resolved URL no longer matches the
    SIGNED destination, and verify_and_consume REFUSES fail-closed before
    any push. The attacker receives NOTHING (content-inspected); the
    refusal text is the R2A scope-mismatch error; then the SAME operation
    with a clean environment (fresh gate cycle) lands ONLY at the signed
    destination. Deterministic summary: a polluted environment can make
    the chain REFUSE — it can never make it REDIRECT.

    Layering (order §4.3, disclosed): permissive path-aware scaffold
    validator reaches the handler layer; the approval chain (HMAC + TTL +
    single-use nonce + registry) and every git effect are REAL — the
    production chain stays rejected through the real bridge, re-proven by
    the R2A/R2A1 matrices in the battery."""
    from test_e10rp22r2a_matrix import _bridge_stack
    base = Path(tmp_path)
    stack = _bridge_stack(base / "ws")
    ws = stack["ws"]
    signed = make_bare(str(base / "n7-signed.git"))
    attacker = make_bare(str(base / "n7-attacker.git"))
    git_out(stack["repoA"], "remote", "add", "n7remote", signed)
    head = git_out(stack["repoA"], "rev-parse", "HEAD")
    repo_root = str(Path(stack["repoA"]).resolve())
    push_url = resolve_push_destination(repo_root, "n7remote")
    assert push_url == str(signed)

    svc = OwnerApprovalService(b"r2a2-n7-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    appr = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                    files_digest="n7", remote="n7remote", force=False,
                    push_url=push_url)
    registry.register(appr)
    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=_permissive_path_aware,  # scaffold (§4.3, disclosed)
        grant_ids=[stack["grant_id"]],
        push_approval_registry=registry,
    )
    mission = engine.create_mission("r2a2-n7")
    mission.state = MissionState.EXECUTING
    ctx = ExecutionContext(
        mission_id=mission.mission_id, run_id="run-n7", task_id="task-n7",
        attempt_id="attempt-n7", agent_id="agent-n7",
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=[stack["grant_id"]],
        grant_validator=_permissive_path_aware,
        workspace_root=str(ws),
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )
    inp = {"repo_path": stack["repoA"], "remote": "n7remote", "branch": "main",
           "owner_approval_nonce": appr.nonce}

    rewrite_cfg = base / "n7-evil.cfg"
    rewrite_cfg.write_text(f'[url "{attacker}"]\n\tinsteadOf = {signed}\n')
    hostile = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{attacker}.insteadOf",
        "GIT_CONFIG_VALUE_0": str(signed),
        "GIT_CONFIG_PARAMETERS": f"'url.{attacker}.insteadOf'='{signed}'",
        "GIT_CONFIG_SYSTEM": str(rewrite_cfg),
        "GIT_CONFIG_GLOBAL": str(rewrite_cfg),
    }

    # ---- attempt 1: hostile env live at push time -> REFUSED fail-closed
    st, payload = _call(engine, ctx, "git_push", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    key = _gate_v2_keys(mission)[0]
    engine.decide_human_gate(mission.mission_id, mission.metadata[key],
                             "approve", "owner", "n7")
    _designate(engine, key, ctx.attempt_id)

    from test_e10rp22r2a1_matrix import _workspace_cwd
    with _polluted_os_environ(hostile), _workspace_cwd(ws):
        st, payload = _call(engine, ctx, "git_push", inp)
    assert st == "TOOL_RESULT" and not payload.success, (st, payload)
    assert "لا تطابق" in (payload.error or "") or \
        "does not match" in (payload.error or ""), payload.error
    # content proof: the attacker received NOTHING; the signed repo too
    assert _head(attacker) == "" and not _has_commit(attacker, head) \
        and _object_count(attacker) == 0, "attacker received something!"
    assert _head(signed) == "", "signed received during a REFUSED push?!"
    assert _refs(signed) == []

    # ---- attempt 2: clean env, fresh gate cycle -> lands ONLY at signed
    # (a consumed identity opens a NEW cycle under the SAME op_key slot —
    # mission.metadata[key] now holds the new cycle's gate id)
    mission.state = MissionState.EXECUTING
    st, payload = _call(engine, ctx, "git_push", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    gate2 = mission.metadata[key]
    assert gate2 != mission.metadata.get(f"{key}#cycle1")  # a NEW gate
    engine.decide_human_gate(mission.mission_id, gate2,
                             "approve", "owner", "n7b")
    _designate(engine, key, ctx.attempt_id)
    with _workspace_cwd(ws):
        st, payload = _call(engine, ctx, "git_push", inp)
    assert st == "TOOL_RESULT" and payload.success, (st, payload)
    assert payload.output["push_url"] == str(signed)
    assert str(signed) in payload.output["push_argv"]
    assert _head(signed) == head
    assert _head(attacker) == "" and not _has_commit(attacker, head) \
        and _object_count(attacker) == 0
