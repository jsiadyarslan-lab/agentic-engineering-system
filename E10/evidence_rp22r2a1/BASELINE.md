# E10-RP2.2-R2A1 — HARD BASELINE (§1)

Order: E10-RP2.2-R2A1 — ENGINE-ISSUED RESUME CAPABILITY + PUSH DESTINATION PINNING
Base commit (mandated): `f3578b8a705c226ced276dcd3ea712de3210c171`
Previous branch: `e10-rp22r2a-approval-push-binding`
MERGE HOLD: ACTIVE. No merge to `main`. No reset/clean/stash/restore/amend/force-push.

All commands below were executed LIVE on 2026-10-10 before any modification.

## B1 — anchors

```
$ git rev-parse origin/main main HEAD
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f   <- origin/main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f   <- local main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f   <- HEAD of primary checkout (branch e10-cw1-r1-prejournal-crash, anchored at main)

$ git ls-remote origin refs/heads/main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	refs/heads/main

$ git rev-parse f3578b8a705c226ced276dcd3ea712de3210c171^{commit}
f3578b8a705c226ced276dcd3ea712de3210c171   <- exists locally

$ git ls-remote origin refs/heads/e10-rp22r2a-approval-push-binding
f3578b8a705c226ced276dcd3ea712de3210c171	refs/heads/e10-rp22r2a-approval-push-binding
```

VERIFIED: `origin/main` == local `main` == anchor `0a26fc70...` (UNCHANGED);
`f3578b8` exists locally AND remotely as the R2A branch head.

## B2 — parentage and topology

```
$ git rev-parse f3578b8a705c226ced276dcd3ea712de3210c171^
b983488290618bc4e65f360f4566f721837157cb   <- parent is EXACTLY the R2 execution commit

$ git merge-base f3578b8a705c226ced276dcd3ea712de3210c171 main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f

$ git rev-list --count main..f3578b8a705c226ced276dcd3ea712de3210c171
8
```

The 8-commit chain main..f3578b8 (verified via `git log --oneline`):
`ac70eb6` (RP) ← `6d83cec` (RP1) ← `631f6fb` (RP2) ← `23ba936` (RP2.1) ←
`6719fe3` (RP2.2) ← `0945960` (R1) ← `b983488` (R2) ← `f3578b8` (R2A).
Consistent with the worklog chain of record. `main` remains the merge-base.

## B3 — worktree states BEFORE creating the R2A1 worktree

```
$ git worktree list
/home/z/my-project/repo             0a26fc7 [e10-cw1-r1-prejournal-crash]
/home/z/my-project/e10rp1_work      6d83cec [e10-rp1-canonical-review-gate]
/home/z/my-project/e10rp21_work     23ba936 [e10-rp21-auth-depth-task-verification]
/home/z/my-project/e10rp22_work     6719fe3 [e10-rp22-workspace-auth-clean-baseline]
/home/z/my-project/e10rp22r1_work   0945960 [e10-rp22r1-path-aware-fail-closed]
/home/z/my-project/e10rp22r2_work   dbe28da [e10-rp22r2-git-sandbox-auth-audit]
/home/z/my-project/e10rp22r2a_work  f3578b8 [e10-rp22r2a-approval-push-binding]
/home/z/my-project/e10rp22r2x_work  b983488 [e10-rp22r2-git-sandbox-hardening]
/home/z/my-project/e10rp2_work      631f6fb [e10-rp2-canonical-auth-verification-truth]
/home/z/my-project/e10rp_work       ac70eb6 [e10-rp-evidence-based-replanning]
```

Porcelain per worktree (`git status --porcelain | wc -l`):

| worktree | HEAD | porcelain lines |
|---|---|---|
| /home/z/my-project/repo | 0a26fc7 | 0 |
| /home/z/my-project/e10rp_work | ac70eb6 | 0 |
| /home/z/my-project/e10rp1_work | 6d83cec | 0 |
| /home/z/my-project/e10rp2_work | 631f6fb | 0 |
| /home/z/my-project/e10rp21_work | 23ba936 | 0 |
| /home/z/my-project/e10rp22_work | 6719fe3 | 0 |
| /home/z/my-project/e10rp22r1_work | 0945960 | **2 (untracked, see below)** |
| /home/z/my-project/e10rp22r2_work | dbe28da | 0 |
| /home/z/my-project/e10rp22r2x_work | b983488 | 0 |
| /home/z/my-project/e10rp22r2a_work | f3578b8 | 0 |

### B3.1 — disclosed observation: pre-existing untracked debris in e10rp22r1_work

```
$ git -C /home/z/my-project/e10rp22r1_work status --porcelain
?? C:/
?? "C:\\Users\\jaber\\Documents\\GitHub\\agentic-engineering-system\\E6\\evidence/"
```

18 untracked files under a literal `C:/...` tree — output of the E8 human-gates
runner (`run_e8_human_gates.py`) which writes to a hardcoded Windows path that
materializes relative to CWD on Linux. File mtimes: 2026-10-10 02:37:25-26 UTC,
i.e. DURING the R2 session's regression battery (R2 commit 03:01:41 UTC, R2A
commit 03:48:05 UTC — both AFTER the debris). This is the same
"Windows-path battery debris" class documented and removed pre-commit in every
prior phase. It sits in a HISTORICAL worktree (R1, HEAD 0945960, unchanged),
is untracked-only, and touches none of the anchors (main / f3578b8 / R2A
worktree / R2 worktree). Note for the record: the R2A BASELINE.md B4 stated
"all historical worktrees clean" while only exhibiting the R2 worktree's
porcelain — that claim was inexact for e10rp22r1_work; the debris already
existed (02:37 < R2A baseline time). Classification: OBSERVED, pre-existing,
untracked, no anchor deviation. NOT removed (historical worktree; no
modification of historical state).

## B4 — R2A1 worktree + branch created FROM f3578b8 ONLY

```
$ git worktree add /home/z/my-project/e10rp22r2a1_work \
    -b e10-rp22r2a1-resume-ticket-push-pinning f3578b8a705c226ced276dcd3ea712de3210c171

$ git -C /home/z/my-project/e10rp22r2a1_work log --format='%H %P' -1
f3578b8a705c226ced276dcd3ea712de3210c171 b983488290618bc4e65f360f4566f721837157cb

$ git merge-base main e10-rp22r2a1-resume-ticket-push-pinning
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f

$ git rev-list --count f3578b8a705c226ced276dcd3ea712de3210c171..e10-rp22r2a1-resume-ticket-push-pinning
0
```

New branch `e10-rp22r2a1-resume-ticket-push-pinning` starts EXACTLY at
`f3578b8` (parent `b983488`), NOT from `main`, zero commits ahead at creation,
clean porcelain. No reset/clean/stash/restore/amend/force-push/merge used.

## B5 — verdict

- All §1 anchors VERIFIED live: main unchanged at `0a26fc70`; `f3578b8` present
  local+remote; parent exactly `b983488`; merge-base main.
- One non-anchor observation disclosed (B3.1, pre-existing untracked debris in
  the R1 historical worktree) — no stop condition triggered (anchors intact).
- PROCEEDING to §2/§3 implementation on the new branch only.
