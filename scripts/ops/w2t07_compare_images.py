#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T07 خطوة 4 — تركيب مقارنات جانبية (قبل|بعد) + تكبيرات مربعات الفرق."""
import json
import os

from PIL import Image, ImageDraw

SCREENS = "/home/z/my-project/download/aes-remediation/W2-T07/screens"
OUTDIR = os.path.join(SCREENS, "compare")
os.makedirs(OUTDIR, exist_ok=True)

PAIRS = {
    "control-center": (1406, 17, 1428, 39),
    "factory": (838, 17, 1428, 41),
    "project-2": (318, 17, 1427, 855),
    "project-2-mobile": (34, 280, 355, 344),
    "settings-drawer": (1396, 8, 1437, 46),
}

def side_by_side(name, zoom_box=None):
    b = Image.open(os.path.join(SCREENS, f"det-before-{name}.png")).convert("RGB")
    a = Image.open(os.path.join(SCREENS, f"det-after-{name}.png")).convert("RGB")
    h = max(b.height, a.height)
    canvas = Image.new("RGB", (b.width + a.width + 8, h), "#ff00ff")
    canvas.paste(b, (0, 0))
    canvas.paste(a, (b.width + 8, 0))
    tag = "" if zoom_box is None else "-zoom"
    canvas.save(os.path.join(OUTDIR, f"side-{name}{tag}.png"))
    if zoom_box:
        x1, y1, x2, y2 = zoom_box
        pad = 30
        box = (max(0, x1 - pad), max(0, y1 - pad), x2 + pad, y2 + pad)
        cb = b.crop(box).resize(((box[2] - box[0]) * 6, (box[3] - box[1]) * 6), Image.NEAREST)
        ca = a.crop(box).resize(((box[2] - box[0]) * 6, (box[3] - box[1]) * 6), Image.NEAREST)
        w = cb.width + ca.width + 8
        canvas2 = Image.new("RGB", (w, cb.height), "#ff00ff")
        canvas2.paste(cb, (0, 0))
        canvas2.paste(ca, (cb.width + 8, 0))
        canvas2.save(os.path.join(OUTDIR, f"zoom-{name}.png"))
    return os.path.join(OUTDIR, f"side-{name}.png")

made = []
for name, box in PAIRS.items():
    made.append(side_by_side(name, box))
# الجوال المطابق حرفيًا: مقارنة عادية فقط
b = Image.open(os.path.join(SCREENS, "det-before-control-center-mobile.png")).convert("RGB")
a = Image.open(os.path.join(SCREENS, "det-after-control-center-mobile.png")).convert("RGB")
canvas = Image.new("RGB", (b.width + a.width + 8, max(b.height, a.height)), "#ff00ff")
canvas.paste(b, (0, 0)); canvas.paste(a, (b.width + 8, 0))
canvas.save(os.path.join(OUTDIR, "side-control-center-mobile.png"))
made.append(os.path.join(OUTDIR, "side-control-center-mobile.png"))
print(json.dumps({"made": [os.path.basename(m) for m in made]}, ensure_ascii=False, indent=2))
print("COMPARE_IMAGES_DONE")
