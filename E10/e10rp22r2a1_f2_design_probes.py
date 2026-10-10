#!/usr/bin/env python3
"""E10-RP2.2-R2A1 §3 — F2 DESIGN PROBES (push destination pinning).

Empirical determination of git's behavior, driving the R2A1 §3.2 design:

  P1  Can a bare STAGING repo (objects reachable ONLY via
      objects/info/alternates) push an explicit ``<sha>:refs/heads/<branch>``
      refspec to a local bare destination? (The staging push design.)
  P2  Does ``git push`` accept the ``--`` option separator before the
      <repository> positional argument? (argv hygiene.)
  P3  ATTACK DEMO: in a NORMAL repo, does a local ``url.<base>.insteadOf``
      rule rewrite an EXPLICIT url passed to ``git push <url> ...``? (Why
      pushing from the source repo — even with the resolved URL — cannot
      structurally exclude a between-verification-and-execution config
      change.)
  P4  STAGING ISOLATION: with the source repo carrying an insteadOf rule
      that WOULD rewrite the signed URL, does the staging push (fresh bare
      repo + alternates + sanitized env) still land at the SIGNED
      destination only (evil destination receives NOTHING)?
  P5  Does GIT_CONFIG_GLOBAL=/dev/null + GIT_CONFIG_NOSYSTEM=1 suppress a
      GLOBAL-config insteadOf rewrite for the push subprocess?
  P6  Does the staging push honor ``--force`` with the sha refspec
      (non-ff update accepted with, rejected without)?
  P7  Does a source-repo pushurl CHANGE (added between "resolution" and
      execution) affect the staging push destination? (It must not.)

Every probe runs in throwaway temp trees; nothing here touches any
worktree. Raw output of every command is recorded.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

RESULTS: list[str] = []


def rec(line: str = "") -> None:
    print(line)
    RESULTS.append(line)


def run(label: str, *argv: str, cwd: str | None = None, env: dict | None = None,
        timeout: int = 30) -> subprocess.CompletedProcess:
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


def sh(label: str, script: str) -> None:
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       timeout=30)
    rec(f"$ bash -c {script!r}")
    rec(f"  exit={r.returncode}")
    if r.stdout.strip():
        rec("  stdout: " + r.stdout.strip().replace("\n", "\n          "))
    if r.stderr.strip():
        rec("  stderr: " + r.stderr.strip().replace("\n", "\n          "))


def head_of(repo: str, ref: str = "main") -> str:
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify",
                        f"refs/heads/{ref}"], capture_output=True, text=True)
    return r.stdout.strip()


def _has_commit(repo: str, sha: str) -> bool:
    """Does the repo's object store contain the commit (cat-file -e)?"""
    r = subprocess.run(["git", "-C", repo, "cat-file", "-e",
                        f"{sha}^{{commit}}"], capture_output=True, text=True)
    return r.returncode == 0


def make_source(base: Path) -> Path:
    src = base / "source"
    src.mkdir()
    run("init source", "git", "init", "-q", "-b", "main", str(src))
    (src / "f.txt").write_text("hello\n")
    run("add", "git", "-C", str(src), "add", "-A")
    r = subprocess.run(
        ["git", "-C", str(src), "-c", "user.name=p", "-c", "user.email=p@x",
         "commit", "-q", "-m", "c1"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return src


def make_bare_at(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    run(f"init bare {path.name}", "git", "init", "-q", "--bare", str(path))
    return path


def make_staging(base: Path, source_objects: Path) -> Path:
    st = base / "staging.git"
    run("init staging bare", "git", "init", "-q", "--bare", str(st))
    info = st / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(str(source_objects) + "\n")
    return st


SAN = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="r2a1-f2-probe-")
    base = Path(tmp)
    rec(f"# workdir: {tmp}")
    rec(f"# git version: {subprocess.run(['git', '--version'], capture_output=True, text=True).stdout.strip()}")
    rec()

    # ---------------- P1: staging push with sha refspec ----------------
    rec("=== P1: staging repo (alternates-only objects) push <sha>:refs/heads/<b>")
    src = make_source(base)
    signed = make_bare_at(base / "signed.git")
    sha = head_of(str(src))
    src_git_dir = subprocess.run(
        ["git", "-C", str(src), "rev-parse", "--absolute-git-dir"],
        capture_output=True, text=True).stdout.strip()
    rec(f"# source git-dir: {src_git_dir}; sha: {sha}")
    st = make_staging(base, Path(src_git_dir) / "objects")
    r = run("staging push (no force)", "git", "--git-dir", str(st), "push",
            str(signed), f"{sha}:refs/heads/main", env=SAN)
    landed = head_of(str(signed))
    rec(f"[P1] {'PASS' if r.returncode == 0 and landed == sha else 'FAIL'}: "
        f"staging push exit={r.returncode}; signed.git main = {landed or '(none)'}; expected {sha}")
    rec()

    # ---------------- P2: '--' separator acceptance ----------------
    rec("=== P2: git push -- <url> <refspec> (option separator)")
    signed2 = make_bare_at(base / "signed2.git")
    (src / "g.txt").write_text("g\n")
    run("second commit", "git", "-C", str(src), "add", "-A")
    subprocess.run(["git", "-C", str(src), "-c", "user.name=p",
                    "-c", "user.email=p@x", "commit", "-q", "-m", "c2"],
                   capture_output=True, text=True)
    sha2 = head_of(str(src))
    r = run("staging push with --", "git", "--git-dir", str(st), "push", "--",
            str(signed2), f"{sha2}:refs/heads/main", env=SAN)
    landed2 = head_of(str(signed2))
    rec(f"[P2] {'PASS' if r.returncode == 0 and landed2 == sha2 else 'FAIL'}: "
        f"'--' accepted; signed2.git main = {landed2 or '(none)'}")
    rec()

    # ---------------- P3: attack demo — explicit URL IS rewritten -------
    rec("=== P3: ATTACK DEMO — local insteadOf rewrites an EXPLICIT push URL")
    evil = make_bare_at(base / "evil.git")
    target = make_bare_at(base / "target.git")
    # normal repo 'victim' whose local config has an insteadOf rule that
    # rewrites anything starting with the target path to the evil path
    victim = base / "victim"
    victim.mkdir()
    run("init victim", "git", "init", "-q", "-b", "main", str(victim))
    (victim / "v.txt").write_text("v\n")
    run("victim add", "git", "-C", str(victim), "add", "-A")
    subprocess.run(["git", "-C", str(victim), "-c", "user.name=p",
                    "-c", "user.email=p@x", "commit", "-q", "-m", "v1"],
                   capture_output=True, text=True)
    vsha = head_of(str(victim))
    run("set insteadOf rewrite", "git", "-C", str(victim), "config",
        f"url.{evil}.insteadOf", str(target))
    # the caller "resolved" the destination as <target> and passes it
    # EXPLICITLY to git push — git still applies the rewrite:
    r = run("victim push explicit <target-url>", "git", "-C", str(victim),
            "push", "--", str(target), f"{vsha}:refs/heads/main")
    t_landed = head_of(str(target))
    e_landed = head_of(str(evil))
    rerouted = e_landed == vsha and t_landed == ""
    rec(f"[P3] {'CONFIRMED' if rerouted else 'NOT-CONFIRMED'}: explicit url "
        f"push landed at evil={e_landed or '(none)'} target={t_landed or '(none)'} "
        f"— an explicit URL is NOT proof of destination in a normal repo")
    rec()

    # ---------------- P4: staging isolation beats the same attack -------
    rec("=== P4: STAGING ISOLATION — same rewrite present in SOURCE config")
    # source repo now carries the same insteadOf rule (as if changed between
    # resolution and execution); the staging push must still land ONLY at the
    # signed destination
    run("source: set the same insteadOf", "git", "-C", str(src), "config",
        f"url.{str(evil)}.insteadOf", str(signed2))
    signed3 = make_bare_at(base / "signed3.git")
    r = run("staging push (source rewritten)", "git", "--git-dir", str(st),
            "push", "--", str(signed3), f"{sha2}:refs/heads/main", env=SAN)
    s3 = head_of(str(signed3))
    e3 = head_of(str(evil))
    # evil may legitimately contain the P3 victim commit; the isolation
    # property is that it does NOT contain THIS push's sha
    ok = (r.returncode == 0 and s3 == sha2
          and sha2 not in (e3,)
          and not _has_commit(str(evil), sha2))
    rec(f"[P4] {'PASS' if ok else 'FAIL'}: staging push landed at "
        f"signed3={s3 or '(none)'}; evil head={e3 or '(none)'}; evil has this "
        f"sha={_has_commit(str(evil), sha2)} (must be False; source-config "
        f"rewrite never read)")
    rec()

    # ---------------- P5: global config neutralized ---------------------
    rec("=== P5: GLOBAL insteadOf neutralized by sanitized env")
    ghome = base / "ghome"
    ghome.mkdir()
    (ghome / ".gitconfig").write_text(
        f"[url \"{base / 'global-evil.git'}\"]\n\tinsteadOf = {base / 'global-target.git'}\n"
        f"[user]\n\tname = p\n\temail = p@x\n")
    gt = make_bare_at(base / "global-target.git")
    ge = make_bare_at(base / "global-evil.git")
    r = run("staging push, global rewrite armed, env sanitized",
            "git", "--git-dir", str(st), "push", "--", str(gt),
            f"{sha2}:refs/heads/main",
            env={**SAN, "HOME": str(ghome), "XDG_CONFIG_HOME": str(ghome / ".config")})
    gtl = head_of(str(gt))
    gel = head_of(str(ge))
    ok = r.returncode == 0 and gtl == sha2 and gel == ""
    rec(f"[P5] {'PASS' if ok else 'FAIL'}: landed at global-target={gtl or '(none)'}; "
        f"global-evil={gel or '(none)'} (global rewrite suppressed)")
    rec()

    # ---------------- P6: force semantics with sha refspec --------------
    rec("=== P6: --force + sha refspec (non-ff REWIND)")
    # advance signed.git to sha2 (fast-forward), then attempt to REWIND it
    # back to sha (non-ff): rejected without --force, accepted with it.
    r_ff = run("advance to c2 (ff)", "git", "--git-dir", str(st), "push",
               "--", str(signed), f"{sha2}:refs/heads/main", env=SAN)
    r_no = run("rewind WITHOUT --force", "git", "--git-dir", str(st), "push",
               "--", str(signed), f"{sha}:refs/heads/main", env=SAN)
    r_yes = run("rewind WITH --force", "git", "--git-dir", str(st), "push",
                "--force", "--", str(signed), f"{sha}:refs/heads/main", env=SAN)
    fin = head_of(str(signed))
    ok = (r_ff.returncode == 0 and r_no.returncode != 0
          and r_yes.returncode == 0 and fin == sha)
    rec(f"[P6] {'PASS' if ok else 'FAIL'}: ff exit={r_ff.returncode}; "
        f"without-force exit={r_no.returncode} (must be non-zero = rejected); "
        f"with-force exit={r_yes.returncode}; final={fin} (== {sha})")
    rec()

    # ---------------- P7: source pushurl change does not matter ---------
    rec("=== P7: source remote.<n>.pushurl added AFTER resolution")
    # pretend "resolution" happened for remote 'x' -> signed3; afterwards the
    # source repo's remote gains a pushurl pointing at evil — the staging
    # push (which never consults source remotes) still goes to signed3
    run("source: add remote x -> signed3", "git", "-C", str(src), "remote",
        "add", "x", str(signed3))
    run("source: set remote.x.pushurl -> evil (AFTER resolution)",
        "git", "-C", str(src), "config", f"remote.x.pushurl", str(evil))
    (src / "i.txt").write_text("i\n")
    run("fourth commit", "git", "-C", str(src), "add", "-A")
    subprocess.run(["git", "-C", str(src), "-c", "user.name=p",
                    "-c", "user.email=p@x", "commit", "-q", "-m", "c4"],
                   capture_output=True, text=True)
    sha4 = head_of(str(src))
    r = run("staging push to SIGNED url (source pushurl now evil)",
            "git", "--git-dir", str(st), "push", "--", str(signed3),
            f"{sha4}:refs/heads/main", env=SAN)
    s3b = head_of(str(signed3))
    ok = (r.returncode == 0 and s3b == sha4
          and not _has_commit(str(evil), sha4))
    rec(f"[P7] {'PASS' if ok else 'FAIL'}: landed at signed3={s3b or '(none)'}; "
        f"evil has this sha={_has_commit(str(evil), sha4)} (must be False) — "
        f"source remote config is irrelevant to the staging push destination")
    rec()

    # ---------------- summary ----------------
    rec("=== PROBE SUMMARY (see [P*] lines above)")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    out = Path(os.environ.get("R2A1_PROBE_OUT", "/dev/stdout"))
    code = main()
    out.write_text("\n".join(RESULTS) + "\n", encoding="utf-8")
    sys.exit(code)
