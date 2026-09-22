"""تتبع استدعاءات النموذج (013.4 §4) — لا انتظار صامت لمزود أبدًا.

كل استدعاء نموذج يمر من هنا يحمل عقدًا كاملًا قابلًا للفحص:

    request_id · provider · model · started_at · completed_at
    · heartbeat (لمس أثناء التنفيذ) · retry_count
    · فشل مصنّف: MODEL_TIMEOUT / PROVIDER_QUOTA /
      PROVIDER_UNAVAILABLE / PROVIDER_AUTH_ERROR /
      MODEL_RESPONSE_INVALID / PROVIDER_NOT_CONFIGURED

الغاية (§3): الواجهة تقول «ينتظر المزود X — الطلب Y — مضى 40ث»
لا «Planning…» إلى ما لا نهاية. التتبع غلاف فوق الموجّه القائم —
لا منطق اختيار جديد ولا إعادة محاولة داخلية (الموجّه يملكها).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CallRecord:
    """سجل استدعاء واحد — يُبث كأحداث ويُخزن في جلسة التخطيط."""

    request_id: str
    purpose: str                 # planning | role:thinker | …
    provider: str = ""
    model: str = ""
    started_at: str = field(default_factory=_now_iso)
    heartbeat_at: str = field(default_factory=_now_iso)
    completed_at: str = ""
    retry_count: int = 0
    duration_ms: int = 0
    error_class: str = ""
    error_detail: str = ""
    tokens: int | None = None
    streamed: bool = False

    def touch(self) -> None:
        """نبضة — الاستدعاء الطويل يثبت حياته (013.4 §3)."""
        self.heartbeat_at = _now_iso()

    def view(self) -> dict:
        return {
            "request_id": self.request_id,
            "purpose": self.purpose,
            "provider": self.provider,
            "model": self.model,
            "started_at": self.started_at,
            "heartbeat_at": self.heartbeat_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "error_class": self.error_class,
            "error_detail": self.error_detail[:400],
        }


def classify_failure(error: BaseException) -> tuple[str, str]:
    """تصنيف صادق لفشل الاستدعاء (§4) — (error_class, detail).

    الخريطة حتمية من أنواع الموجّه المعروفة:
    - TimeoutError/socket.timeout أو is_timeout → MODEL_TIMEOUT
    - 429/اختناق → PROVIDER_QUOTA
    - 5xx/خادم/شبكة → PROVIDER_UNAVAILABLE
    - 401/403/مفتاح → PROVIDER_AUTH_ERROR
    - رد غير صالح ضد العقد → MODEL_RESPONSE_INVALID
    - لا نقل حي → PROVIDER_NOT_CONFIGURED
    - غير ذلك → PROVIDER_ERROR (صريح لا صامت)
    """
    from router.model_router import ProviderCallError

    text = str(error)
    name = type(error).__name__
    if isinstance(error, ProviderCallError):
        if getattr(error, "is_timeout", False):
            return "MODEL_TIMEOUT", text
        lowered = text.lower()
        if "429" in text or "اختناق" in text or "throttl" in lowered:
            return "PROVIDER_QUOTA", text
        if ("401" in text or "403" in text or "مفتاح" in text
                or "auth" in lowered or "unauthorized" in lowered):
            return "PROVIDER_AUTH_ERROR", text
        if ("لا نقل حي" in text or "لا مواصفة حية" in text
                or "لا نموذج محدد" in text):
            return "PROVIDER_NOT_CONFIGURED", text
        if getattr(error, "is_server_error", False) or "5xx" in text \
                or "خادم" in text or "server" in lowered:
            return "PROVIDER_UNAVAILABLE", text
        return "PROVIDER_ERROR", text
    # عقد الخطة (PlannerError/عقد pydantic) — فشل صياغة الرد لا المزود
    try:
        from workflow.planner import PlannerError

        if isinstance(error, PlannerError):
            return "MODEL_RESPONSE_INVALID", text[:400]
    except ImportError:
        pass
    if name in ("TimeoutError", "socket.timeout", "URLError") or \
            "timed out" in lowered_safe(text):
        return "MODEL_TIMEOUT", text
    # عقد الرد (pydantic/JSON) — فشل الصياغة لا فشل المزود
    module = type(error).__module__ or ""
    if "pydantic" in module or isinstance(error, ValueError):
        return "MODEL_RESPONSE_INVALID", text[:400]
    return "PROVIDER_ERROR", text


def lowered_safe(text: str) -> str:
    return text.lower()


class TrackedCall:
    """غلاف استدعاء واحد — ينبض ويُذيع ويصنّف الفشل.

    الاستخدام:

        tracked = TrackedCall(purpose="planning", on_event=emit)
        try:
            outcome = tracked.run(router.chat_live, messages, ...)
        except Exception as error:
            classification = tracked.classify(error)
            …
    """

    #: فترة النبضة أثناء انتظار المزود — خيط مرافق يلمس السجل.
    HEARTBEAT_INTERVAL_S = 2.0

    def __init__(self, purpose: str, *,
                 on_event: Callable[[str, dict], None] | None = None,
                 provider: str = "", model: str = ""):
        self.record = CallRecord(
            request_id=f"req-{uuid.uuid4().hex[:12]}", purpose=purpose,
            provider=provider, model=model,
        )
        self._on_event = on_event
        self._stop = threading.Event()

    # -- أحداث ------------------------------------------------------- #

    def _emit(self, kind: str, extra: dict | None = None) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(kind, {**self.record.view(),
                                  **(extra or {})})
        except Exception:  # noqa: BLE001 — المستقبِل لا يكسر الاستدعاء
            pass

    # -- التنفيذ ----------------------------------------------------- #

    def run(self, call: Callable[..., Any], *args, **kwargs) -> Any:
        """تنفيذ الاستدعاء المتتبَّع — بدء ← نبض ← إتمام/فشل.

        الاستدعاء نفسه كما هو: التتبع غلاف مراقبة لا يعيد المحاولة
        ولا يخترق مهلات الموجّه — التصنيف عند الفشل يحدث في
        classify() ويصل المستدعي ليقرر الإعادة (§4: سياسة الإعادة
        للمنسق، ليس للمتتبع).
        """
        self._emit("MODEL_CALL_STARTED")
        heartbeat = threading.Thread(
            target=self._beat, daemon=True,
            name=f"aes-call-heartbeat[{self.record.request_id}]",
        )
        heartbeat.start()
        started = time.monotonic()
        try:
            outcome = call(*args, **kwargs)
            self.record.duration_ms = int(
                (time.monotonic() - started) * 1000
            )
            self.record.completed_at = _now_iso()
            if isinstance(outcome, dict):
                self.record.provider = str(
                    outcome.get("provider") or self.record.provider
                )
                self.record.model = str(
                    outcome.get("model") or self.record.model
                )
                self.record.tokens = outcome.get("tokens")
                self.record.streamed = bool(outcome.get("streamed"))
            self._emit("MODEL_CALL_COMPLETED", {
                "duration_ms": self.record.duration_ms,
                "streamed": self.record.streamed,
            })
            return outcome
        except BaseException as error:  # noqa: BLE001 — التصنيف ثم الرمي
            self.record.duration_ms = int(
                (time.monotonic() - started) * 1000
            )
            self.record.completed_at = _now_iso()
            error_class, detail = classify_failure(error)
            self.record.error_class = error_class
            self.record.error_detail = detail
            self._emit("MODEL_CALL_FAILED", {
                "duration_ms": self.record.duration_ms,
                "error_class": error_class,
            })
            raise
        finally:
            self._stop.set()
            heartbeat.join(timeout=1.0)

    def classify(self, error: BaseException) -> tuple[str, str]:
        """تصنيف فشل تم التقاطه خارج run() — نفس خريطة classify_failure."""
        error_class, detail = classify_failure(error)
        if not self.record.error_class:
            self.record.error_class = error_class
            self.record.error_detail = detail
            self.record.completed_at = _now_iso()
        return error_class, detail

    def _beat(self) -> None:
        while not self._stop.wait(self.HEARTBEAT_INTERVAL_S):
            self.record.touch()


__all__ = [
    "CallRecord",
    "TrackedCall",
    "classify_failure",
]
