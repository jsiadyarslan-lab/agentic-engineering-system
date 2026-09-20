"""اختبارات عقود الأدوار الخمسة — مطابقة CONTRACTS.md حرفيًا."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.roles import ROLES, RoleType, STATE_BADGES
from core.state import PlanState, SubVerdict
from roles.arbiter import Arbiter, ArbiterRequest, ArbiterResult
from roles.implementer import (
    Implementer,
    ImplementerRequest,
    ImplementerResult,
)
from roles.reviewer import Reviewer, ReviewerRequest, ReviewerResult
from roles.thinker import Plan, PlanTask, Thinker, ThinkerRequest, ThinkerResult
from roles.verifier import Verifier, VerifierRequest, VerifierResult


def _valid_plan() -> Plan:
    return Plan(
        tasks=[PlanTask(id="t1", description="اجمع البيانات", acceptance_criteria=["ملف csv موجود"])],
        risks=["انقطاع المصدر"],
        assumptions=["المصدر متاح اليوم"],
        evidence_required=["مسار الملف"],
    )


# ------------------------------------------------------------------ #
# THINKER
# ------------------------------------------------------------------ #

def test_thinker_contract_roundtrip():
    req = ThinkerRequest(goal="تقرير أسبوعي", context="سياق", constraints=["بلا إنترنت"], previous_reviews=[])
    assert req.goal == "تقرير أسبوعي"
    res = ThinkerResult(plan=_valid_plan())
    assert res.plan.tasks[0].id == "t1"
    assert res.plan.tasks[0].acceptance_criteria == ["ملف csv موجود"]


def test_thinker_rejects_empty_goal():
    with pytest.raises(ValidationError):
        ThinkerRequest(goal="")


# ------------------------------------------------------------------ #
# REVIEWER
# ------------------------------------------------------------------ #

def test_reviewer_contract_bounds():
    res = ReviewerResult(verdict="approved", score=8.5, evolution_score=9.0)
    assert res.verdict.value == "approved"
    with pytest.raises(ValidationError):
        ReviewerResult(verdict="approved", score=11.0, evolution_score=0)  # خارج 0-10
    with pytest.raises(ValidationError):
        ReviewerResult(verdict="maybe", score=5, evolution_score=5)  # حكم غير معروف


# ------------------------------------------------------------------ #
# IMPLEMENTER
# ------------------------------------------------------------------ #

def test_implementer_contract_roundtrip():
    req = ImplementerRequest(
        task=PlanTask(id="t1", description="نفّذ", acceptance_criteria=["المخرج موجود"]),
        tools_available=["python"],
        sandbox_root="/ws/abc",
        previous_attempts=[],
    )
    res = ImplementerResult(
        status="executed",
        artifacts=["/artifacts/out.csv"],
        stdout_truncated="...",
        stderr_truncated="",
        evidence_refs=["sha256:abc"],
    )
    assert res.status.value == "executed"
    assert req.sandbox_root == "/ws/abc"


def test_implementer_has_no_success_status():
    """نُفِّذت ≠ نجحت — لا حالة نجاح في عقد المنفذ."""
    from roles.implementer import ImplementerStatus
    assert {s.value for s in ImplementerStatus} == {"executed", "failed"}


# ------------------------------------------------------------------ #
# VERIFIER
# ------------------------------------------------------------------ #

def test_verifier_contract_and_sub_verdict():
    res = VerifierResult(
        verdict="not_evidenced",
        missing_evidence=["هاش الملف"],
        confidence=0.3,
    )
    assert res.sub_verdict is SubVerdict.NOT_EVIDENCED
    ok = VerifierResult(verdict="evidenced", confidence=0.95)
    assert ok.sub_verdict is None
    with pytest.raises(ValidationError):
        VerifierResult(verdict="evidenced", confidence=1.5)  # خارج 0-1


# ------------------------------------------------------------------ #
# ARBITER
# ------------------------------------------------------------------ #

def test_arbiter_contract_roundtrip():
    res = ArbiterResult(
        decision="reexecute_task",
        rationale="الأدلة ناقصة والهدف لم يتحقق",
        escalation_to_human=False,
        max_retries_remaining=2,
    )
    assert res.max_retries_remaining == 2
    assert res.sub_verdict is None
    with pytest.raises(ValidationError):
        ArbiterResult(decision="x", rationale="y", max_retries_remaining=-1)


def test_arbiter_stagnant_sub_verdict():
    res = ArbiterResult(
        decision="stagnant_escalate",
        rationale="تكررت بصمة الفشل ذاتها",
        escalation_to_human=True,
        max_retries_remaining=0,
    )
    assert res.sub_verdict is SubVerdict.STAGNANT


# ------------------------------------------------------------------ #
# الأدوار: الحالات الصادقة والهياكل التأسيسية
# ------------------------------------------------------------------ #

def test_every_role_honest_state_matches_contracts():
    assert ROLES[RoleType.THINKER].honest_state is PlanState.DRAFT
    assert ROLES[RoleType.REVIEWER].honest_state is PlanState.UNDER_REVIEW
    assert ROLES[RoleType.IMPLEMENTER].honest_state is PlanState.EXECUTED
    assert ROLES[RoleType.VERIFIER].honest_state is PlanState.EVIDENCED
    assert ROLES[RoleType.ARBITER].honest_state is PlanState.ADJUDICATED


def test_role_skeletons_honestly_not_implemented():
    """الهياكل ترفض التنفيذ بصدق — لا كود ميزات في التأسيس."""
    for role, req in (
        (Thinker(), ThinkerRequest(goal="g")),
        (Reviewer(), ReviewerRequest(plan=_valid_plan())),
        (
            Implementer(),
            ImplementerRequest(task=PlanTask(id="t", description="d")),
        ),
        (Verifier(), VerifierRequest()),
        (Arbiter(), ArbiterRequest(conflict_type="c")),
    ):
        with pytest.raises(NotImplementedError):
            role.run(req)


def test_state_badges_cover_all_eleven_states():
    """كل حالة لها شارة عرض — بلا استثناء."""
    for state in PlanState:
        assert state in STATE_BADGES, f"بلا شارة: {state}"
