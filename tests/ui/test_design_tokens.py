# -*- coding: utf-8 -*-
"""عقد تصميم W2-T07 — لا لون خام خارج theme.css إطلاقاً.

يحرس إنجاز مسح الألوان الناجية (31 سطر hex/rgba خارج النظام → صفر):
أي hex أو rgba/rgb جديد يظهر في أي ملف CSS تحت src/ui/ (عدا theme.css
مصدر الحقيقة الوحيد وخطوط fonts/) يُفشل الاختبار فوراً — فيُمنع
«اللوحة الخامسة المتضاربة» من التكون مرة أخرى (عيب AUDIT-001 البصري).

ملاحظة: الفحص يعم القيم داخل التعليقات أيضاً — نية البوابة: لا ذكر
حرفياً للون خارج ملف النظام، حتى في التوثيق (المصدر المعتمد للقيم
المرجعية هو theme.css نفسه).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[2] / "src" / "ui"
THEME = "theme.css"
FONTS_DIR = "fonts"

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB_FN_RE = re.compile(r"\brgba?\(\s*[0-9]")


# استثناءات مقصودة (لا تُعدّ لوحة موازية):
# - theme.css: مصدر الحقيقة الوحيد للقيم.
# - fonts/: ملفات خطوط فقط لا أنماط.
def _css_files_outside_theme() -> list[Path]:
    if not UI_DIR.is_dir():
        pytest.skip(f"UI dir not found: {UI_DIR}")
    files = []
    for p in sorted(UI_DIR.rglob("*.css")):
        rel = p.relative_to(UI_DIR)
        if rel.parts and rel.parts[0] == FONTS_DIR:
            continue
        if p.name == THEME:
            continue
        files.append(p)
    assert files, "expected UI css files besides theme.css — layout changed?"
    return files


@pytest.mark.parametrize("css_file", _css_files_outside_theme(), ids=lambda p: str(p.relative_to(UI_DIR)))
def test_no_raw_hex_outside_theme(css_file: Path) -> None:
    text = css_file.read_text(encoding="utf-8")
    offenders = [
        f"line {i}: {line.strip()[:100]}"
        for i, line in enumerate(text.splitlines(), 1)
        if HEX_RE.search(line)
    ]
    assert not offenders, (
        f"{css_file.name}: قيم hex خام خارج theme.css ممنوعة — "
        "أضف/استخدم توكن نظام في src/ui/theme.css:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("css_file", _css_files_outside_theme(), ids=lambda p: str(p.relative_to(UI_DIR)))
def test_no_raw_rgb_rgba_outside_theme(css_file: Path) -> None:
    text = css_file.read_text(encoding="utf-8")
    offenders = [
        f"line {i}: {line.strip()[:100]}"
        for i, line in enumerate(text.splitlines(), 1)
        if RGB_FN_RE.search(line)
    ]
    assert not offenders, (
        f"{css_file.name}: قيم rgb/rgba خام خارج theme.css ممنوعة — "
        "أضف/استخدم توكن نظام في src/ui/theme.css:\n" + "\n".join(offenders)
    )


def test_theme_css_exists_and_is_token_source() -> None:
    theme = UI_DIR / THEME
    assert theme.is_file(), "theme.css مصدر الحقيقة الوحيد للألوان — لا يجوز حذفه"
    text = theme.read_text(encoding="utf-8")
    token_count = len(re.findall(r"^\s*--[\w-]+\s*:", text, flags=re.M))
    assert token_count >= 136, (
        f"توكنات theme.css تراجعت ({token_count} < 136) — لا يجوز حذف توكنات قائمة"
    )
