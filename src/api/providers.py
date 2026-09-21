"""نقاط نهاية المزودين (الأمر 007.1 §14) — إدارة كاملة من الواجهة.

هذه لم تعد بطاقات مغلقة في الكود: المزود كيان دائم في القاعدة
(إنشاء/تعديل/حذف)، وله تكوينات متعددة (Base URLs) قابلة للإضافة
والتعديل والحذف مع حماية المستخدَم منها، ومسبار جاهزية حقيقي بتصنيف
صريح (READY/AUTH_FAILED/NOT_FOUND/…) وتشخيص منظم كامل (§7).

نقاط النهاية:
- GET/POST /api/providers                     قائمة/إنشاء
- GET/PUT/DELETE /api/providers/{id}          تفصيل/تعديل/حذف
- GET/POST /api/providers/{id}/configurations تكوينات المزود
- PUT/DELETE /api/provider-configurations/{id} تعديل/حذف تكوين
- POST /api/provider-configurations/{id}/test مسبار الجاهزية
- GET /api/providers/{id}/models              نماذج التكوين الأساسي
- POST /api/providers/{id}/models/refresh     جلب حي للنماذج
- PUT/DELETE /api/providers/{name}/key        مفاتيح الأسرار (توافق 006)

لا قيمة مفتاح تعود من أي نقطة إطلاقًا — تقنيع ****+آخر 4 فقط.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from providers_registry import registry
from secrets_store import store as secrets

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _sessions():
    """جلسة القاعدة الحية — مسؤولية routes (المصدر الموحد)."""
    from api import routes  # noqa: PLC0415 — كسول: routes يُستورد متأخرًا

    return routes._sessions


def _err(error: Exception) -> HTTPException:
    """خطأ السجل → HTTP صادق يسمي السبب."""
    if isinstance(error, KeyError):
        return HTTPException(status_code=404, detail=str(error.args[0] or error))
    return HTTPException(status_code=422, detail=str(error))


# ------------------------------------------------------------------ #
# أجسام الطلبات
# ------------------------------------------------------------------ #

class ProviderKeyIn(BaseModel):
    """جسم حفظ مفتاح — القيمة لا تُعاد أبدًا (تقنيع فقط)."""

    key: str = Field(min_length=8, max_length=4096)


class ProviderCreateIn(BaseModel):
    """إنشاء مزود جديد من الواجهة (§3) — القائمة ليست مغلقة."""

    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]+$")
    display_name: str = Field(default="", max_length=120)
    type: str = Field(default="custom", max_length=40)
    api_style: str = Field(default="openai_compatible", max_length=40)
    auth_type: str = Field(default="bearer", max_length=20)
    enabled: bool = True
    base_url: str = Field(default="", max_length=500)
    default_model: str = Field(default="", max_length=200)
    models: list[str] = Field(default_factory=list)
    config_file: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=4096, description="يُحفظ في مخزن الأسرار ولا يُعاد أبدًا")


class ProviderUpdateIn(BaseModel):
    """تعديل مزود — الحقول القابلة للتغيير حصرًا."""

    display_name: str | None = Field(default=None, max_length=120)
    type: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None
    api_style: str | None = Field(default=None, max_length=40)
    auth_type: str | None = Field(default=None, max_length=20)


class ConfigurationIn(BaseModel):
    """تكوين مزود — Base URL واحد بنموذجه (§4+§5)."""

    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)
    api_style: str = Field(default="openai_compatible", max_length=40)
    enabled: bool = True
    default_model: str = Field(default="", max_length=200)
    models: list[str] = Field(default_factory=list)
    config_file: str = Field(default="", max_length=500)


class ConfigurationUpdateIn(BaseModel):
    """تعديل تكوين — base_url قابل للتغيير بلا لمس الكود (§4)."""

    name: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    api_style: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None
    default_model: str | None = Field(default=None, max_length=200)
    models: list[str] | None = None
    config_file: str | None = Field(default=None, max_length=500)


# ------------------------------------------------------------------ #
# القائمة والإنشاء
# ------------------------------------------------------------------ #

@router.get("")
def list_providers() -> dict:
    """كل المزودين بتكويناتهم وجاهزيتهم — من القاعدة الدائمة."""
    providers = registry.list_providers(_sessions())
    return {
        "providers": providers,
        "store": secrets.store_status(),
        "default": _default_selection(),
    }


def _default_selection() -> dict:
    """الاختيار الافتراضي الحالي لعرض الواجهة — من ربط الأدوار الدائم."""
    try:
        mappings = registry.get_mappings(_sessions())
        chat = mappings.get("chat", {})
        return {
            "provider": chat.get("provider", "nvidia"),
            "configuration": chat.get("configuration", ""),
            "model": chat.get("model", ""),
        }
    except Exception:  # noqa: BLE001 — العرض لا ينهار
        return {"provider": "nvidia", "configuration": "", "model": ""}


@router.post("", status_code=201)
def create_provider(body: ProviderCreateIn) -> dict:
    """إنشاء مزود جديد — لا تعديل مصدر مطلوب أبدًا (§3)."""
    try:
        provider = registry.create_provider(
            _sessions(),
            name=body.name, display_name=body.display_name, type_=body.type,
            api_style=body.api_style, auth_type=body.auth_type,
            enabled=body.enabled, base_url=body.base_url,
            default_model=body.default_model, models=body.models,
            config_file=body.config_file,
        )
    except ValueError as error:
        raise _err(error) from error
    # مفتاح اختياري مع الإنشاء — يذهب لمخزن الأسرار مباشرة (لا سجل)
    if body.api_key:
        if provider["auth_type"] != "bearer":
            raise HTTPException(
                status_code=422,
                detail="المزود لا يستخدم مفتاح Bearer — أزل api_key من الطلب",
            )
        secrets.set_key(provider["name"], body.api_key.strip())
        provider["has_key"] = True
        provider["key_masked"] = secrets.mask(body.api_key.strip())
    return {"success": True, "provider": provider}


@router.get("/{provider_id}")
def get_provider(provider_id: int) -> dict:
    """تفصيل مزود واحد — 404 صادق إن لم يكن معروفًا."""
    provider = registry.get_provider(_sessions(), provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"مزود غير معروف: {provider_id}")
    return provider


@router.put("/{provider_id}")
def update_provider(provider_id: int, body: ProviderUpdateIn) -> dict:
    """تعديل مزود — الحقول المعلنة فقط."""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=422, detail="لا حقول للتعديل في الطلب")
    try:
        return registry.update_provider(_sessions(), provider_id, **fields)
    except (ValueError, KeyError) as error:
        raise _err(error) from error


@router.delete("/{provider_id}")
def delete_provider(provider_id: int) -> dict:
    """حذف مزود — مرفوض إن كان مرتبطًا بأدوار (حماية الاستخدام §4)."""
    try:
        return registry.delete_provider(_sessions(), provider_id)
    except (ValueError, KeyError) as error:
        raise _err(error) from error


# ------------------------------------------------------------------ #
# التكوينات — إضافة/تعديل/حذف/اختبار Base URL (§4+§5)
# ------------------------------------------------------------------ #

@router.get("/{provider_id}/configurations")
def list_configurations(provider_id: int) -> dict:
    provider = registry.get_provider(_sessions(), provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"مزود غير معروف: {provider_id}")
    return {"configurations": provider["configurations"]}


@router.post("/{provider_id}/configurations", status_code=201)
def add_configuration(provider_id: int, body: ConfigurationIn) -> dict:
    """إضافة Base URL/تكوين جديد للمزود (§4 إضافة)."""
    try:
        cfg = registry.add_configuration(
            _sessions(), provider_id, name=body.name, base_url=body.base_url,
            api_style=body.api_style, enabled=body.enabled,
            default_model=body.default_model, models=body.models,
            config_file=body.config_file,
        )
    except (ValueError, KeyError) as error:
        raise _err(error) from error
    return {"success": True, "configuration": cfg}


configurations_router = APIRouter(
    prefix="/api/provider-configurations", tags=["providers"]
)


@configurations_router.put("/{config_id}")
def update_configuration(config_id: int, body: ConfigurationUpdateIn) -> dict:
    """تعديل تكوين — Base URL يتغير من الواجهة لا من الكود (§4 تعديل)."""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=422, detail="لا حقول للتعديل في الطلب")
    try:
        return registry.update_configuration(_sessions(), config_id, **fields)
    except (ValueError, KeyError) as error:
        raise _err(error) from error


@configurations_router.delete("/{config_id}")
def delete_configuration(config_id: int) -> dict:
    """حذف تكوين غير مستخدم (§4 حذف) — المحمي بالربط يُرفض."""
    try:
        return registry.delete_configuration(_sessions(), config_id)
    except (ValueError, KeyError) as error:
        raise _err(error) from error


@configurations_router.post("/{config_id}/test")
def test_configuration(config_id: int) -> dict:
    """مسبار الجاهزية الحقيقي (§4 اختبار) — تصنيف صريح وتشخيص كامل.

    يعيد دائمًا 200: النتيجة داخل الجسم ببنية موحدة — status من
    READINESS_STATES حصرًا، ولا «LIVE» بلا نجاح HTTP فعلي.
    """
    registry.log_provider_event(_sessions(), "PROVIDER_TEST_STARTED",
                                {"configuration_id": config_id})
    try:
        result = registry.probe_configuration(_sessions(), config_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0] or error))
    except ValueError as error:
        raise _err(error) from error
    return result


# ------------------------------------------------------------------ #
# النماذج (§12) — معلنة + جلب حي اختياري
# ------------------------------------------------------------------ #

@router.get("/{provider_id}/models")
def provider_models(provider_id: int) -> dict:
    """نماذج التكوين الأساسي للمزود — المعلنة دائمًا، والحي إن أمكن."""
    provider = registry.get_provider(_sessions(), provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"مزود غير معروف: {provider_id}")
    configs = [c for c in provider["configurations"] if c["is_primary"]] \
        or provider["configurations"]
    if not configs:
        return {"ok": False, "source": "declared", "model_ids": [],
                "models_count": 0, "message": "لا تكوين مفعّل لهذا المزود"}
    cfg = configs[0]
    return {
        "ok": True, "source": "declared",
        "model_ids": cfg["models"],
        "models_count": len(cfg["models"]),
        "configuration": cfg["name"],
        "message": "نماذج معلنة من تكوين المزود — استخدم تحديث النماذج للجلب الحي",
    }


@configurations_router.get("/{config_id}/models")
def configuration_models(config_id: int, live: int = 0) -> dict:
    """نماذج تكوين بعينه — المعلنة دائمًا + اكتشاف حي عند live=1.

    (الأمر 008 §9+§35): الاكتشاف يدمج (مكتشف ∪ معلن) في القاعدة —
    القائمة الكاملة (82 نموذجًا عند نفيديا مثلًا) تظهر كما هي، بلا
    اقتطاع ولا قائمة ثابتة. فشل الاكتشاف = رسالة صادقة والمعلنة تبقى.
    """
    cfg = registry.get_configuration(_sessions(), config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"تكوين غير معروف: {config_id}")
    if not live:
        return {
            "ok": True, "source": "declared",
            "model_ids": registry._cfg_models(cfg),
            "models_count": len(registry._cfg_models(cfg)),
        }
    return registry.refresh_models(_sessions(), config_id)


@router.post("/{provider_id}/models/refresh")
def refresh_provider_models(provider_id: int) -> dict:
    """جلب النماذج حيًا من التكوين الأساسي (§12) — ليس شرطًا للتشغيل."""
    provider = registry.get_provider(_sessions(), provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"مزود غير معروف: {provider_id}")
    configs = [c for c in provider["configurations"] if c["is_primary"]] \
        or provider["configurations"]
    if not configs:
        raise HTTPException(status_code=422, detail="لا تكوين مفعّل لهذا المزود")
    try:
        return registry.refresh_models(_sessions(), configs[0]["id"])
    except (ValueError, KeyError) as error:
        raise _err(error) from error


# ------------------------------------------------------------------ #
# مفاتيح الأسرار (توافق الأمر 006) — بالاسم لا بالمعرف
# ------------------------------------------------------------------ #

def _find_by_name(name: str) -> dict:
    for provider in registry.list_providers(_sessions()):
        if provider["name"] == name:
            return provider
    raise HTTPException(status_code=404, detail=f"مزود غير معروف: {name}")


@router.put("/{name}/key")
def put_provider_key(name: str, body: ProviderKeyIn) -> dict:
    """حفظ مفتاح مزود في مخزن الأسرار (DPAPI على Windows — §13)."""
    provider = _find_by_name(name)
    if provider["auth_type"] != "bearer":
        raise HTTPException(
            status_code=400,
            detail=f"المزود {name} لا يتطلب مفتاح API (مصادقته {provider['auth_type']})",
        )
    key = body.key.strip()
    secrets.set_key(name, key)
    masked = secrets.mask(key)
    return {
        "success": True,
        "message": f"تم حفظ مفتاح المزود {name} في المخزن المحلي ({masked})",
        "provider": name,
        "key_masked": masked,
    }


@router.delete("/{name}/key")
def delete_provider_key(name: str) -> dict:
    """حذف مفتاح مزود من المخزن المحلي."""
    _find_by_name(name)
    existed = secrets.delete_key(name)
    message = (
        f"تم حذف مفتاح المزود {name} من المخزن المحلي"
        if existed
        else f"لا يوجد مفتاح محفوظ للمزود {name} أصلًا"
    )
    return {"success": True, "message": message, "existed": existed, "provider": name}
