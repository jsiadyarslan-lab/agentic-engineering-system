"""E1 implementation registry — the truthful map of what is BUILT.

This module is the single source of truth for the E1 implementation
state:

- :data:`E1_OPERATIONS` — the operation registry: every E0-declared
  operation (plus the E1 domain operations) mapped to its real
  implementation, its permission class, and the domains it requires;
- :data:`E1_DOMAIN_IMPLEMENTATIONS` — per-domain implementation
  records used by the domain-state guard
  (:func:`contracts.domain.assert_no_domain_available`) to prove
  that every domain claiming an implemented state really has one.

G3 execution order v1 (2026-09-10, §4): every registered operation
now carries an explicit seven-field operation contract —
``operation_id`` (the stable capability ID), ``input_contract``,
``output_contract``, ``resource_boundary``, ``security_boundary``,
``evidence_expectation``, and ``verification_expectation`` — declared
once here and cross-checked by tests; an operation whose contract is
incomplete cannot remain registered. The same owner order registers
the two controlled write operations (``source_modification``,
``artifact_creation``) — the "separate authorization" that was
recorded as required before any write-class domain operation could
be admitted. ``workspace_file_creation`` and
``configuration_changes`` remain unregistered (still awaiting their
own separate authorization).

Truthfulness rules (checked by tests):

- a domain recorded as ``AVAILABLE`` must expose at least one
  registered operation;
- a domain recorded as ``IMPLEMENTED_EXECUTION_BLOCKED`` must expose
  at least one registered operation whose acceptance gate is blocked
  on a missing external dependency (no domain holds this state at
  0.3.0 — the enum member remains for truthful historical encoding);
- a domain recorded as ``DECLARED_NOT_IMPLEMENTED`` must have NO
  registered operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.contract import PermissionClass
from contracts.domain import (
    DomainImplementationState,
    EngineeringDomain,
    DOMAIN_IMPLEMENTATION_STATES,
)
from contracts.high_impact import parse_high_impact_payload
from contracts.mission import parse_mission_payload
from contracts.objective import parse_objective_payload
from contracts.operations import (
    documentation_reading,
    metadata_analysis,
    repository_inspection,
    source_reading,
)
from contracts.static_analysis import analyze_python_tree, build_import_graph
from contracts.testing_domain import build_sandbox_request, parse_junit_report
from contracts.write_operations import artifact_creation, source_modification


@dataclass(frozen=True)
class OperationSpec:
    """Registration record for one E1 operation.

    ``handler`` is the implementation callable. ``requires_domains``
    lists domains that must appear in the request scope (``None``
    means any declared domain is acceptable). ``blocked_gate`` is
    non-empty only when the operation's ACCEPTANCE (not its
    construction) is blocked on a missing external dependency.

    The G3 §4 contract fields are declared once per operation and
    cross-checked by tests: ``operation_id`` MUST equal the registry
    name (the stable capability ID), and the six contract strings
    MUST be non-empty for every registered operation — an operation
    without a complete, auditable contract cannot remain registered.
    """

    name: str
    permission_class: PermissionClass
    handler: object
    description: str
    requires_domains: frozenset[EngineeringDomain] | None = None
    blocked_gate: str = ""
    #: G3 §4 — stable capability ID (equals the registry name).
    operation_id: str = ""
    #: G3 §4 — the typed input shape and its validation rules.
    input_contract: str = ""
    #: G3 §4 — the typed output shape the operation produces.
    output_contract: str = ""
    #: G3 §4 — resource ceilings and grant coverage that apply.
    resource_boundary: str = ""
    #: G3 §4 — the enforced security boundary of the operation.
    security_boundary: str = ""
    #: G3 §4 — the evidence records the operation must produce.
    evidence_expectation: str = ""
    #: G3 §4 — the machine checks that must run against it.
    verification_expectation: str = ""


_READ_OPS: tuple[OperationSpec, ...] = (
    OperationSpec(
        name="repository_inspection",
        permission_class=PermissionClass.READ,
        handler=repository_inspection,
        description=(
            "file inventory with hashes, structure, and pure-Python git "
            "metadata (loose objects; fail-closed on unsupported layouts)"
        ),
        operation_id="repository_inspection",
        input_contract=(
            "params: target — one absolute directory path string under a "
            "granted root"
        ),
        output_contract=(
            "(payload mapping, accesses tuple) — inventory records plus "
            "per-file FileAccessEvidence (path, sha256, size, mode)"
        ),
        resource_boundary=(
            "D-13 ExecutionLimits output ceiling; reads capped by the path "
            "policy max_read_bytes"
        ),
        security_boundary=(
            "grant-root containment after symlink resolution; read-only; "
            "no process creation, no network"
        ),
        evidence_expectation=(
            "one access record per inventoried file plus environment "
            "identity records"
        ),
        verification_expectation=(
            "deterministic re-run hash sampling on the first access"
        ),
    ),
    OperationSpec(
        name="source_reading",
        permission_class=PermissionClass.READ,
        handler=source_reading,
        description="scoped reads of explicitly requested files under the path policy",
        operation_id="source_reading",
        input_contract=(
            "params: targets — non-empty list of absolute file paths under "
            "granted roots"
        ),
        output_contract=(
            "(payload mapping, accesses tuple) — file contents reference "
            "plus FileAccessEvidence per target"
        ),
        resource_boundary=(
            "D-13 output ceiling; per-read byte ceiling (max_read_bytes)"
        ),
        security_boundary=(
            "grant-root containment after symlink resolution; read-only; "
            "no process creation, no network"
        ),
        evidence_expectation="one access record per requested file",
        verification_expectation="deterministic re-run hash sampling",
    ),
    OperationSpec(
        name="metadata_analysis",
        permission_class=PermissionClass.READ,
        handler=metadata_analysis,
        description="sizes, line counts, and extension distribution of a granted root",
        operation_id="metadata_analysis",
        input_contract="params: target — one absolute directory path string",
        output_contract=(
            "(payload mapping, accesses tuple) — size/line/extension "
            "statistics plus FileAccessEvidence per file"
        ),
        resource_boundary="D-13 output ceiling; per-read byte ceiling",
        security_boundary=(
            "grant-root containment after symlink resolution; read-only; "
            "no process creation, no network"
        ),
        evidence_expectation="one access record per analyzed file",
        verification_expectation="deterministic re-run hash sampling",
    ),
    OperationSpec(
        name="documentation_reading",
        permission_class=PermissionClass.READ,
        handler=documentation_reading,
        description="enumeration and reading of documentation files",
        operation_id="documentation_reading",
        input_contract="params: target — one absolute directory path string",
        output_contract=(
            "(payload mapping, accesses tuple) — documentation file "
            "contents plus FileAccessEvidence per file"
        ),
        resource_boundary="D-13 output ceiling; per-read byte ceiling",
        security_boundary=(
            "grant-root containment after symlink resolution; read-only; "
            "no process creation, no network"
        ),
        evidence_expectation="one access record per documentation file",
        verification_expectation="deterministic re-run hash sampling",
    ),
)

_E1_OPERATIONS: dict[str, OperationSpec] = {}


def _register(spec: OperationSpec) -> None:
    if spec.name in _E1_OPERATIONS:
        raise RuntimeError(f"duplicate operation registration: {spec.name}")
    _E1_OPERATIONS[spec.name] = spec


for _spec in _READ_OPS:
    _register(_spec)

_register(
    OperationSpec(
        name="static_analysis",
        permission_class=PermissionClass.READ,
        handler=analyze_python_tree,
        description="AST-based module analysis for every .py file under a granted root",
        requires_domains=frozenset({EngineeringDomain.CODE_ANALYSIS}),
        operation_id="static_analysis",
        input_contract="params: target — one absolute root path string",
        output_contract=(
            "(payload mapping, accesses tuple) — per-module symbol/import "
            "records plus FileAccessEvidence per parsed file"
        ),
        resource_boundary="D-13 output ceiling; per-read byte ceiling",
        security_boundary=(
            "parsing only — analyzed code is never executed; grant-root "
            "containment; no network"
        ),
        evidence_expectation="one access record per parsed module",
        verification_expectation="deterministic re-run hash sampling",
    )
)
_register(
    OperationSpec(
        name="import_graph",
        permission_class=PermissionClass.READ,
        handler=build_import_graph,
        description="deterministic intra-root import graph construction",
        requires_domains=frozenset({EngineeringDomain.CODE_ANALYSIS}),
        operation_id="import_graph",
        input_contract="params: target — one absolute root path string",
        output_contract=(
            "(payload mapping, accesses tuple) — deterministic graph edge "
            "records plus FileAccessEvidence per analyzed file"
        ),
        resource_boundary="D-13 output ceiling; per-read byte ceiling",
        security_boundary=(
            "static extraction only; grant-root containment; no network"
        ),
        evidence_expectation="one access record per analyzed module",
        verification_expectation="deterministic re-run hash sampling",
    )
)
_register(
    OperationSpec(
        name="parse_test_report",
        permission_class=PermissionClass.READ,
        handler=parse_junit_report,
        description="junit-xml report parsing into typed test records",
        requires_domains=frozenset({EngineeringDomain.TESTING}),
        operation_id="parse_test_report",
        input_contract="params: report_path — one absolute report file path",
        output_contract=(
            "TestReportSummary — typed junit records (total/passed/failed/"
            "errors/skipped, failure names, per-test records)"
        ),
        resource_boundary="D-13 output ceiling; per-read byte ceiling",
        security_boundary=(
            "XML parsing only; grant-root containment; no network; "
            "fail-closed on malformed reports"
        ),
        evidence_expectation=(
            "one access record for the report plus one test record per "
            "parsed test"
        ),
        verification_expectation=(
            "test-report arithmetic consistency + failures-listed check + "
            "re-run hash match"
        ),
    )
)
_register(
    OperationSpec(
        name="run_tests",
        permission_class=PermissionClass.CONTROLLED_WRITE,
        handler=build_sandbox_request,
        description=(
            "sandboxed pytest execution through the isolation substrate "
            "(D-11=A); fixed argv; network NONE; real execution inside "
            "the verified local substrate"
        ),
        requires_domains=frozenset({EngineeringDomain.TESTING}),
        operation_id="run_tests",
        input_contract=(
            "params: targets — repository-relative paths without escapes; "
            "image — allowlisted sandbox image name"
        ),
        output_contract=(
            "junit-xml report at the custody path + parsed "
            "TestReportSummary + sandbox execution record"
        ),
        resource_boundary=(
            "D-13 ExecutionLimits (timeout, vcpu, memory, processes, "
            "output, artifact, workspace ceilings)"
        ),
        security_boundary=(
            "kernel-namespace sandbox (pid 1, namespaces, pivot_root, "
            "seccomp, capability drop, NO_NEW_PRIVS, rlimits); network "
            "NONE; sources mounted read-only; artifacts exit via custody "
            "bind only"
        ),
        evidence_expectation=(
            "command record (argv, exit code, duration) + custody "
            "artifact records + test records + teardown attestation"
        ),
        verification_expectation=(
            "report parsed with consistent counts + custody manifest "
            "match; exit code is evidence, never the verdict"
        ),
    )
)
_register(
    OperationSpec(
        name="run_engineering_loop",
        permission_class=PermissionClass.CONTROLLED_WRITE,
        handler=parse_objective_payload,
        description=(
            "E2 delegated engineering objective: a bounded autonomous "
            "loop (understand -> build/test -> diagnose -> plan -> repair "
            "-> retest -> verify) over a granted repository with an "
            "explicit delegated repair playbook; executed by "
            "engineering.loop.EngineeringLoopEngine, never the "
            "single-pass executor; G4 (order v1, 2026-09-10) runs the "
            "loop under the explicit contract: audited engineering "
            "states, terminal-state categories, and the failure-chain "
            "bound"
        ),
        requires_domains=frozenset({EngineeringDomain.TESTING}),
        operation_id="run_engineering_loop",
        input_contract=(
            "params: target (absolute root), test_targets (repo-relative), "
            "image, strategies (delegated patch playbook), limits "
            "(incl. max_failure_chain); request MUST carry task_id "
            "(G4 order §3 — attribution is mandatory wherever mutation "
            "is possible)"
        ),
        output_contract=(
            "LoopResult with per-iteration records + fresh verification "
            "+ the frozen EngineeringLoopContract (identity, bounds, "
            "audited step history, terminal facts)"
        ),
        resource_boundary=(
            "LoopLimits budgets (iterations, attempts, failure chain, "
            "wall clock) over D-13 ExecutionLimits"
        ),
        security_boundary=(
            "delegated scope only — the loop cannot widen scope, "
            "playbook, or budgets; sandboxed test execution; no network; "
            "task_id is attribution, never authority"
        ),
        evidence_expectation=(
            "per-iteration actions, patch outcomes, command records, "
            "verification records, and the append-only step history"
        ),
        verification_expectation=(
            "independent fresh-verification pass outside the loop"
        ),
    )
)
_register(
    OperationSpec(
        name="run_engineering_mission",
        permission_class=PermissionClass.CONTROLLED_WRITE,
        handler=parse_mission_payload,
        description=(
            "E3 delegated engineering mission: a multi-stage task graph "
            "(understand/modify/test/verify stages with explicit "
            "dependencies, per-task scopes, bounded in-task retries, and "
            "mission-level independent verification) over a granted "
            "repository; executed by "
            "engineering.mission_engine.EngineeringMissionEngine, never "
            "the single-pass executor"
        ),
        requires_domains=frozenset({EngineeringDomain.TESTING}),
        operation_id="run_engineering_mission",
        input_contract=(
            "params: target, image, workspace_scope prefixes, tasks "
            "(id, kind, scope), limits"
        ),
        output_contract="MissionResult with per-task results + mission-level verification",
        resource_boundary=(
            "MissionLimits budgets (tasks, retries, wall clock) over "
            "D-13 ExecutionLimits; per-task scope prefixes"
        ),
        security_boundary=(
            "delegated task graph only — the engine cannot widen mission "
            "scope, stages, or budgets; sandboxed executions; no network"
        ),
        evidence_expectation=(
            "per-attempt records, task results, failure propagation "
            "records, verification records"
        ),
        verification_expectation="mission-level independent verification pass",
    )
)
_register(
    OperationSpec(
        name="run_high_impact_commit",
        permission_class=PermissionClass.HIGH_IMPACT,
        handler=parse_high_impact_payload,
        description=(
            "E4 high-impact git commit: a REAL `git commit` executed by "
            "the real git binary inside the verified kernel-namespace "
            "sandbox against a staged workspace repository, under a "
            "signed Owner approval (single-use lease bound to the request "
            "digest), a frozen policy, and D-13/HighImpactLimits budgets; "
            "verified by independent pure-Python git object-db "
            "reconstruction and reversed by snapshot rollback; executed "
            "by engineering.high_impact_engine.HighImpactEngine, never "
            "the single-pass executor"
        ),
        requires_domains=frozenset({EngineeringDomain.SOFTWARE_ENGINEERING}),
        operation_id="run_high_impact_commit",
        input_contract=(
            "params: target, message, include prefixes, author identity, "
            "rollback flag, limits + a signed Owner approval"
        ),
        output_contract="HighImpactOutcome with commit identity + independent verification",
        resource_boundary=(
            "HighImpactLimits budgets over D-13; single-use request-bound "
            "approval lease"
        ),
        security_boundary=(
            "sandboxed real git commit under frozen policy; independent "
            "object-db verification; snapshot rollback; Owner approval "
            "required"
        ),
        evidence_expectation=(
            "approval validation records, sandbox command records, "
            "commit object evidence, rollback attestation"
        ),
        verification_expectation=(
            "independent pure-Python git object-db reconstruction"
        ),
    )
)

# -- G3 controlled write operations (execution order v1, 2026-09-10) -------
# The "separate authorization" E1.md recorded as required before
# write-class domain operations could be registered. The granted
# repository is NEVER mutated: reads go through the granted-scope
# path policy; writes land only in the per-request ephemeral
# workspace and exit through the custody manifest.

_register(
    OperationSpec(
        name="source_modification",
        permission_class=PermissionClass.CONTROLLED_WRITE,
        handler=source_modification,
        description=(
            "G3 controlled file modification: exact-intent modification "
            "of a file read from the granted scope, executed inside the "
            "per-request ephemeral workspace; the modified content exits "
            "through the custody boundary only; the granted repository "
            "is never mutated"
        ),
        requires_domains=frozenset({EngineeringDomain.SOFTWARE_ENGINEERING}),
        operation_id="source_modification",
        input_contract=(
            "params: source (absolute path under a granted root), "
            "expected_sha256 (declared source precondition, 64-hex), "
            "new_content (declared UTF-8 replacement text), artifact_name "
            "(workspace-relative custody name); request must carry task_id"
        ),
        output_contract=(
            "WriteOperationOutcome with FileAccessEvidence (source read) "
            "+ ArtifactCustodyEntry (custody exit) + declared/observed "
            "hashes"
        ),
        resource_boundary=(
            "D-13 workspace ceiling enforced BEFORE any byte is written "
            "(no partial writes); G3 declaration ceiling on content size; "
            "path-policy read ceiling on the source"
        ),
        security_boundary=(
            "source read confined to granted roots after symlink "
            "resolution; writes confined to the ephemeral workspace; "
            "custody-only artifact exit; no process creation, no network"
        ),
        evidence_expectation=(
            "access record for the source + custody artifact record + "
            "changed-resource ledger (before/after hashes) + request "
            "identity event (task/mission attribution)"
        ),
        verification_expectation=(
            "intent-match check (declared source hash and declared "
            "content vs observed ledger) + output hash check on the "
            "written artifact + artifact-readable check + custody "
            "manifest match"
        ),
    )
)
_register(
    OperationSpec(
        name="artifact_creation",
        permission_class=PermissionClass.CONTROLLED_WRITE,
        handler=artifact_creation,
        description=(
            "G3 artifact generation: declared-content artifact created "
            "directly in the custody boundary of the per-request "
            "ephemeral workspace; the declared hash is a binding "
            "precondition"
        ),
        requires_domains=None,
        operation_id="artifact_creation",
        input_contract=(
            "params: artifact_name (workspace-relative custody name), "
            "content (declared UTF-8 text), content_sha256 (declared "
            "hash, 64-hex); request must carry task_id"
        ),
        output_contract=(
            "WriteOperationOutcome with ArtifactCustodyEntry + "
            "declared/observed hashes"
        ),
        resource_boundary=(
            "D-13 workspace ceiling enforced BEFORE any byte is written; "
            "G3 declaration ceiling on content size"
        ),
        security_boundary=(
            "writes confined to the ephemeral workspace custody "
            "directory; custody-only exit; no process creation, no "
            "network, no granted-repository access"
        ),
        evidence_expectation=(
            "custody artifact record + changed-resource ledger + request "
            "identity event (task/mission attribution)"
        ),
        verification_expectation=(
            "declared-hash precondition check + output hash check on the "
            "written artifact + artifact-readable check + custody "
            "manifest match"
        ),
    )
)

#: The operation registry (read-only view).
E1_OPERATIONS: dict[str, OperationSpec] = {
    name: spec for name, spec in _E1_OPERATIONS.items()
}


@dataclass(frozen=True)
class DomainImplementationRecord:
    """Implementation record for one declared engineering domain."""

    domain: EngineeringDomain
    operations: tuple[str, ...]
    implementation_modules: tuple[str, ...]
    state: DomainImplementationState
    blocked_gate: str = ""


#: Per-domain implementation records (truthful, cross-checked by tests).
E1_DOMAIN_IMPLEMENTATIONS: dict[EngineeringDomain, DomainImplementationRecord] = {
    EngineeringDomain.SOFTWARE_ENGINEERING: DomainImplementationRecord(
        domain=EngineeringDomain.SOFTWARE_ENGINEERING,
        operations=("run_high_impact_commit", "source_modification"),
        implementation_modules=(
            "contracts.high_impact",
            "engineering.approval",
            "engineering.high_impact_engine",
            "contracts.write_operations",
        ),
        state=DomainImplementationState.AVAILABLE,
    ),
    EngineeringDomain.CODE_ANALYSIS: DomainImplementationRecord(
        domain=EngineeringDomain.CODE_ANALYSIS,
        operations=("static_analysis", "import_graph"),
        implementation_modules=("contracts.static_analysis",),
        state=DomainImplementationState.AVAILABLE,
    ),
    EngineeringDomain.TESTING: DomainImplementationRecord(
        domain=EngineeringDomain.TESTING,
        operations=(
            "run_tests",
            "parse_test_report",
            "run_engineering_loop",
            "run_engineering_mission",
        ),
        implementation_modules=(
            "contracts.testing_domain",
            "substrate.local_substrate",
            "contracts.objective",
            "engineering.loop",
            "contracts.mission",
            "engineering.mission_engine",
        ),
        state=DomainImplementationState.AVAILABLE,
    ),
}


def operations_for_domain(domain: EngineeringDomain) -> tuple[OperationSpec, ...]:
    """All registered operations whose required domains include ``domain``."""
    return tuple(
        spec
        for spec in E1_OPERATIONS.values()
        if spec.requires_domains is not None and domain in spec.requires_domains
    )


def domain_state_is_consistent() -> tuple[bool, tuple[str, ...]]:
    """Cross-check domain states against this registry.

    Returns (consistent, problems). A problem string is a truthful
    mismatch description — the domain-state guard raises on them.
    """
    problems: list[str] = []
    for domain, state in DOMAIN_IMPLEMENTATION_STATES.items():
        record = E1_DOMAIN_IMPLEMENTATIONS.get(domain)
        if state in (
            DomainImplementationState.AVAILABLE,
            DomainImplementationState.IMPLEMENTED_EXECUTION_BLOCKED,
        ):
            if record is None:
                problems.append(
                    f"{domain.value} claims {state.value} but has no "
                    "implementation record"
                )
                continue
            if record.state is not state:
                problems.append(
                    f"{domain.value} state {state.value} != registry "
                    f"{record.state.value}"
                )
            if not record.operations:
                problems.append(
                    f"{domain.value} claims {state.value} but registers "
                    "no operations"
                )
            for operation_name in record.operations:
                if operation_name not in E1_OPERATIONS:
                    problems.append(
                        f"{domain.value} references unregistered operation "
                        f"{operation_name!r}"
                    )
            if (
                state is DomainImplementationState.IMPLEMENTED_EXECUTION_BLOCKED
                and not record.blocked_gate
            ):
                problems.append(
                    f"{domain.value} is execution-blocked but records no "
                    "blocked gate"
                )
        elif state is DomainImplementationState.DECLARED_NOT_IMPLEMENTED:
            if record is not None:
                problems.append(
                    f"{domain.value} is DECLARED_NOT_IMPLEMENTED but has "
                    "an implementation record"
                )
            if operations_for_domain(domain):
                problems.append(
                    f"{domain.value} is DECLARED_NOT_IMPLEMENTED but has "
                    "registered operations"
                )
    for domain, record in E1_DOMAIN_IMPLEMENTATIONS.items():
        state = DOMAIN_IMPLEMENTATION_STATES.get(domain)
        if state is None:
            problems.append(f"registry covers undeclared domain {domain.value!r}")
        elif state is not record.state:
            problems.append(
                f"{domain.value} registry state {record.state.value} != "
                f"declared state {state.value}"
            )
    return (not problems), tuple(problems)


__all__ = [
    "DomainImplementationRecord",
    "E1_DOMAIN_IMPLEMENTATIONS",
    "E1_OPERATIONS",
    "OperationSpec",
    "domain_state_is_consistent",
    "operations_for_domain",
]
