"""Capability identity, version, autonomy, and boundary posture.

This module is the single source of truth for WHO the Engineering
capability is (identity + version) and WHAT posture it holds (status,
autonomy, authorities, integration). Identity and version are defined
here explicitly and are never derived from JARVIS PRIME or from any
other repository or system.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

#: Stable identity of this capability. Never derived from JARVIS PRIME.
CAPABILITY_IDENTITY: str = "engineering"

#: Explicit capability contract version (independent of PRIME versioning).
#: 0.1.0 = E0 (contract foundation). 0.2.0 = E1 (controlled execution
#: foundation with the sandbox execution acceptance gate BLOCKED on
#: the missing external container substrate). 0.3.0 = E1 with the
#: local substrate integrated: the verified kernel-namespace sandbox
#: is implemented, proven, and open on adapter registration (see
#: E1_SANDBOX_GATE_STATUS). 0.4.0 = E2: the bounded autonomous
#: engineering loop (delegated objective, repair playbook, bounded
#: iterations, independent verification) is implemented on top of the
#: E1 production path. 0.5.0 = E3: the multi-step engineering mission
#: (delegated task graph with per-task scopes, bounded in-task
#: retries, failure propagation, and mission-level independent
#: verification) is implemented on top of the E2 machinery. 0.6.0 =
#: E4: high-impact operations — exactly ONE (``run_high_impact_commit``):
#: a real git commit executed by the real git binary inside the
#: verified sandbox under a signed, single-use, request-bound Owner
#: approval with a frozen policy, independent object-db verification,
#: and snapshot rollback; every other HIGH_IMPACT operation stays
#: forbidden and denied by default. 0.7.0 = G3 (owner execution order
#: v1, 2026-09-10): the E1 controlled write surface — exactly TWO
#: controlled write operations (``source_modification`` and
#: ``artifact_creation``) under task attribution (task_id REQUIRED for
#: them), hash preconditions, ephemeral-workspace confinement with
#: custody-only exit, and intent verification; the granted repository
#: is never mutated; ``workspace_file_creation`` and
#: ``configuration_changes`` remain unregistered. 0.8.0 = G4 (owner
#: execution order v1, 2026-09-10): the E2 ENGINEERING INTELLIGENCE
#: LOOP contract — the loop runs under the explicit G4 contract
#: (engineering.state machine with ONE audited transition table,
#: terminal-state categories, task attribution REQUIRED for
#: ``run_engineering_loop``, and the failure-chain bound
#: ``max_failure_chain``); the engineering flow itself is unchanged.
CAPABILITY_VERSION: str = "0.8.0"


class CapabilityStatus(str, Enum):
    """Lifecycle status of the Engineering capability itself."""

    #: E0: the contract foundation exists; execution does not.
    AVAILABLE_AS_CONTRACT_FOUNDATION = "AVAILABLE_AS_CONTRACT_FOUNDATION"
    #: E1: controlled execution is implemented: admission, grants,
    #: workspace, single-pass executor, evidence, verification records,
    #: and read-class operations. Execution-class (sandboxed) operations
    #: are implemented as contract + port and BLOCKED on the missing
    #: external container substrate (D-01 = A).
    AVAILABLE_CONTROLLED_EXECUTION = "AVAILABLE_CONTROLLED_EXECUTION"
    #: Declared but not built.
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    #: Explicitly out of bounds.
    CLOSED = "CLOSED"


#: Current capability status (E1).
CAPABILITY_STATUS: CapabilityStatus = (
    CapabilityStatus.AVAILABLE_CONTROLLED_EXECUTION
)

#: E1 sandbox execution acceptance gate. The verified LOCAL substrate
#: (kernel namespaces: user/mount/pid/uts/net, pivot_root, seccomp,
#: capability drop, rlimits — evidence LOCAL-D01-A-SUPPORTED, accepted
#: by the owner) is implemented as substrate.local_substrate and
#: proven by real sandbox executions. The gate OPENS when the caller
#: registers the adapter with the sandbox manager; with no adapter it
#: stays BLOCKED (fail-closed, no host fallback).
E1_SANDBOX_GATE_STATUS: str = "LOCAL_SUBSTRATE_IMPLEMENTED"


class AutonomyLevel(str, Enum):
    """Autonomy ladder for Engineering. E0 declares it; only E0 is open."""

    E0_PASSIVE_ANALYSIS = "E0_PASSIVE_ANALYSIS"
    E1_CONTROLLED_EXECUTION = "E1_CONTROLLED_EXECUTION"
    E2_AUTONOMOUS_ENGINEERING_LOOP = "E2_AUTONOMOUS_ENGINEERING_LOOP"
    E3_MULTI_STEP_ENGINEERING_MISSION = "E3_MULTI_STEP_ENGINEERING_MISSION"
    E4_HIGH_IMPACT_OPERATIONS = "E4_HIGH_IMPACT_OPERATIONS"


#: Autonomy posture. Fail-closed: E1 controlled execution is
#: implemented WITH the verified local substrate (real sandboxed
#: execution proven; D-01=A container-class isolation via kernel
#: namespaces); E2 bounded autonomous engineering loop is
#: IMPLEMENTED (delegated objectives only: the loop's scope, playbook,
#: and budgets are fixed by the delegator — no self-expansion, no
#: invented repairs); E3 multi-step engineering mission is
#: IMPLEMENTED (delegated task graphs only: the mission's scope,
#: stages, and budgets are fixed by the delegator — failure
#: propagation is honest, verification is independent of the tasks);
#: E4 high-impact operations is IMPLEMENTED with bounded authority:
#: exactly ONE operation (the approval-gated git commit) under a
#: signed Owner approval, a single-use request-bound lease, frozen
#: policy, sandboxed execution, independent verification, and
#: snapshot rollback — capability WITHOUT open authority; git_push,
#: release, deployment, production_modification, and
#: external_communication stay FORBIDDEN.
AUTONOMY_POSTURE: Mapping[AutonomyLevel, str] = {
    AutonomyLevel.E0_PASSIVE_ANALYSIS: "AVAILABLE_AS_CONTRACT_FOUNDATION",
    AutonomyLevel.E1_CONTROLLED_EXECUTION: "IMPLEMENTED",
    AutonomyLevel.E2_AUTONOMOUS_ENGINEERING_LOOP: "IMPLEMENTED",
    AutonomyLevel.E3_MULTI_STEP_ENGINEERING_MISSION: "IMPLEMENTED",
    AutonomyLevel.E4_HIGH_IMPACT_OPERATIONS: "IMPLEMENTED_APPROVAL_GATED",
}

#: The only autonomy level the E0 contract admits.
E0_ADMITTED_AUTONOMY: AutonomyLevel = AutonomyLevel.E0_PASSIVE_ANALYSIS

#: The autonomy level the E1 contract admits (implemented with the
#: verified local substrate; all operation classes live).
E1_ADMITTED_AUTONOMY: AutonomyLevel = AutonomyLevel.E1_CONTROLLED_EXECUTION

#: The autonomy level the E2 contract admits: a bounded autonomous
#: engineering loop over a DELEGATED objective (scope, playbook, and
#: budgets fixed by the delegator; the loop cannot widen them).
E2_ADMITTED_AUTONOMY: AutonomyLevel = AutonomyLevel.E2_AUTONOMOUS_ENGINEERING_LOOP

#: The autonomy level the E3 contract admits: a multi-step engineering
#: mission over a DELEGATED task graph (mission/task scopes, stages,
#: and budgets fixed by the delegator; the engine cannot widen them).
E3_ADMITTED_AUTONOMY: AutonomyLevel = (
    AutonomyLevel.E3_MULTI_STEP_ENGINEERING_MISSION
)

#: The autonomy level the E4 contract admits: high-impact operations
#: under EXPLICIT Owner authority (approval, lease, policy) — one
#: operation only (run_high_impact_commit); everything else stays
#: default-deny at both gates.
E4_ADMITTED_AUTONOMY: AutonomyLevel = (
    AutonomyLevel.E4_HIGH_IMPACT_OPERATIONS
)


#: Global authorities Engineering explicitly does NOT hold. They remain
#: with JARVIS PRIME (or their rightful owners) and may never be
#: claimed, granted, or assumed by Engineering.
NOT_HELD_AUTHORITIES: frozenset[str] = frozenset(
    {
        "global_sovereignty",
        "global_planning_authority",
        "global_mission_authority",
        "global_resource_allocation",
        "global_verification_authority",
    }
)

#: Authorities Engineering actually holds: none. Engineering is limited
#: to capability-local contract decisions.
HELD_AUTHORITIES: frozenset[str] = frozenset()


#: Integration posture with JARVIS PRIME (E0): the contract is defined
#: in docs/INTEGRATION.md; no adapter exists; no dependency exists.
INTEGRATION_CONTRACT_STATUS: str = "DEFINED"
INTEGRATION_ADAPTER_STATUS: str = "NOT_IMPLEMENTED"
PRIME_DEPENDENCY: str = "NONE"
