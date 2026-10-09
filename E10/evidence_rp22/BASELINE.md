# E10-RP2.2 Baseline Evidence (captured BEFORE any modification)
Captured: 2026-10-09T20:25:51.222221+00:00

## Live ls-remote origin (after read-only fetch --prune)
```
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	HEAD
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	refs/heads/e10-cw1-r1-prejournal-crash
ac70eb6e1681f55970b098b98d01d4a87c9240c9	refs/heads/e10-rp-evidence-based-replanning
6d83cec11c959d3a38ad802b33faef04d77a185f	refs/heads/e10-rp1-canonical-review-gate
631f6fbb7bed2ea5411af240ea2147ad79318dfb	refs/heads/e10-rp2-canonical-auth-verification-truth
23ba93605a2ad6f8361453225eeef47002ef3eb6	refs/heads/e10-rp21-auth-depth-task-verification
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	refs/heads/main
e7fc240b7e852d122eb781c56e9c59548f6a975c	refs/heads/mission/textstats
```

## main baselines
- origin/main = `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (expected `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`)
- local main  = `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (expected `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`)

## Execution baseline (E10-RP2.1 delivery)
- commit `23ba93605a2ad6f8361453225eeef47002ef3eb6` exists as `commit`
- direct parent = `631f6fbb7bed2ea5411af240ea2147ad79318dfb` (expected `631f6fbb7bed2ea5411af240ea2147ad79318dfb`)
```
23ba93605a2ad6f8361453225eeef47002ef3eb6 631f6fbb7bed2ea5411af240ea2147ad79318dfb | E10-RP2.1: authorization path/depth + task-bound verification
631f6fbb7bed2ea5411af240ea2147ad79318dfb 6d83cec11c959d3a38ad802b33faef04d77a185f | E10-RP2: canonical execution authorization & verification truth
6d83cec11c959d3a38ad802b33faef04d77a185f ac70eb6e1681f55970b098b98d01d4a87c9240c9 | E10-RP1: canonical replanning path & review-gate integration
```

## New worktree provenance (derived from 23ba936 ONLY)
- branch: `e10-rp22-workspace-auth-clean-baseline` at `23ba93605a2ad6f8361453225eeef47002ef3eb6`
- merge-base with 23ba936 = `23ba93605a2ad6f8361453225eeef47002ef3eb6` (== 23ba936 => derived from it)

## Worktree inventory (pre-modification)
```
/home/z/my-project/repo          0a26fc7 [e10-cw1-r1-prejournal-crash]
/home/z/my-project/e10rp1_work   6d83cec [e10-rp1-canonical-review-gate]
/home/z/my-project/e10rp21_work  23ba936 [e10-rp21-auth-depth-task-verification]
/home/z/my-project/e10rp22_work  23ba936 [e10-rp22-workspace-auth-clean-baseline]
/home/z/my-project/e10rp2_work   631f6fb [e10-rp2-canonical-auth-verification-truth]
/home/z/my-project/e10rp_work    ac70eb6 [e10-rp-evidence-based-replanning]
```

## RAW porcelain per worktree (pre-evidence, exact lines)
### /home/z/my-project/repo — HEAD=0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
```
(empty — clean)
```
entries: 0

### /home/z/my-project/e10rp_work — HEAD=ac70eb6e1681f55970b098b98d01d4a87c9240c9
```
(empty — clean)
```
entries: 0

### /home/z/my-project/e10rp1_work — HEAD=6d83cec11c959d3a38ad802b33faef04d77a185f
```
(empty — clean)
```
entries: 0

### /home/z/my-project/e10rp2_work — HEAD=631f6fbb7bed2ea5411af240ea2147ad79318dfb
```
(empty — clean)
```
entries: 0

### /home/z/my-project/e10rp21_work — HEAD=23ba93605a2ad6f8361453225eeef47002ef3eb6
```
(empty — clean)
```
entries: 0

### /home/z/my-project/e10rp22_work — HEAD=23ba93605a2ad6f8361453225eeef47002ef3eb6
```
(empty — clean)
```
entries: 0

## Post-evidence-write self-observation check (explicit, not a contradiction)
After this file was written into the new worktree, a second porcelain
pass records the expected self-observation entries BY NAME:
```
(empty)
```
Any entry above must be exactly the new `E10/evidence_rp22/` evidence
directory created by this capture process itself (identified, dated,
explained — the RP2.1 ambiguity is not repeated).

## Verdict: BASELINE_OK
