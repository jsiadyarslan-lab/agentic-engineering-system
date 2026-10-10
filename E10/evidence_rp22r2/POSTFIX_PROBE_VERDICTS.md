# E10-RP2.2-R2 — Post-fix probe verdicts (order §6.1)

The ORIGINAL 15 discovery probes (byte-identical scripts, copied from the
discovery branch `dbe28da`) were re-run on the FIXED tree. Raw
stdout/stderr/exit per probe: `probe_outputs_postfix/PROBE_*.{out,err,exit}`
(unified format, same runner `E10/run_rp22r2_probes.sh` with
`RP22R2_PROBE_OUT=E10/evidence_rp22r2/probe_outputs_postfix`).

Two reading rules:

1. The RAW observation lines (`[G2] ...`, `[S1] ...`, ...) are the
   authority — they show the post-fix behavior. Several `[... RESULT]`
   lines inside the probe outputs are HARDCODED baseline-era
   interpretation text (the discovery probes were written to document the
   BASELINE); where the leading verdict word is computed (`SECURE` vs
   `GAP-CONFIRMED` vs `MIXED`) it flips automatically, but the trailing
   prose may still describe the baseline. The table below is the
   post-fix interpretation of the SAME scenarios.
2. Six probes exit non-zero: their unwrapped legs now hit the NEW
   enforcement raises (the traceback in each `.err` IS the observation —
   the fix firing). The `R2-Txx` column cites the pytest proof of the
   same behavior with every leg wrapped and zero-trace assertions.

| Probe | Baseline verdict | Post-fix OBSERVED (raw lines) | Post-fix verdict | Binding test |
|---|---|---|---|---|
| G1 absent validator | SECURE (all 7 rejected, zero trace) | all rejected; `sandbox_execute` now `ValueError: Tool not registered` (a rejection, different exception class) — probe marks MIXED only because it counts non-PermissionError as "not rejected" | SECURE (unchanged semantics; sandbox_execute leg moved from permission-error to unregistered-error) | T08, T11 |
| G2 legacy validator, uncontained repo | GAP-CONFIRMED (kind-only final decision, then DF1 NameError crash) | every git op REJECTED: "requires a path-aware grant validator" — the coarse 2-arg form is no longer a final decision for the git family; probe then stops at the sandbox_execute leg (unregistered) | **GAP-1 CLOSED** (authorization half) | T01, T02 |
| G3 real bridge, grant=treeA, target repoB | GAP-CONFIRMED (git_branch/git_status proceed, target never grounded; then DF1 crash) | git_branch/git_status REJECTED: "target '/tmp/.../repoB' not covered by any presented grant"; git_push rejected (write); run_command rejected (execute unattainable); repoB branches unchanged | **GAP-1 CLOSED** (target grounding + scope) | T01, T02 |
| G4 missing/revoked grants | SECURE (fail-closed) + DF1 crash on live grant | all three legs rejected at grounding (probe repos sit outside the workspace universe — an even earlier, cleaner rejection); zero event/action deltas; repoB unchanged | SECURE (strengthened: rejection now at structural grounding) | T01 (out-of-universe leg), T11 |
| G5 rejected-after-allowed zero-trace | SECURE | probe stops at its first unwrapped run_command leg: gate pause raise (registered mission; the probe's legacy mission-wide pre-approval no longer authorizes — no input digest) | zero-trace behavior proven by T11 (after a prior allowed op) | T11, T04 |
| G6 git_push fake nonce + mission-wide approval + arbitrary remote | GAP-CONFIRMED (passes every pre-execution layer; DF1 crash the only stop) | BOTH the empty-nonce negative control AND the fake-nonce push REJECTED at the path-aware validator gate (legacy validator refused for git tools); remote untouched | **GAP-2 CLOSED at the tool layer** (nonce/registry scope proven by T03) | T03 |
| O1 operational parallel zero-auth path | GAP-CONFIRMED (command EXECUTES) | `OperationalImplementerAgent.execute(run_command): success=False` — the manager's §4.1 EMPTY_GRANT_IDS refusal; no execution | **GAP-8 CLOSED** (parallel path fail-closed at the manager) | T06, T10 |
| S1 empty-list bypass vs 2-arg subject call | GAP-CONFIRMED (empty list executes) | live-grant leg: `SandboxError: Invalid grants` (fail-closed); probe stops at the empty-list leg: `EMPTY_GRANT_IDS` raise | **GAP-3 CLOSED** | T06 |
| S2 traversal sandbox_id at execute | GAP-CONFIRMED (dir created outside base) | `SANDBOX_ID_INVALID` raised at execute; "directory OUTSIDE artifacts base created: False"; artifacts base entries: [] | **GAP-7 CLOSED** | T07 |
| S3 single-use + zero-trace grant rejection | SECURE | probe stops at its first unwrapped leg: `EMPTY_GRANT_IDS` raise (the §4.1 enforcement itself) | single-use + zero-trace re-proven by T06 | T06 |
| S4 run_command host subprocess | GAP-CONFIRMED (command EXECUTES on host, marker file) | probe stops at its first unwrapped leg: gate pause raise (mission-wide pre-approval no longer authorizes) | **GAP-4/5 CLOSED** — full-chain refusal proven by T05 (marker file never written; degraded mode only by explicit opt-in) | T04, T05 |
| X1 ghost-mission gate bypass | GAP-CONFIRMED (run_command EXECUTES with ghost mission) | registered mission: gate ACTIVE (preserved); UNREGISTERED: "mission ... is not registered in the engine — refused fail-closed"; git_push ghost: rejected at grounding; remote untouched | **GAP-5 CLOSED** | T04 |
| X2 sandbox_execute registered-but-unimplemented | OBSERVED (Unknown-tool error MASKED by DF2) | `ValueError: Tool not registered: sandbox_execute` surfaced DIRECTLY (no masking — the DF2 fix keeps true errors) | **GAP-6 CLOSED** (unregistered; true error surfaced) | T08, T09 |
| A1 _validate_grant kind-only | OBSERVED (dead code) | unchanged (dead code, no callers — outside R2 §4.5 scope, declared) | UNCHANGED (declared boundary) | — |
| A2 _run_in_sandbox zero-auth primitive | GAP-CONFIRMED latent (executes with empty grants) | `RuntimeError: _run_in_sandbox is disabled fail-closed (E10-RP2.2-R2 §4.5)` — probe stops at the first leg | **GAP-8 sibling CLOSED** (primitive disabled) | T10 |

OVERALL: OVERALL_EXIT=1 on the re-run is expected and is itself evidence —
the six non-zero probes stop exactly at the NEW enforcement raises (each
`.err` traceback cites the R2 rule). Every GAP-1..GAP-8 behavior observed
at baseline is now REJECTED (or the primitive disabled), with the
zero-trace discipline asserted by the binding matrix T01..T11 (19/19
green) rather than by the legacy probe scaffolds.
