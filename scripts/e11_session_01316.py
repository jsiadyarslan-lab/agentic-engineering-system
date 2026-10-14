# -*- coding: utf-8 -*-
"""الجلسة الحية المنسقة لأمر 013.16 — E11 أول مهمة حقيقية عبر المصنع كاملًا.

تُشغَّل بأمر واحد (قيود البيئة: العمليات الخلفية تُقتل بين الاستدعاءات،
والاستدعاءات تسلسلية) — لذلك يستضيف هذا السكربت الجلسة كاملة:

  1. عامل التنفيذ المعزول (وضع substrate) بتوكن وقت-تشغيل.
  2. مسبارات العامل المباشرة: health/capabilities/probe/probe_isolation.
  3. خادم الواجهة (uvicorn README الحرفي) على 8010.
  4. تسجيل البيئة عبر مسار المنتج + التحقق (8/8) + الافتراضية + تشغيل تجريبي.
  5. ربط كل الأدوار بمزود zai_internal/glm-4.6 عبر مسار المنتج + مسبار جاهزية حي.
  6. المتصفح (Chromium حي): إنشاء المهمة من واجهة Control Room — الهدف
     في حقل الإدخال الرئيسي ثم زر «المهمة الحية المتخصصة» (متقدم).
  7. مراقبة الدورة (أحداث حية) بلقطات شاشة عند كل مرحلة.
  8. موافقة المالك عبر القناة المعلنة (POST /api/mission/verify).
  9. جمع الأدلة: حالة المهمة، evidence.json، ملفات مجلد المهمة ببصمات
     sha256، سجل العامل (إثبات مرور التنفيذ به)، سجل الخادم، أحداث القاعدة.

لا يطبع أي سر: التوكن وقت-تشغيل يُقرأ من ملف بصلاحيات 600 ولا يظهر
في أي مخرج أو دليل (بصمته فقط).
"""
from __future__ import annotations

import hashlib
import uuid
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

WORK = Path("/home/z/my-project/order01316_work")
VENV_PY = str(WORK / ".venv" / "bin" / "python")
EVID = WORK / "docs" / "evidence" / "order01316"
TOKEN_FILE = Path("/home/z/my-project/.order01316_worker_token")
SERVER = "http://127.0.0.1:8010"
WORKER = "http://127.0.0.1:8900"

MISSION_GOAL = (
    "مهمة برمجية: اكتب أداة Python باسم tool.py تستخدم المكتبات القياسية "
    "فقط (stdlib)، تقرأ ملف transactions.csv وتنتج report.md بالإجماليات. "
    "بيانات الإدخال ستة سجلات بإجمالي كلي 85.00: food بإجمالي 25.00 "
    "وtravel بإجمالي 40.00 وtools بإجمالي 20.00. اكتب أيضًا ملف اختبارات "
    "test_tool.py يغطي ثلاث حالات: الإدخال الصحيح، وملف CSV فارغ (ترفضه "
    "الأداة برمز خروج غير صفري)، ومبلغ غير صالح (ترفضه الأداة برمز خروج "
    "غير صفري). نفّذ الأداة والاختبارات فعليًا داخل الركيزة المعزولة "
    "وتحقق أن report.md ناتج فعلي من تنفيذ الأداة."
)

_state = {"mission_screenshots": 0, "shot_states": set()}
processes: list[subprocess.Popen] = []


def log(msg: str) -> None:
    print(f"[session {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def http(method: str, url: str, body: dict | None = None,
         timeout: float = 30.0, headers: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode() or "{}")
        except ValueError:
            return error.code, {"raw": str(error)}
    except (urllib.error.URLError, TimeoutError) as error:
        return 0, {"error": str(error)}


def save(name: str, payload) -> None:
    target = EVID / name
    if isinstance(payload, (dict, list)):
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    else:
        target.write_text(str(payload), encoding="utf-8")
    log(f"saved {name}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start_processes() -> None:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    worker_log = open(WORK / "runtime/logs/worker_e11.log", "w")
    server_log = open(WORK / "runtime/logs/server_e11.log", "w")
    processes.append(subprocess.Popen(
        [VENV_PY, "scripts/execution_worker.py", "--port", "8900",
         "--host", "127.0.0.1", "--token", token],
        cwd=WORK, stdout=worker_log, stderr=subprocess.STDOUT,
    ))
    log("worker launched (substrate mode, runtime token)")
    for _ in range(40):
        code, out = http("GET", WORKER + "/health", timeout=3,
                         headers={"Authorization": f"Bearer {token}"})
        if code == 200 and out.get("backend_mode") == "substrate":
            break
        time.sleep(0.5)
    else:
        raise SystemExit("FATAL: worker did not become healthy in substrate mode")
    log("worker healthy: backend_mode=substrate")

    processes.append(subprocess.Popen(
        [VENV_PY, "-m", "uvicorn", "api.routes:app", "--port", "8010",
         "--host", "127.0.0.1"],
        cwd=WORK, stdout=server_log, stderr=subprocess.STDOUT,
    ))
    log("server launching (uvicorn, README literal)")
    for _ in range(60):
        code, _ = http("GET", SERVER + "/health", timeout=3)
        if code == 200:
            break
        time.sleep(0.5)
    else:
        raise SystemExit("FATAL: server did not become healthy")
    log("server healthy on 8010")


def probe_worker_directly() -> None:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    auth = {"Authorization": f"Bearer {token}"}
    _, health = http("GET", WORKER + "/health", headers=auth)
    _, caps = http("GET", WORKER + "/capabilities", headers=auth)
    _, probe = http("POST", WORKER + "/probe", body={}, headers=auth,
                    timeout=60)
    # (013.12 D2) تحدٍّ جديد لكل استدعاء — النتيجة تكرر التحدي حرفيًا
    challenge = f"order01316-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    _, iso = http("POST", WORKER + "/probe_isolation",
                  body={"challenge_id": challenge},
                  headers=auth, timeout=90)
    save("worker_live_health.json", health)
    save("worker_live_capabilities.json", caps)
    save("worker_live_probe.json", probe)
    save("worker_live_isolation_probe.json", iso)
    log(f"worker probes: probe.ok={probe.get('ok')} "
        f"isolation.verdict={iso.get('verdict')} "
        f"challenge_repeated={iso.get('challenge_id') == challenge} "
        f"sandboxed={caps.get('sandboxed')}")
    if not (probe.get("ok") and iso.get("verdict") == "BLOCKED"
            and iso.get("challenge_id") == challenge):
        raise SystemExit(
            "FATAL: worker probes failed — isolation not proven live"
        )


def setup_via_product_api() -> dict:
    # 1) تسجيل بيئة REMOTE_WORKER عبر مسار المنتج (الإعدادات ← بيئات التنفيذ)
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    code, created = http("POST", SERVER + "/api/execution/environments", body={
        "name": "order01316-worker-linux",
        "backend": "REMOTE_WORKER",
        "endpoint": WORKER,
        "token": token,
        "make_default": True,
    })
    if code not in (200, 201):
        raise SystemExit(f"FATAL: env registration failed: {created}")
    env_id = created.get("id") or created.get("environment_id")
    log(f"environment registered via product API: id={env_id} "
        f"(default={created.get('is_default')})")

    # 2) التحقق (فحوص حقيقية مسماة — 8/8)
    code, verified = http(
        "POST", f"{SERVER}/api/execution/environments/{env_id}/verify",
        body={}, timeout=120,
    )
    save("environment_verify_8_8.json", verified)
    verify_block = verified.get("verify") or {}
    checks = verify_block.get("checks") or []
    ok_count = sum(1 for c in checks if c.get("ok"))
    log(f"environment verify: ok={verify_block.get('ok')} "
        f"status={verified.get('status')} checks={ok_count}/{len(checks)}")
    if not verify_block.get("ok") or ok_count < 8:
        raise SystemExit(f"FATAL: environment verify not 8/8: {verified}")

    # 3) تشغيل تجريبي عبر البيئة المسجلة
    code, test_run = http(
        "POST", f"{SERVER}/api/execution/environments/{env_id}/test-run",
        body={}, timeout=120,
    )
    save("environment_test_run.json", test_run)
    log(f"environment test-run: {json.dumps(test_run, ensure_ascii=False)[:180]}")

    # 4) ربط الأدوار بمزود zai_internal عبر مسار المنتج
    selection = {"provider": "zai_internal", "model": "glm-4.6"}
    code, mapped = http("PUT", SERVER + "/api/models/config", body={
        "thinker": selection, "reviewer": selection,
        "implementer": selection, "verifier": selection,
        "arbiter": selection, "chat": selection,
    })
    save("role_mappings_zai_internal.json", mapped)
    if not mapped.get("success"):
        raise SystemExit(f"FATAL: role mapping failed: {mapped}")
    log("all roles mapped to zai_internal/glm-4.6 via product API")

    # 5) مسبار جاهزية حي لتكوين المزود (نداء نموذج حقيقي)
    code, providers = http("GET", SERVER + "/api/providers")
    zai = next((p for p in providers.get("providers", [])
                if p.get("name") == "zai_internal"), None)
    if zai is None:
        raise SystemExit("FATAL: zai_internal not in provider registry")
    _, configs = http(
        "GET", f"{SERVER}/api/providers/{zai['id']}/configurations"
    )
    cfg_list = configs.get("configurations") or []
    cfg_id = cfg_list[0]["id"] if cfg_list else None
    code, probe = http(
        "POST",
        f"{SERVER}/api/provider-configurations/{cfg_id}/test",
        body={}, timeout=180,
    )
    save("provider_live_probe.json", probe)
    log(f"provider live probe: http={code} status={probe.get('status')} "
        f"model={probe.get('model', '')}")
    return {"env_id": env_id, "provider_id": zai["id"], "config_id": cfg_id}


def run_browser_mission() -> dict:
    result: dict = {"mission_created_from": "browser Control Room UI"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(SERVER, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#input", state="visible", timeout=20000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(EVID / "ui_00_landing.png"))
        log("browser: landing captured")

        # بطاقة بيئة التنفيذ المتحقق منها (الإعدادات ← بيئات التنفيذ)
        page.click("#settings-open")
        page.wait_for_selector("#settings-drawer:not([hidden])")
        page.click('#settings-tabs button[data-tab="execution"]')
        page.wait_for_timeout(1500)
        page.screenshot(path=str(EVID / "ui_01_env_verified.png"))
        # ربط الأدوار (الإعدادات ← النماذج)
        page.click('#settings-tabs button[data-tab="models"]')
        page.wait_for_timeout(1500)
        page.screenshot(path=str(EVID / "ui_02_models_zai.png"))
        # إنشاء المهمة: الهدف في حقل الإدخال الرئيسي ثم زر المهمة
        page.click("#settings-close")
        page.wait_for_timeout(500)
        page.fill("#input", MISSION_GOAL)
        page.click("#settings-open")
        page.wait_for_selector("#settings-drawer:not([hidden])")
        page.click('#settings-tabs button[data-tab="advanced"]')
        page.wait_for_timeout(800)
        page.screenshot(path=str(EVID / "ui_03_advanced_ready.png"))
        page.click("#mission-run")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(EVID / "ui_04_mission_started.png"))
        log("browser: mission launched from Control Room UI")

        # مراقبة الدورة — لقطات عند كل حالة جديدة
        deadline = time.monotonic() + 420
        last_state = None
        status_payload = {}
        shot_idx = 5
        while time.monotonic() < deadline:
            code, status_payload = http("GET", SERVER + "/api/mission/status")
            state = status_payload.get("state") or ""
            running = status_payload.get("running", False)
            if state and state != last_state:
                page.screenshot(path=str(
                    EVID / f"ui_{shot_idx:02d}_state_{state}.png"))
                log(f"mission state → {state} (running={running})")
                last_state = state
                shot_idx += 1
            if not running and state in ("EVIDENCED", "FAILED", "STOPPED",
                                         "ESCALATED_TO_HUMAN", "VERIFIED"):
                break
            if not running and status_payload.get("last_result"):
                break
            time.sleep(2)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(EVID / "ui_mission_final.png"))
        result["final_status"] = status_payload
        result["cycle_id"] = status_payload.get("cycle_id")
        result["timed_out"] = time.monotonic() >= deadline

        # موافقة المالك — القناة المعلنة للمنتج (§6.3)
        verdict = ((status_payload.get("last_result") or {}).get("verdict")
                   or "")
        result["verdict"] = verdict
        if verdict == "PASS" and result.get("cycle_id"):
            code, verify_out = http(
                "POST", SERVER + "/api/mission/verify",
                body={"cycle_id": result["cycle_id"]},
            )
            result["owner_verify"] = {"http": code, **verify_out}
            page.wait_for_timeout(1200)
            page.screenshot(path=str(EVID / "ui_owner_verified.png"))
            log(f"owner verify via declared channel: {code} {verify_out}")
        else:
            result["owner_verify"] = None
            log(f"no owner verify — verdict={verdict!r}")
        browser.close()
    return result


def collect_evidence(mission: dict) -> None:
    # evidence.json الخاص بالمهمة (المنتج يكتبه في مجلد المهمة)
    code, evidence = http("GET", SERVER + "/api/mission/evidence")
    if code == 200:
        save("mission_evidence.json", evidence)
    save("mission_status_final.json", mission.get("final_status") or {})

    # ملفات مجلد المهمة ببصماتها
    mission_dir = WORK / "runtime/missions/default"
    inventory = {}
    if mission_dir.is_dir():
        for item in sorted(mission_dir.rglob("*")):
            if item.is_file():
                rel = str(item.relative_to(mission_dir))
                inventory[rel] = {
                    "bytes": item.stat().st_size,
                    "sha256": sha256_file(item),
                }
    save("mission_dir_inventory_sha256.json", inventory)

    # أحداث القاعدة للدورة (سجل كامل بلا اعتماد على الواجهة)
    cycle_id = mission.get("cycle_id") or ""
    if cycle_id:
        import sqlite3

        conn = sqlite3.connect(WORK / "runtime/agent_hub_v2.db")
        try:
            rows = conn.execute(
                "SELECT seq, role, kind, state, duration_ms, payload "
                "FROM events WHERE cycle_id = ? ORDER BY seq",
                (cycle_id,),
            ).fetchall()
            events = []
            for seq, role, kind, state, dur, payload in rows:
                try:
                    events.append(json.loads(payload))
                except ValueError:
                    events.append({"seq": seq, "role": role, "kind": kind,
                                   "state": state, "raw": str(payload)[:400]})
            save("mission_db_events.json", {
                "cycle_id": cycle_id, "count": len(events), "events": events,
            })
            log(f"mission db events: {len(events)} rows for {cycle_id}")
        finally:
            conn.close()

    # سجل العامل — إثبات مرور تنفيذ المهمة عبره (طلبات /run أثناء المهمة)
    worker_log = (WORK / "runtime/logs/worker_e11.log")
    if worker_log.is_file():
        lines = worker_log.read_text(encoding="utf-8", errors="replace")
        save("worker_log_e11_excerpt.txt", lines[-6000:])
    server_log = (WORK / "runtime/logs/server_e11.log")
    if server_log.is_file():
        lines = server_log.read_text(encoding="utf-8", errors="replace")
        save("server_log_e11_excerpt.txt", lines[-8000:])


def reset_session_state() -> None:
    """جلسة معزولة نظيفة لكل تشغيل (بنمط 013.15): قاعدة مجرّدة بالـ
    .gitignore ومجلد مهمة نظيف — الأدلة تُجمع من هذه الجلسة وحدها."""
    import shutil

    db = WORK / "runtime/agent_hub_v2.db"
    for stale in (db, db.with_name(db.name + "-journal"),
                  db.with_name(db.name + "-wal"),
                  db.with_name(db.name + "-shm")):
        if stale.exists():
            stale.unlink()
    missions_dir = WORK / "runtime/missions"
    if missions_dir.is_dir():
        shutil.rmtree(missions_dir)
    log("session state reset: fresh DB + fresh mission dir")


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    (WORK / "runtime/logs").mkdir(parents=True, exist_ok=True)
    reset_session_state()
    started = time.monotonic()
    summary: dict = {"order": "013.16 E11 live session"}
    try:
        start_processes()
        probe_worker_directly()
        infra = setup_via_product_api()
        summary.update(infra)
        mission = run_browser_mission()
        summary["mission"] = mission
        collect_evidence(mission)
    finally:
        for proc in reversed(processes):
            proc.terminate()
        time.sleep(1.5)
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
        log("worker + server terminated cleanly")

    summary["duration_s"] = round(time.monotonic() - started, 1)
    save("session_summary.json", summary)
    log("=== SESSION SUMMARY ===")
    log(json.dumps(summary, ensure_ascii=False, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
