# E10-RP2.2-R2A1 — DELIVERY REPORT
## ENGINE-ISSUED RESUME CAPABILITY + PUSH DESTINATION PINNING

Order: E10-RP2.2-R2A1 (AUTHORIZED WITH AMENDMENTS)
Base commit: `f3578b8a705c226ced276dcd3ea712de3210c171` (R2A)
Branch: `e10-rp22r2a1-resume-ticket-push-pinning`
MERGE HOLD: ACTIVE — no merge to `main` performed or attempted.

---

## 1 — COMMIT / BRANCH / PARENT + DERIVATION PROOF

§1 HARD BASELINE (live, before any modification — raw evidence in
`E10/evidence_rp22r2a1/BASELINE.md`):

* `origin/main` == local `main` == `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`
  (UNCHANGED; verified via `git ls-remote` live).
* `f3578b8a705c226ced276dcd3ea712de3210c171` exists LOCALLY and REMOTELY
  as the head of `e10-rp22r2a-approval-push-binding`; its parent is
  EXACTLY `b983488290618bc4e65f360f4566f721837157cb`; merge-base with
  `main` is `0a26fc70`.
* New worktree `/home/z/my-project/e10rp22r2a1_work` + branch
  `e10-rp22r2a1-resume-ticket-push-pinning` created FROM `f3578b8` ONLY
  (`git worktree add -b ... f3578b8...`; `rev-list --count
  f3578b8..branch` == 0 at creation; clean porcelain).
* No `reset`/`clean`/`stash`/`restore`/`amend`/force-push/merge used
  anywhere in this phase; no historical evidence path modified; all R2A1
  evidence lives under `E10/evidence_rp22r2a1/` (independent path).
* One non-anchor observation disclosed (BASELINE.md B3.1): 18 untracked
  Windows-path debris files in the HISTORICAL R1 worktree
  (`e10rp22r1_work`), mtimes 2026-10-10 02:37 UTC — during the R2 session's
  battery, i.e. pre-existing. Untracked-only; no anchor touched; NOT
  removed (historical worktree, no modification of historical state). The
  R2A BASELINE.md B4 "all historical worktrees clean" claim was inexact
  for that worktree — corrected on the record here.

The delivery commit's parent is EXACTLY `f3578b8` (see §8 command log;
`git log --format='%H %P' -1` recorded in the commit message).

---

## 2 — F1: ENGINE-ISSUED ONE-SHOT RESUME TICKET (§2)

### 2.1 The closed hole

R2A stored `attempt_id`/`agent_id` in the approval record but they were
NOT match conditions: any call presenting the same
mission/run/task/tool/input-digest identity consumed the approval. That
proved an *identity match*, not that the consuming call was **the
engine-designated continuation of the paused operation**.

### 2.2 The new contract (implemented)

* `ResumeTicket` (execution.py) — engine-internal, one-shot:
  `armed → designated → consumed` (+ terminal `expired`). Bound to the
  gate id, the full operation identity (mission/run/task/tool + canonical
  input digest) and the CREATING attempt/agent lineage.
* **Minting** — ONLY `decide_human_gate`'s approve branch mints
  (`_mint_resume_ticket`), at approval time, for the gate's v2 operation
  record. No agent-reachable minting surface exists (input schemas have
  no ticket/resume/continuation field — asserted in R2A1-L1).
* **Designation** — ONLY the engine's resume path designates
  (`_designate_resume_continuation`): `MissionController.resume_approved_task`
  (the production resume path, owner/operator-driven) pre-mints the
  continuation attempt id, designates the ticket with it, re-arms the
  task through the engine's own validated FAILED→READY transition
  (`recover_failed_task` — no test-side state surgery), and relaunches
  through the normal execution path. The designated attempt id is
  injected into the launch (`_designated_continuations` one-shot pop →
  `_execute_single_task(continuation_attempt_id=...)`).
* **Consumption** — `_check_human_gate`'s APPROVED+UNCONSUMED branch now
  delegates to `_consume_resume_ticket_or_raise`, which verifies: ticket
  exists in the ENGINE-INTERNAL registry (lookup by operation key — an
  agent-supplied id is never consulted); ticket binds THIS gate and the
  FULL current identity (transfer/forgery rejected); not expired; not
  consumed; state == `designated`; current attempt == the designated
  continuation attempt; agent unchanged. ALL checks pass → synchronous
  atomic flip to `consumed` (no await between verification and flip).
  ANY failure → `PermissionError` BEFORE any Action record exists
  (gate runs pre-Action), WITHOUT consuming the ticket or burning the
  approval.
* `attempt_id` may change on the sanctioned resume (the engine mints a
  fresh id per continuation — the designated id IS the fresh id); an
  identity match alone never proves continuation (§2.2.8 honored).
* `agent_id` change → refusal (no reassignment mechanism authorized;
  §2.2.4). Cross-run (checkpoint child-run) resumes are different
  operation identities → own gates (mandated §2.3 case 6, proven E4).
* Legacy records (no v2 operation record) mint nothing → still authorize
  nothing.

### 2.3 Mandated tests (all through the REAL MissionController path —
`define_mission → execute_run → pause-storm → decide_human_gate →
resume_approved_task`; zero test-side task-state/retry-counter surgery;
layer legs clearly separated)

| # | Test (R2A1-*) | Order case | Result |
|---|---|---|---|
| E1 | engine_designated_resume_e2e | 1/2/3/4/8 | PASSED |
| E2 | positive_real_push_side_effect_e2e | 2 (positive) + §3.3 | PASSED |
| E3 | expired_ticket_resume_refused_e2e | 5 (expired) | PASSED |
| E4 | cross_run_child_gets_own_gate_e2e | 6 | PASSED |
| E5 | continuation_with_different_input_new_gate_e2e | 6 | PASSED |
| E6 | real_bridge_git_push_stays_rejected_e2e | §4.2 | PASSED |
| L1 | agent_supplied_proof_authorizes_nothing | §2.2.5 (LAYER) | PASSED |
| L2 | transferred_ticket_rejected | 5 (transfer, LAYER) | PASSED |
| L3 | wrong_attempt_and_agent_rejected | §2.2.3/§2.2.4 (LAYER) | PASSED |
| L4 | no_trace_on_pre_execution_refusals | §2.2.7 (LAYER) | PASSED |

E1 proves on the live controller: the strongest available independent
matching call — the engine's own GENERIC recovery relaunch
(`recover_failed_task` + `execute_run`) — is REFUSED ("not yet
designated"), consumes NOTHING, creates ZERO tool Actions, and the
approval stays armed for the designated continuation; then
`resume_approved_task` consumes exactly once via the designated attempt
(consumption record binds ticket id + consuming lineage); a further
resume is refused fail-closed (new approval required).
E2 proves the POSITIVE leg end-to-end: the designated continuation of an
approved git_push gate EXECUTES the real push (lands in the approved
bare at the approved commit) and the task reaches COMPLETED.
E3 proves expiry: TTL passed → designation refused, zero consumption,
zero Actions, terminal (later resumes also refused).
L1–L4 are LAYER legs (synthetic ExecutionContexts) proving the registry
semantics: forged/foreign tickets rejected by identity binding; ticket
transfer between operations rejected; non-designated attempt and agent
change refused (approval reserved); the full refusal family creates zero
Actions. Disclosed as layer tests per order §2.3 (the scheduler
integration is proven E2E in E1–E6).

---

## 3 — F2: PINNED PUSH DESTINATION (§3)

### 3.1 The closed hole

R2A resolved the canonical push URL and compared it with the signed one,
but the final push command still used the remote NAME — git re-resolved
the name at execution, and nothing structurally excluded a destination
config change between verification and use.

**Probe-proven attack** (`E10/evidence_rp22r2a1/F2_DESIGN_PROBES.txt`,
git 2.47.3, P3): a local `url.<base>.insteadOf` rule rewrites even an
EXPLICIT url passed to `git push <url> ...` FROM THE SOURCE REPO — the
victim's push to the "resolved" target landed at the attacker's bare.
So "resolve then push the URL from the source repo" is NOT a structural
fix. P1/P2/P4/P5/P6/P7 prove the design that IS:

### 3.2 The implemented design (`eoe.push_engine.staged_push`)

The push command itself uses THE SIGNED CANONICAL URL — never the remote
name — from an ENGINE-OWNED throwaway bare STAGING repo:

* the staging repo's ONLY link to the source is
  `objects/info/alternates` (read-only object access) — the source
  repo's config is NEVER read by the push (no `remote.<name>`
  re-resolution, no insteadOf/pushInsteadOf rewriting: P4/P7);
* `GIT_CONFIG_NOSYSTEM=1` + `GIT_CONFIG_GLOBAL=/dev/null` suppress
  system+global rewrite sources (P5);
* the staging repo's config contains only what `git init --bare` wrote;
  it lives in a 0700 `mkdtemp` dir, removed after the push;
* the approved commit is proven present (staging view, `cat-file -e`)
  BEFORE any effect;
* refspec = `<approved_sha>:refs/heads/<branch>` — the commit that lands
  is EXACTLY the commit the owner signed (branch structurally validated
  before this point; handler still constructs the refspec);
* `--` terminates option parsing; `--force` only from the explicit flag
  AND a force-scoped signed approval (destination enforces it: P6);
* the handler (`execution.py` git_push) calls `staged_push` with the
  SAME `canonical_push_url` it verified against the approval, and the
  result record (`GitPushOutput.push_url` + new `push_argv`) is
  structurally the destination the push argv itself used — a record can
  never announce a signed address the actual push did not go to (§3.3).
* Multi-destination refusal, unresolvable/unproven destinations,
  option-shaped remote/branch, branch/sha/force scope, URL-changed-after-
  approval, insteadOf/pushInsteadOf effective-destination binding — ALL
  kept from R2A (matrix rows F1–F10 there re-run green; R2A1-F3 re-proves
  multi-pushurl).

### 3.3 Mandated tests

| # | Test (R2A1-*) | Order case | Result |
|---|---|---|---|
| F1 | between_window_url_change_cannot_reroute | §3.3 MANDATORY | PASSED |
| F2 | prewrite_rule_cannot_reroute | §3.3 (armed-at-signing) | PASSED |
| F3 | multi_destination_rejected_before_push | §3.3 kept | PASSED |
| F4 | force_only_with_force_scoped_approval | §3.3 kept (P6) | PASSED |
| F5 | result_record_never_lies | §3.3 | PASSED |

**The deterministic between-window test (F1)**: a wrapped
`resolve_push_destination` fires the mutation EXACTLY between the
handler's own resolution+verification and `staged_push` — arming BOTH
attack vectors at once (`remote.<name>.pushurl → attacker` AND
`url.<attacker>.insteadOf = approved`). Proven outcomes: the push lands
ONLY at the signed destination; the attacker bare does NOT receive the
commit (object-level check); the result record's `push_url` is the
signed destination and `push_argv` proves the command itself used it
(never the remote name); the source repo's config change verifiably
happened (the attack was live). F2 plants the rewrite BEFORE signing —
the naive approval (un-rewritten URL) does not match the effective
destination → refused fail-closed before any effect. F4 proves force
semantics with real non-ff rejections: non-force approval → destination
rejects the rewind (no `--force` in argv); force-scoped approval →
rewind lands, `--force` in argv.

---

## 4 — OWNER CHANNEL & PRIVILEGES (§4) — NO EXPANSION

* NO `admin` grants anywhere; no grant expansion; no EOE bridge changes.
* `git_push` remains REJECTED through the REAL EOE chain — re-proven
  E2E in R2A1-E6 through the real MissionController + real bridge
  (zero gate, zero ticket, zero Actions, resume unavailable).
* No parallel execution paths or `sandbox_execute` re-enabled.
* Layered tests using scaffold validators are labeled inline (E2, F1–F5
  legs; `_permissive_path_aware` / `_permissive` disclose the seam);
  `OwnerApprovalService`/`PushApprovalRegistry` legs are layer tests,
  not production-push proofs.
* The production owner channel binding (registry issuance ↔ real owner
  console in production) remains NOT PROVEN — `git_push` stays
  fail-closed disabled unless a registry is explicitly wired, and the
  real chain never wires one (G-legs of the R2A matrix re-run green).

---

## 5 — REGRESSIONS (§5)

Full battery: `E10/evidence_rp22r2a1/REGRESSIONS_BRANCH.txt` (unified
command/stdout-tail/exit-code records, the same format as every prior
phase).

**GREEN rows (exit 0)** — 14:
R2A1 matrix 15/15 (new), R2A matrix 25/25, R2 matrix 19/19, R1 6/6,
RP2.2 22/22, RP2.1 24/24, RP2 22/22, RP2 session 9/9, RP1 16/16, RP 23/23,
CW1 32/32, CW1-R1 31/31, E9-R PASS, E8 negative gates PASS.

**NOT GREEN rows (exit 1)** — 6, ALL identical to the designated
baseline (DECLARED not green; not new regressions):
vs001+vs002+vs003+vs004+e32e, e3+e4, e6, e33+e32f, e35, e37.
The battery as a whole is therefore NOT described as green.

**Two-state comparison** (this branch vs `f3578b8`, same battery script,
`R2A1_INCLUDE_NEW_MATRIX=0` at a throwaway worktree removed after the
run): `E10/evidence_rp22r2a1/TWO_STATE_BASELINE.json` — 19/19 shared rows
IDENTICAL exit codes AND failure-name sets → `OVERALL_TWO_STATE = 0`.
The R2A and R2 matrices are content-amended on this branch (orders §2/§3
amendments: R2A A3/A4/A6/B/E + R2 T04/T05 to the resume-ticket contract —
original assertion semantics preserved, designation seam added; disclosed
in-file). No other pre-existing test modified.

**Probe re-run**: 15/15 probes — exit codes, normalized `.out`, and
error signatures ALL identical to the committed postfix evidence
(`E10/evidence_rp22r2a1/probe_outputs_rerun` + compare run) — no GAP
reopened.

---

## 6 — CLAIM / OBSERVED / VERIFIED / NOT PROVEN

| # | Claim | Status |
|---|---|---|
| 1 | §1 baseline anchors (main `0a26fc70`, `f3578b8` local+remote, parent `b983488`, new branch from `f3578b8` only) | VERIFIED (live commands, BASELINE.md) |
| 2 | Approval mints a one-shot engine-issued ticket bound to the gate + full operation identity | VERIFIED (E1/L1; code path `decide_human_gate`→`_mint_resume_ticket`) |
| 3 | Only the ENGINE-DESIGNATED continuation consumes (independent matching call refused, zero consumption/side effects) | VERIFIED (E1 — engine's own generic recovery relaunch; L3) |
| 4 | One-shot consumption + new approval after use; refusal family leaves zero Actions | VERIFIED (E1/E2/L4) |
| 5 | Expired/transferred/forged tickets refuse fail-closed | VERIFIED (E3/L1/L2) |
| 6 | Agent change refuses; cross-run child gets own gate; different inputs new gate | VERIFIED (L3/E4/E5) |
| 7 | E9-R production approve/resume flow intact | VERIFIED (E1 legs + E9-R battery row PASS; R2A-E re-run green) |
| 8 | The push command itself uses the SIGNED URL; between-window config change cannot re-route | VERIFIED (F1 — deterministic wrapped-resolver mutation, both attack vectors armed; attacker bare object-checked empty of the push) |
| 9 | Prewrite insteadOf attack fails at signature scope (fail-closed, no effect) | VERIFIED (F2; probe P3 proves the source-repo push WOULD have been re-routed) |
| 10 | Multi-destination / force / record-truth semantics preserved | VERIFIED (F3/F4/F5; R2A F-rows re-run green) |
| 11 | No privilege expansion; real-chain git_push stays rejected | VERIFIED (E6 + R2A G-rows green; no admin grant exists) |
| 12 | No new regression vs `f3578b8` | VERIFIED (two-state 19/19 identical, OVERALL=0) |
| 13 | Battery fully green | NOT CLAIMED — 6 rows NOT GREEN (baseline-identical, declared) |
| 14 | Production owner channel (registry issuance bound to a real owner console in production) | NOT PROVEN (declared limit — git_push stays fail-closed without a wired registry) |
| 15 | `git_branch`/`git_diff` input→argv injection hardening (same class as F2, out of scope) | NOT PROVEN (carried from R2A row 18) |
| 16 | EOE `PushEngine.push()` own-flow destination binding (staged_push covers the unified tool only) | NOT PROVEN (carried from R2A row 19) |
| 17 | TOCTOU/multi-process races, GitHub CI, OBS-1/2, DF3, Windows-native, LocalSubstrate | NOT PROVEN (out of scope per order §4.5 / prior orders) |
| 18 | Resume tickets survive ENGINE PROCESS RESTART (cross-process durability of the ticket registry) | NOT PROVEN (tickets are in-memory engine state; the checkpoint-persisted gate decision survives, but a restarted engine must re-approve — disclosed design boundary, fail-closed direction) |

---

## 7 — REMAINING LIMITS (declared)

1. Rows 14–18 above (owner channel in production; git_branch/git_diff
   argv hardening; PushEngine own flow; TOCTOU/CI/OBS/DF3/Windows;
   cross-process ticket durability).
2. The between-window proof covers the remote-config/url-rewrite attack
   surface; a same-moment replacement of the signed URL's TARGET
   CONTENTS (e.g. swapping the bare repo directory itself) is a
   filesystem-level TOCTOU outside this order's scope (row 17).
3. The engine's generic same-run recovery relaunch refuses (by design)
   while a ticket is armed — resuming an approved operation is ONLY
   possible through `resume_approved_task`. This is the fail-closed
   direction; operators must use the controller API (documented in the
   method docstring).

## 8 — COMMAND LOG (key raw evidence paths)

* `E10/evidence_rp22r2a1/BASELINE.md` — §1 raw baseline (B1–B5 + debris observation)
* `E10/evidence_rp22r2a1/F2_DESIGN_PROBES.txt` — 7 design probes (P1–P7)
* `E10/evidence_rp22r2a1/R2A1_MATRIX_VERBOSE.txt` — 15/15 verbose + summary
* `E10/evidence_rp22r2a1/REGRESSIONS_BRANCH.txt` — 20-row battery (14 green / 6 declared not green)
* `E10/evidence_rp22r2a1/REGRESSIONS_BASELINE_F3578B8.txt` — baseline battery
* `E10/evidence_rp22r2a1/TWO_STATE_BASELINE.json` — 19/19 identical, OVERALL=0
* `E10/evidence_rp22r2a1/probe_outputs_rerun/` — 15 probes + compare (identical)

**Post-push check (§6)**: re-verify live that `main` == `0a26fc70...`
unchanged, then STOP for independent arbitration. No merge. MERGE HOLD
ACTIVE.
