"""مدير الوظائف الهندسية (012-E+F+G) — الحلقة الدائمة كوظيفة قابلة
للملاحظة والانقطاع والاستئناف.

البنية (فوق 011 لا مكانه):

```
API run/stream
   └── JobManager.run_loop(job_id)      ← هذا الملف
         ├── engine.tick(project_id)    ← آلة حالة 011 كما هي
         ├── coordinator.classify_tick  ← حتمي خالص (لا LLM)
         ├── صف engineering_jobs        ← نبضة/مؤشرات/انتظار صادق
         └── أحداث JOB_*                ← عبر الدرة إلى كل المستهلكين
```

الضمانات:
- **نبضة**: كل tick يحدّث heartbeat_at — حياة الحلقة برهان لا
  انطباع؛ وفاة العملية تُكتشف عند الإقلاع (INTERRUPTED) لا
  بمؤقت صامت.
- **توقف صادق**: كل توقف يحمل نوعه (CAPABILITY/WORKER/GATE)
  وتفصيله الحرفي ومسار رفعه — لا «محجوب» عائمة أبدًا.
- **استئناف من آخر checkpoint**: التشغيل بعد انتظار يعيد الصف
  غير النهائي نفسه — الخطة لم تتغير فلا إعادة اعتماد (011 §19).
- **لا تنفيذ عشوائي عند الإقلاع**: assess_jobs_recovery تُقيّم
  وتُعلن، والاستئناف قرار صريح دائمًا.
"""

from __future__ import annotations

import datetime as _dt
import threading
import time
import uuid
from typing import Any, Callable

from harness import coordinator
from harness.models import EngineeringJob, JOB_NON_TERMINAL, JOB_TERMINAL
from harness.seams import HarnessSeams

#: سقف النبضات الافتراضي لكل run_loop — سخي بلا لانهائية.
DEFAULT_MAX_TICKS = 200

#: (§6 AES-EXP-04) حد نبضات الحجب بالفحص المسبق بلا أي تقدم — بعده
#: تُنهى الوظيفة بفشل صادق (لا حلقة إعادة فحص مفتوحة تحجز خيط
#: الحلقات الوحيد). القيمة توازن حالتين: انتظار المالك للتوفير يبقى
#: مستقرًا دقائق (خنق إعادة الفحص 5ث يجعل كلفة النبضة زهيدة)،
#: والتحرر المؤكد لخيط الحلقات ضمن نافذة معقولة. قابل للضبط عبر
#: AES_PREFLIGHT_RECHECK_LIMIT.
DEFAULT_PREFLIGHT_RECHECK_LIMIT = 60


def preflight_recheck_limit() -> int:
    """حد نبضات الحجب بالفحص المسبق — AES_PREFLIGHT_RECHECK_LIMIT."""
    import os

    raw = os.environ.get("AES_PREFLIGHT_RECHECK_LIMIT", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PREFLIGHT_RECHECK_LIMIT
    return value if value > 0 else DEFAULT_PREFLIGHT_RECHECK_LIMIT

_RETRY_KIND = "RETRY_REQUESTED"
_CHECKPOINT_KIND = "CHECKPOINT_CREATED"

#: (013.1 §16-§17) عتبة تقادم النبضة — وظيفة RUNNING بلا نبضة/حدث
#: خلال هذه المدة وعامل حيّ غير موجود = عامل مفقود ← INTERRUPTED.
#: سخية عمدًا: خطوة طويلة (LLM + أدوات) تلمس النبضة مع كل حدث،
#: فالصمت الحقيقي هنا فقدان عامل لا تفكيرًا طويلًا.
STALE_HEARTBEAT_S = 300.0


def new_resume_token() -> str:
    """رمز استئناف غير قابل للتخمين — هوية استرداد الوظيفة (§19)."""
    return "rsm-" + uuid.uuid4().hex[:16]


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    return str(value)


def _job_dict(row: EngineeringJob, *, include_waiting: bool = True) -> dict:
    out = {
        "id": row.id,
        "project_id": row.project_id,
        "status": row.status,
        "waiting_kind": row.waiting_kind,
        "current_phase_id": row.current_phase_id,
        "current_step_id": row.current_step_id,
        "current_execution_id": row.current_execution_id,
        "current_role": row.current_role,
        "checkpoint_id": row.checkpoint_id,
        "tick_count": row.tick_count,
        "retries": row.retries,
        "checkpoints": row.checkpoints,
        "worker_id": row.worker_id,
        "attempt": row.attempt,
        "last_event_id": row.last_event_id,
        "resume_token": row.resume_token,
        "heartbeat_at": _iso(row.heartbeat_at),
        "heartbeat_age_s": heartbeat_age_seconds(row),
        "resumable": bool(row.resumable),
        "last_error": row.last_error,
        "note": row.note,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "last_tick": _last_tick_dict(row),
    }
    if include_waiting:
        out["waiting_detail"] = row.waiting_detail_dict
        out["unblock_path"] = coordinator.waiting_unblock_path(
            row.waiting_kind
        )
    return out


def _last_tick_dict(row: EngineeringJob) -> dict:
    import json

    try:
        return json.loads(row.last_tick or "{}")
    except (TypeError, ValueError):
        return {}


def heartbeat_age_seconds(row: EngineeringJob) -> float | None:
    """عمر النبضة بالثواني — None إن لم تنبض بعد."""
    if row.heartbeat_at is None:
        return None
    now = _utc_now()
    beat = row.heartbeat_at
    if beat.tzinfo is None:
        beat = beat.replace(tzinfo=_dt.timezone.utc)
    return max(0.0, (now - beat).total_seconds())


def touch_heartbeat(sessions, job_id: int) -> None:
    """لمس نبضة الوظيفة (013.1 §16) — حياة أثناء الخطوات الطويلة.

    تُستدعى خنقةً (throttled) مع كل حدث يبثه المحرك أثناء tick:
    الخطوة قد تستغرق دقائق (LLM + أدوات) والحدث هو برهان التقدم —
    فالنبضة تتبع التقدم الفعلي لا دورة الـtick وحدها.
    """
    with sessions() as session:
        row = session.get(EngineeringJob, int(job_id))
        if row is None:
            return
        row.heartbeat_at = _utc_now()
        session.commit()


def detect_interrupted_jobs(
    sessions, *, stale_after_s: float = STALE_HEARTBEAT_S,
    active_job_ids: set[int] | None = None,
) -> list[dict]:
    """كاشف فقدان العامل (013.1 §17) — نبضة مفقودة = INTERRUPTED.

    وظيفة RUNNING/RETRYING/REVISING بنبضة أقدم من ``stale_after_s``
    وليست ضمن ``active_job_ids`` (حلقة حيّة في هذه العملية) =
    عاملها مات/توقف دون إقفال صادق ← تُوسم INTERRUPTED مع السبب
    وحدث دائم JOB_INTERRUPTED، ويُدفع المشروع إلى PAUSED بأمان
    (استئنافه من آخر checkpoint بقرار صريح — لا تنفيذ عشوائي).

    تعيد قائمة الوظائف الموسومة — فارغة = لا فقدان عامل.
    """
    from workflow import service as workflow_service

    active = active_job_ids or set()
    interrupted: list[dict] = []
    with sessions() as session:
        rows = session.query(EngineeringJob).filter(
            EngineeringJob.status.in_(("RUNNING", "RETRYING", "REVISING"))
        ).all()
        stale = [
            row for row in rows
            if row.id not in active
            and (heartbeat_age_seconds(row) or 0.0) > stale_after_s
        ]
    for row in stale:
        age = int(heartbeat_age_seconds(row) or 0)
        reason = (
            f"فقدان العامل: لا نبضة منذ {age}ث (العتبة "
            f"{int(stale_after_s)}ث) — وُسمت INTERRUPTED؛ الاستئناف من "
            "آخر checkpoint بقرار صريح"
        )
        with sessions() as session:
            fresh = session.get(EngineeringJob, row.id)
            if fresh is None or fresh.status not in (
                    "RUNNING", "RETRYING", "REVISING"):
                continue  # حلقتها عادت للحياة أو أُقفلت — لا نكذب عليها
            fresh.status = "INTERRUPTED"
            fresh.last_error = reason[:800]
            fresh.resumable = True
            fresh.updated_at = _utc_now()
            session.commit()
        project = workflow_service.get_project(sessions, row.project_id)
        if project is not None and project.get("status") == "RUNNING":
            workflow_service.update_project(
                sessions, row.project_id, status="PAUSED"
            )
        # حدث دائم — الواجهة ترى JOB_INTERRUPTED فتصالح المشهد
        try:
            from harness.seams import HarnessSeams

            seams = HarnessSeams(sessions)
            seams.add_event(row.project_id, "JOB_INTERRUPTED", {
                "job_id": row.id, "reason": reason,
                "heartbeat_age_s": age, "worker_id": row.worker_id,
                "attempt": row.attempt,
            })
        except Exception:  # noqa: BLE001 — الحدث لا يمنع الوسم
            pass
        try:
            from core.live_bus import BUS, normalize_event

            BUS.publish(normalize_event({
                "project_id": row.project_id, "kind": "JOB_INTERRUPTED",
                "payload": {"job_id": row.id, "reason": reason,
                            "heartbeat_age_s": age},
                "event_id": 0, "stream": "projects", "db": "",
            }))
        except Exception:  # noqa: BLE001
            pass
        interrupted.append({
            "job_id": row.id, "project_id": row.project_id,
            "from_status": row.status, "status": "INTERRUPTED",
            "heartbeat_age_s": age, "reason": reason,
        })
    return interrupted


class JobError(RuntimeError):
    """خطأ وظيفة صريح — يسمي الوظيفة والسبب."""


class JobManager:
    """إدارة الوظائف الدائمة — كل حالة من القاعدة وإليها."""

    def __init__(self, seams: HarnessSeams, *, engine: Any = None,
                 on_event: Callable[[dict], None] | None = None,
                 max_ticks: int = DEFAULT_MAX_TICKS):
        """``engine=None`` لمدير دفاتر فقط (ربط قرارات المالك/
        الاسترداد) — ``run_loop`` يرفض العمل بدونه صراحة."""
        self._seams = seams
        self._engine = engine
        self._on_event = on_event
        self._max_ticks = max(1, int(max_ticks))
        self._loop_lock = threading.Lock()
        self._active_job_id: int | None = None

    # ------------------------------------------------------------------ #
    # الأحداث — دائمة + بث لحظي (نفس مسار أحداث المشروع)
    # ------------------------------------------------------------------ #

    def _emit(self, project_id: int, kind: str, payload: dict) -> None:
        event_id = self._seams.add_event(project_id, kind, payload)
        if self._on_event is not None:
            try:
                self._on_event({
                    "project_id": project_id, "kind": kind,
                    "payload": payload, "event_id": event_id,
                })
            except Exception:  # noqa: BLE001 — المستقبِل لا يكسر الحلقة
                pass

    # ------------------------------------------------------------------ #
    # العمليات العليا
    # ------------------------------------------------------------------ #

    def start_job(self, project_id: int, *, note: str = "") -> dict:
        """إطلاق تشغيل — صف غير نهائي يُعاد استخدامه، وإلا صف جديد.

        الاستمرارية هي القصة: الوظيفة المنتظرة (توفيرًا كان أو
        قرارًا) تُستأنف في صفها نفسه فيبقى خطها الزمني متصلًا
        («توقف بأمان ← استؤنف من آخر checkpoint»). الحالة النهائية
        وحدها تفتح صفًّا جديدًا (تشغيل جديد بعد اكتمال/فشل).
        """
        project = self._seams.get_project(project_id)
        if project is None:
            raise JobError(f"مشروع غير معروف: {project_id}")
        if project["status"] in ("VERIFIED", "STOPPED"):
            raise JobError(
                f"المشروع في حالة نهائية ({project['status']}) — "
                "لا إطلاق وظيفة"
            )
        row = self._latest_non_terminal(project_id)
        resumed = row is not None
        if row is None:
            with self._seams.sessions() as session:
                row = EngineeringJob(
                    project_id=project_id, status="QUEUED",
                    note=note, attempt=0,
                    worker_id="local", resume_token=new_resume_token(),
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                job_id = row.id
            # (013 §4+§19) ولادة الصف حدث دائم قبل الطابور — الوظيفة
            # لا تولد بصمت أبدًا؛ الرمز والمحاولة جزء من الهوية
            self._emit(project_id, "JOB_CREATED", {
                "job_id": job_id, "note": note,
                "resume_token": row.resume_token, "attempt": 0,
            })
        else:
            job_id = row.id
            if not coordinator.can_transition(row.status, "QUEUED"):
                raise JobError(
                    f"الوظيفة #{job_id} في حالة {row.status} لا تقبل "
                    "الطابور — راجع حالتها"
                )
            self._write(job_id, status="QUEUED", waiting_kind="",
                        waiting_detail="{}", note=note, last_error="")
        self._emit(project_id, "JOB_QUEUED", {
            "job_id": job_id, "resumed": resumed,
            "note": note,
        })
        return self.get_job(job_id)

    def run_loop(self, job_id: int) -> dict:
        """حلقة النبضات — tick واحدًا تلو الآخر مع دفتر الوظيفة.

        كل دورة: tick المحرك (كل الحالة من القاعدة) ← تصنيف حتمي ←
        تحديث الصف (نبضة/مؤشرات/انتظار) ← حدث عند كل انتقال. توقف
        الحلقة عند أي انتظار أو حالة نهائية — والاستئناف قرار صريح.
        """
        with self._loop_lock:
            self._active_job_id = int(job_id)
            try:
                return self._run_loop_locked(job_id)
            finally:
                self._active_job_id = None

    def _run_loop_locked(self, job_id: int) -> dict:
        import json

        from workflow import service

        if self._engine is None:
            raise JobError(
                "run_loop يتطلب محركًا — هذا المدير للدفاتر فقط"
            )
        row = self._row(job_id)
        project_id = row.project_id
        sessions = self._seams.sessions
        self._write(job_id, status="RUNNING", heartbeat_at=_utc_now(),
                    started_at=row.started_at or _utc_now(),
                    last_error="", worker_id=row.worker_id or "local",
                    attempt=(row.attempt or 0) + 1)
        self._emit(project_id, "JOB_STARTED", {
            "job_id": job_id,
            "attempt": (row.attempt or 0) + 1,
            "worker_id": row.worker_id or "local",
        })

        last_tick: dict = {}
        ticks = 0
        preflight_blocked_ticks = 0
        last_event_id = self._last_event_id(project_id)
        prev_status = "RUNNING"
        try:
            while ticks < self._max_ticks:
                tick_result = self._engine.tick(project_id)
                ticks += 1
                # أحداث هذه النبضة (للإعادات ونقاط الحفظ الصادقة)
                new_events = self._events_after(project_id,
                                                last_event_id)
                last_event_id = max(
                    [last_event_id]
                    + [e.get("id", 0) for e in new_events]
                ) if new_events else last_event_id
                retry_requested = any(
                    e.get("kind") == _RETRY_KIND for e in new_events
                )
                new_checkpoints = sum(
                    1 for e in new_events
                    if e.get("kind") == _CHECKPOINT_KIND
                )

                project = self._seams.get_project(project_id) or {}
                open_gates = self._seams.open_gates(project_id)
                execution = self._current_execution(project)
                classification = coordinator.classify_tick(
                    tick_result, project=project, open_gates=open_gates,
                    retry_requested=retry_requested,
                )

                # (013.7 §P15) إضافة تأخير قصير عند حجب الفحص المسبق لتجنب استهلاك CPU
                if classification.get("waiting_kind") in ("WORKER", "CAPABILITY") \
                        and tick_result.get("blocked_kind") == "preflight":
                    time.sleep(0.5)

                # (§6 AES-EXP-04) المهمة المحجوبة بالفحص المسبق تنهي نفسها
                # بعد حد معلن بلا أي تقدم — كل إعادة فحص كانت تعيد المسبارات
                # وتحجز خيط الحلقات الوحيد؛ الفشل صادق مسمّى والإجراء للمالك
                if tick_result.get("blocked_kind") == "preflight":
                    preflight_blocked_ticks += 1
                else:
                    preflight_blocked_ticks = 0
                if preflight_blocked_ticks >= preflight_recheck_limit():
                    reason = (
                        "الفحص المسبق محجوب بقدرات غير جاهزة بعد "
                        f"{preflight_blocked_ticks} نبضات بلا تقدم — "
                        "الإجراء: جهّز القدرات المحجوبة (المصفوفة في أحداث "
                        "PREFLIGHT_BLOCKED) ثم أعد تشغيل المشروع"
                    )
                    self._write(job_id, status="FAILED",
                                last_error=reason[:800],
                                finished_at=_utc_now())
                    self._emit(project_id, "JOB_FAILED", {
                        "job_id": job_id, "error": reason,
                    })
                    self._finish(job_id, "FAILED", note=reason)
                    break

                checkpoint = service.latest_checkpoint(
                    sessions, project_id
                )
                new_status = classification["status"]
                if not coordinator.can_transition(prev_status,
                                                  new_status):
                    # انتقال خارج الجدول — لا نكذب بتطبيقه؛ يُعلن
                    # ويُحفظ للتشخيص، والحالة تبقى كما هي.
                    self._append_note(
                        job_id,
                        f"انتقال مرفوض {prev_status}→{new_status} "
                        f"عند tick {ticks}",
                    )
                    new_status = prev_status
                self._write(
                    job_id,
                    status=new_status,
                    waiting_kind=classification["waiting_kind"],
                    waiting_detail=json.dumps(
                        classification["waiting_detail"],
                        ensure_ascii=False,
                    ),
                    current_phase_id=project.get("current_phase_id"),
                    current_step_id=project.get("current_step_id"),
                    current_execution_id=(
                        execution or {}).get("id"),
                    current_role=coordinator.current_role_of(
                        project, execution
                    ),
                    checkpoint_id=(checkpoint or {}).get("id"),
                    tick_count=ticks,
                    heartbeat_at=_utc_now(),
                    last_tick=json.dumps({
                        "action": tick_result.get("action", ""),
                        "reason": (tick_result.get("reason") or "")[:200],
                        "at": _utc_now().isoformat(),
                    }, ensure_ascii=False),
                    last_event_id=last_event_id,
                )
                if retry_requested:
                    self._increment(job_id, "retries", 1)
                # (AES-EXP-04 §14) الاستئناف الآلي من انتظار بوابة/قدرة/
                # عامل = محاولة جديدة على نفس صف الوظيفة — نفس دلالة
                # استئناف المالك (mark_resumed) لا صفّ جديد ولا محاولة
                # كاذبة تبقى 1.
                if (prev_status in ("WAITING_CAPABILITY", "WAITING_WORKER",
                                    "WAITING_GATE")
                        and new_status == "RUNNING"):
                    self._increment(job_id, "attempt", 1)
                if new_checkpoints:
                    self._increment(job_id, "checkpoints",
                                    new_checkpoints)

                if new_status != prev_status:
                    self._emit_transition(
                        project_id, job_id, new_status,
                        classification,
                    )
                prev_status = new_status
                last_tick = tick_result
                if classification["terminal"]:
                    self._finish(job_id, new_status,
                                 note="حالة نهائية للمشروع")
                    break
                if classification["stop"]:
                    break
        except Exception as error:  # noqa: BLE001 — فشل صريح معلن
            self._write(job_id, status="FAILED",
                        last_error=str(error)[:800],
                        finished_at=_utc_now())
            self._emit(project_id, "JOB_FAILED", {
                "job_id": job_id, "error": str(error)[:400],
            })
            raise

        job = self.get_job(job_id)
        last_tick = dict(last_tick)
        last_tick["ticks"] = ticks
        last_tick["job_id"] = job_id
        last_tick["job_status"] = job["status"]
        return last_tick

    # ------------------------------------------------------------------ #
    # ربط قرارات المالك — الوظيفة تتبع المشروع بلا تخلف
    # ------------------------------------------------------------------ #

    def mark_verified(self, project_id: int) -> dict | None:
        """تحقق المالك — القناة الوحيدة إلى COMPLETED للوظيفة."""
        row = self._latest_non_terminal(project_id)
        if row is None:
            return None
        self._transition(row, "COMPLETED",
                         note="تحقق المالك — VERIFIED")
        return self.get_job(row.id)

    def mark_stopped(self, project_id: int) -> dict | None:
        """إيقاف نهائي بقرار مالك (رفض بوابة) — الوظيفة تُغلق صادقة."""
        row = self._latest_non_terminal(project_id)
        if row is None:
            return None
        self._transition(row, "STOPPED", note="إيقاف بقرار المالك")
        return self.get_job(row.id)

    def mark_resumed(self, project_id: int) -> dict | None:
        """استئناف صريح — الصف غير النهائي يعود للطابور (لا صف جديد)."""
        row = self._latest_non_terminal(project_id)
        if row is None:
            return None
        self._transition(row, "QUEUED", note="استئناف صريح من المالك")
        return self.get_job(row.id)

    # ------------------------------------------------------------------ #
    # الاسترداد عند الإقلاع (012-G) — تقييم معلن لا تنفيذ عشوائي
    # ------------------------------------------------------------------ #

    def assess_jobs_recovery(self) -> list[dict]:
        """فحص الوظائف عند الإقلاع — وفاة العملية لا تبقى RUNNING.

        RUNNING/RETRYING/REVISING عند الإقلاع = حلقتها ماتت مع
        العملية ← INTERRUPTED (لا حياة كاذبة). الانتظارات والإيقاف
        تبقى كما هي — لا شيء ضاع. لكل وظيفة: قابلية الاستئناف من
        الحالة الدائمة (بوابات القرار وحدها تمنع — 011 §19).
        """
        from workflow import service

        assessments = []
        with self._seams.sessions() as session:
            rows = session.query(EngineeringJob).filter(
                EngineeringJob.status.in_(JOB_NON_TERMINAL)
            ).all()

        for row in rows:
            project = self._seams.get_project(row.project_id) or {}
            gates = self._seams.open_gates(row.project_id)
            decision_gates = [g for g in gates if g["status"] == "PENDING"]
            from_status = row.status
            reason = ""
            if from_status in ("RUNNING", "RETRYING", "REVISING"):
                # الحلقة ماتت مع العملية — لا خيط حي ممكن
                self._write(row.id, status="INTERRUPTED",
                            note="انقطعت بوفاة العملية عند الإقلاع")
                reason = "كانت الحلقة تدور عند توقف العملية"
            else:
                reason = f"حالة {from_status} سليمة — لا شيء ضاع"

            project_status = project.get("status", "")
            resumable = (
                project_status not in ("VERIFIED", "STOPPED",
                                       "ESCALATED", "COMPLETED")
                and not decision_gates
            )
            self._write(row.id, resumable=resumable)
            assessment = {
                "job_id": row.id,
                "project_id": row.project_id,
                "from_status": from_status,
                "status": "INTERRUPTED" if from_status in (
                    "RUNNING", "RETRYING", "REVISING"
                ) else from_status,
                "resumable": resumable,
                "recommendation": (
                    "RESUMABLE" if resumable else "OWNER_DECISION"
                ),
                "reason": reason,
                "project_status": project_status,
                "open_gates": [g["kind"] for g in gates],
                "checkpoint": (service.latest_checkpoint(
                    self._seams.sessions, row.project_id
                ) or {}).get("id"),
            }
            self._emit(row.project_id, "JOB_RECOVERY_ASSESSED",
                       assessment)
            assessments.append(assessment)
        return assessments

    # ------------------------------------------------------------------ #
    # القراءة — قوائم وتفاصيل
    # ------------------------------------------------------------------ #

    def get_job(self, job_id: int) -> dict:
        row = self._row(job_id)
        return _job_dict(row)

    def job_for_project(self, project_id: int) -> dict | None:
        """أحدث وظيفة للمشروع — أيا كانت حالتها (التاريخ كله)."""
        with self._seams.sessions() as session:
            row = session.query(EngineeringJob).filter(
                EngineeringJob.project_id == int(project_id)
            ).order_by(EngineeringJob.id.desc()).first()
            return _job_dict(row) if row is not None else None

    def list_jobs(self, *, limit: int = 100) -> list[dict]:
        with self._seams.sessions() as session:
            rows = session.query(EngineeringJob).order_by(
                EngineeringJob.id.desc()
            ).limit(int(limit)).all()
            return [_job_dict(r) for r in rows]

    def active_job(self) -> dict | None:
        """الوظيفة التي تدور حلقتها الآن (بث لحظي فقط)."""
        if self._active_job_id is None:
            return None
        try:
            return self.get_job(self._active_job_id)
        except JobError:
            return None

    # ------------------------------------------------------------------ #
    # أدوات داخلية
    # ------------------------------------------------------------------ #

    def _row(self, job_id: int) -> EngineeringJob:
        with self._seams.sessions() as session:
            row = session.get(EngineeringJob, int(job_id))
            if row is None:
                raise JobError(f"وظيفة غير معروفة: {job_id}")
            session.refresh(row)
            return row

    def _latest_non_terminal(self, project_id: int) -> EngineeringJob | None:
        with self._seams.sessions() as session:
            return session.query(EngineeringJob).filter(
                EngineeringJob.project_id == int(project_id),
                EngineeringJob.status.in_(JOB_NON_TERMINAL),
            ).order_by(EngineeringJob.id.desc()).first()

    def _write(self, job_id: int, **fields) -> None:
        with self._seams.sessions() as session:
            row = session.get(EngineeringJob, int(job_id))
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            session.commit()

    def _increment(self, job_id: int, field: str, by: int) -> None:
        with self._seams.sessions() as session:
            row = session.get(EngineeringJob, int(job_id))
            if row is None:
                return
            setattr(row, field, (getattr(row, field) or 0) + int(by))
            session.commit()

    def _append_note(self, job_id: int, text: str) -> None:
        with self._seams.sessions() as session:
            row = session.get(EngineeringJob, int(job_id))
            if row is None:
                return
            row.note = ((row.note or "") + "؛ " + text)[-1000:]
            session.commit()

    def _finish(self, job_id: int, status: str, *, note: str = "") -> None:
        self._write(job_id, status=status, finished_at=_utc_now(),
                    note=note)

    def _transition(self, row: EngineeringJob, target: str, *,
                    note: str = "") -> None:
        if not coordinator.can_transition(row.status, target):
            raise JobError(
                f"انتقال مرفوض للوظيفة #{row.id}: "
                f"{row.status} → {target}"
            )
        self._write(row.id, status=target, waiting_kind="",
                    waiting_detail="{}", finished_at=(
                        _utc_now() if target in JOB_TERMINAL else None
                    ), note=note)
        event_kind = {
            "COMPLETED": "JOB_COMPLETED", "STOPPED": "JOB_STOPPED",
            "QUEUED": "JOB_RESUMED",
        }.get(target)
        if event_kind:
            self._emit(row.project_id, event_kind, {
                "job_id": row.id, "note": note,
            })

    def _emit_transition(self, project_id: int, job_id: int,
                         status: str, classification: dict) -> None:
        """حدث انتقال الوظيفة — الانتظار يحمل نوعه ومسار رفعه."""
        payload: dict = {"job_id": job_id, "status": status}
        if status.startswith("WAITING_"):
            payload.update({
                "waiting_kind": classification["waiting_kind"],
                "detail": classification["waiting_detail"],
                "unblock_path": coordinator.waiting_unblock_path(
                    classification["waiting_kind"]
                ),
            })
            self._emit(project_id, "JOB_WAITING", payload)
            return
        kind = {
            "RETRYING": "JOB_RETRYING", "REVISING": "JOB_REVISING",
            "PAUSED": "JOB_PAUSED", "COMPLETED": "JOB_COMPLETED",
            "FAILED": "JOB_FAILED", "STOPPED": "JOB_STOPPED",
            "ESCALATED": "JOB_ESCALATED",
            "RUNNING": None,
        }.get(status)
        if kind:
            self._emit(project_id, kind, payload)

    def _events_after(self, project_id: int,
                      after_id: int) -> list[dict]:
        events = self._seams.list_events(project_id, limit=500)
        return [e for e in events
                if (e.get("id") or 0) > int(after_id)]

    def _last_event_id(self, project_id: int) -> int:
        events = self._seams.list_events(project_id, limit=500)
        return max((e.get("id") or 0) for e in events) if events else 0

    def _current_execution(self, project: dict) -> dict | None:
        """التنفيذ الجاري من الحالة الدائمة — لا تخمين."""
        from workflow import service

        step_id = project.get("current_step_id")
        if not step_id:
            return None
        step = service.get_step(self._seams.sessions, step_id)
        if step is None:
            return None
        execution_id = step.get("current_execution_id")
        if not execution_id:
            return None
        with self._seams.sessions() as session:
            from workflow.models import Execution

            row = session.get(Execution, int(execution_id))
            if row is None:
                return None
            return {
                "id": row.id, "status": row.status,
                "agent_role": row.agent_role,
            }


__all__ = [
    "DEFAULT_MAX_TICKS",
    "JobError",
    "JobManager",
    "heartbeat_age_seconds",
]
