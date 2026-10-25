"""مُطلق سير العمل (الأمر 013 §1-§4) — الاعتماد أمر، لا صف قاعدة.

المشكلة التي يحلها هذا الموديول (013 §1): كان اعتماد الخطة يحدّث
القاعدة ويسجّل OWNER_GATE_RESOLVED ثم ينتهي الطلب — لا انتقال
تشغيلي، لا فحص، لا وظيفة، لا تنفيذ، والواجهة تنتظر refresh وزر
«تشغيل» يدوي. هنا السلسلة الحية المطلوبة:

    Owner يضغط اعتماد
        ↓ (أمر — POST /plan/approve أو /gates/{id})
    validate → OWNER_GATE_RESOLVED → PLAN_APPROVED (دائمة)
        ↓ launch() — هذا الملف
    Coordinator (JobManager) يستقبل الحالة القابلة للتنفيذ
        ↓
    JOB_CREATED → JOB_QUEUED → JOB_STARTED (أحداث دائمة + بث)
        ↓
    tick: PREFLIGHT_STARTED → CAPABILITIES_EVALUATED →
          ENVIRONMENT_CHECK_STARTED → ENVIRONMENT_READY →
          EXECUTION_OPENED → PHASE/STEP/ROLE/TOOL/EVIDENCE …
        ↓
    SSE/التيار الحي → الواجهة تتحدث بلا refresh

الضمانات:
- **single-flight**: حلقة واحدة نشطة في العملية كلها — المصدر
  الوحيد للحقيقة هنا؛ ``api/projects.run/stream`` يمر من هنا أيضًا
  فلا حلقتان على مشروع واحد أبدًا (اختبار الازدواج §40).
- **لا انتظار للعميل**: الإطلاق خلفي في منفّذ مخصص؛ نتيجة الأمر
  فورية (قبل الطابور) والبث يحمل كل ما يحدث لاحقًا.
- **فشل صريح معلن**: كل خطوة خلفية تكتب حدثًا دائمًا عند الفشل —
  لا موت صامت (JOB_FAILED + last_error).
- **نبضة الوظيفة**: الحلقة نفسها من JobManager (012) كما هي —
  هذا الملف إطلاق وتسجيل فقط، لا منطق انتقال جديد.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from core.live_bus import BUS, normalize_event

#: منفّذ الحلقات — حلقة واحدة تعمل في كل لحظة (max_workers=1).
_RUN_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="aes-workflow-run"
)

#: حالة التشغيل النشط — بث لحظي فقط؛ الحقيقة الدائمة في القاعدة.
_ACTIVE: dict = {"handle": None, "lock": threading.Lock()}

#: (013.1 §17) كلب فقدان العامل — خيط خامل لكل قاعدة دائمة؛ يفحص
#: كل 15ث: وظيفة RUNNING بنبضة متقادمة وحلقة حيّة غير موجودة =
#: INTERRUPTED + بث. لا ينفّذ شيئًا أبدًا — الوسم والإعلان فقط،
#: والاستئناف قرار المالك الصريح.
_WATCHDOGS: dict = {"by_db": {}, "lock": threading.Lock()}
_WATCHDOG_INTERVAL_S = 15.0


class RunConflict(RuntimeError):
    """تعارض إطلاق — حلقة أخرى تعمل فعليًا."""


class RunHandle:
    """مقبض تشغيل خلفي — يُعاد فورًا ويمتلئ لاحقًا."""

    __slots__ = ("project_id", "job_id", "done", "error", "correlation_id",
                 "launched_at", "db_key", "superseded")

    def __init__(self, project_id: int, correlation_id: str = "",
                 db_key: str = ""):
        self.project_id = int(project_id)
        self.job_id: int | None = None
        self.done = threading.Event()
        self.error: str = ""
        self.correlation_id = correlation_id
        self.db_key = db_key
        #: (AES-EXP-04 §6) بيئة أعلى أولوية استلمت المنفّذ الوحيد —
        #: الحلقة تسلّمه عند نقطة أمان النبضة التالية (لا قتل في منتصف
        #: عمل؛ الحالة الدائمة باقية والاستئناف قرار صريح).
        self.superseded = threading.Event()

    def describe(self, *, launched: bool, reason: str = "") -> dict:
        return {
            "launched": launched,
            "reason": reason,
            "project_id": self.project_id,
            "job_id": self.job_id,
            "correlation_id": self.correlation_id,
        }


def sessions_db_key(sessions) -> str:
    """هوية القاعدة الدائمة — مفتاح العزل بين بيئات مختلفة.

    الإنتاج: قاعدة واحدة ⟶ مفتاح واحد (سلوك single-flight كما هو).
    الاختبارات: قاعدة لكل اختبار ⟶ لا تعارض هويات المشروع بينها.
    """
    try:
        bind = getattr(sessions, "kw", {}).get("bind")
        if bind is not None:
            return str(getattr(bind, "url", "")) or str(id(sessions))
    except Exception:  # noqa: BLE001
        pass
    return str(id(sessions))


def active_run(sessions=None) -> dict | None:
    """التشغيل النشط الآن — {project_id, job_id, db_key} أو None.

    sessions: قيّد السؤال بقاعدة معينة (الإنتاج يمرر دائمًا).
    """
    with _ACTIVE["lock"]:
        handle = _ACTIVE.get("handle")
        if handle is not None and not handle.done.is_set():
            if sessions is not None and handle.db_key != sessions_db_key(
                    sessions):
                return None
            return {"project_id": handle.project_id,
                    "job_id": handle.job_id,
                    "correlation_id": handle.correlation_id,
                    "db_key": handle.db_key}
    return None


def _broadcast(project_id: int, kind: str, payload: dict,
              event_id: int = 0, *, db_key: str = "") -> None:
    """بث لحظي على تيار المشاريع — الدائمة كتبها المحرك قبلنا.

    event_id: معرف الحدث الدائم (013 §5) — إسقاط المكرر ومصالحة
    Last-Event-ID تعتمد عليه؛ 0 = بث حي بلا دائمة (استثناء معلن).
    db_key: هوية القاعدة — عزل بث بيئة عن أخرى (لا تسريب عبر
    المشتركين مهما تشابكت هويات المشاريع).
    """
    event = normalize_event({
        "project_id": project_id, "kind": kind, "payload": payload,
        "event_id": event_id, "stream": "projects", "db": db_key,
    })
    BUS.publish(event)


def launch(
    project_id: int,
    *,
    engine_factory: Callable,
    sessions,
    reason: str = "قرار المالك",
    correlation_id: str = "",
) -> dict:
    """إطلاق الحلقة خلفيًا — أمر فوري الوصف، بطيء التنفيذ.

    engine_factory:callable(on_event=...) يبني محرك الإنتاج (لا mock).
    sessions: مصنع جلسات القاعدة الدائمة.
    reason: سبب الإطلاق (اعتماد خطة/حل بوابة/تشغيل صريح).
    correlation_id: ربط الطلب بالأحداث الناتجة عنه (§47).

    تعيد {"launched": true/false, reason, job_id?} فورًا — كل التفاصيل
    اللاحقة تصل عبر تيار الأحداث، لا عبر هذه النتيجة.
    """
    db_key = sessions_db_key(sessions)
    with _ACTIVE["lock"]:
        current = _ACTIVE.get("handle")
        if current is not None and not current.done.is_set() \
                and current.db_key == db_key:
            if current.project_id == int(project_id):
                # نفس المشروع يعمل — الأمر منطقي واحد (§40 الازدواج)
                return current.describe(
                    launched=False, reason="already_running"
                )
            raise RunConflict(
                f"مشروع آخر يعمل حاليًا (#{current.project_id}) — "
                "الحلقة الذاتية واحدة في كل لحظة"
            )
        # (AES-EXP-04 §6) بيئة مختلفة (قاعدة أخرى) تستلم المنفّذ الوحيد:
        # حلقة البيئة السابقة يتيمة الآن — نطلب منها التسليم عند نبضتها
        # التالية بدل احتجاز الخيط طوال نافذة توفيرها (120ث). في الإنتاج
        # قاعدة واحدة ⟶ مسار الاستلام لا يحدث أبدًا؛ عزل الاختبارات
        # (قاعدة لكل اختبار) هو المستفيد — ولا مساس بعقد الازدواج §40.
        if (current is not None and not current.done.is_set()
                and current.db_key != db_key):
            current.superseded.set()
        handle = RunHandle(project_id, correlation_id or uuid.uuid4().hex[:12],
                           db_key=db_key)
        _ACTIVE["handle"] = handle

    _ensure_watchdog(sessions)  # (013.1 §17) الكلب خامل من أول إطلاق
    # (013.4 §7) كلب سير العمل: جلسات تخطيط ميتة + وظائف متقادمة
    try:
        from workflow import watchdog as workflow_watchdog

        workflow_watchdog.ensure_watchdog(sessions)
    except Exception:  # noqa: BLE001 — الكلب لا يمنع الإطلاق أبدًا
        pass
    _RUN_EXECUTOR.submit(
        _run_loop_thread, handle, engine_factory, sessions, reason
    )
    return handle.describe(launched=True, reason="launched")


def _run_loop_thread(handle: RunHandle, engine_factory, sessions,
                     reason: str) -> None:
    """جسم التشغيل الخلفي — JobManager فوق المحرك (012 كما هي)."""
    project_id = handle.project_id
    # (013.1 §16) لمس النبضة مع كل حدث — خنقة 5ث: الخطوة الطويلة
    # (LLM + أدوات) تثبت حياتها بالأحداث لا بانتظار انتهاء الـtick
    last_touch = [0.0]

    def on_event(event: dict) -> None:
        now = time.monotonic()
        if handle.job_id is not None and now - last_touch[0] > 5.0:
            last_touch[0] = now
            try:
                from harness.jobs import touch_heartbeat

                touch_heartbeat(sessions, handle.job_id)
            except Exception:  # noqa: BLE001 — اللمس لا يكسر البث
                pass
        _broadcast(
            event.get("project_id", project_id),
            event.get("kind", ""),
            event.get("payload", {}),
            int(event.get("event_id") or 0),
            db_key=handle.db_key,
        )

    try:
        from harness.jobs import JobManager
        from harness.seams import HarnessSeams

        engine = engine_factory(on_event=on_event)
        manager = JobManager(
            HarnessSeams(sessions), engine=engine, on_event=on_event
        )
        job = manager.start_job(project_id, note=reason)
        handle.job_id = job["id"]
        _broadcast(project_id, "run.launched", {
            "job_id": job["id"], "reason": reason,
            "correlation_id": handle.correlation_id,
        })
        manager.run_loop(job["id"], should_yield=handle.superseded.is_set)
    except Exception as error:  # noqa: BLE001 — فشل صريح معلن لا موت صامت
        handle.error = str(error)[:500]
        _broadcast(project_id, "run.error", {
            "project_id": project_id, "error": handle.error,
            "correlation_id": handle.correlation_id, "reason": reason,
        })
    finally:
        handle.done.set()
        with _ACTIVE["lock"]:
            if _ACTIVE.get("handle") is handle:
                _ACTIVE["handle"] = None


def _ensure_watchdog(sessions) -> None:
    """تشغيل كلب فقدان العامل لهذه القاعدة (مرة واحدة لكل قاعدة).

    (013.1 §17) الوظيفة RUNNING بنبضة متقادمة وليست حلقة نشطة في
    هذه العملية = عاملها مفقود ← INTERRUPTED معلن. الحلقة النشطة
    مستثناة حصرًا (تلمس نبضتها مع كل حدث) فلا وسم كاذب أبدًا.
    """
    db_key = sessions_db_key(sessions)
    with _WATCHDOGS["lock"]:
        if db_key in _WATCHDOGS["by_db"]:
            return
        stop_flag = threading.Event()
        _WATCHDOGS["by_db"][db_key] = stop_flag

    def _watch() -> None:
        from harness.jobs import detect_interrupted_jobs

        while not stop_flag.wait(_WATCHDOG_INTERVAL_S):
            try:
                active = active_run(sessions)
                detect_interrupted_jobs(
                    sessions,
                    active_job_ids={active["job_id"]}
                    if active and active.get("job_id") else set(),
                )
            except Exception:  # noqa: BLE001 — الكلب لا يموت بصمت
                continue

    threading.Thread(
        target=_watch, daemon=True,
        name=f"aes-job-watchdog[{db_key[-12:]:}]",
    ).start()


def detect_interrupted_now(sessions) -> list[dict]:
    """كشف فوري (اختبارات/إجراءات صريحة) — نفس منطق الكلب الدوري."""
    from harness.jobs import detect_interrupted_jobs

    active = active_run(sessions)
    return detect_interrupted_jobs(
        sessions,
        active_job_ids={active["job_id"]}
        if active and active.get("job_id") else set(),
    )


__all__ = [
    "RunConflict",
    "RunHandle",
    "active_run",
    "detect_interrupted_now",
    "launch",
    "sessions_db_key",
]
