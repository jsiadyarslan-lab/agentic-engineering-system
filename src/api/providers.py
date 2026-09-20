"""نقاط نهاية المزودات (الأمر السادس المنقح §1) — منقولة من v1.

نفس عقد v1: بطاقات مزودات + حفظ/حذف مفتاح في مخزن الأسرار + اختبار
اتصال حقيقي (ping صغير عبر نقطة /models) + جلب قائمة النماذج.
لا تُعاد قيمة مفتاح كاملة من أي نقطة إطلاقًا — تقنيع ****+آخر 4 فقط،
والسجلات يحميها مرشح [REDACTED].
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from secrets_store import store as secrets

router = APIRouter(prefix="/api/providers", tags=["providers"])

#: سجل المزودات — بطاقة لكل مزود (نفس بطاقات v1 §1.4: nvidia تظهر فورًا).
PROVIDER_CARDS: dict[str, dict[str, Any]] = {
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "requires_key": True,
        "model": "nemotron-3-ultra-550b-a55b",
        "note": "المزود الافتراضي — مفتاحك يُحفظ في مخزن الأسرار (DPAPI على Windows)",
    },
    "openai_compatible": {
        "label": "OpenRouter (متوافق OpenAI)",
        "base_url": "https://openrouter.ai/api/v1",
        "requires_key": True,
        "model": "anthropic/claude-haiku-3.5",
        "note": "بديل اختياري — يُفعَّل بحفظ مفتاحه",
    },
    "zai_internal": {
        "label": "z.ai داخلي (منشأة الحاوية المعلنة)",
        "base_url": "https://internal-api.z.ai/v1",
        "requires_key": False,
        "model": "glm-4.6",
        "config_file": "/etc/.z-ai-config",
        "note": "منشأة اختبار معلنة داخل الحاوية — مصادقتها من ملف الإعدادات",
    },
}


class ProviderKeyIn(BaseModel):
    """جسم حفظ مفتاح — القيمة لا تُعاد أبدًا (تقنيع فقط)."""

    key: str = Field(min_length=1, max_length=4096)


def _card(name: str) -> dict:
    card = PROVIDER_CARDS[name]
    key = secrets.get_key(name) if card["requires_key"] else None
    return {
        "id": name,
        "label": card["label"],
        "base_url": card["base_url"],
        "requires_key": card["requires_key"],
        "model": card["model"],
        "note": card["note"],
        "has_key": bool(key),
        "key_masked": secrets.mask(key) if key else None,
    }


@router.get("")
def list_providers() -> dict:
    """بطاقات المزودات + حالة المخزن — بلا أي قيمة سرية."""
    return {
        "providers": [_card(name) for name in PROVIDER_CARDS],
        "store": secrets.store_status(),
        "default": {"provider": "nvidia", "model": "nemotron-3-ultra-550b-a55b"},
    }


@router.put("/{name}/key")
def put_provider_key(name: str, body: ProviderKeyIn) -> dict:
    """حفظ مفتاح مزود في مخزن الأسرار (DPAPI على Windows، §1.2)."""
    if name not in PROVIDER_CARDS:
        raise HTTPException(status_code=404, detail=f"مزود غير معروف: {name}")
    if not PROVIDER_CARDS[name]["requires_key"]:
        raise HTTPException(
            status_code=400,
            detail=f"المزود {name} لا يتطلب مفتاح API (مصادقته معلنة)",
        )
    key = body.key.strip()
    if len(key) < 8:
        raise HTTPException(
            status_code=400, detail="المفتاح قصير جدًا (الحد الأدنى 8 أحرف)"
        )
    secrets.set_key(name, key)
    masked = secrets.mask(key)
    # السجل يحمل القيمة المقنّعة فقط — أبدًا لا يُكتب المفتاح كاملًا
    return {
        "success": True,
        "message": f"تم حفظ مفتاح المزود {name} في المخزن المحلي ({masked})",
        "provider": name,
        "key_masked": masked,
    }


@router.delete("/{name}/key")
def delete_provider_key(name: str) -> dict:
    """حذف مفتاح مزود من المخزن المحلي."""
    if name not in PROVIDER_CARDS:
        raise HTTPException(status_code=404, detail=f"مزود غير معروف: {name}")
    existed = secrets.delete_key(name)
    message = (
        f"تم حذف مفتاح المزود {name} من المخزن المحلي"
        if existed
        else f"لا يوجد مفتاح محفوظ للمزود {name} أصلًا"
    )
    return {"success": True, "message": message, "existed": existed, "provider": name}


def _provider_auth(name: str) -> tuple[str, dict[str, str]]:
    """حل مصادقة مزود لاختبار الاتصال — (المفتاح، ترويسات إضافية).

    المفتاح من المخزن المحلي حصرًا (لا بيئة §0.3)؛ zai_internal
    منشأة معلنة تقرأ مصادقتها من ملف الإعدادات.
    """
    card = PROVIDER_CARDS[name]
    headers: dict[str, str] = {}
    config_file = card.get("config_file")
    if config_file:
        try:
            with open(config_file, encoding="utf-8") as handle:
                found = json.load(handle)
        except (OSError, ValueError) as error:
            raise HTTPException(
                status_code=503,
                detail=f"ملف مصادقة المنشأة غير مقروء: {error}",
            ) from error
        headers["X-Z-AI-From"] = "Z"
        if found.get("token"):
            headers["X-Token"] = str(found["token"])
        return str(found.get("apiKey", "")), headers
    key = secrets.get_key(name)
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"لا مفتاح محفوظ للمزود {name} — احفظه أولًا من بطاقته",
        )
    return key, headers


def _get_models(base_url: str, api_key: str, extra_headers: dict) -> dict:
    """GET {base_url}/models عبر urllib — ping صغير بلا استهلاك توكنات."""
    request = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            **extra_headers,
        },
        method="GET",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read()[:200].decode("utf-8", "replace")
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "models_count": 0,
            "message": f"HTTP {error.code}: {detail}",
        }
    except Exception as error:  # noqa: BLE001 — خطأ شبكة واحد صريح
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "models_count": 0,
            "message": f"فشل الاتصال: {error}",
        }
    models = body.get("data", []) if isinstance(body, dict) else []
    return {
        "ok": True,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "models_count": len(models),
        "message": "اتصال ناجح",
        "model_ids": [str(m.get("id", "")) for m in models][:200],
    }


@router.post("/{name}/test")
def test_provider(name: str) -> dict:
    """اختبار اتصال حقيقي بالمفتاح المخزن — ping صغير (§1.4).

    يعيد دائمًا 200 (الخطأ داخل الجسم) — الخادم لا ينهار أبدًا،
    والمفتاح لا يظهر في أي مخرج.
    """
    if name not in PROVIDER_CARDS:
        raise HTTPException(status_code=404, detail=f"مزود غير معروف: {name}")
    try:
        api_key, headers = _provider_auth(name)
    except HTTPException as error:
        return {"ok": False, "latency_ms": 0, "models_count": 0,
                "message": str(error.detail)}
    return _get_models(PROVIDER_CARDS[name]["base_url"], api_key, headers)


#: كاش قوائم النماذج — 5 دقائق لكل مزود (نفس سياسة v1).
_models_cache: dict[str, tuple[float, dict]] = {}
_MODELS_TTL = 300.0


@router.get("/{name}/models")
def list_provider_models(name: str, refresh: bool = False) -> dict:
    """جلب قائمة النماذج من المزود — تظهر في بطاقة الإعدادات (§1.1)."""
    if name not in PROVIDER_CARDS:
        raise HTTPException(status_code=404, detail=f"مزود غير معروف: {name}")
    cached = _models_cache.get(name)
    now = time.monotonic()
    if cached and not refresh and now - cached[0] < _MODELS_TTL:
        return {**cached[1], "cached": True}
    try:
        api_key, headers = _provider_auth(name)
    except HTTPException as error:
        return {"ok": False, "message": str(error.detail), "model_ids": []}
    result = _get_models(PROVIDER_CARDS[name]["base_url"], api_key, headers)
    _models_cache[name] = (now, result)
    return {**result, "cached": False}
