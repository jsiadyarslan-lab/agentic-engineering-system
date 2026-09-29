# MASTER ARCHITECTURE DOCUMENT
## Engineering Agents System — Unified Architecture

**Version:** 1.0  
**Status:** DESIGN / GOVERNANCE / TRACKING  
**Classification:** PROPOSED (based on D0 discovery evidence)  
**Date:** 2026-09-29  

---

## 1. ARCHITECTURAL VISION

### 1.1 Golden Rule (Acceptance Criterion)
> **المصنع الهندسي يجب أن يكون قادرًا على إنتاج وتنفيذ مهمة هندسية بحجم وتعقيد المشروع نفسه، وأن يستهدف مستوى أقوى من الأنظمة الموجودة في السوق.**

This is not a slogan — it is the **final acceptance criterion** for the entire system.

### 1.2 Target System: Engineering Execution Factory
Not a chatbot. Not an agent framework. A **factory** that:
- Accepts massive engineering missions
- Decomposes into verifiable tasks
- Executes in isolated sandboxes
- Verifies by evidence (not claims)
- Recovers from failures autonomously
- Resumes after crashes
- Requires human decisions only at genuine architectural forks

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            USER INTERFACE LAYER                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Dashboard  │  │    CLI      │  │   API       │  │  Owner Callbacks │  │
│  │  (WebSocket)│  │  (Typer)    │  │  (FastAPI)  │  │  (Grants/Push)   │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘  │
└─────────┼────────────────┼────────────────┼──────────────────┼────────────┘
          │                │                │                  │
          ▼                ▼                ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        UNIFIED ORCHESTRATOR                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Intake     │  │  Plan/      │  │  Schedule/  │  │  Observe/        │
│  │  & Parse    │  │  Decompose  │  │  Assign     │  │  Verify/Recover  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │              STATE MACHINE (PlanState + SubVerdicts)                │  │
│  │  RECEIVED → ANALYZING → PLANNING → DESIGNING → REVIEWING →          │  │
│  │  APPROVED → AWAITING_APPROVAL → EXECUTING → EXECUTED →              │  │
│  │  VERIFYING → EVIDENCED → VERIFIED (user only)                       │  │
│  │  ↘ NOT_EVIDENCED → ARBITER → retry/terminate/escalate              │  │
│  │  ↘ FAILED / ESCALATED_TO_HUMAN / STOPPING → STOPPED                │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TASK ENGINE (OrderSpec → Sections)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  OrderSpec  │  │  Section    │  │  Grant      │  │  Dependency      │
│  │  Parser     │  │  Graph/DAG  │  │  Issuer     │  │  Resolver        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────────────┘  │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AGENT RUNTIME (7 Roles + Arbiter)                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │EXPLORER │ │ ANALYST │ │ PLANNER │ │DESIGNER │ │REVIEWER │ │IMPLEM-  │  │
│  │         │ │(THINKER)│ │         │ │         │ │         │ │ENTER    │  │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘  │
│       │           │           │           │           │           │        │
│       └───────────┼───────────┼───────────┼───────────┼───────────┘        │
│                   ▼           ▼           ▼           ▼                    │
│            ┌─────────────────────────────────────────────────┐             │
│            │              VERIFIER + ARBITER                  │             │
│            └─────────────────────────────────────────────────┘             │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TOOL RUNTIME (Grants-Gated)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Sandbox    │  │  Filesystem │  │    Git      │  │    Shell         │  │
│  │  Tools      │  │  (Read)     │  │  (Read/Write)│  │  (Sandbox Only)  │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  ALL WRITE OPERATIONS REQUIRE VALID GRANT (HMAC-signed, revocable) │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      EXECUTION SANDBOX (Platform Adapter)                   │
│  ┌──────────────────────────────┐  ┌────────────────────────────────────┐  │
│  │  Linux: LocalSubstrateAdapter │  │  Windows: WindowsExecutorAdapter    │  │
│  │  • user/mount/pid/uts/net ns  │  │  • Windows Job Objects              │  │
│  │  • pivot_root + tmpfs         │  │  • Memory/CPU/Process limits        │  │
│  │  • seccomp deny-list          │  │  • Working directory enforcement    │  │
│  │  • rlimits (AS, NPROC, FSIZE) │  │  • PARTIAL isolation only           │  │
│  │  • NetworkMode.NONE enforced  │  │  • No fs/net isolation              │  │
│  │  • FULL container-class       │  │  • Fallback: subprocess             │  │
│  └──────────────────────────────┘  └────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  COMMON INTERFACE: ExecutionSandbox.execute(request) → Record      │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      ARTIFACT STORE + VERIFICATION LAYER                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │ Evidence    │  │  Artifact   │  │  Verifier   │  │  Owner Gate      │  │
│  │ Record      │  │  Custody    │  │  (evidence  │  │  (human decisions)│
│  │ (sha256)    │  │  (files)    │  │   checks)   │  │                  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. LAYER SPECIFICATIONS

### 3.1 User Interface Layer
| Component | Technology | Responsibility |
|-----------|------------|----------------|
| Dashboard | Single-file HTML + vanilla JS/CSS (Arabic RTL) | Real-time mission visibility, settings, file browser |
| CLI | Typer | Direct mission execution, debugging |
| API | FastAPI + WebSocket | REST + real-time events |
| Owner Callbacks | Python callables | Grant approval, push approval |

### 3.2 Unified Orchestrator Layer
| Component | Responsibility | Key Contracts |
|-----------|----------------|---------------|
| Intake | Parse user request → Mission/Order | `MissionRequest`, `OrderSpec` |
| Planner | Decompose → Task DAG | `TaskGraph`, `TaskNode`, `acceptance_criteria` |
| Scheduler | Topological sort + parallel execution | `TaskDAG`, `ready_tasks()` |
| Assigner | Map tasks → agents via role | `AgentRole` protocol |
| Observer | EventBus subscription, checkpointing | `FactoryEvent`, `Checkpoint` |
| Verifier | Evidence verification orchestration | `VerifierResult`, `ArbiterResult` |
| Recovery | Retry, replan, escalate, resume | `RetryPolicy`, `CheckpointManager` |

### 3.3 Task Engine Layer
| Component | Responsibility |
|-----------|----------------|
| OrderSpec Parser | Parse engineering order text → structured spec |
| Section Graph | Build DAG from sections (dependencies, parallelism) |
| Grant Issuer | Propose → owner signs → HMAC verify → register |
| Dependency Resolver | Topological sort, ready task detection |

### 3.4 Agent Runtime Layer
| Role | Responsibility | Tools | Grants Required |
|------|---------------|-------|-----------------|
| **EXPLORER** | Codebase mapping, deps, patterns | Read, List, Grep, Find, WebSearch | Read-only |
| **ANALYST** | Root cause, risk, impact | Read, LLM | Read-only |
| **PLANNER** | Task decomposition + acceptance criteria | Read, LLM | Read-only |
| **DESIGNER** | Interfaces, schemas, protocols | Read, LLM | Read-only |
| **REVIEWER** | Approve/revise plans (max 3 rounds) | Read, LLM | Read-only |
| **IMPLEMENTER** | Generate code → execute in sandbox → artifacts | Sandbox (write), Read | **Write grants required** |
| **VERIFIER** | Match artifacts → acceptance criteria | Read, Sandbox (verify) | Read-only |
| **ARBITER** | Conflict resolution, retry budget, stagnation | None (logic) | None |

### 3.5 Tool Runtime Layer
| Category | Tools | Isolation | Grants |
|----------|-------|-----------|--------|
| **Sandbox** | `execute_in_sandbox`, `write_artifact`, `verify_artifact` | Full (platform adapter) | Write grants |
| **Filesystem** | Read, List, Grep, Find | Host (read-only) | Read grants |
| **Git** | Branch, Commit, Diff, Status | Host (read), Sandbox (write) | Read/Write grants |
| **Shell** | `run_command` | Sandbox only | Execute grants |

### 3.6 Execution Sandbox Layer
**Protocol:** `ExecutionSandbox` (defined in `src/unified/sandbox.py`)

| Platform | Implementation | Isolation Level | Capabilities |
|----------|---------------|-----------------|--------------|
| **Linux** | `LocalSubstrateAdapter` | FULL (namespaces, seccomp, pivot_root, rlimits, no network) | Container-class |
| **Windows** | `WindowsExecutorAdapter` | PARTIAL (Job Objects: memory, CPU, process limits) | Resource limits only |

**Common Interface:**
```python
class ExecutionSandbox(Protocol):
    async def execute(request: SandboxRequest) -> SandboxExecutionRecord
    async def teardown(sandbox_id: str) -> TeardownEvidence
```

### 3.7 Artifact Store + Verification Layer
| Component | Responsibility |
|-----------|----------------|
| EvidenceRecord | Content-addressable (sha256), tamper-evident |
| ArtifactCustody | Files written to `/artifacts` in sandbox, tracked by hash |
| Verifier | File existence + hash match + acceptance criteria |
| OwnerGate | Human decisions for grants + push approvals |

---

## 4. CONTRACT LAYER (Unified)

### 4.1 Core Contracts (`src/unified/contracts.py`)
All Pydantic v2 models, frozen, validated:

| Contract | Description | Used By |
|----------|-------------|---------|
| `MissionRequest/Response` | User ↔ Orchestrator | API, CLI, Dashboard |
| `OrderSpec` | Parsed engineering order | Task Engine |
| `TaskGraph/TaskNode` | DAG of tasks with dependencies | Scheduler |
| `AgentTask/AgentResult` | Agent execution unit | Agent Runtime |
| `SandboxRequest/Record` | Sandbox execution | Sandbox Layer |
| `ResourceGrant` | HMAC-signed, typed, revocable | Grant System |
| `EvidenceRecord` | sha256 + metadata | Verification |
| `FactoryEvent` | EventBus payload | Observability |
| `PlanState` | 13 honest states + 2 sub-verdicts | State Machine |
| `HumanDecision` | Owner approval/reject/modify | Human Gate |

### 4.2 State Machine (13 States + 2 Sub-Verdicts)
```
RECEIVED
  → ANALYZING (Explorer + Analyst)
  → PLANNING (Planner)
  → DESIGNING (Designer, optional)
  → REVIEWING (Reviewer)
  → APPROVED / REVISE (max 3 cycles → ARBITER)
  → AWAITING_APPROVAL (Human Gate)
  → EXECUTING (Implementer in sandbox)
  → EXECUTED
  → VERIFYING (Verifier)
  → EVIDENCED → VERIFIED (user only)
       ↘ NOT_EVIDENCED → ARBITER
            ↘ retry_with_constraints (1x) → EXECUTING
            ↘ terminate_stagnant → ESCALATED_TO_HUMAN
            ↘ escalate_to_human → ESCALATED_TO_HUMAN
  → FAILED (execution failure)
  → STOPPING → STOPPED (Order 004, snapshot for resume)
```
**Terminal:** VERIFIED, FAILED, ESCALATED_TO_HUMAN, STOPPED

**Golden Rule (enforced):** `VERIFIED` only by `actor == "user"`

---

## 5. DATA FLOW

### 5.1 Mission Flow (AgentFactory path)
```
User Request
  → MissionRequest
  → UnifiedOrchestrator.intake()
  → Mission (RECEIVED)
  → Explorer → Analyst → Planner → Designer → Reviewer
  → (max 3 review cycles, Arbiter on deadlock)
  → AWAITING_APPROVAL → HumanDecision
  → Implementer (in sandbox) → artifacts
  → Verifier → EVIDENCED / NOT_EVIDENCED
  → (if NOT_EVIDENCED → Arbiter → retry/escalate)
  → VERIFIED (user) → COMPLETED
```

### 5.2 Order Flow (EAS v2 path)
```
Engineering Order Text
  → parse_order() → OrderSpec
  → check_baseline() → HEAD == origin/main
  → issue_grants() → owner signs HMAC
  → for each section:
      → AccessAdmission.validate(grant)
      → ExecutionEngine.execute() → Sandbox
      → ProofBattery.verify(pre/post)
  → maybe_push() → owner signs push
  → build_report() → Report (VERDICT, HARD_STOPS, etc.)
```

---

## 6. SECURITY MODEL

### 6.1 Grant System (EAS v2 — adopted as standard)
- **Typed**: One permission class per grant (read/write/execute per domain)
- **Scoped**: Domains + explicit resource references (absolute paths)
- **Signed**: HMAC-SHA256 by grantor (key never in repo)
- **Expiring**: `issued_at ≤ now < expires_at`
- **Revocable**: Live revocation channel required (fail-closed)
- **Validated**: At admission time AND execution time

### 6.2 Isolation Guarantees
| Operation | Isolation | Verification |
|-----------|-----------|--------------|
| Code execution | Sandbox (platform adapter) | Termination record + artifacts |
| File write | Sandbox `/artifacts` only | sha256 custody log |
| Git push | Owner-signed nonce + approval | Certificate in report |
| Shell command | Sandbox only (never host) | Exit code + stdout/stderr refs |

### 6.3 Credential Handling
- **No keys in repo** — env vars only at runtime
- **Grants replace API keys** for internal operations
- **Owner callbacks** for signing (keys in owner memory only)

---

## 7. OBSERVABILITY MODEL

### 7.1 Event Types (FactoryEvent)
| Event | Payload | Emitted By |
|-------|---------|------------|
| `mission.started` | mission_id, task | Orchestrator |
| `section.start` | section_id, grants | Task Engine |
| `agent.started` | agent_type, task_id | Agent Runtime |
| `tool.started` | tool_name, sandbox_id | Tool Runtime |
| `tool.completed` | result, evidence_hash | Tool Runtime |
| `verification.complete` | verdict, missing | Verifier |
| `arbiter.decided` | decision, budget | Arbiter |
| `human.required` | reason, options | Human Gate |
| `mission.completed` | verdict, artifacts | Orchestrator |
| `hard_stop.fired` | reason, detail | EOE Engine |

### 7.2 Metrics (TokenBudget + Prometheus)
| Metric | Scope | Purpose |
|--------|-------|---------|
| `tokens_used` | agent / mission / project / global | Cost control |
| `mission_duration_seconds` | mission | Performance |
| `agent_execution_seconds` | agent | Bottleneck detection |
| `sandbox_execution_seconds` | sandbox | Resource usage |
| `verification_failures` | mission | Quality signal |
| `retry_count` | mission | Stability signal |

---

## 8. DEPLOYMENT ARCHITECTURE

### 8.1 Local Development
```
┌────────────────────────────────────────────────────────────┐
│                    Single Process (asyncio)                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ FastAPI  │ │ WebSocket│ │ Orchest. │ │ EventBus     │  │
│  │  :8080   │ │  :8768   │ │          │ │ (in-memory)  │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  SQLite (per-mission) + JSON (checkpoints/convs)    │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### 8.2 Production (Future)
```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  API Gateway    │   │  Orchestrator   │   │  Sandbox Pool   │
│  (stateless)    │◄──►│  (stateful)     │◄──►│  (Linux/Windows)│
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         ▼                     ▼                     ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  PostgreSQL     │   │  Redis/Queue    │   │  Object Storage │
│  (missions,     │   │  (tasks,        │   │  (artifacts,    │
│   checkpoints)  │   │   events)       │   │   evidence)     │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

---

## 9. MIGRATION STRATEGY (from D0 Discovery)

### 9.1 Phase 0: Foundation (THIS PHASE - E1)
- Unified contracts (`src/unified/contracts.py`)
- LLM Gateway (`src/unified/llm_gateway.py`)
- Sandbox Interface (`src/unified/sandbox.py`)
- Agent Role Protocol (`src/unified/agent_role.py`)

### 9.2 Phase 1: Unified Orchestrator
- Single orchestrator using `PlanState` machine
- Resume from `STOPPED` + checkpoints
- Mission tracking from AgentFactory + state machine from EAS v2

### 9.3 Phase 2: Task Engine + Grants
- OrderSpec parser + Section DAG
- Grant issuance + validation (admission + execution)
- Cross-platform sandbox adapter factory

### 9.4 Phase 3-10: Progressive Capability
(See Roadmap in `execution_tracker.json`)

---

## 10. ARCHITECTURAL PRINCIPLES (Enforced)

| Principle | Enforcement |
|-----------|-------------|
| **Honest states** | No `SUCCESS` — only `EXECUTED ≠ EVIDENCED ≠ VERIFIED` |
| **Fail-closed** | Every gate rejects by default with machine-readable reason |
| **Grants for writes** | No write operation without valid HMAC-signed grant |
| **Evidence over claims** | Verifier checks file existence + hash, not agent output |
| **Human decides VERIFIED** | Code enforces `actor == "user"` for VERIFIED transition |
| **No silent degradation** | Missing substrate → hard stop with reason |
| **Single execution per ID** | Sandbox ID uniqueness enforced |
| **Durable state** | Checkpoints + STOPPED snapshot for resume |

---

## 11. DECISION LOG (ADR Index)

| ADR | Title | Status | Link |
|-----|-------|--------|------|
| ADR-001 | Consolidate on EAS v2 architecture | PROPOSED | `adr/001_consolidate_eas_v2.md` |
| ADR-002 | Unified LLM Gateway (UnifiedLLMClient + ModelRouter) | PROPOSED | `adr/002_llm_gateway.md` |
| ADR-003 | Cross-platform sandbox abstraction | PROPOSED | `adr/003_sandbox_interface.md` |
| ADR-004 | Grants for all write operations | PROPOSED | `adr/004_grants_for_writes.md` |
| ADR-005 | State machine: PlanState + SubVerdicts | PROPOSED | `adr/005_state_machine.md` |
| ADR-006 | Resume from STOPPED + checkpoints | PROPOSED | `adr/006_resume_capability.md` |
| ADR-007 | Dashboard as unified UI | PROPOSED | `adr/007_dashboard_ui.md` |

---

## 12. APPENDIX: D0 EVIDENCE SUMMARY

| Finding | Evidence | Classification |
|---------|----------|----------------|
| Two independent systems | `src/factory/` vs `src/core/` — zero shared imports | OBSERVED |
| AgentFactory works on Windows | 112/115 tests pass | VERIFIED |
| EAS v2 requires Linux | `SubstrateUnavailable` on Windows | VERIFIED |
| AgentFactory: partial isolation | `WindowsExecutor` Job Objects only | OBSERVED |
| EAS v2: full isolation | `LocalSubstrateAdapter` namespaces/seccomp | OBSERVED (Linux only) |
| No shared contracts | Different `MissionState` vs `PlanState` | OBSERVED |
| No shared LLM gateway | `UnifiedLLMClient` vs `ModelRouter` | OBSERVED |
| 8 agents vs 5 roles | Different contracts, different execution | OBSERVED |
| AgentFactory: no grants | `grants=None` everywhere | OBSERVED |
| EAS v2: grants enforced | `AccessAdmission` at admission+execution | OBSERVED |
| EAS v2: honest states | `PlanState` enum + `validate_transition()` | VERIFIED |
| AgentFactory: checkpoints exist | `CheckpointManager` + SQLite | OBSERVED |
| No resume logic | Checkpoints saved but never loaded | OBSERVED |

---

**END OF MASTER ARCHITECTURE DOCUMENT**

*This document is the architectural blueprint for the unified Engineering Execution Factory. All implementation phases (E1-E10) derive from this specification.*