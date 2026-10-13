# -*- coding: utf-8 -*-
"""الأمر 013.12 §6 — القبول المتكامل عبر API ومسار المنتج الأصلي.

قاعدة اختبار نظيفة + مساحات عمل مؤقتة (عبر project_env): إثبات أن
  1) دليل قديم/بلا هوية لا يمنح جاهزية STRICT عبر API،
  2) التحقق الجديد الكامل (هوية + فحوص + مسبار العزل) يفتح فقط بعد
     اجتياز شرط العزل،
  3) runtime-state وpreflight وresolve_executor يتفقون على البيئة
     ومعرفها وسبب الحجب/السماح،
  4) نتيجة تنفيذ ناجحة عبر API بلا فشل مصطنع (D3) وبلا FAILURE_UNCODED،
  5) التنفيذ مسجل بمعرف البيئة (evidence.environment_id).

ملاحظة §6-6: لا نتائج mock/stub تُقدَّم هنا بوصفها إثبات عزل حي —
بروتوكول المسبار مُختبر وحدويًا وعلى HTTP فعلي في
tests/execution/test_trust_boundary_01312.py، واختبار الركيزة الحية
مُسجل NOT RUN (مضيف Windows بلا ركيزة — موثق في التقرير §4).
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from api import routes  # noqa: E402
from sqlalchemy import select as sa_select  # noqa: E402

from execution import policy as execution_policy  # noqa: E402
from execution.models import ExecutionEnvironment  # noqa: E402


# نفس بيئة اختبارات المشاريع (007) — محرك مخطط + منفذ منظم (نمط 011).
from test_projects_api import (  # noqa: E402,F401
    FakeRouter, project_env,
)


@pytest.fixture()
def client(project_env):
    return TestClient(routes.app)


@pytest.fixture()
def sessions(project_env):
    return project_env["sessions"]


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


@pytest.fixture()
def probe_seam(monkeypatch):
    """وصفة مسبار sandbox مشتقة من سجل البيئات عبر البوابة الموحدة
    (readiness تحت STRICT) — بلا إقلاع ركيزة (له اختباراته الخاصة)."""
    from execution import service as execution_service

    def fake_sandbox_probe(sessions_, **_kwargs):
        ready = any(
            execution_policy.readiness(e, "STRICT_ISOLATED")["ready"]
            for e in execution_service.list_environments(sessions_)
        )
        return {
            "status": "READY" if ready else "NOT_READY",
            "reason": "بيئة معزولة جاهزة (بوابة موحدة)" if ready
            else "لا بيئة تنفيذ معزولة جاهزة (بوابة موحدة)",
            "latency_ms": 1, "ttl_seconds": 300,
            "failure_class": "" if ready else "SANDBOX_FAILURE",
            "failure_stage": "" if ready else "STARTUP",
            "details": {"test_seam": True},
        }

    monkeypatch.setattr(
        execution_service, "sandbox_probe_result", fake_sandbox_probe
    )


def _seed_worker(sessions, *, name="worker-01312", status="HEALTHY",
                 with_identity=True, port=9841):
    """بذر عامل معلن العزل بأدلة كاملة العقد (D2: 8 فحوص) — الهوية
    تُربط بعد flush كما يفعل verify_environment (013.12 D1)."""
    evidence = execution_policy.valid_evidence("REMOTE_WORKER", True)
    stored_at = evidence.get("last_verified_at")
    stored_dt = (
        _dt.datetime.fromisoformat(stored_at) if isinstance(stored_at, str)
        else None
    )
    with sessions() as s:
        row = ExecutionEnvironment(
            name=name, backend="REMOTE_WORKER",
            endpoint=f"http://127.0.0.1:{port}", status=status,
            sandboxed=1, is_default=1,
            last_verified_at=stored_dt,
            last_probe_detail=_json.dumps(evidence, ensure_ascii=False),
        )
        s.add(row)
        s.flush()
        if with_identity:
            evidence["profile"]["environment_id"] = row.id
            row.last_probe_detail = _json.dumps(
                evidence, ensure_ascii=False)
        else:
            evidence["profile"].pop("environment_id", None)
            row.last_probe_detail = _json.dumps(
                evidence, ensure_ascii=False)
        s.commit()
        return row.id


def _break_identity(sessions, env_id, *, mode="missing"):
    """تشويه الهوية فقط (متغير معزول): missing أو mismatch."""
    with sessions() as s:
        row = s.get(ExecutionEnvironment, env_id)
        detail = _json.loads(row.last_probe_detail)
        if mode == "missing":
            detail["profile"].pop("environment_id", None)
        else:
            detail["profile"]["environment_id"] = (row.id or 0) + 500
        row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()


def _restore_identity(sessions, env_id):
    """محاكاة تحقق جديد: هوية حاضرة + زمن حاضر (بقية الأدلة كما هي)."""
    with sessions() as s:
        row = s.get(ExecutionEnvironment, env_id)
        detail = _json.loads(row.last_probe_detail)
        detail["profile"]["environment_id"] = row.id
        fresh = _now().isoformat()
        detail["last_verified_at"] = fresh
        row.last_verified_at = _dt.datetime.fromisoformat(fresh)
        row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()


def _approved_project(client):
    from tests.api.planning_wait import wait_for_plan

    out = client.post("/api/projects", json={
        "name": "مشروع 013.12", "objective": "هدف اختبار حدود الثقة",
    })
    assert out.status_code == 201, out.text
    pid = out.json()["id"]
    assert client.post(f"/api/projects/{pid}/plan/generate").status_code == 200
    wait_for_plan(client, pid)
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200, approved.text
    return pid


# ------------------------------------------------------------------ #
# §6-1 + §6-2 — الدليل بلا هوية لا يمنح جاهزية STRICT؛ الجديد الكامل
# يفتح فقط بعد استيفاء عقد العزل (مسبار ضمن الأدلة)
# ------------------------------------------------------------------ #

def test_api_identityless_evidence_blocks_then_full_evidence_opens(
        client, sessions, probe_seam):
    pid = _approved_project(client)
    env_id = _seed_worker(sessions, with_identity=False)

    # (1) دليل بلا هوية: preflight BLOCKED عبر API
    blocked = client.post(f"/api/projects/{pid}/preflight").json()
    assert blocked["preflight"]["verdict"] == "BLOCKED", blocked

    # (2) runtime-state عبر API: DEGRADED بالسبب الحرفي للهوية
    state = client.get(
        "/api/execution/runtime-state",
        params={"policy": "STRICT_ISOLATED"}).json()
    assert state["state"] != "READY", state
    assert "VERIFICATION_IDENTITY_MISSING" in _json.dumps(
        state, default=str), state.get("coherent")

    # (3) تحقق جديد مع الهوية الكاملة (وبقية العقد: مسبار العزل ضمنها)
    _restore_identity(sessions, env_id)

    opened = client.post(f"/api/projects/{pid}/preflight").json()
    assert opened["preflight"]["verdict"] == "PASS", opened
    assert opened["execution_gate"]["state"] == "OPEN", opened

    # (4) runtime-state نفسه يصبح READY على نفس معرف البيئة
    state2 = client.get(
        "/api/execution/runtime-state",
        params={"policy": "STRICT_ISOLATED"}).json()
    assert state2["state"] == "READY", state2
    assert state2["selected"]["id"] == env_id, state2


def test_api_identity_mismatch_blocks_all_surfaces(client, sessions,
                                                   probe_seam):
    """§6-3: الأسطح الثلاثة تتفق على الحجب وسببه الحرفي (هوية مختلفة)."""
    _approved_project(client)
    env_id = _seed_worker(sessions, name="worker-mismatch")
    _break_identity(sessions, env_id, mode="mismatch")

    # preflight عبر API: محجوب
    pid = _approved_project(client)
    result = client.post(f"/api/projects/{pid}/preflight").json()
    assert result["preflight"]["verdict"] == "BLOCKED", result

    # runtime-state عبر API: الحرفي MISMATCH
    state = client.get(
        "/api/execution/runtime-state",
        params={"policy": "STRICT_ISOLATED"}).json()
    assert state["state"] != "READY"
    assert "VERIFICATION_IDENTITY_MISMATCH" in _json.dumps(
        state, default=str), state.get("coherent")

    # resolve_executor (نفس الكود الذي تستدعيه مسارات API): لا منفذ
    from execution import service as execution_service

    environment, backend = execution_service.resolve_executor(
        sessions, policy="STRICT_ISOLATED")
    assert environment is None and backend is None


# ------------------------------------------------------------------ #
# §6-4 + §6-5 — نتيجة تنفيذ ناجحة عبر API: بلا فشل مصطنع، والهوية
# والعملية موثقة في مواضعها
# ------------------------------------------------------------------ #

def test_api_test_run_success_is_honest(client, sessions):
    from execution import service as execution_service

    local = execution_service.ensure_local_registered(sessions)
    local_id = local["id"]
    out = client.post(f"/api/execution/environments/{local_id}/test-run")
    assert out.status_code == 200, out.text
    body = out.json()
    # (D3) نجاح صادق: لا فشل مصطنع ولا FAILURE_UNCODED
    assert body["ok"] is True, body
    assert body["termination"] == "COMPLETED" and body["exit_code"] == 0
    assert body["failure"] is None, body.get("failure")
    assert "FAILURE_UNCODED" not in body["detail"]
    assert "FAILURE_UNCODED" not in body["stderr"]
    # (D3) معلومات العملية في موضعها المستقل
    assert body["process_info"] and isinstance(
        body["process_info"].get("pid"), int)
    # (§6-5) التنفيذ مسجل بمعرف البيئة (برهان هوية دائم)
    assert body["evidence"]["environment_id"] == local_id, body["evidence"]
