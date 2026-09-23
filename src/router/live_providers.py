"""حل المزودات الحية (الأمر السادس المنقح §2) — منفصل ليبقى الموجّه نحيفًا.

BUILTIN_LIVE_PROVIDERS + _resolve_provider_credentials +
resolve_live_providers + ProviderCallError: منطق «أي مفتاح لأي مزود»
هنا، والتوجيه (حد معدل/تبريد/تبدل) في model_router. المفاتيح من مخزن
الأسرار حصرًا (§0.3) — لا متغيرات بيئة أبدًا.
"""

from __future__ import annotations

import json
from typing import Any

from core.config import live_model_settings

#: (013.5 §B) عقد المخرجات الافتراضي — يغطي الاستدلال **و**الإجابة.
#: قياس حي على النموذج المُهيَّأ (deepseek-ai/deepseek-v4.1-flash):
#: ‏7117 حرف استدلال + 10268 حرف مخرج لخطة من 7 مراحل و34 خطوة.
#: ‏4000 (الافتراضي القديم) كان يُستنفد داخل الاستدلال فيعود الرد
#: بـ content فارغ — وهو ما صُنّف سابقًا «رد فارغ» خطأً.
DEFAULT_MAX_TOKENS = 16000

#: (013.5 §B) مهلة النقل الافتراضية — استدلال طويل شرعي لا عطل.
DEFAULT_REQUEST_TIMEOUT = 600.0


class ProviderCallError(Exception):
    """خطأ نقل مزود — تصنيفه بسمات صريحة تقرؤها الحزم بطرفية.

    is_throttle:      429/503-overloaded — يدخل حلقة التبريد.
    is_server_error:  5xx غير الاختناقي — إعادات ثم تبدّل.
    is_timeout:       انتهت مهلة الاتصال/الفتحة — كخطأ خادم.
    retry_after:      ثواني رأس Retry-After إن أرسلها المزود.
    error_class:      (013.5 §B) تصنيف صريح يسبق الخريطة العامة —
                      مثل REASONING_ONLY_RESPONSE: المزود رد فعلًا
                      لكن مخرجاته كلها داخل مرحلة الاستدلال.
    """

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        is_throttle: bool = False,
        is_server_error: bool = False,
        is_timeout: bool = False,
        retry_after: int | None = None,
        error_class: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.is_throttle = is_throttle
        self.is_server_error = is_server_error
        self.is_timeout = is_timeout
        self.retry_after = retry_after
        self.error_class = error_class




#: قالب المزودات الحية المدمج (الأمر السادس المنقح §2.2) — السلسلة
#: الافتراضية [nvidia] فقط؛ المفاتيح من مخزن الأسرار حصرًا (§0.3 —
#: لا متغيرات بيئة أبدًا). zai_internal منشأة الحاوية المعلنة:
#: مصادقتها من ملف الإعدادات لا من مخزن المالك.
#: قالب المزودات الحية المدمج (الأمر السادس المنقح §2.2) — السلسلة
#: الافتراضية [nvidia] فقط؛ المفاتيح من مخزن الأسرار حصرًا (§0.3 —
#: لا متغيرات بيئة أبدًا). zai_internal منشأة الحاوية المعلنة.
BUILTIN_LIVE_PROVIDERS: dict[str, dict] = {
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "nemotron-3-ultra-550b-a55b",
        "secrets_store": True,
    },
    "openai_compatible": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "anthropic/claude-haiku-3.5",
        "secrets_store": True,
    },
    "zai_internal": {
        "base_url": "https://internal-api.z.ai/v1",
        "model": "glm-4.6",
        "config_file": "/etc/.z-ai-config",
    },
}


def _resolve_provider_credentials(spec: dict, name: str = "") -> dict | None:
    """استكمال مفتاح مزود واحد من مصادره — يعيد None إن لم يحل.

    أولوية الحل (الأمر السادس المنقح §0.3+§2.1):
    1. مفتاح صريح في المواصفة نفسها (مزودات JSON الاختبارية/المخصصة).
    2. مخزن الأسرار المحلي (DPAPI على Windows) — قناة المالك الوحيدة.
    3. ملف إعدادات معلن (منشأة الحاوية zai_internal).
    متغيرات البيئة ليست مصدرًا أبدًا — §0.3 حرفيًا.
    """
    cfg = dict(spec)
    if cfg.get("api_key"):
        cfg.pop("secrets_store", None)
        cfg.pop("config_file", None)
        return cfg
    use_store = cfg.pop("secrets_store", False)
    if use_store and name:
        from secrets_store import store as secrets_store

        stored = secrets_store.get_key(name)
        if stored:
            cfg["api_key"] = stored
            return cfg
    config_file = cfg.pop("config_file", "")
    if config_file:  # من ملف إعدادات جاهز (JSON: baseUrl/apiKey/token)
        try:
            with open(config_file, encoding="utf-8") as handle:
                found = json.load(handle)
            if found.get("apiKey"):
                cfg["api_key"] = found["apiKey"]
                headers = {"X-Z-AI-From": "Z"}
                if found.get("token"):
                    headers["X-Token"] = found["token"]
                cfg.setdefault("headers", {}).update(headers)
                return cfg
        except (OSError, ValueError):
            return None
    return cfg if cfg.get("api_key") else None


def resolve_live_providers(cfg: "Any" = None) -> dict[str, dict]:
    """حل المزودات الحية: سجل القاعدة الدائم + JSON الإعدادات.

    (الأمر 007.1 §15): سجل المزودين في القاعدة هو مصدر الحقيقة —
    المزودون المباشرون من الواجهة، بتكويناتهم المتعددة، يُحلّون هنا.
    JSON الإعدادات (AGenthubV2_LIVE_PROVIDERS) ما زال يعمل فوقهم
    (تخصيص تشغيلي معلن). القالب المدمج يعمل عند غياب سياق القاعدة
    فقط (اختبارات مباشرة بلا خادم). المزود بلا مفتاح قابل للحل
    يُستبعد صراحةً — لا يُنادى أبدًا (فشل صريح لا 401 عشوائية).
    """
    live_cfg = cfg or live_model_settings
    resolved: dict[str, dict] = {}
    # 1) سجل القاعدة الدائم — إن وُجد سياق API (مصدر الحقيقة)
    db_specs = _resolve_db_provider_specs()
    if db_specs is not None:
        resolved.update(db_specs)
    else:
        # لا سياق قاعدة (اختبار مباشر) — القالب المدمج فقط
        for name, spec in BUILTIN_LIVE_PROVIDERS.items():
            found = _resolve_provider_credentials(dict(spec), name=name)
            if found:
                resolved[name] = found
    # 2) تخصيصات JSON التشغيلية فوق الجميع (معلنة لا خفية)
    if getattr(live_cfg, "providers_json", ""):
        try:
            custom = json.loads(live_cfg.providers_json)
        except ValueError as error:
            raise ProviderCallError(
                f"AGenthubV2_LIVE_PROVIDERS ليست JSON صالحًا: {error}"
            ) from error
        if not isinstance(custom, dict):
            raise ProviderCallError("AGenthubV2_LIVE_PROVIDERS يجب أن تكون كائن JSON")
        for name, spec in custom.items():
            if not isinstance(spec, dict) or not spec.get("base_url"):
                raise ProviderCallError(
                    f"المزود المخصص '{name}' يحتاج base_url على الأقل"
                )
            found = _resolve_provider_credentials(dict(spec), name=name)
            if found:
                merged = {**resolved.get(name, {}), **found}
                resolved[name] = merged
    # 3) (013.5 §B) عقد المخرجات والمهلة — معلن لكل مزود لم يحدده.
    #    السبب المقيس حيًّا: النموذج المُهيَّأ استدلالي، وسقف المخرجات
    #    الافتراضي (4000) يُستنفد داخل reasoning_content فيعود الرد
    #    بلا content إطلاقًا. السقف هنا يغطي الاستدلال + الإجابة،
    #    والمهلة تسمح بمرحلة استدلال طويلة شرعية (قيس: أول استدلال
    #    25ث، أول مخرج 112ث، إنهاء 266ث لخطة كاملة).
    for name, spec in resolved.items():
        spec.setdefault("max_tokens", live_cfg_max_tokens(live_cfg))
        spec.setdefault("timeout", live_cfg_timeout(live_cfg))
    return resolved


def live_cfg_max_tokens(live_cfg: "Any" = None) -> int:
    """سقف مخرجات معلن لكل استدعاء — يقبل ضبطًا بمتغير بيئة صريح."""
    cfg = live_cfg or live_model_settings
    try:
        value = int(getattr(cfg, "max_tokens", 0) or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_MAX_TOKENS


def live_cfg_timeout(live_cfg: "Any" = None) -> float:
    """مهلة نقل معلنة لكل استدعاء — تكفي لاستدلال طويل شرعي."""
    cfg = live_cfg or live_model_settings
    try:
        value = float(getattr(cfg, "timeout", 0) or 0)
    except (TypeError, ValueError):
        value = 0.0
    return value if value > 0 else DEFAULT_REQUEST_TIMEOUT


def _resolve_db_provider_specs() -> dict[str, dict] | None:
    """مواصفات المزودين من سجل القاعدة — None إن لم يوجد سياق قاعدة.

    فشلُ مزودٍ واحد في الحل لا يمنع غيره (007.1 §9): كل تكوين يُحل
    باستقلال تام، والمقصي هو الذي بلا مصادقة قابلة للحل فقط.
    """
    try:
        from providers_registry import registry  # noqa: PLC0415 — كسول يمنع الدوران

        sessions = registry._api_sessions()
        if sessions is None:
            return None
        return registry.resolve_provider_specs(sessions)
    except Exception:  # noqa: BLE001 — لا قاعدة = القالب المدمج
        return None
