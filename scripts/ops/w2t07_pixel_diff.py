#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T07 خطوة 4 — فرق البكسل الموضوعي قبل/بعد لكل زوج لقطات.
المتوقع حسب سجل التنفيذ: تطابق شبه تام (13 توكنًا جديدًا بقيم حرفية مطابقة)
مع انحرافات موثقة ≤0.05 ألفا أو ≤4/255 قناة في 19 موضعًا (غير مُدرَكة بصريًا).
المخرجات: جدول لكل زوج (بكسلات مختلفة / أقصى فرق قناة / نسبة الاختلاف).
"""
import json
import os

from PIL import Image, ImageChops

SCREENS = "/home/z/my-project/download/aes-remediation/W2-T07/screens"
OUT = "/home/z/my-project/download/aes-remediation/W2-T07/20261027-pixel-diff.json"

NAMES = [
    "control-center", "control-center-mobile", "factory",
    "project-2", "project-2-mobile", "settings-drawer",
]


def pair_stats(name):
    b = Image.open(os.path.join(SCREENS, f"before-{name}.png")).convert("RGB")
    a = Image.open(os.path.join(SCREENS, f"after-{name}.png")).convert("RGB")
    size_match = b.size == a.size
    if not size_match:
        # وحّد الأبعاد للمقارنة (التطابق المتوقع يشمل الأبعاد)
        w, h = min(b.width, a.width), min(b.height, a.height)
        b, a = b.crop((0, 0, w, h)), a.crop((0, 0, w, h))
    diff = ImageChops.difference(b, a)
    bbox = diff.getbbox()
    hist = diff.histogram()  # لكل قناة 256 سلة
    total_px = b.width * b.height
    # بكسلات مختلفة = أي بكسل ليست قنواته الثلاث صفرًا
    diff_px = sum(1 for i in range(0, len(hist), 256) if False for _ in [0])  # placeholder
    # حساب أدق عبر مصفوفة
    import numpy as np
    arr = np.asarray(diff)
    nonzero_mask = arr.any(axis=2)
    diff_px = int(nonzero_mask.sum())
    max_delta = int(arr.max()) if arr.size else 0
    return {
        "size": f"{b.width}x{b.height}",
        "size_match": bool(size_match),
        "diff_bbox": str(bbox),
        "diff_pixels": diff_px,
        "diff_pixels_pct": round(100.0 * diff_px / total_px, 4),
        "max_channel_delta": max_delta,
        "verdict": "IDENTICAL" if diff_px == 0 else
                   ("IMPERCEPTIBLE" if max_delta <= 4 and diff_px_pct_small(diff_px, total_px) else "CHECK"),
    }


def diff_px_pct_small(dp, total):
    return 100.0 * dp / total < 5.0


def main():
    results = {}
    for n in NAMES:
        results[n] = pair_stats(n)
        print(n, "->", results[n])
    with open(OUT, "w") as f:
        json.dump({"task": "W2-T07 step4 — pixel diff before/after", "pairs": results}, f, ensure_ascii=False, indent=2)
    print("PIXEL_DIFF_DONE")


if __name__ == "__main__":
    main()
