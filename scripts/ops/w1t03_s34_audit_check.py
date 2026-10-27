#!/usr/bin/env python3
"""W1-T03-S34-AUDIT — independent audit of W1-T03 steps 3-4 (owner monitoring step + executor documentation step).

Discipline:
  - Production is strictly READ-ONLY over SSH (tail/grep/systemctl is-active/curl-status only).
  - External checks: GET requests only, issued from THIS environment (not owner, not server).
  - Token discipline: the full token is NEVER printed nor written — masked as <TOKEN>; prefix 5e140aa0 only.
  - Evaluation is based on actual output lines/values, never on exit codes (W1-T02 lesson).

Evidence -> download/aes-remediation/W1-T03/audit_s34_independent.json
"""
import concurrent.futures
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"
ROOT = "/home/z/my-project"
EV = os.path.join(ROOT, "download", "aes-remediation", "W1-T03")
TOKEN_FILE = os.path.join(EV, "owner-token.txt")
NOTIF = os.path.join(EV, "20261027-owner-notification.txt")
LIVE_JSON = os.path.join(EV, "20261027-monitor-live.json")
VERIFY_SCRIPT = os.path.join(ROOT, "scripts", "w1t03_monitor_verify.py")
TRACKER = os.path.join(ROOT, "TRACKER.md")
WORKLOG = os.path.join(ROOT, "worklog.md")
OUT_JSON = os.path.join(EV, "audit_s34_independent.json")
OWNER_IP = "2.215.157.88"
SERVER_IP = HOST
MY_UA = "W1-T03-S34-AUDIT/1.0 (independent audit of steps 3-4)"
EXEC_VERIFY_TS = datetime(2026, 10, 27, 4, 2, 27, tzinfo=timezone.utc)  # executor's verify timestamp

with open(TOKEN_FILE) as f:
    TOKEN = f.read().strip()
TOKEN_PREFIX = TOKEN[:8]


def mask(s):
    return str(s).replace(TOKEN, "<TOKEN>")


CHECKS = []


def add_check(cid, desc, expected, actual, ok, blocking=True, note=None):
    rec = {
        "id": cid,
        "desc": desc,
        "expected": mask(expected),
        "actual": mask(actual),
        "pass": bool(ok),
        "blocking": bool(blocking),
    }
    if note:
        rec["note"] = mask(note)
    CHECKS.append(rec)
    flag = "PASS" if ok else "FAIL"
    star = "" if ok or not blocking else " (BLOCKING)"
    print(f"[{flag}{star}] {cid} :: {desc}")
    print(f"    expected: {mask(expected)}")
    print(f"    actual  : {mask(actual)}")
    if note:
        print(f"    note    : {mask(note)}")


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# =====================================================================
# 1) EXTERNAL LIVE PROBES (GET only, from this environment)
# =====================================================================
section("1) External live probes from THIS environment (GET only)")


def probe(url):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": MY_UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(400).decode("utf-8", "replace"), r.headers.get("Server", "")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(400).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body, e.headers.get("Server", "") if e.headers else ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", ""


code, body, srv = probe(f"http://{HOST}/healthz-{TOKEN}")
try:
    jbody = json.loads(body)
    status_ok = isinstance(jbody, dict) and jbody.get("status") == "ok"
    body_snip = json.dumps({k: jbody[k] for k in list(jbody)[:3]})[:160] if isinstance(jbody, dict) else body[:120]
except Exception:
    status_ok = False
    body_snip = body[:120]
add_check("ext_secret_200", "GET /healthz-<TOKEN> from this env (not owner, not server)",
          "200 + JSON with status=ok", f"{code} | body~{body_snip}",
          code == 200 and status_ok)

code_root, body_root, _ = probe(f"http://{HOST}/")
add_check("ext_root_403", "GET / from this env", "403", f"{code_root} | {body_root[:60]!r}", code_root == 403)

code_wrong, body_wrong, _ = probe(f"http://{HOST}/healthz-{'0' * 32}")
add_check("ext_wrongtoken_403", "GET /healthz-<32 zero hex> from this env", "403",
          f"{code_wrong} | {body_wrong[:60]!r}", code_wrong == 403)

# =====================================================================
# 2) SSH read-only: nginx access log analysis (the core evidence)
# =====================================================================
section("2) SSH read-only: nginx access.log analysis (monitor polling evidence)")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)


def run(cmd, timeout=90):
    _, so, se = ssh.exec_command(cmd, timeout=timeout)
    out = so.read().decode("utf-8", "replace")
    err = se.read().decode("utf-8", "replace")
    return out, err


server_now = run("date -u '+%Y-%m-%d %H:%M:%S UTC'")[0].strip()
print(f"server clock: {server_now}")

log3000, err0 = run("sudo -n tail -n 3000 /var/log/nginx/access.log")
count1000 = run("sudo -n tail -n 1000 /var/log/nginx/access.log | grep -c healthz || true")[0].strip()

LINE_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+)(?: (?P<proto>[^"]*))?" '
    r'(?P<status>\d{3}) (?P<bytes>\S+)(?: "(?P<ref>[^"]*)" "(?P<ua>[^"]*)")?'
)


def parse_log(text):
    recs = []
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        d = m.groupdict()
        try:
            ts = datetime.strptime(d["ts"], "%d/%b/%Y:%H:%M:%S %z")
        except Exception:
            continue
        ua = (d.get("ua") or "").replace("\\x22", '"')
        recs.append({"ip": d["ip"], "ts": ts, "method": d["method"], "path": d["path"],
                     "status": int(d["status"]), "ua": ua, "ref": d.get("ref") or "", "raw": line})
    return recs


def classify(rec):
    ip, ua = rec["ip"], rec["ua"].lower()
    if ip == "127.0.0.1":
        return "loopback"
    if ip == OWNER_IP:
        return "owner"
    if ip == SERVER_IP:
        return "server"
    if "uptimerobot" in ua:
        return "provider_monitor"
    if ("w1-t03-audit" in ua or "python-urllib" in ua or "python-requests" in ua
            or ua.startswith("curl/") or "w1-t03-s34" in ua):
        return "env_tooling"
    return "other"


recs = parse_log(log3000)
print(f"parsed log lines: {len(recs)} (from tail -n 3000; stderr={err0.strip()!r})")

hz = [r for r in recs if r["path"].startswith("/healthz-")]
exact = [r for r in hz if r["path"] == f"/healthz-{TOKEN}"]
for r in hz:
    r["cls"] = classify(r)

env_ips = sorted({r["ip"] for r in hz if r["cls"] == "env_tooling"})
my_probe_ips = sorted({r["ip"] for r in hz if MY_UA in r["ua"]})
provider = sorted([r for r in exact if r["cls"] == "provider_monitor"], key=lambda r: r["ts"])
other_hz = [r for r in hz if r["cls"] == "other"]
owner_hz = [r for r in hz if r["cls"] == "owner"]
loop_hz = [r for r in hz if r["cls"] == "loopback"]

print(f"healthz-* requests in window: {len(hz)} | exact secret path: {len(exact)}")
print(f"class counts: provider_monitor={len(provider)} env_tooling={sum(1 for r in hz if r['cls']=='env_tooling')} "
      f"loopback={len(loop_hz)} owner={len(owner_hz)} other={len(other_hz)}")
print(f"env_tooling IPs (this execution env egress): {env_ips}")
print(f"this audit's probe IPs: {my_probe_ips}")

add_check("my_probes_external", "this audit's probes originate from an IP that is not owner/server/loopback",
          "probe IP not in {owner, server, 127.0.0.1}", my_probe_ips,
          bool(my_probe_ips) and not ({OWNER_IP, SERVER_IP, "127.0.0.1"} & set(my_probe_ips)))

# (a) requests to the secret from external IPs that are not owner/server/loopback/env
provider_ips = sorted({r["ip"] for r in provider})
ext_ok = bool(provider) and not (set(provider_ips) & ({OWNER_IP, SERVER_IP, "127.0.0.1"} | set(env_ips)))
add_check("monitor_polls_external", "provider-UA requests hit /healthz-<TOKEN> from IPs that are NOT owner/server/loopback/execution-env",
          ">=1 external provider IP, disjoint from owner/server/127.0.0.1/env",
          f"{len(provider)} polls from {len(provider_ips)} IPs: {provider_ips}",
          ext_ok and len(provider_ips) >= 1)

# (b) their GET responses are 200
gets = [r for r in provider if r["method"] == "GET"]
heads = [r for r in provider if r["method"] == "HEAD"]
get_200 = all(r["status"] == 200 for r in gets) and len(gets) >= 1
head_dist = {}
for r in heads:
    head_dist[r["status"]] = head_dist.get(r["status"], 0) + 1
add_check("monitor_get_200", "ALL provider GET polls on the secret returned 200",
          "every GET = 200 (>=1 GET)", f"GETs={len(gets)}, statuses={sorted({r['status'] for r in gets})}; HEADs={len(heads)}, statuses={head_dist}",
          get_200,
          note=("provider alternates HEAD then GET ~13-15s later per cycle (HEAD -> 405 because the app /health "
                "answers GET only; provider falls back to GET -> 200 and reports monitor UP per its own notification)"))

# (c) polling intervals — regular periodic cadence
cycle_deltas = []
for a, b in zip(provider, provider[1:]):
    d = (b["ts"] - a["ts"]).total_seconds()
    if d >= 60:  # cycle boundary (HEAD->GET pair gap is 13-15s)
        cycle_deltas.append(round(d, 1))
median_delta = sorted(cycle_deltas)[len(cycle_deltas) // 2] if cycle_deltas else None
regular = len(cycle_deltas) >= 2 and 240 <= median_delta <= 420 and (max(cycle_deltas) - min(cycle_deltas)) <= 120
add_check("monitor_interval_regular", "consecutive poll cycles show a regular periodic cadence",
          ">=2 cycle gaps, median within 240-420s, spread <=120s",
          f"cycle gaps(s)={cycle_deltas} median={median_delta}",
          regular)

# ongoing polling beyond the executor's measurement window (04:02:27)
after_exec = [r for r in provider if r["ts"] > EXEC_VERIFY_TS]
add_check("monitor_ongoing_after_executor", "provider polls continued AFTER executor's verify timestamp 04:02:27",
          ">=1 provider poll with ts > 04:02:27",
          f"{len(after_exec)} polls: {[r['ts'].strftime('%H:%M:%S') + ' ' + r['ip'] for r in after_exec]}",
          len(after_exec) >= 1)

# live second read: catch a poll that appears AFTER my first read (proves polling is alive right now)
newest = provider[-1]["ts"] if provider else None
server_now_dt = datetime.strptime(server_now, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
if newest:
    wait = (newest.timestamp() + 340) - server_now_dt.timestamp()
    wait = max(30.0, min(wait, 330.0))
    print(f"newest provider poll: {newest} -> waiting {round(wait)}s for a fresh poll, then re-reading the log...")
    time.sleep(wait)
    log2 = run("sudo -n tail -n 800 /var/log/nginx/access.log")[0]
    recs2 = parse_log(log2)
    hz2 = [r for r in recs2 if r["path"] == f"/healthz-{TOKEN}"]
    for r in hz2:
        r["cls"] = classify(r)
    prov2 = sorted([r for r in hz2 if r["cls"] == "provider_monitor"], key=lambda r: r["ts"])
    newer = [r for r in prov2 if (not newest) or r["ts"] > newest]
    add_check("monitor_live_second_read", "a NEW provider poll appeared after my first log read (polling alive NOW)",
              ">=1 new provider poll in second read",
              f"new polls: {[r['ts'].strftime('%H:%M:%S') + ' ' + r['ip'] + ' ' + r['method'] + ' ' + str(r['status']) for r in newer]}",
              len(newer) >= 1)
    provider_all = provider + [r for r in newer]
    newest_final = max(r["ts"] for r in provider_all)
    age_final = (datetime.now(timezone.utc) - newest_final).total_seconds()
    add_check("monitor_freshness", "newest provider poll is within the last ~6 minutes",
              "age <= 360s", f"newest={newest_final.strftime('%H:%M:%S')} age={round(age_final)}s",
              age_final <= 360)
else:
    add_check("monitor_live_second_read", "a NEW provider poll appeared after my first log read", ">=1", "no provider polls at all", False)

# (d) count comparison with executor's claim (18 in last 1000 lines at his measurement time)
last1000_recs = parse_log("\n".join(log3000.splitlines()[-1000:]))
prov_in_last1000 = [r for r in last1000_recs if r["path"] == f"/healthz-{TOKEN}" and "uptimerobot" in r["ua"].lower()]
add_check("count_vs_executor", "healthz count in last 1000 lines now vs executor's 18 (pattern is what matters)",
          "count>0 with provider polls present in the window (number may shift with time)",
          f"mine now={count1000} (executor=18 at 04:02:27); provider-UA polls inside my last-1000 window={len(prov_in_last1000)}",
          count1000.isdigit() and int(count1000) > 0 and len(prov_in_last1000) >= 2)

# =====================================================================
# 3) Production health (read-only)
# =====================================================================
section("3) Production health (SSH read-only)")
services = [l for l in run("systemctl is-active agentic nginx firewalld")[0].splitlines() if l.strip()]
health8010 = run("curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")[0].strip()
add_check("services_active", "agentic, nginx, firewalld all active", "3x active", services,
          services == ["active", "active", "active"])
add_check("app_health_direct_200", "direct 8010/health status", "200", health8010, health8010 == "200")

# PTR lookups for provider IPs (informational, best effort)
def ptr(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return "n/a"


with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    ptr_map = {ip: ex.submit(ptr, ip) for ip in provider_ips}
    ptr_results = {ip: f.result() for ip, f in ptr_map.items()}
print(f"provider IP PTR records: {ptr_results}")

# =====================================================================
# 4) Executor evidence integrity (local files)
# =====================================================================
section("4) Executor evidence integrity")

# (a) owner notification archive
notif_exists = os.path.isfile(NOTIF)
notif_txt = open(NOTIF, encoding="utf-8").read() if notif_exists else ""
notif_checks = {
    "exists": notif_exists,
    "url_prefix": f"/healthz-{TOKEN_PREFIX}" in notif_txt,
    "resolved_at": "Resolved at: 2026-10-27 03:51:08" in notif_txt,
    "region_europe": "Region: Europe" in notif_txt,
    "monitor_name": "Monitor name: 92.5.14.150" in notif_txt,
    "up_again": "your monitor is up again in Europe" in notif_txt,
}
add_check("notification_content", "owner notification archive matches the claimed provider email",
          "exists + URL with token prefix 5e140aa0 + Resolved 2026-10-27 03:51:08 + Region Europe + monitor 92.5.14.150 + 'up again'",
          notif_checks, all(notif_checks.values()))

# (b) monitor-live.json consistency with the executor's claims
live_exists = os.path.isfile(LIVE_JSON)
live = json.load(open(LIVE_JSON, encoding="utf-8")) if live_exists else {}
lc = live.get("checks", {})
live_consistent = {
    "verdict_pass": live.get("verdict") == "PASS",
    "secret_200": lc.get("external_secret_200", {}).get("code") == 200,
    "secret_body_ok": '"status":"ok"' in lc.get("external_secret_200", {}).get("body_head", ""),
    "root_403": lc.get("external_root_403", {}).get("code") == 403,
    "wrongtoken_403": lc.get("external_wrongtoken_403", {}).get("code") == 403,
    "services_3_active": lc.get("services") == ["active", "active", "active"],
    "app_health_200": lc.get("app_health_direct") == "200",
    "count_18": lc.get("access_log_healthz_count_last1000") == "18",
    "source_ips_present": isinstance(lc.get("healthz_source_ips"), list) and len(lc["healthz_source_ips"]) >= 5,
}
add_check("monitor_live_consistent", "20261027-monitor-live.json fields consistent with executor's claims",
          "verdict=PASS + ext 200/403/403 + 3xactive + health 200 + count 18 + source ips",
          live_consistent, all(live_consistent.values()))

# misattribution analysis: which of the executor's claimed "monitor checker" IPs are actually provider IPs?
claimed_monitor_ips = ["88.99.80.227", "47.57.232.232", "8.212.10.159", "47.57.242.119"]
env_evidence_lines = []
for r in hz:
    if r["ip"] in claimed_monitor_ips and r["cls"] == "env_tooling":
        env_evidence_lines.append(f"{r['ip']} @ {r['ts'].strftime('%H:%M:%S')} {r['method']} {mask(r['path'])} -> {r['status']} UA={r['ua'][:60]}")
misattributed = [ip for ip in claimed_monitor_ips if ip in env_ips and ip not in provider_ips]
add_check("monitor_ip_attribution",
          "IPs the executor attributed to the external monitor actually belong to the external monitor provider",
          "all claimed monitor IPs show provider UA (UptimeRobot)",
          f"claimed={claimed_monitor_ips}; real provider IPs (UA UptimeRobot)={provider_ips}; "
          f"misattributed (execution-env egress)={misattributed}; evidence lines: {env_evidence_lines}",
          len(misattributed) == 0, blocking=False,
          note=("core claim unaffected: the provider DOES poll the secret (UptimeRobot UA). The 3 misattributed IPs are "
                "this execution environment's egress (they carry W1-T03-AUDIT/curl UAs; 47.57.242.119 is documented in "
                "the first audit's log as ITS OWN IP). Documentation accuracy issue only."))

# (c) w1t03_monitor_verify.py is genuinely read-only on production
src = open(VERIFY_SCRIPT, encoding="utf-8").read()
ssh_cmds = re.findall(r'run\(ssh,\s*"([^"]*)"', src)
READONLY_SEG = re.compile(r'^(sudo -n\s+)?(tail|grep|awk|sort|uniq|head|tr|true|systemctl is-active|curl|date)\b')
seg_bad = []
for cmd in ssh_cmds:
    for seg in cmd.split("|"):
        seg = seg.strip()
        if seg and not READONLY_SEG.match(seg):
            seg_bad.append(seg)
# production mutations that cannot appear innocently anywhere in the source
SRC_MUT_RE = re.compile(
    r"systemctl\s+(restart|reload|stop|start|enable|disable)|nginx\s+-s|firewall-cmd|sed\s+-i|killall", re.IGNORECASE)
src_mutations = SRC_MUT_RE.findall(src)
# shell-level mutations/redirects are scanned ONLY inside the SSH command strings
# (scanning the Python source for '>' would false-positive on '->' annotations / '>' comparisons)
CMD_MUT_RE = re.compile(
    r">|>>|\btee\b|\brm\b|\bmv\b|\bcp\b|chmod|chown|sftp|\bscp\b|\bdd\b|\bkill\b|"
    r"systemctl\s+(?!is-active)|firewall-cmd|sed\s+-i|nginx\s+-s", re.IGNORECASE)
cmd_mutations = []
for cmd in ssh_cmds:
    for m in CMD_MUT_RE.finditer(cmd):
        cmd_mutations.append(m.group(0))
get_only = 'method="GET"' in src and not re.search(r'method\s*=\s*"(POST|PUT|DELETE|HEAD|PATCH)"', src)
exec_cmd_count = src.count("exec_command")
script_readonly = (not seg_bad) and (not src_mutations) and (not cmd_mutations) and get_only and exec_cmd_count == 1
add_check("verify_script_readonly",
          "scripts/w1t03_monitor_verify.py is read-only on production (line-by-line review)",
          "all SSH segments read-only (tail/grep/awk/sort/uniq/head/tr/systemctl is-active/curl), zero mutating commands or redirects in SSH strings, GET-only external probes, single exec_command wrapper",
          {"ssh_commands": ssh_cmds, "non_whitelisted_segments": seg_bad,
           "mutation_hits_in_source": src_mutations, "mutation_hits_in_ssh_commands": cmd_mutations,
           "get_only_external": get_only,
           "exec_command_occurrences": exec_cmd_count,
           "local_writes": "only OUT_JSON evidence file locally (allowed)"},
          script_readonly)

# =====================================================================
# 5) Token leak scan over the whole tree (excluding owner-token.txt itself)
# =====================================================================
section("5) Token leak scan across /home/z/my-project")
leak_matches = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    if ".git" in dirnames:
        dirnames.remove(".git")
    for fn in filenames:
        p = os.path.join(dirpath, fn)
        if p in (TOKEN_FILE, OUT_JSON):
            continue
        try:
            with open(p, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if TOKEN.encode() in data:
            leak_matches.append(os.path.relpath(p, ROOT))
add_check("token_leak_scan",
          "full token absent from every file in the tree except owner-token.txt (evidence files must show prefix 5e140aa0 only)",
          "0 files containing the full token",
          f"{len(leak_matches)} file(s): {leak_matches}",
          len(leak_matches) == 0,
          note=("BLOCKING security-discipline violation: the archived owner notification contains the full 32-hex token "
                "in its 'Checked URL' line. The file is currently untracked in git (no commit touches it, and this "
                "environment's git has no remote configured), but per R9 it is destined for docs/ops/… sync + GitHub "
                "push — the token must be masked there first (prefix 5e140aa0… only, like all other evidence).") if leak_matches else None)

# containment facts (documentation)
def git_out(args):
    r = subprocess.run(["git", "-C", ROOT] + args, capture_output=True, text=True, timeout=30)
    return (r.stdout + r.stderr).strip()

containment = {
    "notif_git_status": git_out(["status", "--porcelain", "--", os.path.relpath(NOTIF, ROOT)]),
    "notif_commits": git_out(["log", "--all", "--oneline", "--", os.path.relpath(NOTIF, ROOT)]) or "(none)",
    "remotes": git_out(["remote", "-v"]) or "(no remote configured in this environment)",
}
print(f"leak containment facts: {containment}")

# token file mode (was 0600 when audited in steps 0-2 audit)
mode = oct(os.stat(TOKEN_FILE).st_mode & 0o777)[2:]
numstat = git_out(["diff", "--numstat", "--", os.path.relpath(TOKEN_FILE, ROOT)])
add_check("token_file_mode_0600", "owner-token.txt still mode 0600", "600", mode,
          mode == "600", blocking=False,
          note=("local hygiene regression only (content byte-identical to git HEAD per numstat="
                f"{numstat or '0 0'}; file unpushed — no remote here). Recommend chmod 600 before any sync. "
                "Does not affect production or the secret's effectiveness.") if mode != "600" else None)

# =====================================================================
# 6) TRACKER consistency
# =====================================================================
section("6) TRACKER consistency")
tr = open(TRACKER, encoding="utf-8").read()
w1t03_start = tr.find("### W1-T03")
w1t03_end = tr.find("### W1-T04")
card = tr[w1t03_start:w1t03_end]
tracker_consistent = {
    "card_status_awaiting_audit_s34": "منجزة — بانتظار التدقيق (الخطوات 3-4)" in card.splitlines()[0 if False else 1] or "منجزة — بانتظار التدقيق (الخطوات 3-4)" in card[:400],
    "steps_0_4_all_checked": card.count("- [x] خطوة") == 5 and card.count("- [ ] خطوة") == 0,
    "board_row_s34": "| W1-T03 | مراقبة خارجية مجانية على /health + تنبيه | 1 | ساعة | منجزة — بانتظار التدقيق (الخطوات 3-4) |" in tr,
    "header_line": "W1-T03 منجزة خطوات 0-4 وبانتظار توقيع تدقيق الخطوات 3-4" in tr,
    "first_audit_signed": "W1-T03-AUDIT · 2026-10-27 · PASS" in card,
}
add_check("tracker_consistency",
          "W1-T03 card shows 'منجزة — بانتظار التدقيق (الخطوات 3-4)', steps 0-4 all [x], board+header consistent, steps 0-2 audit signed",
          "all consistency flags true",
          tracker_consistent, all(tracker_consistent.values()))

wl = open(WORKLOG, encoding="utf-8").read()
s34_entry = ("خطوات 3-4" in wl and "W1-T03" in wl and wl.find("W1-T03-S34") != -1)
last_ids = re.findall(r"^Task ID: (.+)$", wl, re.M)
add_check("worklog_entry_s34", "worklog contains an execution entry for steps 3-4 (R8)",
          "entry with Task ID W1-T03 covering steps 3-4 execution",
          f"last task IDs in worklog: {last_ids[-3:]}",
          s34_entry, blocking=False,
          note=("process gap (R8): the steps 3-4 execution is documented in the TRACKER card (سجل التنفيذ) but no "
                "worklog entry was appended by the executor. The audit appends its own entry; executor should backfill.") if not s34_entry else None)

# =====================================================================
# 7) Verdict + evidence dump
# =====================================================================
section("7) Verdict")
blocking_fails = [c["id"] for c in CHECKS if not c["pass"] and c["blocking"]]
nonblocking_fails = [c["id"] for c in CHECKS if not c["pass"] and not c["blocking"]]
verdict = "PASS" if not blocking_fails else "FAIL"
print(f"checks: {len(CHECKS)} | passed={sum(1 for c in CHECKS if c['pass'])} | "
      f"blocking_fails={blocking_fails} | nonblocking_fails={nonblocking_fails}")
print(f"VERDICT: {verdict}")

provider_table = [
    {"ts": r["ts"].strftime("%Y-%m-%d %H:%M:%S"), "ip": r["ip"], "method": r["method"],
     "path": mask(r["path"]), "status": r["status"], "ua": r["ua"], "ptr": ptr_results.get(r["ip"], "n/a")}
    for r in provider
]

results = {
    "audit_id": "W1-T03-S34-AUDIT",
    "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "server_clock": server_now,
    "scope": "W1-T03 steps 3-4 (owner monitoring step + executor verification/documentation step)",
    "token_policy": "full token masked as <TOKEN> everywhere; only prefix 5e140aa0 disclosed",
    "checks": CHECKS,
    "summary": {
        "total_checks": len(CHECKS),
        "passed": sum(1 for c in CHECKS if c["pass"]),
        "blocking_failures": blocking_fails,
        "nonblocking_failures": nonblocking_fails,
        "verdict": verdict,
    },
    "monitor_evidence": {
        "provider_polls_window": provider_table,
        "provider_ips": provider_ips,
        "provider_ptr_records": ptr_results,
        "cycle_gaps_seconds": cycle_deltas,
        "median_cycle_gap_seconds": median_delta,
        "get_statuses": sorted({r["status"] for r in gets}),
        "head_statuses": head_dist,
        "polls_after_executor_window_0402_27": [r["ts"].strftime("%H:%M:%S") for r in after_exec],
        "env_tooling_ips_excluded": env_ips,
        "this_audit_probe_ips": my_probe_ips,
        "count_healthz_last1000_now_vs_executor": {"mine_now": count1000, "executor_at_0402_27": "18"},
    },
    "executor_evidence_review": {
        "notification_file": os.path.relpath(NOTIF, ROOT),
        "notification_content_flags": notif_checks,
        "monitor_live_flags": live_consistent,
        "verify_script_ssh_commands": ssh_cmds,
        "claimed_monitor_ips": claimed_monitor_ips,
        "misattributed_to_env": misattributed,
        "env_ip_evidence_lines": [mask(l) for l in env_evidence_lines],
    },
    "token_leak": {
        "scan_root": ROOT,
        "excluded": os.path.relpath(TOKEN_FILE, ROOT),
        "matches": leak_matches,
        "containment": containment,
        "token_file_mode": mode,
    },
    "production": {"services": services, "app_health_direct_8010": health8010},
}

blob = json.dumps(results, ensure_ascii=False, indent=2)
if TOKEN in blob:  # belt and braces — must never happen
    blob = blob.replace(TOKEN, "<TOKEN>")
    print("WARNING: token found in results blob and was masked before writing.")
with open(OUT_JSON, "w", encoding="utf-8") as f:
    f.write(blob)
print(f"\nresults written to {OUT_JSON}")
ssh.close()
sys.exit(0)
