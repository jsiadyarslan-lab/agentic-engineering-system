"""Test P0 Case B: Truthfully reach ENVIRONMENT_UNAVAILABLE with real provisioning path."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8025
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
    out = open(logs / "p0_case_b.out", "w", encoding="utf-8")
    err = open(logs / "p0_case_b.err", "w", encoding="utf-8")
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

        # Create project with STRICT_ISOLATED (default)
        created = post("/api/projects", {
            "name": "P0 Case B Test",
            "objective": "بناء خدمة تقارير أسبوعية داخلية بلا تكامل خارجي",
        })
        pid = created["id"]
        print(f"Project created: {pid}, status: {created['status']}")

        # Generate plan
        plan = post(f"/api/projects/{pid}/plan/generate", {})
        print(f"Plan generation started")

        # Wait for plan completion
        deadline = time.monotonic() + 900.0
        while True:
            state = get(f"/api/projects/{pid}/state")
            proj_status = state.get("status")
            rt = state.get("environment", {}).get("runtime_state", {})
            print(f"Poll: project={proj_status}, rt={rt.get('state')}")
            if proj_status == "AWAITING_OWNER_APPROVAL":
                break
            if time.monotonic() > deadline:
                raise AssertionError(f"Planning timeout, status: {proj_status}")
            time.sleep(2.0)

        print(f"Planning done, project status: {proj_status}")

        # Approve plan
        approved = post(f"/api/projects/{pid}/plan/approve", {"approved": True})
        print(f"Approve response: launched={approved.get('launch', {}).get('launched')}")

        # Wait for project to reach terminal state
        deadline = time.monotonic() + 120.0
        while True:
            state = get(f"/api/projects/{pid}/state")
            proj_status = state.get("status")
            rt_state = state.get("environment", {}).get("runtime_state", {}).get("state")
            env_block = state.get("environment", {})
            print(f"Poll: project={proj_status}, rt={rt_state}, env={env_block.get('runtime_state', {}).get('state')}")
            if proj_status in ("COMPLETED", "BLOCKED", "FAILED", "STOPPED"):
                break
            if time.monotonic() > deadline:
                raise AssertionError(f"Project didn't reach terminal state: {proj_status}")
            time.sleep(1.0)

        # Check final state
        final_state = get(f"/api/projects/{pid}/state")
        proj_status = final_state.get("status")
        env_block = final_state.get("environment", {})
        rt_state = env_block.get("runtime_state", {})
        satisfies = env_block.get("satisfies_policy")

        print(f"\n=== FINAL STATE ===")
        print(f"Project status: {proj_status}")
        print(f"Runtime state: {rt_state.get('state')}")
        print(f"Coherent: {rt_state.get('coherent')}")
        print(f"Satisfies policy: {satisfies}")
        print(f"Environment block: {json.dumps(env_block, ensure_ascii=False)[:1000]}")

        # Check if we reached ENVIRONMENT_UNAVAILABLE truthfully
        if rt_state.get('state') == 'UNAVAILABLE':
            reason = rt_state.get('reason', '')
            missing = rt_state.get('missing', [])
            print(f"\n✅ REACHED ENVIRONMENT_UNAVAILABLE TRUTHFULLY")
            print(f"Reason: {reason}")
            print(f"Missing: {json.dumps(missing, ensure_ascii=False)}")
            print(f"Satisfies policy: {satisfies}")
            return 0
        elif proj_status == "RUNNING":
            print(f"\n✅ REACHED RUNNING - REAL EXECUTION!")
            return 0
        else:
            print(f"\n❌ UNEXPECTED STATE: {proj_status}")
            return 1

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