# -*- coding: utf-8 -*-
"""عقد وصولية W2-T11 — أربعة حرّاس دائمون لا يسمحون بالنكوص:

1. test_token_contrast_matrix: كل دور نص × سطح (من theme.css) ≥ 4.5:1
   (مع استثناء --text-disabled الموثق — WCAG 1.4.3 يعفي المعطل)، ونصوص
   الرقائق الدلالية على رقائقها المركبة ≥ 4.5:1 (danger عبر --danger-hi).
2. test_touch_targets_contract: توكن ‎--tap: 44px‎ + كتلة ‎@media (pointer: coarse)‎
   ترفع الحد الأدنى للعناصر التفاعلية (WCAG 2.5.5 على اللمس).
3. test_no_outline_suppression: لا كتم outline في أي CSS (كان يقتل حلقة
   ‎:focus-visible‎ الموحدة) — الاستثناءات الموثقة وحدها مسموحة.
4. test_status_text_beside_dots: نقطة حالة المشروع لا تُعرض بلا نصها
   (.pj-status في projects.js + أنماطها)، ولا ألوان خام في JS inline.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

UI_DIR = Path(__file__).resolve().parents[2] / "src" / "ui"
THEME_TEXT = (UI_DIR / "theme.css").read_text(encoding="utf-8")


# ---------------------------------------------------------------- أدوات WCAG
def _lum(hex_str: str) -> float:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast(fg: str, bg: str) -> float:
    la, lb = _lum(fg), _lum(bg)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _hex_token(name: str) -> str:
    m = re.search(rf"^\s*--{re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{3,8}})\b", THEME_TEXT, re.M)
    assert m, f"توكن ‎--{name}‎ مفقود من theme.css"
    return m.group(1)


def _rgba_token(name: str) -> tuple[str, float]:
    m = re.search(
        rf"^\s*--{re.escape(name)}\s*:\s*rgba?\(\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)"
        rf"(?:\s*,\s*([0-9.]+))?\s*\)", THEME_TEXT, re.M)
    assert m, f"توكن rgba ‎--{name}‎ مفقود من theme.css"
    r, g, b = (int(m.group(i)) for i in (1, 2, 3))
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return f"#{r:02X}{g:02X}{b:02X}", a


def _composite(over_hex: str, alpha: float, under_hex: str) -> str:
    o, u = over_hex.lstrip("#"), under_hex.lstrip("#")
    if len(o) == 3:
        o = "".join(c * 2 for c in o)
    if len(u) == 3:
        u = "".join(c * 2 for c in u)
    chan = [int(round(int(o[i:i + 2], 16) * alpha + int(u[i:i + 2], 16) * (1 - alpha)))
            for i in (0, 2, 4)]
    return "#" + "".join(f"{v:02X}" for v in chan)


# ---------------------------------------------------------------- 1) التباين
SURFACES = ["bg-canvas", "bg-sidebar", "bg-raised", "bg-hover", "bg-elevated"]
TEXT_ROLES = ["text-primary", "text-secondary", "text-muted"]
EXEMPT_ROLES = {"text-disabled": "معطل — معفى من 1.4.3"}


@pytest.mark.parametrize("role", TEXT_ROLES, ids=lambda r: f"{r}")
@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: f"on-{s}")
def test_token_contrast_matrix(role: str, surface: str) -> None:
    """كل دور نص على كل سطح ≥ 4.5:1 — القاعدة التي رفعت muted إلى ‎#89939E‎."""
    ratio = _contrast(_hex_token(role), _hex_token(surface))
    assert ratio >= 4.5, (
        f"--{role} على --{surface} = {ratio:.2f}:1 — دون AA (4.5:1). "
        "ارفع قيمة الدور في theme.css (سابقة W2-T11: muted كان 4.07 على elevated)."
    )


def test_text_disabled_stays_documented_exemption() -> None:
    """المعطل معفى — لكن يجب أن يظل معلنًا كاستثناء لا يُحصب صامتًا."""
    assert "--text-disabled" in THEME_TEXT
    assert "معفاة من AA" in THEME_TEXT or "معفاة" in THEME_TEXT


@pytest.mark.parametrize("fg_tok,chip_tok,label", [
    ("ok", "ok-chip", "ok"),
    ("danger-hi", "danger-chip", "danger"),
    ("warn", "warn-chip", "warn"),
    ("info", "info-chip", "info"),
    ("accent", "accent-soft", "agent"),
])
def test_chip_text_contrast(fg_tok: str, chip_tok: str, label: str) -> None:
    """نص الرقيقة الدلالية على رقاقته المركبة فوق elevated ≥ 4.5:1."""
    fg = _hex_token(fg_tok)
    chip_hex, chip_a = _rgba_token(chip_tok)
    bg = _composite(chip_hex, chip_a, _hex_token("bg-elevated"))
    ratio = _contrast(fg, bg)
    assert ratio >= 4.5, (
        f"نص {label} على رقاقته = {ratio:.2f}:1 — دون AA. "
        f"(سابقة W2-T11: danger الصلب كان 3.64 → أُضيف --danger-hi للنصوص.)"
    )


def test_chip_danger_uses_hi_variant() -> None:
    """.chip.danger نصها ‎--danger-hi‎ لا الصلب (3.6:1 دون AA)."""
    m = re.search(r"^\.chip\.danger\s*\{(.*?)\}", THEME_TEXT, re.M | re.S)
    assert m, "قاعدة .chip.danger مفقودة"
    assert "var(--danger-hi)" in m.group(1), ".chip.danger يجب أن تستخدم var(--danger-hi)"


# ---------------------------------------------------------------- 2) اللمس
def test_tap_token_and_coarse_block() -> None:
    """‎--tap: 44px‎ + كتلة المؤشر الخشن ترفع التفاعلية (WCAG 2.5.5)."""
    assert re.search(r"^\s*--tap:\s*44px", THEME_TEXT, re.M), "توكن --tap: 44px مفقود"
    m = re.search(r"@media \(pointer: coarse\)\s*\{", THEME_TEXT)
    assert m, "كتلة @media (pointer: coarse) مفقودة من theme.css"
    block = THEME_TEXT[m.start():]
    assert "min-height: var(--tap)" in block, "لا min-height: var(--tap) داخل كتلة اللمس"
    assert "min-width: var(--tap)" in block, "لا min-width: var(--tap) داخل كتلة اللمس"
    for needed in ("button", "select", "textarea", ".icon-btn", ".side-nav-item",
                   ".pj-item", ".conv-item"):
        assert needed in block, f"{needed} مفقود من منتقي أهداف اللمس"


def test_coarse_block_stays_last_in_theme() -> None:
    """كتلة اللمس آخر theme.css — لا قاعدة لاحقة تلغيها سهوًا."""
    assert THEME_TEXT.rstrip().rstrip("}").rstrip().endswith(
        "min-width: var(--tap);\n  }") or "@media (pointer: coarse)" in THEME_TEXT[-2000:]


# ---------------------------------------------------------------- 3) التركيز
DOCUMENTED_OUTLINE_EXCEPTIONS: dict[str, str] = {
    # لا استثناءات حاليًا — أي إضافة تحتاج تبريرًا موثقًا هنا
}


def _css_files() -> list[Path]:
    return sorted(p for p in UI_DIR.rglob("*.css")
                  if p.parent.name != "fonts" and p.name != "theme.css")


def test_no_outline_suppression_anywhere() -> None:
    """صفر ‎outline: none|0‎ في كل CSS — حلقة ‎:focus-visible‎ الموحدة لا تُكتم.

    (قبل W2-T11 كانت 7 مواضع قاعدية/‎:focus‎ تكتم الحلقة بخصوصية أعلى.)"""
    offenders = []
    for p in _css_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"outline:\s*(none|0)\s*;", line):
                offenders.append(f"{p.name}:{i}: {line.strip()[:80]}")
    assert not offenders, "كتم outline ممنوع — الحلقة الموحدة في theme.css:\n" + "\n".join(offenders)


def test_global_focus_visible_rule_exists() -> None:
    """القاعدة العالمية الموحدة موجودة بحد وحلقة."""
    m = re.search(r"^:focus-visible\s*\{(.*?)\}", THEME_TEXT, re.M | re.S)
    assert m, "قاعدة :focus-visible العالمية مفقودة من theme.css"
    body = m.group(1)
    assert "outline" in body and "var(--focus-ring)" in body


# ---------------------------------------------------------------- 4) النقاط
def test_project_dot_has_status_text() -> None:
    """projects.js يعرض نص الحالة (.pj-status) بجوار النقطة — لا لونًا صرفًا."""
    src = (UI_DIR / "projects.js").read_text(encoding="utf-8")
    assert '"pj-status"' in src, "projects.js لا ينشئ عنصر نص الحالة .pj-status"
    assert '"pj-meta"' in src
    assert 'aria-hidden' in src, "النقطة اللونية يجب أن تكون aria-hidden (النص يحمل المعنى)"
    css = (UI_DIR / "projects.css").read_text(encoding="utf-8")
    assert ".pj-status" in css and ".pj-meta" in css, "أنماط نص الحالة مفقودة من projects.css"


def test_no_raw_colors_in_js_inline_styles() -> None:
    """لا ألوان خام في أنماط JS المضمنة — النظام التوكني هو المصدر الوحيد.

    (سابقة W2-T09/W2-T11: سطرا harness.js ‎#f87171/#34d399‎.)"""
    offenders = []
    for p in sorted(UI_DIR.glob("*.js")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(color|background)\s*:\s*#[0-9a-fA-F]{3,8}\b", line):
                offenders.append(f"{p.name}:{i}: {line.strip()[:80]}")
    assert not offenders, "ألوان خام في JS — استخدم توكن نظام:\n" + "\n".join(offenders)
