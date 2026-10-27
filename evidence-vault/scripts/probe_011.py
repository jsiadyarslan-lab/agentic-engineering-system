#!/usr/bin/env python3
"""AES-011 — Phase 1 READ-ONLY probe: what is actually served vs what is deployed.

Questions this answers with raw evidence:
  A. production commit / service state now
  B. nginx port-80 routing NOW (did it flip back to 8011 after 010?)
  C. what modified agentic.conf (cron/timer/unit hunt)
  D. HTTP response headers for / and assets (cache policy as served)
  E. fingerprint triple-compare: served bytes vs server file vs git blob (4568ed5)
  F. what an external visitor gets (auth on the public link)
"""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"

FILES = ["index.html", "theme.css", "styles.css", "app-shell.css",
         "factory-control.css", "app.js", "factory-control.js"]

def sh(c, cmd, t=40):
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace").strip(),
            e.read().decode("utf-8", "replace").strip())

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
              look_for_keys=False, allow_agent=False)

    print("===== A. production state =====")
    for name, cmd in [
        ("head", "git -C /opt/agentic-engineering-system rev-parse HEAD"),
        ("expect", "echo 4568ed5dcba44c6bbb112107830b9a2eb1ab5a9f"),
        ("status", "git -C /opt/agentic-engineering-system status --porcelain --untracked-files=no | wc -l"),
        ("svc", "systemctl is-active agentic.service && systemctl show agentic.service -p ActiveEnterTimestamp"),
        ("health", "curl -s --max-time 6 http://127.0.0.1:8010/health | head -c 220"),
    ]:
        out, err = sh(c, cmd)
        print(f"[{name}] {out or err}")

    print("\n===== B. nginx routing NOW =====")
    out, _ = sh(c, "cat /etc/nginx/conf.d/agentic.conf")
    print(out)
    out, _ = sh(c, "stat -c '%y  %n' /etc/nginx/conf.d/agentic.conf* 2>/dev/null | sort")
    print("--- conf files & mtimes ---"); print(out)
    out, _ = sh(c, "diff /etc/nginx/conf.d/agentic.conf.bak-010 /etc/nginx/conf.d/agentic.conf 2>/dev/null && echo 'IDENTICAL to bak-010' || true")
    print("--- diff vs bak-010 ---"); print(out)
    out, _ = sh(c, "sudo -n nginx -T 2>/dev/null | grep -E 'proxy_pass|listen|auth_basic|server_name' | head -20 || grep -rE 'proxy_pass|listen' /etc/nginx/conf.d/ | head -20")
    print("--- effective nginx routing ---"); print(out)

    print("\n===== C. who flips agentic.conf =====")
    for name, cmd in [
        ("cron", "sudo -n grep -rn 'agentic.conf\\|nginx' /etc/cron* /var/spool/cron/ 2>/dev/null | head -10 || true"),
        ("timers", "systemctl list-timers --all --no-pager 2>/dev/null | grep -iE 'vis|aes|nginx|agentic' || echo none"),
        ("vis_unit", "systemctl cat agentic-vis.service 2>/dev/null | grep -E 'ExecStart|WorkingDir|Description' || echo 'no agentic-vis unit'"),
        ("recent_confs", "ls -la --time-style=full-iso /etc/nginx/conf.d/ | head -12"),
    ]:
        out, err = sh(c, cmd)
        print(f"[{name}]"); print(out or err or "(empty)")

    print("\n===== D. response headers as served =====")
    for name, cmd in [
        ("index_via_8010", "curl -sI --max-time 6 http://127.0.0.1:8010/ | tr -d '\\r'"),
        ("theme_via_8010", "curl -sI --max-time 6 'http://127.0.0.1:8010/static/theme.css?v=4.0.0' | tr -d '\\r'"),
        ("index_via_80",   "curl -sI --max-time 6 http://127.0.0.1/ | tr -d '\\r'"),
        ("theme_via_80",   "curl -sI --max-time 6 'http://127.0.0.1/static/theme.css?v=4.0.0' | tr -d '\\r'"),
    ]:
        out, err = sh(c, cmd)
        print(f"[{name}]"); print(out or err)

    print("\n===== E. fingerprint triple-compare (served : server-file : git-blob@HEAD) =====")
    for f in FILES:
        served, _ = sh(c, f"curl -s --max-time 8 'http://127.0.0.1:8010/static/{f}?v=4.0.0' | sha256sum | cut -c1-16")
        if f == "index.html":
            served, _ = sh(c, "curl -s --max-time 8 http://127.0.0.1:8010/ | sha256sum | cut -c1-16")
        onfile, _ = sh(c, f"sha256sum /opt/agentic-engineering-system/src/ui/{f} | cut -c1-16")
        blob, _ = sh(c, f"git -C /opt/agentic-engineering-system show HEAD:src/ui/{f} | sha256sum | cut -c1-16")
        mark = "MATCH" if served == onfile == blob else "*** MISMATCH ***"
        print(f"{f:24s} served={served}  file={onfile}  git@HEAD={blob}  -> {mark}")

    print("\n===== F. what port 80 actually returns (body head) =====")
    out, _ = sh(c, "curl -s --max-time 6 http://127.0.0.1/ | head -c 400")
    print(out)
    out, _ = sh(c, "curl -s --max-time 6 http://127.0.0.1/ | grep -oE 'v=[0-9a-f.]+' | sort | uniq -c | head -5")
    print("--- ?v= values seen in port-80 HTML ---"); print(out or "(none)")
    c.close()

if __name__ == "__main__":
    main()
