"""محدد المعدل لكل مزود — وحدة مستقلة منقولة من v1 (الأمر الثالث).

الأصل: backend/services/rate_limiter.py في v1 (379 سطرًا) — نقلٌ حرفي
للخوارزمية مع استبدال مصدر الإعداد فقط:

  v1: صف rate_limits في قاعدة بيانات + epoch cache + settings_service
  v2: معامل dict في البناء (+ configure لكل مزود) — لا قاعدة بيانات

جذر الحماية (من v1، الأمر 13 جزء 0): مفتاح NVIDIA المجاني محدود بـ40
طلبًا/دقيقة، والدورة الواحدة تستهلك طلبات متتالية — فتُحجب الخطة
بـ HTTP 429 قبل أن يكتمل أي عمل. المنظم هنا:

1) acquire(provider, est_tokens) قبل كل استدعاء: فترة تبريد نشطة ←
   الفاصل الأدنى ← نافذة الدقيقة المنزلقة (rpm) ← سقف التوكنات (tpm)
   — يعيد (مسموح؟، ثواني الانتظار) ولا يسجل شيئًا عند الرفض.
2) note_429(provider) عند استجابة 429 فعلية: تبريد إجباري كامل.
3) إشارة لكل مزود (semaphore، concurrency=1 افتراضيًا): استدعاء واحد
   متزامن لكل مزود — acquire_slot/release_slot يلفان كل طلب فعلي.
4) status(provider): الحالة الحية للواجهة (طلبات الدقيقة N/40…).

خيط-آمن بالكامل — بلا أي تبعيات خارج stdlib (استقلالية الأمر الثالث).
السقف الدائم: <300 سطر (مُرسّخ في tests/contracts/test_thinness.py).
"""

from __future__ import annotations

import threading
import time
from collections import deque

#: الإعداد الافتراضي لكل مزود — نفس قيم نفيديا المجاني في v1
#: (DEFAULTS_NVIDIA): المورد النادر هو الطلبات لا التوكنات.
DEFAULT_CONFIG: dict = {
    "rpm": 40,             # طلبات في الدقيقة (0 = بلا حد)
    "tpm": 0,              # توكنات في الدقيقة (0 = بلا حد — سقف الإخراج مفتوح)
    "min_interval": 1.5,   # أقل فاصل بين طلبين (ثوانٍ)
    "cooldown": 60,        # تبريد إجباري عند 429 (ثوانٍ)
    "concurrency": 1,      # استدعاء واحد متزامن لكل مزود
}


class _ProviderState:
    """حالة عدادات مزود واحد — تُدار تحت قفل المحدد (كما في v1)."""

    __slots__ = (
        "config", "window", "cooldown_until", "last_request",
        "total_429", "semaphore", "waiting", "total_waits",
    )

    def __init__(self, config: dict):
        self.config = dict(config)
        self.window: deque[tuple[float, int]] = deque()  # (الوقت، التوكنات)
        self.cooldown_until: float = 0.0
        self.last_request: float | None = None
        self.total_429 = 0
        self.waiting = 0       # خيوط تنتظر الإشارة الآن (للواجهة ⏳)
        self.total_waits = 0
        concurrency = max(1, int(self.config.get("concurrency", 1) or 1))
        self.semaphore = threading.BoundedSemaphore(concurrency)

    def refresh_semaphore(self) -> None:
        """إعادة بناء الإشارة عند تغيّر concurrency في الإعداد."""
        new_c = max(1, int(self.config.get("concurrency", 1) or 1))
        current = getattr(self.semaphore, "_initial_value", new_c)
        if new_c != current:
            self.semaphore = threading.BoundedSemaphore(new_c)


class RateLimiter:
    """محدد معدل خيط-آمن لكل معرفات المزودات — إعدادات dict لا قاعدة."""

    def __init__(
        self,
        config: dict | None = None,
        *,
        clock: "callable" = time.monotonic,
    ) -> None:
        """
        config: الحدود الافتراضية لكل مزود (مفاتيح DEFAULT_CONFIG).
        clock:  ساعة قابلة للحقن للاختبار — الخوارزمية نفسها لا تتغير.
        """
        self._default = {**DEFAULT_CONFIG, **(config or {})}
        self._overrides: dict[str, dict] = {}
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, _ProviderState] = {}

    def configure(self, provider_id: str, config: dict) -> None:
        """حدود خاصة بمزود واحد (تنسخ فوق الافتراضي) — لكل بطاقة مزود."""
        with self._lock:
            self._overrides[provider_id] = {
                **self._default, **(config or {})
            }
            self._states.pop(provider_id, None)  # يُبنى بالإعداد الجديد

    def _state(self, provider_id: str) -> _ProviderState:
        """حالة المزود — تُنشأ عند أول استخدام (الإعداد: الخاص > الافتراضي)."""
        with self._lock:
            st = self._states.get(provider_id)
            if st is None:
                cfg = self._overrides.get(provider_id, self._default)
                st = _ProviderState(cfg)
                self._states[provider_id] = st
            else:
                st.refresh_semaphore()
            return st

    # ------------------------------------------------------------ #
    # الواجهة الأساسية — نفس خوارزمية v1 حرفيًا
    # ------------------------------------------------------------ #

    def acquire(
        self, provider_id: str, estimated_tokens: int = 1000
    ) -> tuple[bool, float]:
        """
        حجز طلب جديد لدى المزود.

        يعيد (True, 0.0) إذا سُمح فورًا وسُجل الطلب، أو (False,
        wait_seconds) إذا كان لا بد من الانتظار (تبريد 429 / فاصل
        أدنى / نافذة الدقيقة / سقف التوكنات). لا يُسجل أي شيء عند
        الرفض — الاستدعاء يعيد المحاولة بعد الانتظار.
        """
        st = self._state(provider_id)
        cfg = st.config
        now = self._clock()

        # 1) فترة تبريد نشطة (بعد 429 حقيقية) — تُفحص قبل كل شيء
        with self._lock:
            remaining_cd = st.cooldown_until - now
            if remaining_cd > 0:
                return False, remaining_cd

        if (
            not cfg.get("rpm", 0)
            and not cfg.get("min_interval", 0)
            and not cfg.get("tpm", 0)
        ):
            with self._lock:  # مزود بلا حدود (mock) — إحصاء خفيف فقط
                st.last_request = self._clock()
                st.window.append((st.last_request, int(estimated_tokens)))
            return True, 0.0

        with self._lock:
            # 2) الفاصل الأدنى بين الطلبات
            min_interval = float(cfg.get("min_interval", 0) or 0)
            if st.last_request is not None and min_interval > 0:
                since = now - st.last_request
                if since < min_interval:
                    return False, min_interval - since

            # 3) تنظيف نافذة الدقيقة ثم فحص rpm (منزلقة: أقدم طلب يحررها)
            cutoff = now - 60.0
            while st.window and st.window[0][0] < cutoff:
                st.window.popleft()
            rpm = int(cfg.get("rpm", 0) or 0)
            if rpm > 0 and len(st.window) >= rpm:
                wait = st.window[0][0] + 60.0 - now
                return False, max(wait, 0.05)

            # 4) فحص tpm
            tpm = int(cfg.get("tpm", 0) or 0)
            used = sum(t for _, t in st.window)
            if tpm > 0 and used + int(estimated_tokens) > tpm:
                wait = st.window[0][0] + 60.0 - now if st.window else 5.0
                return False, max(wait, 0.05)

            # مسموح — تسجيل الطلب
            st.window.append((now, int(estimated_tokens)))
            st.last_request = now
            return True, 0.0

    # ------------------------------------------------------------ #
    # إشارة التزامن لكل مزود (concurrency=1) — كما في v1 0.16.0
    # ------------------------------------------------------------ #

    def acquire_slot(
        self, provider_id: str, timeout: float = 600.0
    ) -> tuple[bool, float]:
        """
        حجز فتحة استدعاء متزامن — (True, waited_seconds) عند الحصول،
        أو (False, timeout) عند انتهاء المهلة (لا حجب إلى الأبد أبدًا).
        """
        st = self._state(provider_id)
        started = time.monotonic()
        with self._lock:
            st.waiting += 1
            st.total_waits += 1
        try:
            acquired = st.semaphore.acquire(timeout=max(0.1, float(timeout)))
        finally:
            with self._lock:
                st.waiting = max(0, st.waiting - 1)
        waited = time.monotonic() - started
        return bool(acquired), waited

    def release_slot(self, provider_id: str) -> None:
        """تحرير الفتحة — يجب أن يتبع كل acquire_slot ناجح."""
        st = self._state(provider_id)
        try:
            st.semaphore.release()
        except ValueError:
            pass  # تحرير زائد بعد تجدد الإشارة — حالة قديمة آمنة

    # ------------------------------------------------------------ #
    # التغذية الراجعة من الاستجابات الفعلية
    # ------------------------------------------------------------ #

    def note_429(self, provider_id: str) -> float:
        """تسجيل استجابة 429 فعلية — تبريد إجباري كامل. يعيد ثوانيه."""
        st = self._state(provider_id)
        cooldown = float(st.config.get("cooldown", 60) or 0)
        with self._lock:
            st.cooldown_until = self._clock() + cooldown
            st.total_429 += 1
        return cooldown

    def record_tokens(
        self, provider_id: str, actual_tokens: int
    ) -> None:
        """تصحيح التوكنات المقدرة بالفعلية بعد نجاح الاستدعاء (v1)."""
        if actual_tokens <= 0:
            return
        st = self._state(provider_id)
        with self._lock:
            if st.window:
                t, _estimated = st.window[-1]
                st.window[-1] = (t, int(actual_tokens))

    # ------------------------------------------------------------ #
    # الحالة الحية للواجهة
    # ------------------------------------------------------------ #

    def status(self, provider_id: str) -> dict:
        """شريط الحالة الحي: طلبات الدقيقة N/rpm، المتبقي، التبريد."""
        st = self._state(provider_id)
        now = self._clock()
        with self._lock:
            cutoff = now - 60.0
            while st.window and st.window[0][0] < cutoff:
                st.window.popleft()
            requests_last_minute = len(st.window)
            tokens_last_minute = sum(t for _, t in st.window)
            cooldown_remaining = max(0.0, st.cooldown_until - now)
        rpm = int(st.config.get("rpm", 0) or 0)
        return {
            "provider": provider_id,
            "rpm": rpm,
            "min_interval": float(st.config.get("min_interval", 0) or 0),
            "concurrency": int(st.config.get("concurrency", 1) or 1),
            "requests_last_minute": requests_last_minute,
            "tokens_last_minute": tokens_last_minute,
            "remaining_this_minute": (
                max(0, rpm - requests_last_minute) if rpm else None
            ),
            "window_full": bool(rpm and requests_last_minute >= rpm),
            "cooldown_remaining": round(cooldown_remaining, 1),
            "total_429": st.total_429,
            "waiting_on_semaphore": st.waiting,
            "total_semaphore_waits": st.total_waits,
        }

    def window_full(self, provider_id: str) -> bool:
        """هل نافذة الدقيقة ممتلئة الآن؟ (مهلة عند الامتلاء = اختناق)."""
        return bool(self.status(provider_id).get("window_full"))
