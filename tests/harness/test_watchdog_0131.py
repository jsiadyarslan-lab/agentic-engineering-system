"""اختبارات كلب فقدان العامل (013.1 §16+§17).

العقد الحرفي من الأمر:
- worker مستقل عن الواجهة: start/heartbeat/checkpoint/resume/
  interrupt/stop — النبضة برهان حياة لا انطباع.
- نبضة مفقودة (عتبة 300ث) بلا حلقة حية = INTERRUPTED معلن +
  المشروع PAUSED بأمان — لا RUNNING كاذبة.
- الاستئناف يعيد الصف نفسه (نفس job id، attempt+1) — ممنوع إنشاء
  وظيفة جديدة بدل القديمة.
- الحلقة النشطة في العملية مستثناة حصرًا — لا وسم كاذب.
"""

from __future__ import annotations

import datetime as _dt
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from harness.jobs import (  # noqa: E402
    JobManager,
    detect_interrupted_jobs,
    heartbeat_age_seconds,
    touch_heartbeat,
)
from harness.seams import HarnessSeams  # noqa: E402


@pytest.fixture()
def jobs_env(tmp_path, monkeypatch):
    """قاعدة معزولة + مشروع حقيقي في القاعدة."""
    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )
    from workflow import service as workflow_service

    monkeypatch.chdir(tmp_path)
    engine = build_engine(tmp_path / "watchdog-0131.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    project = workflow_service.create_project(
        sessions, name="كلب النبضة", objective="هدف اختبار الكلب"
    )
    return {"sessions": sessions, "project_id": project["id"]}


def _make_running_job(env, *, heartbeat_age_s=0.0, status="RUNNING"):
    """وظيفة RUNNING بنبضة بعمر مضبوط — مادة الكلب الحرفية."""
    import sqlalchemy as sa

    from harness.models import EngineeringJob

    sessions = env["sessions"]
    beat = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(
        seconds=heartbeat_age_s
    )
    with sessions() as s:
        row = EngineeringJob(
            project_id=env["project_id"], status=status,
            worker_id="local", attempt=1,
            heartbeat_at=beat, started_at=beat,
        )
        s.add(row)
        s.commit()
        job_id = row.id
    return job_id


# ------------------------------------------------------------------ #
# §16 — النبضة برهان حياة
# ------------------------------------------------------------------ #

def test_touch_heartbeat_refreshes_liveness(jobs_env):
    """لمس النبضة يحدّث heartbeat_at — الحياة أثناء الخطوات الطويلة."""
    sessions = jobs_env["sessions"]
    job_id = _make_running_job(jobs_env, heartbeat_age_s=400)
    touch_heartbeat(sessions, job_id)
    with sessions() as s:
        from harness.models import EngineeringJob

        row = s.get(EngineeringJob, job_id)
        age = heartbeat_age_seconds(row)
    assert age is not None and age < 5, "اللمس لم يحدث النبضة"


# ------------------------------------------------------------------ #
# §17 — فقدان العامل = INTERRUPTED لا RUNNING كاذبة
# ------------------------------------------------------------------ #

def test_stale_job_marked_interrupted(jobs_env):
    """نبضة أقدم من العتبة بلا حلقة حية = INTERRUPTED + حدث دائم
    + المشروع PAUSED — الفقدان معلن لا صمت."""
    sessions = jobs_env["sessions"]
    # المشروع في RUNNING كما في الواقع أثناء عمل الوظيفة (حلقة
    # الوظيفة تدور فقط والمشروع في حالة تشغيل)
    from workflow import service as workflow_service

    workflow_service.update_project(
        sessions, jobs_env["project_id"], status="RUNNING"
    )
    job_id = _make_running_job(jobs_env, heartbeat_age_s=400)
    interrupted = detect_interrupted_jobs(sessions, stale_after_s=300)
    assert [j["job_id"] for j in interrupted] == [job_id]
    assert interrupted[0]["from_status"] == "RUNNING"

    job = JobManager(HarnessSeams(sessions)).get_job(job_id)
    assert job["status"] == "INTERRUPTED"
    assert job["resumable"] is True
    assert "فقدان العامل" in job["last_error"]

    project = workflow_service.get_project(sessions, jobs_env["project_id"])
    assert project["status"] == "PAUSED", (
        "المشروع بقي RUNNING بعد فقدان العامل — حالة كاذبة"
    )

    # حدث دائم JOB_INTERRUPTED مكتوب — الواجهة تصالح المشهد منه
    events = workflow_service.list_events(
        sessions, jobs_env["project_id"], limit=10
    )
    kinds = [e["kind"] for e in events]
    assert "JOB_INTERRUPTED" in kinds


def test_fresh_job_and_waiting_jobs_not_flagged(jobs_env):
    """نبضة طازجة أو حالة انتظار ≠ فقدان عامل — لا وسم كاذب أبدًا."""
    sessions = jobs_env["sessions"]
    _make_running_job(jobs_env, heartbeat_age_s=10)          # طازجة
    _make_running_job(jobs_env, heartbeat_age_s=400,
                      status="WAITING_WORKER")               # انتظار مشروع
    interrupted = detect_interrupted_jobs(sessions, stale_after_s=300)
    assert interrupted == [], "وسم كاذب لوظيفة حية أو منتظرة"


def test_active_loop_excluded_from_watchdog(jobs_env):
    """الحلقة النشطة في هذه العملية مستثناة حصرًا — خطوة طويلة
    ليست فقدان عامل."""
    sessions = jobs_env["sessions"]
    job_id = _make_running_job(jobs_env, heartbeat_age_s=400)
    interrupted = detect_interrupted_jobs(
        sessions, stale_after_s=300, active_job_ids={job_id},
    )
    assert interrupted == [], "الكلب وسم الحلقة الحية — استثناء مكسور"


def test_interrupted_detection_is_idempotent(jobs_env):
    """الكشف مرتين لا يوسم مرتين — الحالة INTERRUPTED ليست هدفًا."""
    sessions = jobs_env["sessions"]
    _make_running_job(jobs_env, heartbeat_age_s=400)
    first = detect_interrupted_jobs(sessions, stale_after_s=300)
    second = detect_interrupted_jobs(sessions, stale_after_s=300)
    assert len(first) == 1 and second == []


# ------------------------------------------------------------------ #
# §17 — الاستئناف نفس الوظيفة لا وظيفة جديدة
# ------------------------------------------------------------------ #

def test_resume_same_job_row_after_interruption(jobs_env):
    """INTERRUPTED ← start_job يعيد الصف نفسه (نفس id، attempt+1)
    — ممنوع إنشاء وظيفة جديدة بدل القديمة (§17 حرفيًا)."""
    sessions = jobs_env["sessions"]
    job_id = _make_running_job(jobs_env, heartbeat_age_s=400)
    detect_interrupted_jobs(sessions, stale_after_s=300)

    manager = JobManager(HarnessSeams(sessions))
    resumed = manager.start_job(jobs_env["project_id"],
                                note="استئناف بعد فقدان العامل")
    assert resumed["id"] == job_id, (
        f"استؤنفت وظيفة جديدة #{resumed['id']} بدل #{job_id} — "
        "انتهاك §17: ممنوع إنشاء Job جديد"
    )
    assert resumed["status"] == "QUEUED"
