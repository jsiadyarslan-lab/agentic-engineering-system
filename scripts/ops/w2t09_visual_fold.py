#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T09 — تحقق بصري ذري قبل/بعد مع قياس موضوعي لموضع البث فوق الطية.
قبل = HEAD الحالي (worktree نظيف) · بعد = شجرة العمل (تعديلات W2-T09).
القياس: getBoundingClientRect لبطاقة البث/الشريط/البلاطات القديمة — الهدف:
البث داخل أول إطار عرض (1440x900 و390x844) بدل ~600px تحت.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

EVID = "/home/z/my-project/download/aes-remediation/W2-T09"
SCREENS = os.path.join(EVID, "screens")
os.makedirs(SCREENS, exist_ok=True)

BEFORE_TREE = "/home/z/my-project/w2t09-before"
AFTER_TREE = "/home/z/my-project/repo"
PORT_BEFORE, PORT_AFTER = 8015, 8016
VENV = "/home/z/.venv/bin/python"

FREEZE_CSS = """
*, *::before, *::after {
  animation: none !important;
  transition: none !important;
  caret-color: transparent !important;
}
"""

MEASURE_JS = """
() => {
  const vh = window.innerHeight;
  const q = (sel) => { const el = document.querySelector(sel); if (!el) return null;
    const r = el.getBoundingClientRect(); return {top: Math.round(r.top), height: Math.round(r.height)}; };
  return {
    viewport_h: vh,
    live_card: q('.fc-live-card') || q('#factory-body .fc-card:nth-of-type(3)'),
    statbar: q('.fc-statbar'),
    old_system_card: q('.fc-system-card'),
    runs_list: q('.fc-runs-list'),
    first_card_in_body: q('#factory-body .fc-card'),
    empty_tiles: Array.from(document.querySelectorAll('.fc-stat')).map(e => {
      const r = e.getBoundingClientRect();
      return {top: Math.round(r.top), label: (e.querySelector('.fc-stat-label')||{}).textContent || ''};
    }),
  };
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
        stdout=open(f"/tmp/w2t09-server-{port}.log", "w"),
        stderr=subprocess.STDOUT,
    )


def shoot(browser, port, tag, mobile):
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
        locale="ar",
    )
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(f"console:{m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
    page.goto(f"http://127.0.0.1:{port}/#/factory", wait_until="domcontentloaded", timeout=20000)
    time.sleep(3.5)
    page.add_style_tag(content=FREEZE_CSS)
    time.sleep(0.5)
    fname = os.path.join(SCREENS, f"{tag}-factory{'-mobile' if mobile else ''}.png")
    page.screenshot(path=fname, full_page=False)  # الإطار الأول فقط — هذا هو اختبار «فوق الطية»
    measure = page.evaluate(MEASURE_JS)
    ctx.close()
    return {"file": os.path.basename(fname), "js_errors": errors, "measure": measure}


def main():
    # worktree نظيف عند HEAD كـ«قبل»
    subprocess.run(["git", "-C", AFTER_TREE, "worktree", "add", BEFORE_TREE, "HEAD"],
                   capture_output=True, text=True)
    # نسخ قاعدة الإنتاج إلى شجرتي قبل/بعد
    import shutil
    for tree in (BEFORE_TREE, AFTER_TREE):
        dst = os.path.join(tree, "runtime", "agent_hub_v2.db")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy("/home/z/my-project/download/aes-remediation/W2-T07/nightly-20261027.db", dst)

    srv_b = run_server(BEFORE_TREE, PORT_BEFORE)
    srv_a = run_server(AFTER_TREE, PORT_AFTER)
    report = {"pairs": {}}
    try:
        assert wait_health(PORT_BEFORE) and wait_health(PORT_AFTER), "SERVERS_NOT_HEALTHY"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for mobile in (False, True):
                key = "mobile" if mobile else "desktop"
                b = shoot(browser, PORT_BEFORE, "before", mobile)
                a = shoot(browser, PORT_AFTER, "after", mobile)
                report["pairs"][key] = {"before": b, "after": a}
                print(f"[{key}] before errors={len(b['js_errors'])} after errors={len(a['js_errors'])}")
                print(f"  before measure: {json.dumps(b['measure'], ensure_ascii=False)[:300]}")
                print(f"  after  measure: {json.dumps(a['measure'], ensure_ascii=False)[:300]}")
            browser.close()
        report["task"] = "W2-T09 — live stream above the fold: before/after with objective position measurement"
        with open(os.path.join(EVID, "20261027-visual-fold.json"), "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("FOLD_CAPTURE_DONE")
    finally:
        for s in (srv_b, srv_a):
            s.terminate()
        time.sleep(1.5)
        for s in (srv_b, srv_a):
            if s.poll() is None:
                s.kill()


if __name__ == "__main__":
    main()
