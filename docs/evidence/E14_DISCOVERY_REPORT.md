# E14 DISCOVERY REPORT

## BASELINE

| Property | Value |
|----------|-------|
| E13 CLOSED COMMIT | `e4211b7ca4c1a8426da5abb15d2f419a499cc8d3` |
| CURRENT HEAD | `e4211b7ca4c1a8426da5abb15d2f419a499cc8d3` |
| REMOTE MAIN | `e4211b7ca4c1a8426da5abb15d2f419a499cc8d3` |
| BRANCH | `main` |
| E13 REGRESSION | 91/91 PASS (confirmed) |

---

## AGENT ARCHITECTURE DISCOVERY

### SELECTION PATH

```
ExecutionEngine._execute_single_task() [line 576]
    ↓
select_agent_for_task(agent_task, previous_agent_id)
    ↓
AgentRegistry.select_agent_for_task() [agent_role.py:606]
    ↓
1. get_definition_by_type(task.agent_type)  -- returns FIRST definition of that type
2. if not available, fall back to select_agent() [line 580]
    ↓
list_available_agents()  -- filters by is_available() 
    ↓
sort by (-max_tokens, agent_id)  -- deterministic, highest max_tokens wins
    ↓
returns candidates[0]
```

**Key finding**: `get_definition_by_type()` returns the **first** definition of that type, regardless of availability. Then `select_agent_for_task()` checks `.is_available()` but **does not reserve**.

### OWNERSHIP PATH

```
AgentFactory.execute_agent() [execution.py:1579]
    ↓
1. If context.agent_id already set -> use that agent [line 1592]
2. Else select_agent_for_task() [line 1601]
    ↓
3. create_instance(agent_type, agent_id) [line 1607]
    ↓
4. registry.set_lifecycle_state(agent_id, ASSIGNED) [line 1622]
    ↓
5. agent.execute() [line 1658]
    ↓
6. On success: registry.set_lifecycle_state(agent_id, COMPLETED) [line 1672]
   On failure: registry.set_lifecycle_state(agent_id, FAILED) [line 1676]
    ↓
7. Return result
```

**Key finding**: Agent state transitions `AVAILABLE → ASSIGNED → RUNNING → COMPLETED/FAILED → AVAILABLE` happen **inside execute_agent()**, NOT at selection time.

### AGENT LIFECYCLE STATE MACHINE

```
REGISTERED → AVAILABLE → ASSIGNED → RUNNING → COMPLETED → AVAILABLE
                                      ↓
                                    FAILED → AVAILABLE
                                      ↓
                                    DISABLED → AVAILABLE
```

Validated mechanically in `agent_role.py:41-49` via `validate_agent_lifecycle_transition()`.

---

## AGENT CONCURRENCY CONTRACT

**From code inspection: UNSPECIFIED**

The architecture does **not** explicitly declare whether an agent is:
- Single-task exclusive (only one task at a time)
- Multi-task capable (can execute multiple tasks concurrently)

The lifecycle states imply single-task execution (ASSIGNED → RUNNING → COMPLETED), but there is **no reservation mechanism** at selection time to enforce exclusivity.

---

## ADVERSARIAL TEST RESULTS

### Test Setup
- `max_parallel=2` (true concurrent execution)
- Single available agent (`tracked-agent-0`, type IMPLEMENTER)
- Two independent tasks (TaskA, TaskB) both READY at scheduling boundary

### CONDITION A — SAME AGENT SELECTED

**RESULT: CONFIRMED**

```
Test A execution log:
  {'event': 'execute_start', 'task_id': 'task-d02f...', 'agent_id': 'tracked-agent-0', 'timestamp': 1790801740.3579257}
  {'event': 'execute_start', 'task_id': 'task-f7e1...', 'agent_id': 'tracked-agent-0', 'timestamp': 1790801740.3584769}
```

Both tasks selected `tracked-agent-0`. Selection occurred **0.55ms apart** - within the TOCTOU window.

### CONDITION B — SIMULTANEOUS EXECUTION

**RESULT: CONFIRMED**

```
Test B timing:
  Task A: 1790801740.673 - 1790801740.976  (duration: 0.303s)
  Task B: 1790801740.674 - 1790801740.982  (duration: 0.308s)
  Temporal overlap: TRUE
```

Both tasks executed **concurrently** on the same agent instance. The agent's `execute()` method was called twice with overlapping time windows.

### CONDITION C — OWNERSHIP / STATE INTEGRITY

**RESULT: CORRUPTION DETECTED**

```
Test C final states:
  Task A: FAILED (error: "Invalid agent lifecycle transition: COMPLETED -> COMPLETED")
  Task B: COMPLETED
  
  Agent final state: COMPLETED (NOT released to AVAILABLE)
```

**Failure mechanism:**
1. Task B completes first → agent transitions `RUNNING → COMPLETED`
2. Task A completes → agent transitions `COMPLETED → COMPLETED` **INVALID**
3. State machine rejects: `validate_agent_lifecycle_transition(COMPLETED, COMPLETED)` raises
4. Task A marked FAILED with terminal error
5. Agent stuck in COMPLETED state (not released)

### CONTROL — MULTIPLE AGENTS

**RESULT: UNEXPECTED BEHAVIOR**

Even with 2 agents registered (`tracked-agent-0` max_tokens=1000, `tracked-agent-1` max_tokens=1100), **both tasks selected the same agent** (`tracked-agent-1`, highest max_tokens).

The selection logic is **not** distributing tasks across available agents; it's always picking the highest-capacity available agent.

### DEPENDENCY CHAIN — SEQUENTIAL REUSE

**RESULT: WORKS CORRECTLY**

With dependency chain A → B,C and single agent:
- Task A executes, agent goes COMPLETED → AVAILABLE
- Tasks B,C unblocked and execute sequentially
- Agent properly reused

### DUPLICATE SCHEDULING — FAILS

**RESULT: CORRUPTION**

4 tasks, 1 agent, max_parallel=2:
- 1 task succeeds
- 1 task fails with `COMPLETED → COMPLETED` 
- 2 tasks fail with `No available agent` (agent stuck in COMPLETED)

---

## RACE BOUNDARY

The **exact unsafe boundary** is:

```
select_agent_for_task() [execution.py:576]
    ↓ returns agent_defn
agent.agent_id stored in attempt.agent_id [line 586]
    ↓ 
AgentFactory.execute_agent() [line 623]
    ↓
registry.set_lifecycle_state(agent_id, ASSIGNED) [agent_role.py:718]
    ↓
agent.execute() [line 1658]
```

**TOCTOU Window**: Between `select_agent_for_task()` returning and `set_lifecycle_state(ASSIGNED)`.

During this window:
- Multiple tasks can select the same agent
- Agent still shows `is_available() == True` (state is AVAILABLE)
- No atomic reservation occurs

---

## TEST MATRIX

| Test | Task IDs | Agents | max_parallel | Expected | Actual |
|------|----------|--------|--------------|----------|--------|
| A: Same agent selection | 2 | 1 | 2 | Different agents or queue | **Same agent** |
| B: Simultaneous execution | 2 | 1 | 2 | Sequential | **Concurrent (overlap)** |
| C: Ownership integrity | 2 | 1 | 2 | Both succeed | **1 fails, agent stuck** |
| Control: Multi-agent | 2 | 2 | 2 | Distributed | **Same highest-capacity** |
| Dependency chain | 3 | 1 | 2 | Sequential reuse | **Works** |
| Duplicate guard | 4 | 1 | 2 | All 4 succeed | **1 succeeds, 3 fail** |

---

## E13 REGRESSION

**91/91 PASS** - No regression introduced by discovery tests.

---

## SCOPE AUDIT

| In Scope (E14 Discovery) | Out of Scope |
|--------------------------|--------------|
| Agent selection race identification | Fix implementation |
| Ownership contract determination | Atomic reserve-on-select |
| Simultaneous execution measurement | Agent pooling |
| State corruption evidence | Scheduler redesign |
| TOCTOU boundary isolation | Distributed locking |

---

## RECOMMENDED NEXT ACTION

**OWNER DECISION REQUIRED**

The architecture does not define the agent concurrency contract. Three paths exist:

### PATH 1: AGENTS ARE SINGLE-TASK EXCLUSIVE (Recommended)
- Add atomic reservation at selection: `AVAILABLE → ASSIGNED` atomically
- Second task waits or fails fast with "agent busy"
- Matches lifecycle state machine design (ASSIGNED → RUNNING)

### PATH 2: AGENTS ARE MULTI-TASK CAPABLE
- Allow concurrent execution on same agent
- Fix lifecycle: allow `RUNNING → RUNNING` or `COMPLETED → RUNNING`
- Requires agent implementation to be thread-safe/reentrant

### PATH 3: DEFER TO HIGHER LAYER
- Let orchestrator enforce single-task via max_parallel=1 per agent
- Not recommended - defeats parallel execution purpose

---

## FINAL STATUS

```
[✓] Baseline verified (HEAD == origin/main == e4211b7)
[✓] E13 regression confirmed (91/91 PASS)
[✓] Exact selection implementation identified
[✓] Exact ownership implementation identified
[✓] Agent concurrency contract: UNSPECIFIED
[✓] Adversarial race test executed
[✓] Same-agent selection behavior measured: TRUE
[✓] Simultaneous execution behavior measured: TRUE (overlap confirmed)
[✓] Ownership/state integrity measured: CORRUPTION CONFIRMED
[✓] Precise race boundary identified: TOCTOU in select_agent_for_task → set_lifecycle_state(ASSIGNED)
[✓] No unsupported architectural assumption introduced
[✓] No E13 regression
```

**DISCOVERY PHASE: COMPLETE**

**OUTCOME: PASS — DEFECT CONFIRMED**

The agent selection race condition **exists and causes actual state corruption** (CONDITION C). The precise failure boundary is the TOCTOU between agent selection and ASSIGNED state transition.

---

## NEXT STEP

**STOP. Await owner adjudication on agent concurrency contract (PATH 1 vs PATH 2 vs PATH 3).**

Do not implement atomic reservation, agent pooling, or scheduler changes until contract is decided.