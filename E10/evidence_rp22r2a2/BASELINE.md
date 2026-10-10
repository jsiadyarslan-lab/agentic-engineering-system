# E10-RP2.2-R2A2 — §1 HARD BASELINE (live, pre-modification)

Recorded: 2026-10-10T13:49:45Z — worktree e10rp22r2a2_work created from 74c8ec1 ONLY, clean (0 porcelain lines at creation).

## B1 — main anchors (live)
```
origin/main   = 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
local main    = 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
ls-remote origin refs/heads/main -> 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
=> main UNCHANGED (anchor intact; no divergence local<->remote)
```

## B2 — designated base commit 74c8ec1 (local + remote)
```
rev-parse 74c8ec12122df759bec5688f2980e181ea8976bb -> 74c8ec12122df759bec5688f2980e181ea8976bb (exists locally)
ls-remote origin refs/heads/e10-rp22r2a1-resume-ticket-push-pinning -> 74c8ec12122df759bec5688f2980e181ea8976bb (exists remotely)
parent of 74c8ec1 = f3578b8a705c226ced276dcd3ea712de3210c171 (== R2A head; exactly as ordered)
merge-base(74c8ec1, f3578b8) = f3578b8  (74c8ec1 is exactly 1 commit ahead of the R2A base)
```

## B3 — remote branch census (live)
  0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	HEAD
  0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	refs/heads/e10-cw1-r1-prejournal-crash
  ac70eb6e1681f55970b098b98d01d4a87c9240c9	refs/heads/e10-rp-evidence-based-replanning
  6d83cec11c959d3a38ad802b33faef04d77a185f	refs/heads/e10-rp1-canonical-review-gate
  631f6fbb7bed2ea5411af240ea2147ad79318dfb	refs/heads/e10-rp2-canonical-auth-verification-truth
  23ba93605a2ad6f8361453225eeef47002ef3eb6	refs/heads/e10-rp21-auth-depth-task-verification
  6719fe371da3d7854cb612cfa64ef937c7d3d7b2	refs/heads/e10-rp22-workspace-auth-clean-baseline
  0945960427e833522789903e87a64b73c207bccd	refs/heads/e10-rp22r1-path-aware-fail-closed
  dbe28da9998c022e08c6324c2344b30e60bba846	refs/heads/e10-rp22r2-git-sandbox-auth-audit
  b983488290618bc4e65f360f4566f721837157cb	refs/heads/e10-rp22r2-git-sandbox-hardening
  f3578b8a705c226ced276dcd3ea712de3210c171	refs/heads/e10-rp22r2a-approval-push-binding
  74c8ec12122df759bec5688f2980e181ea8976bb	refs/heads/e10-rp22r2a1-resume-ticket-push-pinning
  0a26fc70ce13e69932db7fe54c810fcbf0f99d3f	refs/heads/main
  e7fc240b7e852d122eb781c56e9c59548f6a975c	refs/heads/mission/textstats

## B4 — worktree states before modification (live)
  /home/z/my-project/repo              0a26fc7 [e10-cw1-r1-prejournal-crash]
  /home/z/my-project/e10rp1_work       6d83cec [e10-rp1-canonical-review-gate]
  /home/z/my-project/e10rp21_work      23ba936 [e10-rp21-auth-depth-task-verification]
  /home/z/my-project/e10rp22_work      6719fe3 [e10-rp22-workspace-auth-clean-baseline]
  /home/z/my-project/e10rp22r1_work    0945960 [e10-rp22r1-path-aware-fail-closed]
  /home/z/my-project/e10rp22r2_work    dbe28da [e10-rp22r2-git-sandbox-auth-audit]
  /home/z/my-project/e10rp22r2a1_work  74c8ec1 [e10-rp22r2a1-resume-ticket-push-pinning]
  /home/z/my-project/e10rp22r2a2_work  74c8ec1 [e10-rp22r2a2-sanitized-git-environment]
  /home/z/my-project/e10rp22r2a_work   f3578b8 [e10-rp22r2a-approval-push-binding]
  /home/z/my-project/e10rp22r2x_work   b983488 [e10-rp22r2-git-sandbox-hardening]
  /home/z/my-project/e10rp2_work       631f6fb [e10-rp2-canonical-auth-verification-truth]
  /home/z/my-project/e10rp_work        ac70eb6 [e10-rp-evidence-based-replanning]

  e10rp1_work porcelain_lines=0
  e10rp21_work porcelain_lines=0
  e10rp22_work porcelain_lines=0
  e10rp22r1_work porcelain_lines=2
  e10rp22r2_work porcelain_lines=0
  e10rp22r2a1_work porcelain_lines=0
  e10rp22r2a2_work porcelain_lines=1
  e10rp22r2a_work porcelain_lines=0
  e10rp22r2x_work porcelain_lines=0
  e10rp2_work porcelain_lines=0
  e10rp_work porcelain_lines=0

  NOTE (disclosed, unchanged from R2A1): e10rp22r1_work carries 2 lines of pre-existing
  untracked Windows-path debris in the HISTORICAL R1 worktree — untracked-only,
  anchors untouched, NOT removed (historical worktree; same disclosure as R2A1 BASELINE B4).

## B5 — new worktree derivation proof
```
git worktree add /home/z/my-project/e10rp22r2a2_work -b e10-rp22r2a2-sanitized-git-environment 74c8ec12122df759bec5688f2980e181ea8976bb
=> HEAD 74c8ec1, 0 commits ahead of 74c8ec1 at creation, porcelain=0
```

## Rules honored: no reset/clean/stash/restore/amend/force-push; no historical-evidence
modification; no merge of any branch; main untouched.
