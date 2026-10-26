"""AES-014 — عقود نظام التوكنات المعياري (المرحلة صفر).

يقفل جدول التوكنات الملزم من خطة AES-013 (القسم 7.0) حرفيًا:
  T1  القيم الكنسية التسعة عشر موجودة نصًا في theme.css.
  T2  (G2) أربع طبقات أسطح بفروق إضاءة HSL ≥3% بين كل طبقتين متجاورتين.
  T3  أرضية تباين AA: primary/secondary ≥4.5:1 على الأسطح الأربعة،
      muted ≥4.5:1 على أسطح المحتوى (canvas/sidebar/raised).
  T4  (G7) مسح CSS: لا letter-spacing غير صفري إلا في سياق لاتيني صريح
      (direction:ltr / unicode-bidi / mono / uppercase) — في كل ملفات الواجهة.
  T5  (G1) عنوان البطل display 40px/700/1.15 · الجسم 15/1.6 · الشريط 260px.
  T6  الأسماء القديمة مستعارة (لا مراجع معلقة) وأنصاف ثلاثة فقط 8/12/999.
  T7  (G3) القاعدة الأحادية 13px + tnum مقفلة في theme.css.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI = REPO / "src" / "ui"
THEME = (UI / "theme.css").read_text(encoding="utf-8")
STYLES = (UI / "styles.css").read_text(encoding="utf-8")
SHELL = (UI / "app-shell.css").read_text(encoding="utf-8")

CSS_FILES = sorted(UI.glob("*.css"))
ALL_CSS = "\n".join(p.read_text(encoding="utf-8") for p in CSS_FILES)


# ---------------------------------------------------------------- T1: القيم

def test_t1_canonical_token_values_locked():
    """جدول 7.0 حرفيًا — أي انحراف يسقط العقد."""
    locked = {
        "--bg-canvas: #0A0D12",
        "--bg-sidebar: #12171F",
        "--bg-raised: #191E29",
        "--bg-hover: #212834",
        "--border-subtle: rgba(255, 255, 255, 0.07)",
        "--border-strong: rgba(255, 255, 255, 0.13)",
        "--text-primary: #F5F7FA",
        "--text-secondary: #B8C0CC",
        "--text-muted: #7D8794",
        "--accent: #58A6FF",
        "--ok: #3FB68B",
        "--warn: #E5A54B",
        "--danger: #E5574B",
        "--fs-display: 40px",
        "--lh-display: 1.15",
        "--lh-body: 1.6",
        "--fs-h1: 24px",
        "--fs-h2: 19px",
        "--fs-h3: 16px",
        "--sidebar-width: 260px",
        "--chat-width: 720px",
        "--elev-1: 0 8px 24px rgba(0, 0, 0, 0.35)",
        "--focus-ring: 0 0 0 3px rgba(88, 166, 255, 0.25)",
        "--ease: ease-out",
        "--dur-fast: 0.15s",
        "--dur-slow: 0.2s",
    }
    missing = [tok for tok in locked if tok not in THEME]
    assert not missing, f"توكنات مفقودة/منحرفة عن الجدول الملزم: {missing}"


# ------------------------------------------------- T2: فروق الإضاءة (G2)

def _hex_to_rgb(hx: str) -> tuple[int, int, int]:
    hx = hx.lstrip("#")
    return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)


def _hsl_lightness(hx: str) -> float:
    r, g, b = _hex_to_rgb(hx)
    return (max(r, g, b) + min(r, g, b)) / 2 / 255 * 100


def test_t2_four_surface_layers_separated():
    """G2 — فرق إضاءة ≥3% بين كل طبقتين متجاورتين (المقيس من القيم)."""
    layers = [
        ("canvas", "#0A0D12"),
        ("sidebar", "#12171F"),
        ("raised", "#191E29"),
        ("hover", "#212834"),
    ]
    light = [(name, _hsl_lightness(hx)) for name, hx in layers]
    for (n1, l1), (n2, l2) in zip(light, light[1:]):
        assert l2 - l1 >= 3.0, (
            f"طبقتا {n1}({l1:.1f}%) و{n2}({l2:.1f}%) فرقهما < 3% — العمق ينهار"
        )


# ------------------------------------------------------ T3: تباين AA

def _srgb_to_linear(v: int) -> float:
    s = v / 255
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def _rel_lum(hx: str) -> float:
    r, g, b = _hex_to_rgb(hx)
    return (
        0.2126 * _srgb_to_linear(r)
        + 0.7152 * _srgb_to_linear(g)
        + 0.0722 * _srgb_to_linear(b)
    )


def _contrast(a: str, b: str) -> float:
    la, lb = _rel_lum(a), _rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_t3_contrast_floor_aa():
    """أرضية AA رقميًا — النصوص على أسطحها الفعلية."""
    all_surfaces = ["#0A0D12", "#12171F", "#191E29", "#212834"]
    content_surfaces = ["#0A0D12", "#12171F", "#191E29"]
    for s in all_surfaces:
        for name, t in [("primary", "#F5F7FA"), ("secondary", "#B8C0CC")]:
            r = _contrast(t, s)
            assert r >= 4.5, f"{name} على {s}: {r:.2f}:1 < 4.5"
    for s in content_surfaces:
        r = _contrast("#7D8794", s)
        assert r >= 4.5, f"muted على {s}: {r:.2f}:1 < 4.5 (أزمنة/تسميات فقط)"
    # الحالات الدلالية على أضعف سطح دلالي (chip على canvas)
    for name, c in [("ok", "#3FB68B"), ("warn", "#E5A54B"), ("err", "#E5574B")]:
        r = _contrast(c, "#0A0D12")
        assert r >= 4.5, f"{name} على canvas: {r:.2f}:1 < 4.5"


# ------------------------------------------- T4: مسح G7 (letter-spacing)

def _rule_blocks(css: str):
    """يبدّل التعليقات، ثم يقطع كتل القواعد مع محدداتها."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, body = m.group(1).strip(), m.group(2)
        if sel.startswith("@"):  # المحددات داخل media تُقرأ كذلك
            continue
        yield sel, body


LATIN_MARKERS = (
    "direction: ltr",
    "unicode-bidi",
    "var(--font-mono)",
    "var(--mono)",
    "text-transform: uppercase",
)


def test_t4_g7_zero_letter_spacing_on_arabic():
    """G7 — أي letter-spacing غير صفري يجب أن يكون في سياق لاتيني صريح."""
    offenders = []
    for path in CSS_FILES:
        css = path.read_text(encoding="utf-8")
        for sel, body in _rule_blocks(css):
            for m in re.finditer(r"letter-spacing:\s*([^;]+);", body):
                val = m.group(1).strip()
                if val in ("0", "0px", "normal"):
                    continue
                if any(marker in body for marker in LATIN_MARKERS):
                    continue  # سياق لاتيني صريح — معفى
                offenders.append(f"{path.name} :: {sel.strip()[:60]} → {val}")
    assert not offenders, (
        "قواعد تحمل letter-spacing على نص يمكن أن يكون عربيًا (G7):\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------- T5: G1 قياسات مطبعية

def test_t5_g1_typography_locks():
    """G1 (جزء الملفات) — البطل display والجسم 1.6 والشريط 260."""
    assert "font-size: var(--fs-display)" in STYLES  # .welcome h1
    assert "line-height: var(--lh-display)" in STYLES
    assert "line-height: var(--lh-body)" in STYLES   # html, body
    assert "width: var(--sidebar-width)" in STYLES
    assert "max-width: var(--chat-width)" in SHELL
    # الجوال: بطل الجوال على درجة h1 (24px) لا 28
    assert "font-size: var(--fs-22)" in STYLES


# --------------------------------------- T6: الأسماء القديمة والأنصاف

def test_t6_legacy_aliases_and_radius_scale():
    """لا مراجع معلقة لقيم قديمة، والأنصاف ثلاثة فقط."""
    for alias in [
        "--bg:", "--panel:", "--ink:", "--line:", "--muted:", "--fg:",
        "--text:", "--text-mid:", "--text-dim:", "--border:",
        "--card:", "--ok-strong:", "--danger-strong:", "--warn-strong:",
    ]:
        assert alias in THEME, f"الاسم المستعار القديم {alias} مفقود — fallbacks ستتصارع"
    # أنصاف القطر في theme.css: ثلاث قيم فقط
    radii = set(re.findall(r"--radius-[a-z]+:\s*([^;]+);", THEME))
    assert radii <= {"8px", "12px", "999px"}, f"قيمة نصف قطر رابعة: {radii}"
    assert "--radius-l: 12px" in THEME  # كان 16 — انضبط


# ------------------------------------------------ T7: G3 القاعدة الأحادية

def test_t7_g3_mono_and_tnum_doctrine():
    """G3 — mono 13px + tnum للقيم التقنية، وtnum للجسم."""
    assert 'font-feature-settings: "tnum" 1' in THEME
    assert ".tech, code, .md-code { font-size: var(--fs-13); }" in THEME
    assert "--fs-13: 13px" in THEME
    assert "--font-mono: \"IBM Plex Mono\"" in THEME
