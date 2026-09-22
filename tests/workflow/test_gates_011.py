"""اختبارات آلة حالة البوابات (الأمر 011 §1-§3+§18-§19).

الجرم المدان: واجهة قالت APPROVED ثم «البوابة ليست مفتوحة» — تناقض
state machine لا مشكلة UX. هنا: الفصل الصريح بين قرار البوابة
(gate.status) وفتح التنفيذ (مشتق)، والحل idempotent، ومسار
الاستئناف بلا إعادة اعتماد، وترحيل OPEN→PENDING.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)
from workflow import gates, service  # noqa: E402


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "gates-test.db")
    init_db(engine)
    return make_session_factory(engine)


# ------------------------------------------------------------------ #
# §1 — الحالة المشتقة: فصل القرار عن فتح التنفيذ
# ------------------------------------------------------------------ #

def test_execution_state_awakening_approval():
    state = gates.plan_execution_state(
        plan_approved=None, preflight_verdict=None)
    assert state["state"] == "AWAITING_APPROVAL"
    assert state["open_for_execution"] is False


def test_execution_state_open():
    state = gates.plan_execution_state(
        plan_approved=True, preflight_verdict="PASS")
    assert state["state"] == "OPEN"
    assert state["open_for_execution"] is True


def test_execution_state_approved_but_blocked_exact_wording():
    """(§3 حرفيًا) معتمدة + محجوبة = APPROVED_BUT_BLOCKED مع السبب
    والمطلوب والإجراء — لا «البوابة ليست مفتوحة»."""
    state = gates.plan_execution_state(
        plan_approved=True, preflight_verdict="BLOCKED",
        blocked_reason="لا توجد بيئة تنفيذ متوافقة وجاهزة.",
        required_environment="Linux/x86_64 Execution Worker",
        owner_action="إضافة بيئة تنفيذ ← التحقق ← إعادة الفحص ← استئناف",
    )
    assert state["state"] == "APPROVED_BUT_BLOCKED"
    assert state["open_for_execution"] is False
    assert state["label"] == "التنفيذ محجوب مؤقتًا"
    assert "Linux/x86_64" in state["required"]
    assert "إعادة الفحص" in state["owner_action"]
    # العبارة المضللة محظورة بنيويًا — لا توجد في أي تسمية
    for value in (state["label"], state["reason"], state["owner_action"]):
        assert "ليست مفتوحة" not in value


def test_execution_state_pending_preflight():
    state = gates.plan_execution_state(
        plan_approved=True, preflight_verdict=None)
    assert state["state"] == "PENDING_PREFLIGHT"
    assert state["open_for_execution"] is False


# ------------------------------------------------------------------ #
# §2 — انتقالات صريحة مقفلة
# ------------------------------------------------------------------ #

def test_transitions_table():
    assert gates.can_transition("PENDING", "APPROVED")
    assert gates.can_transition("PENDING", "REJECTED")
    assert not gates.can_transition("APPROVED", "REJECTED")   # القرار نهائي
    assert gates.can_transition("BLOCKED", "APPROVED")        # حل آلي بعد فحص
    assert not gates.can_transition("REJECTED", "APPROVED")
    assert not gates.can_transition("EXPIRED", "PENDING")


# ------------------------------------------------------------------ #
# §1 (الجذر) — الحل idempotent: قرار APPROVED مرتًا = نجاح لا انفجار
# ------------------------------------------------------------------ #

def test_resolve_same_decision_twice_is_idempotent(sessions):
    """السيناريو الحي بالضبط: البوابة APPROVED ثم ضغطة ثانية — كانت
    ترفع «البوابة ليست مفتوحة (حالتها: APPROVED)» فتبدو متناقضة."""
    project_id = service.create_project(sessions, name="p", objective="o")["id"]
    gate_id = service.open_gate(
        sessions, project_id, "PLAN_APPROVAL", "اعتمد الخطة v1",
        {"plan_id": 1},
    )
    first = service.resolve_gate(sessions, gate_id, approved=True)
    assert first["status"] == "APPROVED"
    # الضغطة الثانية: نفس القرار = نجاح صامت بلا أثر (idempotent)
    second = service.resolve_gate(sessions, gate_id, approved=True)
    assert second["status"] == "APPROVED"
    assert second.get("already_resolved") is True
    assert "لا أثر" in second["note"]


def test_resolve_opposite_decision_rejected(sessions):
    """عكس القرار بعد الحل = مرفوض صريحًا — القرار الجوهري لا يُنقض
    بنقرتين؛ البوابة الجديدة قرارها."""
    project_id = service.create_project(sessions, name="p", objective="o")["id"]
    gate_id = service.open_gate(
        sessions, project_id, "PLAN_APPROVAL", "اعتمد", {},
    )
    service.resolve_gate(sessions, gate_id, approved=True)
    with pytest.raises(ValueError, match="قائم"):
        service.resolve_gate(sessions, gate_id, approved=False)


def test_resolve_provisioning_gate_by_decision_is_refused(sessions):
    """بوابة التوفير BLOCKED لا تُحل بموافقة — إعادة الفحص طريقها."""
    project_id = service.create_project(sessions, name="p", objective="o")["id"]
    gate_id = service.open_gate(
        sessions, project_id, "PREFLIGHT_BLOCKED", "لا بيئة جاهزة",
        {}, status="BLOCKED",
    )
    with pytest.raises(ValueError, match="إعادة الفحص"):
        service.resolve_gate(sessions, gate_id, approved=True)


def test_auto_resolve_provisioning_gate(sessions):
    """(§19) GATE_AUTO_RESOLVED — بعد فحص ناجح، بلا قرار مالك جديد."""
    project_id = service.create_project(sessions, name="p", objective="o")["id"]
    gate_id = service.open_gate(
        sessions, project_id, "PREFLIGHT_BLOCKED", "لا بيئة",
        {}, status="BLOCKED",
    )
    outcome = service.auto_resolve_gate(
        sessions, gate_id, note="إعادة فحص ناجحة")
    assert outcome["status"] == "APPROVED"
    assert outcome["auto_resolved"] is True
    # idempotent أيضًا
    again = service.auto_resolve_gate(sessions, gate_id)
    assert again.get("already_resolved") is True


# ------------------------------------------------------------------ #
# §1 — ترحيل البيانات: OPEN التاريخية تصبح PENDING
# ------------------------------------------------------------------ #

def test_data_migration_open_to_pending(tmp_path):
    engine = build_engine(tmp_path / "mig.db")
    init_db(engine)
    with engine.begin() as connection:
        from sqlalchemy import text

        connection.execute(text(
            "INSERT INTO projects (name, objective, status, created_at, "
            "updated_at, stop_requested, completion_state, last_error, "
            "execution_policy) VALUES ('م', 'ه', 'BLOCKED', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, '', '', "
            "'STRICT_ISOLATED')"
        ))
        connection.execute(text(
            "INSERT INTO owner_gates (project_id, kind, reason, details, "
            "status, created_at) VALUES (1, 'PLAN_APPROVAL', 'سبب', '{}', "
            "'OPEN', CURRENT_TIMESTAMP)"
        ))
    # إقلاع جديد فوق القاعدة القديمة: الترحيل يعمل وآمن للتكرار
    init_db(engine)
    init_db(engine)
    factory = make_session_factory(engine)
    gates_rows = service.list_gates(factory, 1)
    assert gates_rows[0]["status"] == "PENDING"
    assert service.open_gates(factory, 1)[0]["status"] == "PENDING"


def test_open_gates_includes_provisioning_for_display(sessions):
    """open_gates تعيد PENDING (قرار) وBLOCKED (توفير) — الواجهة
    ترى الاثنين وتفرق بينهما."""
    project_id = service.create_project(sessions, name="p", objective="o")["id"]
    service.open_gate(sessions, project_id, "PLAN_APPROVAL", "قرار", {})
    service.open_gate(sessions, project_id, "PREFLIGHT_BLOCKED",
                      "توفير", {}, status="BLOCKED")
    open_now = service.open_gates(sessions, project_id)
    statuses = sorted(g["status"] for g in open_now)
    assert statuses == ["BLOCKED", "PENDING"]
