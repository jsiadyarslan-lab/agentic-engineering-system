"""كلب سير العمل الدائم (013.4 §7) — لا حلقة معلقة بلا وسم صادق.

يكتشف ويوسم فقط — لا يزوّر اكتمالًا أبدًا ولا ينفّذ عملًا:

1. **جلسات تخطيط ميتة**: GENERATING بإيجار منتهٍ (بلا نبضة) =
   العملية المولِّدة ماتت ← INTERRUPTED + المشروع DRAFT بخطأ
   صريح + حدث — لا PLANNING أبديًا (جذر عطل §0).
2. **وظائف متقادمة**: كشف 013.1 (detect_interrupted_jobs) كما هو —
   الوظيفة RUNNING بنبضة متقادمة بلا حلقة حية = INTERRUPTED.

التشخيص (DIAGNOSE) يكتب حدث WORKFLOW_DIAGNOSED بتصنيف وقرار:
RETRY (الجلسة القابلة للإعادة أُعيدت آليًا بالفعل) أو
OWNER_ACTION_REQUIRED (قرار المالك الصريح). «استعادة أو حجب
بأمانة» — لا مسار ثالث يخترع نجاحًا.
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

    # 1) جلسات التخطيط الميتة — الإيجار منتهٍ بلا نبضة
    active = active_job_ids or set()
    swept = planning_runtime.sweep_stale_sessions(
        sessions, active_project_ids=set()
    )
    for session in swept:
        diagnosis = {
            "project_id": session["project_id"],
            "kind": "PLANNING_LEASE_EXPIRED",
            "session_id": session["id"],
            "decision": "OWNER_ACTION_REQUIRED",
            "detail": "انتهى إيجار جلسة التخطيط بلا نبضة — وُسمت "
                      "INTERRUPTED والمشروع أعيد DRAFT بخطأ صريح. "
                      "أعد المحاولة من زر الإعادة.",
            "error_class": "PLANNING_INTERRUPTED",
        }
        diagnoses.append(diagnosis)

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


__all__ = [
    "diagnose_once",
    "ensure_watchdog",
    "WATCHDOG_INTERVAL_S",
]
