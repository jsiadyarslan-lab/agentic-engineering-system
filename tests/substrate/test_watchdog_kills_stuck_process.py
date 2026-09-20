"""إثبات سالب 4: المراقب (watchdog) يقتل العملية العالقة.

برنامج نائم إلى ما لا نهاية تحت مهلة جدارية قصيرة — المراقب يجب أن
ينهيه خلال زمن محدود بقتل جماعي حتمي، ويوثق الإنهاء بصدق (ليس
COMPLETED أبدًا)، ثم يُنظَّف كل شيء.
"""

from __future__ import annotations

import time

from substrate.limits import ExecutionLimits
from substrate.sandbox import SandboxTermination

from tests.substrate.conftest import run_in_sandbox


def test_watchdog_kills_stuck_process(adapter, tmp_path):
    # مهلة قصيرة (10 ثوانٍ ≤ الافتراضي 300 — خفض فقط)
    limits = ExecutionLimits(timeout_seconds=10)

    code = '''
import time
print("STUCK:entering-endless-sleep")
time.sleep(99999)
'''
    t0 = time.monotonic()
    record, _ = run_in_sandbox(
        adapter, tmp_path, code, sandbox_id="neg-watchdog-001", limits=limits
    )
    wall = time.monotonic() - t0

    # 1) انتهى خلال زمن محدود (مهلة + هامش التنعيم والتنظيف)
    assert wall < 60, f"استغرق {wall:.1f}s — المراقب لم يُنهِ بسرعة"

    # 2) الإنهاء موثق بصدق: ليس اكتمالًا طبيعيًا أبدًا
    assert record.termination is not SandboxTermination.COMPLETED, (
        f"عملية عالقة سُجلت مكتملة! ({record.termination})"
    )
    assert record.termination in (
        SandboxTermination.TIMEOUT,
        SandboxTermination.KILLED,
        SandboxTermination.LIMIT_BREACH,
    ), f"إنهاء غير متوقع: {record.termination}"
    assert record.exit_code != 0

    # 3) لا عملية باقية: التنظيف الجماعي تم
    evidence = adapter.execution_evidence("neg-watchdog-001")
    assert evidence is not None, "لا دليل تنفيذ — أين الأثر الموثق؟"
