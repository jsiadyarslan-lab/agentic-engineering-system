#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T07 خطوة 4 — التحقق البصري قبل/بعد (سكربت ذري واحد).
قبل = 677b94d (أب مسح الألوان 0994d26) على 8013 · بعد = HEAD (المسح مطبق) على 8014.
الشاشتان تعملان على نسختين متطابقتين من قاعدة الاحتياط الإنتاجي nightly-20261027.db
(محليًا حصرًا — صفر مساس بالإنتاج).
اللقطات: مركز التحكم + المصنع + صفحة المشروع (2) + درج الإعدادات — مكتملة الصفحة.
تجمع أيضًا أخطاء console/page لكل شاشة (بوابة «صفر أخطاء JS»).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

SCREENS_DIR = "/home/z/my-project/download/aes-remediation/W2-T07/screens"
EVID = "/home/z/my-project/download/aes-remediation/W2-T07"
RESULT = os.path.join(EVID, "20261027-visual-before-after.json")

BEFORE_TREE = "/home/z/my-project/w2t07-before"
AFTER_TREE = "/home/z/my-project/repo"
PORT_BEFORE, PORT_AFTER = 8013, 8014
VENV = "/home/z/.venv/bin/python"

os.makedirs(SCREENS_DIR, exist_ok=True)

# (الاسم، المسار، الإجراء الاختياري قبل اللقطة، وضع الجوال؟)
SHOTS = [
    ("control-center", "/", None, False),
    ("control-center-mobile", "/", None, True),
    ("factory", "/#/factory", None, False),
    ("project-2", "/#/project/2", None, False),
    ("project-2-mobile", "/#/project/2", None, True),
    ("settings-drawer", "/", "click:#settings-open", False),
]


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
        stdout=open(f"/tmp/w2t07-server-{port}.log", "w"),
        stderr=subprocess.STDOUT,
    )


def capture(browser, port, label):
    base = f"http://127.0.0.1:{port}"
    out = {}
    for name, path, action, mobile in SHOTS:
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
            locale="ar",
        )
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(f"console:{m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
        try:
            # SSE يبقي اتصالًا مفتوحًا => networkidle لا يتحقق أبدًا؛
            # domcontentloaded + سكون ثابت هو النمط الصحيح هنا.
            page.goto(base + path, wait_until="domcontentloaded", timeout=20000)
        except Exception as ex:
            errors.append(f"goto:{ex}")
        time.sleep(3.0)
        if action and action.startswith("click:"):
            try:
                page.click(action.split(":", 1)[1], timeout=5000)
                time.sleep(1.5)
            except Exception as ex:
                errors.append(f"click:{ex}")
        fname = os.path.join(SCREENS_DIR, f"{label}-{name}.png")
        page.screenshot(path=fname, full_page=True)
        out[name] = {"file": os.path.basename(fname), "js_errors": errors, "url": page.url}
        ctx.close()
        print(f"  [{label}] {name} -> {os.path.basename(fname)} errors={len(errors)}")
    return out


def main():
    print("Starting BEFORE server (677b94d) :8013 ...")
    srv_before = run_server(BEFORE_TREE, PORT_BEFORE)
    print("Starting AFTER server (HEAD)     :8014 ...")
    srv_after = run_server(AFTER_TREE, PORT_AFTER)
    try:
        hb, ha = wait_health(PORT_BEFORE), wait_health(PORT_AFTER)
        print(f"health: before={hb} after={ha}")
        if not (hb and ha):
            print(open(f"/tmp/w2t07-server-{PORT_BEFORE}.log").read()[-800:])
            print(open(f"/tmp/w2t07-server-{PORT_AFTER}.log").read()[-800:])
            sys.exit("SERVERS_NOT_HEALTHY")

        result = {
            "task": "W2-T07 step4 — visual before/after (atomic local run)",
            "before": {"tree": BEFORE_TREE, "commit": "677b94d", "port": PORT_BEFORE},
            "after": {"tree": AFTER_TREE, "commit": "HEAD (color sweep 0994d26 applied)", "port": PORT_AFTER},
            "db": "nightly-20261027.db (production backup copy, local only)",
            "shots": {},
            "js_error_totals": {},
        }
        with sync_playwright() as p:
            browser = p.chromium.launch()
            print("Capturing BEFORE ...")
            result["shots"]["before"] = capture(browser, PORT_BEFORE, "before")
            print("Capturing AFTER ...")
            result["shots"]["after"] = capture(browser, PORT_AFTER, "after")
            browser.close()

        result["js_error_totals"] = {
            "before": sum(len(v["js_errors"]) for v in result["shots"]["before"].values()),
            "after": sum(len(v["js_errors"]) for v in result["shots"]["after"].values()),
        }
        with open(RESULT, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(json.dumps(result["js_error_totals"], ensure_ascii=False))
        print("VISUAL_CAPTURE_DONE")
    finally:
        for s in (srv_before, srv_after):
            s.terminate()
        time.sleep(1.5)
        for s in (srv_before, srv_after):
            if s.poll() is None:
                s.kill()


if __name__ == "__main__":
    main()
