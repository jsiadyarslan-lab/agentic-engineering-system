"""
State Machine — Unified Engineering Agents System

Implements the PlanState machine with 13 honest states + 2 sub-verdicts.
Enforces golden rule: VERIFIED only by actor="user".
Enforces Order 004: STOPPING → STOPPED for resume capability.

Based on EAS v2 core/state.py with unification of AgentFactory MissionState.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, FrozenSet, Set
from dataclasses import dataclass
from pydantic import BaseModel, Field


# ============================================================
# STATE DEFINITIONS
# ============================================================

class PlanState(str, Enum):
    """13 honest states for mission lifecycle."""

    # Initial
    RECEIVED = "RECEIVED"

    # Analysis & Planning
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    DESIGNING = "DESIGNING"

    # Review Cycle
    REVIEWING = "REVIEWING"
    APPROVED = "APPROVED"
    REVISE = "REVISE"

    # Human Gate
    AWAITING_APPROVAL = "AWAITING_APPROVAL"

    # Execution
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"

    # Verification
    VERIFYING = "VERIFYING"
    EVIDENCED = "EVIDENCED"
    ADJUDICATED = "ADJUDICATED"
    VERIFIED = "VERIFIED"

    # Terminal
    FAILED = "FAILED"
    ESCALATED_TO_HUMAN = "ESCALATED_TO_HUMAN"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ABORTED = "ABORTED"

    # E11: Human Mission Control states
    PAUSED = "PAUSED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class SubVerdict(str, Enum):
    """Sub-verdicts that drive transitions (NOT states)."""

    NOT_EVIDENCED = "NOT_EVIDENCED"  # Verifier: evidence insufficient → Arbiter
    STAGNANT = "STAGNANT"             # Arbiter: same conflict fingerprint → escalate


# ============================================================
# TRANSITION TABLE (Frozen - Immutable)
# ============================================================

# Terminal states - no transitions out
TERMINAL_STATES: FrozenSet[PlanState] = frozenset({
    PlanState.VERIFIED,
    PlanState.FAILED,
    PlanState.ESCALATED_TO_HUMAN,
    PlanState.STOPPED,
    PlanState.ABORTED,
    PlanState.CANCELLED,
})

# STOPPING target (Order 004: safe stop request)
_STOP_TARGET: FrozenSet[PlanState] = frozenset({PlanState.STOPPING})

# Allowed transitions: from_state → {allowed to_states}
TRANSITIONS: Dict[PlanState, FrozenSet[PlanState]] = {
    # Initial
    PlanState.RECEIVED: frozenset({
        PlanState.ANALYZING,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),

    # Analysis & Planning
    PlanState.ANALYZING: frozenset({
        PlanState.PLANNING,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),
    PlanState.PLANNING: frozenset({
        PlanState.DESIGNING,
        PlanState.REVIEWING,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),
    PlanState.DESIGNING: frozenset({
        PlanState.REVIEWING,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),

    # Review Cycle (max 3 rounds enforced by orchestrator)
    PlanState.REVIEWING: frozenset({
        PlanState.APPROVED,
        PlanState.REVISE,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),
    PlanState.APPROVED: frozenset({
        PlanState.AWAITING_APPROVAL,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),
    PlanState.REVISE: frozenset({
        PlanState.PLANNING,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),

    # Human Gate
    PlanState.AWAITING_APPROVAL: frozenset({
        PlanState.EXECUTING,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),

    # Execution
    PlanState.EXECUTING: frozenset({
        PlanState.EXECUTED,
        PlanState.FAILED,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
        PlanState.PAUSED,
        PlanState.HUMAN_REQUIRED,
    }),
    PlanState.EXECUTED: frozenset({
        PlanState.VERIFYING,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),

    # Verification
    PlanState.VERIFYING: frozenset({
        PlanState.EVIDENCED,
        PlanState.ADJUDICATED,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),
    PlanState.EVIDENCED: frozenset({
        PlanState.VERIFIED,
        PlanState.ADJUDICATED,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),
    PlanState.ADJUDICATED: frozenset({
        PlanState.EXECUTING,      # Arbiter: retry_with_constraints
        PlanState.ESCALATED_TO_HUMAN,
        PlanState.STOPPING,
        PlanState.CANCEL_REQUESTED,
    }),

    # E11: Human Mission Control states
    PlanState.PAUSED: frozenset({
        PlanState.EXECUTING,      # Resume
        PlanState.CANCEL_REQUESTED,
        PlanState.STOPPING,
    }),
    PlanState.CANCEL_REQUESTED: frozenset({
        PlanState.CANCELLED,
    }),
    PlanState.HUMAN_REQUIRED: frozenset({
        PlanState.EXECUTING,      # Human decision: continue
        PlanState.CANCELLED,      # Human decision: cancel
        PlanState.STOPPING,
    }),

    # Order 004: Safe stop pair
    PlanState.STOPPING: frozenset({PlanState.STOPPED}),

    # Terminal - no outgoing
    PlanState.VERIFIED: frozenset(),
    PlanState.FAILED: frozenset(),
    PlanState.ESCALATED_TO_HUMAN: frozenset(),
    PlanState.STOPPED: frozenset(),
    PlanState.ABORTED: frozenset(),
    PlanState.CANCELLED: frozenset(),
}


# ============================================================
# EXCEPTIONS
# ============================================================

class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        from_state: PlanState,
        to_state: PlanState,
        reason: str,
        actor: str = "system",
    ):
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        self.actor = actor
        super().__init__(
            f"State transition rejected: {from_state.value} → {to_state.value} — {reason}"
        )


# ============================================================
# VALIDATION FUNCTIONS
# ============================================================

def validate_transition(
    from_state: PlanState,
    to_state: PlanState,
    *,
    actor: str = "system",
    review_cycle_count: int = 0,
    max_review_cycles: int = 3,
    arbiter_call_count: int = 0,
    max_arbiter_calls: int = 3,
    execution_attempt: int = 1,
    max_execution_attempts: int = 2,
) -> None:
    """
    Validate a single state transition.

    Enforces:
    - Terminal states cannot be left
    - Golden rule: VERIFIED only by actor="user"
    - Order 004: STOPPING only by user/system, STOPPING→STOPPED only
    - Review cycle limits (max 3 → Arbiter)
    - Arbiter call limits (max 3 → escalate)
    - Execution attempt limits (max 2 → Arbiter)

    Args:
        from_state: Current state
        to_state: Desired next state
        actor: "user" | "arbiter" | "reviewer" | "implementer" | "verifier" | "system" | "orchestrator"
        review_cycle_count: Current review cycle number (for REVISE→PLANNING)
        max_review_cycles: Maximum review cycles before Arbiter
        arbiter_call_count: Number of times Arbiter has been called
        max_arbiter_calls: Maximum Arbiter calls before forced escalation
        execution_attempt: Current execution attempt number
        max_execution_attempts: Maximum attempts per task

    Raises:
        StateTransitionError: If transition is invalid
    """
    # Unknown states
    if from_state not in PlanState:
        raise StateTransitionError(from_state, to_state, "Unknown source state")
    if to_state not in PlanState:
        raise StateTransitionError(from_state, to_state, "Unknown target state")

    # Terminal states cannot be left
    if from_state in TERMINAL_STATES:
        raise StateTransitionError(
            from_state, to_state,
            f"Terminal state {from_state.value} cannot be left"
        )

    # Transition must exist in table
    allowed = TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise StateTransitionError(
            from_state, to_state,
            f"Transition not in allowed table"
        )

    # GOLDEN RULE: VERIFIED only by user
    if to_state is PlanState.VERIFIED and actor != "user":
        raise StateTransitionError(
            from_state, to_state,
            "Golden rule violation: VERIFIED only by actor='user'"
        )

    # Order 004: STOPPING request only by user or system (orchestrator)
    if to_state is PlanState.STOPPING and actor not in ("user", "system", "orchestrator"):
        raise StateTransitionError(
            from_state, to_state,
            "STOPPING request only by user or orchestrator (Order 004)"
        )

    # STOPPING can only go to STOPPED
    if from_state is PlanState.STOPPING and to_state is not PlanState.STOPPED:
        raise StateTransitionError(
            from_state, to_state,
            "STOPPING can only transition to STOPPED (Order 004)"
        )

    # REVISE → PLANNING: review cycle limit
    if from_state is PlanState.REVISE and to_state is PlanState.PLANNING:
        if review_cycle_count >= max_review_cycles:
            raise StateTransitionError(
                from_state, to_state,
                f"Review cycle limit exceeded ({review_cycle_count}/{max_review_cycles}) — Arbiter required"
            )

    # ADJUDICATED → EXECUTING: Arbiter decision only
    if from_state is PlanState.ADJUDICATED and to_state is PlanState.EXECUTING:
        if actor != "arbiter":
            raise StateTransitionError(
                from_state, to_state,
                "EXECUTING after ADJUDICATED only by Arbiter (retry_with_constraints)"
            )

    # VERIFYING → ADJUDICATED: NOT_EVIDENCED sub-verdict required
    if from_state is PlanState.VERIFYING and to_state is PlanState.ADJUDICATED:
        # This is checked by the verifier returning SubVerdict.NOT_EVIDENCED
        pass

    # EVIDENCED → ADJUDICATED: conflict requiring Arbiter
    if from_state is PlanState.EVIDENCED and to_state is PlanState.ADJUDICATED:
        # Arbiter called for conflict resolution
        if arbiter_call_count >= max_arbiter_calls:
            raise StateTransitionError(
                from_state, to_state,
                f"Arbiter call limit exceeded ({arbiter_call_count}/{max_arbiter_calls}) — forced escalation"
            )

    # EXECUTING → FAILED: execution attempt limit
    if from_state is PlanState.EXECUTING and to_state is PlanState.FAILED:
        if execution_attempt >= max_execution_attempts:
            raise StateTransitionError(
                from_state, to_state,
                f"Execution attempt limit exceeded ({execution_attempt}/{max_execution_attempts})"
            )


def allowed_targets(from_state: PlanState) -> FrozenSet[PlanState]:
    """Get allowed target states from a given state (for UI display)."""
    return TRANSITIONS.get(from_state, frozenset())


def is_terminal(state: PlanState) -> bool:
    """Check if state is terminal."""
    return state in TERMINAL_STATES


def is_sub_verdict(value: str) -> bool:
    """Check if string is a sub-verdict."""
    return value in {sv.value for sv in SubVerdict}


# ============================================================
# STATE MACHINE CLASS
# ============================================================

class MissionStateMachine:
    """
    Mission state machine with enforced transitions and audit trail.
    """

    def __init__(
        self,
        initial_state: PlanState = PlanState.RECEIVED,
        max_review_cycles: int = 3,
        max_arbiter_calls: int = 3,
        max_execution_attempts: int = 2,
    ):
        self.current_state = initial_state
        self.max_review_cycles = max_review_cycles
        self.max_arbiter_calls = max_arbiter_calls
        self.max_execution_attempts = max_execution_attempts

        # Counters
        self.review_cycle_count = 0
        self.arbiter_call_count = 0
        self.execution_attempt = 1

        # History
        self.history: List[Dict] = []

    def transition(
        self,
        to_state: PlanState,
        actor: str = "system",
        reason: str = "",
    ) -> PlanState:
        """
        Attempt state transition with validation.

        Returns:
            The new state if successful

        Raises:
            StateTransitionError: If transition is invalid
        """
        from_state = self.current_state

        validate_transition(
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            review_cycle_count=self.review_cycle_count,
            max_review_cycles=self.max_review_cycles,
            arbiter_call_count=self.arbiter_call_count,
            max_arbiter_calls=self.max_arbiter_calls,
            execution_attempt=self.execution_attempt,
            max_execution_attempts=self.max_execution_attempts,
        )

        # Update counters based on transition
        self._update_counters(from_state, to_state)

        # Record transition
        self.history.append({
            "from": from_state.value,
            "to": to_state.value,
            "actor": actor,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counters": {
                "review_cycles": self.review_cycle_count,
                "arbiter_calls": self.arbiter_call_count,
                "execution_attempt": self.execution_attempt,
            },
        })

        self.current_state = to_state
        return to_state

    def _update_counters(self, from_state: PlanState, to_state: PlanState) -> None:
        """Update internal counters based on transition."""
        # Review cycle: REVISE → PLANNING increments
        if from_state is PlanState.REVISE and to_state is PlanState.PLANNING:
            self.review_cycle_count += 1

        # Arbiter call: any transition to ADJUDICATED
        if to_state is PlanState.ADJUDICATED:
            self.arbiter_call_count += 1

        # Execution attempt: EXECUTING → EXECUTED/FAILED resets for next task
        # But FAILED after max attempts → new task starts at attempt 1
        if from_state is PlanState.EXECUTING and to_state in (PlanState.EXECUTED, PlanState.FAILED):
            # This is tracked per-task in the orchestrator
            pass

        # Reset execution attempt on new task (REVIEWING → APPROVED)
        if from_state is PlanState.REVIEWING and to_state is PlanState.APPROVED:
            self.execution_attempt = 1

    def can_transition(self, to_state: PlanState, actor: str = "system") -> bool:
        """Check if transition is allowed without raising."""
        try:
            validate_transition(
                from_state=self.current_state,
                to_state=to_state,
                actor=actor,
                review_cycle_count=self.review_cycle_count,
                max_review_cycles=self.max_review_cycles,
                arbiter_call_count=self.arbiter_call_count,
                max_arbiter_calls=self.max_arbiter_calls,
                execution_attempt=self.execution_attempt,
                max_execution_attempts=self.max_execution_attempts,
            )
            return True
        except StateTransitionError:
            return False

    def is_terminal(self) -> bool:
        """Check if current state is terminal."""
        return self.current_state in TERMINAL_STATES

    def get_audit_trail(self) -> List[Dict]:
        """Get full transition history."""
        return list(self.history)


# ============================================================
# TASK STATE MACHINE (Simpler)
# ============================================================

class TaskState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


TASK_TRANSITIONS: Dict[TaskState, FrozenSet[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.READY, TaskState.CANCELLED}),
    TaskState.READY: frozenset({TaskState.ASSIGNED, TaskState.CANCELLED}),
    TaskState.ASSIGNED: frozenset({TaskState.RUNNING, TaskState.BLOCKED, TaskState.CANCELLED}),
    TaskState.RUNNING: frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.BLOCKED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset({TaskState.READY}),  # Retry
    TaskState.BLOCKED: frozenset({TaskState.READY, TaskState.CANCELLED}),
    TaskState.CANCELLED: frozenset(),
}


TASK_TERMINAL: FrozenSet[TaskState] = frozenset({
    TaskState.COMPLETED,
    TaskState.CANCELLED,
})


def validate_task_transition(
    from_state: TaskState,
    to_state: TaskState,
) -> None:
    """Validate task state transition."""
    if from_state in TASK_TERMINAL and from_state != to_state:
        raise StateTransitionError(from_state, to_state, f"Terminal task state {from_state.value} cannot be left")

    allowed = TASK_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise StateTransitionError(from_state, to_state, "Invalid task transition")


# ============================================================
# PYDANTIC MODELS FOR SERIALIZATION
# ============================================================

class StateTransitionRecord(BaseModel):
    """Record of a single state transition."""
    from_state: str
    to_state: str
    actor: str
    reason: str
    timestamp: str
    counters: Dict[str, int]


class MissionStateSnapshot(BaseModel):
    """Serializable snapshot of mission state machine."""
    current_state: str
    review_cycle_count: int
    arbiter_call_count: int
    execution_attempt: int
    history: List[StateTransitionRecord]
    is_terminal: bool

    @classmethod
    def from_machine(cls, machine: MissionStateMachine) -> "MissionStateSnapshot":
        return cls(
            current_state=machine.current_state.value,
            review_cycle_count=machine.review_cycle_count,
            arbiter_call_count=machine.arbiter_call_count,
            execution_attempt=machine.execution_attempt,
            history=[
                StateTransitionRecord(**h) for h in machine.history
            ],
            is_terminal=machine.is_terminal(),
        )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "PlanState",
    "SubVerdict",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "StateTransitionError",
    "validate_transition",
    "allowed_targets",
    "is_terminal",
    "is_sub_verdict",
    "MissionStateMachine",
    "TaskState",
    "TASK_TRANSITIONS",
    "TASK_TERMINAL",
    "validate_task_transition",
    "StateTransitionRecord",
    "MissionStateSnapshot",
]