# E10-RP2.2-R2A — HARD BASELINE (order §1)

All commands executed live in the R2A session BEFORE any modification.
Throwaway trees for probes/tests only; NO reset/clean/stash/restore; NO
amend or force-push of any history; NO merge of any branch.

## B1 — origin/main anchor

```
$ git fetch origin --prune
$ git rev-parse origin/main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
$ git rev-parse main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
```

`main` (local) == `origin/main` == the certified anchor `0a26fc70`. UNCHANGED.

## B2 — the designated base commit b983488 exists locally AND remotely

```
$ git cat-file -t b983488290618bc4e65f360f4566f721837157cb
commit
$ git branch -a --contains b983488290618bc4e65f360f4566f721837157cb
+ e10-rp22r2-git-sandbox-hardening
  remotes/origin/e10-rp22r2-git-sandbox-hardening
```

## B3 — branch derivation is EXACTLY b983488 (not main, not the discovery branch)

```
$ git log --format='%H %P' -1 e10-rp22r2-git-sandbox-hardening
b983488290618bc4e65f360f4566f721837157cb 0945960427e833522789903e87a64b73c207bccd
$ git rev-list --count 0945960..e10-rp22r2-git-sandbox-hardening   # 1
$ git rev-list --count e10-rp22r2-git-sandbox-hardening..0945960    # 0
$ git merge-base main e10-rp22r2-git-sandbox-hardening
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
```

The R2 branch is exactly ONE commit ahead of `0945960`, zero behind, and
its merge-base with `main` is the main anchor itself.

## B4 — worktree states BEFORE creating the R2A worktree

```
$ git worktree list
/home/z/my-project/repo             0a26fc7 [e10-cw1-r1-prejournal-crash]
/home/z/my-project/e10rp1_work      6d83cec [e10-rp1-canonical-review-gate]
/home/z/my-project/e10rp21_work     23ba936 [e10-rp21-auth-depth-task-verification]
/home/z/my-project/e10rp22_work     6719fe3 [e10-rp22-workspace-auth-clean-baseline]
/home/z/my-project/e10rp22r1_work   0945960 [e10-rp22r1-path-aware-fail-closed]
/home/z/my-project/e10rp22r2_work   dbe28da [e10-rp22r2-git-sandbox-auth-audit]
/home/z/my-project/e10rp22r2x_work  b983488 [e10-rp22r2-git-sandbox-hardening]
/home/z/my-project/e10rp2_work      631f6fb [e10-rp2-canonical-auth-verification-truth]
/home/z/my-project/e10rp_work       ac70eb6 [e10-rp-evidence-based-replanning]
```

All historical worktrees clean (`git status --porcelain` empty for the R2
worktree at b983488: `## e10-rp22r2-git-sandbox-hardening` only).

## B5 — R2A worktree + branch created FROM b983488 ONLY

```
$ git worktree add /home/z/my-project/e10rp22r2a_work \
    -b e10-rp22r2a-approval-push-binding b983488290618bc4e65f360f4566f721837157cb
$ git -C /home/z/my-project/e10rp22r2a_work log --format='%H %P' -1
b983488290618bc4e65f360f4566f721837157cb 0945960427e833522789903e87a64b73c207bccd
$ git merge-base main e10-rp22r2a-approval-push-binding
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
```

The new branch `e10-rp22r2a-approval-push-binding` starts EXACTLY at
`b983488` (parent `0945960`), NOT from `main` and NOT from the discovery
branch (`dbe28da`). Worktree clean at creation.

## B6 — no destructive history operations

No `reset` / `clean` / `stash` / `restore` / `amend` / force-push was
used at any point in this phase; the two-state baseline battery ran in a
THROWAWAY detached worktree at b983488 which was REMOVED after the run
(`git worktree remove`). Historical evidence directories untouched (new
evidence added only under `E10/evidence_rp22r2a/`).
