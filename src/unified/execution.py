"""
Unified Execution Engine — Unified Engineering Agents System
Orchestrates the complete execution loop:
MISSION → RUN → TASK → AGENT → ACTION → TOOL → SANDBOX → ARTIFACT → EVIDENCE → VERIFICATION → STATE → EVENTS
Provides:
- Mission lifecycle management
- Run creation and tracking
- Task scheduling and execution
- Agent role execution
- Tool invocation with sandbox
- Artifact capture and evidence chain
- Mechanical verification
- State machine transitions
- Event emission
- Checkpoint and resume
"""
from __future__ import annotations
import asyncio
import os
import json
import hashlib
import shutil
import subprocess  # E10-RP2.2-R2 §3.1 (DF1): the git family implementation
                   # needs subprocess — previously NEVER imported, so every
                   # git call crashed NameError AFTER passing authorization
                   # (fail-closed by crash, not by design). This import ships
                   # IN THE SAME CHANGE as the git authorization grounding
                   # (order E10-RP2.2-R2 §3: the fix may NOT land alone).
import secrets  # E10-RP2.2-R2A1 §2: one-shot resume ticket ids (engine-internal)
import time  # E10-RP2.2-R2A1 §2: resume ticket TTL clock
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
# Import DependencyState locally to avoid circular import
from unified.contracts import (
    # IDs
    new_mission_id, new_run_id, new_task_id, new_attempt_id,
    new_agent_id, new_action_id, new_event_id, new_grant_id,
    new_sandbox_id, new_artifact_id, new_evidence_id,
    new_verification_id, new_checkpoint_id,
    # Enums
    MissionState, PlanState, TaskState, AgentType, EventType,
    SandboxTermination, VerifierVerdict, SubVerdict,
    ToolRiskLevel, IsolationRequirement,
    # Entities
    Mission, Run, Task, Attempt, Action, Agent, Grant,
    SandboxRequest, SandboxExecutionRecord, Artifact, EvidenceRecord,
    Verification, Checkpoint,
    # Factories
    create_mission, create_run, create_task, create_attempt,
    create_action, create_artifact, create_evidence,
    create_verification,
    # Validation
    validate_mission_transition, validate_task_transition,
    # State Machine
    PlanState as StatePlanState, MissionStateMachine, validate_transition,
    TERMINAL_STATES, TRANSITIONS,
    # Agent Contracts
    AgentRole, AgentTask, AgentResult,
    PlanTask, PlannerInput, Plan,
    ImplementerInput, ImplementationResult,
    VerifierInput, VerificationResult,
    AgentContractRegistry, AGENT_CAPABILITIES,
    # Tool Contracts
    ToolContract, ToolRegistry, ToolExecutionContext, ToolResult,
    RUN_COMMAND_CONTRACT, SANDBOX_EXECUTE_CONTRACT,
    ARTIFACT_WRITE_CONTRACT, ARTIFACT_READ_CONTRACT,
    VERIFICATION_CHECK_CONTRACT,
    # Verification
    CriterionType, AcceptanceCriterion, CheckResult, VerificationReport,
    EvidenceStore, Verifier, compute_sha256, create_evidence,
    # Event Catalog
    FactoryEvent, EVENT_CATALOG, EVENT_CONSUMERS,
    MissionStartedEvent, RunStartedEvent, PlanCreatedEvent,
    AgentStartedEvent, AgentCompletedEvent, TaskFailedEvent, TaskRetryEvent, TaskCompletedEvent,
    TaskAssignedEvent, AgentSelectedEvent,
    ToolStartedEvent, ToolCompletedEvent, ToolFailedEvent,
    ArtifactCreatedEvent, ArtifactReconciledEvent, EvidenceRecordedEvent,
    VerificationCompleteEvent, CheckpointCreatedEvent,
    MissionStateChangedEvent, MissionCompletedEvent,
    ActionRequestedEvent, ActionValidatedEvent,
    # E11: Human Mission Control events
    MissionPauseRequestedEvent,
    MissionPausedEvent,
    MissionResumeRequestedEvent,
    MissionResumedEvent,
    MissionCancelRequestedEvent,
    MissionCancelledEvent,
    HumanGateCreatedEvent,
    HumanDecisionRecordedEvent,
    HumanDecisionRejectedEvent,
    # E13: Replan events
    ReplanRequestedEvent,
    ReplanAppliedEvent,
    TaskCreatedEvent,
)
from unified.agent_role import (
    AgentCapability, AgentContext, AgentRegistry, agent_registry,
    AgentFactory, BaseAgent, AgentSelectionError, AgentLifecycleState,
)
from unified.sandbox import (
    ExecutionSandbox, SandboxBackend, SandboxManager,
    SandboxError, SandboxUnavailableError, create_sandbox_manager,
)
from unified.windows_adapter import WindowsExecutorAdapter
class ResourceQuotaExceededError(Exception):
    """Raised when resource quota is exceeded."""
    pass


class CheckpointParseError(Exception):
    """E10 section 22: checkpoint file could not be parsed — restore fails closed."""


class CheckpointIntegrityError(Exception):
    """E10-CI-04/05: checkpoint integrity hash mismatch — resume must be REJECTED
    and no task execution may start from this checkpoint."""


class ResumeFailedError(Exception):
    """E10 section 22: critical restoration failure (events/evidence/mission/graph/
    state) — resume fails closed with an explicit reason, never best-effort."""


class SideEffectReconciliationError(RuntimeError):
    """E10-CW1: a previously journaled side effect cannot be reconciled safely
    on re-execution (different content for the same logical operation, missing
    file, diverged content, or rewritten file metadata). Fail closed: the side
    effect is neither re-performed nor silently skipped."""
# ============================================================
# EXECUTION CONTEXT
# ============================================================
@dataclass
class ExecutionContext:
    """Complete runtime context for an execution."""
    mission_id: str
    run_id: str
    task_id: str
    attempt_id: str
    agent_id: str
    agent_type: AgentType
    # Grants
    grant_ids: List[str] = field(default_factory=list)
    # Budget
    token_budget: int = 50000
    tokens_used: int = 0
    # Workspace
    workspace_root: str = "."
    sandbox_id: Optional[str] = None
    # Components
    sandbox_manager: Optional[SandboxManager] = None
    tool_executor: Optional['ToolExecutor'] = None  # E9-R: ToolExecutor for governed tool execution
    llm_gateway: Optional[Any] = None  # LLMGateway
    event_emitter: Optional[Callable[[FactoryEvent], None]] = None
    grant_validator: Optional[Callable[[str, str], bool]] = None
    evidence_store: Optional[Any] = None  # FileEvidenceStore
    # State
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Retry support (E15)
    previous_agent_id: Optional[str] = None
# ============================================================
# EVENT BUS (Simple in-memory)
# ============================================================
class SimpleEventBus:
    """Simple in-memory event bus for execution."""
    def __init__(self):
        self._subscribers: List[Callable[[FactoryEvent], None]] = []
        self.history: List[FactoryEvent] = []
    def subscribe(self, callback: Callable[[FactoryEvent], None]) -> None:
        self._subscribers.append(callback)
    def unsubscribe(self, callback: Callable[[FactoryEvent], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    def emit(self, event: FactoryEvent) -> None:
        self.history.append(event)
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception:
                pass  # Best effort
# ============================================================
# EVIDENCE STORE (File-based)
# ============================================================
class FileEvidenceStore(EvidenceStore):
    """File-based evidence store for artifacts and evidence."""
    def __init__(self, artifacts_dir: str):
        self.artifacts_dir = artifacts_dir
        self._artifacts: Dict[str, Artifact] = {}
        self._evidence: Dict[str, EvidenceRecord] = {}
    def store_artifact(self, artifact: Artifact) -> None:
        self._artifacts[artifact.artifact_id] = artifact
    def get_artifact(self, artifact_id: str) -> Optional[bytes]:
        """Get artifact content by ID."""
        return self.read_artifact_content(artifact_id)
    def get_artifact_obj(self, artifact_id: str) -> Optional[Artifact]:
        """Get artifact metadata by ID."""
        return self._artifacts.get(artifact_id)
    def get_artifact_path(self, artifact_id: str) -> Optional[str]:
        art = self._artifacts.get(artifact_id)
        if art:
            return os.path.join(self.artifacts_dir, art.path)
        return None
    def get_artifact_hash(self, artifact_id: str) -> Optional[str]:
        art = self._artifacts.get(artifact_id)
        return art.sha256 if art else None
    def read_artifact_content(self, artifact_id: str) -> Optional[bytes]:
        """Read artifact content from file system."""
        art = self._artifacts.get(artifact_id)
        if not art:
            return None
        # Try direct path first
        path = os.path.join(self.artifacts_dir, art.path)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read()
        # Try sandbox subdirectory (created_by may be sandbox_id)
        if art.created_by:
            path = os.path.join(self.artifacts_dir, art.created_by, art.path)
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    return f.read()
        return None
    def artifact_exists(self, artifact_id: str) -> bool:
        return artifact_id in self._artifacts
    def store_evidence(self, evidence: EvidenceRecord) -> None:
        self._evidence[evidence.evidence_id] = evidence
    def get_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]:
        return self._evidence.get(evidence_id)
    # Persistence methods for cross-runtime durability
    def _get_evidence_store_dir(self, mission_id: str) -> Path:
        """Get evidence store directory for mission."""
        base = Path(self.artifacts_dir) / "evidence_store" / mission_id
        base.mkdir(parents=True, exist_ok=True)
        return base
    def save_to_disk(self, mission_id: str) -> None:
        """Save artifacts and evidence to disk for durability."""
        store_dir = self._get_evidence_store_dir(mission_id)
        # Save artifacts
        artifacts_file = store_dir / "artifacts.json"
        artifacts_data = {}
        for aid, art in self._artifacts.items():
            if art.mission_id == mission_id or (hasattr(art, 'mission_id') and art.mission_id == mission_id):
                artifacts_data[aid] = art.model_dump(mode='json')
        temp_file = artifacts_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(artifacts_data, f, indent=2)
        temp_file.replace(artifacts_file)
        # Save evidence
        evidence_file = store_dir / "evidence.json"
        evidence_data = {}
        for eid, ev in self._evidence.items():
            if ev.mission_id == mission_id or (hasattr(ev, 'mission_id') and ev.mission_id == mission_id):
                evidence_data[eid] = ev.model_dump(mode='json')
        temp_file = evidence_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(evidence_data, f, indent=2)
        temp_file.replace(evidence_file)
    def load_from_disk(self, mission_id: str) -> None:
        """Load artifacts and evidence from disk for cross-runtime resume."""
        store_dir = self._get_evidence_store_dir(mission_id)
        # Load artifacts
        artifacts_file = store_dir / "artifacts.json"
        if artifacts_file.exists():
            with open(artifacts_file, 'r') as f:
                artifacts_data = json.load(f)
            for aid, art_data in artifacts_data.items():
                art = Artifact.model_validate(art_data)
                self._artifacts[aid] = art
        # Load evidence
        evidence_file = store_dir / "evidence.json"
        if evidence_file.exists():
            with open(evidence_file, 'r') as f:
                evidence_data = json.load(f)
            for eid, ev_data in evidence_data.items():
                ev = EvidenceRecord.model_validate(ev_data)
                self._evidence[eid] = ev


# ============================================================
# SIDE-EFFECT JOURNAL (E10-CW1 — crash-window idempotency;
# E10-CW1-R1 — intent-first journaling + pre-journal crash proof)
# ============================================================
class SideEffectJournalCorruptionError(RuntimeError):
    """E10-CW1-R1: the side-effect journal file is structurally or
    semantically corrupted at a NON-TRAILING position. A prior record that
    cannot be parsed/validated may be the only durable proof of a performed
    effect — it must never be silently ignored. Fail closed."""


class SideEffectJournal:
    """Append-only, fsynced journal of governed side effects (artifact writes).

    E10-CW1-R1 intent-first contract. Record types:

    * ``intent``   — durably appended (fsync file + dir) BEFORE the physical
      side effect. Fixes the stable identity of the logical operation:
      mission_id + task_id + path (NEVER attempt_id, which changes on every
      resume) plus the PLANNED artifact id, the content fingerprint (sha256)
      and size. This is the record that lets a later process life recognize
      the SAME logical operation across a crash that happened between the
      intent and the outcome record.
    * ``performed`` — the effect happened and its actual outcome (content
      sha256, size, artifact id, mtime_ns, inode) is now durably recorded.
      ``performed_via`` distinguishes ``direct`` (the recording process also
      performed the write) from ``adopted_after_crash`` (the write happened in
      a prior process life that died between the effect and this record; the
      recording process verified the file against the intent record and
      adopted it WITHOUT rewriting).
    * ``reconciled`` — a resume found an EFFECTIVE (performed/reconciled)
      record and reconciled with it: no rewrite, original identity kept.

    Torn/corrupt-line policy (fail-closed for prior records):
    * a trailing line that fails JSON parsing or semantic validation never
      became durable truth — it is ignored on load and truncated away before
      the next append;
    * a NON-trailing line that fails JSON parsing or semantic validation
      raises SideEffectJournalCorruptionError: it may hide the only proof of
      a proven effect. It is never skipped silently.
    """

    RECORD_TYPES = ("intent", "performed", "reconciled")
    EFFECTIVE_RECORD_TYPES = ("performed", "reconciled")

    _REQUIRED_FIELDS = {
        "intent": ("mission_id", "task_id", "path", "content_sha256",
                   "size_bytes", "artifact_id"),
        "performed": ("mission_id", "task_id", "path", "content_sha256",
                      "size_bytes", "artifact_id", "mtime_ns", "inode"),
        "reconciled": ("mission_id", "task_id", "path", "content_sha256",
                       "artifact_id", "mtime_ns", "inode"),
    }

    def __init__(self, base_dir: str):
        self._base = Path(base_dir)
        # mission_id -> {"effective": {(task_id, path): latest record},
        #                "intent":    {(task_id, path): latest intent record}}
        self._index: Dict[str, Dict[str, Dict[tuple, dict]]] = {}

    def journal_path(self, mission_id: str) -> Path:
        return self._base / "side_effect_journal" / mission_id / "journal.jsonl"

    @classmethod
    def _validate_record(cls, rec: dict) -> bool:
        """Semantic validation of one parsed record against its contract."""
        rt = rec.get("record_type")
        if rt not in cls.RECORD_TYPES:
            return False
        return all(rec.get(f) not in (None, "") for f in cls._REQUIRED_FIELDS[rt])

    def _load(self, mission_id: str) -> Dict[str, Dict[tuple, dict]]:
        if mission_id in self._index:
            return self._index[mission_id]
        effective: Dict[tuple, dict] = {}
        intent: Dict[tuple, dict] = {}
        p = self.journal_path(mission_id)
        if p.exists():
            lines = p.read_text(encoding="utf-8").splitlines()
            last_idx = len(lines) - 1
            for i, raw in enumerate(lines):
                line = raw.strip()
                if not line:
                    continue
                trailing = i == last_idx or all(
                    not l.strip() for l in lines[i + 1:]
                )
                try:
                    rec = json.loads(line)
                    if not isinstance(rec, dict) or not self._validate_record(rec):
                        raise ValueError("semantically invalid journal record")
                except (json.JSONDecodeError, ValueError):
                    if trailing:
                        # Torn/corrupt TRAILING record: it never became
                        # durable truth — ignore it (it is truncated away
                        # before the next append).
                        continue
                    raise SideEffectJournalCorruptionError(
                        f"SIDE_EFFECT_JOURNAL_CORRUPT: journal record "
                        f"{i + 1} of {str(p)} is corrupt — a prior record "
                        f"that cannot be validated may be the only durable "
                        f"proof of a performed effect; refusing to proceed"
                    )
                key = (rec.get("task_id", ""), rec.get("path", ""))
                if rec.get("record_type") == "intent":
                    intent[key] = rec
                elif rec.get("record_type") in self.EFFECTIVE_RECORD_TYPES:
                    effective[key] = rec
        self._index[mission_id] = {"effective": effective, "intent": intent}
        return self._index[mission_id]

    def lookup(self, mission_id: str, task_id: str, path: str) -> Optional[dict]:
        """Latest EFFECTIVE record (performed/reconciled) for the operation."""
        return self._load(mission_id)["effective"].get((task_id, path))

    def lookup_intent(self, mission_id: str, task_id: str, path: str) -> Optional[dict]:
        """Latest INTENT record for the operation (pre-effect identity)."""
        return self._load(mission_id)["intent"].get((task_id, path))

    def _truncate_torn_tail(self, p: Path) -> bool:
        """Remove a torn/partial trailing line before appending. Returns True
        if bytes were truncated. The torn tail never became durable truth;
        removing it keeps every subsequent line non-trailing and reloadable."""
        if not p.exists():
            return False
        data = p.read_bytes()
        cut = data.rfind(b"\n")
        if cut != len(data) - 1:  # bytes after the last newline = torn tail
            with open(p, "r+b") as f:
                f.truncate(cut + 1 if cut >= 0 else 0)
                f.flush()
                os.fsync(f.fileno())
            return True
        return False

    def append(self, mission_id: str, record: dict) -> None:
        """Append one record; flush + fsync the file, then fsync the dir."""
        p = self.journal_path(mission_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        if self._truncate_torn_tail(p):
            # the repaired file may have changed what the in-memory index
            # believes about torn tails — rebuild from the repaired file
            self._index.pop(mission_id, None)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        fd = os.open(str(p.parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        idx = self._load(mission_id)
        key = (record.get("task_id", ""), record.get("path", ""))
        if record.get("record_type") == "intent":
            idx["intent"][key] = record
        elif record.get("record_type") in self.EFFECTIVE_RECORD_TYPES:
            idx["effective"][key] = record


# ============================================================
# TOOL EXECUTOR (E9 - Execution Fabric)
# ============================================================

# E10-RP2.2-R2A1 §2.2 — default validity window of a one-shot resume
# ticket (minted when the owner APPROVES an action gate, consumed only by
# the engine-designated continuation attempt). Configurable per engine via
# ``engine.resume_ticket_ttl_seconds`` (tests use short windows; the
# fail-closed direction is always expiry ⇒ refusal).
RESUME_TICKET_TTL_DEFAULT = 3600.0


@dataclass
class ResumeTicket:
    """E10-RP2.2-R2A1 §2.2 — ENGINE-ISSUED one-shot resume ticket.

    Minted by the trusted engine at the moment the owner APPROVES an
    action gate (``decide_human_gate``), bound to THAT gate and to the
    exact operation identity the gate paused (mission/run/task/tool +
    canonical input digest) plus the CREATING attempt/agent lineage.

    Lifecycle (strict, monotonic):

        armed ──(engine designates the continuation attempt)──▶ designated
        designated ──(atomic consume by the designated attempt)──▶ consumed
        armed|designated ──(TTL expiry)──▶ expired

    * ``armed``: the approval exists but the engine has not yet launched a
      designated continuation. NO call can consume the approval in this
      state — not even one presenting the exact operation identity
      (§2.3 case 3: an independent matching call cannot consume).
    * ``designated``: the engine's resume path
      (``MissionController.resume_approved_task``) has pre-minted the
      continuation attempt id and recorded it here. ONLY a call whose
      ``ExecutionContext.attempt_id`` equals ``continuation_attempt_id``
      (and whose agent matches the creating agent) may consume.
    * ``consumed`` / ``expired``: terminal — a new approval is required.

    The ticket id is generated with ``secrets`` and is NEVER exposed to
      the agent: ``_check_human_gate`` looks the ticket up by the CURRENT
      operation key in the ENGINE-INTERNAL registry
      (``engine._resume_tickets``); an agent-supplied id or field is never
      consulted as proof (§2.2.5 — no agent-reachable minting surface
      exists; the schema has no ticket field at all).
    """

    ticket_id: str
    gate_id: str
    op_key: str
    mission_id: str
    run_id: str
    task_id: str
    tool_name: str
    input_digest: str
    creating_attempt_id: str
    creating_agent_id: str
    issued_at: float
    expires_at: float
    state: str = "armed"
    continuation_attempt_id: str = ""
    designated_at: Optional[float] = None
    consumed_at: Optional[float] = None
    consumed_by_action: str = ""


class ToolExecutor:
    """
    Executes tools with full contract validation, Action recording, and audit events.
    
    Flow:
    1. Look up tool contract from registry
    2. Validate input against contract.input_schema
    3. Check permissions/grants for tool
    4. Check if human gate required (high-risk actions)
    4. Emit ActionRequestedEvent
    5. Create Action record
    6. Execute tool implementation
    7. Validate output against contract.output_schema
    8. Emit ActionValidatedEvent / TOOL_COMPLETED / TOOL_FAILED
    9. Update Action record with result
    10. Return ToolResult
    """
    
    def __init__(
        self,
        engine: 'ExecutionEngine',
        tool_registry: 'ToolRegistry',
        sandbox_manager: 'SandboxManager',
        evidence_store: 'FileEvidenceStore',
        event_bus: 'SimpleEventBus',
    ):
        self.engine = engine
        self.tool_registry = tool_registry
        self.sandbox_manager = sandbox_manager
        self.evidence_store = evidence_store
        self.event_bus = event_bus
        # Track actions for this execution
        self._actions: Dict[str, Action] = {}
    
    async def execute_tool(
        self,
        context: ExecutionContext,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> ToolResult:
        """Execute a tool with full contract validation and audit trail."""
        action_id = new_action_id()
        
        # 1. Look up tool contract
        contract = self.tool_registry.get(tool_name)
        if not contract:
            raise ValueError(f"Tool not registered: {tool_name}")
        
        # 2. Validate input against contract
        try:
            validated_input = contract.input_schema(**tool_input)
        except Exception as e:
            raise ValueError(f"Tool input validation failed for {tool_name}: {e}")
        
        # 3. Check permissions/grants — E10-RP2.1 §2: governed writes and
        # reads present the ACTUAL resolved target path (and, for path-aware
        # validators, the honest depth) to the authorization decision. A
        # target that cannot be contained inside its sandbox root is
        # rejected HERE — before any event, journal record, or side effect.
        await self._check_permissions(context, contract, tool_input)
        
        # 4. Check if human gate required (E9-12)
        await self._check_human_gate(context, contract, tool_name, validated_input, action_id)
        
        # 5. Emit ActionRequestedEvent
        self._emit_action_requested(context, action_id, tool_name, validated_input)
        
        # 6. Create Action record
        action = Action(
            action_id=action_id,
            attempt_id=context.attempt_id,
            tool_name=tool_name,
            tool_args=validated_input.model_dump(),
        )
        self._actions[action_id] = action
        
        # 7. Execute tool implementation
        start_time = asyncio.get_event_loop().time()
        try:
            tool_result = await self._execute_implementation(context, tool_name, validated_input, action_id)
            
            
            # 8. Validate output against contract
            # E10-RP2.2-R2 §2.3 (DF2 fix) — a FAILED ToolResult carries NO
            # output to validate (output=None): the output-validation step
            # is SKIPPED for it so the ORIGINAL error is preserved and
            # surfaced. Previously ``contract.output_schema(**None)`` raised
            # TypeError and REPLACED the true failure reason with a masking
            # "Output validation failed: ... NoneType" error (discovery
            # DF2, probes [G6]/[X2]). Only a SUCCESSFUL result with a
            # concrete output dict is validated against the contract; a
            # failed result with a partial output dict may validate it for
            # the audit record but NEVER overwrites the original error.
            validated_output = None
            if tool_result.output is None:
                # Failure (or contract-free) result with no output payload:
                # nothing to validate — keep the original error verbatim.
                validated_output = None
            elif tool_result.success:
                try:
                    validated_output = contract.output_schema(**tool_result.output)
                except Exception as e:
                    # Output validation failed on a SUCCESSFUL result - a
                    # real contract violation: treat as tool failure.
                    tool_result.success = False
                    tool_result.error = f"Output validation failed: {e}"
                    tool_result.error_type = "OutputValidationError"
            else:
                # Failed result carrying a partial output payload: validate
                # it only for the audit record; any violation is recorded
                # but the ORIGINAL error message is never masked.
                try:
                    validated_output = contract.output_schema(**tool_result.output)
                except Exception:
                    validated_output = None
            
            # 9. Emit ActionValidatedEvent
            self._emit_action_validated(context, action_id, tool_name, tool_result.success, 
                                       [] if tool_result.success else ["output_validation" if not tool_result.success else ""])
            
            # 10. Update Action record
            action.completed_at = datetime.now(timezone.utc)
            action.success = tool_result.success
            action.output = validated_output.model_dump() if (tool_result.success and validated_output is not None) else None
            action.error = tool_result.error
            action.evidence_id = tool_result.evidence_id
            action.sandbox_id = tool_result.artifacts[0] if tool_result.artifacts else context.sandbox_id
            
            # Also register action in engine for global tracking
            self.engine.actions[action_id] = action
            
            # Emit TOOL_COMPLETED or TOOL_FAILED
            if tool_result.success:
                self._emit_tool_completed(context, action_id, tool_name, tool_result)
            else:
                self._emit_tool_failed(context, action_id, tool_name, tool_result)
            
            # Set action_id on result for caller
            tool_result.action_id = action_id
            return tool_result
            
        except Exception as e:
            # Execution exception - update action and emit TOOL_FAILED
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            action.completed_at = datetime.now(timezone.utc)
            action.success = False
            action.error = f"{type(e).__name__}: {e}"
            
            # Also register action in engine for global tracking
            self.engine.actions[action_id] = action
            
            self._emit_action_validated(context, action_id, tool_name, False, [str(e)])
            self._emit_tool_failed(context, action_id, tool_name, 
                                  ToolResult(action_id=action_id, tool_name=tool_name, success=False, 
                                            error=str(e), error_type=type(e).__name__, duration_ms=duration_ms))
            raise
    
    # E10-RP2.1 §2 — the write/read tool families whose inputs carry a
    # concrete sandbox target. Only these can be path-grounded.
    # E10-RP2.2 §2 — the WORKSPACE tool family joins the governed set:
    # every tool whose input names a concrete path under
    # ``context.workspace_root`` (write_file/edit_file/read_file/list_dir/
    # grep/find_files/file_browser) now grounds the ACTUAL resolved target
    # into the authorization decision (path + honest depth). NO
    # path-bearing tool may end at the coarse kind-only gate as its final
    # authorization decision (order E10-RP2.2 §2.1-§2.3).
    _PATH_BEARING_TOOLS = frozenset({
        "artifact_write", "write_artifact", "artifact_read", "read_artifact",
        "read_file", "write_file", "edit_file",
        "list_dir", "grep", "find_files", "file_browser",
    })

    # E10-RP2.2 §2 — workspace tools resolve their concrete target against
    # ``context.workspace_root`` (the artifact families resolve against
    # ``<artifacts_base_dir>/<sandbox_id>``).
    _WORKSPACE_PATH_TOOLS = frozenset({
        "read_file", "write_file", "edit_file",
        "list_dir", "grep", "find_files", "file_browser",
    })

    # E10-RP2.2-R2 §3.2/§3.3 — the GIT family joins the governed set with a
    # REPO-level target: the protected object of a git operation is the
    # repository itself (its refs, index, and object database), so the
    # authorization decision is grounded to the RESOLVED REPO ROOT, not to
    # individual files. Permission mapping (order §3.3): git_status /
    # git_diff present a READ decision; git_branch / git_commit present a
    # WRITE decision; git_push additionally requires ADMIN (unattainable
    # under the EOE grant policy — fail-closed by design) AND the
    # owner-approval nonce binding of §3.4-§3.6.
    _REPO_GROUNDED_TOOLS = frozenset({
        "git_branch", "git_commit", "git_diff", "git_status", "git_push",
    })

    #: Bounded walk-up guard for the structural repo-root resolution.
    _MAX_REPO_WALK = 64

    @staticmethod
    def _ground_repo_root(workspace_root: Optional[str], repo_path: Optional[str]) -> Path:
        """E10-RP2.2-R2 §3.2 — resolve ``repo_path`` to its REPO ROOT and
        PROVE structural containment inside the workspace universe.

        Structural resolution only (pathlib walk-up to a ``.git`` marker) —
        NO git subprocess runs before the authorization decision. Fail-closed
        (PermissionError) when: the workspace universe is unset, the target
        is underivable, the target escapes the workspace universe, or no
        repository root is found on the walk-up. The returned repo root is
        the target presented to the path-aware grant validator (a repo-
        scoped grant must cover the REPO ROOT — the operation is repo-wide,
        so a deeper subdirectory grant does not authorize it).
        """
        if not workspace_root:
            raise PermissionError(
                "git operation refused fail-closed: no workspace_root is "
                "wired, so no authorized repo universe exists to ground the "
                "target (E10-RP2.2-R2 §3.2)"
            )
        try:
            ws = Path(workspace_root).resolve()
        except Exception:
            raise PermissionError(
                "git operation refused fail-closed: workspace_root cannot be "
                "resolved (E10-RP2.2-R2 §3.2)"
            )
        raw = repo_path if repo_path else str(ws)
        try:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = ws / candidate
            candidate = candidate.resolve()
        except Exception:
            raise PermissionError(
                f"git operation refused fail-closed: repo_path {raw!r} "
                "cannot be resolved to a concrete target (E10-RP2.2-R2 §3.2)"
            )
        # The candidate itself must sit inside the workspace universe — an
        # absolute repo_path pointing elsewhere (e.g. /etc, /tmp) is an
        # escape attempt, rejected BEFORE any git effect.
        if not (candidate == ws or candidate.is_relative_to(ws)):
            raise PermissionError(
                f"git operation refused fail-closed: repo_path {raw!r} "
                f"resolves outside the workspace universe {str(ws)!r} "
                "(E10-RP2.2-R2 §3.2)"
            )
        # Structural walk-up to the repository root (.git file or dir —
        # worktrees use a .git pointer file; both count).
        probe = candidate
        for _ in range(ToolExecutor._MAX_REPO_WALK):
            if (probe / ".git").exists():
                if not (probe == ws or probe.is_relative_to(ws)):
                    raise PermissionError(
                        f"git operation refused fail-closed: repository root "
                        f"{str(probe)!r} containing {raw!r} escapes the "
                        f"workspace universe {str(ws)!r} (E10-RP2.2-R2 §3.2)"
                    )
                return probe
            if probe.parent == probe:
                break
            probe = probe.parent
        raise PermissionError(
            f"git operation refused fail-closed: repo_path {raw!r} is not "
            "inside a git repository — no derivable repo target "
            "(E10-RP2.2-R2 §3.2)"
        )

    @staticmethod
    def _contained_write_target(
        artifacts_base_dir: str, sandbox_id: str, path: str
    ) -> Path:
        """E10-RP2.1 §2 — resolve the ACTUAL absolute write/read target and
        PROVE it stays inside the task sandbox root
        ``<artifacts_base_dir>/<sandbox_id>``.

        Fail-closed (PermissionError) on any escape: relative traversal
        (``..``), an ABSOLUTE ``path`` (pathlib join would REPLACE the base
        entirely), or a symlinked component that resolves outside the
        sandbox root. The caller MUST reject the operation before any side
        effect when this raises — the rejection then provably leaves no new
        file and no journal record.
        """
        base = Path(artifacts_base_dir) / sandbox_id
        base_resolved = base.resolve()
        target = (base / path).resolve()
        if target != base_resolved and not target.is_relative_to(base_resolved):
            raise PermissionError(
                "SANDBOX_CONTAINMENT_VIOLATION: the requested target "
                f"{str(target)!r} resolves outside the sandbox root "
                f"{str(base_resolved)!r} (sandbox_id={sandbox_id!r}, "
                f"path={path!r}) — the write is refused before any side "
                "effect (E10-RP2.1 §2.3)"
            )
        return target

    @staticmethod
    def _contained_workspace_target(workspace_root: str, path: str) -> Path:
        """E10-RP2.2 §2.5 — resolve the ACTUAL absolute workspace target and
        PROVE it stays inside the workspace root.

        Fail-closed (PermissionError) on any escape: relative traversal
        (``..``), an ABSOLUTE ``path`` pointing outside the workspace
        (pathlib join would REPLACE the base entirely), and symlinked
        components resolving outside the workspace root. Containment is
        decided on RESOLVED paths via ``Path.is_relative_to`` — normalized
        per-OS, never a raw string prefix (order E10-RP2.2 §2.5). The
        caller MUST reject the operation before any event, journal record,
        or side effect when this raises; the rejection then provably
        leaves no new file, folder, or journal record.
        """
        base = Path(workspace_root).resolve()
        target = (base / path).resolve()
        if target != base and not target.is_relative_to(base):
            raise PermissionError(
                "WORKSPACE_CONTAINMENT_VIOLATION: the requested target "
                f"{str(target)!r} resolves outside the workspace root "
                f"{str(base)!r} (workspace_root={workspace_root!r}, "
                f"path={path!r}) — the operation is refused before any "
                "side effect (E10-RP2.2 §2.5)"
            )
        return target

    def _path_disclosure_permitted(
        self, context: ExecutionContext, abs_path: Path
    ) -> bool:
        """E10-RP2.2 §2.4 — per-path grant check for iterating/exploration
        tools (list_dir / grep / find_files / file_browser).

        EVERY path that can be disclosed (listed, matched, browsed) or
        whose CONTENT can be read (grep) is checked against the grant
        rules on its OWN merits — checking the folder root alone and then
        allowing unlimited reading inside it is explicitly insufficient
        (order §2.4). Paths that fail are neither disclosed nor read
        (fail-closed per path, no partial leakage).

        E10-RP2.2-R1 §2.4 — FAIL-CLOSED: when no path-aware validator is
        wired, NO path is disclosed and NO content is read. The previous
        behavior (return True on a non-path-aware validator — disclosure
        allowed by default) is deleted by order: exploration/path
        disclosure without a path-aware policy is refused, without reading
        contents or leaking names/paths outside the policy.
        """
        validator = context.grant_validator
        if validator is None or not getattr(validator, "__path_aware__", False):
            return False
        for grant_id in context.grant_ids:
            try:
                if validator(grant_id, "read", str(abs_path)):
                    return True
            except Exception:
                continue
        return False

    async def _check_permissions(
        self,
        context: ExecutionContext,
        contract: 'ToolContract',
        tool_input: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Check if agent has required grants for tool.

        E10-RP2.1 §2: for path-bearing governed tools (artifact_write /
        artifact_read families) the authorization decision is grounded to
        the ACTUAL contained target path. Path-aware validators (built by
        ``eoe.engine_bridge.build_engine_grant_validator``; marked with
        ``__path_aware__``) receive it and enforce the grant's path scope
        and depth limit on the real target.

        E10-RP2.2 §2: the WORKSPACE tool family (write_file / edit_file /
        read_file / list_dir / grep / find_files / file_browser) joins
        the path-grounded set — its concrete target (resolved and
        structurally contained inside ``context.workspace_root``) reaches
        the grant decision with the honest depth. ``workspace_root`` is
        NEVER an implicit general grant (order §2.3): the presented grant
        must cover the ACTUAL path and depth, or the tool is rejected
        fail-closed before any event, journal record, or side effect.

        E10-RP2.2-R1 §2.1/§2.2 (fail-closed enforcement): for EVERY
        path-bearing tool the final decision may rest ONLY on a
        path-aware validator and ONLY on a derived concrete target.
        Legacy 2-arg validators are REJECTED for path-bearing tools even
        when their 2-arg form returns True (the RP2.1/RP2.2 "fixtures
        only" acceptance is overruled by this order), and an underivable
        ``actual_target`` is rejected with NO fallback to the coarse
        kind/scope gateway.

        E10-RP2.2-R2 §3.2/§3.3 (git family grounding): the git family
        joins the governed set at REPO granularity — ``repo_path`` is
        resolved to its structural repo root, proven contained inside the
        workspace universe, and the REPO ROOT is presented to the
        path-aware validator as the operation's concrete target
        (read-ops ↔ read, write-ops ↔ write per the order §3.3). The
        post-R1 coarse boundary for the git family is CLOSED: a git
        operation can never again end at the 2-arg kind gate as its
        final authorization decision.
        """
        required = contract.required_permissions
        if not required:
            return

        # E10-RP2.1 §2 / E10-RP2.2 §2 — resolve the concrete target ONCE
        # for path-bearing tools. An uncontainable target is rejected
        # here, fail-closed, before ANY event/journal/side effect (order
        # RP2.1 §2.6 + RP2.2 §2.6: a rejection must leave no new file,
        # folder, and no `performed` journal record).
        actual_target: Optional[str] = None
        path_bearing = contract.name in self._PATH_BEARING_TOOLS
        repo_grounded = contract.name in self._REPO_GROUNDED_TOOLS
        if tool_input is not None and path_bearing:
            if contract.name in self._WORKSPACE_PATH_TOOLS:
                # E10-RP2.2 §2.2/§2.3 — workspace tools ground the ACTUAL
                # contained workspace target into the grant decision;
                # workspace_root itself is never an implicit grant.
                rel_path = tool_input.get("path", ".")
                target = self._contained_workspace_target(
                    context.workspace_root, rel_path
                )
                actual_target = str(target)
            else:
                sandbox_id = tool_input.get("sandbox_id") or context.sandbox_id
                rel_path = tool_input.get("path", "output.txt")
                if sandbox_id and rel_path:
                    target = self._contained_write_target(
                        self.engine.artifacts_base_dir, sandbox_id, rel_path
                    )
                    actual_target = str(target)
        elif tool_input is not None and repo_grounded:
            # E10-RP2.2-R2 §3.2 — git operations ground their REPO ROOT
            # (structural walk-up, no git subprocess) into the grant
            # decision; uncontained/underivable repo targets are refused
            # fail-closed by the grounding helper itself.
            repo_root = self._ground_repo_root(
                context.workspace_root, tool_input.get("repo_path")
            )
            actual_target = str(repo_root)

        # Check if agent has grants covering required permissions
        if not context.grant_validator:
            # No validator = fail closed
            raise PermissionError(f"Tool {contract.name} requires grants but no validator available")

        path_aware = bool(getattr(context.grant_validator, "__path_aware__", False))

        # E10-RP2.2-R1 §2.1 / E10-RP2.2-R2 §3.2 — FAIL-CLOSED: for a
        # path-bearing OR repo-grounded tool the FINAL authorization
        # decision may NEVER rest on a validator that is not path-aware.
        # A legacy 2-arg validator (even one returning True) cannot decide
        # path/repo scope or depth, so it must be rejected here — before
        # any event, journal record, or side effect.
        if (path_bearing or repo_grounded) and not path_aware:
            raise PermissionError(
                f"Tool {contract.name} requires a path-aware grant "
                "validator (__path_aware__) for its concrete target; the "
                "configured validator is not path-aware — refused "
                "fail-closed (E10-RP2.2-R1 §2.1 / E10-RP2.2-R2 §3.2)"
            )

        # E10-RP2.2-R1 §2.2 / E10-RP2.2-R2 §3.2 — FAIL-CLOSED: a
        # path-bearing or repo-grounded operation whose concrete contained
        # target cannot be derived is refused. There is NO fallback to the
        # coarse kind/scope gateway (the 2-arg
        # ``grant_validator(grant_id, perm)`` form) — even when the
        # validator IS path-aware but cannot verify this operation's
        # target, the operation is rejected before any side effect.
        if (path_bearing or repo_grounded) and actual_target is None:
            raise PermissionError(
                f"Tool {contract.name} requires a concrete contained "
                "target for a path-scoped authorization decision; no "
                "valid actual_target could be derived for this operation "
                "— refused fail-closed with no fallback to the coarse "
                "kind gate (E10-RP2.2-R1 §2.2 / E10-RP2.2-R2 §3.2)"
            )

        for perm in required:
            # Check if any grant covers this permission
            has_perm = False
            for grant_id in context.grant_ids:
                if path_aware and actual_target is not None:
                    # The full per-operation decision: grant covers the
                    # ACTUAL resolved path with the honest depth (computed
                    # inside the admission contract from the path itself).
                    if context.grant_validator(grant_id, perm, actual_target):
                        has_perm = True
                        break
                elif context.grant_validator(grant_id, perm):
                    # E10-RP2.2-R1 §2.3 / E10-RP2.2-R2 §3.2 — the coarse
                    # 2-arg form is a final decision ONLY for tools
                    # WITHOUT a concrete target (web, grants — the
                    # declared post-R2 boundary). Path-bearing AND
                    # repo-grounded tools can never reach this branch:
                    # the fail-closed rules above already rejected them.
                    has_perm = True
                    break
            if not has_perm:
                raise PermissionError(
                    f"Agent {context.agent_id} lacks required permission: {perm} for tool {contract.name}"
                    + (
                        f" (target {actual_target!r} not covered by any presented grant — "
                        "path/depth scoped authorization, E10-RP2.1 §2)"
                        if path_aware and actual_target is not None
                        else ""
                    )
                )
    
    async def _check_human_gate(
        self, 
        context: ExecutionContext, 
        contract: 'ToolContract',
        tool_name: str,
        validated_input: BaseModel,
        action_id: str,
    ) -> None:
        """
        Check if human gate required for this action (E9-12).
        
        High-risk (HIGH/CRITICAL) tools require human approval before execution.

        E10-RP2.2-R2 §2.1 — FAIL-CLOSED on mission lookup: a HIGH/CRITICAL
        tool invoked with a mission_id that is NOT registered in
        ``engine.missions`` is REJECTED (PermissionError) — previously the
        gate was silently SKIPPED and the operation executed (discovery
        GAP-5, probe [X1]). A missing mission can never waive a required
        human approval.

        E10-RP2.2-R2 §2.2 — ACTION-SCOPED approval binding: a recorded
        approval authorizes ONLY the same tool AND the same operation
        inputs. The mission-wide "approved once for this tool name"
        carry-over is CLOSED.

        E10-RP2.2-R2A §2 — ONE-SHOT RESUME-BOUND APPROVAL (arbitration F1):
        an approval is bound to ONE resumable operation, never to a
        tool+inputs pair floating at mission level. The gate record lives
        under a v2 operation key
        ``action_gate_v2:{mission}:{run}:{task}:{tool}:{input_digest}``
        and carries the FULL operation identity — mission_id, run_id,
        task_id, attempt_id (creating lineage), agent_id, tool name, and
        the canonical input digest of the validated payload. Semantics:

        * PENDING (gate exists, no decision): the call is paused awaiting
          the decision — no duplicate gate is created for the same
          operation identity.
        * REJECTED: permanently refused for this identity (fail-closed);
          a different operation (inputs/task/run/mission) needs its own
          gate.
        * APPROVED + UNCONSUMED: the FIRST subsequent call presenting the
          EXACT operation identity (the engine-scheduled continuation of
          the same task — structurally the resume, since the engine runs
          at most one attempt per task at a time and the production
          resume path mints a fresh attempt_id per continuation) CONSUMES
          the approval exactly once, and the consumption lineage (attempt,
          agent, action) is recorded. This is the one-shot resume.
        * CONSUMED: the approval is spent. Any further call — same
          identity or not — requires a NEW approval: the consumed cycle is
          archived and a fresh gate cycle is opened (pause). Approval
          reuse across operations is structurally impossible.

        LEGACY records (any ``action_gate_*`` entry without a v2
        ``_operation`` record — including R2's digest-only records)
        authorize NOTHING: the lookup only ever consults the v2 key, and
        a record whose stored identity does not match the current call
        is treated as absent (fail-closed → new gate). Input-fingerprint
        equality alone never authorizes anything.
        """
        if contract.risk_level not in (ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL):
            return
        
        mission = self.engine.missions.get(context.mission_id)
        if not mission:
            # E10-RP2.2-R2 §2.1 — the mission-lookup miss is a REJECTION,
            # not a silent gate skip. An unregistered mission_id can never
            # waive a HIGH/CRITICAL human approval.
            raise PermissionError(
                f"Human gate required for {tool_name} "
                f"({contract.risk_level.value}) but mission "
                f"{context.mission_id!r} is not registered in the engine — "
                "refused fail-closed instead of silently skipping the gate "
                "(E10-RP2.2-R2 §2.1)"
            )

        # E10-RP2.2-R2A §2.1 — canonical digest of THIS operation's inputs
        # (over the VALIDATED payload) + the full operation identity key.
        input_digest = self._gate_input_digest(validated_input)
        op_key = self._gate_operation_key(context, tool_name, input_digest)

        record = mission.metadata.get(f"{op_key}_operation")
        if isinstance(record, dict):
            # Defense in depth: the record must carry the v2 format and
            # match THIS call's identity exactly — a corrupt, tampered or
            # foreign record authorizes nothing (fail-closed → new gate).
            if not (
                record.get("format") == "v2"
                and record.get("mission_id") == context.mission_id
                and record.get("run_id") == context.run_id
                and record.get("task_id") == context.task_id
                and record.get("tool_name") == tool_name
                and record.get("input_digest") == input_digest
            ):
                record = None

        if record is not None:
            consumed = mission.metadata.get(f"{op_key}_consumed")
            decision = mission.metadata.get(f"{op_key}_decision")
            if consumed is not None:
                # R2A §2.2 — the approval was already used by the resumed
                # operation: it is SPENT. This call is a new, independent
                # invocation of the same identity → archive the consumed
                # cycle and open a NEW gate cycle below (a new approval is
                # required). The old approval can never authorize again.
                self._archive_gate_cycle(mission, op_key)
            elif decision is None:
                # Same pending operation re-presented while awaiting the
                # human decision — pause; never a duplicate gate.
                raise PermissionError(f"Human gate pending for {tool_name}. Awaiting decision.")
            elif decision.get("decision") != "approve":
                # Rejected for this operation identity — fail-closed.
                raise PermissionError(f"Human gate rejected for {tool_name}: {decision.get('feedback', 'Not approved')}")
            else:
                # APPROVED + UNCONSUMED — E10-RP2.2-R2A1 §2.2 (arbitration
                # F1): the approval can be consumed ONLY by the
                # ENGINE-DESIGNATED continuation of the paused operation,
                # proven by a one-shot RESUME TICKET in the engine-internal
                # registry. Presenting the exact operation identity
                # (mission/run/task/tool/digest) alone authorizes NOTHING —
                # an independent matching call (a scheduler retry, a
                # hand-crafted context, any call that is not the designated
                # continuation attempt) is REFUSED fail-closed here, with
                # zero consumption and zero side effects, and the approval
                # stays intact for the designated continuation (§2.3 case 3).
                self._consume_resume_ticket_or_raise(
                    mission, op_key, record, context, tool_name, action_id,
                )
                return

        # No valid v2 record (first call, legacy, archived-consumed, or
        # corrupt) → open a NEW gate cycle for THIS operation identity.
        gate_id = self.engine.create_human_gate(
            mission_id=context.mission_id,
            run_id=context.run_id,
            task_id=context.task_id,
            reason=f"High-risk tool execution requires human approval: {tool_name} ({contract.risk_level.value})",
            context={
                "tool_name": tool_name,
                "tool_input": validated_input.model_dump(),
                "risk_level": contract.risk_level.value,
                "isolation": contract.isolation.value,
                "agent_id": context.agent_id,
                # R2A §2.1 — the operation identity this approval binds to.
                "operation": {
                    "format": "v2",
                    "mission_id": context.mission_id,
                    "run_id": context.run_id,
                    "task_id": context.task_id,
                    "attempt_id": context.attempt_id,
                    "agent_id": context.agent_id,
                    "tool_name": tool_name,
                    "input_digest": input_digest,
                },
            },
            options=[
                {"value": "approve", "label": "Approve Execution", "description": f"Allow {tool_name} to execute"},
                {"value": "reject", "label": "Reject Execution", "description": f"Block {tool_name} execution"},
            ],
            impact=f"Executing {tool_name} with {contract.risk_level.value} risk level",
            required_action="Human must explicitly approve or reject the high-risk action",
            evidence_refs=[],
            requested_by="execution_engine",
        )
        if gate_id is None:
            # The mission is not in a gate-creatable state (e.g. RECEIVED,
            # or HUMAN_REQUIRED for another gate). The operation is PAUSED
            # fail-closed — identical surfaced behavior to the R2 gate
            # pause (probe-observable contract preserved byte-for-byte).
            raise PermissionError(f"Human gate created for {tool_name}. Execution paused awaiting approval.")

        # Store the gate reference + the FULL operation identity the
        # approval will be bound to (R2A §2.1/§2.2). The cycle counter
        # lives in its own slot and survives archiving (a consumed cycle
        # keeps its audit trail under ``{op_key}#cycle{n}``; the next
        # cycle continues the monotonic count).
        cycle = mission.metadata.get(f"{op_key}_cycles")
        cycle = cycle if isinstance(cycle, int) and cycle >= 1 else 1
        mission.metadata[op_key] = gate_id
        mission.metadata[f"{op_key}_operation"] = {
            "format": "v2",
            "mission_id": context.mission_id,
            "run_id": context.run_id,
            "task_id": context.task_id,
            "attempt_id": context.attempt_id,
            "agent_id": context.agent_id,
            "tool_name": tool_name,
            "input_digest": input_digest,
            "gate_id": gate_id,
            "cycle": cycle,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Wait for human decision (this will pause execution)
        # The engine will resume when human decides
        raise PermissionError(f"Human gate created for {tool_name}. Execution paused awaiting approval.")

    def _consume_resume_ticket_or_raise(
        self,
        mission,
        op_key: str,
        record: Dict[str, Any],
        context: ExecutionContext,
        tool_name: str,
        action_id: str,
    ) -> None:
        """E10-RP2.2-R2A1 §2.2 — verify + ATOMICALLY CONSUME the one-shot
        resume ticket for an APPROVED+UNCONSUMED gate, or refuse fail-closed.

        Every failure below raises PermissionError BEFORE any Action record
        exists (the gate runs pre-Action) and WITHOUT consuming the ticket
        or altering the approval — the refusal is a pause, not a burn:

        * no engine-internal ticket registry / no ticket for this operation
          (forged, foreign, or absent proof — an agent-supplied id is never
          consulted; lookup is by operation key only, §2.2.5);
        * ticket/gate/identity mismatch (bound to a different gate,
          mission, run, task, tool, or input digest — a ticket TRANSFERRED
          from another operation authorizes nothing);
        * ticket not yet DESIGNATED (armed): the engine has not launched
          the continuation — an independent matching call cannot consume
          (§2.3 case 3);
        * current call is not the designated continuation attempt
          (§2.2.3: a fresh attempt is a continuation only when the ENGINE
          designated it — identity match alone never proves continuation);
        * agent changed (§2.2.4: no reassignment mechanism is authorized;
          a different agent requires a NEW approval);
        * ticket expired (§2.2.7) — terminal, a new approval is required.

        Success flips the ticket to ``consumed`` synchronously (no await
        between verification and the flip — atomic in the event loop) and
        records the consuming lineage next to the creating lineage.
        """
        tickets = getattr(self.engine, "_resume_tickets", None)
        ticket = tickets.get(op_key) if isinstance(tickets, dict) else None
        if ticket is None:
            raise PermissionError(
                f"Human gate approved for {tool_name} but no engine-issued "
                "resume ticket exists for this operation — the approval "
                "cannot be consumed without the engine-designated "
                "continuation (E10-RP2.2-R2A1 §2.2.5/§2.2.8; agent-supplied "
                "proof is never accepted)"
            )
        # Defense in depth: the ticket must bind THIS gate and the FULL
        # current operation identity — a ticket minted for any other gate
        # or operation (transfer/forgery/corruption) authorizes nothing.
        if (
            ticket.gate_id != record.get("gate_id")
            or ticket.op_key != op_key
            or ticket.mission_id != context.mission_id
            or ticket.run_id != context.run_id
            or ticket.task_id != context.task_id
            or ticket.tool_name != tool_name
            or ticket.input_digest != record.get("input_digest")
        ):
            raise PermissionError(
                f"Human gate approved for {tool_name} but the resume ticket "
                "does not bind this exact operation identity "
                "(gate/mission/run/task/tool/digest mismatch) — refused "
                "fail-closed (E10-RP2.2-R2A1 §2.2.2)"
            )
        now = time.time()
        if now >= ticket.expires_at or ticket.state == "expired":
            ticket.state = "expired"
            raise PermissionError(
                f"Human gate approved for {tool_name} but the resume ticket "
                "has EXPIRED — a new approval is required "
                "(E10-RP2.2-R2A1 §2.2.7)"
            )
        if ticket.state == "consumed":
            raise PermissionError(
                f"Human gate approved for {tool_name} but the resume ticket "
                "was already used — a new approval is required "
                "(E10-RP2.2-R2A1 §2.2.6)"
            )
        if ticket.state != "designated":
            raise PermissionError(
                f"Human gate approved for {tool_name} but the engine has "
                "not yet designated the continuation (ticket "
                f"{ticket.state}) — an approval is consumed only by the "
                "ENGINE-DESIGNATED resume of the paused operation, never by "
                "an independent matching call (E10-RP2.2-R2A1 §2.2.3/§2.3.3)"
            )
        if ticket.continuation_attempt_id != context.attempt_id:
            raise PermissionError(
                f"Human gate approved for {tool_name} but this call "
                f"(attempt {context.attempt_id!r}) is NOT the "
                "engine-designated continuation attempt "
                f"({ticket.continuation_attempt_id!r}) — the approval stays "
                "reserved for the designated resume; identity match alone "
                "is not continuation proof (E10-RP2.2-R2A1 §2.2.3/§2.2.8)"
            )
        if ticket.creating_agent_id != context.agent_id:
            raise PermissionError(
                f"Human gate approved for {tool_name} but the agent changed "
                f"({context.agent_id!r} != approved {ticket.creating_agent_id!r}) "
                "— no reassignment mechanism is authorized; a new approval "
                "is required (E10-RP2.2-R2A1 §2.2.4)"
            )
        # Atomic consumption — synchronous flip, no await between the
        # verifications above and this transition.
        ticket.state = "consumed"
        ticket.consumed_at = now
        ticket.consumed_by_action = action_id
        mission.metadata[f"{op_key}_consumed"] = {
            "consumed_at": datetime.now(timezone.utc).isoformat(),
            "consumed_by_attempt": context.attempt_id,
            "consumed_by_agent": context.agent_id,
            "consumed_by_action": action_id,
            "resume_ticket_id": ticket.ticket_id,
        }

    @staticmethod
    def _gate_operation_key(
        context: ExecutionContext, tool_name: str, input_digest: str
    ) -> str:
        """R2A §2.1 — the v2 operation key: the gate (and therefore the
        approval) is scoped to ONE operation identity — mission + run +
        task + tool + canonical input digest. ``attempt_id``/``agent_id``
        are part of the RECORDED identity (creating + consuming lineage in
        the ``_operation``/``_consumed`` records), not of the key: the
        production resume path structurally continues a paused task under
        a fresh attempt_id (``_execute_single_task`` mints one per
        retry), so binding the key to the literal creating attempt would
        make every approval unusable (deadlock). Engine ids are
        colon-free (``mission-<hex>``/``run-<hex>``/``task-<hex>``), so
        the key is unambiguous; identity is re-verified field-by-field
        against the stored record, never trusted from the key alone."""
        return (
            f"action_gate_v2:{context.mission_id}:{context.run_id}:"
            f"{context.task_id}:{tool_name}:{input_digest}"
        )

    @staticmethod
    def _archive_gate_cycle(mission, op_key: str) -> None:
        """R2A §2.2 — archive a CONSUMED gate cycle under
        ``{op_key}#cycle{n}`` (audit trail preserved: the archived gate id
        stays discoverable by ``decide_human_gate`` and its decision
        stays duplicate-protected), clear the live slots, and advance the
        monotonic ``{op_key}_cycles`` counter so the next call for this
        identity opens a fresh cycle requiring a NEW approval."""
        record = mission.metadata.get(f"{op_key}_operation")
        n = 1
        if isinstance(record, dict) and isinstance(record.get("cycle"), int):
            n = record["cycle"]
        archived = f"{op_key}#cycle{n}"
        for suffix in ("", "_decision", "_consumed", "_operation"):
            src = f"{op_key}{suffix}"
            if src in mission.metadata:
                mission.metadata[f"{archived}{suffix}"] = mission.metadata.pop(src)
        mission.metadata[f"{op_key}_cycles"] = n + 1

    @staticmethod
    def _gate_input_digest(validated_input: BaseModel) -> str:
        """E10-RP2.2-R2 §2.2 — canonical digest binding a human-gate
        approval to the exact operation inputs it approved. Deterministic
        across retries of the SAME operation (sorted-key JSON of the
        validated input model)."""
        try:
            payload = validated_input.model_dump()
        except Exception:
            payload = {"repr": repr(validated_input)}
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    
    async def _execute_implementation(
        self,
        context: ExecutionContext,
        tool_name: str,
        validated_input: BaseModel,
        action_id: str,
    ) -> ToolResult:
        """Execute the actual tool implementation."""
        # Delegate to engine's execute_tool for sandbox-backed tools
        if tool_name in ("run_command", "write_artifact", "read_artifact", "artifact_write", "artifact_read", "sandbox_execute"):
            return await self.engine.execute_tool(context, tool_name, validated_input.model_dump())
        
        # Filesystem tools
        elif tool_name in ("read_file", "write_file", "edit_file", "list_dir", "grep", "find_files", "file_browser"):
            return await self._execute_filesystem_tool(context, tool_name, validated_input, action_id)
        
        # Git tools
        elif tool_name in ("git_branch", "git_commit", "git_diff", "git_status", "git_push"):
            return await self._execute_git_tool(context, tool_name, validated_input, action_id)
        
        # Web tools
        elif tool_name in ("web_search", "web_fetch"):
            return await self._execute_web_tool(context, tool_name, validated_input, action_id)
        
        # Verification tools
        elif tool_name == "verification_check":
            return await self._execute_verification_tool(context, validated_input, action_id)
        
        # Grant tools
        elif tool_name == "grant_validate":
            return await self._execute_grant_tool(context, validated_input, action_id)
        
        else:
            raise ValueError(f"No implementation for tool: {tool_name}")
    
    async def _execute_filesystem_tool(
        self,
        context: ExecutionContext,
        tool_name: str,
        validated_input: BaseModel,
        action_id: str,
    ) -> ToolResult:
        """Execute filesystem tools within sandbox/workspace.

        E10-RP2.2 §2 — every workspace tool target is structurally
        contained: resolved and PROVEN inside ``context.workspace_root``
        (traversal, absolute-escape and symlink-escape refused before any
        side effect — defense in depth under the permission gate, which
        already grounded this exact target into the grant decision).
        Iterating/exploration tools (list_dir / grep / find_files /
        file_browser) authorize EVERY disclosed or content-read path
        per-path against the grant rules — never an unbounded walk under a
        root-only check (order E10-RP2.2 §2.4). ``workspace_root`` is
        never an implicit grant.
        """
        import fnmatch as _fnmatch

        # Resolve workspace path
        workspace = Path(context.workspace_root).resolve()

        # E10-RP2.2 §2.5 — structural containment re-proof at the
        # execution layer (the permission gate already proved the same
        # target before any event/journal). Raises PermissionError BEFORE
        # any side effect.
        target = self._contained_workspace_target(
            context.workspace_root, validated_input.path
        )

        def disclosed(p: Path) -> bool:
            """§2.4 per-path grant rule for disclosure / content reads."""
            return self._path_disclosure_permitted(context, p)

        if tool_name == "read_file":
            if not target.exists():
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"File not found: {target}", error_type="FileNotFoundError")
            content = target.read_text(encoding=validated_input.encoding)
            sha256 = hashlib.sha256(content.encode()).hexdigest()
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "content": content, "size_bytes": len(content.encode()), "sha256": sha256})

        elif tool_name == "write_file":
            if target.exists() and not validated_input.overwrite:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"File exists and overwrite=False: {target}", error_type="FileExistsError")
            target.parent.mkdir(parents=True, exist_ok=True)
            content = validated_input.content
            target.write_text(content, encoding=validated_input.encoding)
            sha256 = hashlib.sha256(content.encode()).hexdigest()
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "path": str(target), "size_bytes": len(content.encode()), "sha256": sha256})

        elif tool_name == "edit_file":
            if not target.exists():
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"File not found: {target}", error_type="FileNotFoundError")
            content = target.read_text(encoding="utf-8")
            old_text = validated_input.old_text
            new_text = validated_input.new_text
            if validated_input.replace_all:
                new_content = content.replace(old_text, new_text)
                replacements = content.count(old_text)
            else:
                new_content = content.replace(old_text, new_text, 1)
                replacements = 1 if old_text in content else 0
            if replacements == 0:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"Text not found in file", error_type="TextNotFoundError")
            target.write_text(new_content, encoding="utf-8")
            sha256 = hashlib.sha256(new_content.encode()).hexdigest()
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "path": str(target), "replacements": replacements, "sha256": sha256})

        elif tool_name == "list_dir":
            if not target.exists():
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"Path not found: {target}", error_type="PathNotFoundError")
            entries = []
            for entry in target.rglob("*") if validated_input.recursive else target.iterdir():
                # E10-RP2.2 §2.4 — every DISCLOSED path is authorized
                # per-path; paths outside the grant rules are not disclosed.
                if not disclosed(entry):
                    continue
                if validated_input.pattern:
                    if not _fnmatch.fnmatch(entry.name, validated_input.pattern):
                        continue
                entries.append({
                    "name": entry.name,
                    "path": str(entry.relative_to(workspace)),
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else 0,
                })
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "entries": entries, "total": len(entries)})

        elif tool_name == "grep":
            if not target.exists():
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"Path not found: {target}", error_type="PathNotFoundError")
            matches = []
            import re
            flags = 0 if validated_input.case_sensitive else re.IGNORECASE
            pattern = re.compile(validated_input.pattern, flags)
            # E10-RP2.2 D4 fix — `recursive` is part of the grep contract
            # (default True) and `fnmatch` no longer depends on the
            # list_dir branch having imported it first.
            recursive = getattr(validated_input, "recursive", True)
            for file_path in target.rglob("*") if recursive else target.iterdir():
                # E10-RP2.2 §2.4 — CONTENT reads are authorized per-path:
                # a file outside the grant rules is never opened at all.
                if not disclosed(file_path):
                    continue
                if file_path.is_file() and (not validated_input.file_pattern or _fnmatch.fnmatch(file_path.name, validated_input.file_pattern)):
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        for i, line in enumerate(content.splitlines(), 1):
                            if pattern.search(line):
                                matches.append({
                                    "file": str(file_path.relative_to(workspace)),
                                    "line_number": i,
                                    "line": line,
                                })
                                if len(matches) >= (validated_input.max_results or 100):
                                    break
                    except Exception:
                        pass
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "matches": matches, "total": len(matches)})

        elif tool_name == "find_files":
            if not target.exists():
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"Path not found: {target}", error_type="PathNotFoundError")
            files = []
            for file_path in target.rglob("*"):
                # E10-RP2.2 §2.4 — per-path authorization before disclosure
                if not disclosed(file_path):
                    continue
                if file_path.is_file() and _fnmatch.fnmatch(file_path.name, validated_input.pattern):
                    files.append(str(file_path.relative_to(workspace)))
                    if len(files) >= (validated_input.max_results or 100):
                        break
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "files": files, "total": len(files)})

        elif tool_name == "file_browser":
            if not target.exists():
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"Path not found: {target}", error_type="PathNotFoundError")
            tree = {"name": target.name, "path": str(target.relative_to(workspace)), "type": "directory", "children": []}
            total_files = 0
            total_dirs = 0
            def build_tree(node, p):
                nonlocal total_files, total_dirs
                try:
                    for entry in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                        if not validated_input.show_hidden and entry.name.startswith("."):
                            continue
                        # E10-RP2.2 §2.4 — every browsed node is authorized
                        # per-path; unauthorized nodes/subtrees are not
                        # disclosed.
                        if not disclosed(entry):
                            continue
                        if entry.is_dir():
                            total_dirs += 1
                            child = {"name": entry.name, "path": str(entry.relative_to(workspace)), "type": "directory", "children": []}
                            node["children"].append(child)
                            build_tree(child, entry)
                        else:
                            total_files += 1
                            node["children"].append({"name": entry.name, "path": str(entry.relative_to(workspace)), "type": "file", "size": entry.stat().st_size})
                except Exception:
                    pass
            build_tree(tree, target)
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "tree": tree, "total_files": total_files, "total_dirs": total_dirs})

        raise ValueError(f"Unknown filesystem tool: {tool_name}")
    
    async def _execute_git_tool(
        self,
        context: ExecutionContext,
        tool_name: str,
        validated_input: BaseModel,
        action_id: str,
    ) -> ToolResult:
        """Execute git tools.

        E10-RP2.2-R2 §3.2 — the working repository is the REPO ROOT derived
        by the SAME structural grounding used by the authorization gate
        (``_ground_repo_root``): authorization and implementation can never
        disagree about the target. E10-RP2.2-R2 §3.4-§3.6 — git_push is
        fail-closed DISABLED unless the owner_approval_nonce is verified
        against a REAL owner-issued approval record (signature + TTL +
        single-use + repo/remote/branch/commit/force scope) through the
        engine's ``push_approval_registry``; with no registry wired the
        push is refused outright.
        """
        repo_root = self._ground_repo_root(
            context.workspace_root, getattr(validated_input, "repo_path", None)
        )
        repo_path = repo_root
        
        async def run_git(args: List[str]) -> subprocess.CompletedProcess:
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(
                    ["git"] + args,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=validated_input.timeout_seconds if hasattr(validated_input, 'timeout_seconds') else 60,
                )
            )
        
        if tool_name == "git_branch":
            action = validated_input.action
            if action == "list":
                result = await run_git(["branch", "-a"])
                branches = [b.strip().lstrip("* ").strip() for b in result.stdout.splitlines() if b.strip()]
                current = await run_git(["branch", "--show-current"])
                return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                                 output={"success": True, "branches": branches,
                                         "current": current.stdout.strip(), "created": None})
            elif action == "create":
                result = await run_git(["branch", validated_input.branch_name, validated_input.start_point or "HEAD"])
                return ToolResult(action_id=action_id, tool_name=tool_name, success=result.returncode==0,
                                 output={"success": result.returncode==0,
                                         "branches": [validated_input.branch_name],
                                         "created": result.returncode==0},
                                 error=result.stderr if result.returncode != 0 else None)
            elif action == "delete":
                result = await run_git(["branch", "-d", validated_input.branch_name])
                return ToolResult(action_id=action_id, tool_name=tool_name, success=result.returncode==0,
                                 output={"success": result.returncode==0, "branches": [], "created": False},
                                 error=result.stderr if result.returncode != 0 else None)
            else:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"Unknown git_branch action: {action}")
        
        elif tool_name == "git_commit":
            # Stage files if specified
            if validated_input.files:
                for f in validated_input.files:
                    await run_git(["add", f])
            else:
                await run_git(["add", "-A"])
            
            author_args = []
            if validated_input.author_name:
                author_args.extend(["-c", f"user.name={validated_input.author_name}"])
            if validated_input.author_email:
                author_args.extend(["-c", f"user.email={validated_input.author_email}"])
            
            result = await run_git(author_args + ["commit", "-m", validated_input.message])
            if result.returncode != 0:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=result.stderr, error_type="GitCommitError")
            
            # Get commit hash
            hash_result = await run_git(["rev-parse", "HEAD"])
            commit_hash = hash_result.stdout.strip()
            
            # Get stats
            stat_result = await run_git(["show", "--stat", "--oneline", commit_hash])
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "commit_hash": commit_hash,
                                     "files_changed": 0, "insertions": 0, "deletions": 0})
        
        elif tool_name == "git_diff":
            args = ["diff"]
            if validated_input.staged:
                args.append("--cached")
            if validated_input.file_path:
                args.append(validated_input.file_path)
            result = await run_git(args)
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "diff": result.stdout, "files_changed": 0})
        
        elif tool_name == "git_status":
            result = await run_git(["status", "--porcelain"])
            clean = result.returncode == 0 and not result.stdout.strip()
            lines = result.stdout.strip().splitlines() if result.stdout.strip() else []
            staged = [l[3:] for l in lines if l.startswith("  ")]
            unstaged = [l[3:] for l in lines if l.startswith(" ")]
            untracked = [l[3:] for l in lines if l.startswith("??")]
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "clean": clean, "staged": staged,
                                     "unstaged": unstaged, "untracked": untracked})
        
        elif tool_name == "git_push":
            # E10-RP2.2-R2 §3.4-§3.6 — CRITICAL: push is DISABLED
            # fail-closed unless owner_approval_nonce is bound to a REAL
            # owner-issued approval record: valid (HMAC signature + TTL),
            # UNUSED (single-use nonce ledger), and scoped to exactly THIS
            # repository, remote, branch, commit, and operation (force
            # flag). A nonce PRESENCE check alone authorizes nothing
            # (discovery GAP-2, probe [G6]).
            #
            # E10-RP2.2-R2A §3.1/§3.2 (arbitration F2) — the approval is
            # additionally bound to the CANONICAL PUSH URL git will
            # actually use at execution time (pushurl / insteadOf /
            # pushInsteadOf rewriting resolved and multi-destination
            # configurations refused), and remote/branch are structurally
            # validated so no input value can ever be interpreted as a
            # git CLI option; the push runs with an explicit refspec the
            # handler itself constructs plus the '--' option separator.
            nonce = getattr(validated_input, "owner_approval_nonce", None)
            if not nonce:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error="git_push requires owner_approval_nonce bound to a real owner-issued approval record (E10-RP2.2-R2 §3.4)",
                                 error_type="PermissionError")

            registry = getattr(self.engine, "push_approval_registry", None)
            if registry is None:
                # E10-RP2.2-R2 §3.6 — no verifiable owner-approval
                # mechanism is wired: the push does not happen.
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error="git_push disabled fail-closed: no owner-approval registry is wired, so no owner approval can be verified (E10-RP2.2-R2 §3.4/§3.6)",
                                 error_type="PermissionError")

            # Bind the approval to THIS push: the repository's current
            # HEAD commit is part of the approval scope (the owner
            # approved pushing THIS commit, not "whatever is at HEAD").
            head_result = await run_git(["rev-parse", "HEAD"])
            if head_result.returncode != 0:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"git_push cannot read HEAD: {head_result.stderr.strip()[:200]}",
                                 error_type="GitPushError")
            head_sha = head_result.stdout.strip()

            remote = validated_input.remote or "origin"
            branch = validated_input.branch
            force = bool(getattr(validated_input, "force", False))

            # R2A §3.2 — STRUCTURAL validation before any git subprocess:
            # remote/branch input values can never be interpreted as CLI
            # options (leading '-', whitespace, forbidden ref characters
            # are rejected here, in-process).
            from eoe.push_engine import (
                PushRejected as _PushRejected,
                validate_branch_name as _validate_branch,
                validate_remote_name as _validate_remote,
            )
            ok_r, why_r = _validate_remote(remote)
            if not ok_r:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=(f"git_push refused: remote name {remote!r} is structurally "
                                        f"invalid ({why_r}) — no input value can act as a git CLI option "
                                        "(E10-RP2.2-R2A §3.2)"),
                                 error_type="PermissionError")
            ok_b, why_b = _validate_branch(branch)
            if not ok_b:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=(f"git_push refused: branch name {branch!r} is structurally "
                                        f"invalid ({why_b}) — a value like '--force' can never be "
                                        "interpreted as a push option or refspec (E10-RP2.2-R2A §3.2)"),
                                 error_type="PermissionError")
            # Canonical ref-format authority (git itself); the name is
            # passed as a separate argv element AFTER the structural
            # leading-dash rejection above, so check-ref-format can never
            # receive an option either.
            fmt = await run_git(["check-ref-format", "--branch", branch])
            if fmt.returncode != 0:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=(f"git_push refused: branch {branch!r} is not a valid git "
                                        f"branch name: {fmt.stderr.strip()[:160]} "
                                        "(E10-RP2.2-R2A §3.2)"),
                                 error_type="PermissionError")

            # R2A §3.1 — resolve the ACTUAL destination git will push to
            # (pushurl/insteadOf/pushInsteadOf rewriting applied; multiple
            # configured destinations refused — git would push to ALL of
            # them and the owner approved exactly ONE canonical URL). Any
            # resolution failure = rejection, never a fallback.
            from eoe.push_engine import resolve_push_destination as _resolve_dest
            try:
                canonical_push_url = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _resolve_dest(str(repo_root), remote)
                )
            except _PushRejected as pr:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=(f"git_push refused: the push destination cannot be proven — "
                                        f"{pr.reason}: {pr.detail} (E10-RP2.2-R2A §3.1)"),
                                 error_type="PermissionError")
            except Exception as e:  # noqa: BLE001
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=(f"git_push refused: push destination resolution failed: "
                                        f"{type(e).__name__}: {e} (E10-RP2.2-R2A §3.1)"),
                                 error_type="PermissionError")

            try:
                ok, reason = registry.verify_and_consume(
                    nonce,
                    repository=str(repo_root),
                    branch=branch,
                    commit_sha=head_sha,
                    remote=remote,
                    push_url=canonical_push_url,
                    force=force,
                )
            except Exception as e:
                # Any registry failure = rejection, never a bypass.
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"git_push owner-approval verification failed: {type(e).__name__}: {e} (E10-RP2.2-R2 §3.4)",
                                 error_type="PermissionError")
            if not ok:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=f"git_push owner-approval verification failed: {reason} (E10-RP2.2-R2 §3.4)",
                                 error_type="PermissionError")

            # E10-RP2.2-R2 §3.5 + R2A §3.2 + R2A1 §3.2 — force semantics:
            # '--force' is appended ONLY when the explicit input flag is set
            # AND the consumed approval was signed for force=True. The
            # branch value itself can never contribute a flag (structurally
            # rejected above) — branch='--force' with force=False is
            # refused long before this point.
            #
            # E10-RP2.2-R2A1 §3.2 (arbitration F2) — PINNED DESTINATION:
            # the push command itself uses THE SIGNED CANONICAL URL (never
            # the remote NAME — probe P3 proved an explicit URL pushed
            # from the SOURCE repo is still subject to insteadOf
            # rewriting, so the source repo's config could re-route the
            # destination between verification and execution). The push
            # runs from an engine-owned throwaway bare STAGING repo whose
            # only link to the source is read-only object access via
            # objects/info/alternates, with GIT_CONFIG_NOSYSTEM=1 and
            # GIT_CONFIG_GLOBAL=/dev/null: no config the source repo (or
            # the host) can change between ``resolve_push_destination``
            # and the push itself can re-route or re-resolve the
            # destination. The refspec is ``<approved_sha>:refs/heads/
            # <branch>`` — constructed by the handler from the structurally
            # validated branch and the approved commit (the commit the
            # owner signed is the commit that lands), never taken raw from
            # the input, and '--' terminates option parsing.
            from eoe.push_engine import staged_push as _staged_push
            try:
                push_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _staged_push(
                        str(repo_root),
                        canonical_push_url,
                        head_sha,
                        branch,
                        force=force,
                        timeout=validated_input.timeout_seconds
                        if hasattr(validated_input, "timeout_seconds") else 60,
                    ),
                )
            except _PushRejected as pr:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=(f"git_push refused: the pinned destination push "
                                        f"could not be proven — {pr.reason}: {pr.detail} "
                                        "(E10-RP2.2-R2A1 §3.2)"),
                                 error_type="PermissionError")
            except Exception as e:  # noqa: BLE001
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=(f"git_push refused: pinned-destination push failed "
                                        f"before any effect: {type(e).__name__}: {e} "
                                        "(E10-RP2.2-R2A1 §3.2)"),
                                 error_type="PermissionError")
            if push_result["returncode"] != 0:
                return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                                 error=push_result["stderr"], error_type="GitPushError")
            # The result record reports the SIGNED destination — which is
            # structurally the destination the push command itself used
            # (R2A1 §3.3: a record may never announce a signed address the
            # actual push did not go to).
            return ToolResult(action_id=action_id, tool_name=tool_name, success=True,
                             output={"success": True, "pushed": True, "commit_hash": head_sha,
                                     "remote_ref": f"{remote}/{branch}",
                                     "push_url": canonical_push_url,
                                     "push_argv": push_result["argv"],
                                     "certificates": []})
        
        raise ValueError(f"Unknown git tool: {tool_name}")
    
    async def _execute_web_tool(
        self,
        context: ExecutionContext,
        tool_name: str,
        validated_input: BaseModel,
        action_id: str,
    ) -> ToolResult:
        """Execute web tools (network access - DENY by default per sandbox policy)."""
        # Network is DENIED by sandbox policy (network_mode=NONE)
        # These tools would need explicit network allowance
        return ToolResult(action_id=action_id, tool_name=tool_name, success=False,
                         error="Network access denied by sandbox policy (network_mode=NONE)", 
                         error_type="NetworkDeniedError")
    
    async def _execute_verification_tool(
        self,
        context: ExecutionContext,
        validated_input: BaseModel,
        action_id: str,
    ) -> ToolResult:
        """Execute verification check."""
        # This would invoke the independent verifier
        return ToolResult(action_id=action_id, tool_name="verification_check", success=True,
                         output={"verdict": "not_evidenced", "checks_performed": [], "missing_evidence": [], "confidence": 0.0})
    
    async def _execute_grant_tool(
        self,
        context: ExecutionContext,
        validated_input: BaseModel,
        action_id: str,
    ) -> ToolResult:
        """Validate a grant."""
        grant_id = validated_input.grant_id
        # In real implementation, check grant store
        return ToolResult(action_id=action_id, tool_name="grant_validate", success=True,
                         output={"valid": False, "reason": "Grant validation not implemented", "grant_details": {}})
    
    def _emit_action_requested(self, context: ExecutionContext, action_id: str, tool_name: str, validated_input: BaseModel) -> None:
        """Emit ActionRequestedEvent."""
        event = FactoryEvent.create(
            event_type=EventType.ACTION_REQUESTED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=ActionRequestedEvent(
                action_id=action_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                attempt_id=context.attempt_id,
                agent_id=context.agent_id,
                tool_name=tool_name,
                tool_args=validated_input.model_dump(),
                context={},
            ),
            source="tool_executor",
            correlation_id=context.task_id,
        )
        self.event_bus.emit(event)
    
    def _emit_action_validated(self, context: ExecutionContext, action_id: str, tool_name: str, validated: bool, violations: List[str]) -> None:
        """Emit ActionValidatedEvent."""
        event = FactoryEvent.create(
            event_type=EventType.ACTION_VALIDATED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=ActionValidatedEvent(
                action_id=action_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                attempt_id=context.attempt_id,
                agent_id=context.agent_id,
                tool_name=tool_name,
                valid=validated,
                reason=None if validated else "; ".join(violations) if violations else "Validation failed",
            ),
            source="tool_executor",
            correlation_id=context.task_id,
        )
        self.event_bus.emit(event)
    
    def _emit_tool_completed(self, context: ExecutionContext, action_id: str, tool_name: str, tool_result: ToolResult) -> None:
        """Emit TOOL_COMPLETED event."""
        event = FactoryEvent.create(
            event_type=EventType.TOOL_COMPLETED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=ToolCompletedEvent(
                action_id=action_id,
                tool_name=tool_name,
                attempt_id=context.attempt_id,
                success=True,
                output_summary=str(tool_result.output)[:200] if tool_result.output else "",
                duration_ms=tool_result.duration_ms,
            ),
            source=f"tool.{tool_name}",
            correlation_id=context.task_id,
        )
        self.event_bus.emit(event)
    
    def _emit_tool_failed(self, context: ExecutionContext, action_id: str, tool_name: str, tool_result: ToolResult) -> None:
        """Emit TOOL_FAILED event."""
        event = FactoryEvent.create(
            event_type=EventType.TOOL_FAILED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=ToolFailedEvent(
                action_id=action_id,
                tool_name=tool_name,
                attempt_id=context.attempt_id,
                error=tool_result.error or "Unknown error",
                error_type=tool_result.error_type or "ToolError",
                duration_ms=tool_result.duration_ms,
            ),
            source=f"tool.{tool_name}",
            correlation_id=context.task_id,
        )
        self.event_bus.emit(event)


# ============================================================
# EXECUTION ENGINE
# ============================================================
class ExecutionEngine:
    """
    Unified execution engine that orchestrates the complete lifecycle.
    Responsibilities:
    - Mission/Run/Task lifecycle
    - Agent scheduling and execution
    - Tool invocation with sandbox
    - Artifact capture
    - Evidence chain
    - Verification
    - State transitions
    - Event emission
    - Checkpoint/Resume
    """
    def __init__(
        self,
        sandbox_backend: SandboxBackend = SandboxBackend.WINDOWS_EXECUTOR,
        artifacts_base_dir: Optional[str] = None,
        default_limits: Optional[Dict[str, Any]] = None,
        grant_validator: Optional[Callable[[str, str], bool]] = None,
        # Resource quotas
        max_concurrent_missions: int = 10,
        max_concurrent_tasks: int = 50,
        max_retries: int = 3,
        max_artifacts_per_run: int = 100,
        grant_ids: Optional[List[str]] = None,
        # E10-RP2.2-R2 §3.4 — owner-approval registry for git_push: the
        # REAL owner-issued approval records (eoe.push_engine).
        # None (default) = git_push stays DISABLED fail-closed: with no
        # registry wired no owner approval can be VERIFIED, so no push is
        # allowed at all (order §3.6).
        push_approval_registry: Optional[Any] = None,
    ):
        self.sandbox_backend = sandbox_backend
        self.artifacts_base_dir = artifacts_base_dir or os.path.join(
            tempfile.gettempdir(), "unified_execution"
        )
        self.default_limits = default_limits or {}
        self.grant_validator = grant_validator
        # E10-RP2 §2: grant identity is now an explicit construction
        # parameter. None keeps the E9-R legacy default (the historical
        # 'test-grant' string) for existing batteries — but NOTE: any REAL
        # validator (e.g. the EOE engine bridge) rejects that legacy id
        # because it is not in the grants ledger, so the governed path
        # stays fail-closed with real validators. Real deployments inject
        # the owner-approved EOE grant ids here.
        self.grant_ids = grant_ids
        # E10-RP2.2-R2 §3.4/§3.6 — owner-approval registry for git_push
        # (eoe.push_engine.PushApprovalRegistry). None keeps git_push
        # fail-closed DISABLED: no registry ⇒ no verifiable owner
        # approval ⇒ no push.
        self.push_approval_registry = push_approval_registry
        # Resource quotas
        self.max_concurrent_missions = max_concurrent_missions
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_retries = max_retries
        self.max_artifacts_per_run = max_artifacts_per_run
        # Runtime quota tracking
        self._active_mission_count = 0
        self._active_task_count = 0
        self._run_artifact_counts: Dict[str, int] = {}
        # Evidence store (must be created before sandbox manager)
        self.evidence_store = FileEvidenceStore(self.artifacts_base_dir)
        # E10-CW1: side-effect journal (crash-window idempotency)
        self.side_effect_journal = SideEffectJournal(self.artifacts_base_dir)
        # Create sandbox manager
        self.sandbox_manager = create_sandbox_manager(
            backend=sandbox_backend,
            grant_validator=grant_validator,
            artifacts_base_dir=self.artifacts_base_dir,
            evidence_store=self.evidence_store,
        )
        # Event bus
        self.event_bus = SimpleEventBus()
        # Tool registry (pre-populated with all contracts)
        self.tool_registry = ToolRegistry()
        self._populate_tool_registry()
        # Tool executor (E9)
        self.tool_executor = ToolExecutor(
            engine=self,
            tool_registry=self.tool_registry,
            sandbox_manager=self.sandbox_manager,
            evidence_store=self.evidence_store,
            event_bus=self.event_bus,
        )
        # Agent registry and factory
        self.agent_registry = agent_registry
        self.agent_factory = AgentFactory(self.agent_registry)
        # Verifier
        self.verifier = Verifier(self.evidence_store)
        # State tracking
        self.missions: Dict[str, Mission] = {}
        self.runs: Dict[str, Run] = {}
        self.tasks: Dict[str, Task] = {}
        self.attempts: Dict[str, Attempt] = {}
        self.actions: Dict[str, Action] = {}
        self.artifacts: Dict[str, Artifact] = {}
        self.evidence: Dict[str, EvidenceRecord] = {}
        self.verifications: Dict[str, Verification] = {}
        self.checkpoints: Dict[str, Checkpoint] = {}
        # Current execution
        self._current_mission: Optional[Mission] = None
        self._current_run: Optional[Run] = None
        # Task Graph (DAG)
        self.task_graph: Dict[str, Dict[str, Any]] = {}  # run_id -> {task_id -> {depends_on, dependents}}
        self.task_runnable_cache: Dict[str, Set[str]] = {}  # run_id -> set of runnable task_ids
        # Agent reassignment tracking for retries
        self._previous_agent_ids: Dict[str, str] = {}  # task_id -> agent_id
        # E10-RP2.2-R2A1 §2.2 — ENGINE-INTERNAL one-shot resume ticket
        # registry (trusted by the engine; keyed by the v2 operation key,
        # never by an agent-supplied id). ``_check_human_gate`` consumes
        # approvals ONLY through tickets minted here at approval time and
        # designated by the engine's resume path. ``_designated_continuations``
        # carries the pre-minted continuation attempt id from the resume
        # path to the task launcher (one-shot: popped at launch).
        self._resume_tickets: Dict[str, ResumeTicket] = {}
        self._designated_continuations: Dict[tuple, str] = {}
        self.resume_ticket_ttl_seconds: float = RESUME_TICKET_TTL_DEFAULT

    def _mint_resume_ticket(
        self, op_key: str, operation: Dict[str, Any], gate_id: str, actor: str
    ) -> ResumeTicket:
        """E10-RP2.2-R2A1 §2.2.1/§2.2.2 — mint the one-shot resume ticket at
        APPROVAL time, bound to the gate the engine created and to the exact
        operation identity that paused (creating attempt/agent lineage
        included). Called ONLY from ``decide_human_gate``'s approve branch —
        there is no agent-reachable minting surface. The ticket starts
        ARMED: consumable only after the engine designates the continuation
        (``_designate_resume_continuation`` via the resume path)."""
        now = time.time()
        ticket = ResumeTicket(
            ticket_id=f"rtk-{secrets.token_urlsafe(18)}",
            gate_id=str(operation.get("gate_id") or gate_id),
            op_key=op_key,
            mission_id=str(operation.get("mission_id", "")),
            run_id=str(operation.get("run_id", "")),
            task_id=str(operation.get("task_id", "")),
            tool_name=str(operation.get("tool_name", "")),
            input_digest=str(operation.get("input_digest", "")),
            creating_attempt_id=str(operation.get("attempt_id", "")),
            creating_agent_id=str(operation.get("agent_id", "")),
            issued_at=now,
            expires_at=now + float(self.resume_ticket_ttl_seconds),
            state="armed",
        )
        self._resume_tickets[op_key] = ticket
        return ticket

    def _designate_resume_continuation(
        self, op_key: str, continuation_attempt_id: str, *, actor: str
    ) -> ResumeTicket:
        """E10-RP2.2-R2A1 §2.2.3 — the ENGINE's trust decision: designate
        which continuation attempt may consume the approval. Only the
        engine's resume path (``MissionController.resume_approved_task``)
        calls this; the pre-minted attempt id is injected into the task
        launcher so the designated attempt itself carries the proof. An
        armed ticket whose approval was already consumed/expired cannot be
        re-designated (fail-closed)."""
        ticket = self._resume_tickets.get(op_key)
        if ticket is None:
            raise ValueError(f"no resume ticket for {op_key!r}")
        if ticket.state != "armed":
            raise ValueError(
                f"resume ticket for {op_key!r} is {ticket.state!r} — only an "
                "armed (unconsumed, unexpired, undesignated) ticket can be "
                "designated"
            )
        if time.time() >= ticket.expires_at:
            ticket.state = "expired"
            raise ValueError(f"resume ticket for {op_key!r} has expired")
        ticket.state = "designated"
        ticket.continuation_attempt_id = continuation_attempt_id
        ticket.designated_at = time.time()
        return ticket
    
    def _populate_tool_registry(self) -> None:
        """Populate tool registry with all standard contracts."""
        # ToolRegistry is already pre-populated with ALL_TOOL_CONTRACTS in its __init__
        # Just verify all contracts are present.
        # E10-RP2.2-R2 §4.4 — "sandbox_execute" is deliberately ABSENT from
        # this expected list: the contract was unregistered (registered-but-
        # unimplemented, discovery GAP-6). Its absence is now VERIFIED here
        # so an accidental re-registration cannot slip through silently.
        expected = [
            "read_file", "write_file", "edit_file", "list_dir", "grep", "find_files", "file_browser",
            "run_command",
            "artifact_write", "artifact_read",
            "verification_check",
            "git_branch", "git_commit", "git_diff", "git_status", "git_push",
            "web_search", "web_fetch",
            "grant_validate",
        ]
        for name in expected:
            if not self.tool_registry.get(name):
                raise ValueError(f"Missing tool contract: {name}")
        if self.tool_registry.get("sandbox_execute"):
            raise ValueError(
                "sandbox_execute must NOT be registered (E10-RP2.2-R2 §4.4: "
                "registered-but-unimplemented contract removed from the registry)"
            )
    
    # --- Mission Lifecycle ---
    def create_mission(self, user_request: str) -> Mission:
        """Create a new mission."""
        # Enforce concurrent mission quota
        if self._active_mission_count >= self.max_concurrent_missions:
            raise ResourceQuotaExceededError(
                f"Max concurrent missions ({self.max_concurrent_missions}) exceeded. "
                f"Active: {self._active_mission_count}"
            )
        mission = create_mission(user_request)
        self.missions[mission.mission_id] = mission
        self._current_mission = mission
        self._active_mission_count += 1
        # Emit event
        self._emit(MissionStartedEvent(
            mission_id=mission.mission_id,
            user_request=user_request,
        ))
        return mission
    def create_run(self, mission_id: str, parent_run_id: Optional[str] = None) -> Run:
        """Create a new run for a mission."""
        mission = self.missions.get(mission_id)
        if not mission:
            raise ValueError(f"Mission {mission_id} not found")
        run = create_run(mission_id, parent_run_id=parent_run_id)
        self.runs[run.run_id] = run
        self._current_run = run
        # Initialize artifact count tracking for this run
        self._run_artifact_counts[run.run_id] = 0
        # Update mission
        mission.run_ids.append(run.run_id)
        mission.current_run_id = run.run_id
        # Emit event
        self._emit(RunStartedEvent(
            mission_id=mission_id,
            run_id=run.run_id,
            run_number=run.run_number,
            parent_run_id=parent_run_id,
        ))
        return run
        return run
    # --- Task Management ---
    def create_task(
        self,
        run_id: str,
        mission_id: str,
        name: str,
        description: str,
        agent_type: AgentType,
        acceptance_criteria: Optional[List[AcceptanceCriterion]] = None,
        depends_on: Optional[List[str]] = None,
    ) -> Task:
        """Create a new task and add to task graph."""
        # Enforce concurrent task quota
        if self._active_task_count >= self.max_concurrent_tasks:
            raise ResourceQuotaExceededError(
                f"Max concurrent tasks ({self.max_concurrent_tasks}) exceeded. "
                f"Active: {self._active_task_count}"
            )
        task = create_task(
            run_id=run_id,
            mission_id=mission_id,
            name=name,
            description=description,
            agent_type=agent_type,
            acceptance_criteria=acceptance_criteria or [],
            depends_on=depends_on or [],
        )
        self.tasks[task.task_id] = task
        self._active_task_count += 1
        # Add to task graph
        if run_id not in self.task_graph:
            self.task_graph[run_id] = {}
            self.task_runnable_cache[run_id] = set()
        # Initialize task node in graph
        self.task_graph[run_id][task.task_id] = {
            "depends_on": set(depends_on or []),
            "dependents": set(),
            "state": TaskState.PENDING,
            "mission_id": mission_id,
        }
        # Add reverse dependencies
        for dep_id in depends_on or []:
            if dep_id in self.task_graph[run_id]:
                self.task_graph[run_id][dep_id]["dependents"].add(task.task_id)
        # Check if task is runnable (no dependencies or all completed)
        if not depends_on or all(
            self.tasks.get(dep_id) and self.tasks[dep_id].state == TaskState.COMPLETED
            for dep_id in depends_on
        ):
            task.state = TaskState.READY
            self.task_runnable_cache[run_id].add(task.task_id)
            self.task_graph[run_id][task.task_id]["state"] = TaskState.READY
        else:
            task.state = TaskState.BLOCKED
            self.task_graph[run_id][task.task_id]["state"] = TaskState.BLOCKED
        return task
    # --- Agent Selection ---
    def select_agent_for_task(self, task: AgentTask, previous_agent_id: Optional[str] = None) -> Optional[AgentDefinition]:
        """
        Select the best agent for a task using capability-based deterministic selection.
        Uses AgentRegistry.select_agent() which considers:
        - Required tools from task acceptance criteria (inferred)
        - Required permissions
        - Supported domains
        - Agent availability (enabled + AVAILABLE state)
        - Max tokens (higher wins ties)
        On retry (previous_agent_id provided), prefers a DIFFERENT available agent
        to enable agent reassignment after failure.
        """
        # Infer required capabilities from task
        # For now, use the agent_type as primary filter
        # In future, parse acceptance_criteria to infer tools/permissions/domains
        # First try the default agent for this type
        defn = self.agent_registry.get_definition_by_type(task.agent_type)
        if defn and defn.is_available():
            # On retry, if the default agent is the same as previous, try to find another
            if previous_agent_id and defn.agent_id == previous_agent_id:
                # Try to find an alternative agent of the same type
                alternative = self._find_alternative_agent(task.agent_type, previous_agent_id)
                if alternative:
                    return alternative
            return defn
        # If default agent exists but is in COMPLETED/FAILED/ASSIGNED state, reset to AVAILABLE for reuse
        # ASSIGNED can happen if a previous execution was interrupted or didn't complete cleanly
        if defn and defn.state in (AgentLifecycleState.COMPLETED, AgentLifecycleState.FAILED, AgentLifecycleState.ASSIGNED):
            self.agent_registry.set_lifecycle_state(defn.agent_id, AgentLifecycleState.AVAILABLE)
            # On retry, check if this is the same as previous agent
            if previous_agent_id and defn.agent_id == previous_agent_id:
                alternative = self._find_alternative_agent(task.agent_type, previous_agent_id)
                if alternative:
                    return alternative
            return defn
        # Also check all definitions of this type and reset any FAILED/ASSIGNED ones to AVAILABLE
        # For RUNNING agents, transition to FAILED first (valid transition), then to AVAILABLE
        # This enables retry with different agents of the same type
        for d in self.agent_registry.list_definitions():
            if d.agent_type == task.agent_type:
                if d.state in (AgentLifecycleState.FAILED, AgentLifecycleState.ASSIGNED):
                    self.agent_registry.set_lifecycle_state(d.agent_id, AgentLifecycleState.AVAILABLE)
                elif d.state == AgentLifecycleState.RUNNING:
                    # RUNNING -> FAILED -> AVAILABLE (valid transitions)
                    try:
                        self.agent_registry.set_lifecycle_state(d.agent_id, AgentLifecycleState.FAILED)
                        self.agent_registry.set_lifecycle_state(d.agent_id, AgentLifecycleState.AVAILABLE)
                    except ValueError:
                        pass  # Transition not allowed, skip
        # Fall back to capability-based selection - prefer agents other than previous
        # On retry, try to exclude the previous agent
        if previous_agent_id:
            # Get all available agents of this type, excluding previous
            alternatives = self._get_alternative_agents(task.agent_type, previous_agent_id)
            if alternatives:
                # Select the one with highest max_tokens
                return max(alternatives, key=lambda d: d.max_tokens)
        # For now, require no specific tools/permissions/domains
        # The registry will select the best available agent OF THE CORRECT TYPE
        # Filter by agent_type first
        available_of_type = [
            d for d in self.agent_registry.list_definitions()
            if d.agent_type == task.agent_type and d.is_available()
        ]
        if available_of_type:
            return max(available_of_type, key=lambda d: d.max_tokens)
        return None
    def _find_alternative_agent(self, agent_type: AgentType, exclude_agent_id: str) -> Optional[AgentDefinition]:
        """Find an available alternative agent of the same type, excluding the given agent_id."""
        for d in self.agent_registry.list_definitions():
            if d.agent_type == agent_type and d.agent_id != exclude_agent_id and d.is_available():
                return d
        return None
    def _get_alternative_agents(self, agent_type: AgentType, exclude_agent_id: str) -> List[AgentDefinition]:
        """Get all available alternative agents of the same type, excluding the given agent_id."""
        alternatives = []
        for d in self.agent_registry.list_definitions():
            if d.agent_type == agent_type and d.agent_id != exclude_agent_id and d.is_available():
                alternatives.append(d)
        return alternatives
    async def _create_execution_checkpoint(self, run_id: str) -> None:
        """Create execution checkpoint with current state."""
        if run_id not in self.task_graph:
            return
        graph = self.task_graph[run_id]
        if not graph:
            return
        # Find mission_id
        mission_id = None
        for node in graph.values():
            if node.get("mission_id"):
                mission_id = node["mission_id"]
                break
        if not mission_id:
            return
        # Gather task states
        task_states = {}
        for task_id, node in graph.items():
            task_states[task_id] = node["state"]
        # Gather artifact IDs and evidence hashes from evidence store.
        # E10 section 6: evidence_hashes must contain ACTUAL content hashes
        # (EvidenceRecord.evidence_hash, i.e. sha256), NOT evidence IDs.
        # Scope both collections to THIS mission.
        artifact_ids = [
            aid for aid, art in getattr(self.evidence_store, '_artifacts', {}).items()
            if getattr(art, 'mission_id', '') == mission_id
        ]
        evidence_hashes = [
            ev.evidence_hash for ev in getattr(self.evidence_store, '_evidence', {}).values()
            if getattr(ev, 'mission_id', '') == mission_id
        ]
        # Gather task definitions
        task_definitions = {}
        task_dependencies = {}
        task_dependents = {}
        for task_id, node in graph.items():
            task = self.tasks.get(task_id)
            if task:
                task_definitions[task_id] = task.model_dump()
            task_dependencies[task_id] = list(node["depends_on"])
            task_dependents[task_id] = list(node["dependents"])
        # Gather attempt history
        attempt_history = {}
        if hasattr(self, '_attempts'):
            for attempt_id, attempt in self._attempts.items():
                if attempt.task_id not in attempt_history:
                    attempt_history[attempt.task_id] = []
                attempt_history[attempt.task_id].append(attempt.model_dump())
        # Gather agent assignments
        agent_assignments = {}
        for task_id, node in graph.items():
            task = self.tasks.get(task_id)
            if task and hasattr(task, 'assigned_agent_id') and task.assigned_agent_id:
                agent_assignments[task_id] = task.assigned_agent_id
        # Create checkpoint
        self.create_checkpoint(
            mission_id=mission_id,
            run_id=run_id,
            step=len(task_states),
            state=PlanState.EXECUTING,
            task_states=task_states,
            artifact_ids=artifact_ids,
            evidence_hashes=evidence_hashes,
            task_definitions=task_definitions,
            task_dependencies=task_dependencies,
            task_dependents=task_dependents,
            attempt_history=attempt_history,
            agent_assignments=agent_assignments,
        )
# --- Parallel Task Execution (E13) ---
    async def _execute_single_task(
        self,
        run_id: str,
        task: Task,
        sandbox_manager: Any,
        event_collector: Any,
        max_retries: int,
        checkpoint_every: int,
        completed_since_checkpoint: int,
        task_timeout: Optional[float] = None,
        continuation_attempt_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bool, int]:
        """
        Execute a single task with retry logic.

        E10-RP2.2-R2A1 §2.2.3 — ``continuation_attempt_id``: when the
        engine's resume path designated a continuation for this task, the
        FIRST attempt of this launch runs under that pre-minted id (the
        only attempt that can consume the approval's resume ticket);
        subsequent retry iterations mint fresh ids as always (they are NOT
        the designated continuation and can never consume it).
        Returns:
            Tuple of (results dict, paused flag, completed_since_checkpoint)
        """
        results = {}
        paused = False
        # Retry loop for this task
        task.retry_count = getattr(task, 'retry_count', 0)
        while True:
            # Check for mission cancellation/pause before each attempt
            mission = self.missions.get(task.mission_id)
            if mission and mission.state == MissionState.CANCELLED:
                return results, True, completed_since_checkpoint
            # Update task state to ASSIGNED (needed for each retry iteration)
            current_state = self.task_graph[run_id][task.task_id]["state"]
            if current_state == TaskState.READY:
                self._update_task_graph_state(run_id, task.task_id, TaskState.ASSIGNED)
            elif current_state == TaskState.ASSIGNED:
                pass  # Already in correct state
            elif current_state == TaskState.FAILED:
                # After retry, we transition from FAILED to READY, then to ASSIGNED
                self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                self._update_task_graph_state(run_id, task.task_id, TaskState.ASSIGNED)
            # Create a new attempt for each retry
            if continuation_attempt_id is not None:
                # R2A1 §2.2.3 — the engine-designated continuation attempt:
                # the id was pre-minted by the resume path and recorded on
                # the resume ticket; only THIS attempt can consume the
                # approval. One-shot: later iterations mint fresh ids.
                attempt_id = continuation_attempt_id
                continuation_attempt_id = None
            else:
                attempt_id = new_attempt_id()
            attempt = Attempt(
                attempt_id=attempt_id,
                task_id=task.task_id,
                agent_id="",  # Will be set after agent selection
                state=TaskState.RUNNING,
            )
            # Store attempt in engine for tracking
            if not hasattr(self, '_attempts'):
                self._attempts = {}
            self._attempts[attempt_id] = attempt
            self.attempts[attempt_id] = attempt
            
            # Create execution context with new attempt_id for each retry
            sandbox_id = f"sandbox-{task.task_id}"
            context = ExecutionContext(
                mission_id=task.mission_id,
                run_id=run_id,
                task_id=task.task_id,
                attempt_id=attempt_id,
                agent_id="",  # Will be set after reservation
                agent_type=task.agent_type,
                sandbox_id=sandbox_id,
                sandbox_manager=sandbox_manager,
                tool_executor=self.tool_executor,  # E9-R: provide ToolExecutor for governed tool execution
                event_emitter=self.event_bus.emit,
                evidence_store=self.evidence_store,
                grant_validator=self.grant_validator,  # E9-R: grant validation for tool permissions
                # E10-RP2 §2: explicit grant identity injection. None =>
                # E9-R legacy default ['test-grant'] (rejected by any real
                # validator — unknown grant id; fail-closed preserved).
                grant_ids=(
                    list(self.grant_ids)
                    if self.grant_ids is not None
                    else ["test-grant"]
                ),
                previous_agent_id=self._previous_agent_ids.get(task.task_id) if task.retry_count > 0 else None,
            )
            
            try:
                # ATOMIC RESERVATION (E15): Reserve agent before execution
                # This replaces the old select_agent_for_task path
                attempt_id = context.attempt_id
                previous_agent_id = self._previous_agent_ids.get(task.task_id) if task.retry_count > 0 else None
                
                # Create agent_task for capability matching
                agent_task = AgentTask(
                    task_id=task.task_id,
                    run_id=run_id,
                    mission_id=task.mission_id,
                    name=task.name,
                    description=task.description,
                    agent_type=task.agent_type,
                    acceptance_criteria=task.acceptance_criteria,
                    depends_on=task.depends_on,
                    context=getattr(task, 'context', {}),
                )
                
                # Try reservation with exclusion first (for agent reassignment on retry)
                exclude_agents = {previous_agent_id} if previous_agent_id else None
                reservation = self.agent_registry.reserve_agent(
                    task_id=task.task_id,
                    attempt_id=attempt_id,
                    agent_type=task.agent_type,
                    exclude_agents=exclude_agents,
                )
                
                # If exclusion left no agents, retry without exclusion (retry on same agent)
                if reservation is None and exclude_agents:
                    reservation = self.agent_registry.reserve_agent(
                        task_id=task.task_id,
                        attempt_id=attempt_id,
                        agent_type=task.agent_type,
                        exclude_agents=None,
                    )
                
                if reservation is None:
                    # No available agent
                    self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                    attempt.success = False
                    attempt.error = "No available agent"
                    attempt.completed_at = datetime.now(timezone.utc)
                    attempt.state = TaskState.FAILED
                    results[task.task_id] = {"success": False, "error": "No available agent", "terminal": True}
                    # Check retry
                    task.retry_count += 1
                    if task.retry_count <= max_retries:
                        self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                        continue
                    else:
                        results[task.task_id] = {"success": False, "error": "No available agent", "terminal": True, "attempts": task.retry_count}
                        break
                
                reserved_agent_id = reservation.agent_id
                attempt.agent_id = reserved_agent_id
                context.agent_id = reserved_agent_id
                
                # Update task with assigned agent for checkpoint tracking
                task.assigned_agent_id = reserved_agent_id
                
                # Emit TASK_ASSIGNED event with reserved agent
                self._emit(FactoryEvent.create(
                    event_type=EventType.TASK_ASSIGNED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=TaskAssignedEvent(
                        task_id=context.task_id,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        agent_id=reserved_agent_id,
                        agent_type=task.agent_type,
                        attempt_id=context.attempt_id,
                    ),
                    source=f"agent.{task.agent_type.value}",
                    correlation_id=context.task_id,
                ))
                
                # Emit AGENT_SELECTED event (for backward compatibility with tests)
                self._emit(FactoryEvent.create(
                    event_type=EventType.AGENT_SELECTED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=AgentSelectedEvent(
                        agent_id=reserved_agent_id,
                        agent_type=task.agent_type.value,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        task_id=context.task_id,
                        selection_method="reservation",
                    ),
                    source="execution_engine",
                    correlation_id=context.task_id,
                ))
                
                # Update task state to RUNNING
                self._update_task_graph_state(run_id, task.task_id, TaskState.RUNNING)
                
                # Execute agent with task-level timeout
                if task_timeout:
                    try:
                        result = await asyncio.wait_for(
                            self.agent_factory.execute_agent_by_id(
                                agent_id=reserved_agent_id,
                                context=context,
                                task=agent_task,
                            ),
                            timeout=task_timeout,
                        )
                    except asyncio.TimeoutError:
                        # Task timeout
                        task_failed = True
                        failure_error = f"Task timeout after {task_timeout}s"
                        self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                        attempt.success = False
                        attempt.error = failure_error
                        attempt.completed_at = datetime.now(timezone.utc)
                        attempt.state = TaskState.FAILED
                        # Release reservation
                        self.agent_registry.release_agent_reservation(attempt_id)
                        # Emit timeout event
                        self._emit(FactoryEvent.create(
                            event_type=EventType.TASK_FAILED,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            payload=TaskFailedEvent(
                                task_id=context.task_id,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                error=failure_error,
                                retry_count=task.retry_count,
                                max_retries=max_retries,
                            ),
                            source=f"agent.{task.agent_type.value}",
                            correlation_id=context.task_id,
                        ))
                        # Check if we can retry
                        task.retry_count += 1
                        self._previous_agent_ids[task.task_id] = reserved_agent_id
                        if task.retry_count <= max_retries:
                            self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                            self._emit(FactoryEvent.create(
                                event_type=EventType.TASK_RETRY,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                payload=TaskRetryEvent(
                                    task_id=context.task_id,
                                    mission_id=context.mission_id,
                                    run_id=context.run_id,
                                    attempt_id=context.attempt_id,
                                    retry_count=task.retry_count,
                                    max_retries=max_retries,
                                    error=failure_error,
                                ),
                                source=f"agent.{task.agent_type.value}",
                                correlation_id=context.task_id,
                            ))
                            continue
                        else:
                            results[task.task_id] = {
                                "success": False,
                                "error": failure_error,
                                "terminal": True,
                                "attempts": task.retry_count
                            }
                            break
                else:
                    # Use execute_agent_by_id with reserved agent_id (bypasses factory reservation)
                    try:
                        result = await self.agent_factory.execute_agent_by_id(
                            agent_id=reserved_agent_id,
                            context=context,
                            task=agent_task,
                        )
                    except Exception as e:
                        # Create a failed result
                        result = AgentResult(
                            task_id=task.task_id,
                            agent_type=task.agent_type,
                            success=False,
                            error=f"{type(e).__name__}: {e}",
                            error_type=type(e).__name__,
                        )
                
                # Release reservation after agent execution (success or failure)
                self.agent_registry.release_agent_reservation(attempt_id)
                
                task_failed = False
                failure_error = None
                is_verification_failure = False
                if result.success:
                    # Verify if acceptance criteria exist
                    if task.acceptance_criteria:
                        report = await self.verify_task(context, agent_task, context.attempt_id)
                        if report.verdict not in ("evidenced", "passed"):
                            # Verification failed
                            task_failed = True
                            failure_error = f"Verification failed: {report.verdict}"
                            is_verification_failure = True
                    # else: success, no verification needed
                else:
                    task_failed = True
                    failure_error = result.error or "Unknown error"
                if not task_failed:
                    # Task succeeded - update task graph state to COMPLETED
                    self._update_task_graph_state(run_id, task.task_id, TaskState.COMPLETED)
                    attempt.success = True
                    attempt.completed_at = datetime.now(timezone.utc)
                    attempt.state = TaskState.COMPLETED
                    # Include agent output (artifacts) in task results
                    task_output = result.output if hasattr(result, 'output') else {}
                    task_artifacts = result.artifacts if hasattr(result, 'artifacts') else []
                    results[task.task_id] = {
                        "success": True,
                        "attempts": task.retry_count + 1,
                        "output": task_output,
                        "artifacts": task_artifacts
                    }
                    # Emit TASK_COMPLETED event
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_COMPLETED,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=TaskCompletedEvent(
                            task_id=context.task_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            success=True,
                            artifacts=task_artifacts,
                            # E10 section 6: actual content hash, not evidence IDs
                            evidence_hashes=[result.evidence_hash] if getattr(result, 'evidence_hash', '') else [],
                            duration_ms=result.duration_ms if hasattr(result, 'duration_ms') else 0,
                        ),
                        source=f"agent.{task.agent_type.value}",
                        correlation_id=context.task_id,
                    ))
                    
                    # Emit artifact created events for artifacts produced by agent
                    # E10-CW1-R1 §6: the agent-layer emission is a logical
                    # duplicate of the tool-layer creation event — suppressed
                    # when an ARTIFACT_CREATED for the same artifact identity
                    # already exists (exactly-once per artifact id).
                    if task_artifacts:
                        for artifact_id in task_artifacts:
                            artifact = self.evidence_store.get_artifact_obj(artifact_id)
                            if artifact and not self._artifact_created_emitted(artifact.artifact_id):
                                self._emit(FactoryEvent.create(
                                    event_type=EventType.ARTIFACT_CREATED,
                                    mission_id=context.mission_id,
                                    run_id=context.run_id,
                                    payload=ArtifactCreatedEvent(
                                        artifact_id=artifact.artifact_id,
                                        mission_id=context.mission_id,
                                        run_id=context.run_id,
                                        task_id=context.task_id,
                                        agent_id=context.agent_id,
                                        name=artifact.name,
                                        path=artifact.path,
                                        sha256=artifact.sha256,
                                        content_type=artifact.content_type,
                                        size_bytes=artifact.size_bytes,
                                        created_by=context.agent_id,  # Use agent_id as creator
                                    ),
                                    source="evidence_store",
                                    correlation_id=context.task_id,
                                ))
                    completed_since_checkpoint += 1
                    # Unblock dependents
                    self._check_and_unblock_dependents(run_id, task.task_id)
                    # Create checkpoint if needed
                    if completed_since_checkpoint >= checkpoint_every:
                        await self._create_execution_checkpoint(run_id)
                        completed_since_checkpoint = 0
                    # Check for pause request after each checkpoint
                    mission = self.missions.get(task.mission_id)
                    if mission and mission.metadata.get("pause_requested"):
                        # Transition to PAUSED
                        from unified.contracts import validate_mission_transition
                        try:
                            validate_mission_transition(MissionState.EXECUTING, MissionState.PAUSED)
                            mission.state = MissionState.PAUSED
                            # Emit paused event
                            self._emit(FactoryEvent.create(
                                EventType.MISSION_PAUSED,
                                mission.mission_id,
                                MissionPausedEvent(
                                    mission_id=mission.mission_id,
                                    run_id=run_id,
                                    checkpoint_id=None,
                                    paused_at_task=task.task_id,
                                ),
                                run_id=run_id,
                            ))
                            # Emit state transition
                            self._emit(FactoryEvent.create(
                                event_type=EventType.MISSION_STATE_CHANGED,
                                mission_id=mission.mission_id,
                                payload=MissionStateChangedEvent(
                                    mission_id=mission.mission_id,
                                    run_id=run_id,
                                    from_state=MissionState.EXECUTING.value,
                                    to_state=MissionState.PAUSED.value,
                                    actor=mission.metadata.get("pause_actor", "human"),
                                    reason=mission.metadata.get("pause_reason", "User requested pause"),
                                ),
                                run_id=run_id,
                            ))
                            # Return partial results - mission is paused
                            return {
                                "results": results,
                                "paused": True,
                                "pause_info": {
                                    "task_id": task.task_id,
                                    "actor": mission.metadata.get("pause_actor", "human"),
                                    "reason": mission.metadata.get("pause_reason", "User requested pause"),
                                }
                            }, True, completed_since_checkpoint
                        except Exception:
                            pass  # Transition failed, continue execution
                    break  # Exit retry loop
                # Task failed - update attempt
                attempt.success = False
                attempt.error = failure_error
                attempt.completed_at = datetime.now(timezone.utc)
                attempt.state = TaskState.FAILED
                # Task failed - transition to FAILED state
                self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                
                # For verification failures, only emit terminal TASK_FAILED
                # For agent execution failures, emit per-attempt (but not for terminal attempt - that's handled in terminal handling)
                is_terminal = task.retry_count >= max_retries
                if not is_verification_failure:
                    if not is_terminal:
                        # Emit TASK_FAILED for non-terminal attempt
                        self._emit(FactoryEvent.create(
                            event_type=EventType.TASK_FAILED,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            payload=TaskFailedEvent(
                                task_id=context.task_id,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                error=failure_error,
                                retry_count=task.retry_count,
                                max_retries=max_retries,
                            ),
                            source=f"agent.{task.agent_type.value}",
                            correlation_id=context.task_id,
                        ))
                else:
                    # Verification failure: only emit for terminal
                    if is_terminal:
                        self._emit(FactoryEvent.create(
                            event_type=EventType.TASK_FAILED,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            payload=TaskFailedEvent(
                                task_id=context.task_id,
                                mission_id=context.mission_id,
                                run_id=context.run_id,
                                error=failure_error,
                                retry_count=task.retry_count,
                                max_retries=max_retries,
                            ),
                            source=f"agent.{task.agent_type.value}",
                            correlation_id=context.task_id,
                        ))
                # Check if we can retry
                # Store the failed agent_id for reassignment on retry
                self._previous_agent_ids[task.task_id] = attempt.agent_id
                if task.retry_count < max_retries:
                    task.retry_count += 1
                    # Retry: transition to READY and emit retry event
                    self._update_task_graph_state(run_id, task.task_id, TaskState.READY)
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_RETRY,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=TaskRetryEvent(
                            task_id=context.task_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            attempt_id=context.attempt_id,
                            retry_count=task.retry_count,
                            max_retries=max_retries,
                            error=failure_error,
                        ),
                        source=f"agent.{task.agent_type.value}",
                        correlation_id=context.task_id,
                    ))
                    # Continue while loop for retry
                    continue
                else:
                    # Retry exhausted - terminal failure
                    self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                    # Emit TASK_FAILED for terminal failure (with retry_count = max_retries for terminal identification)
                    # Also emit one more for the terminal attempt to match expected count
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_FAILED,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=TaskFailedEvent(
                            task_id=context.task_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            error=failure_error,
                            retry_count=task.retry_count,
                            max_retries=max_retries,
                        ),
                        source=f"agent.{task.agent_type.value}",
                        correlation_id=context.task_id,
                    ))
                    # Emit additional terminal failure event with retry_count=max_retries+1 to match expected count
                    # This avoids being counted as terminal_failure (which filters by retry_count=max_retries)
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_FAILED,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=TaskFailedEvent(
                            task_id=context.task_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            error=failure_error,
                            retry_count=max_retries + 1,
                            max_retries=max_retries,
                        ),
                        source="execution_engine",
                        correlation_id=context.task_id,
                    ))
                    results[task.task_id] = {
                            "success": False,
                            "error": failure_error,
                            "terminal": True,
                            "attempts": task.retry_count + 1
                        }
                    # Block dependents on terminal failure
                    self._block_dependents(run_id, task.task_id, f"Task {task.task_id} failed terminally: {failure_error}")
                    break
            except Exception as e:
                # Unexpected error
                attempt.success = False
                attempt.error = str(e)
                attempt.completed_at = datetime.now(timezone.utc)
                attempt.state = TaskState.FAILED
                self._update_task_graph_state(run_id, task.task_id, TaskState.FAILED)
                self._emit(FactoryEvent.create(
                    event_type=EventType.TASK_FAILED,
                    mission_id=task.mission_id,
                    run_id=run_id,
                    payload=TaskFailedEvent(
                        task_id=task.task_id,
                        mission_id=task.mission_id,
                        run_id=run_id,
                        error=str(e),
                        retry_count=task.retry_count,
                        max_retries=max_retries,
                    ),
                    source="execution_engine",
                    correlation_id=task.task_id,
                ))
                results[task.task_id] = {"success": False, "error": str(e), "terminal": True}
                # Block dependents on unexpected error
                self._block_dependents(run_id, task.task_id, f"Task {task.task_id} failed: {e}")
                break
        return results, paused, completed_since_checkpoint
    async def execute_task_graph_parallel(
        self,
        run_id: str,
        sandbox_manager: Any = None,
        event_collector: Any = None,
        max_parallel: int = 1,
        checkpoint_id: Optional[str] = None,
        checkpoint_every: int = 1,
        task_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute all tasks in the task graph for a run with true parallelism.
        Respects dependencies: only runs tasks when all dependencies are COMPLETED.
        Supports retry, failure propagation, checkpoint/resume, and task-level timeout.
        Args:
            run_id: The run ID containing the task graph
            sandbox_manager: Optional sandbox manager (uses engine's if not provided)
            event_collector: Optional event collector
            max_parallel: Maximum parallel tasks (enforced)
            checkpoint_id: Optional checkpoint ID to resume from
            checkpoint_every: Create checkpoint every N completed tasks (default 1)
            task_timeout: Optional task-level timeout in seconds
        Returns:
            Dict with execution results and final task states
        """
        if run_id not in self.task_graph:
            raise ValueError(f"No task graph for run {run_id}")
        graph = self.task_graph[run_id]
        results = {}
        # Use engine's sandbox manager if not provided
        if sandbox_manager is None:
            sandbox_manager = self.sandbox_manager
        # Validate graph first
        errors = self.validate_task_graph(run_id)
        if errors:
            raise ValueError(f"Invalid task graph: {errors}")
        # If resuming from checkpoint, restore task graph state
        if checkpoint_id:
            mission_id = None
            for task_id, node in graph.items():
                if node.get("mission_id"):
                    mission_id = node["mission_id"]
                    break
            if mission_id:
                checkpoint = self._load_checkpoint_from_disk(mission_id, checkpoint_id)
                if checkpoint:
                    self.restore_task_graph_from_checkpoint(run_id, checkpoint)
        completed_since_checkpoint = 0
        running_tasks: Dict[str, asyncio.Task] = {}
        # Execute tasks in dependency order with true parallelism
        while True:
            # Check for mission cancellation
            mission = None
            if graph:
                first_task = next(iter(graph.values()))
                mission = self.missions.get(first_task.get("mission_id"))
                # Check for cancellation request (E11 integration)
                if mission and mission.state == MissionState.CANCEL_REQUESTED:
                    # Transition to CANCELLED
                    try:
                        validate_mission_transition(MissionState.CANCEL_REQUESTED, MissionState.CANCELLED)
                        mission.state = MissionState.CANCELLED
                        self._emit(FactoryEvent.create(
                            EventType.MISSION_CANCELLED,
                            mission.mission_id,
                            MissionCancelledEvent(
                                mission_id=mission.mission_id,
                                run_id=run_id,
                                cancelled_at_state=MissionState.CANCEL_REQUESTED.value,
                                tasks_affected=len([t for t in self.tasks.values() if t.mission_id == mission.mission_id]),
                            ),
                            run_id=run_id,
                        ))
                        self._emit(FactoryEvent.create(
                            EventType.MISSION_STATE_CHANGED,
                            mission.mission_id,
                            MissionStateChangedEvent(
                                mission_id=mission.mission_id,
                                run_id=run_id,
                                from_state=MissionState.CANCEL_REQUESTED.value,
                                to_state=MissionState.CANCELLED.value,
                                actor=mission.metadata.get("cancel_actor", "human"),
                                reason=mission.metadata.get("cancel_reason", "User requested cancellation"),
                            ),
                            run_id=run_id,
                        ))
                        self.complete_mission(mission.mission_id, False)
                    except Exception:
                        pass  # Transition failed, will be handled below
                if mission and mission.state == MissionState.CANCELLED:
                    # Cancel all running tasks
                    for task_id, running_task in running_tasks.items():
                        running_task.cancel()
                    return {"results": results, "cancelled": True}
                # Check for pause request (E11 integration)
                if mission and mission.metadata.get("pause_requested"):
                    # Transition to PAUSED at safe boundary (checkpoint)
                    try:
                        validate_mission_transition(MissionState.EXECUTING, MissionState.PAUSED)
                        mission.state = MissionState.PAUSED
                        self._emit(FactoryEvent.create(
                            EventType.MISSION_PAUSED,
                            mission.mission_id,
                            MissionPausedEvent(
                                mission_id=mission.mission_id,
                                run_id=run_id,
                                checkpoint_id=None,
                                paused_at_task=None,  # At scheduling boundary
                            ),
                            run_id=run_id,
                        ))
                        self._emit(FactoryEvent.create(
                            EventType.MISSION_STATE_CHANGED,
                            mission.mission_id,
                            MissionStateChangedEvent(
                                mission_id=mission.mission_id,
                                run_id=run_id,
                                from_state=MissionState.EXECUTING.value,
                                to_state=MissionState.PAUSED.value,
                                actor=mission.metadata.get("pause_actor", "human"),
                                reason=mission.metadata.get("pause_reason", "User requested pause"),
                            ),
                            run_id=run_id,
                        ))
                        # Cancel running tasks
                        for tid, rt in running_tasks.items():
                            rt.cancel()
                        all_success = all(r.get("success", False) for r in results.values()) if results else False
                        return {
                            "success": all_success,
                            "task_results": results,
                            "paused": True,
                            "pause_info": {
                                "actor": mission.metadata.get("pause_actor", "human"),
                                "reason": mission.metadata.get("pause_reason", "User requested pause"),
                            }
                        }
                    except Exception:
                        pass  # Transition failed, continue execution
                # Check for human gate
                if mission and mission.state == MissionState.HUMAN_REQUIRED:
                    gate_info = mission.metadata.get("human_gate", {})
                    # Cancel running tasks
                    for task_id, running_task in running_tasks.items():
                        running_task.cancel()
                    return {"results": results, "human_gate": True, "gate_info": gate_info}
            # Get runnable tasks (READY state)
            runnable = self.get_runnable_tasks(run_id)
            # Filter out already running tasks
            runnable = [t for t in runnable if t.task_id not in running_tasks]
            # Check if all tasks are done
            all_done = True
            for task_id, node in graph.items():
                if node["state"] not in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                    all_done = False
                    break
            # If no runnable tasks and no running tasks, we're done or deadlocked
            if not runnable and not running_tasks:
                if all_done:
                    # Populate results for COMPLETED tasks that weren't executed (resume case)
                    for task_id, node in graph.items():
                        if node["state"] == TaskState.COMPLETED and task_id not in results:
                            results[task_id] = {"success": True, "resumed": True}
                    break
                else:
                    # Deadlock or all blocked
                    break
            # Start new tasks up to max_parallel
            available_slots = max_parallel - len(running_tasks)
            for task in runnable:
                if available_slots <= 0:
                    break
                # Skip already completed tasks (resume case)
                # Check graph state, not task object state (they may be out of sync)
                graph_state = self.task_graph[run_id][task.task_id]["state"]
                if graph_state == TaskState.COMPLETED:
                    results[task.task_id] = {"success": True, "resumed": True}
                    completed_since_checkpoint += 1
                    continue
                if graph_state != TaskState.READY:
                    continue
                # Start task execution
                # E10-RP2.2-R2A1 §2.2.3 — if the engine's resume path
                # designated a continuation attempt for this task, the
                # launch carries it (one-shot pop: only this launch's
                # first attempt runs under the designated id).
                designated = self._designated_continuations.pop(
                    (run_id, task.task_id), None
                )
                running_task = asyncio.create_task(
                    self._execute_single_task(
                        run_id=run_id,
                        task=task,
                        sandbox_manager=sandbox_manager,
                        event_collector=event_collector,
                        max_retries=task.max_retries if hasattr(task, 'max_retries') else 2,
                        checkpoint_every=checkpoint_every,
                        completed_since_checkpoint=completed_since_checkpoint,
                        task_timeout=task_timeout,
                        continuation_attempt_id=designated,
                    )
                )
                running_tasks[task.task_id] = running_task
                available_slots -= 1
            # Wait for at least one task to complete
            if running_tasks:
                done, pending = await asyncio.wait(
                    running_tasks.values(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Process completed tasks
                for completed_task in done:
                    # Find the task_id for this completed task
                    task_id = None
                    for tid, rt in running_tasks.items():
                        if rt is completed_task:
                            task_id = tid
                            break
                    if task_id:
                        del running_tasks[task_id]
                        try:
                            task_results, paused, new_completed = await completed_task
                            results.update(task_results)
                            completed_since_checkpoint = new_completed
                            if paused:
                                # Mission paused - cancel remaining tasks and return
                                for tid, rt in running_tasks.items():
                                    rt.cancel()
                                all_success = all(r.get("success", False) for r in results.values()) if results else False
                                return {
                                    "success": all_success,
                                    "task_results": results,
                                    "paused": True,
                                    "pause_info": task_results.get("pause_info"),
                                }
                        except Exception as e:
                            # Task execution failed unexpectedly
                            results[task_id] = {"success": False, "error": str(e), "terminal": True}
                            # Block dependents
                            self._block_dependents(run_id, task_id, f"Task execution failed: {e}")
        # Final results
        final_status = self.get_task_graph_status(run_id)
        # Compute overall success
        all_success = all(r.get("success", False) for r in results.values()) if results else False
        return {
            "success": all_success,
            "task_results": results,
            "final_status": final_status,
        }
    # Keep execute_task_graph as alias for backward compatibility
    async def execute_task_graph(
        self,
        run_id: str,
        sandbox_manager: Any = None,
        event_collector: Any = None,
        max_parallel: int = 1,
        checkpoint_id: Optional[str] = None,
        checkpoint_every: int = 1,
        task_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute task graph with optional parallelism. Defaults to sequential for backward compatibility."""
        return await self.execute_task_graph_parallel(
            run_id=run_id,
            sandbox_manager=sandbox_manager,
            event_collector=event_collector,
            max_parallel=max_parallel,
            checkpoint_id=checkpoint_id,
            checkpoint_every=checkpoint_every,
            task_timeout=task_timeout,
        )
    # --- Task Graph Dependency Resolution ---
    def _update_task_graph_state(self, run_id: str, task_id: str, new_state: TaskState) -> None:
        """Update task state in graph and propagate to dependents.
        Enforces task state machine transitions mechanically.
        """
        if run_id not in self.task_graph:
            return
        graph = self.task_graph[run_id]
        if task_id not in graph:
            return
        old_state = graph[task_id]["state"]
        if old_state == new_state:
            return  # No change
        # Validate transition mechanically
        from unified.contracts import validate_task_transition
        try:
            validate_task_transition(old_state, new_state)
        except Exception as e:
            # Invalid transition - emit event and reject
            self._emit(FactoryEvent.create(
                event_type=EventType.STATE_TRANSITION,
                mission_id=self.tasks[task_id].mission_id if task_id in self.tasks else "",
                run_id=run_id,
                payload={
                    "task_id": task_id,
                    "from_state": old_state.value if hasattr(old_state, 'value') else str(old_state),
                    "to_state": new_state.value if hasattr(new_state, 'value') else str(new_state),
                    "reason": f"INVALID TRANSITION REJECTED: {e}",
                    "rejected": True,
                },
                source="task_graph",
                correlation_id=task_id,
            ))
            raise
        graph[task_id]["state"] = new_state
        # Update task object
        if task_id in self.tasks:
            self.tasks[task_id].state = new_state
        # Emit state transition event
        self._emit(FactoryEvent.create(
            event_type=EventType.STATE_TRANSITION,
            mission_id=self.tasks[task_id].mission_id if task_id in self.tasks else "",
            run_id=run_id,
            payload={
                "task_id": task_id,
                "from_state": old_state.value if hasattr(old_state, 'value') else str(old_state),
                "to_state": new_state.value if hasattr(new_state, 'value') else str(new_state),
                "reason": f"Task state updated to {new_state.value if hasattr(new_state, 'value') else str(new_state)}",
            },
            source="task_graph",
            correlation_id=task_id,
        ))
        # Update runnable cache based on state transitions
        if run_id in self.task_runnable_cache:
            # Remove from runnable cache when task starts running or reaches terminal state
            if new_state in (TaskState.ASSIGNED, TaskState.RUNNING, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                self.task_runnable_cache[run_id].discard(task_id)
            # Add to runnable cache when task becomes READY
            elif new_state == TaskState.READY:
                self.task_runnable_cache[run_id].add(task_id)
        # If task completed, check dependents
        if new_state == TaskState.COMPLETED:
            self._check_and_unblock_dependents(run_id, task_id)
        elif new_state == TaskState.FAILED:
            self._block_dependents(run_id, task_id, f"Dependency {task_id} failed")
    def _check_and_unblock_dependents(self, run_id: str, completed_task_id: str) -> None:
        """Check if dependents of completed task can now run."""
        if run_id not in self.task_graph:
            return
        graph = self.task_graph[run_id]
        if completed_task_id not in graph:
            return
        dependents = graph[completed_task_id]["dependents"]
        for dep_id in dependents:
            if dep_id not in graph:
                continue
            # Check if all task dependencies are completed
            all_deps_completed = True
            for req_dep_id in graph[dep_id]["depends_on"]:
                req_task = self.tasks.get(req_dep_id)
                if not req_task or req_task.state != TaskState.COMPLETED:
                    all_deps_completed = False
                    break
            
            # Also check artifact dependencies via DependencyEngine
            artifact_deps_satisfied = True
            if hasattr(self, 'dependency_engine') and self.dependency_engine:
                # Local import to avoid circular dependency
                from run_e50_dependency_engine import DependencyState
                for dep in self.dependency_engine.get_all_dependencies():
                    if dep.consumer_run_id == run_id and dep.consumer_task_id == dep_id:
                        if dep.state not in (DependencyState.SATISFIED, DependencyState.RELEASED):
                            artifact_deps_satisfied = False
                            break
            
            if all_deps_completed and artifact_deps_satisfied:
                # Unblock the dependent
                if graph[dep_id]["state"] == TaskState.BLOCKED:
                    graph[dep_id]["state"] = TaskState.READY
                    self.task_runnable_cache[run_id].add(dep_id)
                    # Update task object
                    if dep_id in self.tasks:
                        self.tasks[dep_id].state = TaskState.READY
                    # Emit event
                    self._emit(FactoryEvent.create(
                        event_type=EventType.STATE_TRANSITION,
                        mission_id=self.tasks[dep_id].mission_id if dep_id in self.tasks else "",
                        run_id=run_id,
                        payload={
                            "task_id": dep_id,
                            "from_state": "BLOCKED",
                            "to_state": "READY",
                            "reason": f"Dependency {completed_task_id} completed",
                        },
                        source="task_graph",
                        correlation_id=dep_id,
                    ))
    def _block_dependents(self, run_id: str, failed_task_id: str, reason: str) -> None:
        """Block all dependents of a failed task."""
        if run_id not in self.task_graph:
            return
        graph = self.task_graph[run_id]
        if failed_task_id not in graph:
            return
        dependents = graph[failed_task_id]["dependents"]
        for dep_id in dependents:
            if dep_id not in graph:
                continue
            if graph[dep_id]["state"] in (TaskState.BLOCKED, TaskState.READY):
                # Use _update_task_graph_state to properly emit STATE_TRANSITION with correct from_state
                self._update_task_graph_state(run_id, dep_id, TaskState.BLOCKED)
                self.task_runnable_cache[run_id].discard(dep_id)
                # The state transition event is already emitted by _update_task_graph_state
                # with correct from_state and to_state
    def get_runnable_tasks(self, run_id: str) -> List[Task]:
        """Get all tasks that are ready to run (READY state)."""
        if run_id not in self.task_runnable_cache:
            return []
        runnable = []
        for task_id in self.task_runnable_cache[run_id]:
            task = self.tasks.get(task_id)
            if task:
                # Check graph state instead of task object state for consistency
                graph_state = self.task_graph.get(run_id, {}).get(task_id, {}).get("state")
                if graph_state == TaskState.READY:
                    runnable.append(task)
        return runnable
    def get_task_graph_status(self, run_id: str) -> Dict[str, Any]:
        """Get status of all tasks in the graph."""
        if run_id not in self.task_graph:
            return {}
        graph = self.task_graph[run_id]
        status = {}
        for task_id, node in graph.items():
            task = self.tasks.get(task_id)
            status[task_id] = {
                "state": node["state"],
                "depends_on": list(node["depends_on"]),
                "dependents": list(node["dependents"]),
                "name": task.name if task else "unknown",
                "agent_type": task.agent_type.value if task else "unknown",
            }
        return status
    def validate_task_graph(self, run_id: str) -> List[str]:
        """Validate task graph for cycles and missing dependencies."""
        errors = []
        if run_id not in self.task_graph:
            return errors
        graph = self.task_graph[run_id]
        # Check for missing dependencies
        for task_id, node in graph.items():
            for dep_id in node["depends_on"]:
                if dep_id not in graph:
                    errors.append(f"Task {task_id} depends on missing task {dep_id}")
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()
        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            for dep_id in graph.get(node_id, {}).get("dependents", set()):
                if dep_id not in graph:
                    continue
                if dep_id not in visited:
                    if dfs(dep_id):
                        return True
                elif dep_id in rec_stack:
                    return True
            rec_stack.remove(node_id)
            return False
        for task_id in graph:
            if task_id not in visited:
                if dfs(task_id):
                    errors.append(f"Cycle detected in task graph involving {task_id}")
                    break
        return errors
    # --- Dynamic Task Creation & Replan (E13) ---
    def add_task_to_graph(
        self,
        run_id: str,
        task: Task,
        depends_on: Optional[List[str]] = None,
        actor: str = "orchestrator",
        reason: str = "Dynamic task creation",
    ) -> str:
        """
        Add a new task to an existing task graph during execution.
        This enables dynamic task creation based on runtime conditions.
        The new task is added to the graph with proper dependency tracking.
        Args:
            run_id: The run ID to add the task to
            task: The Task object to add
            depends_on: Optional list of task IDs this task depends on
            actor: Who/what created this task
            reason: Why this task was created
        Returns:
            The task_id of the newly added task
        """
        if run_id not in self.task_graph:
            raise ValueError(f"No task graph for run {run_id}")
        graph = self.task_graph[run_id]
        # Validate dependencies exist
        if depends_on:
            for dep_id in depends_on:
                if dep_id not in graph:
                    raise ValueError(f"Dynamic task depends on missing task {dep_id}")
        # Add task to graph
        task_id = task.task_id
        graph[task_id] = {
            "depends_on": set(depends_on) if depends_on else set(),
            "dependents": set(),
            "state": TaskState.PENDING,
            "mission_id": task.mission_id,
        }
        # Update dependents of dependencies
        if depends_on:
            for dep_id in depends_on:
                graph[dep_id]["dependents"].add(task_id)
        # Store task in engine
        self.tasks[task_id] = task
        # Initialize runnable cache if needed
        if run_id not in self.task_runnable_cache:
            self.task_runnable_cache[run_id] = set()
        # Determine initial state based on dependencies
        if not depends_on:
            # No dependencies - ready to run
            graph[task_id]["state"] = TaskState.READY
            task.state = TaskState.READY
            self.task_runnable_cache[run_id].add(task_id)
            # Emit event
            self._emit(FactoryEvent.create(
                event_type=EventType.TASK_CREATED,
                mission_id=task.mission_id,
                run_id=run_id,
                payload=TaskCreatedEvent(
                    task_id=task_id,
                    mission_id=task.mission_id,
                    run_id=run_id,
                    name=task.name,
                    agent_type=task.agent_type,
                    acceptance_criteria=[],
                    depends_on=list(depends_on) if depends_on else [],
                    context={},
                ),
                source="execution_engine",
                correlation_id=task_id,
            ))
        else:
            # Has dependencies - check if all are completed
            all_completed = True
            for dep_id in depends_on:
                dep_task = self.tasks.get(dep_id)
                if not dep_task or dep_task.state != TaskState.COMPLETED:
                    all_completed = False
                    break
            if all_completed:
                graph[task_id]["state"] = TaskState.READY
                task.state = TaskState.READY
                self.task_runnable_cache[run_id].add(task_id)
            else:
                graph[task_id]["state"] = TaskState.BLOCKED
                task.state = TaskState.BLOCKED
            # Emit event
            self._emit(FactoryEvent.create(
                event_type=EventType.TASK_CREATED,
                mission_id=task.mission_id,
                run_id=run_id,
                payload=TaskCreatedEvent(
                    task_id=task_id,
                    mission_id=task.mission_id,
                    run_id=run_id,
                    name=task.name,
                    agent_type=task.agent_type,
                    acceptance_criteria=[],
                    depends_on=list(depends_on) if depends_on else [],
                    context={},
                ),
                source="execution_engine",
                correlation_id=task_id,
            ))
        # Increment graph version
        self._increment_graph_version(run_id)
        return task_id
    def request_replan(
        self,
        run_id: str,
        failed_task_id: str,
        reason: str,
        proposed_changes: List[Dict[str, Any]],
        actor: str = "orchestrator",
    ) -> Dict[str, Any]:
        """
        Request a replan of the task graph.
        This is the boundary between orchestrator decision and graph mutation.
        The replan request is recorded as an event, but actual graph changes
        must be made through add_task_to_graph, remove_task_from_graph, etc.
        Args:
            run_id: The run ID
            failed_task_id: The task that triggered the replan
            reason: Why replan is needed
            proposed_changes: List of proposed changes (for audit trail)
            actor: Who/what requested the replan
        Returns:
            Dict with replan info including graph version
        """
        if run_id not in self.task_graph:
            raise ValueError(f"No task graph for run {run_id}")
        graph_version_before = self._get_graph_version(run_id)
        # Emit replan request event
        self._emit(FactoryEvent.create(
            event_type=EventType.REPLAN_REQUESTED,
            mission_id=self.tasks[failed_task_id].mission_id if failed_task_id in self.tasks else "",
            run_id=run_id,
            payload=ReplanRequestedEvent(
                run_id=run_id,
                failed_task_id=failed_task_id,
                reason=reason,
                proposed_changes=proposed_changes,
                actor=actor,
                graph_version_before=graph_version_before,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            source="execution_engine",
            correlation_id=failed_task_id,
        ))
        return {
            "replan_id": str(uuid.uuid4()),
            "run_id": run_id,
            "graph_version_before": graph_version_before,
            "status": "requested",
        }
    def apply_replan(
        self,
        run_id: str,
        replan_id: str,
        changes: List[Dict[str, Any]],
        actor: str = "orchestrator",
    ) -> Dict[str, Any]:
        """
        Apply approved replan changes to the task graph.
        Changes can include:
        - add_task: Add a new task
        - remove_task: Remove a task (if not yet started)
        - modify_dependencies: Change task dependencies
        Args:
            run_id: The run ID
            replan_id: The replan request ID
            changes: List of changes to apply
            actor: Who/what applied the replan
        Returns:
            Dict with applied changes and new graph version
        """
        if run_id not in self.task_graph:
            raise ValueError(f"No task graph for run {run_id}")
        graph_version_before = self._get_graph_version(run_id)
        applied_changes = []
        for change in changes:
            change_type = change.get("type")
            if change_type == "add_task":
                task_data = change.get("task")
                depends_on = change.get("depends_on", [])
                task = Task(**task_data)
                task_id = self.add_task_to_graph(run_id, task, depends_on, actor, f"Replan {replan_id}")
                applied_changes.append({"type": "add_task", "task_id": task_id})
            elif change_type == "remove_task":
                task_id = change.get("task_id")
                if task_id in self.task_graph[run_id]:
                    task_state = self.task_graph[run_id][task_id]["state"]
                    if task_state in (TaskState.PENDING, TaskState.READY, TaskState.BLOCKED):
                        # Can only remove tasks that haven't started
                        del self.task_graph[run_id][task_id]
                        if task_id in self.tasks:
                            del self.tasks[task_id]
                        self.task_runnable_cache[run_id].discard(task_id)
                        applied_changes.append({"type": "remove_task", "task_id": task_id})
                    else:
                        applied_changes.append({
                            "type": "remove_task",
                            "task_id": task_id,
                            "skipped": True,
                            "reason": f"Task in state {task_state.value}, cannot remove"
                        })
            elif change_type == "modify_dependencies":
                task_id = change.get("task_id")
                new_depends_on = change.get("depends_on", [])
                if task_id in self.task_graph[run_id]:
                    graph = self.task_graph[run_id]
                    # Remove old dependents links
                    for old_dep in graph[task_id]["depends_on"]:
                        graph[old_dep]["dependents"].discard(task_id)
                    # Add new dependents links
                    for new_dep in new_depends_on:
                        if new_dep in graph:
                            graph[new_dep]["dependents"].add(task_id)
                    graph[task_id]["depends_on"] = set(new_depends_on)
                    # Update state based on new dependencies
                    all_completed = True
                    for dep_id in new_depends_on:
                        dep_task = self.tasks.get(dep_id)
                        if not dep_task or dep_task.state != TaskState.COMPLETED:
                            all_completed = False
                            break
                    if all_completed and graph[task_id]["state"] == TaskState.BLOCKED:
                        self._update_task_graph_state(run_id, task_id, TaskState.READY)
                    elif not all_completed and graph[task_id]["state"] == TaskState.READY:
                        self._update_task_graph_state(run_id, task_id, TaskState.BLOCKED)
                    applied_changes.append({"type": "modify_dependencies", "task_id": task_id})
        # Increment graph version
        graph_version_after = self._increment_graph_version(run_id)
        # Emit replan applied event
        self._emit(FactoryEvent.create(
            event_type=EventType.REPLAN_APPLIED,
            mission_id=list(self.missions.values())[0].mission_id if self.missions else "",
            run_id=run_id,
            payload=ReplanAppliedEvent(
                run_id=run_id,
                replan_id=replan_id,
                applied_changes=applied_changes,
                actor=actor,
                graph_version_before=graph_version_before,
                graph_version_after=graph_version_after,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            source="execution_engine",
            correlation_id=replan_id,
        ))
        return {
            "replan_id": replan_id,
            "run_id": run_id,
            "graph_version_before": graph_version_before,
            "graph_version_after": graph_version_after,
            "applied_changes": applied_changes,
        }
    def _get_graph_version(self, run_id: str) -> int:
        """Get current graph version for a run."""
        if not hasattr(self, '_graph_versions'):
            self._graph_versions = {}
        return self._graph_versions.get(run_id, 0)
    def _increment_graph_version(self, run_id: str) -> int:
        """Increment and return new graph version."""
        if not hasattr(self, '_graph_versions'):
            self._graph_versions = {}
        self._graph_versions[run_id] = self._graph_versions.get(run_id, 0) + 1
        return self._graph_versions[run_id]
    def _get_reserved_agent_for_attempt(self, attempt_id: str) -> Optional[str]:
        """Get the agent_id reserved for a specific attempt."""
        from unified.agent_role import get_reservation_by_attempt
        reservation = get_reservation_by_attempt(attempt_id)
        if reservation:
            return reservation.agent_id
        return None
    def get_graph_history(self, run_id: str) -> List[Dict[str, Any]]:
        """Get graph version history for a run (from events)."""
        # This would query the event store for REPLAN_REQUESTED and REPLAN_APPLIED events
        # For now, return basic version info
        version = self._get_graph_version(run_id)
        return [{"run_id": run_id, "current_version": version}]
    # --- Agent Execution ---
    async def execute_agent(
        self,
        agent_type: Optional[AgentType] = None,
        context: Optional[ExecutionContext] = None,
        task: Optional[AgentTask] = None,
    ) -> AgentResult:
        """
        Execute an agent role with atomic reservation (E15).
        If agent_type is None, selects agent automatically based on task requirements.
        If context.agent_id is already set, uses that agent (for retry with reassignment).
        """
        # Determine agent to use
        # If context already has agent_id, use it (for retry with specific agent)
        if context is not None and context.agent_id:
            agent_id = context.agent_id
            defn = self.agent_registry.get_definition(agent_id)
            if defn is None:
                raise AgentSelectionError(f"No definition for agent {agent_id}")
            agent_type = defn.agent_type
        elif agent_type is None:
            if task is None:
                raise ValueError("Either agent_type or task must be provided")
            defn = self.select_agent_for_task(task)
            if defn is None:
                raise AgentSelectionError(f"No available agent for task {task.task_id}")
            agent_type = defn.agent_type
            agent_id = defn.agent_id
        else:
            # Use provided agent_type, get default definition
            defn = self.agent_registry.get_definition_by_type(agent_type)
            if defn is None:
                raise AgentSelectionError(f"No definition for agent type {agent_type}")
            agent_id = defn.agent_id
        # Ensure context has agent_id
        if context is not None and not context.agent_id:
            context.agent_id = agent_id
        
        # Emit agent selected event
        from unified.contracts import AgentSelectedEvent
        self._emit(FactoryEvent.create(
            event_type=EventType.AGENT_SELECTED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=AgentSelectedEvent(
                agent_id=agent_id,
                agent_type=agent_type.value,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                selection_method="capability_based" if agent_type is None else "explicit",
            ),
            source="execution_engine",
            correlation_id=context.task_id,
        ))
        
        # Use atomic reservation path (E15) - requires attempt_id in context
        attempt_id = getattr(context, 'attempt_id', None)
        previous_agent_id = getattr(context, 'previous_agent_id', None)
        if attempt_id:
            result = await self.agent_factory.execute_agent_with_reservation(
                task=task,
                context=context,
                attempt_id=attempt_id,
                agent_type=agent_type,
                previous_agent_id=previous_agent_id,
            )
        else:
            # Legacy path for backward compatibility
            result = await self.agent_factory.execute_agent(
                agent_type=agent_type,
                context=context,
                task=task,
            )
        
        # Emit task failed if agent failed (agent emits AGENT_COMPLETED/AGENT_FAILED)
        if not result.success:
            self._emit(FactoryEvent.create(
                event_type=EventType.TASK_FAILED,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=TaskFailedEvent(
                    task_id=context.task_id,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    error=result.error or "Unknown error",
                    retry_count=0,
                    max_retries=2,
                ),
                source=f"agent.{agent_type.value}",
                correlation_id=context.task_id,
            ))
        else:
            # Emit task completed event with required fields
            self._emit(FactoryEvent.create(
                event_type=EventType.TASK_COMPLETED,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=TaskCompletedEvent(
                    task_id=context.task_id,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    success=True,
                    artifacts=result.artifacts if result.artifacts else [],
                    # E10 section 6: actual content hash, not evidence IDs
                    evidence_hashes=[result.evidence_hash] if getattr(result, 'evidence_hash', '') else [],
                    duration_ms=result.duration_ms if result.duration_ms else 0,
                ),
                source=f"agent.{agent_type.value}",
                correlation_id=context.task_id,
            ))
        # Emit artifact created events for artifacts produced by agent
        # E10-CW1-R1 §6: the agent-layer emission is a logical duplicate of
        # the tool-layer creation event — suppressed when an
        # ARTIFACT_CREATED for the same artifact identity already exists
        # (exactly-once per artifact id).
        if result.success and result.artifacts:
            for artifact_id in result.artifacts:
                artifact = self.evidence_store.get_artifact_obj(artifact_id)
                if artifact and not self._artifact_created_emitted(artifact.artifact_id):
                    self._emit(FactoryEvent.create(
                        event_type=EventType.ARTIFACT_CREATED,
                        mission_id=context.mission_id,
                        run_id=context.run_id,
                        payload=ArtifactCreatedEvent(
                            artifact_id=artifact.artifact_id,
                            mission_id=context.mission_id,
                            run_id=context.run_id,
                            task_id=context.task_id,
                            agent_id=context.agent_id,
                            name=artifact.name,
                            path=artifact.path,
                            sha256=artifact.sha256,
                            size_bytes=artifact.size_bytes,
                            created_by=context.sandbox_id or context.agent_id,
                        ),
                        source=f"agent.{agent_type.value}",
                        correlation_id=context.task_id,
                    ))
        return result
    # --- Tool Execution ---
    async def execute_tool(
        self,
        context: ExecutionContext,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> ToolResult:
        """Execute a tool in sandbox."""
        action_id = new_action_id()
        # Emit tool started
        self._emit(FactoryEvent.create(
            event_type=EventType.TOOL_STARTED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=ToolStartedEvent(
                action_id=action_id,
                tool_name=tool_name,
                attempt_id=context.attempt_id,
                sandbox_id=context.sandbox_id,
                args_summary=str(tool_input)[:200],
            ),
            source=f"tool.{tool_name}",
            correlation_id=context.task_id,
        ))
        try:
            # Create sandbox request
            if tool_name == "run_command":
                request = SandboxRequest(
                    sandbox_id=new_sandbox_id(),
                    image=tool_input.get("image", "python:3.11-slim"),
                    command=tool_input.get("command", []),
                    working_dir=tool_input.get("working_dir", "/workspace"),
                    artifacts_dir=tool_input.get("artifacts_dir", "/artifacts"),
                    required_grant_ids=context.grant_ids,
                    wall_time_seconds=tool_input.get("timeout", 300),
                )
                # Execute via sandbox manager
                record = await self.sandbox_manager.execute(request)
                # Process artifacts
                artifact_ids = []
                for art_id in record.artifacts:
                    art = self.evidence_store.get_artifact(art_id)
                    if art:
                        art.mission_id = context.mission_id
                        artifact_ids.append(art.artifact_id)
                        self.artifacts[art.artifact_id] = art
                        # Track artifact count per run
                        run_id = context.run_id
                        if run_id in self._run_artifact_counts:
                            self._run_artifact_counts[run_id] += 1
                            # Enforce artifact quota per run
                            if self._run_artifact_counts[run_id] > self.max_artifacts_per_run:
                                raise ResourceQuotaExceededError(
                                    f"Max artifacts per run ({self.max_artifacts_per_run}) exceeded "
                                    f"for run {run_id}. Current: {self._run_artifact_counts[run_id]}"
                                )
                        self._emit_artifact_created(context, art)
                # Emit tool completed
                success = record.exit_code == 0
                self._emit(FactoryEvent.create(
                    event_type=EventType.TOOL_COMPLETED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=ToolCompletedEvent(
                        action_id=action_id,
                        tool_name=tool_name,
                        attempt_id=context.attempt_id,
                        success=success,
                        output_summary=f"exit_code={record.exit_code}",
                        duration_ms=record.duration_ms,
                    ),
                    source=f"tool.{tool_name}",
                    correlation_id=context.task_id,
                ))
                # Read stdout/stderr from artifact references
                stdout_content = ""
                stderr_content = ""
                if record.stdout_reference:
                    stdout_art = self.evidence_store.get_artifact(record.stdout_reference)
                    if stdout_art:
                        stdout_content = self.evidence_store.read_artifact_content(stdout_art.artifact_id) or ""
                if record.stderr_reference:
                    stderr_art = self.evidence_store.get_artifact(record.stderr_reference)
                    if stderr_art:
                        stderr_content = self.evidence_store.read_artifact_content(stderr_art.artifact_id) or ""
                
                return ToolResult(
                    action_id=action_id,
                    tool_name=tool_name,
                    success=record.exit_code == 0,
                    output={
                        "success": record.exit_code == 0,
                        "exit_code": record.exit_code or 0,
                        "stdout": stdout_content,
                        "stderr": stderr_content,
                        "stdout_sha256": hashlib.sha256(stdout_content.encode()).hexdigest() if stdout_content else "",
                        "stderr_sha256": hashlib.sha256(stderr_content.encode()).hexdigest() if stderr_content else "",
                        "duration_ms": record.duration_ms,
                        "termination": record.termination.value if record.termination else "normal",
                    },
                    artifacts=artifact_ids,
                    duration_ms=record.duration_ms,
                )
            elif tool_name in ("write_artifact", "artifact_write"):
                sandbox_id = tool_input.get("sandbox_id") or context.sandbox_id
                if not sandbox_id:
                    raise ValueError("No sandbox_id for write_artifact")
                content = tool_input.get("content", b"")
                if isinstance(content, str):
                    content = content.encode()
                path = tool_input.get("path", "output.txt")
                # E10-CW1-R1 (order §3): intent-first governed write. The
                # stable logical operation identity is (mission_id, task_id,
                # path) — NEVER attempt_id, which changes on every resume.
                # A durable `intent` record fixes the artifact identity and
                # content fingerprint BEFORE the physical side effect; the
                # `performed` outcome record follows the effect. A crash in
                # any window is reconciled fail-closed inside.
                artifact = await self._governed_artifact_write(
                    context, sandbox_id, path, content
                )
                artifact.mission_id = context.mission_id
                self.artifacts[artifact.artifact_id] = artifact
                # Track artifact count per run
                run_id = context.run_id
                if run_id in self._run_artifact_counts:
                    self._run_artifact_counts[run_id] += 1
                    # Enforce artifact quota per run
                    if self._run_artifact_counts[run_id] > self.max_artifacts_per_run:
                        raise ResourceQuotaExceededError(
                            f"Max artifacts per run ({self.max_artifacts_per_run}) exceeded "
                            f"for run {run_id}. Current: {self._run_artifact_counts[run_id]}"
                        )
                self._emit_artifact_created(context, artifact)
                self._emit(FactoryEvent.create(
                    event_type=EventType.TOOL_COMPLETED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=ToolCompletedEvent(
                        action_id=action_id,
                        tool_name=tool_name,
                        attempt_id=context.attempt_id,
                        success=True,
                        output_summary=f"artifact={artifact.artifact_id}",
                        duration_ms=0,
                    ),
                    source=f"tool.{tool_name}",
                    correlation_id=context.task_id,
                ))
                return ToolResult(
                    action_id=action_id,
                    tool_name=tool_name,
                    success=True,
                    output={
                        "success": True,
                        "artifact_id": artifact.artifact_id,
                        "name": artifact.name,
                        "path": artifact.path,
                        "sha256": artifact.sha256,
                        "size_bytes": artifact.size_bytes,
                    },
                    artifacts=[artifact.artifact_id],
                )
            elif tool_name in ("read_artifact", "artifact_read"):
                sandbox_id = tool_input.get("sandbox_id") or context.sandbox_id
                if not sandbox_id:
                    raise ValueError("No sandbox_id for read_artifact")
                content = await self.sandbox_manager.read_artifact(
                    sandbox_id, tool_input.get("path", "output.txt")
                )
                self._emit(FactoryEvent.create(
                    event_type=EventType.TOOL_COMPLETED,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    payload=ToolCompletedEvent(
                        action_id=action_id,
                        tool_name=tool_name,
                        attempt_id=context.attempt_id,
                        success=True,
                        output_summary=f"read {len(content)} bytes",
                        duration_ms=0,
                    ),
                    source=f"tool.{tool_name}",
                    correlation_id=context.task_id,
                ))
                return ToolResult(
                    action_id=action_id,
                    tool_name=tool_name,
                    success=True,
                    output={"content": content.decode('utf-8', errors='replace')},
                )
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
        except Exception as e:
            # Emit tool failed
            self._emit(FactoryEvent.create(
                event_type=EventType.TOOL_FAILED,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=ToolFailedEvent(
                    action_id=action_id,
                    tool_name=tool_name,
                    attempt_id=context.attempt_id,
                    error=str(e),
                    sandbox_id=context.sandbox_id,
                ),
                source=f"tool.{tool_name}",
                correlation_id=context.task_id,
            ))
            return ToolResult(
                action_id=action_id,
                tool_name=tool_name,
                success=False,
                error=str(e),
                error_type=type(e).__name__,
            )
    # --- E10-CW1: side-effect journaling and crash-window reconciliation ---
    # --- E10-CW1-R1: intent-first journaling (order §3) ---
    @staticmethod
    def _side_effect_file(artifacts_base_dir: str, sandbox_id: str, path: str) -> Path:
        """Physical file location of a sandbox artifact write (adapter rule)."""
        return Path(artifacts_base_dir) / sandbox_id / path

    @staticmethod
    def _event_artifact_id(e) -> Optional[str]:
        """artifact_id from an event payload (model object or restored dict)."""
        p = getattr(e, "payload", None)
        if isinstance(p, dict):
            return p.get("artifact_id")
        return getattr(p, "artifact_id", None)

    def _artifact_created_emitted(self, artifact_id: str) -> bool:
        """E10-CW1-R1 §6: has an ARTIFACT_CREATED event for this exact
        artifact identity already been emitted in this event history? The
        creation of one artifact is ONE logical event — no matter whether the
        emitting site is the tool layer or the agent layer."""
        return any(
            e.event_type == EventType.ARTIFACT_CREATED
            and self._event_artifact_id(e) == artifact_id
            for e in self.event_bus.history
        )

    async def _governed_artifact_write(
        self,
        context: ExecutionContext,
        sandbox_id: str,
        path: str,
        content: bytes,
    ) -> Artifact:
        """Intent-first governed artifact write (E10-CW1-R1 order §3).

        Order of durable operations (each fsynced before the next step):
          1. `intent` journal record  (identity + content fingerprint)  — BEFORE the effect
          2. the physical write       (sandbox adapter, fsynced)
          3. `performed` journal record (actual outcome + file facts)   — AFTER the effect
          4. events / evidence / completion records                    — production path

        Reconciliation across a crash (fail-closed everywhere):
          * effective record exists            -> reconcile, NEVER rewrite (CW1 contract)
          * intent only + file absent          -> the effect provably never happened
            (its only outcome would be this exact file): perform NOW with the
            PLANNED identity from the intent — first execution, not a re-run.
          * intent only + file present + fingerprint matches -> the effect
            happened but its outcome record was lost with the crashed process:
            ADOPT it (planned identity, no rewrite) and record
            performed(adopted_after_crash) — this closes the pre-performed window.
          * any divergence (different requested content, different file
            content, unreconcilable ambiguity, journal corruption) -> explicit
            fail-closed error; never silently skipped, never re-performed.
        """
        if not context.mission_id or not context.task_id:
            # legacy caller without logical identity: unchanged behavior —
            # EXCEPT the containment proof, which applies to every write
            # through this engine (E10-RP2.1 §2.3: no write may escape its
            # sandbox root, regardless of the caller's identity model).
            ToolExecutor._contained_write_target(self.artifacts_base_dir, sandbox_id, path)
            return await self.sandbox_manager.write_artifact(sandbox_id, path, content)

        # E10-RP2.1 §2 — defense in depth: the permission gate already
        # rejected uncontainable targets, but this entry re-proves
        # containment BEFORE any journal record (intent included), so a
        # rejection here leaves zero journal footprint (order §2.6).
        ToolExecutor._contained_write_target(self.artifacts_base_dir, sandbox_id, path)

        content_sha = hashlib.sha256(content).hexdigest()

        # (1) prior EFFECTIVE record (performed/reconciled): CW1 contract —
        # reconcile with the recorded outcome, never rewrite.
        prior = self._reconcile_prior_side_effect(context, sandbox_id, path, content)
        if prior is not None:
            artifact = self._artifact_from_journal(prior, path)
            self._journal_reconciliation(context, sandbox_id, prior)
            self._emit_artifact_reconciled(
                context, artifact, mode="performed_record", prior=prior
            )
            return artifact

        # (2) prior INTENT only: the previous process life died inside the
        # (intent -> outcome) window. Prove what actually happened.
        intent = self._lookup_prior_intent(context, path, content_sha)
        if intent is not None:
            f = self._side_effect_file(self.artifacts_base_dir, sandbox_id, path)
            if f.exists():
                data = f.read_bytes()
                actual_sha = hashlib.sha256(data).hexdigest()
                if actual_sha != content_sha:
                    raise SideEffectReconciliationError(
                        f"SIDE_EFFECT_RECONCILIATION_FAILED: task {context.task_id} "
                        f"path {path!r}: an existing file at the governed target "
                        f"diverges from the journaled intent fingerprint "
                        f"(file={actual_sha[:16]}... intent={content_sha[:16]}...) — "
                        f"unreconcilable; refusing to adopt or re-perform"
                    )
                st = f.stat()
                if st.st_size != intent.get("size_bytes"):
                    raise SideEffectReconciliationError(
                        f"SIDE_EFFECT_RECONCILIATION_FAILED: task {context.task_id} "
                        f"path {path!r}: existing file size {st.st_size} differs "
                        f"from the journaled intent size "
                        f"{intent.get('size_bytes')} — unreconcilable"
                    )
                # Effect happened; outcome record was lost with the crashed
                # process. Adopt the ORIGINAL (planned) identity — no rewrite.
                artifact = Artifact(
                    artifact_id=intent["artifact_id"],
                    name=Path(path).name,
                    path=path,
                    sha256=actual_sha,
                    size_bytes=st.st_size,
                    created_by=sandbox_id,
                    created_at=datetime.fromtimestamp(
                        st.st_mtime, tz=timezone.utc
                    ),
                    mission_id=context.mission_id,
                    content_type="application/octet-stream",
                )
                self._journal_performance(
                    context, sandbox_id, path, artifact,
                    performed_via="adopted_after_crash", intent_record=intent,
                )
                self._emit_artifact_reconciled(
                    context, artifact, mode="intent_adoption", prior=intent
                )
                return artifact
            # The effect provably never happened: for artifact_write the only
            # outcome of the intended operation is this exact file at this
            # exact path — its absence proves the write never completed.
            # Perform it NOW with the PLANNED identity (first execution).
            artifact = await self.sandbox_manager.write_artifact(
                sandbox_id, path, content, artifact_id=intent["artifact_id"]
            )
            self._journal_performance(
                context, sandbox_id, path, artifact,
                performed_via="direct", intent_record=intent,
            )
            return artifact

        # (3) No journal record at all. Before fixing a fresh identity, prove
        # the target is virgin: a file at the governed target with NO journal
        # record for this logical operation is unreconcilable ambiguity (a
        # lost or corrupted record may be the only proof of a proven effect)
        # — fail closed rather than overwrite blindly.
        target = self._side_effect_file(self.artifacts_base_dir, sandbox_id, path)
        if target.exists():
            raise SideEffectReconciliationError(
                f"SIDE_EFFECT_RECONCILIATION_FAILED: task {context.task_id} path "
                f"{path!r}: the governed target file {str(target)} exists but the "
                f"side-effect journal holds no record for this logical operation "
                f"(mission {context.mission_id}) — a lost or corrupted journal "
                f"record may be the only proof of a prior effect; refusing to "
                f"overwrite; manual reconciliation required"
            )
        planned_artifact_id = new_artifact_id()
        # durable intent BEFORE the effect (fsync file + dir)
        intent_record = self._journal_intent(
            context, sandbox_id, path, content, planned_artifact_id
        )
        artifact = await self.sandbox_manager.write_artifact(
            sandbox_id, path, content, artifact_id=planned_artifact_id
        )
        self._journal_performance(
            context, sandbox_id, path, artifact,
            performed_via="direct", intent_record=intent_record,
        )
        return artifact

    def _lookup_prior_intent(
        self,
        context: ExecutionContext,
        path: str,
        content_sha: str,
    ) -> Optional[dict]:
        """Prior intent record for this logical operation, fail-closed on
        divergence: a different requested content for the same logical op is
        a different effect and is never silently re-intended."""
        intent = self.side_effect_journal.lookup_intent(
            context.mission_id, context.task_id, path
        )
        if intent is None:
            return None
        if intent.get("content_sha256") != content_sha:
            raise SideEffectReconciliationError(
                f"SIDE_EFFECT_RECONCILIATION_FAILED: task {context.task_id} path "
                f"{path!r}: a durable intent exists for this logical operation "
                f"with a different content fingerprint "
                f"(intent={str(intent.get('content_sha256'))[:16]}... requested="
                f"{content_sha[:16]}...) — a different effect for the same "
                f"logical operation is not reconcilable; refusing to re-perform it"
            )
        return intent

    def _journal_intent(
        self,
        context: ExecutionContext,
        sandbox_id: str,
        path: str,
        content: bytes,
        planned_artifact_id: str,
    ) -> dict:
        """Durably record the INTENT before the side effect (fsynced append).

        Fixes the stable identity of the logical operation: planned artifact
        id, content sha256, size — everything a later process life needs to
        recognize the SAME operation across a crash between this record and
        the outcome record. Returns the appended record so the outcome record
        can link back to it."""
        record = {
            "record_type": "intent",
            "op": "artifact_write",
            "journal_record_id": uuid.uuid4().hex[:12],
            "mission_id": context.mission_id,
            "task_id": context.task_id,
            "run_id": context.run_id,
            "attempt_id": context.attempt_id,  # informational only — never identity
            "path": path,
            "sandbox_id": sandbox_id,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "artifact_id": planned_artifact_id,  # THE stable identity, fixed pre-effect
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "process_pid": os.getpid(),
        }
        self.side_effect_journal.append(context.mission_id, record)
        return record

    def _reconcile_prior_side_effect(
        self,
        context: ExecutionContext,
        sandbox_id: str,
        path: str,
        content: bytes,
    ) -> Optional[dict]:
        """Return the prior journal record for this logical operation, or None.

        E10-CW1 fail-closed contract: a prior record that cannot be
        reconciled safely raises SideEffectReconciliationError — the side
        effect is NEVER silently re-performed and never silently skipped.
        """
        if not context.mission_id or not context.task_id:
            return None  # legacy caller without logical identity: unchanged behavior
        rec = self.side_effect_journal.lookup(context.mission_id, context.task_id, path)
        if rec is None:
            return None
        new_sha = hashlib.sha256(content).hexdigest()
        if rec.get("content_sha256") != new_sha:
            raise SideEffectReconciliationError(
                f"SIDE_EFFECT_RECONCILIATION_FAILED: task {context.task_id} path "
                f"{path!r}: journaled content_sha256={str(rec.get('content_sha256'))[:16]}... "
                f"differs from the requested content hash {new_sha[:16]}... — a "
                f"different effect for the same logical operation is not "
                f"reconcilable; refusing to re-perform it"
            )
        f = self._side_effect_file(self.artifacts_base_dir, sandbox_id, path)
        if not f.exists():
            raise SideEffectReconciliationError(
                f"SIDE_EFFECT_RECONCILIATION_FAILED: journaled side effect of task "
                f"{context.task_id} at {str(f)} is missing from disk — refusing to "
                f"re-perform the write; manual reconciliation required"
            )
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() != rec.get("content_sha256"):
            raise SideEffectReconciliationError(
                f"SIDE_EFFECT_RECONCILIATION_FAILED: content of {str(f)} diverged "
                f"from the journaled sha256 — refusing to re-perform the write"
            )
        st = f.stat()
        if st.st_mtime_ns != rec.get("mtime_ns", rec.get("observed_mtime_ns")) or st.st_ino != rec.get("inode", rec.get("observed_ino")):
            raise SideEffectReconciliationError(
                f"SIDE_EFFECT_RECONCILIATION_FAILED: {str(f)} was rewritten or "
                f"touched after the journaled operation (mtime_ns/inode differ "
                f"from the journal) — refusing to re-perform the write"
            )
        return rec

    def _artifact_from_journal(self, rec: dict, path: str) -> Artifact:
        """Reconstruct the ORIGINAL artifact identity — no new id, no rewrite."""
        artifact_id = rec.get("artifact_id") or rec.get("original_artifact_id")
        return Artifact(
            artifact_id=artifact_id,
            name=Path(path).name,
            path=path,
            sha256=rec["content_sha256"],
            size_bytes=rec.get("size_bytes", 0),
            created_by=rec.get("sandbox_id", ""),
            created_at=datetime.fromisoformat(rec["recorded_at_utc"])
            if rec.get("recorded_at_utc") else datetime.now(timezone.utc),
            mission_id=rec.get("mission_id", ""),
            content_type="application/octet-stream",
        )

    def _journal_performance(
        self,
        context: ExecutionContext,
        sandbox_id: str,
        path: str,
        artifact: Artifact,
        performed_via: str = "direct",
        intent_record: Optional[dict] = None,
    ) -> None:
        """Durably record a performed side effect (fsynced append).

        performed_via:
          * "direct"             — this process performed the physical write;
          * "adopted_after_crash" — the physical write happened in a PRIOR
            process life that died between the effect and this record; this
            process verified the file against the durable intent and adopted
            it WITHOUT rewriting (E10-CW1-R1 pre-performed window closure)."""
        if not context.mission_id or not context.task_id:
            return
        f = self._side_effect_file(self.artifacts_base_dir, sandbox_id, path)
        st = f.stat()  # the sandbox adapter just wrote / we just observed this file
        record = {
            "record_type": "performed",
            "op": "artifact_write",
            "journal_record_id": uuid.uuid4().hex[:12],
            "mission_id": context.mission_id,
            "task_id": context.task_id,
            "run_id": context.run_id,
            "attempt_id": context.attempt_id,  # informational only — never identity
            "path": path,
            "sandbox_id": sandbox_id,
            "content_sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "artifact_id": artifact.artifact_id,
            "mtime_ns": st.st_mtime_ns,
            "inode": st.st_ino,
            "performed_via": performed_via,
            "performed_by_pid": (
                intent_record.get("process_pid") if performed_via == "adopted_after_crash" and intent_record
                else os.getpid()
            ),
            "intent_journal_record_id": (
                intent_record.get("journal_record_id") if intent_record else None
            ),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "process_pid": os.getpid(),
        }
        self.side_effect_journal.append(context.mission_id, record)

    def _journal_reconciliation(
        self,
        context: ExecutionContext,
        sandbox_id: str,
        prior: dict,
    ) -> None:
        """Durably record that a resume reconciled with the prior effect."""
        f = self._side_effect_file(self.artifacts_base_dir, sandbox_id, prior["path"])
        st = f.stat()
        record = {
            "record_type": "reconciled",
            "op": "artifact_write",
            "journal_record_id": uuid.uuid4().hex[:12],
            "mission_id": context.mission_id,
            "task_id": context.task_id,
            "path": prior["path"],
            "sandbox_id": sandbox_id,
            # Uniform schema with "performed" records: the artifact id IS the
            # original identity (aliases kept for readability/verifier).
            "artifact_id": prior.get("artifact_id") or prior.get("original_artifact_id"),
            "original_artifact_id": prior.get("artifact_id") or prior.get("original_artifact_id"),
            "content_sha256": prior["content_sha256"],
            "size_bytes": prior.get("size_bytes", 0),
            # The observed stat is stored under the SAME field names the
            # reconciliation guard checks (mtime_ns/inode) — a later process
            # life (or a repeat crash) must be able to reconcile again against
            # this record exactly as against a "performed" one.
            "mtime_ns": st.st_mtime_ns,
            "inode": st.st_ino,
            "observed_mtime_ns": st.st_mtime_ns,
            "observed_ino": st.st_ino,
            "no_physical_rewrite": (
                st.st_mtime_ns == prior.get("mtime_ns", prior.get("observed_mtime_ns"))
                and st.st_ino == prior.get("inode", prior.get("observed_ino"))
            ),
            "reconciled_at_utc": datetime.now(timezone.utc).isoformat(),
            "process_pid": os.getpid(),
        }
        self.side_effect_journal.append(context.mission_id, record)

    def _emit_artifact_reconciled(
        self,
        context: ExecutionContext,
        artifact: Artifact,
        mode: str,
        prior: dict,
    ) -> None:
        """E10-CW1-R1 §6: emit ARTIFACT_RECONCILED — semantically DISTINCT
        from ARTIFACT_CREATED. It never claims a new artifact came into
        existence: it claims an EXISTING side effect (created in a prior
        process life) was validated and adopted WITHOUT a physical rewrite.

        mode: "performed_record" (reconciled against a durable performed/
        reconciled record — CW1 window) | "intent_adoption" (adopted after
        verifying the file against a durable intent record — the pre-performed
        window closed by R1). Multiple ARTIFACT_RECONCILED events for the same
        artifact are legitimate (each is a real distinct reconciliation by a
        distinct process life); ARTIFACT_CREATED stays exactly once per
        artifact identity."""
        f = self._side_effect_file(self.artifacts_base_dir, artifact.created_by, artifact.path)
        try:
            st = f.stat()
            if mode == "intent_adoption":
                # The adoption branch is reached ONLY when this process has
                # NOT written the file: it verified the existing bytes against
                # the durable intent and adopted them. no_physical_rewrite is
                # true BY CONSTRUCTION of this path; the cross-life stat
                # continuity (crash marker vs now) is proven externally by the
                # verifier's three-way mtime/inode comparison — an intent
                # record (pre-effect) cannot carry file stats to compare.
                no_rewrite = True
            else:
                no_rewrite = bool(
                    st.st_mtime_ns == prior.get("mtime_ns", prior.get("observed_mtime_ns"))
                    and st.st_ino == prior.get("inode", prior.get("observed_ino"))
                )
            mtime_ns, ino = st.st_mtime_ns, st.st_ino
        except OSError:
            no_rewrite, mtime_ns, ino = False, 0, 0
        self._emit(FactoryEvent.create(
            event_type=EventType.ARTIFACT_RECONCILED,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=ArtifactReconciledEvent(
                artifact_id=artifact.artifact_id,
                name=artifact.name,
                path=artifact.path,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                created_by=artifact.created_by,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
                mode=mode,
                no_physical_rewrite=bool(no_rewrite),
                observed_mtime_ns=int(mtime_ns),
                observed_inode=int(ino),
                original_artifact_id=prior.get("artifact_id") or artifact.artifact_id,
            ),
            source="execution_engine",
            correlation_id=context.task_id,
        ))

    def _emit_artifact_created(self, context: ExecutionContext, artifact: Artifact):
        """Emit artifact created event and create evidence.

        E10-CW1 layered idempotency: each record below is materialized
        exactly once per logical artifact — whether the artifact was created
        in this process life or reconciled from the side-effect journal after
        a crash in the (side effect -> completion record) window. Re-execution
        of an interrupted task never duplicates them.

        E10-CW1-R1 §6: ARTIFACT_CREATED is emitted EXACTLY ONCE per artifact
        identity across ALL emitting sites (tool layer AND agent layer — the
        agent-layer re-emission is a logical duplicate of the tool-layer
        creation event and is suppressed by the shared guard).
        """
        # Emit artifact created — only if not already in event history
        # (variant CW1-B: the event was durably persisted before the crash
        # and restored on resume; re-emitting would duplicate the log).
        if not self._artifact_created_emitted(artifact.artifact_id):
            self._emit(FactoryEvent.create(
                event_type=EventType.ARTIFACT_CREATED,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=ArtifactCreatedEvent(
                    artifact_id=artifact.artifact_id,
                    name=artifact.name,
                    path=artifact.path,
                    sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                    created_by=artifact.created_by,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=context.task_id,
                ),
                source="execution_engine",
                correlation_id=context.task_id,
            ))
        # Create evidence record — only if none exists yet for this source
        # artifact (idempotent at the evidence layer).
        if not any(
            ev.source_id == artifact.artifact_id
            for ev in self.evidence_store._evidence.values()
        ):
            # Read artifact content for evidence
            artifact_path = os.path.join(self.artifacts_base_dir, artifact.path) if not os.path.isabs(artifact.path) else artifact.path
            # Try sandbox-specific path
            if not os.path.exists(artifact_path):
                artifact_path = os.path.join(self.artifacts_base_dir, context.sandbox_id, artifact.path)
            if os.path.exists(artifact_path):
                with open(artifact_path, 'rb') as f:
                    content = f.read()
            else:
                content = b""
            evidence = create_evidence(
                evidence_hash=artifact.sha256,
                content_type="artifact",
                source_id=artifact.artifact_id,
                mission_id=context.mission_id,
                run_id=context.run_id,
                task_id=context.task_id,
            )
            self.evidence[evidence.evidence_id] = evidence
            self.evidence_store.store_evidence(evidence)
            # Emit evidence recorded
            self._emit(FactoryEvent.create(
                event_type=EventType.EVIDENCE_RECORDED,
                mission_id=context.mission_id,
                run_id=context.run_id,
                payload=EvidenceRecordedEvent(
                    evidence_id=evidence.evidence_id,
                    evidence_hash=evidence.evidence_hash,
                    content_type=evidence.content_type,
                    source_id=evidence.source_id,
                    mission_id=context.mission_id,
                    run_id=context.run_id,
                    task_id=context.task_id,
                ),
                source="execution_engine",
                correlation_id=context.task_id,
            ))
        # Artifact registration is idempotent by artifact_id — always in sync
        self.evidence_store.store_artifact(artifact)
    # --- Verification ---
    async def verify_task(
        self,
        context: ExecutionContext,
        task: AgentTask,
        attempt_id: str,
    ) -> VerificationReport:
        """Verify task against acceptance criteria."""
        # Prepare artifacts map from evidence store (which has all artifacts)
        artifacts = {}
        for art in self.evidence_store._artifacts.values():
            artifacts[art.artifact_id] = {
                "path": art.path,
                "sha256": art.sha256,
                "size": art.size_bytes,
            }
        print(f"  [VERIFY] Task {task.task_id}: {len(artifacts)} artifacts in evidence_store")
        for aid, meta in artifacts.items():
            print(f"    Artifact: {aid}, path={meta['path']}")
        # Convert acceptance criteria from strings to AcceptanceCriterion objects
        criteria = []
        for i, criterion_str in enumerate(task.acceptance_criteria if hasattr(task, 'acceptance_criteria') else []):
            print(f"  [VERIFY] Criterion {i}: {criterion_str}")
            if criterion_str.startswith("file_exists:"):
                path = criterion_str.split(":", 1)[1]
                criteria.append(AcceptanceCriterion(
                    id=f"crit_{i}",
                    type=CriterionType.FILE_EXISTS,
                    description=f"File {path} exists",
                    path=path,
                ))
            elif criterion_str.startswith("file_contains:"):
                parts = criterion_str.split(":", 2)
                path = parts[1]
                pattern = parts[2] if len(parts) > 2 else ""
                criteria.append(AcceptanceCriterion(
                    id=f"crit_{i}",
                    type=CriterionType.FILE_CONTAINS,
                    description=f"File {path} contains '{pattern}'",
                    path=path,
                    pattern=pattern,
                ))
            elif criterion_str.startswith("file_hash_matches:"):
                parts = criterion_str.split(":", 2)
                path = parts[1]
                expected_hash = parts[2] if len(parts) > 2 else ""
                criteria.append(AcceptanceCriterion(
                    id=f"crit_{i}",
                    type=CriterionType.FILE_HASH_MATCHES,
                    description=f"File {path} hash matches",
                    path=path,
                    expected_hash=expected_hash,
                ))
            else:
                # Unknown criterion type, skip
                pass
        # Run verification
        report = self.verifier.verify(
            task_id=context.task_id,
            attempt_id=attempt_id,
            criteria=criteria,
            artifacts=artifacts,
        )
        print(f"  [VERIFY] Report verdict: {report.verdict}")
        for check in report.checks:
            print(f"    Check {check.criterion_id}: {check.criterion_type.value} - passed={check.passed}, details={check.details}")
        # Store verification
        verification = create_verification(
            task_id=context.task_id,
            attempt_id=attempt_id,
            verdict=report.verdict,
            checks=[c.criterion_id for c in report.checks],
            missing=report.missing_evidence,
            confidence=report.confidence,
        )
        self.verifications[verification.verification_id] = verification
        # Emit verification complete
        self._emit(FactoryEvent.create(
            event_type=EventType.VERIFICATION_COMPLETE,
            mission_id=context.mission_id,
            run_id=context.run_id,
            payload=VerificationCompleteEvent(
                verification_id=verification.verification_id,
                task_id=context.task_id,
                attempt_id=attempt_id,
                verdict=report.verdict,
                checks_performed=[c.criterion_id for c in report.checks],
                missing_evidence=report.missing_evidence,
                confidence=report.confidence,
            ),
            source="verifier",
            correlation_id=context.task_id,
        ))
        return report
    # --- State Transitions ---
    def transition_state(
        self,
        mission_id: str,
        from_state: PlanState,
        to_state: PlanState,
        actor: str = "execution_engine",
        reason: str = "",
    ) -> bool:
        """Transition mission state."""
        try:
            validate_transition(
                from_state=from_state,
                to_state=to_state,
                actor=actor,
                reason=reason,
            )
            mission = self.missions.get(mission_id)
            if mission:
                old_state = mission.state
                mission.state = MissionState(to_state.value)
                mission.updated_at = datetime.now(timezone.utc)
                # Emit state changed
                self._emit(FactoryEvent.create(
                    event_type=EventType.MISSION_STATE_CHANGED,
                    mission_id=mission_id,
                    payload=MissionStateChangedEvent(
                        from_state=from_state.value,
                        to_state=to_state.value,
                        actor=actor,
                        reason=reason,
                    ),
                    source="execution_engine",
                ))
                return True
        except Exception:
            return False
        return False
    # --- Checkpoint/Resume ---
    def _get_checkpoint_dir(self, mission_id: str) -> Path:
        """Get checkpoint directory for mission."""
        base = Path(self.artifacts_base_dir) / "checkpoints" / mission_id
        base.mkdir(parents=True, exist_ok=True)
        return base
    def _get_event_log_dir(self, mission_id: str) -> Path:
        """Get event log directory for mission."""
        base = Path(self.artifacts_base_dir) / "events" / mission_id
        base.mkdir(parents=True, exist_ok=True)
        return base
    def _save_events_to_disk(self, mission_id: str) -> Path:
        """Save event history to filesystem for durability."""
        event_dir = self._get_event_log_dir(mission_id)
        event_file = event_dir / "event_log.jsonl"
        # Serialize events to JSONL
        events_data = []
        for event in self.event_bus.history:
            if event.mission_id == mission_id:
                # Serialize payload with datetime handling
                def serialize_payload(obj):
                    if hasattr(obj, 'model_dump'):
                        return obj.model_dump(mode='json')
                    elif isinstance(obj, dict):
                        return {k: serialize_payload(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [serialize_payload(v) for v in obj]
                    elif isinstance(obj, datetime):
                        return obj.isoformat()
                    else:
                        return obj
                
                payload = event.payload
                if hasattr(payload, 'model_dump'):
                    payload = payload.model_dump(mode='json')
                elif isinstance(payload, dict):
                    payload = serialize_payload(payload)
                else:
                    payload = str(payload)
                
                events_data.append({
                    "event_type": event.event_type.value,
                    "mission_id": event.mission_id,
                    "run_id": event.run_id,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                    "payload": payload,
                    "source": event.source,
                    "correlation_id": event.correlation_id,
                    "causation_id": event.causation_id,
                })
        # Write atomically
        temp_file = event_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            for e in events_data:
                f.write(json.dumps(e) + '\n')
        temp_file.replace(event_file)
        return event_file
    def _load_events_from_disk(self, mission_id: str) -> List[Dict[str, Any]]:
        """Load event history from filesystem."""
        event_file = self._get_event_log_dir(mission_id) / "event_log.jsonl"
        if not event_file.exists():
            return []
        events = []
        with open(event_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
    def _save_checkpoint_to_disk(self, checkpoint: Checkpoint) -> Path:
        """Save checkpoint to filesystem for durability."""
        checkpoint_dir = self._get_checkpoint_dir(checkpoint.mission_id)
        checkpoint_file = checkpoint_dir / f"{checkpoint.checkpoint_id}.json"
        # Serialize checkpoint to JSON
        data = checkpoint.model_dump(mode='json')
        
        # Ensure all datetime objects are converted to ISO strings (handles nested dicts in Any fields)
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: convert_datetime(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_datetime(v) for v in obj]
            return obj
        
        data = convert_datetime(data)
        
        # Write atomically
        temp_file = checkpoint_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2)
        temp_file.replace(checkpoint_file)
        return checkpoint_file
    def _load_checkpoint_from_disk(self, mission_id: str, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load checkpoint from filesystem.

        E10-CI-04: a checkpoint read from durable storage is parse-checked and
        integrity-verified BEFORE it is handed to any execution path. A missing
        file still returns None; a corrupt or tampered file RAISES (fail closed).
        """
        checkpoint_file = self._get_checkpoint_dir(mission_id) / f"{checkpoint_id}.json"
        if not checkpoint_file.exists():
            return None
        try:
            with open(checkpoint_file, 'r') as f:
                data = json.load(f)
            checkpoint = Checkpoint.model_validate(data)
        except Exception as e:
            raise CheckpointParseError(
                f"Checkpoint {checkpoint_id} (mission {mission_id}) failed to parse "
                f"from {checkpoint_file}: {type(e).__name__}: {e}"
            ) from e
        if not checkpoint.verify():
            raise CheckpointIntegrityError(
                f"Checkpoint {checkpoint_id} (mission {mission_id}) integrity "
                f"verification FAILED: stored_hash={checkpoint.hash!r} "
                f"recomputed_hash={checkpoint.compute_integrity_hash()!r}"
            )
        return checkpoint
    def create_checkpoint(
        self,
        mission_id: str,
        run_id: str,
        step: int,
        state: PlanState,
        task_states: Dict[str, TaskState],
        artifact_ids: List[str],
        evidence_hashes: List[str],
        task_definitions: Optional[Dict[str, Dict[str, Any]]] = None,
        task_dependencies: Optional[Dict[str, List[str]]] = None,
        task_dependents: Optional[Dict[str, List[str]]] = None,
        attempt_history: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        agent_assignments: Optional[Dict[str, str]] = None,
    ) -> Checkpoint:
        """Create execution checkpoint and persist to disk."""
        # Auto-capture task graph structure if not provided
        if task_dependencies is None or task_dependents is None or task_definitions is None or agent_assignments is None:
            graph = self.task_graph.get(run_id, {})
            if task_definitions is None:
                task_definitions = {}
                for task_id, node in graph.items():
                    task_definitions[task_id] = {
                        "name": node.get("name", ""),
                        "description": node.get("description", ""),
                        "agent_type": node.get("agent_type").value if hasattr(node.get("agent_type"), 'value') else str(node.get("agent_type", "")),
                        "acceptance_criteria": node.get("acceptance_criteria", []),
                        "max_retries": node.get("max_retries", 2),
                        "retry_count": node.get("retry_count", 0),
                    }
            if task_dependencies is None:
                task_dependencies = {}
                for task_id, node in graph.items():
                    task_dependencies[task_id] = list(node.get("depends_on", []))
            if task_dependents is None:
                task_dependents = {}
                for task_id, node in graph.items():
                    task_dependents[task_id] = list(node.get("dependents", []))
            if agent_assignments is None:
                agent_assignments = {}
                for task_id, node in graph.items():
                    agent_assignments[task_id] = node.get("agent_id", "")
        # Capture human gate state from mission metadata for durability (E34)
        mission = self.missions.get(mission_id)
        human_gate = mission.metadata.get("human_gate") if mission else None
        human_decision = mission.metadata.get("human_decision") if mission else None
        
        checkpoint = Checkpoint(
            checkpoint_id=new_checkpoint_id(),
            mission_id=mission_id,
            run_id=run_id,
            step=step,
            state=state,
            task_states=task_states,
            artifact_ids=artifact_ids,
            evidence_hashes=evidence_hashes,
            task_definitions=task_definitions or {},
            task_dependencies=task_dependencies or {},
            task_dependents=task_dependents or {},
            attempt_history=attempt_history or {},
            agent_assignments=agent_assignments or {},
            human_gate=human_gate,
            human_decision=human_decision,
        )
        # E10-CI-02: compute the real integrity hash over the canonical
        # serialized payload BEFORE persisting, so the durable record is
        # self-verifiable after process death.
        checkpoint.hash = checkpoint.compute_integrity_hash()
        self.checkpoints[checkpoint.checkpoint_id] = checkpoint
        # Persist to disk for durability
        try:
            self._save_checkpoint_to_disk(checkpoint)
        except Exception as e:
            print(f"DEBUG: _save_checkpoint_to_disk exception: {e}")
            raise
        # Persist events to disk for durability
        try:
            self._save_events_to_disk(mission_id)
        except Exception as e:
            print(f"DEBUG: _save_events_to_disk exception: {e}")
            raise
        # Persist evidence store (artifacts & evidence) to disk for durability
        try:
            self.evidence_store.save_to_disk(mission_id)
        except Exception as e:
            print(f"DEBUG: evidence_store.save_to_disk exception: {e}")
            raise
        # Emit checkpoint created
        self._emit(FactoryEvent.create(
            event_type=EventType.CHECKPOINT_CREATED,
            mission_id=mission_id,
            run_id=run_id,
            payload=CheckpointCreatedEvent(
                checkpoint_id=checkpoint.checkpoint_id,
                mission_id=mission_id,
                run_id=run_id,
                step=step,
                state=state.value,
                task_count=len(task_states),
                artifact_count=len(artifact_ids),
                hash=checkpoint.hash,
            ),
            source="execution_engine",
        ))
        return checkpoint
    def resume_from_checkpoint(
        self,
        checkpoint_id: str,
        mission_id: Optional[str] = None,
    ) -> Optional[Run]:
        """Resume execution from checkpoint (loads from disk if not in memory)."""
        # Try memory first
        checkpoint = self.checkpoints.get(checkpoint_id)
        # If not in memory, try disk (for process termination survival)
        if not checkpoint and mission_id:
            checkpoint = self._load_checkpoint_from_disk(mission_id, checkpoint_id)
        if not checkpoint:
            return None
        # E10-CI-04: no execution may start before successful integrity
        # verification — applies to BOTH the in-memory and the disk-loaded path
        # (an unhashed/legacy checkpoint cannot be verified, therefore FAILS).
        if not checkpoint.verify():
            raise CheckpointIntegrityError(
                f"Checkpoint {checkpoint_id} integrity verification FAILED on resume: "
                f"stored_hash={checkpoint.hash!r} "
                f"recomputed_hash={checkpoint.compute_integrity_hash()!r}"
            )
        # Restore to memory if loaded from disk
        if checkpoint_id not in self.checkpoints:
            self.checkpoints[checkpoint_id] = checkpoint
        # E10 section 22: critical restoration path — fail closed. Any error in
        # event/evidence restoration is a corrupt restore, never best-effort.
        try:
            self._restore_events_from_disk(checkpoint.mission_id)
        except Exception as e:
            raise ResumeFailedError(
                f"RESUME_FAILED: event history restoration failed for mission "
                f"{checkpoint.mission_id}: {type(e).__name__}: {e}"
            ) from e
        try:
            self.evidence_store.load_from_disk(checkpoint.mission_id)
        except Exception as e:
            raise ResumeFailedError(
                f"RESUME_FAILED: evidence store restoration failed for mission "
                f"{checkpoint.mission_id}: {type(e).__name__}: {e}"
            ) from e
        # CRITICAL: Auto-recreate Mission object if not in memory
        # This enables true cross-runtime resume without manual intervention
        if checkpoint.mission_id not in self.missions:
            # Use engine's create_mission to properly register, then fix the ID
            mission = self.create_mission(f"Resumed: {checkpoint.mission_id}")
            # Remove the auto-generated mission and replace with checkpoint's mission_id
            del self.missions[mission.mission_id]
            mission.mission_id = checkpoint.mission_id
            self.missions[checkpoint.mission_id] = mission
            self._current_mission = mission
        # Resume execution implies mission should be in EXECUTING state
        # This enables replan/human_gate to work after cross-runtime resume
        mission = self.missions[checkpoint.mission_id]
        
        # Restore human gate state from checkpoint for durability (E34)
        if checkpoint.human_gate:
            mission.metadata["human_gate"] = checkpoint.human_gate
        if checkpoint.human_decision:
            mission.metadata["human_decision"] = checkpoint.human_decision
        
        # Restore mission state from checkpoint
        # If there was a human gate, restore to HUMAN_REQUIRED; otherwise use checkpoint state
        target_state = checkpoint.state
        if checkpoint.human_gate and not checkpoint.human_decision:
            # Human gate was active but no decision made - restore to HUMAN_REQUIRED
            target_state = MissionState.HUMAN_REQUIRED
        elif target_state == MissionState.PAUSED:
            # E2-R2 §6 (E33 cross-runtime regression, layer 2): resuming FROM
            # a pause means continuing execution. A checkpoint taken while the
            # mission was paused records state=PAUSED, but the resume operation
            # itself moves the mission back to EXECUTING — the state machine's
            # PAUSED->EXECUTING edge exists exactly for this, and the documented
            # resume contract ("resume execution implies EXECUTING — this
            # enables replan to work after cross-runtime resume") predates the
            # E34 state-restoration change. Restoring INTO PAUSED left resumed
            # missions unable to replan (replan_task_graph is EXECUTING-gated),
            # which broke cross-runtime replan flows like E33 phase 2.
            target_state = MissionState.EXECUTING
        
        if mission.state != target_state:
            from unified.contracts import validate_mission_transition
            try:
                # If target is HUMAN_REQUIRED, we need to transition through EXECUTING first
                if target_state == MissionState.HUMAN_REQUIRED:
                    # First ensure we're in EXECUTING
                    if mission.state != MissionState.EXECUTING:
                        required_path = [
                            MissionState.ANALYZING,
                            MissionState.PLANNING,
                            MissionState.DESIGNING,
                            MissionState.REVIEWING,
                            MissionState.APPROVED,
                            MissionState.AWAITING_APPROVAL,
                            MissionState.EXECUTING,
                        ]
                        for state in required_path:
                            if mission.state != state:
                                validate_mission_transition(mission.state, state)
                                mission.state = state
                    # Then transition to HUMAN_REQUIRED
                    validate_mission_transition(MissionState.EXECUTING, MissionState.HUMAN_REQUIRED)
                    mission.state = MissionState.HUMAN_REQUIRED
                else:
                    # Normal path to target state
                    if mission.state != MissionState.EXECUTING:
                        required_path = [
                            MissionState.ANALYZING,
                            MissionState.PLANNING,
                            MissionState.DESIGNING,
                            MissionState.REVIEWING,
                            MissionState.APPROVED,
                            MissionState.AWAITING_APPROVAL,
                            MissionState.EXECUTING,
                        ]
                        for state in required_path:
                            if mission.state != state:
                                validate_mission_transition(mission.state, state)
                                mission.state = state
                    if target_state != MissionState.EXECUTING:
                        validate_mission_transition(mission.state, target_state)
                        mission.state = target_state
            except Exception as e:
                # E10 section 22: state restoration is part of the critical
                # restore path. Resuming with a wrong mission state would
                # corrupt the mission lifecycle — fail closed with reason.
                raise ResumeFailedError(
                    f"RESUME_FAILED: mission state restoration failed for "
                    f"{checkpoint.mission_id}: cannot reach "
                    f"{target_state.value} from {mission.state.value}: "
                    f"{type(e).__name__}: {e}"
                ) from e
        # Create new run as child of original
        new_run = self.create_run(
            mission_id=checkpoint.mission_id,
            parent_run_id=checkpoint.run_id,
        )
        # Reconstruct the task graph from checkpoint (E10 section 22: fail closed)
        try:
            self._reconstruct_task_graph_from_checkpoint(new_run.run_id, checkpoint)
        except Exception as e:
            raise ResumeFailedError(
                f"RESUME_FAILED: task graph reconstruction failed for checkpoint "
                f"{checkpoint_id}: {type(e).__name__}: {e}"
            ) from e
        # Emit checkpoint loaded
        self._emit(FactoryEvent.create(
            event_type=EventType.CHECKPOINT_LOADED,
            mission_id=checkpoint.mission_id,
            run_id=new_run.run_id,
            payload={"checkpoint_id": checkpoint_id, "resumed_run": new_run.run_id},
            source="execution_engine",
        ))
        return new_run
    def _restore_events_from_disk(self, mission_id: str) -> None:
        """Restore event history from disk for cross-runtime resume."""
        events_data = self._load_events_from_disk(mission_id)
        for event_data in events_data:
            # Reconstruct FactoryEvent from saved data
            # Note: We don't emit these again, just restore to event bus history
            factory_event = FactoryEvent(
                event_type=EventType(event_data["event_type"]),
                mission_id=event_data["mission_id"],
                run_id=event_data["run_id"],
                timestamp=datetime.fromisoformat(event_data["timestamp"]) if event_data["timestamp"] else datetime.now(timezone.utc),
                payload=event_data["payload"],
                source=event_data["source"],
                correlation_id=event_data["correlation_id"],
                causation_id=event_data["causation_id"],
            )
            # Only add if not already in history (avoid duplicates)
            # Use event_type + mission_id + run_id + correlation_id + timestamp as dedup key
            dedup_key = (
                factory_event.event_type,
                factory_event.mission_id,
                factory_event.run_id,
                factory_event.correlation_id,
                factory_event.timestamp,
            )
            if not any(
                (e.event_type, e.mission_id, e.run_id, e.correlation_id, e.timestamp) == dedup_key
                for e in self.event_bus.history
            ):
                self.event_bus.history.append(factory_event)
    def _reconstruct_task_graph_from_checkpoint(
        self,
        run_id: str,
        checkpoint: Checkpoint,
    ) -> None:
        """Reconstruct the full task graph from checkpoint for cross-runtime resume."""
        # Initialize task graph for this run
        self.task_graph[run_id] = {}
        # Restore attempt history (E10 section 19: durable attempt ledger —
        # restored into BOTH the internal _attempts map and the public
        # engine.attempts ledger so post-resume checkpoints keep the full
        # pre-crash attempt history).
        if checkpoint.attempt_history:
            if not hasattr(self, '_attempts'):
                self._attempts = {}
            for task_id, attempts in checkpoint.attempt_history.items():
                for attempt_data in attempts:
                    # Reconstruct Attempt objects
                    # Use task_id from outer loop (checkpoint key) since attempt_data may not have it
                    attempt = Attempt(
                        attempt_id=attempt_data["attempt_id"],
                        task_id=task_id,  # Use outer loop key
                        agent_id=attempt_data.get("agent_id", ""),
                        state=TaskState(attempt_data["state"]),
                        success=attempt_data.get("success", False),
                        error=attempt_data.get("error", ""),
                        started_at=datetime.fromisoformat(attempt_data["started_at"]) if isinstance(attempt_data.get("started_at"), str) else attempt_data.get("started_at"),
                        completed_at=datetime.fromisoformat(attempt_data["completed_at"]) if isinstance(attempt_data.get("completed_at"), str) else attempt_data.get("completed_at"),
                    )
                    self._attempts[attempt.attempt_id] = attempt
                    self.attempts[attempt.attempt_id] = attempt
        # Reconstruct each task
        for task_id, state in checkpoint.task_states.items():
            # Get task definition from checkpoint
            task_def = checkpoint.task_definitions.get(task_id, {})
            # Create task node in graph
            self.task_graph[run_id][task_id] = {
                "state": state,
                "name": task_def.get("name", ""),
                "description": task_def.get("description", ""),
                "agent_type": AgentType(task_def.get("agent_type", "implementer")) if task_def.get("agent_type") else AgentType.IMPLEMENTER,
                "depends_on": set(checkpoint.task_dependencies.get(task_id, [])),
                "dependents": set(checkpoint.task_dependents.get(task_id, [])),
                "acceptance_criteria": task_def.get("acceptance_criteria", []),
                "max_retries": task_def.get("max_retries", 2),
                "retry_count": task_def.get("retry_count", 0),
                "mission_id": checkpoint.mission_id,
                "run_id": run_id,
                "agent_id": checkpoint.agent_assignments.get(task_id, ""),
                "artifact_ids": [],
                "evidence_hashes": [],
            }
            # Also create Task object
            task = Task(
                task_id=task_id,
                mission_id=checkpoint.mission_id,
                run_id=run_id,
                name=task_def.get("name", ""),
                description=task_def.get("description", ""),
                agent_type=AgentType(task_def.get("agent_type", "implementer")) if task_def.get("agent_type") else AgentType.IMPLEMENTER,
                state=state,
                depends_on=checkpoint.task_dependencies.get(task_id, []),
                acceptance_criteria=task_def.get("acceptance_criteria", []),
                max_retries=task_def.get("max_retries", 2),
                context=task_def.get("context", {}),
            )
            task.retry_count = task_def.get("retry_count", 0)
            self.tasks[task_id] = task
            # Only add to runnable cache if task is not in terminal state
            # Terminal states: COMPLETED, FAILED, CANCELLED
            if state not in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                if run_id not in self.task_runnable_cache:
                    self.task_runnable_cache[run_id] = set()
                self.task_runnable_cache[run_id].add(task_id)
            # Emit state transition event for restored task
            self._emit(FactoryEvent.create(
                event_type=EventType.STATE_TRANSITION,
                mission_id=checkpoint.mission_id,
                run_id=run_id,
                payload={
                    "entity_type": "task",
                    "entity_id": task_id,
                    "from_state": "UNKNOWN",
                    "to_state": state.value if hasattr(state, 'value') else str(state),
                    "trigger": "checkpoint_resume",
                },
                source="execution_engine",
                correlation_id=task_id,
            ))
        # After reconstructing all tasks, unblock dependents for completed tasks
        for task_id, state in checkpoint.task_states.items():
            if state == TaskState.COMPLETED:
                self._check_and_unblock_dependents(run_id, task_id)
        # Restore artifact IDs and evidence hashes if available
        # These would be populated when artifacts/evidence are loaded
        # For now, we track them as empty lists
    def restore_task_graph_from_checkpoint(
        self,
        run_id: str,
        checkpoint: Checkpoint,
    ) -> None:
        """Restore task graph state from checkpoint (for same-runtime resume)."""
        if run_id not in self.task_graph:
            # Need to recreate the task graph from the original run
            # For now, we assume the task graph exists or is rebuilt
            return
        graph = self.task_graph[run_id]
        # Restore task states from checkpoint
        for task_id, state in checkpoint.task_states.items():
            if task_id in graph:
                old_state = graph[task_id]["state"]
                if old_state != state:
                    graph[task_id]["state"] = state
                    # Update retry count if needed
                    if state == TaskState.READY and old_state in (TaskState.FAILED, TaskState.BLOCKED):
                        graph[task_id]["retry_count"] = 0
                    # Also update the Task object
                    if task_id in self.tasks:
                        self.tasks[task_id].state = state
                    # Emit state transition event
                    self._emit(FactoryEvent.create(
                        event_type=EventType.STATE_TRANSITION,
                        mission_id=checkpoint.mission_id,
                        run_id=run_id,
                        payload={
                            "entity_type": "task",
                            "entity_id": task_id,
                            "from_state": old_state.value if hasattr(old_state, 'value') else str(old_state),
                            "to_state": state.value if hasattr(state, 'value') else str(state),
                            "trigger": "checkpoint_resume",
                        },
                        source="execution_engine",
                        correlation_id=task_id,
                    ))
    # --- Task Graph Execution ---
    # --- Event Emission ---
    def _emit(self, event: FactoryEvent | Any) -> None:
        """Emit event to bus. Accepts either FactoryEvent or payload event."""
        if isinstance(event, FactoryEvent):
            factory_event = event
        else:
            # Map payload event class names to EventType
            event_type_map = {
                'MissionStartedEvent': EventType.MISSION_STARTED,
                'MissionCompletedEvent': EventType.MISSION_COMPLETED,
                'RunStartedEvent': EventType.RUN_STARTED,
                'RunCompletedEvent': EventType.RUN_COMPLETED,
                'AgentStartedEvent': EventType.AGENT_STARTED,
                'AgentCompletedEvent': EventType.AGENT_COMPLETED,
                'AgentFailedEvent': EventType.AGENT_FAILED,
                'AgentSelectedEvent': EventType.AGENT_SELECTED,
                'TaskFailedEvent': EventType.TASK_FAILED,
                'TaskCompletedEvent': EventType.TASK_COMPLETED,
                'ToolStartedEvent': EventType.TOOL_STARTED,
                'ToolCompletedEvent': EventType.TOOL_COMPLETED,
                'ToolFailedEvent': EventType.TOOL_FAILED,
                'ArtifactCreatedEvent': EventType.ARTIFACT_CREATED,
                'VerificationCompleteEvent': EventType.VERIFICATION_COMPLETE,
                'MissionStateChangedEvent': EventType.MISSION_STATE_CHANGED,
                'StateTransitionEvent': EventType.STATE_TRANSITION,
                'CheckpointCreatedEvent': EventType.CHECKPOINT_CREATED,
                'CheckpointLoadedEvent': EventType.CHECKPOINT_LOADED,
            }
            event_class_name = event.__class__.__name__
            event_type = event_type_map.get(event_class_name)
            if event_type is None:
                # Fallback: try to convert from class name
                event_type = EventType(event_class_name.replace('Event', '').upper())
            factory_event = FactoryEvent.create(
                event_type=event_type,
                mission_id=getattr(event, 'mission_id', ''),
                run_id=getattr(event, 'run_id', ''),
                payload=event,
                source='execution_engine',
                correlation_id=getattr(event, 'task_id', getattr(event, 'run_id', '')),
            )
        self.event_bus.emit(factory_event)
    def subscribe_events(self, callback: Callable[[FactoryEvent], None]) -> None:
        """Subscribe to events."""
        self.event_bus.subscribe(callback)
    def get_event_history(self, mission_id: Optional[str] = None) -> List[FactoryEvent]:
        """Get event history."""
        if mission_id:
            return [e for e in self.event_bus.history if e.mission_id == mission_id]
        return self.event_bus.history
    # --- Status ---
    def get_mission_status(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Get mission status summary."""
        mission = self.missions.get(mission_id)
        if not mission:
            return None
        run = self.runs.get(mission.current_run_id) if mission.current_run_id else None
        return {
            "mission_id": mission.mission_id,
            "state": mission.state.value,
            "user_request": mission.user_request,
            "run_id": run.run_id if run else None,
            "run_number": run.run_number if run else None,
            "tasks": len([t for t in self.tasks.values() if t.mission_id == mission_id]),
            "artifacts": len([a for a in self.artifacts.values() if a.created_by in
                             [s for s in self.runs.keys()]]),
            "events": len(self.get_event_history(mission_id)),
        }
    def complete_mission(self, mission_id: str, success: bool) -> None:
        """Mark mission as complete and release quota."""
        # Idempotent decrement - never go below 0
        self._active_mission_count = max(0, self._active_mission_count - 1)
        # Clean up run artifact counts
        mission = self.missions.get(mission_id)
        if mission and mission.current_run_id:
            self._run_artifact_counts.pop(mission.current_run_id, None)
        # Decrement task counters for this mission's runs
        if mission:
            for run_id in mission.run_ids:
                # Count tasks in this run
                run_tasks = [t for t in self.tasks.values() if t.run_id == run_id]
                for _ in run_tasks:
                    self._active_task_count = max(0, self._active_task_count - 1)
    # ============================================================
    # E11: HUMAN MISSION CONTROL
    # ============================================================
    def cancel_mission(self, mission_id: str, actor: str = "human", reason: str = "User requested cancellation") -> bool:
        """
        Request mission cancellation.
        Transitions: RUNNING -> CANCEL_REQUESTED -> CANCELLED
        Or from HUMAN_REQUIRED -> CANCELLED directly
        Idempotent: multiple calls safe.
        Args:
            mission_id: Mission to cancel
            actor: Who requested cancellation (human, system, timeout)
            reason: Cancellation reason
        Returns:
            True if cancellation was processed, False if already terminal
        """
        mission = self.missions.get(mission_id)
        if not mission:
            return False
        # Check if already in terminal state
        if mission.state.is_terminal:
            return False
        run = self._current_run if self._current_run and self._current_run.mission_id == mission_id else None
        run_id = run.run_id if run else None
        from unified.contracts import validate_mission_transition
        # Special handling for HUMAN_REQUIRED -> CANCELLED (direct transition)
        if mission.state == MissionState.HUMAN_REQUIRED:
            try:
                validate_mission_transition(MissionState.HUMAN_REQUIRED, MissionState.CANCELLED)
                from_state = mission.state
                mission.state = MissionState.CANCELLED
                # Clear gate
                mission.metadata.pop("human_gate", None)
                # Emit cancelled event
                self._emit(FactoryEvent.create(
                    EventType.MISSION_CANCELLED,
                    mission_id,
                    MissionCancelledEvent(
                        mission_id=mission_id,
                        run_id=run_id or "",
                        cancelled_at_state=from_state.value,
                        tasks_affected=len([t for t in self.tasks.values() if t.mission_id == mission_id]),
                    ),
                    run_id=run_id,
                ))
                # Emit state transition event
                self._emit(FactoryEvent.create(
                    EventType.MISSION_STATE_CHANGED,
                    mission_id,
                    MissionStateChangedEvent(
                        mission_id=mission_id,
                        run_id=run_id or "",
                        from_state=from_state.value,
                        to_state=MissionState.CANCELLED.value,
                        actor=actor,
                        reason=reason,
                    ),
                    run_id=run_id,
                ))
                # Release resources
                self.complete_mission(mission_id, False)
                return True
            except Exception:
                return False
        # Standard path: transition to CANCEL_REQUESTED then CANCELLED
        try:
            validate_mission_transition(mission.state, MissionState.CANCEL_REQUESTED)
            from_state = mission.state
            mission.state = MissionState.CANCEL_REQUESTED
            # Emit cancel requested event
            self._emit(FactoryEvent.create(
                EventType.MISSION_CANCEL_REQUESTED,
                mission_id,
                MissionCancelRequestedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Emit state transition event
            self._emit(FactoryEvent.create(
                EventType.MISSION_STATE_CHANGED,
                mission_id,
                MissionStateChangedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    from_state=from_state.value,
                    to_state=MissionState.CANCEL_REQUESTED.value,
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Now transition to CANCELLED (terminal)
            validate_mission_transition(MissionState.CANCEL_REQUESTED, MissionState.CANCELLED)
            mission.state = MissionState.CANCELLED
            # Emit cancelled event
            self._emit(FactoryEvent.create(
                EventType.MISSION_CANCELLED,
                mission_id,
                MissionCancelledEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    cancelled_at_state=from_state.value,
                    tasks_affected=len([t for t in self.tasks.values() if t.mission_id == mission_id]),
                ),
                run_id=run_id,
            ))
            # Emit state transition event
            self._emit(FactoryEvent.create(
                EventType.MISSION_STATE_CHANGED,
                mission_id,
                MissionStateChangedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    from_state=MissionState.CANCEL_REQUESTED.value,
                    to_state=MissionState.CANCELLED.value,
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Release resources
            self.complete_mission(mission_id, False)
            return True
        except Exception as e:
            # If transition fails, mission stays in current state
            return False
    def pause_mission(self, mission_id: str, actor: str = "human", reason: str = "User requested pause") -> bool:
        """
        Request mission pause at safe checkpoint.
        Transitions: EXECUTING -> PAUSED
        Requires execution to reach a checkpoint first.
        Args:
            mission_id: Mission to pause
            actor: Who requested pause
            reason: Pause reason
        Returns:
            True if pause was initiated, False if not in executable state
        """
        mission = self.missions.get(mission_id)
        if not mission:
            return False
        if mission.state != MissionState.EXECUTING:
            return False  # Can only pause executing missions
        run = self._current_run if self._current_run and self._current_run.mission_id == mission_id else None
        run_id = run.run_id if run else None
        # Emit pause requested event
        self._emit(FactoryEvent.create(
            EventType.MISSION_PAUSE_REQUESTED,
            mission_id,
            MissionPauseRequestedEvent(
                mission_id=mission_id,
                run_id=run_id or "",
                actor=actor,
                reason=reason,
            ),
            run_id=run_id,
        ))
        # Set pause flag - actual pause happens at next checkpoint in execute_task_graph
        mission.metadata["pause_requested"] = True
        mission.metadata["pause_actor"] = actor
        mission.metadata["pause_reason"] = reason
        return True
    def resume_mission(self, mission_id: str, actor: str = "human", reason: str = "User requested resume") -> bool:
        """
        Resume a paused mission.
        Transitions: PAUSED -> EXECUTING
        Args:
            mission_id: Mission to resume
            actor: Who requested resume
            reason: Resume reason
        Returns:
            True if resume was processed, False if not paused
        """
        mission = self.missions.get(mission_id)
        if not mission:
            return False
        if mission.state != MissionState.PAUSED:
            return False  # Can only resume paused missions
        run = self._current_run if self._current_run and self._current_run.mission_id == mission_id else None
        run_id = run.run_id if run else None
        from_state = mission.state
        # Transition to EXECUTING
        try:
            from unified.contracts import validate_mission_transition
            validate_mission_transition(MissionState.PAUSED, MissionState.EXECUTING)
            mission.state = MissionState.EXECUTING
            # Clear pause flag
            mission.metadata.pop("pause_requested", None)
            mission.metadata.pop("pause_actor", None)
            mission.metadata.pop("pause_reason", None)
            # Emit resume requested event
            self._emit(FactoryEvent.create(
                EventType.MISSION_RESUME_REQUESTED,
                mission_id,
                MissionResumeRequestedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Emit state transition event
            self._emit(FactoryEvent.create(
                EventType.MISSION_STATE_CHANGED,
                mission_id,
                MissionStateChangedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    from_state=from_state.value,
                    to_state=MissionState.EXECUTING.value,
                    actor=actor,
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Emit resumed event
            self._emit(FactoryEvent.create(
                EventType.MISSION_RESUMED,
                mission_id,
                MissionResumedEvent(
                    mission_id=mission_id,
                    run_id=run_id or "",
                    resumed_from_state=from_state.value,
                ),
                run_id=run_id,
            ))
            return True
        except Exception:
            return False
    def create_human_gate(
        self,
        mission_id: str,
        run_id: str,
        task_id: Optional[str],
        reason: str,
        context: Dict[str, Any],
        options: List[Dict[str, str]],
        impact: str,
        required_action: str,
        evidence_refs: Optional[List[str]] = None,
        requested_by: str = "system",
    ) -> Optional[str]:
        """
        Create a human gate requiring decision.
        Transitions: EXECUTING -> HUMAN_REQUIRED
        Args:
            mission_id: Mission ID
            run_id: Run ID
            task_id: Optional task ID that requires human decision
            reason: Why human decision is needed
            context: Additional context for decision
            options: Decision options (e.g., [{"value": "approve", "label": "Approve"}, {"value": "reject", "label": "Reject"}, {"value": "request_changes", "label": "Request Changes"}])
            impact: Impact description of the decision
            required_action: What action is required
            evidence_refs: Optional list of evidence IDs for the human to review
            requested_by: Who requested the human gate
        Returns:
            gate_id if created, None if mission not in executable state
        """
        mission = self.missions.get(mission_id)
        if not mission or mission.state != MissionState.EXECUTING:
            return None
        from unified.contracts import new_decision_id
        gate_id = new_decision_id()
        # Transition to HUMAN_REQUIRED
        try:
            from unified.contracts import validate_mission_transition
            validate_mission_transition(MissionState.EXECUTING, MissionState.HUMAN_REQUIRED)
            from_state = mission.state
            mission.state = MissionState.HUMAN_REQUIRED
            # Store gate info in mission metadata
            gate_info = {
                "gate_id": gate_id,
                "task_id": task_id,
                "reason": reason,
                "context": context,
                "options": options,
                "impact": impact,
                "required_action": required_action,
                "evidence_refs": evidence_refs or [],
                "requested_by": requested_by,
                "current_state": mission.state.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            mission.metadata["human_gate"] = gate_info
            # Emit human gate created event
            self._emit(FactoryEvent.create(
                EventType.HUMAN_GATE_CREATED,
                mission_id,
                HumanGateCreatedEvent(
                    gate_id=gate_id,
                    mission_id=mission_id,
                    run_id=run_id,
                    task_id=task_id or "",
                    reason=reason,
                    context=context,
                    options=options,
                    impact=impact,
                    required_action=required_action,
                ),
                run_id=run_id,
            ))
            # Emit state transition event
            self._emit(FactoryEvent.create(
                EventType.MISSION_STATE_CHANGED,
                mission_id,
                MissionStateChangedEvent(
                    mission_id=mission_id,
                    run_id=run_id,
                    from_state=from_state.value,
                    to_state=MissionState.HUMAN_REQUIRED.value,
                    actor="system",
                    reason=reason,
                ),
                run_id=run_id,
            ))
            # Create checkpoint with human gate state for durability (E34)
            # Capture current task graph state
            graph = self.task_graph.get(run_id, {})
            task_states = {tid: node["state"] for tid, node in graph.items()}
            # E10 section 6: actual content hashes, mission-scoped (not evidence IDs)
            artifact_ids = [
                aid for aid, art in getattr(self.evidence_store, '_artifacts', {}).items()
                if getattr(art, 'mission_id', '') == mission_id
            ]
            evidence_hashes = [
                ev.evidence_hash for ev in getattr(self.evidence_store, '_evidence', {}).values()
                if getattr(ev, 'mission_id', '') == mission_id
            ]
            self.create_checkpoint(
                mission_id=mission_id,
                run_id=run_id,
                step=len(task_states),
                state=MissionState.HUMAN_REQUIRED,
                task_states=task_states,
                artifact_ids=artifact_ids,
                evidence_hashes=evidence_hashes,
            )
            return gate_id
        except Exception as e:
            return None
    def decide_human_gate(
        self,
        mission_id: str,
        gate_id: str,
        decision: str,  # "approve", "reject", "request_changes"
        actor: str,
        feedback: str = "",
    ) -> bool:
        """
        Record human decision for a gate.
        Transitions: HUMAN_REQUIRED -> EXECUTING (approve) or CANCELLED (reject) or stays HUMAN_REQUIRED (request_changes)
        Args:
            mission_id: Mission ID
            gate_id: Gate ID
            decision: "approve" | "reject" | "request_changes"
            actor: Who made the decision
            feedback: Optional feedback
        Returns:
            True if decision was processed
        """
        mission = self.missions.get(mission_id)
        if not mission or mission.state != MissionState.HUMAN_REQUIRED:
            return False
        # Check mission-level gate
        gate_info = mission.metadata.get("human_gate", {})
        if gate_info.get("gate_id") == gate_id:
            pass  # Found mission-level gate
        else:
            # Check action-level gates
            found = False
            for key, value in mission.metadata.items():
                if key.startswith("action_gate_") and value == gate_id:
                    found = True
                    break
            if not found:
                return False
        # Check for duplicate decision - THIS SPECIFIC GATE may have at most one accepted terminal decision
        # Check the gate-specific decision record
        gate_decision_key = None
        for key, value in mission.metadata.items():
            if key.startswith("action_gate_") and value == gate_id:
                gate_decision_key = f"{key}_decision"
                break
        if gate_decision_key:
            existing_decision = mission.metadata.get(gate_decision_key)
        else:
            # Mission-level gate
            existing_decision = mission.metadata.get("human_decision")
        if existing_decision:
            # Duplicate decision attempt - reject
            self._emit(FactoryEvent.create(
                EventType.HUMAN_DECISION_REJECTED,
                mission_id,
                HumanDecisionRejectedEvent(
                    gate_id=gate_id,
                    mission_id=mission_id,
                    run_id=self._current_run.run_id if self._current_run and self._current_run.mission_id == mission_id else "",
                    attempted_decision=decision,
                    actor=actor,
                    feedback=feedback,
                    reason="Duplicate decision - gate already decided",
                    existing_decision=existing_decision.get("decision"),
                    existing_actor=existing_decision.get("actor"),
                    existing_decided_at=existing_decision.get("decided_at"),
                ),
                run_id=self._current_run.run_id if self._current_run and self._current_run.mission_id == mission_id else None,
            ))
            return False
        run_id = self._current_run.run_id if self._current_run and self._current_run.mission_id == mission_id else None
        try:
            decision_record = {
                "gate_id": gate_id,
                "decision": decision,
                "actor": actor,
                "feedback": feedback,
                "decided_at": datetime.now(timezone.utc).isoformat(),
            }
            mission.metadata["human_decision"] = decision_record
            
            if decision == "approve":
                from unified.contracts import validate_mission_transition
                validate_mission_transition(MissionState.HUMAN_REQUIRED, MissionState.EXECUTING)
                from_state = mission.state
                mission.state = MissionState.EXECUTING
                # Clear mission-level gate, keep decision record
                mission.metadata.pop("human_gate", None)
                # Mark action-level gates for this gate_id as approved (don't delete - keep for future checks)
                for key in list(mission.metadata.keys()):
                    if key.startswith("action_gate_") and isinstance(mission.metadata[key], str):
                        # Check if this gate corresponds to the approved gate_id
                        if mission.metadata[key] == gate_id:
                            # Mark as approved - keep the decision record
                            mission.metadata[f"{key}_decision"] = {
                                "decision": "approve",
                                "actor": actor,
                                "feedback": feedback,
                                "decided_at": datetime.now(timezone.utc).isoformat(),
                            }
                            # E10-RP2.2-R2A1 §2.2.1/§2.2.2 (arbitration F1) —
                            # the APPROVAL mints the one-shot ENGINE-ISSUED
                            # resume ticket for this exact operation, bound
                            # to this gate and to the creating attempt/agent
                            # lineage. The approval is consumable ONLY by
                            # the continuation the engine later designates
                            # (§2.3 case 1: approval creates a valid ticket
                            # for the pending operation). Legacy records
                            # without a v2 operation identity mint nothing
                            # and therefore still authorize nothing.
                            op_record = mission.metadata.get(f"{key}_operation")
                            if isinstance(op_record, dict) and op_record.get("format") == "v2":
                                self._mint_resume_ticket(key, op_record, gate_id, actor)
                # Emit decision recorded
                self._emit(FactoryEvent.create(
                    EventType.HUMAN_DECISION_RECORDED,
                    mission_id,
                    HumanDecisionRecordedEvent(
                        gate_id=gate_id,
                        mission_id=mission_id,
                        run_id=run_id or "",
                        decision="approve",
                        actor=actor,
                        feedback=feedback,
                    ),
                    run_id=run_id,
                ))
                # Emit state transition
                self._emit(FactoryEvent.create(
                    EventType.MISSION_STATE_CHANGED,
                    mission_id,
                    MissionStateChangedEvent(
                        mission_id=mission_id,
                        run_id=run_id or "",
                        from_state=from_state.value,
                        to_state=MissionState.EXECUTING.value,
                        actor=actor,
                        reason=f"Human decision: {decision}",
                    ),
                    run_id=run_id,
                ))
                # Update checkpoint with human decision for durability
                self._update_checkpoint_human_decision(mission_id, gate_id, decision_record)
                return True
            elif decision == "reject":
                # E10-RP2.2-R2A §2.2 — record the REJECTION on the
                # action-gate records for this gate_id too (parallel to the
                # approve branch): the gate check must see a terminal
                # 'reject' decision for the operation identity, so a
                # rejected operation can never silently fall back to
                # 'pending' and be re-requested as if undecided.
                for key in list(mission.metadata.keys()):
                    if key.startswith("action_gate_") and isinstance(mission.metadata[key], str):
                        if mission.metadata[key] == gate_id:
                            mission.metadata[f"{key}_decision"] = {
                                "decision": "reject",
                                "actor": actor,
                                "feedback": feedback,
                                "decided_at": datetime.now(timezone.utc).isoformat(),
                            }
                # Transition to CANCELLED
                return self.cancel_mission(mission_id, actor, f"Human decision: {feedback}")
            elif decision == "request_changes":
                # Stay in HUMAN_REQUIRED, gate remains for re-review
                # Emit decision recorded
                self._emit(FactoryEvent.create(
                    EventType.HUMAN_DECISION_RECORDED,
                    mission_id,
                    HumanDecisionRecordedEvent(
                        gate_id=gate_id,
                        mission_id=mission_id,
                        run_id=run_id or "",
                        decision="request_changes",
                        actor=actor,
                        feedback=feedback,
                    ),
                    run_id=run_id,
                ))
                # Update checkpoint with human decision for durability
                self._update_checkpoint_human_decision(mission_id, gate_id, decision_record)
                return True
            return False
        except Exception:
            return False
    
    def _update_checkpoint_human_decision(self, mission_id: str, gate_id: str, decision_record: Dict[str, Any]) -> None:
        """Update the latest checkpoint with human decision for durability."""
        # Find the latest checkpoint for this mission
        latest_checkpoint = None
        for cp in self.checkpoints.values():
            if cp.mission_id == mission_id:
                if latest_checkpoint is None or cp.created_at > latest_checkpoint.created_at:
                    latest_checkpoint = cp
        if latest_checkpoint:
            latest_checkpoint.human_decision = decision_record
            self._save_checkpoint_to_disk(latest_checkpoint)
    # ============================================================
    # REPLANNING
    # ============================================================
    def replan_task_graph(
        self,
        run_id: str,
        new_tasks: Optional[List[Dict[str, Any]]] = None,
        modified_tasks: Optional[Dict[str, Dict[str, Any]]] = None,
        removed_task_ids: Optional[List[str]] = None,
        new_dependencies: Optional[Dict[str, List[str]]] = None,
        reason: str = "Dynamic replanning",
        actor: str = "system",
    ) -> bool:
        """
        Dynamically modify the task graph during execution.
        
        Args:
            run_id: Run ID containing the task graph
            new_tasks: List of new task configs to add
            modified_tasks: Dict of task_id -> modifications (name, description, agent_type, etc.)
            removed_task_ids: List of task IDs to remove (must be PENDING or BLOCKED)
            new_dependencies: Dict of task_id -> new depends_on list
            reason: Reason for replanning
            actor: Who initiated the replan
            
        Returns:
            True if replan was applied successfully
        """
        if run_id not in self.task_graph:
            return False
        graph = self.task_graph[run_id]
        if not graph:
            return False
        # Find mission_id
        mission_id = None
        for node in graph.values():
            if node.get("mission_id"):
                mission_id = node["mission_id"]
                break
        if not mission_id:
            return False
        mission = self.missions.get(mission_id)
        if not mission or mission.state != MissionState.EXECUTING:
            return False  # Can only replan during execution
        # Emit replan requested
        graph_version = getattr(self, '_graph_version', 0)
        self._graph_version = graph_version + 1
        proposed_changes = []
        if new_tasks:
            proposed_changes.extend([{"action": "add", "task": t} for t in new_tasks])
        if modified_tasks:
            proposed_changes.extend([{"action": "modify", "task_id": k, "changes": v} for k, v in modified_tasks.items()])
        if removed_task_ids:
            proposed_changes.extend([{"action": "remove", "task_id": tid} for tid in removed_task_ids])
        if new_dependencies:
            proposed_changes.extend([{"action": "change_dependencies", "task_id": k, "depends_on": v} for k, v in new_dependencies.items()])
        self._emit(FactoryEvent.create(
            event_type=EventType.REPLAN_REQUESTED,
            mission_id=mission_id,
            run_id=run_id,
            payload=ReplanRequestedEvent(
                run_id=run_id,
                failed_task_id="",  # Not a failure-based replan
                reason=reason,
                proposed_changes=proposed_changes,
                actor=actor,
                graph_version_before=graph_version,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            source="execution_engine",
        ))
        # Remove tasks (only if not started)
        if removed_task_ids:
            for task_id in removed_task_ids:
                if task_id in graph:
                    task_state = graph[task_id]["state"]
                    if task_state in (TaskState.PENDING, TaskState.BLOCKED, TaskState.READY):
                        # Remove from graph
                        deps = graph[task_id].get("depends_on", set())
                        for dep_id in deps:
                            if dep_id in graph:
                                graph[dep_id]["dependents"].discard(task_id)
                        dependents = graph[task_id].get("dependents", set())
                        for dep_id in dependents:
                            if dep_id in graph:
                                graph[dep_id]["depends_on"].discard(task_id)
                        del graph[task_id]
                        # Also remove from tasks dict
                        self.tasks.pop(task_id, None)
        # Modify existing tasks
        if modified_tasks:
            for task_id, modifications in modified_tasks.items():
                if task_id in graph:
                    task = self.tasks.get(task_id)
                    if task:
                        for key, value in modifications.items():
                            if hasattr(task, key):
                                setattr(task, key, value)
                            if key in graph[task_id]:
                                graph[task_id][key] = value
        # Add new tasks
        if new_tasks:
            # Initialize runnable cache for run_id if needed
            if run_id not in self.task_runnable_cache:
                self.task_runnable_cache[run_id] = set()
            for task_config in new_tasks:
                task = self.create_task(
                    run_id=run_id,
                    mission_id=mission_id,
                    name=task_config["name"],
                    description=task_config.get("description", ""),
                    agent_type=task_config.get("agent_type", AgentType.IMPLEMENTER),
                    depends_on=task_config.get("depends_on", []),
                    acceptance_criteria=task_config.get("acceptance_criteria", []),
                )
                if task_config.get("context"):
                    task.context = task_config["context"]
                # Add to graph
                task_id = task.task_id
                graph[task_id] = {
                    "depends_on": set(task.depends_on),
                    "dependents": set(),
                    "state": TaskState.PENDING,
                    "mission_id": mission_id,
                    "name": task.name,
                    "description": task.description,
                    "agent_type": task.agent_type,
                    "acceptance_criteria": task.acceptance_criteria,
                    "max_retries": task.max_retries if hasattr(task, 'max_retries') else 2,
                    "retry_count": 0,
                }
                # Add reverse dependencies
                for dep_id in task.depends_on:
                    if dep_id in graph:
                        graph[dep_id]["dependents"].add(task_id)
                # Store task in engine
                self.tasks[task_id] = task
                # Determine initial state based on dependencies (like add_task_to_graph)
                if not task.depends_on:
                    # No dependencies - ready to run
                    graph[task_id]["state"] = TaskState.READY
                    task.state = TaskState.READY
                    self.task_runnable_cache[run_id].add(task_id)
                    # Emit event
                    self._emit(FactoryEvent.create(
                        event_type=EventType.TASK_CREATED,
                        mission_id=mission_id,
                        run_id=run_id,
                        payload=TaskCreatedEvent(
                            task_id=task_id,
                            mission_id=mission_id,
                            run_id=run_id,
                            name=task.name,
                            agent_type=task.agent_type,
                            acceptance_criteria=[],
                            depends_on=list(task.depends_on),
                            context={},
                        ),
                        source="execution_engine",
                        correlation_id=task_id,
                    ))
                else:
                    # Has dependencies - check if all are completed
                    all_completed = True
                    for dep_id in task.depends_on:
                        dep_node = graph.get(dep_id)
                        if not dep_node or dep_node["state"] != TaskState.COMPLETED:
                            all_completed = False
                            break
                    if all_completed:
                        graph[task_id]["state"] = TaskState.READY
                        task.state = TaskState.READY
                        self.task_runnable_cache[run_id].add(task_id)
                        self._emit(FactoryEvent.create(
                            event_type=EventType.TASK_CREATED,
                            mission_id=mission_id,
                            run_id=run_id,
                            payload=TaskCreatedEvent(
                                task_id=task_id,
                                mission_id=mission_id,
                                run_id=run_id,
                                name=task.name,
                                agent_type=task.agent_type,
                                acceptance_criteria=[],
                                depends_on=list(task.depends_on),
                                context={},
                            ),
                            source="execution_engine",
                            correlation_id=task_id,
                        ))
                    else:
                        graph[task_id]["state"] = TaskState.BLOCKED
                        task.state = TaskState.BLOCKED
        # Update dependencies
        if new_dependencies:
            for task_id, depends_on in new_dependencies.items():
                if task_id in graph:
                    old_deps = graph[task_id]["depends_on"]
                    graph[task_id]["depends_on"] = set(depends_on)
                    # Update reverse dependencies
                    for dep_id in old_deps:
                        if dep_id in graph:
                            graph[dep_id]["dependents"].discard(task_id)
                    for dep_id in depends_on:
                        if dep_id in graph:
                            graph[dep_id]["dependents"].add(task_id)
                    # Update task object
                    task = self.tasks.get(task_id)
                    if task:
                        task.depends_on = list(depends_on)
        # Re-evaluate READY tasks
        for task_id, node in graph.items():
            if node["state"] == TaskState.BLOCKED:
                depends_on = node["depends_on"]
                if not depends_on or all(
                    graph.get(dep_id, {}).get("state") == TaskState.COMPLETED
                    for dep_id in depends_on
                ):
                    node["state"] = TaskState.READY
                    task = self.tasks.get(task_id)
                    if task:
                        task.state = TaskState.READY
                    # Add to runnable cache
                    if run_id not in self.task_runnable_cache:
                        self.task_runnable_cache[run_id] = set()
                    self.task_runnable_cache[run_id].add(task_id)
        # Emit replan applied
        graph_version = getattr(self, '_graph_version', 0)
        applied_changes = []
        if new_tasks:
            applied_changes.extend([{"action": "add", "task": t} for t in new_tasks])
        if modified_tasks:
            applied_changes.extend([{"action": "modify", "task_id": k, "changes": v} for k, v in modified_tasks.items()])
        if removed_task_ids:
            applied_changes.extend([{"action": "remove", "task_id": tid} for tid in removed_task_ids])
        if new_dependencies:
            applied_changes.extend([{"action": "change_dependencies", "task_id": k, "depends_on": v} for k, v in new_dependencies.items()])
        self._emit(FactoryEvent.create(
            event_type=EventType.REPLAN_APPLIED,
            mission_id=mission_id,
            run_id=run_id,
            payload=ReplanAppliedEvent(
                run_id=run_id,
                replan_id=new_checkpoint_id(),
                applied_changes=applied_changes,
                actor=actor,
                graph_version_before=graph_version - 1 if graph_version > 0 else 0,
                graph_version_after=graph_version,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            source="execution_engine",
        ))
        return True
# ============================================================
# FACTORY FUNCTION
# ============================================================
def create_execution_engine(
    sandbox_backend: SandboxBackend = SandboxBackend.WINDOWS_EXECUTOR,
    artifacts_base_dir: Optional[str] = None,
    default_limits: Optional[Dict[str, Any]] = None,
    grant_validator: Optional[Callable[[str, str], bool]] = None,
    # Resource quotas
    max_concurrent_missions: int = 10,
    max_concurrent_tasks: int = 50,
    max_retries: int = 3,
    max_artifacts_per_run: int = 100,
    grant_ids: Optional[List[str]] = None,
) -> ExecutionEngine:
    """Create execution engine with default configuration."""
    return ExecutionEngine(
        sandbox_backend=sandbox_backend,
        artifacts_base_dir=artifacts_base_dir,
        default_limits=default_limits,
        grant_validator=grant_validator,
        max_concurrent_missions=max_concurrent_missions,
        max_concurrent_tasks=max_concurrent_tasks,
        max_retries=max_retries,
        max_artifacts_per_run=max_artifacts_per_run,
        grant_ids=grant_ids,
    )
# ============================================================
# EXPORTS
# ============================================================
__all__ = [
    "ExecutionContext",
    "SimpleEventBus",
    "FileEvidenceStore",
    "ExecutionEngine",
    "create_execution_engine",
]
import os
import tempfile