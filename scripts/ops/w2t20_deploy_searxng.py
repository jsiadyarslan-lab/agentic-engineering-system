#!/usr/bin/env python3
# W2-T20 step 2: deploy SearXNG from source on production (no docker/podman).
# R6 gates around every mutation. Evidence -> download/aes-remediation/W2-T20/
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 step 2: deploy SearXNG",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:1500],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

ev["health_before"] = health()
assert ev["health_before"] == "200", f"R6 FAIL before: {ev['health_before']}"

# ---- (1) system user -------------------------------------------------
ev["useradd"] = run(
    "sudo -n id searxng >/dev/null 2>&1 && echo EXISTS || "
    "sudo -n useradd --system --home-dir /opt/searxng --shell /sbin/nologin searxng && echo CREATED",
    20, "useradd searxng")

# ---- (2) clone (shallow) ----------------------------------------------
ev["clone"] = run(
    "test -d /opt/searxng/.git && echo ALREADY || "
    "sudo -n git clone --depth 1 https://github.com/searxng/searxng /opt/searxng 2>&1 | tail -2",
    300, "git clone searxng")

# ---- (3) python requirement check --------------------------------------
ev["pyproject_python"] = run(
    "sudo -n grep -E 'requires-python' /opt/searxng/pyproject.toml || echo 'no requires-python'",
    15, "requires-python")

# ---- (4) venv + deps ---------------------------------------------------
ev["venv"] = run(
    "test -x /opt/searxng/searxngenv/bin/python && echo VENV_EXISTS || "
    "sudo -n python3.12 -m venv /opt/searxng/searxngenv && echo VENV_CREATED",
    120, "create venv (py3.12)")

ev["pip_install"] = run(
    "sudo -n /opt/searxng/searxngenv/bin/pip install --quiet --no-input "
    "-r /opt/searxng/requirements.txt uwsgi 2>&1 | tail -5; "
    "sudo -n /opt/searxng/searxngenv/bin/pip list 2>/dev/null | grep -iE 'flask|httpx|uwsgi|searx' | head -8",
    540, "pip install requirements + uwsgi")

# ---- (5) settings.yml ---------------------------------------------------
secret = run("openssl rand -hex 32", 15, "gen secret key")["out"]
assert len(secret) == 64, f"secret generation failed: {secret!r}"
ev["secret_len"] = len(secret)

SETTINGS = """use_default_settings: true
server:
  secret_key: "%SECRET%"
  bind_address: "127.0.0.1"
  port: 8888
  limiter: false
  public_instance: false
  image_proxy: false
search:
  formats:
    - html
    - json
  autocomplete: ""
outgoing:
  request_timeout: 6.0
  max_request_timeout: 8.0
"""
ev["settings_write"] = run(
    "sudo -n mkdir -p /etc/searxng && sudo -n tee /etc/searxng/settings.yml > /dev/null <<'YEOF'\n"
    + SETTINGS.replace("%SECRET%", secret) + "YEOF\n"
    "sudo -n chown root:searxng /etc/searxng/settings.yml && sudo -n chmod 640 /etc/searxng/settings.yml && "
    "echo SETTINGS_WRITTEN && sudo -n grep -c 'format' /etc/searxng/settings.yml",
    20, "write settings.yml")

# ---- (6) permissions ----------------------------------------------------
ev["chown"] = run(
    "sudo -n chown -R searxng:searxng /opt/searxng && echo CHOWNED",
    60, "chown /opt/searxng")

# ---- (7) systemd unit ----------------------------------------------------
UNIT = """[Unit]
Description=SearXNG metasearch (private instance for agentic research)
After=network.target

[Service]
Type=simple
User=searxng
Group=searxng
WorkingDirectory=/opt/searxng
Environment=SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml
ExecStart=/opt/searxng/searxngenv/bin/uwsgi --http-socket 127.0.0.1:8888 --module searx.webapp:app --master --processes 2 --threads 4 --enable-threads --die-on-term --buffer-size=8192
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
ev["unit_write"] = run(
    "sudo -n tee /etc/systemd/system/searxng.service > /dev/null <<'UEOF'\n" + UNIT + "UEOF\n"
    "sudo -n systemctl daemon-reload && echo UNIT_INSTALLED",
    20, "install systemd unit")

# ---- (8) start + verify ---------------------------------------------------
ev["start"] = run(
    "sudo -n systemctl enable --now searxng 2>&1 | tail -1; sleep 4; "
    "sudo -n systemctl is-active searxng",
    60, "enable + start searxng")

ev["json_search_test"] = run(
    "sleep 3; curl -s -o /tmp/searx_test.json -w 'HTTP %{http_code} in %{time_total}s' "
    "--max-time 25 'http://127.0.0.1:8888/search?q=open+source+python&format=json&language=en'; "
    "echo; python3 -c \"import json;d=json.load(open('/tmp/searx_test.json'));"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70]);"
    "print('unresponsive:',d.get('unresponsive_engines',[])[:6])\" 2>&1 | head -5",
    60, "JSON API search test")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/step2_searxng_deploy.json"
import os
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
