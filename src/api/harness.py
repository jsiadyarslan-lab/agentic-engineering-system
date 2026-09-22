"""نقاط نهاية الـHarness (012-J للقراءات) — نقل نحيف فوق الطبقة.

لا منطق هنا: الوظائف من harness/jobs، الإسقاطات من
harness/projections، الأدوار من harness/roles_runtime، القدرات من
harness/capabilities — كلها عبر الدروز (harness/seams) إلى مصادر
حقيقة 011 كما هي.

- GET /api/harness/roles                 الأدوار الخمسة + الربط الحي
- GET /api/harness/capabilities          الكتالوج الموحد + تصنيف الانتظار
- GET /api/harness/events/vocabulary     المفردة القانونية للأحداث
- GET /api/harness/jobs                  قائمة الوظائف الدائمة
- GET /api/harness/jobs/{job_id}         وظيفة واحدة بتفاصيل انتظارها
- GET /api/projects/{id}/job             أحدث وظيفة للمشروع
- GET /api/projects/{id}/timeline        خط الزمن المرحلي (إسقاط قراءة)
- GET /api/projects/{id}/chain           سلسلة القبول Owner → VERIFIED
"""

from __future__ import annotations

from fastapi import APIRouter

from harness import projections
from workflow import service

router = APIRouter(prefix="/api/harness", tags=["harness"])
projects_router = APIRouter(prefix="/api/projects", tags=["harness"])


def _sessions():
    from api import routes  # noqa: PLC0415 — كسول يمنع الدوران

    return routes._sessions


def _seams():
    from harness.seams import HarnessSeams

    return HarnessSeams(_sessions())


def _manager():
    from harness.jobs import JobManager

    return JobManager(_seams())


@router.get("/roles")
def harness_roles() -> dict:
    """الأدوار الخمسة ككيانات أولى — التعريف + الربط الحي + الجاهزية."""
    from harness.roles_runtime import role_runtime_view

    return {"roles": role_runtime_view(_seams())}


@router.get("/capabilities")
def harness_capabilities() -> dict:
    """الكتالوج الموحد — الحالة من المصدر، التنظيم من الـHarness."""
    from harness.capabilities import capability_catalog

    return {"capabilities": capability_catalog(_seams())}


@router.get("/events/vocabulary")
def harness_event_vocabulary() -> dict:
    """المفردة القانونية — أنواع الوظيفة + خريطة canonical كاملة."""
    from harness.events import CANONICAL_MAP, CHAIN_STAGES, JOB_EVENT_KINDS

    return {
        "job_event_kinds": list(JOB_EVENT_KINDS),
        "canonical_map": CANONICAL_MAP,
        "chain_stages": list(CHAIN_STAGES),
    }


@router.get("/jobs")
def harness_jobs(limit: int = 100) -> dict:
    """قائمة الوظائف الدائمة — الأحدث أولًا."""
    return {"jobs": _manager().list_jobs(limit=min(limit, 200))}


@router.get("/jobs/{job_id}")
def harness_job(job_id: int) -> dict:
    """وظيفة واحدة — تفاصيل الانتظار والنبضة والمؤشرات كاملة."""
    from harness.jobs import JobError

    try:
        return _manager().get_job(job_id)
    except JobError as error:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(error)) from error


@projects_router.get("/{project_id}/job")
def project_job(project_id: int) -> dict:
    """أحدث وظيفة للمشروع — أيا كانت حالتها (404 إن لم توجد)."""
    from fastapi import HTTPException

    if service.get_project(_sessions(), project_id) is None:
        raise HTTPException(status_code=404,
                            detail=f"مشروع غير معروف: {project_id}")
    job = _manager().job_for_project(project_id)
    if job is None:
        raise HTTPException(status_code=404,
                            detail="لا وظيفة بعد — شغّل المشروع أولًا")
    return job


@projects_router.get("/{project_id}/timeline")
def project_timeline(project_id: int, limit: int = 200) -> dict:
    """خط زمن مرحلي — إسقاط قراءة فقط من الأحداث الدائمة."""
    from fastapi import HTTPException

    if service.get_project(_sessions(), project_id) is None:
        raise HTTPException(status_code=404,
                            detail=f"مشروع غير معروف: {project_id}")
    events = service.list_events(
        _sessions(), project_id, limit=min(limit, 500)
    )
    return projections.project_timeline(events)


@projects_router.get("/{project_id}/chain")
def project_chain(project_id: int) -> dict:
    """سلسلة القبول — أين يقف المسار ولماذا توقف (حتمية خالصة)."""
    from fastapi import HTTPException

    if service.get_project(_sessions(), project_id) is None:
        raise HTTPException(status_code=404,
                            detail=f"مشروع غير معروف: {project_id}")
    events = service.list_events(_sessions(), project_id, limit=500)
    return projections.acceptance_chain(events)
