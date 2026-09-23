"""تحقق الفوضى والاسترداد (013.5 §Q) — قتل الخادم أثناء عمل حقيقي.

العطل الأصلي: مشروع حقيقي بقي في PLANNING قرابة 17992ث (‏5 ساعات) بعد
أن مات مولّد الخطة مع إغلاق الخادم، لأن كلب سير العمل لم يكن يُشغَّل
إلا داخل ``runner.launch`` — فلا فحص بعد إعادة التشغيل.

يقيس هذا الملف أربع حقائق على قاعدة البيانات الحيّة:

‏§Q1 — قتل الخادم **أثناء توليد حقيقي** يترك جلسة GENERATING في القاعدة.
‏§Q2 — إعادة التشغيل تُصالح الجلسة اليتيمة إلى حالة نهائية صادقة
      (لا تبقى GENERATING)، خلال زمن محدود ومقيس.
‏§Q3 — لا خطة ملفَّقة بعد الانهيار (لا نجاح بلا نداء مزود مكتمل).
‏§Q4 — فشل المزود الحقيقي يُصنَّف باسمه (لا انتظار صامت) عند تضييق
      المهلة عبر متغيرات البيئة وحدها — بلا تعديل كود.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
DB = ROOT / "runtime" / "agent_hub_v2.db"
EVID = ROOT / "runtime" / "evidence"
PORT = 8010
BASE = f"http://127.0.0.1:{PORT}"


# ------------------------------------------------------------------ #
# أدوات HTTP
# ------------------------------------------------------------------ #

def api(method: str, path: str, body: dict | None = None,
        timeout: float = 60.0, base: str = BASE):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    request = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, raw
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")[:400]
    except Exception as error:  # noqa: BLE001 — الخادم ميت = نتيجة
        return 0, f"{type(error).__name__}: {error}"


def health(timeout: float = 3.0, base: str = BASE) -> bool:
    status, _ = api("GET", "/health", timeout=timeout, base=base)
    return status == 200


# ------------------------------------------------------------------ #
# الخادم
# ------------------------------------------------------------------ #

def start_server(port: int = PORT, env_extra: dict | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({"PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1"})
    if env_extra:
        env.update(env_extra)
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "api.routes:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=creation)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if health(base=f"http://127.0.0.1:{port}"):
            return proc
        if proc.poll() is not None:
            raise RuntimeError(f"الخادم مات فورًا (exit={proc.returncode})")
        time.sleep(1.0)
    raise RuntimeError("الخادم لم يستجب خلال 90ث")


def hard_kill(proc: subprocess.Popen) -> dict:
    """قتل قسري — لا إغلاق لطيف (نحاكي انهيارًا لا إيقافًا نظيفًا)."""
    pid = proc.pid
    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                   capture_output=True, check=False)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.4)
    return {"pid": pid, "exit_code": proc.poll(),
            "gone": proc.poll() is not None}


# ------------------------------------------------------------------ #
# قراءة القاعدة مباشرة (المصدر الموثوق للحقيقة)
# ------------------------------------------------------------------ #

def db_rows(sql: str, params: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def project_row(project_id: int) -> dict | None:
    rows = db_rows(
        "SELECT id, status, current_plan_id, last_error FROM projects "
        "WHERE id = ?", (project_id,))
    if not rows:
        return None
    pid, status, plan_id, last_error = rows[0]
    return {"id": pid, "status": status, "current_plan_id": plan_id,
            "last_error": last_error}


def planning_rows(project_id: int) -> list[dict]:
    rows = db_rows(
        "SELECT id, state, error_class, actual_provider, actual_model, "
        "plan_id, started_at, finished_at FROM planning_sessions "
        "WHERE project_id = ? ORDER BY id", (project_id,))
    return [
        {"id": r[0], "state": r[1], "error_class": r[2],
         "actual_provider": r[3], "actual_model": r[4], "plan_id": r[5],
         "started_at": r[6], "finished_at": r[7]}
        for r in rows
    ]


def event_kinds(project_id: int, limit: int = 300) -> list[str]:
    rows = db_rows(
        "SELECT kind FROM project_events WHERE project_id = ? "
        "ORDER BY id LIMIT ?", (project_id, limit))
    return [r[0] for r in rows]


def wait_generating(project_id: int, timeout: float = 150.0) -> dict:
    """انتظر حتى يُقاس توليد حقيقي جارٍ (لا تخمين)."""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        status, runtime = api("GET", f"/api/projects/{project_id}/runtime")
        if status == 200 and isinstance(runtime, dict):
            planning = runtime.get("planning") or {}
            last = {"state": planning.get("state"),
                    "wait_phase": planning.get("wait_phase"),
                    "reasoning_chars": planning.get("reasoning_chars"),
                    "project_status": (runtime.get("project") or {}).get(
                        "status") or runtime.get("status")}
            if planning.get("state") == "GENERATING":
                return last
        time.sleep(2.0)
    return {**last, "timed_out": True}


# ------------------------------------------------------------------ #
# السيناريوهات
# ------------------------------------------------------------------ #

def scenario_crash_during_planning(evidence: dict) -> dict:
    """§Q1-§Q3: قتل الخادم أثناء توليد حقيقي ثم إعادة التشغيل."""
    server = start_server()
    out: dict = {}
    try:
        status, project = api("POST", "/api/projects", {
            "name": "تحقق 013.5 §Q — انهيار أثناء التخطيط",
            "objective": "قياس استرداد جلسة تخطيط يتيمة بعد قتل الخادم",
        })
        project_id = (project or {}).get("id") or (project or {}).get(
            "project_id")
        out["project_id"] = project_id
        out["create_http"] = status
        print(f"[§Q1] مشروع {project_id} أُنشئ (HTTP {status})", flush=True)
        status, started = api("POST",
                              f"/api/projects/{project_id}/plan/generate", {})
        out["generate_http"] = status
        print(f"[§Q1] بدء التوليد: HTTP {status}", flush=True)

        observed = wait_generating(project_id)
        out["generating_observed"] = observed
        print(f"[§Q1] التوليد الجاري: {json.dumps(observed, ensure_ascii=False)}",
              flush=True)
        out["was_generating"] = observed.get("state") == "GENERATING"

        rows_before = planning_rows(project_id)
        out["sessions_before_kill"] = rows_before
        print(f"[§Q1] جلسات قبل القتل: "
              f"{[(r['id'], r['state']) for r in rows_before]}", flush=True)

        kill = hard_kill(server)
        out["kill"] = kill
        print(f"[§Q1] قُتل الخادم: {json.dumps(kill)}", flush=True)

        # القاعدة بعد القتل مباشرة: هل بقيت GENERATING؟ (هذا هو العطل الأصلي)
        rows_after_kill = planning_rows(project_id)
        out["sessions_after_kill"] = rows_after_kill
        out["stuck_generating_after_kill"] = any(
            r["state"] == "GENERATING" for r in rows_after_kill)
        print(f"[§Q1] جلسات بعد القتل: "
              f"{[(r['id'], r['state'], r['error_class']) for r in rows_after_kill]}",
              flush=True)
    finally:
        if server.poll() is None:
            hard_kill(server)

    # ---- إعادة التشغيل: القياس الحقيقي للاسترداد ----
    boot_started = time.monotonic()
    server = start_server()
    out["boot_seconds"] = round(time.monotonic() - boot_started, 1)
    try:
        project_id = out["project_id"]
        healed_at = None
        series: list[dict] = []
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            rows = planning_rows(project_id)
            project = project_row(project_id)
            entry = {
                "t": round(time.monotonic() - boot_started, 1),
                "sessions": [(r["id"], r["state"], r["error_class"])
                             for r in rows],
                "project_status": (project or {}).get("status"),
                "plan_id": (project or {}).get("current_plan_id"),
            }
            series.append(entry)
            if rows and all(r["state"] != "GENERATING" for r in rows):
                healed_at = entry["t"]
                break
            time.sleep(3.0)
        out["recovery_series"] = series
        out["healed_after_seconds"] = healed_at
        out["sessions_after_boot"] = planning_rows(project_id)
        final_project = project_row(project_id)
        out["project_after_boot"] = final_project
        out["events"] = event_kinds(project_id)
        print(f"[§Q2] استُردت في {healed_at}ث بعد الإقلاع | مشروع="
              f"{(final_project or {}).get('status')} | جلسات="
              f"{[(r['id'], r['state'], r['error_class']) for r in out['sessions_after_boot']]}",
              flush=True)

        # ---- §Q3: لا خطة ملفقة ----
        status, plan = api("GET", f"/api/projects/{project_id}/plan")
        plan_id = (final_project or {}).get("current_plan_id")
        out["plan_http"] = status
        out["plan_body_keys"] = (sorted(plan) if isinstance(plan, dict)
                                 else str(plan)[:200])
        out["plan_after_crash"] = plan_id
        out["no_fabricated_plan"] = plan_id is None and not (
            isinstance(plan, dict) and plan.get("id"))
        print(f"[§Q3] خطة بعد الانهيار: project.current_plan_id={plan_id} | "
              f"HTTP {status} | لا تلفيق={out['no_fabricated_plan']}", flush=True)
    finally:
        if server.poll() is None:
            hard_kill(server)
    return out


def scenario_provider_failure(evidence: dict) -> dict:
    """§Q4: فشل مزود حقيقي يُصنَّف — بلا انتظار صامت (§C/§D)."""
    port = 8012
    base = f"http://127.0.0.1:{port}"
    server = start_server(
        port=port,
        env_extra={"AGENTHUB_PLAN_HARD_TIMEOUT": "25",
                   "AGENTHUB_PLAN_SILENCE_LIMIT": "12"})
    out: dict = {"port": port}
    try:
        status, project = api("POST", "/api/projects", {
            "name": "تحقق 013.5 §Q — فشل مزود مصنَّف",
            "objective": "قياس تصنيف فشل المزود عند تضييق المهلة",
        }, base=base)
        project_id = (project or {}).get("id") or (project or {}).get(
            "project_id")
        out["project_id"] = project_id
        print(f"[§Q4] مشروع {project_id} (مهلة 25ث، صمت 12ث)", flush=True)
        status, started = api("POST",
                              f"/api/projects/{project_id}/plan/generate", {},
                              base=base)
        out["generate_http"] = status
        deadline = time.monotonic() + 200
        series: list[dict] = []
        while time.monotonic() < deadline:
            rows = planning_rows(project_id)
            project = project_row(project_id)
            series.append({
                "t": round(time.monotonic() - (deadline - 200), 1),
                "sessions": [(r["id"], r["state"], r["error_class"])
                             for r in rows],
                "project_status": (project or {}).get("status"),
            })
            if rows and all(r["state"] not in ("GENERATING", "QUEUED",
                                               "CONNECTING") for r in rows):
                break
            time.sleep(3.0)
        out["series"] = series
        out["sessions_final"] = planning_rows(project_id)
        out["project_final"] = project_row(project_id)
        out["events"] = event_kinds(project_id)
        failed = [r for r in out["sessions_final"]
                  if r["state"] == "FAILED" and r["error_class"]]
        out["classified_failure"] = bool(failed)
        out["error_classes"] = sorted({r["error_class"]
                                       for r in out["sessions_final"]
                                       if r["error_class"]})
        out["bounded_seconds"] = series[-1]["t"] if series else None
        print(f"[§Q4] جلسات: "
              f"{[(r['id'], r['state'], r['error_class']) for r in out['sessions_final']]}"
              f" | مشروع={(out['project_final'] or {}).get('status')}"
              f" | في {out['bounded_seconds']}ث", flush=True)
    finally:
        if server.poll() is None:
            hard_kill(server)
    return out


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    evidence: dict = {"started_at": started.isoformat()}
    print("=== §Q1-§Q3: انهيار أثناء توليد حقيقي ===", flush=True)
    evidence["crash"] = scenario_crash_during_planning(evidence)
    print("\n=== §Q4: فشل مزود مصنَّف بمهلة مضيّقة ===", flush=True)
    evidence["provider_failure"] = scenario_provider_failure(evidence)

    crash = evidence["crash"]
    provider = evidence["provider_failure"]
    checks = {
        "crash_was_mid_generation": bool(crash.get("was_generating")),
        "server_actually_died": bool(crash.get("kill", {}).get("gone")),
        "orphan_was_generating": bool(
            crash.get("stuck_generating_after_kill")),
        "session_healed_after_boot": (
            crash.get("healed_after_seconds") is not None
            and not any(r["state"] == "GENERATING"
                        for r in crash.get("sessions_after_boot", []))),
        "healed_within_120s": (crash.get("healed_after_seconds") is not None
                               and crash["healed_after_seconds"] <= 120),
        "no_fabricated_plan": bool(crash.get("no_fabricated_plan")),
        "provider_failure_classified": bool(provider.get("classified_failure")),
        "provider_failure_bounded": (
            provider.get("bounded_seconds") is not None
            and provider["bounded_seconds"] <= 180),
    }
    evidence["checks"] = checks
    evidence["error_classes_observed"] = provider.get("error_classes")
    evidence["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    evidence["finished_at"] = datetime.now(timezone.utc).isoformat()

    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    path = EVID / f"order0135-q-chaos-{stamp}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print("\n=== الفحوص ===", flush=True)
    for name, value in checks.items():
        print(f"  {'✓' if value else '✗'} {name} = {value}")
    print(f"\nالحكم §Q: {evidence['verdict']}")
    print(f"أصناف الفشل المقيسة: {evidence['error_classes_observed']}")
    print(f"دليل: {path}")
    return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
