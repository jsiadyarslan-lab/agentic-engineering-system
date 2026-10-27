#!/usr/bin/env python3
"""RLR-002-e — locate capability check API route (frontend -> backend)."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

CMDS = [
    ("api structure", "ls /opt/agentic-engineering-system/api/ 2>/dev/null | head; ls /opt/agentic-engineering-system/src/ui/ 2>/dev/null | head"),
    ("MODEL_TIMEOUT source",
     "cd /opt/agentic-engineering-system && grep -rn 'MODEL_TIMEOUT' --include='*.py' --include='*.js' . 2>/dev/null | grep -v '.venv' | head -8"),
    ("capability route in backend",
     "cd /opt/agentic-engineering-system && grep -rn -iE '(capabilities|readiness|selfcheck|self_check|system_check|environment)' api/ --include='*.py' 2>/dev/null | grep -iE 'def |route|@|path' | head -15"),
    ("frontend check calls",
     "cd /opt/agentic-engineering-system && grep -n -oE \"(fetch|api)[^\\\"]*\\\"[^\\\"]*(check|capab|readiness|probe|env)[^\\\"]*\\\"\" src/ui/*.js src/ui/*.html 2>/dev/null | head -15"),
    ("frontend api paths general",
     "cd /opt/agentic-engineering-system && grep -oE \"'/api/[a-z0-9_/{}-]*'|\\\"/api/[a-z0-9_/{}-]*\\\"\" src/ui/app.js 2>/dev/null | sort -u | head -40"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        for title, cmd in CMDS:
            _, o, e = c.exec_command(cmd, timeout=50)
            o.channel.recv_exit_status()
            out = o.read().decode("utf-8", "replace").strip()
            err = e.read().decode("utf-8", "replace").strip()
            print(f"### {title}")
            if out:
                print(out[:3000])
            if err and not out:
                print(f"[stderr] {err[:400]}")
            print(flush=True)
    finally:
        c.close()


if __name__ == "__main__":
    main()
