"""اختبارات عقد نقاط نهاية الإيقاف/الاستئناف (الأمر 004) — HTTP.

عقود الرفض الصادقة: 404 لدورة/لقطة غير معروفة، 409 لدورة ليست قيد
التشغيل أو مهمة لا تعمل، 422 لمعرف غير صالح (fail-closed ضد اجتياز
المسارات). المسار السعيد أثناء التشغيل مغطى في tests/core/ (مستوى
المنسق والمهمة) — هنا طبقة النقل حصرًا.

الأمر 006: مسار الدورة صار حيًا (لا mock بعد الآن) — الاختبارات التي
تحتاج دورة منجزة تحقن مصنع موجّه اختباري (test wiring §12) عبر
``routes._test_router_factory``: نقلات حتمية، وكل ما عداها حقيقي.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api import routes  # noqa: E402
from tests.test_mission import (  # noqa: E402 — سيناريو مسجل مشترك
    FAKE_SEARCH,
    REPORT_MD,
    TOOL_PLAN,
)


@pytest.fixture()
def client():
    return TestClient(routes.app)


# ---- test wiring (§12): موجّه حتمي بلا شبكة + أدوات ويب مجمدة ---- #

class ScriptedRouter:
    """موجّه اختباري — استجابات مسجلة حسب حِمل الطلب، بلا mock أدوار."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def has_live_provider(self, provider_id):
        return True  # الاختبار يعلن كل المزودات متاحة

    def live_providers(self):
        return ["fake-test-provider"]

    def chat_live(self, messages, *, provider_id=None, model=None, **_kw):
        self.calls.append((str(provider_id), str(model)))
        user = messages[-1].content
        if '"phase": "plan_tools"' in user:
            return self._wrap(TOOL_PLAN)
        if '"phase": "write_report"' in user:
            return self._wrap(REPORT_MD)
        if '"previous_reviews"' in user:  # المفكر
            return self._wrap(
                '{"tasks": [{"id": "T1", "description": "اكتب تقريرًا '
                'قصيرًا من المصادر المجلوبة", "acceptance_criteria": '
                '["الملف T1-report.md موجود ضمن الأدلة", '
                '"الملف T1-report.pdf موجود ضمن الأدلة", '
                '"الملف sources.json موجود ضمن الأدلة"]}], '
                '"risks": ["مصادر ناقصة"], "assumptions": ["الشبكة متاحة"], '
                '"evidence_required": ["مسار PDF"]}'
            )
        if '"previous_gaps"' in user:  # المدقق
            return self._wrap(
                '{"verdict": "approved", "issues": [], '
                '"required_changes": [], "score": 9.0, '
                '"evolution_score": 8.0}'
            )
        if '"criteria"' in user:  # المراجع
            return self._wrap(
                '{"verdict": "evidenced", "checks_performed": '
                '["الملفات الثلاثة موجودة"], "missing_evidence": [], '
                '"confidence": 1.0}'
            )
        if '"conflict_type"' in user:  # المُحكَّم
            return self._wrap(
                '{"decision": "retry_with_constraints", "rationale": "نقص", '
                '"escalation_to_human": false, "max_retries_remaining": 1}'
            )
        raise AssertionError(f"طلب غير متوقع: {user[:120]}")

    @staticmethod
    def _wrap(text):
        return {"text": text, "provider": "fake-test-provider",
                "model": "fake-test-model", "tokens": 10, "duration_ms": 1}


@pytest.fixture()
def live_task_env(tmp_path, monkeypatch):
    """بيئة مهمة حية معزولة: قاعدة مؤقتة + موجّه مخطوط + ويب مجمد."""
    import roles.tools as tools
    from persistence.database import build_engine, init_db, make_session_factory

    # قاعدة بيانات مؤقتة معزولة عن runtime التطوير
    engine = build_engine(tmp_path / "test.db")
    init_db(engine)
    monkeypatch.setattr(routes, "_sessions", make_session_factory(engine))
    # مساحات عمل المهام داخل tmp (TASKS_DIR نسبي إلى CWD)
    monkeypatch.chdir(tmp_path)

    def fake_search(query, **_kwargs):
        return list(FAKE_SEARCH)

    def fake_fetch(url, **_kwargs):
        return ("نص صفحة طويل بما يكفي عن الموضوع المطلوب "
                "بجوانبه المتعددة. " * 6)

    monkeypatch.setattr(tools, "web_search", fake_search)
    monkeypatch.setattr(tools, "fetch_page", fake_fetch)

    router_box = {"router": ScriptedRouter()}

    def factory(**_kwargs):
        return router_box["router"]

    monkeypatch.setattr(routes, "_test_router_factory", factory)

    # (الأمر 009) مسبار preflight مضبوط — بيئة الاختبار معزولة عن
    # الشبكة الحية عمدًا؛ الفحص الحقيقي له اختباراته في tests/readiness/.
    from readiness import registry as readiness_registry
    from readiness.probes import ProbeResult
    import datetime as _dt

    def fast_probe(sessions, capability_id, **_kwargs):
        return readiness_registry.record_probe(
            sessions, capability_id,
            ProbeResult(
                status="READY",
                reason="مضبوط لبيئة الاختبار المعزولة",
                checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                ttl_seconds=3600,
                details={"test_seam": True},
            ),
        )

    monkeypatch.setattr(routes, "_preflight_probe_fn", fast_probe)
    yield router_box


def _run_task_to_completion(client, goal="دورة كاملة لعقد الإيقاف"):
    """تشغيل مهمة حية عبر الـAPI وانتظار ختامها — يعيد (الأحداث، cycle_id)."""
    resp = client.post("/api/cycle/stream", json={"goal": goal})
    assert resp.status_code == 200, resp.text[:400]
    events = [
        json.loads(line[5:])
        for line in resp.text.split("\n\n")
        if line.startswith("data: ")
    ]
    done = [e for e in events if e.get("kind") == "task_done"]
    assert done, f"لا task_done في البث: {[e.get('kind') for e in events]}"
    return events, done[0]["details"]["cycle_id"]


def test_cycle_stop_unknown_id_404(client):
    resp = client.post(
        "/api/cycle/stop", json={"cycle_id": "cycle-nonexistent"}
    )
    assert resp.status_code == 404
    assert "غير معروفة" in resp.json()["detail"]


def test_cycle_stop_finished_cycle_409(client, live_task_env):
    """الأمر 006: الدورة المنجزة عبر المسار الحي — طلب الإيقاف يُرفض 409."""
    _events, cycle_id = _run_task_to_completion(client)
    resp = client.post("/api/cycle/stop", json={"cycle_id": cycle_id})
    assert resp.status_code == 409
    assert "ليست قيد التشغيل" in resp.json()["detail"]


def test_cycle_status_unknown_404(client):
    assert client.get("/api/cycle/status/cycle-unknown").status_code == 404


def test_cycle_status_invalid_id_422(client):
    """معرف بخط مائل = محاولة اجتياز — رفض fail-closed قبل أي مسار."""
    resp = client.get("/api/cycle/status/../etc")
    assert resp.status_code in (404, 422)


def test_cycle_status_finished_shape(client, live_task_env):
    """حالة مهمة منجزة عبر المسار الحي — الشكل الكامل بعد الانتهاء."""
    _events, cycle_id = _run_task_to_completion(client)
    resp = client.get(f"/api/cycle/status/{cycle_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "EVIDENCED"
    assert body["running"] is False
    assert body["stop_requested"] is False
    assert body["stop_receipt"] is None
    assert body["can_resume"] is False


def test_cycle_resume_invalid_id_422(client):
    resp = client.post(
        "/api/cycle/resume", json={"cycle_id": "../escape/attempt"}
    )
    assert resp.status_code == 422


def test_cycle_resume_no_snapshot_404(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # لا runtime/tasks هنا — لا لقطة أبدًا
    (tmp_path / "runtime" / "tasks" / "task-empty").mkdir(parents=True)
    resp = client.post(
        "/api/cycle/resume", json={"cycle_id": "task-empty"}
    )
    assert resp.status_code == 404
    assert "لا لقطة" in resp.json()["detail"]


def test_mission_stop_no_active_409(client):
    resp = client.post("/api/mission/stop", json={"reason": "لا شيء يعمل"})
    assert resp.status_code == 409
    assert "لا مهمة حية" in resp.json()["detail"]


def test_mission_status_idle_shape(client):
    resp = client.get("/api/mission/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False
    assert body["stop_requested"] is False
    assert body["stop_receipt"] is None


def test_mission_resume_no_snapshot_404(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resp = client.post("/api/mission/resume")
    assert resp.status_code == 404
    assert "لا لقطة إيقاف" in resp.json()["detail"]
