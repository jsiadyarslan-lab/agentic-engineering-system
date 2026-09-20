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


class ProviderCallError(Exception):
    """خطأ نقل مزود — تصنيفه بسمات صريحة تقرؤها الحزم بطرفية.

    is_throttle:      429/503-overloaded — يدخل حلقة التبريد.
    is_server_error:  5xx غير الاختناقي — إعادات ثم تبدّل.
    is_timeout:       انتهت مهلة الاتصال/الفتحة — كخطأ خادم.
    retry_after:      ثواني رأس Retry-After إن أرسلها المزود.
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
    ) -> None:
        super().__init__(message)
        self.code = code
        self.is_throttle = is_throttle
        self.is_server_error = is_server_error
        self.is_timeout = is_timeout
        self.retry_after = retry_after




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
    """حل المزودات الحية: المدمج + JSON الإعدادات — بلا مفاتيح يُستبعد.

    المزود من providers_json ينسخ فوق المدمج بالاسم نفسه (تخصيص كامل:
    base_url/api_key/model/الحدود). المزود بلا مفتاح قابل للحل يُستبعد
    صراحةً — لا يُنادى أبدًا (فشل صريح لا 401 عشوائية).
    """
    live_cfg = cfg or live_model_settings
    resolved: dict[str, dict] = {}
    for name, spec in BUILTIN_LIVE_PROVIDERS.items():
        found = _resolve_provider_credentials(dict(spec), name=name)
        if found:
            resolved[name] = found
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
    return resolved
