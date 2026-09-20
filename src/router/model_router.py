"""موجّه النماذج النحيف — <600 سطر التزامًا (design-principles.md المبدأ 6).

سِجِل القرار: v1 حمل التبريد وسلسلة التبدّل وحد المعدل داخل الموجّه
(4,239 سطرًا). الأمر الثالث نقلها **حزمًا مستقلة** في src/router/
(rate_limiter + failover_chain + cooling_loop — بلا اعتماديات، إعدادات
dict) والموجّه يبقى منسقًا فقط:

    chat(messages, provider_id, model)
      1) rate_limiter.acquire()        → إذا لم يُسمح: انتظر (⏳)
      2) cooling_loop.execute_with_…() → إذا اختناق (429): صبر (🧊)
      3) failover_chain.execute_with_…() → إذا انهيار (5xx): تبدّل (🔄)
      4) النقل (mock فقط في هذه المرحلة — لا استدعاءات LLM حقيقية بعد)

التركيب من الخارج (wiring): الحزم تُبنى افتراضيًا من ProviderConfig
(as_dicts) وتُبث أحداثها عبر on_event واحدة — ومن يبني الموجّه يملك
توجيه الأحداث (البث مسؤولية الطبقة الأعلى، لا الحزم).

الأحداث: rate_limit.wait (الموجّه) + cooling.cooldown (الحزمة) +
failover.logged (الحزمة) + router.call.logged الختامي (الموجّه):
{provider, model, tokens, duration_ms, cooled, failed_over}.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from core.config import provider_settings
from router.cooling_loop import CoolingLoop
from router.failover_chain import FailoverChain
from router.rate_limiter import RateLimiter


class Provider(str, Enum):
    """أسماء المزودات — بلا أي منطق تبريد/تبديل هنا (الحزم تملكه)."""

    MOCK = "mock"                    # محلي دائمًا — للاختبار والتجريب
    OLLAMA = "ollama"                # محلي
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"  # أي نقطة متوافقة (OpenRouter…)


@dataclass(frozen=True)
class ProviderSpec:
    """مواصفة مزود — بيانات فقط، لا سلوك."""

    name: Provider
    key_required: bool
    base_url: str = ""


PROVIDERS: dict[Provider, ProviderSpec] = {
    Provider.MOCK: ProviderSpec(name=Provider.MOCK, key_required=False),
    Provider.OLLAMA: ProviderSpec(
        name=Provider.OLLAMA, key_required=False, base_url="http://127.0.0.1:11434"
    ),
    Provider.OPENAI: ProviderSpec(
        name=Provider.OPENAI,
        key_required=True,
        base_url="https://api.openai.com/v1",
    ),
    Provider.ANTHROPIC: ProviderSpec(
        name=Provider.ANTHROPIC,
        key_required=True,
        base_url="https://api.anthropic.com",
    ),
    Provider.OPENAI_COMPATIBLE: ProviderSpec(
        name=Provider.OPENAI_COMPATIBLE, key_required=True
    ),
}


@dataclass
class ChatMessage:
    """رسالة محادثة موحدة عبر كل المزودات."""

    role: str  # "system" | "user" | "assistant"
    content: str


class ProviderCallError(Exception):
    """خطأ نقل مزود — تصنيفه بسمات صريحة تقرؤها الحزم بطرفية.

    is_throttle:      429/503-overloaded — يدخل حلقة التبريد.
    is_server_error:  5xx غير الاختناقي — إعادات ثم تبدّل.
    is_timeout:       انتهت مهلة الاتصال/الفتحة — كخطأ خادم.
    retry_after:      ثواني رأس Retry-After إن أرسلها المزود.
    """

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        is_throttle: bool = False,
        is_server_error: bool = False,
        is_timeout: bool = False,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.is_throttle = is_throttle
        self.is_server_error = is_server_error
        self.is_timeout = is_timeout
        self.retry_after = retry_after


class RateLimitBlocked(RuntimeError):
    """حد المعدل ما زال مرفوعًا بعد انتظارات الموجّه المحدودة."""


class ModelRouter:
    """المنسّق النحيف بين الحزم الثلاث — لا يملك أي منطق حماية بنفسه.

    default construction يبني الحزم من ProviderConfig ويوصل أحداثها
    كلها بمخرج واحد (on_event). الحزم المحقونة تحتفظ بتوصيلها الخاص.
    """

    def __init__(
        self,
        *,
        rate_limiter: RateLimiter | None = None,
        failover_chain: FailoverChain | None = None,
        cooling_loop: CoolingLoop | None = None,
        default_provider: Provider | str = Provider.MOCK,
        transports: dict[str, Callable[[str, list[ChatMessage]], str]]
        | None = None,
        on_event: Callable[[dict], None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_rate_waits: int = 3,
        slot_timeout: float = 30.0,
    ) -> None:
        cfg = provider_settings.as_dicts()
        self._limiter = rate_limiter or RateLimiter(cfg["rate_limiter"])
        self._failover = failover_chain or FailoverChain(
            [Provider.MOCK.value], cfg["failover"], on_event=on_event
        )
        self._cooling = cooling_loop or CoolingLoop(
            cfg["cooling"], on_event=on_event
        )
        if isinstance(default_provider, Provider):
            self.default_provider = default_provider.value
        else:
            self.default_provider = str(default_provider)
        self._transports = dict(transports or {})
        self._on_event = on_event
        self._sleeper = sleeper
        self._max_rate_waits = max(1, int(max_rate_waits))
        self._slot_timeout = float(slot_timeout)
        self.events: list[dict] = []

    # ------------------------------------------------------------ #
    # التسجيل — أحداث الموجّه (حد المعدل + سجل الاستدعاء)
    # ------------------------------------------------------------ #

    def _emit(self, event: dict) -> None:
        self.events.append(event)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001 — المستقبِل لا يكسر الاستدعاء
                pass

    # ------------------------------------------------------------ #
    # سجل المزودات (بيانات فقط — يعمل منذ التأسيس)
    # ------------------------------------------------------------ #

    def spec(self, provider: Provider | None = None) -> ProviderSpec:
        """مواصفة مزود مسجل — KeyError مستحيل (الجدول مغلق)."""
        name = provider or Provider(self.default_provider)
        return PROVIDERS[name]

    # ------------------------------------------------------------ #
    # الاستدعاء الموحد — acquire → cool → failover → نقل
    # ------------------------------------------------------------ #

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        provider_id: Provider | str | None = None,
        model: str | None = None,
    ) -> dict:
        """استدعاء مزود عبر حمايات v1 الثلاث المنقولة.

        1) acquire: بوابة حد المعدل — رفضٌ يعني انتظارًا (حدث ⏳) ثم
           إعادة فحص؛ استمرار الرفض بعد max_rate_waits = RateLimitBlocked.
        2) التبريد يلفّ التبدّل: الاختناق (429) يُسجَّل في المحدد
           (note_429) ثم يُبرَّد عليه بنفس المزود قبل أي تبدّل —
           لا انتظار مزدوج أبدًا (كل انتظار له مالك واحد).
        3) التبدّل داخل التبريد: 5xx/مهلة عضو → إعادتان → العضو التالي.

        يعيد dict: {text, provider, model, tokens, duration_ms, cooled,
        failed_over} — والحدث الكامل router.call.logged يُبث قبل العودة.
        """
        if isinstance(provider_id, Provider):
            pid = provider_id.value
        else:
            pid = str(provider_id or self.default_provider)
        model_name = model or "mock-v2"
        started = time.monotonic()
        est_tokens = self._estimate_tokens(messages)

        # 1) بوابة حد المعدل — انتظار محدود (v1: محاولة واحدة ثم حجب؛
        #    v2: حتى max_rate_waits انتظارات ثم استثناء صريح)
        allowed = False
        for attempt in range(1, self._max_rate_waits + 1):
            allowed, wait = self._limiter.acquire(pid, est_tokens)
            if allowed:
                break
            self._emit(
                {
                    "kind": "rate_limit.wait",
                    "provider": pid,
                    "wait_seconds": round(wait, 2),
                    "attempt": attempt,
                }
            )
            self._sleeper(max(wait, 0.01))
        if not allowed:
            raise RateLimitBlocked(
                f"حد المعدل ما زال مرفوعًا لمزود {pid} بعد "
                f"{self._max_rate_waits} انتظارات"
            )

        def _call(provider: str) -> str:
            """نقل واحد لعضو السلسلة — فتحة التزامن حول النقل فقط (v1)."""
            ok, _waited = self._limiter.acquire_slot(
                provider, timeout=self._slot_timeout
            )
            if not ok:
                raise ProviderCallError(
                    f"انتهت مهلة انتظار فتحة التزامن لمزود {provider}",
                    is_timeout=True,
                )
            try:
                return self._transport(provider, model_name, messages)
            finally:
                self._limiter.release_slot(provider)

        def _cooled_call() -> str:
            try:
                return active.execute_with_failover(_call)
            except Exception as exc:  # noqa: BLE001 — تغذية المحدد فقط
                if getattr(exc, "is_throttle", False):
                    # 429 فعلية: تبريد المحدد قبل حلقة التبريد (كما في
                    # v1 — المنسق كان يفعلها قبل _throttle_cool)
                    self._limiter.note_429(pid)
                raise

        # سلسلة التبدّل للاستدعاء: سلسلة الموجّه إن كان مزود الطلب عضوًا
        # فيها، وإلا سلسلة أحادية صريحة (لا احتياطي معروف لهذا المزود —
        # إعلان لا تخمين). الاختناق يُبرَّد عليه بنفس المزود قبل أي تبدّل.
        active = (
            self._failover
            if pid in self._failover.providers
            else FailoverChain([pid], self._failover.config, sleeper=self._sleeper)
        )
        text = self._cooling.execute_with_cooling(_cooled_call)

        duration_ms = int((time.monotonic() - started) * 1000)
        tokens = max(1, len(text) // 4)
        self._limiter.record_tokens(pid, tokens)
        cx = dict(self._cooling.last_execution or {})
        fx = dict(active.last_execution or {})
        result = {
            "text": text,
            "provider": fx.get("provider") or pid,
            "model": model_name,
            "tokens": tokens,
            "duration_ms": duration_ms,
            "cooled": bool(cx.get("cooled")),
            "cooling_waits": int(cx.get("waits", 0) or 0),
            "failed_over": bool(fx.get("failed_over")),
            "failover_from": fx.get("from"),
        }
        self._emit({"kind": "router.call.logged", **result})
        return result

    # ------------------------------------------------------------ #
    # النقل — mock فقط في هذه المرحلة (لا استدعاءات LLM حقيقية بعد)
    # ------------------------------------------------------------ #

    def _transport(
        self, provider: str, model: str, messages: list[ChatMessage]
    ) -> str:
        transport = self._transports.get(provider)
        if transport is not None:
            return transport(model, messages)
        if provider == Provider.MOCK.value:
            return self._mock_transport(model, messages)
        raise ProviderCallError(
            f"لا نقل مسجَّل للمزود '{provider}' — النقل الحقيقي يُضاف في "
            "أمر الاستدعاءات الحية؛ mock متاح دائمًا",
        )

    @staticmethod
    def _mock_transport(model: str, messages: list[ChatMessage]) -> str:
        """نقل mock حتمي — أول رد مستخدم مقتطعًا (لا ادعاء توليد)."""
        user_text = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            messages[-1].content if messages else "",
        )
        return f"[mock:{model}] {user_text[:80]}"

    @staticmethod
    def _estimate_tokens(messages: list[ChatMessage]) -> int:
        """تقدير خشن (~4 محارف/توكن) — يُصحَّح بالفعل بعد النجاح."""
        return sum(len(m.content) for m in messages) // 4 + 32
