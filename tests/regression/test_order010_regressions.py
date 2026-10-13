"""اختبارات انحدار الأمر 010 (§39) — تمنع عودة مشاكل اللقطة تحديدًا.

الثمانية المرجعية حرفيًا:
1. رسالة ثانية → نفس المحادثة (وليس محادثة جديدة)
2. رد عربي → RTL صحيح
3. إنجليزي/كود → LTR صحيح
4. نقرة مشروع → المشروع يُحمّل (جذر الصفحة السوداء)
5. تحديث صفحة المشروع → المشروع يُحمّل (توجيه دائم)
6. مسبار بيئة READY → المنفذ الفعلي يوافق (مصدر واحد)
7. مهمة ببيئة غير متاحة → حالة محجوبة واضحة
8. بحث معطل + جلب متاح → قرار واعٍ بالقدرات
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from api import routes  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)


def sse_events(resp):
    """تفكيك استجابة SSE إلى قائمة أحداث JSON (نفس عقد tests/api)."""
    import json as _json

    return [
        _json.loads(line[5:])
        for line in resp.text.split("\n\n")
        if line.startswith("data: ")
    ]
from readiness import preflight, registry  # noqa: E402
from readiness.probes import ProbeResult  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "regression-test.db")
    init_db(engine)
    factory = make_session_factory(engine)
    registry.ensure_capabilities(factory)
    return factory


def _sandbox_env_ready(sessions):
    """(011 §14) قدرة sandbox تُشتق من سجل البيئات — بذر بيئة معزولة
    جاهزة بأدلة كاملة العقد (013.11 §5) كي يبقى اختبار الانحدار 8
    محصورًا بعقد البحث وحده. العزل يُحاكى بعامل بعيد معلن العزل —
    صف LOCAL المحلي يتبع توفر الركيزة فعليًا (011 §4-§5)."""
    import json as _json

    from execution import policy as execution_policy
    from execution.models import ExecutionEnvironment

    detail = execution_policy.valid_evidence("REMOTE_WORKER", True)
    with sessions() as s:
        row = ExecutionEnvironment(
            name="worker-sandbox-seed", backend="REMOTE_WORKER",
            endpoint="http://127.0.0.1:9796", status="READY",
            sandboxed=1, is_default=1,
            last_verified_at=_dt.datetime.now(_dt.timezone.utc),
            last_probe_detail=_json.dumps(detail, ensure_ascii=False),
        )
        s.add(row)
        s.flush()
        detail["profile"]["environment_id"] = row.id
        row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()
        return row.id


def _seamed(**statuses):
    def probe(sessions_, capability_id, **_kw):
        return registry.record_probe(
            sessions_, capability_id,
            ProbeResult(
                status=statuses.get(capability_id, "READY"),
                reason="مضبوط لاختبار الانحدار",
                checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            ),
        )
    return probe


# ---------- (1) رسالة ثانية → نفس المحادثة ----------

def test_regression_second_message_same_conversation(client):
    first = sse_events(client.post("/api/chat/stream", json={
        "message": "الرسالة الأولى",
    }))
    conv_id = first[0]["details"]["conversation_id"]
    second = sse_events(client.post("/api/chat/stream", json={
        "message": "الرسالة الثانية", "conversation_id": conv_id,
    }))
    assert second[0]["kind"] == "conversation.bind"
    assert second[0]["details"]["conversation_id"] == conv_id
    assert second[0]["details"]["created"] is False
    listed = client.get("/api/conversations").json()["conversations"]
    assert sum(1 for c in listed if c["conversation_id"] == conv_id) == 1


# ---------- (2+3) اتجاهات العرض ----------

def test_regression_rtl_ltr_directions():
    app_js = (REPO / "src" / "ui" / "app.js").read_text(encoding="utf-8")
    markdown = (REPO / "src" / "ui" / "markdown.js").read_text(encoding="utf-8")
    # عربي: dir=auto يجعل الجملة العربية تبدأ يمينًا (RTL تلقائي)
    assert 'body.dir = "auto"' in app_js
    # إنجليزي/كود/JSON/جداول: ltr قسري لا انقلاب
    for marker in ("md-pre", "md-code", "md-table-wrap"):
        assert marker in markdown
    assert markdown.count('dir="ltr"') >= 3


# ---------- (4+5) المشروع يُحمّل بالنقرة وبالتحديث ----------

def test_regression_project_click_and_refresh_load(client):
    projects_js = (REPO / "src" / "ui" / "projects.js").read_text(encoding="utf-8")
    # الجذر (§15): hidden يُزال عند الدخول ويعود عند الخروج
    assert "view.hidden = false" in projects_js
    assert "view.hidden = true" in projects_js
    # التوجيه الدائم: التحديث يعيد فتح نفس المشروع من الهاش
    assert "#/project/" in projects_js
    assert "location.hash" in projects_js
    # والواجهة الرئيسية تطبق المسار عند الإقلاع
    app_js = (REPO / "src" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "applyRoute()" in app_js
    # الـAPI: بيانات المشروع من معرفه (الذي يقرأه التوجيه)
    created = client.post("/api/projects", json={
        "name": "مشروع انحدار", "objective": "إثبات التحميل بالنقرة",
    }).json()
    fetched = client.get(f"/api/projects/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "مشروع انحدار"
    assert fetched.json()["status"] == "DRAFT"


# ---------- (6) مسبار READY ↔ منفذ يوافق (مصدر واحد) ----------

def test_regression_probe_and_executor_agree(sessions, monkeypatch):
    from execution import service as execution_service
    from execution.backends import ExecutionOutcome, VerifyResult

    class AgreeingBackend:
        """خلفية واحدة: المسبار والمنفذ من resolve_executor نفسه (§19)."""
        backend_kind = "STUB"
        verified = 0
        executed = 0

        def describe(self):
            return {"os": "T", "architecture": "t", "sandboxed": True,
                    "available": True}

        def verify(self):
            AgreeingBackend.verified += 1
            # (013.11 §5) العقد الكامل لسلم العامل — لا قائمة مختزلة
            return VerifyResult(
                ok=True, status="READY", checks=[
                    {"name": n, "ok": True, "detail": "x"}
                    for n in ("connectivity", "authentication", "heartbeat",
                              "environment_probe", "workspace_probe",
                              "execute_probe", "artifact_probe")
                ],
                profile=self.describe(),
            )

        def run_code(self, code, *, workspace, artifacts, timeout_s=120):
            AgreeingBackend.executed += 1
            return ExecutionOutcome(
                environment_id="1", backend="STUB", exit_code=0,
                stdout="ok", stderr="", termination="COMPLETED",
            )

    shared = AgreeingBackend()
    monkeypatch.setattr(execution_service, "build_backend", lambda env: shared)

    probe_result = execution_service.sandbox_probe_result(sessions)
    assert probe_result["status"] == "READY"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        outcome = execution_service.run_code_unified(
            sessions, "print('x')", workspace=Path(tmp),
            artifacts=Path(tmp) / "a",
        )
    assert outcome.ok
    # المصدر نفسه: كل من المسبار والمنفذ مرّا بالخلفية الموحدة
    assert AgreeingBackend.verified >= 1 and AgreeingBackend.executed == 1
    # هوية البيئة في تفاصيل المسبار — التفسير إلزامي عند أي خلاف
    assert probe_result["details"]["environment_id"] is not None


# ---------- (7) مهمة ببيئة غير متاحة → محجوبة بوضوح ----------

def test_regression_unavailable_environment_clear_blocked_state(sessions):
    result = preflight.task_preflight(
        sessions, "مهمة تحتاج تنفيذًا", llm_ready=True,
        run_probe_fn=_seamed(sandbox="NOT_READY"),
    )
    assert result["verdict"] == "BLOCKED"
    sandbox = [b for b in result["blocked"]
               if b["capability_id"] == "sandbox"][0]
    # سبب + إجراء + مسار مالك حقيقي — لا رسالة صامتة
    assert sandbox["reason"]
    assert sandbox["recovery"]
    assert sandbox["owner_action"]
    assert "OWNER ACTION REQUIRED" in sandbox["owner_action"]
    assert "REMOTE_WORKER" in sandbox["owner_action"]
    # المصفوفة تعلن الحجب
    row = [r for r in result["matrix"]
           if r["capability_id"] == "sandbox"][0]
    assert row["decision"] == "BLOCK"


# ---------- (8) بحث معطل + جلب متاح → قرار واعٍ ----------

def test_regression_search_down_fetch_up_capability_aware(sessions):
    from research import service as research_service
    from execution.models import ResearchProvider

    _sandbox_env_ready(sessions)
    # (011 §12) البحث من مزوديه: DDG فاشل بمسبار حقيقي مسجل
    research_service.ensure_seeded(sessions)
    with sessions() as s:
        from sqlalchemy import select as sa_select

        row = s.scalars(sa_select(ResearchProvider).where(
            ResearchProvider.kind == "search_ddg")).first()
        row.last_probe_status = "NOT_READY"
        row.failure_reason = "مهلة من هذه الشبكة"
        row.last_probe_at = _dt.datetime.now(_dt.timezone.utc)
        s.commit()
    result = preflight.task_preflight(
        sessions, "منصة OSINT بمصادر مفتوحة", llm_ready=True,
        run_probe_fn=_seamed(web_search="NOT_READY"),
    )
    assert result["verdict"] == "BLOCKED"
    ids = {b["capability_id"] for b in result["blocked"]}
    assert ids == {"web_search"}, (
        f"الحجب يجب أن يكون للبحث وحده (الجلب جاهز): {ids}"
    )
    # إجراء المالك يفرّق: البحث قابل للتوفير (searx/api) لا «إنترنت مقطوع»
    action = [b for b in result["blocked"]
              if b["capability_id"] == "web_search"][0]["owner_action"]
    assert "SearXNG" in action or "Search API" in action
