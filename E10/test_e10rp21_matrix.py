#!/usr/bin/env python3
"""E10-RP2.1 REQUIRED TEST MATRIX — Authorization Path/Depth + Task-Bound
Verification + Verifier Error Classification (order E10-RP2.1 §2-§4),
RP2.1-T01..RP2.1-T24.

Levels of proof:
  * UNIT (direct): the governed write path is exercised through
    ``engine.tool_executor.execute_tool`` — the REAL operational chain
    (ToolExecutor._check_permissions -> path-aware bridge validator ->
    AccessAdmission.admit_grant_id with the ACTUAL resolved target and
    honest depth) — with REAL owner-approved EOE grants. Rejections are
    proven to leave ZERO new files and ZERO journal records (order §2.6).
  * UNIT (direct): the task-bound verifier chain
    (RoleCoordinator.run_verifier -> E3VerifierAgent) with fabricated
    engine state — same-name collisions across two task sandboxes with
    CONTROLLED mtimes (the exact trap the old newest-mtime glob fell
    into), missing evidence, and out-of-sandbox decoys.
  * SCENARIO (subprocess): E10/e10rp21_scenarios.py runs complete
    missions through CanonicalOrchestrator.execute_mission with the REAL
    EOE authorization (NO allow-all validator anywhere) and DISCLOSED
    fault injections at decision/machinery boundaries only.

Every test asserts against DURABLE evidence (facts.json / events.jsonl
written by the runs) or direct return values — never re-executions.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(HERE), str(REPO / "src"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from e10rp2_common import build_real_authorization  # noqa: E402


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


# ============================================================ session fixture

SCENARIO_MODES = ["collision-resolve", "verifier-read-error",
                  "verifier-exec-crash", "unprovable-attempt"]


@pytest.fixture(scope="session")
def rp21_session(tmp_path_factory):
    base = tmp_path_factory.mktemp("rp21_session")
    runs = {}
    for mode in SCENARIO_MODES:
        out = base / mode
        proc = subprocess.run(
            [sys.executable, str(HERE / "e10rp21_scenarios.py"),
             "--mode", mode, "--out", str(out),
             "--expectations", str(HERE / "evidence_rp2_expectations.json")],
            capture_output=True, text=True, timeout=600, cwd=str(REPO),
        )
        runs[mode] = {"exit": proc.returncode, "stdout_tail": proc.stdout[-1500:]}
        assert proc.returncode == 0, (
            f"scenario {mode} failed:\n{proc.stdout[-4000:]}")
    return {
        "base": base,
        "runs": runs,
        **{mode: _load(base / mode / "facts.json") for mode in SCENARIO_MODES},
    }


# ==================================================== §2 unit-level helpers

def _engine_with_grant(base: Path, *, grant_target: str = None,
                       max_depth: int = None, scope: str = "read_write",
                       with_validator: bool = True, grant_ids: list = None):
    """Real engine + real EOE authorization, exactly as the operational
    path wires them (create_execution_engine + eoe.engine_bridge). All
    parts (validator, grant, admission) come from ONE authorization stack
    so the denial REASON is always the intended one."""
    from eoe.access_gateway import (AccessAdmission, AccessLedger,
                                    GrantorService)
    from eoe.engine_bridge import build_engine_grant_validator
    from eoe.order_parser import AccessRequest, GrantKind
    from unified.execution import create_execution_engine

    os.makedirs(base, exist_ok=True)
    key = os.urandom(32)
    ledger = AccessLedger()
    grantor = GrantorService(key)
    admission = AccessAdmission(ledger, grantor, now=time.time)

    target = grant_target or str(base)
    prop = grantor.propose(
        AccessRequest(kind=GrantKind.PATH_GRANT, scope=scope, target=target))
    if max_depth is not None:
        # the OWNER constrains depth at approval (part of the signed grant)
        prop = dataclasses.replace(prop, max_depth=max_depth)
    grant = grantor.approve(prop)
    ledger.register(grant)

    validator = (build_engine_grant_validator(admission, str(base))
                 if with_validator else None)
    ids = grant_ids if grant_ids is not None else [grant.grant_id]
    engine = create_execution_engine(
        artifacts_base_dir=str(base),
        grant_validator=validator,
        grant_ids=ids,
    )
    return engine, validator, grant, admission, ledger


def _write_ctx(validator, grant_ids, *, task="task-U1"):
    from unified.execution import ExecutionContext
    return ExecutionContext(
        mission_id="m-rp21", run_id="r-rp21", task_id=task,
        attempt_id="a-rp21", agent_id="ag-rp21", agent_type="implementer",
        sandbox_id=f"sandbox-{task}",
        grant_validator=validator, grant_ids=grant_ids,
    )


def _journal_records(base: Path, mission_id: str):
    p = base / "side_effect_journal" / mission_id / "journal.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _sandbox_files(base: Path):
    return sorted(str(p.relative_to(base)) for p in base.rglob("*")
                  if p.is_file() and "sandbox-" in str(p.relative_to(base))
                  and "side_effect_journal" not in str(p))


async def _attempt_write(engine, ctx, *, path="out.txt", content=b"data",
                         tool="artifact_write"):
    return await engine.tool_executor.execute_tool(
        context=ctx, tool_name=tool,
        tool_input={"sandbox_id": ctx.sandbox_id, "path": path,
                    "content": content.decode()},
    )


def _run_write(engine, ctx, **kw):
    try:
        res = asyncio.run(_attempt_write(engine, ctx, **kw))
        return {"raised": None, "success": res.success,
                "error": res.error or ""}
    except PermissionError as e:
        return {"raised": "PermissionError", "success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"raised": type(e).__name__, "success": False, "error": str(e)}


# ============================================= §2 authorization path & depth

def test_RP21_T01_bridge_contract_explicit_no_fixed_depth():
    """§2.2/§2.3: the bridge carries NO fixed depth — the full decision
    receives the ACTUAL path and passes depth through to the admission
    contract, which computes the honest depth when none is given. The
    validator is marked path-aware; the contract (paths and depth within
    the root, never the whole root unconditionally) is documented."""
    src = (REPO / "src" / "eoe" / "engine_bridge.py").read_text("utf-8")
    # no CALL passes a literal fixed depth — the only admit_grant_id call
    # forwards the caller's depth (None => honest computation inside the
    # admission contract)
    call_lines = [l for l in src.splitlines()
                  if "admit_grant_id(" in l and "def " not in l]
    assert call_lines, "the bridge must call admit_grant_id"
    assert all("depth=0" not in l for l in call_lines), call_lines
    assert "admit_grant_id(grant_id, write=write, path=resolved, depth=depth)" in src
    assert "__path_aware__" in src
    assert "admit_grant_kind" in src  # coarse 2-arg gate is a separate, explicit API
    gw = (REPO / "src" / "eoe" / "access_gateway.py").read_text("utf-8")
    assert "_actual_depth" in gw
    assert "int | None" in gw  # depth=None => honest computation


def test_RP21_T02_engine_consumes_path_aware_validator():
    """§2.1: ToolExecutor._check_permissions grounds the authorization
    decision to the ACTUAL contained target for path-bearing tools, and
    structural containment exists at every write layer."""
    ex = (REPO / "src" / "unified" / "execution.py").read_text("utf-8")
    assert "_PATH_BEARING_TOOLS" in ex
    assert "_contained_write_target" in ex
    assert "__path_aware__" in ex
    assert "SANDBOX_CONTAINMENT_VIOLATION" in ex
    sb = (REPO / "src" / "unified" / "sandbox.py").read_text("utf-8")
    assert "SANDBOX_CONTAINMENT_VIOLATION" in sb
    wa = (REPO / "src" / "unified" / "windows_adapter.py").read_text("utf-8")
    assert "SANDBOX_CONTAINMENT_VIOLATION" in wa


def test_RP21_T03_auth_allow_real_write(tmp_path):
    """§2.5.1: a grant covering the artifacts root admits the required
    write; the file exists and the journal holds intent+performed."""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="rp21_t03_"))
    engine, validator, grant, admission, _ledger = _engine_with_grant(base)
    ctx = _write_ctx(validator, [grant.grant_id])
    out = _run_write(engine, ctx)
    assert out["raised"] is None and out["success"] is True, out
    assert (base / "sandbox-task-U1" / "out.txt").read_bytes() == b"data"
    recs = _journal_records(base, "m-rp21")
    kinds = {r["record_type"] for r in recs}
    assert "intent" in kinds and "performed" in kinds
    # the admission consulted the ACTUAL target path (not the bare root)
    targets = [u["target"] for u in admission.usage_log]
    assert targets and all(t.endswith("sandbox-task-U1/out.txt") for t in targets), targets


def test_RP21_T04_auth_depth_zero_rejects_depth_one(tmp_path):
    """§2.5.2: a max_depth=0 grant does NOT admit a write beyond the depth
    the contract permits (any file write is at depth >= 1 under the
    target). Rejection leaves ZERO new files and ZERO journal records."""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="rp21_t04_"))
    sbx = base / "sandbox-task-U1"
    engine, validator, grant, _, _ = _engine_with_grant(
        base, grant_target=str(sbx), max_depth=0)
    ctx = _write_ctx(validator, [grant.grant_id])
    out = _run_write(engine, ctx, path="out.txt")
    assert out["success"] is False, out
    assert "lacks required permission" in out["error"], out
    # §2.6 zero-side-effect proof
    assert _sandbox_files(base) == [], _sandbox_files(base)
    assert _journal_records(base, "m-rp21") == []


def test_RP21_T05_auth_depth_boundary_exact(tmp_path):
    """§2.3: the depth limit is enforced on the ACTUAL write depth with the
    explicit convention (components below the grant target): max_depth=2
    admits depth-2 writes and rejects depth-3 writes — both with the same
    grant, proving the decision uses the real path, not a constant."""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="rp21_t05_"))
    engine, validator, grant, _, _ = _engine_with_grant(base, max_depth=2)
    ctx = _write_ctx(validator, [grant.grant_id])
    # depth 2 below base: sandbox-task-U1/out.txt  -> ADMITTED
    ok = _run_write(engine, ctx, path="out.txt")
    assert ok["success"] is True, ok
    # depth 3 below base: sandbox-task-U1/sub/out.txt -> REJECTED
    deep = _run_write(engine, ctx, path="sub/out.txt")
    assert deep["success"] is False, deep
    assert "lacks required permission" in deep["error"]
    assert not (base / "sandbox-task-U1" / "sub").exists()
    # the allowed write exists; the rejected one left nothing
    assert (base / "sandbox-task-U1" / "out.txt").is_file()
    assert _sandbox_files(base) == ["sandbox-task-U1/out.txt"]


def test_RP21_T06_auth_out_of_scope_grant_rejects(tmp_path):
    """§2.5.3: a grant covering a DIFFERENT directory rejects the write;
    zero files, zero journal records."""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="rp21_t06_"))
    other = Path(tempfile.mkdtemp(prefix="rp21_t06_other_"))
    engine, validator, grant, _, _ = _engine_with_grant(
        base, grant_target=str(other))
    ctx = _write_ctx(validator, [grant.grant_id])
    out = _run_write(engine, ctx)
    assert out["success"] is False, out
    assert "lacks required permission" in out["error"]
    assert _sandbox_files(base) == []
    assert _journal_records(base, "m-rp21") == []


def test_RP21_T07_auth_missing_grant_fails_closed(tmp_path):
    """§2.5.4: validator present but NO grant ids -> fail-closed."""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="rp21_t07_"))
    engine, validator, grant, _, _ = _engine_with_grant(base, grant_ids=[])
    ctx = _write_ctx(validator, [])
    out = _run_write(engine, ctx)
    assert out["success"] is False and "lacks required permission" in out["error"]
    assert _sandbox_files(base) == []
    assert _journal_records(base, "m-rp21") == []


def test_RP21_T08_auth_missing_validator_fails_closed(tmp_path):
    """§2.5.4: NO validator at all -> fail-closed ('no validator
    available'); zero files, zero journal records."""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="rp21_t08_"))
    engine, validator, grant, _, _ = _engine_with_grant(
        base, with_validator=False)
    ctx = _write_ctx(None, ["grant-any"])
    out = _run_write(engine, ctx)
    assert out["success"] is False and "no validator available" in out["error"], out
    assert _sandbox_files(base) == []
    assert _journal_records(base, "m-rp21") == []


@pytest.mark.parametrize("evil", ["../../escape.txt", "/tmp/rp21-escape.txt",
                                  "a/../../escape.txt"])
def test_RP21_T09_containment_blocks_escape_at_every_layer(tmp_path, evil):
    """§2.3: traversal and absolute-path escapes are blocked at the
    permission gate (BEFORE any event/journal/side effect) and at the
    sandbox adapter (structural last line, legacy callers included)."""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="rp21_t09_"))
    engine, validator, grant, _, _ = _engine_with_grant(base)
    ctx = _write_ctx(validator, [grant.grant_id])
    out = _run_write(engine, ctx, path=evil)
    assert out["success"] is False, out
    assert "SANDBOX_CONTAINMENT_VIOLATION" in out["error"], out
    assert _sandbox_files(base) == []
    assert _journal_records(base, "m-rp21") == []
    assert not Path("/tmp/rp21-escape.txt").exists()

    # structural layer: direct SandboxManager call (legacy path)
    from unified.sandbox import SandboxError
    with pytest.raises(SandboxError, match="SANDBOX_CONTAINMENT_VIOLATION"):
        asyncio.run(engine.sandbox_manager.write_artifact(
            "sandbox-task-U1", evil, b"x"))


# ================================================ §3 task-bound verification

def _verifier_env(tmp: Path):
    """Minimal REAL verifier chain: a canonical orchestrator + fabricated
    engine state (tasks, attempts, per-task sandbox files)."""
    from orchestrator.canonical import create_canonical_orchestrator
    from unified.domain_model import Task, Attempt, TaskState
    from unified.agent_contract import AgentType as _AT
    from e10rp2_common import ScriptedDecomposerProvider

    orch = create_canonical_orchestrator(
        llm_provider=ScriptedDecomposerProvider("[]"),
        artifacts_base_dir=str(tmp),
        auto_approve_plans=True,
        grant_validator=None, grant_ids=None,
    )
    engine = orch.mc.engine
    return orch, engine, Task, Attempt, TaskState, _AT


def _add_task(engine, Task, _AT, tid, criteria):
    engine.tasks[tid] = Task(
        task_id=tid, run_id="r-v", mission_id="m-v", name=tid,
        description=tid, agent_type=_AT.IMPLEMENTER,
        acceptance_criteria=criteria,
    )


def _add_attempt(engine, Attempt, TaskState, tid, aid):
    engine.attempts[aid] = Attempt(
        attempt_id=aid, task_id=tid, agent_id="ag",
        state=TaskState.COMPLETED, completed_at="2026-01-01T00:00:00+00:00",
    )


def _verify(orch, tid):
    return asyncio.run(orch.role_coordinator.run_verifier(
        "m-v", "r-v", tid, []))


def test_RP21_T10_collision_each_task_from_own_file(tmp_path):
    """§3.3 DIRECT collision: two tasks write the SAME relative name with
    DIFFERENT contents; each verdict comes from the task's OWN file. The
    other task's file — even with a NEWER mtime (the exact old-glob trap)
    — cannot change the current task's verdict."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rp21_t10_"))
    orch, engine, Task, _Attempt, _TS, _AT = _verifier_env(tmp)
    _add_task(engine, Task, _AT, "task-AAA", ["file_contains:shared.txt:AAA"])
    _add_task(engine, Task, _AT, "task-BBB", ["file_contains:shared.txt:BBB"])
    _add_attempt(engine, _Attempt, _TS, "task-AAA", "att-AAA")
    _add_attempt(engine, _Attempt, _TS, "task-BBB", "att-BBB")
    sa = tmp / "sandbox-task-AAA" / "shared.txt"
    sb = tmp / "sandbox-task-BBB" / "shared.txt"
    sa.parent.mkdir(parents=True); sb.parent.mkdir(parents=True)
    sa.write_text("AAA", encoding="utf-8")
    sb.write_text("BBB", encoding="utf-8")
    # B's file is NEWER (the old newest-mtime glob would read B's file
    # while verifying A — and fail A falsely)
    os.utime(sa, (1000000000, 1000000000))
    os.utime(sb, (2000000000, 2000000000))

    ra = _verify(orch, "task-AAA")
    rb = _verify(orch, "task-BBB")
    assert ra.success is True and rb.success is True
    pa = ra.output["evidence_paths"]["shared.txt"]
    pb = rb.output["evidence_paths"]["shared.txt"]
    assert pa.endswith("sandbox-task-AAA/shared.txt"), pa
    assert pb.endswith("sandbox-task-BBB/shared.txt"), pb


def test_RP21_T11_collision_no_false_pass_from_other_sandbox(tmp_path):
    """§3.3 the false-pass trap: task B's OWN file does NOT satisfy its
    criterion while task A's file (NEWER mtime) DOES — the old glob would
    FALSELY PASS B; the task-bound verifier must FAIL B from B's own
    file, with the explicit criteria_mismatch class."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rp21_t11_"))
    orch, engine, Task, _Attempt, _TS, _AT = _verifier_env(tmp)
    _add_task(engine, Task, _AT, "task-AAA", ["file_contains:shared.txt:GOOD"])
    _add_task(engine, Task, _AT, "task-BBB", ["file_contains:shared.txt:GOOD"])
    _add_attempt(engine, _Attempt, _TS, "task-AAA", "att-AAA")
    _add_attempt(engine, _Attempt, _TS, "task-BBB", "att-BBB")
    (tmp / "sandbox-task-AAA").mkdir()
    (tmp / "sandbox-task-BBB").mkdir()
    (tmp / "sandbox-task-AAA" / "shared.txt").write_text("GOOD", encoding="utf-8")
    (tmp / "sandbox-task-BBB" / "shared.txt").write_text("BAD", encoding="utf-8")
    # A's file is NEWER: the old newest-mtime glob would read A's GOOD
    # file while verifying B -> false pass
    os.utime(tmp / "sandbox-task-BBB" / "shared.txt", (1000000000, 1000000000))
    os.utime(tmp / "sandbox-task-AAA" / "shared.txt", (2000000000, 2000000000))

    ra = _verify(orch, "task-AAA")
    rb = _verify(orch, "task-BBB")
    assert ra.success is True
    assert rb.success is False
    assert rb.output["failure_class"] == "criteria_mismatch"
    assert rb.output["evidence_paths"]["shared.txt"].endswith(
        "sandbox-task-BBB/shared.txt")


def test_RP21_T12_missing_evidence_only_from_own_sandbox(tmp_path):
    """§3.4 missing evidence: the task's own sandbox holds NO file, while
    ANOTHER task's sandbox holds a same-name file with the RIGHT content —
    the verdict must still be not_evidenced (a correct file in another
    sandbox cannot evidence this task)."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rp21_t12_"))
    orch, engine, Task, _Attempt, _TS, _AT = _verifier_env(tmp)
    _add_task(engine, Task, _AT, "task-AAA", ["file_exists:shared.txt"])
    _add_task(engine, Task, _AT, "task-BBB", ["file_exists:shared.txt",
                                              "file_contains:shared.txt:GOOD"])
    _add_attempt(engine, _Attempt, _TS, "task-AAA", "att-AAA")
    _add_attempt(engine, _Attempt, _TS, "task-BBB", "att-BBB")
    (tmp / "sandbox-task-AAA").mkdir()
    (tmp / "sandbox-task-AAA" / "shared.txt").write_text("GOOD", encoding="utf-8")
    # task-BBB sandbox intentionally LEFT EMPTY

    rb = _verify(orch, "task-BBB")
    assert rb.success is False
    assert rb.output["failure_class"] == "criteria_mismatch"
    assert rb.output["evidence_paths"] == {}


def test_RP21_T13_event_bindings_and_class_in_events(tmp_path):
    """§3.2/§4.2: the VERIFICATION_COMPLETE event carries the task
    binding, the producing attempt, the explicit failure_class, and the
    task-bound evidence paths."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rp21_t13_"))
    orch, engine, Task, _Attempt, _TS, _AT = _verifier_env(tmp)
    _add_task(engine, Task, _AT, "task-AAA", ["file_contains:f.txt:X"])
    _add_attempt(engine, _Attempt, _TS, "task-AAA", "att-AAA")
    (tmp / "sandbox-task-AAA").mkdir()
    (tmp / "sandbox-task-AAA" / "f.txt").write_text("X", encoding="utf-8")
    _verify(orch, "task-AAA")
    evs = [e for e in engine.event_bus.history
           if e.event_type.value == "verification.complete"
           and e.source == "canonical_orchestrator"]
    assert evs, "orchestrator verifier event must exist"
    raw = evs[-1].payload
    p = raw if isinstance(raw, dict) else raw.model_dump()
    assert p["task_id"] == "task-AAA"
    assert p["attempt_id"] == "att-AAA"          # producing attempt bound
    assert p["verdict"] == "evidenced"
    assert p["failure_class"] is None
    assert p["evidence_paths"] and p["evidence_paths"][0].endswith(
        "sandbox-task-AAA/f.txt")


def test_RP21_T14_unprovable_attempt_not_evidenced(tmp_path):
    """§3.4: when the producing attempt cannot be established the verdict
    is not_evidenced with the explicit provenance_unprovable class
    (fail-closed — provenance is never fabricated)."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rp21_t14_"))
    orch, engine, Task, _Attempt, _TS, _AT = _verifier_env(tmp)
    _add_task(engine, Task, _AT, "task-AAA", ["file_contains:f.txt:X"])
    # NO attempt recorded -> producing attempt unestablishable
    (tmp / "sandbox-task-AAA").mkdir()
    (tmp / "sandbox-task-AAA" / "f.txt").write_text("X", encoding="utf-8")
    r = _verify(orch, "task-AAA")
    assert r.success is False
    assert r.output["failure_class"] == "provenance_unprovable"


def test_RP21_T15_verifier_read_error_is_verifier_error(tmp_path):
    """§4.1/§4.3: a READ failure of the verifier machinery (file exists
    but reading it raises) is classified verifier_error — NEVER a
    criteria mismatch — and produces no success."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rp21_t15_"))
    orch, engine, Task, _Attempt, _TS, _AT = _verifier_env(tmp)
    _add_task(engine, Task, _AT, "task-AAA", ["file_contains:f.txt:X"])
    _add_attempt(engine, _Attempt, _TS, "task-AAA", "att-AAA")
    (tmp / "sandbox-task-AAA").mkdir()
    (tmp / "sandbox-task-AAA" / "f.txt").write_text("X", encoding="utf-8")

    import pathlib
    orig = pathlib.Path.read_text

    def boom(self, *a, **kw):
        if self.name == "f.txt":
            raise OSError("injected read failure")
        return orig(self, *a, **kw)

    pathlib.Path.read_text = boom
    try:
        r = _verify(orch, "task-AAA")
    finally:
        pathlib.Path.read_text = orig
    assert r.success is False
    assert r.output["failure_class"] == "verifier_error"
    assert any("read error" in c for c in r.output["missing_evidence"])


# ============================================ §4 classification source-level

def test_RP21_T16_no_string_heuristic_classification():
    """§4.2: the failure type is carried by the EXPLICIT failure_class
    field end-to-end; the RP2 string-sniffing heuristics are gone from
    the classification code."""
    src = (REPO / "src" / "orchestrator" / "canonical.py").read_text("utf-8")
    assert '"sandbox" in error_text.lower()' not in src
    assert '"Tool/runtime failure" in error_text' not in src
    assert 'output.get("failure_class")' in src
    ev = (REPO / "src" / "unified" / "event_catalog.py").read_text("utf-8")
    assert "failure_class" in ev and "evidence_paths" in ev


# ================================================= scenario-level assertions

def test_RP21_T17_collision_scenario_task_bound_resolution(rp21_session):
    """§3.3/§3.4 end-to-end: the engine layer passes B through a
    first-path-match collision (disclosed pre-existing engine gap); the
    task-bound orchestrator verifier CATCHES it (B not_evidenced from
    B's OWN file), the replan corrects the criteria to observed reality,
    review approves, continuation runs, and B is evidenced under v2 by
    NEWER evidence — history preserved, mission completes."""
    f = rp21_session["collision-resolve"]
    assert f["result"]["success"] is True
    assert f["verifications_by_key"]["B"][0]["verdict"] == "not_evidenced"
    assert f["verifications_by_key"]["B"][0]["failure_class"] == "criteria_mismatch"
    assert f["verifications_by_key"]["B"][1]["verdict"] == "evidenced"
    assert f["verifications_by_key"]["B"][1]["plan_version"] == "v2"
    assert f["verifications_by_key"]["A"][0]["verdict"] == "evidenced"
    b_tid = [t for k, t in f["sandbox_ids"].items() if k == "B"]
    assert f["verifications_by_key"]["B"][0]["evidence_paths"], (
        "B's failing verification must record the file it read")
    assert f["replans"] == ["v2"]
    bf = [x for x in f["verifier_failures"] if x["task_key"] == "B"]
    assert bf and bf[0]["kind"] == "plan_deviation" and bf[0]["resolved"]


def test_RP21_T18_read_error_no_replan_no_success(rp21_session):
    """§4.3 direct: a verifier READ error does NOT invoke replan_mission
    (provider never consulted) and does NOT produce a final success; the
    completion report names the current unresolved verification failure."""
    f = rp21_session["verifier-read-error"]
    assert f["result"]["success"] is False
    assert f["provider_calls"] == 0, "verifier_error must never feed replanning"
    assert f["replans"] == []
    assert f["verifications_by_key"]["A"][0]["failure_class"] == "verifier_error"
    af = [x for x in f["verifier_failures"] if x["task_key"] == "A"]
    assert af and af[0]["kind"] == "tool_runtime_failure"
    reasons = [vf["reason"] for vf in (f["completion"]["report"]["checks"]
                                       ["verification_history"]
                                       ["verification_failures"])]
    assert "current_unresolved_verification_failure" in reasons


def test_RP21_T19_exec_crash_no_replan_no_success(rp21_session):
    """§4.3 direct: the verifier EXECUTION crashing is caught and
    classified verifier_error (the run itself never crashes); no replan,
    no final success."""
    f = rp21_session["verifier-exec-crash"]
    assert f["crashed"] is False
    assert f["result"]["success"] is False
    assert f["provider_calls"] == 0
    assert f["replans"] == []
    assert f["verifications_by_key"]["A"][0]["failure_class"] == "verifier_error"
    af = [x for x in f["verifier_failures"] if x["task_key"] == "A"]
    assert af and af[0]["kind"] == "tool_runtime_failure"


def test_RP21_T20_unprovable_attempt_scenario(rp21_session):
    """§3.4 end-to-end: unestablishable producing attempt -> not_evidenced
    with explicit provenance_unprovable class; replan-ELIGIBLE (mission
    state problem) but the provider declines -> honest failure with the
    failure named in the completion report."""
    f = rp21_session["unprovable-attempt"]
    assert f["result"]["success"] is False
    assert f["verifications_by_key"]["A"][0]["failure_class"] == "provenance_unprovable"
    assert f["provider_calls"] >= 1, "provenance failure is replan-eligible"
    assert f["replans"] == []
    af = [x for x in f["verifier_failures"] if x["task_key"] == "A"]
    assert af and af[0]["kind"] == "plan_deviation"


def test_RP21_T21_scenarios_all_exit_zero(rp21_session):
    """Every scenario harness run exits 0 with all pre-registered
    expectations passing (the durable expectations_check.json)."""
    for mode, run in rp21_session["runs"].items():
        assert run["exit"] == 0, (mode, run["stdout_tail"])
        checks = _load(rp21_session["base"] / mode / "expectations_check.json")
        failed = [c for c in checks if not c["pass"]]
        assert not failed, (mode, failed)


def test_RP21_T22_scenarios_use_real_authorization(rp21_session):
    """No allow-all validator in any RP2.1 scenario: every run used the
    real eoe.engine_bridge validator and a real owner-approved grant, and
    the admission was actually consulted on the ACTUAL write targets."""
    for mode in SCENARIO_MODES:
        f = rp21_session[mode]
        assert f["grant"]["validator"] == "eoe.engine_bridge (REAL)", mode
        assert f["grant"]["grant_ids_passed"], mode
        if f["result"]["success"] or f["own_files"]:
            assert f["grant"]["admission_usage_log"], (
                f"{mode}: admission must have been consulted")
            targets = [u["target"] for u in f["grant"]["admission_usage_log"]]
            assert all("/sandbox-" in t for t in targets), (mode, targets)
