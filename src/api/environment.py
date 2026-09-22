"""نقاط نهاية البيئة والجاهزية (الأمر 009 §22-§23+§32 + 013 §16-§17).

- GET  /api/environment/readiness   كل القدرات بآخر قراءة (STALE مطبقة)
- POST /api/environment/probe       {capability_id} — مسبار واحد حقيقي
- POST /api/environment/probe/all   الفحص الكامل (كل قدرة بمسبارها)
- POST /api/environment/provision   تجهيز بيئة تنفيذ — دورة معلنة (013)
- GET  /api/environment/provision/heartbeat  نبضة البيئة الأخيرة
- GET  /api/environment/inventory   جرد البيئة الفعلي (OS/CPU/…/شبكة)
- GET  /api/environment/metrics     لقطة المقاييس الحية
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from readiness import environment, metrics, registry

router = APIRouter(prefix="/api/environment", tags=["environment"])

#: منفذ الفحص الكامل — المسبارات شبكية؛ لا يحتجز حلقة الأحداث.
_probe_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="env")


def _sessions():
    from api import routes  # noqa: PLC0415 — كسول: routes يُستورد متأخرًا

    return routes._sessions


class ProbeIn(BaseModel):
    """جسم مسبار واحد — قدرة من الجرد."""

    capability_id: str = Field(min_length=1, max_length=64)


@router.get("/readiness")
def readiness_state() -> dict:
    """القدرات بالعرض المشتق الموحد (011 §14) — مصدر واحد لا تناقض.

    القدرات المجمعة (web_search من مزوديها، sandbox من بيئاتها)
    تُشتق من مصادرها الحقيقية لحظة القراءة — فلا يمكن لمزود أن
    يقول جاهز والقدرة تقول منتهية في نفس الرد أبدًا.
    """
    from readiness import service as readiness_service

    caps = readiness_service.capabilities_view(_sessions())
    summary = readiness_service.summary(_sessions())
    return {
        "capabilities": caps,
        "summary": summary,
        "note": "مصدر واحد للحقيقة — المجمعة تُشتق من مزوديها/بيئاتها "
                "بصلاحية موحدة؛ READY بمسبار حقيقي فقط",
    }


@router.post("/probe")
def probe_one(body: ProbeIn) -> dict:
    """مسبار واحد حقيقي — النتيجة تُكتب دائمًا وتُعاد."""
    try:
        result = registry.run_probe(_sessions(), body.capability_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail=str(error.args[0] or error)
        ) from error
    metrics.count_probe(result.get("probe_latency_ms", 0),
                        result.get("readiness_status") == "READY")
    return result


@router.post("/probe/all")
def probe_all() -> dict:
    """الفحص الكامل (§22) — كل قدرة بمسبارها، فشل واحدة لا يوقف البقية."""
    results = registry.probe_all(_sessions())
    for result in results:
        metrics.count_probe(result.get("probe_latency_ms", 0),
                            result.get("readiness_status") == "READY")
    summary = {"READY": 0, "DEGRADED": 0, "NOT_READY": 0, "UNAVAILABLE": 0}
    for result in results:
        status = result.get("readiness_status", "UNKNOWN")
        summary[status] = summary.get(status, 0) + 1
    return {
        "results": results,
        "summary": summary,
        "note": "فحص كامل حقيقي — لا جاهزية بلا مسبار ناجح",
    }


@router.get("/inventory")
def inventory() -> dict:
    """جرد البيئة الفعلي (§5) — كل عنصر مقروء لحظة الطلب."""
    return environment.environment_inventory()


@router.get("/metrics")
def observability() -> dict:
    """لقطة المقاييس (§32) — عدادات فعلية من مسار الأدوات."""
    return metrics.snapshot()


@router.post("/provision")
def provision_environment() -> dict:
    """تجهيز بيئة التنفيذ (013 §16-§17) — دورة حياة معلنة.

    DISCOVERING ← PROVISIONING ← BOOTING ← HEALTH_CHECK ← READY،
    وكل خطوة موقوتة بمعلن في الاستجابة وعلى التيار الحي. التعذر
    البنيوي = PROVISIONING_UNAVAILABLE بالمتطلب الحرفي (لا فشل
    ملفق ولا READY كاذبة). النجاح يسجل البيئة جاهزة فورًا — المسبار
    والمنفذ من مصدر واحد (011 محفوظ).
    """
    from execution import provisioner

    return provisioner.provision(_sessions())


@router.get("/provision/heartbeat")
def provision_heartbeat() -> dict:
    """نبضة البيئة الأخيرة (013 §16) — فارغة = لم تنبض بعد."""
    from execution import provisioner

    return {
        "heartbeat": provisioner.last_heartbeat(),
        "note": "النبضة فحص جاهزية حقيقي — الحقيقة في سجل البيئات",
    }


@router.post("/provision/heartbeat")
def run_provision_heartbeat() -> dict:
    """إجراء نبضة الآن — فحص جاهزية حقيقي بالوقت والنتيجة (§16)."""
    from execution import provisioner

    return provisioner.heartbeat(_sessions())
