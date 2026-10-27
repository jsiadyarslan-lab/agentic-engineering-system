#!/usr/bin/env python3
"""W1-T01 — POST-STATE EVIDENCE COLLECTOR (read-only).
Run #2 completed all server-side changes but was killed locally before writing
results (bash timeout 240s). This collector independently documents the final
state as canonical evidence: results_postverify.json + postverify_log.txt
"""
import json
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
OUT_DIR = "/home/z/my-project/download/aes-remediation/W1-T01"
STAMP = "20261027"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, key_filename=KEY, timeout=25,
          look_for_keys=False, allow_agent=False)

LOG = []
def run(name, cmd, timeout=40):
    _, o, e = c.exec_command(cmd, timeout=timeout)
    rc = o.channel.recv_exit_status()
    out = o.read().decode(errors="replace").strip()
    err = e.read().decode(errors="replace").strip()
    LOG.append(f"===== {name} [rc={rc}] =====\n$ {cmd}\n{out[:3000]}\n" + (f"[stderr] {err[:400]}\n" if err else ""))
    print(f"--- {name} [rc={rc}]: {out[:200].replace(chr(10), ' | ')}")
    return {"rc": rc, "out": out, "err": err}

R = {}
R["states"] = run("states",
    "for s in agentic agentic-vis aes-shim nginx; do printf '%s active=' $s; systemctl is-active $s 2>&1; printf ' enabled='; systemctl is-enabled $s 2>&1; done")
R["ports"] = run("ports", "sudo -n ss -tln | grep -E ':8010|:8011|:8099'; echo EXIT_$?")
R["ports_detail"] = run("ports_detail", "sudo -n ss -tlnp | head -15")
R["archive"] = run("archive",
    f"sudo -n du -sh /opt/aes-archive/* && sudo -n ls -la /opt/aes-archive/ && echo '--- origins:' && ls -d /opt/aes-vis /opt/aes-shim 2>&1")
R["unit_files_kept"] = run("unit_files_kept",
    "ls -la /etc/systemd/system/agentic-vis.service /etc/systemd/system/aes-shim.service")
R["health"] = run("health",
    "curl -s --max-time 8 http://127.0.0.1:8010/health | head -c 300")
R["health_code"] = run("health_code",
    "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
R["nginx_path"] = run("nginx_path",
    "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1/ ; echo ' <- nginx port80 from loopback (expect 401: auth wall intact)'")
R["agentic_journal_errors"] = run("agentic_journal_errors",
    "sudo -n journalctl -u agentic --since '-40 min' --no-pager 2>/dev/null | grep -iE 'error|traceback|critical' | grep -v 'error_log' | head -8; echo EXIT_$?")
R["agentic_journal_tail"] = run("agentic_journal_tail",
    "sudo -n journalctl -u agentic --since '-40 min' --no-pager 2>/dev/null | tail -6")
R["mem"] = run("mem", "free -m | head -2")
R["procs_frozen"] = run("procs_frozen",
    "ps aux | grep -E 'aes-vis|aes-shim|aes_local_shim' | grep -v grep; echo EXIT_$?")
R["production_git"] = run("production_git",
    "cd /opt/agentic-engineering-system && git rev-parse --short HEAD && git status -s | head -3")

# --- verdict ---
states = R["states"]["out"]
ports_lines = [l for l in R["ports"]["out"].splitlines() if l.strip() and not l.strip().startswith("EXIT_")]
verdict = {
    "vis_inactive_disabled": "agentic-vis active=inactive" in states and "disabled" in states.split("agentic-vis")[1],
    "shim_inactive_disabled": "aes-shim active=inactive" in states and "disabled" in states.split("aes-shim")[1],
    "agentic_active": "agentic active=active" in states,
    "nginx_active": "nginx active=active" in states,
    "only_8010_listening": any(":8010" in l for l in ports_lines) and not any((":8011" in l or ":8099" in l) for l in ports_lines),
    "health_200_json_ok": R["health_code"]["out"] == "200" and '"status":"ok"' in R["health"]["out"],
    "nginx_auth_wall_intact": "401" in R["nginx_path"]["out"],
    "archive_complete": f"aes-vis-frozen-{STAMP}" in R["archive"]["out"] and f"aes-shim-frozen-{STAMP}" in R["archive"]["out"],
    "origins_removed": "No such file" in R["archive"]["out"],
    "unit_files_kept_for_rollback": "agentic-vis.service" in R["unit_files_kept"]["out"] and "aes-shim.service" in R["unit_files_kept"]["out"],
    "no_frozen_procs": all(not l.strip() or l.strip().startswith("EXIT_") for l in R["procs_frozen"]["out"].splitlines()),
    "production_git_unchanged": "0f2d9c6" in R["production_git"]["out"],
    "no_new_agentic_errors": all((not l.strip() or l.strip().startswith("EXIT_")) for l in R["agentic_journal_errors"]["out"].splitlines()),
}
R["verdict"] = {"checks": verdict, "passed": all(verdict.values())}
print("\nVERDICT:", json.dumps(verdict, ensure_ascii=False))
print("PASSED:", R["verdict"]["passed"])
c.close()

json.dump(R, open(f"{OUT_DIR}/results_postverify.json", "w"), ensure_ascii=False, indent=1)
open(f"{OUT_DIR}/postverify_log.txt", "w").write("\n".join(LOG))
print(f"Evidence written: {OUT_DIR}/results_postverify.json + postverify_log.txt")
