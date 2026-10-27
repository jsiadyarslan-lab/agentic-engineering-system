#!/usr/bin/env python3
"""RLR-002-d — find production capability-check endpoints + model router config path."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

CMDS = [
    ("prod secrets vault",
     "ls -la /opt/agentic-engineering-system/runtime/secrets/ 2>&1; "
     "sudo -n cat /opt/agentic-engineering-system/runtime/secrets/secrets.json 2>/dev/null | head -c 200; echo"),
    ("etc z-ai-config",
     "sudo -n ls -la /etc/.z-ai-config 2>&1; sudo -n head -c 80 /etc/.z-ai-config 2>&1 | sed -E 's/(nvapi-|sk-)[A-Za-z0-9_-]+/\\1****MASKED/g'"),
    ("capability endpoints in api",
     "cd /opt/agentic-engineering-system && grep -rn 'capabilit\\|readiness\\|probe' api/routes*.py api/routes/ 2>/dev/null | grep -iE 'router|@|def ' | head -20"),
    ("llm/model check endpoints",
     "cd /opt/agentic-engineering-system && grep -rn -iE '@(app|router)\\.(get|post).*(check|capab|readiness|health|probe|llm|model)' api/ 2>/dev/null | head -20"),
    ("search provider check endpoints",
     "cd /opt/agentic-engineering-system && grep -rn -iE '(ddg|duck|bing|wikipedia|searx)' api/ 2>/dev/null | grep -iE '@|def ' | head -12"),
    ("model router baseUrl source",
     "cd /opt/agentic-engineering-system && grep -rn 'baseUrl\\|base_url\\|integrate.api' src/*/model_router*.py src/model_router*.py src/llm/*.py 2>/dev/null | grep -v test | head -12"),
    ("env var proxy handling",
     "cd /opt/agentic-engineering-system && grep -rn 'https_proxy\\|HTTPS_PROXY\\|proxy' src/llm/*.py src/*/provider*.py 2>/dev/null | head -10"),
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
                print(out[:2500])
            if err and not out:
                print(f"[stderr] {err[:400]}")
            print(flush=True)
    finally:
        c.close()


if __name__ == "__main__":
    main()
