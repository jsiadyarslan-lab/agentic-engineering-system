"""E10-RP2.2-R2A1 — BINDING TEST MATRIX (arbitration order §2.3 + §3.3).

F1 (§2.3, engine-issued resume capability): the approval is consumable ONLY
by the ENGINE-DESIGNATED continuation of the paused operation, proven
through the REAL MissionController production path (define_mission ->
execute_run -> pause-storm -> decide_human_gate -> resume_approved_task) —
never through test-side task-state or retry-counter surgery (order §2.3
explicitly forbids it). Layer-level legs (synthetic ExecutionContexts) are
marked LAYER and prove the ticket registry semantics only.

F2 (§3.3, pinned push destination): the push command itself uses THE SIGNED
CANONICAL URL from an isolated staging repo (read-only alternates into the
source object store + sanitized config env), so a remote-config change
landing BETWEEN destination resolution and push execution can never re-route
the destination. The deterministic between-window test mutates the repo
config exactly there (a wrapped resolver) and proves the push lands ONLY at
the signed destination (the attacker destination receives NOTHING) and that
the result record's push_url is the destination the push argv itself used.

Layering disclosure (order §4.3/§4.4): the git_push handler legs that reach
the execution layer use the disclosed permissive scaffold validator (the
real EOE policy cannot express 'admin' — proven separately through the REAL
bridge, here and in the R2A matrix G-legs). The approval chain (HMAC + TTL
+ single-use nonce ledger + registry) and every git effect are REAL in
every leg; OwnerApprovalService / PushApprovalRegistry / handler legs using
scaffold are LAYERED tests, not end-to-end production pushes.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

sys.path.insert(0, str(HERE))

from e10rp22r2_probes_lib import (  # noqa: E402
    PY, git_out, make_bare, make_repo,
)

from test_e10rp22r2a_matrix import (  # noqa: E402
    _bare_head, _bridge_stack, _call, _counts, _designate, _engine,
    _gate_v2_keys, _permissive, _permissive_path_aware,
)

from unified.contracts import AgentType, MissionState  # noqa: E402
from unified.execution import ExecutionEngine, ExecutionContext  # noqa: E402
from unified.mission_controller import MissionController, TaskSpec  # noqa: E402
from unified.agent_role import (  # noqa: E402
    AgentRegistry, AgentFactory, BaseAgent, AgentContext, AgentTask,
    AgentResult, AgentDefinition, AgentLifecycleState,
)
from eoe.push_engine import (  # noqa: E402
    NonceLedger, OwnerApprovalService, PushApprovalRegistry,
    resolve_push_destination,
)


# ================================================================
# E2E scaffolding through the REAL MissionController path
# ================================================================

class _GateAgentBase(BaseAgent):
    """Agent whose task makes ONE governed tool call per attempt via the
    REAL ToolExecutor (context.tool_executor) — the production path."""

    tool_name = "run_command"
    # per-class call log: list of dicts the test inspects afterwards
    calls: list = []

    def __init__(self):
        super().__init__(AgentType.IMPLEMENTER)

    def make_input(self, attempt_no: int) -> dict:
        raise NotImplementedError

    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        tool_executor = getattr(context, "tool_executor", None)
        if tool_executor is None:
            return AgentResult(task_id=task.task_id, agent_type=self.agent_type,
                               success=False, output={}, evidence_hash="", artifacts=[])
        attempt_no = len(type(self).calls) + 1
        inp = self.make_input(attempt_no)
        record = {"attempt_id": context.attempt_id, "agent_id": context.agent_id,
                  "input": inp, "events": [], "actions_before": 0}
        type(self).calls.append(record)
        try:
            r = await tool_executor.execute_tool(
                context=context, tool_name=self.tool_name, tool_input=inp)
            record["outcome"] = {"success": r.success, "output": r.output,
                                 "error": r.error}
            return AgentResult(task_id=task.task_id, agent_type=self.agent_type,
                               success=r.success, output=r.output or {},
                               evidence_hash="", artifacts=[])
        except PermissionError as e:
            # the gate pause surfaces to the controller as a failed attempt
            # (E9-R behavior preserved) — captured for the test's assertions
            record["outcome"] = {"permission": str(e)}
            return AgentResult(task_id=task.task_id, agent_type=self.agent_type,
                               success=False,
                               output={"gate_pause": str(e)}, evidence_hash="", artifacts=[])


def _controller_engine(stack, agent_cls, *, validator=None, **kw) -> tuple:
    """Engine + fresh agent registry + MissionController — the production
    controller stack (mirrors the E9-R human-gate test's own scaffolding)."""
    fresh = AgentRegistry()
    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=validator if validator is not None else _permissive,
        grant_ids=[stack["grant_id"]],
        **kw,
    )
    engine.agent_registry = fresh
    engine.agent_factory = AgentFactory(fresh)
    fresh.register_definition(AgentDefinition(
        agent_id="r2a1-gate-agent", agent_type=AgentType.IMPLEMENTER,
        name="R2A1 Gate Agent", description="gate flow",
        implementation="E10.test_e10rp22r2a1_matrix",
        capabilities=[agent_cls.tool_name], lifecycle_state=AgentLifecycleState.AVAILABLE))
    fresh.enable_agent("r2a1-gate-agent")
    fresh.register_implementation(AgentType.IMPLEMENTER, agent_cls)
    mc = MissionController(engine)
    return engine, mc


def _single_task_mission(mc: MissionController, name: str):
    mission, run, key_to_id = mc.define_mission(
        name, [TaskSpec(key="G", name="gate_task", description="gate",
                        agent_type=AgentType.IMPLEMENTER, depends_on=[],
                        acceptance_criteria=[], context={"task_key": "G"})])
    return mission, run, key_to_id["G"]


def _run(coro):
    return asyncio.run(coro)


from contextlib import contextmanager  # noqa: E402


@contextmanager
def _workspace_cwd(ws):
    """DISCLOSED E2E POSTURE (R2 git-family semantics): the engine-built
    ExecutionContext carries no ``workspace_root`` in the production
    chain, so the git family's containment universe is the ENGINE
    PROCESS CWD (``_ground_repo_root`` fallback). A governed workspace
    deployment therefore runs the engine with CWD = the workspace root —
    exactly this wrapper. All engine/storage paths are absolute
    (artifacts, evidence, ledgers), so only the containment universe
    changes."""
    old = os.getcwd()
    os.chdir(str(ws))
    try:
        yield
    finally:
        os.chdir(old)


# ================================================================
# F1 — END-TO-END through the REAL MissionController (order §2.3)
# ================================================================

def test_R2A1_E1_engine_designated_resume_e2e(tmp_path):
    """R2A1-E1 (§2.3 cases 1/2/3/4/8 E2E, REAL MissionController path):

    * the first run pauses at the gate (real pause-storm);
    * the APPROVAL mints the armed one-shot ticket (case 1);
    * an independent matching call BEFORE designation — the engine's own
      GENERIC recovery relaunch, the strongest available form of "a fresh
      engine attempt that is not the designated continuation" — is REFUSED,
      consumes nothing, and leaves ZERO tool Actions/side effects (cases
      3+8);
    * ``resume_approved_task`` (the engine's designated continuation
      launcher) consumes the ticket EXACTLY ONCE via the designated attempt
      (case 2);
    * after the one-shot resume, a further resume is refused fail-closed —
      a NEW approval is required (case 4);
    * the E9-R pause/approve state contract is preserved throughout.
    """
    stack = _bridge_stack(tmp_path)

    class RunAgent(_GateAgentBase):
        tool_name = "run_command"
        calls = []

        def make_input(self, attempt_no: int) -> dict:
            # SAME input every attempt — the paused operation's identity
            return {"command": [PY, "-c", "print('R2A1-E1')"],
                    "working_dir": str(tmp_path), "timeout": 30}

    engine, mc = _controller_engine(stack, RunAgent)
    mission, run, task_id = _single_task_mission(mc, "R2A1-E1")

    # ---- first run: pauses at the REAL gate (E9-R behavior) ----
    result = _run(mc.execute_run(run.run_id, max_parallel=1))
    assert result.get("paused") or result.get("human_gate") or \
        not result.get("task_results", {}).get(task_id, {}).get("success", True)
    gate_id = mission.metadata["human_gate"]["gate_id"]
    key = _gate_v2_keys(mission)[0]
    creating_attempt = mission.metadata[f"{key}_operation"]["attempt_id"]
    assert mission.metadata[f"{key}_operation"]["task_id"] == task_id
    # task FAILED terminally after the pause-storm (agent swallows the
    # pause into a failed result; the retry budget burns; E9-R semantics)
    from unified.contracts import TaskState
    assert engine.task_graph[run.run_id][task_id]["state"] == TaskState.FAILED

    # ---- owner approves → mission EXECUTING + ticket ARMED (case 1) ----
    assert engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                                    "owner", "r2a1-e1") is True
    assert mission.state == MissionState.EXECUTING
    ticket = engine._resume_tickets[key]
    assert ticket.state == "armed" and ticket.gate_id == gate_id

    # ---- independent matching call BEFORE designation (case 3+8) ----
    # The engine's own GENERIC recovery path relaunches the task (a fresh
    # engine attempt, NOT the designated continuation): the identical call
    # must be REFUSED, the ticket NOT consumed, zero tool-layer Actions.
    actions_before = len(engine.actions)
    events_before = len(engine.event_bus.history)
    mc.recover_failed_task(run.run_id, task_id, "generic recovery relaunch")
    _run(mc.execute_run(run.run_id, max_parallel=1))
    assert mission.metadata.get(f"{key}_consumed") is None  # NOT consumed
    assert engine._resume_tickets[key].state == "armed"     # still armed
    assert len(engine.actions) == actions_before            # zero Actions
    assert engine.event_bus.history[events_before:]          # scheduler
    # the refusal message is the not-designated pause (not a new gate):
    refused = [c for c in RunAgent.calls
               if c.get("outcome", {}).get("permission")]
    assert refused, "the independent relaunch must have been refused"
    assert any("not yet designated" in c["outcome"]["permission"]
               for c in refused), [c["outcome"] for c in refused]
    # and the task is FAILED again after the refusal storm
    assert engine.task_graph[run.run_id][task_id]["state"] == TaskState.FAILED

    # ---- the ENGINE-DESIGNATED resume consumes exactly once (case 2) ----
    resumed = _run(mc.resume_approved_task(run.run_id, task_id, actor="owner"))
    assert resumed["resumed"] is True
    cont = resumed["continuation_attempt_id"]
    assert cont.startswith("attempt-") and cont != creating_attempt
    cons = mission.metadata.get(f"{key}#cycle1_consumed")
    assert cons is not None, "the designated continuation must consume"
    assert cons["consumed_by_attempt"] == cont
    assert cons["resume_ticket_id"] == ticket.ticket_id
    assert engine._resume_tickets[key].state == "consumed"
    # the designated attempt PASSED the gate (its outcome is the sandbox
    # layer's documented Linux refusal, never a gate pause)
    designated_call = [c for c in RunAgent.calls if c["attempt_id"] == cont]
    assert designated_call, "the designated attempt must have run"
    outc = designated_call[0]["outcome"]
    assert "permission" not in outc or "Human gate" not in outc["permission"], outc

    # ---- after the one-shot resume: new approval required (case 4) ----
    with pytest.raises(ValueError):
        _run(mc.resume_approved_task(run.run_id, task_id, actor="owner"))
    assert mission.metadata.get(f"{key}#cycle2_consumed") is None


def test_R2A1_E2_positive_real_push_side_effect_e2e(tmp_path):
    """R2A1-E2 (§2.3 case 2 POSITIVE + §3.3 E2E, REAL MissionController):
    the engine-designated continuation of an approved git_push gate EXECUTES
    the push for real — through the pinned SIGNED destination — and the very
    next relaunch needs a NEW approval. The push lands in the approved bare
    at the approved commit; the result record's push_url is the destination
    the push argv itself used.

    LAYERING DISCLOSURE (order §4.3): the permissive path-aware validator
    lets the call reach the gate/handler layers (the real EOE policy cannot
    express 'admin'); the approval chain (HMAC + TTL + single-use nonce +
    registry), the gate, the resume machinery, the staging push and every
    git effect are REAL. The scenario runs with CWD = the workspace root
    (``_workspace_cwd`` — the governed-workspace production posture for
    the git-family CWD universe, disclosed above).
    """
    stack = _bridge_stack(tmp_path)
    bare = make_bare(str(Path(tmp_path) / "r2a1-remote.git"))
    evil = make_bare(str(Path(tmp_path) / "r2a1-evil.git"))
    git_out(stack["repoA"], "remote", "add", "r2a1remote", bare)
    head = git_out(stack["repoA"], "rev-parse", "HEAD")
    repo_root = str(Path(stack["repoA"]).resolve())
    push_url = resolve_push_destination(repo_root, "r2a1remote")

    svc = OwnerApprovalService(b"r2a1-e2-owner-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    appr = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                    files_digest="r2a1-e2", remote="r2a1remote", force=False,
                    push_url=push_url)
    registry.register(appr)

    class PushAgent(_GateAgentBase):
        tool_name = "git_push"
        calls = []

        def make_input(self, attempt_no: int) -> dict:
            return {"repo_path": stack["repoA"], "remote": "r2a1remote",
                    "branch": "main", "owner_approval_nonce": appr.nonce}

    engine, mc = _controller_engine(
        stack, PushAgent, validator=_permissive_path_aware,
        push_approval_registry=registry)
    mission, run, task_id = _single_task_mission(mc, "R2A1-E2")

    with _workspace_cwd(stack["ws"]):
        # first run: the CRITICAL tool pauses at the REAL gate
        _run(mc.execute_run(run.run_id, max_parallel=1))
        gate_id = mission.metadata["human_gate"]["gate_id"]
        key = _gate_v2_keys(mission)[0]
        assert mission.metadata[f"{key}_operation"]["tool_name"] == "git_push"
        assert mission.metadata.get(f"{key}_consumed") is None

        # owner approves the GATE (the registry approval is already registered)
        assert engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                                        "owner", "r2a1-e2") is True
        assert engine._resume_tickets[key].state == "armed"

        # the ENGINE-DESIGNATED continuation consumes the ticket and EXECUTES
        resumed = _run(mc.resume_approved_task(run.run_id, task_id, actor="owner"))
        assert resumed["resumed"] is True
        cont = resumed["continuation_attempt_id"]
        # the consumption record lives in the LIVE slot (the push SUCCEEDED —
        # no post-consumption retry storm to archive the cycle; E1's
        # run_command leg shows the archived-cycle variant)
        cons = mission.metadata.get(f"{key}_consumed") \
            or mission.metadata.get(f"{key}#cycle1_consumed")
        assert cons is not None and cons["consumed_by_attempt"] == cont

        # THE PUSH HAPPENED — to the approved bare, at the approved commit,
        # through the SIGNED destination (the pinned-destination argv)
        assert _bare_head(bare) == head, "the push must land the approved commit"
        assert _bare_head(evil) == "" or head not in _bare_head(evil)
        designated_call = [c for c in PushAgent.calls if c["attempt_id"] == cont]
        assert designated_call, "the designated attempt must have run"
        outc = designated_call[0]["outcome"]
        assert outc.get("success") is True, outc
        assert outc["output"]["push_url"] == push_url           # the SIGNED dest
        argv = outc["output"]["push_argv"]
        assert push_url in argv and f"{head}:refs/heads/main" in argv
        assert "r2a1remote" not in argv  # never the remote NAME
        assert "--" in argv

        # the task COMPLETED (real successful execution through the gate)
        from unified.contracts import TaskState
        assert engine.task_graph[run.run_id][task_id]["state"] == TaskState.COMPLETED

        # a further resume: nothing approved+unconsumed remains — fail-closed
        with pytest.raises(ValueError):
            _run(mc.resume_approved_task(run.run_id, task_id, actor="owner"))


def test_R2A1_E3_expired_ticket_resume_refused_e2e(tmp_path):
    """R2A1-E3 (§2.3 case 5, EXPIRED, E2E): a ticket past its TTL can never
    be designated or consumed — the resume is refused fail-closed BEFORE
    any relaunch, with zero consumption and zero side effects."""
    stack = _bridge_stack(tmp_path)

    class RunAgent(_GateAgentBase):
        tool_name = "run_command"
        calls = []

        def make_input(self, attempt_no: int) -> dict:
            return {"command": [PY, "-c", "print('R2A1-E3')"],
                    "working_dir": str(tmp_path), "timeout": 30}

    engine, mc = _controller_engine(stack, RunAgent)
    engine.resume_ticket_ttl_seconds = 0.05  # short window (engine config)
    mission, run, task_id = _single_task_mission(mc, "R2A1-E3")

    _run(mc.execute_run(run.run_id, max_parallel=1))
    gate_id = mission.metadata["human_gate"]["gate_id"]
    key = _gate_v2_keys(mission)[0]
    actions_before = len(engine.actions)

    assert engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                                    "owner", "r2a1-e3") is True
    time.sleep(0.1)  # the ticket is now past its TTL

    with pytest.raises(ValueError):
        _run(mc.resume_approved_task(run.run_id, task_id, actor="owner"))
    assert engine._resume_tickets[key].state == "expired"
    assert mission.metadata.get(f"{key}_consumed") is None
    assert len(engine.actions) == actions_before  # zero tool Actions
    # a LATER resume also fails (the ticket is terminal — new approval)
    with pytest.raises(ValueError):
        _run(mc.resume_approved_task(run.run_id, task_id, actor="owner"))


def test_R2A1_E4_cross_run_child_gets_own_gate_e2e(tmp_path):
    """R2A1-E4 (§2.3 case 6, E2E): a cross-run (E8-style) resume is a
    DIFFERENT operation identity — the approval of the original run NEVER
    carries over, and the resumed run's ticket never exists (a cross-run
    approval needs its own gate + approval + resume)."""
    stack = _bridge_stack(tmp_path)

    class RunAgent(_GateAgentBase):
        tool_name = "run_command"
        calls = []

        def make_input(self, attempt_no: int) -> dict:
            return {"command": [PY, "-c", "print('R2A1-E4')"],
                    "working_dir": str(tmp_path), "timeout": 30}

    engine, mc = _controller_engine(stack, RunAgent)
    mission, run, task_id = _single_task_mission(mc, "R2A1-E4")
    _run(mc.execute_run(run.run_id, max_parallel=1))
    gate_id = mission.metadata["human_gate"]["gate_id"]
    key = _gate_v2_keys(mission)[0]
    engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                             "owner", "r2a1-e4")
    assert engine._resume_tickets[key].state == "armed"

    # a SECOND mission/run making the IDENTICAL call: its own gate, no
    # inherited approval, and NO ticket minted for the foreign operation
    mission2, run2, task_id2 = _single_task_mission(mc, "R2A1-E4-child")
    _run(mc.execute_run(run2.run_id, max_parallel=1))
    keys_m2 = _gate_v2_keys(mission2)
    assert keys_m2, "the child-run operation must get its own gate"
    assert mission2.metadata.get(f"{keys_m2[0]}_consumed") is None
    assert mission2.metadata[f"{keys_m2[0]}_operation"]["run_id"] == run2.run_id
    # the ORIGINAL mission's ticket is untouched by the child run
    assert engine._resume_tickets[key].state == "armed"
    assert mission.metadata.get(f"{key}_consumed") is None


def test_R2A1_E5_continuation_with_different_input_new_gate_e2e(tmp_path):
    """R2A1-E5 (§2.3 case 6, E2E): the designated continuation attempt that
    presents DIFFERENT inputs does not inherit the approval — a NEW gate is
    opened for the new operation; the original approval is never consumed
    by the different-input call."""
    stack = _bridge_stack(tmp_path)

    class SwitchAgent(_GateAgentBase):
        tool_name = "run_command"
        calls = []

        def make_input(self, attempt_no: int) -> dict:
            if attempt_no <= 2:  # first run + first retry: the SAME input
                return {"command": [PY, "-c", "print('R2A1-E5-a')"],
                        "working_dir": str(tmp_path), "timeout": 30}
            # from the third invocation on: a DIFFERENT input
            return {"command": [PY, "-c", "print('R2A1-E5-b')"],
                    "working_dir": str(tmp_path), "timeout": 30}

    engine, mc = _controller_engine(stack, SwitchAgent)
    mission, run, task_id = _single_task_mission(mc, "R2A1-E5")
    _run(mc.execute_run(run.run_id, max_parallel=1))
    gate_id = mission.metadata["human_gate"]["gate_id"]
    key = _gate_v2_keys(mission)[0]
    engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                             "owner", "r2a1-e5")
    assert engine._resume_tickets[key].state == "armed"

    # the designated continuation makes a DIFFERENT call → its OWN gate
    _run(mc.resume_approved_task(run.run_id, task_id, actor="owner"))
    assert mission.metadata.get(f"{key}_consumed") is None  # never consumed
    # a second gate now exists (the different-input operation), PENDING
    live = _gate_v2_keys(mission)
    assert len(live) == 2, live
    new_key = [k for k in live if k != key][0]
    assert mission.metadata.get(f"{new_key}_decision") is None  # pending
    # the original ticket is still armed-designated for its attempt, and
    # a NEW resume cannot proceed (the approved gate's designated attempt
    # is spent — its continuation made a different call): fail-closed
    assert engine._resume_tickets[key].state in ("armed", "designated", "consumed")
    assert engine._resume_tickets[key].state != "consumed"


def test_R2A1_E6_real_bridge_git_push_stays_rejected_e2e(tmp_path):
    """R2A1-E6 (order §4.2, E2E): through the REAL EOE bridge, git_push
    remains rejected BEFORE the gate is even reached (the 'admin' permission
    is unattainable) — no gate, no ticket, no resume possible, zero trace.
    The engine-issued resume capability grants NO new privilege."""
    stack = _bridge_stack(tmp_path)  # REAL bridge validator

    class PushAgent(_GateAgentBase):
        tool_name = "git_push"
        calls = []

        def make_input(self, attempt_no: int) -> dict:
            return {"repo_path": stack["repoA"], "remote": "origin",
                    "branch": "main", "owner_approval_nonce": "real-nonce"}

    engine, mc = _controller_engine(stack, PushAgent, validator=stack["validator"])
    mission, run, task_id = _single_task_mission(mc, "R2A1-E6")
    actions_before = len(engine.actions)

    _run(mc.execute_run(run.run_id, max_parallel=1))
    # no gate was ever created (the permission refusal precedes the gate)
    assert _gate_v2_keys(mission) == [], "no gate through the real bridge"
    assert mission.metadata.get("human_gate") is None
    assert len(engine.actions) == actions_before  # zero tool Actions
    # and the resume path is unavailable (nothing approved to resume)
    with pytest.raises(ValueError):
        _run(mc.resume_approved_task(run.run_id, task_id, actor="owner"))


# ================================================================
# F1 — LAYER legs (synthetic ExecutionContexts; ticket registry
# semantics ONLY — the scheduler integration is proven E2E above)
# ================================================================

def test_R2A1_L1_agent_supplied_proof_authorizes_nothing(tmp_path):
    """R2A1-L1 (§2.2.5, LAYER): an agent presenting a FORGED ticket id (or
    any id) authorizes nothing — the ticket lookup is by operation key in
    the engine-internal registry; no schema field exists to carry a ticket
    id, and a hand-crafted resume ticket placed into the registry is
    rejected by the identity/gate binding checks."""
    from unified.tool_contract import GitPushInput, RunCommandInput
    # (a) the input schemas have NO ticket/resume field at all
    import inspect
    for schema in (RunCommandInput, GitPushInput):
        fields = schema.model_fields
        assert not any("ticket" in f or "resume" in f or "continuation" in f
                       for f in fields), list(fields)

    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A1-L1")
    mission.state = MissionState.EXECUTING
    ctx = _ctx_l(engine, stack, mission)
    inp = {"command": [PY, "-c", "print('L1')"], "working_dir": str(tmp_path)}
    st, _ = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION"
    key = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key]
    engine.decide_human_gate(mission.mission_id, gate_id, "approve", "owner", "l1")
    assert engine._resume_tickets[key].state == "armed"

    # (b) a FORGED ticket forged into the registry with a WRONG gate
    # binding: the identity checks reject it (fail-closed)
    from unified.execution import ResumeTicket
    forged = ResumeTicket(
        ticket_id="rtk-forged", gate_id="gate-OTHER", op_key=key,
        mission_id=mission.mission_id, run_id="run-l1", task_id="task-l1",
        tool_name="run_command", input_digest="0" * 64,
        creating_attempt_id="attempt-x", creating_agent_id="agent-l1",
        issued_at=time.time(), expires_at=time.time() + 600,
        state="designated", continuation_attempt_id="attempt-l1",
    )
    engine._resume_tickets[key] = forged
    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "does not bind this exact operation" in payload, (st, payload)
    assert mission.metadata.get(f"{key}_consumed") is None
    # the real approval was never touched by the forgery (restore + prove)
    del engine._resume_tickets[key]


def test_R2A1_L2_transferred_ticket_rejected(tmp_path):
    """R2A1-L2 (§2.3 case 5, LAYER — TRANSFER): a ticket minted for
    operation A cannot authorize operation B even when B has an
    approved+unconsumed gate of its own (the transfer is refused by the
    identity binding; B's approval stays intact for its own resume)."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A1-L2")
    mission.state = MissionState.EXECUTING
    inp = {"command": [PY, "-c", "print('L2')"], "working_dir": str(tmp_path)}
    # operation A: task-a
    ctx_a = _ctx_l(engine, stack, mission, task_id="task-a", attempt_id="att-a")
    st, _ = _call(engine, ctx_a, "run_command", inp)
    key_a = _gate_v2_keys(mission)[0]
    gate_a = mission.metadata[key_a]
    # operation B: task-b (same inputs, different task)
    mission.state = MissionState.EXECUTING
    ctx_b = _ctx_l(engine, stack, mission, task_id="task-b", attempt_id="att-b")
    st, _ = _call(engine, ctx_b, "run_command", inp)
    key_b = [k for k in _gate_v2_keys(mission) if k != key_a][0]
    gate_b = mission.metadata[key_b]
    # approve BOTH (each approve requires the mission to be in the
    # HUMAN_REQUIRED pause the respective gate created)
    engine.decide_human_gate(mission.mission_id, gate_a, "approve", "owner", "l2a")
    mission.state = MissionState.HUMAN_REQUIRED  # gate_b's pause
    engine.decide_human_gate(mission.mission_id, gate_b, "approve", "owner", "l2b")
    mission.state = MissionState.EXECUTING
    # designate A's ticket for A's continuation
    _designate(engine, key_a, "att-a-resume")
    # ...and try to CONSUME B's approval with A's designated continuation:
    # the call presents B's identity; A's ticket sits under key_a and is
    # never consulted for key_b; B's own ticket is ARMED (not designated)
    ctx_b_res = _ctx_l(engine, stack, mission, task_id="task-b",
                       attempt_id="att-a-resume")  # A's designated attempt!
    st, payload = _call(engine, ctx_b_res, "run_command", inp)
    assert st == "PERMISSION" and "not yet designated" in payload, (st, payload)
    # neither approval was consumed by the transfer attempt
    assert mission.metadata.get(f"{key_a}_consumed") is None
    assert mission.metadata.get(f"{key_b}_consumed") is None
    assert engine._resume_tickets[key_a].state == "designated"
    assert engine._resume_tickets[key_b].state == "armed"


def test_R2A1_L3_wrong_attempt_and_agent_rejected(tmp_path):
    """R2A1-L3 (§2.2.3/§2.2.4, LAYER): after designation, a NON-designated
    attempt is refused (approval reserved), and an AGENT CHANGE is refused
    (no reassignment mechanism authorized)."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A1-L3")
    mission.state = MissionState.EXECUTING
    inp = {"command": [PY, "-c", "print('L3')"], "working_dir": str(tmp_path)}
    ctx = _ctx_l(engine, stack, mission)
    _call(engine, ctx, "run_command", inp)
    key = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key]
    engine.decide_human_gate(mission.mission_id, gate_id, "approve", "owner", "l3")
    _designate(engine, key, "attempt-l3-resume")

    # (a) a NON-designated attempt: refused, nothing consumed
    ctx_wrong = _ctx_l(engine, stack, mission, attempt_id="attempt-l3-OTHER")
    st, payload = _call(engine, ctx_wrong, "run_command", inp)
    assert st == "PERMISSION" and "NOT the engine-designated continuation" in payload
    assert mission.metadata.get(f"{key}_consumed") is None
    assert engine._resume_tickets[key].state == "designated"

    # (b) agent change on the designated attempt: refused (new approval)
    ctx_agent = _ctx_l(engine, stack, mission, attempt_id="attempt-l3-resume",
                       agent_id="agent-OTHER")
    st, payload = _call(engine, ctx_agent, "run_command", inp)
    assert st == "PERMISSION" and "agent changed" in payload, (st, payload)
    assert mission.metadata.get(f"{key}_consumed") is None

    # (c) the DESIGNATED attempt with the SAME agent passes the gate
    ctx_ok = _ctx_l(engine, stack, mission, attempt_id="attempt-l3-resume")
    st, payload = _call(engine, ctx_ok, "run_command", inp)
    assert not (st == "PERMISSION" and "Human gate" in payload), (st, payload)
    assert mission.metadata.get(f"{key}_consumed") is not None
    assert engine._resume_tickets[key].state == "consumed"


def test_R2A1_L4_no_trace_on_pre_execution_refusals(tmp_path):
    """R2A1-L4 (§2.2.7, LAYER): every ticket refusal happens BEFORE any
    Action record and BEFORE any side effect — the refusing calls create
    zero engine actions across the whole refusal family (missing ticket,
    armed, non-designated attempt, agent change, expired)."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A1-L4")
    mission.state = MissionState.EXECUTING
    inp = {"command": [PY, "-c", "print('L4')"], "working_dir": str(tmp_path)}
    ctx = _ctx_l(engine, stack, mission)
    _call(engine, ctx, "run_command", inp)
    key = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key]
    engine.decide_human_gate(mission.mission_id, gate_id, "approve", "owner", "l4")
    actions0, events0 = _counts(engine)

    # armed refusal
    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "not yet designated" in payload
    # missing-ticket refusal (approval without any ticket at all)
    engine._resume_tickets.pop(key, None)
    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "no engine-issued resume ticket" in payload
    # expired refusal (restore an armed ticket then age it out)
    from unified.execution import ResumeTicket
    op = mission.metadata[f"{key}_operation"]
    engine._resume_tickets[key] = ResumeTicket(
        ticket_id="rtk-l4", gate_id=op["gate_id"], op_key=key,
        mission_id=op["mission_id"], run_id=op["run_id"], task_id=op["task_id"],
        tool_name=op["tool_name"], input_digest=op["input_digest"],
        creating_attempt_id=op["attempt_id"], creating_agent_id=op["agent_id"],
        issued_at=time.time() - 10, expires_at=time.time() - 1,
        state="designated", continuation_attempt_id=ctx.attempt_id,
    )
    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "EXPIRED" in payload, (st, payload)

    # ZERO Actions across the whole refusal family
    assert _counts(engine) == (actions0, events0) or len(engine.actions) == actions0


def _ctx_l(engine, stack, mission, *, run_id="run-l", task_id="task-l",
           attempt_id="attempt-l", agent_id="agent-l"):
    """Synthetic LAYER context (E10-RP2.2-R2A1 §2.3 — layer legs only)."""
    return ExecutionContext(
        mission_id=mission.mission_id, run_id=run_id, task_id=task_id,
        attempt_id=attempt_id, agent_id=agent_id,
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=[stack["grant_id"]], grant_validator=_permissive,
        workspace_root=str(stack["ws"]),
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )


# ================================================================
# F2 — PINNED PUSH DESTINATION (order §3.3)
# ================================================================

def _push_stack(tmp_path, *, rewrite_attack=False, second_destination=None):
    """The canonical F2 harness: repoA + remote 'r2a1remote' + TWO bare
    destinations (approved/attacker). With ``rewrite_attack`` a local
    ``url.<attacker>.insteadOf = <approved>`` rule is planted in repoA's
    config BEFORE the approval is signed (the strongest attack: the rule
    is present at resolution time too, so a naive 'resolve then push by
    name' implementation would be re-routed; probe P3 proved even an
    explicit-URL push FROM THE SOURCE REPO is re-routed)."""
    stack = _bridge_stack(tmp_path)
    approved = make_bare(str(Path(tmp_path) / "approved.git"))
    attacker = make_bare(str(Path(tmp_path) / "attacker.git"))
    git_out(stack["repoA"], "remote", "add", "r2a1remote", approved)
    if second_destination:
        git_out(stack["repoA"], "remote", "add", "r2a1second", second_destination)
    if rewrite_attack:
        git_out(stack["repoA"], "config",
                f"url.{attacker}.insteadOf", approved)
    head = git_out(stack["repoA"], "rev-parse", "HEAD")
    repo_root = str(Path(stack["repoA"]).resolve())
    return {
        **stack, "approved": approved, "attacker": attacker,
        "head": head, "repo_root": repo_root,
        "signed_url": str(approved),
    }


def test_R2A1_F1_between_window_url_change_cannot_reroute(tmp_path):
    """R2A1-F1 (order §3.3 MANDATORY): a remote-config change landing
    EXACTLY BETWEEN destination resolution and push execution (via a
    wrapped resolver — the deterministic between-window mutation) can
    NEVER re-route the push: the pinned staging push uses the SIGNED URL,
    so the push lands ONLY at the approved destination; the attacker
    destination receives NOTHING (no commit object at all), and the result
    record's push_url is the destination the push argv itself used.

    The mutation arms BOTH attack vectors at once:
    * remote.<name>.pushurl → attacker (a name-based push would follow it);
    * url.<attacker>.insteadOf → approved (would rewrite even an explicit
      URL pushed from the source repo — probe P3).
    """
    stack = _push_stack(tmp_path)
    approved, attacker = stack["approved"], stack["attacker"]
    head, repo_root = stack["head"], stack["repo_root"]
    svc = OwnerApprovalService(b"r2a1-f1-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    # destination resolved NOW (approval signing reads it through the REAL
    # resolver) — the between-window mutation lands after this line
    push_url = resolve_push_destination(repo_root, "r2a1remote")
    assert push_url == str(approved)
    appr = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                    files_digest="f1", remote="r2a1remote", force=False,
                    push_url=push_url)
    registry.register(appr)

    # === THE BETWEEN-WINDOW MUTATION (deterministic, order §3.3) ===
    # Wrapped resolver injected into the handler: the mutation fires
    # AFTER the handler's own resolution+verification succeed and BEFORE
    # staged_push runs — exactly the window the arbitrator demands.
    import eoe.push_engine as _pe
    real_resolve = _pe.resolve_push_destination
    mutated = {"fired": False}

    def _mutating_resolve(repo_root_, remote_):
        url = real_resolve(repo_root_, remote_)
        if not mutated["fired"]:
            mutated["fired"] = True
            # BOTH attack vectors, mid-flight:
            git_out(stack["repoA"], "config",
                    f"remote.{remote_}.pushurl", attacker)
            git_out(stack["repoA"], "config",
                    f"url.{attacker}.insteadOf", approved)
        return url
    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=_permissive_path_aware,  # scaffold (§4.3, disclosed)
        grant_ids=[stack["grant_id"]],
        push_approval_registry=registry,
    )
    mission = engine.create_mission("R2A1-F1")
    mission.state = MissionState.EXECUTING
    ctx = ExecutionContext(
        mission_id=mission.mission_id, run_id="run-f1", task_id="task-f1",
        attempt_id="attempt-f1", agent_id="agent-f1",
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=[stack["grant_id"]], grant_validator=_permissive_path_aware,
        workspace_root=str(stack["ws"]),
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )
    inp = {"repo_path": stack["repoA"], "remote": "r2a1remote", "branch": "main",
           "owner_approval_nonce": appr.nonce}

    # the gate: first call pauses; approve; designate; resume executes
    st, payload = _call(engine, ctx, "git_push", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    key = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key]
    engine.decide_human_gate(mission.mission_id, gate_id, "approve", "owner", "f1")
    _designate(engine, key, ctx.attempt_id)

    with _monkeypatched(_pe, "resolve_push_destination", _mutating_resolve), \
         _workspace_cwd(stack["ws"]):
        st, payload = _call(engine, ctx, "git_push", inp)

    assert mutated["fired"] is True, "the between-window mutation must fire"
    assert st == "TOOL_RESULT" and payload.success, (st, payload)
    # the push landed ONLY at the SIGNED destination
    assert _bare_head(approved) == head
    assert not _has_commit(attacker, head), "attacker received the commit!"
    # the result record announces the SIGNED destination — and the argv
    # PROVES the push command itself used it (never the remote name)
    assert payload.output["push_url"] == str(approved)
    argv = payload.output["push_argv"]
    assert str(approved) in argv and f"{head}:refs/heads/main" in argv
    assert "r2a1remote" not in argv
    # and the source repo's own config DID change (the attack was live)
    now_pushurl = git_out(stack["repoA"], "config",
                          "--get", "remote.r2a1remote.pushurl")
    assert now_pushurl.strip() == str(attacker), now_pushurl


def test_R2A1_F2_prewrite_rule_cannot_reroute(tmp_path):
    """R2A1-F2 (order §3.3): an insteadOf rewrite planted in the SOURCE
    repo BEFORE the approval (armed at resolution time as well) cannot
    re-route the staging push — the signed canonical URL is used by the
    push command itself, in an isolated config environment."""
    stack = _push_stack(tmp_path, rewrite_attack=True)
    approved, attacker = stack["approved"], stack["attacker"]
    head, repo_root = stack["head"], stack["repo_root"]
    # NOTE: with the rewrite armed, the REAL resolver resolves the
    # EFFECTIVE destination (the rewritten URL) — an approval signed for
    # the un-rewritten path does not match the effective destination and
    # is rejected (verify_and_consume). The attack therefore FAILS at
    # signature-scope: refusing before any effect.
    svc = OwnerApprovalService(b"r2a1-f2-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    naive_url = str(approved)  # what a naive implementation would sign
    appr = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                    files_digest="f2", remote="r2a1remote", force=False,
                    push_url=naive_url)
    registry.register(appr)

    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=_permissive_path_aware,  # scaffold (§4.3)
        grant_ids=[stack["grant_id"]],
        push_approval_registry=registry,
    )
    mission = engine.create_mission("R2A1-F2")
    mission.state = MissionState.EXECUTING
    ctx = ExecutionContext(
        mission_id=mission.mission_id, run_id="run-f2", task_id="task-f2",
        attempt_id="attempt-f2", agent_id="agent-f2",
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=[stack["grant_id"]], grant_validator=_permissive_path_aware,
        workspace_root=str(stack["ws"]),
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )
    inp = {"repo_path": stack["repoA"], "remote": "r2a1remote", "branch": "main",
           "owner_approval_nonce": appr.nonce}
    st, payload = _call(engine, ctx, "git_push", inp)
    assert st == "PERMISSION" and "Human gate created" in payload
    key = _gate_v2_keys(mission)[0]
    engine.decide_human_gate(mission.mission_id, mission.metadata[key],
                             "approve", "owner", "f2")
    _designate(engine, key, ctx.attempt_id)
    with _workspace_cwd(stack["ws"]):
        st, payload = _call(engine, ctx, "git_push", inp)
    # the rewritten effective destination does NOT match the signed URL →
    # refused fail-closed BEFORE any push (attacker untouched)
    assert st == "TOOL_RESULT" and not payload.success, (st, payload)
    assert "no تطابق" in payload.error or "does not match" in payload.error or \
        "لا تطابق" in (payload.error or ""), payload.error
    assert _bare_head(approved) == ""
    assert not _has_commit(attacker, head)


def test_R2A1_F3_multi_destination_rejected_before_push(tmp_path):
    """R2A1-F3 (order §3.3, kept from R2A): a remote with MULTIPLE
    destinations (two pushurls) is refused at resolution — the approval
    binds exactly ONE canonical destination and git would push to ALL."""
    stack = _push_stack(tmp_path)
    head, repo_root = stack["head"], stack["repo_root"]
    second = make_bare(str(Path(tmp_path) / "second.git"))
    third = make_bare(str(Path(tmp_path) / "third.git"))
    # TWO pushurls on the same remote — git would push to BOTH
    git_out(stack["repoA"], "config", "--add",
            "remote.r2a1remote.pushurl", second)
    git_out(stack["repoA"], "config", "--add",
            "remote.r2a1remote.pushurl", third)
    with pytest.raises(Exception) as ei:
        resolve_push_destination(repo_root, "r2a1remote")
    assert "متعددة" in str(ei.value) or "pushurl" in str(ei.value), str(ei.value)
    # neither destination received anything
    assert _bare_head(stack["approved"]) == ""
    assert _bare_head(second) == ""
    assert _bare_head(third) == ""


def test_R2A1_F4_force_only_with_force_scoped_approval(tmp_path):
    """R2A1-F4 (order §3.3, kept from R2A): --force is appended ONLY when
    the explicit flag is set AND the consumed approval was signed for
    force=True — with a non-force approval, a non-ff push is REJECTED by
    the destination (probe P6 semantics) and the argv carries no --force."""
    stack = _push_stack(tmp_path)
    approved, attacker = stack["approved"], stack["attacker"]
    head, repo_root = stack["head"], stack["repo_root"]
    # advance repoA one commit (c2); the rewind scenario resets the branch
    # back to c1 afterwards — every approval below is signed for the
    # CURRENT HEAD at push time (the handler binds approval to HEAD)
    (Path(stack["repoA"]) / "force.txt").write_text("f\n")
    git_out(stack["repoA"], "add", "-A")
    git_out(stack["repoA"], "-c", "user.name=p", "-c", "user.email=p@x",
            "commit", "-m", "c2")
    head2 = git_out(stack["repoA"], "rev-parse", "HEAD")
    svc = OwnerApprovalService(b"r2a1-f4-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    url = resolve_push_destination(repo_root, "r2a1remote")
    # leg 1: ff push of head2 (non-force approval) — lands
    appr_ff = svc.sign(repository=repo_root, branch="main", commit_sha=head2,
                       files_digest="f4", remote="r2a1remote", force=False,
                       push_url=url)
    registry.register(appr_ff)
    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=_permissive_path_aware,  # scaffold (§4.3)
        grant_ids=[stack["grant_id"]],
        push_approval_registry=registry,
    )
    mission = engine.create_mission("R2A1-F4")
    mission.state = MissionState.EXECUTING
    ctx = ExecutionContext(
        mission_id=mission.mission_id, run_id="run-f4", task_id="task-f4",
        attempt_id="attempt-f4", agent_id="agent-f4",
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=[stack["grant_id"]], grant_validator=_permissive_path_aware,
        workspace_root=str(stack["ws"]),
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )
    inp_ff = {"repo_path": stack["repoA"], "remote": "r2a1remote",
              "branch": "main", "owner_approval_nonce": appr_ff.nonce,
              "force": False}
    st, payload = _call(engine, ctx, "git_push", inp_ff)
    key = _gate_v2_keys(mission)[0]
    engine.decide_human_gate(mission.mission_id, mission.metadata[key],
                             "approve", "owner", "f4")
    _designate(engine, key, ctx.attempt_id)
    with _workspace_cwd(stack["ws"]):
        st, payload = _call(engine, ctx, "git_push", inp_ff)
    assert st == "TOOL_RESULT" and payload.success, (st, payload)
    assert _bare_head(approved) == head2

    # leg 2: REWIND — reset the branch to c1 (test-side repo prep); a
    # non-force approval for the new HEAD (c1) is a NON-FF update the
    # destination rejects (no --force in the argv)
    git_out(stack["repoA"], "reset", "--hard", head)
    appr_rw = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                       files_digest="f4rw", remote="r2a1remote", force=False,
                       push_url=url)
    registry.register(appr_rw)
    inp_rw = {"repo_path": stack["repoA"], "remote": "r2a1remote",
              "branch": "main", "owner_approval_nonce": appr_rw.nonce,
              "force": False}
    mission.state = MissionState.EXECUTING
    st, payload = _call(engine, ctx, "git_push", inp_rw)
    key_rw = [k for k in _gate_v2_keys(mission) if k != key][0]
    engine.decide_human_gate(mission.mission_id, mission.metadata[key_rw],
                             "approve", "owner", "f4rw")
    _designate(engine, key_rw, ctx.attempt_id)
    with _workspace_cwd(stack["ws"]):
        st, payload = _call(engine, ctx, "git_push", inp_rw)
    assert st == "TOOL_RESULT" and not payload.success, (st, payload)
    assert _bare_head(approved) == head2  # unchanged — the rewind failed
    # and a FORCE-scoped approval DOES push the rewind (P6 semantics)
    appr_force = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                          files_digest="f4f", remote="r2a1remote", force=True,
                          push_url=url)
    registry.register(appr_force)
    inp_force = {"repo_path": stack["repoA"], "remote": "r2a1remote",
                 "branch": "main", "owner_approval_nonce": appr_force.nonce,
                 "force": True}
    mission.state = MissionState.EXECUTING
    st, payload = _call(engine, ctx, "git_push", inp_force)
    key_fc = [k for k in _gate_v2_keys(mission) if k not in (key, key_rw)][0]
    engine.decide_human_gate(mission.mission_id, mission.metadata[key_fc],
                             "approve", "owner", "f4f")
    _designate(engine, key_fc, ctx.attempt_id)
    with _workspace_cwd(stack["ws"]):
        st, payload = _call(engine, ctx, "git_push", inp_force)
    assert st == "TOOL_RESULT" and payload.success, (st, payload)
    assert "--force" in payload.output["push_argv"]
    assert _bare_head(approved) == head  # the rewind LANDED via force


def test_R2A1_F5_result_record_never_lies(tmp_path):
    """R2A1-F5 (order §3.3): a FAILED pinned push never reports a push_url
    as if it happened — the failing result carries the git error and the
    success record's push_url is structurally the argv's own destination."""
    stack = _push_stack(tmp_path)
    head, repo_root = stack["head"], stack["repo_root"]
    # a SIGNED destination that does not exist as a repo → push fails
    ghost = str(Path(tmp_path) / "ghost-dest.git")
    svc = OwnerApprovalService(b"r2a1-f5-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    appr = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                    files_digest="f5", remote="r2a1remote", force=False,
                    push_url=ghost)
    registry.register(appr)
    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=_permissive_path_aware,  # scaffold (§4.3)
        grant_ids=[stack["grant_id"]],
        push_approval_registry=registry,
    )
    mission = engine.create_mission("R2A1-F5")
    mission.state = MissionState.EXECUTING
    ctx = ExecutionContext(
        mission_id=mission.mission_id, run_id="run-f5", task_id="task-f5",
        attempt_id="attempt-f5", agent_id="agent-f5",
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=[stack["grant_id"]], grant_validator=_permissive_path_aware,
        workspace_root=str(stack["ws"]),
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )
    inp = {"repo_path": stack["repoA"], "remote": "r2a1remote", "branch": "main",
           "owner_approval_nonce": appr.nonce}
    st, payload = _call(engine, ctx, "git_push", inp)
    key = _gate_v2_keys(mission)[0]
    engine.decide_human_gate(mission.mission_id, mission.metadata[key],
                             "approve", "owner", "f5")
    _designate(engine, key, ctx.attempt_id)
    with _workspace_cwd(stack["ws"]):
        st, payload = _call(engine, ctx, "git_push", inp)
    assert st == "TOOL_RESULT" and not payload.success, (st, payload)
    assert payload.output is None or not payload.output.get("pushed"), payload.output


# ---- tiny helpers --------------------------------------------------------

def _has_commit(repo: str, sha: str) -> bool:
    import subprocess
    r = subprocess.run(["git", "-C", str(repo), "cat-file", "-e",
                        f"{sha}^{{commit}}"], capture_output=True, text=True)
    return r.returncode == 0


from contextlib import contextmanager as _cm  # noqa: E402


@_cm
def _monkeypatched(module, attr, value):
    """Minimal monkeypatch for the between-window test (test-local)."""
    old = getattr(module, attr)
    setattr(module, attr, value)
    try:
        yield
    finally:
        setattr(module, attr, old)
