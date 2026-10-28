#!/usr/bin/env python3
# W2-T20 step 2 (fix): uwsgi wheel failed -> switch to gunicorn (pure python).
# Stop service, install requirements alone, install gunicorn, update unit, verify.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 step 2 fix: gunicorn instead of uwsgi",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:1600],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

ev["health_before"] = health()
assert ev["health_before"] == "200", f"R6 FAIL before: {ev['health_before']}"

# ---- (1) stop the restart loop -----------------------------------------
ev["stop"] = run("sudo -n systemctl stop searxng; sudo -n systemctl is-active searxng || true", 30, "stop searxng")

# ---- (2) install requirements alone ------------------------------------
ev["pip_req"] = run(
    "sudo -n /opt/searxng/searxngenv/bin/pip install --quiet --no-input "
    "-r /opt/searxng/requirements.txt 2>&1 | tail -4; echo RC=$?",
    540, "pip install requirements")

# ---- (3) install gunicorn (pure python) ---------------------------------
ev["pip_gunicorn"] = run(
    "sudo -n /opt/searxng/searxngenv/bin/pip install --quiet gunicorn 2>&1 | tail -2; "
    "sudo -n /opt/searxng/searxngenv/bin/pip list 2>/dev/null | grep -iE '^(flask|httpx|gunicorn|babel|pygments)' ",
    240, "pip install gunicorn")

# ---- (4) update systemd unit to gunicorn --------------------------------
UNIT = """[Unit]
Description=SearXNG metasearch (private instance for agentic research)
After=network.target

[Service]
Type=simple
User=searxng
Group=searxng
WorkingDirectory=/opt/searxng
Environment=SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml
ExecStart=/opt/searxng/searxngenv/bin/gunicorn --bind 127.0.0.1:8888 --workers 2 --threads 4 --timeout 30 --graceful-timeout 10 --access-logfile - --error-logfile - searx.webapp:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/opt/searxng
PrivateDevices=true

[Install]
WantedBy=multi-user.target
"""
ev["unit_update"] = run(
    "sudo -n tee /etc/systemd/system/searxng.service > /dev/null <<'UEOF'\n" + UNIT + "UEOF\n"
    "sudo -n systemctl daemon-reload && echo UNIT_UPDATED",
    20, "update unit -> gunicorn")

# ---- (5) start + verify ---------------------------------------------------
ev["start"] = run(
    "sudo -n systemctl start searxng; sleep 6; sudo -n systemctl is-active searxng",
    60, "start searxng")

ev["json_search_test"] = run(
    "curl -s -o /tmp/searx_test.json -w 'HTTP %{http_code} in %{time_total}s' "
    "--max-time 30 'http://127.0.0.1:8888/search?q=open+source+python&format=json&language=en'; "
    "echo; python3 -c \"import json;d=json.load(open('/tmp/searx_test.json'));"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70]);"
    "print('unresponsive:',[e[0] if isinstance(e,tuple) else e for e in d.get('unresponsive_engines',[])][:8])\" 2>&1 | head -6",
    60, "JSON API search test")

ev["service_uptime"] = run(
    "sudo -n systemctl show searxng -p ActiveEnterTimestamp -p MainPID -p NRestarts | tr '\\n' ' '", 15, "uptime")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/step2_fix_gunicorn.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
