"""اختبارات دورة حياة المحرك (الأمر 007 §22) — الحالة الدائمة مثبتة.

كل سيناريو من العشرين المطلوبة يُختبر هنا على المحرك الحقيقي والقاعدة
الحقيقية (حدود خارجية منظمة فقط: المخطط والمنفذ والموجّه)، والاختبار
الأخير يحاكي العملية الكاملة: إنشاء ← اعتماد ← تنفيذ ← دليل ← restart
فعلي (محرك جديد على نفس القاعدة) ← استرداد ← استئناف ← اكتمال ←
تدقيق نهائي ← تحقق المالك.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from plans import SCRIPTED_PLAN, TWO_PHASE_PLAN  # noqa: E402
from workflow import service  # noqa: E402


def _approved_project(env, *, plan=None):
    """مشروع بخطة معتمدة جاهز للتشغيل."""
    engine = env["build_engine"](plan=plan)
    project = engine.create_project("مشروع الاختبار", "هدف اختبار كامل")
    engine.generate_plan(project["id"])
    engine.approve_plan(project["id"], approved=True)
    return project["id"]


# ------------------------------------------------------------------ #
# §22.1-§22.6 — الدوام الأساسي
# ------------------------------------------------------------------ #

def test_project_creation_persists(wf_env):
    """1. إنشاء المشروع يدوم — قراءة جديدة من القاعدة."""
    engine = wf_env["build_engine"]()
    project = engine.create_project("مشروع دائم", "هدف مستمر")
    from workflow.engine import ProjectEngine

    # محرك جديد (محاكاة restart) يرى المشروع نفسه
    fresh = ProjectEngine(
        wf_env["sessions"], router_factory=lambda: None
    )
    found = fresh._project(project["id"])
    assert found["status"] == "DRAFT"
    assert found["objective"] == "هدف مستمر"
    assert service.list_projects(wf_env["sessions"])[0]["id"] == project["id"]


def test_plan_v1_persists(wf_env):
    """2. الخطة v1 تدوم بعد التوليد."""
    engine = wf_env["build_engine"]()
    project = engine.create_project("p", "هدف")
    plan = engine.generate_plan(project["id"])
    stored = service.get_plan(wf_env["sessions"], plan["id"])
    assert stored["version"] == 1
    assert stored["status"] == "AWAITING_OWNER_APPROVAL"
    assert len(stored["phases"]) == 1
    assert len(stored["phases"][0]["steps"]) == 2


def test_owner_approval_persists(wf_env):
    """3. اعتماد المالك يدوم — القاعدة لا الذاكرة."""
    pid = _approved_project(wf_env)
    plan = service.latest_plan(wf_env["sessions"], pid)
    assert plan["approved_by_owner"] is True
    assert plan["approved_at"] is not None
    assert plan["status"] == "ACTIVE"
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "READY"


def test_phase_step_state_persists(wf_env):
    """4. حالة المراحل/الخطوات تدوم — بعد التشغيل تبقى في القاعدة."""
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    engine.run(pid)
    phases = service.list_phases(wf_env["sessions"], pid)
    assert phases[0]["status"] == "COMPLETED"
    steps = service.phase_steps(wf_env["sessions"], phases[0]["id"])
    assert all(s["status"] == "COMPLETED" for s in steps)


def test_execution_creates_durable_record(wf_env):
    """5. كل تنفيذ سجل دائم بمزوده ونموذجه ومساحة عمله."""
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    engine.run(pid)
    executions = service.list_executions(wf_env["sessions"], pid)
    assert len(executions) == 2  # خطوتان
    assert executions[0]["status"] == "COMPLETED"
    assert executions[0]["provider"]
    assert executions[0]["workspace"]
    assert executions[0]["attempt"] >= 1


def test_evidence_links_execution_and_step(wf_env):
    """6. الدليل مرتبط بالتنفيذ والخطوة — قابل للرجوع بالمعرفات."""
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    engine.run(pid)
    evidences = service.list_evidence(wf_env["sessions"], pid)
    assert len(evidences) == 2
    for evidence in evidences:
        assert evidence["execution_id"]
        assert evidence["step_id"]
        assert evidence["files"]
        assert evidence["evidence_sha256"]
        execution = [
            e for e in service.list_executions(wf_env["sessions"], pid)
            if e["id"] == evidence["execution_id"]
        ]
        assert execution, "الدليل يتيم — لا تنفيذ له"
        assert execution[0]["step_id"] == evidence["step_id"]


# ------------------------------------------------------------------ #
# §22.7-§22.9 — الفشل والتشخيص والمراجعة
# ------------------------------------------------------------------ #

def test_failure_creates_diagnosis(wf_env):
    """7. الفشل يخلق تشخيصًا موثقًا — RetryRecord بسبب وقرار."""
    executor = wf_env["executor"]
    executor.fail_prefixes = ("كتابة المخرج الأول",)
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    outcome = engine.run(pid)
    steps = _steps_of(wf_env, pid)
    first = [s for s in steps if s["ordinal"] == 1][0]
    second = [s for s in steps if s["ordinal"] == 2][0]
    # الخطوة الأولى فشلت مرتين (استنفاد الميزانية) والثانية لم تبدأ
    assert first["attempts"] == 2
    assert first["status"] == "FAILED"
    assert second["attempts"] == 0, "الخطوة التالية بدأت رغم انسداد الأولى"
    executions = service.list_executions(wf_env["sessions"], pid)
    assert all(e["status"] == "FAILED" for e in executions)
    # التشخيص موجود في سجلات الإعادة: إعادة ثم تصعيد
    with wf_env["sessions"]() as session:
        from sqlalchemy import select

        from workflow.models import RetryRecord

        retries = session.scalars(
            select(RetryRecord).order_by(RetryRecord.id)
        ).all()
        assert len(retries) == 2, "لا تشخيصان لفشلين (إعادة + تصعيد)"
        assert retries[0].decision == "RETRY"
        assert retries[0].reason
        assert retries[0].diagnosis
        assert retries[1].decision == "ESCALATE"


def _steps_of(env, pid):
    steps = []
    for phase in service.list_phases(env["sessions"], pid):
        steps.extend(service.phase_steps(env["sessions"], phase["id"]))
    return steps


def test_retry_creates_new_execution(wf_env):
    """8. الإعادة تنشئ تنفيذًا جديدًا — لا إعادة استخدام سجل سابق."""
    executor = wf_env["executor"]

    # أول تنفيذ للخطوة الأولى يفشل (فشل تدقيق: ملف خاطئ) ثم ينجح
    executor.audit_fail_execs = {1}
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    outcome = engine.run(pid)
    steps = _steps_of(wf_env, pid)
    first = [s for s in steps if s["ordinal"] == 1][0]
    assert first["attempts"] == 2, "الإعادة لم تُنشئ محاولة ثانية"
    executions = [
        e for e in service.list_executions(wf_env["sessions"], pid)
        if e["step_id"] == first["id"]
    ]
    assert len(executions) == 2, "سجل واحد لتنفيذين — إعادة استخدام ممنوعة"
    attempts = sorted(e["attempt"] for e in executions)
    assert attempts == [1, 2]
    assert first["status"] == "COMPLETED"


def test_plan_revision_creates_v2_without_deleting_v1(wf_env):
    """9. مراجعة الخطة: v2 تُنشأ وv1 تبقى SUPERSEDED بسببها وأدلتها."""
    executor = wf_env["executor"]
    executor.fail_prefixes = ("كتابة المخرج الأول", "كتابة المخرج الثاني")
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    engine.run(pid)  # كل الخطوات تفشل مرتين ← بوابة مراجعة الخطة
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "BLOCKED"
    gates = service.open_gates(wf_env["sessions"], pid)
    assert gates and gates[0]["kind"] == "PLAN_REVISION_APPROVAL"

    engine.resolve_gate(pid, gates[0]["id"], approved=True)
    plans = [
        p for p in [service.latest_plan(wf_env["sessions"], pid)]
    ]
    v2 = plans[0]
    assert v2["version"] == 2
    assert v2["status"] == "AWAITING_OWNER_APPROVAL"
    assert v2["supersedes_plan_id"] is not None
    v1 = service.get_plan(wf_env["sessions"], v2["supersedes_plan_id"])
    assert v1 is not None, "v1 حُذفت — الممنوع الصريح (§4)"
    assert v1["status"] == "SUPERSEDED"
    assert v2["revision_reason"], "المراجعة بلا سبب موثق"


# ------------------------------------------------------------------ #
# §22.10-§22.12 — نقاط الاستئناف وإعادة التشغيل
# ------------------------------------------------------------------ #

def test_checkpoint_survives_process_recreation(wf_env):
    """10. الـcheckpoint يبقى بعد إعادة إنشاء العملية (محرك جديد)."""
    from workflow.engine import ProjectEngine

    pid = _approved_project(wf_env, plan=TWO_PHASE_PLAN)
    engine = wf_env["build_engine"](plan=TWO_PHASE_PLAN)
    # نفّذ مرحلة واحدة فقط بحد النبضات = 3 (بدء+تنفيذ+مراجعة مرحلة)
    engine.run(pid, max_ticks=3)
    checkpoint = service.latest_checkpoint(wf_env["sessions"], pid)
    assert checkpoint is not None, "لا checkpoint بعد العمل"
    # محرك جديد يقرأ نفس الـcheckpoint من القاعدة
    fresh = ProjectEngine(wf_env["sessions"], router_factory=lambda: None)
    again = service.latest_checkpoint(fresh._sessions, pid)
    assert again["id"] == checkpoint["id"]


def test_restart_recovery_finds_unfinished_projects(wf_env):
    """11. الاسترداد يجد المشاريع غير المنتهية ويقيّمها — لا تشغيل."""
    from workflow.engine import ProjectEngine

    pid = _approved_project(wf_env)
    # شغّل ثم أوقف بالعلم — المشروع يصبح PAUSED بلقطة
    engine = wf_env["build_engine"]()
    engine.request_stop(pid, "اختبار الاسترداد")
    engine.run(pid)
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "PAUSED"

    fresh = ProjectEngine(wf_env["sessions"], router_factory=lambda: None)
    assessments = fresh.assess_recovery()
    found = [a for a in assessments if a["project_id"] == pid]
    assert found, "الاسترداد لم يجد المشروع غير المنتهي"
    assert found[0]["recommendation"] == "RESUMABLE"
    assert found[0]["checkpoint"]
    # لا تنفيذ عشوائي: الحالة ما زالت PAUSED بعد التقييم
    assert service.get_project(
        wf_env["sessions"], pid
    )["status"] == "PAUSED"


def test_resume_continues_from_checkpoint(wf_env):
    """12. الاستئناف يكمل من نقطة التوقف — الخطوة المتبقية تنفذ."""
    executor = wf_env["executor"]
    executor.stop_prefixes = ("كتابة المخرج الثاني",)
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    outcome = engine.run(pid)
    assert outcome["action"] == "paused"
    steps = _steps_of(wf_env, pid)
    assert steps[0]["status"] == "COMPLETED"
    assert steps[1]["status"] == "READY"  # أوقفت أثناءها — جاهزة للإعادة

    # محاكاة restart: محرك جديد يستأنف من القاعدة وحدها
    executor.stop_prefixes = ()
    fresh_engine = wf_env["build_engine"]()
    fresh_engine.resume(pid)
    result = fresh_engine.run(pid)
    steps = _steps_of(wf_env, pid)
    assert all(s["status"] == "COMPLETED" for s in steps)
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "COMPLETED"
    assert project["completion_state"] == "CANDIDATE"


# ------------------------------------------------------------------ #
# §22.13-§22.16 — المراحل والبوابات والتحقق
# ------------------------------------------------------------------ #

def test_completed_phase_advances_to_next_phase(wf_env):
    """13. المرحلة المكتملة تنقل تلقائيًا إلى التالية."""
    pid = _approved_project(wf_env, plan=TWO_PHASE_PLAN)
    engine = wf_env["build_engine"](plan=TWO_PHASE_PLAN)
    engine.run(pid)
    phases = service.list_phases(wf_env["sessions"], pid)
    active = [p for p in phases if p["plan_id"] == service.latest_plan(
        wf_env["sessions"], pid)["id"]]
    assert [p["status"] for p in active] == ["COMPLETED", "COMPLETED"]
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "COMPLETED"


def test_failed_phase_does_not_silently_advance(wf_env):
    """14. المرحلة الفاشلة لا تتقدم صامتة — بوابة مالك أو تصعيد."""
    executor = wf_env["executor"]
    executor.fail_prefixes = ("كتابة المخرج",)  # كل الخطوات تفشل دائمًا
    pid = _approved_project(wf_env, plan=TWO_PHASE_PLAN)
    engine = wf_env["build_engine"](plan=TWO_PHASE_PLAN)
    outcome = engine.run(pid)
    assert outcome["action"] == "blocked"
    phases = [
        p for p in service.list_phases(wf_env["sessions"], pid)
        if p["status"] != "PLANNED"
    ]
    # مرحلة واحدة فقط بدأت — الثانية لم تُفتح أبدًا
    assert len(phases) == 1
    assert phases[0]["status"] != "COMPLETED"
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "BLOCKED"


def test_owner_gate_blocks_autonomous_progress(wf_env):
    """15. البوابة المفتوحة تمنع التقدم الذاتي — tick لا ينفذ شيئًا."""
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    # قبل الاعتماد: tick ينتظر المالك ولا ينفذ
    service.update_project(wf_env["sessions"], pid,
                           status="AWAITING_OWNER_APPROVAL")
    outcome = engine.tick(pid)
    assert outcome["action"] == "wait_owner"
    assert not wf_env["executor"].runs, "tick نفذ خطوة رغم بوابة مفتوحة!"


def test_final_verified_only_by_owner(wf_env):
    """16. VERIFIED لا يصنعه إلا المالك — المحرك لا يملك المسار."""
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    engine.run(pid)
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "COMPLETED"  # مرشح — ليس VERIFIED
    # البوابة موجودة
    gates = service.open_gates(wf_env["sessions"], pid)
    assert any(g["kind"] == "FINAL_VERIFICATION" for g in gates)
    # المحرك الكامل لم يكتب VERIFIED في أي مكان — فقط verify() (المالك)
    verified = engine.verify(pid)
    assert verified["status"] == "VERIFIED"
    assert verified["completion_state"] == "VERIFIED"


# ------------------------------------------------------------------ #
# §22.17-§22.20 — السجلات والروابط والصدق
# ------------------------------------------------------------------ #

def test_event_log_survives_restart(wf_env):
    """17. سجل الأحداث يبقى بعد إعادة التشغيل — كل الانتقالات المهمة."""
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    engine.run(pid)
    engine.verify(pid)
    kinds = {e["kind"] for e in service.list_events(
        wf_env["sessions"], pid, limit=500
    )}
    required = {
        "PROJECT_CREATED", "PLAN_APPROVAL_REQUIRED", "PLAN_APPROVED",
        "PHASE_STARTED", "STEP_STARTED", "EXECUTION_STARTED",
        "EXECUTION_COMPLETED", "EVIDENCE_CREATED", "TEST_COMPLETED",
        "REVIEW_COMPLETED", "AUDIT_COMPLETED", "CHECKPOINT_CREATED",
        "PHASE_COMPLETED", "PROJECT_COMPLETION_CANDIDATE",
        "PROJECT_VERIFIED", "OWNER_GATE_RESOLVED",
    }
    missing = required - kinds
    assert not missing, f"أحداث مفقودة من السجل الدائم: {sorted(missing)}"


def test_commit_evidence_audit_remain_linked(wf_env):
    """18. الروابط تبقى: Step→Execution→Evidence→Audit بمعرفات صحيحة."""
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    engine.run(pid)
    audits = service.list_audits(wf_env["sessions"], pid)
    assert audits
    for audit in audits:
        if audit["step_id"] is None:
            continue  # تدقيق المرحلة
        execution = [
            e for e in service.list_executions(wf_env["sessions"], pid)
            if e["id"] == audit["execution_id"]
        ]
        assert execution
        evidence = [
            ev for ev in service.list_evidence(wf_env["sessions"], pid)
            if ev["execution_id"] == audit["execution_id"]
        ]
        assert evidence, "تدقيق بلا دليل مرتبط"
        assert str(audit["evidence_refs"][0]) == str(evidence[0]["id"])
        assert audit["findings"]["implemented"]["files"]


def test_no_completion_without_final_audit(wf_env, monkeypatch):
    """19. لا اكتمال بلا تدقيق نهائي ناجح — فشله يفتح بوابة لا يكمل."""
    from workflow import auditor as auditor_mod

    def failing_final(project, phases, steps, evidences, audits):
        return {"verdict": "FAIL", "unresolved_issues": ["x"],
                "phases_total": len(phases), "phases_completed": 0,
                "phases_pending": [p["id"] for p in phases],
                "steps_pending": [], "failed_audits": [],
                "evidence_integrity": {}, "broken_evidence": []}

    monkeypatch.setattr(auditor_mod, "audit_final", failing_final)
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    outcome = engine.run(pid)
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "BLOCKED", "اكتمل المشروع بلا تدقيق نهائي!"
    assert project["completion_state"] != "CANDIDATE"
    gates = service.open_gates(wf_env["sessions"], pid)
    assert any(g["kind"] == "PLAN_REVISION_APPROVAL" for g in gates)


def test_execution_not_silently_verified(wf_env):
    """20. التنفيذ المكتمل لا يعامل كأنه VERIFIED — الفرق مصان."""
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"]()
    engine.run(pid, max_ticks=1)  # تنفيذ واحد فقط
    executions = service.list_executions(wf_env["sessions"], pid)
    completed = [e for e in executions if e["status"] == "COMPLETED"]
    assert completed, "النبضة الأولى يجب أن تنجز تنفيذًا"
    project = service.get_project(wf_env["sessions"], pid)
    # تنفيذ مكتمل ≠ مشروع مكتمل ≠ تحقق — ثلاثة مستويات صادقة
    assert project["status"] == "RUNNING"
    assert project["completion_state"] == ""
    with pytest.raises(Exception):
        engine.verify(pid)  # التحقق قبل الأوان مرفوض


# ------------------------------------------------------------------ #
# اختبار المحاكاة الكاملة (§22 الختامي) — restart حقيقي في المنتصف
# ------------------------------------------------------------------ #

def test_full_lifecycle_with_process_restart(wf_env):
    """المسار الكامل: إنشاء ← اعتماد ← تنفيذ ← دليل ← restart فعلي
    (محرك جديد على نفس القاعدة) ← استرداد ← استئناف ← اكتمال مرحلة ←
    تدقيق نهائي ← تحقق المالك — كل حالة من القاعدة وحدها."""
    from workflow.engine import ProjectEngine

    # المرحلة 1: إنشاء + خطة + اعتماد + تنفيذ أول خطوة
    engine = wf_env["build_engine"]()
    project = engine.create_project("دورة كاملة", "هدف الدورة الكاملة")
    pid = project["id"]
    engine.generate_plan(pid)
    engine.approve_plan(pid, approved=True)
    # نبضة واحدة: بدء المرحلة + تنفيذ الخطوة الأولى حصرًا
    engine.run(pid, max_ticks=1)
    steps = _steps_of(wf_env, pid)
    assert steps[0]["status"] == "COMPLETED"
    assert steps[1]["status"] == "PENDING"

    # المرحلة 2: "عملية جديدة" — محرك جديد لا يعرف شيئًا من الذاكرة
    del engine
    fresh_engine = ProjectEngine(
        wf_env["sessions"],
        router_factory=lambda: ScriptedRouterForRestart(),
        planner_factory=lambda: wf_env["planner"],
    )
    assessments = fresh_engine.assess_recovery()
    assert any(a["project_id"] == pid for a in assessments)

    # المرحلة 3: استئناف صريح وإكمال
    fresh_engine.resume(pid)
    outcome = fresh_engine.run(pid)
    steps = _steps_of(wf_env, pid)
    assert all(s["status"] == "COMPLETED" for s in steps)

    # المرحلة 4: مرشح + تحقق المالك
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "COMPLETED"
    assert project["completion_state"] == "CANDIDATE"
    verified = fresh_engine.verify(pid)
    assert verified["status"] == "VERIFIED"
    # الأحداث كلها باقية
    kinds = [e["kind"] for e in service.list_events(
        wf_env["sessions"], pid, limit=500)]
    assert "RECOVERY_ASSESSED" in kinds
    assert "PROJECT_RESUMED" in kinds


class ScriptedRouterForRestart:
    def has_live_provider(self, provider_id):
        return True

    def live_providers(self):
        return ["nvidia"]


# ------------------------------------------------------------------ #
# 007.1 §19 — بوابة المزود داخل الحلقة
# ------------------------------------------------------------------ #

def test_provider_not_ready_blocks_step_then_resumes(wf_env):
    """مزود غير جاهز ← خطوة محجوبة ← دليل ← فعل مالك ← جاهز ← تستأنف."""
    # المزود غير متاح في الموجّه — كل الأدوار بلا نقل
    pid = _approved_project(wf_env)
    engine = wf_env["build_engine"](providers=())  # لا مزود حي
    outcome = engine.run(pid)
    assert outcome["action"] == "blocked"
    project = service.get_project(wf_env["sessions"], pid)
    assert project["status"] == "BLOCKED"

    # دليل المنع موجود (007.1 §17) — يسمي المزود والحالة
    evidences = service.list_evidence(wf_env["sessions"], pid)
    blocked_evidence = [e for e in evidences
                        if e["verdict"] == "EXECUTION_BLOCKED"]
    assert blocked_evidence, "لا دليل للمنع — انتهاك §17"
    assert blocked_evidence[0]["tests"]["unready_roles"]

    # بوابة المالك من النوع الصحيح مع سبب واضح
    gates = service.open_gates(wf_env["sessions"], pid)
    assert gates[0]["kind"] == "PROVIDER_ACTION_REQUIRED"
    assert "غير جاهز" in gates[0]["reason"]

    # فعل المالك: عالج المزود وحل البوابة ← استئناف ← إكمال
    engine_after_fix = wf_env["build_engine"](providers=("nvidia",))
    engine_after_fix.resolve_gate(pid, gates[0]["id"], approved=True)
    engine_after_fix.resume(pid)
    engine_after_fix.run(pid)
    steps = _steps_of(wf_env, pid)
    assert all(s["status"] == "COMPLETED" for s in steps)
    verified_project = service.get_project(wf_env["sessions"], pid)
    assert verified_project["status"] == "COMPLETED"
