"""نقاط نهاية البحث (الأمر 010 §24-§25) — مزودون حقيقيون قابلة للتوفير.

- GET  /api/research/providers           المزودون + حالة مسبار كل واحد
- POST /api/research/providers/{id}/probe     مسبار حقيقي واحد
- POST /api/research/providers/{id}/configure تعديل التكوين (+مفتاح للمخزن)
- POST /api/research/search              بحث فعلي بأول مزود جاهز
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from research import service

router = APIRouter(prefix="/api/research", tags=["research"])


def _sessions():
    from api import routes  # noqa: PLC0415 — كسول يمنع الاستيراد الدائري

    return routes._sessions


class ConfigureIn(BaseModel):
    """تعديل تكوين مزود بحث — المفتاح يذهب للمخزن لا الردود أبدًا."""

    config: dict[str, str] = Field(default_factory=dict)
    enabled: bool | None = None
    api_key: str = Field(default="", max_length=400)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=400)


@router.get("/providers")
def providers() -> dict:
    """المزودون بحالتهم المشتقة الموحدة (011 §12-§14).

    effective_status تطبق الصلاحية: مسبار READY قديم = STALE — فلا
    يمكن أن يقول المزود «جاهز» والقدرة «منتهية» في نفس اللحظة.
    """
    from readiness.service import research_providers_view

    return {
        "providers": research_providers_view(_sessions()),
        "note": "البحث قدرة قابلة للتوفير — DDG مهلة ≠ الإنترنت مقطوع؛ "
                "الحالة المعروضة موحدة الصلاحية مع قدرة web_search",
    }


@router.post("/providers/{provider_id}/probe")
def probe(provider_id: int) -> dict:
    try:
        return service.probe_provider(_sessions(), provider_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail=str(error.args[0] or error)
        ) from error


@router.post("/providers/{provider_id}/configure")
def configure(provider_id: int, body: ConfigureIn) -> dict:
    """حفظ ← فحص حقيقي ← جاهزية محدثة (011 §16) — لا save فقط."""
    try:
        record = service.configure_provider(
            _sessions(), provider_id, config=body.config,
            enabled=body.enabled, api_key=body.api_key,
        )
        from readiness.service import provider_effective_state

        state = provider_effective_state(record)
        return {**record, "effective_status": state["status"],
                "state_reason": state["reason"]}
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail=str(error.args[0] or error)
        ) from error


@router.post("/search")
def search(body: SearchIn) -> dict:
    try:
        return service.search(_sessions(), body.query)
    except Exception as error:  # noqa: BLE001 — أخطاء الأداة مصنفة أصلًا
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/providers/probe/all")
def probe_all() -> dict:
    results = service.probe_all(_sessions())
    return {
        "results": results,
        "aggregate": service.aggregate_capability(_sessions()),
    }
