# -*- coding: utf-8 -*-
"""الجلسة الحية المنسقة لأمر 013.17 — E11 إصلاح أمانة البيانات وبوابة
موافقة المالك البشرية الفعلية.

تصحيحي محدود على 013.16 (الذي رفضه التحكيم لعيبين):
  1. أمانة البيانات: هدف المهمة ينقل بيانات ORDER013.13 **حرفيًا**
     (header + 6 صفوف بالترتيب) من المصدر الوحيد
     ``scripts/order01317_fixture.py`` — لا مجاميع بديلة ولا عينة
     من صنع المنفّذ. وبعد الدورة يُقارن الملف المنتَج صفًا بصف عبر
     المدقق المستقل، ويُعاد تشغيل الأداة فعليًا على الملف المعتمد
     لمقارنة report.md، وتُعاد حالتا CSV الفارغ والمبلغ غير الصالح
     في مجلدات مؤقتة دون إفساد الملف الأصلي.
  2. موافقة المالك: هذا السكربت **لا يرسل** ``POST /api/mission/verify``
     ولا ينقر أي موافقة ولا ينشئ حدث user_verification نيابةً عن
     المالك — يوجد تدقيق ذاتي ميكانيكي يفشل الجلسة فورًا إذا ظهر
     الاستدعاء المحظور في مصدرها. عند انتهاء الدورة بحكم PASS تُوقف
     الجلسة عند بوابة الموافقة وتُسلّم المالك: معرف الدورة ورابط
     الواجهة والإجراء الوحيد المطلوب (زر «أوافق على النتيجة» في بطاقة
     الدورة — القناة البشرية المعلنة عبر /api/cycle/verify).

التشغيل (في البيئة المعتمدة ذات الركيزة Linux — نمط 013.15/013.16):
    ORDER01317_WORK=/home/z/my-project/order01317_work  (clone للفرع)
    python scripts/e11_session_01317.py
لا يطبع أي سر: التوكن وقت-تشغيل من ملف بصلاحيات مقيدة، وبصمته فقط
في الأدلة. لا ui_owner_verified.png — الموافقة قرار المالك حصرًا.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from order01317_fixture import APPROVED_CSV, verify_fixture  # noqa: E402

WORK = Path(os.environ.get(
    "ORDER01317_WORK", "/home/z/my-project/order01317_work"))
VENV_PY = os.environ.get(
    "ORDER01317_VENV_PY", str(WORK / ".venv" / "bin" / "python"))
TOKEN_FILE = Path(os.environ.get(
    "ORDER01317_TOKEN_FILE",
    str(WORK.parent / ".order01317_worker_token")))
EVID = WORK / "docs" / "evidence" / "order01317"
SERVER = os.environ.get("ORDER01317_SERVER", "http://127.0.0.1:8010")
WORKER = os.environ.get("ORDER01317_WORKER", "http://127.0.0.1:8900")

#: (D1-1) البيانات الحرفية جزء إلزامي من هدف المهمة — من المصدر الوحيد
MISSION_GOAL = (
    "مهمة برمجية: اكتب أداة Python باسم tool.py تستخدم المكتبات القياسية "
    "فقط (stdlib)، تقرأ ملف transactions.csv وتنتج report.md بالإجماليات. "
    "بيانات الإدخال المعتمدة حرفيًا — يجب أن يكون ملف transactions.csv "
    "مطابقًا لهذه البيانات تمامًا: نفس الأعمدة (date,category,amount) "
    "ونفس الصفوف الستة بنفس الترتيب والتواريخ والمبالغ، دون أي زيادة "
    "أو نقصان أو تبديل:\n"
    "```csv\n" + APPROVED_CSV.rstrip("\n") + "\n```\n"
    "القيم المرجعية المشتقة من البيانات أعلاه: 6 سجلات، food=25.00، "
    "travel=40.00، tools=20.00، الإجمالي الكلي=85.00. اكتب أيضًا ملف "
    "اختبارات test_tool.py تغطي ثلاث حالات: الإدخال الصحيح (على البيانات "
    "المعتمدة نفسها أعلاه حرفيًا وتتحقق من الإجماليات الأربع)، وملف CSV "
    "فارغ (ترفضه الأداة برمز خروج غير صفري)، ومبلغ غير صالح (ترفضه "
    "الأداة برمز خروج غير صفري) — دون إفساد ملف البيانات المعتمد. "
    "نفّذ الأداة والاختبارات فعليًا داخل الركيزة المعزولة وتحقق أن "
    "report.md ناتج فعلي من تنفيذ الأداة على transactions.csv."
)

#: استدعاء الموافقة المحظور آليًا — يُبنى من جزأين كي لا يحوي مصدر
#: السكربت النص الحرفي الكامل، والتدقيق ذاتي فلكسي (AST) يفحص
#: استدعاءات الكود الفعلية حصرًا (لا نصوص التوثيق).
FORBIDDEN_HOST_PART = "/api/mission/"
FORBIDDEN_TAIL_PART = "verify"


_state = {"screens": 0}
processes: list[subprocess.Popen] = []


def log(msg: str) -> None:
    print(f"[session {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def http(method: str, url: str, body: dict | None = None,
         timeout: float = 30.0, headers: dict | None = None):
    data = (json.dumps(body, ensure_ascii=False).encode()
            if body is not None else None)
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
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8")
    else:
        target.write_text(str(payload), encoding="utf-8")
    log(f"saved {name}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def self_audit_no_auto_approval() -> None:
    """(D2-1) تدقيق ذاتي ميكانيكي (AST): لا استدعاء فعلي في هذا
    السكربت يمرر قناة الموافقة المحظورة داخل وسيطه النصي — أي ظهور
    فيها داخل استدعاء = إخفاق فوري للجلسة. النصوص التوثيقية والثوابت
    الجزئية لا تُحتسب؛ الاستدعاءات وحدها هي الخطر."""
    import ast

    forbidden = FORBIDDEN_HOST_PART + FORBIDDEN_TAIL_PART
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        args = (*node.args, *[
            kw.value for kw in node.keywords if kw.value is not None])
        for arg in args:
            for sub in ast.walk(arg):
                if (isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and forbidden in sub.value):
                    hits.append(sub.value)
    if hits:
        raise SystemExit(
            "FATAL: self-audit failed — forbidden auto-approval "
            f"channel present in session call-args: {hits}")
    log("self-audit (AST): no auto-approval call in session source ✓")


def start_processes() -> None:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    (WORK / "runtime/logs").mkdir(parents=True, exist_ok=True)
    worker_log = open(WORK / "runtime/logs/worker_01317.log", "w")
    server_log = open(WORK / "runtime/logs/server_01317.log", "w")
    processes.append(subprocess.Popen(
        [VENV_PY, "scripts/execution_worker.py", "--port",
         str(WORKER.rsplit(":", 1)[-1]), "--host", "127.0.0.1",
         "--token", token],
        cwd=WORK, stdout=worker_log, stderr=subprocess.STDOUT,
    ))
    log("worker launching (substrate mode required)")
    for _ in range(40):
        code, out = http("GET", WORKER + "/health", timeout=3,
                         headers={"Authorization": f"Bearer {token}"})
        if code == 200 and out.get("backend_mode") == "substrate":
            break
        time.sleep(0.5)
    else:
        raise SystemExit(
            "FATAL: worker did not reach substrate mode — STRICT gate "
            "requires an authorized Linux substrate; refusing to "
            "continue in subprocess mode (no fallback per order)")
    log("worker healthy: backend_mode=substrate")

    processes.append(subprocess.Popen(
        [VENV_PY, "-m", "uvicorn", "api.routes:app", "--port",
         str(SERVER.rsplit(":", 1)[-1]), "--host", "127.0.0.1"],
        cwd=WORK, stdout=server_log, stderr=subprocess.STDOUT,
    ))
    for _ in range(60):
        code, _ = http("GET", SERVER + "/health", timeout=3)
        if code == 200:
            break
        time.sleep(0.5)
    else:
        raise SystemExit("FATAL: server did not become healthy")
    log(f"server healthy on {SERVER}")


def probe_worker_directly() -> None:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    auth = {"Authorization": f"Bearer {token}"}
    _, health = http("GET", WORKER + "/health", headers=auth)
    _, caps = http("GET", WORKER + "/capabilities", headers=auth)
    _, probe = http("POST", WORKER + "/probe", body={}, headers=auth,
                    timeout=60)
    challenge = f"order01317-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    _, iso = http("POST", WORKER + "/probe_isolation",
                  body={"challenge_id": challenge},
                  headers=auth, timeout=90)
    save("worker_live_health.json", health)
    save("worker_live_capabilities.json", caps)
    save("worker_live_probe.json", probe)
    save("worker_live_isolation_probe.json", iso)
    log(f"worker probes: probe.ok={probe.get('ok')} "
        f"isolation.verdict={iso.get('verdict')} "
        f"challenge_repeated={iso.get('challenge_id') == challenge}")
    if not (probe.get("ok") and iso.get("verdict") == "BLOCKED"
            and iso.get("challenge_id") == challenge):
        raise SystemExit(
            "FATAL: worker probes failed — isolation not proven live")


def setup_via_product_api() -> dict:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    code, created = http("POST", SERVER + "/api/execution/environments",
                         body={
                             "name": "order01317-worker-linux",
                             "backend": "REMOTE_WORKER",
                             "endpoint": WORKER,
                             "token": token,
                             "make_default": True,
                         })
    if code not in (200, 201):
        raise SystemExit(f"FATAL: env registration failed: {created}")
    env_id = created.get("id") or created.get("environment_id")
    log(f"environment registered via product API: id={env_id}")

    code, verified = http(
        "POST", f"{SERVER}/api/execution/environments/{env_id}/verify",
        body={}, timeout=120)
    save("environment_verify_8_8.json", verified)
    verify_block = verified.get("verify") or {}
    checks = verify_block.get("checks") or []
    ok_count = sum(1 for c in checks if c.get("ok"))
    log(f"environment verify: ok={verify_block.get('ok')} "
        f"status={verified.get('status')} checks={ok_count}/{len(checks)}")
    if not verify_block.get("ok") or ok_count < 8:
        raise SystemExit(f"FATAL: environment verify not 8/8: {verified}")

    code, test_run = http(
        "POST",
        f"{SERVER}/api/execution/environments/{env_id}/test-run",
        body={}, timeout=120)
    save("environment_test_run.json", test_run)
    log(f"environment test-run exit={test_run.get('exit_code')}")

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

    code, providers = http("GET", SERVER + "/api/providers")
    zai = next((p for p in providers.get("providers", [])
                if p.get("name") == "zai_internal"), None)
    if zai is None:
        raise SystemExit("FATAL: zai_internal not in provider registry")
    _, configs = http(
        "GET", f"{SERVER}/api/providers/{zai['id']}/configurations")
    cfg_list = configs.get("configurations") or []
    cfg_id = cfg_list[0]["id"] if cfg_list else None
    code, probe = http(
        "POST",
        f"{SERVER}/api/provider-configurations/{cfg_id}/test",
        body={}, timeout=180)
    save("provider_live_probe.json", probe)
    log(f"provider live probe: status={probe.get('status')} "
        f"model={probe.get('model', '')}")
    return {"env_id": env_id, "provider_id": zai["id"],
            "config_id": cfg_id}


def run_browser_mission() -> dict:
    """(D2-3/4) الدورة من الواجهة — والتوقف عند بوابة موافقة المالك:
    لا استدعاء موافقة إطلاقًا؛ تسليم يد موثق (معرف + رابط + الإجراء
    الوحيد). لا ui_owner_verified.png في هذا الأمر أبدًا."""
    result: dict = {"mission_created_from": "browser Control Room UI"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(SERVER, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#input", state="visible", timeout=20000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(EVID / "ui_00_landing.png"))

        page.click("#settings-open")
        page.wait_for_selector("#settings-drawer:not([hidden])")
        page.click('#settings-tabs button[data-tab="execution"]')
        page.wait_for_timeout(1500)
        page.screenshot(path=str(EVID / "ui_01_env_verified.png"))
        page.click('#settings-tabs button[data-tab="models"]')
        page.wait_for_timeout(1500)
        page.screenshot(path=str(EVID / "ui_02_models_zai.png"))

        page.click("#settings-close")
        page.wait_for_timeout(500)
        # (D1-1) الهدف ببيانات المعتمد الحرفية في حقل الإدخال الرئيسي
        page.fill("#input", MISSION_GOAL)
        page.click("#settings-open")
        page.wait_for_selector("#settings-drawer:not([hidden])")
        page.click('#settings-tabs button[data-tab="advanced"]')
        page.wait_for_timeout(800)
        page.screenshot(path=str(EVID / "ui_03_advanced_ready.png"))
        page.click("#mission-run")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(EVID / "ui_04_mission_started.png"))
        log("browser: mission launched from Control Room UI "
            "(goal includes literal approved CSV)")

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
                                         "ESCALATED_TO_HUMAN"):
                break
            if not running and status_payload.get("last_result"):
                break
            time.sleep(2)
        page.wait_for_timeout(1500)
        # (D2-3) لقطة بوابة الانتظار — ليست لقطة موافقة منفَّذة
        page.screenshot(path=str(EVID / "ui_05_approval_waiting.png"))
        result["final_status"] = status_payload
        result["cycle_id"] = status_payload.get("cycle_id")
        result["timed_out"] = time.monotonic() >= deadline
        verdict = ((status_payload.get("last_result") or {}).get("verdict")
                   or "")
        result["verdict"] = verdict
        # (D2-6) لا يُعتبر أي سجل user/endpoint دليل موافقة — لا نداء
        # موافقة هنا إطلاقًا؛ المالك وحده يوافق عبر الواجهة.
        result["owner_approval"] = {
            "status": "WAITING_OWNER" if verdict == "PASS" else
                      f"NOT_ELIGIBLE ({verdict or 'no verdict'})",
            "auto_verify_sent": False,
            "note": "session stopped at the owner approval gate — "
                    "no verify call was made by the executor",
        }
        browser.close()
    return result


def independent_d1_audit() -> dict:
    """(D1-2..6 + D3) تدقيق مستقل آلي بعد الدورة:
    1) مقارنة transactions المنتَج صفًا بصف مع المعتمد.
    2) إعادة تشغيل الأداة فعليًا على الملف المعتمد في مجلد مؤقت
       ومقارنة report الناتج بملف المهمة (بصمة sha256).
    3) إعادة حالتي CSV الفارغ والمبلغ غير الصالح في مجلدات مؤقتة —
       يجب أن تفشل برمز خروج غير صفري، ودون لمس الملف المعتمد.
    """
    mission_dir = WORK / "runtime/missions/default"
    audit: dict = {"mission_dir": str(mission_dir)}

    produced_csv = mission_dir / "transactions.csv"
    fixture_report = verify_fixture(produced_csv)
    save("fixture_verification.json", fixture_report)
    audit["fixture_match"] = fixture_report["ok"]
    log(f"fixture row-by-row match: {fixture_report['ok']} "
        f"(findings={len(fixture_report['findings'])})")

    tool_py = mission_dir / "tool.py"
    if tool_py.is_file():
        with tempfile.TemporaryDirectory(prefix="e111317-") as td:
            tmp = Path(td)
            shutil.copy2(tool_py, tmp / "tool.py")
            (tmp / "transactions.csv").write_text(
                APPROVED_CSV, encoding="utf-8")
            run = subprocess.run(
                [VENV_PY, str(tmp / "tool.py")], cwd=tmp,
                capture_output=True, timeout=120)
            reproduced = tmp / "report.md"
            audit["reproduction"] = {
                "exit_code": run.returncode,
                "report_reproduced": reproduced.is_file(),
                "reproduced_sha256": sha256_file(reproduced)
                if reproduced.is_file() else None,
                "mission_report_sha256": sha256_file(mission_dir
                                                     / "report.md")
                if (mission_dir / "report.md").is_file() else None,
            }
            if (mission_dir / "report.md").is_file() and reproduced.is_file():
                audit["reproduction"]["report_sha_equal"] = (
                    audit["reproduction"]["mission_report_sha256"]
                    == audit["reproduction"]["reproduced_sha256"])
            log(f"independent reproduction exit={run.returncode} "
                f"sha_equal={audit['reproduction'].get('report_sha_equal')}")

        cases: dict = {}
        with tempfile.TemporaryDirectory(prefix="e111317-neg-") as td:
            tmp = Path(td)
            shutil.copy2(tool_py, tmp / "tool.py")
            (tmp / "empty.csv").write_text("", encoding="utf-8")
            run_empty = subprocess.run(
                [VENV_PY, str(tmp / "tool.py"), "empty.csv", "out.md"],
                cwd=tmp, capture_output=True, timeout=120)
            cases["empty_csv_nonzero_exit"] = {
                "exit_code": run_empty.returncode,
                "ok_nonzero": run_empty.returncode != 0,
            }
        with tempfile.TemporaryDirectory(prefix="e111317-bad-") as td:
            tmp = Path(td)
            shutil.copy2(tool_py, tmp / "tool.py")
            (tmp / "bad.csv").write_text(
                "date,category,amount\n2026-10-01,food,abc\n",
                encoding="utf-8")
            run_bad = subprocess.run(
                [VENV_PY, str(tmp / "tool.py"), "bad.csv", "out.md"],
                cwd=tmp, capture_output=True, timeout=120)
            cases["invalid_amount_nonzero_exit"] = {
                "exit_code": run_bad.returncode,
                "ok_nonzero": run_bad.returncode != 0,
            }
        audit["negative_cases"] = cases
        save("independent_test_reruns.json", audit["reproduction"]
             | {"negative_cases": cases})

    audit["canonical_file_untouched"] = (
        produced_csv.is_file()
        and verify_fixture(produced_csv)["ok"])
    return audit


def collect_evidence(mission: dict, audit: dict) -> None:
    code, evidence = http("GET", SERVER + "/api/mission/evidence")
    if code == 200:
        save("mission_evidence.json", evidence)
    save("mission_status_final.json", mission.get("final_status") or {})

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

    cycle_id = mission.get("cycle_id") or ""
    if cycle_id:
        import sqlite3

        conn = sqlite3.connect(WORK / "runtime/agent_hub_v2.db")
        try:
            rows = conn.execute(
                "SELECT seq, role, kind, state, duration_ms, payload "
                "FROM events WHERE cycle_id = ? ORDER BY seq",
                (cycle_id,)).fetchall()
            events = []
            for seq, role, kind, state, dur, payload in rows:
                try:
                    events.append(json.loads(payload))
                except ValueError:
                    events.append({"seq": seq, "role": role,
                                   "kind": kind, "state": state,
                                   "raw": str(payload)[:400]})
            save("mission_db_events.json", {
                "cycle_id": cycle_id, "count": len(events),
                "events": events,
            })
            log(f"mission db events: {len(events)} rows for {cycle_id}")
        finally:
            conn.close()

    worker_log = WORK / "runtime/logs/worker_01317.log"
    if worker_log.is_file():
        save("worker_log_01317_excerpt.txt",
             worker_log.read_text(encoding="utf-8",
                                  errors="replace")[-6000:])
    server_log = WORK / "runtime/logs/server_01317.log"
    if server_log.is_file():
        save("server_log_01317_excerpt.txt",
             server_log.read_text(encoding="utf-8",
                                  errors="replace")[-8000:])


def owner_handoff(mission: dict) -> dict:
    """(D2-4) تسليم يد المالك: معرف الدورة + رابط الواجهة + الإجراء
    الوحيد المطلوب. يُحفظ أدلة ويُطبع للجلسة."""
    cycle_id = mission.get("cycle_id") or ""
    handoff = {
        "mission_cycle_id": cycle_id,
        "review_url": SERVER,
        "state": (mission.get("final_status") or {}).get("state"),
        "verdict": mission.get("verdict"),
        "single_required_action": (
            "افتح رابط الواجهة ← بطاقة الدورة الظاهرة بنتيجة PASS تحمل "
            "زر «أوافق على النتيجة» — نقرة واحدة تسجل موافقتك البشرية "
            "(POST /api/cycle/verify عبر الواجهة). لا تستخدم أي أداة "
            "آلية نيابةً عنك."),
        "auto_approval_by_executor": False,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime()),
    }
    save("owner_approval_handoff.json", handoff)
    log("OWNER HANDOFF: " + json.dumps(handoff, ensure_ascii=False))
    return handoff


def reset_session_state() -> None:
    """جلسة معزولة نظيفة (نمط 013.16) — قاعدة مجرّدة ومجلد مهمة نظيف."""
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
    self_audit_no_auto_approval()
    reset_session_state()
    started = time.monotonic()
    summary: dict = {"order": "013.17 E11 fixture fidelity + owner gate"}
    try:
        start_processes()
        probe_worker_directly()
        infra = setup_via_product_api()
        summary.update(infra)
        mission = run_browser_mission()
        summary["mission"] = mission
        audit = independent_d1_audit()
        summary["d1_independent_audit"] = {
            k: audit.get(k) for k in (
                "fixture_match", "reproduction", "negative_cases",
                "canonical_file_untouched")}
        collect_evidence(mission, audit)
        if mission.get("verdict") == "PASS":
            owner_handoff(mission)
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
