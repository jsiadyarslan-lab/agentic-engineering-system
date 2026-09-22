"""اختبارات الأمر 012 — طبقة الـHarness فوق خط 011.

نفس فلسفة العزل المعتمدة منذ 007: كل شيء حقيقي إلا الحدود
الخارجية (موجّه منظم، مخطط منظم، منفذ خطوة منظم يكتب ملفات
وsha256 حقيقية). المحرك والقاعدة والبوابات والوظيفة الدائمة
والمنسق الحتمي والإسقاطات كلها حقيقية بالكامل.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
# إعادة استخدام أدوات اختبارات workflow (نفس الحدود الصادقة)
sys.path.insert(0, str(REPO / "tests" / "workflow"))
