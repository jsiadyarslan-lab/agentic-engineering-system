"""كلب سير العمل الدائم (013.4 §7 + 013.5 §C/§Q) — لا حلقة معلقة بلا وسم صادق.

يكتشف ويوسم فقط — لا يزوّر اكتمالًا أبدًا ولا ينفّذ عملًا:

1. **جلسات تخطيط غير سليمة**: GENERATING تجاوزت سقف زمن الجدار
   (MODEL_TIMEOUT)، أو انتهى إيجارها المحسوب من **النشاط الحقيقي**
   (INTERRUPTED إن ماتت العملية، MODEL_TIMEOUT إن كان الخيط حيًّا
   لكن المزود صامت) — لا PLANNING أبديًا (جذر عطل §0 و013.5 §C).
2. **حارس الثبات** (013.5 §C): كل مشروع في PLANNING بلا جلسة توليد
   صالحة يُعاد إلى DRAFT بسبب صريح — الشرط الصريح لفشل قبول 013.5.
3. **وظائف متقادمة**: كشف 013.1 (detect_interrupted_jobs) كما هو —
   الوظيفة RUNNING بنبضة متقادمة بلا حلقة حية = INTERRUPTED.

التشخيص (DIAGNOSE) يكتب حدث WORKFLOW_DIAGNOSED بتصنيف وقرار:
RETRY (الجلسة القابلة للإعادة أُعيدت آليًا بالفعل) أو
OWNER_ACTION_REQUIRED (قرار المالك الصريح). «استعادة أو حجب
بأمانة» — لا مسار ثالث يخترع نجاحًا.

(013.5 §C.4) **يُشغَّل عند إقلاع التطبيق** لا عند إطلاق حلقة تنفيذ
فقط: هذا بالضبط ما جعل مشروعًا مات مولّده يبقى PLANNING 17992ث.
"""

from __future__ import annotations

import threading

from workflow import service

#: فترة الكلب — كل 15ث مثل كلب الوظائف (013.1 §17).
WATCHDOG_INTERVAL_S = 15.0

_WATCHDOGS: dict[str, threading.Event] = {}
_WATCHDOG_LOCK = threading.Lock()


def diagnose_once(sessions, *, active_job_ids: set[int] | None = None) -> list[dict]:
    """مسحة تشخيص واحدة — تُستدعى دوريًا وعند الطلب (الاختبارات).

    يعيد قائمة التشخيصات [{project_id, kind, decision, detail}] —
    كل تشخيص يقابله حدث دائم WORKFLOW_DIAGNOSED على مشروعه.
    """
    from harness.jobs import detect_interrupted_jobs
    from workflow import planning_runtime

    diagnoses: list[dict] = []

    # 1) جلسات التخطيط غير السليمة — مهلة صلبة أو إيجار نشاط منتهٍ
    active = active_job_ids or set()
    swept = planning_runtime.sweep_stale_sessions(
        sessions, active_project_ids=set()
    )
    for session in swept:
        verdict = session.get("verdict") or {}
        diagnosis = {
            "project_id": session["project_id"],
            "kind": "PLANNING_LEASE_EXPIRED",
            "session_id": session["id"],
            "decision": "OWNER_ACTION_REQUIRED",
            "detail": verdict.get("reason")
            or ("انتهى إيجار جلسة التخطيط بلا نبضة — وُسمت "
                "INTERRUPTED والمشروع أعيد DRAFT بخطأ صريح. "
                "أعد المحاولة من زر الإعادة."),
            "error_class": verdict.get("error_class")
            or "PLANNING_INTERRUPTED",
            "session_state": verdict.get("state"),
            "hard_deadline_at": session.get("hard_deadline_at"),
            "last_meaningful_activity_at": session.get(
                "last_meaningful_activity_at"),
        }
        diagnoses.append(diagnosis)

    # 1.b) (013.5 §C) حارس الثبات — PLANNING بلا مولِّد صالح
    for healed in planning_runtime.enforce_invariant(sessions):
        diagnoses.append({
            "project_id": healed["project_id"],
            "kind": "PLANNING_INVARIANT_HEALED",
            "session_id": healed.get("session_id"),
            "decision": "OWNER_ACTION_REQUIRED",
            "detail": healed["reason"],
            "error_class": "PLANNING_INTERRUPTED",
        })

    # 2) الوظائف المتقادمة — نفس كشف 013.1 (وسم لا تنفيذ)
    try:
        interrupted = detect_interrupted_jobs(
            sessions, active_job_ids=active
        )
    except Exception:  # noqa: BLE001 — الكلب لا يموت بصمت
        interrupted = []
    for job in interrupted:
        diagnoses.append({
            "project_id": job.get("project_id"),
            "kind": "JOB_HEARTBEAT_STALE",
            "job_id": job.get("job_id"),
            "decision": "OWNER_ACTION_REQUIRED",
            "detail": "نبضة الوظيفة متقادمة وليست حلقة نشطة — "
                      "وُسمت INTERRUPTED؛ الاستئناف قرار صريح.",
            "error_class": "JOB_INTERRUPTED",
        })

    # كل تشخيص حدث دائم على مشروعه (013.4 §7: DIAGNOSE معلن)
    for diagnosis in diagnoses:
        project_id = diagnosis.get("project_id")
        if project_id is None:
            continue
        service.add_event(
            sessions, int(project_id), "WORKFLOW_DIAGNOSED", diagnosis
        )
    return diagnoses


def ensure_watchdog(sessions) -> None:
    """تشغيل كلب سير العمل لهذه القاعدة (مرة واحدة) — خامل دائمًا."""
    from workflow.runner import sessions_db_key

    db_key = sessions_db_key(sessions)
    with _WATCHDOG_LOCK:
        if db_key in _WATCHDOGS:
            return
        stop_flag = threading.Event()
        _WATCHDOGS[db_key] = stop_flag

    def _watch() -> None:
        while not stop_flag.wait(WATCHDOG_INTERVAL_S):
            try:
                diagnose_once(sessions)
            except Exception:  # noqa: BLE001 — الكلب لا يموت بصمت
                continue

    threading.Thread(
        target=_watch, daemon=True,
        name=f"aes-workflow-watchdog[{db_key[-12:]:}]",
    ).start()


def start_at_boot(sessions) -> dict:
    """(013.5 §C.4) إقلاع صادق: استرداد فوري ثم كلب دائم.

    يُستدعى من lifespan التطبيق — قبل خدمة أي طلب. يعيد ملخّص ما
    استُرد حتى يُسجَّل في السجل ولا يمرّ صامتًا.
    """
    from workflow import planning_runtime

    recovery = {}
    try:
        recovery = planning_runtime.recover_at_startup(sessions)
    except Exception as error:  # noqa: BLE001 — الإقلاع لا يسقط
        recovery = {"error": str(error)[:300], "healthy": False}
    ensure_watchdog(sessions)
    return recovery


__all__ = [
    "diagnose_once",
    "ensure_watchdog",
    "start_at_boot",
    "WATCHDOG_INTERVAL_S",
]
