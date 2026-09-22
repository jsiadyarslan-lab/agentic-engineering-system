#!/usr/bin/env python3
"""القبول الحي بالمتصفح (الأمر 012) — الخادم الفعلي + Playwright.

يثبت بالمتصفح الحقيقي فوق خط 011 الحي:
1. بطاقة الوظيفة الدائمة (نبضة حية/انتظار صادق بنوعه وسببه ومساره)
2. سلسلة القبول (المراحل الثماني بحالاتها) + الخط الزمن المرحلي
3. التحديث اللحظي عبر تيار الأحداث بلا refresh يدوي
4. توقف صادق معلن (بوابة/توفير) — لا حالة غامضة
اللقطات إلى download/order012-screenshots/.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8012"
SHOTS = Path("/home/z/my-project/download/order012-screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, note: str = ""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {note}" if note else ""))
    (PASS if ok else FAIL).append(name)


def shot(page, name: str):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)
    print(f"    📸 {name}.png")


def api(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def main() -> int:
    # ================= 1) نقاط الـHarness عبر HTTP =================
    print("== 1) نقاط الـHarness ==")
    roles = api("GET", "/api/harness/roles")["roles"]
    check("خمسة أدوار بعقودها وربطها الحي", len(roles) == 5 and all(
        r["prompt_exists"] for r in roles))

    caps = api("GET", "/api/harness/capabilities")["capabilities"]
    by_id = {c["capability_id"]: c for c in caps}
    check("تصنيف الانتظار: sandbox=WORKER والباقي CAPABILITY",
          by_id["sandbox"]["blocked_kind"] == "WORKER"
          and by_id["llm"]["blocked_kind"] == "CAPABILITY")
    check("البحث سلسلة FAILOVER بثلاثة مزودين",
          by_id["web_search"]["resolution"] == "FAILOVER"
          and len(by_id["web_search"]["providers"]) == 3)

    vocab = api("GET", "/api/harness/events/vocabulary")
    check("المفردة القانونية مكتملة",
          vocab["canonical_map"]["PLAN_APPROVED"] == "plan/approved"
          and "JOB_WAITING" in vocab["job_event_kinds"])

    # ================= 2) مشروع جديد + خطة حية + اعتماد =================
    print("\n== 2) مشروع حي: إنشاء ← خطة حية ← اعتماد ==")
    project = api("POST", "/api/projects", {
        "name": "وظيفة 012 الحية",
        "objective": "اكتب تقريرًا موجزًا عن فوائد الاختبارات الآلية "
                     "في المشاريع الهندسية بملف markdown",
    })
    pid = project["id"]
    plan = api("POST", f"/api/projects/{pid}/plan/generate")
    check(f"خطة حية v{plan['version']} تولدت", plan["version"] == 1,
          f"{len(plan['phases'])} مراحل")
    api("POST", f"/api/projects/{pid}/plan/approve",
        {"approved": True})
    detail = api("GET", f"/api/projects/{pid}")
    check("الاعتماد ← READY (لا وظيفة بعد)",
          detail["status"] == "READY" and detail["job"] is None)

    # ================= 3) المتصفح: التشغيل والبطاقة الحية =================
    print("\n== 3) المتصفح: بطاقة الوظيفة + السلسلة + الخط الزمني ==")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 940})
        page.goto(f"{BASE}/#/project/{pid}", wait_until="domcontentloaded")
        page.wait_for_selector(".pj-head", timeout=15000)
        shot(page, "01-project-ready")

        # لا وظيفة بعد — لا بطاقة وهمية
        check("لا بطاقة وظيفة قبل التشغيل",
              page.locator("#pj-job").count() == 0)

        # التشغيل من زر الواجهة — SSE حي
        page.click("#pj-run")
        # البطاقة تظهر خلال ثوانٍ (JOB_QUEUED/STARTED عبر التيار العام)
        deadline = time.time() + 60
        appeared = False
        while time.time() < deadline:
            if page.locator("#pj-job").count():
                appeared = True
                break
            page.wait_for_timeout(800)
        check("بطاقة الوظيفة ظهرت بلا refresh يدوي", appeared,
              "عبر تيار الأحداث العام (REFRESH_KINDS)")
        if appeared:
            page.wait_for_selector("#pj-job .pj-job-status", timeout=10000)
            # انتظر حالة غير الطابور (تعمل/تنتظر)
            deadline = time.time() + 90
            while time.time() < deadline:
                status = page.locator("#pj-job .pj-job-status"
                                      ).inner_text().strip()
                if status not in ("في الطابور",):
                    break
                page.wait_for_timeout(1000)
            shot(page, "02-job-card-live")
            status_text = page.locator("#pj-job .pj-job-status"
                                       ).inner_text().strip()
            beat = page.locator("#pj-job .pj-job-beat").inner_text()
            check(f"حالة الوظيفة الحية: «{status_text}»",
                  status_text in ("تعمل الآن", "تنتظر قدرة",
                                  "تنتظر بيئة تنفيذ", "تنتظر قرارك",
                                  "تعيد المحاولة", "اكتملت — VERIFIED"))
            check(f"النبضة ظاهرة: {beat[:30]}",
                  "نبضت" in beat or "لم تنبض" in beat)

        # السلسلة والخط الزمني (إسقاطات)
        page.wait_for_selector(".pj-chain", timeout=20000)
        chain_text = page.locator(".pj-chain").inner_text()
        check("سلسلة القبول: الهدف والاعتماد منجزان",
              "الهدف" in chain_text and "الاعتماد" in chain_text)
        shot(page, "03-chain")

        page.wait_for_selector(".pj-timeline", timeout=20000)
        items = page.locator(".pj-tl-item").count()
        check(f"الخط الزمني المرحلي: {items} بندًا", items >= 5)
        tl_text = page.locator(".pj-timeline").inner_text()
        check("الخط الزمني يعرض الفاعلين (المالك/المنسق)",
              "المالك" in tl_text or "المنسق" in tl_text)
        shot(page, "04-timeline")

        # ================= 4) النتيجة النهائية الصادقة =================
        print("\n== 4) النتيجة النهائية (توقف صادق أو مرشح) ==")
        # انتظر انتهاء البث (الزر يعود) أو حالة انتظار مستقرة
        deadline = time.time() + 420
        final_status = ""
        while time.time() < deadline:
            job = api("GET", f"/api/projects/{pid}/job")
            if job["status"] in ("WAITING_GATE", "WAITING_CAPABILITY",
                                 "WAITING_WORKER", "COMPLETED", "FAILED",
                                 "STOPPED", "ESCALATED", "PAUSED"):
                final_status = job["status"]
                break
            time.sleep(4)
        check(f"الوظيفة انتهت إلى حالة صادقة: {final_status}",
              final_status != "")

        # الصفحة تزامنت لحظيًا (بلا refresh) — أعد التحقق من DOM
        if final_status:
            page.wait_for_timeout(2500)
            card = page.locator("#pj-job").inner_text()
            shot(page, "05-final-honest-state")
            if final_status.startswith("WAITING"):
                check("البطاقة تعرض سبب الانتظار ومسار رفعه",
                      "تنتظر" in card and ("↻" in card or "الإجراء" in card),
                      final_status)
            job = api("GET", f"/api/projects/{pid}/job")
            check("دفتر الوظيفة: نبضات ونقاط حفظ",
                  job["tick_count"] >= 1 and job["heartbeat_at"] != "",
                  f"ticks={job['tick_count']} "
                  f"checkpoints={job['checkpoints']}")

        chain = api("GET", f"/api/projects/{pid}/chain")
        stages = {s["stage"]: s["status"] for s in chain["stages"]}
        print("    السلسلة:", " / ".join(
            f"{k}={v}" for k, v in stages.items()))
        check("السلسلة متسقة مع الحالة النهائية",
              stages["OBJECTIVE"] == "DONE"
              and stages["APPROVAL"] == "DONE")

        timeline = api("GET", f"/api/projects/{pid}/timeline")
        canons = {i["canonical"] for i in timeline["items"]}
        check("الخط الزمني يحمل الأحداث القانونية",
              {"project/created", "plan/approved"} <= canons)

        # ================= 5) أحداث الوظيفة في السجل =================
        events = api("GET", f"/api/projects/{pid}/events?limit=200")
        kinds = {e["kind"] for e in events["events"]}
        check("أحداث JOB_* دائمة في السجل",
              {"JOB_QUEUED", "JOB_STARTED"} <= kinds)
        jobs_list = api("GET", "/api/harness/jobs")["jobs"]
        check("قائمة الوظائف تعرض وظيفة المشروع",
              any(j["project_id"] == pid for j in jobs_list))

        browser.close()

    print(f"\n===== النتيجة: {len(PASS)} ناجح / {len(FAIL)} فاشل =====")
    if FAIL:
        print("فاشل:", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
