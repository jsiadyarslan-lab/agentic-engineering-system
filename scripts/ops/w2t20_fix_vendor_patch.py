#!/usr/bin/env python3
# W2-T20 step 2 (fix 4): vendor patch tracker_patterns.py -> graceful degrade
# on old system SQLite; revert ExecStart to searx.webapp:app; restart + test.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 step 2 fix4: vendor patch tracker_patterns",
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

PATCH_CMD = r'''sudo -n python3 - <<'PEOF'
path = "/opt/searxng/searx/data/tracker_patterns.py"
src = open(path).read()
old = """    def init(self):
        if self.cache.properties("tracker_patterns loaded") != "OK":
            # To avoid parallel initializations, the property is set first
            self.cache.properties.set("tracker_patterns loaded", "OK")
            self.load()
"""
new = """    def init(self):
        if self.cache.properties("tracker_patterns loaded") != "OK":
            # To avoid parallel initializations, the property is set first
            self.cache.properties.set("tracker_patterns loaded", "OK")
            # W2-T20 vendor patch 2026-10-28: system SQLite 3.34.1 (< 3.35)
            # cannot run the UPSERT inside cache.setmany; degrade gracefully
            # to an empty rule set instead of crashing the worker at boot.
            try:
                self.load()
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "TRACKER_PATTERNS disabled on old SQLite: %s", exc)
"""
assert old in src, "anchor not found"
open(path, "w").write(src.replace(old, new, 1))
print("PATCHED")
PEOF'''

ev["vendor_patch"] = run(PATCH_CMD, 30, "patch tracker_patterns.py")

# backup for rollback
ev["backup"] = run(
    "sudo -n cp /opt/searxng/searx/data/tracker_patterns.py "
    "/opt/searxng/searx/data/tracker_patterns.py.pre-w2t20 && echo BACKED_UP", 15, "backup")

# revert ExecStart to canonical module
ev["unit_revert"] = run(
    "sudo -n sed -i 's|pysqlite3_shim:app|searx.webapp:app|' /etc/systemd/system/searxng.service && "
    "sudo -n rm -f /opt/searxng/pysqlite3_shim.py && "
    "sudo -n systemctl daemon-reload && grep ExecStart /etc/systemd/system/searxng.service",
    20, "revert ExecStart")

# restart + verify
ev["restart"] = run(
    "sudo -n systemctl restart searxng; sleep 8; sudo -n systemctl is-active searxng",
    60, "restart searxng")

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

path = "/home/z/my-project/download/aes-remediation/W2-T20/step2_fix4_vendor_patch.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
