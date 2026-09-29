"""
Vertical Slice Definition — Unified Engineering Agents System

A vertical slice is a minimal end-to-end path through the entire system
that exercises all layers: intake → planning → execution → verification → completion.

This defines the FIRST vertical slice to implement (WS-12 in tracker).
Success criteria: Mission goes from user request to VERIFIED with real artifacts.

Based on: EAS v2 first mission pattern + AgentFactory CLI flow
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


# ============================================================
# VERTICAL SLICE SCOPE
# ============================================================

VERTICAL_SLICE_NAME = "Hello World File Creation"
VERTICAL_SLICE_ID = "VS-001"

VERTICAL_SLICE_DESCRIPTION = """
Create a single file (hello.txt) with content "Hello, World!" in the workspace.
This exercises: intake → planner (1 task) → implementer (sandbox write) → verifier (file exists + content) → human approval → VERIFIED.
"""

# What this slice TESTS (not just demonstrates):
# - Mission intake and state machine (RECEIVED → ANALYZING → PLANNING → ... → VERIFIED)
# - LLM Gateway: Planner generates plan, Implementer generates code
# - Sandbox: Implementer runs in sandbox, writes to /artifacts
# - Grants: Implementer needs write grant, validated at admission + execution
# - Evidence: Artifact created with sha256, EvidenceRecord created
# - Verification: Verifier checks file_exists + file_contains criteria
# - Human Gate: AWAITING_APPROVAL → user approves → VERIFIED
# - Events: All FactoryEvents emitted and received by Dashboard
# - Checkpoint: Created at each state transition
# - Resume: Stop at AWAITING_APPROVAL, resume after approval


# ============================================================
# SLICE COMPONENTS
# ============================================================

@dataclass
class SliceComponent:
    """A component required for the vertical slice."""
    name: str
    module: str
    status: str  # "existing" | "new" | "adapter"
    description: str
    dependencies: List[str] = field(default_factory=list)


SLICE_COMPONENTS = [
    # Intake
    SliceComponent(
        name="Mission Intake",
        module="src/factory/orchestrator.py",
        status="existing",
        description="Orchestrator.create_mission() - creates Mission from user request",
        dependencies=["UnifiedLLMClient"],
    ),
    SliceComponent(
        name="State Machine",
        module="src/unified/state_machine.py",
        status="new",
        description="MissionStateMachine validates transitions through 13 states",
        dependencies=["domain_model.py"],
    ),

    # Planning (1 task)
    SliceComponent(
        name="Planner Agent",
        module="src/roles/planner.py",
        status="adapter",
        description="EAS v2 Thinker adapted to AgentRole protocol. Generates Plan with 1 PlanTask",
        dependencies=["UnifiedLLMClient", "agent_contract.py"],
    ),
    SliceComponent(
        name="Planner Contract",
        module="src/unified/agent_contract.py",
        status="new",
        description="PlannerInput → Plan output validation with acceptance criteria",
        dependencies=["domain_model.py"],
    ),

    # Execution
    SliceComponent(
        name="Implementer Agent",
        module="src/roles/implementer.py",
        status="adapter",
        description="EAS v2 Implementer adapted. Runs in sandbox, writes hello.txt",
        dependencies=["UnifiedLLMClient", "sandbox.py", "grants.py"],
    ),
    SliceComponent(
        name="Sandbox Execution",
        module="src/core/windows_executor.py",
        status="existing",
        description="WindowsExecutorAdapter runs command in Job Object isolation",
        dependencies=["grants.py"],
    ),
    SliceComponent(
        name="Grant Validation",
        module="src/core/grants.py",
        status="existing",
        description="AccessAdmission validates write grant at admission + execution",
        dependencies=["domain_model.py"],
    ),

    # Evidence & Verification
    SliceComponent(
        name="Artifact Collection",
        module="src/core/artifacts.py",
        status="existing",
        description="Collects /artifacts/hello.txt, computes sha256, creates EvidenceRecord",
        dependencies=["domain_model.py"],
    ),
    SliceComponent(
        name="Verifier Agent",
        module="src/roles/verifier.py",
        status="adapter",
        description="EAS v2 Verifier adapted. Mechanical check: file_exists + file_contains 'Hello, World!'",
        dependencies=["verification_standard.py", "agent_contract.py"],
    ),

    # Human Gate
    SliceComponent(
        name="Human Gate",
        module="src/core/human_gate.py",
        status="existing",
        description="Requests approval at AWAITING_APPROVAL, blocks until user decision",
        dependencies=["event_catalog.py", "state_machine.py"],
    ),
    SliceComponent(
        name="Dashboard Approval",
        module="src/factory/events/dashboard.html",
        status="existing",
        description="Web UI shows approval request, user clicks Approve → VERIFIED",
        dependencies=["ws_server.py", "contracts.py"],
    ),

    # Observability
    SliceComponent(
        name="Event Bus",
        module="src/factory/events/ws_server.py",
        status="existing",
        description="In-process pub/sub + WebSocket bridge to Dashboard",
        dependencies=["event_catalog.py"],
    ),
    SliceComponent(
        name="Checkpoint Manager",
        module="src/core/checkpoints.py",
        status="existing",
        description="Creates checkpoint at each state transition for resume",
        dependencies=["domain_model.py"],
    ),
]


# ============================================================
# SLICE TEST SCENARIO
# ============================================================

@dataclass
class SliceTestStep:
    """A step in the vertical slice test."""
    step: int
    name: str
    action: str
    expected_state: str
    expected_events: List[str]
    verification: str


SLICE_TEST_SCENARIO: List[SliceTestStep] = [
    SliceTestStep(
        step=1,
        name="Mission Intake",
        action="POST /missions with request 'Create hello.txt with Hello World'",
        expected_state="RECEIVED",
        expected_events=["mission.started"],
        verification="Mission created with mission_id, state=RECEIVED",
    ),
    SliceTestStep(
        step=2,
        name="Analysis (Auto-skip)",
        action="Orchestrator transitions to ANALYZING → PLANNING",
        expected_state="PLANNING",
        expected_events=["mission.state_changed", "section.start"],
        verification="State machine allows RECEIVED→ANALYZING→PLANNING",
    ),
    SliceTestStep(
        step=3,
        name="Planner Generates Plan",
        action="Planner agent executes, returns Plan with 1 task",
        expected_state="PLANNING",
        expected_events=["plan.created", "agent.started", "agent.completed"],
        verification="Plan has 1 task: agent_type=IMPLEMENTER, acceptance_criteria=[file_exists, file_contains]",
    ),
    SliceTestStep(
        step=4,
        name="Review (Auto-approve)",
        action="Reviewer auto-approves simple plan",
        expected_state="APPROVED",
        expected_events=["plan.approved", "mission.state_changed"],
        verification="Review verdict=approved, no required_changes",
    ),
    SliceTestStep(
        step=5,
        name="Human Approval Gate",
        action="Orchestrator transitions to AWAITING_APPROVAL",
        expected_state="AWAITING_APPROVAL",
        expected_events=["human.required"],
        verification="Dashboard shows approval request with plan summary",
    ),
    SliceTestStep(
        step=6,
        name="User Approves",
        action="User clicks Approve on Dashboard",
        expected_state="EXECUTING",
        expected_events=["human.decision", "mission.state_changed"],
        verification="HumanDecision.decision_type=APPROVE, approved=true",
    ),
    SliceTestStep(
        step=7,
        name="Implementer Runs in Sandbox",
        action="Implementer agent executes task in sandbox",
        expected_state="EXECUTING",
        expected_events=["agent.started", "tool.started", "tool.completed", "sandbox.started", "sandbox.completed"],
        verification="SandboxExecutionRecord: exit_code=0, artifacts=[hello.txt], sha256=...",
    ),
    SliceTestStep(
        step=8,
        name="Artifact Collection",
        action="System collects artifacts from sandbox /artifacts",
        expected_state="EXECUTING",
        expected_events=["artifact.created", "evidence.recorded"],
        verification="Artifact hello.txt exists with correct sha256, EvidenceRecord created",
    ),
    SliceTestStep(
        step=9,
        name="Verification",
        action="Verifier checks acceptance criteria",
        expected_state="VERIFYING",
        expected_events=["verification.started", "verification.complete"],
        verification="VerificationReport: verdict=evidenced, checks=[file_exists:pass, file_contains:pass]",
    ),
    SliceTestStep(
        step=10,
        name="EVIDENCED State",
        action="Orchestrator transitions to EVIDENCED",
        expected_state="EVIDENCED",
        expected_events=["mission.state_changed"],
        verification="State machine allows VERIFYING→EVIDENCED",
    ),
    SliceTestStep(
        step=11,
        name="Human Final Verification",
        action="User reviews evidence, clicks Verify",
        expected_state="VERIFIED",
        expected_events=["human.decision", "mission.completed"],
        verification="VERIFIED only by actor=user (golden rule). Mission.completed event emitted.",
    ),
]


# ============================================================
# ACCEPTANCE CRITERIA FOR SLICE COMPLETION
# ============================================================

SLICE_ACCEPTANCE_CRITERIA = [
    # Functional
    "Mission reaches VERIFIED state with user approval",
    "hello.txt created in workspace with exact content 'Hello, World!'",
    "File sha256 matches evidence record",
    "All 11 test steps pass in sequence",

    # State Machine
    "All state transitions validated by MissionStateMachine",
    "No invalid transitions possible",
    "VERIFIED only by actor='user' enforced",

    # LLM Gateway
    "Planner uses UnifiedLLMClient.structured_chat() with Plan schema",
    "Implementer uses UnifiedLLMClient for code generation",
    "Retry policy handles transient failures",

    # Sandbox
    "Implementer runs in WindowsExecutorAdapter (Job Object)",
    "Write grant validated at admission AND execution",
    "No host filesystem writes - all via sandbox /artifacts",
    "NetworkMode.NONE enforced",

    # Grants
    "Write grant issued for workspace path",
    "Grant HMAC signature verified",
    "Grant expires, not perpetual",

    # Evidence
    "Artifact collected with sha256",
    "EvidenceRecord created with content hash",
    "Verification checks hash, not filesystem path",

    # Verification
    "Verifier uses mechanical checks only (no LLM)",
    "file_exists criterion passes",
    "file_contains 'Hello, World!' criterion passes",
    "Sub-verdict NOT_EVIDENCED not triggered",

    # Events
    "All expected FactoryEvents emitted",
    "Dashboard receives events via WebSocket",
    "EventStore persists all events",

    # Checkpoint/Resume
    "Checkpoint created at AWAITING_APPROVAL",
    "Resume from checkpoint creates new run with parent_run_id",
    "State restored correctly",

    # No Mock
    "Zero mock providers in execution path",
    "Real LLM provider used (Ollama or API)",
    "Tests skip if no provider configured",
]


# ============================================================
# IMPLEMENTATION ORDER (Dependency Topological Sort)
# ============================================================

IMPLEMENTATION_ORDER = [
    # Phase 0: Foundation (WS-01 to WS-05)
    {
        "phase": 0,
        "name": "Foundation",
        "tasks": [
            "domain_model.py - All entities and IDs",
            "state_machine.py - 13 states + validation",
            "contracts.py - Unified Pydantic models (re-exports)",
            "event_catalog.py - Event types and FactoryEvent",
            "agent_contract.py - AgentRole protocol + contracts",
            "tool_contract.py - Tool contracts + registry",
            "verification_standard.py - Mechanical verifier",
            "llm_gateway.py - UnifiedLLMClient wrapper",
            "sandbox.py - ExecutionSandbox protocol",
            "agent_role.py - AgentRole protocol (unified)",
        ],
    },
    # Phase 1: Orchestrator Integration (WS-06)
    {
        "phase": 1,
        "name": "Orchestrator Integration",
        "tasks": [
            "orchestrator.py - UnifiedOrchestrator with state machine",
            "mission_manager.py - Mission/Run/Task lifecycle",
            "task_engine.py - Task graph execution",
            "agent_runtime.py - AgentRole execution wrapper",
        ],
    },
    # Phase 2: Role Adapters (WS-10)
    {
        "phase": 2,
        "name": "Role Adapters",
        "tasks": [
            "planner_adapter.py - Thinker → AgentRole",
            "implementer_adapter.py - Implementer → AgentRole",
            "verifier_adapter.py - Verifier → AgentRole",
            "reviewer_adapter.py - Reviewer → AgentRole",
            "analyst_adapter.py - Thinker → AgentRole (analysis)",
            "designer_adapter.py - Designer → AgentRole",
            "explorer_adapter.py - Explorer → AgentRole",
            "arbiter_adapter.py - Arbiter → AgentRole",
        ],
    },
    # Phase 3: Human Gate + Dashboard (WS-12 prep)
    {
        "phase": 3,
        "name": "Human Gate + Dashboard",
        "tasks": [
            "human_gate_integration.py - AWAITING_APPROVAL flow",
            "dashboard_approval.py - WebSocket approval handler",
            "cli_approve.py - CLI approval command",
        ],
    },
    # Phase 4: Vertical Slice Test (WS-12)
    {
        "phase": 4,
        "name": "Vertical Slice Test",
        "tasks": [
            "test_vertical_slice.py - End-to-end test",
            "test_resume.py - Checkpoint resume test",
            "test_no_mock.py - Verify no mock in path",
        ],
    },
]


# ============================================================
# DEFINITION OF DONE
# ============================================================

DEFINITION_OF_DONE = """
VERTICAL SLICE VS-001 COMPLETE WHEN:

1. CODE COMPLETE
   □ All SLICE_COMPONENTS implemented and wired
   □ IMPLEMENTATION_ORDER phases 0-3 done
   □ No TODOs in slice path code

2. TESTS PASS
   □ test_vertical_slice.py passes (all 11 steps)
   □ test_resume.py passes (stop at AWAITING_APPROVAL, resume, verify)
   □ test_no_mock.py passes (grep -r mock src --include="*.py" = only comments)
   □ Existing factory tests pass (112 tests)
   □ Existing EAS v2 contract tests pass (112 tests, excluding Windows substrate)

3. EVIDENCE PRODUCED
   □ hello.txt artifact with correct sha256
   □ EvidenceRecord for artifact
   □ VerificationReport with verdict=evidenced
   □ HumanDecision with decision_type=APPROVE
   □ Complete event timeline in EventStore

4. DOCUMENTATION
   □ Vertical slice run recorded in execution_tracker.json
   □ Any new ADRs added to adr_index.json
   □ Risk register updated if new risks found

5. DEMO READY
   □ python -m src.factory.api_server starts cleanly
   □ Dashboard at http://localhost:8080 shows mission
   □ WebSocket at ws://127.0.0.1:8768 streams events
   □ User can approve via Dashboard and see VERIFIED
"""


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "VERTICAL_SLICE_NAME",
    "VERTICAL_SLICE_ID",
    "VERTICAL_SLICE_DESCRIPTION",
    "SliceComponent",
    "SLICE_COMPONENTS",
    "SliceTestStep",
    "SLICE_TEST_SCENARIO",
    "SLICE_ACCEPTANCE_CRITERIA",
    "IMPLEMENTATION_ORDER",
    "DEFINITION_OF_DONE",
]