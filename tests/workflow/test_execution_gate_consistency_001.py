"""DEF-02 regression, using isolated SQLite and recording launch requests only."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import projects
from workflow import service


_OPEN_EVENTS = {"PREFLIGHT_PASS", "EXECUTION_OPENED"}
_BUILD_REASON = "node/npm missing on the build worker"


@pytest.fixture
def gate_case(wf_env, monkeypatch):
    sessions = wf_env["sessions"]
    engine = wf_env["build_engine"]()
    project_id = engine.create_project("Isolated gate fixture", "Build one file")["id"]
    engine.generate_plan(project_id)
    engine.approve_plan(project_id, approved=True)
    service.update_project(sessions, project_id, status="BLOCKED", last_error=_BUILD_REASON)
    gates = {}

    def add_build(reason=_BUILD_REASON):
        gate_id = service.open_gate(
            sessions, project_id, "PREFLIGHT_BLOCKED", reason,
            {"blocked": [{"capability_id": "build", "status": "NOT_READY"}]},
            status="BLOCKED",
        )
        gates[gate_id] = True
        return gate_id

    build_id = add_build()
    probes = []
    raw_probe = {"verdict": "PASS", "summary": "General probe passed",
                 "matrix": [], "blocked": []}

    def general_probe(*args, **kwargs):
        probes.append(raw_probe["verdict"])
        return dict(raw_probe)

    monkeypatch.setattr(engine, "_run_preflight", general_probe)
    monkeypatch.setattr(engine, "_build_tooling_still_missing", lambda gate: gates[gate["id"]])
    monkeypatch.setattr(projects, "_sessions", lambda: sessions)
    monkeypatch.setattr(projects, "_build_engine", lambda *_args, **_kwargs: engine)
    launches, steps = [], []

    def count_launch(pid, *, reason, **_kwargs):
        launches.append((pid, reason))
        return {"launched": True, "reason": "test_counter_only"}

    def count_step(*_args):
        steps.append(project_id)
        return {"action": "continue", "reason": "test_counter_only"}

    monkeypatch.setattr(projects.workflow_runner, "launch", count_launch)
    monkeypatch.setattr(projects.workflow_runner, "active_run", lambda *_args: None)
    monkeypatch.setattr(engine, "_execute_step", count_step)
    app = FastAPI()
    app.include_router(projects.router)
    return {
        "sessions": sessions, "engine": engine, "pid": project_id,
        "url": f"/api/projects/{project_id}", "client": TestClient(app),
        "gate_id": build_id, "missing": gates, "add_build": add_build,
        "launches": launches, "steps": steps, "probes": probes, "raw_probe": raw_probe,
    }


def _post(a, path="/preflight"):
    return a["client"].post(a["url"] + path)


def _gates(a):
    return {g["id"]: g["status"] for g in service.list_gates(a["sessions"], a["pid"])}


def _events(a):
    return service.list_events(a["sessions"], a["pid"], limit=100)


def _kinds(a):
    return [e["kind"] for e in _events(a)]


def _snapshot(a):
    response = a["client"].get(a["url"] + "/state")
    assert response.status_code == 200, response.text
    return response


def _record(a, record_property, scenario, *, post=None, tick=None):
    state = _snapshot(a)
    view = state.json()
    body = {"status": view["status"], "execution_gate": view["execution_gate"]}
    if "stored_status" in view:
        body["stored_status"] = view["stored_status"]
    record = {
        "GET /state": {"status": state.status_code, "body": body},
        "stored_project_status": service.get_project(a["sessions"], a["pid"])["status"],
        "stored_gates": _gates(a),
        "events": [e for e in _events(a) if e["kind"] in {
            "PREFLIGHT_RECHECKED", "GATE_KEPT_BLOCKED", "GATE_AUTO_RESOLVED",
            "PREFLIGHT_PASS", "EXECUTION_OPENED", "PROJECT_RESUMED", "ENVIRONMENT_READY",
            "EXECUTION_LAUNCH_RESULT",
        }],
        "general_probe_verdicts": a["probes"],
        "launch_requests": len(a["launches"]),
        "step_requests": len(a["steps"]),
    }
    if isinstance(post, tuple):
        method, response = post
        body = response.json()
        if method == "POST /preflight" and "project" in body:
            body["project"] = {k: body["project"][k] for k in ("id", "status", "last_error")}
        record[method] = {"status": response.status_code, "body": body}
    if tick is not None:
        record["engine_tick"] = tick
    record_property(scenario, json.dumps(record, ensure_ascii=False))


def _assert_blocked(a):
    snapshot = _snapshot(a).json()
    gate = snapshot["execution_gate"]
    assert snapshot["status"] == "BLOCKED"
    assert gate["state"] == "APPROVED_BUT_BLOCKED" and not gate["open_for_execution"]
    assert any(b["capability_id"] == "build" for b in gate["blockers"])
    assert _BUILD_REASON in gate["reason"]


def test_general_pass_does_not_launch_with_a_remaining_build_blocker(gate_case, record_property):
    a = gate_case
    response = _post(a)
    assert response.status_code == 200, response.text
    body = response.json()
    _record(a, record_property, "blocked_preflight", post=("POST /preflight", response))
    actual = (body["project"]["status"], body["preflight"]["verdict"],
              body["execution_gate"]["state"], _gates(a)[a["gate_id"]],
              body["launch"]["launched"], len(a["launches"]))
    assert actual == ("BLOCKED", "BLOCKED", "APPROVED_BUT_BLOCKED", "BLOCKED", False, 0)
    assert body["preflight"]["probe_verdict"] == "PASS"
    assert _BUILD_REASON in body["preflight"]["summary"]
    assert not _OPEN_EVENTS.intersection(_kinds(a))
    _assert_blocked(a)


@pytest.mark.parametrize("stored", ["BLOCKED", "READY"])
def test_resume_refuses_a_persisted_build_blocker(gate_case, stored, record_property):
    a = gate_case
    service.update_project(a["sessions"], a["pid"], status=stored)
    response = _post(a, "/resume")
    _record(a, record_property, f"resume_{stored.lower()}", post=("POST /resume", response))
    assert response.status_code == 409 and _BUILD_REASON in response.json()["detail"]
    assert _gates(a)[a["gate_id"]] == "BLOCKED"
    assert not (_OPEN_EVENTS | {"PROJECT_RESUMED"}).intersection(_kinds(a))
    assert not a["launches"]
    _assert_blocked(a)


@pytest.mark.parametrize("stored", ["BLOCKED", "READY", "RUNNING"])
def test_tick_cannot_enter_step_before_persisted_gate_clears(gate_case, stored, record_property):
    a = gate_case
    service.update_project(a["sessions"], a["pid"], status=stored)
    result = a["engine"].tick(a["pid"])
    _record(a, record_property, f"tick_{stored.lower()}", tick=result)
    assert result["action"] == "blocked"
    assert not a["steps"] and not a["launches"]
    assert not _OPEN_EVENTS.intersection(_kinds(a))
    assert _gates(a)[a["gate_id"]] == "BLOCKED"
    _assert_blocked(a)


def test_state_overrules_historical_ready_and_pass_without_changing_history(gate_case, record_property):
    a = gate_case
    service.update_project(a["sessions"], a["pid"], status="READY")
    historical = service.add_event(a["sessions"], a["pid"], "PREFLIGHT_PASS",
                                   {"verdict": "PASS", "summary": "Historical unguarded PASS"})
    _record(a, record_property, "historical_ready")
    _assert_blocked(a)
    assert service.get_project(a["sessions"], a["pid"])["status"] == "READY"
    assert _gates(a)[a["gate_id"]] == "BLOCKED"
    assert _events(a)[-1]["id"] == historical
    assert not a["launches"] and not a["probes"]


def test_clearing_last_blocker_opens_and_requests_one_launch(gate_case, record_property):
    a = gate_case
    a["missing"][a["gate_id"]] = False
    response = _post(a)
    _record(a, record_property, "cleared", post=("POST /preflight", response))
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["project"]["status"] == "READY"
    assert body["preflight"]["verdict"] == "PASS"
    assert body["execution_gate"]["state"] == "OPEN"
    assert body["launch"]["launched"] and len(a["launches"]) == 1
    assert _gates(a)[a["gate_id"]] == "APPROVED"
    repeated = _post(a)
    _record(a, record_property, "repeat_after_clear", post=("POST /preflight", repeated))
    assert repeated.status_code == 200
    assert repeated.json()["execution_gate"]["state"] == "OPEN"
    assert not repeated.json()["launch"]["launched"] and len(a["launches"]) == 1
    kinds = _kinds(a)
    assert kinds.index("GATE_AUTO_RESOLVED") < kinds.index("EXECUTION_OPENED")
    assert kinds.count("PREFLIGHT_PASS") == kinds.count("EXECUTION_OPENED") == 1


def test_partial_clear_keeps_remaining_gate_and_reason(gate_case, record_property):
    a = gate_case
    cleared = a["add_build"]("different build blocker already fixed")
    a["missing"][cleared] = False
    response = _post(a)
    _record(a, record_property, "two_gates_one_cleared", post=("POST /preflight", response))
    assert response.status_code == 200, response.text
    assert _gates(a)[cleared] == "APPROVED"
    assert _gates(a)[a["gate_id"]] == "BLOCKED"
    assert response.json()["preflight"]["verdict"] == "BLOCKED"
    assert "different build blocker already fixed" not in response.json()["execution_gate"]["reason"]
    assert not a["launches"] and not _OPEN_EVENTS.intersection(_kinds(a))
    _assert_blocked(a)


def test_general_probe_cannot_resolve_a_pending_owner_decision(gate_case, record_property):
    a = gate_case
    a["missing"][a["gate_id"]] = False
    owner_gate = service.open_gate(a["sessions"], a["pid"], "ESCALATION", "Owner decision required")
    response = _post(a)
    _record(a, record_property, "owner_decision_remains", post=("POST /preflight", response))
    assert response.status_code == 200, response.text
    body = response.json()
    assert _gates(a)[owner_gate] == "PENDING"
    assert _gates(a)[a["gate_id"]] == "APPROVED"
    assert body["project"]["status"] == "BLOCKED"
    assert body["execution_gate"]["state"] == "APPROVED_BUT_BLOCKED"
    assert "Owner decision required" in body["execution_gate"]["reason"]
    assert not a["launches"] and not _OPEN_EVENTS.intersection(_kinds(a))


def test_concurrent_rechecks_request_one_launch(gate_case, monkeypatch, record_property):
    a = gate_case
    a["missing"][a["gate_id"]] = False
    probe = a["engine"]._run_preflight
    barrier = Barrier(2, timeout=5)

    def simultaneous_probe(*args, **kwargs):
        result = probe(*args, **kwargs)
        barrier.wait()
        return result

    monkeypatch.setattr(a["engine"], "_run_preflight", simultaneous_probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: _post(a), range(2)))
    _record(a, record_property, "concurrent_clear", post=("POST /preflight", responses[0]))
    assert all(r.status_code == 200 for r in responses)
    assert all(r.json()["execution_gate"]["state"] == "OPEN" for r in responses)
    assert sorted(r.json()["launch"]["launched"] for r in responses) == [False, True]
    assert len(a["launches"]) == 1
    assert _kinds(a).count("EXECUTION_OPENED") == 1


def test_clearing_last_blocker_in_tick_does_not_emit_open_twice(gate_case, record_property):
    a = gate_case
    a["missing"][a["gate_id"]] = False
    result = a["engine"].tick(a["pid"])
    _record(a, record_property, "cleared_in_tick", tick=result)
    assert result["action"] == "continue" and len(a["steps"]) == 1
    assert not a["launches"]
    kinds = _kinds(a)
    assert kinds.count("PREFLIGHT_PASS") == kinds.count("EXECUTION_OPENED") == 1


def test_initial_probe_cannot_open_after_a_blocker_is_recorded(gate_case, monkeypatch):
    a = gate_case
    service.auto_resolve_gate(a["sessions"], a["gate_id"])
    service.update_project(a["sessions"], a["pid"], status="READY")
    probe = a["engine"]._run_preflight

    def record_new_gate(*args, **kwargs):
        a["add_build"]()
        return probe(*args, **kwargs)

    monkeypatch.setattr(a["engine"], "_run_preflight", record_new_gate)
    assert a["engine"].tick(a["pid"])["action"] == "blocked"
    assert not a["steps"] and not a["launches"]
    assert not _OPEN_EVENTS.intersection(_kinds(a))
    _assert_blocked(a)


def test_explicit_run_does_not_launch_a_new_loop_while_build_blocked(gate_case):
    a = gate_case
    response = _post(a, "/run/stream")
    assert response.status_code == 409 and _BUILD_REASON in response.json()["detail"]
    assert not a["launches"]


def _conflict_once(a, monkeypatch):
    a["missing"][a["gate_id"]] = False

    def count_launch(pid, *, reason, **_kwargs):
        a["launches"].append((pid, reason))
        if len(a["launches"]) == 1:
            raise projects.workflow_runner.RunConflict("another project is busy")
        return {"launched": True, "reason": "isolated counter"}

    monkeypatch.setattr(projects.workflow_runner, "launch", count_launch)


def test_explicit_recheck_retries_conflict_once_without_reopening(
    gate_case, monkeypatch, record_property,
):
    a = gate_case
    _conflict_once(a, monkeypatch)
    first = _post(a)
    _record(a, record_property, "first_conflict", post=("POST /preflight", first))
    second = _post(a)
    _record(a, record_property, "retry_after_conflict", post=("POST /preflight", second))
    third = _post(a)
    _record(a, record_property, "repeat_after_success", post=("POST /preflight", third))
    assert first.status_code == second.status_code == third.status_code == 200
    assert all(r.json()["execution_gate"]["state"] == "OPEN" for r in (first, second, third))
    assert first.json()["launch"]["reason"] == "conflict"
    assert second.json()["launch"]["launched"]
    assert not third.json()["launch"]["launched"]
    assert len(a["launches"]) == 2
    assert _kinds(a).count("EXECUTION_OPENED") == _kinds(a).count("PREFLIGHT_PASS") == 1


@pytest.mark.parametrize("succeeds", [True, False])
def test_concurrent_retries_share_one_conflict_receipt(
    gate_case, monkeypatch, record_property, succeeds,
):
    a = gate_case
    _conflict_once(a, monkeypatch)
    assert _post(a).json()["launch"]["reason"] == "conflict"
    if not succeeds:
        def still_busy(pid, *, reason, **_kwargs):
            a["launches"].append((pid, reason))
            raise projects.workflow_runner.RunConflict("another project is still busy")

        monkeypatch.setattr(projects.workflow_runner, "launch", still_busy)
    probe = a["engine"]._run_preflight
    barrier = Barrier(2, timeout=5)

    def simultaneous_probe(*args, **kwargs):
        barrier.wait()
        return probe(*args, **kwargs)

    monkeypatch.setattr(a["engine"], "_run_preflight", simultaneous_probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: _post(a), range(2)))
    for index, response in enumerate(responses):
        _record(a, record_property, f"concurrent_conflict_retry_{succeeds}_{index}",
                post=("POST /preflight", response))
    assert all(r.status_code == 200 for r in responses)
    if succeeds:
        assert sorted(r.json()["launch"]["launched"] for r in responses) == [False, True]
    else:
        assert {r.json()["launch"]["reason"] for r in responses} == {"conflict", "not_requested"}
    assert len(a["launches"]) == 2 and _kinds(a).count("EXECUTION_OPENED") == 1


def test_conflict_retry_waits_until_no_active_loop(gate_case, monkeypatch):
    a = gate_case
    _conflict_once(a, monkeypatch)
    assert _post(a).json()["launch"]["reason"] == "conflict"
    with monkeypatch.context() as patch:
        patch.setattr(projects.workflow_runner, "active_run",
                      lambda *_args: {"project_id": a["pid"] + 1})
        assert not _post(a).json()["launch"]["launched"]
        assert len(a["launches"]) == 1
    assert _post(a).json()["launch"]["launched"] and len(a["launches"]) == 2


def test_recheck_observes_existing_loop_without_claiming_a_new_launch(gate_case, monkeypatch):
    a = gate_case
    _conflict_once(a, monkeypatch)
    assert _post(a).json()["launch"]["reason"] == "conflict"
    with monkeypatch.context() as patch:
        patch.setattr(projects.workflow_runner, "active_run",
                      lambda *_args: {"project_id": a["pid"], "job_id": 17})
        assert _post(a).json()["launch"] == {
            "launched": False, "reason": "active_job_continues",
            "project_id": a["pid"], "job_id": 17,
        }
    assert not _post(a).json()["launch"]["launched"] and len(a["launches"]) == 1


def test_successful_explicit_stream_consumes_the_same_opening(gate_case, monkeypatch):
    a = gate_case
    _conflict_once(a, monkeypatch)
    assert _post(a).json()["launch"]["reason"] == "conflict"
    stream = _post(a, "/run/stream?after=0")
    assert stream.status_code == 200 and '"launched": true' in stream.text
    assert not _post(a).json()["launch"]["launched"]
    assert len(a["launches"]) == 2
    assert _kinds(a).count("EXECUTION_OPENED") == 1


def _open_owner_decision(a):
    service.auto_resolve_gate(a["sessions"], a["gate_id"])
    service.update_project(a["sessions"], a["pid"], status="READY")
    return service.open_gate(a["sessions"], a["pid"], "ESCALATION", "Owner decision required")


def _record_stream(a, response, record_property, scenario):
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines() if line.startswith("data: ")
    ]
    record_property(scenario, json.dumps({
        "status": response.status_code,
        "body": events if response.status_code == 200 else response.json(),
        "launch_requests": len(a["launches"]),
        "gates": _gates(a),
    }))
    return events


@pytest.mark.parametrize("with_build", [False, True])
def test_new_stream_denies_pending_owner_decision(gate_case, record_property, with_build):
    a = gate_case
    owner_gate = _open_owner_decision(a)
    if with_build:
        a["add_build"]("A newer build blocker")
    response = _post(a, "/run/stream?after=0")
    _record_stream(a, response, record_property,
                   "pending_owner_and_build_no_loop" if with_build else "pending_owner_no_loop")
    assert response.status_code == 409
    assert response.json()["detail"] == "Owner decision required"
    assert not a["launches"] and _gates(a)[owner_gate] == "PENDING"


def test_pending_owner_can_attach_to_same_active_loop_without_launch(
    gate_case, monkeypatch, record_property,
):
    a = gate_case
    owner_gate = _open_owner_decision(a)
    handles = iter([{"project_id": a["pid"], "job_id": 17}])
    monkeypatch.setattr(projects.workflow_runner, "active_run",
                        lambda *_args: next(handles, None))
    response = _post(a, "/run/stream?after=0")
    events = _record_stream(a, response, record_property, "pending_owner_active_loop")
    assert response.status_code == 200
    assert events[0]["kind"] == "run.start"
    assert events[0]["payload"]["status"] == "BLOCKED"
    assert not events[0]["payload"]["launch"]["launched"]
    assert events[-1]["kind"] == "run.done" and events[-1]["payload"]["job_id"] == 17
    assert not a["launches"] and _gates(a)[owner_gate] == "PENDING"
