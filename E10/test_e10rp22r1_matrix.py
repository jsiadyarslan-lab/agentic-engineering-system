#!/usr/bin/env python3
"""E10-RP2.2-R1 MATRIX — FAIL-CLOSED PATH-AWARE VALIDATOR ENFORCEMENT.

Order E10-RP2.2-R1 §3: binding NEGATIVE and POSITIVE tests through the
REAL ``ToolExecutor`` chain (``execute_tool`` -> contract lookup -> input
validation -> ``_check_permissions`` -> execution), NOT static
source-pattern checks. The six required categories:

  §3.1 (T01)  a non-path-aware 2-arg validator is REJECTED for every
              path-bearing tool — even when its 2-arg form returns True.
  §3.2 (T02)  missing ``sandbox_id`` / underivable concrete target in the
              artifact tools => rejection BEFORE any side effect, with NO
              fallback to the coarse kind/scope gateway.
  §3.3 (T03)  ``list_dir`` / ``grep`` / ``find_files`` / ``file_browser``
              disclose and read NOTHING without a path-aware policy.
  §3.4 (T04)  the CORRECT grant (scope + depth) ALLOWS the authorized
              operation through the real EOE bridge + ``AccessAdmission``.
  §3.5 (T05)  a grant out of path scope or beyond the depth limit is
              rejected — write, read AND exploration alike.
  §3.6 (T06)  every rejection here leaves files, folders, the journal and
              the event history with ZERO new side effects.

Baseline: 6719fe371da3d7854cb612cfa64ef937c7d3d7b2. All grant fixtures
are the REAL EOE stack (owner-approved signed grants over each test's own
tree only — no scope expansion, no permissive substitute validator; order
§2.6).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(HERE), str(REPO / "src"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

ALL_ELEVEN = (
    "artifact_write", "write_artifact", "artifact_read", "read_artifact",
    "read_file", "write_file", "edit_file",
    "list_dir", "grep", "find_files", "file_browser",
)
REGISTRY_PATH_TOOLS = (
    "artifact_write", "artifact_read", "read_file", "write_file",
    "edit_file", "list_dir", "grep", "find_files", "file_browser",
)


# ---------------------------------------------------------------- helpers
def _stack(target: str, *, scope: str = "read_write", max_depth=None,
           revoke: bool = False):
    """Real EOE authorization stack: ledger + grantor + ONE owner-approved
    PATH_GRANT over ``target`` (+ optional depth constraint at approval —
    part of the signed grant). Returns (validator, grant_id, admission,
    ledger)."""
    import dataclasses

    from eoe.access_gateway import AccessAdmission, AccessLedger, GrantorService
    from eoe.engine_bridge import build_engine_grant_validator
    from eoe.order_parser import AccessRequest, GrantKind

    ledger = AccessLedger()
    grantor = GrantorService(os.urandom(32))
    admission = AccessAdmission(ledger, grantor, now=time.time)
    prop = grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope=scope, target=target))
    if max_depth is not None:
        prop = dataclasses.replace(prop, max_depth=max_depth)
    grant = grantor.approve(prop)
    ledger.register(grant)
    if revoke:
        ledger.revoke(grant.grant_id)
    validator = build_engine_grant_validator(admission, target)
    return validator, grant.grant_id, admission, ledger


def _engine_and_ctx(base: Path, validator, grant_ids, *, sandbox_id="sbx-t",
                    mission="m-r1"):
    from unified.execution import ExecutionContext, create_execution_engine
    engine = create_execution_engine(
        artifacts_base_dir=str(base / "art"),
        grant_validator=validator, grant_ids=grant_ids)
    ctx = ExecutionContext(
        mission_id=mission, run_id="r-r1", task_id="t-r1",
        attempt_id="a-r1", agent_id="ag-r1", agent_type="implementer",
        workspace_root=str(base / "ws"), sandbox_id=sandbox_id,
        grant_validator=validator, grant_ids=grant_ids)
    return engine, ctx


def _run(engine, ctx, tool, **inp):
    """One governed invocation through the REAL ToolExecutor chain."""
    try:
        res = asyncio.run(engine.tool_executor.execute_tool(
            context=ctx, tool_name=tool, tool_input=inp))
        return {"raised": None, "success": res.success,
                "error": res.error or "", "output": res.output}
    except PermissionError as e:
        return {"raised": "PermissionError", "success": False,
                "error": str(e), "output": None}
    except Exception as e:  # noqa: BLE001
        return {"raised": type(e).__name__, "success": False,
                "error": str(e), "output": None}


def _tree(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _journal(base: Path, mission: str):
    # the side-effect journal lives under the ARTIFACTS base dir (the
    # engine constructs SideEffectJournal(self.artifacts_base_dir))
    p = base / "art" / "side_effect_journal" / mission / "journal.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _all_events(engine):
    return list(engine.event_bus.history)


# ================================ §3.1 non-path-aware 2-arg validator
def test_R1_T01_two_arg_validator_rejected_for_every_path_tool():
    """§3.1: a NON-path-aware validator is rejected for EVERY path-bearing
    tool even when its 2-arg form returns True. The spy validator really
    answers True for the 2-arg form (so the rejection cannot be explained
    by a denying validator) — the 2-arg True is simply never admissible as
    a final decision (order §2.1)."""
    from unified.execution import ExecutionContext, create_execution_engine
    from unified.tool_contract import ARTIFACT_READ_CONTRACT, \
        ARTIFACT_WRITE_CONTRACT, ToolContract

    base = Path(tempfile.mkdtemp(prefix="r1_t01_"))
    (base / "ws").mkdir()
    (base / "ws" / "seed.txt").write_text("seed")

    calls = []

    def legacy_spy(grant_id, permission):
        calls.append((grant_id, permission))
        return True  # the permissive 2-arg answer

    engine = create_execution_engine(
        artifacts_base_dir=str(base / "art"),
        grant_validator=legacy_spy, grant_ids=["g-legacy"])
    ctx = ExecutionContext(
        mission_id="m-t01", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer",
        workspace_root=str(base / "ws"), sandbox_id="sbx-t",
        grant_validator=legacy_spy, grant_ids=["g-legacy"])

    # sanity: the spy's 2-arg form answers True
    assert legacy_spy("g-legacy", "write") is True

    # end-to-end through the chain for every registry path tool
    for tool in REGISTRY_PATH_TOOLS:
        inp = {"path": "in.txt", "content": "X"} if tool == "write_file" else \
              {"path": "in.txt", "old_text": "a", "new_text": "b"} if tool == "edit_file" else \
              {"path": ".", "pattern": "x"} if tool in ("grep", "find_files") else \
              {"path": "."} if tool in ("list_dir", "file_browser") else \
              {"path": "seed.txt"} if tool == "read_file" else \
              {"sandbox_id": "sbx-t", "path": "seed.txt"} if tool == "artifact_read" else \
              {"sandbox_id": "sbx-t", "path": "a.txt", "content": "X"}
        r = _run(engine, ctx, tool, **inp)
        assert not r["success"], (tool, r)
        assert r["raised"] == "PermissionError", (tool, r)
        assert "path-aware" in r["error"], (tool, r)

    # nothing was written anywhere by any of the rejected tools
    assert not (base / "ws" / "in.txt").exists()
    assert not (base / "art" / "sbx-t" / "a.txt").exists()

    # the two registry-UNREGISTERED aliases cannot execute through the
    # chain at all (no contract => fail-closed before any decision)
    for alias in ("write_artifact", "read_artifact"):
        r = _run(engine, ctx, alias, sandbox_id="sbx-t", path="x.txt",
                 content="X")
        assert r["raised"] == "ValueError" and "not registered" in r["error"], \
            (alias, r)

    # ...and the RULE ITSELF covers their names: the real permission gate
    # rejects a non-path-aware validator for the alias contracts too
    # (direct call of the actual decision method — behavioral, not static)
    from unified.execution import ToolExecutor
    for name, tmpl in (("write_artifact", ARTIFACT_WRITE_CONTRACT),
                       ("read_artifact", ARTIFACT_READ_CONTRACT)):
        contract = ToolContract(
            name=name, category=tmpl.category, description=tmpl.description,
            input_schema=tmpl.input_schema, output_schema=tmpl.output_schema,
            required_permissions=tmpl.required_permissions,
            risk_level=tmpl.risk_level, isolation=tmpl.isolation)
        with pytest.raises(PermissionError, match="path-aware"):
            asyncio.run(engine.tool_executor._check_permissions(
                ctx, contract, {"sandbox_id": "sbx-t", "path": "x.txt"}))
    # all ELEVEN names are members of the governed set the rule reads
    assert set(ALL_ELEVEN) == set(ToolExecutor._PATH_BEARING_TOOLS)


# ================================ §3.2 underivable target, no fallback
def test_R1_T02_underivable_target_rejected_no_coarse_fallback():
    """§3.2: missing sandbox_id / underivable actual target in the
    artifact tools => rejection BEFORE any side effect, and the decision
    does NOT fall back to the coarse kind/scope gateway even though a
    VALID path-aware validator and grant are present (proving the grant
    itself is fine: the same grant authorizes a properly-derived target
    immediately after)."""
    base = Path(tempfile.mkdtemp(prefix="r1_t02_"))
    (base / "ws").mkdir()
    art = base / "art"
    art.mkdir()
    validator, gid, admission, ledger = _stack(str(art))

    # grant is valid and covers the artifacts tree (coarse form True —
    # yet it must NOT terminate the decision for a path tool)
    assert validator(gid, "write") is True

    engine, ctx = _engine_and_ctx(base, validator, [gid],
                                  sandbox_id=None)  # context has NO sandbox
    tree_before = _tree(base)
    events_before = _all_events(engine)
    assert _journal(base, "m-r1") == []

    # artifact_write with EMPTY sandbox_id input + None context sandbox:
    # input validation passes ("" is a valid str), but no concrete target
    # can be derived => fail-closed with no fallback (order §2.2)
    r = _run(engine, ctx, "artifact_write", sandbox_id="", path="x.txt",
             content="X")
    assert not r["success"] and r["raised"] == "PermissionError", r
    assert "no valid actual_target" in r["error"], r
    assert "no fallback" in r["error"], r

    # same for artifact_read
    r2 = _run(engine, ctx, "artifact_read", sandbox_id="", path="x.txt")
    assert not r2["success"] and r2["raised"] == "PermissionError", r2
    assert "no valid actual_target" in r2["error"], r2

    # zero side effects: no file, no folder, no journal record, no events
    assert _tree(base) == tree_before, _tree(base)
    assert _journal(base, "m-r1") == []
    assert _all_events(engine) == events_before

    # the coarse gateway was NOT the terminating decision: the SAME grant
    # authorizes the SAME tool the moment a concrete target is derivable
    # (context WITH a sandbox id — the None-sandbox context is only needed
    # for the underivable-target proofs above)
    from unified.execution import ExecutionContext
    ctx_pos = ExecutionContext(
        mission_id="m-r1", run_id="r-r1", task_id="t-r1",
        attempt_id="a-r1", agent_id="ag-r1", agent_type="implementer",
        workspace_root=str(base / "ws"), sandbox_id="sbx-t",
        grant_validator=validator, grant_ids=[gid])
    r3 = _run(engine, ctx_pos, "artifact_write", sandbox_id="sbx-t",
              path="ok.txt", content="OK")
    assert r3["success"] is True, r3
    assert (art / "sbx-t" / "ok.txt").exists()

    # direct gate call with tool_input=None on a path tool: also refused
    from unified.tool_contract import ToolRegistry
    contract = ToolRegistry().get("write_file")
    with pytest.raises(PermissionError, match="no valid actual_target"):
        asyncio.run(engine.tool_executor._check_permissions(
            ctx, contract, None))


# ================================ §3.3 exploration without path-aware policy
def test_R1_T03_exploration_discloses_nothing_without_path_aware_policy():
    """§3.3: list_dir / grep / find_files / file_browser neither disclose
    nor read ANY path when no path-aware policy is wired — with a legacy
    2-arg validator AND with no validator at all. Includes the
    defense-in-depth disclosure layer directly (order §2.4 deleted the
    True-return: without a path-aware validator nothing is permitted)."""
    from unified.execution import ExecutionContext, create_execution_engine
    base = Path(tempfile.mkdtemp(prefix="r1_t03_"))
    ws = base / "ws"
    (ws / "sub").mkdir(parents=True)
    (ws / "public.txt").write_text("public needle")
    (ws / "sub" / "secret.txt").write_text("secret needle")

    legacy = lambda g, p: True  # noqa: E731
    engine = create_execution_engine(
        artifacts_base_dir=str(base / "art"),
        grant_validator=legacy, grant_ids=["g-any"])
    ctx = ExecutionContext(
        mission_id="m-t03", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sbx-t", grant_validator=legacy, grant_ids=["g-any"])

    for tool, kw in (("list_dir", {}), ("grep", {"pattern": "needle"}),
                     ("find_files", {"pattern": "*.txt"}),
                     ("file_browser", {})):
        r = _run(engine, ctx, tool, path=".", **kw)
        assert not r["success"] and r["raised"] == "PermissionError", (tool, r)
        assert "path-aware" in r["error"], (tool, r)
        assert r["output"] is None, (tool, r)  # nothing disclosed at all

    # no-validator case: refused even earlier ("no validator available")
    engine2 = create_execution_engine(artifacts_base_dir=str(base / "art"))
    ctx2 = ExecutionContext(
        mission_id="m-t03b", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sbx-t")
    for tool, kw in (("list_dir", {}), ("grep", {"pattern": "needle"}),
                     ("find_files", {"pattern": "*.txt"}),
                     ("file_browser", {})):
        r = _run(engine2, ctx2, tool, path=".", **kw)
        assert not r["success"] and r["raised"] == "PermissionError", (tool, r)
        assert "no validator available" in r["error"], (tool, r)

    # defense-in-depth layer (order §2.4): the deleted True-return is gone
    assert engine.tool_executor._path_disclosure_permitted(
        ctx, ws / "public.txt") is False
    assert engine.tool_executor._path_disclosure_permitted(
        ctx, ws / "sub" / "secret.txt") is False


# ================================ §3.4 correct grant allows through real EOE
def test_R1_T04_correct_grant_allows_through_real_eoe_bridge():
    """§3.4: the CORRECT grant (right scope, right depth) ALLOWS the
    authorized operation through the real EOE bridge and AccessAdmission —
    proven not just by success but by the admission USAGE LOG and the
    ledger's grant.used events carrying the ACTUAL target path."""
    base = Path(tempfile.mkdtemp(prefix="r1_t04_"))
    ws = base / "ws"
    (ws / "docs").mkdir(parents=True)
    validator, gid, admission, ledger = _stack(str(ws))

    from unified.execution import ExecutionContext, create_execution_engine
    engine = create_execution_engine(
        artifacts_base_dir=str(base / "art"),
        grant_validator=validator, grant_ids=[gid])
    ctx = ExecutionContext(
        mission_id="m-t04", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sbx-t", grant_validator=validator, grant_ids=[gid])

    # write inside the granted tree: allowed
    r = _run(engine, ctx, "write_file", path="docs/allowed.txt",
             content="AUTH")
    assert r["success"] is True, r
    assert (ws / "docs" / "allowed.txt").exists()
    # read it back: allowed
    r2 = _run(engine, ctx, "read_file", path="docs/allowed.txt")
    assert r2["success"] is True and "AUTH" in r2["output"]["content"], r2
    # exploration discloses the granted paths: allowed
    r3 = _run(engine, ctx, "list_dir", path=".")
    assert r3["success"] is True, r3
    names = [e["name"] for e in r3["output"]["entries"]]
    assert "docs" in names and "public" not in names, names
    r4 = _run(engine, ctx, "grep", path=".", pattern="AUTH")
    assert r4["success"] is True and r4["output"]["total"] >= 1, r4

    # the REAL EOE admission actually decided each operation: usage log
    # entries carry the concrete targets; ledger recorded grant.used
    used_targets = [u["target"] for u in admission.usage_log]
    assert str(ws / "docs" / "allowed.txt") in used_targets, used_targets
    assert any(e["kind"] == "grant.used" and e["grant_id"] == gid
               for e in ledger.events), ledger.events


# ================================ §3.5 out-of-scope / out-of-depth rejected
def test_R1_T05_out_of_scope_and_out_of_depth_rejected_every_family():
    """§3.5: a grant OUT of the path scope or BEYOND the depth limit is
    rejected for WRITE, READ and EXPLORATION alike; the exact-target
    operation at depth 0 remains allowed (honest boundary, not over-
    rejection)."""
    base = Path(tempfile.mkdtemp(prefix="r1_t05_"))
    ws = base / "ws"
    (ws / "sub").mkdir(parents=True)
    (ws / "sub" / "inside.txt").write_text("NEEDLE")

    # ---- (a) grant covering a DIFFERENT directory entirely ----
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    validator, gid, _, _ = _stack(str(elsewhere))
    from unified.execution import ExecutionContext, create_execution_engine
    engine = create_execution_engine(
        artifacts_base_dir=str(base / "art"),
        grant_validator=validator, grant_ids=[gid])
    ctx = ExecutionContext(
        mission_id="m-t05a", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sbx-t", grant_validator=validator, grant_ids=[gid])
    tree_before = _tree(base)

    rw = _run(engine, ctx, "write_file", path="w.txt", content="X")
    assert not rw["success"] and "lacks required permission" in rw["error"], rw
    rr = _run(engine, ctx, "read_file", path="sub/inside.txt")
    assert not rr["success"] and "lacks required permission" in rr["error"], rr
    rl = _run(engine, ctx, "list_dir", path=".")
    assert not rl["success"] and "lacks required permission" in rl["error"], rl
    rg = _run(engine, ctx, "grep", path=".", pattern="NEEDLE")
    assert not rg["success"], rg
    assert _tree(base) == tree_before  # nothing written, nothing created

    # ---- (b) grant ON the workspace root but max_depth=0 ----
    validator0, gid0, _, _ = _stack(str(ws), max_depth=0)
    engine0 = create_execution_engine(
        artifacts_base_dir=str(base / "art"),
        grant_validator=validator0, grant_ids=[gid0])
    ctx0 = ExecutionContext(
        mission_id="m-t05b", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sbx-t", grant_validator=validator0, grant_ids=[gid0])

    # depth>0 operations are beyond the limit: write, read, exploration
    rd_w = _run(engine0, ctx0, "write_file", path="sub/deep.txt",
                content="X")
    assert not rd_w["success"] and "lacks required permission" in rd_w["error"], rd_w
    rd_r = _run(engine0, ctx0, "read_file", path="sub/inside.txt")
    assert not rd_r["success"] and "lacks required permission" in rd_r["error"], rd_r
    rd_l = _run(engine0, ctx0, "list_dir", path=".")
    # the exploration itself runs only if its ROOT is admissible; with
    # max_depth=0 the root is covered but NOTHING INSIDE may be disclosed
    if rd_l["success"]:
        assert rd_l["output"]["entries"] == [], rd_l["output"]
    else:
        assert "lacks required permission" in rd_l["error"], rd_l
    rd_g = _run(engine0, ctx0, "grep", path=".", pattern="NEEDLE")
    if rd_g["success"]:
        assert rd_g["output"]["matches"] == [], rd_g["output"]
    else:
        assert "lacks required permission" in rd_g["error"], rd_g
    assert not (ws / "sub" / "deep.txt").exists()

    # honest boundary: the EXACT target at depth 0 stays authorized
    exact = ws / "root.txt"
    validator_e, gid_e, _, _ = _stack(str(exact), max_depth=0)
    engine_e = create_execution_engine(
        artifacts_base_dir=str(base / "art"),
        grant_validator=validator_e, grant_ids=[gid_e])
    ctx_e = ExecutionContext(
        mission_id="m-t05c", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sbx-t", grant_validator=validator_e, grant_ids=[gid_e])
    re_w = _run(engine_e, ctx_e, "write_file", path="root.txt", content="OK")
    assert re_w["success"] is True, re_w
    assert exact.exists()


# ================================ §3.6 zero side effects on rejection
def test_R1_T06_rejection_leaves_zero_side_effects_everywhere():
    """§3.6: rejections leave files, folders, the side-effect journal and
    the event history untouched — including AFTER a prior ALLOWED governed
    write under the same mission (proving rejections do not append to an
    existing journal either)."""
    base = Path(tempfile.mkdtemp(prefix="r1_t06_"))
    ws = base / "ws"
    ws.mkdir()
    art = base / "art"
    art.mkdir()
    (ws / "seed.txt").write_text("seed")

    validator, gid, _, _ = _stack(str(art))
    engine, ctx = _engine_and_ctx(base, validator, [gid], mission="m-t06")

    # one ALLOWED governed artifact write first (creates journal + events)
    ok = _run(engine, ctx, "artifact_write", sandbox_id="sbx-t",
              path="first.txt", content="FIRST")
    assert ok["success"] is True, ok
    tree_after_ok = _tree(base)
    journal_after_ok = _journal(base, "m-t06")
    events_after_ok = _all_events(engine)
    assert journal_after_ok, "expected the allowed write to journal"

    # a battery of rejections under the SAME mission/context
    rejections = [
        ("write_file", dict(path="out.txt", content="X")),          # out of grant scope (ws not covered by this grant)
        ("artifact_write", dict(sandbox_id="../evil", path="x.txt",
                                content="X")),                       # traversal sandbox_id
    ]
    for tool, inp in rejections:
        r = _run(engine, ctx, tool, **inp)
        assert not r["success"], (tool, inp, r)

    # underivable-target rejection: needs a context WITHOUT a sandbox id
    # (input "" + context sandbox None => no derivable target at all;
    # NOTE: input "" + a NON-None context sandbox is a LEGAL derivation —
    # the decision is then grounded on the concrete contained target)
    from unified.execution import ExecutionContext
    ctx_nosbx = ExecutionContext(
        mission_id="m-t06", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id=None, grant_validator=validator, grant_ids=[gid])
    r = _run(engine, ctx_nosbx, "artifact_write", sandbox_id="",
             path="x.txt", content="X")
    assert not r["success"] and "no valid actual_target" in r["error"], r

    # and with a legacy validator on the same tree: rejected too
    legacy = lambda g, p: True  # noqa: E731
    ctx_l = ExecutionContext(
        mission_id="m-t06", run_id="r", task_id="t", attempt_id="a",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sbx-t", grant_validator=legacy, grant_ids=["g"])
    r = _run(engine, ctx_l, "write_file", path="legacy.txt", content="X")
    assert not r["success"] and "path-aware" in r["error"], r
    r = _run(engine, ctx_l, "list_dir", path=".")
    assert not r["success"] and "path-aware" in r["error"], r

    # ZERO new side effects from every rejection above
    assert _tree(base) == tree_after_ok, _tree(base)
    assert _journal(base, "m-t06") == journal_after_ok
    assert _all_events(engine) == events_after_ok
