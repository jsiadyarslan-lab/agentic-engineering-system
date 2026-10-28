#!/usr/bin/env python3
# W2-T23 deploy: ff pull 0916484 -> py_compile -> R6-gated restart -> verify
import json, time, paramiko, os

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T23"
os.makedirs(EVDIR, exist_ok=True)
EXPECT_HEAD = "0916484812bd371462a49bec5e939871240c2af1"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T23 deploy (0916484)", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=180, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:140], "rc": rc, "out": out.strip()[:3000],
            "err": err.strip()[:400]}

# --- R6: gate BEFORE ---
ev["health_before"] = run("curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health", 20, "health before")
ev["head_before"] = run("sudo -n git -C /opt/agentic-engineering-system rev-parse HEAD", 20, "HEAD before")
ev["status_before"] = run("sudo -n git -C /opt/agentic-engineering-system status --short | head -8", 20, "status before")
ev["services_before"] = run("systemctl is-active agentic nginx searxng search-api", 20, "services before")

gate_ok = (ev["health_before"]["out"] == "200" and ev["head_before"]["out"] == "6fc02343cbd7453d368bb3d96313214b004e989e")
if not gate_ok:
    ev["_meta"]["ABORT"] = "pre-deploy gate failed: health=%s head=%s" % (
        ev["health_before"]["out"], ev["head_before"]["out"])
    with open(os.path.join(EVDIR, "deploy.json"), "w") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    print("ABORT pre-gate:", ev["_meta"]["ABORT"])
    ssh.close()
    raise SystemExit(2)

# --- pull ff-only ---
ev["git_pull"] = run("sudo -n git -C /opt/agentic-engineering-system pull --ff-only origin main 2>&1 | tail -4", 120, "git ff pull")
ev["head_after_pull"] = run("sudo -n git -C /opt/agentic-engineering-system rev-parse HEAD", 20, "HEAD after pull")
if ev["head_after_pull"]["out"] != EXPECT_HEAD:
    ev["_meta"]["ABORT"] = "head after pull != expected: %s" % ev["head_after_pull"]["out"]
    with open(os.path.join(EVDIR, "deploy.json"), "w") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    print("ABORT head-mismatch:", ev["_meta"]["ABORT"])
    ssh.close()
    raise SystemExit(2)

# --- py_compile gate on the changed role files ---
ev["py_compile"] = run(
    "cd /opt/agentic-engineering-system && .venv/bin/python -m py_compile "
    "src/roles/implementer_live.py src/roles/build_files.py src/roles/verifier.py && echo COMPILE_OK", 120, "py_compile")
if "COMPILE_OK" not in ev["py_compile"]["out"]:
    ev["_meta"]["ABORT"] = "py_compile failed"
    with open(os.path.join(EVDIR, "deploy.json"), "w") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    print("ABORT compile:", ev["py_compile"])
    ssh.close()
    raise SystemExit(2)

# --- restart + R6 gate AFTER ---
t_restart = time.time()
ev["restart"] = run("sudo -n systemctl restart agentic && echo RESTART_ISSUED", 120, "restart")
health_after = ""
for i in range(36):
    time.sleep(5)
    code = run("curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8010/health", 20, "health poll")
    if code.get("out") == "200":
        health_after = "200 (after %ds)" % int(time.time() - t_restart)
        break
ev["health_after_restart"] = health_after or "NOT_200_WITHIN_180S"

ev["services_after"] = run("systemctl is-active agentic nginx searxng search-api", 20, "services after")
ev["journal_err"] = run("sudo -n journalctl -u agentic -p err --since '-5 minutes' --no-pager | tail -8", 30, "journal errors")
ev["asset_version"] = run(
    "curl -s -m 8 -u \"$HTUSER:$HTPASS\" http://127.0.0.1:8010/ -o /dev/null -w '%{http_code}'; "
    "sudo -n grep -o 'asset_version[^,]*' /opt/agentic-engineering-system/runtime/*.log 2>/dev/null | tail -2; "
    "cd /opt/agentic-engineering-system && sudo -n git log --oneline -1", 30, "asset/version check")

with open(os.path.join(EVDIR, "deploy.json"), "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=1)

print("HEAD:", ev["head_after_pull"]["out"])
print("health_after:", ev["health_after_restart"])
print("services_after:", ev["services_after"]["out"].replace("\n", " | "))
print("journal_err:", repr(ev["journal_err"]["out"][:200]))
print("compile:", ev["py_compile"]["out"])
ssh.close()
print("EVIDENCE:", os.path.join(EVDIR, "deploy.json"))
