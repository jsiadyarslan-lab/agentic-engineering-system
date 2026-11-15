#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R1-F — إعادة الفحص الميكانيكي البصري (51 حالة) بعد تعديلات R1
AES-FACTORY-CONSOLE-REARCHITECTURE-001-R1 §6 R1-F.

نفس بنية audit.json الأصلية (17 سطحًا × 3 مقاسات):
  {vp, surface, overflowX, drawerOpen, errors}
  overflowX: null إن لا فيض أفقي، وإلا الفارق بالبكسل.
  drawerOpen: حالة درج التنقل الجانبي بعد الوصول للسطح (الموبايل فقط —
              يجب أن يبقى مغلقًا فوق مساحة العمل).
  errors: عدد أخطاء JS (pageerror + console.error).

زائد فحص سلوك الدرج الحقيقي على الموبايل (إثبات §7 الحاسم):
  ☰ يفتح الدرج → اختيار سطح يغلقه تلقائيًا → نقطة خارجية تغلقه → Escape يغلقه.
  مسجل في summary.drawer_flow مع لقطاته.

الخادم الحي حقيقي بقاعدة جديدة (حالات فراغ صادقة — لا بيانات مختلقة).
الخرج: docs/rearchitecture-001/r1/audit.json + لقطات r1/screenshots/.
"""

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
REPO = Path(__file__).resolve().parent.parent
EV = REPO / "docs" / "rearchitecture-001" / "r1"
SHOTS = EV / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

VIEWPORTS = [
    ("desktop1600", 1600, 900),
    ("laptop1366", 1366, 768),
    ("mobile390", 390, 844),
]
SURFACES = ["overview", "projects", "tasks", "activity", "reviews",
            "agents", "artifacts", "logs", "chat", "factory", "archive"]
HASH_ROUTABLE = {"overview", "projects", "tasks", "activity", "reviews",
                 "agents", "artifacts", "logs"}
SETTINGS_TABS = ["general", "models", "providers", "execution", "tools",
                 "advanced"]


def drawer_open_mobile(pg):
    return pg.evaluate(
        "() => window.matchMedia('(max-width: 900px)').matches &&"
        " !document.body.classList.contains('sidebar-collapsed')")


def measure(pg, vp_name):
    overflow = pg.evaluate(
        "() => Math.max(0, document.documentElement.scrollWidth -"
        " document.documentElement.clientWidth)")
    drawer_open = drawer_open_mobile(pg) if vp_name == "mobile390" else False
    return overflow, drawer_open


def run_case(pg, vp_name, surface, errors_count):
    """التنقل بمسارات المستخدم الفعلية: الهاش للمحاور المؤسسية،
    وshowView للسطوح غير المؤسسية (نفس عقد أزرار التنقل)،
    والحدث الموثق hub:open-settings للإعدادات على الموبايل
    (زر الترس يسكن داخل الدرج المغلق — نفس نقطة التكامل app.js:40)."""
    if surface in HASH_ROUTABLE:
        pg.evaluate("() => { location.hash = '#/%s'; }" % surface)
    elif surface in ("chat", "factory", "archive"):
        pg.evaluate("() => window.ControlCenter.showView('%s');" % surface)
    time.sleep(1.4)
    overflow, drawer_open = measure(pg, vp_name)
    errs = errors_count["n"]
    pg.screenshot(path=str(SHOTS / ("%s_%s.png" % (vp_name, surface))))
    return {
        "vp": vp_name, "surface": surface,
        "overflowX": (None if overflow == 0 else overflow),
        "drawerOpen": bool(drawer_open), "errors": errs,
    }


def drawer_flow_case(pg, flow_results):
    """إثبات §7 على البناء المعدّل: فتح حقيقي → إغلاق بالاختيار/خارجي/زر/Escape.
    ☰ يسكن ترويسة المحادثة حصرًا — العودة للمحادثة قبل كل فتح (مسار المستخدم)."""
    steps = []
    pg.keyboard.press("Escape")  # إغلاق الإعدادات إن كانت مفتوحة من آخر تبويب
    time.sleep(0.6)
    pg.evaluate("() => window.ControlCenter.showView('chat');")
    time.sleep(1.0)
    # 1) ☰ يفتح الدرج
    pg.locator("#sidebar-toggle").first.click()
    time.sleep(0.6)
    opened = drawer_open_mobile(pg)
    steps.append({"step": "M1_فتح_بالزر", "pass": bool(opened)})
    pg.screenshot(path=str(SHOTS / "R1F_M1_drawer_open.png"))
    # 2) اختيار سطح يغلق الدرج تلقائيًا
    pg.locator('.side-nav-item[data-nav="projects"]').first.click()
    time.sleep(1.0)
    closed_after_nav = not drawer_open_mobile(pg)
    steps.append({"step": "M2_إغلاق_بعد_الاختيار", "pass": bool(closed_after_nav)})
    pg.screenshot(path=str(SHOTS / "R1F_M2_drawer_closed_after_nav.png"))
    # 3) ☰ يفتح ثم النقر خارجيًا يغلق (الخلفية)
    pg.evaluate("() => window.ControlCenter.showView('chat');")
    time.sleep(0.8)
    pg.locator("#sidebar-toggle").first.click()
    time.sleep(0.6)
    pg.locator("#sidebar-backdrop").click(position={"x": 10, "y": 400})
    time.sleep(0.6)
    closed_outside = not drawer_open_mobile(pg)
    steps.append({"step": "M3_إغلاق_بالنقر_خارجي", "pass": bool(closed_outside)})
    # 4) ☰ يفتح ثم Escape يغلق
    pg.evaluate("() => window.ControlCenter.showView('chat');")
    time.sleep(0.8)
    pg.locator("#sidebar-toggle").first.click()
    time.sleep(0.6)
    pg.keyboard.press("Escape")
    time.sleep(0.6)
    closed_esc = not drawer_open_mobile(pg)
    steps.append({"step": "M4_إغلاق_بـEscape", "pass": bool(closed_esc)})
    flow_results.append({"viewport": "mobile390", "steps": steps,
                         "pass": all(s["pass"] for s in steps)})


def main():
    rows = []
    overflow_failures, drawer_failures, js_failures = [], [], []
    drawer_flow = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for vp_name, w, h in VIEWPORTS:
            pg = browser.new_page(viewport={"width": w, "height": h})
            errors_count = {"n": 0}
            pg.on("pageerror", lambda e: errors_count.__setitem__(
                "n", errors_count["n"] + 1))
            pg.on("console", lambda m: errors_count.__setitem__(
                "n", errors_count["n"] + 1) if m.type == "error" else None)
            pg.goto(BASE + "/", wait_until="load")
            pg.wait_for_selector("#cmd-strip .cmd-cell-value", timeout=20000)
            time.sleep(2.0)
            errors_count["n"] = 0  # أخطاء الإقلاع لا تُحسب على السطوح
            for surface in SURFACES:
                r = run_case(pg, vp_name, surface, errors_count)
                rows.append(r)
                if r["overflowX"]:
                    overflow_failures.append("%s/%s=%spx" % (r["vp"], r["surface"], r["overflowX"]))
                if r["drawerOpen"]:
                    drawer_failures.append("%s/%s" % (r["vp"], r["surface"]))
                if r["errors"]:
                    js_failures.append("%s/%s=%d" % (r["vp"], r["surface"], r["errors"]))
            for tab in SETTINGS_TABS:
                surface = "settings_" + tab
                pg.keyboard.press("Escape")  # إغلاق الإعدادات بين التبويبات
                time.sleep(0.4)
                if vp_name == "mobile390":
                    # زر الترس داخل الدرج المغلق على الهاتف — الحدث الموثق
                    # هو نقطة التكامل نفسها (app.js: hub:open-settings)
                    pg.evaluate(
                        "() => document.dispatchEvent(new Event('hub:open-settings'));")
                else:
                    pg.locator("#settings-open").click()
                time.sleep(0.5)
                pg.locator('.settings-tab[data-tab="%s"]' % tab).first.click()
                time.sleep(0.9)
                overflow, drawer_open = measure(pg, vp_name)
                r = {"vp": vp_name, "surface": surface,
                     "overflowX": (None if overflow == 0 else overflow),
                     "drawerOpen": bool(drawer_open),
                     "errors": errors_count["n"]}
                pg.screenshot(path=str(SHOTS / ("%s_%s.png" % (vp_name, surface))))
                rows.append(r)
                if r["overflowX"]:
                    overflow_failures.append("%s/%s=%spx" % (r["vp"], r["surface"], r["overflowX"]))
                if r["drawerOpen"]:
                    drawer_failures.append("%s/%s" % (r["vp"], r["surface"]))
                if r["errors"]:
                    js_failures.append("%s/%s=%d" % (r["vp"], r["surface"], r["errors"]))
            if vp_name == "mobile390":
                drawer_flow_case(pg, drawer_flow)
            pg.close()
        browser.close()

    audit = {
        "rows": rows,
        "summary": {
            "shots": len(rows),
            "overflow_failures": overflow_failures,
            "mobile_drawer_open_failures": drawer_failures,
            "js_error_failures": js_failures,
            "mobile_drawer_flow": drawer_flow,
        },
    }
    (EV / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    clean = len(rows) - len(overflow_failures) - len(drawer_failures) - len(js_failures)
    print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))
    print("%d/%d صف نظيف" % (clean, len(rows)))


if __name__ == "__main__":
    main()
