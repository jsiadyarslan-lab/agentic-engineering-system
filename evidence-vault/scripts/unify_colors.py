# -*- coding: utf-8 -*-
"""توحيد لوحة الألوان عبر وحدات CSS كلها (AES-UI-PREMIUM-REDESIGN-001).

كل بديلة قائمة على تحليل سياق الاستخدام:
- الأزرق Tailwind (#2563eb/#60a5fa/#6ea8ff) → معلومات/تشغيل نشط → --info
- الأخضر (#16a34a/#34d399/#59c98d/#7fd8a4) → نجاح → --ok
- الأحمر (#dc2626/#f87171/#e06c5a/#e8906e) → خطأ → --danger
- الكهرماني (#d97706/#b45309/#fbbf24/#ffaa00) → تحذير/انتظار → --warn
- الرمادي #6b7280/#9a9aa8 → نص ثانوي → --text-dim
- النصوص #e8e8ef/#e6e6ef → --text
- الحدود #2a2a33 → --border-soft
- الخلفيات #14141b/#111827/#17171f/#1d1d27 → طبقاتنا
- النيلي rgba(99,102,241) (عنصر نشط) → ذهبي --accent-soft
"""
import re
import sys
from pathlib import Path

UI = Path("/home/z/my-project/ui-work/src/ui")

# (ملف, [(نمط, بديل, وصف)])
PLANS = {
    "app-shell.css": [
        (r"var\(--muted,\s*#9a9aa8\)", "var(--muted)", "fallback muted"),
        (r"var\(--fg,\s*#e8e8ef\)", "var(--fg)", "fallback fg"),
        (r"var\(--line,\s*#2a2a33\)", "var(--line)", "fallback line"),
        (r"var\(--card,\s*#1b1b22\)", "var(--card)", "fallback card"),
        (r"var\(--ink,\s*#e8e8ee?\)", "var(--ink)", "fallback ink"),
        (r"var\(--accent,\s*#6c8cff\)", "var(--accent)", "fallback accent"),
        (r"#e8906e", "var(--danger)", "خطر قديم"),
        (r"#7fd8a4", "var(--ok)", "نجاح قديم"),
        (r"#14141b", "var(--bg-input)", "خلفية إدخال"),
        (r"#17171f", "var(--bg-raised)", "سطح"),
        (r"#1d1d27", "var(--bg-elevated)", "سطح مرتفع"),
        (r"#1d3a2a", "var(--ok-chip)", "شريحة نجاح"),
        (r"#3a1d1d", "var(--danger-chip)", "شريحة خطر"),
        (r"#3a1d1d33", "var(--danger-chip)", "صف خطر"),
        (r"#3a1d1d44", "var(--danger-chip)", "خلفية خطر"),
        (r"rgba\(232,\s*144,\s*110,\s*0\.45\)", "var(--danger-border)", "حد خطر"),
        (r"rgba\(232,\s*144,\s*110,\s*0\.07\)", "var(--danger-soft)", "سطح خطر"),
        (r"#2a1212f2", "rgba(24, 11, 9, 0.96)", "حدود أخطاء"),
        (r"#a9553f66", "var(--danger-border)", "حد خطر"),
        (r"#a9553f88", "var(--danger-border)", "حد زر خطر"),
        (r"#a9553f\b", "var(--danger)", "زر خطر"),
        (r"#1d2a3a55", "var(--info-chip)", "بيئة معلومات"),
        (r"#3a2a1d55", "var(--warn-chip)", "بيئة تحذير"),
        (r"#e8c26e", "var(--warn)", "نص تحذير"),
        (r"rgba\(0,\s*0,\s*0,\s*0\.25\)", "rgba(0, 0, 0, 0.25)", "يبقى"),
    ],
    "projects.css": [
        (r"rgba\(255,\s*255,\s*255,\s*0\.05\)", "var(--bg-hover)", "تحويم"),
        (r"rgba\(99,\s*102,\s*241,\s*0\.16\)", "var(--accent-soft)", "نشط نيلي → ذهبي"),
        (r"#34d399", "var(--ok)", "نجاح"),
        (r"#60a5fa", "var(--info)", "تشغيل"),
        (r"#fbbf24", "var(--warn)", "انتظار"),
        (r"#f87171", "var(--danger)", "خطر"),
        (r"rgba\(52,\s*211,\s*153,\s*0\.4\)", "var(--ok-border)", "حد نجاح"),
        (r"rgba\(96,\s*165,\s*250,\s*0\.4\)", "var(--info-border)", "حد تشغيل"),
        (r"rgba\(251,\s*191,\s*36,\s*0\.4\)", "var(--warn-border)", "حد انتظار"),
        (r"rgba\(248,\s*113,\s*113,\s*0\.4\)", "var(--danger-border)", "حد خطر"),
        (r"var\(--muted,\s*#9a9aa8\)", "var(--muted)", "fallback"),
        (r"var\(--line,\s*#2a2a33\)", "var(--line)", "fallback"),
    ],
    "control-center.css": [
        (r"#6b7280", "var(--text-dim)", "رمادي tw"),
        (r"rgba\(37,\s*99,\s*235,\s*\.10\)", "var(--info-chip)", "شريحة معلومات"),
        (r"rgba\(37,\s*99,\s*235,\s*\.4\)", "var(--info-border)", "حد معلومات"),
        (r"rgba\(37,\s*99,\s*235,\s*\.35\)", "var(--info-border)", "حد معلومات"),
        (r"rgba\(37,\s*99,\s*235,\s*\.08\)", "var(--info-soft)", "سطح معلومات"),
        (r"rgba\(37,\s*99,\s*235,\s*\.15\)", "var(--info-chip)", "تحويم معلومات"),
        (r"rgba\(37,\s*99,\s*235,\s*\.07\)", "var(--info-soft)", "سطح معلومات"),
        (r"rgba\(37,\s*99,\s*235,\s*\.25\)", "var(--info-border)", "حد معلومات"),
        (r"#2563eb", "var(--info)", "أزرق tw"),
        (r"#16a34a", "var(--ok)", "أخضر tw"),
        (r"#dc2626", "var(--danger)", "أحمر tw"),
        (r"rgba\(220,\s*38,\s*38,\s*\.3\)", "var(--danger-border)", "حد خطر"),
        (r"#d97706", "var(--warn)", "كهرماني tw"),
        (r"#b45309", "var(--warn)", "كهرماني داكن tw"),
        (r"#111827", "var(--bg-elevated)", "سطح tw"),
        (r"rgba\(17,\s*24,\s*39,\s*\.06\)", "rgba(0, 0, 0, 0.24)", "سطح خافت"),
    ],
    "harness.css": [
        (r"#9a9aa8", "var(--text-dim)", "رمادي"),
        (r"#2a2a33", "var(--border-soft)", "حد"),
        (r"#e6e6ef", "var(--text)", "نص"),
        (r"#fbbf24", "var(--warn)", "كهرماني"),
        (r"#34d399", "var(--ok)", "أخضر"),
        (r"#60a5fa", "var(--info)", "أزرق"),
        (r"#f87171", "var(--danger)", "أحمر"),
        (r"#f472b6", "#D98BA8", "حكم وردي متناسق"),
        (r"var\(--muted,\s*#9a9aa8\)", "var(--muted)", "fallback"),
        (r"var\(--line,\s*#2a2a33\)", "var(--line)", "fallback"),
    ],
    "live.css": [
        (r"#3a4a6b", "var(--border)", "حد مزرق"),
        (r"#59c98d", "var(--ok)", "أخضر"),
        (r"#e06c5a", "var(--danger)", "أحمر"),
        (r"#6ea8ff", "var(--info)", "أزرق"),
        (r"#f0a99e", "var(--danger)", "أحمر فاتح"),
        (r"#ffaa00", "var(--warn)", "كهرماني"),
        (r"#e0a35a", "var(--warn)", "كهرماني"),
        (r"#a04a3c", "var(--danger-border)", "حد أحمر"),
    ],
    "project-live.css": [
        (r"#d9b25f", "var(--accent)", "ذهبي قديم"),
    ],
}

total = 0
for fname, rules in PLANS.items():
    path = UI / fname
    src = path.read_text(encoding="utf-8")
    counts = []
    for pat, rep, desc in rules:
        if pat == rep:
            continue
        n = len(re.findall(pat, src))
        if n:
            src = re.sub(pat, rep, src)
            counts.append(f"  {desc}: {n}")
    path.write_text(src, encoding="utf-8")
    if counts:
        print(f"{fname}:")
        print("\n".join(counts))
        total += sum(int(c.split(": ")[1]) for c in counts)
    else:
        print(f"{fname}: (لا تغييرات)")

print(f"\nإجمالي الاستبدالات: {total}")
