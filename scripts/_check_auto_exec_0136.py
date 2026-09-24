"""(013.6 §E) تحقق حي: اعتماد الخطة + بيئة مؤهلة → انتقال تلقائي EXECUTION.

هذا الاختبار ينشئ مشروعًا بسياسة COMPATIBLE_LOCAL (بيئة مؤهلة),
يعتمد الخطة، ويتحقق من أن الحلقة تطلق تلقائيًا وتصل إلى EXECUTION
بلا refresh يدوي.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8022
BASE = f"http://127.0.0.1:{PORT}"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post(path: str, body: dict):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers={
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logs = ROOT / "runtime" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = open(logs / "auto_exec_0136.out", "w", encoding="utf-8")
    err = open(logs / "auto_exec_0136.err", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.routes:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, stdout=out, stderr=err,
    )
    try:
        for _ in range(45):
            time.sleep(1)
            try:
                get("/health")
                break
            except Exception:  # noqa: BLE001
                continue
        else:
            print("FAIL — الخادم لم يقلع")
            return 4

        # إنشاء مشروع بسياسة COMPATIBLE_LOCAL (بيئة مؤهلة)
        created = post("/api/projects", {
            "name": "اختبار انتقال تلقائي",
            "objective": "بناء خدمة تقارير أسبوعية داخلية بلا تكامل خارجي",
            "execution_policy": "COMPATIBLE_LOCAL",
        })
        pid = created["id"]
        print(f"Project created: {pid}")

        # توليد الخطة
        plan = post(f"/api/projects/{pid}/plan/generate", {})
        print(f"Plan generation started: {plan.get('session_id')}")

        # انتظار أن يكتمل التخطيط ويتحول المشروع إلى AWAITING_OWNER_APPROVAL
        deadline = time.monotonic() + 900.0  # نفس مهلة القبول
        while True:
            state = get(f"/api/projects/{pid}/state")
            proj_status = state.get("status")
            rt = state.get("environment", {}).get("runtime_state", {})
            print(f"Poll: project={proj_status}, rt={rt.get('state')}")
            if proj_status == "AWAITING_OWNER_APPROVAL":
                break
            if time.monotonic() > deadline:
                raise AssertionError(f"التخطيط لم يكتمل، الحالة: {proj_status}")
            time.sleep(2.0)  # أبطأ لتقليل الحمل

        print(f"Planning done, project status: {proj_status}")

        # اعتماد الخطة
        approved = post(f"/api/projects/{pid}/plan/approve", {"approved": True})
        print(f"Approve response: launched={approved.get('launch', {}).get('launched')}")

        # انتظار انتقال المشروع إلى EXECUTION (RUNNING)
        deadline = time.monotonic() + 60.0
        while True:
            state = get(f"/api/projects/{pid}/state")
            proj_status = state.get("status")
            rt_state = state.get("environment", {}).get("runtime_state", {}).get("state")
            print(f"Poll: project={proj_status}, rt={rt_state}")
            if proj_status == "RUNNING" or rt_state == "RUNNING":
                print("SUCCESS — المشروع دخل RUNNING تلقائيًا بعد الاعتماد!")
                return 0
            if time.monotonic() > deadline:
                raise AssertionError(f"المشروع لم يدخل RUNNING، الحالة: {proj_status}")
            time.sleep(0.5)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
        out.close()
        err.close()
        print("\n(الخادم أُوقف)")


if __name__ == "__main__":
    raise SystemExit(main())