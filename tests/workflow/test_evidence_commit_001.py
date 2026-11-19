"""AES-P0-01: SQLite, output bytes and HTTP reads around the accept boundary."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path

from plans import SCRIPTED_PLAN

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from api import projects
from persistence.database import build_engine, make_session_factory
from workflow import auditor, service
from workflow.models import Step


_SUCCESS = (
    "EXECUTION_COMPLETED", "EVIDENCE_CREATED", "STEP_COMPLETED",
    "CHECKPOINT_CREATED",
)


@pytest.fixture
def attempt(wf_env, monkeypatch):
    sessions = wf_env["sessions"]
    live = []
    first_phase = SCRIPTED_PLAN["phases"][0]
    single_step = {
        **SCRIPTED_PLAN,
        "phases": [{**first_phase, "steps": first_phase["steps"][:1]}],
    }
    engine = wf_env["build_engine"](on_event=live.append, plan=single_step)
    pid = engine.create_project("DEF-01 fixture", "Produce deliverable.md")["id"]
    engine.generate_plan(pid)
    engine.approve_plan(pid, approved=True)
    plan = service.latest_plan(sessions, pid)
    phase = service.list_phases(sessions, pid)[0]
    step = service.phase_steps(sessions, phase["id"])[0]
    monkeypatch.setattr(projects, "_sessions", lambda: sessions)
    app = FastAPI()
    app.include_router(projects.router)
    client = TestClient(app)
    project_url = f"/api/projects/{pid}"

    def run():
        return engine._execute_step(service.get_project(sessions, pid), plan, phase,
                                    service.get_step(sessions, step["id"]))

    return {
        "sessions": sessions, "engine": engine, "run": run, "pid": pid,
        "plan": plan, "phase": phase, "step": step, "client": client,
        "url": project_url, "live": live, "monkeypatch": monkeypatch,
    }


def _outputs(a):
    response = a["client"].get(a["url"] + "/artifacts")
    assert response.status_code == 200, response.text
    return response.json()["artifacts"]


def _preview(a, *, name="deliverable.md", evidence_id=None):
    params = {"step_id": a["step"]["id"], "name": name}
    if evidence_id is not None:
        params["evidence_id"] = evidence_id
    return a["client"].get(a["url"] + "/artifacts/content", params=params)


def _success(a):
    return service.list_events(a["sessions"], a["pid"], kinds=_SUCCESS)


def _http_evidence(a, suffix):
    """Capture only the evidence fields needed to verify the HTTP contract."""
    response = a["client"].get(a["url"] + suffix)
    keys = ("id", "execution_id", "step_id", "project_id", "verdict", "files", "artifacts")

    def public_rows(rows):
        return [
            {**{key: row[key] for key in keys},
             "unready_reasons": [role["reason"] for role in row["tests"].get("unready_roles", [])]}
            for row in rows
        ]

    assert response.status_code == 200, response.text
    body = response.json()
    selected = {"evidence": public_rows(body["evidence"])}
    if "diagnostic_evidence" in body:
        selected["diagnostic_evidence"] = public_rows(body["diagnostic_evidence"])
    return {"status": response.status_code, "body": selected}


def test_blocked_provider_diagnostic_is_not_a_delivery(attempt, wf_env, record_property):
    a = attempt
    sessions, pid = a["sessions"], a["pid"]
    blocked_engine = wf_env["build_engine"](providers=())
    result = blocked_engine._execute_step(
        service.get_project(sessions, pid), a["plan"], a["phase"], a["step"],
    )
    assert result["action"] == "blocked"
    (record,) = service.list_evidence(sessions, pid)
    (execution,) = service.list_executions(sessions, pid)
    reasons = [role["reason"] for role in record["tests"]["unready_roles"]]
    assert reasons and all(reasons)
    assert record["verdict"] == "EXECUTION_BLOCKED"
    assert record["execution_id"] == execution["id"] and execution["status"] == "BLOCKED"

    before_api_reads = service.get_evidence(sessions, record["id"])
    http_evidence = _http_evidence(a, "/evidence")
    http_state = _http_evidence(a, "/state")
    artifacts = a["client"].get(a["url"] + "/artifacts")
    preview = _preview(a, evidence_id=record["id"])
    other_pid = service.create_project(sessions, name="Other project", objective="Other work")["id"]
    other = {**a, "url": f"/api/projects/{other_pid}"}
    other_evidence = _http_evidence(other, "/evidence")
    other_state = _http_evidence(other, "/state")
    observed = {
        "sqlite": {"id": record["id"], "verdict": record["verdict"], "unready_reasons": reasons},
        "GET /evidence": http_evidence,
        "GET /state": http_state,
        "GET /artifacts": {"status": artifacts.status_code, "body": artifacts.json()},
        "GET /artifacts/content": {"status": preview.status_code, "body": preview.json()},
        "other project": {"GET /evidence": other_evidence, "GET /state": other_state},
    }
    record_property("r1_http_blocked", json.dumps(observed, ensure_ascii=False))
    assert artifacts.status_code == 200 and artifacts.json() == {"artifacts": []}
    assert preview.status_code == 404
    assert other_evidence["body"]["evidence"] == []
    (diagnostic,) = http_evidence["body"]["evidence"]
    assert diagnostic["id"] == record["id"] and diagnostic["verdict"] == record["verdict"]
    assert diagnostic["unready_reasons"] == reasons
    assert diagnostic["files"] == {} and diagnostic["artifacts"] == []
    assert a["client"].get(a["url"] + "/evidence").json() == {"evidence": [record]}
    assert http_state["body"] == {"evidence": [], "diagnostic_evidence": [diagnostic]}
    assert other_state["body"] == {"evidence": [], "diagnostic_evidence": []}
    assert service.get_evidence(sessions, record["id"]) == before_api_reads


def test_evidence_list_keeps_block_history_beside_later_acceptance(attempt, wf_env):
    a = attempt
    sessions, pid = a["sessions"], a["pid"]
    blocked_engine = wf_env["build_engine"](providers=())
    result = blocked_engine._execute_step(
        service.get_project(sessions, pid), a["plan"], a["phase"], a["step"],
    )
    (blocked,) = service.list_evidence(sessions, pid)
    a["engine"].resolve_gate(pid, result["gate_id"], approved=True)
    a["engine"].resume(pid)
    assert a["run"]()["verdict"] == "PASS"
    (output,) = _outputs(a)
    rows = _http_evidence(a, "/evidence")["body"]["evidence"]
    assert [(row["id"], row["verdict"]) for row in rows] == [
        (output["evidence_id"], "PASS"), (blocked["id"], "EXECUTION_BLOCKED"),
    ]
    assert _http_evidence(a, "/state")["body"] == {
        "evidence": [rows[0]], "diagnostic_evidence": [rows[1]],
    }
    assert _preview(a, evidence_id=blocked["id"]).status_code == 404
    response = _preview(a, evidence_id=output["evidence_id"])
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == output["sha256"]


def _record_state(a, record_property):
    """Make the actual read surface available in the optional JUnit output."""
    sessions, pid = a["sessions"], a["pid"]
    step = service.get_step(sessions, a["step"]["id"])
    preview = _preview(a)
    record_property("observed", json.dumps({
        "executions": [{"id": row["id"], "status": row["status"]}
                       for row in service.list_executions(sessions, pid)],
        "step": {"id": step["id"], "status": step["status"],
                 "evidence_id": step["evidence_id"]},
        "evidence_ids": [row["id"] for row in service.list_evidence(sessions, pid)],
        "audit_verdicts": [row["verdict"] for row in service.list_audits(sessions, pid)],
        "success_events": [{"id": row["id"], "kind": row["kind"]} for row in _success(a)],
        "artifacts": [{key: row[key] for key in (
            "name", "execution_id", "evidence_id", "sha256", "delivery_status",
        )} for row in _outputs(a)],
        "preview_http_status": preview.status_code,
        "preview_sha256": hashlib.sha256(preview.content).hexdigest()
        if preview.status_code == 200 else None,
    }))


def test_rejection_retains_diagnosis_but_publishes_no_success(attempt, record_property):
    a = attempt
    sessions, pid, sid = a["sessions"], a["pid"], a["step"]["id"]
    with sessions.begin() as s:
        s.get(Step, sid).acceptance_criteria = '["missing.txt"]'
    a["run"]()
    (execution,) = service.list_executions(sessions, pid)
    (audit,) = service.list_audits(sessions, pid)
    assert execution["status"] == "FAILED"
    assert "missing.txt" in execution["error"]
    assert audit["execution_id"] == execution["id"]
    assert audit["verdict"] == "FAIL" and audit["evidence_refs"] == []
    assert audit["findings"]["missing"] == ["missing.txt"]
    assert (Path(execution["workspace"]) / "deliverable.md").is_file()
    assert service.list_evidence(sessions, pid) == []
    assert service.get_step(sessions, sid)["evidence_id"] is None
    assert _success(a) == []
    assert not any(e["kind"] in _SUCCESS for e in a["live"])
    assert _outputs(a) == [] and _preview(a).status_code == 404
    _record_state(a, record_property)


def test_acceptance_links_audit_execution_step_checkpoint_event_and_actual_bytes(
    attempt, record_property,
):
    a = attempt
    sessions, pid, sid = a["sessions"], a["pid"], a["step"]["id"]
    seen_while_auditing = []
    audit_step = auditor.audit_step

    def observe(step, execution, candidate):
        seen_while_auditing.append((_outputs(a), _success(a)))
        return audit_step(step, execution, candidate)

    a["monkeypatch"].setattr(auditor, "audit_step", observe)
    assert a["run"]()["verdict"] == "PASS"
    assert seen_while_auditing == [([], [])]
    (record,) = service.list_evidence(sessions, pid)
    (execution,) = service.list_executions(sessions, pid)
    (audit,) = service.list_audits(sessions, pid)
    step = service.get_step(sessions, sid)
    checkpoint = service.latest_checkpoint(sessions, pid)
    assert execution["status"] == step["status"] == "COMPLETED"
    assert record["execution_id"] == audit["execution_id"] == execution["id"]
    assert step["evidence_id"] == record["id"] == audit["evidence_refs"][0]
    assert record["verdict"] == audit["verdict"] == "PASS"
    assert checkpoint["state"]["last_execution"] == execution["id"]
    assert hashlib.sha256(Path(record["evidence_path"]).read_bytes()).hexdigest() == record["evidence_sha256"]
    events = service.list_events(sessions, pid, kinds=_SUCCESS + ("AUDIT_COMPLETED",))
    assert [e["kind"] for e in events] == ["AUDIT_COMPLETED", *_SUCCESS]
    assert [e["id"] for e in events] == [
        e["event_id"] for e in a["live"] if e["kind"] in {*_SUCCESS, "AUDIT_COMPLETED"}
    ]
    # Mutating the work directory does not change the detached accepted snapshot.
    (Path(execution["workspace"]) / "deliverable.md").write_text("not accepted")
    (output,) = _outputs(a)
    assert output["execution_id"] == execution["id"] and output["evidence_id"] == record["id"]
    response = _preview(a, evidence_id=record["id"])
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == output["sha256"]
    assert len(response.content) == output["bytes"]
    http_evidence = _http_evidence(a, "/evidence")
    (accepted,) = http_evidence["body"]["evidence"]
    assert accepted["id"] == record["id"] and accepted["verdict"] == "PASS"
    http_state = _http_evidence(a, "/state")
    assert http_state["body"] == {"evidence": [accepted], "diagnostic_evidence": []}
    record_property("r1_http_accepted", json.dumps({
        "GET /evidence": http_evidence,
        "GET /state": http_state,
        "GET /artifacts": {"status": 200, "body": {"artifacts": [output]}},
        "GET /artifacts/content": {
            "status": response.status_code,
            "bytes": len(response.content),
            "sha256": hashlib.sha256(response.content).hexdigest(),
        },
    }, ensure_ascii=False))
    _record_state(a, record_property)
    (Path(record["evidence_path"]).parent / "files" / output["name"]).write_text("changed")
    assert _preview(a, evidence_id=record["id"]).status_code == 409


class _Interruption(BaseException):
    """Simulate worker loss, not a model/build failure handled by the engine."""


def test_interruption_after_all_sql_writes_before_commit_remains_unpublished(
    attempt, record_property,
):
    a = attempt
    sessions, pid = a["sessions"], a["pid"]
    bind = sessions.kw["bind"]
    observed = []

    def interrupt(session, _context):
        if session.bind is not bind or not any(
            getattr(row, "kind", None) == "STEP_COMPLETED" for row in session.new
        ):
            return
        # All rows, including event rows, were flushed within this transaction.
        # An independent HTTP request/connection must still see no delivery.
        observed.append((_outputs(a), _success(a)))
        raise _Interruption

    event.listen(sessions, "after_flush", interrupt)
    try:
        with pytest.raises(_Interruption):
            a["run"]()
    finally:
        event.remove(sessions, "after_flush", interrupt)
    assert observed == [([], [])]
    (execution,) = service.list_executions(sessions, pid)
    assert execution["status"] == "RUNNING"
    assert service.get_step(sessions, a["step"]["id"])["status"] == "RUNNING"
    assert service.list_evidence(sessions, pid) == []
    assert service.list_audits(sessions, pid) == []
    assert service.latest_checkpoint(sessions, pid) is None
    assert not any(e["kind"] in _SUCCESS for e in a["live"])
    assert _success(a) == [] and _outputs(a) == [] and _preview(a).status_code == 404
    # The staged bytes do exist, but cannot be delivered through the API.
    assert (Path(execution["workspace"]).parent / "delivery/files/deliverable.md").is_file()
    _record_state(a, record_property)


def test_restart_after_commit_before_broadcast_preserves_one_delivery(
    attempt, wf_env, record_property,
):
    a = attempt
    pid, sid = a["pid"], a["step"]["id"]
    broadcast = a["engine"]._broadcast

    def interrupt(project_id, kind, payload, event_id):
        if kind == "TEST_COMPLETED":
            raise _Interruption
        broadcast(project_id, kind, payload, event_id)

    with a["monkeypatch"].context() as patch:
        patch.setattr(a["engine"], "_broadcast", interrupt)
        with pytest.raises(_Interruption):
            a["run"]()

    # Reopen the same SQLite file as a new engine and recover through the real tick.
    reopened = build_engine(wf_env["tmp_path"] / "wf-test.db")
    try:
        sessions = make_session_factory(reopened)
        from workflow.engine import ProjectEngine

        restart = ProjectEngine(sessions, router_factory=lambda: None)
        restart.assess_recovery()
        restart.resume(pid)
        assert restart.tick(pid)["action"] == "continue"
        (record,) = service.list_evidence(sessions, pid)
        (execution,) = service.list_executions(sessions, pid)
        audit = next(item for item in service.list_audits(sessions, pid) if item["step_id"] == sid)
        assert record["execution_id"] == execution["id"] == audit["execution_id"]
        # Explicit duplicate finalization of the same committed attempt is a no-op.
        assert service.commit_step_acceptance(
            sessions, project_id=pid, plan_id=a["plan"]["id"],
            plan_version=a["plan"]["version"], phase_id=a["phase"]["id"],
            step_id=sid, execution_id=execution["id"], commit=record["commit"],
            findings=audit["findings"], files=record["files"],
            evidence_path=record["evidence_path"], evidence_sha256=record["evidence_sha256"],
            tool_calls=record["tool_calls"], final_state=record["verification"]["final_state"],
            state_history=record["verification"]["state_history"],
        ) == []
        assert len(service.list_evidence(sessions, pid)) == 1
        assert len(service.list_executions(sessions, pid)) == 1
        (output,) = _outputs(a)
        assert output["evidence_id"] == record["id"]
        assert _preview(a, evidence_id=record["id"]).status_code == 200
        assert sum(e["kind"] == "EVIDENCE_CREATED" for e in _success(a)) == 1
        assert sum(e["kind"] == "EXECUTION_COMPLETED" for e in _success(a)) == 1
        assert not any(e["kind"] in _SUCCESS for e in a["live"])
        _record_state(a, record_property)
    finally:
        reopened.dispose()


@pytest.mark.parametrize(
    ("status", "audit_verdict", "visible"),
    [("FAILED", ("PASS",), False), ("COMPLETED", ("FAIL",), False),
     ("COMPLETED", ("PASS", "PARTIAL"), False), ("COMPLETED", ("PASS",), True)],
)
def test_legacy_pass_is_not_delivery_if_attempt_or_audit_disagrees(
    attempt, tmp_path, status, audit_verdict, visible,
):
    a = attempt
    sessions, pid, sid = a["sessions"], a["pid"], a["step"]["id"]
    payload = b"legacy bytes"
    (tmp_path / "deliverable.md").write_bytes(payload)
    execution_id = service.create_execution(
        sessions, sid, attempt=1, provider="fixture", model="", workspace=str(tmp_path),
    )
    eid = service.create_evidence(
        sessions, project_id=pid, step_id=sid, execution_id=execution_id,
        files={"deliverable.md": {"sha256": hashlib.sha256(payload).hexdigest(),
                                  "bytes": len(payload)}},
        tool_calls=[], verification={}, review_result={}, commit="",
        evidence_path="", evidence_sha256="", verdict="PASS",
    )
    service.update_execution(sessions, execution_id, status=status)
    service.update_step(sessions, sid, status="COMPLETED",
                        evidence_id=eid, current_execution_id=execution_id)
    for verdict in audit_verdict:
        service.create_audit(
            sessions, project_id=pid, phase_id=a["phase"]["id"], step_id=sid,
            execution_id=execution_id, plan_version=a["plan"]["version"], findings={},
            evidence_refs=[eid], commit_sha="", tests={}, verdict=verdict,
        )
    raw = service.get_evidence(sessions, eid)
    response = _preview(a, evidence_id=eid)
    assert bool(_outputs(a)) is visible
    assert response.status_code == (200 if visible else 404)
    assert service.get_evidence(sessions, eid) == raw and raw["verdict"] == "PASS"
    assert bool(a["client"].get(a["url"] + "/evidence").json()["evidence"]) is visible


def test_candidate_changed_after_audit_cannot_be_accepted(attempt, monkeypatch):
    a = attempt
    real = auditor.audit_step

    def change_candidate(step, execution, evidence):
        findings = real(step, execution, evidence)
        assert findings["verdict"] == "PASS"
        (attempt_execution_workspace(a) / "deliverable.md").write_text("changed")
        return findings

    monkeypatch.setattr(auditor, "audit_step", change_candidate)
    a["run"]()
    (audit,) = service.list_audits(a["sessions"], a["pid"])
    assert audit["verdict"] == "FAIL"
    assert "candidate bytes changed" in audit["findings"]["delivery_error"]
    assert _success(a) == [] and _outputs(a) == []


def attempt_execution_workspace(a):
    return Path(service.list_executions(a["sessions"], a["pid"])[0]["workspace"])


def test_retry_uses_new_workspace_and_only_accepted_attempt_reaches_final_audit(
    attempt, monkeypatch,
):
    a = attempt
    sessions, pid = a["sessions"], a["pid"]
    original = auditor.audit_step
    with monkeypatch.context() as patch:
        def reject(step, execution, evidence):
            findings = original(step, execution, evidence)
            return {**findings, "verdict": "FAIL", "missing": ["fixture rejection"]}

        patch.setattr(auditor, "audit_step", reject)
        a["run"]()
    rejected_path = attempt_execution_workspace(a)
    (rejected_path / "only-in-rejected-attempt.txt").write_text("rejected")

    assert a["run"]()["verdict"] == "PASS"
    assert attempt_execution_workspace(a) != rejected_path
    assert {file["name"] for file in _outputs(a)} == {"deliverable.md"}
    assert a["engine"].tick(pid)["action"] == "continue"
    a["engine"].tick(pid)
    assert service.get_project(sessions, pid)["completion_state"] == "CANDIDATE"
    assert any(row["verdict"] == "FAIL" for row in service.list_audits(sessions, pid))


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(),
                    reason="worker process exit uses fork in this Linux fixture")
@pytest.mark.parametrize("committed", [False, True])
def test_real_process_exit_at_sqlite_publication_boundary(attempt, committed):
    a = attempt
    sessions, pid = a["sessions"], a["pid"]

    def worker():
        bind = sessions.kw["bind"]
        bind.dispose(close=False)
        if committed:
            broadcast = a["engine"]._broadcast

            def exit_before_feed(project_id, kind, payload, event_id):
                if kind == "TEST_COMPLETED":
                    os._exit(77)
                broadcast(project_id, kind, payload, event_id)

            a["engine"]._broadcast = exit_before_feed
        else:
            def exit_after_flush(session, _context):
                if any(getattr(row, "kind", None) == "STEP_COMPLETED"
                       for row in session.new):
                    os._exit(77)

            event.listen(sessions, "after_flush", exit_after_flush)
        a["run"]()

    process = multiprocessing.get_context("fork").Process(target=worker)
    process.start()
    process.join(10)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("isolated worker did not exit at the designated boundary")
    assert process.exitcode == 77
    assert len(service.list_evidence(sessions, pid)) == int(committed)
    assert len(service.list_audits(sessions, pid)) == int(committed)
    assert len(_outputs(a)) == int(committed)
    assert _preview(a).status_code == (200 if committed else 404)
    assert [e["kind"] for e in _success(a)] == (list(_SUCCESS) if committed else [])
