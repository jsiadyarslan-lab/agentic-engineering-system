# E10-RP2.2-R2 EXECUTION — §1 HARD BASELINE (live capture)

Captured live at worktree creation, BEFORE any modification. Every block is
the raw output of the stated command.

## B1 — origin/main anchor (order §1.3)
```
$ git ls-remote origin refs/heads/main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f        refs/heads/main
```

## B2 — designated baseline commit exists and is the R1 branch head (local + remote)
```
$ git rev-parse 0945960427e833522789903e87a64b73c207bccd
0945960427e833522789903e87a64b73c207bccd
$ git rev-parse e10-rp22r1-path-aware-fail-closed
0945960427e833522789903e87a64b73c207bccd
$ git ls-remote origin refs/heads/e10-rp22r1-path-aware-fail-closed
0945960427e833522789903e87a64b73c207bccd        refs/heads/e10-rp22r1-path-aware-fail-closed
$ git rev-parse main
0a26fc70ce13e69932db7fe54c810fcbf0f99d3f
```

## B3 — parent of the designated commit
```
$ git rev-parse 0945960427e833522789903e87a64b73c207bccd^
6719fe371da3d7854cb612cfa64ef937c7d3d7b2
```

## B4 — all worktree porcelain states BEFORE creating the execution worktree
```
/home/z/my-project/repo                       HEAD=0a26fc7 porcelain=0
/home/z/my-project/e10rp1_work                HEAD=6d83cec porcelain=0
/home/z/my-project/e10rp21_work               HEAD=23ba936 porcelain=0
/home/z/my-project/e10rp22_work               HEAD=6719fe3 porcelain=0
/home/z/my-project/e10rp22r1_work             HEAD=0945960 porcelain=0
/home/z/my-project/e10rp22r2_work             HEAD=dbe28da porcelain=0
/home/z/my-project/e10rp2_work                HEAD=631f6fb porcelain=0
/home/z/my-project/e10rp_work                 HEAD=ac70eb6 porcelain=0
```

## B5 — execution worktree creation (order §1.1: from 0945960 ONLY, NOT the discovery branch)
```
$ git worktree add -b e10-rp22r2-git-sandbox-hardening \
    /home/z/my-project/e10rp22r2x_work 0945960427e833522789903e87a64b73c207bccd
HEAD is now at 0945960 E10-RP2.2-R1: fail-closed path-aware validator enforcement

$ git rev-parse HEAD HEAD~1
0945960427e833522789903e87a64b73c207bccd
6719fe371da3d7854cb612cfa64ef937c7d3d7b2
$ git branch --show-current
e10-rp22r2-git-sandbox-hardening
$ git merge-base HEAD 0945960427e833522789903e87a64b73c207bccd
0945960427e833522789903e87a64b73c207bccd
$ git rev-list --count 0945960427e833522789903e87a64b73c207bccd..HEAD
0
$ git status --porcelain | wc -l
0
```

No reset / clean / stash / restore / force-push used. Historical worktrees and
evidence untouched. main remains 0a26fc70. No merge.
