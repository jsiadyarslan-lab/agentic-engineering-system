# E10-RP2.2-R2A — ONE-SHOT HUMAN APPROVAL + PUSH DESTINATION/REF BINDING

**Status:** DELIVERED — awaiting independent arbitration
**MERGE HOLD:** ACTIVE — nothing merged to `main`; `main` remains at
`0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`.
**Branch:** `e10-rp22r2a-approval-push-binding`
**Base commit (parent):** `b983488290618bc4e65f360f4566f721837157cb`
(the certified R2 commit; derivation proof in
`E10/evidence_rp22r2a/BASELINE.md` B1–B6).
**Scope:** close arbitration findings **F1** (one-shot, resume-bound human
approval) and **F2** (push destination + refspec/argv binding) ONLY — no
privilege expansion, no scope growth (order §4).

---

## 1 — What changed (source)

| File | Change |
|---|---|
| `src/unified/execution.py` | **F1**: `_check_human_gate` rewritten around a v2 **operation identity** (`action_gate_v2:{mission}:{run}:{task}:{tool}:{input-digest}`) with full identity record (mission_id, run_id, task_id, attempt_id, agent_id, tool, canonical input digest), PENDING / REJECTED / APPROVED+UNCONSUMED / CONSUMED states, **one-shot consumption** with consuming-attempt/agent/action lineage, **cycle archiving** (`{op_key}#cycle{n}` + monotonic `_cycles` counter), legacy-record non-authorization, fail-closed on corrupt/foreign records; helpers `_gate_operation_key` / `_archive_gate_cycle`. The R2 mission-wide tool+digest scan loop (the F1 hole) is REMOVED. `decide_human_gate` REJECT branch now records the rejection on the action-gate records (parallel to approve) so a rejected operation can never fall back to "pending". **F2**: `git_push` handler — structural remote/branch validation (leading `-`, whitespace, control chars, forbidden ref characters) BEFORE any git subprocess; `git check-ref-format --branch` as the final authority; **execution-time destination resolution** via `resolve_push_destination` with `push_url` passed into `verify_and_consume`; safe argv (`["push"] (+ --force) + ["--", remote, refs/heads/B:refs/heads/B]`) — the refspec is CONSTRUCTED by the handler, never taken raw from input. |
| `src/eoe/push_engine.py` | **F2**: `PushApproval.push_url` (canonical destination) inside the **signed payload**; `OwnerApprovalService.sign(push_url=...)`; `verify_and_consume(push_url=...)` — a record without a signed destination authorizes NOTHING (fail-closed), and the execution-time resolved destination must EQUAL the signed one; new `validate_remote_name` / `validate_branch_name` (structural) and `resolve_push_destination` (pushurl/`insteadOf`/`pushInsteadOf` rewriting via `git remote get-url --push`; **multi-destination refusal** — multiple `pushurl`s or multiple `url`s would push to ALL of them; nonexistent remote / unresolvable destination / any failure = `PushRejected`). |
| `src/unified/tool_contract.py` | `GitPushOutput.push_url` — the verified canonical destination is part of the tool's output contract (additive). |
| `E10/test_e10rp22r2_matrix.py` | T03 AMENDED to the R2A push-destination contract (see §6 test-changes). |

### Design decisions (disclosed, with mechanical justification)

1. **`attempt_id`/`agent_id` are RECORDED identity, not match-key.** The
   production resume path structurally continues a paused task under a
   FRESH attempt_id (`_execute_single_task` mints one per retry,
   execution.py). Binding the lookup key to the literal creating attempt
   would make every approval unusable (deadlock — violating §2.3 case 2).
   The approval therefore binds the operation scope
   (mission+run+task+tool+input-digest), records the CREATING lineage in
   `_operation` and the CONSUMING lineage in `_consumed`, and is
   consumable exactly once by the engine-scheduled continuation of the
   SAME task (the engine serializes attempts per task; a call from any
   other mission/run/task, or after consumption, never matches).
2. **Cross-run resume needs a new approval.** A checkpoint child-run
   (E8-style) has a different `run_id` → different operation identity →
   its own gate (order §2.3 case 6 — explicit). This is a MANDATED
   behavior change: at b983488 such a call passed via the mission-wide
   scan (the F1 hole).
3. **Legacy approvals are dead-on-arrival.** The signed payload now
   includes `push_url`; a pre-R2A approval object fails signature
   verification under the amended payload AND carries an empty
   `push_url` (rejected by scope check) — double fail-closed.
4. **`git push` argv**: option parsing is terminated with `--`, the
   remote is structurally validated first, and the refspec is always the
   handler-constructed `refs/heads/B:refs/heads/B` — no input value can
   act as an option (empirically verified: `git push -- r1 refspec`
   works; `--force` as a branch value is rejected structurally long
   before argv construction).
5. **Multi-destination is unconditionally refused.** The signed payload
   covers exactly ONE canonical URL; git pushes to ALL configured
   `pushurl`s (or `url`s when no pushurl) — proven empirically — so any
   multi-destination configuration cannot be covered by an approval and
   is rejected (order §3.1).

---

## 2 — F1 verification (order §2.3, the nine mandatory cases)

All through the REAL gate machinery (`engine.create_human_gate` /
`decide_human_gate` / mission metadata) — never a mocked gate.
Matrix: `E10/test_e10rp22r2a_matrix.py` (25/25 green, exit 0).

| §2.3 case | Test (all exit 0) | Proof |
|---|---|---|
| 1 — HIGH/CRITICAL on registered mission creates a real gate | `test_R2A_A1_gate_creation_binds_full_operation_identity` | gate created; mission → HUMAN_REQUIRED; the record carries ALL SEVEN identity fields (mission/run/task/attempt/agent/tool/input-digest); gate context embeds the operation; nothing consumed yet |
| (pending discipline) | `test_R2A_A2_pending_reentry_no_duplicate_gate` | re-presenting the same operation while undecided pauses on the EXISTING gate — no duplicate gate, from any attempt |
| 2 — after approval, resume of the SAME operation works ONCE | `test_R2A_A3_approve_then_one_shot_resume` + `test_R2A_A6_positive_resume_real_push_side_effect` | A3: the continuation attempt presents the same identity → gate CONSUMED (lineage recorded: `consumed_by_attempt` = the resuming attempt, creating attempt preserved) → proceeds past the gate. A6: POSITIVE with a real side effect — the resumed `git_push` (CRITICAL) actually EXECUTES and the push lands in the approved bare destination |
| 3 — new independent call, same tool+inputs → new approval | `test_R2A_A5_independent_call_requires_new_approval` | different task / different mission / different run with IDENTICAL tool+inputs: each gets its OWN gate; an approved gate of one operation never authorizes another; the other operation's approval is not consumed |
| 4 — reuse after completion rejected | `test_R2A_A4_reuse_after_completion_rejected` (+ A6 last leg, + E third-run leg) | after consumption, the next identical call opens a NEW cycle ("Human gate created"); the consumed cycle is archived (`#cycle1`), the old gate id stays duplicate-decision-protected, `_cycles` advances |
| 5 — changed inputs / tool / scope rejected | `test_R2A_B_changed_scope_rejected` | different inputs → new gate; different tool (git_push after a run_command approval) → its own gate; different task with same inputs → its own gate |
| 6 — different mission/run/attempt context does not inherit | `test_R2A_A5_...` + `test_R2A_E_e9r_production_gate_flow_and_resume` (cross-run leg) | different mission / run / task → own gate; a checkpoint child-run's identical call gets its OWN gate (`run_id` differs — the mandated cross-run semantics); post-consumption attempts never inherit (A4, E third-run) |
| 7 — unregistered mission stays fail-closed | `test_R2A_D_unregistered_mission_and_zero_trace` | HIGH (run_command) and CRITICAL (git_push) with a ghost mission → explicit "not registered in the engine" rejection (R2 §2.1 preserved) |
| 8 — E9-R approve/resume flow intact | `test_R2A_E_e9r_production_gate_flow_and_resume` + battery row "E9-R" (exit 0) | MissionController run pauses at the gate; `decide_human_gate(approve)` restores EXECUTING; the re-executed same run CONSUMES the approval exactly once (archived cycle-1 consumption, fresh consuming attempt); E9-R test suite green unchanged |
| 9 — rejection before execution: no events/Action/side effects | `test_R2A_D_unregistered_mission_and_zero_trace` | event/action counts UNCHANGED across the ghost-mission rejections and the rejected-decision re-entry |
| (legacy) — old records authorize nothing | `test_R2A_D2_legacy_records_authorize_nothing` | pre-R2 bare records, R2 digest-only records, and a corrupt v2 record all fail-closed → new gate |
| (rejection terminality) | `test_R2A_C_rejected_decision_is_terminal_for_identity` | a REJECTED decision is terminal for the identity (re-entry refused with the recorded feedback); duplicate decision on a decided gate refused by the engine |

**Approval-not-reused proof (order §6):** A4 (same identity after
consumption → new cycle), A5 (different operation contexts never match),
A6 (post-execution identical call re-gated), E (same-run retries after
consumption hit the spent approval and open a fresh pending cycle —
`#cycle2_consumed` stays None). The mission-wide scan that allowed all
of these at b983488 no longer exists (code-removed, not
test-suppressed).

---

## 3 — F2 verification (order §3.1–§3.3)

All push legs run against REAL local bare repositories; every leg
asserts WHICH destination received (or did not receive) the ref — never
registry-text comparison alone. Layered tests (handler reached through a
DISCLOSED permissive scaffold because the real EOE policy cannot express
`admin`) are labeled as such (order §4.3); the production chain is
proven separately in the G-legs.

| Case (order §3.2 + §3.1) | Test (all exit 0) | Destination proof |
|---|---|---|
| branch starting with `-` | `test_R2A_F1_option_shaped_branch_and_remote_rejected` | rejected structurally pre-subprocess; BOTH bares stay empty |
| `branch="--force"` with `force=False` | same | rejected structurally — the value can never act as a push option; nothing pushed |
| remote starting with `-` | same | rejected structurally; nothing pushed |
| whitespace / forbidden ref chars | same | rejected; nothing pushed |
| ref-format authority | `test_R2A_F2_check_ref_format_is_the_authority` | `git check-ref-format --branch` refusal surfaced; nothing pushed |
| remote URL CHANGED after approval | `test_R2A_F3_url_changed_after_approval_rejected` | same remote NAME re-pointed → refused ("وجهة الدفع الفعلية … لا تطابق"); NEITHER the new NOR the originally approved destination received anything |
| multi-`pushurl` (2 destinations) | `test_R2A_F4_multi_destination_pushurl_rejected` | refused ("وجهات دفع متعددة") — proven against two real bares that git WOULD have pushed to both without the guard; both stay empty |
| multi-`url`, no pushurl | `test_R2A_F4b_multi_url_no_pushurl_rejected` | same refusal class; both bares stay empty |
| actual destination differs from signed | `test_R2A_F5_signed_destination_mismatch_rejected` | approval signed for dest2 while the remote points at dest1 → refused; nothing pushed anywhere |
| different branch | `test_R2A_F6_scope_mismatch_branch_sha_force` | refused (approval scope); nothing pushed |
| different commit SHA (HEAD moved after approval) | same | refused ("التزام آخر"); nothing pushed |
| force mismatch (both directions) | same | refused (force scope) in both directions; nothing pushed |
| valid approval (URL+branch+commit) | `test_R2A_F7_valid_approval_pushes_to_the_approved_destination` | push lands EXACTLY in the approved destination (dest1 HEAD == approved sha); dest2 stays empty; output names the verified `push_url` |
| nonce reuse after consumption | same (final legs) | reuse refused; dest1 unchanged |
| force push requires force-scoped approval | `test_R2A_F8_force_push_requires_force_scoped_approval` | non-force push of diverged history refused BY GIT (GitPushError, dest unchanged); force-scoped approval + force=True lands at the approved dest only |
| nonexistent remote (incl. default `origin`) | `test_R2A_F9_nonexistent_remote_and_legacy_approval` | "remote غير موجود" / destination cannot be proven → refused |
| legacy approval without `push_url` | same | signed-but-destinationless approval refused ("push_url فارغ"); an R2-era approval OBJECT replayed into the amended registry fails signature under the amended payload (dead-on-arrival) — verified at the registry level |
| `insteadOf` rewriting (effective destination) | `test_R2A_F10_url_rewriting_effective_destination_binding` | the RAW configured URL signed → refused; the EFFECTIVE rewritten destination signed → push lands at the rewritten destination |
| `pushInsteadOf` (push-specific precedence) | same | effective destination switches to the push-rewritten one; an approval signed for the OLD effective destination is refused; the push-rewritten destination receives the commit |

### §3.3 — owner approval channel

* `test_R2A_G1_real_bridge_git_push_stays_rejected`: through the REAL
  EOE bridge, `git_push` stays REJECTED at the permission layer
  (`admin` unattainable) EVEN WITH a real, correctly signed, registered
  approval — zero trace, zero effects on the destination, and the
  approval is NOT consumed by the rejection (the production chain never
  reaches it). Per order §4.2 the push remains disabled through the
  production chain.
* `test_R2A_G2_no_registry_wired_push_refused`: no registry wired →
  push refused outright (R2 §3.6 preserved).
* `test_R2A_G3_owner_channel_not_agent_reachable`: forged/unregistered
  nonces refused; an owner-SIGNED but UNREGISTERED approval is as good
  as a forgery (signing ≠ registering); the git_push input schema
  carries ONLY `{repo_path, remote, branch, force, owner_approval_nonce}`
  — no approval-minting field exists in any registered tool; the engine
  never auto-populates the registry (constructor wiring only).
* Registry/handler legs are LAYERED tests (disclosed scaffolds), NOT
  end-to-end production pushes (order §4.3) — the production push
  pathway stays fail-closed (G1).

---

## 4 — No privilege expansion (order §4)

1. No `admin` grant is created or widened; the real-bridge rejection of
   `git_push` is re-proven (G1) with a REAL registered approval.
2. `git_push` stays rejected through the real EOE bridge (admin
   unattainable) — unchanged from R2.
3. Layered tests are labeled inline (permissive/path-aware scaffolds,
   with the production-chain counterproof in the G-legs).
4. `sandbox_execute` remains unregistered; all R2 parallel-path closures
   untouched (battery rows R2/R1/RP2.2 green unchanged).
5. Scope untouched: OBS-1, OBS-2, DF3, Windows-native, LocalSubstrate,
   TOCTOU remain declared boundaries.

---

## 5 — Regression (order §5)

Battery: `E10/run_rp22r2a_regressions.sh` →
`E10/evidence_rp22r2a/REGRESSIONS_BRANCH.txt` (command + exit + output
tail per row, unified format).

### Green rows (exit 0)

`R2A matrix (new)` 25/25 · `R2 matrix` 19/19 · `R1 matrix` 6/6 ·
`RP2.2 matrix` 22/22 · `RP2.1 matrix` 24/24 · `RP2 matrix` 22/22 ·
`RP2 session` 9/9 · `RP1 matrix` 16/16 · `E10-RP matrix` 23/23 ·
`E10/CW1 matrix` 32/32 · `E10-CW1-R1 matrix` 31/31 · `E9-R` PASS ·
`E8 negative gates` PASS.

### NOT GREEN rows (exit 1) — DECLARED, identical to baseline b983488

`vs001..e32e` (3 fails) · `e3+e4` (5 fails) · `e6` (4 fails) ·
`e33+e32f` (1 fail) · `e35` · `e37`. Pre-existing at baseline (and
before); the battery is NOT described as green while these rows are
non-zero (order §5.6).

### Two-state comparison vs b983488

`E10/evidence_rp22r2a/TWO_STATE_BASELINE.json` (baseline run:
`REGRESSIONS_BASELINE_B983488.txt`, throwaway detached worktree at
b983488, removed after): **18/18 shared rows IDENTICAL exit codes AND
failure-name sets → OVERALL_TWO_STATE=0** (no new regression PROVEN;
non-zero rows stay declared not-green). The R2-matrix shared row is
flagged `content_amended_on_branch` (T03 — see §6).

### Probe re-run (supplementary)

All 15 discovery probes re-run on the R2A tree
(`evidence_rp22r2a/probe_outputs_rerun/`, unified format):
**exit codes 15/15 identical, normalized `.out` 15/15 identical, error
signatures 15/15 identical** to the committed postfix evidence
(`PROBE_RERUN_COMPARE.txt`; masking covers only random temp-dir names,
random engine ids, and fresh-repo commit shas — all non-deterministic
values). No GAP reopened; the six non-zero probes (A2, G2, G5, S1, S3,
S4) stay DECLARED NOT GREEN exactly as at b983488.

---

## 6 — Test changes to pre-existing suites (disclosed)

* `E10/test_e10rp22r2_matrix.py` **T03** — the R2 matrix's push test was
  amended to the R2A contract: approvals are now signed WITH the
  canonical `push_url` (resolved via `resolve_push_destination` over the
  same repo) and `verify_and_consume` is called with the execution-time
  `push_url`. Two registry-level legs were ADDED inside T03 (wrong
  destination with matching remote name; destination proven in the
  handler output). Every ORIGINAL leg's assertion semantics are
  unchanged (fake/wrong-remote/wrong-branch/wrong-sha/force-mismatch/
  expired/reuse rejections; valid single consume; handler refusal with
  no registry; real push + force push to the bare). This amendment is
  REQUIRED by the order (§3.1 changes the approval contract; §2.2
  forbids weakening the gate to preserve old tests). Two-state: the R2
  row is 0 → 0 with identical (empty) failure sets.
* No other pre-existing test was modified. The R2A matrix is a NEW file.

---

## 7 — CLAIM / OBSERVED / VERIFIED / NOT PROVEN

| # | Claim | Observed | Verdict |
|---|---|---|---|
| 1 | A HIGH/CRITICAL gate binds the FULL operation identity (7 fields) | R2A-A1: record + gate context carry all seven; mission → HUMAN_REQUIRED | **VERIFIED** |
| 2 | The approval authorizes exactly ONE resume of the SAME operation | R2A-A3/A6: first continuation consumes (lineage recorded), proceeds; next identical call re-gated | **VERIFIED** |
| 3 | A new independent call (same tool+inputs, different operation context) never reuses an approval | R2A-A5/B/E: different task/mission/run → own gate; not consumed by others | **VERIFIED** |
| 4 | Reuse after completion is rejected | R2A-A4/A6/E: consumed → archived cycle → NEW gate; old gate duplicate-decision-protected | **VERIFIED** |
| 5 | Legacy/corrupt gate records authorize nothing | R2A-D2: pre-R2, R2-style, corrupt v2 records all fail-closed | **VERIFIED** |
| 6 | Unregistered mission = explicit rejection, zero trace | R2A-D: message + zero event/action delta (HIGH and CRITICAL) | **VERIFIED** |
| 7 | E9-R approve/resume flow intact | R2A-E + E9-R battery row exit 0; same-run continuation consumes once | **VERIFIED** |
| 8 | Rejected decision is terminal for the identity | R2A-C: re-entry refused with feedback; duplicate decision refused | **VERIFIED** |
| 9 | PushApproval binds the canonical DESTINATION, not the remote name | F3/F5/F7/F10: URL-change/mismatch refused; valid destination lands exactly there; effective (rewritten) destination is the binding one | **VERIFIED** |
| 10 | Multi-destination pushes are refused | F4/F4b: 2 pushurls / 2 urls refused; both real bares stay empty (git would push to all) | **VERIFIED** |
| 11 | No input value can act as a git CLI option | F1/F2: leading-dash remote/branch (incl. `--force` with force=False), whitespace, forbidden chars — all rejected before any subprocess; argv uses `--` + constructed refspec | **VERIFIED** |
| 12 | `--force` only from the explicit flag + force-scoped approval | F6 (both mismatches refused) + F8 (force push only with force-scoped approval) | **VERIFIED** |
| 13 | Nonce single-use | F7/A6 reuse refused; registry burn (R2, re-proven) | **VERIFIED** |
| 14 | git_push stays rejected through the REAL production chain | G1: real bridge + REAL registered approval → permission-layer rejection, zero trace, approval unconsumed | **VERIFIED** |
| 15 | Owner channel not agent-reachable | G3: forged/unregistered/signed-unregistered nonces refused; input schema has no approval-minting field; engine never auto-populates | **VERIFIED** |
| 16 | No regression vs b983488 | Two-state 18/18 identical (exit + failure sets), OVERALL=0; probes 15/15 identical | **VERIFIED** |
| 17 | Same-run re-execution of a gate-paused task re-arms cleanly in production without test intervention | The engine's scheduler leaves the task FAILED after the pause-retry storm; the E test re-arms it via the engine's own retry-state transition (disclosed inline). The E8 suite's cross-run path works but now requires a fresh approval per run (mandated §2.3 case 6) | **OBSERVED** (engine mechanics; disclosed; not a security regression — fail-closed direction) |
| 18 | git_branch/git_diff pass other input fields (branch_name/file_path) to git argv without structural validation | Same input-injection CLASS as F2 but on NON-push tools (MEDIUM/LOW risk, inside repo grounding + write-grant authorization); OUT OF R2A SCOPE per order §4 ("close F1 and F2 ONLY") | **NOT PROVEN / DECLARED** (new observation, left for a future order) |
| 19 | EOE PushEngine's own flow (substrate push path) binds its destination URL the same way | Not touched — F2 targets the git_push tool path (the arbitration finding); EOE PushEngine.push uses its own §5 flow; signature payload change is version-consistent within itself | **NOT PROVEN / DECLARED** (out of finding scope) |
| 20 | GitHub CI result for the new commit | No CI runs recorded for the branch (same as all prior phases); evidence is local + pushed branch only | **NOT PROVEN** |
| 21 | TOCTOU between destination resolution and push execution | Resolution and push run in the same handler execution; a concurrent remote reconfiguration between them is not structurally excluded | **NOT PROVEN / DECLARED** (TOCTOU remains a declared boundary per order §4.5) |
| 22 | OBS-1, OBS-2, DF3, Windows-native, LocalSubstrate | Untouched, out of scope per order §4.5 | **NOT PROVEN / DECLARED** |

Zero CLAIM-only rows.

---

## 8 — Remaining certification blockers

None identified within the R2A order's scope. Honest boundaries for the
arbitrator's attention:

1. **Cross-run approvals are now per-run by design** (§2.3 case 6): an
   E8-style checkpoint child-run resuming a HIGH/CRITICAL operation
   needs its own approval. Operationally stricter; fail-closed; if the
   arbitrator wants cross-run approval portability, that is a NEW
   requirement needing its own identity model (e.g., signed approval
   tokens carrying the operation identity) — not assumed here.
2. **Engine scheduler mechanics** (row 17): the same-run re-execution of
   a gate-paused task currently requires the task re-arm the engine
   itself performs for retries; disclosed in-test. Not a security issue.
3. **Row 18** (non-push git tools' input→argv validation) and **row 19**
   (EOE PushEngine destination binding): same-class observations outside
   this order's scope, declared for a future order.
4. CI remains unrecorded on GitHub for this commit (row 20).

**Delivery state:** branch `e10-rp22r2a-approval-push-binding` pushed
(NOT force), parent EXACTLY `b983488`; `main` UNTOUCHED at
`0a26fc70ce13e69932db7fe54c810fcbf0f99d3f`; MERGE HOLD respected —
stopping here for independent arbitration.
