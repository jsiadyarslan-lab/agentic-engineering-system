"""نقاط نهاية إعدادات النماذج (الأمر 006 §5+§13) — لكل دور اختياره.

GET /api/models/config : المزودون وحالتهم + اختيار كل دور + الافتراضات.
PUT /api/models/config : حفظ اختيارات الأدوار — بعد تحقق صارم:
                          مزود معروف + نموذج معلَن أو حي.

لا تُعاد قيمة مفتاح من أي رد أبدًا (تقنيع ****+آخر 4 في الأفضل،
وهنا لا تُعاد أصلًا — حالة المخزن فقط).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.providers import PROVIDER_CARDS, _get_models, _provider_auth
from router import role_config as rc
from secrets_store import store as secrets

router = APIRouter(prefix="/api/models", tags=["models-config"])

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
    """جسم اختيار دور واحد — مزود + نموذج."""

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)


class ModelsConfigIn(BaseModel):
    """جسم الحفظ — دور واحد على الأقل، والباقي يبقى كما هو."""

    thinker: RoleSelectionIn | None = None
    reviewer: RoleSelectionIn | None = None
    implementer: RoleSelectionIn | None = None
    verifier: RoleSelectionIn | None = None
    arbiter: RoleSelectionIn | None = None
    chat: RoleSelectionIn | None = None


def _provider_availability(name: str, card: dict) -> dict:
    """حالة المزود الصادقة: متاح للربط الحي أم لا — ولماذا."""
    if not card["requires_key"]:
        # مزود بلا مفتاح مطلوب (منشأة معلنة): متاح إن حلّت مصادقته
        from router.live_providers import _resolve_provider_credentials

        spec = {
            k: v for k, v in card.items()
            if k in ("base_url", "model", "config_file")
        }
        resolved = _resolve_provider_credentials(spec, name)
        return {
            "available": resolved is not None,
            "state": "متاح" if resolved else "غير متصل",
            "reason": None if resolved else "تعذّر حل مصادقة المنشأة المعلنة",
        }
    has_key = bool(secrets.get_key(name))
    return {
        "available": has_key,
        "state": "متاح" if has_key else "غير متصل",
        "reason": None if has_key else "لا مفتاح محفوظ لهذا المزود",
    }


def _provider_payload(name: str) -> dict[str, Any]:
    card = PROVIDER_CARDS[name]
    availability = _provider_availability(name, card)
    return {
        "id": name,
        "label": card["label"],
        "base_url": card["base_url"],
        "requires_key": card["requires_key"],
        "default_model": card["model"],
        "known_models": list(card.get("known_models", [])),
        "has_key": bool(secrets.get_key(name)) if card["requires_key"] else None,
        "availability": availability,
    }


def _live_model_ids(name: str) -> set[str]:
    """أفضل محاولة لجلب النماذج الحية — الفشل = مجموعة فارغة (معلنة فقط).

    تجاوز كاش الواجهة هنا مقصود: التحقق وقت الحفظ يريد الحقيقة الآن،
    لا قائمة عمرها 5 دقائق غيّرها المزود.
    """
    try:
        api_key, headers = _provider_auth(name)
    except HTTPException:
        return set()
    outcome = _get_models(PROVIDER_CARDS[name]["base_url"], api_key, headers)
    if outcome.get("ok"):
        return {str(m) for m in outcome.get("model_ids", [])}
    return set()


def _validate_selection(role: str, selection: rc.RoleSelection) -> None:
    """تحقق صارم — الخطأ يسمي الدور والسبب (رفض لا تخمين)."""
    if selection.provider not in PROVIDER_CARDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"الدور '{ROLE_LABELS.get(role, role)}': مزود غير معروف "
                f"'{selection.provider}' (المعروفون: {sorted(PROVIDER_CARDS)})"
            ),
        )
    card = PROVIDER_CARDS[selection.provider]
    allowed = set(card.get("known_models", [])) | {card["model"]}
    allowed |= _live_model_ids(selection.provider)
    if selection.model not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"الدور '{ROLE_LABELS.get(role, role)}' ({role}): النموذج "
                f"'{selection.model}' غير موجود ولا معلَن لدى مزود "
                f"'{selection.provider}' — المعلنون: {sorted(allowed)[:12]}"
            ),
        )


@router.get("/config")
def get_models_config() -> dict:
    """الإعدادات الحالية: مزودون + اختيار كل دور + الافتراضات المعلنة."""
    selections = rc.load_role_config()
    return {
        "providers": [_provider_payload(name) for name in PROVIDER_CARDS],
        "roles": [
            {
                "key": key,
                "label": ROLE_LABELS.get(key, key),
                "selection": selections[key].as_dict(),
                "is_default": (
                    selections[key].provider == rc.DEFAULT_PROVIDER
                    and selections[key].model == rc.DEFAULT_MODEL
                ),
            }
            for key in rc.ROLE_KEYS
        ],
        "defaults": {
            "provider": rc.DEFAULT_PROVIDER,
            "model": rc.DEFAULT_MODEL,
        },
        "warning": rc.load_warning(),
        "note": "اختيار كل دور مستقل — لا دور يرث مزود دور آخر",
    }


@router.put("/config")
def put_models_config(body: ModelsConfigIn) -> dict:
    """حفظ اختيارات الأدوار — تحقق صارم ثم حفظ atomic."""
    incoming = {
        key: value
        for key, value in body.model_dump().items()
        if value is not None
    }
    if not incoming:
        raise HTTPException(
            status_code=422, detail="لا اختيارات في الطلب — دور واحد على الأقل"
        )
    selections = rc.load_role_config()
    validated: dict[str, rc.RoleSelection] = {}
    for key, raw in incoming.items():
        if key not in rc.ROLE_KEYS:
            raise HTTPException(
                status_code=422, detail=f"دور غير معروف: {key}"
            )
        try:
            selection = rc.RoleSelection(
                provider=raw["provider"], model=raw["model"]
            )
        except (KeyError, TypeError) as error:
            raise HTTPException(
                status_code=422,
                detail=f"الدور '{key}': اختيار غير صالح ({error})",
            ) from error
        _validate_selection(key, selection)
        validated[key] = selection
    selections.update(validated)
    rc.save_role_config(selections)
    return {
        "success": True,
        "saved": sorted(validated),
        "selections": rc.selections_as_dict(selections),
        "note": "حُفظت اختيارات النماذج لكل دور — المهام القادمة تستخدمها",
    }
