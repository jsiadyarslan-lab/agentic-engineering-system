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


def test_exactly_eleven_honest_states():
    """11 حالة بالضبط — لا 13 كما تراكمت في v1."""
    assert len(PlanState) == 11


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
