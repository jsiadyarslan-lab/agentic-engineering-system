"""(013.6 §12) تشغيل اختبار الاسترداد المتذبذب N مرة وتسجيل الفشل حرفيًا.

لا يكفي القول «ربما توقيت»: المطلوب جذر السبب. هذا المشغّل يعيد
الاختبار ويكتب خرج كل تشغيل فاشل في ملف مستقل، ثم يطبع توزيع النتائج
وأول أثر فشل كامل.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "tests/api/test_projects_api.py::test_recovery_listing_after_pause"
OUT = ROOT / "runtime" / "flaky0136"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("run-*.txt"):
        old.unlink()
    outcomes: Counter[str] = Counter()
    failure_tails: list[str] = []
    for index in range(1, runs + 1):
        log = OUT / f"run-{index:03d}.txt"
        with open(log, "w", encoding="utf-8") as handle:
            subprocess.run(
                [sys.executable, "-m", "pytest", TARGET, "-q",
                 "-p", "no:cacheprovider", "--no-header"],
                cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                timeout=600,
            )
        text = log.read_text(encoding="utf-8", errors="replace")
        passed = bool(re.search(r"\b1 passed\b", text))
        outcomes["PASS" if passed else "FAIL"] += 1
        if not passed:
            failure_tails.append(
                f"----- تشغيل {index} -----\n{text.strip()[-1800:]}"
            )
        print(f"  {index:>3}/{runs}: {'PASS' if passed else 'FAIL'}",
              flush=True)
    print(f"\nالتوزيع: {dict(outcomes)}")
    if failure_tails:
        print("\n=== أول ثلاثة آثار فشل ===")
        for tail in failure_tails[:3]:
            print(tail)
    return 0 if not failure_tails else 1


if __name__ == "__main__":
    raise SystemExit(main())
