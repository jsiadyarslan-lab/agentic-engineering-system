#!/usr/bin/env python3
# W2-T20 step 2 (fix 2): disable tracker_url_remover plugin (SQLite 3.34 < 3.35
# UPSERT syntax crash in searx.cache), restart, verify JSON API.
import json, time, paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

ev = {"_meta": {"task": "W2-T20 step 2 fix2: disable tracker_url_remover",
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

# append plugin deactivation to settings.yml
ev["settings_patch"] = run(
    "sudo -n tee -a /etc/searxng/settings.yml > /dev/null <<'YEOF'\n"
    "plugins:\n"
    "  searx.plugins.tracker_url_remover.SXNGPlugin:\n"
    "    active: false\n"
    "YEOF\n"
    "sudo -n tail -5 /etc/searxng/settings.yml",
    20, "append plugins block")

# restart
ev["restart"] = run(
    "sudo -n systemctl restart searxng; sleep 7; sudo -n systemctl is-active searxng; "
    "sudo -n systemctl show searxng -p NRestarts | tail -1", 60, "restart searxng")

# JSON search test (English)
ev["json_search_test"] = run(
    "curl -s -o /tmp/searx_test.json -w 'HTTP %{http_code} in %{time_total}s' "
    "--max-time 30 'http://127.0.0.1:8888/search?q=open+source+python&format=json&language=en'; "
    "echo; python3 -c \"import json;d=json.load(open('/tmp/searx_test.json'));"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70]);"
    "print('unresponsive:',str(d.get('unresponsive_engines',[]))[:220])\" 2>&1 | head -6",
    60, "JSON API search test")

# Arabic query test (the model's language)
ev["json_search_arabic"] = run(
    "curl -s -o /tmp/searx_ar.json -w 'HTTP %{http_code} in %{time_total}s' "
    "--max-time 30 'http://127.0.0.1:8888/search?q=%D9%87%D9%8A%D9%83%D9%84+%D9%85%D9%88%D9%82%D8%B9+%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1&format=json&language=ar'; "
    "echo; python3 -c \"import json;d=json.load(open('/tmp/searx_ar.json'));"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70])\" 2>&1 | head -4",
    60, "Arabic JSON search test")

# long natural query — same failing shape as tool_invocations #207
ev["json_search_long"] = run(
    "curl -s -o /tmp/searx_long.json -w 'HTTP %{http_code} in %{time_total}s' "
    "--max-time 30 'http://127.0.0.1:8888/search?q=news+website+page+structure+homepage+world+politics+business+technology+sports+entertainment+article+detail+search+results+best+practices&format=json&language=en'; "
    "echo; python3 -c \"import json;d=json.load(open('/tmp/searx_long.json'));"
    "print('results:',len(d.get('results',[])));"
    "print('first:',(d.get('results') or [{}])[0].get('title','')[:70]);"
    "print('second:',(d.get('results') or [{}])[1].get('title','')[:70] if len(d.get('results',[]))>1 else '')\" 2>&1 | head -6",
    60, "long query JSON search test")

ev["health_after"] = health()

path = "/home/z/my-project/download/aes-remediation/W2-T20/step2_fix2_plugin_off.json"
with open(path, "w") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)
print(json.dumps(ev, ensure_ascii=False, indent=2))
ssh.close()
