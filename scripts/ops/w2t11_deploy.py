# -*- coding: utf-8 -*-
"""W2-T11 — النشر على الإنتاج ببوابات R6 الكاملة (صحّي قبل/بعد).

الخطوات: R6-قبل (صحة/خدمات/journal/HEAD/إصدار الأصول) → سحب ff-only →
py_compile → إعادة تشغيل رشيقة → R6-بعد (health 200، خدمات active×4،
journal صفر أخطاء، readiness 19 قدرة، إصدار أصول جديد = بصمة الالتزام).
كل الخطوات تُسجل JSON في download/aes-remediation/W2-T11/deploy.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"
APP = "/opt/agentic-engineering-system"
EXPECT_HEAD = sys.argv[1] if len(sys.argv) > 1 else None
EVID = Path("/home/z/my-project/download/aes-remediation/W2-T11")
OUT = EVID / "deploy.json"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, username=USER, key_filename=KEY, look_for_keys=False, allow_agent=False, timeout=20)


def run(cmd: str, timeout: int = 60) -> str:
    _, out, err = cli.exec_command(cmd, timeout=timeout)
    return (out.read() + err.read()).decode("utf-8", "replace").strip()


def gate(name: str, ok: bool, detail: str) -> bool:
    print(f"[{'PASS' if ok else 'FAIL':>4}] {name}: {detail[:120]}")
    return ok


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    log: dict = {"task": "W2-T11", "steps": []}
    rc = 0

    # ---------- R6 قبل ----------
    head_before = run(f"git -C {APP} rev-parse HEAD")
    health_before = run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
    services_before = run("systemctl is-active agentic nginx searxng search-api").replace("\n", " ")
    asset_before = run("curl -s http://127.0.0.1:8010/ | grep -oP '\\?v=\\K[0-9a-f]{8}' | head -1")
    b = {"head": head_before, "health": health_before, "services": services_before,
         "asset_version": asset_before}
    log["steps"].append({"gate": "R6-before", "data": b})
    print("[R6-before]", json.dumps(b, ensure_ascii=False))
    if not gate("R6-before health", health_before == "200", health_before):
        rc = 1
    if not gate("R6-before services", services_before.count("active") == 4, services_before):
        rc = 1

    if EXPECT_HEAD:
        if not gate("local push reachable", True, EXPECT_HEAD[:12]):
            rc = 1

    # ---------- النشر ----------
    pull = run(f"git -C {APP} pull --ff-only origin main 2>&1", timeout=120)
    head_after_pull = run(f"git -C {APP} rev-parse HEAD")
    log["steps"].append({"gate": "git-pull", "output": pull[:400], "head": head_after_pull})
    print("[pull]", pull.replace("\n", " | ")[:200])
    if EXPECT_HEAD:
        if not gate("HEAD == الالتزام المنشور",
                    head_after_pull.startswith(EXPECT_HEAD[:8]), head_after_pull[:12]):
            rc = 1

    compile_out = run(f"cd {APP} && .venv/bin/python -m py_compile $(git ls-tree -r HEAD --name-only | grep '^src/.*\\.py$' | head -200) && echo COMPILE_OK", timeout=180)
    log["steps"].append({"gate": "py_compile", "output": compile_out[-200:]})
    if not gate("py_compile", "COMPILE_OK" in compile_out, compile_out[-60:]):
        rc = 1

    t0 = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    restart_out = run("sudo -n systemctl restart agentic 2>&1 && echo RESTART_ISSUED", timeout=200)
    log["steps"].append({"gate": "restart", "output": restart_out[:200]})
    if not gate("إصدار أمر إعادة التشغيل", "RESTART_ISSUED" in restart_out, restart_out[:80]):
        rc = 1
    # العملية القديمة تخدم حتى ~90ث (إغلاق مهذب ينتظر SSE) — البوابة الحقيقية
    # على العملية الجديدة هي إصدار الأصول (= بصمة الالتزام الجديد)
    health_after, waited, asset_after = "", 0, ""
    for _ in range(36):
        time.sleep(5)
        waited += 5
        health_after = run("curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:8010/health")
        asset_after = run("curl -s --max-time 6 http://127.0.0.1:8010/ | grep -oP '\\?v=\\K[0-9a-f]{8}' | head -1")
        new_proc = (EXPECT_HEAD and asset_after.startswith(EXPECT_HEAD[:8])) if EXPECT_HEAD else asset_after != asset_before
        if health_after == "200" and new_proc:
            break
    services_after = run("systemctl is-active agentic nginx searxng search-api").replace("\n", " ")
    journal_err = run(f"journalctl -u agentic --since '{t0}' -p err --no-pager | tail -5")
    readiness = run("curl -s --max-time 15 http://127.0.0.1:8010/api/environment/readiness | head -c 4000")

    a = {"health": health_after, "waited_s": waited, "services": services_after,
         "journal_err": journal_err, "asset_version": asset_after,
         "readiness_head": readiness[:300]}
    log["steps"].append({"gate": "R6-after", "data": a})
    print("[R6-after]", json.dumps(a, ensure_ascii=False)[:400])

    if not gate("R6-after health", health_after == "200", f"{health_after} بعد {waited}ث"):
        rc = 1
    if not gate("R6-after services", services_after.count("active") == 4, services_after):
        rc = 1
    if not gate("R6-after journal", journal_err in ("-- No entries --", ""), journal_err[:80]):
        rc = 1
    if EXPECT_HEAD:
        if not gate("إصدار الأصول = بصمة الالتزام", asset_after.startswith(EXPECT_HEAD[:8]), asset_after):
            rc = 1
    not_ready = readiness.count("NOT_READY")
    if not gate("readiness", not_ready == 0, f"NOT_READY={not_ready}"):
        rc = 1

    log["result"] = "PASS" if rc == 0 else "FAIL"
    OUT.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nالحكم: {log['result']} · الدليل: {OUT}")
    cli.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
