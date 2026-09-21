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

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from core.config import live_model_settings, provider_settings
from router.cooling_loop import CoolingLoop
from router.failover_chain import FailoverChain
from router.rate_limiter import RateLimiter
from router.live_providers import (  # noqa: F401 — إعادة تصدير契约 العقد القديم
    BUILTIN_LIVE_PROVIDERS,
    ProviderCallError,
    _resolve_provider_credentials,
    resolve_live_providers,
)


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
        #: النموذج الافتراضي للاستدعاءات الحية (build_live يضبطه — §1).
        self._live_default_model: str = ""
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
    # المسبار العام — أي المزودات الحية متاحة (الأمر 006 §1)
    # ------------------------------------------------------------ #

    def has_live_provider(self, provider_id: str) -> bool:
        """هل لهذا المزود نقل حي مسجّل؟ — فحص مقدّم صادق قبل الدورة.

        يستخدمه مسار المهمة للإعلان المبكر عن أي دور لن يجد نموذجه،
        بدل انفجار في منتصف الدورة (CONFIGURATION_REQUIRED صريح).
        """
        pid = provider_id.value if isinstance(provider_id, Provider) else str(provider_id)
        return pid in self._transports

    def live_providers(self) -> list[str]:
        """أسماء المزودات الحية المحلولة — للعرض والإعلان الصادق."""
        return sorted(self._transports)

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

    # ------------------------------------------------------------------ #
    # الأمر السادس — الربط الحي: نقل urllib + chat_live + build_live
    # ------------------------------------------------------------------ #

    @classmethod
    def build_live(
        cls,
        live_cfg: "Any" = None,
        *,
        on_event: Callable[[dict], None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        require_default: bool = True,
        cooling_overrides: dict | None = None,
    ) -> "ModelRouter":
        """بناء موجّه حي — كل مزود محلول بمفتاحه، بسلسلة تبدّل مرتّبة.

        المزود الافتراضي أول السلسلة؛ ما بعده احتياط بترتيب الحل (§1.5).
        حدود كل مزود تُضبط في المحدد بإعداداته الخاصة (§1.4)، والتبريد
        والتبريد يعملان على أي مزود بنفس المنطق (§1.6). لا مزود محلول
        = ProviderCallError صريحة — لا mock ولا صمت.

        require_default (الأمر 006 §1): مسار الأدوار صار اختياره الصريح
        هو المصدر — فالفحص الأمامي لكل دور (has_live_provider) أصدق من
        فحص المزود الافتراضي العام. بـ require_default=False يُبنى
        الموجّه بكل المزودات المحلولة، وكل دور بلا مزوده يُسمّى صراحة
        في CONFIGURATION_REQUIRED (لا تبدّل صامت أبدًا).
        """
        live_cfg = live_cfg or live_model_settings
        resolved = resolve_live_providers(live_cfg)
        if not resolved:
            raise ProviderCallError(
                "لا مزود حي بمفتاح قابل للحل — احفظ مفتاح nvidia من صفحة المزودات في الواجهة فيُخزَّن في مخزن الأسرار (فشل صريح، "
                "لا سقوط إلى mock)"
                "لا سقوط إلى mock)"
            )
        default_provider = str(getattr(live_cfg, "default_provider", "nvidia"))
        default_model = str(getattr(live_cfg, "default_model", ""))
        if default_provider not in resolved and require_default:
            # المزود الافتراضي بلا مفتاح: فشل صريح — لا نبدّل بصمت
            raise ProviderCallError(
                f"المزود الافتراضي '{default_provider}' بلا مفتاح قابل "
                f"للحل (المتاح: {sorted(resolved)}) — احفظ مفتاحه من صفحة المزودات في الواجهة (مخزن الأسرار) ‎.env"
            )

        transports = {
            name: live_transport(cfg) for name, cfg in resolved.items()
        }
        chain_head = (
            default_provider if default_provider in resolved
            else next(iter(resolved))
        )
        # (الأمر 007.1 §9) لا تبدّل صامتًا بين المزودين: اختيار المزود
        # صريح لكل دور — فسلسلة التبدّل أحادية العضو (إعادات داخلية على
        # المزود نفسه عند 5xx ثم فشل صريح). بقية المزودين المحلولين
        # مسجلون كنقلات، وكل استدعاء صريح عليهم يمر بسلسلته الأحادية
        # (فرع else في chat) — المزود الفاشل لا يمنع غيره ولا يُبدَّل
        # إليه خفيةً أبدًا.
        chain_members = [chain_head]
        # حدود كل مزود بإعداداته الخاصة (§1.4) — rpm/min_interval/cooldown
        limiter = RateLimiter(provider_settings.as_dicts()["rate_limiter"])
        for name, cfg in resolved.items():
            override = {
                key: cfg[key]
                for key in ("rpm", "min_interval", "cooldown", "concurrency")
                if cfg.get(key) is not None
            }
            if override:
                limiter.configure(name, override)

        router = cls(
            rate_limiter=limiter,
            failover_chain=FailoverChain(
                chain_members,
                provider_settings.as_dicts()["failover"],
                on_event=on_event,
            ),
            cooling_loop=CoolingLoop(
                {**provider_settings.as_dicts()["cooling"],
                 **(cooling_overrides or {})}, on_event=on_event,
            ),
            default_provider=default_provider,
            transports=transports,
            on_event=on_event,
            sleeper=sleeper,
        )
        router._live_default_model = (
            default_model
            or resolved.get(default_provider, {}).get("model", "")
            or resolved[chain_head].get("model", "")
            or "gpt-4o-mini"
        )
        # (الأمر 008 §3) مواصفات المزودين الحية — مسار البث المتدفق
        # يبني نقله منها (streaming.py) بمعزل عن نقل الرد الكامل.
        router._live_specs = dict(resolved)
        return router

    def chat_live(
        self,
        messages: list[ChatMessage],
        *,
        provider_id: Provider | str | None = None,
        model: str | None = None,
    ) -> dict:
        """استدعاء حي — نموذج حقيقي عبر نقل urllib، لا سقوط إلى mock أبدًا.

        نفس حمايات chat() (حد معدل ← تبريد ← تبدّل) لكن النقل حصريًا
        حي: إن لم يكن للمزود نقل urllib مسجَّل يُرفض الطلب فورًا —
        الفشل الصريح أفضل من رد وهمي (الأمر السادس §2.4).
        """
        pid = (
            provider_id.value
            if isinstance(provider_id, Provider)
            else str(provider_id or self.default_provider)
        )
        if pid == Provider.MOCK.value or pid not in self._transports:
            raise ProviderCallError(
                f"لا نقل حي مسجَّل للمزود '{pid}' — الربط الحي يُبنى عبر "
                "ModelRouter.build_live()؛ لا سقوط إلى mock"
            )
        chosen_model = model or self._live_default_model
        if not chosen_model:
            raise ProviderCallError(
                "لا نموذج محدد للاستدعاء الحي — مرره أو اضبط "
                "AGenthubV2_LIVE_DEFAULT_MODEL في .env"
            )
        return self.chat(messages, provider_id=pid, model=chosen_model)

    def chat_live_stream(
        self,
        messages: list[ChatMessage],
        *,
        provider_id: Provider | str | None = None,
        model: str | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> dict:
        """استدعاء حي متدفق (الأمر 008 §3) — قطع فعلية لحظة وصولها.

        نفس صراحة chat_live: لا سقوط إلى mock؛ فشل البث المتدفق
        (مزود لا يدعم stream) يُعاد خطأً مصنَّفًا ليقرر المستدعي
        التراجع الصريح إلى المسار الكامل — لا نجاح وهمي.
        """
        from router.streaming import stream_completion  # noqa: PLC0415

        pid = (
            provider_id.value
            if isinstance(provider_id, Provider)
            else str(provider_id or self.default_provider)
        )
        specs = getattr(self, "_live_specs", {})
        if pid not in specs:
            raise ProviderCallError(
                f"لا مواصفة حية للمزود '{pid}' — البث المتدفق يُبنى عبر "
                "ModelRouter.build_live()"
            )
        chosen_model = model or self._live_default_model
        if not chosen_model:
            raise ProviderCallError(
                "لا نموذج محدد للاستدعاء الحي — مرره صراحة"
            )
        # بوابة حد المعدل نفسها (chat) — البث لا يتجاوزها أبدًا
        est_tokens = self._estimate_tokens(messages)
        allowed = False
        for attempt in range(1, self._max_rate_waits + 1):
            allowed, wait = self._limiter.acquire(pid, est_tokens)
            if allowed:
                break
            self._emit({
                "kind": "rate_limit.wait",
                "provider": pid,
                "wait_seconds": round(wait, 2),
                "attempt": attempt,
            })
            self._sleeper(max(wait, 0.01))
        if not allowed:
            raise ProviderCallError(
                f"حد المعدل ما زال مرفوعًا لمزود {pid} بعد "
                f"{self._max_rate_waits} انتظارات"
            )
        started = time.monotonic()
        try:
            text = stream_completion(
                dict(specs[pid]), chosen_model, messages, on_delta=on_delta
            )
        except ProviderCallError:
            raise
        except Exception as error:  # noqa: BLE001 — فشل صريح لا صامت
            raise ProviderCallError(
                f"البث المتدفق فشل مع {pid}: {error}", is_server_error=True
            ) from error
        duration_ms = int((time.monotonic() - started) * 1000)
        self._emit({
            "kind": "router.call.logged",
            "provider": pid, "model": chosen_model, "tokens": None,
            "duration_ms": duration_ms, "cooled": False,
            "failed_over": False, "streamed": True,
        })
        return {
            "text": text, "provider": pid, "model": chosen_model,
            "tokens": None, "duration_ms": duration_ms, "streamed": True,
        }


def live_transport(provider_cfg: dict) -> Callable[[str, list[ChatMessage]], str]:
    """نقل urllib حقيقي لمزود متوافق مع OpenAI — صفر تبعيات جديدة (§1.3).

    provider_cfg: {base_url, api_key, model, headers?, timeout?, max_tokens?}
    الأخطاء مصنَّفة بطرفية ProviderCallError: 429 اختناق (تبريد)،
    5xx/مهلة خطأ خادم (إعادات ثم تبدّل)، 4xx عميل (فشل صريح فوري).
    """
    base_url = str(provider_cfg["base_url"]).rstrip("/")
    api_key = str(provider_cfg.get("api_key", ""))
    timeout = float(provider_cfg.get("timeout", 90))
    max_tokens = int(provider_cfg.get("max_tokens", 4000) or 0)

    def transport(model: str, messages: list[ChatMessage]) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages
            ],
        }
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens
        # حقول إضافية خاصة بالمزود (مثل تعطيل thinking في نقاط GLM)
        payload.update(dict(provider_cfg.get("extra_body", {}) or {}))
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        headers.update(dict(provider_cfg.get("headers", {}) or {}))
        request = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode("utf-8", "replace")
            code = int(error.code)
            if code == 429:
                retry_after = error.headers.get("Retry-After") if error.headers else None
                raise ProviderCallError(
                    f"429 اختناق من {base_url}: {detail}",
                    code=code,
                    is_throttle=True,
                    retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
                ) from error
            if code >= 500:
                raise ProviderCallError(
                    f"{code} خطأ خادم من {base_url}: {detail}",
                    code=code,
                    is_server_error=True,
                ) from error
            raise ProviderCallError(
                f"{code} خطأ عميل من {base_url} (مفتاح/عنوان؟): {detail}",
                code=code,
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise ProviderCallError(
                f"مهلة/اتصال فشل مع {base_url}: {error}",
                is_timeout=True,
            ) from error
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderCallError(
                f"استجابة بلا choices/content من {base_url}: "
                f"{json.dumps(body, ensure_ascii=False)[:200]}",
                is_server_error=True,
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ProviderCallError(
                f"رد فارغ من {base_url} — فشل صريح لا تكرار صامت",
                is_server_error=True,
            )
        return content

    return transport


