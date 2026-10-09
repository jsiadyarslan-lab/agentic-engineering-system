# BASELINE CORRECTION — E10-RP2.1 evidence_rp21/BASELINE.md

**Correction date:** 2026-10-10 (E10-RP2.2 §1.5, order: arbitration HOLD on
commit `23ba93605a2ad6f8361453225eeef47002ef3eb6`)
**Corrected by:** E10-RP2.2 executor
**Old evidence file (NOT modified):** `E10/evidence_rp21/BASELINE.md`
**Report sentence corrected:** `E10/E10_RP21_REPORT.md` line 15 —
"All 5 worktrees clean before work"

## The contradiction being reconciled

`E10/evidence_rp21/BASELINE.md` records in its "All worktrees porcelain
(clean check)" table:

```
--- /home/z/my-project/e10rp21_work: 1 dirty entries, HEAD=631f6fbb7bed2ea5411af240ea2147ad79318dfb
```

while the other four worktrees each show `0 dirty entries`, and the RP2.1
report + worklog summarized this as "all 5 worktrees clean". The summary and
the table row contradict each other. This correction identifies the entry and
fixes the summary. The old evidence file is preserved byte-for-byte.

## Identification of the single dirty entry (what the evidence shows)

**IDENTIFIED — with high confidence — as the RP2.1 capture process's own
evidence directory, i.e. a self-observation artifact, NOT a source-tree
modification:**

1. **The worktree was brand new.** The same BASELINE.md "Worktree list
   (pre-RP2.1)" section records `/home/z/my-project/e10rp21_work` at
   `631f6fb` — freshly created for RP2.1 (its whole purpose). A fresh
   `git worktree add` produces a pristine checkout.
2. **The count line is the LAST line of the file being written into that
   very worktree.** The capture header reads `Captured: 2026-10-09T19:02:14Z`;
   the file's filesystem mtime is `2026-10-09 19:02:20 (+0000)` — the file
   was being appended to DURING capture, so it already existed as an
   untracked file when the porcelain count for `e10rp21_work` ran.
3. **Porcelain collapses an untracked directory to ONE entry.** `E10/` is a
   tracked directory at `631f6fb`; the new untracked subdir
   `E10/evidence_rp21/` (containing the in-progress BASELINE.md) is reported
   as exactly one line `?? E10/evidence_rp21/` — reproduced identically in a
   throwaway worktree at `631f6fb` during this RP2.2 investigation
   (mechanism proof: pristine tree = 0 entries; after writing one untracked
   file inside a new `E10/evidence_rp21/` subdir = exactly
   `?? E10/evidence_rp21/`, 1 entry; throwaway worktree removed after).
4. **`.gitignore` excludes the plausible noise classes** (`__pycache__/`,
   `*.pyc`, `*.log`, `*.db`, `.venv/`, …), so ordinary test execution debris
   would not appear in porcelain at all — the 1 entry is not pycache noise.
5. **Nothing else was ever left behind.** The only content ever added under
   that path is the three RP2.1 evidence files, committed 39 minutes later
   in `23ba936` (`git log --diff-filter=A`: BASELINE.md added in 23ba936 at
   2026-10-09 19:41:57 +0000). Current porcelain of `e10rp21_work` = 0
   entries.

## Corrected statement (supersedes the report sentence)

- The **four pre-existing worktrees** (`repo`, `e10rp_work`, `e10rp1_work`,
  `e10rp2_work`) were clean at RP2.1 baseline — **VERIFIED** (0 entries
  each, recorded in the same table).
- The **newly created** `e10rp21_work` had **exactly one untracked entry**,
  identified with high confidence as the RP2.1 evidence directory itself
  (`?? E10/evidence_rp21/`) written by the capture process into its own
  worktree — a self-observation artifact of the capture method, not a
  modification of any source file and not present in any original tree.
- "All 5 worktrees clean" was therefore imprecise wording: the correct claim
  is "all four original worktrees clean; the new execution worktree's single
  untracked entry is the baseline evidence file being written by the capture
  process itself."

## What remains NOT PROVEN (honest limits of retained evidence)

- The **raw porcelain line** at RP2.1 capture time was not retained (only
  the count); the identification above rests on structural + timeline
  evidence, not on the retained line itself.
- The RP2.1 capture **script/command sequence was not persisted**, so the
  write order (evidence file before porcelain) is inferred from the file's
  own content ordering + mtime, not proven from a script artifact.

## Process fix applied by E10-RP2.2 (so this class of ambiguity cannot recur)

`E10/evidence_rp22/BASELINE.md` (this delivery) records porcelain **raw
lines**, captures all git state **before** writing the evidence file, and
records a **second post-write pass naming the self-observation entries
explicitly**.
