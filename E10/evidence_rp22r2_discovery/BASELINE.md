# E10-RP2.2-R2-DISCOVERY — §2 HARD BASELINE (live capture)

Captured: 2026-10-09T22:29:57Z — every block below is the RAW output of the stated command, re-runnable in this worktree.

## B1 — origin/main anchor
```
$ git ls-remote origin refs/heads/main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	refs/heads/main
```

## B2 — target commit exists and is the branch head (local + remote)
```
$ git rev-parse 0945960427e833522789903e87a64b73c207bccd
0945960427e833522789903e87a64b73c207bccd
$ git rev-parse e10-rp22r1-path-aware-fail-closed
0945960427e833522789903e87a64b73c207bccd
$ git ls-remote origin refs/heads/e10-rp22r1-path-aware-fail-closed
0945960427e833522789903e87a64b73c207bccd	refs/heads/e10-rp22r1-path-aware-fail-closed
```

## B3 — parent + merge-base (R2 worktree derivation proof)
```
$ git rev-parse HEAD HEAD~1  &&  git merge-base HEAD 0945960
0945960427e833522789903e87a64b73c207bccd
6719fe371da3d7854cb612cfa64ef937c7d3d7b2
0945960427e833522789903e87a64b73c207bccd
$ git branch --show-current
e10-rp22r2-git-sandbox-auth-audit
```

## B4 — worktree inventory + porcelain status of EVERY worktree (pre-modification)
```
/home/z/my-project/repo            0a26fc7 [e10-cw1-r1-prejournal-crash]
/home/z/my-project/e10rp1_work     6d83cec [e10-rp1-canonical-review-gate]
/home/z/my-project/e10rp21_work    23ba936 [e10-rp21-auth-depth-task-verification]
/home/z/my-project/e10rp22_work    6719fe3 [e10-rp22-workspace-auth-clean-baseline]
/home/z/my-project/e10rp22r1_work  0945960 [e10-rp22r1-path-aware-fail-closed]
/home/z/my-project/e10rp22r2_work  0945960 [e10-rp22r2-git-sandbox-auth-audit]
/home/z/my-project/e10rp2_work     631f6fb [e10-rp2-canonical-auth-verification-truth]
/home/z/my-project/e10rp_work      ac70eb6 [e10-rp-evidence-based-replanning]

-- /home/z/my-project/repo
HEAD: 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
porcelain lines: 0
-- /home/z/my-project/e10rp_work
HEAD: ac70eb6e1681f55970b098b98d01d4a87c9240c9
porcelain lines: 0
-- /home/z/my-project/e10rp1_work
HEAD: 6d83cec11c959d3a38ad802b33faef04d77a185f
porcelain lines: 0
-- /home/z/my-project/e10rp21_work
HEAD: 23ba93605a2ad6f8361453225eeef47002ef3eb6
porcelain lines: 0
-- /home/z/my-project/e10rp2_work
HEAD: 631f6fbb7bed2ea5411af240ea2147ad79318dfb
porcelain lines: 0
-- /home/z/my-project/e10rp22_work
HEAD: 6719fe371da3d7854cb612cfa64ef937c7d3d7b2
porcelain lines: 0
-- /home/z/my-project/e10rp22r1_work
HEAD: 0945960427e833522789903e87a64b73c207bccd
porcelain lines: 0
-- /home/z/my-project/e10rp22r2_work
HEAD: 0945960427e833522789903e87a64b73c207bccd
porcelain lines: 4
```

## B5 — this discovery worktree status at capture time
```
4
0945960 E10-RP2.2-R1: fail-closed path-aware validator enforcement
6719fe3 E10-RP2.2: complete workspace tool authorization + clean-baseline reconciliation
23ba936 E10-RP2.1: authorization path/depth + task-bound verification
```

## B6 — note on the 4 porcelain lines in e10rp22r2_work (epistemic honesty)

The R2 worktree was created CLEAN from `0945960` (verified at creation:
`git status --porcelain` = 0 lines, recorded in the session log before any
file was written). The 4 lines captured above in B4/B5 are the R2 DISCOVERY
DELIVERABLES THEMSELVES (probe scripts + this evidence directory) — the only
class of file this phase is permitted to add (order R2 §5). No production
source file is modified. Historical worktrees (repo, e10rp*_work except
e10rp22r2_work) are all CLEAN (0 lines) and were never touched. `main`
remains `0a26fc70`; no merge; no reset/clean/stash/restore anywhere.
