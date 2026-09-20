"""المراجع (Verifier) — يطابق النتائج بمعايير القبول (CONTRACTS.md §4).

تنفيذ الأمر الثاني (mock بفحص **حقيقي** لا بعدّاد):
- يستخرج أسماء الملفات المذكورة في معايير القبول (اتفاقية المفكر)،
  ثم يفحص كل اسم فعليًا: هل هو ضمن الأدلة المسلَّمة **وواقع على القرص**؟
- الحكم ينشأ من حالة الملفات الحقيقية: المحاولة الأولى للمنفذ تُنتج
  المخرج الرئيسي فقط، فيعود not_evidenced بنقص موثَّق؛ إعادة التنفيذ
  تُكمل الملف الناقص فيعود evidenced. لا «فشل مزيف» يصنعه عدّاد.
- معيار بلا اسم ملف يُوثَّق كفحص «لا يمكن التحقق منه ميكانيكيًا» —
  لا يُزوَّر نجاحًا ولا يُخفى.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from core.state import PlanState, SubVerdict


class VerifierVerdict(str, Enum):
    EVIDENCED = "evidenced"
    NOT_EVIDENCED = "not_evidenced"


class VerifierRequest(BaseModel):
    """عقد طلب المراجع."""

    task_acceptance_criteria: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class VerifierResult(BaseModel):
    """عقد نتيجة المراجع — الحالة الصادقة: EVIDENCED.

    not_evidenced ليس فشلًا — نقص أدلة يوثَّق ويُغذّي المُحكَّم
    (SubVerdict.NOT_EVIDENCED).
    """

    verdict: VerifierVerdict
    checks_performed: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def sub_verdict(self) -> SubVerdict | None:
        """الحكم الفرعي — NOT_EVIDENCED عند قصور الأدلة."""
        if self.verdict is VerifierVerdict.NOT_EVIDENCED:
            return SubVerdict.NOT_EVIDENCED
        return None


#: أسماء الملفات القابلة للاستخراج من نص المعيار (اتفاقية المفكر).
_FILENAME = re.compile(r"[\w.-]+\.(?:txt|json|log|md|csv|xml|yaml|yml)")


class Verifier:
    """دور المراجع — فحص ملفات حقيقي عديم الحالة (الأمر الثاني)."""

    HONEST_STATE = PlanState.EVIDENCED

    def run(self, request: VerifierRequest) -> VerifierResult:
        # الأدلة مراجع (مسارات) — نتحقق من الاسم ومن الوجود الفعلي معًا
        present: dict[str, bool] = {}
        for reference in request.artifacts:
            name = Path(reference).name
            present[name] = Path(reference).is_file()

        checks: list[str] = []
        missing: list[str] = []
        expected: list[str] = []

        for criterion in request.task_acceptance_criteria:
            names = _FILENAME.findall(criterion)
            if not names:
                checks.append(
                    f"معيار بلا ملف قابل للفحص (لا يتحقق ميكانيكيًا): "
                    f"{criterion[:90]}"
                )
                continue
            for name in dict.fromkeys(names):
                expected.append(name)
                found = present.get(name, False)
                checks.append(
                    f"{'وُجد' if found else 'مفقود'} {name} ضمن الأدلة"
                )
                if not found:
                    missing.append(
                        f"الملف {name} غائب عن الأدلة (المعيار: "
                        f"{criterion[:90]})"
                    )

        if not expected:
            # لا معايير ميكانيكية إطلاقًا — الحد الأدنى الصادق: وجود أي دليل
            any_artifact = any(present.values())
            checks.append(
                "يوجد أثر أدلة واحد على الأقل"
                if any_artifact
                else "لا أدلة إطلاقًا"
            )
            if not any_artifact:
                missing.append("لم تُنتَج أي أدلة")
            return VerifierResult(
                verdict=(
                    VerifierVerdict.EVIDENCED
                    if any_artifact
                    else VerifierVerdict.NOT_EVIDENCED
                ),
                checks_performed=checks,
                missing_evidence=missing,
                confidence=1.0 if any_artifact else 0.0,
            )

        passed = len(expected) - len(missing)
        confidence = round(passed / len(expected), 2)
        return VerifierResult(
            verdict=(
                VerifierVerdict.EVIDENCED
                if not missing
                else VerifierVerdict.NOT_EVIDENCED
            ),
            checks_performed=checks,
            missing_evidence=missing,
            confidence=confidence,
        )
