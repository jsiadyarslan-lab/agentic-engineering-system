"""زمن تشغيل التخطيط (013.4 §1-§3) — التخطيط أمر خلفي محدود لا طلب حاجز.

جذر عطل 013.4 §0 (المشروع يدخل PLANNING ولا يخرج):

    POST /plan/generate كان استدعاءً متزامنًا داخل الطلب: الحالة
    تُكتب PLANNING ثم استدعاء LLM حاجز (مهلة 90ث × إعادات × تبدّل
    × محاولتَي مخطط) — الدقائق كلها بلا حدث واحد أو نبضة، وإن مات
    الطلب/الصفحة/العملية بقي المشروع PLANNING إلى الأبد.

العقد الجديد هنا (§2):

    PLANNING_STARTED → PLAN_GENERATING (نبضة + إيجار + مزود/نموذج/
    request_id) → PLAN_CREATED → PLAN_APPROVAL_REQUIRED
    أو → PLANNING_FAILED (مصنّف: MODEL_TIMEOUT/PROVIDER_QUOTA/…)
    أو → PLANNING_INTERRUPTED (كلب الإيجار: ماتت العملية)

الضمانات:
- **أمر فوري الوصف**: POST يعيد {started: true, session: …} خلال
  ملّي ثوانٍ؛ كل التفاصيل تصل عبر تيار الأحداث (نفس عقد 013 §3).
- **single-flight لكل مشروع**: جلسة GENERATING حية = رفض صريح
  بلا بدء ثانٍ (لا حلقتان على مشروع واحد).
- **إيجار منتهٍ = وسم صادق**: الكلب (watchdog.py) يوسم INTERRUPTED
  ويعيد المشروع DRAFT بخطأ صريح — لا PLANNING أبديًا.
- **فشل مصنّف**: كل فشل يحمل error_class من PLANNING_ERROR_CLASSES.
- **إعادة واحدة آلية** (§2 retry policy) ثم فشل صريح بقرار المالك.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from typing import Callable

from workflow import service
from workflow.models import PlanningSession

#: منفّذ التخطيط — خيط لكل مشروع نشط (قد يخطط مشروع أثناء تنفيذ آخر).
_PLANNING_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="aes-planning"
)

#: إيجار جلسة التخطيط: تنتهي بلا نبضة = العملية ماتت (كلب الإيجار).
LEASE_SECONDS = 120.0
#: فترة لمس النبضة الدورية للصف الدائم (لا ننتظر حدث المزود).
HEARTBEAT_SECONDS = 5.0
#: إعادة آلية واحدة عند فشل مصنّف قابل للإعادة (§2 retry policy).
MAX_AUTO_RETRIES = 1

#: فشل قابل للإعادة الآلية — عابر بطبيعته (مهلة/خادم مشغول).
_RETRYABLE_CLASSES = {
    "MODEL_TIMEOUT", "PROVIDER_QUOTA", "PROVIDER_UNAVAILABLE",
}

#: الجلسات الحية في هذه العملية — بث لحظي فقط؛ الحقيقة في القاعدة.
_ACTIVE: dict[int, dict] = {}
_ACTIVE_LOCK = threading.Lock()


class PlanningError(RuntimeError):
    """خطأ تخطيط صريح — يصل الطلب فورًا (قبل أي عمل خلفي)."""


def _utc_now():
    from workflow.models import _utc_now as _now
    return _now()


# ------------------------------------------------------------------ #
# قراءة الحالة (§3) — ما الذي ينتظره التخطيط حرفيًا
# ------------------------------------------------------------------ #

def latest_session(sessions, project_id: int) -> dict | None:
    """آخر جلسة تخطيط للمشروع — أحدث صف مهما كانت حالته."""
    from sqlalchemy import select

    with sessions() as session:
        row = session.scalars(
            select(PlanningSession)
            .where(PlanningSession.project_id == int(project_id))
            .order_by(PlanningSession.id.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        return _row_view(row)


def session_view(sessions, project_id: int) -> dict:
    """عرض الحالة الحالية للتخطيط — ما يحتاجه §3 حرفيًا.

    GENERATING: provider/model/request_id/started_at/last_activity/
    elapsed/retry/lease. الفشل: error_class + detail + إعادة متاحة.
    """
    row = latest_session(sessions, project_id)
    if row is None:
        return {"active": False, "state": "NONE",
                "waiting_for": None, "detail": {}}
    detail = dict(row)
    active = row["state"] == "GENERATING"
    waiting_for = None
    if active:
        waiting_for = {
            "kind": "model",
            "provider": row["provider"],
            "model": row["model"],
            "request_id": row["request_id"],
            "attempt": row["attempt"],
        }
    return {
        "active": active,
        "state": row["state"],
        "waiting_for": waiting_for,
        "retry_available": row["state"] in ("FAILED", "INTERRUPTED"),
        "detail": detail,
    }


def _coerce_utc(value):
    """توحيد المنطقة الزمنية — SQLite يعيد ساذجًا؛ الساذج = UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _row_view(row: PlanningSession) -> dict:
    def _iso(value):
        return value.isoformat() if value is not None else None

    now = _utc_now()
    started = _coerce_utc(row.started_at)
    finished = _coerce_utc(row.finished_at)
    elapsed_s = None
    if started is not None:
        end = finished or now
        elapsed_s = max(0.0, (end - started).total_seconds())
    return {
        "id": row.id,
        "project_id": row.project_id,
        "attempt": row.attempt,
        "state": row.state,
        "provider": row.provider,
        "model": row.model,
        "request_id": row.request_id,
        "started_at": _iso(row.started_at),
        "last_activity_at": _iso(row.last_activity_at),
        "lease_expires_at": _iso(row.lease_expires_at),
        "finished_at": _iso(row.finished_at),
        "elapsed_s": round(elapsed_s, 1) if elapsed_s is not None else None,
        "plan_id": row.plan_id,
        "error_class": row.error_class,
        "error_detail": row.error_detail[:400],
        "retry_of": row.retry_of,
    }


# ------------------------------------------------------------------ #
# بدء التخطيط — أمر خلفي فوري الوصف (§1)
# ------------------------------------------------------------------ #

def start_planning(
    project_id: int,
    *,
    sessions,
    engine_factory: Callable,
    on_live_event: Callable[[dict], None] | None = None,
    previous_failure: dict | None = None,
    reason: str = "توليد الخطة",
) -> dict:
    """بدء توليد الخطة خلفيًا — يعيد وصف الجلسة فورًا.

    engine_factory:callable() يبني المحرك (نفس مصنع 013 runner —
    وقت الطلب لا داخل الخيط). الجلسة تُكتب GENERATING قبل أي عمل،
    وكل انتقال يصل حدثًا دائمًا + بثًا لحظيًا.
    """
    project = service.get_project(sessions, int(project_id))
    if project is None:
        raise PlanningError(f"مشروع غير معروف: {project_id}")
    if project["status"] in ("VERIFIED", "COMPLETED", "STOPPED",
                             "ESCALATED"):
        raise PlanningError(
            f"المشروع في حالة نهائية ({project['status']}) — لا توليد خطة"
        )

    # single-flight لكل مشروع: جلسة GENERATING حية في القاعدة
    existing = latest_session(sessions, project_id)
    if existing is not None and existing["state"] == "GENERATING":
        live = _is_live_locally(project_id)
        if live:
            return {"started": False, "reason": "already_generating",
                    "session": existing}
        # صف GENERATING من عملية ماتت — الكلب سيعالجه؛ نبدأ جلسة
        # جديدة فقط بعد وسمه INTERRUPTED كي لا نجمع جلسات يتيمة.
        _expire_stale_session(sessions, existing)
        existing = latest_session(sessions, project_id)

    engine = engine_factory()
    selections = engine.role_selections() if hasattr(
        engine, "role_selections") else {}
    selection = (selections or {}).get("thinker")
    provider = getattr(selection, "provider", "") or ""
    model = getattr(selection, "model", "") or ""
    attempt = (existing["attempt"] if existing else 0) + 1

    row_id = _create_session(
        sessions, project_id, provider=provider, model=model,
        attempt=attempt, retry_of=(existing or {}).get("id"),
    )
    service.update_project(sessions, project_id, status="PLANNING",
                           last_error="")
    _emit(sessions, project_id, "PLANNING_STARTED", {
        "session_id": row_id, "attempt": attempt,
        "provider": provider, "model": model,
        "previous_failure": previous_failure or {},
        "reason": reason,
    }, on_live_event)

    _PLANNING_EXECUTOR.submit(
        _plan_thread, row_id, project_id, engine_factory, sessions,
        previous_failure, on_live_event,
    )
    return {"started": True,
            "session": latest_session(sessions, project_id)}


def _is_live_locally(project_id: int) -> bool:
    with _ACTIVE_LOCK:
        entry = _ACTIVE.get(int(project_id))
        return bool(entry and not entry["done"].is_set())


def _create_session(sessions, project_id: int, *, provider: str,
                    model: str, attempt: int,
                    retry_of: int | None = None) -> int:
    now = _utc_now()
    with sessions() as session:
        row = PlanningSession(
            project_id=int(project_id), attempt=int(attempt),
            state="GENERATING", provider=provider, model=model,
            request_id=f"plan-{uuid.uuid4().hex[:12]}",
            started_at=now, last_activity_at=now,
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            retry_of=retry_of,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return int(row.id)


def _update_session(sessions, row_id: int, **fields) -> None:
    with sessions() as session:
        row = session.get(PlanningSession, int(row_id))
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()


def _touch(sessions, row_id: int) -> None:
    now = _utc_now()
    _update_session(sessions, row_id, last_activity_at=now,
                    lease_expires_at=now + timedelta(
                        seconds=LEASE_SECONDS))


def _emit(sessions, project_id: int, kind: str, payload: dict,
          on_live_event: Callable[[dict], None] | None) -> None:
    """حدث دائم + بث لحظي — نفس عقد المحرك (event_id موحّد)."""
    event_id = service.add_event(sessions, project_id, kind, payload)
    if on_live_event is not None:
        try:
            on_live_event({
                "project_id": project_id, "kind": kind,
                "payload": payload, "event_id": event_id,
            })
        except Exception:  # noqa: BLE001 — البث لا يكسر التخطيط
            pass


# ------------------------------------------------------------------ #
# خيط التخطيط — النبض والتصنيف والإتمام الصادق (§2+§4)
# ------------------------------------------------------------------ #

def _plan_thread(row_id: int, project_id: int, engine_factory: Callable,
                 sessions, previous_failure: dict | None,
                 on_live_event) -> None:
    done = threading.Event()
    with _ACTIVE_LOCK:
        _ACTIVE[int(project_id)] = {"done": done, "session_id": row_id}
    try:
        _run_planning(row_id, project_id, engine_factory, sessions,
                      previous_failure, on_live_event, done)
    finally:
        done.set()
        with _ACTIVE_LOCK:
            if _ACTIVE.get(int(project_id), {}).get("done") is done:
                _ACTIVE.pop(int(project_id), None)


def _run_planning(row_id: int, project_id: int, engine_factory: Callable,
                  sessions, previous_failure, on_live_event,
                  done: threading.Event) -> None:
    from router.call_tracker import TrackedCall

    def emit(kind: str, payload: dict) -> None:
        _emit(sessions, project_id, kind, payload, on_live_event)

    # نبضة الصف الدائم — خيط مرافق يلمس الإيجار كل HEARTBEAT_SECONDS
    def _beat() -> None:
        while not done.wait(HEARTBEAT_SECONDS):
            try:
                _touch(sessions, row_id)
            except Exception:  # noqa: BLE001 — النبض لا يكسر التخطيط
                continue

    import threading as _th
    beater = _th.Thread(target=_beat, daemon=True,
                        name=f"aes-planning-beat[{project_id}]")
    beater.start()

    try:
        engine = engine_factory()
        planner = engine.build_planner()
    except Exception as error:  # noqa: BLE001 — فشل صريح مصنّف
        _finish_failed(sessions, row_id, project_id, "PROVIDER_NOT_CONFIGURED",
                       f"تعذر بناء المخطط الحي: {error}", emit,
                       on_live_event, done)
        return

    tracked = TrackedCall(
        "planning",
        on_event=lambda kind, payload: emit(kind, {
            **payload, "session_id": row_id,
        }),
    )
    emit("PLAN_GENERATING", {
        "session_id": row_id,
        "provider": tracked.record.provider or
        (latest_session(sessions, project_id) or {}).get("provider", ""),
        "model": tracked.record.model or
        (latest_session(sessions, project_id) or {}).get("model", ""),
        "request_id": tracked.record.request_id,
    })
    try:
        project = service.get_project(sessions, project_id) or {}
        plan_data = tracked.run(
            planner.generate, project.get("objective", ""),
            previous_failure=previous_failure,
        )
    except Exception as error:  # noqa: BLE001 — فشل مصنّف لا صامت
        error_class, detail = tracked.classify(error)
        # الجلسة الحالية انتهت فعلًا — تُوسم قبل قرار الإعادة كي تبدو
        # جلسة الإعادة نظيفة (لا GENERATING حية تعيقها)
        _update_session(
            sessions, row_id, state="FAILED",
            finished_at=_utc_now(), error_class=error_class,
            error_detail=str(detail)[:800],
            provider=tracked.record.provider, model=tracked.record.model,
        )
        retried = _auto_retry_if_worth(
            row_id, project_id, engine_factory, sessions,
            previous_failure, on_live_event, error_class,
        )
        if retried is not None:
            done.set()   # الجلسة الأصلية انتهت؛ الإعادة جلسة جديدة
            return
        _finish_project_failure(
            sessions, project_id, error_class, detail, emit,
        )
        done.set()
        return

    # نجاح — نفس مسار المحرك الأصلي: خطة + بوابة اعتماد
    try:
        plan = engine.record_generated_plan(
            project_id, plan_data,
            generated_by=tracked.record.view(),
            previous_failure=previous_failure,
        )
    except Exception as error:  # noqa: BLE001 — فشل التدوين صريح
        _finish_failed(sessions, row_id, project_id, "PLANNING_ERROR",
                       f"الخطة وُلدت لكن تعذر تدوينها: {error}", emit,
                       on_live_event, done)
        return
    _update_session(sessions, row_id, state="COMPLETED",
                    finished_at=_utc_now(), plan_id=plan["id"],
                    provider=tracked.record.provider,
                    model=tracked.record.model)
    emit("PLAN_CREATED", {
        "session_id": row_id, "plan_id": plan["id"],
        "version": plan["version"], "phases": len(plan["phases"]),
        "provider": tracked.record.provider, "model": tracked.record.model,
        "duration_ms": tracked.record.duration_ms,
    })
    _touch(sessions, row_id)
    done.set()


def _auto_retry_if_worth(row_id, project_id, engine_factory, sessions,
                         previous_failure, on_live_event,
                         error_class: str) -> int | None:
    """إعادة آلية واحدة للفشل القابل للإعادة (§2) — جلسة جديدة صادقة.

    يعيد معرف الجلسة الجديدة إن أُعيد البدء، أو None إن لم تُستحق.
    الإعادة بلا تمويه: حدث PLANNING_RETRY يحمل الجلسة والسبب.
    المستدعي وسّم الجلسة الأصلية FAILED قبل النداء — جلسة الإعادة
    تبدأ نظيفة بلا تعارض single-flight.
    """
    if error_class not in _RETRYABLE_CLASSES:
        return None
    existing = latest_session(sessions, project_id)
    if existing is None or existing["id"] != row_id:
        return None
    # (§2) إعادة آلية واحدة حصرًا: الجلسة الثانية (attempt=2) لا تُعاد
    # تلقائيًا — ما بعدها قرار المالك الصريح (زر الإعادة)
    if int(existing.get("attempt") or 1) >= 1 + MAX_AUTO_RETRIES:
        return None
    try:
        result = start_planning(
            project_id, sessions=sessions, engine_factory=engine_factory,
            on_live_event=on_live_event, previous_failure=previous_failure,
            reason=f"إعادة آلية بعد {error_class}",
        )
    except Exception:  # noqa: BLE001 — فشل الإعادة = فشل صريح
        return None
    if not result.get("started"):
        return None
    _emit(sessions, project_id, "PLANNING_RETRY", {
        "from_session": row_id, "error_class": error_class,
        "new_session": (result.get("session") or {}).get("id"),
    }, on_live_event)
    return int(result["session"]["id"])


def _finish_failed(sessions, row_id: int, project_id: int,
                   error_class: str, detail: str, emit, on_live_event,
                   done: threading.Event,
                   event_kind: str = "PLANNING_FAILED") -> None:
    """فشل صريح — صف الجلسة + المشروع DRAFT بخطأ + حدث مصنّف."""
    _update_session(sessions, row_id, state="FAILED",
                    finished_at=_utc_now(), error_class=error_class,
                    error_detail=str(detail)[:800])
    service.update_project(
        sessions, project_id, status="DRAFT",
        last_error=f"فشل توليد الخطة [{error_class}]: "
                   f"{str(detail)[:400]}",
    )
    emit(event_kind, {
        "session_id": row_id, "error_class": error_class,
        "error_detail": str(detail)[:400],
        "retry_available": True,
    })
    done.set()


def _finish_project_failure(sessions, project_id: int,
                            error_class: str, detail: str,
                            emit) -> None:
    """فشل بلا إعادة — الجلسة وُسمت؛ هنا المشروع والحدث فقط (§2)."""
    service.update_project(
        sessions, project_id, status="DRAFT",
        last_error=f"فشل توليد الخطة [{error_class}]: "
                   f"{str(detail)[:400]}",
    )
    emit("PLANNING_FAILED", {
        "project_id": project_id, "error_class": error_class,
        "error_detail": str(detail)[:400],
        "retry_available": True,
    })


# ------------------------------------------------------------------ #
# انتهاء الإيجار — كلب الجلسات الميتة (يستدعيه watchdog.py)
# ------------------------------------------------------------------ #

def _expire_stale_session(sessions, row: dict) -> None:
    """وسم جلسة GENERATING منتهية الإيجار INTERRUPTED — أمانة كاملة."""
    lease = row.get("lease_expires_at")
    if not lease:
        return
    try:
        from datetime import datetime
        expires = datetime.fromisoformat(str(lease))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires > _utc_now():
            return   # الإيجار حي — ليست ميتة
    except ValueError:
        pass
    if _is_live_locally(row["project_id"]):
        return   # الخيط حي في هذه العملية — النبضة ستلمس قريبًا
    _update_session(sessions, row["id"], state="INTERRUPTED",
                    finished_at=_utc_now(),
                    error_class="PLANNING_INTERRUPTED",
                    error_detail="انتهى إيجار الجلسة بلا نبضة — "
                                 "العملية المولِّدة ماتت")
    service.update_project(
        sessions, row["project_id"], status="DRAFT",
        last_error="توقف توليد الخطة — ماتت العملية المولِّدة "
                   "(PLANNING_INTERRUPTED). أعد المحاولة.",
    )
    service.add_event(
        sessions, row["project_id"], "PLANNING_INTERRUPTED", {
            "session_id": row["id"], "error_class": "PLANNING_INTERRUPTED",
            "retry_available": True,
        },
    )


def sweep_stale_sessions(sessions, *, active_project_ids: set[int]) -> list[dict]:
    """مسح كل جلسات GENERATING منتهية الإيجار (013.4 §7).

    يعيد قائمة الجلسات الموسومة — الكلب يستخدمها للإعلان والتشخيص.
    active_project_ids: مشاريع لها حلقة نشطة في هذه العملية (تُستثنى
    إن كانت نبضتها حديثة).
    """
    from sqlalchemy import select

    swept: list[dict] = []
    with sessions() as session:
        rows = session.scalars(
            select(PlanningSession)
            .where(PlanningSession.state == "GENERATING")
        ).all()
        views = [_row_view(row) for row in rows]
    for view in views:
        if view["project_id"] in active_project_ids \
                and _is_live_locally(view["project_id"]):
            continue
        _expire_stale_session(sessions, view)
        swept.append(view)
    return swept


def wait_for_planning(sessions, project_id: int, *,
                      timeout: float = 30.0) -> dict:
    """انتظار اكتمال جلسة التخطيط الجارية (اختبارات/إجراءات صريحة).

    ينتظر حتى تستقر الحالة: آخر جلسة نهائية **ولا جلسة GENERATING
    حية** (الإعادة الآلية قد تفتح جلسة جديدة لحظة وسم سابقتها).
    المهلة تنتهي بخطأ صريح — لا انتظار بلا سقف (روح 013.4 §2).
    """
    import time as _time
    from sqlalchemy import select

    deadline = _time.monotonic() + float(timeout)
    last: dict | None = None
    while _time.monotonic() < deadline:
        last = latest_session(sessions, int(project_id))
        if last is None:
            raise PlanningError(
                f"لا جلسة تخطيط للمشروع {project_id} — ابدأها أولًا"
            )
        if last["state"] in ("COMPLETED", "FAILED", "INTERRUPTED"):
            with sessions() as session:
                generating = session.scalars(
                    select(PlanningSession)
                    .where(PlanningSession.project_id == int(project_id),
                           PlanningSession.state == "GENERATING")
                    .limit(1)
                ).first()
            if generating is None:
                return last   # استقرت: لا جلسة حية ولا إعادة قادمة
        _time.sleep(0.05)
    raise PlanningError(
        f"التخطيط لم يكتمل خلال {timeout}ث — آخر حالة: "
        f"{(last or {}).get('state', '?')}"
    )


__all__ = [
    "PlanningError",
    "latest_session",
    "session_view",
    "start_planning",
    "sweep_stale_sessions",
    "wait_for_planning",
    "LEASE_SECONDS",
]
