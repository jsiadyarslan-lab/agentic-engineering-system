"""E2 delegated engineering objective — the bounded autonomy contract.

This module holds ONLY contract types and the fail-closed payload
parser for a delegated engineering objective (E2 order §2: how a
delegated task enters, how its scope/limits/playbook are fixed). The
engine that executes the objective lives in
:mod:`engineering.loop` — the split keeps the operation registry
(import-free of the engine) acyclic.

Contract shape (all frozen, validated at construction):

- :class:`LoopLimits` — the bounded-autonomy budget: iteration cap,
  per-iteration execution timeout, wall-clock budget, repair budget,
  per-file write cap, plus the D-13 execution-limit fields the
  iterations may only LOWER. Every ceiling is enforced at parse time —
  an objective that exceeds any ceiling is rejected, never clamped.
- :class:`FilePatch` — one deterministic file edit: an exact
  ``old_text`` -> ``new_text`` replacement at a repository-relative
  path. The old text must match EXACTLY ONCE; the engine never guesses.
- :class:`RepairStrategy` — one delegated repair: which observed
  diagnosis signatures it addresses (``kind:``/``message:``/``test:``
  matchers), the patch it may apply, and how many times it may be
  applied. Repair knowledge is DELEGATED (declared in the objective)
  — the autonomy of the loop is the bounded control flow
  (observe -> diagnose -> select -> apply -> retest), never invention.
- :class:`DelegatedObjective` — the objective itself: repository root,
  test targets, sandbox image, the ordered playbook, and the limits.

Fail-closed parsing: :func:`parse_objective_payload` converts an
admitted ``run_engineering_loop`` operation payload into a typed
objective or a machine-readable :class:`ObjectiveRejectionReason`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from substrate.limits import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_MAX_PROCESSES,
    DEFAULT_MAX_WORKSPACE_BYTES,
    DEFAULT_MEMORY_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_VCPU,
    ExecutionLimits,
)

#: Structural ceiling on loop iterations (order §3: deterministic
#: termination; the engine's cycle count is bounded by construction).
MAX_LOOP_ITERATIONS_CEILING: int = 32

#: Structural ceiling on the wall-clock budget (seconds).
MAX_WALL_CLOCK_BUDGET_SECONDS: float = 3600.0

#: Structural ceiling on total repair applications.
MAX_REPAIR_APPLICATIONS_CEILING: int = 32

#: Structural ceiling on the failure chain (G4 order §4: maximum
#: consecutive failed iterations without an applied repair — the
#: belt-and-braces bound that guarantees no unproductive repair
#: cycling even when strategy and application budgets remain).
MAX_FAILURE_CHAIN_CEILING: int = 8

#: Structural ceiling on one patched file's resulting size (bytes).
MAX_PATCHED_FILE_BYTES_CEILING: int = 8 * 1024 * 1024

#: Observed failure kinds the engine may diagnose. Strategies match on
#: these (``kind:TEST_FAILURE`` style) plus message/test substrings.
DIAGNOSIS_KINDS: frozenset[str] = frozenset(
    {
        "TEST_FAILURE",  # tests ran; at least one failed
        "BUILD_ERROR",  # collection/syntax/import errors (the build phase)
        "NO_TESTS",  # the report parsed but carries zero tests
        "EXECUTION_TIMEOUT",  # the iteration watchdog killed the run
        "RESOURCE_LIMIT",  # the sandbox enforced a resource limit
        "REPORT_MISSING",  # execution produced no junit report
        "REPORT_UNPARSEABLE",  # the report exists but failed to parse
        "SANDBOX_BLOCKED",  # substrate/acceptance gate blocked execution
        "GRANT_INVALID",  # the grant failed execution-time validation
    }
)

_MATCH_PREFIXES: frozenset[str] = frozenset({"kind:", "message:", "test:"})


class ObjectiveRejectionReason(str, Enum):
    """Machine-readable reasons an objective payload is rejected."""

    PAYLOAD_NOT_MAPPING = "objective_payload_not_mapping"
    TARGET_MISSING = "objective_target_missing"
    TARGET_INVALID = "objective_target_invalid"
    TEST_TARGETS_INVALID = "objective_test_targets_invalid"
    IMAGE_INVALID = "objective_image_invalid"
    STRATEGIES_MISSING = "objective_strategies_missing"
    STRATEGY_INVALID = "objective_strategy_invalid"
    LIMITS_INVALID = "objective_limits_invalid"
    LIMITS_EXCEED_CEILINGS = "objective_limits_exceed_ceilings"
    LIMITS_EXCEED_D13 = "objective_limits_exceed_d13"


@dataclass(frozen=True)
class ObjectiveParseResult:
    """Fail-closed parse outcome for an objective payload."""

    ok: bool
    objective: "DelegatedObjective | None" = None
    reason: ObjectiveRejectionReason | None = None
    detail: str = ""


@dataclass(frozen=True)
class LoopLimits:
    """The bounded-autonomy budget for one delegated objective.

    Fail-closed: structurally invalid values raise at construction;
    ceiling violations are rejected by the payload parser (never
    clamped). ``iteration_timeout_seconds`` and the resource fields
    feed the per-iteration :class:`ExecutionLimits` and may only LOWER
    the D-13 defaults.
    """

    max_iterations: int = 4
    iteration_timeout_seconds: int = 60
    wall_clock_budget_seconds: float = 300.0
    max_repair_applications: int = 8
    max_failure_chain: int = 3
    max_file_bytes: int = 2 * 1024 * 1024
    vcpu: int = DEFAULT_VCPU
    memory_bytes: int = DEFAULT_MEMORY_BYTES
    max_processes: int = DEFAULT_MAX_PROCESSES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    max_workspace_bytes: int = DEFAULT_MAX_WORKSPACE_BYTES

    def __post_init__(self) -> None:
        integer_fields = (
            "max_iterations",
            "iteration_timeout_seconds",
            "max_repair_applications",
            "max_failure_chain",
            "max_file_bytes",
            "vcpu",
            "memory_bytes",
            "max_processes",
            "max_output_bytes",
            "max_artifact_bytes",
            "max_workspace_bytes",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer, got {value!r}")
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value!r}")
        clock = self.wall_clock_budget_seconds
        if isinstance(clock, bool) or not isinstance(clock, (int, float)):
            raise ValueError(
                f"wall_clock_budget_seconds must be a number, got {clock!r}"
            )
        if clock <= 0:
            raise ValueError(f"wall_clock_budget_seconds must be positive, got {clock!r}")

    def ceilings_report(self) -> tuple[str, ...]:
        """Names of structural ceilings this budget exceeds (may be empty)."""
        violations: list[str] = []
        if self.max_iterations > MAX_LOOP_ITERATIONS_CEILING:
            violations.append(
                f"max_iterations {self.max_iterations} > ceiling "
                f"{MAX_LOOP_ITERATIONS_CEILING}"
            )
        if self.iteration_timeout_seconds > DEFAULT_TIMEOUT_SECONDS:
            violations.append(
                f"iteration_timeout_seconds {self.iteration_timeout_seconds} > "
                f"D-13 timeout {DEFAULT_TIMEOUT_SECONDS}"
            )
        if self.wall_clock_budget_seconds > MAX_WALL_CLOCK_BUDGET_SECONDS:
            violations.append(
                f"wall_clock_budget_seconds {self.wall_clock_budget_seconds} > "
                f"ceiling {MAX_WALL_CLOCK_BUDGET_SECONDS}"
            )
        if self.max_repair_applications > MAX_REPAIR_APPLICATIONS_CEILING:
            violations.append(
                f"max_repair_applications {self.max_repair_applications} > "
                f"ceiling {MAX_REPAIR_APPLICATIONS_CEILING}"
            )
        if self.max_failure_chain > MAX_FAILURE_CHAIN_CEILING:
            violations.append(
                f"max_failure_chain {self.max_failure_chain} > ceiling "
                f"{MAX_FAILURE_CHAIN_CEILING}"
            )
        if self.max_file_bytes > MAX_PATCHED_FILE_BYTES_CEILING:
            violations.append(
                f"max_file_bytes {self.max_file_bytes} > ceiling "
                f"{MAX_PATCHED_FILE_BYTES_CEILING}"
            )
        return tuple(violations)

    def execution_limits(self) -> ExecutionLimits:
        """The per-iteration D-13 execution limits (may only lower)."""
        return ExecutionLimits(
            timeout_seconds=self.iteration_timeout_seconds,
            vcpu=self.vcpu,
            memory_bytes=self.memory_bytes,
            max_processes=self.max_processes,
            max_output_bytes=self.max_output_bytes,
            max_artifact_bytes=self.max_artifact_bytes,
            max_workspace_bytes=self.max_workspace_bytes,
        )


@dataclass(frozen=True)
class FilePatch:
    """One deterministic file edit (exact unique-match replacement).

    ``path`` is repository-relative (no absolute paths, no ``..``
    segments). ``old_text`` must occur exactly once in the file; a
    zero or ambiguous match makes the patch inapplicable — the engine
    never guesses and never applies a partial edit.
    """

    path: str
    old_text: str
    new_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("patch path must be a non-empty string")
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError(
                f"patch path must be repository-relative without escapes: {self.path!r}"
            )
        for text, label in ((self.old_text, "old_text"), (self.new_text, "new_text")):
            if not isinstance(text, str):
                raise ValueError(f"patch {label} must be a string")


@dataclass(frozen=True)
class RepairStrategy:
    """One delegated repair: a matcher set plus one bounded patch.

    ``matches`` entries are explicit signatures with the prefixes
    ``kind:`` (a diagnosis kind), ``message:`` (a substring of an
    observed failure message), or ``test:`` (a substring of a failing
    test name). ``max_applications`` bounds how often the strategy may
    fire across the whole objective.
    """

    strategy_id: str
    description: str
    matches: tuple[str, ...]
    patch: FilePatch
    max_applications: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_id, str) or not self.strategy_id:
            raise ValueError("strategy_id must be a non-empty string")
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")
        if not isinstance(self.matches, tuple) or not self.matches:
            raise ValueError("matches must be a non-empty tuple of signatures")
        for signature in self.matches:
            if not isinstance(signature, str) or not signature:
                raise ValueError("each match signature must be a non-empty string")
            if not any(signature.startswith(prefix) for prefix in _MATCH_PREFIXES):
                raise ValueError(
                    f"match signature must start with kind:/message:/test:: {signature!r}"
                )
            if signature.startswith("kind:"):
                kind = signature[len("kind:"):]
                if kind not in DIAGNOSIS_KINDS:
                    raise ValueError(
                        f"unknown diagnosis kind in matcher: {kind!r} "
                        f"(known: {sorted(DIAGNOSIS_KINDS)})"
                    )
        if not isinstance(self.patch, FilePatch):
            raise ValueError("patch must be a FilePatch")
        if (
            not isinstance(self.max_applications, int)
            or isinstance(self.max_applications, bool)
            or self.max_applications <= 0
        ):
            raise ValueError(
                f"max_applications must be a positive integer, got {self.max_applications!r}"
            )

    def applies_to(self, kind: str, failure_messages: tuple[str, ...],
                   failing_tests: tuple[str, ...]) -> bool:
        """Deterministic matcher evaluation against one observation."""
        for signature in self.matches:
            if signature.startswith("kind:"):
                if signature[len("kind:"):] == kind:
                    return True
            elif signature.startswith("message:"):
                needle = signature[len("message:"):]
                for message in failure_messages:
                    if needle and needle in message:
                        return True
            elif signature.startswith("test:"):
                needle = signature[len("test:"):]
                for name in failing_tests:
                    if needle and needle in name:
                        return True
        return False


@dataclass(frozen=True)
class DelegatedObjective:
    """A delegated engineering objective (E2 order §0 entry point).

    The objective fixes EVERYTHING the loop may do: the repository it
    may repair, the tests that define success, the sandbox image, the
    ordered repair playbook, and the bounded-autonomy limits. The
    engine can neither widen the scope nor invent repairs — there is
    no code path that adds a strategy, a target, or a budget at run
    time.
    """

    objective_id: str
    description: str
    repo_root: str
    test_targets: tuple[str, ...] = ("tests/",)
    image: str = ""
    strategies: tuple[RepairStrategy, ...] = ()
    limits: LoopLimits = LoopLimits()

    def __post_init__(self) -> None:
        if not isinstance(self.objective_id, str) or not self.objective_id:
            raise ValueError("objective_id must be a non-empty string")
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")
        if not isinstance(self.repo_root, str) or not self.repo_root.startswith("/"):
            raise ValueError("repo_root must be an absolute path string")
        if not isinstance(self.test_targets, tuple) or not self.test_targets:
            raise ValueError("test_targets must be a non-empty tuple")
        for target in self.test_targets:
            if not isinstance(target, str) or not target:
                raise ValueError("each test target must be a non-empty string")
            if target.startswith("/") or ".." in target.split("/"):
                raise ValueError(
                    f"test targets must be repository-relative: {target!r}"
                )
        if not isinstance(self.image, str) or not self.image:
            raise ValueError("image must name an allowlisted sandbox image")
        if not isinstance(self.strategies, tuple) or not all(
            isinstance(strategy, RepairStrategy) for strategy in self.strategies
        ):
            raise ValueError("strategies must be a tuple of RepairStrategy")
        if not isinstance(self.limits, LoopLimits):
            raise ValueError("limits must be LoopLimits")
        seen_ids: set[str] = set()
        for strategy in self.strategies:
            if strategy.strategy_id in seen_ids:
                raise ValueError(
                    f"duplicate strategy_id: {strategy.strategy_id!r}"
                )
            seen_ids.add(strategy.strategy_id)
        if self.limits.max_repair_applications < len(self.strategies):
            raise ValueError(
                "max_repair_applications must be at least the playbook size "
                f"({len(self.strategies)})"
            )


#: Limits mapping keys accepted in an objective payload.
_LOOP_LIMIT_FIELDS: frozenset[str] = frozenset(
    {
        "max_iterations",
        "iteration_timeout_seconds",
        "wall_clock_budget_seconds",
        "max_repair_applications",
        "max_failure_chain",
        "max_file_bytes",
        "vcpu",
        "memory_bytes",
        "max_processes",
        "max_output_bytes",
        "max_artifact_bytes",
        "max_workspace_bytes",
    }
)


def parse_objective_payload(
    payload: object,
    *,
    objective_id: str,
) -> ObjectiveParseResult:
    """Parse an admitted ``run_engineering_loop`` payload (fail-closed).

    The payload mapping (all keys besides ``name`` of the operation
    entry):

    ```text
    {
      "target": "/abs/repo/root",          # required
      "test_targets": ["tests/"],          # optional, repo-relative
      "image": "local:...",                # required
      "strategies": [                      # optional (empty = observe-only)
        {"id": "...", "description": "...",
         "matches": ["kind:TEST_FAILURE", "message:ZeroDivision"],
         "patch": {"path": "tests/test_x.py",
                   "old_text": "...", "new_text": "..."},
         "max_applications": 1}
      ],
      "limits": {"max_iterations": 3, ...} # optional subset
    }
    ```
    """
    if not isinstance(payload, dict):
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.PAYLOAD_NOT_MAPPING,
            detail=f"expected a mapping, got {type(payload).__name__}",
        )
    target = payload.get("target")
    if target is None:
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.TARGET_MISSING,
            detail="'target' (the delegated repository root) is required",
        )
    if not isinstance(target, str) or not target.startswith("/"):
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.TARGET_INVALID,
            detail=f"'target' must be an absolute path string, got {target!r}",
        )

    raw_targets = payload.get("test_targets", ["tests/"])
    if not isinstance(raw_targets, (list, tuple)) or not raw_targets:
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.TEST_TARGETS_INVALID,
            detail="'test_targets' must be a non-empty list",
        )
    test_targets: list[str] = []
    for item in raw_targets:
        if not isinstance(item, str) or not item:
            return ObjectiveParseResult(
                ok=False,
                reason=ObjectiveRejectionReason.TEST_TARGETS_INVALID,
                detail=f"test target must be a non-empty string, got {item!r}",
            )
        if item.startswith("/") or ".." in item.split("/"):
            return ObjectiveParseResult(
                ok=False,
                reason=ObjectiveRejectionReason.TEST_TARGETS_INVALID,
                detail=f"test targets must be repository-relative: {item!r}",
            )
        test_targets.append(item)

    image = payload.get("image")
    if not isinstance(image, str) or not image:
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.IMAGE_INVALID,
            detail="'image' must name an allowlisted sandbox image",
        )

    raw_strategies = payload.get("strategies", [])
    if not isinstance(raw_strategies, (list, tuple)):
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.STRATEGIES_MISSING,
            detail="'strategies' must be a list (possibly empty)",
        )
    strategies: list[RepairStrategy] = []
    for index, entry in enumerate(raw_strategies):
        if not isinstance(entry, dict):
            return ObjectiveParseResult(
                ok=False,
                reason=ObjectiveRejectionReason.STRATEGY_INVALID,
                detail=f"strategy #{index} must be a mapping",
            )
        patch_entry = entry.get("patch")
        if not isinstance(patch_entry, dict):
            return ObjectiveParseResult(
                ok=False,
                reason=ObjectiveRejectionReason.STRATEGY_INVALID,
                detail=f"strategy #{index} needs a 'patch' mapping",
            )
        try:
            patch = FilePatch(
                path=patch_entry.get("path", ""),
                old_text=patch_entry.get("old_text", ""),
                new_text=patch_entry.get("new_text", ""),
            )
            strategy = RepairStrategy(
                strategy_id=entry.get("id", ""),
                description=entry.get("description", ""),
                matches=tuple(entry.get("matches", ())),
                patch=patch,
                max_applications=entry.get("max_applications", 1),
            )
        except (ValueError, TypeError) as error:
            return ObjectiveParseResult(
                ok=False,
                reason=ObjectiveRejectionReason.STRATEGY_INVALID,
                detail=f"strategy #{index}: {error}",
            )
        strategies.append(strategy)

    raw_limits = payload.get("limits")
    if raw_limits is None:
        limits = LoopLimits()
    else:
        if not isinstance(raw_limits, dict):
            return ObjectiveParseResult(
                ok=False,
                reason=ObjectiveRejectionReason.LIMITS_INVALID,
                detail="'limits' must be a mapping or absent",
            )
        unknown = sorted(set(raw_limits) - _LOOP_LIMIT_FIELDS)
        if unknown:
            return ObjectiveParseResult(
                ok=False,
                reason=ObjectiveRejectionReason.LIMITS_INVALID,
                detail=f"unknown limit fields: {unknown}",
            )
        values: dict[str, object] = dict(raw_limits)
        try:
            limits = LoopLimits(**values)  # type: ignore[arg-type]
        except (ValueError, TypeError) as error:
            return ObjectiveParseResult(
                ok=False,
                reason=ObjectiveRejectionReason.LIMITS_INVALID,
                detail=f"limits: {error}",
            )
    ceiling_violations = limits.ceilings_report()
    if ceiling_violations:
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.LIMITS_EXCEED_CEILINGS,
            detail="; ".join(ceiling_violations),
        )
    from substrate.limits import validate_against_defaults

    policy = validate_against_defaults(limits.execution_limits())
    if not policy.valid:
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.LIMITS_EXCEED_D13,
            detail=policy.detail,
        )

    description = payload.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    try:
        objective = DelegatedObjective(
            objective_id=objective_id,
            description=description,
            repo_root=target,
            test_targets=tuple(test_targets),
            image=image,
            strategies=tuple(strategies),
            limits=limits,
        )
    except (ValueError, TypeError) as error:
        return ObjectiveParseResult(
            ok=False,
            reason=ObjectiveRejectionReason.STRATEGY_INVALID,
            detail=str(error),
        )
    return ObjectiveParseResult(ok=True, objective=objective)


__all__ = [
    "DIAGNOSIS_KINDS",
    "DelegatedObjective",
    "FilePatch",
    "LoopLimits",
    "MAX_FAILURE_CHAIN_CEILING",
    "MAX_LOOP_ITERATIONS_CEILING",
    "MAX_PATCHED_FILE_BYTES_CEILING",
    "MAX_REPAIR_APPLICATIONS_CEILING",
    "MAX_WALL_CLOCK_BUDGET_SECONDS",
    "ObjectiveParseResult",
    "ObjectiveRejectionReason",
    "RepairStrategy",
    "parse_objective_payload",
]
