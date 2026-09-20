"""E3 engineering mission contract — multi-stage, delegated, bounded.

This module holds ONLY contract types, the fail-closed payload parser,
and the delegator-side request builder for an engineering mission (E3
order §3: how a multi-stage mission enters, how its scope/limits/task
graph are fixed). The engine that executes the mission lives in
:mod:`engineering.mission_engine` — the split keeps the operation
registry (import-free of the engine) acyclic, exactly like the E2
objective/loop split.

Contract shape (all frozen, validated at construction):

- :class:`MissionLimits` — the mission budget: per-task attempt cap,
  mission-wide attempt cap, wall-clock budget, mission-wide repair
  budget, per-file write cap, plus the D-13 execution-limit fields the
  attempts may only LOWER. Every ceiling is enforced at parse time —
  a mission that exceeds any ceiling is rejected, never clamped.
- :class:`MissionTask` — one node of the mission task graph: a task
  kind (:class:`TaskKind`), explicit dependencies, the task scope
  (repository-relative prefixes the task may touch), and the
  task-specific payload (patch for MODIFY, test targets for
  TEST/VERIFY, a delegated repair playbook for in-task bounded
  retries).
- :class:`EngineeringMission` — the mission itself: objective,
  repository root (repository scope), workspace scope (mission-wide
  prefix boundary), the ordered task graph, the sandbox image, and
  the limits.

The five scopes (order §2) and where each is fixed:

```text
Mission Scope     repo_root + workspace_scope     (here, frozen)
Task Scope        MissionTask.scope               (here, frozen;
                                                  subset of workspace)
Execution Scope   per-attempt run_tests requests  (mission_engine;
                  through full production          admission re-runs)
                  admission
Resource Scope    MissionLimits + D-13 fields     (here, frozen;
                                                  may only lower)
Authority Scope   registered operations only      (admission/registry;
                                                  never widened)
```

Engineering cannot modify the Owner Objective, Authority, Policy, or
Mission Scope from inside the mission: every contract here is a frozen
dataclass, the engine holds no widening code path, and the parser
rejects anything that would place a task outside the declared scope.

Fail-closed parsing: :func:`parse_mission_payload` converts an
admitted ``run_engineering_mission`` operation payload into a typed
mission or a machine-readable :class:`MissionRejectionReason`.
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
from contracts.objective import RepairStrategy

#: Structural ceiling on the task-graph size (order §3: deterministic
#: termination — the graph is finite by construction).
MAX_MISSION_TASKS: int = 32

#: Structural ceiling on attempts for ONE task.
MAX_TASK_ATTEMPTS_CEILING: int = 8

#: Structural ceiling on attempts across the WHOLE mission. The parser
#: additionally requires sum(task.max_attempts) <= this value, so the
#: engine's total work is bounded by construction.
MAX_TOTAL_ATTEMPTS_CEILING: int = 64

#: Structural ceiling on the mission wall-clock budget (seconds).
MAX_MISSION_WALL_CLOCK_SECONDS: float = 3600.0

#: Structural ceiling on total repair applications (mission-wide).
MAX_MISSION_REPAIRS_CEILING: int = 32

#: Structural ceiling on one patched file's resulting size (bytes).
MAX_MISSION_PATCHED_FILE_BYTES: int = 8 * 1024 * 1024


class TaskKind(str, Enum):
    """The kinds of work a mission task may perform (delegated).

    - ``UNDERSTAND``: read-only repository facts (host-side, evidenced).
    - ``MODIFY``: one deterministic delegated file edit (host-side,
      exact-match patch, scope-checked before any byte is written).
    - ``TEST``: one REAL sandboxed pytest execution per attempt; may
      carry a delegated repair playbook for bounded in-task retries
      (the order §7 recovery shape: fail -> repair -> retry).
    - ``VERIFY``: one REAL fresh sandboxed run, no repair playbook —
      a verification stage never repairs itself.
    """

    UNDERSTAND = "UNDERSTAND"
    MODIFY = "MODIFY"
    TEST = "TEST"
    VERIFY = "VERIFY"


class MissionRejectionReason(str, Enum):
    """Machine-readable reasons a mission payload is rejected."""

    PAYLOAD_NOT_MAPPING = "mission_payload_not_mapping"
    TARGET_MISSING = "mission_target_missing"
    TARGET_INVALID = "mission_target_invalid"
    IMAGE_INVALID = "mission_image_invalid"
    WORKSPACE_SCOPE_INVALID = "mission_workspace_scope_invalid"
    TASKS_MISSING = "mission_tasks_missing"
    TASKS_EMPTY = "mission_tasks_empty"
    TASKS_TOO_MANY = "mission_tasks_too_many"
    TASK_INVALID = "mission_task_invalid"
    TASK_DUPLICATE_ID = "mission_task_duplicate_id"
    DEPENDENCY_UNKNOWN = "mission_dependency_unknown"
    DEPENDENCY_CYCLE = "mission_dependency_cycle"
    TASK_SCOPE_OUTSIDE_WORKSPACE = "mission_task_scope_outside_workspace"
    TOTAL_ATTEMPTS_EXCEED_BUDGET = "mission_total_attempts_exceed_budget"
    LIMITS_INVALID = "mission_limits_invalid"
    LIMITS_EXCEED_CEILINGS = "mission_limits_exceed_ceilings"
    LIMITS_EXCEED_D13 = "mission_limits_exceed_d13"


@dataclass(frozen=True)
class MissionParseResult:
    """Fail-closed parse outcome for a mission payload."""

    ok: bool
    mission: "EngineeringMission | None" = None
    reason: MissionRejectionReason | None = None
    detail: str = ""


@dataclass(frozen=True)
class MissionLimits:
    """The bounded-mission budget.

    Fail-closed: structurally invalid values raise at construction;
    ceiling violations are rejected by the payload parser (never
    clamped). ``attempt_timeout_seconds`` and the resource fields feed
    the per-attempt :class:`ExecutionLimits` and may only LOWER the
    D-13 defaults.
    """

    max_task_attempts: int = 4
    max_total_attempts: int = 16
    wall_clock_budget_seconds: float = 300.0
    max_repair_applications: int = 8
    max_file_bytes: int = 2 * 1024 * 1024
    attempt_timeout_seconds: int = 60
    vcpu: int = DEFAULT_VCPU
    memory_bytes: int = DEFAULT_MEMORY_BYTES
    max_processes: int = DEFAULT_MAX_PROCESSES
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    max_workspace_bytes: int = DEFAULT_MAX_WORKSPACE_BYTES

    def __post_init__(self) -> None:
        integer_fields = (
            "max_task_attempts",
            "max_total_attempts",
            "max_repair_applications",
            "max_file_bytes",
            "attempt_timeout_seconds",
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
            raise ValueError(
                f"wall_clock_budget_seconds must be positive, got {clock!r}"
            )

    def ceilings_report(self) -> tuple[str, ...]:
        """Names of structural ceilings this budget exceeds (may be empty)."""
        violations: list[str] = []
        if self.max_task_attempts > MAX_TASK_ATTEMPTS_CEILING:
            violations.append(
                f"max_task_attempts {self.max_task_attempts} > ceiling "
                f"{MAX_TASK_ATTEMPTS_CEILING}"
            )
        if self.max_total_attempts > MAX_TOTAL_ATTEMPTS_CEILING:
            violations.append(
                f"max_total_attempts {self.max_total_attempts} > ceiling "
                f"{MAX_TOTAL_ATTEMPTS_CEILING}"
            )
        if self.wall_clock_budget_seconds > MAX_MISSION_WALL_CLOCK_SECONDS:
            violations.append(
                f"wall_clock_budget_seconds {self.wall_clock_budget_seconds} > "
                f"ceiling {MAX_MISSION_WALL_CLOCK_SECONDS}"
            )
        if self.max_repair_applications > MAX_MISSION_REPAIRS_CEILING:
            violations.append(
                f"max_repair_applications {self.max_repair_applications} > "
                f"ceiling {MAX_MISSION_REPAIRS_CEILING}"
            )
        if self.max_file_bytes > MAX_MISSION_PATCHED_FILE_BYTES:
            violations.append(
                f"max_file_bytes {self.max_file_bytes} > ceiling "
                f"{MAX_MISSION_PATCHED_FILE_BYTES}"
            )
        if self.attempt_timeout_seconds > DEFAULT_TIMEOUT_SECONDS:
            violations.append(
                f"attempt_timeout_seconds {self.attempt_timeout_seconds} > "
                f"D-13 timeout {DEFAULT_TIMEOUT_SECONDS}"
            )
        return tuple(violations)

    def execution_limits(self) -> ExecutionLimits:
        """The per-attempt D-13 execution limits (may only lower)."""
        return ExecutionLimits(
            timeout_seconds=self.attempt_timeout_seconds,
            vcpu=self.vcpu,
            memory_bytes=self.memory_bytes,
            max_processes=self.max_processes,
            max_output_bytes=self.max_output_bytes,
            max_artifact_bytes=self.max_artifact_bytes,
            max_workspace_bytes=self.max_workspace_bytes,
        )


@dataclass(frozen=True)
class MissionTask:
    """One node of the mission task graph (frozen, delegated).

    ``scope`` is a tuple of repository-relative path prefixes (a file
    path or a directory prefix) that bound where this task may MODIFY.
    The parser enforces ``scope ⊆ workspace_scope`` so a task can never
    be declared outside the mission workspace. ``depends_on`` names
    other task ids; the graph must be acyclic (checked at parse).
    ``max_attempts`` bounds retries for THIS task; the parser bounds
    the sum across tasks by the mission-wide attempt budget.
    """

    task_id: str
    kind: TaskKind
    description: str = ""
    depends_on: tuple[str, ...] = ()
    scope: tuple[str, ...] = ()
    patch: "tuple[str, str, str] | None" = None  # (path, old_text, new_text)
    test_targets: tuple[str, ...] = ()
    strategies: tuple[RepairStrategy, ...] = ()
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError("task_id must be a non-empty string")
        if not isinstance(self.kind, TaskKind):
            raise ValueError("kind must be a TaskKind")
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")
        if not isinstance(self.depends_on, tuple):
            raise ValueError("depends_on must be a tuple of task ids")
        if not isinstance(self.scope, tuple):
            raise ValueError("scope must be a tuple of path prefixes")
        if not isinstance(self.test_targets, tuple):
            raise ValueError("test_targets must be a tuple")
        if not isinstance(self.strategies, tuple) or not all(
            isinstance(strategy, RepairStrategy) for strategy in self.strategies
        ):
            raise ValueError("strategies must be a tuple of RepairStrategy")
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or self.max_attempts <= 0
        ):
            raise ValueError(
                f"max_attempts must be a positive integer, got {self.max_attempts!r}"
            )


@dataclass(frozen=True)
class EngineeringMission:
    """A delegated engineering mission (E3 order §0 entry point).

    The mission fixes EVERYTHING the engine may do: the repository it
    may work on, the workspace prefix boundary, the task graph with
    its explicit dependencies and per-task scopes, and the bounded
    budgets. The engine can neither widen the scope nor add tasks,
    strategies, or budget at run time — there is no code path that
    mutates this contract (frozen dataclass; structural tests prove
    the engine never assigns to it).
    """

    mission_id: str
    objective: str
    repo_root: str
    workspace_scope: tuple[str, ...]
    tasks: tuple[MissionTask, ...]
    image: str = ""
    limits: MissionLimits = MissionLimits()

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, str) or not self.mission_id:
            raise ValueError("mission_id must be a non-empty string")
        if not isinstance(self.objective, str):
            raise ValueError("objective must be a string")
        if not isinstance(self.repo_root, str) or not self.repo_root.startswith("/"):
            raise ValueError("repo_root must be an absolute path string")
        if not isinstance(self.workspace_scope, tuple) or not self.workspace_scope:
            raise ValueError("workspace_scope must be a non-empty tuple of prefixes")
        if not isinstance(self.tasks, tuple) or not self.tasks:
            raise ValueError("tasks must be a non-empty tuple of MissionTask")
        if not all(isinstance(task, MissionTask) for task in self.tasks):
            raise ValueError("tasks must be MissionTask objects")
        if not isinstance(self.image, str) or not self.image:
            raise ValueError("image must name an allowlisted sandbox image")
        if not isinstance(self.limits, MissionLimits):
            raise ValueError("limits must be MissionLimits")

    def topological_order(self) -> tuple[str, ...]:
        """Deterministic topological order of the task ids.

        Kahn's algorithm with a lexicographic ready-set so the order is
        fully deterministic (no dict/set iteration order dependence).
        The pass count is a ``for`` over the finite task count (there is
        no ``while`` anywhere in this module — a structural guard
        proves it); a graph that still has remaining nodes after every
        pass carries a cycle and raises ``ValueError``.
        """
        remaining = {task.task_id: set(task.depends_on) for task in self.tasks}
        order: list[str] = []
        for _pass in range(len(self.tasks)):
            ready = sorted(
                task_id
                for task_id, deps in remaining.items()
                if not (deps & remaining.keys())
            )
            if not ready:
                break
            for task_id in ready:
                order.append(task_id)
                del remaining[task_id]
            if not remaining:
                break
        if remaining:
            raise ValueError(
                f"mission task graph has a cycle among {sorted(remaining)}"
            )
        return tuple(order)

    def verification_targets(self) -> tuple[str, ...]:
        """The targets of the mission-level verification re-run.

        Derived deterministically from the frozen contract (never
        invented): the union of VERIFY-kind task targets when any
        exist, else the union of TEST-kind task targets.
        """
        kinds = (TaskKind.VERIFY, TaskKind.TEST)
        for kind in kinds:
            targets: list[str] = []
            for task in self.tasks:
                if task.kind is kind and task.test_targets:
                    for target in task.test_targets:
                        if target not in targets:
                            targets.append(target)
            if targets:
                return tuple(targets)
        return ()


#: Limits mapping keys accepted in a mission payload.
_MISSION_LIMIT_FIELDS: frozenset[str] = frozenset(
    {
        "max_task_attempts",
        "max_total_attempts",
        "wall_clock_budget_seconds",
        "max_repair_applications",
        "max_file_bytes",
        "attempt_timeout_seconds",
        "vcpu",
        "memory_bytes",
        "max_processes",
        "max_output_bytes",
        "max_artifact_bytes",
        "max_workspace_bytes",
    }
)


def _repo_relative(value: object) -> bool:
    """True when ``value`` is a repository-relative path string."""
    return (
        isinstance(value, str)
        and value != ""
        and not value.startswith("/")
        and ".." not in value.split("/")
    )


def _valid_scope_prefix(prefix: object) -> bool:
    """True when ``prefix`` names a real subtree/file (never the root).

    Scope prefixes are repository-relative AND must not normalize to
    the workspace root itself (``""``/``"."``): scopes name real
    boundaries, and the root is deliberately not expressible.
    """
    return _repo_relative(prefix) and _normalize_prefix(prefix) not in ("", ".")


def _normalize_prefix(prefix: str) -> str:
    """Normalize a declared scope prefix for containment checks.

    Bounded by construction: at most one leading ``./`` group is
    consumed by a finite ``for`` (no ``while`` exists in this module —
    a structural guard proves it) and trailing separators are stripped
    by ``rstrip``.
    """
    normalized = prefix.strip()
    for _ in range(8):
        if normalized.startswith("./"):
            normalized = normalized[2:]
        else:
            break
    normalized = normalized.rstrip("/")
    return normalized


def path_within_prefixes(path: str, prefixes: tuple[str, ...]) -> bool:
    """Deterministic prefix containment for repository-relative paths.

    A path is within a prefix when it equals the prefix (a file) or
    lies under it (``prefix + "/"``). Empty prefixes never match; the
    workspace root itself ("." or "") is deliberately NOT expressible
    as a prefix — scopes name real subtrees/files, never the root.
    """
    if not _repo_relative(path):
        return False
    normalized_path = _normalize_prefix(path)
    if normalized_path in ("", "."):
        return False
    for prefix in prefixes:
        normalized_prefix = _normalize_prefix(prefix)
        if not normalized_prefix or normalized_prefix == ".":
            continue
        if normalized_path == normalized_prefix:
            return True
        if normalized_path.startswith(normalized_prefix + "/"):
            return True
    return False


def _parse_strategy_entry(
    entry: object, index: int
) -> tuple[RepairStrategy | None, str]:
    """Parse one delegated repair strategy entry; (None, error) on failure."""
    if not isinstance(entry, dict):
        return None, f"strategy #{index} must be a mapping"
    patch_entry = entry.get("patch")
    if not isinstance(patch_entry, dict):
        return None, f"strategy #{index} needs a 'patch' mapping"
    try:
        from contracts.objective import FilePatch

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
        return None, f"strategy #{index}: {error}"
    return strategy, ""


def _parse_task_entry(
    entry: object,
    index: int,
    *,
    workspace_scope: tuple[str, ...],
    max_task_attempts_ceiling: int,
) -> tuple[MissionTask | None, MissionRejectionReason | None, str]:
    """Parse one task entry; (None, reason, detail) on failure (fail-closed).

    ``reason`` is ``None`` for ordinary task-shape failures (mapped to
    TASK_INVALID by the caller) and a SPECIFIC reason where the order
    names one (task scope outside the mission workspace).
    """
    if not isinstance(entry, dict):
        return None, None, f"task #{index} must be a mapping"
    task_id = entry.get("id")
    if not isinstance(task_id, str) or not task_id:
        return None, None, f"task #{index} needs a non-empty string 'id'"
    kind_value = entry.get("kind")
    try:
        kind = TaskKind(kind_value)
    except ValueError:
        return None, None, (
            f"task {task_id!r}: unknown kind {kind_value!r} (known: "
            f"{[member.value for member in TaskKind]})"
        )

    raw_deps = entry.get("depends_on", [])
    if not isinstance(raw_deps, (list, tuple)):
        return None, None, f"task {task_id!r}: 'depends_on' must be a list"
    depends_on: list[str] = []
    for dep in raw_deps:
        if not isinstance(dep, str) or not dep:
            return None, None, f"task {task_id!r}: dependency ids must be non-empty strings"
        depends_on.append(dep)

    raw_scope = entry.get("scope", [])
    if not isinstance(raw_scope, (list, tuple)):
        return None, None, f"task {task_id!r}: 'scope' must be a list"
    scope: list[str] = []
    for prefix in raw_scope:
        if not _valid_scope_prefix(prefix):
            return None, None, (
                f"task {task_id!r}: scope prefix must name a real subtree or "
                f"file (repository-relative, not the root): {prefix!r}"
            )
        scope.append(prefix)

    raw_targets = entry.get("test_targets", [])
    if not isinstance(raw_targets, (list, tuple)):
        return None, None, f"task {task_id!r}: 'test_targets' must be a list"
    test_targets: list[str] = []
    for target in raw_targets:
        if not _repo_relative(target):
            return None, None, (
                f"task {task_id!r}: test target must be repository-relative: "
                f"{target!r}"
            )
        test_targets.append(target)

    raw_strategies = entry.get("strategies", [])
    if not isinstance(raw_strategies, (list, tuple)):
        return None, None, f"task {task_id!r}: 'strategies' must be a list"
    strategies: list[RepairStrategy] = []
    for strategy_index, strategy_entry in enumerate(raw_strategies):
        strategy, error = _parse_strategy_entry(strategy_entry, strategy_index)
        if strategy is None:
            return None, None, f"task {task_id!r}: {error}"
        strategies.append(strategy)
    strategy_ids = [strategy.strategy_id for strategy in strategies]
    if len(strategy_ids) != len(set(strategy_ids)):
        return None, None, f"task {task_id!r}: duplicate strategy ids"

    patch_payload = entry.get("patch")
    patch: tuple[str, str, str] | None = None
    if patch_payload is not None:
        if not isinstance(patch_payload, dict):
            return None, None, f"task {task_id!r}: 'patch' must be a mapping"
        path = patch_payload.get("path", "")
        old_text = patch_payload.get("old_text", "")
        new_text = patch_payload.get("new_text", "")
        if not all(isinstance(value, str) for value in (path, old_text, new_text)):
            return None, None, f"task {task_id!r}: patch path/old_text/new_text must be strings"
        if not _repo_relative(path):
            return None, None, (
                f"task {task_id!r}: patch path must be repository-relative: {path!r}"
            )
        patch = (path, old_text, new_text)

    max_attempts = entry.get("max_attempts", 1)
    if (
        not isinstance(max_attempts, int)
        or isinstance(max_attempts, bool)
        or max_attempts <= 0
    ):
        return None, None, (
            f"task {task_id!r}: max_attempts must be a positive integer, got "
            f"{max_attempts!r}"
        )
    if max_attempts > max_task_attempts_ceiling:
        return None, None, (
            f"task {task_id!r}: max_attempts {max_attempts} > ceiling "
            f"{max_task_attempts_ceiling}"
        )

    description = entry.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    # -- kind-specific requirements (fail-closed) ---------------------------
    if kind is TaskKind.MODIFY:
        if patch is None:
            return None, None, f"task {task_id!r}: MODIFY requires a 'patch' mapping"
        if not scope:
            return None, None, (
                f"task {task_id!r}: MODIFY requires a non-empty 'scope' "
                "(the task's write boundary)"
            )
        if strategies:
            return None, None, (
                f"task {task_id!r}: MODIFY carries no repair playbook "
                "(strategies belong to TEST tasks)"
            )
    elif kind in (TaskKind.TEST, TaskKind.VERIFY):
        if not test_targets:
            return None, None, (
                f"task {task_id!r}: {kind.value} requires non-empty 'test_targets'"
            )
        if kind is TaskKind.VERIFY and strategies:
            return None, None, (
                f"task {task_id!r}: VERIFY carries no repair playbook "
                "(a verification stage never repairs itself)"
            )
        if strategies and not scope:
            return None, None, (
                f"task {task_id!r}: TEST tasks with a repair playbook must "
                "declare their write 'scope' (the repair boundary)"
            )
    elif kind is TaskKind.UNDERSTAND:
        if patch is not None or strategies or test_targets:
            return None, None, (
                f"task {task_id!r}: UNDERSTAND is read-only (no patch, no "
                "strategies, no test targets)"
            )

    # -- task scope must sit inside the mission workspace scope -------------
    if scope and not all(
        path_within_prefixes(prefix, workspace_scope) for prefix in scope
    ):
        return (
            None,
            MissionRejectionReason.TASK_SCOPE_OUTSIDE_WORKSPACE,
            (
                f"task {task_id!r}: scope declares paths outside the mission "
                f"workspace scope {list(workspace_scope)}"
            ),
        )

    task = MissionTask(
        task_id=task_id,
        kind=kind,
        description=description,
        depends_on=tuple(depends_on),
        scope=tuple(scope),
        patch=patch,
        test_targets=tuple(test_targets),
        strategies=tuple(strategies),
        max_attempts=max_attempts,
    )
    return task, None, ""


def parse_mission_payload(
    payload: object,
    *,
    mission_id: str,
) -> MissionParseResult:
    """Parse an admitted ``run_engineering_mission`` payload (fail-closed).

    The payload mapping (all keys besides ``name`` of the operation
    entry):

    ```text
    {
      "target": "/abs/repo/root",          # required
      "image": "local:...",                # required
      "objective": "...",                  # optional description
      "workspace_scope": ["tests/"],       # required: mission-wide prefixes
      "tasks": [                           # required, non-empty, <= 32
        {"id": "T1", "kind": "UNDERSTAND"},
        {"id": "T2", "kind": "MODIFY", "depends_on": ["T1"],
         "scope": ["tests/test_math.py"],
         "patch": {"path": "tests/test_math.py",
                   "old_text": "...", "new_text": "..."}},
        {"id": "T3", "kind": "TEST", "depends_on": ["T2"],
         "test_targets": ["tests/"],
         "strategies": [ ...E2 strategy shape... ],
         "max_attempts": 2},
        {"id": "T4", "kind": "VERIFY", "depends_on": ["T3"],
         "test_targets": ["tests/"]}
      ],
      "limits": {"max_total_attempts": 8, ...}   # optional subset
    }
    ```
    """
    if not isinstance(payload, dict):
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.PAYLOAD_NOT_MAPPING,
            detail=f"expected a mapping, got {type(payload).__name__}",
        )
    target = payload.get("target")
    if target is None:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.TARGET_MISSING,
            detail="'target' (the mission repository root) is required",
        )
    if not isinstance(target, str) or not target.startswith("/"):
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.TARGET_INVALID,
            detail=f"'target' must be an absolute path string, got {target!r}",
        )

    image = payload.get("image")
    if not isinstance(image, str) or not image:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.IMAGE_INVALID,
            detail="'image' must name an allowlisted sandbox image",
        )

    raw_workspace = payload.get("workspace_scope")
    if not isinstance(raw_workspace, (list, tuple)) or not raw_workspace:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.WORKSPACE_SCOPE_INVALID,
            detail="'workspace_scope' must be a non-empty list of prefixes",
        )
    workspace_scope: list[str] = []
    for prefix in raw_workspace:
        if not _valid_scope_prefix(prefix):
            return MissionParseResult(
                ok=False,
                reason=MissionRejectionReason.WORKSPACE_SCOPE_INVALID,
                detail=(
                    "workspace scope prefixes must name a real subtree or "
                    f"file (repository-relative, not the root): {prefix!r}"
                ),
            )
        workspace_scope.append(prefix)

    raw_tasks = payload.get("tasks")
    if raw_tasks is None:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.TASKS_MISSING,
            detail="'tasks' (the mission task graph) is required",
        )
    if not isinstance(raw_tasks, (list, tuple)):
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.TASKS_MISSING,
            detail="'tasks' must be a list of task mappings",
        )
    if not raw_tasks:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.TASKS_EMPTY,
            detail="the mission task graph must carry at least one task",
        )
    if len(raw_tasks) > MAX_MISSION_TASKS:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.TASKS_TOO_MANY,
            detail=(
                f"task graph carries {len(raw_tasks)} tasks > ceiling "
                f"{MAX_MISSION_TASKS}"
            ),
        )

    raw_limits = payload.get("limits")
    if raw_limits is None:
        limits = MissionLimits()
    else:
        if not isinstance(raw_limits, dict):
            return MissionParseResult(
                ok=False,
                reason=MissionRejectionReason.LIMITS_INVALID,
                detail="'limits' must be a mapping or absent",
            )
        unknown = sorted(set(raw_limits) - _MISSION_LIMIT_FIELDS)
        if unknown:
            return MissionParseResult(
                ok=False,
                reason=MissionRejectionReason.LIMITS_INVALID,
                detail=f"unknown limit fields: {unknown}",
            )
        values: dict[str, object] = dict(raw_limits)
        try:
            limits = MissionLimits(**values)  # type: ignore[arg-type]
        except (ValueError, TypeError) as error:
            return MissionParseResult(
                ok=False,
                reason=MissionRejectionReason.LIMITS_INVALID,
                detail=f"limits: {error}",
            )
    ceiling_violations = limits.ceilings_report()
    if ceiling_violations:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.LIMITS_EXCEED_CEILINGS,
            detail="; ".join(ceiling_violations),
        )
    from substrate.limits import validate_against_defaults

    policy = validate_against_defaults(limits.execution_limits())
    if not policy.valid:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.LIMITS_EXCEED_D13,
            detail=policy.detail,
        )

    tasks: list[MissionTask] = []
    for index, entry in enumerate(raw_tasks):
        task, reason_override, error = _parse_task_entry(
            entry,
            index,
            workspace_scope=tuple(workspace_scope),
            max_task_attempts_ceiling=limits.max_task_attempts,
        )
        if task is None:
            return MissionParseResult(
                ok=False,
                reason=reason_override or MissionRejectionReason.TASK_INVALID,
                detail=error,
            )
        tasks.append(task)

    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        duplicates = sorted(
            {task_id for task_id in task_ids if task_ids.count(task_id) > 1}
        )
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.TASK_DUPLICATE_ID,
            detail=f"duplicate task ids: {duplicates}",
        )
    known = set(task_ids)
    for task in tasks:
        for dep in task.depends_on:
            if dep not in known:
                return MissionParseResult(
                    ok=False,
                    reason=MissionRejectionReason.DEPENDENCY_UNKNOWN,
                    detail=(
                        f"task {task.task_id!r} depends on unknown task {dep!r}"
                    ),
                )
            if dep == task.task_id:
                return MissionParseResult(
                    ok=False,
                    reason=MissionRejectionReason.DEPENDENCY_CYCLE,
                    detail=f"task {task.task_id!r} depends on itself",
                )

    total_attempts = sum(task.max_attempts for task in tasks)
    if total_attempts > limits.max_total_attempts:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.TOTAL_ATTEMPTS_EXCEED_BUDGET,
            detail=(
                f"sum of task attempts {total_attempts} exceeds the mission "
                f"attempt budget {limits.max_total_attempts}"
            ),
        )

    mission = EngineeringMission(
        mission_id=mission_id,
        objective=payload.get("objective", "") or "",
        repo_root=target,
        workspace_scope=tuple(workspace_scope),
        tasks=tuple(tasks),
        image=image,
        limits=limits,
    )
    try:
        mission.topological_order()  # cycle defense-in-depth re-check
    except ValueError as error:
        return MissionParseResult(
            ok=False,
            reason=MissionRejectionReason.DEPENDENCY_CYCLE,
            detail=str(error),
        )
    return MissionParseResult(ok=True, mission=mission)


def engineering_mission_request(
    *,
    request_id: str,
    repo_root: str,
    image: str,
    tasks: tuple[object, ...] | list[object],
    workspace_scope: tuple[str, ...] | list[str] = ("tests/",),
    limits: dict[str, object] | None = None,
    objective: str = "",
    subject: str = "JARVIS_PRIME",
) -> "object":
    """Build an E3 request carrying one engineering mission.

    ``tasks`` entries are payload mappings (the delegator-side
    convenience; the admission gate and the parser validate the result
    exactly like any request). Returns a
    :class:`contracts.contract.CapabilityRequest`.
    """
    from contracts.capability import CAPABILITY_IDENTITY, CAPABILITY_VERSION
    from contracts.contract import (
        AuthorizationContext,
        CapabilityRequest,
        CapabilityScope,
        ExecutionMode,
        PermissionClass,
    )
    from contracts.domain import EngineeringDomain

    serialized: list[dict[str, object]] = []
    for task in tasks:
        if isinstance(task, dict):
            serialized.append(dict(task))
        else:
            raise TypeError("mission tasks must be payload mappings")
    operation: dict[str, object] = {
        "name": "run_engineering_mission",
        "target": repo_root,
        "image": image,
        "objective": objective,
        "workspace_scope": list(workspace_scope),
        "tasks": serialized,
    }
    if limits is not None:
        operation["limits"] = dict(limits)
    return CapabilityRequest(
        request_id=request_id,
        capability=CAPABILITY_IDENTITY,
        capability_version=CAPABILITY_VERSION,
        scope=CapabilityScope(domains=(EngineeringDomain.TESTING,)),
        authorization=AuthorizationContext(
            subject=subject,
            permission_class=PermissionClass.CONTROLLED_WRITE,
        ),
        execution_mode=ExecutionMode.MULTI_STEP_ENGINEERING_MISSION,
        input={"operations": [operation]},
    )


__all__ = [
    "MAX_MISSION_PATCHED_FILE_BYTES",
    "MAX_MISSION_REPAIRS_CEILING",
    "MAX_MISSION_TASKS",
    "MAX_MISSION_WALL_CLOCK_SECONDS",
    "MAX_TASK_ATTEMPTS_CEILING",
    "MAX_TOTAL_ATTEMPTS_CEILING",
    "EngineeringMission",
    "MissionLimits",
    "MissionParseResult",
    "MissionRejectionReason",
    "MissionTask",
    "TaskKind",
    "engineering_mission_request",
    "parse_mission_payload",
    "path_within_prefixes",
]
