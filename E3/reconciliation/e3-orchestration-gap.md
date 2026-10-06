# E3 Orchestration Gap Analysis

**Date**: 2026-10-05
**Baseline SHA**: ea109e785189bebd0fc4eeb03577981e774ccfe9
**Canonical Path**: P1 (Unified ExecutionEngine) + P2 (MissionController)

---

## 1. Current MissionController Public API (P2)

**File**: `src/unified/mission_controller.py`

### Core Methods:
| Method | Purpose | Parameters | Returns |
|--------|---------|------------|---------|
| `define_mission(user_request, specs)` | Create mission from declarative spec | `user_request: str`, `specs: List[TaskSpec]` | `(Mission, Run, Dict[key→task_id])` |
| `record_plan_v1(run_id, mission_id)` | Record initial plan version | `run_id`, `mission_id` | `Dict` (plan representation) |
| `execute_run(run_id, max_parallel, task_timeout)` | Execute task graph through engine | `run_id`, `max_parallel=1`, `task_timeout` | Normalized execution result |
| `scan_failures(events, task_results)` | Detect & classify failures | `events: List[FactoryEvent]`, `task_results` | `List[FailureRecord]` |
| `recover_failed_task(run_id, task_id, reason)` | Recover task after failure | `run_id`, `task_id`, `reason` | `None` |
| `replan_mission(...)` | Mission-level replanning | `run_id`, `deviation`, `invalidate_task_ids`, `corrected_criteria`, `add_specs`, `rewire`, `reason`, `plan_version` | `ReplanRecord` |
| `emit_marker(...)` | Emit custom marker event | `mission_id`, `run_id`, `trigger`, `detail` | `None` |
| `create_full_checkpoint(mission_id, run_id, step)` | Full durable checkpoint | `mission_id`, `run_id`, `step` | `Checkpoint` |
| `build_reexecution_ledger(...)` | NO_FALSE_REEXECUTION proof | `mission_id`, `resume_marker`, `expected`, `absent_tasks` | `List[Dict]` |
| `verify_completion(run_id, required_keys)` | Mission completion check | `run_id`, `required_keys: List[str]` | `(bool, Dict)` |
| `finalize_mission(mission_id, run_id, reason)` | Drive to EVIDENCED | `mission_id`, `run_id`, `reason` | `Dict` |
| `export_event_trace(mission_id)` | Reconstruct history from events | `mission_id` | `List[Dict]` |
| `export_evidence_chain(mission_id)` | Evidence chain reconstruction | `mission_id` | `List[Dict]` |
| `ledger_snapshot()` | Persist controller ledger | — | `Dict` |
| `list_checkpoints()` | List available checkpoints | — | `List[Checkpoint]` |
| `restore_from_checkpoint(checkpoint_id)` | Restore from checkpoint | `checkpoint_id` | `bool` |

### Data Structures:
- `TaskSpec` — declarative task definition (key, name, description, depends_on, acceptance_criteria, context)
- `FailureRecord` — classified failure with kind, recovery_action, evidence
- `ReplanRecord` — v1→v2 plan change with added/removed/invalidated/preserved/rewired tasks
- `FailureKind` enum: TASK_EXECUTION_FAILURE, TOOL_RUNTIME_FAILURE, PLAN_DEVIATION, PROCESS_INTERRUPTION
- `RecoveryAction` enum: NONE, RETRY, REASSIGN, REPLAN, RESUME

---

## 2. Current ExecutionEngine Public API (P1)

**File**: `src/unified/execution.py`

### Core Methods:
| Method | Purpose |
|--------|---------|
| `create_mission(user_request)` | Create Mission entity |
| `create_run(mission_id, parent_run_id)` | Create Run entity |
| `create_task(...)` | Create Task with dependencies, agent_type, acceptance_criteria |
| `execute_task_graph(run_id, ...)` | Execute graph with parallelism, retry, checkpoint |
| `execute_task_graph_parallel(...)` | Parallel execution entry point |
| `get_runnable_tasks(run_id)` | Get READY tasks respecting dependencies |
| `get_task_graph_status(run_id)` | Full graph status |
| `validate_task_graph(run_id)` | Validate graph integrity |
| `add_task_to_graph(run_id, task)` | Dynamic task addition |
| `request_replan(...)` | Request replan (emits REPLAN_REQUESTED) |
| `apply_replan(...)` | Apply replan changes |
| `replan_task_graph(...)` | Core replanning logic |
| `create_checkpoint(...)` | Create checkpoint |
| `resume_from_checkpoint(checkpoint_id, mission_id)` | Cross-runtime resume |
| `restore_task_graph_from_checkpoint(...)` | Restore graph from checkpoint |
| `subscribe_events(callback)` | Event bus subscription |
| `get_event_history(mission_id)` | Get persisted events |
| `get_mission_status(mission_id)` | Mission status snapshot |
| `complete_mission/cancel_mission/pause_mission/resume_mission` | Mission lifecycle |
| `create_human_gate/decide_human_gate` | Human gate protocol |

### Supporting Classes:
- `FileEvidenceStore` — artifact/evidence persistence with disk I/O
- `SimpleEventBus` — in-memory event emission
- `ExecutionContext` — agent execution context (sandbox, evidence_store, event_emitter)

---

## 3. Existing Mission/Task Contracts

**File**: `src/unified/contracts.py`

### Domain Entities:
- `Mission` — mission_id, user_request, state (MissionState), metadata
- `Run` — run_id, mission_id, parent_run_id, state
- `Task` — task_id, run_id, mission_id, name, description, agent_type, depends_on, acceptance_criteria, state, max_retries, retry_count, context
- `Checkpoint` — checkpoint_id, mission_id, run_id, step, state, task_states, artifact_ids, evidence_hashes, task_definitions, task_dependencies, task_dependents, attempt_history, human_gate, human_decision
- `Artifact` / `EvidenceRecord` / `Verification`

### State Machines:
- `MissionState`: ANALYZING → PLANNING → DESIGNING → REVIEWING → APPROVED → AWAITING_APPROVAL → EXECUTING → EXECUTED → VERIFYING → EVIDENCED → VERIFIED (owner-gated) / CANCEL_REQUESTED → CANCELLED
- `TaskState`: PENDING → BLOCKED → READY → RUNNING → COMPLETED / FAILED / CANCELLED

### Event Catalog (Key Events):
- Mission: `mission.started`, `mission.completed`, `mission.state_changed`, `mission.paused`, `mission.resumed`
- Run: `run.started`, `run.completed`
- Task: `task.created`, `task.assigned`, `task.started`, `task.completed`, `task.failed`, `task.retry`
- Agent: `agent.started`, `agent.completed`, `agent.failed`
- Verification: `verification.started`, `verification.complete`
- Replan: `replan.requested`, `replan.applied`
- Checkpoint: `checkpoint.created`, `checkpoint.loaded`
- Human: `human.required`, `human.decision`
- Tools: `tool.started`, `tool.completed`

### Agent Contracts:
- `AgentTask` / `AgentResult` — execution protocol
- `AgentContext` — sandbox, evidence_store, event_emitter
- `BaseAgent` — on_start, on_complete, on_failed, execute, validate_input/output
- `AgentRegistry` / `AgentFactory` — role registration and instantiation

### Tool Contracts:
- Filesystem: ReadFile, WriteFile, EditFile, ListDir, Grep, FindFiles, FileBrowser
- Shell: RunCommand
- Git: Branch, Commit, Diff, Status, Push
- Web: Search, Fetch
- Sandbox: Execute, ArtifactRead/Write, VerificationCheck

---

## 4. Agent Registration/Runtime Contracts

**File**: `src/unified/agent_role.py`

### Key Components:
- `AgentRegistry` — global registry with `_implementations`, `_definitions`, `_type_to_definition`
- `AgentDefinition` — agent_id, agent_type, name, description, capabilities, enabled, lifecycle_state
- `AgentFactory` — `execute_agent_by_id(agent_id, context, task)` → `AgentResult`
- `BaseAgent` — abstract base with `execute()`, `on_start()`, `on_complete()`, `on_failed()`, `validate_input()`, `validate_output()`
- `MissionTaskAgent` (in mission_controller.py) — concrete implementation for E33-style tasks

### Current Registration Pattern (from E33 test):
```python
register_mission_agent(agent_registry)  # Registers "e33-mission-agent" for IMPLEMENTER
```

---

## 5. Failure/Recovery/Replan Interfaces

### Failure Detection (MissionController.scan_failures):
- Input: event history + task_results
- Output: List[FailureRecord] with classified `FailureKind`
- Kinds detected:
  - `TASK_EXECUTION_FAILURE` — agent RuntimeError
  - `TOOL_RUNTIME_FAILURE` — sandbox/filesystem OSError
  - `PLAN_DEVIATION` — verification failure against plan contract
  - `PROCESS_INTERRUPTION` — process death (handled via resume)

### Recovery Actions:
- `RETRY` — engine-level retry (max_retries on Task)
- `REASSIGN` — engine-level agent reassignment
- `REPLAN` — mission-level plan invalidation + regeneration
- `RESUME` — cross-runtime checkpoint resume

### Replanning (MissionController.replan_mission):
- Invalidates downstream tasks (must be PENDING/BLOCKED/READY)
- Corrects acceptance criteria (data-driven from artifact)
- Adds remediation tasks (new TaskSpecs)
- Rewires dependencies (surviving tasks → new tasks via "NEW:<key>")
- Re-baselines rewired tasks to BLOCKED until new deps complete
- Records `ReplanRecord` with full diff

---

## 6. Event/State/Checkpoint Interfaces

### Event Persistence:
- `ExecutionEngine._restore_events_from_disk(mission_id)` — loads events from disk
- `FileEvidenceStore.save_to_disk(mission_id)` / `load_from_disk(mission_id)`
- Checkpoints saved to `state_dir/checkpoints/{mission_id}/{checkpoint_id}.json`

### Checkpoint Contents (create_full_checkpoint):
- `task_states` — {task_id: TaskState}
- `task_definitions` — full task specs including context
- `task_dependencies` / `task_dependents` — graph edges
- `attempt_history` — per-task attempt records
- `artifact_ids` / `evidence_hashes` — evidence linkage

### Resume Flow:
1. `ExecutionEngine.resume_from_checkpoint()` loads checkpoint
2. Restores events, evidence store, mission object
3. **FIX APPLIED**: If checkpoint.state == PAUSED → target_state = EXECUTING
4. Creates new child run
5. Reconstructs task graph from checkpoint definitions
6. Returns new Run for continued execution

---

## 7. Legacy Orchestrators (P4/P5) - Functionality Analysis

### P4: Workflow/ProjectEngine (`src/workflow/engine.py`)
**Purpose**: Self-driving project loop with phase/step/gate structure

**Key Capabilities**:
- Project creation with objective + execution_policy
- Phase/step determination from durable DB state
- Planner role integration (live LLM planning)
- Owner approval gates (AWAITING_OWNER_APPROVAL)
- Step execution via `run_task` (external function)
- Evidence collection + test + review + audit + adjudicate per step
- Failure classification: TRANSIENT/EXECUTION → RETRY → OwnerGate(PLAN_REVISION)
- Provider unready → EXECUTION_BLOCKED + OwnerGate(PROVIDER_ACTION)
- Checkpoint after every tick (DB-backed)
- Crash/restart survival: first tick() resumes from DB

**What P4 has that P1+P2 lacks**:
1. **Project/Phase/Step abstraction** — multi-phase project lifecycle vs single mission
2. **Planner role integration** — live LLM generates plan from objective
3. **Owner approval gates** — explicit human-in-the-loop for plan approval
4. **Role cycle orchestration** — thinker→reviewer→implementer→verifier→arbiter
5. **DB-backed durability** — SQLite persistence vs file-based checkpoints
6. **Step-level execution** — `run_task` function vs full graph execution
7. **Project state queries** — `/api/projects/{id}/state` full reconciliation snapshot

### P5: Missions/Orchestrator (`src/core/orchestrator.py`, `src/missions.py`)
**Purpose**: 5-role mission cycle (Thinker→Reviewer→Implementer→Verifier→Arbiter)

**Key Capabilities**:
- Fixed 5-role cycle with hard-coded transitions
- Thinker: produces Plan (DRAFT) with PlanTask list
- Reviewer: approves or requests revision (≤3 cycles → Arbiter)
- Implementer: executes tasks in sandbox, produces artifacts
- Verifier: checks evidence, produces VerificationResult (≤2 attempts → Arbiter)
- Arbiter: resolves disputes (≤3 calls → forced escalation)
- Cycle state machine: DRAFT → REVIEWING → APPROVED → AWAITING_APPROVAL → EXECUTING → EXECUTED → VERIFYING → EVIDENCED → VERIFIED
- Owner-gated VERIFIED (user_verifies only)
- StopController integration (cycle_id, checkpoint, resume)
- PDF report generation (mideast_report.pdf)
- Event streaming via SSE

**What P5 has that P1+P2 lacks**:
1. **Role orchestration** — coordinates 5 distinct agent roles in sequence
2. **Planning role** — Thinker generates structured Plan from goal
3. **Review/approval cycle** — iterative plan refinement
4. **Verification role** — independent Verifier checks evidence
5. **Arbitration** — dispute resolution mechanism
6. **Fixed domain mission** — geopolitical report with PDF output
7. **Cycle-level stop/resume** — StopController with cycle_id
8. **Thread-based execution** — runs in executor thread with SSE streaming

---

## 8. Existing Tests as E3 Foundations

### Canonical Tests (E2-R2 Verified):
| Test | File | What it Proves |
|------|------|----------------|
| E32e | `tests/unified/test_e32e_durable_execution.py` | Durable execution + checkpoint/resume + replanning + human gate |
| E32f | `tests/unified/test_e32f_autonomous_replanning.py` | Autonomous replanning + cross-runtime resume |
| E33 | `tests/unified/test_e33_mission_autonomy.py` | 3-runtime mission with real process kill, replanning, no false re-execution |

### Supporting Tests:
| Test | File | Relevance |
|------|------|-----------|
| VS-001 | `tests/unified/test_vs001_integration.py` | State machine transitions |
| VS-002 | `tests/unified/test_vs002.py` | Basic execution spine |
| VS-002-E8 | `tests/unified/test_vs002_e8.py` | E8 extensions |
| VS-004 | `tests/unified/test_vs004_graph.py` | Graph operations |

### Legacy Tests (Not Canonical):
- Factory tests: tool tests, dashboard, events (skipped without LLM)
- Core tests: cycle_stop, stop_api (Linux-specific skips)

---

## 9. Orchestration Gap Summary

| Capability | P1+P2 (Canonical) | P4 (Workflow) | P5 (Missions) | Gap for Canonical Orchestrator |
|------------|-------------------|---------------|---------------|--------------------------------|
| Mission definition from goal | ✅ `define_mission(specs)` | ✅ `create_project(objective)` | ✅ `run_mission(goal)` | **Goal→Spec translation missing** |
| Planning (LLM-generated plan) | ❌ Manual TaskSpecs | ✅ Thinker role | ✅ Thinker role | **No canonical planner** |
| Plan approval gate | ❌ | ✅ AWAITING_OWNER_APPROVAL | ✅ Reviewer→Arbiter→Owner | **No canonical approval gate** |
| Role orchestration | ❌ | ✅ Phase/step roles | ✅ 5-role cycle | **No canonical role coordinator** |
| Independent verification | ❌ Engine verify_task | ✅ Reviewer role | ✅ Verifier role | **Verifier role missing from P1+P2** |
| Arbitration | ❌ | ✅ Adjudicate step | ✅ Arbiter role | **No canonical arbiter** |
| Project/phase abstraction | ❌ Mission/Run/Task | ✅ Project/Phase/Step | ❌ Single mission | **Multi-phase not in canonical** |
| DB-backed durability | ❌ File checkpoints | ✅ SQLite | ❌ File snapshots | **Only file-based checkpoints** |
| SSE streaming API | ❌ | ✅ /api/projects/{id}/run/stream | ✅ /api/mission/stream | **No canonical streaming API** |
| Cycle stop/resume | ❌ Mission pause/resume | ✅ Step-level stop | ✅ Cycle-level stop | **Cycle concept missing** |

---

## 10. Minimum Canonical Orchestrator Design

Based on the gap analysis, the minimum canonical orchestrator above P1+P2 should provide:

### 1. Goal → Spec Translation
- Accept natural language mission goal
- Decompose into TaskSpecs (using LLM or template)
- Output: `List[TaskSpec]` for `MissionController.define_mission()`

### 2. Plan Approval Gate (Optional)
- Present generated plan to owner
- Wait for approval/revision
- Integrate with MissionController's human_gate or new approval event

### 3. Role Coordination (Minimal)
- **Thinker** → generates plan (can be same agent type with different context)
- **Verifier** → independent verification (separate from engine's verify_task)
- No need for full 5-role cycle initially — just prove coordination works

### 4. Canonical Event Streaming
- SSE endpoint for mission events (reusing existing event catalog)
- No new event types unless contracts require

### 5. Integration Points with P1+P2:
```
Orchestrator
    ↓ (delegates)
MissionController.define_mission(specs)
    ↓
MissionController.record_plan_v1()
    ↓
MissionController.execute_run()
    ↓ (observes via events)
MissionController.scan_failures()
MissionController.replan_mission()
MissionController.verify_completion()
MissionController.finalize_mission()
```

---

## 11. Recommended E3 Vertical Slice

**Mission**: "Create a markdown report from 3 web sources"

**Flow**:
1. Orchestrator accepts goal
2. Thinker (IMPLEMENTER with planner context) generates TaskSpecs
3. Plan presented → owner approval gate (or auto-approve for test)
4. MissionController defines mission + executes
5. Verifier (VERIFIER agent type) checks evidence independently
6. On failure → MissionController.replan_mission()
7. Finalize → EVIDENCED
8. Event trace reconstructable

**No new architecture** — pure coordination layer over P1+P2.

---

## 12. Files to Inspect for Implementation

### Core Canonical:
- `src/unified/mission_controller.py` — P2 API
- `src/unified/execution.py` — P1 API
- `src/unified/contracts.py` — All contracts
- `src/unified/agent_role.py` — Agent registry/factory

### Legacy (Reference Only):
- `src/core/orchestrator.py` — P5 orchestrator (5-role cycle)
- `src/missions.py` — P5 mission runner
- `src/workflow/engine.py` — P4 project engine
- `src/api/projects.py` — P4 API layer
- `src/api/routes.py` — P5 API layer

### Tests (Reference):
- `tests/unified/test_e33_mission_autonomy.py` — Full mission test
- `tests/unified/test_e32f_autonomous_replanning.py` — Replanning test