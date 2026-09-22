"""اختبارات دورة حياة الوظيفة الدائمة (012-E+G) — السلسلة الكاملة
والتوقفات الصادقة والاسترداد، فوق محرك 011 الحقيقي كما هو.

السلسلة المطلوبة (معيار قبول 012):
Owner → Objective → Coordinator → Plan → Approval → Preflight →
EngineeringJob → Role → Tool/Capability → Evidence → Verifier →
Arbiter → Checkpoint → Restart → Resume → Audit → Owner
Verification → VERIFIED

مع توقف صادق عند أي نقطة: WAITING_CAPABILITY / WAITING_WORKER /
WAITING_GATE / RETRYING / REVISING / BLOCKED.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from workflow import service  # noqa: E402
from workflow.engine import EngineError  # noqa: E402


def _approved_project(env, *, providers=("nvidia",)):
    """مشروع بخطة معتمدة جاهز للتشغيل — عبر المسار الرسمي كاملًا."""
    engine = env["build_engine"](providers=providers)
    project = engine.create_project(
        "مشروع الوظائف", "هدف اختبار الوظيفة"
    )
    engine.generate_plan(project["id"])
    engine.approve_plan(project["id"], approved=True)
    return project["id"]


def _kinds(sessions, pid):
    return [e["kind"] for e in service.list_events(sessions, pid, limit=200)]


# ------------------------------------------------------------------ #
# السلسلة الكاملة — happy path حتى VERIFIED
# ------------------------------------------------------------------ #

def test_full_chain_job_lifecycle_to_verified(harness_env):
    """السلسلة كاملة: خطة ← اعتماد ← فحص ← وظيفة ← أدلة ← تدقيق ←
    checkpoint ← انتظار التحقق ← VERIFIED ← الوظيفة COMPLETED."""
    env = harness_env
    sessions = env["sessions"]
    engine = env["build_engine"]()
    pid = _approved_project(env)

    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)
    assert job["status"] == "QUEUED"
    assert "JOB_QUEUED" in _kinds(sessions, pid)

    outcome = manager.run_loop(job["id"])
    assert outcome["job_id"] == job["id"]

    job = manager.get_job(job["id"])
    # اكتمال المرشح ← التحقق النهائي قرار المالك ← انتظار بوابة
    assert job["status"] == "WAITING_GATE", job
    assert job["waiting_kind"] == "GATE"
    assert "FINAL_VERIFICATION" in job["waiting_detail"]["gate_kinds"]
    # دفتر صادق: نبضات ونقاط حفظ ومؤشرات
    assert job["tick_count"] >= 3
    assert job["checkpoints"] >= 1
    assert job["heartbeat_at"] != ""
    assert job["heartbeat_age_s"] is not None
    assert job["current_role"] in ("coordinator", "implementer")
    assert job["checkpoint_id"] is not None
    # أحداث الوظيفة كاملة في السجل الدائم
    kinds = _kinds(sessions, pid)
    for expected in ("JOB_QUEUED", "JOB_STARTED", "JOB_WAITING",
                     "CHECKPOINT_CREATED", "EVIDENCE_CREATED",
                     "AUDIT_COMPLETED", "PROJECT_COMPLETION_CANDIDATE"):
        assert expected in kinds, expected

    # التحقق النهائي للمالك — القناة الوحيدة إلى COMPLETED
    engine.verify(pid)
    verified_job = manager.mark_verified(pid)
    assert verified_job["status"] == "COMPLETED"
    assert "JOB_COMPLETED" in _kinds(sessions, pid)

    # مشروع VERIFIED نهائي — لا وظيفة جديدة أبدًا (الحد الصادق)
    with pytest.raises(Exception, match="نهائية"):
        manager.start_job(pid)


# ------------------------------------------------------------------ #
# التوقفات الصادقة — WORKER / CAPABILITY / GATE / RETRYING
# ------------------------------------------------------------------ #

def test_waiting_worker_then_provision_resume_same_row(
        harness_env, sandbox_seam):
    """(012-H) فحص يحجب على البيئة ← WAITING_WORKER بالسلم والمسار ←
    المالك يوفر ← إعادة فحص ← استئناف في الصف نفسه بلا إعادة اعتماد."""
    env = harness_env
    sessions = env["sessions"]
    engine = env["build_engine"]()
    pid = _approved_project(env)

    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)
    manager.run_loop(job["id"])

    job = manager.get_job(job["id"])
    assert job["status"] == "WAITING_WORKER", job
    assert job["waiting_kind"] == "WORKER"
    detail = job["waiting_detail"]
    assert detail["blocked"][0]["capability_id"] == "sandbox"
    assert detail["owner_action"]          # إجراء المالك الحرفي
    assert "بلا إعادة اعتماد" in detail["recovery"]
    assert job["unblock_path"]             # مسار الرفع معروض
    waiting_event = next(
        e for e in service.list_events(sessions, pid, limit=100)
        if e["kind"] == "JOB_WAITING"
    )
    assert waiting_event["payload"]["waiting_kind"] == "WORKER"

    # المالك وفّر البيئة ← إعادة فحص تنجح ← استئناف في الصف نفسه
    sandbox_seam["provision"]()
    recheck = engine.recheck_preflight(pid)
    assert recheck["verdict"] == "PASS"
    resumed = manager.start_job(pid)
    assert resumed["id"] == job["id"], "استمرارية الصف — لا صف جديد"
    assert resumed["status"] == "QUEUED"
    manager.run_loop(resumed["id"])

    final = manager.get_job(job["id"])
    assert final["status"] == "WAITING_GATE"   # التحقق النهائي
    assert "GATE_AUTO_RESOLVED" in _kinds(sessions, pid)
    # الخطة ما زالت v1 معتمدة — لم يُمس القرار
    plan = service.latest_plan(sessions, pid)
    assert plan["approved_by_owner"] is True and plan["version"] == 1


def test_waiting_capability_on_unready_provider(harness_env,
                                                sandbox_seam):
    """مزود الأدوار غير جاهز ← PROVIDER_ACTION_REQUIRED ← الوظيفة
    تنتظر قدرة (لا عاملًا ولا بوابة قرار)."""
    env = harness_env
    sessions = env["sessions"]
    sandbox_seam["provision"]()   # البيئة جاهزة — الحجب حصرًا على المزود
    # موجّه بلا أي نقل حي — الأدوار كلها بلا مزود قابل للاستدعاء
    engine = env["build_engine"](providers=())
    pid = _approved_project(env, providers=())

    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)
    manager.run_loop(job["id"])

    job = manager.get_job(job["id"])
    assert job["status"] == "WAITING_CAPABILITY", job
    assert job["waiting_kind"] == "CAPABILITY"
    detail = job["waiting_detail"]
    assert "implementer" in detail["unready_roles"]
    assert detail["owner_action"]
    assert "EXECUTION_BLOCKED" in _kinds(sessions, pid)


def test_retrying_then_success_in_same_run(harness_env, sandbox_seam):
    """فشل عابر ← RETRY_REQUESTED ← الوظيفة تعلن RETRYING ثم تكمل."""
    env = harness_env
    sessions = env["sessions"]
    sandbox_seam["provision"]()
    env["executor"].fail_first = 1   # المحاولة الأولى تفشل ثم تنجح

    engine = env["build_engine"]()
    pid = _approved_project(env)
    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)
    manager.run_loop(job["id"])

    final = manager.get_job(job["id"])
    assert final["status"] == "WAITING_GATE"
    assert final["retries"] == 1
    kinds = _kinds(sessions, pid)
    assert "RETRY_REQUESTED" in kinds
    assert "JOB_RETRYING" in kinds
    assert "EXECUTION_FAILED" in kinds


def test_exhausted_failures_wait_revision_gate(harness_env, sandbox_seam):
    """فشل مستنفد ← بوابة مراجعة خطة ← WAITING_GATE ← موافقة ← خطة
    v2 تنجح ← الوظيفة تكمل في صفها نفسه."""
    env = harness_env
    sessions = env["sessions"]
    sandbox_seam["provision"]()
    env["executor"].fail_prefixes = ("كتابة المخرج الأول",)

    engine = env["build_engine"]()
    pid = _approved_project(env)
    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)
    manager.run_loop(job["id"])

    job = manager.get_job(job["id"])
    assert job["status"] == "WAITING_GATE"
    assert "PLAN_REVISION_APPROVAL" in job["waiting_detail"]["gate_kinds"]
    # إعادة واحدة معلنة ثم التصعيد (المحاولة المستنفدة تصعَّد بلا إعادة)
    assert job["retries"] == 1

    # المالك وافق المراجعة ← خطة v2 تُولد (خلفية محدودة 013.4 §1)
    # ← «أصلح البيئة» فنجحت
    gates = [g for g in service.list_gates(sessions, pid)
             if g["kind"] == "PLAN_REVISION_APPROVAL"
             and g["status"] == "PENDING"]
    engine.resolve_gate(pid, gates[0]["id"], approved=True)
    # (013.4 §1) التوليد خلفي — ننتظر الجلسة نهايتها الصادقة
    from workflow import planning_runtime

    session = planning_runtime.wait_for_planning(sessions, pid,
                                                 timeout=15.0)
    assert session["state"] == "COMPLETED", session
    engine.approve_plan(pid, approved=True)     # خطة v2
    env["executor"].fail_prefixes = ()          # الإصلاح: تنجح الآن

    resumed = manager.start_job(pid)
    assert resumed["id"] == job["id"]
    manager.run_loop(resumed["id"])
    final = manager.get_job(job["id"])
    assert final["status"] == "WAITING_GATE"
    assert service.latest_plan(sessions, pid)["version"] == 2


# ------------------------------------------------------------------ #
# الإيقاف والاستئناف والانقطاع (012-G)
# ------------------------------------------------------------------ #

def test_stop_honored_at_checkpoint_then_resume_same_row(
        harness_env, sandbox_seam):
    """إيقاف المالك يُكرَّم عند checkpoint ← الوظيفة PAUSED ← استئناف
    صريح ← الصف نفسه يكمل."""
    env = harness_env
    sandbox_seam["provision"]()
    engine = env["build_engine"]()
    pid = _approved_project(env)

    engine.request_stop(pid, "اختبار الإيقاف")
    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)
    manager.run_loop(job["id"])
    assert manager.get_job(job["id"])["status"] == "PAUSED"
    assert "JOB_PAUSED" in _kinds(env["sessions"], pid)

    engine.resume(pid)
    resumed = manager.mark_resumed(pid)
    assert resumed["id"] == job["id"]
    assert resumed["status"] == "QUEUED"
    assert "JOB_RESUMED" in _kinds(env["sessions"], pid)
    manager.run_loop(job["id"])
    assert manager.get_job(job["id"])["status"] == "WAITING_GATE"


def test_recovery_marks_running_job_interrupted_and_resumable(
        harness_env, sandbox_seam):
    """(012-G) وفاة العملية لا تترك RUNNING كاذبة: الإقلاع الجديد
    يوسم INTERRUPTED ويعلن قابلية الاستئناف — ثم الاستئناف يكمل."""
    env = harness_env
    sessions = env["sessions"]
    sandbox_seam["provision"]()
    engine = env["build_engine"]()
    pid = _approved_project(env)

    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)

    # محاكاة الموت أثناء الدوران: الحالة كما كانت لحظة الوفاة
    manager._write(job["id"], status="RUNNING",
                   heartbeat_at=None, tick_count=5)

    # إقلاع جديد (مدير جديد — لا ذاكرة مشتركة) يقيّم ويعلن
    fresh_manager = env["build_manager"]()
    assessments = fresh_manager.assess_jobs_recovery()
    matching = [a for a in assessments if a["job_id"] == job["id"]]
    assert matching and matching[0]["from_status"] == "RUNNING"
    assert matching[0]["status"] == "INTERRUPTED"
    assert matching[0]["resumable"] is True
    assert matching[0]["recommendation"] == "RESUMABLE"
    assert "JOB_RECOVERY_ASSESSED" in _kinds(sessions, pid)

    recovered = fresh_manager.get_job(job["id"])
    assert recovered["status"] == "INTERRUPTED"

    # الاستئناف الصريح (قرار مالك — لا تنفيذ عشوائي) في الصف نفسه
    engine.resume(pid)
    resumed = fresh_manager.start_job(pid)
    assert resumed["id"] == job["id"]
    assert resumed["status"] == "QUEUED"
    run_manager = env["build_manager"](engine=engine)
    run_manager.run_loop(job["id"])
    assert run_manager.get_job(job["id"])["status"] == "WAITING_GATE"


def test_waiting_jobs_survive_recovery_without_interruption(
        harness_env, sandbox_seam):
    """الانتظارات لا تُوسم مقاطعة — لا شيء ضاع أصلًا (لا حياة كاذبة
    ولا موت كاذب)."""
    env = harness_env
    # الافتراضي في الوصفة: لا بيئة جاهزة — يبقى في انتظار عامل
    engine = env["build_engine"]()
    pid = _approved_project(env)
    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)
    manager.run_loop(job["id"])
    assert manager.get_job(job["id"])["status"] == "WAITING_WORKER"

    fresh = env["build_manager"]()
    assessments = fresh.assess_jobs_recovery()
    matching = [a for a in assessments if a["job_id"] == job["id"]]
    assert matching[0]["from_status"] == "WAITING_WORKER"
    assert matching[0]["status"] == "WAITING_WORKER"   # كما هي
    assert matching[0]["resumable"] is True
    assert fresh.get_job(job["id"])["status"] == "WAITING_WORKER"


def test_rejected_gate_stops_job(harness_env, sandbox_seam):
    """رفض المالك لبوابة المراجعة يغلق الوظيفة صادقة (STOPPED) لا
    تبقى منتظرة لبوابة ماتت."""
    env = harness_env
    sessions = env["sessions"]
    sandbox_seam["provision"]()
    env["executor"].fail_prefixes = ("كتابة المخرج الأول",)
    engine = env["build_engine"]()
    pid = _approved_project(env)
    manager = env["build_manager"](engine=engine)
    job = manager.start_job(pid)
    manager.run_loop(job["id"])

    gates = [g for g in service.list_gates(sessions, pid)
             if g["status"] == "PENDING"]
    engine.resolve_gate(pid, gates[0]["id"], approved=False)
    stopped = manager.mark_stopped(pid)
    assert stopped["status"] == "STOPPED"
    assert "JOB_STOPPED" in _kinds(sessions, pid)
    # صف الوظيفة نهائي — لا يستأنف في صفه
    with pytest.raises(Exception):
        manager.start_job(pid)


# ------------------------------------------------------------------ #
# دفتر الوظيفة — حدود صادقة
# ------------------------------------------------------------------ #

def test_bookkeeping_manager_rejects_run_loop(harness_env):
    """مدير بلا محرك = دفاتر فقط — run_loop يرفض صراحة لا يفشل غامضًا."""
    manager = harness_env["build_manager"]()
    job = manager.start_job(_approved_project(harness_env))
    with pytest.raises(Exception, match="محرك"):
        manager.run_loop(job["id"])


def test_start_job_rejects_terminal_project(harness_env):
    """المشروع النهائي (STOPPED برفض بوابة) لا يقبل وظيفة جديدة."""
    env = harness_env
    engine = env["build_engine"]()
    project = engine.create_project("نهاية", "هدف ينتهي سريعًا")
    engine.generate_plan(project["id"])
    gate = next(
        g for g in service.list_gates(env["sessions"], project["id"])
        if g["kind"] == "PLAN_APPROVAL" and g["status"] == "PENDING"
    )
    engine.resolve_gate(project["id"], gate["id"], approved=False)
    stopped = service.get_project(env["sessions"], project["id"])
    assert stopped["status"] == "STOPPED"

    manager = env["build_manager"]()
    with pytest.raises(Exception, match="نهائية"):
        manager.start_job(project["id"])


def test_job_for_project_and_list(harness_env, sandbox_seam):
    """القراءات: أحدث وظيفة للمشروع + القائمة العامة."""
    env = harness_env
    sandbox_seam["provision"]()
    engine = env["build_engine"]()
    pid = _approved_project(env)
    manager = env["build_manager"]()

    assert manager.job_for_project(pid) is None   # لم تُشغل بعد
    job = manager.start_job(pid)
    assert manager.job_for_project(pid)["id"] == job["id"]
    assert any(j["project_id"] == pid for j in manager.list_jobs())
    assert manager.get_job(job["id"])["id"] == job["id"]
