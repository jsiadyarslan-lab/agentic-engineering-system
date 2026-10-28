# -*- coding: utf-8 -*-
"""W2-T11 — الفحص الساكن لتباين التوكنات (قبل/بعد الإصلاح).

يحسب نسب تباين WCAG لكل زوج (توكن نص × سطح) في theme.css:
  - أدوار النص: --text-primary/--text-secondary/--text-muted (+ المستعارات)
    على الأسطح الأربعة: --bg-canvas/--bg-sidebar/--bg-raised/--bg-hover.
  - نصوص الرقائق الدلالية (ok/danger/warn/info/agent) على رقائقها
    المركّبة فوق --bg-elevated.
  - استثناء موثق: --text-disabled (عناصر معطلة — معفاة من AA).

قاعدة القبول: >= 4.5:1 لكل نص (لا نص كبير في نظامنا أصغر من 24px
غير العناوين، والعناوين primary أصلاً).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "repo" / "src" / "ui"
THEME = (UI / "theme.css").read_text(encoding="utf-8")


def lum(hexstr: str) -> float:
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: str, b: str) -> float:
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def tok(name: str) -> str:
    m = re.search(rf"^\s*--{re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{3,8}})\b", THEME, re.M)
    if not m:
        raise KeyError(name)
    return m.group(1)


def composite(over_hex: str, alpha: float, under_hex: str) -> str:
    """يركّب لونًا شفافًا فوق مصمت ويعيد hex النتيجة."""
    o = over_hex.lstrip("#")
    u = under_hex.lstrip("#")
    if len(o) == 3:
        o = "".join(c * 2 for c in o)
    if len(u) == 3:
        u = "".join(c * 2 for c in u)
    out = []
    for i in (0, 2, 4):
        ov = int(o[i:i + 2], 16)
        un = int(u[i:i + 2], 16)
        out.append(int(round(ov * alpha + un * (1 - alpha))))
    return "#" + "".join(f"{v:02X}" for v in out)


def rgba_tok(name: str) -> tuple[str, float]:
    m = re.search(rf"^\s*--{re.escape(name)}\s*:\s*rgba?\(\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)"
                  rf"(?:\s*,\s*([0-9.]+))?\s*\)", THEME, re.M)
    if not m:
        raise KeyError(name)
    r, g, b = (int(m.group(i)) for i in (1, 2, 3))
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return f"#{r:02X}{g:02X}{b:02X}", a


SURFACES = {
    "bg-canvas": lambda: tok("bg-canvas"),
    "bg-sidebar": lambda: tok("bg-sidebar"),
    "bg-raised": lambda: tok("bg-raised"),
    "bg-hover": lambda: tok("bg-hover"),
    "bg-elevated": lambda: tok("bg-elevated"),
}

TEXT_ROLES = ["text-primary", "text-secondary", "text-muted", "text-disabled"]
EXEMPT = {"text-disabled": "عناصر معطلة فقط — WCAG يعفي النص المعطل (1.4.3 استثناء)"}

# رقائق الدلالة: نص الرقيقة على خلفيتها المركبة فوق elevated
# (chip.danger ترجع إلى --danger-hi منذ W2-T11 — الزوج الصلب المهجور لا يُفحص)
CHIPS = {
    "chip.ok(ok على ok-chip)": (lambda: (tok("ok"), composite(*rgba_tok("ok-chip"), tok("bg-elevated")))),
    "chip.danger(danger-hi على danger-chip)": (lambda: (
        tok("danger-hi") if re.search(r"^\s*--danger-hi\s*:", THEME, re.M) else tok("danger"),
        composite(*rgba_tok("danger-chip"), tok("bg-elevated")))),
    "chip.warn(warn على warn-chip)": (lambda: (tok("warn"), composite(*rgba_tok("warn-chip"), tok("bg-elevated")))),
    "chip.info(info على info-chip)": (lambda: (tok("info"), composite(*rgba_tok("info-chip"), tok("bg-elevated")))),
    "chip.agent(accent على accent-soft)": (lambda: (tok("accent"), composite(*rgba_tok("accent-soft"), tok("bg-elevated")))),
}


def main() -> int:
    rows = []
    failures = []
    for role in TEXT_ROLES:
        fg = tok(role)
        for sname, sfn in SURFACES.items():
            bg = sfn()
            ratio = contrast(fg, bg)
            row = {"pair": f"--{role} على --{sname}", "fg": fg, "bg": bg,
                   "ratio": round(ratio, 2), "required": 4.5}
            if role in EXEMPT:
                row["exempt"] = EXEMPT[role]
            elif ratio < 4.5:
                failures.append(row)
            rows.append(row)
    for label, fn in CHIPS.items():
        fg, bg = fn()
        ratio = contrast(fg, bg)
        row = {"pair": label, "fg": fg, "bg": bg, "ratio": round(ratio, 2), "required": 4.5}
        if ratio < 4.5:
            failures.append(row)
        rows.append(row)

    out = {
        "task": "W2-T11",
        "check": "static token contrast (WCAG 1.4.3 AA = 4.5:1)",
        "source": "src/ui/theme.css",
        "total_pairs": len(rows),
        "failures": len(failures),
        "rows": rows,
    }
    dest = Path("/home/z/my-project/download/aes-remediation/W2-T11/static_token_contrast.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    for r in rows:
        flag = "FAIL" if r["ratio"] < r.get("required", 4.5) and "exempt" not in r else ("معفى" if "exempt" in r else "pass")
        print(f"[{flag:>4}] {r['pair']:<46} {r['fg']} على {r['bg']}  = {r['ratio']}:1")
    print(f"\nالمجموع: {len(rows)} زوجًا · الإخفاقات: {len(failures)}")
    print(f"الدليل: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
