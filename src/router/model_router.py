"""موجّه النماذج النحيف — <600 سطر التزامًا (design-principles.md المبدأ 6).

سِجِل القرار: v1 حمل التبريد وسلسلة التبدّل وحد المعدل داخل الموجّه
(4,239 سطرًا). في v2 هذه **حزم مستقلة تُنقل لاحقًا من v1** (docs/
migration-plan.md) — الموجّه يبقى نحيفًا: تسجيل مزود + استدعاء.

هذا ملف تأسيسي: يعرف سجل المزودات وعقد الاستدعاء، وchat() مقفولة
صراحةً حتى الأمر الثاني — بلا كود ميزات.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Provider(str, Enum):
    """أسماء المزودات — بلا أي منطق تبريد/تبديل هنا (تُنقل لاحقًا)."""

    MOCK = "mock"                    # محلي دائمًا — للاختبار والتجريب
    OLLAMA = "ollama"                # محلي
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"  # أي نقطة متوافقة (OpenRouter…)


@dataclass(frozen=True)
class ProviderSpec:
    """مواصفة مزود — بيانات فقط، لا سلوك."""

    name: Provider
    key_required: bool
    base_url: str = ""


PROVIDERS: dict[Provider, ProviderSpec] = {
    Provider.MOCK: ProviderSpec(name=Provider.MOCK, key_required=False),
    Provider.OLLAMA: ProviderSpec(
        name=Provider.OLLAMA, key_required=False, base_url="http://127.0.0.1:11434"
    ),
    Provider.OPENAI: ProviderSpec(
        name=Provider.OPENAI,
        key_required=True,
        base_url="https://api.openai.com/v1",
    ),
    Provider.ANTHROPIC: ProviderSpec(
        name=Provider.ANTHROPIC,
        key_required=True,
        base_url="https://api.anthropic.com",
    ),
    Provider.OPENAI_COMPATIBLE: ProviderSpec(
        name=Provider.OPENAI_COMPATIBLE, key_required=True
    ),
}


@dataclass
class ChatMessage:
    """رسالة محادثة موحدة عبر كل المزودات."""

    role: str  # "system" | "user" | "assistant"
    content: str


class ModelRouter:
    """الموجّه النحيف — تسجيل واستدعاء فقط.

    ملاحظة تأسيسية: chat() تُنفَّذ في الأمر الثاني. التبريد/التبدّل/حد
    المعدل تصل كحزم مستقلة من v1 في أمر لاحق — لن تدخل هذا الملف أبدًا
    (سقف 600 سطر يشمل ذلك).
    """

    def __init__(self, default_provider: Provider = Provider.MOCK):
        if default_provider not in PROVIDERS:
            raise ValueError(f"مزود غير معروف: {default_provider}")
        self.default_provider = default_provider

    def chat(self, messages: list[ChatMessage], *, provider: Provider | None = None):
        """استدعاء مزود — عقد التنفيذ يُعرَّف في الأمر الثاني."""
        raise NotImplementedError(
            "ModelRouter.chat يُنفَّذ في الأمر الثاني — هذا أمر تأسيس فقط"
        )

    def spec(self, provider: Provider | None = None) -> ProviderSpec:
        """مواصفة مزود — تعمل الآن (بيانات فقط)."""
        name = provider or self.default_provider
        return PROVIDERS[name]
