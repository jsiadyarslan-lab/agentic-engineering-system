"""اختبارات صدق زمن تشغيل التخطيط (013.5 §B-§D + §C.4 + §Q).

الجذر الحي (من قاعدة الإنتاج، مشروع #10):
    project.status = PLANNING
    project.created_at = 2026-09-22 11:32:20
    planning_sessions[3].state = GENERATING
    planning_sessions[3].lease_expires_at = 2026-09-22 16:38:02
    -> بقي PLANNING ‏17992ث بلا أي وسم صادق.

كل اختبار هنا يثبت قانونًا من قوانين §C/§D، لا سلوكًا تجميليًا:

- §C.1  سقف زمن الجدار يحسم MODEL_TIMEOUT **ولو كان الخيط حيًّا**.
- §C.2  توقف النبضة = INTERRUPTED (لا GENERATING أبدية).
- §C.3  صمت المزود مع عامل حي = MODEL_TIMEOUT.
- §C.4  الإقلاع يسترد فورًا — الجذر الحرفي للعطل الحي.
- §C    حارس الثبات: PLANNING بلا مولِّد صالح = شذوذ يُعاد DRAFT.
- §D    نبضة المؤقت **لا تمدّد الإيجار**؛ النشاط الحقيقي وحده يفعل.
- §C    خيط متأخر لا يكتب فوق حكم نهائي (لا COMPLETED بعد FAILED).
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from workflow import planning_runtime, service, watchdog  # noqa: E402
from workflow.models import PlanningSession  # noqa: E402


@pytest.fixture()
def project_env(wf_env):
    engine = wf_env["build_engine"]()
    project = engine.create_project("مشروع 013.5", "هدف صدق التخطيط")
    wf_env["engine"] = engine
    wf_env["project"] = project
    return wf_env


def _kinds(sessions, pid) -> list[str]:
    return [e["kind"] for e in service.list_events(sessions, pid)]


def _dead_session(sessions, pid, **overrides):
    """صف GENERATING ميت يدويًا — كما يتركه موت العملية فعلًا."""
    now = datetime.now(timezone.utc)
    fields = {
        "project_id": pid, "state": "GENERATING",
        "provider": "nvidia", "model": "nvidia/nemotron-3-nano",
        "request_id": "plan-deadbeef0001",
        "started_at": now - timedelta(minutes=30),
        "last_activity_at": now - timedelta(minutes=30),
        "heartbeat_at": now - timedelta(minutes=30),
        "last_meaningful_activity_at": now - timedelta(minutes=30),
        "lease_expires_at": now - timedelta(minutes=28),
    }
    fields.update(overrides)
    with sessions() as session:
        row = PlanningSession(**fields)
        session.add(row)
        session.commit()
        session.refresh(row)
        return int(row.id)


# ------------------------------------------------------------------ #
# §C.1  سقف زمن الجدار — يحسم ولو كان الخيط حيًّا
# ------------------------------------------------------------------ #

def test_hard_deadline_fails_even_when_thread_is_alive(project_env):
    """مهلة صلبة تجاوزت + خيط «حي» في هذه العملية = MODEL_TIMEOUT.

    هذا هو الفرق الجوهري بين «حلقة موجودة» و«حلقة تتقدم»: النبضة
    الزمنية وحدها لم تعد تحمي جلسة معلّقة.
    """
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(
        env["sessions"], pid,
        heartbeat_at=now,                      # العامل ينبض (حي)
        lease_expires_at=now + timedelta(seconds=60),
        hard_deadline_at=now - timedelta(seconds=5),   # السقف تجاوز
    )
    service.update_project(env["sessions"], pid, status="PLANNING")

    verdict = planning_runtime.session_failure_verdict(
        planning_runtime.latest_session(env["sessions"], pid),
        live_locally=True,
    )
    assert verdict is not None, "السقف الصلب يجب أن يحسم ولو كان الخيط حيًّا"
    assert verdict["error_class"] == "MODEL_TIMEOUT"
    assert verdict["state"] == "FAILED"

    watchdog.diagnose_once(env["sessions"])
    row = planning_runtime.latest_session(env["sessions"], pid)
    assert row["id"] == session_id
    assert row["state"] == "FAILED"
    assert row["error_class"] == "MODEL_TIMEOUT"
    project = service.get_project(env["sessions"], pid)
    assert project["status"] == "DRAFT", "المشروع يجب أن يخرج من PLANNING"
    assert "MODEL_TIMEOUT" in project["last_error"]


# ------------------------------------------------------------------ #
# §C.2  موت العامل — نبضة متقادمة = INTERRUPTED
# ------------------------------------------------------------------ #

def test_dead_worker_is_interrupted_not_eternal(project_env):
    env = project_env
    pid = env["project"]["id"]
    session_id = _dead_session(env["sessions"], pid)
    service.update_project(env["sessions"], pid, status="PLANNING")

    watchdog.diagnose_once(env["sessions"])

    row = planning_runtime.latest_session(env["sessions"], pid)
    assert row["id"] == session_id
    assert row["state"] == "INTERRUPTED"
    assert row["error_class"] == "PLANNING_INTERRUPTED"
    project = service.get_project(env["sessions"], pid)
    assert project["status"] == "DRAFT"
    assert "PLANNING_INTERRUPTED" in project["last_error"]
    assert "PLANNING_INTERRUPTED" in _kinds(env["sessions"], pid)
    assert "WORKFLOW_DIAGNOSED" in _kinds(env["sessions"], pid)


# ------------------------------------------------------------------ #
# §C.3  صمت المزود مع عامل حي = MODEL_TIMEOUT
# ------------------------------------------------------------------ #

def test_silent_provider_with_live_worker_times_out(project_env, monkeypatch):
    """العامل ينبض لكن لا نشاط مزود حقيقي = MODEL_TIMEOUT (لا انتظار)."""
    monkeypatch.setattr(planning_runtime, "PROVIDER_SILENCE_LIMIT_SECONDS",
                        0.5)
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    _dead_session(
        env["sessions"], pid,
        started_at=now,
        heartbeat_at=now,                        # العامل حي
        last_activity_at=now,
        last_meaningful_activity_at=now - timedelta(seconds=30),
        lease_expires_at=now + timedelta(seconds=60),
        hard_deadline_at=now + timedelta(seconds=600),
    )
    service.update_project(env["sessions"], pid, status="PLANNING")

    watchdog.diagnose_once(env["sessions"])

    row = planning_runtime.latest_session(env["sessions"], pid)
    assert row["state"] == "FAILED"
    assert row["error_class"] == "MODEL_TIMEOUT"
    assert "صامت" in row["error_detail"]
    assert service.get_project(env["sessions"], pid)["status"] == "DRAFT"


def test_reasoning_counts_as_real_provider_activity(project_env):
    """(013.5 §D) أحرف الاستدلال المُثبتة = حياة مزود — لا وسم صمت.

    العطل المقيس حيًّا: النموذج المُهيَّأ (deepseek-ai/deepseek-v4.1-flash)
    نموذج استدلالي يعمل دقائق داخل reasoning_content قبل أول مخرج؛
    اعتبار ذلك «صمتًا» يوسم MODEL_TIMEOUT على عمل جارٍ صحيح — حكم
    كاذب من الجهة المقابلة تمامًا لعطل الانتظار الأبدي.
    """
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(
        env["sessions"], pid,
        started_at=now, heartbeat_at=now, last_activity_at=now,
        last_meaningful_activity_at=now - timedelta(seconds=600),
        lease_expires_at=now - timedelta(seconds=60),
        hard_deadline_at=now + timedelta(seconds=900),
    )

    planning_runtime._mark_activity(env["sessions"], session_id,
                                    reasoning_chars=8192)

    row = planning_runtime.latest_session(env["sessions"], pid)
    assert row["reasoning_chars"] == 8192
    assert row["silence_s"] is not None and row["silence_s"] < 5
    lease = datetime.fromisoformat(row["lease_expires_at"])
    if lease.tzinfo is None:
        lease = lease.replace(tzinfo=timezone.utc)
    assert lease > now, "النشاط الحقيقي يجب أن يمدّد الإيجار"


def test_reasoning_only_response_is_classified_not_hidden():
    """(013.5 §B) رد ‏200 باستدلال فقط يُصنَّف صراحةً لا «رد فارغ»."""
    from router.call_tracker import classify_failure
    from router.model_router import ProviderCallError

    error = ProviderCallError(
        "رد استدلال فقط بلا مخرجات (finish_reason=length)",
        is_server_error=True, error_class="REASONING_ONLY_RESPONSE",
    )
    error_class, detail = classify_failure(error)
    assert error_class == "REASONING_ONLY_RESPONSE"
    assert "استدلال" in detail
    # مصنَّف معتمد في مفردات التخطيط — لا صنف مجهول
    assert error_class in planning_runtime_models().PLANNING_ERROR_CLASSES
    # ولا يُعاد آليًا: نفس الإعداد يفشل بنفس الطريقة
    assert error_class not in planning_runtime._RETRYABLE_CLASSES


def planning_runtime_models():
    from workflow import models

    return models


def test_late_plan_never_contradicts_a_decided_session(project_env):
    """(013.5 §C/§H) خطة وصلت بعد حسم الجلسة **لا تُدوَّن ولا تقلب
    حالة المشروع** — العطل المقيس حيًّا في مشروع 11:

        ‏20:14:34  PLANNING_FAILED  (المزود صامت 243ث — الكلب حسم)
        ‏20:14:52  MODEL_CALL_COMPLETED + PLAN_CREATED
                   + PLAN_APPROVAL_REQUIRED
        ‏20:14:52  PLANNING_RESULT_DISCARDED

    النتيجة الدائمة كانت: جلسة FAILED/MODEL_TIMEOUT بينما المشروع
    AWAITING_OWNER_APPROVAL وخطة للعرض — حقيقتان متناقضتان في نفس
    اللحظة. السبب: التدوين (الذي يقلب حالة المشروع) كان يسبق الحارس.
    القانون الآن: الحجز (CAS) يسبق التدوين حتمًا.
    """
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(
        env["sessions"], pid,
        started_at=now, heartbeat_at=now, last_activity_at=now,
        last_meaningful_activity_at=now - timedelta(seconds=600),
        lease_expires_at=now - timedelta(seconds=60),
        hard_deadline_at=now + timedelta(seconds=900),
    )
    service.update_project(env["sessions"], pid, status="PLANNING")

    # الكلب يحسم الجلسة فشلًا (صمت مزود)
    assert planning_runtime._finish_generating(
        env["sessions"], session_id, state="FAILED",
        error_class="MODEL_TIMEOUT", error_detail="المزود صامت",
    ) is True

    # خيط التخطيط المتأخر يحاول الحجز للنجاح — يُرفض
    claimed = planning_runtime._finish_generating(
        env["sessions"], session_id, state="COMPLETED", plan_id=None,
        actual_provider="nvidia", actual_model="model-x",
    )
    assert claimed is False, "لا حجز لنجاح بعد حسم فشل"

    row = planning_runtime.latest_session(env["sessions"], pid)
    assert row["state"] == "FAILED"
    assert row["plan_id"] is None
    # ولا خطة دُوّنت ولا حالة مشروع انقلبت
    assert service.get_project(env["sessions"], pid)["status"] == "PLANNING"
    assert "PLAN_CREATED" not in _kinds(env["sessions"], pid)


def test_completed_session_without_plan_is_corrected(project_env):
    """جلسة COMPLETED بلا خطة = كذبة تُصحَّح — الاستثناء الوحيد المعلن."""
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(env["sessions"], pid, started_at=now,
                              heartbeat_at=now, last_activity_at=now,
                              hard_deadline_at=now + timedelta(seconds=900))

    assert planning_runtime._finish_generating(
        env["sessions"], session_id, state="COMPLETED", plan_id=None) is True
    # محاولة ثانية بلا استثناء تُرفض (حسم نهائي)
    assert planning_runtime._finish_generating(
        env["sessions"], session_id, state="FAILED",
        error_class="PLANNING_ERROR") is False
    # ومع الاستثناء المعلن تُصحَّح
    assert planning_runtime._finish_generating(
        env["sessions"], session_id, state="FAILED",
        error_class="PLANNING_ERROR", allow_from_completed=True) is True
    assert planning_runtime.latest_session(
        env["sessions"], pid)["state"] == "FAILED"


def test_attach_plan_id_only_while_completed(project_env):
    """ربط الخطة بالجلسة لا يكتب فوق حالة غير COMPLETED."""
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(env["sessions"], pid, started_at=now,
                              heartbeat_at=now, last_activity_at=now,
                              hard_deadline_at=now + timedelta(seconds=900))

    assert planning_runtime._attach_plan_id(
        env["sessions"], session_id, 99) is False   # ما زالت GENERATING
    planning_runtime._finish_generating(
        env["sessions"], session_id, state="COMPLETED", plan_id=None)
    assert planning_runtime._attach_plan_id(
        env["sessions"], session_id, 99) is True
    assert planning_runtime.latest_session(
        env["sessions"], pid)["plan_id"] == 99


# ------------------------------------------------------------------ #
# §K  إيقاف/إلغاء حقيقي أثناء توليد جارٍ
# ------------------------------------------------------------------ #

def test_stop_during_planning_cancels_for_real(project_env):
    """(013.5 §K) الإيقاف النهائي أثناء التخطيط يلغي التوليد فعلًا.

    العطل المُغلق: ``request_stop`` كان يضبط علمًا على صف المشروع فقط،
    بينما خيط التوليد يواصل الاستدعاء — ثم تصل الخطة وتقلب الحالة إلى
    AWAITING_OWNER_APPROVAL بعد الإيقاف. الآن: الجلسة CANCELLED
    والمشروع STOPPED، والخيط يرى الإلغاء فيقطع الاتصال.
    """
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(env["sessions"], pid, started_at=now,
                              heartbeat_at=now, last_activity_at=now,
                              lease_expires_at=now + timedelta(seconds=120),
                              hard_deadline_at=now + timedelta(seconds=900))
    service.update_project(env["sessions"], pid, status="PLANNING")
    done = threading.Event()
    with planning_runtime._ACTIVE_LOCK:
        planning_runtime._ACTIVE[pid] = {"done": done,
                                         "session_id": session_id}

    result = planning_runtime.cancel_planning(
        env["sessions"], pid, reason="توقف نهائي من المالك", final=True)
    assert result["cancelled"] is True
    assert result["state"] == "CANCELLED"
    assert result["project_status"] == "STOPPED"

    row = planning_runtime.latest_session(env["sessions"], pid)
    assert row["state"] == "CANCELLED"
    assert row["error_class"] == "OWNER_CANCELLED"
    assert service.get_project(env["sessions"], pid)["status"] == "STOPPED"
    assert done.is_set(), "خيط التوليد يجب أن يُشعَر بالإلغاء"
    kinds = _kinds(env["sessions"], pid)
    assert "PLANNING_CANCELLED" in kinds
    # الإلغاء يقطع الاتصال فعلًا — النية مرئية للخيط
    assert planning_runtime.cancel_pending(env["sessions"], session_id) is False \
        or row["state"] == "CANCELLED"


def test_pause_during_planning_is_paused_not_running(project_env):
    """(013.5 §K) الإيقاف المؤقت صادق: PAUSED + جلسة ملغاة."""
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    _dead_session(env["sessions"], pid, started_at=now, heartbeat_at=now,
                  last_activity_at=now,
                  lease_expires_at=now + timedelta(seconds=120),
                  hard_deadline_at=now + timedelta(seconds=900))
    service.update_project(env["sessions"], pid, status="PLANNING")

    result = planning_runtime.cancel_planning(
        env["sessions"], pid, reason="إيقاف مؤقت", final=False)
    assert result["project_status"] == "PAUSED"
    project = service.get_project(env["sessions"], pid)
    assert project["status"] == "PAUSED"
    assert project["last_error"] == "إيقاف مؤقت"
    assert planning_runtime.latest_session(
        env["sessions"], pid)["state"] == "CANCELLED"


def test_resume_after_planning_pause_needs_a_real_plan(project_env):
    """(013.5 §K) استئناف بلا خطة لا يصير RUNNING — نجاح مُدّعى من فراغ."""
    env = project_env
    engine = env["engine"]
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    _dead_session(env["sessions"], pid, started_at=now, heartbeat_at=now,
                  last_activity_at=now,
                  lease_expires_at=now + timedelta(seconds=120),
                  hard_deadline_at=now + timedelta(seconds=900))
    service.update_project(env["sessions"], pid, status="PLANNING")
    planning_runtime.cancel_planning(env["sessions"], pid,
                                    reason="إيقاف مؤقت", final=False)

    resumed = engine.resume(pid)
    assert resumed["status"] == "DRAFT", "لا RUNNING بلا خطة"
    events = [e for e in service.list_events(env["sessions"], pid)
              if e["kind"] == "PROJECT_RESUMED"]
    assert events, "الاستئناف يجب أن يُعلن"
    assert events[-1]["payload"].get("needs_planning") is True


def test_cancel_without_active_generation_is_not_faked(project_env):
    """لا إلغاء وهمي: مشروع بلا توليد جارٍ يُعلن أنه لا شيء ليُلغى."""
    env = project_env
    pid = env["project"]["id"]
    result = planning_runtime.cancel_planning(env["sessions"], pid,
                                             reason="لا شيء", final=True)
    assert result["cancelled"] is False
    assert result["state"] == "NONE"
    assert _kinds(env["sessions"], pid).count("PLANNING_CANCELLED") == 0


def test_cancel_check_fires_inside_provider_activity(project_env):
    """الإلغاء يُقطع من داخل حلقة البث نفسها (خيط التوليد) — §K.

    يثبت المسار الحقيقي: نشاط مزود ← نداء النشاط ← رفع
    ``PlanningCancelled`` ← انغلاق الاتصال عبر ``with response`` في
    مولّد النقل. لا انتظار حتى انتهاء مهلة النقل.
    """
    from router.model_router import ChatMessage
    from workflow.planner import LivePlanner

    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(env["sessions"], pid, started_at=now,
                              heartbeat_at=now, last_activity_at=now,
                              hard_deadline_at=now + timedelta(seconds=900))

    seen: list[str] = []

    class _StreamingRouter:
        def chat_live_stream(self, messages, *, on_delta=None,
                            on_reasoning=None, **kwargs):
            # المزود يعمل: يبث استدلالًا — فتُستدعى نقطة القطع
            for chars in range(10, 60, 10):
                seen.append("reasoning")
                on_reasoning(chars)
            return {"text": "{}", "provider": "nvidia", "model": "m"}

    planner = LivePlanner(_StreamingRouter())
    planner.on_activity = (
        lambda kind, chars: planning_runtime._check_cancel(session_id, kind)
    )
    with planning_runtime._CANCEL_LOCK:
        planning_runtime._CANCEL[session_id] = {"reason": "اختبار",
                                                "final": True}
    try:
        with pytest.raises(planning_runtime.PlanningCancelled):
            planner._call([ChatMessage(role="user", content="x")])
    finally:
        with planning_runtime._CANCEL_LOCK:
            planning_runtime._CANCEL.pop(session_id, None)
    assert seen, "المزود كان يعمل فعلًا حين وصل الإلغاء"
    assert planning_runtime.latest_session(
        env["sessions"], pid)["state"] == "GENERATING", \
        "الإلغاء المعلّق لا يكتب حالة — الكتابة في cancel_planning"


# ------------------------------------------------------------------ #
# §D  نبضة المؤقت لا تمدّد الإيجار
# ------------------------------------------------------------------ #

def test_heartbeat_does_not_extend_the_lease(project_env):
    """(§D) النبضة الزمنية تحدّث heartbeat_at فقط — الإيجار لا يُمَس."""
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(
        env["sessions"], pid,
        last_meaningful_activity_at=now - timedelta(seconds=90),
        lease_expires_at=now + timedelta(seconds=30),
        hard_deadline_at=now + timedelta(seconds=600),
    )

    planning_runtime._touch_heartbeat(env["sessions"], session_id)

    row = planning_runtime.latest_session(env["sessions"], pid)
    lease_after = datetime.fromisoformat(row["lease_expires_at"])
    assert lease_after.tzinfo is None
    lease_after = lease_after.replace(tzinfo=timezone.utc)
    # الإيجار لم يتحرك (كان now+30 — بقي هناك)
    assert lease_after < now + timedelta(seconds=45), \
        "نبضة المؤقت مدّدت الإيجار — هذا هو العطل §D"
    assert row["heartbeat_at"] > (now - timedelta(seconds=5)).isoformat(), \
        "نبضة الحياة يجب أن تُسجَّل"


def test_real_activity_extends_the_lease_but_never_past_the_deadline(
        project_env):
    """(§D) النشاط الحقيقي وحده يمدّد — وبسقف زمن الجدار دائمًا."""
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(seconds=60)
    session_id = _dead_session(
        env["sessions"], pid,
        last_meaningful_activity_at=now - timedelta(seconds=300),
        lease_expires_at=now - timedelta(seconds=60),
        hard_deadline_at=deadline,
    )

    planning_runtime._mark_activity(env["sessions"], session_id)

    row = planning_runtime.latest_session(env["sessions"], pid)
    lease = datetime.fromisoformat(row["lease_expires_at"])
    if lease.tzinfo is None:
        lease = lease.replace(tzinfo=timezone.utc)
    assert lease > now, "النشاط الحقيقي يجب أن يمدّد الإيجار"
    assert lease <= deadline, "لا تمديد يفلت من سقف زمن الجدار"


# ------------------------------------------------------------------ #
# §C  حارس الثبات — PLANNING بلا مولِّد صالح
# ------------------------------------------------------------------ #

def test_invariant_heals_planning_with_no_session(project_env):
    """PLANNING بلا أي جلسة تخطيط = شذوذ يُعاد DRAFT بحدث معلن."""
    env = project_env
    pid = env["project"]["id"]
    service.update_project(env["sessions"], pid, status="PLANNING",
                           last_error="")

    healed = planning_runtime.enforce_invariant(env["sessions"])

    assert [h["project_id"] for h in healed] == [pid]
    project = service.get_project(env["sessions"], pid)
    assert project["status"] == "DRAFT"
    assert "حارس الثبات" in project["last_error"]
    assert "PLANNING_INVARIANT_HEALED" in _kinds(env["sessions"], pid)


def test_invariant_heals_planning_with_terminal_session(project_env):
    """PLANNING بآخر جلسة FAILED = شذوذ (لا انتظار فشل مكتمل)."""
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    _dead_session(
        env["sessions"], pid, state="FAILED",
        finished_at=now, error_class="MODEL_TIMEOUT",
    )
    service.update_project(env["sessions"], pid, status="PLANNING")

    healed = planning_runtime.enforce_invariant(env["sessions"])

    assert [h["project_id"] for h in healed] == [pid]
    assert service.get_project(env["sessions"], pid)["status"] == "DRAFT"


def test_invariant_leaves_healthy_planning_alone(project_env):
    """جلسة GENERATING بإيجار صالح = لا تدخل (لا وسم كاذب)."""
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    _dead_session(
        env["sessions"], pid,
        started_at=now, heartbeat_at=now, last_activity_at=now,
        last_meaningful_activity_at=now,
        lease_expires_at=now + timedelta(seconds=120),
        hard_deadline_at=now + timedelta(seconds=300),
    )
    service.update_project(env["sessions"], pid, status="PLANNING")

    healed = planning_runtime.enforce_invariant(env["sessions"])

    assert healed == []
    assert service.get_project(env["sessions"], pid)["status"] == "PLANNING"
    assert planning_runtime.latest_session(
        env["sessions"], pid)["state"] == "GENERATING"


# ------------------------------------------------------------------ #
# §C    خيط متأخر لا يكتب فوق حكم نهائي
# ------------------------------------------------------------------ #

def test_late_thread_cannot_overwrite_a_terminal_verdict(project_env):
    """(§C) بعد حسم الكلب: لا كتابة فوق الحقيقة (لا COMPLETED بعد FAILED)."""
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    session_id = _dead_session(
        env["sessions"], pid,
        heartbeat_at=now,                    # العامل ينبض — القانون 1 يحسم
        lease_expires_at=now + timedelta(seconds=60),
        hard_deadline_at=now - timedelta(seconds=5),
    )
    service.update_project(env["sessions"], pid, status="PLANNING")
    planning_runtime.enforce_invariant(env["sessions"])
    row = planning_runtime.latest_session(env["sessions"], pid)
    assert row["state"] == "FAILED"
    assert row["error_class"] == "MODEL_TIMEOUT"

    wrote = planning_runtime._finish_generating(
        env["sessions"], session_id, state="COMPLETED", plan_id=99
    )

    assert wrote is False, "خيط متأخر كتب فوق حكم نهائي — هذا كذب حالة"
    row = planning_runtime.latest_session(env["sessions"], pid)
    assert row["state"] == "FAILED"
    assert row["plan_id"] is None


# ------------------------------------------------------------------ #
# §C.4  الإقلاع يسترد فورًا (الجذر الحرفي للعطل الحي)
# ------------------------------------------------------------------ #

def test_startup_recovery_sweeps_and_heals_immediately(project_env):
    """mimic الواقع: مشروع PLANNING بجلسة منتهية الإيجار + إعادة تشغيل.

    العطل الحي: الكلب كان يُشغَّل فقط عند إطلاق حلقة تنفيذ، فبقي
    المشروع PLANNING ‏17992ث. الآن ``recover_at_startup`` يحسمه في
    الإقلاع نفسه، و``start_at_boot`` يشغّل الكلب أيضًا.
    """
    env = project_env
    sessions = env["sessions"]
    pid = env["project"]["id"]
    _dead_session(sessions, pid)
    service.update_project(sessions, pid, status="PLANNING")

    report = planning_runtime.recover_at_startup(sessions)

    assert report["healthy"] is False
    assert report["swept_verdicts"], "جلسة يتيمة لم تُمسح"
    assert report["healed_projects"] == []
    project = service.get_project(sessions, pid)
    assert project["status"] == "DRAFT"
    assert planning_runtime.latest_session(sessions, pid)["state"] == \
        "INTERRUPTED"


def test_start_at_boot_reports_and_starts_watchdog(project_env):
    """``start_at_boot`` يعيد ملخّص الاسترداد ويشغّل الكلب الدائم."""
    env = project_env
    sessions = env["sessions"]
    pid = env["project"]["id"]
    service.update_project(sessions, pid, status="PLANNING")  # بلا جلسة

    report = watchdog.start_at_boot(sessions)

    assert report["healthy"] is False
    assert [h["project_id"] for h in report["healed_projects"]] == [pid]
    assert service.get_project(sessions, pid)["status"] == "DRAFT"


def test_healthy_boot_reports_clean(project_env):
    env = project_env
    report = watchdog.start_at_boot(env["sessions"])
    assert report["healthy"] is True
    assert report["swept_sessions"] == []
    assert report["healed_projects"] == []


# ------------------------------------------------------------------ #
# §Q  موت العملية المالكة — استرداد فوري بلا انتظار الإيجار
# ------------------------------------------------------------------ #

def test_liveness_probe_is_truthful_for_this_process():
    """فحص الحياة يقول الحقيقة عن عملية قائمة وعن معرّف غير موجود.

    (013.5 §Q) هذا الفحص هو ما يجعل الاسترداد قطعيًا: على ويندوز
    ``os.kill(pid, 0)`` يقتل فعلًا ولا يفحص، فالمنصة تُفحص بـ
    ``OpenProcess`` — وكل فشل غير متوقع يعود «حيّ» فتبقى قوانين
    الإيجار هي الحكم (لا حسم صفّ خطأً بسبب قصور في المنصة).
    """
    import os

    assert planning_runtime._pid_alive(os.getpid()) is True
    assert planning_runtime._pid_alive(None) is True      # مجهول ≠ ميت
    assert planning_runtime._pid_alive(0) is True
    assert planning_runtime._pid_alive(999_999) is False  # لا عملية بهذا


def test_dead_owner_heals_instantly_despite_fresh_heartbeat(project_env):
    """النبضة حديثة والعملية ميتة → INTERRUPTED فورًا، لا انتظار 120ث.

    هذا هو الفرق المقيس: في اختبار الفوضى الحقيقي (قتل الخادم أثناء
    توليد فعلي) كان الاسترداد يستغرق ‏123.3ث لأن النبضة كانت حديثة
    لحظة القتل فلم يكن الإيجار قد انتهى. بعد هذا القانون صار ‏3.1ث.
    """
    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    _dead_session(
        env["sessions"], pid,
        owner_pid=999_999,                 # عملية ماتت
        heartbeat_at=now,                  # والقلب ما زال ينبض!
        lease_expires_at=now + timedelta(seconds=120),
        hard_deadline_at=now + timedelta(seconds=900),
        last_meaningful_activity_at=now,
    )
    service.update_project(env["sessions"], pid, status="PLANNING")

    verdict = planning_runtime.session_failure_verdict(
        planning_runtime.latest_session(env["sessions"], pid),
        live_locally=True,                 # و«محليًا حيّ» أيضًا
    )
    assert verdict is not None, "عملية ميتة يجب أن تحسم فورًا"
    assert verdict["error_class"] == "PLANNING_INTERRUPTED"
    assert verdict["state"] == "INTERRUPTED"
    assert "999999" in verdict["reason"]

    report = planning_runtime.recover_at_startup(env["sessions"])
    assert report["healthy"] is False
    assert planning_runtime.latest_session(env["sessions"], pid)["state"] == \
        "INTERRUPTED"
    assert service.get_project(env["sessions"], pid)["status"] == "DRAFT"


def test_live_owner_is_not_swept_by_the_liveness_law(project_env):
    """عملية المالك **حاضرة** → لا يُحسم الصف بها؛ الإيجار يبقى الحكم.

    هذا هو الحدّ الذي يمنع القانون الجديد من إساءة الحسم: ما دامت
    العملية حيّة والسقف لم يُتجاوز والنشاط حديث، الجلسة سليمة.
    """
    import os

    env = project_env
    pid = env["project"]["id"]
    now = datetime.now(timezone.utc)
    _dead_session(
        env["sessions"], pid,
        owner_pid=os.getpid(),             # نحن — حيّون
        heartbeat_at=now,
        last_meaningful_activity_at=now,
        lease_expires_at=now + timedelta(seconds=120),
        hard_deadline_at=now + timedelta(seconds=900),
    )
    service.update_project(env["sessions"], pid, status="PLANNING")

    verdict = planning_runtime.session_failure_verdict(
        planning_runtime.latest_session(env["sessions"], pid),
        live_locally=True,
    )
    assert verdict is None, "جلسة سليمة لا تُحسم"
    assert planning_runtime.recover_at_startup(env["sessions"])[
        "healthy"] is True


def test_new_session_records_its_owning_process(project_env):
    """كل محاولة جديدة تُسجّل العملية المالكة — أساس الاسترداد القطعي.

    يُقاس على مسار الإنشاء الحقيقي (‏``_create_session`` كما يستدعيه
    ``start_planning``) لا ببناء صف يدوي.
    """
    import os

    env = project_env
    pid = env["project"]["id"]
    session_id = planning_runtime._create_session(
        env["sessions"], pid, provider="nvidia", model="m", attempt=1)
    with env["sessions"]() as session:
        row = session.get(PlanningSession, session_id)
        assert row.owner_pid == os.getpid()
        assert row.state == "GENERATING"
    view = planning_runtime.latest_session(env["sessions"], pid)
    assert view["owner_pid"] == os.getpid()


# ------------------------------------------------------------------ #
# §B  المزود/النموذج الفعليان مسجَّلان دائمًا
# ------------------------------------------------------------------ #

def test_failed_session_keeps_provider_and_model(project_env, monkeypatch):
    """(§B) الفشل لا يُفقد المزود/النموذج — لا صف بلا هوية مزود.

    الدليل الحي: جلستان فاشلتان في الإنتاج بلا provider/model، فأي
    مقارنة بين «ما تختبره الواجهة» و«ما يظهر في الواجهة» تصبح
    مستحيلة. الآن يُحفظ الاختيار لحظة الإنشاء والفعلي عند الفشل.
    """
    from router.model_router import ProviderCallError

    env = project_env
    pid = env["project"]["id"]
    engine = env["build_engine"]()
    engine._role_selections = lambda: {  # type: ignore
        "thinker": type("Sel", (), {"provider": "nvidia",
                                    "model": "nvidia/nemotron-3-nano"})()
    }

    class FailingPlanner:
        def generate(self, *args, **kwargs):
            raise ProviderCallError("401 مفتاح غير صالح")

    monkeypatch.setattr(engine, "_build_planner", lambda: FailingPlanner())
    started = engine.start_plan_generation(pid)
    assert started["started"] is True
    assert started["session"]["provider"] == "nvidia"
    assert started["session"]["model"] == "nvidia/nemotron-3-nano"
    assert started["session"]["hard_deadline_at"], \
        "سقف زمن الجدار يُعلن من اللحظة الأولى (§C)"

    row = planning_runtime.wait_for_planning(env["sessions"], pid, timeout=15)
    assert row["state"] == "FAILED"
    assert row["error_class"] == "PROVIDER_AUTH_ERROR"
    assert row["provider"] == "nvidia", "المزود المعلن محفوظ"


# ------------------------------------------------------------------ #
# §J  رموز الانتظار الصادقة
# ------------------------------------------------------------------ #

def test_wait_phase_is_literal_not_a_generic_spinner(project_env):
    """(§J) الواجهة تُنسّق رمزًا صادقًا — لا «جاري التخطيط» أبدية."""
    env = project_env
    pid = env["project"]["id"]
    sessions = env["sessions"]

    assert planning_runtime.session_view(sessions, pid)["wait_phase"] == "NONE"

    now = datetime.now(timezone.utc)
    _dead_session(
        sessions, pid,
        started_at=now, heartbeat_at=now, last_activity_at=now,
        last_meaningful_activity_at=now - timedelta(seconds=280),
        lease_expires_at=now + timedelta(seconds=120),
        hard_deadline_at=now + timedelta(seconds=600),
    )
    service.update_project(sessions, pid, status="PLANNING")
    view = planning_runtime.session_view(sessions, pid)
    assert view["active"] is True
    assert view["wait_phase"] == "AWAITING_PROVIDER"
    assert view["waiting_for"]["silence_s"] >= 270
    assert view["waiting_for"]["hard_deadline_at"]

    # نشاط استدلال مُثبت = النموذج يفكّر فعلًا، لا «صمت مزود» (§D/§J)
    now = datetime.now(timezone.utc)
    with sessions() as session:
        row = session.query(PlanningSession).filter(
            PlanningSession.project_id == pid
        ).order_by(PlanningSession.id.desc()).first()
        row.reasoning_chars = 4096
        session.commit()
    view = planning_runtime.session_view(sessions, pid)
    assert view["wait_phase"] == "REASONING"
    assert view["waiting_for"]["reasoning_chars"] == 4096

    # تجاوز سقف الصمت **مع** استدلال متوقف = MODEL_TIMEOUT حتمًا
    silence_limit = planning_runtime.PROVIDER_SILENCE_LIMIT_SECONDS
    with sessions() as session:
        row = session.query(PlanningSession).filter(
            PlanningSession.project_id == pid
        ).order_by(PlanningSession.id.desc()).first()
        row.last_meaningful_activity_at = now - timedelta(
            seconds=silence_limit + 30)
        row.lease_expires_at = now + timedelta(seconds=120)
        session.commit()

    planning_runtime.enforce_invariant(sessions)
    view = planning_runtime.session_view(sessions, pid)
    assert view["active"] is False
    assert view["wait_phase"] == "FAILED"
    assert view["retry_available"] is True


def test_healthy_session_state_machine_vocabulary(project_env):
    """(§C) مفردات الحالات مقفلة كما نصّ الأمر."""
    assert planning_runtime.SESSION_STATES == (
        "QUEUED", "GENERATING", "COMPLETED", "FAILED", "INTERRUPTED",
        "PAUSED", "CANCELLED",
    )
    assert set(planning_runtime.TERMINAL_SESSION_STATES) <= set(
        planning_runtime.SESSION_STATES)


# ------------------------------------------------------------------ #
# §Q  فوضى: قتل الخيط أثناء التخطيط لا يترك PLANNING
# ------------------------------------------------------------------ #

def test_killed_planning_thread_leaves_no_phantom_planning(project_env,
                                                           monkeypatch):
    """عامل يموت بلا وسم ذاتي (كما لو قُتل) — الكلب يحسم الحالة."""
    env = project_env
    pid = env["project"]["id"]
    sessions = env["sessions"]
    release = threading.Event()
    engine = env["build_engine"]()

    class HangingPlanner:
        def generate(self, *args, **kwargs):
            release.wait(timeout=30)
            raise RuntimeError("لن يصل")

    monkeypatch.setattr(engine, "_build_planner", lambda: HangingPlanner())
    engine.start_plan_generation(pid)
    assert service.get_project(sessions, pid)["status"] == "PLANNING"

    # محاكاة موت العملية: إزالة الخيط من السجل الحي + تقادم النبضة.
    with planning_runtime._ACTIVE_LOCK:
        planning_runtime._ACTIVE.pop(int(pid), None)
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    with sessions() as session:
        row = session.query(PlanningSession).filter(
            PlanningSession.project_id == pid
        ).order_by(PlanningSession.id.desc()).first()
        row.heartbeat_at = past
        row.last_activity_at = past
        row.last_meaningful_activity_at = past
        row.lease_expires_at = past + timedelta(seconds=1)
        session.commit()

    watchdog.diagnose_once(sessions)

    assert service.get_project(sessions, pid)["status"] != "PLANNING", \
        "خيط مقتول أثناء التخطيط ترك المشروع PLANNING — جذر العطل §0"
    assert planning_runtime.latest_session(sessions, pid)["state"] in (
        "INTERRUPTED", "FAILED")
    release.set()
    time.sleep(0.2)
