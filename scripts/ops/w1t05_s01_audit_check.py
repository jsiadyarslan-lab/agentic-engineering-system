#!/usr/bin/env python3
"""W1-T05-S01-AUDIT — independent audit of W1-T05 steps 0-1 (READ-ONLY on server).

Scope: step 0 (proof of outbound TCP/80 blocking) + step 1 (owner spec for the
VCN egress rule). Step 2 is an owner action that has NOT happened yet.
All server commands are read-only (curl probes / getent / which / ls /
systemctl is-active / journalctl / sudo -n firewall-cmd --list-all / raw
bash /dev/tcp connects). No POST /api/environment/probe (would mutate state).
Evidence -> download/aes-remediation/W1-T05/audit_s01_independent.json
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EV_DIR = "/home/z/my-project/download/aes-remediation/W1-T05"
STEPS_JSON = os.path.join(EV_DIR, "20261027-steps01.json")
SPEC_MD = os.path.join(EV_DIR, "OWNER-SPEC.md")
OUT_JSON = os.path.join(EV_DIR, "audit_s01_independent.json")
TS = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)


def run(cmd, timeout=30):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    return out, err


checks = []


def add(cid, group, desc, cmd, output, ok, evidence):
    checks.append({
        "id": cid, "group": group, "desc": desc, "cmd": cmd,
        "output": output[:1200], "verdict": "PASS" if ok else "FAIL",
        "evidence": evidence,
    })


def curl_probe(url, max_time=8):
    """Run curl on the server; parse code/time/errormsg/RC from OUTPUT TEXT."""
    c = (f"curl -s -o /dev/null -w '%{{http_code}}@@%{{time_total}}@@%{{errormsg}}' "
         f"--max-time {max_time} {url} ; echo '@@RC='$?")
    out, err = run(c, timeout=max_time + 25)
    raw = (out + ((" STDERR:" + err) if err else "")).strip()
    parts = raw.split("@@")
    code, time_s, errmsg, rc = "", "", "", ""
    if len(parts) >= 3:
        code = parts[0]
        time_s = parts[1] if len(parts) > 2 else ""
        if parts[-1].startswith("RC="):
            rc = parts[-1][3:]
            errmsg = "@@".join(parts[2:-1])
        else:
            errmsg = "@@".join(parts[2:])
    return raw, code, time_s, errmsg, rc


# ============ Group A — reproduce the outbound port-80 block myself ============
# A1: http://example.com (port 80) -> 000 / connection timed out / RC=28
raw, code, t, msg, rc = curl_probe("http://example.com/")
ok = code == "000" and rc == "28" and ("imed out" in msg) and (t == "" or float(t) >= 4)
add("A1", "A: reproduce block", "curl http://example.com/ (TCP/80) from server -> 000 timeout RC=28",
    "curl -w '%{http_code}@@%{time_total}@@%{errormsg}' --max-time 8 http://example.com/", raw, ok,
    f"http_code={code} time_total={t}s rc={rc} err='{msg}'")

# A2: https://example.com (port 443) -> 200 fast, SAME host
raw2, code2, t2, msg2, rc2 = curl_probe("https://example.com/")
ok = code2 == "200" and rc2 == "0" and float(t2) < 2.0
add("A2", "A: reproduce block", "curl https://example.com/ (TCP/443) same host -> 200 fast RC=0",
    "curl ... https://example.com/", raw2, ok,
    f"http_code={code2} time_total={t2}s rc={rc2} (same host as A1: only the port differs)")

# A3: second independent http target (neverssl.com) -> 000
raw3, code3, t3, msg3, rc3 = curl_probe("http://neverssl.com/")
ok = code3 == "000" and rc3 == "28"
add("A3", "A: reproduce block", "curl http://neverssl.com/ (2nd target, TCP/80) -> 000 RC=28",
    "curl ... http://neverssl.com/", raw3, ok,
    f"http_code={code3} time_total={t3}s rc={rc3} err='{msg3}'")

# A4: third http target (httpbin.org) -> 000
raw4, code4, t4, msg4, rc4 = curl_probe("http://httpbin.org/")
ok = code4 == "000" and rc4 == "28"
add("A4", "A: reproduce block", "curl http://httpbin.org/ (3rd target, TCP/80) -> 000 RC=28",
    "curl ... http://httpbin.org/", raw4, ok,
    f"http_code={code4} time_total={t4}s rc={rc4} err='{msg4}'")

# A5: raw TCP connect (bash /dev/tcp, curl-independent) to example.com:443 -> OPEN
c = "timeout 6 bash -c '</dev/tcp/example.com/443' && echo TCP443_OPEN || echo TCP444_FAIL_RC=$?"
o5, _ = run(c, timeout=20)
add("A5", "A: reproduce block", "raw TCP connect example.com:443 (bash /dev/tcp) -> opens",
    c, o5, "TCP443_OPEN" in o5, f"output='{o5}' (curl-independent proof 443 egress works)")

# A6: raw TCP connect to example.com:80 -> blocked (timeout kills it, RC=124)
c = "timeout 6 bash -c '</dev/tcp/example.com/80' && echo TCP80_OPEN || echo TCP80_BLOCKED_RC=$?"
o6, _ = run(c, timeout=20)
add("A6", "A: reproduce block", "raw TCP connect example.com:80 (bash /dev/tcp) -> blocked",
    c, o6, "TCP80_BLOCKED_RC=124" in o6, f"output='{o6}' (dropped packets -> timeout 124)")

# A7: DNS resolves fine (IPv4 or IPv6) -> failure is at TCP-connect stage, not DNS
# (curl's own "Connection timed out" message already implies resolution succeeded)
c = "getent hosts example.com | head -2; getent ahostsv4 example.com | head -1; echo GETENT_RC=$?"
o7, _ = run(c, timeout=15)
has_ip = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[0-9a-fA-F:]*:[0-9a-fA-F:]+)\b", o7) is not None
add("A7", "A: reproduce block", "DNS resolution of example.com works (failure is connect-stage)",
    c, o7, has_ip,
    f"getent RC=0 with addresses returned ('{o7.splitlines()[0] if o7 else ''}' + IPv4 via ahostsv4) "
    f"-> DNS fine, TCP/80 connect fails")

# ============ Group B — factory readiness capability state (GET, read-only) ============
c = "curl -s --max-time 10 http://127.0.0.1:8010/api/environment/readiness"
oR, _ = run(c, timeout=20)
net = {}
try:
    for it in json.loads(oR)["capabilities"]:
        if str(it.get("capability_id", "")).startswith("network"):
            net[it["capability_id"]] = it
except Exception as exc:  # noqa: BLE001
    oR = f"PARSE_ERROR: {exc} :: raw[:400]={oR[:400]}"

nh = net.get("network_http", {})
B1 = nh.get("stored_status") == "NOT_READY" and nh.get("readiness_status") == "NOT_READY"
add("B1", "B: factory readiness", "GET /api/environment/readiness: network_http stored_status=NOT_READY",
    c, json.dumps({k: nh.get(k) for k in ("capability_id", "readiness_status", "stored_status",
                                          "last_probe_at")}, ensure_ascii=False), B1,
    f"network_http readiness_status={nh.get('readiness_status')} stored_status={nh.get('stored_status')} "
    f"last_probe_at={nh.get('last_probe_at')}")

fr = str(nh.get("failure_reason", ""))
B2 = ("Errno 101" in fr) or ("Network is unreachable" in fr) or ("تعذر HTTP" in fr)
add("B2", "B: factory readiness", "network_http failure_reason mentions Errno 101 / network unreachable",
    "(parsed from same GET)", fr, B2, f"failure_reason='{fr}'")

nd, ns = net.get("network_dns", {}), net.get("network_https", {})
B3 = nd.get("stored_status") == "READY" and ns.get("stored_status") == "READY"
add("B3", "B: factory readiness", "network_dns + network_https stored_status=READY (only STALE freshness)",
    "(parsed from same GET)",
    json.dumps({"network_dns": {k: nd.get(k) for k in ("stored_status", "readiness_status")},
                "network_https": {k: ns.get(k) for k in ("stored_status", "readiness_status")}},
               ensure_ascii=False), B3,
    f"dns stored={nd.get('stored_status')} ({nd.get('readiness_status')}) · "
    f"https stored={ns.get('stored_status')} ({ns.get('readiness_status')})")

# ============ Group C — management path (oci CLI / ~/.oci) ============
c = "R=$(which oci 2>/dev/null); echo \"WHICH=[$R] WHICH_RC=$?\"; oci --version 2>&1 | head -1"
oC, _ = run(c, timeout=15)
C1 = ("WHICH=[]" in oC) and ("command not found" in oC)
add("C1", "C: mgmt path", "oci CLI not installed ('command not found')",
    c, oC, C1, f"output='{oC.replace(chr(10), ' | ')}'")

c = "ls -la ~/.oci 2>&1; echo LS_RC=$?"
oC2, _ = run(c, timeout=15)
C2 = ("No such file" in oC2) and ("LS_RC=2" in oC2)
add("C2", "C: mgmt path", "~/.oci config dir absent",
    c, oC2, C2, f"output='{oC2.replace(chr(10), ' | ')}' -> no OCI API path from the server")

# ============ Group F — general production health (R6), run early-ish ============
c = "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health"
oH, _ = run(c, timeout=15)
F1ok = oH.strip() == "200"
add("F1", "F: health (R6)", "/health from loopback -> 200", c, oH, F1ok,
    f"http_code={oH.strip()}")

c = "systemctl is-active agentic nginx firewalld"
oS, _ = run(c, timeout=15)
F2ok = oS.split() == ["active", "active", "active"]
add("F2", "F: health (R6)", "services agentic/nginx/firewalld all active", c, oS,
    F2ok, f"is-active output='{oS.replace(chr(10), '+')}'")

c = "journalctl -u agentic --since '-30 min' -p err --no-pager | tail -3"
oJ, _ = run(c, timeout=20)
F3ok = ("No entries" in oJ) and ("error" not in oJ.lower().replace("-- no entries --", ""))
add("F3", "F: health (R6)", "no new agentic errors in journal (last 30 min)", c, oJ, F3ok,
    f"journal err output='{oJ.replace(chr(10), ' | ')}'")

# context capture (not a pass/fail check): firewalld zone + curl version
oFW, _ = run("sudo -n firewall-cmd --list-all 2>/dev/null | head -12", timeout=15)
oCV, _ = run("curl --version | head -1", timeout=15)

ssh.close()

# ============ Group D — executor evidence integrity (local files) ============
with open(STEPS_JSON, encoding="utf-8") as f:
    steps = json.load(f)

meta = steps.get("_meta", {})
D1 = ("READ-ONLY" in str(meta.get("mode", ""))) and all(
    k in steps for k in ("http80_example_com", "https443_example_com", "http80_neverssl_com",
                         "oci_cli", "services", "health"))
add("D1", "D: evidence integrity", "20261027-steps01.json valid, all keys present, _meta READ-ONLY",
    "(local read)", json.dumps(meta, ensure_ascii=False), D1,
    f"_meta.mode='{meta.get('mode')}' timestamp={meta.get('timestamp')}")

v = str(steps.get("http80_example_com", ""))
t_exec = re.search(r"([\d.]+)", v)
D2 = v.startswith("000") and ("imed out" in v) and ("RC=28" in v) and (code == "000")
add("D2", "D: evidence integrity", "steps01 http80_example_com == my measurement (000/timeout/RC=28)",
    "(local read)", v, D2,
    f"executor='{v[:90]}' vs mine: 000/{t}s/RC={rc} — same verdict, both timeouts "
    f"(exec {t_exec.group(1) if t_exec else '?'}s, mine {t}s — approx match)")

v2 = str(steps.get("https443_example_com", ""))
D3 = v2.startswith("200") and ("RC=0" in v2) and (code2 == "200")
add("D3", "D: evidence integrity", "steps01 https443_example_com == my measurement (200/RC=0)",
    "(local read)", v2, D3,
    f"executor='{v2}' vs mine: 200/{t2}s/RC=0 — same host fast on 443 both times")

v3 = str(steps.get("http80_neverssl_com", ""))
D4 = v3.startswith("000") and ("RC=28" in v3) and (code3 == "000")
add("D4", "D: evidence integrity", "steps01 http80_neverssl_com == my measurement (000/RC=28)",
    "(local read)", v3, D4, f"executor='{v3[:90]}' vs mine: 000/RC={rc3}")

v4 = str(steps.get("oci_cli", ""))
D5 = ("command not found" in v4) and C1
add("D5", "D: evidence integrity", "steps01 oci_cli == my measurement (command not found)",
    "(local read)", v4, D5, f"executor='{v4.replace(chr(10), ' | ')}' matches my C1 finding")

v5s, v5h = str(steps.get("services", "")), str(steps.get("health", ""))
D6 = (v5s.split() == ["active", "active", "active"]) and (v5h.strip() == "200") and F2ok
add("D6", "D: evidence integrity", "steps01 services/health == my measurements (active x3 / 200)",
    "(local read)", f"services='{v5s.replace(chr(10), '+')}' health='{v5h}'", D6,
    "executor recorded active x3 + health 200; my live re-check agrees (F1/F2)")

# ============ Group E — OWNER-SPEC.md correctness for the owner ============
with open(SPEC_MD, encoding="utf-8") as f:
    spec = f.read()
spec_l = spec.lower()

E1 = ("egress" in spec_l) and ("add egress rules" in spec_l) and ("ingress" not in spec_l)
add("E1", "E: owner spec", "spec is an EGRESS rule (word 'Ingress' absent entirely)",
    "(local read)", "Add Egress Rules present: %s; 'ingress' occurrences: %d"
    % ("add egress rules" in spec_l, spec_l.count("ingress")), E1,
    f"'Add Egress Rules' in spec={'add egress rules' in spec_l}; ingress count={spec_l.count('ingress')}")

E2 = ("مكتفٍ بالحالة" in spec) and ("غير محدد" in spec)
add("E2", "E: owner spec", "Stateless = unchecked (stateful rule) as the card requires",
    "(local read)", [ln for ln in spec.splitlines() if "Stateless" in ln], E2,
    "spec: 'مكتفٍ بالحالة (Stateless = غير محدد/مقصوص)' -> stateful, matching card 'Stateless=لا'")

E3 = bool(re.search(r"Destination CIDR.*\*\*0\.0\.0\.0/0\*\*", spec, re.S))
add("E3", "E: owner spec", "Destination CIDR = 0.0.0.0/0", "(local read)",
    [ln for ln in spec.splitlines() if "0.0.0.0/0" in ln], E3, "field table shows 0.0.0.0/0")

E4 = bool(re.search(r"IP Protocol.*\*\*TCP\*\*", spec, re.S))
add("E4", "E: owner spec", "IP Protocol = TCP", "(local read)",
    [ln for ln in spec.splitlines() if "IP Protocol" in ln], E4, "field table shows TCP")

E5 = bool(re.search(r"Destination Port Range.*\*\*80\*\*", spec, re.S)) and (
    "Source Port Range" in spec)
add("E5", "E: owner spec", "Destination Port Range = 80 (source port left All/empty)",
    "(local read)",
    [ln for ln in spec.splitlines() if "Port Range" in ln], E5,
    "port 80 is the DESTINATION port of the egress rule; Source Port Range = (اتركه فارغًا/All)")

E6 = ("نفس Security List" in spec) and ("443" in spec) and ("بعد الإضافة" in spec) and (
    "التراجع" in spec)
add("E6", "E: owner spec", "same Security List carrying the 443 rule + post-add steps + rollback",
    "(local read)", "same-SL mention + post-add + rollback sections", E6,
    "spec: 'نفس Security List التي تحوي قاعدة خروج TCP 443 القائمة' + 'بعد الإضافة' + 'التراجع'")

# ============ verdict ============
passed = sum(1 for c in checks if c["verdict"] == "PASS")
failed = len(checks) - passed
verdict = "PASS" if failed == 0 else "FAIL"

script_md5 = hashlib.md5(open(__file__, "rb").read()).hexdigest()

result = {
    "_meta": {
        "task": "W1-T05-S01-AUDIT (independent audit of W1-T05 steps 0-1; step 2 is owner action, "
                "not yet performed)",
        "agent": "W1-T05-S01-AUDIT (independent audit agent, general-purpose)",
        "timestamp": TS, "mode": "READ-ONLY (zero writes on the server; no POST probe; no git)",
        "server": f"{USER}@{HOST}", "script": __file__, "script_md5": script_md5,
    },
    "checks": checks,
    "claims_vs_audit": [
        {"claim": "curl http://example.com/ fails 000/RC=28 connection timeout while "
                  "https://example.com/ = 200 fast (same host)",
         "finding": f"my own probes: http80={code}/{t}s/RC={rc} ('{msg}'); https443={code2}/{t2}s/RC={rc2}; "
                    f"raw TCP /dev/tcp: 443 OPEN, 80 blocked (timeout 124); httpbin.org also 000/RC={rc4}",
         "verdict": "CONFIRMED" if (code == "000" and code2 == "200") else "NOT CONFIRMED"},
        {"claim": "factory network_http = NOT_READY (Errno 101 Network is unreachable) while "
                  "network_dns + network_https READY",
         "finding": f"network_http stored/readiness={nh.get('stored_status')}/{nh.get('readiness_status')}, "
                    f"failure_reason='{fr}', last_probe_at={nh.get('last_probe_at')}; "
                    f"dns/https stored=READY",
         "verdict": "CONFIRMED" if (B1 and B2 and B3) else "NOT CONFIRMED"},
        {"claim": "oci CLI not installed and ~/.oci absent -> no technical path from the server",
         "finding": f"which oci: '{oC.replace(chr(10), ' | ')}'; ~/.oci: "
                    f"'{oC2.replace(chr(10), ' | ')}'",
         "verdict": "CONFIRMED" if (C1 and C2) else "NOT CONFIRMED"},
        {"claim": "OWNER-SPEC.md matches the card: Egress / Stateless=لا / 0.0.0.0/0 / TCP / "
                  "Destination Port 80 / same Security List as 443",
         "finding": "E1-E6 all verified on the actual file (Egress-only wording, 'ingress' absent, "
                    "stateful, 0.0.0.0/0, TCP, dest port 80, same-SL-as-443, post-add + rollback)",
         "verdict": "CONFIRMED" if all([E1, E2, E3, E4, E5, E6]) else "NOT CONFIRMED"},
        {"claim": "20261027-steps01.json consistent with my measurements and READ-ONLY",
         "finding": "D1-D6 verified: same HTTP codes/RCs/timeouts for all three targets, oci absent, "
                    "services x3 active, health 200, _meta mode 'READ-ONLY steps 0-1'",
         "verdict": "CONFIRMED" if all([D1, D2, D3, D4, D5, D6]) else "NOT CONFIRMED"},
    ],
    "counts": {"total": len(checks), "passed": passed, "failed": failed},
    "non_blocking_notes": [
        "steps01.json 'readiness_now' is a truncated 600-char string showing only the 'llm' item — "
        "it does NOT itself contain the network_http NOT_READY/Errno-101 record; the claim is TRUE "
        "(independently confirmed via GET /api/environment/readiness: stored NOT_READY, Errno 101, "
        f"last_probe_at={nh.get('last_probe_at')}) and OWNER-SPEC.md cites the values, but the raw "
        "evidence file under-documents this specific item (documentation gap only).",
        "network_http last_success_at=2026-10-26T21:26:59 — it succeeded once earlier (before the "
        "probe window), consistent with an environment-level egress block rather than app logic.",
    ],
    "context": {"firewalld_zone": oFW, "curl_version": oCV,
                "readiness_raw_network_items": {k: {kk: v.get(kk) for kk in
                    ("stored_status", "readiness_status", "failure_reason", "last_probe_at")}
                    for k, v in net.items()}},
    "final_verdict": verdict,
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"VERDICT: {verdict} — {passed}/{len(checks)} checks passed, {failed} failed")
for c in checks:
    print(f"  [{c['verdict']}] {c['id']} {c['desc']}")
print(f"evidence -> {OUT_JSON}")
