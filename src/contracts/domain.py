"""Engineering domain declarations and implementation states.

Every domain below is DECLARED. A domain may only move beyond
``DECLARED_NOT_IMPLEMENTED`` when a real, tested implementation
exists behind it, registered in the E1 implementation registry
(:mod:`contracts.implementation`) — the guard
:func:`assert_no_domain_available` enforces exactly that.

E1 (contract version 0.2.0) implementation states:

- ``code_analysis`` — AVAILABLE (real, tested static analysis);
- ``testing`` — IMPLEMENTED_EXECUTION_BLOCKED (spec, junit-xml
  parsing, and sandbox request construction are implemented and
  tested; the run itself requires the container substrate, whose
  acceptance gate is BLOCKED on the missing external dependency);
- all other domains — DECLARED / NOT_IMPLEMENTED (unchanged).

E4 (contract version 0.6.0): ``software_engineering`` becomes
AVAILABLE with exactly ONE registered operation — the
approval-gated ``run_high_impact_commit`` (real git commit inside
the verified sandbox, owner-approved, lease-bounded, verified,
reversible). The domain record stays truthful about that scope.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum


class EngineeringDomain(str, Enum):
    """Declared engineering domains (declarations only)."""

    SOFTWARE_ENGINEERING = "software_engineering"
    SYSTEM_ENGINEERING = "system_engineering"
    ARCHITECTURE = "architecture"
    CODE_ANALYSIS = "code_analysis"
    BUILD = "build"
    TESTING = "testing"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    SIMULATION = "simulation"
    TECHNICAL_RESEARCH = "technical_research"
    ENGINEERING_AUTOMATION = "engineering_automation"


class DomainImplementationState(str, Enum):
    """Implementation state of a declared domain."""

    #: Declared in the contract; no implementation exists.
    DECLARED_NOT_IMPLEMENTED = "DECLARED_NOT_IMPLEMENTED"
    #: Backed by a real, tested implementation.
    AVAILABLE = "AVAILABLE"
    #: Implementation exists and is tested, but the domain's execution
    #: acceptance gate is BLOCKED on a missing external dependency
    #: (the container isolation substrate, D-01 = A). The domain is
    #: NOT operational end-to-end and never claims to be.
    IMPLEMENTED_EXECUTION_BLOCKED = "IMPLEMENTED_EXECUTION_BLOCKED"


#: Implementation state of every declared domain (E4: code_analysis,
#: testing, and software_engineering available — the testing domain's
#: run_tests executes for real inside the verified local substrate;
#: software_engineering carries the E4 approval-gated commit; the rest
#: declared-only).
DOMAIN_IMPLEMENTATION_STATES: Mapping[EngineeringDomain, DomainImplementationState] = {
    EngineeringDomain.SOFTWARE_ENGINEERING: DomainImplementationState.AVAILABLE,
    EngineeringDomain.SYSTEM_ENGINEERING: DomainImplementationState.DECLARED_NOT_IMPLEMENTED,
    EngineeringDomain.ARCHITECTURE: DomainImplementationState.DECLARED_NOT_IMPLEMENTED,
    EngineeringDomain.CODE_ANALYSIS: DomainImplementationState.AVAILABLE,
    EngineeringDomain.BUILD: DomainImplementationState.DECLARED_NOT_IMPLEMENTED,
    EngineeringDomain.TESTING: DomainImplementationState.AVAILABLE,
    EngineeringDomain.DEBUGGING: DomainImplementationState.DECLARED_NOT_IMPLEMENTED,
    EngineeringDomain.REFACTORING: DomainImplementationState.DECLARED_NOT_IMPLEMENTED,
    EngineeringDomain.SIMULATION: DomainImplementationState.DECLARED_NOT_IMPLEMENTED,
    EngineeringDomain.TECHNICAL_RESEARCH: DomainImplementationState.DECLARED_NOT_IMPLEMENTED,
    EngineeringDomain.ENGINEERING_AUTOMATION: DomainImplementationState.DECLARED_NOT_IMPLEMENTED,
}


def domain_implementation_state(domain: EngineeringDomain) -> DomainImplementationState:
    """Return the implementation state of ``domain``.

    Fails closed: anything that is not a declared EngineeringDomain is
    an error — never an assumption.
    """
    if not isinstance(domain, EngineeringDomain):
        raise ValueError(f"undeclared domain: {domain!r}")
    return DOMAIN_IMPLEMENTATION_STATES[domain]


def assert_no_domain_available() -> None:
    """Raise if a domain's implementation state is unjustified.

    The guard cross-checks the declared domain states against the E1
    implementation registry: every domain claiming ``AVAILABLE`` or
    ``IMPLEMENTED_EXECUTION_BLOCKED`` must have a registered, real
    implementation (with a recorded blocked gate for the blocked
    state), and no ``DECLARED_NOT_IMPLEMENTED`` domain may have one.
    This is the evolved form of the E0 invariant — availability
    claims are still forbidden unless they are TRUE.
    """
    # Lazy import avoids a module-level cycle with the registry.
    from contracts.implementation import domain_state_is_consistent

    consistent, problems = domain_state_is_consistent()
    if not consistent:
        raise RuntimeError(
            "domain implementation states are inconsistent with the "
            "registry: " + "; ".join(problems)
        )
