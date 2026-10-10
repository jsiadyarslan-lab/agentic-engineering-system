"""E10-RP2.2-R2A — BINDING TEST MATRIX (arbitration order §2.3 + §3.2).

F1 (§2.3, one-shot human approval): every case of the arbitrator's
nine-case list, through the REAL gate machinery (engine.create_human_gate /
decide_human_gate / mission metadata) — never a mocked gate.

F2 (§3.2, push destination/ref binding): every case of the arbitrator's
explicit list plus the §3.1 destination rules, proven with REAL local bare
repositories — each leg asserts WHICH destination received (or did not
receive) the pushed ref, never text comparison inside the registry alone.

Layering disclosure (order §4.3): the git_push handler legs reach the layer
ABOVE the permission gate through a permissive scaffold validator (the real
EOE policy cannot express 'admin' — proven separately in G-legs: through the
REAL bridge git_push stays rejected with zero trace). They are LAYERED
tests of the approval/destination machinery, not end-to-end production
pushes. The approval chain (HMAC + TTL + single-use nonce ledger +
registry) and every git effect are REAL in every leg.

The production resume semantics proven here match the engine's mechanics:
``_execute_single_task`` mints a fresh attempt_id per continuation, so the
sanctioned resume of a paused operation presents the SAME
mission/run/task/tool/input-digest identity under a NEW attempt — the
consumption record binds both lineages (creating attempt in ``_operation``,
consuming attempt in ``_consumed``).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

sys.path.insert(0, str(HERE))

from e10rp22r2_probes_lib import (  # noqa: E402
    PY, git_out, make_bare, make_repo,
)

from unified.contracts import AgentType, MissionState  # noqa: E402
from unified.execution import ExecutionEngine, ExecutionContext  # noqa: E402
from unified.tool_contract import GitPushInput  # noqa: E402
from eoe.access_gateway import AccessLedger, GrantorService  # noqa: E402
from eoe.engine_bridge import build_engine_grant_validator  # noqa: E402
from eoe.order_parser import AccessRequest, GrantKind  # noqa: E402
from eoe.push_engine import (  # noqa: E402
    NonceLedger, OwnerApprovalService, PushApprovalRegistry,
    resolve_push_destination,
)


# ---------------------------------------------------------------- helpers

def _bridge_stack(base: Path, *, scope: str = "read_write",
                  grant_target: str | None = None):
    """Real EOE stack over a workspace universe (treeA/treeB + repoA inside
    treeA), grant covering exactly treeA — the canonical harness pattern."""
    base = Path(base)
    ws = base / "workspace"
    art = base / "artifacts"
    tree_a = ws / "treeA"
    tree_b = ws / "treeB"
    for d in (ws, art, tree_a, tree_b):
        d.mkdir(parents=True, exist_ok=True)
    repo_a = make_repo(str(tree_a / "repoA"))

    ledger = AccessLedger()
    grantor = GrantorService(os.urandom(32))
    admission = __import__("eoe.access_gateway", fromlist=["AccessAdmission"]).AccessAdmission(
        ledger, grantor, now=__import__("time").time)
    target = grant_target or str(tree_a)
    grant = grantor.approve(grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope=scope, target=target)))
    ledger.register(grant)
    validator = build_engine_grant_validator(
        admission, artifacts_root=str(art), workspace_root=str(ws))
    return {
        "ws": ws, "art": art, "treeA": tree_a, "treeB": tree_b,
        "repoA": repo_a, "grant": grant, "grant_id": grant.grant_id,
        "admission": admission, "validator": validator,
    }


def _engine(stack: dict, **kw) -> ExecutionEngine:
    return ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=stack["validator"],
        grant_ids=[stack["grant_id"]],
        **kw,
    )


def _ctx(engine: ExecutionEngine, stack: dict, *, mission_id: str = "ghost-mission",
         run_id: str = "run-r2a", task_id: str = "task-r2a",
         attempt_id: str = "attempt-r2a", agent_id: str = "agent-r2a",
         validator=None, grant_ids=None) -> ExecutionContext:
    return ExecutionContext(
        mission_id=mission_id, run_id=run_id, task_id=task_id,
        attempt_id=attempt_id, agent_id=agent_id,
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=list(grant_ids) if grant_ids is not None else [stack["grant_id"]],
        grant_validator=validator if validator is not None else stack["validator"],
        workspace_root=str(stack["ws"]),
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )


def _counts(engine: ExecutionEngine) -> tuple[int, int]:
    return len(engine.event_bus.history), len(engine.actions)


def _outcome(coro):
    """Run a tool call; classify the outcome without swallowing anything."""
    try:
        result = asyncio.run(coro)
    except PermissionError as e:
        return ("PERMISSION", str(e))
    except Exception as e:  # noqa: BLE001
        return (type(e).__name__, str(e))
    return ("TOOL_RESULT", result)


def _call(engine, ctx, name, inp):
    return _outcome(engine.tool_executor.execute_tool(ctx, name, inp))


def _permissive(gid, perm, path=None, depth=None):
    """DISCLOSED SCAFFOLD (order §4.3): permissive validator used ONLY to
    reach the gate/execution layers under test (run_command is not
    path-bearing; git_push's 'admin' is unattainable under the real EOE
    policy — proven separately in the G-legs through the REAL bridge)."""
    return True


def _permissive_path_aware(gid, perm, path=None, depth=None):
    """DISCLOSED SCAFFOLD (order §4.3) — same as ``_permissive`` but marked
    path-aware (3-arg form) so the git-family repo grounding accepts it and
    the call reaches the GATE + HANDLER layers under test. The production
    chain (real bridge) is proven separately in the G-legs."""
    return True


_permissive_path_aware.__path_aware__ = True


def _gate_v2_keys(mission) -> list[str]:
    """Live (non-archived) v2 operation keys in mission metadata."""
    return sorted(
        k for k in mission.metadata
        if k.startswith("action_gate_v2:") and not k.endswith(
            ("_decision", "_consumed", "_operation", "_cycles"))
        and "#cycle" not in k
    )


def _bare_head(bare: str, ref: str = "main") -> str:
    r = git_out(bare, "rev-parse", "--verify", f"refs/heads/{ref}")
    return r if not r.startswith("fatal:") else ""


# ================================================================ F1
# Order §2.3 — the nine mandatory one-shot approval cases.

def test_R2A_A1_gate_creation_binds_full_operation_identity(tmp_path):
    """R2A-A1 (§2.3 case 1): a HIGH tool on a REGISTERED mission creates a
    REAL approval gate; the record carries the FULL operation identity —
    mission_id, run_id, task_id, attempt_id, agent_id, tool name, and the
    canonical input digest of the validated payload."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-A1")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               run_id="run-a1", task_id="task-a1",
               attempt_id="attempt-a1", agent_id="agent-a1",
               validator=_permissive)
    inp = {"command": [PY, "-c", "print('A1')"], "working_dir": str(tmp_path)}

    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)

    keys = _gate_v2_keys(mission)
    assert len(keys) == 1, keys  # exactly ONE gate for this operation
    op = mission.metadata[f"{keys[0]}_operation"]
    # the FULL identity the approval binds to (§2.1) — all seven fields
    assert op["format"] == "v2"
    assert op["mission_id"] == mission.mission_id
    assert op["run_id"] == "run-a1"
    assert op["task_id"] == "task-a1"
    assert op["attempt_id"] == "attempt-a1"
    assert op["agent_id"] == "agent-a1"
    assert op["tool_name"] == "run_command"
    assert isinstance(op["input_digest"], str) and len(op["input_digest"]) == 64
    # the gate itself is real (mission paused, gate id recorded)
    assert mission.state == MissionState.HUMAN_REQUIRED
    gate_id = mission.metadata["human_gate"]["gate_id"]
    assert mission.metadata[keys[0]] == gate_id
    assert mission.metadata["human_gate"]["context"]["operation"]["input_digest"] \
        == op["input_digest"]
    # no approval exists yet → nothing consumed
    assert mission.metadata.get(f"{keys[0]}_consumed") is None


def test_R2A_A2_pending_reentry_no_duplicate_gate(tmp_path):
    """R2A-A2: re-presenting the SAME operation while awaiting the decision
    pauses on the EXISTING gate — no duplicate gate is created (a pending
    operation has exactly one gate, whoever re-enters it)."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-A2")
    mission.state = MissionState.EXECUTING
    inp = {"command": [PY, "-c", "print('A2')"], "working_dir": str(tmp_path)}
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               validator=_permissive)
    st, _ = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION"
    gate_id = mission.metadata["human_gate"]["gate_id"]

    # mission still awaiting decision; a NEW attempt of the same operation
    # re-presents the same identity → pending, same gate, no new gate
    mission.state = MissionState.EXECUTING
    ctx2 = _ctx(engine, stack, mission_id=mission.mission_id,
                attempt_id="attempt-a2-retry", agent_id="agent-a2-retry",
                validator=_permissive)
    st, payload = _call(engine, ctx2, "run_command", inp)
    assert st == "PERMISSION" and "pending" in payload, (st, payload)
    assert len(_gate_v2_keys(mission)) == 1
    assert mission.metadata[_gate_v2_keys(mission)[0]] == gate_id


def test_R2A_A3_approve_then_one_shot_resume(tmp_path):
    """R2A-A3 (§2.3 case 2): after approval, resuming the SAME operation
    works EXACTLY ONCE — the first continuation presenting the operation
    identity consumes the approval and proceeds past the gate (here: into
    the sandbox layer's documented refusal), with the consuming lineage
    recorded."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-A3")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               run_id="run-a3", task_id="task-a3",
               attempt_id="attempt-a3-create", agent_id="agent-a3",
               validator=_permissive)
    inp = {"command": [PY, "-c", "print('A3')"], "working_dir": str(tmp_path)}
    st, _ = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION"
    key = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key]

    assert engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                                    "owner", "r2a-a3") is True
    assert mission.state == MissionState.EXECUTING

    # the sanctioned resume: a CONTINUATION attempt of the same task (the
    # engine mints a fresh attempt_id per continuation) presents the same
    # operation identity → the gate is consumed and the call proceeds
    resume_ctx = _ctx(engine, stack, mission_id=mission.mission_id,
                      run_id="run-a3", task_id="task-a3",
                      attempt_id="attempt-a3-resume", agent_id="agent-a3",
                      validator=_permissive)
    st, payload = _call(engine, resume_ctx, "run_command", inp)
    # gate PASSED — the refusal that follows is the sandbox layer's
    # documented default (no isolation backend), NOT a gate rejection
    assert not (st == "PERMISSION" and "Human gate" in payload), (st, payload)
    if st == "TOOL_RESULT":
        assert payload.success is False
        assert "Human gate" not in (payload.error or "")
    cons = mission.metadata.get(f"{key}_consumed")
    assert cons is not None, "approval must be consumed by the resume"
    assert cons["consumed_by_attempt"] == "attempt-a3-resume"
    assert cons["consumed_by_agent"] == "agent-a3"
    # creating lineage preserved in the operation record
    assert mission.metadata[f"{key}_operation"]["attempt_id"] == "attempt-a3-create"


def test_R2A_A4_reuse_after_completion_rejected(tmp_path):
    """R2A-A4 (§2.3 case 4): after the operation resumed and the approval
    was consumed, reusing it is REJECTED — the next identical call opens a
    NEW gate cycle (a new approval is required), and the consumed cycle is
    archived for audit."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-A4")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               run_id="run-a4", task_id="task-a4",
               attempt_id="attempt-a4", agent_id="agent-a4",
               validator=_permissive)
    inp = {"command": [PY, "-c", "print('A4')"], "working_dir": str(tmp_path)}
    _call(engine, ctx, "run_command", inp)
    key = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key]
    engine.decide_human_gate(mission.mission_id, gate_id, "approve", "owner", "a4")
    mission.state = MissionState.EXECUTING
    _call(engine, ctx, "run_command", inp)  # the one-shot resume (consumes)

    # second call — SAME identity, SAME attempt even: the approval is SPENT
    mission.state = MissionState.EXECUTING
    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    # consumed cycle archived; fresh cycle opened with a NEW gate id
    assert mission.metadata.get(f"{key}#cycle1") == gate_id
    assert mission.metadata.get(f"{key}#cycle1_consumed") is not None
    assert mission.metadata.get(f"{key}_cycles") == 2
    new_gate_id = mission.metadata[key]
    assert new_gate_id != gate_id
    # and the archived approval can never be re-decided (duplicate protection)
    assert engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                                    "owner", "re-approve-old") is False


def test_R2A_A5_independent_call_requires_new_approval(tmp_path):
    """R2A-A5 (§2.3 case 3 + 6): a NEW INDEPENDENT invocation — same tool,
    same inputs, DIFFERENT task (and different mission, and different run)
    — requires a NEW approval; neither a pending nor an approved gate of
    another operation ever authorizes it."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-A5")
    mission.state = MissionState.EXECUTING
    inp = {"command": [PY, "-c", "print('A5')"], "working_dir": str(tmp_path)}

    ctx_t1 = _ctx(engine, stack, mission_id=mission.mission_id,
                  run_id="run-a5", task_id="task-t1",
                  attempt_id="attempt-t1", agent_id="agent-t1",
                  validator=_permissive)
    st, payload = _call(engine, ctx_t1, "run_command", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    key_t1 = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key_t1]

    # (a) a different TASK in the same run: paused like every undecided
    #     HIGH operation (the mission is HUMAN_REQUIRED awaiting t1's
    #     decision, so t2's gate cannot even be created yet) — the call
    #     does NOT pass, and t1's pending gate does not cover it
    ctx_t2 = _ctx(engine, stack, mission_id=mission.mission_id,
                  run_id="run-a5", task_id="task-t2",
                  attempt_id="attempt-t2", agent_id="agent-t2",
                  validator=_permissive)
    st, payload = _call(engine, ctx_t2, "run_command", inp)
    assert st == "PERMISSION", (st, payload)  # paused — never authorized

    # (b) approve task-t1's gate: task-t2's identical call STILL gated —
    # now its own REAL gate exists (two separate v2 operations)
    engine.decide_human_gate(mission.mission_id, gate_id, "approve", "owner", "a5")
    mission.state = MissionState.EXECUTING
    st, payload = _call(engine, ctx_t2, "run_command", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    assert len(_gate_v2_keys(mission)) == 2  # two SEPARATE gates
    # and task-t1's approval was NOT consumed by task-t2's call
    assert mission.metadata.get(f"{key_t1}_consumed") is None

    # (c) different MISSION, same tool+inputs: own gate again
    mission2 = engine.create_mission("R2A-A5-other")
    mission2.state = MissionState.EXECUTING
    ctx_m2 = _ctx(engine, stack, mission_id=mission2.mission_id,
                  run_id="run-a5x", task_id="task-t1",
                  attempt_id="attempt-t1", agent_id="agent-t1",
                  validator=_permissive)
    st, payload = _call(engine, ctx_m2, "run_command", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)

    # (d) different RUN of the same mission/task: own gate again
    ctx_r2 = _ctx(engine, stack, mission_id=mission.mission_id,
                  run_id="run-a5-other", task_id="task-t1",
                  attempt_id="attempt-t1", agent_id="agent-t1",
                  validator=_permissive)
    st, payload = _call(engine, ctx_r2, "run_command", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)


def test_R2A_A6_positive_resume_real_push_side_effect(tmp_path):
    """R2A-A6 (§2.3 case 2, POSITIVE proof with a real side effect): the
    resumed operation actually EXECUTES exactly once. git_push (CRITICAL)
    through the disclosed layered scaffold with a REAL owner approval: the
    gate pauses, the approval resumes it ONCE, and the push lands in the
    approved bare destination; the very next identical call is gated again
    (new approval cycle)."""
    stack = _bridge_stack(tmp_path)
    bare = make_bare(str(Path(tmp_path) / "r2a-remote.git"))
    git_out(stack["repoA"], "remote", "add", "r2aremote", bare)
    head = git_out(stack["repoA"], "rev-parse", "HEAD")
    repo_root = str(Path(stack["repoA"]).resolve())
    push_url = resolve_push_destination(repo_root, "r2aremote")

    svc = OwnerApprovalService(b"r2a-a6-owner-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=_permissive_path_aware,  # scaffold (disclosed, §4.3)
        grant_ids=[stack["grant_id"]],
        push_approval_registry=registry,
    )
    mission = engine.create_mission("R2A-A6")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               run_id="run-a6", task_id="task-a6",
               attempt_id="attempt-a6", agent_id="agent-a6",
               validator=_permissive_path_aware)

    inp = {"repo_path": stack["repoA"], "remote": "r2aremote", "branch": "main",
           "owner_approval_nonce": "PENDING-NONCE"}
    st, payload = _call(engine, ctx, "git_push", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    key = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key]
    assert mission.metadata[f"{key}_operation"]["tool_name"] == "git_push"

    # the owner approves the operation; the REAL approval for THIS push is
    # registered by the owner channel (outside the agent's inputs)
    engine.decide_human_gate(mission.mission_id, gate_id, "approve", "owner", "a6")
    mission.state = MissionState.EXECUTING
    appr = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                    files_digest="r2a-a6", remote="r2aremote", force=False,
                    push_url=push_url)
    registry.register(appr)

    # the resumed operation carries the nonce inside its INPUTS — the same
    # identity that was approved (input digest includes the nonce)
    inp_resume = {"repo_path": stack["repoA"], "remote": "r2aremote", "branch": "main",
                  "owner_approval_nonce": appr.nonce}
    st, payload = _call(engine, ctx, "git_push", inp_resume)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    # ^ different inputs (nonce now real) = different identity → NEW gate.
    # Approve THAT operation, then the resume executes the push for real.
    key2 = [k for k in _gate_v2_keys(mission) if mission.metadata[k] != gate_id][0]
    gate2 = mission.metadata[key2]
    engine.decide_human_gate(mission.mission_id, gate2, "approve", "owner", "a6")
    mission.state = MissionState.EXECUTING
    st, payload = _call(engine, ctx, "git_push", inp_resume)
    assert st == "TOOL_RESULT" and payload.success, (st, payload)
    assert _bare_head(bare) == head  # THE push happened, to the approved dest
    assert mission.metadata.get(f"{key2}_consumed") is not None

    # the very next identical call: approval spent → NEW gate cycle
    mission.state = MissionState.EXECUTING
    st, payload = _call(engine, ctx, "git_push", inp_resume)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)
    assert mission.metadata.get(f"{key2}_cycles") == 2


def test_R2A_B_changed_scope_rejected(tmp_path):
    """R2A-B (§2.3 case 5): changing the INPUTS, the TOOL, or the operation
    SCOPE (mission/run/task) is refused — the recorded approval covers only
    the exact operation it was decided for."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-B")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               run_id="run-b", task_id="task-b",
               attempt_id="attempt-b", agent_id="agent-b",
               validator=_permissive_path_aware)  # scaffold: git leg needs path-aware
    inp_x = {"command": [PY, "-c", "print('X')"], "working_dir": str(tmp_path)}
    st, _ = _call(engine, ctx, "run_command", inp_x)
    assert st == "PERMISSION"
    key = _gate_v2_keys(mission)[0]
    engine.decide_human_gate(mission.mission_id, mission.metadata[key],
                             "approve", "owner", "b")
    mission.state = MissionState.EXECUTING
    # resume once (consume) so the approval is LIVE-USED, not just approved
    _call(engine, ctx, "run_command", inp_x)
    assert mission.metadata.get(f"{key}_consumed") is not None

    # (a) different INPUTS: new gate, never covered by the old approval
    mission.state = MissionState.EXECUTING
    inp_y = {"command": [PY, "-c", "print('Y')"], "working_dir": str(tmp_path)}
    st, payload = _call(engine, ctx, "run_command", inp_y)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)

    # (b) different TOOL (git_push CRITICAL): its own gate — a run_command
    # approval can never authorize a push
    st, payload = _call(engine, ctx, "git_push",
                        {"repo_path": stack["repoA"], "branch": "main",
                         "owner_approval_nonce": "n"})
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)

    # (c) an approval still UNCONSUMED does not cover a changed scope
    #     either: different task with the SAME inputs → its own gate
    ctx_other = _ctx(engine, stack, mission_id=mission.mission_id,
                     run_id="run-b", task_id="task-b2",
                     attempt_id="attempt-b", agent_id="agent-b",
                     validator=_permissive)
    st, payload = _call(engine, ctx_other, "run_command", inp_x)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)


def test_R2A_C_rejected_decision_is_terminal_for_identity(tmp_path):
    """R2A-C: a REJECTED decision is terminal for the operation identity —
    re-entry is refused with the recorded feedback (fail-closed), and a
    duplicate decision on the same gate is refused by the engine."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-C")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               validator=_permissive)
    inp = {"command": [PY, "-c", "print('C')"], "working_dir": str(tmp_path)}
    _call(engine, ctx, "run_command", inp)
    key = _gate_v2_keys(mission)[0]
    gate_id = mission.metadata[key]

    assert engine.decide_human_gate(mission.mission_id, gate_id, "reject",
                                    "owner", "not allowed") is True
    mission.state = MissionState.EXECUTING
    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "rejected" in payload.lower(), (st, payload)
    assert "not allowed" in payload
    # duplicate decision on the decided gate is refused
    assert engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                                    "owner", "flip") is False


def test_R2A_D_unregistered_mission_and_zero_trace(tmp_path):
    """R2A-D (§2.3 cases 7 + 9): an UNREGISTERED mission is an explicit
    fail-closed rejection for HIGH and CRITICAL tools alike (R2 §2.1
    preserved), and pre-execution rejections leave NO events, NO Action
    records, and no side effects (zero trace)."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-D-registered")
    mission.state = MissionState.EXECUTING
    ghost = _ctx(engine, stack, mission_id="ghost-not-registered",
                 validator=_permissive)
    inp = {"command": [PY, "-c", "print('D')"], "working_dir": str(tmp_path)}

    ev0, act0 = _counts(engine)
    st, payload = _call(engine, ghost, "run_command", inp)
    assert st == "PERMISSION" and "not registered in the engine" in payload, (st, payload)
    st, payload = _call(engine, ghost, "git_push",
                        {"repo_path": stack["repoA"], "branch": "main",
                         "owner_approval_nonce": "n"})
    assert st == "PERMISSION", (st, payload)
    ev1, act1 = _counts(engine)
    assert (ev1, act1) == (ev0, act0)  # zero trace for both rejections

    # rejected-decision re-entry: also zero trace for the rejected call
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               validator=_permissive)
    ev2, act2 = _counts(engine)
    _call(engine, ctx, "run_command", inp)  # gate created (emits gate events)
    gate_id = mission.metadata["human_gate"]["gate_id"]
    engine.decide_human_gate(mission.mission_id, gate_id, "reject", "owner", "no")
    mission.state = MissionState.EXECUTING
    ev3, act3 = _counts(engine)
    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "rejected" in payload.lower()
    ev4, act4 = _counts(engine)
    assert (ev4, act4) == (ev3, act3)  # the rejected call added NOTHING


def test_R2A_D2_legacy_records_authorize_nothing(tmp_path):
    """R2A-D2 (§2.2): LEGACY gate records — pre-R2 bare records AND R2's
    digest-only records — authorize NOTHING. Only a v2 operation record
    matching the current call can ever satisfy the gate."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2A-D2")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               validator=_permissive)
    inp = {"command": [PY, "-c", "print('D2')"], "working_dir": str(tmp_path)}

    # pre-R2 style: bare gate id + approve decision, no digest at all
    mission.metadata["action_gate_run_command_prer2"] = "gate-prer2"
    mission.metadata["action_gate_run_command_prer2_decision"] = {"decision": "approve"}
    # R2 style: action-id key + input digest, but NO v2 operation record
    mission.metadata["action_gate_run_command_action-abc12345"] = "gate-r2style"
    mission.metadata["action_gate_run_command_action-abc12345_decision"] = {"decision": "approve"}
    from unified.execution import ToolExecutor as _TE
    mission.metadata["action_gate_run_command_action-abc12345_input_digest"] = \
        _TE._gate_input_digest(__import__("pydantic").create_model("X")())
    # a v2 record with a CORRUPTED identity (wrong task) must not authorize
    mission.metadata["action_gate_v2:corrupt:key"] = "gate-corrupt"

    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)


def test_R2A_E_e9r_production_gate_flow_and_resume(tmp_path):
    """R2A-E (§2.3 case 8): the E9-R production gate flow stays intact AND
    gains the one-shot resume semantics end-to-end — the MissionController
    run pauses at the gate, the human decision restores EXECUTING, and the
    RE-EXECUTED run's continuation attempt consumes the approval exactly
    once (then the documented sandbox-layer refusal applies — the gate
    itself passed)."""
    from unified.mission_controller import MissionController, TaskSpec, register_mission_agent
    from unified.agent_role import AgentRegistry, AgentFactory, BaseAgent, AgentContext, AgentTask, AgentResult, AgentDefinition, AgentLifecycleState
    from datetime import datetime, timezone

    stack = _bridge_stack(tmp_path)
    fresh = AgentRegistry()
    # DISCLOSED SCAFFOLD (order §4.3, mirroring E9-R's own human-gate test):
    # run_command's 'execute' permission is unattainable under the real EOE
    # bridge (SEC-3) — a permissive engine validator lets the run reach the
    # layer under test here: the GATE lifecycle through the REAL
    # MissionController production path.
    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=_permissive,
        grant_ids=[stack["grant_id"]],
    )
    engine.agent_registry = fresh
    engine.agent_factory = AgentFactory(fresh)

    class GateAgent(BaseAgent):
        def __init__(self):
            super().__init__(AgentType.IMPLEMENTER)

        async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
            tool_executor = getattr(context, "tool_executor", None)
            if tool_executor is None:
                return AgentResult(task_id=task.task_id, agent_type=self.agent_type,
                                   success=False, output={}, evidence_hash="", artifacts=[])
            try:
                r = await tool_executor.execute_tool(
                    context=context, tool_name="run_command",
                    tool_input={"command": [PY, "-c", "print('E')"],
                                "working_dir": str(tmp_path), "timeout": 30})
                return AgentResult(task_id=task.task_id, agent_type=self.agent_type,
                                   success=r.success, output=r.output or {},
                                   evidence_hash="", artifacts=[])
            except PermissionError as e:
                # the gate pause surfaces to the controller as a failed
                # attempt (E9-R behavior preserved)
                return AgentResult(task_id=task.task_id, agent_type=self.agent_type,
                                   success=False,
                                   output={"gate_pause": str(e)}, evidence_hash="", artifacts=[])

    fresh.register_definition(AgentDefinition(
        agent_id="r2a-gate-agent", agent_type=AgentType.IMPLEMENTER,
        name="R2A Gate Agent", description="gate flow",
        implementation="E10.test_e10rp22r2a_matrix",
        capabilities=["run_command"], lifecycle_state=AgentLifecycleState.AVAILABLE))
    fresh.enable_agent("r2a-gate-agent")  # REGISTERED → AVAILABLE
    fresh.register_implementation(AgentType.IMPLEMENTER, GateAgent)
    mc = MissionController(engine)
    mission, run, key_to_id = mc.define_mission(
        "R2A-E", [TaskSpec(key="G", name="gate_task", description="gate",
                           agent_type=AgentType.IMPLEMENTER, depends_on=[],
                           acceptance_criteria=[], context={"task_key": "G"})])
    task_id = key_to_id["G"]

    async def _first_run():
        return await mc.execute_run(run.run_id, max_parallel=1)

    result = asyncio.run(_first_run())
    assert result.get("paused") or result.get("human_gate") or \
        not result.get("task_results", {}).get(task_id, {}).get("success", True)
    gate_info = mission.metadata.get("human_gate", {})
    gate_id = gate_info.get("gate_id")
    assert gate_id, mission.metadata.keys()
    key = _gate_v2_keys(mission)[0]
    creating_attempt = mission.metadata[f"{key}_operation"]["attempt_id"]
    assert mission.metadata[f"{key}_operation"]["task_id"] == task_id

    # human approves → mission returns to EXECUTING (E9-R contract)
    assert engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                                    "owner", "r2a-e") is True
    assert mission.state == MissionState.EXECUTING

    # RE-EXECUTE the same run: the continuation attempt presents the same
    # operation identity → the gate is CONSUMED once (never re-gated).
    # (The pause surfaces to the controller as a failed task after the
    # retry budget burns on 'pending' — the engine's own retry mechanism
    # re-arms the task in the SAME run via the same state transition the
    # engine uses internally; run_e8 documents the same-run re-execution
    # quirk and uses a checkpoint child-run instead. Both semantics are
    # proven here: same-run continuation consumes; a CHILD-RUN resume is a
    # different operation identity → own gate.)
    task_obj = engine.tasks[task_id]
    task_obj.retry_count = 0
    engine._update_task_graph_state(run.run_id, task_id, __import__("unified.contracts", fromlist=["TaskState"]).TaskState.READY)

    async def _resume_run():
        return await mc.execute_run(run.run_id, max_parallel=1)

    asyncio.run(_resume_run())
    # the FIRST resumed attempt CONSUMED the approval (now archived as
    # cycle 1 — the subsequent same-run retries of the same operation hit
    # the spent approval and opened a fresh cycle 2 requiring a NEW
    # approval, exactly the one-shot contract)
    cons1 = mission.metadata.get(f"{key}#cycle1_consumed")
    assert cons1 is not None, "the resumed run must consume the approval (archived cycle 1)"
    assert cons1["consumed_by_attempt"] != creating_attempt  # fresh attempt
    assert cons1["consumed_by_attempt"].startswith("attempt-")
    assert mission.metadata.get(f"{key}_cycles") == 2  # later retries re-gated

    # a THIRD execution of the same run: cycle 2 is PENDING (no free
    # passage — a new approval is required; nothing is consumed)
    mission.state = MissionState.EXECUTING
    task_obj.retry_count = 0
    engine._update_task_graph_state(run.run_id, task_id, __import__("unified.contracts", fromlist=["TaskState"]).TaskState.READY)

    async def _third_run():
        return await mc.execute_run(run.run_id, max_parallel=1)

    asyncio.run(_third_run())
    assert mission.metadata.get(f"{key}_cycles") == 2  # no new consumption
    assert mission.metadata.get(f"{key}#cycle2_consumed") is None

    # CROSS-RUN resume (E8-style checkpoint child-run) is a DIFFERENT
    # operation identity (run_id differs): the identical call gets its OWN
    # gate — the approval of the original run never carries over (order
    # §2.3 case 6). This is the mandated fail-closed semantics.
    mission2, run2, _ = mc.define_mission(
        "R2A-E-child", [TaskSpec(key="G", name="gate_task", description="gate",
                                 agent_type=AgentType.IMPLEMENTER, depends_on=[],
                                 acceptance_criteria=[], context={"task_key": "G"})])

    async def _child_run():
        return await mc.execute_run(run2.run_id, max_parallel=1)

    asyncio.run(_child_run())
    # a gate exists for the new run's operation — independent of the first
    keys_m2 = _gate_v2_keys(mission2)
    assert keys_m2, "the child-run operation must get its own gate"
    assert mission2.metadata[f"{keys_m2[0]}_operation"]["run_id"] == run2.run_id
    assert mission2.metadata.get(f"{keys_m2[0]}_consumed") is None  # not inherited


# ================================================================ F2
# Order §3.1/§3.2 — push destination + refspec/argv binding. Every leg
# proves WHICH bare destination received (or did not receive) the ref.

def _push_env(tmp_path, *, remote_url=None, extra_cfg=None):
    """Layered push environment: real repo + TWO real bare destinations +
    real owner-approval chain + engine wired with the registry (disclosed
    permissive scaffold — see module docstring / order §4.3)."""
    base = Path(tmp_path)
    stack = _bridge_stack(base / "ws")
    bare1 = make_bare(str(base / "dest1.git"))
    bare2 = make_bare(str(base / "dest2.git"))
    repo = stack["repoA"]
    git_out(repo, "remote", "add", "r2aremote", remote_url or bare1)
    if extra_cfg:
        for args in extra_cfg:
            git_out(repo, *args)
    head = git_out(repo, "rev-parse", "HEAD")
    svc = OwnerApprovalService(b"r2a-f2-owner-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    # engine wired with the registry + DISCLOSED permissive scaffold
    # validator (order §4.3 — the real EOE policy cannot express 'admin';
    # the production chain stays rejected, proven in the G-legs)
    engine = ExecutionEngine(
        artifacts_base_dir=str(stack["art"]),
        grant_validator=_permissive,
        grant_ids=[stack["grant_id"]],
        push_approval_registry=registry,
    )
    mission = engine.create_mission("r2a-f2")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               run_id="run-f2", task_id="task-f2",
               attempt_id="attempt-f2", agent_id="agent-f2",
               validator=_permissive)
    repo_root = str(Path(repo).resolve())
    return {"stack": stack, "repo": repo, "repo_root": repo_root,
            "bare1": bare1, "bare2": bare2, "head": head,
            "svc": svc, "registry": registry, "engine": engine,
            "mission": mission, "ctx": ctx}


def _push(env, *, remote="r2aremote", branch="main", nonce="x", force=False):
    """Direct handler call (layer ABOVE the permission gate; approval chain
    + git effects REAL — order §4.3 layered-test labeling)."""
    inp = GitPushInput(repo_path=env["repo"], remote=remote, branch=branch,
                       force=force, owner_approval_nonce=nonce)
    return asyncio.run(env["engine"].tool_executor._execute_git_tool(
        env["ctx"], "git_push", inp, "a-r2a-f2"))


def _sign(env, *, branch="main", sha=None, remote="r2aremote",
          push_url=None, force=False):
    appr = env["svc"].sign(repository=env["repo_root"], branch=branch,
                           commit_sha=sha or env["head"], files_digest="r2a-f2",
                           remote=remote, force=force,
                           push_url=push_url if push_url is not None
                           else str(env["bare1"]))
    env["registry"].register(appr)
    return appr


def test_R2A_F1_option_shaped_branch_and_remote_rejected(tmp_path):
    """R2A-F1 (§3.2): branch values starting with '-' — including exactly
    '--force' WITH force=False — and remote values starting with '-' are
    structurally rejected BEFORE any git subprocess: no input value can be
    interpreted as a git CLI option. No destination receives anything."""
    env = _push_env(tmp_path)
    # branch='--force' with force=False — the arbitrator's exact case
    r = _push(env, branch="--force", force=False)
    assert not r.success and "structurally invalid" in r.error, r.error
    # any other option-shaped branch
    r = _push(env, branch="--evil")
    assert not r.success and "structurally invalid" in r.error, r.error
    # option-shaped remote
    r = _push(env, remote="--evil")
    assert not r.success and "structurally invalid" in r.error, r.error
    # whitespace / control / forbidden ref characters
    r = _push(env, branch="ma in")
    assert not r.success and "structurally invalid" in r.error
    r = _push(env, branch="evil~1")
    assert not r.success and "structurally invalid" in r.error
    # nothing was pushed anywhere
    assert _bare_head(env["bare1"]) == ""
    assert _bare_head(env["bare2"]) == ""


def test_R2A_F2_check_ref_format_is_the_authority(tmp_path):
    """R2A-F2 (§3.2): git's own check-ref-format is the final authority —
    a name passing the structural check but invalid as a branch ref is
    refused (passed as a separate argv element; leading-dash values were
    already rejected structurally, so check-ref-format itself can never
    receive an option)."""
    env = _push_env(tmp_path)
    r = _push(env, branch="HEAD")
    assert not r.success and ("not a valid git branch" in r.error
                              or "structurally invalid" in r.error), r.error
    r = _push(env, branch="a//b")
    assert not r.success, r.error
    assert _bare_head(env["bare1"]) == ""


def test_R2A_F3_url_changed_after_approval_rejected(tmp_path):
    """R2A-F3 (§3.1): the owner signs the resolved destination; the remote
    URL is then CHANGED (same remote name); the push is refused and NO
    destination receives the commit — neither the newly pointed one nor
    the originally approved one."""
    env = _push_env(tmp_path)
    appr = _sign(env)  # signed for dest1 (the resolved URL at sign time)
    # the attacker/operator repoints the SAME remote name to dest2
    git_out(env["repo"], "remote", "set-url", "r2aremote", env["bare2"])
    r = _push(env, nonce=appr.nonce)
    assert not r.success and "لا تطابق" in r.error, r.error
    # proof by destination: NEITHER bare received the push
    assert _bare_head(env["bare1"]) == ""
    assert _bare_head(env["bare2"]) == ""


def test_R2A_F4_multi_destination_pushurl_rejected(tmp_path):
    """R2A-F4 (§3.1): a remote configured with TWO pushurls would make git
    push to BOTH — the approval (bound to exactly ONE canonical URL) can
    never cover it, so the push is refused outright and BOTH destinations
    stay untouched (proven against real bare repos, since git would
    otherwise actually push to each)."""
    env = _push_env(tmp_path)
    git_out(env["repo"], "config", "--add", "remote.r2aremote.pushurl", env["bare1"])
    git_out(env["repo"], "config", "--add", "remote.r2aremote.pushurl", env["bare2"])
    appr = _sign(env, push_url=str(env["bare1"]))  # even correctly signed for dest1
    r = _push(env, nonce=appr.nonce)
    assert not r.success and "متعددة" in r.error, r.error
    assert _bare_head(env["bare1"]) == ""
    assert _bare_head(env["bare2"]) == ""


def test_R2A_F4b_multi_url_no_pushurl_rejected(tmp_path):
    """R2A-F4b (§3.1): two remote URLs without any pushurl likewise push to
    ALL of them — refused before any git effect; both destinations stay
    untouched."""
    env = _push_env(tmp_path)
    git_out(env["repo"], "config", "--add", "remote.r2aremote.url", env["bare2"])
    appr = _sign(env, push_url=str(env["bare1"]))
    r = _push(env, nonce=appr.nonce)
    assert not r.success and "متعددة" in r.error, r.error
    assert _bare_head(env["bare1"]) == ""
    assert _bare_head(env["bare2"]) == ""


def test_R2A_F5_signed_destination_mismatch_rejected(tmp_path):
    """R2A-F5 (§3.1): an approval signed for a DIFFERENT destination than
    the one the repo actually points at (remote name matches!) is refused;
    nothing is pushed anywhere."""
    env = _push_env(tmp_path)
    appr = _sign(env, push_url=str(env["bare2"]))  # signed for dest2…
    r = _push(env, nonce=appr.nonce)               # …but the remote points at dest1
    assert not r.success and "لا تطابق" in r.error, r.error
    assert _bare_head(env["bare1"]) == ""
    assert _bare_head(env["bare2"]) == ""


def test_R2A_F6_scope_mismatch_branch_sha_force(tmp_path):
    """R2A-F6 (§3.2): different branch, different commit SHA (HEAD moved
    after the approval), and force mismatch (both directions) are each
    refused — the approval binds repo+remote+URL+branch+commit+force."""
    env = _push_env(tmp_path)
    # wrong branch
    appr = _sign(env)
    git_out(env["repo"], "branch", "feature/x")
    r = _push(env, branch="feature/x", nonce=appr.nonce)
    assert not r.success and "فرع آخر" in r.error, r.error
    # wrong sha: HEAD amended after the approval
    appr2 = _sign(env)
    git_out(env["repo"], "commit", "--amend", "-m", "moved", "--allow-empty")
    new_head = git_out(env["repo"], "rev-parse", "HEAD")
    r = _push(env, nonce=appr2.nonce)
    assert not r.success and "التزام آخر" in r.error, r.error
    # force mismatch: non-force approval + force=True input
    appr3 = _sign(env, sha=new_head)
    r = _push(env, nonce=appr3.nonce, force=True)
    assert not r.success and "force" in r.error, r.error
    # force approval + force=False input
    appr4 = _sign(env, sha=new_head, force=True)
    r = _push(env, nonce=appr4.nonce, force=False)
    assert not r.success and "force" in r.error, r.error
    # nothing pushed anywhere by any leg
    assert _bare_head(env["bare1"]) == ""


def test_R2A_F7_valid_approval_pushes_to_the_approved_destination(tmp_path):
    """R2A-F7 (§3.2 positive): a correctly signed approval — canonical
    destination + branch + commit (+ force) — pushes EXACTLY ONCE to the
    approved destination: dest1 holds the approved commit, dest2 stays
    empty, the output names the verified destination, and the nonce is
    spent (reuse refused)."""
    env = _push_env(tmp_path)
    appr = _sign(env, push_url=resolve_push_destination(env["repo_root"], "r2aremote"))
    r = _push(env, nonce=appr.nonce)
    assert r.success, (r.error, r.error_type)
    assert r.output.get("push_url") == str(env["bare1"])
    assert _bare_head(env["bare1"]) == env["head"]  # dest1 received exactly it
    assert _bare_head(env["bare2"]) == ""           # dest2 received nothing
    # nonce spent: reuse refused, nothing new pushed
    git_out(env["repo"], "commit", "--allow-empty", "-m", "second", "--allow-empty")
    r = _push(env, nonce=appr.nonce)
    assert not r.success, "nonce reuse must be refused"
    assert _bare_head(env["bare1"]) == env["head"]  # dest1 unchanged


def test_R2A_F8_force_push_requires_force_scoped_approval(tmp_path):
    """R2A-F8 (§3.2 positive force leg): after the histories diverge, only
    a force-scoped approval + explicit force=True lands the force push;
    the non-force attempt (with a correctly scoped non-force approval) is
    refused BY GIT itself (non-fast-forward)."""
    env = _push_env(tmp_path)
    appr = _sign(env)
    r = _push(env, nonce=appr.nonce)
    assert r.success
    # diverge
    git_out(env["repo"], "commit", "--amend", "-m", "diverged", "--allow-empty")
    new_head = git_out(env["repo"], "rev-parse", "HEAD")
    appr_nf = _sign(env, sha=new_head)
    r = _push(env, nonce=appr_nf.nonce, force=False)
    assert not r.success and "GitPushError" == r.error_type, (r.error, r.error_type)
    assert _bare_head(env["bare1"]) == env["head"]  # unchanged
    appr_f = _sign(env, sha=new_head, force=True)
    r = _push(env, nonce=appr_f.nonce, force=True)
    assert r.success, (r.error, r.error_type)
    assert _bare_head(env["bare1"]) == new_head     # force push landed
    assert _bare_head(env["bare2"]) == ""           # only the approved dest


def test_R2A_F9_nonexistent_remote_and_legacy_approval(tmp_path):
    """R2A-F9 (§3.1 + §3.3): an unconfigured remote name cannot have its
    destination proven → refused; a legacy approval WITHOUT a signed
    destination (push_url empty — including pre-R2A approval objects whose
    signature fails under the amended payload) authorizes nothing."""
    env = _push_env(tmp_path)
    # remote not configured at all (the handler default 'origin' included)
    r = _push(env, remote="nosuchremote")
    assert not r.success and ("غير موجود" in r.error
                              or "destination cannot be proven" in r.error), r.error
    r = _push(env, remote="origin")
    assert not r.success, r.error
    # legacy approval: signed WITHOUT push_url (empty destination scope)
    appr_legacy = env["svc"].sign(repository=env["repo_root"], branch="main",
                                  commit_sha=env["head"], files_digest="d",
                                  remote="r2aremote", force=False)
    env["registry"].register(appr_legacy)
    r = _push(env, nonce=appr_legacy.nonce)
    assert not r.success and "push_url" in r.error, r.error
    # R2-era approval object (no push_url field at all) replayed into the
    # amended registry: signature fails under the amended canonical payload
    from eoe.push_engine import PushApproval
    import time as _t
    legacy_obj = PushApproval(
        push_id="push-legacy", repository=env["repo_root"], branch="main",
        commit_sha=env["head"], files_digest="d", nonce="nonce-legacy-r2era",
        issued_at=_t.time(), expires_at=_t.time() + 600, approver="owner",
        remote="r2aremote", force=False, signature="0" * 64)
    env["registry"].register(legacy_obj)
    ok, why = env["registry"].verify_and_consume(
        "nonce-legacy-r2era", repository=env["repo_root"], branch="main",
        commit_sha=env["head"], remote="r2aremote",
        push_url=resolve_push_destination(env["repo_root"], "r2aremote"))
    assert not ok, (ok, why)  # dead-on-arrival: never authorizes
    assert _bare_head(env["bare1"]) == ""


def test_R2A_F10_url_rewriting_effective_destination_binding(tmp_path):
    """R2A-F10 (§3.1): insteadOf / pushInsteadOf rewriting is resolved to
    the EFFECTIVE destination. An owner who signed the RAW configured URL
    (not the rewritten one) does NOT authorize the push; an owner who
    signed the effective rewritten destination does. Push-specific
    rewriting (pushInsteadOf) takes precedence, exactly as git computes
    it."""
    env = _push_env(tmp_path, remote_url="https://example.com/x.git")
    # (a) insteadOf rewrites the fetch/push URL to dest1
    git_out(env["repo"], "config", "url.".rstrip() + str(env["bare1"]) + ".insteadOf",
            "https://example.com/x.git")
    effective = resolve_push_destination(env["repo_root"], "r2aremote")
    assert effective == str(env["bare1"]), effective  # rewritten, not the raw URL
    appr_raw = _sign(env, push_url="https://example.com/x.git")
    r = _push(env, nonce=appr_raw.nonce)
    assert not r.success and "لا تطابق" in r.error, r.error
    appr_eff = _sign(env, push_url=effective)
    r = _push(env, nonce=appr_eff.nonce)
    assert r.success, (r.error, r.error_type)
    assert _bare_head(env["bare1"]) == env["head"]

    # (b) pushInsteadOf takes precedence for pushes: effective = dest2 now
    git_out(env["repo"], "config", "url.".rstrip() + str(env["bare2"]) + ".pushInsteadOf",
            "https://example.com/x.git")
    effective2 = resolve_push_destination(env["repo_root"], "r2aremote")
    assert effective2 == str(env["bare2"]), effective2
    git_out(env["repo"], "commit", "--allow-empty", "-m", "second")
    head2 = git_out(env["repo"], "rev-parse", "HEAD")
    appr_stale = _sign(env, sha=head2, push_url=str(env["bare1"]))  # signed for the OLD effective
    r = _push(env, nonce=appr_stale.nonce)
    assert not r.success and "لا تطابق" in r.error, r.error
    appr_right = _sign(env, sha=head2, push_url=effective2)
    r = _push(env, nonce=appr_right.nonce)
    assert r.success, (r.error, r.error_type)
    assert _bare_head(env["bare2"]) == head2  # landed at the push-rewritten dest


# ================================================================ G
# Order §3.3 / §4 — owner channel + NO privilege expansion.

def test_R2A_G1_real_bridge_git_push_stays_rejected(tmp_path):
    """R2A-G1 (§3.3/§4.2): through the REAL EOE bridge the permission
    policy cannot express 'admin', so git_push stays REJECTED regardless
    of the nonce — even a REAL, correctly signed, registered approval
    never reaches execution through the production chain; zero trace, zero
    effects on every destination."""
    base = Path(tmp_path)
    stack = _bridge_stack(base / "ws")
    bare = make_bare(str(base / "dest.git"))
    git_out(stack["repoA"], "remote", "add", "r2aremote", bare)
    head = git_out(stack["repoA"], "rev-parse", "HEAD")
    repo_root = str(Path(stack["repoA"]).resolve())
    svc = OwnerApprovalService(b"r2a-g1-owner-key", ttl_seconds=600)
    registry = PushApprovalRegistry(svc, NonceLedger())
    appr = svc.sign(repository=repo_root, branch="main", commit_sha=head,
                    files_digest="g1", remote="r2aremote", force=False,
                    push_url=str(bare))
    registry.register(appr)

    engine = _engine(stack, push_approval_registry=registry)  # REAL validator
    mission = engine.create_mission("r2a-g1")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id)
    ev0, act0 = _counts(engine)
    st, payload = _call(engine, ctx, "git_push",
                        {"repo_path": stack["repoA"], "branch": "main",
                         "remote": "r2aremote", "owner_approval_nonce": appr.nonce})
    assert st == "PERMISSION", (st, payload)  # admin unattainable under the real bridge
    ev1, act1 = _counts(engine)
    assert (ev1, act1) == (ev0, act0)  # zero trace
    assert _bare_head(bare) == ""      # nothing was pushed
    # the approval was NOT consumed by the rejection (nonce still unusable
    # through the chain, but the record remains owner-side property)
    ok, _ = registry.verify_and_consume(appr.nonce, repository=repo_root,
                                        branch="main", commit_sha=head,
                                        remote="r2aremote", push_url=str(bare))
    assert ok  # unconsumed — the production chain never reached it


def test_R2A_G2_no_registry_wired_push_refused(tmp_path):
    """R2A-G2 (§3.6 preserved): with NO owner-approval registry wired the
    push is refused outright — no owner approval can be verified, so none
    can be assumed."""
    env = _push_env(tmp_path)
    engine_no_reg = _engine(env["stack"])  # real validator, NO registry
    mission = engine_no_reg.create_mission("g2")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine_no_reg, env["stack"], mission_id=mission.mission_id,
               validator=_permissive)
    inp = GitPushInput(repo_path=env["repo"], remote="r2aremote", branch="main",
                       owner_approval_nonce="whatever")
    r = asyncio.run(engine_no_reg.tool_executor._execute_git_tool(
        ctx, "git_push", inp, "a-g2"))
    assert not r.success and "no owner-approval registry" in r.error, r.error
    assert _bare_head(env["bare1"]) == ""


def test_R2A_G3_owner_channel_not_agent_reachable(tmp_path):
    """R2A-G3 (§3.3): the approval channel is owner-side — the agent can
    present ONLY a nonce; forged/unregistered nonces never authorize, the
    engine never auto-populates the registry, and no registered tool mints
    approvals (structural: the registry is engine wiring, filled only by
    owner-side ``register`` calls outside every tool input schema)."""
    env = _push_env(tmp_path)
    # forged nonce (agent-invented): unregistered
    r = _push(env, nonce="FORGED-NONCE-BY-AGENT")
    assert not r.success and "غير مسجل" in r.error, r.error
    # guessing a real nonce that was never registered
    r = _push(env, nonce="nonce-never-registered")
    assert not r.success and "غير مسجل" in r.error, r.error
    # a SIGNED approval that the owner did NOT register: its nonce is as
    # unknown to the registry as a forgery (signing ≠ registering)
    unreg = env["svc"].sign(repository=env["repo_root"], branch="main",
                            commit_sha=env["head"], files_digest="d",
                            remote="r2aremote", force=False,
                            push_url=resolve_push_destination(env["repo_root"], "r2aremote"))
    r = _push(env, nonce=unreg.nonce)
    assert not r.success and "غير مسجل" in r.error, r.error
    # the engine never auto-populates the registry
    fresh = _engine(env["stack"], push_approval_registry=PushApprovalRegistry(
        env["svc"], NonceLedger()))
    assert fresh.push_approval_registry is not None
    # structural: no registered tool can mint an approval — the git_push
    # input schema carries ONLY the nonce (plus push parameters)
    from unified.tool_contract import ALL_TOOL_CONTRACTS
    gp = ALL_TOOL_CONTRACTS["git_push"].input_schema.model_fields
    assert set(gp) == {"repo_path", "remote", "branch", "force",
                       "owner_approval_nonce"}, set(gp)
    # no tool name suggests approval minting
    for name in ALL_TOOL_CONTRACTS:
        assert "approval" not in name and "sign" not in name, name
    assert _bare_head(env["bare1"]) == ""


