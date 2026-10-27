#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T07 خطوة 4 (صرامة نهائية) — لقطات حتمية + أرضية ضجيج.
1) حقن CSS يقتل الأنيميشن/الانتقالات => إطار عرض واحد حتمي لكل لقطة.
2) التقاط كل زوج متتاليًا (قبل ثم بعد فورًا) لتقليل فجوة الزمن.
3) زوج تحكم: البعد مقابل نفسه (نفس الخادم مرتين) => أرضية ضجيج عدم الحتمية.
الحكم: لا انحدار <=> فرق (قبل/بعد) <= أرضية الضجيج أو تطابق حرفي.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

SCREENS_DIR = "/home/z/my-project/download/aes-remediation/W2-T07/screens"
EVID = "/home/z/my-project/download/aes-remediation/W2-T07"
RESULT = os.path.join(EVID, "20261027-visual-deterministic.json")

BEFORE_TREE = "/home/z/my-project/w2t07-before"
AFTER_TREE = "/home/z/my-project/repo"
PORT_BEFORE, PORT_AFTER = 8013, 8014
VENV = "/home/z/.venv/bin/python"

NAMES = [
    ("control-center", "/", None, False),
    ("control-center-mobile", "/", None, True),
    ("factory", "/#/factory", None, False),
    ("project-2", "/#/project/2", None, False),
    ("project-2-mobile", "/#/project/2", None, True),
    ("settings-drawer", "/", "click:#settings-open", False),
]

FREEZE_CSS = """
*, *::before, *::after {
  animation: none !important;
  transition: none !important;
  caret-color: transparent !important;
}
"""


def wait_health(port, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def run_server(tree, port):
    return subprocess.Popen(
        [VENV, "-m", "uvicorn", "api.routes:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=tree, env={**os.environ, "PYTHONPATH": "src"},
        stdout=open(f"/tmp/w2t07-det-server-{port}.log", "w"),
        stderr=subprocess.STDOUT,
    )


def shoot(browser, port, name, path, action, mobile, tag):
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
        locale="ar",
    )
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(f"console:{m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
    page.goto(f"http://127.0.0.1:{port}{path}", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2.5)
    page.add_style_tag(content=FREEZE_CSS)  # حتمية الإطار
    time.sleep(0.5)
    if action and action.startswith("click:"):
        try:
            page.click(action.split(":", 1)[1], timeout=5000)
            time.sleep(1.5)
        except Exception as ex:
            errors.append(f"click:{ex}")
    fname = os.path.join(SCREENS_DIR, f"{tag}-{name}.png")
    page.screenshot(path=fname, full_page=True)
    ctx.close()
    return {"file": os.path.basename(fname), "js_errors": errors}


def diff_stats(f1, f2):
    b = Image.open(f1).convert("RGB")
    a = Image.open(f2).convert("RGB")
    assert b.size == a.size, f"SIZE MISMATCH {f1} {b.size} vs {f2} {a.size}"
    d = ImageChops.difference(b, a)
    import numpy as np
    arr = np.asarray(d)
    nonzero = arr.any(axis=2)
    dp = int(nonzero.sum())
    md = int(arr.max()) if arr.size else 0
    ys, xs = nonzero.nonzero() if dp else ([], [])
    bbox = f"({xs.min()},{ys.min()},{xs.max()},{ys.max()})" if dp else "None"
    return {"diff_pixels": dp, "pct": round(100.0 * dp / (b.width * b.height), 4),
            "max_channel_delta": md, "bbox": str(bbox)}


def main():
    srv_b = run_server(BEFORE_TREE, PORT_BEFORE)
    srv_a = run_server(AFTER_TREE, PORT_AFTER)
    try:
        assert wait_health(PORT_BEFORE) and wait_health(PORT_AFTER), "SERVERS_NOT_HEALTHY"
        report = {"pairs": {}, "control": {}, "js_errors": {}}
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, path, action, mobile in NAMES:
                # زوج متتالي: قبل ثم بعد فورًا
                sb = shoot(browser, PORT_BEFORE, name, path, action, mobile, "det-before")
                sa = shoot(browser, PORT_AFTER, name, path, action, mobile, "det-after")
                # تحكم: البعد مرتين متتاليتين (أرضية الضجيج)
                sc1 = shoot(browser, PORT_AFTER, name, path, action, mobile, "ctrl1")
                sc2 = shoot(browser, PORT_AFTER, name, path, action, mobile, "ctrl2")
                pair = diff_stats(os.path.join(SCREENS_DIR, sb["file"]),
                                  os.path.join(SCREENS_DIR, sa["file"]))
                ctrl = diff_stats(os.path.join(SCREENS_DIR, sc1["file"]),
                                  os.path.join(SCREENS_DIR, sc2["file"]))
                report["pairs"][name] = pair
                report["control"][name] = ctrl
                report["js_errors"][name] = {
                    "before": sb["js_errors"], "after": sa["js_errors"], "ctrl": sc1["js_errors"] + sc2["js_errors"],
                }
                verdict = "NO_REGRESSION" if (
                    pair["diff_pixels"] == 0 or
                    (pair["diff_pixels"] <= max(ctrl["diff_pixels"], 50) and
                     pair["max_channel_delta"] <= 4)
                ) else "REVIEW"
                report["pairs"][name]["verdict"] = verdict
                print(name, "pair:", pair, "| ctrl:", ctrl, "=>", verdict)
            browser.close()
        report["task"] = "W2-T07 step4 — deterministic visual comparison with noise floor"
        with open(RESULT, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("DETERMINISTIC_VISUAL_DONE")
    finally:
        for s in (srv_b, srv_a):
            s.terminate()
        time.sleep(1.5)
        for s in (srv_b, srv_a):
            if s.poll() is None:
                s.kill()


if __name__ == "__main__":
    main()
