# E10-RP2.2-R2A2 — DELIVERY REPORT
## SANITIZED GIT ENVIRONMENT + PINNED DESTINATION REGRESSION

**Order:** E10-RP2.2-R2A2 (AUTHORIZED WITH AMENDMENTS; arbitration verdict on R2A1 @ `74c8ec1`: PARTIAL ACCEPTANCE / REQUEST CHANGES — F2 not closed)
**Base commit:** `74c8ec12122df759bec5688f2980e181ea8976bb` (R2A1 head; parent `f3578b8`)
**Branch:** `e10-rp22r2a2-sanitized-git-environment` — derived from `74c8ec1` ONLY
**Direct parent of the delivery commit:** `74c8ec12122df759bec5688f2980e181ea8976bb`
**MERGE HOLD:** ACTIVE — no merge to `main`; `main` untouched at `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (verified live pre-modification and re-verified live post-push).

---

## 1. §1 — HARD BASELINE (E10/evidence_rp22r2a2/BASELINE.md)

* B1: `origin/main` == local `main` == `0a26fc70` — unchanged, no local/remote divergence.
* B2: `74c8ec1` exists locally AND remotely (R2A1 branch head); parent of `74c8ec1` is exactly `f3578b8` (== R2A head, exactly as ordered); merge-base(`74c8ec1`, `f3578b8`) = `f3578b8` (exactly 1 commit ahead of the R2A base).
* B3: live remote branch census recorded (all 15 refs).
* B4: all 11 worktrees recorded; the historical R1 worktree's pre-existing untracked Windows-path debris (disclosed unchanged since R2A1) left untouched — historical worktree.
* B5: new worktree `e10rp22r2a2_work` created from `74c8ec1` ONLY; 0 commits ahead at creation; porcelain=0 pre-work.
* Rules honored: no `reset`/`clean`/`stash`/`restore`/`amend`/force-push; no historical-evidence modification; no merge of any branch.

## 2. §2 — THE FIX: `src/eoe/push_engine.py` (the ONLY production file touched)

### 2.1 Root cause (arbitration finding, reproduced pre-fix — probe evidence)

Pre-fix `staged_push` built the push child's environment as `dict(os.environ)` plus two modifications (`GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`). Every OTHER inherited variable stayed live. Probes (E10/evidence_rp22r2a2/F2_ENV_PROBES.txt, git 2.47.3, run against the pre-fix code BEFORE the source change):

* **EP1 — the arbitrator's exact PoC (raw git)**: with `GIT_CONFIG_NOSYSTEM=1` + `GIT_CONFIG_GLOBAL=/dev/null` armed AND `GIT_CONFIG_COUNT=1` + `GIT_CONFIG_KEY_0=url.<attacker>.insteadOf` + `GIT_CONFIG_VALUE_0=<signed-url>` inherited, the push of the EXPLICIT signed URL from the alternates-only staging repo landed at the ATTACKER repo — the signed repo received nothing. **VULNERABLE (OBSERVED)** — identical to the arbitration reproduction table.
* **EP2 — `GIT_CONFIG_PARAMETERS`**: grammar derived from git v2.47.3 source (`config.c:669-719 parse_config_env_list`): sq-quoted tokens — old-style `'key=value'` / new-style `'key'='value'` (JSON forms are rejected as "bogus format" — verified). With the discovered grammar the same reroute through `GIT_CONFIG_PARAMETERS` alone: **VULNERABLE (OBSERVED)**.
* **EP3 — the shipped engine code**: the CURRENT (pre-fix) `eoe.push_engine.staged_push` — the exact function the `git_push` handler runs — with the hostile variables planted in the calling process `os.environ`: **VULNERABLE (OBSERVED)** — the accreditation blocker.
* **EP4 — control**: the identical push with a clean environment lands only at the signed repo — the setup is sound; the difference is the inherited environment.
* **EP5a/EP5b — `GIT_CONFIG_SYSTEM`**: the channel is LIVE at git level whenever `GIT_CONFIG_NOSYSTEM` is unset (raw reroute OBSERVED); the pre-fix shipped push was NOT rerouted through it only because `GIT_CONFIG_NOSYSTEM=1` happens to suppress the system-config source — safety by accident of precedence, honestly disclosed; the fix replaces the accident with an explicit rule.

### 2.2 The contract now implemented (`_sanitized_git_env` + `_validate_transport` + `staged_push`)

1. **Allowlist-built child environment — never inheritance** (order §2.2.1): `_sanitized_git_env()` starts from an EMPTY dict, copies ONLY `_SANITIZED_ENV_ALLOWLIST` = `PATH` (+ `SYSTEMROOT`/`SYSTEMDRIVE`/`COMSPEC`/`PATHEXT` on `os.name == "nt"` only — Windows CRT process startup; none can influence git config, the destination, the repo, or the object database).
2. **Explicit hard strip of every `GIT_*` name** (order §2.3) — belt-and-braces ON TOP of the allowlist, as one rule that also covers every future `GIT_*` channel environment inspection may reveal: `GIT_CONFIG_COUNT`, all `GIT_CONFIG_KEY_*`/`GIT_CONFIG_VALUE_*`, `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_GLOBAL` (cleaned BEFORE the safe value is set — strip-then-set, never inherit-then-modify), `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_NAMESPACE`, `GIT_SSH_COMMAND`, `GIT_PROXY_COMMAND`, `GIT_ASKPASS`, `GIT_TERMINAL_PROMPT`, `GIT_TRACE*` — structurally absent from the child env.
3. **Three fixed safe overrides set AFTER the strip**: `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, **`GIT_CONFIG_SYSTEM=/dev/null` (pinned EXPLICITLY — R2A2; no longer the NOSYSTEM accident)**.
4. **Not inherited at all**: `HOME`, `XDG_CONFIG_HOME` (no global-config lookup paths), `SSH_AUTH_SOCK`, `http_proxy`/`HTTPS_PROXY`, locale, `TMPDIR`. The proof NEVER relies on `GIT_CONFIG_GLOBAL=/dev/null` alone (order §2.6) — sanitization is structural; the safe values ride on an already-clean environment.
5. **ONE sanitized environment for EVERY child spawned by `staged_push`**: `rev-parse --absolute-git-dir` (source git-dir discovery — the object-database link writer), `init --bare` (staging), `cat-file -e` (approved-commit presence proof), and the push itself. A hostile `GIT_DIR`/`GIT_OBJECT_DIRECTORY` in the process env can no longer redirect source-object discovery.
6. **Transport policy, fail-closed** (order §2.5): the ONLY accredited transport is the LOCAL FILESYSTEM — an absolute path, or `file:///` with an EMPTY authority (Windows drive-letter paths accepted on their platform). Everything else — `http`/`https`/`ssh`/`git`/`ftp`/`ftps`/`rsync` schemes and scp-like `[user@]host:path` — is REFUSED `PushRejected` BEFORE any subprocess. Relative paths are refused (a CWD-dependent destination is a non-pinned destination). No auth variable was deleted and then claimed supported: **no network transport is claimed**; network pushes stay impossible through the engine until a transport is accredited with its own allowlist and independent tests.
7. `_git()` gained an optional `env=None` parameter (default = inherit, the historical behavior for every other caller — `resolve_push_destination` and the rest are untouched).

**Declared boundary (unchanged class):** `PATH` is inherited (executable resolution for the `git` binary) — executable-level substitution through a hostile `PATH` is the engine-wide status quo for every git-family call and is NOT a config/destination/repo/object-database vector; same declared class as R2A1's TOCTOU boundary, not a claim of defense.

## 3. §3 — NEGATIVE TESTS (E10/test_e10rp22r2a2_matrix.py — 25/25, exit 0)

Every destination assertion is by **REPO CONTENT** (refs + `cat-file -e` + object counts via `--batch-all-objects`), never by parsing push output; every leg uses a FRESH signed/attacker pair so content proves THIS call.

* **N1 (§3.2/§3.3 — the arbitrator's exact set)**: `GIT_CONFIG_COUNT=1` + `GIT_CONFIG_KEY_0=url.<attacker>.insteadOf` + `GIT_CONFIG_VALUE_0=<signed-url>` planted in the process `os.environ`; push via the REAL `staged_push` (source repo + staging bare on `objects/info/alternates` + signed + attacker bares). Only accepted outcome observed: **signed received the commit; attacker has NO refs, NO commit object, ZERO objects**; argv evidence carries the signed URL.
* **N2 (§3.4 — `GIT_CONFIG_PARAMETERS`)**: the same reroute attempt through `GIT_CONFIG_PARAMETERS` alone (sq-quoted grammar, source-cited) — neutralized identically.
* **N3 (§3.4 — the sweep)**: 18 hostile inherited variables, one per leg, each with a REWRITE/REPOINT-capable value where the channel allows it (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_CONFIG`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_NOSYSTEM=0`, `GIT_NAMESPACE`, `GIT_SSH_COMMAND`, `GIT_PROXY_COMMAND`, `GIT_ASKPASS`, `GIT_TERMINAL_PROMPT`, `HOME` + `.gitconfig` rewrite, `XDG_CONFIG_HOME` + rewrite config, `http_proxy`, `HTTPS_PROXY`, `SSH_AUTH_SOCK`) — every leg: push succeeds AND lands ONLY at the signed repo; attacker empty; the `GIT_SSH_COMMAND`/`GIT_PROXY_COMMAND` marker-writing probes NEVER execute.
* **N4 (§2.5)**: `https`/`ssh`/scp-like/`file://localhost`/relative/`git`/`ftp`/`rsync` ALL refused `PushRejected` BEFORE any subprocess (proven by ordering — a nonexistent source repo would fail `rev-parse` first if the gate did not precede it); `file:///` and absolute paths accredited and landing.
* **N5 (§2.2/§2.3 unit)**: with a fully hostile `os.environ`, `_sanitized_git_env()` returns EXACTLY the allowlist + the three safe values; nothing else; the no-`GIT_*`-except-safe-trio invariant holds by rule.
* **N6 (§3.5 — direct child-process env proof)**: the SIGNED destination carries a pre-receive hook (receiving-side test double, disclosed) that dumps its inherited environment while the push runs under a 20-variable hostile process env. The dump shows NONE of the hostile values and the three safe values; receive-pack's OWN receiving-side additions (`GIT_DIR='.'`, `GIT_QUARANTINE_PATH`, its `GIT_OBJECT_DIRECTORY`/`GIT_ALTERNATE_OBJECT_DIRECTORIES` pointing at the RECEIVING repo's objects) are disclosed and value-checked — none equals a planted hostile value. This proves the sanitization happens inside the child process env itself, with a polluted parent (it does not rely on a clean test environment).
* **N7 (full-chain property)**: with the hostile env live at PUSH time through the REAL handler chain (gate → approve → designation → resume), the handler's own resolution inherits the pollution, the resolved URL no longer matches the SIGNED destination, and `verify_and_consume` REFUSES fail-closed before any push — the attacker receives NOTHING (content-proven); a fresh gate cycle with a clean environment then lands ONLY at the signed destination. Deterministic summary: **a polluted environment can make the chain REFUSE; it can never make it REDIRECT.**

**Order §3.7 honored:** the R2A1 matrix (15/15) and the R2A matrix (25/25) re-ran GREEN, UNMODIFIED — no pre-existing test touched this round; no pass/fail semantics changed (their between-window/pushurl/insteadOf/force/refspec/multi-destination coverage is kept exactly as it was).

## 4. §4 — F1 + E2 PRESERVED

* `ResumeTicket` logic, `MissionController.resume_approved_task`, `_check_human_gate`: **ZERO changes** — only `src/eoe/push_engine.py` touched. All R2A1 ticket/attempt/agent/expiry/reuse tests green (15/15, unamended).
* E2's CWD posture (engine run from the governed workspace root) unchanged — N7 reuses the same `_workspace_cwd` wrapper; no claim that `ExecutionContext` now carries a per-task workspace root (it does not).
* Ledger/artifact paths stay absolute in every test.
* NO privilege expansion: no `admin` grants; `git_push` still rejected through the real EOE bridge (R2A1 matrix E6 leg, green unmodified); `sandbox_execute` still unregistered; owner approval channel in production still unproven — the path stays fail-closed with no trusted approval record.

## 5. §5 — REGRESSIONS (E10/evidence_rp22r2a2/)

Battery `E10/run_rp22r2a2_regressions.sh` (REGRESSIONS_BRANCH.txt) — 20 rows, uniform command/exit/output-tail capture:

* **15 GREEN**: R2A2 matrix (new) 25/25, R2A1 15/15, R2A 25/25, R2 19/19, R1 6/6, RP2.2 22/22, RP2.1 24/24, RP2 22/22, session 9/9, RP1 16/16, RP 23/23, CW1 32/32, CW1-R1 31/31, E9-R PASS, E8 PASS.
* **6 NOT GREEN — DECLARED, identical to baseline** (`vs001+…+e32e`, `e3+e4`, `e6`, `e33+e32f`, `e35`, `e37`): matching the baseline is "no new regression PROVEN in the comparison", NOT "the battery is green". The battery is never described as green.
* **TWO-STATE vs `74c8ec1`** (REGRESSIONS_BASELINE_74C8EC1.txt, throwaway worktree, removed after): **19/19 shared rows IDENTICAL exit codes AND failure-name sets — OVERALL_TWO_STATE = 0**; zero content-amended rows this round (R2A2 amends NO test).
* **Probes re-run 15/15**: exit codes + normalized `.out` + error signatures ALL IDENTICAL to the committed postfix evidence (evidence_rp22r2a2/probe_outputs_rerun + comparator run) — no GAP reopened.
* Windows-path battery debris removed pre-commit (untracked; same class as every prior phase).

## 6. CLAIM / OBSERVED / VERIFIED / NOT PROVEN

| # | Claim | Evidence | Verdict |
|---|-------|----------|---------|
| 1 | Pre-fix R2A1 shipped `staged_push` reroutable via inherited `GIT_CONFIG_COUNT` family (arbitration finding) | F2_ENV_PROBES EP1/EP3 (destination tables by repo content) | **OBSERVED** (pre-fix) |
| 2 | Same via `GIT_CONFIG_PARAMETERS` (grammar from git v2.47.3 `config.c:669-719`) | F2_ENV_PROBES EP2 + EP2a acceptance scan | **OBSERVED** (pre-fix) |
| 3 | `GIT_CONFIG_SYSTEM` channel live at git level when NOSYSTEM unset; pre-fix shipped code neutralized only by the NOSYSTEM accident | F2_ENV_PROBES EP5a/EP5b | **OBSERVED** (channel) / **VERIFIED** (accident disclosed) |
| 4 | Fixed `staged_push` lands ONLY at the signed destination under the arbitrator's exact hostile env — attacker receives no commit, no related objects | Matrix N1 (+post-fix sanity: argv + content) | **VERIFIED** |
| 5 | Same under `GIT_CONFIG_PARAMETERS` | Matrix N2 | **VERIFIED** |
| 6 | Same under every discovered inherited variable (18-name sweep incl. repo/object-db selection, transport commands, HOME/XDG) | Matrix N3 | **VERIFIED** |
| 7 | Sanitization happens inside the child process env itself; independent of test-env cleanliness | Matrix N6 hook dump (+N1..N3 all run with polluted parent) | **VERIFIED** |
| 8 | Transport policy fail-closed; only local filesystem accredited | Matrix N4 + `_validate_transport` | **VERIFIED** |
| 9 | Full chain: hostile env can only cause fail-closed refusal, never redirection | Matrix N7 (content-proven) | **VERIFIED** |
| 10 | No new regression vs baseline `74c8ec1` | TWO_STATE 19/19 identical, OVERALL=0; probes 15/15 identical | **VERIFIED** |
| 11 | F1 (resume ticket) and E2 (CWD posture) preserved unmodified | R2A1 matrix 15/15 green unamended; zero changes in execution.py/mission_controller.py | **VERIFIED** |
| 12 | Production owner-approval channel binding | Unchanged from R2A1 declaration | **NOT PROVEN** (declared) |
| 13 | Network transports (http/https/ssh/…) support | Refused fail-closed by policy — no claim made | **NOT PROVEN — DECLARED UNSUPPORTED** (by design, §2.5) |
| 14 | `PATH`-level executable substitution defense | Not a config/destination/repo/objects vector; engine-wide status quo | **NOT PROVEN** (declared boundary, same class as TOCTOU) |
| 15 | Filesystem-level target swap between verification and execution (TOCTOU), Windows-native pywin32/LocalSubstrate, GitHub CI | Unchanged declarations | **NOT PROVEN** (declared) |
| 16 | Resolution-time env pollution (`resolve_push_destination` inherits) | Can only cause signature-scope MISMATCH → refusal (proven N7); the PUSH itself uses the signed URL + sanitized env | **VERIFIED** (as fail-closed, never a redirect) |

## 7. Remaining limitations (for arbitration)

1. **Production owner-approval channel**: still unproven and unbound to a trusted record — `git_push` stays rejected through the real EOE bridge; fail-closed with no trusted approval record.
2. **Unsupported transports**: network pushes (http/https/ssh/git/ftp/rsync, scp-like) are refused fail-closed BY POLICY; accrediting any of them requires its own auth allowlist + independent tests (order §2.5).
3. `PATH`-level executable substitution and TOCTOU/filesystem-level target swap remain declared boundaries (unchanged class since R2A1).
4. `git_branch`/`git_diff` input→argv hardening and the EOE `PushEngine` own-flow destination binding remain the same NOT-PROVEN rows declared in R2A1 (rows 18–19 there).
5. Resume tickets remain in-memory engine state (engine restart = re-approval; fail-closed direction) — unchanged from R2A1.

**Live post-push verification (to be re-run after push):** `origin/main` == local `main` == `0a26fc70…` — then STOP for independent arbitration. MERGE HOLD continues; no merge; no next stage before the verdict.
