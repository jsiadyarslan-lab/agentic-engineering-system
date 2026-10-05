# E2-R WORKTREE RECONCILIATION REPORT

## Provenance Analysis

### 1. Why is the worktree dirty?

The worktree at baseline `70ec26efff49fa582b153dc0602e67b348b74a3e` contains 131 changes (27 modified, 26 deleted, 78 untracked) because **multiple experimental phases have executed and produced evidence since the baseline commit**, but none of this work was committed. The dirty state represents the accumulated output of:

- **E33** — Multiple mission runs (original + new `mission-a4d000ec9778`)
- **E35** — Modified evidence files from post-processing
- **E38/E40** — Test updates for operational agents
- **E41-E47** — Complete evidence directories from each experiment
- **E51** — Verified durable dependency integration (13/13 tests passing)
- **E2-UI** — Factory Control Room source code (factory-control.js, factory-control.css, index.html modifications)
- **Runtime artifacts** — Generated mission state, artifacts, and database files

### 2. Which work produced each major change?

| Category | Phase | Description |
|----------|-------|-------------|
| **Modified tracked evidence (E33/E35)** | E33/E35 | Post-experiment evidence updates (baseline, mission spec, acceptance matrix, attempts, etc.) |
| **Deleted E33 state files** | E33 | Original mission `7ebaf6f5cf2e` checkpoint/event/evidence files removed from working tree (still in HEAD) |
| **Source code changes** | E51 + E2-UI | `execution.py` (artifact dep check), `mission_controller.py` (checkpoint/resume), `index.html` (factory nav) |
| **Test updates** | E38/E40 | Switched from ContextAgent to Operational agents |
| **Untracked evidence dirs (E40-E51)** | E40-E51 | Complete evidence outputs from each executive order |
| **Untracked runtime artifacts** | E44, E2-UI, E51 | Generated mission state, artifacts, SQLite DB |
| **Factory Control Room** | E2-UI | `factory-control.js` (914 lines), `factory-control.css` — **VERIFIED control plane** |
| **Run scripts** | E45-E51 | Experiment runner scripts for each phase |
| **Test directories** | E41-E43 | Formal experiment test code |
| **Ad-hoc test scripts** | Unknown | `test_security*.py`, `test_task_failed_event.py` — unclear provenance |

### 3. Which changes are valuable?

**HIGH VALUE — Must Preserve:**

| Path/Class | Reason |
|------------|--------|
| `src/unified/execution.py` | E51 integration: DependencyEngine artifact dependency checking in `_check_and_unblock_dependents` |
| `src/unified/mission_controller.py` | E51 integration: `create_checkpoint`, `list_checkpoints`, `restore_from_checkpoint` methods |
| `src/ui/index.html` | E2-UI: Factory navigation + imports (VERIFIED control plane) |
| `src/ui/factory-control.js` | E2-UI: Complete Factory Control Room (914 lines, VERIFIED) |
| `src/ui/factory-control.css` | E2-UI: Factory Control Room styles |
| `run_e51_durable_dependency.py` | E51: Test runner for 13/13 verified durability tests |
| `docs/evidence/e51/` | E51: Complete evidence (13 test files, final report, test matrix) |
| `docs/evidence/e47/` | E47: Verified autonomous loop evidence |
| `docs/evidence/e33/state/.../mission-a4d000ec9778/` | E33: New mission run evidence |
| `docs/evidence/e35/*.json` | E35: Modified evidence files |
| `tests/e38/test_autonomous_engineering_mission.py` | E38/E40: Updated to operational agents |
| `tests/e41/`, `tests/e42/`, `tests/e43/` | Formal experiment test code |
| `runtime/missions/`, `runtime/e44_artifacts/` | Active runtime state |

**MEDIUM VALUE — Archive:**

| Path/Class | Reason |
|------------|--------|
| `run_e45_*.py`, `run_e46_factory.py`, `run_e47_autonomous_loop.py` | Experiment runners — useful for reproduction but not core source |
| `e47_resume_process.py` | Utility script for E47 resume testing |
| `docs/evidence/e40/` through `e46/` | Prior experiment evidence — preserve for audit trail |

**LOW VALUE — Discard Pending Approval:**

| Path/Class | Reason |
|------------|--------|
| `integration_test_output.txt` | Temporary test output |
| `src/agentic_engineering_system.egg-info/` | Python build artifact |
| `test_security*.py`, `test_task_failed_event.py` | Ad-hoc tests with unclear provenance |

### 4. Which changes are disposable?

Only the **LOW VALUE** items above are clearly disposable. All evidence directories, source code changes, and formal experiment outputs must be preserved per the governance principle: *Artifact existence ≠ system integration ≠ operational capability* — but **evidence must not be destroyed** merely because it is untracked.

### 5. Which changes cannot yet be attributed?

| Path | Uncertainty |
|------|-------------|
| `test_security.py`, `test_security_audit.py`, `test_security_negative.py`, `test_task_failed_event.py` | No clear phase attribution; appear to be ad-hoc security/negative testing |
| Some runtime subdirectories (`cycles`, `diagX`, `flaky0136`, `pt_*`, `_pytest_tmp`, `_tmp`) | Accumulated test/debug artifacts over time |

### 6. Are any E1/E2 artifacts at risk?

**YES.** The deleted E33 state files (26 files: checkpoints, events, evidence_store, sandbox tasks, handshake, ledger, runner_phase2) are **deleted from the working tree but still exist in HEAD at `70ec26e`**. A `git reset --hard` or `git checkout .` would restore them from HEAD, so they are **not at risk of permanent loss** — but the *new* E33 mission run (`mission-a4d000ec9778`) in untracked directories **would be lost** if cleaned.

**E1/E2 core artifacts are NOT at risk** because:
- Baseline commit `70ec26e` contains all E1-E2 source code
- All prior evidence (E33-E35 tracked files) exists in HEAD
- New evidence (E40-E51) is in untracked directories

### 7. Is there any evidence that prior work was never committed?

**YES — Extensive.** The entire E2-UI (Factory Control Room) and E51 (Durable Dependency Integration) work exists **only as uncommitted changes and untracked files**:
- E51 source changes: `execution.py`, `mission_controller.py` (modified, tracked)
- E51 test runner: `run_e51_durable_dependency.py` (untracked)
- E51 evidence: `docs/evidence/e51/` (untracked, 17 files)
- E2-UI source: `factory-control.js`, `factory-control.css` (untracked), `index.html` (modified)
- E47 evidence: `docs/evidence/e47/` (untracked, 12 files)

**This represents ~5 experimental phases of verified work that has never been committed.**

### 8. Is the clean baseline recoverable without losing valuable work?

**YES, but only with selective preservation.** The clean baseline at `70ec26e` is recoverable via `git reset --hard`, but this would destroy:
- All untracked evidence directories (E40-E51)
- All untracked source files (Factory Control Room, run scripts)
- All runtime state

**A clean baseline requires:**
1. Archive/commit valuable untracked work first
2. Then reset to clean state
3. Then selectively restore/re-apply

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `git clean -fd` destroys E51 evidence | HIGH | CRITICAL | Never run clean without archival |
| `git reset --hard` loses new E33 mission run | HIGH | HIGH | New mission run is untracked only |
| Source changes lost if not committed | MEDIUM | HIGH | E51/E2-UI changes are tracked modifications — survive reset but not clean |
| Runtime DB (`agent_hub_v2.db`) corrupted | LOW | MEDIUM | Backup before any reset |

---

## Recommended Disposition

| Path/Class | Proposed Action | Confidence | Reason |
|------------|----------------|------------|--------|
| `src/unified/execution.py` | **PRESERVE** (commit) | HIGH | E51 core integration |
| `src/unified/mission_controller.py` | **PRESERVE** (commit) | HIGH | E51 checkpoint/resume |
| `src/ui/index.html` | **PRESERVE** (commit) | HIGH | E2-UI control plane integration |
| `src/ui/factory-control.js` | **PRESERVE** (commit) | HIGH | E2-UI verified control room |
| `src/ui/factory-control.css` | **PRESERVE** (commit) | HIGH | E2-UI styles |
| `run_e51_durable_dependency.py` | **PRESERVE** (commit) | HIGH | E51 test runner |
| `docs/evidence/e51/` | **PRESERVE** (commit) | HIGH | E51 verified evidence (13/13) |
| `docs/evidence/e47/` | **PRESERVE** (commit) | HIGH | E47 verified evidence |
| `docs/evidence/e33/state/.../mission-a4d000ec9778/` | **PRESERVE** (commit) | HIGH | New E33 mission evidence |
| `docs/evidence/e35/*.json` (modified) | **PRESERVE** (commit) | HIGH | Updated E35 evidence |
| `tests/e38/test_autonomous_engineering_mission.py` | **PRESERVE** (commit) | HIGH | E38/E40 operational agents |
| `tests/e41/`, `tests/e42/`, `tests/e43/` | **PRESERVE** (commit) | HIGH | Formal test code |
| `docs/evidence/e40/` - `e46/` | **ARCHIVE** (commit) | HIGH | Prior experiment evidence |
| `run_e45_*.py`, `run_e46_factory.py`, `run_e47_autonomous_loop.py` | **ARCHIVE** (commit) | MEDIUM | Experiment runners |
| `e47_resume_process.py` | **ARCHIVE** (commit) | MEDIUM | Utility script |
| `runtime/e44_artifacts/`, `runtime/e44_artifacts_resume/` | **PRESERVE** (archive externally) | MEDIUM | Runtime artifacts |
| `runtime/missions/` | **PRESERVE** (archive externally) | MEDIUM | Active runtime state |
| `integration_test_output.txt` | **DISCARD_PENDING_APPROVAL** | MEDIUM | Temporary output |
| `src/agentic_engineering_system.egg-info/` | **DISCARD_PENDING_APPROVAL** | HIGH | Build artifact |
| `test_security*.py`, `test_task_failed_event.py` | **DISCARD_PENDING_APPROVAL** | LOW | Unclear provenance |
| Runtime temp dirs (`_pytest_tmp`, `_tmp`, `flaky*`, `pt_*`) | **DISCARD_PENDING_APPROVAL** | HIGH | Test debris |

---

## Baseline Readiness

**BLOCKED_HUMAN_DISPOSITION_REQUIRED**

### Unresolved Items Requiring Human Decision:

1. **E40-E46 evidence directories** — Should these be committed to the repo, archived externally, or left untracked? They represent ~7 phases of formal experiment evidence.

2. **Runtime directories** (`runtime/missions/`, `runtime/e44_artifacts/`, `agent_hub_v2.db`) — These are active runtime state. Should they be:
   - Backed up and excluded via `.gitignore`?
   - Committed as evidence?
   - Left as-is (untracked)?

3. **Ad-hoc test scripts** (`test_security*.py`, `test_task_failed_event.py`) — No clear ownership. Discard or investigate?

4. **Run scripts** (`run_e45_*.py`, etc.) — Commit as experiment reproducers or archive externally?

5. **Runtime temp directories** — Safe to clean, but confirm no active processes using them.

---

## Next Steps Required

Before E2-R can proceed with a clean baseline:

1. **Human disposition** on the 5 unresolved item classes above
2. **Selective commit** of all PRESERVE items (source + evidence)
3. **External archive** of runtime state (missions, artifacts, DB)
4. **Gitignore update** for runtime directories and build artifacts
5. **Then** `git reset --hard` to establish clean baseline
6. **Then** E2-R execution can begin

**Do not clean the worktree yet.** Wait for the next executive order authorizing the exact disposition.