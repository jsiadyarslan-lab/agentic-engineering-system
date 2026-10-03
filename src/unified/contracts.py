"""
Unified Contracts — Unified Engineering Agents System

Single source of truth for all Pydantic models used across the system.
Re-exports from domain_model, agent_contract, tool_contract, event_catalog, etc.

This file is the canonical import for all contracts:
    from unified.contracts import Mission, Task, AgentTask, FactoryEvent, ...
"""

from __future__ import annotations

# ============================================================
# DOMAIN MODEL (Core Entities)
# ============================================================
from unified.domain_model import (
    # IDs
    new_mission_id,
    new_run_id,
    new_task_id,
    new_attempt_id,
    new_agent_id,
    new_action_id,
    new_event_id,
    new_grant_id,
    new_sandbox_id,
    new_artifact_id,
    new_evidence_id,
    new_verification_id,
    new_decision_id,
    new_checkpoint_id,
    # Enums
    MissionState,
    SubVerdict,
    TaskState,
    AgentType,
    PermissionClass,
    EngineeringDomain,
    EventType,
    SandboxTermination,
    VerifierVerdict,
    ArbiterDecision,
    HumanDecisionType,
    # Entities
    Mission,
    Run,
    Task,
    Attempt,
    Action,
    Agent,
    Grant,
    SandboxRequest,
    SandboxExecutionRecord,
    Artifact,
    EvidenceRecord,
    Verification,
    ArbiterRecord,
    HumanDecision,
    Checkpoint,
    # Factories
    create_mission,
    create_run,
    create_task,
    create_attempt,
    create_action,
    create_artifact,
    create_evidence,
    create_verification,
    create_arbiter_record,
    # Validation
    validate_mission_transition,
    validate_task_transition,
)

# ============================================================
# STATE MACHINE
# ============================================================
from unified.state_machine import (
    PlanState,
    SubVerdict as StateSubVerdict,
    TERMINAL_STATES,
    TRANSITIONS,
    StateTransitionError,
    validate_transition,
    allowed_targets,
    is_terminal,
    is_sub_verdict,
    MissionStateMachine,
    TaskState as StateTaskState,
    TASK_TRANSITIONS,
    TASK_TERMINAL,
    validate_task_transition as validate_state_task_transition,
    StateTransitionRecord,
    MissionStateSnapshot,
)

# ============================================================
# EVENT CATALOG
# ============================================================
from unified.event_catalog import (
    EventType,
    EventMetadata,
    MissionStartedEvent,
    MissionCompletedEvent,
    MissionStateChangedEvent,
    RunStartedEvent,
    PlanCreatedEvent,
    PlanRevisedEvent,
    SectionStartEvent,
    SectionCompleteEvent,
    AgentStartedEvent,
    AgentCompletedEvent,
    AgentFailedEvent,
    AgentSelectedEvent,
    TaskCreatedEvent,
    TaskAssignedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskRetryEvent,
    ToolStartedEvent,
    ToolCompletedEvent,
    ToolFailedEvent,
    ArtifactCreatedEvent,
    EvidenceRecordedEvent,
    VerificationCompleteEvent,
    VerificationStartedEvent,
    LLMRequestedEvent,
    LLMCompletedEvent,
    ActionRequestedEvent,
    ActionValidatedEvent,
    ArbiterCalledEvent,
    ArbiterDecidedEvent,
    HumanRequiredEvent,
    HumanDecisionEvent,
    GrantIssuedEvent,
    GrantValidatedEvent,
    SandboxStartedEvent,
    SandboxCompletedEvent,
    CheckpointCreatedEvent,
    HardStopFiredEvent,
    TokenUsageEvent,
    BudgetWarningEvent,
    SystemErrorEvent,
    EVENT_PAYLOAD_MODELS,
    FactoryEvent,
    EventBusInterface,
    EventStoreInterface,
    EventCatalogEntry,
    EVENT_CATALOG,
    EVENT_CONSUMERS,
    get_event_payload_model,
    get_event_consumers,
    get_event_catalog_entry,
    validate_event_payload,
    list_all_events,
    # E11: Human Mission Control events
    MissionPauseRequestedEvent,
    MissionPausedEvent,
    MissionResumeRequestedEvent,
    MissionResumedEvent,
    MissionCancelRequestedEvent,
    MissionCancelledEvent,
    HumanGateCreatedEvent,
    HumanDecisionRecordedEvent,
    # E13: Replan events
    ReplanRequestedEvent,
    ReplanAppliedEvent,
)

# ============================================================
# AGENT CONTRACTS
# ============================================================
from unified.agent_contract import (
    AgentRole,
    AgentTask,
    AgentResult,
    # Explorer
    ExplorerInput,
    ExplorationReport,
    # Analyst
    AnalystInput,
    Analysis,
    # Planner
    PlanTask,
    PlannerInput,
    Plan,
    # Designer
    DesignerInput,
    DesignSpec,
    # Reviewer
    ReviewVerdict,
    ReviewInput,
    Review,
    # Implementer
    ImplementerInput,
    ImplementationResult,
    # Verifier
    VerifierInput,
    VerificationResult,
    # Arbiter
    ArbiterInput,
    ArbiterResult,
    # Registry
    AgentContractRegistry,
    # Capabilities
    AgentCapability,
    AGENT_CAPABILITIES,
)

# ============================================================
# AGENT ROLE (E4: Agent Registry & Lifecycle)
# ============================================================
from unified.agent_role import (
    # Lifecycle
    AgentLifecycleState,
    AGENT_LIFECYCLE_TRANSITIONS,
    validate_agent_lifecycle_transition,
    # Definition
    AgentDefinition,
    # Capability (re-export)
    AgentCapability,
    AGENT_CAPABILITIES,
    # Context
    AgentContext,
    # Protocol
    AgentRole,
    # Base
    BaseAgent,
    # Registry
    AgentRegistry,
    agent_registry,
    AgentSelectionError,
    # Factory
    AgentFactory,
    # Adapter
    EASRoleAdapter,
)

# ============================================================
# TOOL CONTRACTS
# ============================================================
from unified.tool_contract import (
    ToolCategory,
    ToolRiskLevel,
    IsolationRequirement,
    ToolInputSchema,
    ToolOutputSchema,
    RetryPolicy,
    ToolContract,
    # Filesystem
    ReadFileInput, ReadFileOutput, READ_FILE_CONTRACT,
    WriteFileInput, WriteFileOutput, WRITE_FILE_CONTRACT,
    EditFileInput, EditFileOutput, EDIT_FILE_CONTRACT,
    ListDirInput, ListDirOutput, LIST_DIR_CONTRACT,
    GrepInput, GrepOutput, GREP_CONTRACT,
    FindFilesInput, FindFilesOutput, FIND_FILES_CONTRACT,
    FileBrowserInput, FileBrowserOutput, FILE_BROWSER_CONTRACT,
    # Shell
    RunCommandInput, RunCommandOutput, RUN_COMMAND_CONTRACT,
    # Git
    GitBranchInput, GitBranchOutput, GIT_BRANCH_CONTRACT,
    GitCommitInput, GitCommitOutput, GIT_COMMIT_CONTRACT,
    GitDiffInput, GitDiffOutput, GIT_DIFF_CONTRACT,
    GitStatusInput, GitStatusOutput, GIT_STATUS_CONTRACT,
    GitPushInput, GitPushOutput, GIT_PUSH_CONTRACT,
    # Web
    WebSearchInput, WebSearchOutput, WEB_SEARCH_CONTRACT,
    WebFetchInput, WebFetchOutput, WEB_FETCH_CONTRACT,
    # Sandbox
    SandboxExecuteInput, SandboxExecuteOutput, SANDBOX_EXECUTE_CONTRACT,
    ArtifactWriteInput, ArtifactWriteOutput, ARTIFACT_WRITE_CONTRACT,
    ArtifactReadInput, ArtifactReadOutput, ARTIFACT_READ_CONTRACT,
    VerificationCheckInput, VerificationCheckOutput, VERIFICATION_CHECK_CONTRACT,
    # Grants
    GrantValidateInput, GrantValidateOutput, GRANT_VALIDATE_CONTRACT,
    # Registry
    ALL_TOOL_CONTRACTS,
    ToolRegistry,
    # Context
    ToolExecutionContext,
    ToolResult,
)

# ============================================================
# VERIFICATION STANDARD
# ============================================================
from unified.verification_standard import (
    CriterionType,
    VerificationMethod,
    AcceptanceCriterion,
    CheckResult,
    VerificationReport,
    EvidenceStore,
    Verifier,
    compute_sha256,
    compute_file_sha256,
    create_evidence_record,
    VERIFICATION_CHECKLIST,
)

# ============================================================
# VERTICAL Slice
# ============================================================
from unified.vertical_slice import (
    VERTICAL_SLICE_NAME,
    VERTICAL_SLICE_ID,
    VERTICAL_SLICE_DESCRIPTION,
    SliceComponent,
    SLICE_COMPONENTS,
    SliceTestStep,
    SLICE_TEST_SCENARIO,
    SLICE_ACCEPTANCE_CRITERIA,
    IMPLEMENTATION_ORDER,
    DEFINITION_OF_DONE,
)

# ============================================================
# SELF-HOSTING BENCHMARK
# ============================================================
from unified.self_hosting_benchmark import (
    BENCHMARK_PHILOSOPHY,
    BenchmarkLevel,
    BenchmarkMission,
    SELF_HOSTING_BENCHMARKS,
    BenchmarkResult,
    SelfHostingBenchmarkRunner,
    CONTINUOUS_BENCHMARK_CONFIG,
)

# ============================================================
# RISK REGISTER (JSON - loaded at runtime)
# ============================================================

def load_risk_register() -> dict:
    """Load risk register from JSON file."""
    import json
    from pathlib import Path
    path = Path(__file__).parent / "risk_register.json"
    with open(path) as f:
        return json.load(f)


def load_adr_index() -> dict:
    """Load ADR index from JSON file."""
    import json
    from pathlib import Path
    path = Path(__file__).parent / "adr_index.json"
    with open(path) as f:
        return json.load(f)


def load_dependency_graph() -> dict:
    """Load dependency graph from JSON file."""
    import json
    from pathlib import Path
    path = Path(__file__).parent / "dependency_graph.json"
    with open(path) as f:
        return json.load(f)


def load_execution_tracker() -> dict:
    """Load execution tracker from JSON file."""
    import json
    from pathlib import Path
    path = Path(__file__).parent / "execution_tracker.json"
    with open(path) as f:
        return json.load(f)


# ============================================================
# ARCHITECTURE DOCUMENT (Markdown - loaded at runtime)
# ============================================================

def load_architecture() -> str:
    """Load architecture document from markdown file."""
    from pathlib import Path
    path = Path(__file__).parent / "architecture.md"
    with open(path) as f:
        return f.read()


# ============================================================
# VERSION INFO
# ============================================================

__version__ = "1.0.0"
__description__ = "Unified Engineering Agents System - Consolidated Contracts"

# All public exports
__all__ = [
    # Domain Model
    "new_mission_id", "new_run_id", "new_task_id", "new_attempt_id",
    "new_agent_id", "new_action_id", "new_event_id", "new_grant_id",
    "new_sandbox_id", "new_artifact_id", "new_evidence_id",
    "new_verification_id", "new_decision_id", "new_checkpoint_id",
    "MissionState", "SubVerdict", "TaskState", "AgentType",
    "PermissionClass", "EngineeringDomain", "EventType",
    "SandboxTermination", "VerifierVerdict", "ArbiterDecision",
    "HumanDecisionType",
    "Mission", "Run", "Task", "Attempt", "Action", "Agent",
    "Grant", "SandboxRequest", "SandboxExecutionRecord",
    "Artifact", "EvidenceRecord", "Verification", "ArbiterRecord",
    "HumanDecision", "Checkpoint",
    "create_mission", "create_run", "create_task", "create_attempt",
    "create_action", "create_artifact", "create_evidence",
    "create_verification", "create_arbiter_record",
    "validate_mission_transition", "validate_task_transition",
    # State Machine
    "PlanState", "StateSubVerdict", "TERMINAL_STATES", "TRANSITIONS",
    "StateTransitionError", "validate_transition", "allowed_targets",
    "is_terminal", "is_sub_verdict", "MissionStateMachine",
    "StateTaskState", "TASK_TRANSITIONS", "TASK_TERMINAL",
    "validate_state_task_transition", "StateTransitionRecord", "MissionStateSnapshot",
    # Event Catalog
    "EventType", "EventMetadata", "MissionStartedEvent", "MissionCompletedEvent",
    "MissionStateChangedEvent", "RunStartedEvent", "PlanCreatedEvent",
    "PlanRevisedEvent", "SectionStartEvent", "SectionCompleteEvent",
    "AgentStartedEvent", "AgentCompletedEvent", "AgentFailedEvent", "AgentSelectedEvent", "TaskCreatedEvent",
    "TaskAssignedEvent", "TaskCompletedEvent", "TaskFailedEvent", "TaskRetryEvent",
    "ToolStartedEvent", "ToolCompletedEvent", "ToolFailedEvent",
    "ArtifactCreatedEvent", "EvidenceRecordedEvent", "VerificationCompleteEvent",
    "ArbiterCalledEvent", "ArbiterDecidedEvent", "HumanRequiredEvent",
    "HumanDecisionEvent", "GrantIssuedEvent", "GrantValidatedEvent",
    "SandboxStartedEvent", "SandboxCompletedEvent", "CheckpointCreatedEvent",
    "HardStopFiredEvent", "TokenUsageEvent", "BudgetWarningEvent", "SystemErrorEvent",
    "EVENT_PAYLOAD_MODELS", "FactoryEvent", "EventBusInterface", "EventStoreInterface",
    "EventCatalogEntry", "EVENT_CATALOG", "EVENT_CONSUMERS",
    "get_event_payload_model", "get_event_consumers", "get_event_catalog_entry",
    "validate_event_payload", "list_all_events",
    # Agent Contracts
    "AgentRole", "AgentTask", "AgentResult",
    "ExplorerInput", "ExplorationReport",
    "AnalystInput", "Analysis",
    "PlanTask", "PlannerInput", "Plan",
    "DesignerInput", "DesignSpec",
    "ReviewVerdict", "ReviewInput", "Review",
    "ImplementerInput", "ImplementationResult",
    "VerifierInput", "VerificationResult",
    "ArbiterInput", "ArbiterResult",
    "AgentContractRegistry", "AgentCapability", "AGENT_CAPABILITIES",
    # Agent Role (E4)
    "AgentLifecycleState", "AGENT_LIFECYCLE_TRANSITIONS",
    "validate_agent_lifecycle_transition",
    "AgentDefinition",
    "AgentContext",
    "BaseAgent",
    "AgentRegistry", "agent_registry", "AgentSelectionError",
    "AgentFactory",
    "EASRoleAdapter",
    # Tool Contracts
    "ToolCategory", "ToolRiskLevel", "IsolationRequirement",
    "ToolInputSchema", "ToolOutputSchema", "RetryPolicy", "ToolContract",
    "ReadFileInput", "ReadFileOutput", "READ_FILE_CONTRACT",
    "WriteFileInput", "WriteFileOutput", "WRITE_FILE_CONTRACT",
    "EditFileInput", "EditFileOutput", "EDIT_FILE_CONTRACT",
    "ListDirInput", "ListDirOutput", "LIST_DIR_CONTRACT",
    "GrepInput", "GrepOutput", "GREP_CONTRACT",
    "FindFilesInput", "FindFilesOutput", "FIND_FILES_CONTRACT",
    "FileBrowserInput", "FileBrowserOutput", "FILE_BROWSER_CONTRACT",
    "RunCommandInput", "RunCommandOutput", "RUN_COMMAND_CONTRACT",
    "GitBranchInput", "GitBranchOutput", "GIT_BRANCH_CONTRACT",
    "GitCommitInput", "GitCommitOutput", "GIT_COMMIT_CONTRACT",
    "GitDiffInput", "GitDiffOutput", "GIT_DIFF_CONTRACT",
    "GitStatusInput", "GitStatusOutput", "GIT_STATUS_CONTRACT",
    "GitPushInput", "GitPushOutput", "GIT_PUSH_CONTRACT",
    "WebSearchInput", "WebSearchOutput", "WEB_SEARCH_CONTRACT",
    "WebFetchInput", "WebFetchOutput", "WEB_FETCH_CONTRACT",
    "SandboxExecuteInput", "SandboxExecuteOutput", "SANDBOX_EXECUTE_CONTRACT",
    "ArtifactWriteInput", "ArtifactWriteOutput", "ARTIFACT_WRITE_CONTRACT",
    "ArtifactReadInput", "ArtifactReadOutput", "ARTIFACT_READ_CONTRACT",
    "VerificationCheckInput", "VerificationCheckOutput", "VERIFICATION_CHECK_CONTRACT",
    "GrantValidateInput", "GrantValidateOutput", "GRANT_VALIDATE_CONTRACT",
    "ALL_TOOL_CONTRACTS", "ToolRegistry", "ToolExecutionContext", "ToolResult",
    # Verification Standard
    "CriterionType", "VerificationMethod", "AcceptanceCriterion",
    "CheckResult", "VerificationReport", "EvidenceStore", "Verifier",
    "compute_sha256", "compute_file_sha256", "create_evidence_record",
    "VERIFICATION_CHECKLIST",
    # Vertical Slice
    "VERTICAL_SLICE_NAME", "VERTICAL_SLICE_ID", "VERTICAL_SLICE_DESCRIPTION",
    "SliceComponent", "SLICE_COMPONENTS", "SliceTestStep", "SLICE_TEST_SCENARIO",
    "SLICE_ACCEPTANCE_CRITERIA", "IMPLEMENTATION_ORDER", "DEFINITION_OF_DONE",
    # Self-Hosting Benchmark
    "BENCHMARK_PHILOSOPHY", "BenchmarkLevel", "BenchmarkMission",
    "SELF_HOSTING_BENCHMARKS", "BenchmarkResult", "SelfHostingBenchmarkRunner",
    "CONTINUOUS_BENCHMARK_CONFIG",
    # JSON Loaders
    "load_risk_register", "load_adr_index", "load_dependency_graph",
    "load_execution_tracker", "load_architecture",
    # Version
    "__version__", "__description__",
]