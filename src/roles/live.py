"""الأدوار الحية (الأمر السادس §2) — كل دور يستدعي نموذجًا حقيقيًا.

لا mock في أي دور: كل دور يبني رسائله من برومبت prompts/<role>.md
ثم يستدعي ModelRouter.chat_live() (نقل urllib حقيقي)، يتحقق من
استجابته ضد عقد pydantic الصارم (CONTRACTS.md)، يعيد المحاولة مرة
واحدة عند فشل التحقق، ثم يفشل الدور صراحةً (RoleSystemFault) —
الفشل الصريح أفضل من رد وهمي.

الأدوار mock السابقة (roles/*.py) تبقى كما هي: اختبارات الأمر
الثاني تعتمدها، والدورة الافتراضية للخادم تبقى mock حتى يجهز
المستخدم مفتاحه — مهمة الأمر السادس وحدها تبني الأدوار الحية.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from roles.arbiter import ArbiterRequest, ArbiterResult
from roles.reviewer import ReviewerRequest, ReviewerResult
from roles.thinker import Plan, ThinkerRequest, ThinkerResult
from roles.verifier import VerifierRequest, VerifierResult
from router.model_router import ChatMessage, ModelRouter
from router.role_config import RoleSelection

#: جذر البرومبتات — نسبيًا لمستودع src/ (prompts/ في جذر المستودع).
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class RoleSystemFault(RuntimeError):
    """فشل دور حي بعد إعادة المحاولة الواحدة — يُسجَّل system_fault."""

    def __init__(self, role: str, reason: str):
        self.role = role
        self.reason = reason
        super().__init__(f"system_fault [{role}]: {reason}")


def load_prompt(name: str) -> str:
    """قراءة برومبت الدور — برومبت مفقود = فشل صريح لا صمت."""
    path = PROMPTS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise RoleSystemFault(name, f"البرومبت مفقود: {path} ({error})") from error


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict:
    """استخراج أول كائن JSON من رد النموذج — يتحمل أي لفّ نصي حوله."""
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError("لا كائن JSON في الرد")
    return json.loads(match.group(0))


class LiveRoleBase:
    """القاعدة المشتركة: برومبت ← chat_live ← تحقق ← إعادة واحدة ← فشل.

    selection (الأمر 006 §3+§4): اختيار الدور المستقل — المزود
    والنموذج المخصصان له حصرًا؛ غيابه = افتراضات الموجّه المعلنة.
    """

    #: اسم البرومبت (prompts/<name>.md) — يضبطه كل دور.
    PROMPT_NAME = ""
    #: اسم الدور في الأحداث والتشخيص.
    ROLE = ""

    def __init__(self, router: ModelRouter, selection: RoleSelection | None = None):
        self._router = router
        self._selection = selection
        self._system_prompt = load_prompt(self.PROMPT_NAME)

    def _live_call(self, messages: list[ChatMessage]) -> dict:
        """استدعاء حي واحد باختيار الدور — لا افتراض صامت لمزود آخر.

        transport_key (007.1 §10): اختيار الدور قد يحدد تكوينًا بعينه
        داخل المزود — «مزود::تكوين» — فيصل الاستدعاء إلى Base URL
        المختار حصرًا، لا إلى التكوين الأساسي.
        """
        if self._selection is None:
            return self._router.chat_live(messages)
        return self._router.chat_live(
            messages,
            provider_id=self._selection.transport_key(),
            model=self._selection.model,
        )

    # ------------------------------------------------------------------ #
    # الاستدعاء + التحقق + إعادة المحاولة الواحدة (§2.3)
    # ------------------------------------------------------------------ #

    def _validated_completion(self, payload: dict, result_model: type[BaseModel]) -> BaseModel:
        """استدعاء حي واحد مع تحقق العقد — إعادة واحدة ثم فشل الدور."""
        messages = [
            ChatMessage(role="system", content=self._system_prompt),
            ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]
        last_error: Exception | None = None
        for attempt in (1, 2):
            outcome = self._live_call(messages)
            text = outcome["text"]
            try:
                data = extract_json(text)
                return result_model.model_validate(data)
            except (ValueError, ValidationError) as error:
                last_error = error
                # إعادة المحاولة بتغذية راجعة: الخطأ نفسه يرى النموذج
                messages = messages + [
                    ChatMessage(role="assistant", content=text[:2000]),
                    ChatMessage(
                        role="user",
                        content=(
                            f"ردك غير صالح ضد العقد ({error}). أعد الإخراج "
                            "JSON صالحًا بالصيغة الحرفية المطلوبة فقط — لا نص إضافي."
                        ),
                    ),
                ]
        raise RoleSystemFault(
            self.ROLE,
            f"فشل تحقق JSON بعد إعادة واحدة — آخر خطأ: {last_error}",
        )


class ThinkerLive(LiveRoleBase):
    """المفكر الحي — الهدف ← خطة بعقد ThinkerResult نفسه.

    البرومبت يطلب حقول الخطة مباشرة (tasks/risks/…) — الدور يتحقق
    منها كعقد Plan ثم يغلّفها في ThinkerResult (تكييف العقد، لا
    تمييعه: نفس حقول pydantic الصارمة).
    """

    PROMPT_NAME = "thinker"
    ROLE = "thinker"

    def run(self, request: ThinkerRequest) -> ThinkerResult:
        payload = {
            "goal": request.goal,
            "context": request.context,
            "previous_reviews": request.previous_reviews,
        }
        plan = self._validated_completion(payload, Plan)
        return ThinkerResult(plan=plan)


class ReviewerLive(LiveRoleBase):
    """المدقق الحي — الخطة ← approved/revise بعقد ReviewerResult."""

    PROMPT_NAME = "reviewer"
    ROLE = "reviewer"

    def run(self, request: ReviewerRequest) -> ReviewerResult:
        payload = {
            "plan": request.plan.model_dump(),
            "previous_gaps": request.previous_gaps,
        }
        return self._validated_completion(payload, ReviewerResult)


class VerifierLive(LiveRoleBase):
    """المراجع الحي — يبني الحقائق الميكانيكية بنفسه ثم يحكم عليها.

    الحقائق (وجود الملفات، صفحات PDF، عدد المصادر، sha256) تُجمع
    ميكانيكيًا هنا وتُمرَّر للنموذج — حكمه يُبنى على أرقام مثبتة
    لا على نص يدّعي (الصدق قبل الراحة).

    (W2-T25 2026-10-28) مقتطف المحتوى: معايير المفكر كثيرًا ما تفحص
    **مضمون** الملف («package.json content showing name: news-site»)
    بينما الحقائق كانت وجودًا وبصمة فقط — فالملف الصحيح موجود على
    القرص والمراجع لا يراه: يعيد not_evidenced بصدق والمحكَّم ينهي
    الدورة «ركودًا» بخطوة نُفِّذت صحيحة. الحق الأصدق: مقتطف حقيقي
    محدود من محتوى الملفات النصية الصغيرة (content_head) — المضمون
    المثبت نفسه، لا حكم مُعد سلفًا.
    """

    PROMPT_NAME = "verifier"
    ROLE = "verifier"

    #: فحوص ميكانيكية إضافية تُدمج في facts إن توفرت الدالة الخارجية.
    facts_builder: Any = None

    #: امتدادات نصية يُقتطف محتواها — البقية (ثنائي/PDF/صور) بوجودها فقط.
    _TEXT_EXTS: frozenset[str] = frozenset({
        ".json", ".md", ".txt", ".log", ".csv", ".xml", ".yaml", ".yml",
        ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".html",
        ".astro", ".toml", ".py", ".mdx", ".sh", ".env", ".cfg",
    })
    #: سقف المقتطف وحد حجم الملف المقروء — أمان إحداثي معلن.
    _CONTENT_HEAD_LIMIT = 1800
    _CONTENT_FILE_LIMIT = 262_144

    def _content_head(self, path: Path) -> str | None:
        """مقتطف حقيقي محدود من ملف نصي صغير — أو None."""
        try:
            if path.suffix.lower() not in self._TEXT_EXTS:
                return None
            if path.stat().st_size > self._CONTENT_FILE_LIMIT:
                return None
            raw = path.read_bytes()[: self._CONTENT_HEAD_LIMIT]
            text = raw.decode("utf-8", "replace").strip()
            return text or None
        except OSError:
            return None

    def run(self, request: VerifierRequest) -> VerifierResult:
        facts: dict[str, Any] = {"files": {}}
        for reference in request.artifacts:
            path = Path(reference)
            facts["files"][path.name] = {
                "exists": path.is_file(),
                "sha256_head": (
                    __import__("hashlib")
                    .sha256(path.read_bytes())
                    .hexdigest()[:16]
                    if path.is_file() and path.stat().st_size < 20_000_000
                    else None
                ),
            }
            head = self._content_head(path)
            if head is not None:
                facts["files"][path.name]["content_head"] = head
        if self.facts_builder is not None:
            try:
                facts.update(self.facts_builder(request))
            except Exception:  # noqa: BLE001 — الحقائق الإضافية اختيارية
                pass
        payload = {
            "criteria": request.task_acceptance_criteria,
            "evidence_refs": request.evidence_refs[:40],
            "facts": facts,
        }
        return self._validated_completion(payload, VerifierResult)


class ArbiterLive(LiveRoleBase):
    """المُحكَّم الحي — حسم الخلافات بعقد ArbiterResult."""

    PROMPT_NAME = "arbiter"
    ROLE = "arbiter"

    def __init__(
        self,
        router: ModelRouter,
        max_retries: int = 2,
        selection: RoleSelection | None = None,
    ):
        super().__init__(router, selection=selection)
        self._max_retries = max_retries

    def run(self, request: ArbiterRequest) -> ArbiterResult:
        payload = {
            "conflict_type": request.conflict_type,
            "parties": request.parties,
            "evidences": request.evidences[:20],
            "history": request.history[:20],
            "max_retries_budget": self._max_retries,
            # سياق الفشل المنظم (إضافة 008 §14) — قرار حقيقي على السبب
            "failure_context": request.failure_context or None,
        }
        result = self._validated_completion(payload, ArbiterResult)
        # الميزانية المركزية ملك المحكَّم — لا يتجاوزها النموذج فوق السقف
        if result.max_retries_remaining > self._max_retries:
            result = result.model_copy(
                update={"max_retries_remaining": self._max_retries}
            )
        return result


#: إعادة تصدير العقود المطلوبة في التركيب — استيراد واحد للوحدة.
__all__ = [
    "ArbiterLive",
    "LiveRoleBase",
    "Plan",
    "ReviewerLive",
    "RoleSystemFault",
    "ThinkerLive",
    "VerifierLive",
    "load_prompt",
]
