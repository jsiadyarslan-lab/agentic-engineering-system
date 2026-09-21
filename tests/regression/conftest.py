"""تجهيزات انحدار الأمر 010 — يعيد استخدام بيئة API المعزولة."""

from __future__ import annotations

import sys
from pathlib import Path

# بيئة API (api_env) معرفة في tests/api/conftest.py — نجعلها متاحة هنا
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from conftest import api_env  # noqa: E402,F401
