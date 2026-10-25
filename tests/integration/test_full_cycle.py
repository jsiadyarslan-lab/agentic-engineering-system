"""اختبارات الأمر الثاني — أول دورة كاملة بين الأدوار الخمسة.

خمسة اختبارات بالضبط كما نصّ الأمر:
1. الدورة الكاملة: goal → DRAFT → … → EVIDENCED → VERIFIED (موافقة مستخدم وهمية)
2. حلقة المراجعة: revise ثم تعديل المفكر ثم approved
3. حلقة الإصلاح: not_evidenced ثم إعادة تنفيذ ثم evidenced
4. المحكَّم: خصام مراجعة بعد سقف الجولات → terminate_stagnant → STAGNANT
5. القاعدة الذهبية: VERIFIED لا تُبنى إلا بفاعل «user»

كل الأدوار mock؛ التنفيذ داخل الركيزة **حقيقي** (namespaces + seccomp).
الركيزة تعمل على Linux/x86_64 (WSL2 على Windows) — خارجها تُتخطى الاختبارات
بصدق مع بيان السبب، لا فشلًا صامتًا ولا نجاحًا مزيفًا.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.orchestrator import MAX_REVIEW_CYCLES
from core.roles import RoleType
from core.state import PlanState, StateTransitionError, SubVerdict, validate_transition
from core.wiring import build_mock_orchestrator
from roles.reviewer import Reviewer
from substrate.factory import substrate_available, substrate_failure_reason

pytestmark = pytest.mark.skipif(
    not substrate_available(),
    reason=(
        "لا ركيزة عزل متاحة على هذا المضيف — " + substrate_failure_reason()
    ),
)


@pytest.fixture
def orchestrator(tmp_path):
    """دورة افتراضية بمساحة عمل مؤقتة معزولة عن المستودع."""
    return build_mock_orchestrator()


def _events_of(result, kind: str) -> list[dict]:
    return [e for e in result.events if e["kind"] == kind]


def _verdicts_of(result, kind: str) -> list[str]:
    return [e["details"].get("verdict") for e in _events_of(result, kind)]


# ------------------------------------------------------------------ #
# 1) الدورة الكاملة end-to-end — حتى VERIFIED بعد موافقة مستخدم وهمية
# ------------------------------------------------------------------ #


def test_full_cycle_reaches_verified_after_user_approval(tmp_path, orchestrator):
    result = orchestrator.run_cycle(
        "بناء تقرير نصي داخل الركيزة",
        workspace_root=tmp_path / "cycles",
    )

    # تسلسل الحالات المطلوب حرفيًا (يشمل حلقتي المراجعة والإصلاح)
    assert result.state_history == [
        "DRAFT",
        "UNDER_REVIEW",
        "DRAFT",           # عودة للتنقيح (حلقة المراجعة)
        "UNDER_REVIEW",
        "APPROVED",
        "EXECUTING",
        "EXECUTED",
        "VERIFYING",
        "EVIDENCED",
    ]
    assert result.final_state is PlanState.EVIDENCED

    # كل المهام نُفِّذت داخل الركيزة وأُثبتت أدلتها
    assert len(result.tasks) == 3
    assert all(t.evidenced for t in result.tasks)
    assert all(t.attempts == 2 for t in result.tasks)  # حلقة الإصلاح لكل مهمة
    assert all(Path(p).is_file() for t in result.tasks for p in t.artifacts)

    # VERIFIED لا تأتي من الدورة — قرار المستخدم وحده (موافقة وهمية)
    outcome = orchestrator.user_verifies(result.cycle_id)
    assert outcome["state"] == "VERIFIED"
    assert result.context.state is PlanState.VERIFIED
    assert result.context.history[-1].endswith("(by user)")


# ------------------------------------------------------------------ #
# 2) حلقة المراجعة: revise → يعدّل المفكر → approved
# ------------------------------------------------------------------ #


def test_review_loop_thinker_revises_then_reviewer_approves(
    tmp_path, orchestrator
):
    result = orchestrator.run_cycle(
        "هدف يحتاج جولة مراجعة", workspace_root=tmp_path / "cycles"
    )

    verdicts = _verdicts_of(result, "review_verdict")
    assert verdicts == ["revise", "approved"]
    assert result.review_cycles == 2

    # المفكر أنتج خطة أولى ثم عدّلها وفق الملاحظات (لا خطة واحدة معاد عرضها)
    plan_kinds = [e["kind"] for e in result.events if e["role"] == "thinker"]
    assert plan_kinds == ["plan", "plan_revised"]
    revised_event = _events_of(result, "plan_revised")[0]
    assert revised_event["details"]["review_round"] == 2

    # المراجع الأول رفض بملاحظات موثقة لا حكم أعمى
    first_review = _events_of(result, "review_verdict")[0]
    assert first_review["details"]["issues"]

    # ولا تنفيذ قبل الموافقة
    first_execution_seq = _events_of(result, "task_execution")[0]["seq"]
    approval_seq = [
        e for e in result.events if e["kind"] == "state_change"
        and e["details"]["to"] == "APPROVED"
    ][0]["seq"]
    assert approval_seq < first_execution_seq


# ------------------------------------------------------------------ #
# 3) حلقة الإصلاح: not_evidenced → إعادة تنفيذ → evidenced
# ------------------------------------------------------------------ #


def test_repair_loop_implementer_retries_then_evidenced(tmp_path, orchestrator):
    result = orchestrator.run_cycle(
        "هدف يمر بحلقة إصلاح", workspace_root=tmp_path / "cycles"
    )
    assert result.final_state is PlanState.EVIDENCED

    for task in result.tasks:
        task_id = task.task_id
        executions = [
            e for e in _events_of(result, "task_execution")
            if e["details"]["task_id"] == task_id
        ]
        verifications = [
            e for e in _events_of(result, "task_verification")
            if e["details"]["task_id"] == task_id
        ]
        # محاولتان لكل مهمة: الأولى ناقصة الدليل والثانية مكتملة
        assert len(executions) == 2
        assert [v["details"]["verdict"] for v in verifications] == [
            "not_evidenced",
            "evidenced",
        ]
        # النقص في المحاولة الأولى موثق بالاسم (الملف الناقص فعلًا)
        missing = verifications[0]["details"]["missing_evidence"]
        assert any(f"{task_id}-run-log.txt" in m for m in missing)
        # وإعادة التنفيذ جاءت بعد حكم المراجع لا قبله
        assert verifications[0]["seq"] < executions[1]["seq"]

    # والتحقق الكلي أثبت كل معايير كل المهام
    rollup = _events_of(result, "verification_rollup")
    assert len(rollup) == 1
    assert rollup[0]["details"]["verdict"] == "evidenced"
    assert rollup[0]["details"]["confidence"] == 1.0


# ------------------------------------------------------------------ #
# 4) المحكَّم: خصام مراجعة (لا اتفاق أبدًا) → terminate → STAGNANT
# ------------------------------------------------------------------ #


def test_arbiter_terminates_review_deadlock_as_stagnant(tmp_path):
    # مدقق لا يوافق أبدًا — لإثبات مسار الحسم عند استنفاد الجولات
    orchestrator = build_mock_orchestrator(
        overrides={RoleType.REVIEWER: Reviewer(approve_after=None)}
    )
    result = orchestrator.run_cycle(
        "هدف لا يتفق عليه أحد", workspace_root=tmp_path / "cycles"
    )

    # سقف الجولات 3 ثم المحكَّم — الرابعة لا تحدث أصلًا
    assert MAX_REVIEW_CYCLES == 3
    assert result.review_cycles == 3
    verdicts = _verdicts_of(result, "review_verdict")
    assert verdicts == ["revise", "revise", "revise"]

    # المحكَّم استُدعي وأصدر إنهاءً ركوديًا
    arbiter_events = _events_of(result, "arbiter_decision")
    assert len(arbiter_events) == 1
    assert "terminate" in arbiter_events[0]["details"]["decision"]
    assert arbiter_events[0]["details"]["escalation_to_human"] is True

    # «الحالة تصبح STAGNANT»: الحكم الفرعي STAGNANT موثق على النتيجة
    # (STAGNANT حكم فرعي لا حالة خطة — CONTRACTS.md) والحالة النهائية
    # للخطة ESCALATED_TO_HUMAN (جدول الانتقالات لا يسمح
    # UNDER_REVIEW → ADJUDICATED — موثق في ARCHITECTURE.md §11)
    assert result.sub_verdict is SubVerdict.STAGNANT
    assert result.final_state is PlanState.ESCALATED_TO_HUMAN

    # لا تنفيذ إطلاقًا بعد الخصام — ولا دوران حتى المحاولة الرابعة
    assert _events_of(result, "task_execution") == []
    assert not any(
        e for e in result.events if e["kind"] == "state_change"
        and e["details"]["to"] == "EXECUTING"
    )


# ------------------------------------------------------------------ #
# 5) القاعدة الذهبية: VERIFIED بفاعل «user» وحده — اختبار صريح
# ------------------------------------------------------------------ #


def test_golden_rule_verified_only_by_user(tmp_path, orchestrator):
    result = orchestrator.run_cycle(
        "هدف القاعدة الذهبية", workspace_root=tmp_path / "cycles"
    )
    assert result.final_state is PlanState.EVIDENCED

    # كل الفاعلين غير المستخدم مرفوضون حتى من EVIDENCED (الجدول يسمح
    # المسار لكن القاعدة الذهبية ترفض الفاعل)
    for actor in ("thinker", "reviewer", "implementer", "verifier", "arbiter", "system"):
        with pytest.raises(StateTransitionError):
            validate_transition(
                PlanState.EVIDENCED, PlanState.VERIFIED, actor=actor
            )

    # حتى المنسق نفسه لا يستطيع — عبر سياق الدورة الحقيقي
    with pytest.raises(StateTransitionError):
        result.context.move_to(PlanState.VERIFIED, actor="system")

    # ومن حالة غير نهائية يُرفض حتى للمستخدم (DRAFT → VERIFIED ليست مسارًا)
    with pytest.raises(StateTransitionError):
        validate_transition(PlanState.DRAFT, PlanState.VERIFIED, actor="user")

    # القناة الوحيدة: user_verifies — بفاعل user حصرًا
    outcome = orchestrator.user_verifies(result.cycle_id)
    assert outcome["state"] == "VERIFIED"
    assert result.context.state is PlanState.VERIFIED
    assert result.context.history[-1].endswith("(by user)")

    # وبعد VERIFIED (حالة نهائية) لا خروج — ولا موافقة مزدوجة
    with pytest.raises(StateTransitionError):
        orchestrator.user_verifies(result.cycle_id)
