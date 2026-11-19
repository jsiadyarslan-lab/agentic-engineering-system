"""Exercise explicit search requirements on project HTTP with a launch counter."""

import copy
import pytest
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import projects
from persistence.database import build_engine, init_db, make_session_factory
from providers_registry import registry as providers
from readiness import registry
from tests.readiness.test_preflight import _ddg, _not_ready, _ready, _sandbox_ready
from tests.workflow.conftest import ScriptedPlanner, ScriptedRouter
from tests.workflow.plans import SCRIPTED_PLAN
from workflow import service
from workflow.engine import ProjectEngine


AUDIT = [
    ("offline_dashboard", "Build an offline static dashboard. Web search is not required."),
    ("bundled_sources", "Build a parser using only bundled sources. No network research."),
    ("optional_news_ar", "أنشئ موقعًا إخباريًا ثابتًا. بحث الويب اختياري."),
]


def run_case(name, objective, *, criterion=None, project_dependency=False, step_gate=False):
    with TemporaryDirectory(prefix="aes-def03-audit-") as temp, ExitStack() as patches:
        db = build_engine(Path(temp) / "base.db")
        patches.callback(db.dispose)
        init_db(db)
        sessions = make_session_factory(db)
        providers.ensure_seeded(sessions)
        registry.ensure_capabilities(sessions)
        _sandbox_ready(sessions)
        failure = "Isolated search provider reports NOT_READY"
        _ddg(sessions, "NOT_READY", failure)

        probe_calls = Counter()
        launch_requests = []

        def probe(current_sessions, capability, **kwargs):
            probe_calls[capability] += 1
            result = _not_ready(failure) if capability == "web_search" else _ready(capability)
            return registry.record_probe(current_sessions, capability, result)

        def launch(pid, *, reason, **kwargs):
            launch_requests.append(pid)
            return {"launched": True, "reason": "counter_only"}

        plan_data = copy.deepcopy(SCRIPTED_PLAN)
        if criterion is not None:
            plan_data["acceptance_criteria"].append(criterion)
        if project_dependency:
            plan_data["dependencies"] = ["web_search"]
        if step_gate:
            plan_data["phases"][0]["steps"][0]["dependencies"] = ["web_search"]
        engine = ProjectEngine(
            sessions, router_factory=lambda: ScriptedRouter(("nvidia", "openai_compatible")),
            planner_factory=lambda: ScriptedPlanner(plan=plan_data),
            probe_injections={"search_fn": lambda _: []},
        )
        pid = engine.create_project("DEF-03 isolated fixture", objective)["id"]
        engine.generate_plan(pid)
        engine.approve_plan(pid, approved=True)
        step_id = None
        if step_gate:
            plan = service.latest_plan(sessions, pid)
            phase = service.active_phases(sessions, plan["id"])[0]
            step_id = service.phase_steps(sessions, phase["id"])[0]["id"]
            service.open_gate(
                sessions, pid, "PREFLIGHT_BLOCKED", "Stored search gate for step",
                {"step_id": step_id, "blocked": [
                    {"capability_id": "web_search", "status": "STALE",
                     "reason": "Stored reason at earlier attempt"},
                ]}, status="BLOCKED",
            )
            service.update_project(sessions, pid, status="BLOCKED")
        patches.enter_context(patch.object(registry, "run_probe", probe))
        patches.enter_context(patch.object(projects, "_sessions", lambda: sessions))
        patches.enter_context(patch.object(projects, "_build_engine", lambda: engine))
        patches.enter_context(patch.object(projects.workflow_runner, "launch", launch))
        patches.enter_context(patch.object(projects.workflow_runner, "active_run", lambda *_: None))
        app = FastAPI()
        app.include_router(projects.router)
        with TestClient(app) as client:
            response = client.post(f"/api/projects/{pid}/preflight")
            state_response = client.get(f"/api/projects/{pid}/state")
        assert response.status_code == state_response.status_code == 200
        body = response.json()
        state = state_response.json()
        check = body["preflight"]
        return {
            "case": name, "objective": objective, "plan_criterion": criterion,
            "plan_dependencies": plan_data["dependencies"], "fixture_step_id": step_id,
            "post_preflight": {
                "http": response.status_code, "verdict": check["verdict"],
                "probe_verdict": check["probe_verdict"],
                "blocked": check["blocked"],
                "search_matrix": [r for r in check["matrix"] if r["capability_id"] == "web_search"],
                "project_status": body["project"]["status"],
                "gate_state": body["execution_gate"]["state"],
                "launch": body["launch"],
            },
            "get_state": {"http": state_response.status_code, "status": state["status"],
                          "execution_gate": state["execution_gate"]},
            "search_probe_calls": probe_calls["web_search"],
            "probe_calls": dict(probe_calls),
            "launch_requests": len(launch_requests),
            "events": [
                {"kind": event["kind"], "blocked": event["payload"].get("blocked", [])}
                for event in service.list_events(sessions, pid, limit=100)
                if event["kind"] in ("PREFLIGHT_RECHECKED", "PREFLIGHT_PASS", "EXECUTION_OPENED")
            ],
        }



@pytest.mark.parametrize("objective", [goal for _, goal in AUDIT] + [
    "اريد بناء منصة OSINT",
    "Use bundled sources to build a news dashboard",
    "Inspect source links only. No live research.",
])
@pytest.mark.parametrize("where", ["goal", "criterion"])
def test_project_does_not_probe_optional_search(objective, where):
    c = run_case(where, objective if where == "goal" else "Build one file",
                 criterion=objective if where == "criterion" else None)
    assert c["post_preflight"]["verdict"] == "PASS"
    assert c["search_probe_calls"] == 0
    assert c["launch_requests"] == 1


@pytest.mark.parametrize("goal", [
    "Search the web for current official publications.",
    "ابحث في الويب عن منشورات رسمية حديثة.",
    "Create a local report.",
    "Build a dashboard. Search the web for its real-time inputs.",
])
def test_explicit_text_or_persisted_project_dependency_blocks(goal):
    c = run_case("explicit", goal, project_dependency=goal == "Create a local report.")
    assert c["post_preflight"]["verdict"] == "BLOCKED"
    assert c["post_preflight"]["blocked"][0]["capability_id"] == "web_search"
    assert c["search_probe_calls"] == 1
    assert c["launch_requests"] == 0


def test_step_recheck_reports_current_measurement_without_losing_identity():
    c = run_case("step", "Build one file", step_gate=True)
    assert c["post_preflight"]["verdict"] == "BLOCKED"
    blocked = c["post_preflight"]["blocked"]
    assert len(blocked) == 1, blocked
    assert blocked[0]["status"] == "NOT_READY"
    assert blocked[0]["step_id"] == c["fixture_step_id"]
    assert blocked[0]["gate_id"] > 0
    state_gate = c["get_state"]["execution_gate"]
    assert state_gate["step_id"] == c["fixture_step_id"]
    assert state_gate["blockers"][0]["status"] == "NOT_READY"
    assert c["launch_requests"] == 0
