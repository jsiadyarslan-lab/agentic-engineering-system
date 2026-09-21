"""نقاط نهاية إعدادات النماذج (الأمر 006 §5+§13 + الأمر 007.1 §10).

GET /api/models/config : المزودون بتكويناتهم وجاهزيتهم + ربط كل دور
                          (مزود + تكوين + نموذج) — من القاعدة الدائمة.
PUT /api/models/config : حفظ ربط الأدوار — بعد تحقق صارم: مزود معروف
                          وتكوين موجود ونموذج معلَن في التكوين.

لا تُعاد قيمة مفتاح من أي رد أبدًا — حالة المخزن فقط.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from providers_registry import registry

router = APIRouter(prefix="/api/models", tags=["models-config"])


def _sessions():
    from api import routes  # noqa: PLC0415 — كسول: routes يُستورد متأخرًا

    return routes._sessions


#: أسماء الأدوار العربية — المرجع الواحد للعرض (core/roles.py هو المصدر).
ROLE_LABELS: dict[str, str] = {
    "thinker": "المفكر",
    "reviewer": "المدقق",
    "implementer": "المنفذ",
    "verifier": "المراجع",
    "arbiter": "المُحكَّم",
    "chat": "المحادثة",
}


class RoleSelectionIn(BaseModel):
    """جسم اختيار دور واحد — مزود + تكوين + نموذج (007.1 §10)."""

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    configuration: str = Field(default="", max_length=120)


class ModelsConfigIn(BaseModel):
    """جسم الحفظ — دور واحد على الأقل، والباقي يبقى كما هو."""

    thinker: RoleSelectionIn | None = None
    reviewer: RoleSelectionIn | None = None
    implementer: RoleSelectionIn | None = None
    verifier: RoleSelectionIn | None = None
    arbiter: RoleSelectionIn | None = None
    chat: RoleSelectionIn | None = None


def _provider_payload(provider: dict) -> dict:
    """حالة المزود للعرض — متاح للربط الحي أم لا، ولماذا (صادق)."""
    configs = provider["configurations"]
    usable = [c for c in configs if c["enabled"]]
    if not usable:
        return {**_base(provider), "available": False,
                "state": "غير مفعّل", "reason": "لا تكوين مفعّل للمزود"}
    primary = usable[0]
    if provider["auth_type"] == "bearer" and not provider.get("has_key"):
        return {**_base(provider), "available": False,
                "state": "غير متصل",
                "reason": "لا مفتاح محفوظ لهذا المزود"}
    if provider["auth_type"] == "config_file" and not primary.get("config_file"):
        return {**_base(provider), "available": False,
                "state": "غير متصل",
                "reason": "ملف مصادقة المنشأة غير معلن"}
    return {
        **_base(provider),
        "available": True,
        "state": "متاح",
        "reason": None,
        "readiness_status": primary["readiness"]["status"],
    }


def _base(provider: dict) -> dict:
    primary = provider["configurations"][0] if provider["configurations"] else {}
    return {
        "id": provider["name"],          # الاسم هو المعرف في ربط الأدوار
        "provider_id": provider["id"],
        "label": provider["display_name"],
        "base_url": primary.get("base_url", ""),
        "requires_key": provider["auth_type"] == "bearer",
        "default_model": primary.get("default_model", ""),
        "known_models": primary.get("models", []),
        "has_key": provider.get("has_key"),
        "configurations": [
            {
                "name": c["name"],
                "base_url": c["base_url"],
                "default_model": c["default_model"],
                "models": c["models"],
                "enabled": c["enabled"],
                "is_primary": c["is_primary"],
                "readiness": c["readiness"],
            }
            for c in provider["configurations"]
        ],
    }


def _find_provider(name: str) -> dict | None:
    for provider in registry.list_providers(_sessions()):
        if provider["name"] == name:
            return provider
    return None


def _validate_selection(role: str, raw: dict) -> None:
    """تحقق صارم — الخطأ يسمي الدور والسبب (رفض لا تخمين)."""
    label = ROLE_LABELS.get(role, role)
    provider = _find_provider(raw["provider"])
    if provider is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"الدور '{label}': مزود غير معروف '{raw['provider']}' "
                "(أضفه من إدارة المزودين في الإعدادات)"
            ),
        )
    if not provider["enabled"]:
        raise HTTPException(
            status_code=422,
            detail=f"الدور '{label}': المزود '{raw['provider']}' معطّل",
        )
    config_name = raw.get("configuration", "") or ""
    configs = {
        c["name"]: c for c in provider["configurations"] if c["enabled"]
    }
    if config_name and config_name not in configs:
        raise HTTPException(
            status_code=422,
            detail=(
                f"الدور '{label}': تكوين غير معروف '{config_name}' لدى مزود "
                f"'{raw['provider']}' (المتاح: {sorted(configs)})"
            ),
        )
    cfg = configs.get(config_name) or (
        provider["configurations"][0] if provider["configurations"] else None
    )
    if cfg is None:
        raise HTTPException(
            status_code=422,
            detail=f"الدور '{label}': المزود '{raw['provider']}' بلا تكوين مفعّل",
        )
    allowed = set(cfg.get("models", [])) | ({cfg["default_model"]} if cfg["default_model"] else set())
    if raw["model"] not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"الدور '{label}' ({role}): النموذج '{raw['model']}' غير معلَن "
                f"في تكوين '{cfg['name']}' لدى مزود '{raw['provider']}' — "
                f"المعلنون: {sorted(allowed)[:12]}"
            ),
        )


@router.get("/config")
def get_models_config() -> dict:
    """الإعدادات الحالية: مزودون بتكويناتهم + ربط كل دور — من القاعدة."""
    from router.role_config import DEFAULT_MODEL, DEFAULT_PROVIDER, ROLE_KEYS

    providers = registry.list_providers(_sessions())
    mappings = registry.get_mappings(_sessions())
    roles = []
    for key in ROLE_KEYS:
        found = mappings.get(key, {})
        roles.append({
            "key": key,
            "label": ROLE_LABELS.get(key, key),
            "selection": {
                "provider": found.get("provider", DEFAULT_PROVIDER),
                "configuration": found.get("configuration", ""),
                "model": found.get("model", DEFAULT_MODEL),
            },
            "is_default": (
                found.get("provider", DEFAULT_PROVIDER) == DEFAULT_PROVIDER
                and found.get("model", DEFAULT_MODEL) == DEFAULT_MODEL
            ),
        })
    return {
        "providers": [_provider_payload(p) for p in providers],
        "roles": roles,
        "defaults": {
            "provider": DEFAULT_PROVIDER,
            "model": DEFAULT_MODEL,
        },
        "warning": None,
        "note": "اختيار كل دور مستقل (مزود + تكوين + نموذج) — دائم في القاعدة",
    }


@router.put("/config")
def put_models_config(body: ModelsConfigIn) -> dict:
    """حفظ ربط الأدوار — تحقق صارم ثم upsert دائم في القاعدة."""
    from router.role_config import ROLE_KEYS

    incoming = {
        key: value
        for key, value in body.model_dump().items()
        if value is not None
    }
    if not incoming:
        raise HTTPException(
            status_code=422, detail="لا اختيارات في الطلب — دور واحد على الأقل"
        )
    validated: dict[str, dict] = {}
    for key, raw in incoming.items():
        if key not in ROLE_KEYS:
            raise HTTPException(status_code=422, detail=f"دور غير معروف: {key}")
        _validate_selection(key, raw)
        validated[key] = raw
    registry.save_mappings(_sessions(), validated)
    return {
        "success": True,
        "saved": sorted(validated),
        "selections": registry.get_mappings(_sessions()),
        "note": "حُفظ ربط الأدوار في القاعدة — المهام القادمة تستخدمه",
    }
