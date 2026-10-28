#!/usr/bin/env python3
# W2-T20 step 3: deploy Search API service (127.0.0.1:8098) + systemd + key.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 step 3: deploy Search API service",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:2200],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

ev["health_before"] = health()
assert ev["health_before"] == "200", f"R6 FAIL before: {ev['health_before']}"

# (0) read the service source from local disk and upload via SFTP
sftp = ssh.open_sftp()
sftp.put("/home/z/my-project/scripts/search_api_service.py", "/tmp/search_api.py")
sftp.close()
ev["upload"] = {"rc": 0, "out": "SFTP uploaded /tmp/search_api.py"}

# (1) system user
ev["useradd"] = run(
    "sudo -n id searchapi >/dev/null 2>&1 && echo EXISTS || "
    "sudo -n useradd --system --home-dir /opt/search-api --shell /sbin/nologin searchapi && echo CREATED",
    20, "useradd searchapi")

# (2) install dir + file
ev["install"] = run(
    "sudo -n mkdir -p /opt/search-api && sudo -n mv /tmp/search_api.py /opt/search-api/search_api.py && "
    "sudo -n chown -R searchapi:searchapi /opt/search-api && "
    "sudo -n chmod 750 /opt/search-api && sudo -n chmod 640 /opt/search-api/search_api.py && "
    "echo INSTALLED && sudo -n wc -l /opt/search-api/search_api.py", 20, "install service file")

# (3) key + env file
apikey = run("openssl rand -hex 24", 15, "gen api key")["out"]
assert len(apikey) == 48, f"key gen failed: {apikey!r}"
ev["key_len"] = len(apikey)
ev["env_write"] = run(
    "sudo -n mkdir -p /etc/search-api && "
    "sudo -n bash -c 'cat > /etc/search-api/env <<EOF\n"
    f"SEARCH_API_KEY={apikey}\n"
    "SEARX_BASE_URL=http://127.0.0.1:8888\n"
    "SEARCH_API_PORT=8098\n"
    "EOF' && "
    "sudo -n chown root:searchapi /etc/search-api/env && sudo -n chmod 640 /etc/search-api/env && "
    "echo ENV_WRITTEN", 20, "write env file")

# (4) systemd unit
UNIT = """[Unit]
Description=Search API (owner-owned JSON endpoint over local SearXNG)
After=network.target searxng.service
Wants=searxng.service

[Service]
Type=simple
User=searchapi
Group=searchapi
EnvironmentFile=/etc/search-api/env
ExecStart=/usr/bin/python3.12 /opt/search-api/search_api.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
PrivateDevices=true

[Install]
WantedBy=multi-user.target
"""
ev["unit_write"] = run(
    "sudo -n tee /etc/systemd/system/search-api.service > /dev/null <<'UEOF'\n" + UNIT + "UEOF\n"
    "sudo -n systemctl daemon-reload && echo UNIT_INSTALLED", 20, "install unit")

# (5) start + verify
ev["start"] = run(
    "sudo -n systemctl enable --now search-api 2>&1 | tail -1; sleep 3; "
    "sudo -n systemctl is-active search-api", 40, "start search-api")

ev["healthz"] = run(
    "curl -s --max-time 10 http://127.0.0.1:8098/healthz", 20, "GET /healthz")

ev["auth_reject"] = run(
    "curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "
    "http://127.0.0.1:8098/search -H 'Content-Type: application/json' "
    "-d '{\"query\":\"test\"}'", 20, "POST without key (expect 401)")

# POST with key — exact failing query #207 (same shape ApiSearchProvider sends)
q207 = ("news website page structure homepage world politics business "
        "technology sports entertainment article detail search results "
        "best practices")
ev["auth_ok_207"] = run(
    "curl -s --max-time 25 -X POST http://127.0.0.1:8098/search "
    "-H 'Content-Type: application/json' -H 'X-API-Key: " + apikey + "' "
    "-d '{\"query\": \"" + q207 + "\", \"max_results\": 8}' | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70]);"
    "print('second:',(d.get('results') or [{}])[1].get('title','')[:70] if len(d.get('results',[]))>1 else '')\"",
    40, "POST #207 query with key")

# Arabic query through the API
ev["auth_ok_arabic"] = run(
    "curl -s --max-time 25 -X POST http://127.0.0.1:8098/search "
    "-H 'Content-Type: application/json' -H 'X-API-Key: " + apikey + "' "
    "-d '{\"query\": \"هيكل موقع أخبار\", \"max_results\": 6}' | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70])\"",
    40, "POST arabic query with key")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/step3_search_api_deploy.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
# نحفظ المفتاح في ملف منفصل محليًا (لا يُرفع للمستودع أبدًا)
with open("/home/z/my-project/download/aes-remediation/W2-T20/.search_api_key.local", "w") as f:
    f.write(apikey + "\n")
print(json.dumps(ev, ensure_ascii=False, indent=2))
print("API_KEY saved locally (not for repo):", apikey[:6] + "..." + apikey[-4:])
ssh.close()
