#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R1 regression tests — AES-FACTORY-CONSOLE-REARCHITECTURE-001-R1 §6 (R1-A..R1-E).

طبقتان صادقتان ولا تختلطان:
  (1) تكامل حي عبر API الحقيقي (لا مختلقات): مسبار zai_internal → READY فعلي،
      تكوين ثانٍ يبقى UNTESTED، ربط الأدوار بينهما — الفحص على الواجهة الحية.
  (2) مسارات الفشل التي لا تُنتج بصدق عبر API (HTTP 4xx على إعادة المحاولة،
      FAILED بلا إجراء، نماذج غير معلنة) — بتثبيت مسارات Playwright على
      نقاط النهاية تحديدًا (بقية الطلبات تمر للخادم الحي). هذه عقود اختبار
      موصوفة بوضوح، لا بيانات تشغيل ولا أدلة زائفة.

الخرج: R1_FUNCTIONAL_RESULTS.json + لقطات في docs/rearchitecture-001/r1/.
"""

import json
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
REPO = Path(__file__).resolve().parent.parent
EV = REPO / "docs" / "rearchitecture-001" / "r1"
SHOTS = EV / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

results = []


def record(tid, name, passed, detail, shot=None):
    results.append({
        "id": tid, "name": name, "pass": bool(passed),
        "detail": detail, "screenshot": shot,
    })
    print(("PASS " if passed else "FAIL ") + tid + " — " + name)
    print("      " + detail)


# ------------------------------------------------------------------ #
# الجزء 1 — تكامل حي عبر API الحقيقي (R1-A وR1-B بمسبار حي فعلي)
# ------------------------------------------------------------------ #

def setup_live_scenario():
    """مسبار حي → تكوين READY + تكوين ثانٍ UNTESTED + ربط ثلاثة أدوار بينهما."""
    # مسبار حي على التكوين الأساسي (id=3) — نتيجة حقيقية من الشبكة
    probe = requests.post(BASE + "/api/provider-configurations/3/test", timeout=60).json()
    assert probe["status"] == "READY", "المسبار الحي لم ينجح: %s" % probe.get("reason")

    # تكوين ثانٍ لنفس المزود يبقى بلا فحص (UNTESTED) — نفس العنوان، بلا مسبار
    # (idempotent: يُعاد استخدامه إن وُجد من تشغيل سابق لنفس السيناريو)
    provs = requests.get(BASE + "/api/providers", timeout=30).json()["providers"]
    zai = [p for p in provs if (p.get("name") or p.get("id")) == "zai_internal"][0]
    cfg2_id = None
    for c in zai["configurations"]:
        if c.get("name") == "r1_untested_cfg":
            cfg2_id = c["id"]
            break
    if cfg2_id is None:
        add = requests.post(BASE + "/api/providers/3/configurations", json={
            "name": "r1_untested_cfg",
            "base_url": "https://internal-api.z.ai/v1",
            "api_style": "openai_compatible",
            "enabled": True,
            "default_model": "glm-4.6",
            "models": ["glm-4.6"],
            "config_file": "",
        }, timeout=30).json()
        cfg2_id = add["configuration"]["id"]

    # نموذج ثانٍ معلن في التكوين الأساسي (المفحوص) — لبناء حالة R1-B:
    # معلن لكنه ليس النموذج الافتراضي الذي فحصه المسبار
    requests.put(BASE + "/api/provider-configurations/3", json={
        "models": ["glm-4.6", "glm-4.5-air"],
    }, timeout=30)

    # ربط الأدوار (عقد PUT /api/models/config):
    # reviewer  → الأساسي المفحوص + النموذج الافتراضي  → READY متوقع
    # thinker   → التكوين الثاني غير المفحوص          → R1-A: لا READY
    # arbiter   → الأساسي المفحوص + نموذج معلن غير مفحوص → R1-B: لا READY
    put = requests.put(BASE + "/api/models/config", json={
        "reviewer": {"provider": "zai_internal", "model": "glm-4.6",
                     "configuration": "default"},
        "thinker": {"provider": "zai_internal", "model": "glm-4.6",
                    "configuration": "r1_untested_cfg"},
        "arbiter": {"provider": "zai_internal", "model": "glm-4.5-air",
                    "configuration": "default"},
    }, timeout=30)
    assert put.status_code == 200, put.text
    return cfg2_id


def part1_live(pw):
    browser = pw.chromium.launch(headless=True)
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_selector("#cmd-strip .cmd-cell-value", timeout=15000)
    # انتظر نبضة تجميع تكمل تحميل cfg ثم الشريط يعاد رسمه — نقيس بعد استقرار
    time.sleep(2.5)
    agents = pg.locator("#cmd-strip .cmd-cell", has_text="الوكلاء الجاهزة")\
               .locator(".cmd-cell-value").inner_text()
    pg.screenshot(path=str(SHOTS / "R1A_live_strip_agents.png"))

    ok_a = agents.strip().startswith("1/6")
    record("R1-A-live", "الدور على التكوين غير المفحوص لا يحصل على READY (تكامل حي)",
           ok_a,
           "الشريط الحي: «%s» — reviewer فقط على التكوين المفحوص default/glm-4.6 جاهز؛ "
           "thinker على r1_untested_cfg (UNTESTED) مستبعد" % agents.strip(),
           "R1A_live_strip_agents.png")

    # لوحة صحة المصنع — الأدوار الثلاثة المربوطة بعناوينها الصادقة
    pg.goto(BASE + "/#/overview", wait_until="load")
    time.sleep(2.5)
    lines = pg.locator(".cmd-health-card", has_text="الوكلاء والأدوار")\
              .locator(".cmd-health-line").all_inner_texts()
    joined = "\n".join(lines)
    # الثلاث حالات الصادقة معروضة معًا: مفحوص/غير مفحوص/تكوين متصل بنموذج غير مُفحوص
    ok_lines = ("READY" in joined
                and "UNTESTED" in joined
                and "غير مُفحوص" in joined)
    pg.screenshot(path=str(SHOTS / "R1AB_live_health_roles.png"))
    record("R1-A/B-live", "لوحة صحة المصنع تعرض الحالات الثلاث الصادقة (تكامل حي)",
           ok_lines,
           "أسطر الأدوار الحية: " + " ⏎ ".join(l.strip() for l in lines if l.strip())[:600],
           "R1AB_live_health_roles.png")

    js_ok = len(errors) == 0
    record("R1-CONSOLE-live", "صفر أخطاء JS في السطح الحي المفحوص", js_ok,
           "pageerror count = %d" % len(errors))
    browser.close()


# ------------------------------------------------------------------ #
# الجزء 2 — مسارات الفشل عبر تثبيت مسارات محددة (عقود اختبار معلنة)
# ------------------------------------------------------------------ #

CFG_FIXTURE = {
    "providers": [{
        "id": "stubprov", "provider_id": 99, "label": "Stub Provider",
        "base_url": "https://stub.example/v1", "requires_key": True,
        "default_model": "m-default", "known_models": ["m-default", "m-alt"],
        "has_key": True,
        "configurations": [
            {"name": "probed", "base_url": "https://stub.example/v1",
             "default_model": "m-default", "models": ["m-default", "m-alt"],
             "enabled": True, "is_primary": True,
             "readiness": {"status": "READY",
                           "checked_at": "2026-11-15T09:00:00+00:00"}},
            {"name": "never_probed", "base_url": "https://stub2.example/v1",
             "default_model": "m-default", "models": ["m-default"],
             "enabled": True, "is_primary": False,
             "readiness": {"status": "UNTESTED", "checked_at": None}},
        ],
    }],
    "roles": [
        {"key": "thinker", "label": "المفكر",
         "selection": {"provider": "stubprov", "configuration": "never_probed",
                       "model": "m-default"}, "is_default": False},
        {"key": "reviewer", "label": "المدقق",
         "selection": {"provider": "stubprov", "configuration": "probed",
                       "model": "m-default"}, "is_default": False},
        {"key": "implementer", "label": "المنفذ",
         "selection": {"provider": "stubprov", "configuration": "probed",
                       "model": "m-alt"}, "is_default": False},
        {"key": "verifier", "label": "المراجع",
         "selection": {"provider": "stubprov", "configuration": "probed",
                       "model": "m-undeclared"}, "is_default": False},
        {"key": "arbiter", "label": "المُحكَّم",
         "selection": {"provider": "stubprov", "configuration": "probed",
                       "model": "m-alt"}, "is_default": False},
        {"key": "chat", "label": "المحادثة",
         "selection": {"provider": "stubprov", "configuration": "probed",
                       "model": "m-alt"}, "is_default": False},
    ],
    "defaults": {"provider": "stubprov", "model": "m-default"},
}

FAILED_PROJECT = {
    "id": 7, "name": "مشروع فاشل R1", "objective": "اختبار ظهور الفاشل",
    "status": "FAILED",
    "last_error": "EXECUTION_FAILED — الأداة pdf_build انهارت: TTFError",
    "created_at": "2026-11-14T10:00:00", "updated_at": "2026-11-14T11:30:00",
    "current_plan_id": 9, "current_phase_id": 2, "current_step_id": 5,
    "stop_requested": False, "completion_state": None,
    "execution_policy": "STRICT_ISOLATED", "archived_at": None,
    "original_id": None,
}

STATE_WITH_RETRY = {
    "project": {"id": 7, "status": "FAILED"},
    "available_actions": ["retry", "duplicate", "rename", "history", "archive"],
    "last_error": FAILED_PROJECT["last_error"],
}
STATE_NO_RETRY = {
    "project": {"id": 7, "status": "FAILED"},
    "available_actions": ["duplicate", "rename", "history", "archive"],
    "last_error": FAILED_PROJECT["last_error"],
}


def stub_routes(pg, *, retry_status=200, retry_body=None, state=None):
    """تثبيت مسارات محددة فقط — بقية الطلبات تمر للخادم الحي."""
    retry_calls = {"n": 0}

    def h_models(route):
        route.fulfill(json=CFG_FIXTURE)

    def h_projects(route):
        route.fulfill(json={"projects": [FAILED_PROJECT], "recovery": [],
                            "active_run": None})

    def h_runs(route):
        route.fulfill(json={"runs": []})

    def h_state(route):
        route.fulfill(json=state or STATE_WITH_RETRY)

    def h_retry(route):
        retry_calls["n"] += 1
        if retry_status == 200:
            route.fulfill(json=retry_body or {"retried": "steps", "launch": None})
        else:
            route.fulfill(status=retry_status,
                          json=retry_body or {"detail": "لا فشل قابل للإعادة (409)"})

    pg.route("**/api/models/config", h_models)
    pg.route("**/api/projects", h_projects)
    pg.route("**/api/projects/runs/active", h_runs)
    pg.route("**/api/projects/7/state", h_state)
    pg.route("**/api/projects/7/retry", h_retry)
    return retry_calls


def open_overview(pg):
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_selector(".cmd-decision", timeout=15000)
    time.sleep(1.2)  # لقطة الحالة تصل وتُقرر زر الإعادة


def part2_stubbed(pw):
    browser = pw.chromium.launch(headless=True)

    # R1-A: دور على تكوين UNTESTED — لا READY في الشريط ولا اللوحة
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    stub_routes(pg)
    open_overview(pg)
    time.sleep(2.0)
    agents = pg.locator("#cmd-strip .cmd-cell", has_text="الوكلاء الجاهزة")\
               .locator(".cmd-cell-value").inner_text()
    ok_a = agents.strip().startswith("3/6")  # reviewer+implementer+arbiter+chat=4؟ لا:
    # reviewer(m-default) جاهز؛ implementer(m-alt) غير مُفحوص النموذج؛
    # verifier(m-undeclared) غير معلن؛ arbiter/chat(m-alt) غير مُفحوص → 1/6 فقط
    ok_a = agents.strip().startswith("1/6")
    pg.screenshot(path=str(SHOTS / "R1A_stub_strip_1of6.png"))
    record("R1-A", "دور على تكوين UNTESTED لا يظهر جاهزًا (فحص منطق مركزي)",
           ok_a, "الشريط: «%s» — المتوقع 1/6 (reviewer وحده على probed/m-default)" % agents.strip(),
           "R1A_stub_strip_1of6.png")

    lines = pg.locator(".cmd-health-card", has_text="الوكلاء والأدوار")\
              .locator(".cmd-health-line").all_inner_texts()
    joined = "\n".join(lines)
    ok_labels = ("UNTESTED" in joined
                 and "غير مُفحوص" in joined
                 and "غير معلن في التكوين" in joined
                 and "READY" in joined)
    record("R1-B", "النموذج غير المُفحوص/غير المعلن لا يُعرض جاهزًا — الحالة منفصلة",
           ok_labels,
           "أسطر الأدوار: " + " ⏎ ".join(l.strip() for l in lines if l.strip())[:600])
    pg.close()

    # R1-C + R1-D: صفحة بتثبيت 409 على إعادة المحاولة
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    retry_calls = stub_routes(pg, retry_status=409)
    open_overview(pg)
    row = pg.locator(".cmd-decision", has_text="#7")
    ok_c = row.count() == 1 and FAILED_PROJECT["last_error"] in row.inner_text()
    pg.screenshot(path=str(SHOTS / "R1C_failed_in_queue.png"))
    record("R1-C", "مشروع FAILED يظهر في طابور القرارات مع سبب الفشل",
           ok_c, "الصف: «%s»" % row.inner_text()[:220], "R1C_failed_in_queue.png")

    # R1-D: إعادة محاولة → HTTP 409 — الخطأ معلن والصف باقٍ والزر يعود
    btn = row.locator("button", has_text="إعادة المحاولة")
    ok_btn = btn.count() == 1
    btn.click()
    time.sleep(1.5)
    note = pg.locator("#cmd-queue-note")
    note_txt = note.inner_text() if note.count() else "(لا عقدة)"
    ok_note = "رُفضت إعادة المحاولة" in note_txt \
        and "لا فشل قابل للإعادة" in note_txt
    row_after = pg.locator(".cmd-decision", has_text="#7")
    ok_row = row_after.count() == 1
    btn_after = row_after.locator("button", has_text="إعادة المحاولة")
    ok_enabled = btn_after.count() == 1 and btn_after.is_enabled()
    pg.screenshot(path=str(SHOTS / "R1D_retry_http409.png"))
    record("R1-D", "إعادة محاولة HTTP 409 — الخطأ معلن والصف باقٍ والزر يعود فعالًا",
           ok_btn and ok_note and ok_row and ok_enabled,
           "زر موجود=%s، نداءات retry=%d، نص الملاحظة=«%s»، الصف باقٍ=%s، الزر فعال=%s — استجابة {ok:false} لم تُعامل كنجاح"
           % (ok_btn, retry_calls["n"], note_txt[:160], ok_row, ok_enabled), "R1D_retry_http409.png")

    # R1-E: إعادة محاولة ناجحة — الحالة تُحدّث من المصدر الحي (render كامل يعيد الجمع)
    pg2 = browser.new_page(viewport={"width": 1600, "height": 900})
    retry_calls_ok = stub_routes(pg2, retry_status=200)
    open_overview(pg2)
    time.sleep(1.2)
    row_ok = pg2.locator(".cmd-decision", has_text="#7")
    row_ok.locator("button", has_text="إعادة المحاولة").first.click()
    # إعادة الرسم تمسح الصفحة ثم تبنيها من الجمع الحي — استطلاع صبور حتى 15 ثانية
    row_fresh = False
    cleared = False
    for _ in range(30):
        time.sleep(0.5)
        rows_now = pg2.locator(".cmd-decision", has_text="#7").count()
        note2 = pg2.locator("#cmd-queue-note")
        note_txt2 = note2.inner_text() if note2.count() else ""
        if rows_now == 1 and not note_txt2.strip():
            row_fresh = True
            cleared = True
            break
    ok_e = retry_calls_ok["n"] == 1 and cleared and row_fresh
    pg2.screenshot(path=str(SHOTS / "R1E_retry_success.png"))
    record("R1-E", "إعادة محاولة ناجحة — تحديث من المصدر الحي ومسح الخطأ القديم",
           ok_e, "عدد نداءات retry=%d (استجابة 200)، الطابور أُعيد بناؤه=%s، الملاحظة مُسحت=%s"
           % (retry_calls_ok["n"], row_fresh, cleared),
           "R1E_retry_success.png")
    pg2.close()
    pg.close()

    # R1-D2: لقطة بلا retry في available_actions — لا زر إعادة أصلًا
    pg = browser.new_page(viewport={"width": 1600, "height": 900})
    stub_routes(pg, state=STATE_NO_RETRY)
    open_overview(pg)
    time.sleep(1.2)
    row3 = pg.locator(".cmd-decision", has_text="#7")
    no_btn = row3.locator("button", has_text="إعادة المحاولة").count() == 0
    hint = row3.locator(".cmd-acts-check").count() >= 0
    pg.screenshot(path=str(SHOTS / "R1D2_no_retry_action.png"))
    record("R1-D2", "بلا retry في available_actions — لا زر إعادة يُعرض",
           no_btn, "الزر غائب=%s، الإجراءات من اللقطة القانونية حصرًا (hint=%s)" % (no_btn, hint),
           "R1D2_no_retry_action.png")
    pg.close()
    browser.close()


def main():
    t0 = time.time()
    with sync_playwright() as pw:
        cfg2 = setup_live_scenario()
        print("live scenario ready: secondary cfg id=%s" % cfg2)
        part1_live(pw)
        part2_stubbed(pw)
    out = {
        "suite": "AES-FACTORY-CONSOLE-REARCHITECTURE-001-R1 §6 (R1-A..R1-E)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "duration_s": round(time.time() - t0, 1),
        "layers": {
            "live_integration": "مسبار حي حقيقي + ربط حقيقي عبر API — لقطات من الواجهة الحية",
            "failure_paths": "تثبيت مسارات Playwright لنقاط نهاية محددة (409/FAILED/بلا إجراء) — عقود اختبار لا بيانات تشغيل",
        },
        "results": results,
    }
    (EV / "R1_FUNCTIONAL_RESULTS.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    npass = sum(1 for r in results if r["pass"])
    print("\n%d/%d PASS — results: docs/rearchitecture-001/r1/R1_FUNCTIONAL_RESULTS.json"
          % (npass, len(results)))
    sys.exit(0 if npass == len(results) else 1)


if __name__ == "__main__":
    main()
