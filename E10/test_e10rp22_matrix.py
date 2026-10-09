#!/usr/bin/env python3
"""E10-RP2.2 REQUIRED TEST MATRIX — Complete Workspace Tool Authorization &
Clean-Baseline Reconciliation (order E10-RP2.2 §2-§4), RP2.2-T01..RP2.2-T14.

Levels of proof:
  * UNIT (direct): every workspace tool (write_file / edit_file / read_file /
    list_dir / grep / find_files / file_browser) is exercised through
    ``engine.tool_executor.execute_tool`` — the REAL operational chain
    (ToolExecutor._check_permissions -> structural workspace containment ->
    path-aware bridge validator -> AccessAdmission.admit_grant_id with the
    ACTUAL resolved target and honest depth) — with REAL owner-approved EOE
    grants. Rejections are proven to leave ZERO new files/folders, ZERO
    journal records and ZERO tool events (order §2.6/§3.4).
  * UNIT (direct): the LOWER sandbox layers (SandboxManager +
    WindowsExecutorAdapter) are called DIRECTLY (legacy caller simulation)
    with escaping targets and malformed sandbox_ids — every rejection must
    leave the disk untouched: not even a sandbox FOLDER may be created
    (order §3).
  * SOURCE (static): the wiring itself is pinned — the 11 path-bearing
    tools, the workspace containment helper, the per-path disclosure gate,
    the bridge workspace universe, the OS-aware coverage in the gateway,
    and the §3 validation-before-creation ordering.

Every test asserts against durable filesystem facts, event-bus history,
journal files, or direct return values — never re-executions.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(HERE), str(REPO / "src"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


# ==================================================== workspace auth helpers

def _ws_env(*, grant_target: str = None, max_depth: int = None,
            scope: str = "read_write", with_validator: bool = True,
            grant_ids: list = None, artifacts_target: bool = False):
    """Real engine + REAL EOE authorization stack, wired exactly as the
    operational path wires it (create_execution_engine +
    eoe.engine_bridge with BOTH the artifacts root and the workspace root
    in the engine containment universe). Returns everything the tests need
    to assert denial reasons and admission usage."""
    from eoe.access_gateway import (AccessAdmission, AccessLedger,
                                    GrantorService)
    from eoe.engine_bridge import build_engine_grant_validator
    from eoe.order_parser import AccessRequest, GrantKind
    from unified.execution import create_execution_engine

    base = Path(tempfile.mkdtemp(prefix="rp22_env_"))
    ws = base / "workspace"
    ws.mkdir()
    art = base / "artifacts"

    key = os.urandom(32)
    ledger = AccessLedger()
    grantor = GrantorService(key)
    admission = AccessAdmission(ledger, grantor, now=time.time)

    target = grant_target if grant_target is not None else str(ws)
    if artifacts_target:
        target = str(art)
    prop = grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope=scope, target=target))
    if max_depth is not None:
        # the OWNER constrains depth at approval (part of the signed grant)
        prop = dataclasses.replace(prop, max_depth=max_depth)
    grant = grantor.approve(prop)
    ledger.register(grant)

    validator = (build_engine_grant_validator(
        admission, str(art), workspace_root=str(ws))
        if with_validator else None)
    ids = grant_ids if grant_ids is not None else [grant.grant_id]
    engine = create_execution_engine(
        artifacts_base_dir=str(art),
        grant_validator=validator,
        grant_ids=ids,
    )

    from unified.execution import ExecutionContext
    ctx = ExecutionContext(
        mission_id="m-rp22", run_id="r-rp22", task_id="task-U1",
        attempt_id="a-rp22", agent_id="ag-rp22", agent_type="implementer",
        workspace_root=str(ws), sandbox_id="sandbox-task-U1",
        grant_validator=validator, grant_ids=ids,
    )
    return {"base": base, "ws": ws, "art": art, "engine": engine,
            "validator": validator, "grant": grant, "ids": ids,
            "admission": admission, "ledger": ledger, "grantor": grantor,
            "ctx": ctx}


def _run(engine, ctx, tool, **inp):
    """One governed tool invocation through the REAL ToolExecutor chain."""
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
    """Every file AND folder under root (relative, sorted) — the zero-trace
    comparison basis (order §3.4: not even a folder)."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _journal_records(base: Path, mission_id: str):
    p = base / "side_effect_journal" / mission_id / "journal.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _tool_events(engine):
    from unified.event_catalog import EventType
    return [e for e in engine.event_bus.history
            if e.event_type in (EventType.TOOL_COMPLETED, EventType.TOOL_FAILED)]


# ============================================ §2 source-level wiring (T01)

def test_RP22_T01_source_wiring_all_path_bearing_tools_grounded():
    """§2.1/§2.2: ALL eleven file-access tools are in _PATH_BEARING_TOOLS
    (the four artifact families + the seven workspace tools), so NONE of
    them can end at the coarse kind-only gate; the workspace family is
    explicitly marked; the structural containment helper and the per-path
    disclosure gate exist; the bridge carries the workspace universe and
    pathlib containment (no string prefix)."""
    ex = (REPO / "src" / "unified" / "execution.py").read_text("utf-8")
    for tool in ("artifact_write", "write_artifact", "artifact_read",
                 "read_artifact", "read_file", "write_file", "edit_file",
                 "list_dir", "grep", "find_files", "file_browser"):
        assert f'"{tool}"' in ex, tool
    assert "_WORKSPACE_PATH_TOOLS" in ex
    assert "_contained_workspace_target" in ex
    assert "_path_disclosure_permitted" in ex
    assert "WORKSPACE_CONTAINMENT_VIOLATION" in ex
    br = (REPO / "src" / "eoe" / "engine_bridge.py").read_text("utf-8")
    assert "workspace_root" in br
    assert "is_relative_to" in br
    assert 'startswith(root + "/")' not in br  # OS-aware, not string prefix
    gw = (REPO / "src" / "eoe" / "access_gateway.py").read_text("utf-8")
    assert "_path_covers" in gw and "PurePath" in gw
    assert 'path.startswith(grant.target.rstrip("/") + "/")' not in gw


def test_RP22_T02_grep_contract_declares_recursive():
    """§2 (discovery D4): the grep contract declares `recursive` (the
    executor reads it; before this order pydantic dropped it and every
    governed grep call crashed with AttributeError) and the grep branch no
    longer depends on another branch's `import fnmatch`."""
    tc = (REPO / "src" / "unified" / "tool_contract.py").read_text("utf-8")
    assert "class GrepInput" in tc
    gi = tc.split("class GrepInput", 1)[1].split("class GrepOutput", 1)[0]
    assert "recursive: bool = True" in gi
    ex = (REPO / "src" / "unified" / "execution.py").read_text("utf-8")
    grep_branch = ex.split('elif tool_name == "grep"', 1)[1] \
                     .split('elif tool_name == "find_files"', 1)[0]
    assert "import fnmatch" not in grep_branch  # no branch-local import


# ================================== §4.1 in-scope grant allows writes (T03)

def test_RP22_T03_in_scope_grant_allows_workspace_writes():
    """§4.1: a grant covering the workspace admits write_file (and edit/
    read) INSIDE the covered scope; the file exists on disk and the
    admission was consulted on the ACTUAL target path."""
    env = _ws_env()
    ws, engine, ctx = env["ws"], env["engine"], env["ctx"]
    out = _run(engine, ctx, "write_file", path="deliverable.txt",
               content="CONTENT-1")
    assert out["raised"] is None and out["success"] is True, out
    assert (ws / "deliverable.txt").read_text() == "CONTENT-1"
    # edit within scope
    out = _run(engine, ctx, "edit_file", path="deliverable.txt",
               old_text="CONTENT-1", new_text="CONTENT-2")
    assert out["success"] is True, out
    assert (ws / "deliverable.txt").read_text() == "CONTENT-2"
    # read within scope
    out = _run(engine, ctx, "read_file", path="deliverable.txt")
    assert out["success"] is True and \
        out["output"]["content"] == "CONTENT-2", out
    # the admission decided on the ACTUAL resolved targets (never the root)
    targets = [u["target"] for u in env["admission"].usage_log]
    assert targets and all(t.endswith("deliverable.txt") for t in targets), \
        targets
    assert any(u["write"] for u in env["admission"].usage_log)


# ============================ §4.2 different-path grant rejects, zero trace

def test_RP22_T04_out_of_scope_grant_rejects_write_and_edit_zero_traces():
    """§4.2: a grant covering a DIFFERENT directory rejects write_file AND
    edit_file; the rejection leaves ZERO new files/folders, ZERO journal
    records, ZERO tool events (fail-closed before any side effect)."""
    other = Path(tempfile.mkdtemp(prefix="rp22_other_"))
    env = _ws_env(grant_target=str(other))
    ws, engine, ctx = env["ws"], env["engine"], env["ctx"]
    before_ws, before_art = _tree(ws), _tree(env["art"])
    events_before = len(_tool_events(engine))

    w = _run(engine, ctx, "write_file", path="evil.txt", content="X")
    e = _run(engine, ctx, "edit_file", path="evil.txt",
             old_text="X", new_text="Y")
    assert not w["success"] and "lacks required permission" in w["error"], w
    assert not e["success"] and "lacks required permission" in e["error"], e
    assert "not covered by any presented grant" in w["error"]
    # §4.2 zero traces: files, folders, journal, events
    assert _tree(ws) == before_ws
    assert _tree(env["art"]) == before_art
    assert _journal_records(env["base"], "m-rp22") == []
    assert len(_tool_events(engine)) == events_before
    assert not (ws / "evil.txt").exists()


def test_RP22_T05_artifacts_grant_does_not_authorize_workspace_writes():
    """§4.2/§4.7: a grant covering the ARTIFACTS root authorizes artifact
    writes but NOT workspace writes (different subtree of the engine
    universe) — a valid general state never covers a different target."""
    env = _ws_env(artifacts_target=True)
    engine, ctx = env["engine"], env["ctx"]
    # artifact write inside its grant: allowed
    art_ok = _run(engine, ctx, "artifact_write",
                  sandbox_id="sandbox-task-U1", path="out.txt",
                  content="A")
    assert art_ok["success"] is True, art_ok
    # workspace write with the SAME grant: rejected (target not covered)
    w = _run(engine, ctx, "write_file", path="evil.txt", content="X")
    assert not w["success"] and "lacks required permission" in w["error"], w
    assert not (env["ws"] / "evil.txt").exists()


# ==================== §4.3 outside-workspace / traversal rejected pre-trace

@pytest.mark.parametrize("evil", [
    "../../escape.txt",
    "/tmp/rp22-escape-absolute-marker.txt",
    "a/../../escape.txt",
    "sub/../../../escape.txt",
])
def test_RP22_T06_workspace_escape_rejected_before_any_trace(evil):
    """§4.3: writes outside the workspace root (traversal or absolute)
    are rejected at the permission gate BEFORE any event, journal record,
    or side effect — for write_file AND edit_file AND read_file."""
    env = _ws_env()
    ws, engine, ctx = env["ws"], env["engine"], env["ctx"]
    (ws / "legit.txt").write_text("KEEP")
    before_ws = _tree(ws)
    events_before = len(_tool_events(engine))

    for tool, extra in (("write_file", {"content": "X"}),
                        ("edit_file", {"old_text": "K", "new_text": "X"}),
                        ("read_file", {})):
        r = _run(engine, ctx, tool, path=evil, **extra)
        assert not r["success"], (tool, evil, r)
        assert "WORKSPACE_CONTAINMENT_VIOLATION" in r["error"], (tool, r)
    # zero traces: tree unchanged, no journal, no tool events
    assert _tree(ws) == before_ws
    assert _journal_records(env["base"], "m-rp22") == []
    assert len(_tool_events(engine)) == events_before
    assert not Path("/tmp/rp22-escape-absolute-marker.txt").exists()


def test_RP22_T07_symlink_escape_rejected():
    """§4.3/§2.5: a symlink INSIDE the workspace pointing OUTSIDE is an
    escape for every workspace tool (resolved containment), both for
    reads and writes."""
    env = _ws_env()
    ws, engine, ctx = env["ws"], env["engine"], env["ctx"]
    outside = Path(tempfile.mkdtemp(prefix="rp22_outside_"))
    (outside / "secret.txt").write_text("SECRET")
    os.symlink(outside / "secret.txt", ws / "leak.txt")

    r = _run(engine, ctx, "read_file", path="leak.txt")
    assert not r["success"] and \
        "WORKSPACE_CONTAINMENT_VIOLATION" in r["error"], r
    r = _run(engine, ctx, "write_file", path="leak.txt", content="X")
    assert not r["success"] and \
        "WORKSPACE_CONTAINMENT_VIOLATION" in r["error"], r
    # the outside file was neither modified nor disclosed
    assert (outside / "secret.txt").read_text() == "SECRET"


# ============== §4.4 exploration cannot exceed scope via the coarse gateway

def test_RP22_T08_exploration_root_out_of_scope_rejected():
    """§4.4: when the requested root itself is NOT covered by the grant,
    the whole exploration tool is rejected fail-closed (not partially
    executed)."""
    sub = Path(tempfile.mkdtemp(prefix="rp22_sub_"))
    env = _ws_env(grant_target=str(sub))
    engine, ctx = env["engine"], env["ctx"]
    (env["ws"] / "a.txt").write_text("public")
    for tool, extra in (("list_dir", {}), ("grep", {"pattern": "x"}),
                        ("find_files", {"pattern": "*.txt"}),
                        ("file_browser", {}), ("read_file", {})):
        r = _run(engine, ctx, tool, path="a.txt" if tool == "read_file"
                 else ".", **extra)
        assert not r["success"] and "lacks required permission" in r["error"], \
            (tool, r)


def test_RP22_T09_exploration_per_path_disclosure_depth_limited():
    """§4.4 (the core of Blockade 1's read side): with a depth-limited
    grant (max_depth=1) whose ROOT check passes, every DISCLOSED path and
    every CONTENT read is still authorized PER-PATH: deeper files are
    neither listed, found, browsed, nor grep-read — checking the folder
    root alone and allowing unlimited reading inside is impossible."""
    env = _ws_env(max_depth=1)
    ws, engine, ctx = env["ws"], env["engine"], env["ctx"]
    (ws / "top.txt").write_text("TOP_MARKER")
    (ws / "sub").mkdir()
    (ws / "sub" / "mid.txt").write_text("MID_MARKER")
    (ws / "deep" / "x").mkdir(parents=True)
    (ws / "deep" / "x" / "z.txt").write_text("DEEP_MARKER")

    # root listing allowed (root covered, depth 0)
    r = _run(engine, ctx, "list_dir", path=".", recursive=True)
    assert r["success"] is True, r
    paths = [e["path"] for e in r["output"]["entries"]]
    assert "top.txt" in paths and "sub" in paths        # depth 1: disclosed
    assert "sub/mid.txt" not in paths                    # depth 2: excluded
    assert not any(p.startswith("deep/x") and p != "deep" for p in paths)

    # grep: content of depth-2+ files is NEVER read (no MID/DEEP leak)
    r = _run(engine, ctx, "grep", pattern="MARKER", path=".")
    assert r["success"] is True, r
    files = [m["file"] for m in r["output"]["matches"]]
    assert files == ["top.txt"], files

    # find_files / file_browser: same per-path policy
    r = _run(engine, ctx, "find_files", pattern="*.txt", path=".")
    assert r["success"] is True
    assert r["output"]["files"] == ["top.txt"], r["output"]["files"]
    r = _run(engine, ctx, "file_browser", path=".")
    assert r["success"] is True
    tree_str = json.dumps(r["output"]["tree"])
    assert "top.txt" in tree_str and "mid.txt" not in tree_str

    # read_file at depth 2 under a max_depth=1 grant: rejected
    r = _run(engine, ctx, "read_file", path="sub/mid.txt")
    assert not r["success"] and "lacks required permission" in r["error"], r


def test_RP22_T10_max_depth_zero_grant_discloses_nothing_inside():
    """§4.4/§2.3: a max_depth=0 grant covers ONLY the target itself — no
    file inside is writable, readable, or disclosable (empty listing, no
    grep matches) — proving depth is enforced on the ACTUAL path, not a
    constant."""
    env = _ws_env(max_depth=0)
    ws, engine, ctx = env["ws"], env["engine"], env["ctx"]
    (ws / "inside.txt").write_text("INSIDE")
    w = _run(engine, ctx, "write_file", path="new.txt", content="X")
    assert not w["success"] and "lacks required permission" in w["error"], w
    r = _run(engine, ctx, "read_file", path="inside.txt")
    assert not r["success"] and "lacks required permission" in r["error"], r
    r = _run(engine, ctx, "list_dir", path=".")
    assert r["success"] is True and r["output"]["entries"] == [], r["output"]
    r = _run(engine, ctx, "grep", pattern="INSIDE", path=".")
    assert r["success"] is True and r["output"]["matches"] == []
    assert not (ws / "new.txt").exists()


def test_RP22_T11_depth_boundary_exact_workspace():
    """§2.3: the honest-depth convention on workspace tools: max_depth=2
    admits depth-2 (sub/x.txt) and rejects depth-3 (sub/x/y.txt) with the
    SAME grant — the decision uses the real path, never a constant."""
    env = _ws_env(max_depth=2)
    ws, engine, ctx = env["ws"], env["engine"], env["ctx"]
    ok = _run(engine, ctx, "write_file", path="sub/x.txt", content="OK")
    assert ok["success"] is True, ok
    deep = _run(engine, ctx, "write_file", path="sub/x/y.txt", content="N")
    assert not deep["success"] and "lacks required permission" in deep["error"], deep
    assert (ws / "sub" / "x.txt").is_file()
    assert not (ws / "sub" / "x" / "y.txt").exists()


# ======================================== §4.5 fail-closed on missing parts

def test_RP22_T12_missing_grant_or_validator_fail_closed():
    """§4.5: no grant ids (validator present) OR no validator at all ->
    every workspace tool is refused fail-closed, zero traces."""
    # validator present, no grants
    env = _ws_env(grant_ids=[])
    engine, ctx = env["engine"], env["ctx"]
    (env["ws"] / "a.txt").write_text("A")
    for tool, extra in (("write_file", {"content": "X"}),
                        ("read_file", {}),
                        ("list_dir", {}),
                        ("grep", {"pattern": "A"}),
                        ("find_files", {"pattern": "*"}),
                        ("file_browser", {}),
                        ("edit_file", {"old_text": "A", "new_text": "B"})):
        r = _run(engine, ctx, tool, path="a.txt" if tool in
                 ("write_file", "read_file", "edit_file") else ".", **extra)
        assert not r["success"] and "lacks required permission" in r["error"], \
            (tool, r)
    assert not (env["ws"] / "a.txt").read_text() == "X"

    # no validator at all
    env2 = _ws_env(with_validator=False)
    engine2, ctx2 = env2["engine"], env2["ctx"]
    r = _run(engine2, ctx2, "write_file", path="b.txt", content="X")
    assert not r["success"] and "no validator available" in r["error"], r
    r = _run(engine2, ctx2, "read_file", path="x.txt")
    assert not r["success"] and "no validator available" in r["error"], r
    assert not (env2["ws"] / "b.txt").exists()


# ==================== §4.6 direct lower-layer calls create NOTHING on reject

def test_RP22_T13_direct_lower_layer_rejection_creates_no_folder():
    """§3.2-§3.4 (§4.6): DIRECT calls to the lower sandbox layers
    (SandboxManager AND WindowsExecutorAdapter — legacy caller simulation)
    with escaping targets are rejected BEFORE the sandbox folder is
    created: the whole artifacts tree is byte-identical after the
    rejection (zero new files AND zero new folders), and no journal
    intent/performed records exist.

    Setup discipline: the sandbox directory legitimately exists (seeded
    by ONE valid write) and an escape symlink is planted INSIDE it — the
    zero-trace criterion compares the tree across each REJECTED call."""
    from unified.sandbox import SandboxError
    from unified.windows_adapter import WindowsExecutorAdapter

    # adapter layer
    adp_base = Path(tempfile.mkdtemp(prefix="rp22_adp_"))
    adp = WindowsExecutorAdapter(artifacts_base_dir=str(adp_base))
    # one legitimate write creates the sandbox directory + seed file
    asyncio.run(adp.write_artifact("sandbox-direct", "seed.txt", b"s"))
    # escape symlink planted INSIDE the sandbox root (the only place a
    # symlink can influence a contained target)
    outside_target = Path(tempfile.mkdtemp(prefix="rp22_outside_t_"))
    os.symlink(outside_target, adp_base / "sandbox-direct" / "lnk")
    escape_cases = [
        "../../escape.txt",                 # traversal
        "/tmp/rp22-direct-absolute.txt",    # absolute
        "lnk/escape.txt",                   # symlink to outside the root
    ]
    for evil in escape_cases:
        before = _tree(adp_base)
        with pytest.raises(SandboxError, match="SANDBOX_CONTAINMENT_VIOLATION"):
            asyncio.run(adp.write_artifact("sandbox-direct", evil, b"x"))
        assert _tree(adp_base) == before, (evil, _tree(adp_base))
    assert not Path("/tmp/rp22-direct-absolute.txt").exists()
    # and a fresh (not-yet-existing) sandbox dir stays NON-existent on a
    # rejected direct call — not even a folder is created (§3.2)
    with pytest.raises(SandboxError, match="SANDBOX_CONTAINMENT_VIOLATION"):
        asyncio.run(adp.write_artifact("sandbox-fresh", "../../escape.txt", b"x"))
    assert not (adp_base / "sandbox-fresh").exists()

    # manager layer (governed engine's own sandbox_manager, direct call)
    env = _ws_env()
    engine = env["engine"]
    art = env["art"]
    asyncio.run(engine.sandbox_manager.write_artifact(
        "sandbox-direct", "seed.txt", b"s"))
    os.symlink(outside_target, art / "sandbox-direct" / "lnk")
    for evil in ["../../escape.txt", "/tmp/rp22-direct-absolute.txt",
                 "lnk/escape.txt"]:
        before = _tree(art)
        with pytest.raises(SandboxError, match="SANDBOX_CONTAINMENT_VIOLATION"):
            asyncio.run(engine.sandbox_manager.write_artifact(
                "sandbox-direct", evil, b"x"))
        assert _tree(art) == before, (evil, _tree(art))
    # a fresh sandbox dir via the manager is not created either
    with pytest.raises(SandboxError, match="SANDBOX_CONTAINMENT_VIOLATION"):
        asyncio.run(engine.sandbox_manager.write_artifact(
            "sandbox-fresh", "../../escape.txt", b"x"))
    assert not (art / "sandbox-fresh").exists()
    # zero journal records from any rejected direct call
    assert _journal_records(env["base"], "m-rp22") == []


def test_RP22_T14_sandbox_id_traversal_rejected_before_disk():
    """§3.1 (§4.6): a malformed sandbox_id (traversal, separators,
    absolute, drive-relative, whitespace) is refused BEFORE any disk
    effect at BOTH layers — the artifacts base itself cannot be escaped
    through the sandbox_id join, and no folder is created anywhere."""
    from unified.sandbox import SandboxError, validate_sandbox_id
    from unified.windows_adapter import WindowsExecutorAdapter

    for bad in ("../evil", "a/b", "..", ".", "/abs", "C:\\x", " sbx ", ""):
        with pytest.raises(SandboxError, match="SANDBOX_ID_INVALID"):
            validate_sandbox_id(bad)
    assert validate_sandbox_id("sandbox-task-U1") == "sandbox-task-U1"

    adp_base = Path(tempfile.mkdtemp(prefix="rp22_adpid_"))
    adp = WindowsExecutorAdapter(artifacts_base_dir=str(adp_base))
    before = _tree(adp_base)
    with pytest.raises(SandboxError, match="SANDBOX_ID_INVALID"):
        asyncio.run(adp.write_artifact("../evil", "x.txt", b"x"))
    with pytest.raises(SandboxError, match="SANDBOX_ID_INVALID"):
        asyncio.run(adp.write_artifact("a/b", "x.txt", b"x"))
    assert _tree(adp_base) == before
    assert not (adp_base.parent / "evil").exists()

    # manager layer: same guarantee
    env = _ws_env()
    with pytest.raises(SandboxError, match="SANDBOX_ID_INVALID"):
        asyncio.run(env["engine"].sandbox_manager.write_artifact(
            "../evil", "x.txt", b"x"))
    assert not (env["base"] / "evil").exists()


def test_RP22_T15_direct_lower_layer_read_contained():
    """§4.4/§2.4 (acceptance 2): DIRECT legacy reads are contained too —
    SandboxManager.read_artifact and WindowsExecutorAdapter.read_artifact
    refuse targets resolving outside the sandbox custody root BEFORE any
    open()."""
    from unified.sandbox import SandboxError
    from unified.windows_adapter import WindowsExecutorAdapter

    adp_base = Path(tempfile.mkdtemp(prefix="rp22_adpr_"))
    adp = WindowsExecutorAdapter(artifacts_base_dir=str(adp_base))
    asyncio.run(adp.write_artifact("sandbox-r", "data.txt", b"OK"))
    # legitimate read works
    assert asyncio.run(adp.read_artifact("sandbox-r", "data.txt")) == b"OK"
    # escapes refused (containment, not FileNotFoundError)
    for evil in ("../../etc/passwd", "/etc/passwd"):
        with pytest.raises(SandboxError, match="SANDBOX_CONTAINMENT_VIOLATION"):
            asyncio.run(adp.read_artifact("sandbox-r", evil))
    with pytest.raises(SandboxError, match="SANDBOX_ID_INVALID"):
        asyncio.run(adp.read_artifact("../evil", "x.txt"))
    # manager layer: same guarantee
    env = _ws_env()
    sm = env["engine"].sandbox_manager
    asyncio.run(sm.write_artifact("sandbox-r", "data.txt", b"OK"))
    assert asyncio.run(sm.read_artifact("sandbox-r", "data.txt")) == b"OK"
    with pytest.raises(SandboxError, match="SANDBOX_CONTAINMENT_VIOLATION"):
        asyncio.run(sm.read_artifact("sandbox-r", "../../etc/passwd"))


# ========== §4.7 no historical/general state covers a different target

def test_RP22_T16_prior_success_never_covers_new_target():
    """§4.7: a SUCCESSFUL authorized write (journal intent+performed, the
    admission actually consulted) never covers a LATER access to a
    DIFFERENT target: an artifact write success (grant scoped to the
    task's own sandbox) does not authorize a workspace write beyond the
    workspace grant's depth, nor an artifact write to ANOTHER task's
    sandbox — every decision is per-path and per-grant."""
    from eoe.access_gateway import (AccessAdmission, AccessLedger,
                                    GrantorService)
    from eoe.engine_bridge import build_engine_grant_validator
    from eoe.order_parser import AccessRequest, GrantKind
    from unified.execution import ExecutionContext, create_execution_engine

    base = Path(tempfile.mkdtemp(prefix="rp22_t16_"))
    ws = base / "workspace"; ws.mkdir()
    art = base / "artifacts"
    own_sandbox = art / "sandbox-task-U1"

    key = os.urandom(32)
    ledger = AccessLedger(); grantor = GrantorService(key)
    admission = AccessAdmission(ledger, grantor, now=time.time)
    # grant A: the task's OWN sandbox only (artifact writes)
    ga = grantor.approve(grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope="read_write", target=str(own_sandbox))))
    ledger.register(ga)
    # grant B: the workspace, depth-limited to 2
    gb_prop = grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope="read_write", target=str(ws)))
    gb = grantor.approve(dataclasses.replace(gb_prop, max_depth=2))
    ledger.register(gb)

    ids = [ga.grant_id, gb.grant_id]
    validator = build_engine_grant_validator(admission, str(art),
                                             workspace_root=str(ws))
    engine = create_execution_engine(artifacts_base_dir=str(art),
                                     grant_validator=validator, grant_ids=ids)
    ctx = ExecutionContext(
        mission_id="m-rp22", run_id="r-rp22", task_id="task-U1",
        attempt_id="a-rp22", agent_id="ag-rp22", agent_type="implementer",
        workspace_root=str(ws), sandbox_id="sandbox-task-U1",
        grant_validator=validator, grant_ids=ids)

    # 1) successful governed artifact write into the OWN sandbox (grant A)
    a = _run(engine, ctx, "artifact_write", sandbox_id="sandbox-task-U1",
             path="out.txt", content="A")
    assert a["success"] is True, a
    kinds = {r["record_type"] for r in _journal_records(art, "m-rp22")}
    assert "intent" in kinds and "performed" in kinds
    # 2) the SAME grants still refuse a workspace write beyond depth 2
    deep = _run(engine, ctx, "write_file", path="sub/x/y.txt", content="N")
    assert not deep["success"] and "lacks required permission" in deep["error"]
    assert not (ws / "sub").exists()
    # 3) and refuse an artifact write to a DIFFERENT task's sandbox
    other = _run(engine, ctx, "artifact_write",
                 sandbox_id="sandbox-other-task", path="out.txt",
                 content="B")
    assert not other["success"] and "lacks required permission" in other["error"]
    assert not (art / "sandbox-other-task").exists()
    # 4) the prior success left exactly its own file — nothing else
    assert (own_sandbox / "out.txt").read_bytes() == b"A"


def test_RP22_T17_revoked_and_expired_grants_never_authorize():
    """§4.7: a grant that previously authorized writes loses all effect
    the moment it is REVOKED or EXPIRED — a historical verification
    result (usage log entries, prior journal records) never covers a
    current access decision."""
    env = _ws_env()
    engine, ctx = env["engine"], env["ctx"]
    ok = _run(engine, ctx, "write_file", path="first.txt", content="1")
    assert ok["success"] is True, ok

    # revoke -> same target now rejected
    env["ledger"].revoke(env["grant"].grant_id)
    r = _run(engine, ctx, "write_file", path="second.txt", content="2")
    assert not r["success"] and "lacks required permission" in r["error"], r
    assert not (env["ws"] / "second.txt").exists()

    # expired -> rejected (fresh stack, TTL squeezed to zero)
    from eoe.access_gateway import AccessAdmission, AccessLedger, GrantorService
    from eoe.engine_bridge import build_engine_grant_validator
    from eoe.order_parser import AccessRequest, GrantKind
    from unified.execution import ExecutionContext, create_execution_engine
    base = Path(tempfile.mkdtemp(prefix="rp22_exp_"))
    ws = base / "workspace"; ws.mkdir()
    key = os.urandom(32)
    ledger = AccessLedger(); grantor = GrantorService(key, ttl_seconds=0.0)
    admission = AccessAdmission(ledger, grantor, now=time.time)
    g = grantor.approve(grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope="read_write", target=str(ws))))
    ledger.register(g)
    v = build_engine_grant_validator(admission, str(base / "art"),
                                     workspace_root=str(ws))
    engine2 = create_execution_engine(artifacts_base_dir=str(base / "art"),
                                      grant_validator=v, grant_ids=[g.grant_id])
    ctx2 = ExecutionContext(
        mission_id="m-e", run_id="r-e", task_id="t-e", attempt_id="a-e",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sandbox-t", grant_validator=v, grant_ids=[g.grant_id])
    r = _run(engine2, ctx2, "write_file", path="x.txt", content="X")
    assert not r["success"], r
    assert not (ws / "x.txt").exists()


# ============================ legacy fixtures: structural containment holds

def test_RP22_T18_legacy_validator_still_structurally_contained():
    """§2.5 + E10-RP2.2-R1 §2.1/§3.1: structural containment is
    VALIDATOR-INDEPENDENT — and a legacy 2-arg fixture validator
    (permission-name check only) is now REJECTED fail-closed for
    path-bearing tools even when its 2-arg form returns True (the
    RP2.1/RP2.2 'fixtures only' acceptance is overruled by order
    E10-RP2.2-R1 §2.1). In-scope writes are refused by the permission
    gate BEFORE any side effect; traversal/absolute workspace targets
    are still refused by the structural layer (containment proof fires
    first for escapes)."""
    from unified.execution import ExecutionContext, create_execution_engine
    base = Path(tempfile.mkdtemp(prefix="rp22_leg_"))
    ws = base / "workspace"; ws.mkdir()
    engine = create_execution_engine(
        artifacts_base_dir=str(base / "art"),
        grant_validator=lambda g, p: True,   # legacy fixture validator
        grant_ids=["g-any"])
    ctx = ExecutionContext(
        mission_id="m-l", run_id="r-l", task_id="t-l", attempt_id="a-l",
        agent_id="ag", agent_type="implementer", workspace_root=str(ws),
        sandbox_id="sandbox-t", grant_validator=lambda g, p: True,
        grant_ids=["g-any"])
    # E10-RP2.2-R1 §2.1 — the legacy validator's 2-arg True is NEVER a
    # final decision for a path-bearing tool: the in-scope write is
    # refused fail-closed at the permission gate, before any effect.
    ok = _run(engine, ctx, "write_file", path="fine.txt", content="F")
    assert not ok["success"], ok
    assert "path-aware" in ok["error"], ok
    assert not (ws / "fine.txt").exists()
    # structural containment still fires FIRST for escapes
    for evil in ("../../esc.txt", "/tmp/rp22-legacy-esc.txt"):
        r = _run(engine, ctx, "write_file", path=evil, content="X")
        assert not r["success"] and \
            "WORKSPACE_CONTAINMENT_VIOLATION" in r["error"], (evil, r)
    assert not Path("/tmp/rp22-legacy-esc.txt").exists()


# ======================= §2.5 OS-aware coverage (gateway + bridge) sanity

def test_RP22_T19_gateway_coverage_os_aware():
    """§2.5: coverage/depth in the admission contract is decided on
    normalized path components (PurePath) — sibling-prefix paths that
    share a string prefix are NOT covered; trailing separators and
    duplicate slashes do not defeat the check."""
    from eoe.access_gateway import AccessAdmission, AccessLedger, \
        GrantorService, AccessDenied
    from eoe.order_parser import AccessRequest, GrantKind
    base = Path(tempfile.mkdtemp(prefix="rp22_gw_"))
    key = os.urandom(32)
    ledger = AccessLedger(); grantor = GrantorService(key)
    admission = AccessAdmission(ledger, grantor, now=time.time)
    target = base / "proj"
    target.mkdir()
    g = grantor.approve(grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope="read_write", target=str(target))))
    ledger.register(g)
    # sibling with a shared STRING prefix must NOT be covered
    sibling = base / "proj-evil"
    sibling.mkdir()
    with pytest.raises(AccessDenied):
        admission.admit_grant_id(g.grant_id, write=True,
                                 path=str(sibling / "x.txt"))
    # covered path with trailing/duplicate separators still admitted
    inside = target / "a" / "b.txt"
    inside.parent.mkdir(parents=True)
    inside.write_text("x")
    got = admission.admit_grant_id(g.grant_id, write=True,
                                   path=str(target) + "/a//b.txt")
    assert got.grant_id == g.grant_id
    # depth: honest computation on components
    assert AccessAdmission._actual_depth(g, str(inside)) == 2
    assert AccessAdmission._actual_depth(g, str(target)) == 0
    assert AccessAdmission._actual_depth(g, str(sibling)) > 10**6
