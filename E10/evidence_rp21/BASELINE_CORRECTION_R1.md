# BASELINE CORRECTION ADDENDUM (R1) — epistemic status of the RP2.1
# worktree "1 dirty entry"

**Addendum date:** 2026-10-10 (E10-RP2.2-R1 §5, order: targeted correction
on baseline `6719fe371da3d7854cb612cfa64ef937c7d3d7b2`)
**Issued by:** E10-RP2.2-R1 executor
**Files NOT modified (historical, byte-for-byte preserved):**
`E10/evidence_rp21/BASELINE.md` (RP2.1 delivery, commit `23ba936`) and
`E10/evidence_rp21/BASELINE_CORRECTION.md` (RP2.2 delivery, commit
`6719fe3`).

## What this addendum records (order §5 verbatim requirements)

1. **The cause of the `1 dirty entry` in the RP2.1 worktree
   (`e10rp21_work`) is a HIGH-CONFIDENCE SELF-OBSERVATION HYPOTHESIS —
   NOT a fully proven fact.** The identification recorded in
   `BASELINE_CORRECTION.md` (the capture process's own untracked evidence
   directory `E10/evidence_rp21/`, reported by porcelain as one collapsed
   entry) rests on strong structural and timeline evidence (fresh
   worktree, mtime inside the capture window, .gitignore exclusions,
   porcelain dir-collapse mechanism reproduced at `631f6fb`), but the two
   artifacts that would make it a FACT were never retained:
   - the **raw porcelain line at RP2.1 capture time** (only the count
     "1 dirty entries" was preserved), and
   - the **original capture command order** (the RP2.1 capture script was
     not persisted, so "evidence file written before the porcelain count
     ran" is an inference from content ordering + mtime, not a recorded
     sequence).

2. **The cleanliness of `e10rp21_work` at the historical capture moment is
   NOT PROVEN.** What IS proven from the retained table: the four
   pre-existing worktrees (`repo`, `e10rp_work`, `e10rp1_work`,
   `e10rp2_work`) showed `0 dirty entries` at RP2.1 baseline, and
   `e10rp21_work` showed exactly `1 dirty entry`. Whether that single
   entry was the self-observation artifact (hypothesis) or some other
   untracked path cannot be decided from the retained evidence — the row
   as captured is neither fully explained nor fully dismissed, so the
   cleanliness of that worktree at that moment is recorded as
   **NOT PROVEN** rather than "clean" or "explained".

This addendum does not alter any prior conclusion about source-tree
integrity: no tracked file was modified in any worktree (that remains
supported by the committed trees themselves), and the RP2.2 process fix
(raw porcelain lines + pre-write capture + explicit self-observation
naming) already prevents this ambiguity class from recurring.
