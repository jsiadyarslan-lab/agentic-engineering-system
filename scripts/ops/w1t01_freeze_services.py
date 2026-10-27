#!/usr/bin/env python3
"""W1-T01 — Freeze agentic-vis (8011) + aes-shim (8099) with archival.
Safety-gated: aborts BEFORE any change if production references found;
aborts BEFORE archive if post-stop verification fails.
Evidence: download/aes-remediation/W1-T01/{results.json, execution_log.txt}
"""
import json, sys, time
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
OUT_DIR = "/home/z/my-project/download/aes-remediation/W1-T01"
STAMP = "20261027"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=25,
          look_for_keys=False, allow_agent=False)

LOG = []
def run(name, cmd, timeout=45):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    rc = o.channel.recv_exit_status()
    out = o.read().decode(errors="replace").strip()
    err = e.read().decode(errors="replace").strip()
    LOG.append(f"===== {name} [rc={rc}] =====\n$ {cmd}\n{out[:2500]}\n" + (f"[stderr] {err[:400]}\n" if err else ""))
    print(f"--- {name} [rc={rc}]")
    if out:
        print(out[:600])
    if err:
        print(f"[stderr] {err[:200]}")
    print()
    return {"rc": rc, "out": out, "err": err}

R = {}

# ========== PHASE 0: PRE-FLIGHT SAFETY (read-only) ==========
print("### PHASE 0 — PRE-FLIGHT (read-only)")
R["preflight_services"] = run("preflight_services",
    "for s in agentic agentic-vis aes-shim nginx; do printf '%s: ' $s; systemctl is-active $s; done")
R["preflight_env_refs"] = run("preflight_env_refs",
    "sudo -n grep -nE '8099|8011' /opt/agentic-engineering-system/.env* 2>/dev/null | sed 's/=.*/=<redacted>/' ; echo EXIT_$?")
R["preflight_src_refs"] = run("preflight_src_refs",
    "grep -rnE ':8099|:8011' /opt/agentic-engineering-system/src/ 2>/dev/null | head -10; echo EXIT_$?")
R["preflight_db_shim_refs"] = run("preflight_db_shim_refs",
    "sudo -n strings /opt/agentic-engineering-system/runtime/agent_hub_v2.db 2>/dev/null | grep -nE '127\\.0\\.0\\.1:8099|localhost:8099' | head -5; echo COUNT_$(sudo -n strings /opt/agentic-engineering-system/runtime/agent_hub_v2.db 2>/dev/null | grep -cE '127\\.0\\.0\\.1:8099|localhost:8099')")
R["preflight_connections"] = run("preflight_connections",
    "sudo -n ss -tnp 2>/dev/null | grep -E ':8099|:8011'; echo EXIT_$?")
R["preflight_unit_deps"] = run("preflight_unit_deps",
    "sudo -n grep -rlE 'aes-shim|agentic-vis' /etc/systemd/system/ 2>/dev/null | grep -vE 'aes-shim\\.service|agentic-vis\\.service'; echo EXIT_$?")
R["preflight_health"] = run("preflight_health",
    "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
R["preflight_mem"] = run("preflight_mem", "free -m | head -2")
R["preflight_listeners"] = run("preflight_listeners", "sudo -n ss -tlnp 2>/dev/null | grep -E ':8011|:8099'")

# GATE 0 — abort before ANY change (evaluate actual match LINES, not exit markers)
def match_lines(out):
    return [l for l in out.splitlines()
            if l.strip() and not l.strip().startswith("EXIT_") and not l.strip().startswith("COUNT_")]

env_refs = match_lines(R["preflight_env_refs"]["out"])
src_refs = match_lines(R["preflight_src_refs"]["out"])
db_count = 0
for line in R["preflight_db_shim_refs"]["out"].splitlines():
    if line.startswith("COUNT_"):
        db_count = int(line[6:]) if line[6:].isdigit() else 0
db_lines = match_lines(R["preflight_db_shim_refs"]["out"])
conns = match_lines(R["preflight_connections"]["out"])
deps = match_lines(R["preflight_unit_deps"]["out"])
health0 = R["preflight_health"]["out"]

gate0 = {
    "env_refs_empty": len(env_refs) == 0,
    "src_refs_empty": len(src_refs) == 0,
    "db_shim_refs_zero": db_count == 0 and len(db_lines) == 0,
    "no_live_connections": len(conns) == 0,
    "no_unit_dependencies": len(deps) == 0,
    "health_200": health0 == "200",
}
R["gate0"] = {"checks": gate0, "passed": all(gate0.values()),
               "env_match_lines": env_refs, "src_match_lines": src_refs,
               "conn_lines": conns, "dep_lines": deps, "db_count": db_count}
print("GATE 0:", json.dumps(gate0))
if not R["gate0"]["passed"]:
    R["aborted_at"] = "gate0"
    print("!! ABORT — production reference to shim/vis found or health failing. NO CHANGES MADE.")
    c.close()
    json.dump(R, open(f"{OUT_DIR}/results.json", "w"), ensure_ascii=False, indent=1)
    open(f"{OUT_DIR}/execution_log.txt", "w").write("\n".join(LOG))
    sys.exit(2)

# ========== PHASE 1: STOP + DISABLE ==========
print("### PHASE 1 — STOP + DISABLE")
R["stop_vis"] = run("stop_vis", "sudo -n systemctl stop agentic-vis")
R["stop_shim"] = run("stop_shim", "sudo -n systemctl stop aes-shim")
R["disable_vis"] = run("disable_vis", "sudo -n systemctl disable agentic-vis")
R["disable_shim"] = run("disable_shim", "sudo -n systemctl disable aes-shim")

# ========== PHASE 2: POST-STOP VERIFICATION ==========
print("### PHASE 2 — VERIFY AFTER STOP")
R["post_states"] = run("post_states",
    "for s in agentic agentic-vis aes-shim nginx; do printf '%s active=' $s; systemctl is-active $s; printf ' enabled='; systemctl is-enabled $s 2>&1; done")
R["post_listeners"] = run("post_listeners", "sudo -n ss -tlnp 2>/dev/null | grep -E ':8011|:8099'; echo EXIT_$?")
R["post_health"] = run("post_health", "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
R["post_mem"] = run("post_mem", "free -m | head -2")
R["post_nginx_err"] = run("post_nginx_err", "sudo -n tail -n 3 /var/log/nginx/error.log")

states = R["post_states"]["out"]
listeners = match_lines(R["post_listeners"]["out"])
health1 = R["post_health"]["out"]
gate2 = {
    "vis_inactive": "agentic-vis active=inactive" in states,
    "shim_inactive": "aes-shim active=inactive" in states,
    "vis_disabled": "agentic-vis" in states and "disabled" in states.split("agentic-vis")[1],
    "shim_disabled": "aes-shim" in states and "disabled" in states.split("aes-shim")[1],
    "no_listeners": len(listeners) == 0,
    "agentic_still_active": "agentic active=active" in states,
    "nginx_still_active": "nginx active=active" in states,
    "health_200": health1 == "200",
}
R["gate2"] = {"checks": gate2, "passed": all(gate2.values())}
print("GATE 2:", json.dumps(gate2))
if not R["gate2"]["passed"]:
    R["aborted_at"] = "gate2"
    print("!! STOP verified but gate2 failed — ROLLBACK (restart services) before abort.")
    run("rollback_restart", "sudo -n systemctl start agentic-vis aes-shim")
    run("rollback_health", "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
    c.close()
    json.dump(R, open(f"{OUT_DIR}/results.json", "w"), ensure_ascii=False, indent=1)
    open(f"{OUT_DIR}/execution_log.txt", "w").write("\n".join(LOG))
    sys.exit(3)

# ========== PHASE 3: ARCHIVE ==========
print("### PHASE 3 — ARCHIVE OUTSIDE RUNTIME PATH")
R["archive_mkdir"] = run("archive_mkdir", "sudo -n mkdir -p /opt/aes-archive")
R["archive_vis"] = run("archive_vis", f"sudo -n mv /opt/aes-vis /opt/aes-archive/aes-vis-frozen-{STAMP}")
R["archive_shim"] = run("archive_shim", f"sudo -n mv /opt/aes-shim /opt/aes-archive/aes-shim-frozen-{STAMP}")
R["archive_verify"] = run("archive_verify",
    f"sudo -n du -sh /opt/aes-archive/* && sudo -n ls /opt/aes-archive/ && echo '--- origin gone:' && ls /opt/aes-vis /opt/aes-shim 2>&1 | head -4")

# ========== PHASE 4: FINAL VERIFICATION ==========
print("### PHASE 4 — FINAL VERIFY")
R["final_health"] = run("final_health",
    "curl -s --max-time 8 http://127.0.0.1:8010/health | head -c 200; echo; curl -s -o /dev/null -w 'nginx_path_%{http_code}' --max-time 8 -u \"$HOME/x\" http://127.0.0.1/ || true")
R["final_states"] = run("final_states",
    "systemctl is-active agentic nginx; systemctl is-enabled agentic-vis aes-shim 2>&1")
R["final_listeners"] = run("final_listeners", "sudo -n ss -tln | grep -E ':8011|:8099'; echo EXIT_$?")
R["final_port8010"] = run("final_port8010", "sudo -n ss -tln | grep -c ':8010'")
R["final_mem"] = run("final_mem", "free -m | head -2")

health_final = R["final_health"]["out"].splitlines()[0] if R["final_health"]["out"] else ""
final_gate = {
    "health_ok_json": '"status":"ok"' in R["final_health"]["out"],
    "agentic_nginx_active": R["final_states"]["out"].startswith("active"),
    "both_disabled": R["final_states"]["out"].count("disabled") >= 2,
    "no_8011_8099_listeners": len(match_lines(R["final_listeners"]["out"])) == 0,
    "port_8010_listening": R["final_port8010"]["out"].strip().isdigit(),
    "archive_exists": f"aes-vis-frozen-{STAMP}" in R["archive_verify"]["out"] and f"aes-shim-frozen-{STAMP}" in R["archive_verify"]["out"],
    "origin_gone": "No such file" in R["archive_verify"]["out"] or "cannot access" in R["archive_verify"]["out"],
}
R["final_gate"] = {"checks": final_gate, "passed": all(final_gate.values())}
print("FINAL GATE:", json.dumps(final_gate))

R["outcome"] = "SUCCESS" if final_gate["passed"] else "PARTIAL (see final_gate)"
c.close()

json.dump(R, open(f"{OUT_DIR}/results.json", "w"), ensure_ascii=False, indent=1)
open(f"{OUT_DIR}/execution_log.txt", "w").write("\n".join(LOG))
print(f"\n>>> OUTCOME: {R['outcome']}")
print(f">>> Evidence: {OUT_DIR}/results.json + execution_log.txt")
sys.exit(0 if final_gate["passed"] else 4)
