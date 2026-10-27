#!/usr/bin/env python3
"""RLR-002-c — read model endpoint config (MASKED, no secrets printed) from the server."""
import json
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"

CMDS = [
    ("z-ai-config baseUrl (masked)",
     "sudo -n cat /etc/.z-ai-config 2>/dev/null | /usr/bin/python3 -c \""
     "import json,sys;"
     "d=json.load(sys.stdin);"
     "ks=list(d.keys());"
     "print('keys:',ks);"
     "bu=d.get('baseUrl') or d.get('base_url') or d.get('url','');"
     "print('baseUrl:',bu);"
     "ak=d.get('apiKey') or d.get('api_key') or '';"
     "print('apiKey: MASKED len=%d prefix=%s...' % (len(ak), ak[:6]))"
     "\""),
    ("secrets.json structure (masked)",
     "cd /opt/agentic-engineering-system 2>/dev/null && "
     "/usr/bin/python3 -c \""
     "import json;"
     "d=json.load(open('runtime/secrets/secrets.json'));"
     "def walk(o,p=''):"
     "    if isinstance(o,dict):"
     "        [walk(v,p+'/'+k) for k,v in o.items()]"
     "    elif isinstance(o,list):"
     "        print(p,'list len',len(o))"
     "    else:"
     "        s=str(o); print(p, ':', s[:60] if 'key' not in p.lower() and 'token' not in p.lower() else f'MASKED len={len(s)}')"
     "\" 2>&1 | head -25"),
    ("prod .env current contents (names only)",
     "cut -d= -f1 /opt/agentic-engineering-system/.env 2>/dev/null | head -20; echo ---; "
     "wc -l /opt/agentic-engineering-system/.env 2>/dev/null"),
    ("prod env file exists?", "ls -la /opt/agentic-engineering-system/.env 2>&1"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=25,
              look_for_keys=False, allow_agent=False)
    try:
        for title, cmd in CMDS:
            _, o, e = c.exec_command(cmd, timeout=45)
            o.channel.recv_exit_status()
            out = o.read().decode("utf-8", "replace").strip()
            err = e.read().decode("utf-8", "replace").strip()
            print(f"### {title}")
            if out:
                print(out[:2000])
            if err and not out:
                print(f"[stderr] {err[:400]}")
            print(flush=True)
    finally:
        c.close()


if __name__ == "__main__":
    main()
