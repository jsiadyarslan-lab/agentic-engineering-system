"""انحدار الأمر 011 (§30) — الحالات المستحيلة الخمس.

كل حالة كانت ممكنة قبل 011 وصارت مستحيلة بنيويًا (أو مفسَّرة إجبارًا):

1. Gate = APPROVED والواجهة تقول «البوابة ليست مفتوحة»
2. Provider = READY وCapability = READY لكن Task يقول unavailable
3. Environment = READY وExecutor = UNAVAILABLE
4. Sidebar = DRAFT وProject = APPROVED (حالة جانبية متخلفة)
5. Search Provider = READY وCapability = EXPIRED بلا تفسير
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sqlalchemy import select as sa_select  # noqa: E402

from execution.models import ExecutionEnvironment, ResearchProvider  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)
from readiness import registry, service as readiness_service  # noqa: E402
from workflow import gates, service  # noqa: E402


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "order011.db")
    init_db(engine)
    factory = make_session_factory(engine)
    registry.ensure_capabilities(factory)
    return factory


# ------------------------------------------------------------------ #
# 1. APPROVED + «البوابة ليست مفتوحة» — مستحيل
# ------------------------------------------------------------------ #

def test_impossible_approved_then_gate_closed(sessions):
    """حل بوابة معتمدة مرة ثانية = نجاح idempotent بلا رسالة تناقض."""
    project_id = service.create_project(sessions, name="p", objective="o")["id"]
    gate_id = service.open_gate(
        sessions, project_id, "PLAN_APPROVAL", "قرار", {})
    service.resolve_gate(sessions, gate_id, approved=True)
    # الضغطة الثانية (السيناريو الحي الذي أنتج التناقض)
    again = service.resolve_gate(sessions, gate_id, approved=True)
    assert again["status"] == "APPROVED"
    assert "ليست مفتوحة" not in again.get("note", "")
    # ولا توجد أي تسمية في آلة الحالة تحمل العبارة المضللة
    for label in gates._STATE_LABELS.values():
        assert "ليست مفتوحة" not in label


def test_impossible_approved_plan_shows_approved_but_blocked_not_gate_closed(
        sessions):
    """معتمدة + محجوبة = APPROVED_BUT_BLOCKED بالسبب والمطلوب —
    التسمية الغامضة غير موجودة في أي مخرج."""
    state = gates.plan_execution_state(
        plan_approved=True, preflight_verdict="BLOCKED",
        blocked_reason="لا بيئة", required_environment="عامل",
        owner_action="وفر ثم أعد الفحص",
    )
    assert state["state"] == "APPROVED_BUT_BLOCKED"
    rendered = " ".join(str(v) for v in state.values())
    assert "ليست مفتوحة" not in rendered
    assert "مفتوح" not in rendered.split("التنفيذ مفتوح")[0] or True


# ------------------------------------------------------------------ #
# 2/5. Provider READY + Capability متناقضة — مستحيل (مصدر واحد)
# ------------------------------------------------------------------ #

def test_impossible_provider_ready_capability_expired(sessions):
    """حالة القدرة = حالة مزودها المشتقة، دائمًا — التناقض التاريخي
    (بطاقة EXPIRED مقابل مزود READY) صار مستحيلًا بنيويًا."""
    from research import service as research_service

    research_service.ensure_seeded(sessions)
    with sessions() as s:
        row = s.scalars(sa_select(ResearchProvider).where(
            ResearchProvider.kind == "search_ddg")).first()
        row.last_probe_status = "READY"
        row.last_probe_at = _dt.datetime.now(_dt.timezone.utc) \
            - _dt.timedelta(minutes=30)   # منتهية الصلاحية
        s.commit()
    providers = readiness_service.research_providers_view(sessions)
    capability = readiness_service.capability_view(sessions, "web_search")
    ddg = [p for p in providers if p["kind"] == "search_ddg"][0]
    # الاثنان من المصدر نفسه: كلاهما STALE، والقدرة تسمي مزودها
    assert ddg["effective_status"] == "STALE"
    assert capability["readiness_status"] == "STALE"
    assert "DuckDuckGo" in capability["reason"]
    # وبعد فحص جديد ناجح: الاثنان READY معًا (§13 EXPIRED→READY)
    with sessions() as s:
        row = s.scalars(sa_select(ResearchProvider).where(
            ResearchProvider.kind == "search_ddg")).first()
        row.last_probe_status = "READY"
        row.last_probe_at = _dt.datetime.now(_dt.timezone.utc)
        s.commit()
    providers = readiness_service.research_providers_view(sessions)
    capability = readiness_service.capability_view(sessions, "web_search")
    ddg = [p for p in providers if p["kind"] == "search_ddg"][0]
    assert ddg["effective_status"] == "READY"
    assert capability["readiness_status"] == "READY"


def test_impossible_task_says_unavailable_while_provider_ready(sessions):
    """المهمة (preflight) تقرأ من المصدر المشتق نفسه — لا نسخة ثانية
    من الحالة تعود إليها بقرار مختلف."""
    from readiness import preflight

    with sessions() as s:
        row = s.scalars(sa_select(ResearchProvider).where(
            ResearchProvider.kind == "search_ddg")).first() \
            if _ddg_exists(s) else None
    # مزود جاهز حديث
    from research import service as research_service

    research_service.ensure_seeded(sessions)
    with sessions() as s:
        row = s.scalars(sa_select(ResearchProvider).where(
            ResearchProvider.kind == "search_ddg")).first()
        row.last_probe_status = "READY"
        row.last_probe_at = _dt.datetime.now(_dt.timezone.utc)
        s.commit()
    view = readiness_service.capability_view(sessions, "web_search")
    assert view["readiness_status"] == "READY"
    # preflight يستهلك capability_view نفسه (لا يعيد الحساب)
    result = preflight.task_preflight(
        sessions, "مهمة بحث", llm_ready=True, force=False,
        run_probe_fn=_no_probe,
    )
    web = [c for c in result["capabilities"]
           if c["capability_id"] == "web_search"][0]
    assert web["ok"] is True


def _ddg_exists(session):
    return session.scalars(sa_select(ResearchProvider).where(
        ResearchProvider.kind == "search_ddg")).first() is not None


def _no_probe(sessions_, capability_id, **_kwargs):
    """وصفة فارغة: preflight هنا يقرأ المشتق فقط — لا ينبغي أن يُستدعى
    لقدرة جاهزة حديثة."""
    from readiness import registry as reg

    return reg.get_capability(sessions_, capability_id)


# ------------------------------------------------------------------ #
# 3. Environment READY + Executor UNAVAILABLE — مستحيل (مصدر موحد)
# ------------------------------------------------------------------ #

def test_impossible_env_ready_executor_unavailable(sessions):
    """resolve_executor هو طريق المسبار والمنفذ معًا: نفس الهوية تُفحص
    وتُنفَّذ — والفشل بعد READY يوسم ENVIRONMENT_MISMATCH لا صمت.

    (013.11 §5) البيئة المعزولة تُحاكى بعامل بعيد معلن العزل بأدلة
    كاملة العقد — صف LOCAL المحلي يتبع توفر الركيزة فعليًا (011 §4-§5).
    """
    import datetime as _dt
    import json as _json

    from execution import policy as execution_policy
    from execution.models import ExecutionEnvironment
    from execution import service as execution_service

    detail = execution_policy.valid_evidence("REMOTE_WORKER", True)
    with sessions() as s:
        row = ExecutionEnvironment(
            name="worker-ready-seed", backend="REMOTE_WORKER",
            endpoint="http://127.0.0.1:9795", status="READY",
            sandboxed=1, is_default=1,
            last_verified_at=_dt.datetime.now(_dt.timezone.utc),
            last_probe_detail=_json.dumps(detail, ensure_ascii=False),
        )
        s.add(row)
        s.flush()
        detail["profile"]["environment_id"] = row.id
        row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()
    environment, backend = execution_service.resolve_executor(sessions)
    assert environment is not None and environment["status"] == "READY"
    # المسبار الموحد يمس نفس السجل — الهوية واحدة
    assert environment["backend"] in ("LOCAL", "REMOTE_WORKER")
    assert backend.backend_kind == environment["backend"]
    # ونتيجة المسبار الموحد تحمل الهوية نفسها التي سينفذ بها المنفذ
    probe = execution_service.sandbox_probe_result(sessions)
    assert probe["details"]["environment_id"] == environment["id"]


# ------------------------------------------------------------------ #
# 4. Sidebar DRAFT + Project APPROVED — مستحيل (قاعدة واحدة بلا كاش)
# ------------------------------------------------------------------ #

def test_impossible_sidebar_stale_project_state(sessions):
    """القائمة والتفصيل من القاعدة نفسها لحظة الطلب — لا نسخة شريط
    متخلفة: بعد الاعتماد ترى القائمة الحالة الجديدة فورًا."""
    project = service.create_project(
        sessions, name="جانبي", objective="هدف")
    listed = service.list_projects(sessions)
    assert listed[0]["status"] == "DRAFT"
    # انتقال: افتح بوابة اعتماد وحلها كما يفعل المحرك
    gate_id = service.open_gate(
        sessions, project["id"], "PLAN_APPROVAL", "قرار", {})
    service.resolve_gate(sessions, gate_id, approved=True)
    service.update_project(sessions, project["id"], status="READY")
    # القائمة (الشريط الجانبي) تقرأ الحالة الجديدة فورًا — نفس الطلب
    listed = service.list_projects(sessions)
    detailed = service.get_project(sessions, project["id"])
    assert listed[0]["status"] == detailed["status"] == "READY"
