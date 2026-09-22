"""اختبارات مسار التوفير الكامل (الأمر 011 §2+§17-§19+§26-§27).

السيناريو المطلوب حرفيًا: خطة معتمدة ← فحص يحجب (لا بيئة) ← بوابة
توفير (BLOCKED لا قرار) ← المالك يوفر بيئة ← إعادة فحص ← فتح آلي
← استئناف بلا إعادة اعتماد. مع السياسة: STRICT يطلب معزولة،
COMPATIBLE يقبل المعلنة غير المعزولة.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sqlalchemy import select as sa_select  # noqa: E402

from execution.models import ExecutionEnvironment  # noqa: E402
from workflow import service  # noqa: E402
from workflow.engine import EngineError  # noqa: E402

from test_engine_lifecycle import _approved_project  # noqa: E402


def _set_local_env(sessions, *, status, sandboxed=None):
    """ضبط بيئة التنفيذ المحلية في السجل — مصدر الحقيقة للمشتق.

    sandboxed يزامَن مع توفر الركيزة الفعلي عند القراءة (صدق 011 §5)
    — لا معنى لفرض sandboxed=0 على مضيف ركيزته متاحة، لذا محاكاة
    «بيئة متوافقة فقط» تمر عبر بيئة مسماة مستقلة أدناه.
    """
    from execution import service as execution_service

    execution_service.ensure_local_registered(sessions)
    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.name.in_(("local-linux",
                                           "local-windows")))).first()
        row.status = status
        if sandboxed is not None:
            row.sandboxed = sandboxed
        s.commit()
    return row.id


def _compat_env_only(sessions):
    """(§26 بصدق) بيئة متوافقة وحيدة جاهزة: بيئة مسماة بلا عزل +
    الافتراضية غير جاهزة — كما على مضيف Windows بلا ركيزة."""
    from execution import service as execution_service

    _set_local_env(sessions, status="NOT_READY")
    env = execution_service.add_environment(
        sessions, name="compat-worker", backend="LOCAL",
    )
    with sessions() as s:
        row = s.get(ExecutionEnvironment, env["id"])
        row.status = "READY"
        row.sandboxed = 0
        s.commit()
    return env["id"]


@pytest.fixture()
def probe_seam(monkeypatch):
    """وصفة مسبار sandbox من المصدر (سجل البيئات) — حتمية عبر
    المنصات: لا انطلاق ركيزة فعلي هنا (له اختباراته المستقلة)."""
    from execution import service as execution_service

    def fake_sandbox_probe(sessions, **_kwargs):
        environments = execution_service.list_environments(sessions)
        ready = [
            e for e in environments
            if e["status"] == "READY" and e.get("sandboxed")
        ]
        return {
            "status": "READY" if ready else "NOT_READY",
            "reason": "بيئة معزولة جاهزة (وصفة)" if ready
            else "لا بيئة تنفيذ معزولة جاهزة (وصفة)",
            "latency_ms": 1, "ttl_seconds": 300,
            "failure_class": "" if ready else "SANDBOX_FAILURE",
            "failure_stage": "" if ready else "STARTUP",
            "details": {
                "environment_id": ready[0]["id"] if ready else None,
                "test_seam": True,
            },
        }

    monkeypatch.setattr(
        execution_service, "sandbox_probe_result", fake_sandbox_probe
    )
    return fake_sandbox_probe


# ------------------------------------------------------------------ #
# §19 — المسار الكامل: حجب ← توفير ← إعادة فحص ← فتح ← استئناف
# ------------------------------------------------------------------ #

def test_blocked_then_provisioned_recheck_resume_without_reapproval(
        wf_env, probe_seam):
    """(§19 حرفيًا) الخطة لم تتغير → لا إعادة اعتماد أبدًا."""
    pid = _approved_project(wf_env)
    sessions = wf_env["sessions"]

    # 1) لا بيئة جاهزة → الفحص يحجب قبل أول خطوة
    engine = wf_env["build_engine"]()
    outcome = engine.run(pid)
    assert outcome["action"] == "blocked"
    assert outcome.get("blocked_kind") == "preflight"
    project = service.get_project(sessions, pid)
    assert project["status"] == "BLOCKED"

    # بوابة توفير (BLOCKED) لا قرار — والسبب يسمي المطلوب
    gates_rows = service.open_gates(sessions, pid)
    assert len(gates_rows) == 1
    gate = gates_rows[0]
    assert gate["kind"] == "PREFLIGHT_BLOCKED"
    assert gate["status"] == "BLOCKED"
    assert gate["details"]["recheck_hint"]

    # الأحداث الدائمة: PREFLIGHT_BLOCKED بالقصة كاملة
    kinds = [e["kind"] for e in service.list_events(sessions, pid, 100)]
    assert "PREFLIGHT_BLOCKED" in kinds

    # 2) المالك يوفر البيئة (التسجيل في المصدر: سجل البيئات)
    _set_local_env(sessions, status="READY", sandboxed=1)

    # 3) إعادة الفحص → PASS → حل آلي للبوابة → READY
    recheck = engine.recheck_preflight(pid)
    assert recheck["verdict"] == "PASS"
    refreshed = service.list_gates(sessions, pid)
    assert refreshed[0]["status"] == "APPROVED"
    assert refreshed[0]["details"].get("auto_resolved") is True
    assert service.get_project(sessions, pid)["status"] == "READY"

    # 4) استئناف بلا إعادة اعتماد — الخطة معتمدة كما هي
    resumed = engine.resume(pid)
    assert resumed["status"] == "RUNNING"
    plan = service.latest_plan(sessions, pid)
    assert plan["approved_by_owner"] is True
    # لا بوابة PLAN_APPROVAL جديدة فُتحت
    assert not [
        g for g in service.list_gates(sessions, pid)
        if g["kind"] == "PLAN_APPROVAL" and g["status"] == "PENDING"
    ]

    # 5) الحلقة تكمل فعليًا حتى الإكمال
    final = engine.run(pid)
    steps = [
        st for ph in service.list_phases(sessions, pid)
        for st in service.phase_steps(sessions, ph["id"])
    ]
    assert steps and all(s["status"] == "COMPLETED" for s in steps)
    assert service.get_project(sessions, pid)["status"] == "COMPLETED"


def test_resume_with_pending_decision_gate_still_refuses(wf_env, probe_seam):
    """بوابة قرار PENDING تمنع الاستئناف — التوفير وحده لا يكفي
    حين يكون القرار الجوهري (اعتماد خطة مثلًا) معلقًا."""
    pid = _approved_project(wf_env)
    sessions = wf_env["sessions"]
    engine = wf_env["build_engine"]()
    engine.run(pid)   # → BLOCKED ببوابة توفير
    # افتح بوابة قرار إضافية (محاكاة تصعيد يتطلب قرارًا)
    service.open_gate(sessions, pid, "ESCALATION", "قرار مطلوب", {})
    _set_local_env(sessions, status="READY", sandboxed=1)
    with pytest.raises(EngineError, match="بوابات قرار تنتظرك"):
        engine.resume(pid)


def test_run_rechecks_provisioning_automatically(wf_env, probe_seam):
    """زر «تشغيل» وحده يكفي بعد التوفير: tick يرى بوابات توفير فقط
    فيعيد الفحص تلقائيًا (BLOCKED ← RECHECK ← READY ← OPEN)."""
    pid = _approved_project(wf_env)
    sessions = wf_env["sessions"]
    engine = wf_env["build_engine"]()
    engine.run(pid)   # حجب
    assert service.get_project(sessions, pid)["status"] == "BLOCKED"
    # المالك وفر البيئة ثم ضغط «تشغيل» مباشرة (بلا زر إعادة فحص)
    _set_local_env(sessions, status="READY", sandboxed=1)
    outcome = wf_env["build_engine"]().run(pid)
    assert outcome.get("blocked_kind") != "preflight"
    assert service.get_project(sessions, pid)["status"] == "COMPLETED"
    # حل آلي حدث فعلًا
    kinds = [e["kind"] for e in service.list_events(sessions, pid, 200)]
    assert "GATE_AUTO_RESOLVED" in kinds and "PREFLIGHT_PASS" in kinds


# ------------------------------------------------------------------ #
# §26 — السياسة: عزل صارم مقابل توافق محلي معلن
# ------------------------------------------------------------------ #

def test_strict_policy_blocks_without_isolated_env(wf_env, probe_seam):
    """بيئة متوافقة (بلا عزل) وحيدة جاهزة + سياسة STRICT → حجب صادق
    يسمي المطلوب: بيئة معزولة (لا خفض للسقف §28)."""
    pid = _approved_project(wf_env)
    sessions = wf_env["sessions"]
    _compat_env_only(sessions)
    outcome = wf_env["build_engine"]().run(pid)
    assert outcome["action"] == "blocked"
    assert outcome.get("blocked_kind") == "preflight"
    blocked = outcome["preflight"]["blocked"]
    sandbox_block = [b for b in blocked
                     if b["capability_id"] == "sandbox"][0]
    assert "معزولة" in sandbox_block["required_environment"]
    assert service.get_project(sessions, pid)["status"] == "BLOCKED"


def test_compatible_policy_runs_on_unsandboxed_env(wf_env, probe_seam):
    """السياسة المتوافقة (قرار مالك صريح) تقبل البيئة غير المعزولة —
    والنتيجة معلنة، لا ادعاء عزل."""
    sessions = wf_env["sessions"]
    _compat_env_only(sessions)
    engine = wf_env["build_engine"]()
    project = engine.create_project(
        "متوافق", "هدف بلا حساسية عزل", execution_policy="COMPATIBLE_LOCAL")
    assert project["execution_policy"] == "COMPATIBLE_LOCAL"
    engine.generate_plan(project["id"])
    engine.approve_plan(project["id"], approved=True)
    engine.run(project["id"])
    assert service.get_project(sessions, project["id"])["status"] == "COMPLETED"


def test_set_execution_policy_validates_and_records_event(wf_env, probe_seam):
    pid = _approved_project(wf_env)
    sessions = wf_env["sessions"]
    engine = wf_env["build_engine"]()
    with pytest.raises(EngineError, match="غير مدعومة"):
        engine.set_execution_policy(pid, "WHATEVER")
    updated = engine.set_execution_policy(pid, "COMPATIBLE_LOCAL")
    assert updated["execution_policy"] == "COMPATIBLE_LOCAL"
    kinds = [e["kind"] for e in service.list_events(sessions, pid, 50)]
    assert "EXECUTION_POLICY_CHANGED" in kinds


def test_preflight_matrix_names_policy_and_environment(wf_env, probe_seam):
    """(§17) المصفوفة تتصدرها السياسة والبيئة — القرار كاملًا."""
    from readiness import preflight

    pid = _approved_project(wf_env)
    sessions = wf_env["sessions"]
    project = service.get_project(sessions, pid)
    plan = service.latest_plan(sessions, pid)
    engine = wf_env["build_engine"]()
    result = engine._run_preflight(project, plan)
    ids = [row["capability_id"] for row in result["matrix"]]
    assert ids[:2] == ["execution_policy", "environment"]
    assert result["policy"] == "STRICT_ISOLATED"
    assert result["policy_note"]
