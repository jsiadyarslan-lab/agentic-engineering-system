"""حلقة التبريد المثابرة — وحدة مستقلة منقولة من v1 (الأمر الثالث).

الأصل: PlanOrchestrator._throttle_cool في v1 (16.1 — تعديل الأمر 16
جزء ب): العمل لا يتوقف عند استنفاد حصة الدقيقة؛ تبريد ← محاولة ←
فشل ← تبريد… حتى النجاح أو استنفاد الميزانيات، وبعدها فقط مسار
التبدّل. المنطق الرياضي نفسه ينقل حرفيًا:

  فترة الانتظار: رأس Retry-After إن أرسله المزود، وإلا تصاعد أُسّي
  cooldown_base × 2^(n-1)  →  60 ← 120 ← 240 ← سقف cooldown_max (300)
  الحدود: max_waits لكل استدعاء (10) + budget_seconds لكل استدعاء
  (1800) — استنفاد أيهما ينهي الحلقة باستثناء CoolingBudgetExhausted.

فروق موثقة عن v1:
  - الميزانية في v1 كانت لكل «نطاق» (مهمة/وكيل عبر استدعاءات)؛
    الأمر الثالث يحددها **لكل استدعاء** — نطاق المهام يعود مع
    البعثات في أمر لاحق.
  - أحداث v1 (throttle.cooldown/retry/recovered) كانت تُكتب في قاعدة
    البيانات مع عدّاد حي للواجهة؛ v2 تبث حدث cooling.cooldown عبر
    on_event (بلا قاعدة) — البث مسؤولية الطبقة الأعلى.
  - sleeper قابل للحقن: الاختبار يتحقق من المتتالية بلا نوم حقيقي.

الاختناق (‎.is_throttle على الاستثناء) وحده يدخل الحلقة؛ كل خطأ آخر
يُرفع فورًا (التبدّل يملك 5xx/المهلة — لا انتظار مزدوج أبدًا).
السقف الدائم: <250 سطر (مُرسّخ في tests/contracts/test_thinness.py).
"""

from __future__ import annotations

import time
from typing import Any, Callable

#: الإعداد الافتراضي — مطابق لسياسة v1 الموحدة (60/300/10/1800).
DEFAULT_CONFIG: dict = {
    "cooldown_base": 60,        # أساس التبريد الأسي (ثوانٍ)
    "cooldown_max": 300,        # سقف فترة التبريد (ثوانٍ)
    "max_waits": 10,            # حد مرات الانتظار لكل استدعاء
    "budget_seconds": 1800,     # ميزانية انتظار لكل استدعاء (ثوانٍ)
}


class CoolingBudgetExhausted(RuntimeError):
    """استُنفدت ميزانية التبريد — عدد الانتظارات ومجموعها في التقرير."""

    def __init__(self, message: str, waits: int, waited_seconds: float):
        super().__init__(message)
        self.waits = waits
        self.waited_seconds = waited_seconds


def _is_throttle(exc: BaseException) -> bool:
    return bool(getattr(exc, "is_throttle", False))


class CoolingLoop:
    """الصبر عند الاختناق — إعادة المحاولة بنفس المزود بعد تبريد متصاعد."""

    def __init__(
        self,
        config: dict | None = None,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._sleeper = sleeper
        self._on_event = on_event
        self.events: list[dict] = []
        #: آخر تنفيذ: {cooled, waits, waited_seconds, retry_after_used}
        self.last_execution: dict[str, Any] = {}

    def _emit(self, event: dict) -> None:
        self.events.append(event)
        if self._on_event is not None:
            try:
                self._on_event(event)
            except Exception:  # noqa: BLE001 — المستقبِل لا يكسر الحلقة
                pass

    def execute_with_cooling(
        self, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """تنفيذ fn() مع صبر أسي عند اختناقه (429 / 503-overloaded).

        يعيد نتيجة fn عند أول نجاح، أو يرفع CoolingBudgetExhausted عند
        استنفاد حد الانتظارات أو الميزانية. غير الاختناقي يُرفع فورًا.
        """
        base = float(self.config.get("cooldown_base", 60))
        cap = float(self.config.get("cooldown_max", 300))
        max_waits = int(self.config.get("max_waits", 10))
        budget = float(self.config.get("budget_seconds", 1800))

        if max_waits <= 0 or budget <= 0 or base <= 0:
            # مزود بلا سياسة تبريد (مثل mock) — تنفيذ مباشر بلا انتظار
            result = fn(*args, **kwargs)
            self.last_execution = {
                "cooled": False, "waits": 0, "waited_seconds": 0.0
            }
            return result

        waits = 0
        waited = 0.0
        while True:
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — تصنيف أدناه
                if not _is_throttle(exc):
                    raise  # 5xx/مهلة/عميل — ملك التبدّل لا التبريد
                reason = str(exc)[:150]
                retry_after = getattr(exc, "retry_after", None)

                n = waits + 1
                if n > max_waits:
                    raise CoolingBudgetExhausted(
                        f"استُنفد حد مرات التبريد ({max_waits} انتظارًا) — "
                        f"انتظرنا {waited:.0f}ث من ميزانية {budget:.0f}ث",
                        waits=waits, waited_seconds=waited,
                    )

                if retry_after and int(retry_after) > 0:
                    wait_s = float(retry_after)
                else:
                    wait_s = base * (2 ** (n - 1))
                if cap > 0:
                    wait_s = min(wait_s, cap)

                if wait_s > budget - waited:
                    raise CoolingBudgetExhausted(
                        f"تبريد مطلوب {wait_s:.0f}ث يتجاوز الميزانية "
                        f"المتبقية ({max(0.0, budget - waited):.0f}ث من "
                        f"{budget:.0f}ث) بعد {waits} انتظارًا",
                        waits=waits, waited_seconds=waited,
                    )

                self._emit(
                    {
                        "kind": "cooling.cooldown",
                        "wait_s": wait_s,
                        "attempt": n,
                        "max_waits": max_waits,
                        "reason": reason,
                    }
                )
                self._sleeper(wait_s)
                waits = n
                waited += wait_s
                continue

            self.last_execution = {
                "cooled": waits > 0,
                "waits": waits,
                "waited_seconds": waited,
            }
            return result
