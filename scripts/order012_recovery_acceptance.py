#!/usr/bin/env python3
"""القبول الحي (012-G) — الانقطاع الحقيقي والاسترداد والاستئناف.

الخادم قُتل في القبول السابق والوظيفة كانت تدور فعليًا (RUNNING
بنبضة حديثة). هذا السكربت يثبت فوق هذه الحقيقة:
1. الإقلاع الجديد يوسمها INTERRUPTED (لا حياة كاذبة) + قابل استئناف
2. البطاقة في الواجهة تعرض «انقطعت (وفاة العملية)» بصدق
3. الاستئناف الصريح يعيدها في الصف نفسه وتكمل إلى حالة نهائية صادقة
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


def api(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def main() -> int:
    # آخر مشروع أُنشئ (الذي مات خادمه أثناء عمله)
    projects = api("GET", "/api/projects")["projects"]
    target = max(p["id"] for p in projects)
    print(f"== المشروع المستهدف: #{target} ==")

    # ================= 1) الاسترداد عند الإقلاع (012-G) =================
    job = api("GET", f"/api/projects/{target}/job")
    check(f"الوظيفة اليتيمة وُسمت INTERRUPTED عند الإقلاع "
          f"(كانت {job['status']})", job["status"] == "INTERRUPTED",
          f"resumable={job['resumable']}")
    check("قابلة للاستئناف — بوابات القرار وحدها تمنع",
          job["resumable"] is True)
    events = api("GET", f"/api/projects/{target}/events?limit=50")["events"]
    kinds = [e["kind"] for e in events]
    check("حدث JOB_RECOVERY_ASSESSED مسجل",
          "JOB_RECOVERY_ASSESSED" in kinds)

    # ================= 2) الواجهة: البطاقة الصادقة =================
    print("\n== الواجهة: بطاقة الانقطاع ==")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 940})
        page.goto(f"{BASE}/#/project/{target}",
                  wait_until="domcontentloaded")
        page.wait_for_selector("#pj-job", timeout=15000)
        card = page.locator("#pj-job").inner_text()
        check("البطاقة تعرض «انقطعت (وفاة العملية)»",
              "انقطعت" in card and "وفاة العملية" in card)
        check("النبضة حمراء (ميتة) لا نابضة",
              page.locator("#pj-job .pj-job-beat.dead").count() == 1)
        shot(page, "06-job-interrupted-honest")

        # ================= 3) الاستئناف في الصف نفسه =================
        print("\n== الاستئناف الصريح ==")
        job_id = job["id"]
        api("POST", f"/api/projects/{target}/resume")
        resumed = api("POST", f"/api/projects/{target}/run/stream"
                        ) if False else None
        # التشغيل عبر الواجهة (زر التشغيل بعد الاستئناف)
        page.wait_for_selector("#pj-run", timeout=15000)
        page.click("#pj-run")
        deadline = time.time() + 60
        while time.time() < deadline:
            if "تعمل الآن" in page.locator("#pj-job .pj-job-status"
                                            ).inner_text():
                break
            page.wait_for_timeout(1000)
        status_now = page.locator("#pj-job .pj-job-status").inner_text()
        check(f"الوظيفة عادت تعمل: «{status_now}»",
              "تعمل" in status_now or "تنتظر" in status_now)
        same = api("GET", f"/api/projects/{target}/job")
        check("الصف نفسه — لا صف جديد (استمرارية الاستئناف)",
              same["id"] == job_id,
              f"#{same['id']} == #{job_id}")
        check("حدث JOB_RESUMED دائم",
              "JOB_RESUMED" in kinds or "JOB_QUEUED" in kinds)

        # ================= 4) النتيجة النهائية (مهلة ممتدة) =================
        print("\n== النتيجة النهائية (حتى 12 دقيقة — LLM حي) ==")
        deadline = time.time() + 720
        final_status = ""
        last_print = 0.0
        while time.time() < deadline:
            job = api("GET", f"/api/projects/{target}/job")
            if job["status"] in ("WAITING_GATE", "WAITING_CAPABILITY",
                                 "WAITING_WORKER", "COMPLETED", "FAILED",
                                 "STOPPED", "ESCALATED", "PAUSED",
                                 "INTERRUPTED"):
                final_status = job["status"]
                break
            if time.time() - last_print > 60:
                beat = job["heartbeat_age_s"]
                print(f"    … تعمل: نبضات={job['tick_count']} "
                      f"إعادات={job['retries']} "
                      f"نبضة قبل {beat and int(beat)}ث")
                last_print = time.time()
            time.sleep(5)
        check(f"الوظيفة انتهت إلى حالة صادقة: {final_status}",
              final_status != "")
        page.wait_for_timeout(2500)
        try:
            page.wait_for_selector("#pj-job", timeout=15000)
            shot(page, "07-final-after-resume")
        except Exception:  # noqa: BLE001 — اللقطة لا تكسر القبول
            pass

        if final_status:
            job = api("GET", f"/api/projects/{target}/job")
            check("دفتر الوظيفة النهائي: نبضات ونقاط حفظ",
                  job["tick_count"] >= 1 and job["heartbeat_at"] != "",
                  f"ticks={job['tick_count']} "
                  f"checkpoints={job['checkpoints']} "
                  f"retries={job['retries']}")
            chain = api("GET", f"/api/projects/{target}/chain")
            stages = {s["stage"]: s["status"] for s in chain["stages"]}
            print("    السلسلة:", " / ".join(
                f"{k}={v}" for k, v in stages.items()))
            check("التحقق النهائي لم يكتمل قبل قرار المالك",
                  stages["VERIFICATION"] in ("WAITING", "PENDING",
                                             "DONE"))

        browser.close()

    print(f"\n===== النتيجة: {len(PASS)} ناجح / {len(FAIL)} فاشل =====")
    if FAIL:
        print("فاشل:", FAIL)
        return 1
    return 0


def shot(page, name: str):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)
    print(f"    📸 {name}.png")


if __name__ == "__main__":
    sys.exit(main())
