"""اختبارات زمن تشغيل التخطيط (013.4 §1-§7) — عقد الحالة المحدود.

جذر العطل (§0): المشروع يدخل PLANNING ولا يخرج. هذه الاختبارات تثبت
الشيفلة الجديدة:
- التوليد أمر خلفي: يعيد فورًا ووصفه كامل (مزود/نموذج/طلب/إيجار).
- الأحداث معلنة خطوة خطوة — لا صمت أبدًا.
- الفشل مصنّف (MODEL_TIMEOUT/…) لا «Planning…» أبدية.
- الإعادة الآلية واحدة ثم فشل صريح بقرار المالك.
- الكلب يوسم الجلسات الميتة INTERRUPTED — لا PLANNING أبديًا.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from router.model_router import ProviderCallError  # noqa: E402
from workflow import planning_runtime, service  # noqa: E402


@pytest.fixture()
def planning_env(wf_env):
    """بيئة wf_env مع مشروع جاهز للتخطيط."""
    engine = wf_env["build_engine"]()
    project = engine.create_project("مشروع تخطيط", "هدف اختبار التخطيط")
    wf_env["engine"] = engine
    wf_env["project"] = project
    return wf_env


def _events_kinds(sessions, pid) -> list[str]:
    return [e["kind"] for e in service.list_events(sessions, pid)]


def _wait_terminal(sessions, pid, timeout=10.0) -> dict:
    return planning_runtime.wait_for_planning(sessions, pid, timeout=timeout)


# ------------------------------------------------------------------ #
# A + D. التخطيط الحي الكامل — أمر فوري + أحداث معلنة + خطة تنتظر
# ------------------------------------------------------------------ #

def test_planning_command_is_immediate_and_described(planning_env):
    """الأمر يعيد فورًا وصفًا كاملًا — لا استدعاءً حاجزًا داخل الطلب."""
    env = planning_env
    pid = env["project"]["id"]
    started = time.monotonic()
    result = env["engine"].start_plan_generation(pid)
    elapsed = time.monotonic() - started

    assert result["started"] is True
    assert elapsed < 2.0, "الأمر يجب أن يكون فوري الوصف (لا ينتظر LLM)"
    session = result["session"]
    assert session["state"] == "GENERATING"
    assert session["request_id"].startswith("plan-")
    assert session["lease_expires_at"], "الإيجار معلن من اللحظة الأولى"

    _wait_terminal(env["sessions"], pid)
    project = service.get_project(env["sessions"], pid)
    assert project["status"] == "AWAITING_OWNER_APPROVAL"


def test_planning_events_are_explicit_not_silent(planning_env):
    """(§3) كل خطوة حدث معلن: STARTED ← GENERATING ← CALL ← CREATED."""
    env = planning_env
    pid = env["project"]["id"]
    env["engine"].start_plan_generation(pid)
    _wait_terminal(env["sessions"], pid)

    kinds = _events_kinds(env["sessions"], pid)
    assert "PLANNING_STARTED" in kinds
    assert "PLAN_GENERATING" in kinds
    assert "MODEL_CALL_STARTED" in kinds
    assert "MODEL_CALL_COMPLETED" in kinds
    assert "PLAN_CREATED" in kinds
    assert "PLAN_APPROVAL_REQUIRED" in kinds
    # لا فشل ملفقًا
    assert "PLANNING_FAILED" not in kinds


def test_single_flight_no_second_session(planning_env):
    """جلسة GENERATING حية = رفض صريح بلا بدء ثانٍ."""
    env = planning_env
    pid = env["project"]["id"]
    first = env["engine"].start_plan_generation(pid)
    assert first["started"] is True
    second = env["engine"].start_plan_generation(pid)
    assert second["started"] is False
    assert second["reason"] == "already_generating"


# ------------------------------------------------------------------ #
# B. مهلة المزود → MODEL_TIMEOUT (لا PLANNING أبدية)
# ------------------------------------------------------------------ #

def test_provider_timeout_is_classified_not_eternal(planning_env,
                                                    monkeypatch):
    """(§4) مزود لا يجيب = MODEL_TIMEOUT + إعادة آلية واحدة ثم فشل
    صريح بقرار المالك — المشروع لا يبقى PLANNING أبدًا."""
    env = planning_env
    pid = env["project"]["id"]
    calls = {"n": 0}

    def timeout_planner(objective, *, previous_failure=None,
                        feedback=""):
        calls["n"] += 1
        raise ProviderCallError(
            "انتهت مهلة المزود المنظم", is_timeout=True
        )

    engine = env["build_engine"]()
    original = engine._build_planner

    class HangingPlanner:
        def generate(self, *args, **kwargs):
            return timeout_planner(*args, **kwargs)

    monkeypatch.setattr(
        engine, "_build_planner", lambda: HangingPlanner()
    )

    result = engine.start_plan_generation(pid)
    assert result["started"] is True

    session = _wait_terminal(env["sessions"], pid, timeout=15.0)
    assert session["state"] == "FAILED"
    assert session["error_class"] == "MODEL_TIMEOUT"

    project = service.get_project(env["sessions"], pid)
    assert project["status"] != "PLANNING", \
        "المشروع لا يبقى في PLANNING إلى الأبد — هذا جذر عطل §0"
    assert "MODEL_TIMEOUT" in project["last_error"]

    kinds = _events_kinds(env["sessions"], pid)
    assert "PLANNING_FAILED" in kinds
    assert "MODEL_CALL_FAILED" in kinds
    # إعادة آلية واحدة للفشل القابل للإعادة (§2)
    assert "PLANNING_RETRY" in kinds
    assert calls["n"] >= 2, "إعادة آلية واحدة على الأقل حدثت"


def test_auth_error_no_auto_retry(planning_env, monkeypatch):
    """(§4) خطأ تصريح غير قابل للإعادة — فشل فوري بلا إعادة آلية."""
    env = planning_env
    pid = env["project"]["id"]
    retries = {"n": 0}

    class AuthFailedPlanner:
        def generate(self, *args, **kwargs):
            retries["n"] += 1
            raise ProviderCallError("401 مفتاح غير صالح")

    engine = env["build_engine"]()
    monkeypatch.setattr(
        engine, "_build_planner", lambda: AuthFailedPlanner()
    )
    engine.start_plan_generation(pid)

    session = _wait_terminal(env["sessions"], pid, timeout=15.0)
    assert session["state"] == "FAILED"
    assert session["error_class"] == "PROVIDER_AUTH_ERROR"
    assert retries["n"] == 1, "لا إعادة آلية لخطأ التصريح"
    kinds = _events_kinds(env["sessions"], pid)
    assert "PLANNING_RETRY" not in kinds


# ------------------------------------------------------------------ #
# C. الرد غير الصالح → MODEL_RESPONSE_INVALID
# ------------------------------------------------------------------ #

def test_invalid_response_is_classified(planning_env, monkeypatch):
    """(§4) رد لا يطابق عقد الخطة = MODEL_RESPONSE_INVALID لا غموض."""
    env = planning_env
    pid = env["project"]["id"]

    class InvalidModelPlanner:
        """كما المخطط الحي تمامًا: رد فاسد ← PlannerError بعقد العقد."""

        def generate(self, *args, **kwargs):
            from workflow.planner import PlannerError

            raise PlannerError(
                "فشل توليد الخطة بعد إعادة واحدة — آخر خطأ: "
                "لا كائن JSON في الرد"
            )

    engine = env["build_engine"]()
    monkeypatch.setattr(
        engine, "_build_planner", lambda: InvalidModelPlanner()
    )
    engine.start_plan_generation(pid)

    session = _wait_terminal(env["sessions"], pid, timeout=15.0)
    assert session["state"] == "FAILED"
    # عقد الخطة — فشل الصياغة لا فشل المزود
    assert session["error_class"] == "MODEL_RESPONSE_INVALID"


# ------------------------------------------------------------------ #
# §7. الكلب — الجلسة الميتة تُوسم INTERRUPTED لا تبقى GENERATING
# ------------------------------------------------------------------ #

def test_watchdog_marks_stale_session_interrupted(planning_env):
    """إيجار منتهٍ بلا نبضة = INTERRUPTED + المشروع DRAFT بخطأ صريح."""
    env = planning_env
    pid = env["project"]["id"]
    # جلسة ميتة يدوية: صف GENERATING بإيجار منتهٍ (كأن العملية ماتت)
    from datetime import datetime, timedelta, timezone

    from workflow.models import PlanningSession

    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    with env["sessions"]() as session:
        session.add(PlanningSession(
            project_id=pid, state="GENERATING",
            provider="x", model="y", request_id="plan-dead",
            started_at=stale, last_activity_at=stale,
            lease_expires_at=stale + timedelta(seconds=1),
        ))
        session.commit()
    service.update_project(env["sessions"], pid, status="PLANNING")

    from workflow import watchdog

    diagnoses = watchdog.diagnose_once(env["sessions"])

    assert any(
        d["project_id"] == pid and d["kind"] == "PLANNING_LEASE_EXPIRED"
        for d in diagnoses
    )
    view = planning_runtime.latest_session(env["sessions"], pid)
    assert view["state"] == "INTERRUPTED"
    assert view["error_class"] == "PLANNING_INTERRUPTED"
    project = service.get_project(env["sessions"], pid)
    assert project["status"] == "DRAFT"
    assert "PLANNING_INTERRUPTED" in project["last_error"]
    kinds = _events_kinds(env["sessions"], pid)
    assert "PLANNING_INTERRUPTED" in kinds
    assert "WORKFLOW_DIAGNOSED" in kinds


# ------------------------------------------------------------------ #
# tick + منسق — wait_planning معلن بجلسته (§3+§6)
# ------------------------------------------------------------------ #

def test_tick_waits_for_planning_with_literal_reason(planning_env):
    """tick لا يستدعي LLM داخل الحلقة — يطلق التوليد وينتظر معلنًا."""
    env = planning_env
    pid = env["project"]["id"]
    engine = env["engine"]

    tick_result = engine.tick(pid)
    assert tick_result["action"] == "wait_planning"
    assert "الخطة" in tick_result["reason"]
    assert tick_result["planning"], "تفسير الانتظار حرفي لا عام"

    # المنسق: wait_planning → WAITING_PLANNING (انتظار معلن)
    from harness import coordinator

    classification = coordinator.classify_tick(
        tick_result, project=service.get_project(env["sessions"], pid),
        open_gates=[],
    )
    assert classification["status"] == "WAITING_PLANNING"
    assert classification["waiting_kind"] == "PLANNING"
    assert classification["stop"] is True

    _wait_terminal(env["sessions"], pid)


def test_retry_planning_after_failure(planning_env, monkeypatch):
    """زر الإعادة (§11): جلسة فاشلة ← إعادة صريحة ← جلسة جديدة."""
    env = planning_env
    pid = env["project"]["id"]

    class AlwaysTimeout:
        def generate(self, *args, **kwargs):
            raise ProviderCallError("مهلة", is_timeout=True)

    engine = env["build_engine"]()
    monkeypatch.setattr(engine, "_build_planner", lambda: AlwaysTimeout())
    engine.start_plan_generation(pid)
    failed = _wait_terminal(env["sessions"], pid, timeout=15.0)
    assert failed["state"] == "FAILED"

    # الإعادة عبر المحرك الحقيقي (بلا فشل) — جلسة retry_of تشير للفاشلة
    fresh_engine = env["engine"]
    result = fresh_engine.retry(pid)
    assert result["retried"] == "planning"
    retried = _wait_terminal(env["sessions"], pid, timeout=15.0)
    assert retried["state"] == "COMPLETED"
    assert retried["retry_of"] == failed["id"]
    project = service.get_project(env["sessions"], pid)
    assert project["status"] == "AWAITING_OWNER_APPROVAL"
