"""(013.6 §1+§4) تحقق حي: هل صار للبيئة ثلاث حالات منفصلة؟

يشغّل الخادم، يقرأ كتلة بيئة مشروع حقيقي، ويطبع:
  - الحالات الثلاث لكل بيئة مسجلة (discovered/healthy/eligible)
  - وسم العرض (eligibility_label) الذي تمنع الواجهةُ تجاوزه
  - خيارات الركائز المتاحة فعلًا على هذا المضيف
  - حالة التشغيل القانونية وسبب عدم التوفر الحرفي

الفشل الصريح مقبول ومطلوب: على مضيف بلا ركيزة عزل يجب أن تكون
النتيجة UNAVAILABLE مع سبب حرفي — لا READY كاذبة.
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
PORT = 8021
BASE = f"http://127.0.0.1:{PORT}"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logs = ROOT / "runtime" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = open(logs / "env0136.out", "w", encoding="utf-8")
    err = open(logs / "env0136.err", "w", encoding="utf-8")
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

        projects = get("/api/projects")["projects"]
        if not projects:
            print("FAIL — لا مشاريع")
            return 3
        # آخر مشروع — الأقرب لما اختبره المالك
        project_id = projects[-1]["id"]
        state = get(f"/api/projects/{project_id}/state")
        env = state.get("environment") or {}
        print(f"project_id = {project_id}")
        print(f"policy     = {env.get('policy')} ({env.get('policy_label')})")
        print(f"satisfies_policy = {env.get('satisfies_policy')}")
        print(f"host       = {json.dumps(env.get('host'), ensure_ascii=False)}")
        print("\n--- البيئات المسجلة (الحالات الثلاث) ---")
        for item in env.get("environments", []):
            print(json.dumps(item, ensure_ascii=False, indent=1))
        print("\n--- خيارات الركائز (§4) ---")
        for option in env.get("substrate_options", []):
            print(json.dumps(option, ensure_ascii=False))
        print("\n--- الحالة القانونية ---")
        runtime = env.get("runtime_state") or {}
        print(f"state   = {runtime.get('state')}")
        print(f"coherent= {json.dumps(runtime.get('coherent'), ensure_ascii=False)}")
        print(f"reason  = {runtime.get('reason') or '(عرض متماسك)'}")
        print(f"missing = {json.dumps(runtime.get('missing'), ensure_ascii=False)[:600]}")
        return 0
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
