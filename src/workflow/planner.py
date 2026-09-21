"""المخطط الحي (الأمر 007 §10+§11) — توليد Master Plan بنموذج حقيقي.

الخطة تُولد باستدعاء LLM حي (نموذج المفكر من ربط الأدوار) بعقد
pydantic صارم: هدف + افتراضات + معايير قبول + مراحل بخطواتها + مخاطر
+ تبعيات + قرارات مطلوبة من المالك. لا mock ولا خطة ملفقة أبدًا —
فشل التوليد = إعلان صريح يعود للمشروع (last_error) ليقرر المالك.

البرومبت يمرر فشل الخطة السابقة عند المراجعة (§4: كل Revision تحتفظ
بسببها وأدلتها) — الخطة v2 ترى ما فشل في v1 فتتجنبه.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from router.model_router import ChatMessage


class StepDraft(BaseModel):
    """مسودة خطوة — الوحدة التي ستنفذها الحلقة الذاتية."""

    objective: str = Field(min_length=3, max_length=2000)
    input: str = ""
    expected_output: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class PhaseDraft(BaseModel):
    """مسودة مرحلة — وحدة مراجعة تكتمل بمراجعتها (§15)."""

    title: str = Field(min_length=2, max_length=300)
    objective: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    steps: list[StepDraft] = Field(min_length=1)


class PlanDraft(BaseModel):
    """عقد Master Plan الكامل (§4) — صارم: مرحلة واحدة بخطوة على الأقل."""

    objective: str = Field(min_length=3)
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=1)
    phases: list[PhaseDraft] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    required_owner_decisions: list[str] = Field(default_factory=list)


_PLANNER_PROMPT = """أنت مخطط هندسي رئيسي في نظام Agentic Engineering System.
مهمتك: تحويل هدف المالك إلى Master Plan قابل للتنفيذ الآلي بمراحل وخطوات.

قواعد صارمة:
1. أعد JSON صالحًا فقط — لا نص خارج كائن JSON واحد.
2. المراحل (phases) متسلسلة منطقيًا؛ كل مرحلة 1-3 خطوات.
3. كل خطوة objective واحد قابل للتنفيذ المستقل، مع acceptance_criteria
   قابلة للتحقق الميكانيكي (ملفات تُنشأ، محتوى يُكتب، أدلة تُنتج).
4. الخطوات هنا تنفذها دورة الأدوار الخمسة: تخطيط ← مراجعة ← تنفيذ
   (كتابة ملفات عبر أدوات البحث والكتابة داخل مساحة عمل معزولة) ←
   تحقق بالأدلة ← تحكيم. صمم الخطوات بما يناسب هذه القدرات.
5. لا تخترع قدرات غير موجودة (لا شبكة خارج الأدوات المعلنة، لا تنفيذ
   أوامر نظام خارج الركيزة المعزولة).
6. اجعل عدد المراحل والخطوات صغيرًا واقعيًا (1-3 مراحل).

الصيغة الحرفية:
{
  "objective": "الهدف كما سيفهمه المنفذ",
  "assumptions": ["افتراض"],
  "acceptance_criteria": ["معيار قبول قابل للتحقق"],
  "phases": [
    {
      "title": "عنوان المرحلة",
      "objective": "هدف المرحلة",
      "acceptance_criteria": ["معيار"],
      "steps": [
        {
          "objective": "هدف الخطوة القابل للتنفيذ",
          "input": "مدخلات الخطوة",
          "expected_output": "المخرج المتوقع",
          "acceptance_criteria": ["معيار قابل للتحقق ميكانيكيًا"],
          "dependencies": []
        }
      ]
    }
  ],
  "risks": ["خطر"],
  "dependencies": ["تبعية"],
  "required_owner_decisions": ["قرار يحتاجه المالك"]
}
"""


class PlannerError(RuntimeError):
    """فشل توليد الخطة — السبب موثق يعود للمشروع (لا خطة ملفقة)."""


class LivePlanner:
    """مخطط حي — استدعاء LLM واحد بعقد صارم وإعادة واحدة بتغذية راجعة."""

    def __init__(self, router: Any, selection: Any = None):
        self._router = router
        self._selection = selection

    def generate(self, objective: str, *, previous_failure: dict | None = None,
                 feedback: str = "") -> dict:
        """توليد خطة — إعادة واحدة عند فشل العقد ثم فشل صريح."""
        user_payload: dict[str, Any] = {"objective": objective}
        if previous_failure:
            user_payload["previous_plan_failure"] = previous_failure
        if feedback:
            user_payload["owner_feedback"] = feedback
        messages = [
            ChatMessage(role="system", content=_PLANNER_PROMPT),
            ChatMessage(role="user",
                        content=json.dumps(user_payload, ensure_ascii=False)),
        ]
        last_error: Exception | None = None
        for _attempt in (1, 2):
            outcome = self._call(messages)
            text = outcome["text"]
            try:
                data = _extract_json(text)
                draft = PlanDraft.model_validate(data)
                return self._to_plan_json(draft, outcome)
            except (ValueError, ValidationError) as error:
                last_error = error
                messages = messages + [
                    ChatMessage(role="assistant", content=text[:2000]),
                    ChatMessage(role="user", content=(
                        f"ردك غير صالح ضد العقد ({error}). أعد JSON صالحًا "
                        "بالصيغة الحرفية المطلوبة فقط — لا نص إضافي."
                    )),
                ]
        raise PlannerError(
            f"فشل توليد الخطة بعد إعادة واحدة — آخر خطأ: {last_error}"
        )

    def _call(self, messages: list[ChatMessage]) -> dict:
        if self._selection is None:
            return self._router.chat_live(messages)
        return self._router.chat_live(
            messages,
            provider_id=self._selection.transport_key(),
            model=self._selection.model,
        )

    @staticmethod
    def _to_plan_json(draft: PlanDraft, outcome: dict) -> dict:
        return {
            "objective": draft.objective,
            "assumptions": draft.assumptions,
            "acceptance_criteria": draft.acceptance_criteria,
            "phases": [
                {
                    "title": phase.title,
                    "objective": phase.objective,
                    "acceptance_criteria": phase.acceptance_criteria,
                    "steps": [step.model_dump() for step in phase.steps],
                }
                for phase in draft.phases
            ],
            "risks": draft.risks,
            "dependencies": draft.dependencies,
            "required_owner_decisions": draft.required_owner_decisions,
            "generated_by": {
                "provider": outcome.get("provider", ""),
                "model": outcome.get("model", ""),
            },
        }


def _extract_json(text: str) -> dict:
    """أول كائن JSON في الرد — يتحمل أي لف نصي حوله."""
    import re

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("لا كائن JSON في الرد")
    return json.loads(match.group(0))


#: مصنع المخطط الافتراضي — يبنى بالموجّه الحي واختيار المفكر.
def default_planner_factory(router_factory: Callable, role_selections: dict):
    """مصنع حي: يبني موجّهًا ثم مخططًا بنموذج المفكر (لا mock أبدًا)."""

    def factory() -> "LivePlanner":
        router = router_factory()
        return LivePlanner(router, selection=role_selections.get("thinker"))

    return factory
