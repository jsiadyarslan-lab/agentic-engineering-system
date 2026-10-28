#!/usr/bin/env python3
# W2-T20 step 2 (fix 3): pysqlite3-binary shim -> modern SQLite for python3.12
# (system sqlite 3.34.1 < 3.35 required by searx.cache UPSERT).
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 step 2 fix3: pysqlite3 shim",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

def run(cmd, t=90, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:110], "rc": rc, "out": out.strip()[:2000],
            "err": err.strip()[:400]}

def health():
    return run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 "
               "http://127.0.0.1:8010/health", 15, "health")["out"]

ev["health_before"] = health()
assert ev["health_before"] == "200", f"R6 FAIL before: {ev['health_before']}"

# (1) install pysqlite3-binary
ev["pip_pysqlite3"] = run(
    "sudo -n /opt/searxng/searxngenv/bin/pip install --quiet pysqlite3-binary 2>&1 | tail -2; "
    "sudo -n /opt/searxng/searxngenv/bin/python -c \"import pysqlite3; print('sqlite:', pysqlite3.sqlite_version)\"",
    240, "pip install pysqlite3-binary")

# (2) shim module
SHIM = '''"""W2-T20: shim — use bundled modern SQLite before importing searx.

system sqlite (3.34.1) < 3.35 required by searx.cache (UPSERT syntax).
pysqlite3-binary bundles a modern SQLite; swapping sys.modules before
searx imports gives every searx module the new library.
"""
import sys

import pysqlite3  # noqa: E402

sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")

from searx.webapp import app  # noqa: E402,F401
'''
ev["shim_write"] = run(
    "sudo -n tee /opt/searxng/pysqlite3_shim.py > /dev/null <<'SEOF'\n" + SHIM + "SEOF\n"
    "sudo -n chown searxng:searxng /opt/searxng/pysqlite3_shim.py && echo SHIM_WRITTEN",
    20, "write shim")

# (3) update unit -> shim module
ev["unit_patch"] = run(
    "sudo -n sed -i 's|searx.webapp:app|pysqlite3_shim:app|' /etc/systemd/system/searxng.service && "
    "sudo -n systemctl daemon-reload && grep ExecStart /etc/systemd/system/searxng.service",
    20, "patch unit ExecStart")

# (4) restart + verify
ev["restart"] = run(
    "sudo -n systemctl restart searxng; sleep 8; sudo -n systemctl is-active searxng; "
    "sudo -n systemctl show searxng -p NRestarts | tail -1", 60, "restart searxng")

ev["json_search_test"] = run(
    "curl -s -o /tmp/searx_test.json -w 'HTTP %{http_code} in %{time_total}s' "
    "--max-time 30 'http://127.0.0.1:8888/search?q=open+source+python&format=json&language=en'; "
    "echo; python3 -c \"import json;d=json.load(open('/tmp/searx_test.json'));"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70]);"
    "print('unresponsive:',str(d.get('unresponsive_engines',[]))[:250])\" 2>&1 | head -6",
    60, "JSON search test (english)")

ev["json_search_arabic"] = run(
    "curl -s -o /tmp/searx_ar.json -w 'HTTP %{http_code} in %{time_total}s' "
    "--max-time 30 'http://127.0.0.1:8888/search?q=%D9%87%D9%8A%D9%83%D9%84+%D9%85%D9%88%D9%82%D8%B9+%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1&format=json&language=ar'; "
    "echo; python3 -c \"import json;d=json.load(open('/tmp/searx_ar.json'));"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70])\" 2>&1 | head -4",
    60, "JSON search test (arabic)")

ev["json_search_long"] = run(
    "curl -s -o /tmp/searx_long.json -w 'HTTP %{http_code} in %{time_total}s' "
    "--max-time 30 'http://127.0.0.1:8888/search?q=news+website+page+structure+homepage+world+politics+business+technology+sports+entertainment+article+detail+search+results+best+practices&format=json&language=en'; "
    "echo; python3 -c \"import json;d=json.load(open('/tmp/searx_long.json'));"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70]);"
    "print('second:',(d.get('results') or [{}])[1].get('title','')[:70] if len(d.get('results',[]))>1 else '')\" 2>&1 | head -6",
    60, "JSON search test (long #207 shape)")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/step2_fix3_pysqlite3.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
