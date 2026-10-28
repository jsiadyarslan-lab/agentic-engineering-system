"""(W1-T06) تصنيف العائق البيئي في فشل الخطوة — اختبارات وحدة مركّزة.

الدافع الموثق (شكوى المالك: «أعطيت موافقتي خمسين مرة» + 7+ بوابات
مراجعة خطة في 24 ساعة — owner-complaint-forensics.json): استنفاد محاولات
الخطوة بسبب عائق بيئي (network_http / web_search معطوبة) كان يفتح بوابة
PLAN_REVISION_APPROVAL بلا استشارة جاهزية القدرات — كل موافقة تولّد خطة
جديدة تحتاج نفس البحث المحجوب فيفشل ويفتح بوابة جديدة في حلقة لا تنتهي.

العقد الجديد (W1-T06):
1. فشل بعائق بيئي والقدرة ما زالت معطوبة → بوابة PREFLIGHT_BLOCKED
   (حاجز توفير يُحل بإعادة الفحص بلا إعادة اعتماد) والخطوة تعود READY —
   لا تُحرق موافقة مراجعة خطة.
2. فشل بعائق بيئي والقدرة جاهزة الآن → محاولة واحدة جديدة
   (ENV_RECOVERED_RETRY) بلا بوابة أصلًا — مرة واحدة للخطوة حصرًا.
3. تكرار الفشل رغم جاهزية البيئة (بعد منح محاولة الاسترداد) → يسقط
   إلى مراجعة الخطة كما كان — حرس الحلقة اللانهائية.
4. الفشل غير البيئي → PLAN_REVISION_APPROVAL كما كان دائمًا (رجعية).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from workflow import service  # noqa: E402

GENERIC_REASON = "الحالة النهائية FAILED — الدورة لم تكتمل أدلةً"


def _approved_step(wf_env):
    """مشروع بخطة معتمدة — يعيد (engine, project, plan, phase, step)."""
    engine = wf_env["build_engine"]()
    project = engine.create_project("مشروع W1-T06", "هدف اختبار العائق البيئي")
    engine.generate_plan(project["id"])
    engine.approve_plan(project["id"], approved=True)
    plan = service.latest_plan(wf_env["sessions"], project["id"])
    phase = service.list_phases(wf_env["sessions"], project["id"])[0]
    step = service.phase_steps(wf_env["sessions"], phase["id"])[0]
    return engine, project, plan, phase, step


def _exhausted_executions(wf_env, step) -> int:
    """تنفيذان فاشلان (الميزانية = 2) — الثاني هو الجاري تصنيفه."""
    for attempt in (1, 2):
        execution_id = service.create_execution(
            wf_env["sessions"], step["id"], attempt=attempt,
            provider="nvidia", model="test", workspace=str(wf_env["tmp_path"]),
        )
        service.update_execution(wf_env["sessions"], execution_id,
                                 status="FAILED", error=GENERIC_REASON)
    return execution_id


def _add_env_tool_failure(wf_env, project, step):
    """استدعاء web_search فاشل بمحاولة التنفيذ الجارية — توقيع العائق."""
    from readiness.models import ToolInvocation

    with wf_env["sessions"]() as session:
        session.add(ToolInvocation(
            cycle_id=f"project-{project['id']}-step-{step['id']}",
            tool_call_id="tc-w1t06-test", tool="web_search",
            status="FAILED", transport_status="SUCCESS",
            result_status="NOT_USABLE", failure_class="DEPENDENCY_FAILURE",
            failure_stage="PROVIDER_RESOLUTION",
            failure_reason="SEARCH_PROVIDER_NOT_READY",
            query="test query", error="لا مزود بحث جاهز", retryable=0,
        ))
        session.commit()


def _patch_capability(monkeypatch, status: str):
    from readiness import service as readiness_service

    monkeypatch.setattr(
        readiness_service, "capability_view",
        lambda sessions, capability_id: {
            "capability_id": capability_id,
            "readiness_status": status,
            "reason": f"حالة منظمة للاختبار: {status}",
            "failure_reason": "" if status == "READY" else "جهّز المزود",
        },
    )


def _gates(wf_env, project_id):
    return service.open_gates(wf_env["sessions"], project_id)


def _retries(wf_env, step_id):
    with wf_env["sessions"]() as session:
        from sqlalchemy import select

        from workflow.models import RetryRecord

        return session.scalars(
            select(RetryRecord).where(
                RetryRecord.step_id == int(step_id))
        ).all()


# ---------------- 1. عائق بيئي ما زال قائمًا ---------------- #

def test_env_blocker_opens_provisioning_gate_not_plan_revision(
        wf_env, monkeypatch):
    """(W1-T06) القدرة معطوبة → PREFLIGHT_BLOCKED (يُحل بإعادة الفحص)
    لا PLAN_REVISION_APPROVAL — والخطوة تعود READY لا FAILED."""
    engine, project, plan, phase, step = _approved_step(wf_env)
    execution_id = _exhausted_executions(wf_env, step)
    _add_env_tool_failure(wf_env, project, step)
    _patch_capability(monkeypatch, "NOT_READY")

    outcome = engine._on_step_failure(
        project, plan, phase, step, execution_id, GENERIC_REASON)

    assert outcome["action"] == "blocked"
    assert outcome["blocked_kind"] == "environment"
    assert "web_search" in outcome["reason"]

    gates = _gates(wf_env, project["id"])
    assert gates, "لا بوابة فُتحت"
    gate = gates[-1]
    assert gate["kind"] == "PREFLIGHT_BLOCKED", (
        f"عائق بيئي يجب أن يفتح حاجز توفير لا مراجعة خطة: {gate['kind']}"
    )
    assert gate["status"] == "BLOCKED"
    assert "web_search" in gate["reason"]

    fresh_step = service.get_step(wf_env["sessions"], step["id"])
    assert fresh_step["status"] == "READY", (
        "البيئة فشلت لا الخطوة — الخطوة تعود READY للإعادة بعد التوفير"
    )
    # لا سجل تصعيد مراجعة خطة — الفشل مصنف بيئيًا
    assert all(r.decision != "ESCALATE" for r in _retries(wf_env, step["id"]))


def test_env_signature_in_reason_text_also_classified(
        wf_env, monkeypatch):
    """(W1-T06) التوقيع الصريح في نص السبب يكفي — بلا استدعاءات أدوات."""
    engine, project, plan, phase, step = _approved_step(wf_env)
    execution_id = _exhausted_executions(wf_env, step)
    _patch_capability(monkeypatch, "NOT_READY")

    reason = "لا مزود بحث جاهز: DDG: تحدّ؛ Bing: 429 — " \
             "SEARCH_PROVIDER_NOT_READY"
    outcome = engine._on_step_failure(
        project, plan, phase, step, execution_id, reason)

    assert outcome["blocked_kind"] == "environment"
    assert _gates(wf_env, project["id"])[-1]["kind"] == "PREFLIGHT_BLOCKED"


# ---------------- 2. العائق زال — محاولة واحدة بلا بوابة ---------------- #

def test_env_recovered_grants_single_gateless_retry(wf_env, monkeypatch):
    """(W1-T06) القدرة جاهزة الآن → ENV_RECOVERED_RETRY بلا أي بوابة."""
    engine, project, plan, phase, step = _approved_step(wf_env)
    execution_id = _exhausted_executions(wf_env, step)
    _add_env_tool_failure(wf_env, project, step)
    _patch_capability(monkeypatch, "READY")

    outcome = engine._on_step_failure(
        project, plan, phase, step, execution_id, GENERIC_REASON)

    assert outcome["action"] == "continue", outcome
    retries = _retries(wf_env, step["id"])
    assert any(r.decision == "ENV_RECOVERED_RETRY" for r in retries)
    assert not _gates(wf_env, project["id"]), (
        "البيئة جاهزة — لا بوابة ولا موافقة تُحرق"
    )
    fresh_step = service.get_step(wf_env["sessions"], step["id"])
    assert fresh_step["status"] == "READY"


def test_env_recovered_retry_granted_only_once(wf_env, monkeypatch):
    """(W1-T06) حرس الحلقة: بعد منح محاولة الاسترداد مرة، الفشل المتكرر
    رغم جاهزية البيئة يسقط إلى مراجعة الخطة كما كان."""
    engine, project, plan, phase, step = _approved_step(wf_env)
    execution_id = _exhausted_executions(wf_env, step)
    _add_env_tool_failure(wf_env, project, step)
    _patch_capability(monkeypatch, "READY")

    with wf_env["sessions"]() as session:
        from workflow.models import RetryRecord

        session.add(RetryRecord(
            step_id=int(step["id"]), previous_execution_id=None,
            reason=GENERIC_REASON, decision="ENV_RECOVERED_RETRY",
            diagnosis="منحة سابقة للاختبار",
        ))
        session.commit()

    outcome = engine._on_step_failure(
        project, plan, phase, step, execution_id, GENERIC_REASON)

    assert outcome["action"] == "blocked"
    gate = _gates(wf_env, project["id"])[-1]
    assert gate["kind"] == "PLAN_REVISION_APPROVAL", (
        "تكرار الفشل رغم جاهزية البيئة = ليس عائقًا بيئيًا — مراجعة خطة"
    )
    fresh_step = service.get_step(wf_env["sessions"], step["id"])
    assert fresh_step["status"] == "FAILED"


# ---------------- 3. رجعية — الفشل غير البيئي كما كان ---------------- #

def test_non_environment_failure_still_opens_plan_revision(
        wf_env, monkeypatch):
    """(W1-T06 رجعية) فشل بلا توقيع بيئي → PLAN_REVISION_APPROVAL كما كان."""
    engine, project, plan, phase, step = _approved_step(wf_env)
    execution_id = _exhausted_executions(wf_env, step)
    _patch_capability(monkeypatch, "NOT_READY")  # جاهزية متعطوبة لكن لا صلة

    outcome = engine._on_step_failure(
        project, plan, phase, step, execution_id, GENERIC_REASON)

    assert outcome["action"] == "blocked"
    gate = _gates(wf_env, project["id"])[-1]
    assert gate["kind"] == "PLAN_REVISION_APPROVAL"
    fresh_step = service.get_step(wf_env["sessions"], step["id"])
    assert fresh_step["status"] == "FAILED"
    assert any(r.decision == "ESCALATE" for r in _retries(wf_env, step["id"]))


def test_env_blocker_requires_tool_failure_from_current_attempt(
        wf_env, monkeypatch):
    """(W1-T06) دقة النطاق: استدعاء فاشل **قبل** محاولة التنفيذ الجارية
    (توقيت أقدم) لا يُصنّف الفشل الحالي عائقًا بيئيًا."""
    import datetime as _dt

    engine, project, plan, phase, step = _approved_step(wf_env)
    execution_id = _exhausted_executions(wf_env, step)
    _patch_capability(monkeypatch, "NOT_READY")

    from readiness.models import ToolInvocation

    with wf_env["sessions"]() as session:
        old = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)
        invocation = ToolInvocation(
            cycle_id=f"project-{project['id']}-step-{step['id']}",
            tool_call_id="tc-w1t06-old", tool="web_search",
            status="FAILED", failure_class="DEPENDENCY_FAILURE",
            failure_stage="PROVIDER_RESOLUTION",
            failure_reason="SEARCH_PROVIDER_NOT_READY",
            query="old query", error="قديم",
        )
        invocation.created_at = old
        session.add(invocation)
        session.commit()

    outcome = engine._on_step_failure(
        project, plan, phase, step, execution_id, GENERIC_REASON)

    assert outcome["action"] == "blocked"
    gate = _gates(wf_env, project["id"])[-1]
    assert gate["kind"] == "PLAN_REVISION_APPROVAL", (
        "فشل قديم السبب لا يعني أن الفشل الحالي بيئي — النطاق زمني"
    )
