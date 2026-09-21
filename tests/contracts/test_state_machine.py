"""اختبارات آلة الحالات — 11 حالة + الحكمان الفرعيان + القاعدة الذهبية."""

from __future__ import annotations

import pytest

from core.state import (
    PlanState,
    TERMINAL_STATES,
    TRANSITIONS,
    SubVerdict,
    StateTransitionError,
    validate_transition,
)


def test_exactly_thirteen_honest_states():
    """13 حالة بالضبط — 11 الأصلية + زوج الإيقاف STOPPING/STOPPED (الأمر 004)."""
    assert len(PlanState) == 13


def test_no_success_state_exists():
    """لا SUCCESS إطلاقًا — النموذج الصادق."""
    assert "SUCCESS" not in {s.value for s in PlanState}


def test_two_sub_verdicts_only():
    """حكمان فرعيان — ليسا حالتَي خطة."""
    assert {s.value for s in SubVerdict} == {"NOT_EVIDENCED", "STAGNANT"}


def test_happy_path_walks_to_verified_by_user_only():
    """المسار الكامل يعمل — وVERIFIED لا تُبنى إلا بقرار المستخدم."""
    path = [
        (PlanState.DRAFT, PlanState.UNDER_REVIEW, "system"),
        (PlanState.UNDER_REVIEW, PlanState.APPROVED, "reviewer"),
        (PlanState.APPROVED, PlanState.EXECUTING, "system"),
        (PlanState.EXECUTING, PlanState.EXECUTED, "implementer"),
        (PlanState.EXECUTED, PlanState.VERIFYING, "system"),
        (PlanState.VERIFYING, PlanState.EVIDENCED, "verifier"),
        (PlanState.EVIDENCED, PlanState.ADJUDICATED, "arbiter"),
        (PlanState.ADJUDICATED, PlanState.VERIFIED, "user"),
    ]
    for frm, to, actor in path:
        validate_transition(frm, to, actor=actor)  # لا يرفض أبدًا


def test_golden_rule_no_role_grants_verified():
    """القاعدة الذهبية: أي فاعل غير المستخدم يُمنع من VERIFIED."""
    for actor in ("system", "thinker", "reviewer", "implementer", "verifier", "arbiter"):
        with pytest.raises(StateTransitionError) as err:
            validate_transition(
                PlanState.EVIDENCED, PlanState.VERIFIED, actor=actor
            )
        assert "القاعدة الذهبية" in str(err.value)


def test_reexecution_after_adjudication_is_arbiter_only():
    """إعادة التنفيذ بعد الحسم قرار المُحكَّم وحده."""
    with pytest.raises(StateTransitionError):
        validate_transition(
            PlanState.ADJUDICATED, PlanState.EXECUTING, actor="implementer"
        )
    validate_transition(
        PlanState.ADJUDICATED, PlanState.EXECUTING, actor="arbiter"
    )  # مسموح له وحده


def test_terminal_states_have_no_exits():
    """الحالات النهائية مغلقة — لا خروج منها."""
    for state in TERMINAL_STATES:
        assert TRANSITIONS[state] == frozenset(), f"{state} لديها مخارج!"


def test_illegal_jump_rejected():
    """قفزات خارج الجدول مرفوضة fail-closed."""
    with pytest.raises(StateTransitionError):
        validate_transition(PlanState.DRAFT, PlanState.VERIFIED, actor="user")
    with pytest.raises(StateTransitionError):
        validate_transition(PlanState.EXECUTING, PlanState.EVIDENCED, actor="verifier")
    with pytest.raises(StateTransitionError):
        validate_transition(PlanState.VERIFIED, PlanState.DRAFT, actor="user")


def test_reviewer_revise_returns_to_draft():
    """المدقق يُعيد للمفكر عند التنقيح — الحلقة الصغرى."""
    validate_transition(
        PlanState.UNDER_REVIEW, PlanState.DRAFT, actor="reviewer"
    )


# ------------------------------------------------------------------ #
# الأمر 004 — زوج الإيقاف الآمن (STOPPING → STOPPED)
# ------------------------------------------------------------------ #


def test_stop_reachable_from_every_non_terminal_state():
    """كل حالة نشطة قابلة للإيقاف — لا حالة تعجز المالك عن إيقافها."""
    for state in PlanState:
        if state in TERMINAL_STATES or state is PlanState.STOPPING:
            continue
        validate_transition(state, PlanState.STOPPING, actor="user")


def test_stopping_goes_only_to_stopped():
    """STOPPING هدفها الوحيد STOPPED — لا التفاف إلى مسارات العمل."""
    assert TRANSITIONS[PlanState.STOPPING] == frozenset({PlanState.STOPPED})


def test_stopped_is_terminal_and_frozen():
    """STOPPED نهائية مجمّدة — الاستئناف دورة جديدة لا إحياء."""
    assert PlanState.STOPPED in TERMINAL_STATES
    assert TRANSITIONS[PlanState.STOPPED] == frozenset()
    with pytest.raises(StateTransitionError):
        validate_transition(PlanState.STOPPED, PlanState.EXECUTING, actor="user")


def test_no_role_can_stop_a_cycle():
    """الإيقاف فعل المالك/المنسق حصرًا — الأدوار لا توقف دورة."""
    for actor in ("thinker", "reviewer", "implementer", "verifier", "arbiter"):
        with pytest.raises(StateTransitionError) as err:
            validate_transition(
                PlanState.EXECUTING, PlanState.STOPPING, actor=actor
            )
        assert "حصرًا" in str(err.value)
    validate_transition(
        PlanState.EXECUTING, PlanState.STOPPING, actor="user"
    )  # المالك يملكها


def test_stopped_not_verified_path():
    """الموقوفة لا تُمنح VERIFIED — لا نجاح بعد إيقاف بأمر."""
    with pytest.raises(StateTransitionError):
        validate_transition(PlanState.STOPPED, PlanState.VERIFIED, actor="user")
