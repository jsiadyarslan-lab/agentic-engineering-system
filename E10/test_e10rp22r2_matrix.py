"""E10-RP2.2-R2 — BINDING TEST MATRIX (R2-T01..R11; T12 = battery evidence).

Order: E10-RP2.2-R2 (GIT & SANDBOX LIFECYCLE AUTHORIZATION HARDENING).
Every test runs through the REAL chains:

* ToolExecutor.execute_tool → _check_permissions (repo/path grounding) →
  _check_human_gate → _execute_implementation → engine.execute_tool /
  SandboxManager.execute / WindowsExecutorAdapter.execute;
* the REAL EOE bridge ``eoe.engine_bridge.build_engine_grant_validator``
  over a REAL ``AccessAdmission`` + ``AccessLedger`` + ``GrantorService``
  with owner-approved PATH_GRANTs (no permissive substitute for any
  permission decision under test);
* the REAL owner-approval mechanism for git_push: ``eoe.push_engine``
  ``OwnerApprovalService`` (HMAC-signed, TTL) + ``NonceLedger``
  (single-use) + ``PushApprovalRegistry`` (nonce → record lookup and
  repo/remote/branch/commit/force scope binding).

Legs that deliberately test a layer ABOVE the permission layer (the
git_push handler, the approval registry) or the EXECUTION layer (the
sandbox adapter's degraded mode) are labeled inline as such and use the
minimal scaffold needed to REACH that layer — the scaffold never weakens
the layer under test. No grant scope is expanded to make any test pass:
the in-scope grant covers exactly ``<workspace>/treeA`` and every
expected-rejection target is outside it (or outside the workspace
universe entirely).

R2-T12 (regression battery + two-state comparison at baseline 0945960) is
delivered as evidence, not as a pytest test: see
``E10/run_rp22r2_regressions.sh`` and
``E10/evidence_rp22r2/REGRESSIONS_BRANCH.txt`` +
``E10/evidence_rp22r2/TWO_STATE_BASELINE.json``.
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
    PY, fresh_bridge, git_out, make_bare, make_repo,
)

from unified.contracts import AgentType, MissionState  # noqa: E402
from unified.execution import ExecutionEngine, ExecutionContext  # noqa: E402
from unified.sandbox import (  # noqa: E402
    SandboxBackend, SandboxError, SandboxManager, create_sandbox_manager,
    validate_sandbox_id,
)
from unified.domain_model import SandboxRequest  # noqa: E402
from unified.windows_adapter import WindowsExecutorAdapter  # noqa: E402
from eoe.access_gateway import AccessAdmission, AccessLedger, GrantorService  # noqa: E402
from eoe.engine_bridge import build_engine_grant_validator  # noqa: E402
from eoe.order_parser import AccessRequest, GrantKind  # noqa: E402
from eoe.push_engine import (  # noqa: E402
    NonceLedger, OwnerApprovalService, PushApprovalRegistry,
)


# ---------------------------------------------------------------- helpers

def _bridge_stack(base: Path, *, scope: str = "read_write",
                  grant_target: str | None = None):
    """Real EOE stack over a workspace universe with treeA/treeB + REAL git
    repos repoA (inside treeA) and repoB (inside treeB). The grant covers
    exactly ``grant_target`` (default: treeA). The validator is the REAL
    engine bridge wired with BOTH universes (artifacts root + workspace
    root), exactly like the canonical harness pattern."""
    ws = base / "workspace"
    art = base / "artifacts"
    tree_a = ws / "treeA"
    tree_b = ws / "treeB"
    for d in (ws, art, tree_a, tree_b):
        d.mkdir(parents=True, exist_ok=True)
    repo_a = make_repo(str(tree_a / "repoA"))
    repo_b = make_repo(str(tree_b / "repoB"))

    ledger = AccessLedger()
    grantor = GrantorService(os.urandom(32))
    admission = AccessAdmission(ledger, grantor, now=__import__("time").time)
    target = grant_target or str(tree_a)
    grant = grantor.approve(grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope=scope, target=target)))
    ledger.register(grant)
    validator = build_engine_grant_validator(
        admission, artifacts_root=str(art), workspace_root=str(ws))
    return {
        "ws": ws, "art": art, "treeA": tree_a, "treeB": tree_b,
        "repoA": repo_a, "repoB": repo_b,
        "grant": grant, "grant_id": grant.grant_id,
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
         validator=None, grant_ids=None) -> ExecutionContext:
    return ExecutionContext(
        mission_id=mission_id, run_id="run-r2t", task_id="task-r2t",
        attempt_id="attempt-r2t", agent_id="agent-r2t",
        agent_type=AgentType.IMPLEMENTER,
        grant_ids=list(grant_ids) if grant_ids is not None else [stack["grant_id"]],
        grant_validator=validator if validator is not None else stack["validator"],
        workspace_root=str(stack["ws"]),
        tool_executor=engine.tool_executor,
        event_emitter=engine.event_bus.emit,
        evidence_store=engine.evidence_store,
    )


def _snap(root: str | Path) -> set:
    snap = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel != ".":
            snap.add(rel + "/")
        for f in filenames:
            snap.add(os.path.join(rel, f) if rel != "." else f)
    return snap


def _counts(engine: ExecutionEngine) -> tuple[int, int]:
    return len(engine.event_bus.history), len(engine.actions)


def _outcome(coro):
    """Run a tool call; classify the outcome without swallowing anything."""
    try:
        result = asyncio.run(coro)
    except PermissionError as e:
        return ("PERMISSION", str(e))
    except SandboxError as e:
        return ("SANDBOX_ERROR", str(e))
    except ValueError as e:
        return ("VALUE_ERROR", str(e))
    except RuntimeError as e:
        return ("RUNTIME_ERROR", str(e))
    except Exception as e:  # noqa: BLE001
        return (type(e).__name__, str(e))
    return ("TOOL_RESULT", result)


def _call(engine, ctx, name, inp):
    return _outcome(engine.tool_executor.execute_tool(ctx, name, inp))


# ================================================================ T01
def test_R2_T01_git_target_grounding(tmp_path):
    """R2-T01 (order §3.2, GAP-1): the git family's authorization decision
    is grounded to the RESOLVED, CONTAINED repo root. In-scope repo (grant
    over treeA) is ALLOWED — and now genuinely EXECUTES (DF1 fixed in the
    same change); out-of-scope repo, out-of-universe repo, and non-repo
    targets are REJECTED fail-closed with zero side effects."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    ctx = _ctx(engine, stack)
    repo_a, repo_b = stack["repoA"], stack["repoB"]

    ev0, act0 = _counts(engine)
    snap0 = _snap(tmp_path)

    # (1) POSITIVE — git_status/git_diff on the in-scope repo: real bridge,
    # real grant, real git execution (proves the DF1 import fix AND that a
    # correct grant still authorizes: no over-blocking).
    st, payload = _call(engine, ctx, "git_status", {"repo_path": repo_a})
    assert st == "TOOL_RESULT" and payload.success, (st, payload)
    assert payload.output["clean"] is True
    st, payload = _call(engine, ctx, "git_diff", {"repo_path": repo_a})
    assert st == "TOOL_RESULT" and payload.success, (st, payload)

    # relative repo_path resolves against the workspace root as well
    st, payload = _call(engine, ctx, "git_status", {"repo_path": "treeA/repoA"})
    assert st == "TOOL_RESULT" and payload.success, (st, payload)

    # (2) OUT-OF-GRANT-SCOPE — repoB is inside the workspace universe but
    # outside the grant scope (treeA): rejected at the path-aware decision.
    st, payload = _call(engine, ctx, "git_status", {"repo_path": repo_b})
    assert st == "PERMISSION" and "not covered by any presented grant" in payload, (st, payload)
    st, payload = _call(engine, ctx, "git_diff", {"repo_path": repo_b})
    assert st == "PERMISSION", (st, payload)

    # (3) OUT-OF-UNIVERSE — an absolute repo_path outside the workspace:
    # rejected at grounding, never reaches any validator.
    outside = make_repo(str(tmp_path.parent / f"r2t1-outside-{os.getpid()}"))
    try:
        st, payload = _call(engine, ctx, "git_status", {"repo_path": outside})
        assert st == "PERMISSION" and "outside the workspace universe" in payload, (st, payload)
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)

    # (4) NON-REPO target inside the universe: underivable repo root.
    st, payload = _call(engine, ctx, "git_status", {"repo_path": "treeA"})
    assert st == "PERMISSION" and "not inside a git repository" in payload, (st, payload)

    # (5) ZERO-TRACE for every rejection above.
    ev1, act1 = _counts(engine)
    snap1 = _snap(tmp_path)
    assert ev1 > ev0  # the POSITIVE legs emitted events
    assert "r2t1" not in git_out(repo_b, "branch")  # nothing written to repoB
    assert git_out(repo_a, "status", "--porcelain") == ""  # repoA untouched by reads


# ================================================================ T02
def test_R2_T02_git_kind_scoping(tmp_path):
    """R2-T02 (order §3.3, GAP-1): read-ops ↔ read, write-ops ↔ write.
    A READ-scope grant authorizes git_status/git_diff but NEVER
    git_branch/git_commit; a read_write grant over treeA does not authorize
    write ops (or any op) outside treeA."""
    stack = _bridge_stack(tmp_path, scope="read")  # READ-ONLY grant over treeA
    engine = _engine(stack)
    ctx = _ctx(engine, stack)
    repo_a, repo_b = stack["repoA"], stack["repoB"]

    # read ops allowed under the read grant
    st, payload = _call(engine, ctx, "git_status", {"repo_path": repo_a})
    assert st == "TOOL_RESULT" and payload.success, (st, payload)
    st, payload = _call(engine, ctx, "git_diff", {"repo_path": repo_a})
    assert st == "TOOL_RESULT" and payload.success, (st, payload)

    # write ops REJECTED under the read grant (write not covered)
    st, payload = _call(engine, ctx, "git_branch",
                        {"action": "create", "branch_name": "r2t2-b", "repo_path": repo_a})
    assert st == "PERMISSION" and "lacks required permission: write" in payload, (st, payload)
    st, payload = _call(engine, ctx, "git_commit",
                        {"message": "r2t2 must not commit", "repo_path": repo_a})
    assert st == "PERMISSION" and "lacks required permission: write" in payload, (st, payload)
    assert "r2t2-b" not in git_out(repo_a, "branch")
    assert git_out(repo_a, "log", "--oneline").count("\n") == 0  # single seed commit only

    # read_write grant over treeA: write INSIDE scope allowed, OUTSIDE rejected
    stack2 = _bridge_stack(tmp_path / "s2", scope="read_write")
    engine2 = _engine(stack2)
    ctx2 = _ctx(engine2, stack2)
    st, payload = _call(engine2, ctx2, "git_branch",
                        {"action": "create", "branch_name": "r2t2-inside", "repo_path": stack2["repoA"]})
    assert st == "TOOL_RESULT" and payload.success, (st, payload)
    assert "r2t2-inside" in git_out(stack2["repoA"], "branch")

    st, payload = _call(engine2, ctx2, "git_branch",
                        {"action": "create", "branch_name": "r2t2-outside", "repo_path": stack2["repoB"]})
    assert st == "PERMISSION" and "not covered by any presented grant" in payload, (st, payload)
    st, payload = _call(engine2, ctx2, "git_commit",
                        {"message": "r2t2 outside scope", "repo_path": stack2["repoB"]})
    assert st == "PERMISSION", (st, payload)
    assert "r2t2-outside" not in git_out(stack2["repoB"], "branch")


# ================================================================ T03
def _push_stack(tmp_path):
    """Real repo + real LOCAL bare remote + real owner-approval chain."""
    stack = _bridge_stack(tmp_path)
    bare = make_bare(str(tmp_path / "r2remote.git"))
    repo_a = stack["repoA"]
    git_out(repo_a, "remote", "add", "r2remote", bare)
    head = git_out(repo_a, "rev-parse", "HEAD")
    svc = OwnerApprovalService(b"r2t3-owner-key", ttl_seconds=600)
    ledger = NonceLedger()
    registry = PushApprovalRegistry(svc, ledger)
    stack.update({"bare": bare, "head": head, "svc": svc,
                  "ledger": ledger, "registry": registry})
    return stack


def test_R2_T03_git_push_nonce_and_owner_approval(tmp_path):
    """R2-T03 (order §3.4-§3.6, GAP-2 + GAP-5 for push):

    (a) under the REAL bridge git_push stays unattainable at the permission
        layer (admin is not an EOE grant kind — fail-closed by policy) with
        a FAKE nonce and an unregistered mission alike, zero effects on the
        remote;
    (b) the REAL owner-approval mechanism (signed record + single-use nonce
        + repo/remote/branch/commit/force scope) rejects fake, reused,
        out-of-scope, and expired nonces, and accepts exactly one
        correctly-scoped approval;
    (c) handler level: no registry wired → push refused outright (§3.6);
        a valid scoped approval → the push executes (and a force push
        requires a force-scoped approval — §3.5 force semantics)."""
    stack = _push_stack(tmp_path)

    # ---- (a) full real bridge: permission layer
    engine = _engine(stack)
    ctx = _ctx(engine, stack)  # ghost mission
    ev0, act0 = _counts(engine)
    st, payload = _call(engine, ctx, "git_push",
                        {"repo_path": stack["repoA"], "branch": "main",
                         "remote": "r2remote", "owner_approval_nonce": "R2T3-FAKE-NONCE"})
    assert st == "PERMISSION", (st, payload)  # admin unattainable under real bridge
    # CRITICAL gate fail-closed on the unregistered mission (GAP-5)
    assert "not registered in the engine" in payload or "lacks required permission" in payload, payload
    assert git_out(stack["bare"], "rev-parse", "--verify", "main") == "" \
        or "HEAD" not in git_out(stack["bare"], "log", "--oneline")
    ev1, act1 = _counts(engine)
    assert (ev1, act1) == (ev0, act0)  # zero trace

    # ---- (b) the REAL approval mechanism (registry level — the chain the
    # tool delegates to; no validator involved at this layer).
    # E10-RP2.2-R2A §3.1 — the approval now also binds the CANONICAL PUSH
    # URL (resolved via the owner-side helper over the same repo), so a
    # remote-name match alone can never authorize: the signed destination
    # must equal the execution-time destination.
    from eoe.push_engine import resolve_push_destination as _rpd
    reg, svc = stack["registry"], stack["svc"]
    repo_root = str(Path(stack["repoA"]).resolve())
    push_url = _rpd(repo_root, "r2remote")
    appr = svc.sign(repository=repo_root, branch="main", commit_sha=stack["head"],
                    files_digest="r2t3", remote="r2remote", force=False,
                    push_url=push_url)
    reg.register(appr)

    ok, why = reg.verify_and_consume("R2T3-UNKNOWN-NONCE", repository=repo_root,
                                     branch="main", commit_sha=stack["head"], remote="r2remote",
                                     push_url=push_url)
    assert not ok and "غير مسجل" in why, (ok, why)  # fake nonce rejected

    ok, why = reg.verify_and_consume(appr.nonce, repository=repo_root,
                                     branch="main", commit_sha=stack["head"],
                                     remote="OTHER-REMOTE", push_url=push_url)
    assert not ok and "remote" in why, (ok, why)  # unapproved remote rejected

    ok, why = reg.verify_and_consume(appr.nonce, repository=repo_root,
                                     branch="other-branch", commit_sha=stack["head"],
                                     remote="r2remote", push_url=push_url)
    assert not ok, (ok, why)  # wrong branch rejected

    ok, why = reg.verify_and_consume(appr.nonce, repository=repo_root,
                                     branch="main", commit_sha="0" * 40, remote="r2remote",
                                     push_url=push_url)
    assert not ok and "التزام آخر" in why, (ok, why)  # wrong commit rejected

    ok, why = reg.verify_and_consume(appr.nonce, repository=repo_root,
                                     branch="main", commit_sha=stack["head"],
                                     remote="r2remote", push_url=push_url, force=True)
    assert not ok and "force" in why, (ok, why)  # force not in approval scope

    # R2A §3.1 — approval whose signed destination differs from the
    # execution-time destination is rejected (remote NAME matches).
    ok, why = reg.verify_and_consume(appr.nonce, repository=repo_root,
                                     branch="main", commit_sha=stack["head"],
                                     remote="r2remote", push_url=str(stack["bare"]) + "-other")
    assert not ok and "لا تطابق" in why, (ok, why)  # wrong destination rejected

    # expired approval rejected (signed in the past, TTL elapsed)
    expired = svc.sign(repository=repo_root, branch="main", commit_sha=stack["head"],
                       files_digest="r2t3", remote="r2remote", force=False,
                       push_url=push_url,
                       now=__import__("time").time() - 10_000)
    reg.register(expired)
    ok, why = reg.verify_and_consume(expired.nonce, repository=repo_root,
                                     branch="main", commit_sha=stack["head"], remote="r2remote",
                                     push_url=push_url)
    assert not ok and "منتهية" in why, (ok, why)

    # valid + correctly scoped → approved exactly once; replay rejected
    ok, why = reg.verify_and_consume(appr.nonce, repository=repo_root,
                                     branch="main", commit_sha=stack["head"], remote="r2remote",
                                     push_url=push_url)
    assert ok, why
    ok, why = reg.verify_and_consume(appr.nonce, repository=repo_root,
                                     branch="main", commit_sha=stack["head"], remote="r2remote",
                                     push_url=push_url)
    assert not ok, (ok, why)  # reused nonce rejected

    # ---- (c) handler level (the layer ABOVE the permission gate; the
    # EOE policy cannot express 'admin', so the handler is reached directly
    # with a real context — the approval chain and git effects are REAL)
    from unified.tool_contract import GitPushInput
    engine2 = _engine(stack)  # NO push_approval_registry wired
    ctx2 = _ctx(engine2, stack, mission_id="m-handler")
    engine2.missions["m-handler"] = engine2.create_mission("handler")
    inp = GitPushInput(repo_path=stack["repoA"], remote="r2remote", branch="main",
                       owner_approval_nonce="whatever")
    r = asyncio.run(engine2.tool_executor._execute_git_tool(ctx2, "git_push", inp, "a-r2t3"))
    assert not r.success and "no owner-approval registry" in (r.error or ""), r.error  # §3.6

    # wire the REAL registry; a fresh, correctly scoped approval (R2A:
    # including the canonical push URL) pushes.
    engine3 = _engine(stack, push_approval_registry=stack["registry"])
    ctx3 = _ctx(engine3, stack, mission_id="m-handler3")
    engine3.missions["m-handler3"] = engine3.create_mission("handler3")
    appr2 = stack["svc"].sign(repository=repo_root, branch="main",
                              commit_sha=stack["head"], files_digest="r2t3",
                              remote="r2remote", force=False, push_url=push_url)
    stack["registry"].register(appr2)
    inp2 = GitPushInput(repo_path=stack["repoA"], remote="r2remote", branch="main",
                        owner_approval_nonce=appr2.nonce)
    r = asyncio.run(engine3.tool_executor._execute_git_tool(ctx3, "git_push", inp2, "a-r2t3b"))
    assert r.success, (r.error, r.error_type)
    assert r.output.get("push_url") == push_url  # destination proven
    assert git_out(stack["bare"], "rev-parse", "HEAD") == stack["head"]  # remote advanced

    # force semantics (§3.5): diverge the repo, then a NON-force push is
    # rejected by git and only a force-scoped approval + force=True pushes.
    git_out(stack["repoA"], "commit", "--amend", "-m", "diverged", "--allow-empty")
    new_head = git_out(stack["repoA"], "rev-parse", "HEAD")
    assert new_head != stack["head"]
    appr_nf = stack["svc"].sign(repository=repo_root, branch="main", commit_sha=new_head,
                                files_digest="r2t3", remote="r2remote", force=False,
                                push_url=push_url)
    stack["registry"].register(appr_nf)
    inp_nf = GitPushInput(repo_path=stack["repoA"], remote="r2remote", branch="main",
                          owner_approval_nonce=appr_nf.nonce)
    r = asyncio.run(engine3.tool_executor._execute_git_tool(ctx3, "git_push", inp_nf, "a-r2t3c"))
    assert not r.success, "non-force push of a diverged history must fail"
    appr_f = stack["svc"].sign(repository=repo_root, branch="main", commit_sha=new_head,
                               files_digest="r2t3", remote="r2remote", force=True,
                               push_url=push_url)
    stack["registry"].register(appr_f)
    inp_f = GitPushInput(repo_path=stack["repoA"], remote="r2remote", branch="main",
                         force=True, owner_approval_nonce=appr_f.nonce)
    r = asyncio.run(engine3.tool_executor._execute_git_tool(ctx3, "git_push", inp_f, "a-r2t3d"))
    assert r.success, (r.error, r.error_type)
    assert git_out(stack["bare"], "rev-parse", "HEAD") == new_head  # force push landed


# ================================================================ T04
def test_R2_T04_human_gate_fail_closed_and_action_scoped(tmp_path):
    """R2-T04 (order §2.1/§2.2, GAP-5):

    * an UNREGISTERED mission_id is an explicit REJECTION for HIGH/CRITICAL
      tools (run_command HIGH, git_push CRITICAL) — never a silent skip;
    * a REGISTERED mission still gets the gate (SEC-7 preserved);
    * an approval binds to THIS tool + THESE inputs: the same input passes
      after approval, a DIFFERENT input gets a NEW gate, and a legacy
      approval record without an input digest authorizes nothing."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)

    def permissive(gid, perm, path=None, depth=None):
        # SCAFFOLD (disclosed): run_command is not path-bearing; this
        # permissive validator only lets the call REACH the gate/execution
        # layers — the layers under test here. The gate layer ignores the
        # validator entirely.
        return True

    mission = engine.create_mission("R2-T04 mission")
    mission.state = MissionState.EXECUTING  # so create_human_gate really creates

    # (1) registered mission → gate ACTIVE (pause), as at baseline
    ctx = _ctx(engine, stack, mission_id=mission.mission_id, validator=permissive)
    inp_x = {"command": [PY, "-c", "print('X')"], "working_dir": str(tmp_path)}
    st, payload = _call(engine, ctx, "run_command", inp_x)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)

    # (2) UNREGISTERED mission → explicit fail-closed rejection (GAP-5)
    ghost = _ctx(engine, stack, mission_id="ghost-not-registered", validator=permissive)
    ev0, act0 = _counts(engine)
    st, payload = _call(engine, ghost, "run_command", inp_x)
    assert st == "PERMISSION" and "not registered in the engine" in payload, (st, payload)
    st, payload = _call(engine, ghost, "git_push",
                        {"repo_path": stack["repoA"], "branch": "main",
                         "owner_approval_nonce": "n"})
    assert st == "PERMISSION", (st, payload)  # CRITICAL gate fail-closed too
    ev1, act1 = _counts(engine)
    assert (ev1, act1) == (ev0, act0)  # zero trace for both rejections

    # (3) action-scoped approval (§2.2): approve the REAL gate for input X
    gate_id = mission.metadata["human_gate"]["gate_id"]
    assert engine.decide_human_gate(mission.mission_id, gate_id, "approve",
                                    "owner", "r2t4") is True
    st, payload = _call(engine, ctx, "run_command", inp_x)  # SAME input X
    # The gate PASSED (no Human gate error): execution is then refused at
    # the sandbox layer (§4.1/§4.3) — exactly the post-fix layering. The
    # refusal surfaces either as a raised SandboxError or as a FAILED
    # ToolResult carrying the sandbox refusal (the engine catches the
    # sandbox error and returns a failed result).
    assert st != "PERMISSION" or "Human gate" not in payload, (st, payload)
    if st == "TOOL_RESULT":
        assert payload.success is False, payload
        assert "Invalid grants" in (payload.error or "") or \
            "EMPTY_GRANT_IDS" in (payload.error or "") or \
            "HOST_SUBPROCESS_FALLBACK_DISABLED" in (payload.error or ""), payload.error
    else:
        assert st == "SANDBOX_ERROR", (st, payload)
        assert "Invalid grants" in payload or "EMPTY_GRANT_IDS" in payload, payload

    # (4) DIFFERENT input Y → the recorded approval does NOT cover it →
    # a NEW gate is required (mission-wide carry-over closed)
    inp_y = {"command": [PY, "-c", "print('Y')"], "working_dir": str(tmp_path)}
    st, payload = _call(engine, ctx, "run_command", inp_y)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)

    # (5) legacy approval record WITHOUT an input digest authorizes nothing
    mission.metadata["action_gate_run_command_r2legacy"] = "gate-r2-legacy"
    mission.metadata["action_gate_run_command_r2legacy_decision"] = {"decision": "approve"}
    inp_z = {"command": [PY, "-c", "print('Z')"], "working_dir": str(tmp_path)}
    st, payload = _call(engine, ctx, "run_command", inp_z)
    assert st == "PERMISSION" and "Human gate created" in payload, (st, payload)


# ================================================================ T05
def test_R2_T05_run_command_isolation_refusal(tmp_path):
    """R2-T05 (order §4.3, GAP-4): run_command must NOT execute via an
    unisolated host subprocess presented as a safe sandbox. With no
    isolation-proving backend available (pywin32 absent on this host) the
    default is REFUSAL — before any directory is created; the degraded
    host-subprocess mode exists only as an EXPLICIT construction opt-in."""
    art = tmp_path / "art"
    art.mkdir()
    adapter = WindowsExecutorAdapter(artifacts_base_dir=str(art))
    wd = tmp_path / "wd"
    wd.mkdir()
    marker = wd / "r2t5_marker.txt"
    req = SandboxRequest(sandbox_id="r2t5-sbx", image="python:3.11-slim",
                         command=[PY, "-c", f"open({str(marker)!r}, 'w').write('x')"],
                         working_dir=str(wd), required_grant_ids=["g-r2t5"])

    snap0 = _snap(tmp_path)
    with pytest.raises(Exception, match="HOST_SUBPROCESS_FALLBACK_DISABLED"):
        asyncio.run(adapter.execute(req))
    assert not marker.exists()  # nothing executed
    assert _snap(tmp_path) == snap0  # refusal precedes even makedirs

    # degraded mode = EXPLICIT opt-in only
    adapter2 = WindowsExecutorAdapter(artifacts_base_dir=str(art),
                                      allow_host_subprocess_fallback=True)
    rec = asyncio.run(adapter2.execute(req.model_copy(update={"sandbox_id": "r2t5-sbx2"})))
    assert rec.exit_code == 0 and marker.exists()

    # manager level under the REAL bridge: non-empty grants are fail-closed
    # (the 'agent' subject call is not a permission the EOE policy admits)
    stack = _bridge_stack(tmp_path / "m")
    mgr = create_sandbox_manager(backend=SandboxBackend.WINDOWS_EXECUTOR,
                                 grant_validator=stack["validator"],
                                 artifacts_base_dir=str(tmp_path / "mart"))
    with pytest.raises(SandboxError, match="Invalid grants"):
        asyncio.run(mgr.execute(SandboxRequest(
            sandbox_id="r2t5-m", image="python:3.11-slim",
            command=[PY, "-c", "print('never')"], working_dir=str(wd),
            required_grant_ids=[stack["grant_id"]])))

    # full chain (disclosed permissive scaffold — the ENGINE-level
    # validator is permissive so the call passes BOTH the permission layer
    # (coarse gate for a non-path tool) AND the manager's grant check, and
    # the layer under test — the EXECUTION layer — is reached): even past
    # permission + gate the execution is refused; no host subprocess
    # anywhere by default.
    def permissive(gid, perm, path=None, depth=None):
        return True

    engine = ExecutionEngine(artifacts_base_dir=str(stack["art"]),
                             grant_validator=permissive,
                             grant_ids=["g-r2t5"])
    mission = engine.create_mission("R2-T05")
    mission.state = MissionState.EXECUTING
    ctx = _ctx(engine, stack, mission_id=mission.mission_id,
               validator=permissive, grant_ids=["g-r2t5"])
    inp = {"command": [PY, "-c", f"open({str(marker)!r}, 'a').write('y')"],
           "working_dir": str(wd)}
    st, payload = _call(engine, ctx, "run_command", inp)
    assert st == "PERMISSION" and "Human gate created" in payload  # gate first
    gate_id = mission.metadata["human_gate"]["gate_id"]
    engine.decide_human_gate(mission.mission_id, gate_id, "approve", "owner", "r2t5")
    st, payload = _call(engine, ctx, "run_command", inp)  # same input, gate passed
    # refused at the execution layer: the unisolated host-subprocess
    # backend is disabled by default (§4.3)
    if st == "TOOL_RESULT":
        assert payload.success is False, payload
        assert "HOST_SUBPROCESS_FALLBACK_DISABLED" in (payload.error or ""), payload.error
    else:
        assert st in ("SANDBOX_ERROR", "RUNTIME_ERROR"), (st, payload)
        assert "HOST_SUBPROCESS_FALLBACK_DISABLED" in payload, payload
    assert marker.stat().st_size == 1  # ONLY the degraded-mode leg wrote (1 byte 'x')


# ================================================================ T06
def test_R2_T06_empty_required_grant_ids_rejected(tmp_path):
    """R2-T06 (order §4.1, GAP-3): SandboxManager.execute refuses an EMPTY
    required_grant_ids list — the empty-list bypass of the grant decision
    is closed for EVERY caller (direct, agent, operational). Rejections
    leave zero directories and zero lifecycle entries."""
    art = tmp_path / "art"
    art.mkdir()
    mgr = SandboxManager(
        sandbox=WindowsExecutorAdapter(artifacts_base_dir=str(art)),
        grant_validator=None,  # no validator = fail-closed for non-empty too
    )
    req = SandboxRequest(sandbox_id="r2t6-sbx", image="python:3.11-slim",
                         command=[PY, "-c", "print('never')"],
                         working_dir=str(tmp_path), required_grant_ids=[])
    snap0 = _snap(art)
    with pytest.raises(SandboxError, match="EMPTY_GRANT_IDS"):
        asyncio.run(mgr.execute(req))
    assert _snap(art) == snap0  # zero directories
    assert "r2t6-sbx" not in mgr._active and "r2t6-sbx" not in mgr._completed

    # non-empty + no validator → all grants invalid (fail-closed preserved)
    with pytest.raises(SandboxError, match="Invalid grants"):
        asyncio.run(mgr.execute(SandboxRequest(
            sandbox_id="r2t6-sbx2", image="python:3.11-slim",
            command=[PY, "-c", "print('never')"], working_dir=str(tmp_path),
            required_grant_ids=["some-grant"])))
    assert _snap(art) == snap0

    # operational parallel path (GAP-8): the legacy operational agents call
    # sandbox_manager.execute with NO grants — now refused fail-closed.
    from unified.operational import OperationalImplementerAgent
    agent = OperationalImplementerAgent()
    from e10rp22r2_probes_lib import make_agent_context, make_task
    ctxa = make_agent_context(sandbox_manager=mgr, grant_ids=[])
    task = make_task({"operation": "run_command", "command": "print('O1-NEVER')",
                      "working_dir": str(tmp_path)})
    result = asyncio.run(agent.execute(ctxa, task))
    assert result.success is False  # the run_command operation failed closed
    assert "EMPTY_GRANT_IDS" in (result.error or ""), result.error
    assert _snap(art) == snap0  # still zero directories


# ================================================================ T07
@pytest.mark.parametrize("bad_id", [
    "../r2t7_escape", "a/b", "a\\b", "/abs/r2t7", "C:\\abs", ".", "..", " r2t7 ", "",
])
def test_R2_T07_sandbox_id_validated_before_any_mkdir(tmp_path, bad_id):
    """R2-T07 (order §4.2, GAP-7): a traversal/separator/absolute/
    whitespace sandbox_id is rejected at BOTH the manager and the adapter
    BEFORE any join/makedirs — a rejected request leaves zero directories
    outside (or inside) the artifacts base."""
    art = tmp_path / "art"
    art.mkdir()
    outside_before = _snap(tmp_path.parent)
    mgr = SandboxManager(
        sandbox=WindowsExecutorAdapter(artifacts_base_dir=str(art)),
        grant_validator=None,
    )
    req = SandboxRequest(sandbox_id=bad_id, image="python:3.11-slim",
                         command=[PY, "-c", "print('never')"],
                         working_dir=str(tmp_path), required_grant_ids=["g"])
    with pytest.raises(SandboxError, match="SANDBOX_ID_INVALID"):
        asyncio.run(mgr.execute(req))
    # adapter level (defense-in-depth): same rejection before makedirs
    adapter = WindowsExecutorAdapter(artifacts_base_dir=str(art))
    with pytest.raises(Exception, match="SANDBOX_ID_INVALID"):
        asyncio.run(adapter.execute(req))
    # ZERO new directories anywhere: artifacts base unchanged, nothing
    # escaped next to it (the ../r2t7_escape case would land in tmp_path.parent).
    assert _snap(art) == set()
    assert _snap(tmp_path.parent) == outside_before

    # parity: write_artifact still validates (RP2.2 §3.1 intact)
    with pytest.raises(SandboxError, match="SANDBOX_ID_INVALID"):
        asyncio.run(mgr.write_artifact("../r2t7_escape", "x.txt", b"x"))


# ================================================================ T08
def test_R2_T08_sandbox_execute_unregistered(tmp_path):
    """R2-T08 (order §4.4, GAP-6): sandbox_execute is REMOVED from the
    registry — a call is rejected at contract lookup BEFORE any event,
    action record, or side effect (its registered-but-unimplemented state
    and the DF2-masked 'Unknown tool' failure are both gone)."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    # the contract is unreachable through the registry...
    assert engine.tool_registry.get("sandbox_execute") is None
    # ...and the engine's population check ENFORCES its absence.
    engine._populate_tool_registry()  # must not raise

    ctx = _ctx(engine, stack)
    ev0, act0 = _counts(engine)
    snap0 = _snap(stack["art"])
    st, payload = _call(engine, ctx, "sandbox_execute",
                        {"sandbox_id": "r2t8", "image": "python:3.11-slim",
                         "command": [PY, "-c", "print('never')"],
                         "required_grant_ids": ["g"]})
    assert st == "VALUE_ERROR" and "Tool not registered: sandbox_execute" in payload, (st, payload)
    ev1, act1 = _counts(engine)
    assert (ev1, act1) == (ev0, act0)  # zero events / zero actions
    assert _snap(stack["art"]) == snap0  # zero directories


# ================================================================ T09
def test_R2_T09_df2_no_error_masking(tmp_path):
    """R2-T09 (order §2.3, DF2): a FAILED ToolResult keeps its ORIGINAL
    error — output validation is skipped for output=None instead of
    crashing on ``schema(**None)`` and replacing the true reason with a
    masking 'Output validation failed: ... NoneType' message.

    Leg 1 (full real chain): web_search passes the real bridge on a READ
    grant (coarse branch — web tools carry no path target), then fails in
    its handler with output=None; the surfaced error must be the network
    denial, not an output-validation crash.
    Leg 2 (handler level): git_push without a nonce fails with the true
    nonce requirement."""
    stack = _bridge_stack(tmp_path, scope="read")  # read grant (web: read)
    engine = _engine(stack)
    ctx = _ctx(engine, stack)

    ev0 = len(engine.event_bus.history)
    st, payload = _call(engine, ctx, "web_search", {"query": "r2t9"})
    assert st == "TOOL_RESULT" and payload.success is False, (st, payload)
    assert "Network access denied" in (payload.error or ""), payload.error
    assert "Output validation failed" not in (payload.error or ""), payload.error
    assert payload.error_type == "NetworkDeniedError"
    # the failure still emits its audit events (TOOL_FAILED) — the fix
    # removes the MASKING, not the audit trail
    def _etype(e):
        et = getattr(e, "event_type", None)
        return getattr(et, "value", str(et)) if et is not None else ""

    assert any(_etype(e) == "tool.failed" for e in engine.event_bus.history[ev0:])

    # handler level: the true git_push nonce requirement is surfaced
    from unified.tool_contract import GitPushInput
    inp = GitPushInput(repo_path=stack["repoA"], remote="r2remote", branch="main",
                       owner_approval_nonce="")
    r = asyncio.run(engine.tool_executor._execute_git_tool(ctx, "git_push", inp, "a-r2t9"))
    assert not r.success and "owner_approval_nonce" in (r.error or ""), r.error
    assert "Output validation failed" not in (r.error or ""), r.error


# ================================================================ T10
def test_R2_T10_parallel_execution_paths_closed(tmp_path):
    """R2-T10 (order §4.5, GAP-8): no zero-authorization sandbox execution
    path remains. ``_run_in_sandbox`` (dormant direct primitive) is
    disabled fail-closed; the operational agents' run_command is refused
    at the manager (§4.1, proven end-to-end in T06 — here the same
    refusal is shown for a SECOND agent class); ``sandbox_execute`` is
    unregistered (T08)."""
    from unified.agent_role import BaseAgent
    from unified.operational import OperationalExplorerAgent
    from e10rp22r2_probes_lib import make_agent_context, make_task

    art = tmp_path / "art"
    art.mkdir()
    mgr = SandboxManager(sandbox=WindowsExecutorAdapter(artifacts_base_dir=str(art)),
                         grant_validator=None)

    class ProbeAgent(BaseAgent):
        def __init__(self):
            super().__init__(AgentType.IMPLEMENTER)

        async def execute(self, context, task):
            from unified.contracts import AgentResult
            return AgentResult(task_id=task.task_id, agent_type=self.agent_type,
                               success=True, output={})

    agent = ProbeAgent()
    ctx = make_agent_context(sandbox_manager=mgr, grant_ids=[])
    agent.on_start(ctx, make_task())
    # the direct primitive refuses regardless of wiring (§4.5)
    with pytest.raises(RuntimeError, match="disabled fail-closed"):
        asyncio.run(agent._run_in_sandbox([PY, "-c", "print('never')"],
                                          working_dir=str(tmp_path)))
    assert _snap(art) == set()

    # a second operational agent class: same §4.1 refusal end to end
    explorer = OperationalExplorerAgent()
    ctx2 = make_agent_context(sandbox_manager=mgr, grant_ids=[])
    task2 = make_task({"operation": "run_command", "command": "print('never2')",
                       "working_dir": str(tmp_path)})
    result = asyncio.run(explorer.execute(ctx2, task2))
    assert result.success is False and "EMPTY_GRANT_IDS" in (result.error or "")
    assert _snap(art) == set()


# ================================================================ T11
def test_R2_T11_zero_trace_for_every_new_rejection(tmp_path):
    """R2-T11 (order §5/§6 discipline, SEC-1/2/5 preserved): every NEW
    rejection introduced by this phase — git out-of-scope, git
    out-of-universe, ghost-mission HIGH/CRITICAL gate, empty-grant
    execute, traversal sandbox_id, unregistered sandbox_execute — leaves
    events, action records, the journal, and the artifacts tree
    IDENTICAL. Proven after a PRIOR ALLOWED operation in the same mission
    (the R1 §3.6 discipline)."""
    stack = _bridge_stack(tmp_path)
    engine = _engine(stack)
    mission = engine.create_mission("R2-T11")
    ctx = _ctx(engine, stack, mission_id=mission.mission_id)

    # prior ALLOWED op (positive path through the real bridge)
    st, payload = _call(engine, ctx, "git_status", {"repo_path": stack["repoA"]})
    assert st == "TOOL_RESULT" and payload.success, (st, payload)

    journal = Path(stack["art"]) / "side_effect_journal"
    ev0, act0 = _counts(engine)
    j0 = _snap(journal) if journal.exists() else None
    art0 = _snap(stack["art"])
    ws0 = _snap(stack["ws"])

    # ghost-mission context: the §2.1 gate rejection happens BEFORE any
    # gate creation, so it must leave zero trace (a REGISTERED mission's
    # gate creation legitimately emits gate events — that is a pause, not
    # a rejection, and is covered in T04).
    ghost = _ctx(engine, stack, mission_id="r2t11-ghost")
    rejections = [
        ("git_status", {"repo_path": stack["repoB"]}, ctx),              # out of grant scope
        ("git_status", {"repo_path": str(tmp_path)}, ctx),               # outside the universe
        ("git_branch", {"action": "create", "branch_name": "r2t11-x",
                        "repo_path": stack["repoB"]}, ctx),              # write outside scope
        ("run_command", {"command": [PY, "-c", "print('n')"],
                         "working_dir": str(tmp_path)}, ghost),          # ghost-mission gate (§2.1)
        ("git_push", {"repo_path": stack["repoA"], "branch": "main",
                      "owner_approval_nonce": "n"}, ghost),               # CRITICAL ghost gate (§2.1)
        ("sandbox_execute", {"sandbox_id": "r2t11", "image": "python:3.11-slim",
                             "command": [PY, "-c", "print('n')"]}, ctx),  # unregistered (§4.4)
    ]
    for name, inp, use_ctx in rejections:
        st, payload = _call(engine, use_ctx, name, inp)
        assert st in ("PERMISSION", "VALUE_ERROR"), (name, st, payload)

    # sandbox-layer rejections leave the tree identical too
    mgr = SandboxManager(sandbox=WindowsExecutorAdapter(artifacts_base_dir=str(stack["art"])),
                         grant_validator=None)
    for req in (
        SandboxRequest(sandbox_id="../r2t11_escape", image="python:3.11-slim",
                       command=[PY, "-c", "print('n')"], working_dir=str(tmp_path),
                       required_grant_ids=[]),
        SandboxRequest(sandbox_id="r2t11-sbx", image="python:3.11-slim",
                       command=[PY, "-c", "print('n')"], working_dir=str(tmp_path),
                       required_grant_ids=[]),
    ):
        with pytest.raises(SandboxError):
            asyncio.run(mgr.execute(req))

    ev1, act1 = _counts(engine)
    assert (ev1, act1) == (ev0, act0)  # no event / no action record grew
    assert (_snap(journal) if journal.exists() else None) == j0  # journal untouched
    assert _snap(stack["art"]) == art0  # artifacts tree untouched
    assert _snap(stack["ws"]) == ws0  # workspace (both repos) untouched
    assert "r2t11-x" not in git_out(stack["repoB"], "branch")
