"""سلسلة تبدّل المزودات — وحدة مستقلة منقولة من v1 (الأمر الثالث).

الأصل في v1 موزَّع: إعادات داخلية مصنّفة في ModelRouter.chat (retries_
on_5xx=2 بتراجع أُسّي يحترم Retry-After) + اجتياز السلسلة بحدث
provider.failover في المنسق. v2 يجمع المنطق في وحدة واحدة صرفة:

  execute_with_failover(fn, *args, **kwargs)
    fn(provider, *args, **kwargs) — الوحدة تختار العضو، والدالة تنفّذ.

تصنيف الأخطاء (بطرفية — duck typing، نفس فئات v1 الثلاث):
  - throttle (‎.is_throttle): تُرفع فورًا بلا إعادة ولا تبدّل — حلقة
    التبريد وحدها تملك انتظار الاختناق (لا انتظار مزدوج أبدًا).
  - server (‎.is_server_error أو ‎.is_timeout): إعادات داخلية
    (max_retries=2 — مطابق لـ retries_on_5xx في v1) بتراجع
    backoff_base × 2^(n-1)، ثم تبدّل للعضو التالي بنفس الاستدعاء.
  - client (غيرها، مثل 401): تُرفع فورًا — لا فائدة من أي إعادة.

استنفاد السلسلة كاملة = FailoverExhausted بتقرير يذكر كل عضو وسبب
فشله (في v1 كانت حالة BLOCKED قابلة للاستئناف؛ في v2 استثناء صريح
يقرر المتصل — المنسق لاحقًا — ماذا يفعل به).

الأحداث: failover.logged {from, to, reason} عند كل تبدّل + تقرير
self.last_execution {provider, failed_over, attempts…} بعد كل تنفيذ.
السقف الدائم: <250 سطر (مُرسّخ في tests/contracts/test_thinness.py).
"""

from __future__ import annotations

import time
from typing import Any, Callable

#: إعداد السلسلة الافتراضي — مطابق لسياسة v1 الموحدة (retries_on_5xx=2).
DEFAULT_CONFIG: dict = {
    "max_retries": 2,        # إعادات داخلية لكل عضو قبل التبدّل
    "backoff_base": 2.0,     # ثواني التراجع: base × 2^(n-1) → 2، 4…
}


class FailoverExhausted(RuntimeError):
    """كل أعضاء السلسلة فشلوا — التقرير يذكر كل عضو وسبب فشله."""

    def __init__(self, message: str, failures: list[dict]):
        super().__init__(message)
        self.failures = failures  # [{provider, attempts, reason}]


def _is_throttle(exc: BaseException) -> bool:
    return bool(getattr(exc, "is_throttle", False))


def _is_retryable(exc: BaseException) -> bool:
    """عقد التصنيف (بطرفية — أي استثناء يفي به):

    - مهلة (TimeoutError أو ‎.is_timeout) → قابل للإعادة.
    - ‎.is_server_error موجود → قيمته تحكم (5xx صريح أو عميل مصنف).
    - غير مصنف أصلًا: أخطاء البرمجة (TypeError…) تفشل فورًا، وما
      عداها يُعامل كخطأ خادم قابل للإعادة — نفس قرار v1 الذي صنّف
      كل مجهول النقل "server" (انحراف موثق: أخطاء البرمجة استثناء).
    """
    if isinstance(exc, TimeoutError) or bool(getattr(exc, "is_timeout", False)):
        return True
    if hasattr(exc, "is_server_error"):
        return bool(exc.is_server_error)
    return not isinstance(
        exc, (TypeError, ValueError, KeyError, AttributeError)
    )


class FailoverChain:
    """سلسلة مزودين مرتبة — الأعضاء الاحتياطيون بمفاتيح محفوظة."""

    def __init__(
        self,
        providers: list[str],
        config: dict | None = None,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("سلسلة التبدّل تحتاج عضوًا واحدًا على الأقل")
        self.providers = [str(p) for p in providers]
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._sleeper = sleeper
        self._on_event = on_event
        self.events: list[dict] = []
        #: آخر تنفيذ: {provider, failed_over, from, to, reason, attempts}
        self.last_execution: dict[str, Any] = {}

    def _emit(self, event: dict) -> None:
        self.events.append(event)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001 — المستقبِل لا يكسر السلسلة
                pass

    def execute_with_failover(
        self, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """تنفيذ fn(provider, *args, **kwargs) عبر السلسلة المرتبة.

        لكل عضو: محاولة واحدة + max_retries إعادة عند server/timeout
        (تراجع أُسّي بين المحاولات)، ثم حدث failover.logged والانتقال
        للعضو التالي. throttle يُرفع فورًا (ملك حلقة التبريد)، وكذلك
        أخطاء العميل.
        """
        max_retries = int(self.config.get("max_retries", 2))
        backoff_base = float(self.config.get("backoff_base", 2.0))
        failures: list[dict] = []
        total_attempts = 0

        for position, provider in enumerate(self.providers):
            attempt = 0
            while True:
                attempt += 1
                total_attempts += 1
                try:
                    result = fn(provider, *args, **kwargs)
                except Exception as exc:  # noqa: BLE001 — تصنيف أدناه
                    # (Exception لا BaseException: الإيقاف/الخروج يُرفعان دائمًا)
                    if _is_throttle(exc):
                        # الاختناق ملك التبريد — يُرفع فورًا بلا إعادة
                        self.last_execution = {
                            "provider": provider,
                            "failed_over": False,
                            "attempts": total_attempts,
                            "throttled": True,
                        }
                        raise
                    if not _is_retryable(exc):
                        raise  # خطأ عميل حتمي — لا فائدة من أي إعادة
                    if attempt <= max_retries:
                        wait = backoff_base * (2 ** (attempt - 1))
                        if wait > 0:
                            self._sleeper(wait)
                        continue
                    failures.append(
                        {
                            "provider": provider,
                            "attempts": attempt,
                            "reason": str(exc)[:200],
                        }
                    )
                    break  # عضو مستنفد → التالي

                # نجاح العضو الحالي — توثيق التنفيذ والعودة
                self.last_execution = {
                    "provider": provider,
                    "failed_over": position > 0,
                    "from": self.providers[0] if position > 0 else None,
                    "to": provider if position > 0 else None,
                    "attempts": total_attempts,
                }
                return result

            # عضو فشل بعد إعاداته — حدث تبدّل إن وُجد التالي
            if position + 1 < len(self.providers):
                nxt = self.providers[position + 1]
                self._emit(
                    {
                        "kind": "failover.logged",
                        "from": provider,
                        "to": nxt,
                        "reason": failures[-1]["reason"],
                    }
                )

        raise FailoverExhausted(
            "استُنفدت سلسلة التبدّل كاملة — "
            + "؛ ".join(
                f"{f['provider']} فشل بعد {f['attempts']} محاولة ({f['reason']})"
                for f in failures
            ),
            failures=failures,
        )
