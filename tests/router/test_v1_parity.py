"""التكافؤ الوظيفي مع v1 — الأمر الثالث القسم 4-5 (معيار القبول 6).

المنهج: **تشغيل كود v1 الحقيقي** في subprocess بمفسّر بيئته الافتراضية
(تبعيات v1 غير مثبتة في بيئة v2، والمقارنة عبر حدث عملية صادقة لا عبر
استيراد مُوَطَّن). السيناريو نفسه يُشغَّل في v2 داخل العملية، ثم:

  1) محدد المعدل: نفس الإعداد dict في الطرفين → نفس نمط السماح/الرفض
     في اندفاع الخمسين، وسلوك النافذة المنزلقة، والتبريد الإجباري.
  2) سياسة v1 الموحدة تُقرأ من كود v1 نفسه (EXECUTION_POLICY_DEFAULTS)
     → إعدادات v2 الافتراضية (ProviderConfig) تطابقها قيمةً بقيمة.
  3) متتالية التبريد (60←120←240) تُشتق من قيم v1 الفعلية المستوردة
     بالصيغة الحرفية من منسق v1 (wait = base × 2^(n-1) بسقف max).

فروق الإعداد الموثقة (لا تمس الخوارزمية):
  - v1 يقرأ إعداده من قاعدة بيانات (settings_service)؛ السكربت يحقن
    dict عبر تجاوز _config_for — المصدر وحده يختلف، الخوارزمية نفسها.
  - مرور الدقيقة في طرف v1 يُحقن بطوابع زمنية قديمة داخل نافذته
    (خوارزمية القص تعمل فعليًا)؛ طرف v2 يقدم ساعته القابلة للحقن.

يُتخطى الاختبار بوضوح إن غاب مستودع v1 أو بيئته (التكافؤ يُفحص حيث
يتجاور المستودعان — بيئة التطوير هذه).
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

from core.config import provider_settings
from router.cooling_loop import CoolingLoop
from router.rate_limiter import RateLimiter


class Throttle429(Exception):
    """429 كما يراها التبريد — بطرفية كاستثناءات النقل."""

    is_throttle = True

REPO = Path(__file__).resolve().parents[2]
V1_REPO = Path(
    os.environ.get("AGENTHUB_V1_PATH", str(REPO.parent / "agent-hub"))
)
V1_PYTHON = V1_REPO / ".venv" / "bin" / "python"

pytestmark = pytest.mark.skipif(
    not V1_PYTHON.exists(),
    reason="مستودع v1 أو بيئته الافتراضية غير موجودين — اختبار التكافؤ "
    "يعمل حيث يتجاور المستودعان (بيئة التطوير)",
)

#: الإعداد المشترك للطرفين — حدود نفيديا المجانية كما في v1.
SHARED_CONFIG = {
    "rpm": 40,
    "tpm": 0,
    "min_interval": 0.0,
    "cooldown": 60,
    "concurrency": 1,
}

#: سكربت طرف v1: كود v1 الفعلي (rate_limiter + settings_service) —
#: لا نسخ منطق هنا، استيراد وتشغيل حرفيان.
V1_SCRIPT = r'''
import json
import sys
import time
from collections import deque

sys.path.insert(0, ".")
from backend.services import rate_limiter as rl
from backend.services import settings_service

# (أ) سياسة v1 الموحدة الحقيقية — قراءة من الكود لا من الذاكرة
policy = settings_service.EXECUTION_POLICY_DEFAULTS

# (ب) خوارزمية المحدد بإعداد محقون dict (نفس ما يستلمه v2 معاملًا)
CFG = json.loads(sys.argv[1])

class _ConfigInjected(rl.RateLimiter):
    """تجاوز مصدر الإعداد فقط (قاعدة البيانات ← dict محقون)."""
    def _config_for(self, provider_id):
        return dict(CFG)

lim = _ConfigInjected()
burst = [lim.acquire("p", 1000) for _ in range(50)]
allowed = sum(1 for ok, _ in burst if ok)
rejected = [w for ok, w in burst if not ok]

# (ج) النافذة المنزلقة: حقن طوابع قديمة داخل نافذة v1 الحقيقية —
# خوارزمية القص (cutoff 60s) هي التي تُفرغ النافذة فعليًا
st = lim._states["p"]
now = time.monotonic()
st.window.clear()
st.window.extend([(now - 61.0, 1000)] * 40)
window_recovers = lim.acquire("p", 1000)[0]

# (د) التبريد الإجباري بعد 429 — ثم زواله بحقن طابع منقضٍ
lim.note_429("p")
cooldown_blocks = lim.acquire("p", 1000)[0] is False
st.cooldown_until = time.monotonic() - 1.0
cooldown_recovers = lim.acquire("p", 1000)[0] is True

print(json.dumps({
    "policy": {
        "retries_on_5xx": policy["retries_on_5xx"],
        "cooldown_base": policy["cooldown_base"],
        "cooldown_max": policy["cooldown_max"],
        "max_throttle_waits": policy["max_throttle_waits"],
        "throttle_budget_seconds": policy["throttle_budget_seconds"],
    },
    "allowed": allowed,
    "rejected": len(rejected),
    "min_rejected_wait": min(rejected),
    "window_recovers": window_recovers,
    "cooldown_blocks": cooldown_blocks,
    "cooldown_recovers": cooldown_recovers,
}, ensure_ascii=False))
'''


@lru_cache(maxsize=1)
def _run_v1_side() -> dict:
    """تشغيل سكربت طرف v1 ببيئته الافتراضية — JSON النتائج (مخبأ)."""
    completed = subprocess.run(
        [
            str(V1_PYTHON), "-c", V1_SCRIPT,
            json.dumps(SHARED_CONFIG),
        ],
        cwd=str(V1_REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, (
        f"فشل طرف v1: {completed.stderr[-800:]}"
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _v2_burst() -> dict:
    """السيناريو نفسه في v2 — ساعة قابلة للتقديم بدل حقن الطوابع."""
    clock = FakeClock()
    limiter = RateLimiter(dict(SHARED_CONFIG), clock=clock)
    results = [limiter.acquire("p", 1000) for _ in range(50)]
    allowed = sum(1 for ok, _ in results if ok)
    rejected = [w for ok, w in results if not ok]

    clock.advance(60.5)  # مرور الدقيقة — النافذة تفرغ
    window_recovers = limiter.acquire("p", 1000)[0]

    limiter.note_429("p")
    cooldown_blocks = limiter.acquire("p", 1000)[0] is False
    clock.advance(61.0)
    cooldown_recovers = limiter.acquire("p", 1000)[0]
    return {
        "allowed": allowed,
        "rejected": len(rejected),
        "min_rejected_wait": min(rejected),
        "window_recovers": window_recovers,
        "cooldown_blocks": cooldown_blocks,
        "cooldown_recovers": cooldown_recovers,
    }


def test_rate_limiter_burst_parity_with_v1():
    """اندفاع الخمسين: نفس النمط في v1 و v2 — 40/10 وانتظارات موجبة."""
    v1 = _run_v1_side()
    v2 = _v2_burst()

    assert v2["allowed"] == v1["allowed"] == 40
    assert v2["rejected"] == v1["rejected"] == 10
    assert v2["min_rejected_wait"] > 0 and v1["min_rejected_wait"] > 0
    # الفرق الطفيف في طول الانتظار مقبول (طوابع v1 حقيقية وساعتنا مجمدة)
    assert abs(v1["min_rejected_wait"] - v2["min_rejected_wait"]) < 1.0


def test_sliding_window_and_cooldown_parity_with_v1():
    """النافذة المنزلقة والتبريد الإجباري: نفس السلوك في الطرفين."""
    v1 = _run_v1_side()
    v2 = _v2_burst()

    assert v2["window_recovers"] == v1["window_recovers"] is True
    assert v2["cooldown_blocks"] == v1["cooldown_blocks"] is True
    assert v2["cooldown_recovers"] == v1["cooldown_recovers"] is True


def test_v2_defaults_match_v1_execution_policy():
    """إعدادات v2 الافتراضية = سياسة v1 الموحدة قراءةً من كود v1."""
    v1_policy = _run_v1_side()["policy"]

    assert provider_settings.failover_max_retries == v1_policy["retries_on_5xx"]
    assert provider_settings.cooling_base_seconds == v1_policy["cooldown_base"]
    assert provider_settings.cooling_max_seconds == v1_policy["cooldown_max"]
    assert provider_settings.cooling_max_waits == v1_policy["max_throttle_waits"]
    assert (
        provider_settings.cooling_budget_seconds
        == v1_policy["throttle_budget_seconds"]
    )


def test_cooling_sequence_parity_with_v1_formula():
    """متتالية التبريد 60←120←240 كما تُشتق من قيم v1 وصيغته الحرفية.

    صيغة v1 (منسق v1، ‎_throttle_cool): wait = cooldown_base × 2^(n-1)
    بسقف cooldown_max — القيم من سياسة v1 المستوردة فعليًا أعلاه.
    """
    v1_policy = _run_v1_side()["policy"]
    base = float(v1_policy["cooldown_base"])
    cap = float(v1_policy["cooldown_max"])
    v1_expected_waits = [
        min(base * (2 ** (n - 1)), cap) for n in (1, 2, 3)
    ]  # → 60، 120، 240

    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] <= 3:
            raise Throttle429()
        return "نجاح"

    class Throttle429(Exception):
        is_throttle = True

    waits: list[float] = []
    loop = CoolingLoop(
        {
            "cooldown_base": v1_policy["cooldown_base"],
            "cooldown_max": v1_policy["cooldown_max"],
            "max_waits": v1_policy["max_throttle_waits"],
            "budget_seconds": v1_policy["throttle_budget_seconds"],
        },
        sleeper=waits.append,
    )
    assert loop.execute_with_cooling(flaky) == "نجاح"
    assert waits == v1_expected_waits  # v2 تطبق صيغة v1 بنتيجتها
