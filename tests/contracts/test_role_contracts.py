"""اختبارات عقود الأدوار الخمسة — مطابقة CONTRACTS.md حرفيًا."""

from __future__ import annotations

import tempfile
from pathlib import Path

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
from roles.reviewer import (
    Reviewer,
    ReviewerRequest,
    ReviewerResult,
    ReviewerVerdict,
)
from roles.thinker import Plan, PlanTask, Thinker, ThinkerRequest, ThinkerResult
from roles.verifier import Verifier, VerifierRequest, VerifierResult, VerifierVerdict


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


def test_role_mocks_execute_and_return_contracts():
    """الأمر الثاني فتح الأدوار — كل mock يعيد عقده (بلا NotImplementedError).

    المفكر/المدقق/المحكَّم بلا ركيزة؛ المراجع بفحص ملفات حقيقي (tmp)؛
    المنفذ يُغطى في اختبارات التكامل لأنه يحتاج الركيزة الفعلية.
    """
    # المفكر: خطة بثلاث مهام ومخاطر وافتراضات
    thinker = Thinker()
    result = thinker.run(ThinkerRequest(goal="بناء تقرير"))
    assert len(result.plan.tasks) == 3
    assert result.plan.risks and result.plan.assumptions

    # المدقق: الجولة الأولى revise، وبعد معالجة الملاحظات approved
    reviewer = Reviewer()
    first = reviewer.run(ReviewerRequest(plan=result.plan))
    assert first.verdict is ReviewerVerdict.REVISE
    assert first.issues  # الملاحظات موثقة لا حكم أعمى
    revised = thinker.run(
        ThinkerRequest(goal="بناء تقرير", previous_reviews=first.issues)
    )
    second = reviewer.run(ReviewerRequest(plan=revised.plan))
    assert second.verdict is ReviewerVerdict.APPROVED

    # المراجع: فحص ملفات حقيقي — الناقص not_evidenced ثم evidenced بعد الإكمال
    verifier = Verifier()
    criteria = ["الملف T1-output.txt موجود ضمن الأدلة",
                "الملف T1-run-log.txt موجود ضمن الأدلة"]
    incomplete = verifier.run(VerifierRequest(task_acceptance_criteria=criteria))
    assert incomplete.verdict is VerifierVerdict.NOT_EVIDENCED
    assert incomplete.missing_evidence  # النقص موثق بالاسم
    tmp = Path(tempfile.mkdtemp(prefix="v2-contracts-"))
    for name in ("T1-output.txt", "T1-run-log.txt"):
        (tmp / name).write_text("أثر", encoding="utf-8")
    complete = verifier.run(
        VerifierRequest(
            task_acceptance_criteria=criteria,
            artifacts=[str(tmp / "T1-output.txt"), str(tmp / "T1-run-log.txt")],
        )
    )
    assert complete.verdict is VerifierVerdict.EVIDENCED
    assert complete.confidence == 1.0

    # المحكَّم: خصام مراجعة → إنهاء ركودي بتصعيد؛ وبصمة متكررة → كذلك
    arbiter = Arbiter()
    verdict = arbiter.run(
        ArbiterRequest(conflict_type="review_deadlock",
                       parties=["thinker", "reviewer"])
    )
    assert verdict.sub_verdict is SubVerdict.STAGNANT
    assert verdict.escalation_to_human is True
    repeat = arbiter.run(
        ArbiterRequest(conflict_type="execution_exhausted", history=[
            "execution_exhausted:retry_with_constraints",
        ])
    )
    assert repeat.decision == "terminate_stagnant"


def test_state_badges_cover_all_eleven_states():
    """كل حالة لها شارة عرض — بلا استثناء."""
    for state in PlanState:
        assert state in STATE_BADGES, f"بلا شارة: {state}"
