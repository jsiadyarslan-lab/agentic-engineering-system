#!/usr/bin/env python3
"""AES-UI-PREMIUM-REDESIGN-008 — Independent reviewer image verification.
Read-only analysis of the evidence package PNGs (baseline vs after vs reproof shots).
"""
import os
from PIL import Image

ROOT = "/home/z/my-project/ui007/docs/evidence/UI007_evidence"

def load(rel):
    p = os.path.join(ROOT, rel)
    im = Image.open(p)
    im.load()  # force full decode -> validates PNG structure
    return im, p

def stats(im):
    g = im.convert("L")
    w, h = g.size
    px = list(g.getdata())
    mean = sum(px) / len(px)
    return w, h, mean

def diff_metric(im1, im2):
    """Downscale both to common 512-wide grayscale; mean abs diff + % differing pixels."""
    target_w = 512
    def prep(im):
        g = im.convert("L")
        w, h = g.size
        nh = max(1, round(h * target_w / w))
        return g.resize((target_w, nh))
    a, b = prep(im1), prep(im2)
    if a.size != b.size:
        b = b.resize(a.size)
    pa, pb = a.getdata(), b.getdata()
    n = len(pa)
    tot = sum(abs(x - y) for x, y in zip(pa, pb))
    mad = tot / n
    pct = sum(1 for x, y in zip(pa, pb) if abs(x - y) > 8) / n * 100
    return mad, pct

pairs = [
    ("welcome-1440", 1440),
    ("chat-long-ar-1440", 1440),
    ("factory-1440", 1440),
    ("settings-general-1440", 1440),
    ("chat-en-1440", 1440),
    ("project-overview-1440", 1440),
    ("tablet-chat-768", 768),
    ("mobile-chat-390", 390),
]

print(f"{'pair':32} {'base WxH':12} {'after WxH':12} {'wOK':4} {'meanB':6} {'meanA':6} {'MAD':7} {'%diff>8':8}")
for name, want_w in pairs:
    b, _ = load(f"baseline/{name}.png")
    a, _ = load(f"after/{name}.png")
    bw, bh, bmean = stats(b)
    aw, ah, amean = stats(a)
    mad, pct = diff_metric(b, a)
    wok = "OK" if bw == want_w and aw == want_w else "BAD"
    print(f"{name:32} {bw}x{bh:<6} {aw}x{ah:<6} {wok:4} {bmean:6.1f} {amean:6.1f} {mad:7.2f} {pct:7.1f}%")

print()
# special pairs
special = [
    ("pop chat-long-ar-1440-full.png", "after chat-long-ar-1440-full.png", "full-page pop vs after"),
    ("chat-1440.png", "../reproof-008/shots/chat-1440.png", "baseline chat-1440 vs reproof re-capture"),
]
for brel, arel, label in special:
    b, _ = load(f"baseline/{brel}")
    a, _ = load(f"after/{arel}")
    bw, bh, bmean = stats(b)
    aw, ah, amean = stats(a)
    mad, pct = diff_metric(b, a)
    print(f"{label}: base {bw}x{bh} (mean {bmean:.1f}) vs after {aw}x{ah} (mean {amean:.1f}) MAD {mad:.2f} diff>8 {pct:.1f}%")

print()
# validity of every PNG in the three dirs (full decode, no blanks)
for d in ["baseline", "after", "reproof-008/shots"]:
    bad, blank = [], []
    n = 0
    for f in sorted(os.listdir(os.path.join(ROOT, d))):
        if not f.endswith(".png"):
            continue
        n += 1
        try:
            im, _ = load(f"{d}/{f}")
        except Exception as e:
            bad.append((f, str(e)))
            continue
        w, h, mean = stats(im)
        if mean < 3 or mean > 250:  # near-black or near-white blank
            blank.append((f, round(mean, 1)))
    print(f"{d}: {n} PNGs, decode failures: {len(bad)} {bad}, suspicious blanks: {len(blank)} {blank}")
