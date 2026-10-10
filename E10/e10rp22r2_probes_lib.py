#!/usr/bin/env python3
"""E10-RP2.2-R2-DISCOVERY — shared helpers for the authorization probes.

Baseline under audit: commit 0945960427e833522789903e87a64b73c207bccd
(branch e10-rp22r1-path-aware-fail-closed).

Every helper is side-effect-contained: all filesystem work happens inside
per-probe throwaway temp directories. Nothing here touches the repository
worktrees, `main`, or historical evidence.
"""

import os
import subprocess
import sys
import tempfile
import time

SRC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from unified.contracts import AgentType, AgentTask, AgentResult  # noqa: E402
from unified.execution import ExecutionEngine, ExecutionContext  # noqa: E402
from unified.sandbox import SandboxBackend, SandboxError, create_sandbox_manager  # noqa: E402
from unified.domain_model import SandboxRequest  # noqa: E402
from unified.agent_role import BaseAgent, AgentContext  # noqa: E402
from eoe.access_gateway import AccessAdmission, AccessLedger, GrantorService  # noqa: E402
from eoe.engine_bridge import build_engine_grant_validator  # noqa: E402
from eoe.order_parser import AccessRequest, GrantKind  # noqa: E402

PY = sys.executable or "python3"


def tmpdir(prefix: str = "r2probe-") -> str:
    return tempfile.mkdtemp(prefix=prefix)


def fresh_bridge(scope_target: str) -> dict:
    """Real EOE stack (ledger + grantor + admission + engine bridge) with ONE
    live owner-approved PATH_GRANT (read_write) over ``scope_target``.

    This is the same production wiring pattern as E9-R / E10 batteries —
    no permissive substitute (order R2 §4: probes prove the REAL chain)."""
    ledger = AccessLedger()
    grantor = GrantorService(os.urandom(32))
    admission = AccessAdmission(ledger, grantor, now=time.time)
    grant = grantor.approve(grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope="read_write", target=scope_target)))
    ledger.register(grant)
    validator = build_engine_grant_validator(admission, scope_target)
    return {
        "ledger": ledger, "grantor": grantor, "admission": admission,
        "grant": grant, "grant_id": grant.grant_id, "validator": validator,
    }


def legacy_validator(grant_id, permission, path=None, depth=None):
    """Old-style permissive validator: the 2-arg form returns True for any
    (grant_id, permission). NOT marked __path_aware__. This is exactly the
    class of validator the R1 order demoted for path tools — here it is used
    to probe the NON-path (git / sandbox lifecycle) boundary."""
    return True


def make_repo(path: str) -> str:
    """Throwaway git repo with one commit on ``main``."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "probe@local"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "R2 Probe"], check=True)
    with open(os.path.join(path, "seed.txt"), "w", encoding="utf-8") as f:
        f.write("seed\n")
    subprocess.run(["git", "-C", path, "add", "-A"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", "seed"], check=True)
    return path


def make_bare(path: str) -> str:
    """Throwaway LOCAL bare repo used as a git remote (no network involved)."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", path], check=True)
    return path


def git_out(repo: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def make_context(
    engine: ExecutionEngine,
    *,
    mission_id: str = "ghost-mission",
    validator=None,
    grant_ids=None,
    workspace_root: str = ".",
    sandbox_id=None,
) -> ExecutionContext:
    """ExecutionContext identical in shape to the ones the engine builds in
    execute_task_graph (src/unified/execution.py:1744)."""
    return ExecutionContext(
        mission_id=mission_id,
        run_id="run-r2probe",
        task_id="task-r2probe",
        attempt_id="attempt-r2probe",
        agent_id="agent-r2probe",
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=list(grant_ids) if grant_ids is not None else [],
        grant_validator=validator,
        workspace_root=workspace_root,
        sandbox_id=sandbox_id,
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )


def make_agent_context(**overrides) -> AgentContext:
    """AgentContext (unified.agent_role) with sane probe defaults."""
    base = dict(
        mission_id="m-r2probe", run_id="run-r2probe", task_id="task-r2probe",
        attempt_id="attempt-r2probe", agent_id="agent-r2probe",
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=[], token_budget=1000, tokens_used=0,
        workspace_root=".", sandbox_id="sandbox-r2probe",
    )
    base.update(overrides)
    return AgentContext(**base)


def make_task(context: dict = None) -> AgentTask:
    return AgentTask(
        task_id="task-r2probe", run_id="run-r2probe", mission_id="m-r2probe",
        name="r2probe", description="r2 discovery probe task",
        agent_type=AgentType.IMPLEMENTER,
        acceptance_criteria=[], depends_on=[],
        context=context or {},
    )


def preapprove_tool_gate(engine: ExecutionEngine, mission_id: str, tool_name: str) -> None:
    """Put the mission metadata into EXACTLY the state it reaches after a
    human approves a gate for ``tool_name`` (mirrors _check_human_gate's
    approved-gate scan, src/unified/execution.py:829-835)."""
    mission = engine.missions[mission_id]
    key = f"action_gate_{tool_name}_r2preapprove"
    mission.metadata[key] = "gate-r2-preapprove"
    mission.metadata[f"{key}_decision"] = {"decision": "approve"}


def event_counts(engine: ExecutionEngine) -> dict:
    counts = {}
    for e in engine.event_bus.history:
        et = getattr(e.event_type, "value", str(e.event_type))
        counts[et] = counts.get(et, 0) + 1
    return counts


def tree_snapshot(root: str) -> set:
    """Full recursive relative-path snapshot of a directory tree."""
    snap = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel != ".":
            snap.add(rel + "/")
        for f in filenames:
            snap.add(os.path.join(rel, f) if rel != "." else f)
    return snap


class ProbeAgent(BaseAgent):
    """Minimal BaseAgent subclass exposing _validate_grant / _run_in_sandbox."""

    def __init__(self):
        super().__init__(AgentType.IMPLEMENTER)

    async def execute(self, context, task):
        return AgentResult(
            task_id=task.task_id, agent_type=self.agent_type,
            success=True, output={"probe": True},
        )


def sandbox_manager(artifacts_base_dir: str, grant_validator=None):
    """SandboxManager wired exactly like the engine's default:
    backend=WINDOWS_EXECUTOR (the ExecutionEngine default), which on Linux
    resolves to WindowsExecutorAdapter's subprocess fallback."""
    return create_sandbox_manager(
        backend=SandboxBackend.WINDOWS_EXECUTOR,
        grant_validator=grant_validator,
        artifacts_base_dir=artifacts_base_dir,
    )


def sbx_request(sandbox_id: str, command, working_dir: str, required_grant_ids=None):
    return SandboxRequest(
        sandbox_id=sandbox_id,
        image="python:3.11-slim",
        command=command,
        working_dir=working_dir,
        required_grant_ids=required_grant_ids if required_grant_ids is not None else [],
    )
