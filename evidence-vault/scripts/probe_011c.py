#!/usr/bin/env python3
"""AES-011 — Phase 3: full per-asset status for the owner's post-deploy session."""
import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/home/z/.ssh_key_010"

def sh(c, cmd, t=60):
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode("utf-8", "replace").strip(),
            e.read().decode("utf-8", "replace").strip())

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY, timeout=20,
              look_for_keys=False, allow_agent=False)

    print("===== owner session 19:56-20:09 — every /static request with status =====")
    out, _ = sh(c, "sudo -n journalctl -u agentic.service --since '2026-10-25 19:56' "
                   "--until '2026-10-25 20:09' --no-pager 2>/dev/null | "
                   "grep '2.215.157.88' | grep -E 'GET /static|GET / HTTP|GET /index' | "
                   "sed 's/.*INFO:     2.215.157.88:0 - //'")
    print(out or "(none)")

    print("\n===== changed-file status summary (14 redesigned files) =====")
    changed = ["app-shell.css", "app.js", "chat-stream.js", "control-center.css",
               "factory-control.css", "factory-control.js", "harness.css",
               "live.css", "project-live.css", "projects.css", "styles.css",
               "task-cards.js", "theme.css"]
    out, _ = sh(c, "sudo -n journalctl -u agentic.service --since '2026-10-25 19:56' "
                   "--until '2026-10-25 20:09' --no-pager 2>/dev/null | grep '2.215.157.88'")
    lines = out.splitlines()
    import re
    for f in changed:
        sts = [re.search(r'"(GET|HEAD) [^"]*' + re.escape(f) + r'[^"]*" (\d+)', l)
               for l in lines if f in l]
        codes = [m.group(2) for m in sts if m]
        print(f"{f:24s} -> {codes if codes else 'NOT REQUESTED'}")

    print("\n===== owner first-entry / page navigations (GET / with referer or not) =====")
    navs = [l for l in lines if re.search(r'"GET / HTTP', l)]
    print("\n".join(navs[-8:]) or "(none)")

    print("\n===== any 5xx in window =====")
    errs = [l for l in lines if re.search(r'" (5\d\d)', l)]
    print("\n".join(errs[:10]) or "(no 5xx)")

    print("\n===== last-modified/etag of served theme.css vs old? check journal HEAD requests =====")
    out, _ = sh(c, "curl -s --max-time 6 -o /dev/null -D - 'http://127.0.0.1:8010/static/theme.css?v=4.0.0' | tr -d '\\r' | grep -iE 'etag|last-modified|content-length'")
    print(out)
    c.close()

if __name__ == "__main__":
    main()
