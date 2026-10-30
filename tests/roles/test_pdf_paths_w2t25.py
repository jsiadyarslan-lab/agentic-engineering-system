"""اختبارات W2-T25 — مسار الخط داخل الركيزة وسلامة تهريب كود PDF.

الدافع المقيس (الخطوة 460، ثلاث محاولات):
(1) كود PDF المولَّد يشير للخط بـ/ws/_fonts (اتفاقية ركيزة ميتة) بينما
bwrap يربط مساحة العمل على /work قراءةً — سابقًا كانت الركيزة ترفض
التنفيذ فينجح الاحتياطي داخل العملية ويغطي العلة؛ إتاحة bwrap كشفتها
وTTFError قتل دورة كاملة كانت مكتملة أدلةً.
(2) تقرير خطوة HTML يصف وسومًا حرفية — التهريب نقطة واحدة على مستوى
md كاملًا (757b3b7) بلا تهريب ثانٍ داخل ar() فلا &amp;amp; في الناتج.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from roles.pdf_tools import build_pdf_code  # noqa: E402
from roles.tools import substrate_font_ref  # noqa: E402


def test_substrate_font_ref_uses_work_mount():
    """مسار الخط داخل الركيزة من WORK_MOUNT (/work) — لا /ws الميتة."""
    assert substrate_font_ref("IBMPlexSansArabic-Regular.ttf") == \
        "/work/_fonts/IBMPlexSansArabic-Regular.ttf"


def test_pdf_code_escapes_once_at_md_level():
    """التهريب نقطة واحدة على md كاملًا — لا esc ثانية داخل ar() (الدمج
    أولًا ضاعفه: &amp;amp; في ناتج الPDF)."""
    code = build_pdf_code("T1-report.md", "T1-report.pdf", "/x/font.ttf")
    assert "md.replace('&', '&amp;')" in code
    assert "def esc" not in code
    assert "reshape(str(t))" in code
    # التنظيف الحرفي \uXXXX حاضر (757b3b7)
    assert "_re.sub(r'\\\\u[0-9a-fA-F]{4}', '', md)" in code
