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

(013.5 §B-§D) التصحيح الجذري بعد أن ثبت حيًّا أن المشروع بقي
«PLANNING» 17992ث:

1. **نبضتان لا نبضة** (§D): ``heartbeat_at`` = حياة الخيط (مؤقت)،
   و``last_meaningful_activity_at`` = نشاط مزود حقيقي (بدء الطلب/
   وصول قطعة/اكتمال الرد). **الإيجار يُحسب من النشاط الحقيقي
   حصرًا** — نبضة المؤقت لم تعد تمدّد عمر الجلسة، فلا يمكن لمزود
   معلّق أن يُبقي GENERATING إلى الأبد.
2. **سقف زمن الجدار** (§B/§C.1): ``hard_deadline_at`` لكل محاولة.
   تجاوزه = MODEL_TIMEOUT حتمًا **حتى لو كان الخيط حيًّا** — ذلك هو
   الفرق بين «حلقة موجودة» و«حلقة تتقدم».
3. **حارس الثبات** (§C): ``enforce_invariant`` يضمن ألّا يبقى
   ``project.status == PLANNING`` بلا جلسة GENERATING حية بإيجار
   صالح — أي شذوذ يُعاد إلى DRAFT بسبب صريح.
4. **استرداد عند الإقلاع** (§C.4): ``recover_at_startup`` يمسح
   الجلسات الميتة فورًا عند إنشاء التطبيق. العطل الحي وقع لأن الكلب
   كان يُشغَّل **فقط** عند إطلاق حلقة تنفيذ — فمشروع مات مولّده
   بقي PLANNING ساعات بلا أي فحص.
5. **حارس الحالة النهائية**: خيط تخطيط تأخّر عن الكلب لا يستطيع
   الكتابة فوق نتيجة نهائية موثّقة (لا COMPLETED بعد FAILED).
"""

from __future__ import annotations

import json
import os as _os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from typing import Callable

from workflow import service
from workflow.models import PlanningSession


def _env_seconds(name: str, default: float) -> float:
    """(013.5 §C) سقوف التخطيط قابلة للضبط بمتغير بيئة صريح.

    القيمة معلنة في اللقطة والواجهة دائمًا — فالضبط لا يُخفي الحقيقة،
    والمُشغِّل يملك تشديد السقف أو توسيعه لمزود بطيء إن أراد.
    """
    raw = _os.environ.get(name, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    return float(default) if value <= 0 else value

#: منفّذ التخطيط — خيط لكل مشروع نشط (قد يخطط مشروع أثناء تنفيذ آخر).
_PLANNING_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="aes-planning"
)

#: إيجار جلسة التخطيط: تنتهي بلا **نشاط مزود حقيقي** = العملية ماتت
#: أو المزود صامت (كلب الإيجار). (013.5 §D) لم يعد المؤقت يمدّده.
LEASE_SECONDS = 120.0
#: (013.5 §D) فترة لمس نبضة الحياة للصف الدائم — حياة لا تقدم:
#: تُكتب في ``heartbeat_at`` ولا تمدّد الإيجار أبدًا.
HEARTBEAT_SECONDS = 5.0
#: (013.5 §C.1) سقف زمن الجدار المطلق لمحاولة تخطيط واحدة. تجاوزه =
#: MODEL_TIMEOUT حتمًا ولو كان الخيط حيًّا يرزح على طلب معلّق.
#:
#: ‏900ث لا 300ث: النموذج المُهيَّأ (deepseek-ai/deepseek-v4.1-flash)
#: نموذج **استدلالي** — يقضي زمنًا طويلًا في reasoning_content قبل أن
#: تُنتج مخرجاته حرفًا واحدًا (قيس مباشرة: ‏36ث لثمانية رموز فقط).
#: سقف ضيّق كان يحسم MODEL_TIMEOUT على عمل صحيح جارٍ — وهو حكم كاذب
#: من الجهة المقابلة. السقف موجود ومعلن في الواجهة ويطبّق حتمًا.
HARD_TIMEOUT_SECONDS = _env_seconds("AGENTHUB_PLAN_HARD_TIMEOUT", 900.0)
#: (013.5 §C.3) حدّ صمت المزود والاستدعاء جارٍ — بعدها MODEL_TIMEOUT
#: برسالة أدق قبل السقف المطلق. «الصمت» الآن = لا استدلال ولا مخرجات
#: ولا حدث استدعاء، فالنموذج الاستدلالي لا يُوسم صامتًا وهو يفكّر.
PROVIDER_SILENCE_LIMIT_SECONDS = _env_seconds(
    "AGENTHUB_PLAN_SILENCE_LIMIT", 300.0)
#: إعادة آلية واحدة عند فشل مصنّف قابل للإعادة (§2 retry policy).
MAX_AUTO_RETRIES = 1

#: (013.5 §C) الحالات المسموحة لجلسة التخطيط — مفردات مقفلة.
SESSION_STATES: tuple[str, ...] = (
    "QUEUED", "GENERATING", "COMPLETED", "FAILED", "INTERRUPTED",
    "PAUSED", "CANCELLED",
)

#: الحالات النهائية — لا انتقال بعدها أبدًا (حارس الحالة النهائية).
TERMINAL_SESSION_STATES = ("COMPLETED", "FAILED", "INTERRUPTED",
                           "CANCELLED")

#: فشل قابل للإعادة الآلية — عابر بطبيعته (مهلة/خادم مشغول).
_RETRYABLE_CLASSES = {
    "MODEL_TIMEOUT", "PROVIDER_QUOTA", "PROVIDER_UNAVAILABLE",
}

#: الجلسات الحية في هذه العملية — بث لحظي فقط؛ الحقيقة في القاعدة.
_ACTIVE: dict[int, dict] = {}
_ACTIVE_LOCK = threading.Lock()

#: (013.5 §K) نية الإلغاء لكل جلسة — يقرأها خيط التوليد **داخل**
#: حلقة البث فيقطع الاتصال فعليًا من نفس الخيط (إغلاق الفتحة عبر
#: ``with response``). هذا إلغاء حقيقي لا علم تجميلي: لا انتظار حتى
#: انتهاء مهلة النقل.
_CANCEL: dict[int, dict] = {}
_CANCEL_LOCK = threading.Lock()


class PlanningError(RuntimeError):
    """خطأ تخطيط صريح — يصل الطلب فورًا (قبل أي عمل خلفي)."""


class PlanningCancelled(RuntimeError):
    """(013.5 §K) أُلغي التوليد بأمر المالك — لا فشل مزود ولا نجاح.

    تُرفع من داخل حلقة البث نفسها فينغلق الاتصال فورًا، وتُصنَّف
    CANCELLED لا FAILED: الفرق جوهري في التقرير والواجهة.
    """


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

    (013.5 §J) ``wait_phase`` رمز صادق يشرح **الانتظار نفسه** لا
    كلمة «جاري التخطيط» العامة: CONNECTING (بدأ الطلب للتو) ←
    REASONING (النموذج يفكّر فعلًا ووصل نشاط استدلال) ←
    AWAITING_PROVIDER (لا نشاط مُثبت بعد بدء الطلب) ← (منتهية:
    FAILED / INTERRUPTED / DONE). الواجهة تُنسّق الرمز إلى العربية؛
    المنطق هنا واحد لا يتكرر في خمسة ملفات واجهة.
    """
    row = latest_session(sessions, project_id)
    if row is None:
        return {"active": False, "state": "NONE", "wait_phase": "NONE",
                "waiting_for": None, "detail": {}}
    detail = dict(row)
    active = row["state"] == "GENERATING"
    waiting_for = None
    wait_phase = {
        "COMPLETED": "DONE",
        "FAILED": "FAILED",
        "INTERRUPTED": "INTERRUPTED",
        "CANCELLED": "CANCELLED",
        "PAUSED": "PAUSED",
        "QUEUED": "QUEUED",
    }.get(row["state"], "NONE")
    if active:
        silence = row.get("silence_s") or 0.0
        # (013.5 §D/§J) استدلال حيّ ≠ صمت: النموذج الاستدلالي يعمل
        # دقائق قبل أول حرف من الإجابة، والوسم الصادق هو REASONING.
        reasoned = bool(row.get("reasoning_chars"))
        if reasoned:
            wait_phase = "REASONING"
        elif silence < 15.0:
            wait_phase = "CONNECTING"
        else:
            wait_phase = "AWAITING_PROVIDER"
        waiting_for = {
            "kind": "model",
            "provider": row["provider"],
            "model": row["model"],
            "request_id": row["request_id"],
            "attempt": row["attempt"],
            "silence_s": silence,
            "reasoning_chars": row.get("reasoning_chars") or 0,
            "hard_deadline_at": row.get("hard_deadline_at"),
        }
    return {
        "active": active,
        "state": row["state"],
        "wait_phase": wait_phase,
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
    # (013.5 §D) الصفوف القديمة (قبل الترحيل) بلا نبضة نشاط صريحة:
    # نشتقّها من last_activity_at حتى يبقى الحكم صادقًا لا منكسرًا.
    meaningful = _coerce_utc(
        getattr(row, "last_meaningful_activity_at", None)
    ) or _coerce_utc(row.last_activity_at)
    heartbeat = _coerce_utc(getattr(row, "heartbeat_at", None)) \
        or _coerce_utc(row.last_activity_at)
    deadline = _coerce_utc(getattr(row, "hard_deadline_at", None))
    # (013.5 §C) لا نخترع سقفًا لم يُسجَّل: الصفوف السابقة للترحيل
    # بلا hard_deadline_at صريح يحكمها الإيجار وحده (وسم صادق لا
    # تخمين). الصفوف الجديدة تحمل السقف من لحظة الإنشاء.
    derived_deadline = None
    if deadline is None and started is not None:
        derived_deadline = started + timedelta(seconds=HARD_TIMEOUT_SECONDS)
    silence_s = None
    if meaningful is not None and row.state == "GENERATING":
        silence_s = max(0.0, (now - meaningful).total_seconds())
    return {
        "id": row.id,
        "project_id": row.project_id,
        "attempt": row.attempt,
        "state": row.state,
        "provider": row.provider,
        "model": row.model,
        "request_id": row.request_id,
        "started_at": _iso(row.started_at),
        "heartbeat_at": _iso(heartbeat),
        "last_meaningful_activity_at": _iso(meaningful),
        "silence_s": round(silence_s, 1) if silence_s is not None else None,
        "hard_deadline_at": _iso(deadline),
        "hard_deadline_derived_at": _iso(derived_deadline),
        "hard_timeout_s": HARD_TIMEOUT_SECONDS,
        "last_activity_at": _iso(row.last_activity_at),
        "lease_expires_at": _iso(row.lease_expires_at),
        "finished_at": _iso(row.finished_at),
        "elapsed_s": round(elapsed_s, 1) if elapsed_s is not None else None,
        "plan_id": row.plan_id,
        "error_class": row.error_class,
        "error_detail": row.error_detail[:400],
        "retry_of": row.retry_of,
        "actual_provider": getattr(row, "actual_provider", "") or "",
        "actual_model": getattr(row, "actual_model", "") or "",
        # (013.5 §D) أحرف الاستدلال المُثبتة — دليل «المزود يعمل»
        # لنموذج استدلالي قبل أن تصل أول قطعة مخرجات.
        "reasoning_chars": int(getattr(row, "reasoning_chars", 0) or 0),
        # (013.5 §Q) العملية المالكة وحياتها — تُقرأ في اللقطة فتشرح
        # أي استرداد فوري ولماذا.
        "owner_pid": getattr(row, "owner_pid", None),
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
    # (013.5 §C) تسجيل النية **قبل** تحديث المشروع: حارس الثبات يقرأ
    # ``_is_live_locally`` في هذه النافذة، فلا يوسم انتقالًا جاريًا
    # كشذوذ. نفس الحدث يُسلَّم لخيط التخطيط فلا هويتان لمحاولة واحدة.
    done = threading.Event()
    with _ACTIVE_LOCK:
        _ACTIVE[int(project_id)] = {"done": done, "session_id": row_id}
    service.update_project(sessions, project_id, status="PLANNING",
                           last_error="")
    _emit(sessions, project_id, "PLANNING_STARTED", {
        "session_id": row_id, "attempt": attempt,
        "provider": provider, "model": model,
        "hard_deadline_at": (latest_session(sessions, project_id) or {})
        .get("hard_deadline_at"),
        "hard_timeout_s": HARD_TIMEOUT_SECONDS,
        "previous_failure": previous_failure or {},
        "reason": reason,
    }, on_live_event)

    try:
        _PLANNING_EXECUTOR.submit(
            _plan_thread, row_id, project_id, engine_factory, sessions,
            previous_failure, on_live_event, done,
        )
    except Exception:  # noqa: BLE001 — إرسال فاشل = فشل صريح لا تعليق
        done.set()
        with _ACTIVE_LOCK:
            if _ACTIVE.get(int(project_id), {}).get("done") is done:
                _ACTIVE.pop(int(project_id), None)
        _finish_failed(
            sessions, row_id, project_id, "PLANNING_ERROR",
            "تعذر إرسال مهمة التخطيط إلى المنفّذ", _emit_plain(sessions,
                                                              project_id,
                                                              on_live_event),
            on_live_event, done,
        )
    return {"started": True,
            "session": latest_session(sessions, project_id)}


def _emit_plain(sessions, project_id: int, on_live_event):
    def emit(kind: str, payload: dict) -> None:
        _emit(sessions, project_id, kind, payload, on_live_event)
    return emit


def _is_live_locally(project_id: int) -> bool:
    with _ACTIVE_LOCK:
        entry = _ACTIVE.get(int(project_id))
        return bool(entry and not entry["done"].is_set())


def _create_session(sessions, project_id: int, *, provider: str,
                    model: str, attempt: int,
                    retry_of: int | None = None) -> int:
    now = _utc_now()
    deadline = now + timedelta(seconds=HARD_TIMEOUT_SECONDS)
    with sessions() as session:
        row = PlanningSession(
            project_id=int(project_id), attempt=int(attempt),
            state="GENERATING", provider=provider, model=model,
            request_id=f"plan-{uuid.uuid4().hex[:12]}",
            started_at=now,
            # (013.5 §D) النشاط الحقيقي الابتدائي = لحظة الإنشاء؛
            # أول ``mark_activity`` حقيقي يأتي مع MODEL_CALL_STARTED.
            last_meaningful_activity_at=now,
            heartbeat_at=now,
            last_activity_at=now,
            lease_expires_at=min(
                now + timedelta(seconds=LEASE_SECONDS), deadline
            ),
            hard_deadline_at=deadline,
            retry_of=retry_of,
            # (013.5 §Q) العملية المالكة — أساس الاسترداد الفوري.
            owner_pid=_os.getpid(),
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


def _touch_heartbeat(sessions, row_id: int) -> None:
    """(013.5 §D) نبضة الحياة وحدها — **لا تمدّد الإيجار**.

    هذا هو الفصل الإلزامي: خيط حي على طلب معلّق ليس تقدمًا، فلا
    يجوز أن تحميه نبضة المؤقت من كلب المهلة.
    """
    _update_session(sessions, row_id, heartbeat_at=_utc_now())


def _mark_activity(sessions, row_id: int, *, note: str = "",
                   reasoning_chars: int | None = None) -> None:
    """(013.5 §D) نشاط مزود **حقيقي** — هو الوحيد الذي يمدّد الإيجار.

    الإيجار مقيّد دائمًا بسقف زمن الجدار: لا تمديد يفلت من المهلة
    الصلبة مهما تكرر النشاط.

    ``reasoning_chars``: عدّاد أحرف الاستدلال المُثبت — دليل دائم
    يُقرأ في الواجهة واللقطة، فلا يُوسم نموذج استدلالي صامتًا.
    """
    now = _utc_now()
    with sessions() as session:
        row = session.get(PlanningSession, int(row_id))
        if row is None or row.state in TERMINAL_SESSION_STATES:
            return
        deadline = _coerce_utc(getattr(row, "hard_deadline_at", None))
        if deadline is None:
            started = _coerce_utc(row.started_at) or now
            deadline = started + timedelta(seconds=HARD_TIMEOUT_SECONDS)
            row.hard_deadline_at = deadline
        row.last_meaningful_activity_at = now
        row.last_activity_at = now
        row.heartbeat_at = now
        if reasoning_chars is not None:
            row.reasoning_chars = max(
                int(getattr(row, "reasoning_chars", 0) or 0),
                int(reasoning_chars),
            )
        row.lease_expires_at = min(
            now + timedelta(seconds=LEASE_SECONDS), deadline
        )
        session.commit()


def _current_state(sessions, row_id: int) -> str:
    """حالة الصف الآن — لحارس الحالة النهائية (§C)."""
    with sessions() as session:
        row = session.get(PlanningSession, int(row_id))
        return row.state if row is not None else ""


def _finish_generating(sessions, row_id: int, *, allow_from_completed=False,
                       **fields) -> bool:
    """إنهاء الجلسة **فقط إن كانت ما زالت GENERATING** (§C حارس نهائي).

    يعيد True إن كتبنا النتيجة، وFalse إن كان الكلب قد حسم الجلسة
    قبلنا — عندها لا نكتب فوق حقيقة نهائية موثّقة (لا COMPLETED
    بعد FAILED، ولا العكس).

    (013.5 §C/§H) ``allow_from_completed``: تصحيح معلن لحالة مستحيلة
    الدلالة — جلسة COMPLETED بلا ``plan_id`` تعني «نجاح بلا خطة»، وهي
    كذبة لا حقيقة؛ تُصحَّح إلى FAILED عند فشل التدوين حصرًا.
    """
    with sessions() as session:
        row = session.get(PlanningSession, int(row_id))
        if row is None:
            return False
        if row.state in TERMINAL_SESSION_STATES:
            if not (allow_from_completed and row.state == "COMPLETED"
                    and row.plan_id is None):
                return False
        for key, value in fields.items():
            setattr(row, key, value)
        if "finished_at" not in fields:
            row.finished_at = _utc_now()
        session.commit()
        return True


def _attach_plan_id(sessions, row_id: int, plan_id: int) -> bool:
    """ربط الخطة المدوّنة بجلستها — بعد الحجز لا قبله (§C).

    الحجز يسبق التدوين فلا تناقض؛ هذا النداء يُتمّم الصف بالمعرّف
    الحقيقي. يعيد False إن كانت الجلسة لم تعد COMPLETED (حسم لاحق
    من الكلب) — عندها التناقض يُعلن ولا يُخفى.
    """
    with sessions() as session:
        row = session.get(PlanningSession, int(row_id))
        if row is None or row.state != "COMPLETED":
            return False
        row.plan_id = int(plan_id)
        session.commit()
        return True


def cancel_planning(sessions, project_id: int, *,
                    reason: str = "", final: bool = False,
                    on_live_event: Callable[[dict], None] | None = None) -> dict:
    """(013.5 §K) إلغاء **حقيقي** لتوليد جارٍ — إيقاف أو إيقاف مؤقت.

    العطل الذي يغلق هذه الدالة: ``request_stop``/``pause`` كانا يضبطان
    علمًا على صف المشروع فقط، بينما خيط التوليد يواصل الاستدعاء —
    فالإيقاف أثناء التخطيط لم يكن يوقف شيئًا: المشروع يبقى PLANNING
    والخطة تصل لاحقًا وتقلب الحالة. هنا:

    1. ``_CANCEL`` يُضبط أولًا — خيط التوليد يرفع ``PlanningCancelled``
       من داخل حلقة البث فينغلق الاتصال **من نفس الخيط** (لا انتظار
       حتى انتهاء مهلة النقل).
    2. الجلسة تُحسم ``CANCELLED`` بحارس CAS: النتيجة المتأخرة لا
       تكتب فوق الإلغاء.
    3. حالة المشروع تُعلن صراحة: ``STOPPED`` نهائيًا أو ``PAUSED``
       قابلًا للاستئناف — وسبب المالك محفوظ حرفيًا.

    ``_ACTIVE`` يُفرَّغ **بعد** تحديث المشروع: في تلك النافذة يحمي
    حارس الثبات المشروع من إعادة DRAFT خطأً.
    """
    project_id = int(project_id)
    reason = reason or "إلغاء من المالك"
    row = latest_session(sessions, project_id)
    if row is None or row["state"] != "GENERATING":
        return {"cancelled": False, "session_id": None,
                "state": (row or {}).get("state", "NONE"),
                "reason": "لا توليد جارٍ لإلغائه — لا إلغاء وهمي"}

    row_id = int(row["id"])
    with _CANCEL_LOCK:
        _CANCEL[row_id] = {"reason": reason, "final": bool(final)}
    wrote = _finish_generating(
        sessions, row_id, state="CANCELLED",
        error_class="OWNER_CANCELLED", error_detail=reason,
    )
    service.update_project(
        sessions, project_id,
        status="STOPPED" if final else "PAUSED",
        stop_requested=not final,
        last_error=reason,
    )
    with _ACTIVE_LOCK:
        entry = _ACTIVE.get(project_id) or {}
        done = entry.get("done")
        _ACTIVE.pop(project_id, None)
    if done is not None:
        try:
            done.set()
        except Exception:  # noqa: BLE001 — الإشارة لا تُفشل الإلغاء
            pass
    _emit(sessions, project_id, "PLANNING_CANCELLED", {
        "session_id": row_id,
        "final": bool(final),
        "reason": reason,
        "session_written": wrote,
        "project_status": "STOPPED" if final else "PAUSED",
        "note": "الاستدعاء المعلّق يُقطع عند أول نشاط مزود (بث استدلال/"
                "مخرجات) — وإن صمت المزود كليًّا فالقطع عند مهلة النقل",
    }, on_live_event)
    with _CANCEL_LOCK:
        _CANCEL.pop(row_id, None)
    return {"cancelled": bool(wrote), "session_id": row_id,
            "state": "CANCELLED" if wrote else _current_state(sessions, row_id),
            "project_status": "STOPPED" if final else "PAUSED",
            "reason": reason}


def cancel_pending(sessions, row_id: int) -> bool:
    """هل ما زال الإلغاء معلَّقًا (الخيط لم يلاحظه بعد)؟ (§K صراحة)."""
    with _CANCEL_LOCK:
        return int(row_id) in _CANCEL


def _check_cancel(row_id: int, activity: str = "") -> None:
    """(013.5 §K) نقطة القطع الحقيقية — تُنادى من داخل حلقة البث.

    الرفع هنا يجري في خيط التوليد نفسه، فينغلق الاتصال عبر
    ``with response`` في مولّد النقل فورًا. ليست علمًا تجميليًا.
    """
    with _CANCEL_LOCK:
        pending = _CANCEL.get(int(row_id))
    if pending is not None:
        raise PlanningCancelled(
            str(pending.get("reason") or "") or f"إلغاء عند {activity}"
        )


def _adopt_planner_call(tracked, planner) -> None:
    """(013.5 §B) انقل نتيجة الموجّه الحقيقية إلى سجل الاستدعاء.

    ``planner.generate`` يعيد الخطة، و``TrackedCall`` يقرأ provider/
    model من مخرَج الاستدعاء — فتبقى الحقول الفعلية فارغة. المخطط
    يحتفظ بنتيجة الموجّه في ``last_call`` وهذا ما يُعتمد.
    """
    info = getattr(planner, "last_call", None) or {}
    if not isinstance(info, dict):
        return
    if info.get("provider"):
        tracked.record.provider = str(info["provider"])
    if info.get("model"):
        tracked.record.model = str(info["model"])
    if info.get("duration_ms"):
        try:
            tracked.record.duration_ms = int(info["duration_ms"])
        except (TypeError, ValueError):
            pass
    if info.get("streamed") is not None:
        tracked.record.streamed = bool(info.get("streamed"))


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
                 on_live_event, done: threading.Event) -> None:
    """(013.5 §C) الحدث يُمرَّر من ``start_planning`` — هوية واحدة
    للمحاولة، فلا نافذة يُرى فيها المشروع PLANNING بلا مولِّد."""
    with _ACTIVE_LOCK:
        entry = _ACTIVE.get(int(project_id))
        if entry is None or entry.get("done") is not done:
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

    # (013.5 §D) نبضة **الحياة** وحدها — لا تمدّد الإيجار. الإيجار
    # يُمدّد من نشاط المزود الحقيقي فقط (mark_activity أدناه).
    def _beat() -> None:
        while not done.wait(HEARTBEAT_SECONDS):
            try:
                _touch_heartbeat(sessions, row_id)
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

    def _on_tracked(kind: str, payload: dict) -> None:
        """(013.5 §D) جسر نشاط المزود: كل حدث استدعاء حقيقي يمدّد
        الإيجار — والنبضة الزمنية وحدها لا تفعل."""
        emit(kind, {**payload, "session_id": row_id})
        if kind in ("MODEL_CALL_STARTED", "MODEL_CALL_PROGRESS",
                    "MODEL_CALL_COMPLETED", "MODEL_CALL_FAILED",
                    "MODEL_CALL_HEARTBEAT", "MODEL_REASONING"):
            try:
                _mark_activity(sessions, row_id)
            except Exception:  # noqa: BLE001 — الوسم لا يكسر التخطيط
                pass

    # (013.5 §D) نشاط المخطط الحقيقي — قطعة مخرجات أو استدلال:
    # النموذج المُهيَّأ استدلالي، فمرحلة الاستدلال الطويلة كانت تبدو
    # «صمت مزود» فيُوسم MODEL_TIMEOUT وهو يعمل فعلًا. الآن تُمدَّد
    # الحياة من النشاط المُثبت، ويُعلن الاستدلال حدثًا مرئيًا للواجهة.
    _last_activity_emit = {"at": 0.0}

    def _on_planner_activity(kind: str, chars: int) -> None:
        import time as _time

        # (013.5 §K) نقطة القطع الحقيقية: هذا النداء يجري **داخل** حلقة
        # البث في خيط التوليد، فالرفع هنا يُنهي الاستدعاء ويغلق الفتحة.
        _check_cancel(row_id, kind)

        now_mono = _time.monotonic()
        if kind in ("content_delta", "reasoning_delta"):
            try:
                _mark_activity(
                    sessions, row_id,
                    reasoning_chars=chars if kind == "reasoning_delta" else None,
                )
            except Exception:  # noqa: BLE001 — الوسم لا يكسر التخطيط
                pass
        # أحداث معلنة متباعدة: لا نُغرق البث بقطعة لكل حرف
        if now_mono - _last_activity_emit["at"] < 2.0:
            return
        _last_activity_emit["at"] = now_mono
        emit("MODEL_REASONING" if kind == "reasoning_delta"
             else "MODEL_CALL_PROGRESS",
             {"session_id": row_id, "activity": kind, "chars": chars,
              "request_id": tracked.record.request_id,
              "provider": tracked.record.provider or
              (latest_session(sessions, project_id) or {}).get("provider", ""),
              "model": tracked.record.model or
              (latest_session(sessions, project_id) or {}).get("model", "")})

    if hasattr(planner, "on_activity"):
        planner.on_activity = _on_planner_activity

    tracked = TrackedCall("planning", on_event=_on_tracked)
    emit("PLAN_GENERATING", {
        "session_id": row_id,
        "provider": (latest_session(sessions, project_id) or {})
        .get("provider", ""),
        "model": (latest_session(sessions, project_id) or {})
        .get("model", ""),
        "request_id": tracked.record.request_id,
    })
    try:
        project = service.get_project(sessions, project_id) or {}
        plan_data = tracked.run(
            planner.generate, project.get("objective", ""),
            previous_failure=previous_failure,
        )
        # (§B) نتيجة الموجّه الحقيقية تُنقل إلى سجل الاستدعاء: التخطيط
        # يعيد الخطة لا نتيجة الموجّه، فبلا هذه النقلة يبقى
        # actual_provider/actual_model فارغين في صف الجلسة — وهو نقص
        # عقد صريح طلبه §B (المزود والنموذج **الفعليان** محفوظان).
        _adopt_planner_call(tracked, planner)
    except Exception as error:  # noqa: BLE001 — فشل مصنّف لا صامت
        if isinstance(error, PlanningCancelled):
            # (§K) إلغاء المالك — الجلسة وُسمت CANCELLED في cancel_planning.
            # لا وسم FAILED ولا رسالة فشل مزود: الفرق جوهري.
            emit("PLANNING_CANCEL_OBSERVED", {
                "session_id": row_id,
                "reason": str(error) or "إلغاء من المالك",
                "current_state": _current_state(sessions, row_id),
                "note": "خيط التوليد رأى الإلغاء وقطع الاستدعاء فعليًا",
            })
            done.set()
            return
        error_class, detail = tracked.classify(error)
        # (013.5 §C) حارس الحالة النهائية: إن كان الكلب حسم الجلسة
        # (مهلة صلبة/انقطاع) لا نكتب فوق حقيقته — نُعلن التجاهل.
        wrote = _finish_generating(
            sessions, row_id, state="FAILED",
            error_class=error_class, error_detail=str(detail)[:800],
            actual_provider=tracked.record.provider,
            actual_model=tracked.record.model,
        )
        if not wrote:
            emit("PLANNING_RESULT_DISCARDED", {
                "session_id": row_id,
                "error_class": error_class,
                "reason": "الجلسة حُسمت نهائيًا من الكلب قبل وصول خيط "
                          "التخطيط — لا كتابة فوق حقيقة موثّقة",
                "current_state": _current_state(sessions, row_id),
            })
            done.set()
            return
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

    # نجاح — نفس مسار المحرك الأصلي: خطة + بوابة اعتماد.
    #
    # (013.5 §C/§H) الترتيب هنا جوهري وقد كان معطوبًا: كان التدوين
    # (record_generated_plan) — الذي يحفظ الخطة **ويقلب حالة المشروع
    # إلى AWAITING_OWNER_APPROVAL** — يسبق حارس الحالة النهائية. فإذا
    # حسم الكلب الجلسة فشلًا في الأثناء، صار لدينا تناقض دائم مقيس
    # حيًّا في مشروع 11: جلسة FAILED/MODEL_TIMEOUT بينما المشروع
    # AWAITING_OWNER_APPROVAL وخطة معتمدة للعرض — حقيقتان متناقضتان
    # في نفس اللحظة، وهو بالضبط ما يُفقد الواجهة مصداقيتها (§A).
    #
    # الحسم الآن: **نحجز الجلسة أولًا** (CAS) — إن لم تكن GENERATING
    # فالحقيقة محسومة من الكلب ولا نكتب خطة ولا نقلب حالة مشروع.
    claimed = _finish_generating(
        sessions, row_id, state="COMPLETED", plan_id=None,
        actual_provider=tracked.record.provider,
        actual_model=tracked.record.model,
    )
    if not claimed:
        emit("PLANNING_RESULT_DISCARDED", {
            "session_id": row_id,
            "reason": "حُسمت الجلسة نهائيًا (مهلة/انقطاع) قبل وصول "
                      "الخطة — لا تدوين ولا قلب حالة مشروع فوق حقيقة "
                      "موثّقة",
            "current_state": _current_state(sessions, row_id),
            "late_plan_chars": len(json.dumps(plan_data, ensure_ascii=False)),
        })
        done.set()
        return
    try:
        plan = engine.record_generated_plan(
            project_id, plan_data,
            generated_by=tracked.record.view(),
            previous_failure=previous_failure,
        )
    except Exception as error:  # noqa: BLE001 — فشل التدوين صريح
        # جلسة COMPLETED بلا خطة = كذبة؛ نصحّحها فورًا (وهذا الاستثناء
        # الوحيد المسموح: لا خطة دُوّنت فلا تناقض مع حقيقة دائمة).
        _finish_failed(sessions, row_id, project_id, "PLANNING_ERROR",
                       f"الخطة وُلدت لكن تعذر تدوينها: {error}", emit,
                       on_live_event, done, allow_from_completed=True)
        return
    _attach_plan_id(sessions, row_id, plan["id"])
    emit("PLAN_CREATED", {
        "session_id": row_id, "plan_id": plan["id"],
        "version": plan["version"], "phases": len(plan["phases"]),
        "provider": tracked.record.provider, "model": tracked.record.model,
        "duration_ms": tracked.record.duration_ms,
    })
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
                   event_kind: str = "PLANNING_FAILED",
                   allow_from_completed: bool = False) -> None:
    """فشل صريح — صف الجلسة + المشروع DRAFT بخطأ + حدث مصنّف.

    ``allow_from_completed``: استثناء واحد معلن — جلسة وُسمت COMPLETED
    بلا خطة دُوّنت (فشل ``record_generated_plan``) تُصحّح إلى FAILED،
    لأن «COMPLETED بلا خطة» كذبة لا حقيقة. غير ذلك لا كتابة فوق حسم.
    """
    if not _finish_generating(sessions, row_id, state="FAILED",
                              error_class=error_class,
                              error_detail=str(detail)[:800],
                              allow_from_completed=allow_from_completed):
        done.set()
        return   # حُسمت نهائيًا من الكلب — لا كتابة فوق حقيقته
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
# انتهاء الإيجار والمهلة الصلبة — كلب الجلسات (يستدعيه watchdog.py)
# ------------------------------------------------------------------ #

def _parse_dt(value):
    if not value:
        return None
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


def _pid_alive(pid: int | None) -> bool:
    """(013.5 §Q) هل العملية المالكة حيّة الآن؟ — استعلام قطعي لا تخمين.

    على ويندوز ``os.kill(pid, 0)`` **لا** يصلح كاختبار حياة (‏Python
    تحوّله إلى إشارة قتل فعلية للمعالج CTRL_*_EVENT). لذلك يُستخدم
    ``OpenProcess`` + ``GetExitCodeProcess``: فتح بمقبض استعلام فقط
    (‏PROCESS_QUERY_LIMITED_INFORMATION) ثم قراءة رمز الخروج — عملية
    ميتة تعطي ``STILL_ACTIVE`` مختلفًا، أو يفشل الفتح أصلًا.

    أي فشل غير متوقع يُعيد ``True`` (‏«افترض الحياة») — فالقانون
    البديل (‏LEASE_SECONDS) يبقى هو الحكم، ولا يُحسم صفّ خطأً بسبب
    قصور في المنصة.
    """
    if not pid or int(pid) <= 0:
        return True
    try:
        if _os.name == "nt":
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return False          # لا وجود لعملية بهذا المعرّف
            try:
                code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True
                return code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        _os.kill(int(pid), 0)         # POSIX: 0 = فحص صلاحية فقط
        return True
    except (OSError, ValueError, AttributeError):
        return False


def session_failure_verdict(row: dict, *, live_locally: bool) -> dict | None:
    """(013.5 §C) حكم حتمي على جلسة GENERATING — أو None إن كانت سليمة.

    القوانين مرتّبة، كل منها يحسم إلى حالة صريحة:

    0. **(013.5 §Q) موت العملية المالكة**: ``owner_pid`` معلوم وغير
       حيّ = INTERRUPTED في اللحظة، بلا انتظار انتهاء الإيجار. هذا
       هو القانون الذي جعل استرداد جلسة قُتل خادمها فوريًا بدل ‏123ث
       (النبضة كانت حديثة لحظة القتل، فلم يكن الإيجار قد انتهى).
    1. **سقف زمن الجدار** (``hard_deadline_at``): تجاوزه = MODEL_TIMEOUT
       حتمًا ولو كان الخيط حيًّا يرزح على طلب معلّق. هذا هو القانون
       الذي يمنع «PLANNING أبدية» حين يُعلّق المزود بلا رد.
    2. **موت العامل**: غياب ``heartbeat_at`` أطول من LEASE_SECONDS =
       العملية/الخيط مات = INTERRUPTED. **نبضة المؤقت لا تحمي من هذا
       القانون**: توقّفها هو الدليل نفسه.
    3. **صمت المزود والاستدعاء جارٍ**: لا نشاط حقيقي أطول من
       PROVIDER_SILENCE_LIMIT_SECONDS بينما العامل ينبض = MODEL_TIMEOUT
       برسالة أدق («المزود صامت») قبل السقف المطلق.

    ``live_locally`` يوجّه الرسالة فقط (عملية هذه العملية أم عملية
    ماتت) — لا يمنح حصانة من أي قانون.
    """
    now = _utc_now()
    # 0) (013.5 §Q) العملية المالكة ماتت — قطعي وفوري.
    owner = row.get("owner_pid")
    if owner and not _pid_alive(owner):
        beat = _parse_dt(row.get("heartbeat_at")) \
            or _parse_dt(row.get("last_activity_at"))
        idle = int((now - beat).total_seconds()) if beat else 0
        return {
            "error_class": "PLANNING_INTERRUPTED",
            "state": "INTERRUPTED",
            "reason": f"العملية المالكة ({int(owner)}) لم تعد موجودة — "
                      f"توقفت عند {idle}ث من آخر نبضة (لا انتظار إيجار)",
            "event": "PLANNING_INTERRUPTED",
        }
    # 1) السقف الصلب — المسجَّل صراحةً حصرًا (لا نخترع مهلة لصف قديم).
    deadline = _parse_dt(row.get("hard_deadline_at"))
    if deadline is not None and now > deadline:
        over = int((now - deadline).total_seconds())
        return {
            "error_class": "MODEL_TIMEOUT",
            "state": "FAILED",
            "reason": "تجاوزت المحاولة سقف زمن الجدار "
                      f"({int(HARD_TIMEOUT_SECONDS)}ث) بتجاوز {over}ث — "
                      "المزود لم يُكمل الرد",
            "event": "PLANNING_FAILED",
        }
    # 2) موت العامل — النبضة (أو آخر لمسة لصف قديم) متقادمة.
    beat = _parse_dt(row.get("heartbeat_at")) \
        or _parse_dt(row.get("last_activity_at"))
    if beat is not None:
        idle = (now - beat).total_seconds()
        if idle > LEASE_SECONDS:
            return {
                "error_class": "PLANNING_INTERRUPTED",
                "state": "INTERRUPTED",
                "reason": "توقفت نبضة العامل المولِّد منذ "
                          f"{int(idle)}ث (بلا نشاط مزود) — العملية "
                          "أو الخيط مات",
                "event": "PLANNING_INTERRUPTED",
            }
    # 3) صمت المزود والاستدعاء جارٍ — العامل حي والمزود لا يجيب.
    activity = _parse_dt(row.get("last_meaningful_activity_at")) \
        or beat
    if activity is not None:
        silence = (now - activity).total_seconds()
        if silence > PROVIDER_SILENCE_LIMIT_SECONDS:
            return {
                "error_class": "MODEL_TIMEOUT",
                "state": "FAILED",
                "reason": "المزود صامت منذ "
                          f"{int(silence)}ث بعد آخر نشاط حقيقي "
                          "مُثبت — لا رد ولا قطع",
                "event": "PLANNING_FAILED",
            }
    return None


def _apply_verdict(sessions, row: dict, verdict: dict) -> None:
    """تطبيق حكم الكلب — الحالة + المشروع + حدث صريح (§C)."""
    state = verdict["state"]
    error_class = verdict["error_class"]
    if not _finish_generating(sessions, row["id"], state=state,
                              error_class=error_class,
                              error_detail=verdict["reason"]):
        return
    service.update_project(
        sessions, row["project_id"], status="DRAFT",
        last_error=f"توقف توليد الخطة [{error_class}]: "
                   f"{verdict['reason']}",
    )
    service.add_event(
        sessions, row["project_id"], verdict["event"], {
            "session_id": row["id"], "error_class": error_class,
            "error_detail": verdict["reason"][:400],
            "lease_expires_at": row.get("lease_expires_at"),
            "hard_deadline_at": row.get("hard_deadline_at"),
            "last_meaningful_activity_at": row.get(
                "last_meaningful_activity_at"),
            "retry_available": True,
        },
    )


def _expire_stale_session(sessions, row: dict) -> None:
    """حكم على جلسة GENERATING مشكوك فيها (§7 + 013.5 §C)."""
    verdict = session_failure_verdict(
        row, live_locally=_is_live_locally(row["project_id"])
    )
    if verdict is None:
        return
    _apply_verdict(sessions, row, verdict)


def sweep_stale_sessions(sessions, *, active_project_ids: set[int]) -> list[dict]:
    """مسح كل جلسات GENERATING غير السليمة (013.4 §7 + 013.5 §C).

    يعيد قائمة الجلسات الموسومة — الكلب يستخدمها للإعلان والتشخيص.
    ``active_project_ids``: مشاريع لها حلقة نشطة في هذه العملية —
    **لم تعد حصانة**: المهلة الصلبة تُطبَّق على الجميع (§C.1).
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
        live = _is_live_locally(view["project_id"])
        verdict = session_failure_verdict(view, live_locally=live)
        if verdict is None:
            continue
        _apply_verdict(sessions, view, verdict)
        swept.append({**view, "verdict": verdict,
                      "live_locally": live})
    return swept


def enforce_invariant(sessions) -> list[dict]:
    """(013.5 §C) الحارس المطلق: PLANNING بلا جلسة حية = شذوذ.

    الشرط الذي يكسر قبول 013.5: ``project.status == PLANNING`` لساعات
    بينما لا جلسة GENERATING بإيجار صالح ولا نشاط مزود. تلتقط هذه
    الدالة كل شكل من أشكال ذلك (جلسة مفقودة، جلسة منتهية، جلسة في
    حالة غير مسموحة) وتعيد المشروع إلى DRAFT بخطأ صريح + حدث.
    """
    from sqlalchemy import select

    from workflow.models import Project

    healed: list[dict] = []
    with sessions() as session:
        projects = session.scalars(
            select(Project).where(Project.status == "PLANNING")
        ).all()
        project_ids = [int(p.id) for p in projects]

    for project_id in project_ids:
        row = latest_session(sessions, project_id)
        healthy = False
        if row is not None and row["state"] == "GENERATING":
            verdict = session_failure_verdict(
                row, live_locally=_is_live_locally(project_id)
            )
            healthy = verdict is None
            if verdict is not None:
                _apply_verdict(sessions, row, verdict)
        if healthy:
            continue
        # (013.5 §C) PLANNING بلا مولِّد صالح — لا يُترك لحظة واحدة.
        reason = (
            "PLANNING بلا جلسة توليد صالحة — المشروع أُعيد DRAFT "
            "(حارس الثبات §C)"
            if row is not None else
            "PLANNING بلا أي جلسة توليد — المشروع أُعيد DRAFT "
            "(حارس الثبات §C)"
        )
        service.update_project(sessions, project_id, status="DRAFT",
                               last_error=reason)
        service.add_event(sessions, project_id, "PLANNING_INVARIANT_HEALED", {
            "session_id": (row or {}).get("id"),
            "session_state": (row or {}).get("state"),
            "reason": reason,
            "retry_available": True,
        })
        healed.append({"project_id": project_id,
                       "session_id": (row or {}).get("id"),
                       "session_state": (row or {}).get("state"),
                       "reason": reason})
    return healed


def recover_at_startup(sessions) -> dict:
    """(013.5 §C.4) استرداد صادق عند إقلاع العملية.

    الجذر الحي لعطل 013.4: الكلب كان يُشغَّل **فقط** عند إطلاق حلقة
    تنفيذ، فمشروع مات مولّده أثناء التخطيط بقي PLANNING 17992ث بلا
    أي فحص بعد إعادة التشغيل. هذا النداء يُنفَّذ عند إنشاء التطبيق
    وقبل خدمة أي طلب: يمسح الجلسات الميتة ثم يفرض الثبات.
    """
    swept = sweep_stale_sessions(sessions, active_project_ids=set())
    healed = enforce_invariant(sessions)
    return {
        "swept_sessions": [s["id"] for s in swept],
        "swept_verdicts": [
            {"session_id": s["id"], "state": s["verdict"]["state"],
             "error_class": s["verdict"]["error_class"]}
            for s in swept
        ],
        "healed_projects": healed,
        "healthy": not swept and not healed,
    }


def wait_for_planning(sessions, project_id: int, *,
                      timeout: float = 30.0) -> dict:
    """انتظار استقرار التخطيط (اختبارات/إجراءات صريحة).

    (013.5 §C) الاستقرار الحقيقي شرطان معًا، لا واحد:
    ``project.status != PLANNING`` **و** لا جلسة GENERATING حية.
    الشرط الثاني وحده كان يكفي ليعود الانتظار لحظة وسم الجلسة FAILED
    بينما سلسلة الإعادة الآلية تفتح جلسة جديدة وتعيد PLANNING —
    فيرى المستدعي «فشل» ثم يجد المشروع PLANNING (سباق موثّق).

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
        project = service.get_project(sessions, int(project_id)) or {}
        if last["state"] in TERMINAL_SESSION_STATES and \
                project.get("status") != "PLANNING":
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
        f"التخطيط لم يستقر خلال {timeout}ث — آخر حالة: "
        f"{(last or {}).get('state', '?')}"
    )


__all__ = [
    "PlanningError",
    "session_failure_verdict",
    "latest_session",
    "session_view",
    "start_planning",
    "sweep_stale_sessions",
    "enforce_invariant",
    "recover_at_startup",
    "wait_for_planning",
    "LEASE_SECONDS",
    "HEARTBEAT_SECONDS",
    "HARD_TIMEOUT_SECONDS",
    "SESSION_STATES",
    "TERMINAL_SESSION_STATES",
]
