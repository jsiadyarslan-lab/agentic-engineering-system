# E10-RP2.2-R1 — HARD BASELINE EVIDENCE (§1)

**Captured:** 2026-10-10 (session start, BEFORE any modification of the
execution tree — per the E10-RP2.2 process fix: git state first, raw
porcelain lines, self-observation entries named explicitly)
**Executor:** E10-RP2.2-R1 (order: fail-closed path-aware validator
enforcement)
**Execution baseline (per order):**
`6719fe371da3d7854cb612cfa64ef937c7d3d7b2`

## 1. Remote references (live `git fetch origin` + `git ls-remote origin`)

```
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	HEAD
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	refs/heads/e10-cw1-r1-prejournal-crash
ac70eb6e1681f55970b098b98d01d4a87c9240c9	refs/heads/e10-rp-evidence-based-replanning
6d83cec11c959d3a38ad802b33faef04d77a185f	refs/heads/e10-rp1-canonical-review-gate
631f6fbb7bed2ea5411af240ea2147ad79318dfb	refs/heads/e10-rp2-canonical-auth-verification-truth
23ba93605a2ad6f8361453225eeef47002ef3eb6	refs/heads/e10-rp21-auth-depth-task-verification
6719fe371da3d7854cb612cfa64ef937c7d3d7b2	refs/heads/e10-rp22-workspace-auth-clean-baseline
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	refs/heads/main
e7fc240b7e852d122eb781c56e9c59548f6a975c	refs/heads/mission/textstats
```

- `origin/main` == `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` — EXACT
  (order §1.3 requirement: main unchanged) — local `main` identical.
- The RP2.2 delivery branch (remote) == `6719fe3` == the order's baseline
  commit. All earlier phase branches unchanged at their certified values.

## 2. Baseline commit identity + parent (before creating anything)

```
$ git log --format='%H%nparent: %P%nsubject: %s' -1 6719fe371da3d7854cb612cfa64ef937c7d3d7b2
6719fe371da3d7854cb612cfa64ef937c7d3d7b2
parent: 23ba93605a2ad6f8361453225eeef47002ef3eb6
subject: E10-RP2.2: complete workspace tool authorization + clean-baseline reconciliation

$ git merge-base --is-ancestor 23ba93605a2ad6f8361453225eeef47002ef3eb6 6719fe3 && echo TRUE
TRUE                       # 23ba936 IS the direct parent — history intact
$ git rev-list --count 0a26fc70..6719fe3
5                          # exactly the five certified phase commits
```

## 3. Worktree states as-found (raw porcelain, before any modification)

`git worktree list` (as found):

```
/home/z/my-project/repo            0a26fc7 [e10-cw1-r1-prejournal-crash]
/home/z/my-project/e10rp1_work   6d83cec [e10-rp1-canonical-review-gate]
/home/z/my-project/e10rp21_work  23ba936 [e10-rp21-auth-depth-task-verification]
/home/z/my-project/e10rp22_work  6719fe3 [e10-rp22-workspace-auth-clean-baseline]
/home/z/my-project/e10rp2_work   631f6fb [e10-rp2-canonical-auth-verification-truth]
/home/z/my-project/e10rp_work    ac70eb6 [e10-rp-evidence-based-replanning]
```

Raw porcelain (`git status --porcelain`) per tree — **ALL SIX TREES EMPTY
(0 entries each; empty porcelain output, no lines to quote)**:

| Worktree | Branch | HEAD | Porcelain entries |
|---|---|---|---|
| `/home/z/my-project/repo` | e10-cw1-r1-prejournal-crash | 0a26fc7 | **0** |
| `/home/z/my-project/e10rp_work` | e10-rp-evidence-based-replanning | ac70eb6 | **0** |
| `/home/z/my-project/e10rp1_work` | e10-rp1-canonical-review-gate | 6d83cec | **0** |
| `/home/z/my-project/e10rp2_work` | e10-rp2-canonical-auth-verification-truth | 631f6fb | **0** |
| `/home/z/my-project/e10rp21_work` | e10-rp21-auth-depth-task-verification | 23ba936 | **0** |
| `/home/z/my-project/e10rp22_work` | e10-rp22-workspace-auth-clean-baseline | 6719fe3 | **0** |

Note (honest, environmental): the main repo's `core.filemode=false` is set
(the historical Windows-origin mode-noise class — as also observed clean
in the RP2.2 baseline capture).

## 4. New execution worktree (order §1.1)

```
$ git worktree add /home/z/my-project/e10rp22r1_work -b e10-rp22r1-path-aware-fail-closed 6719fe371da3d7854cb612cfa64ef937c7d3d7b2
Preparing worktree (new branch 'e10-rp22r1-path-aware-fail-closed')
HEAD is now at 6719fe3 E10-RP2.2: complete workspace tool authorization + clean-baseline reconciliation
exit=0
```

Post-creation verification:
- HEAD == `6719fe371da3d7854cb612cfa64ef937c7d3d7b2` — EXACT
- branch == `e10-rp22r1-path-aware-fail-closed`
- parent == `23ba93605a2ad6f8361453225eeef47002ef3eb6` — EXACT
- porcelain == 0 entries (pristine)
- `git merge-base HEAD 6719fe3` == `6719fe3` — derived from the baseline
  commit ONLY (order §1.1).

## 5. Stop conditions

NONE. Baseline commit present with exact parent, main unchanged at
`0a26fc70`, all trees clean, no history anomaly. Work proceeded under the
order's constraints: no `reset`/`clean`/`stash`/`restore` anywhere, no
touch of the original worktrees (re-verified post-work in §6 of the
report), no merge, no push to `main`.
