# -*- coding: utf-8 -*-
"""P3-NPM-DIAG — تشخيص قراءة-فقط لتوقف المشروع #3 عند الخطوة 103 (npm).

يجمع عبر SSH (بلا أي تغيير إنتاجي):
  A) حالة الخدمات + /health
  B) توفر node/npm على المضيف (كل المسارات الشائعة)
  C) القاعدة: الوظيفة، الخطوة 103، التنفيذات الأخيرة، بوابات المالك،
     استدعاءات أدوات دورات step-103، سجلات الأدلة وأحكامها
  D) سجل الأخطاء الأخيرة + الكلمات المفتاحية للبوابة/التصنيف
  E) أدوات المنفذ الحي المتاحة (خطة الأدوات)
المخرجات: JSON في download/aes-remediation/P3-NPM-DIAG/diag_readonly.json
"""
import json
import os
import sys

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"

REMOTE_PY = r'''
import sqlite3, json
DB = "file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro"
con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row

def trunc(v):
    s = str(v)
    return s if len(s) <= 400 else s[:400] + "…<%d chars>" % len(s)

def rows(table, where="", order="", limit=10):
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]
        if not cols:
            return [{"error": "no table " + table}]
        sel = ", ".join('"%s"' % c for c in cols)
        q = "SELECT %s FROM %s %s %s LIMIT %d" % (sel, table, where, order, limit)
        out = []
        for r in con.execute(q):
            d = {}
            for c in cols:
                try:
                    d[c] = trunc(r[c])
                except Exception:
                    d[c] = None
            out.append(d)
        return out
    except Exception as e:
        return [{"error": str(e)}]

out = {
  "project": rows("projects", "WHERE id=3", "", 2),
  "job_p3": rows("engineering_jobs", "WHERE project_id=3", "ORDER BY id DESC", 2),
  "step_103": rows("steps", "WHERE id=103", "", 2),
  "steps_p3_all": rows("steps", "WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3)", "ORDER BY id", 30),
  "gates_p3": rows("owner_gates", "WHERE project_id=3", "ORDER BY id DESC", 8),
  "executions_103": rows("executions", "WHERE step_id=103", "ORDER BY id DESC", 8),
  "executions_recent": rows("executions", "", "ORDER BY id DESC", 8),
  "tools_step103": rows("tool_invocations", "WHERE record_json LIKE '%step-103%'", "ORDER BY id DESC", 30),
  "tools_recent": rows("tool_invocations", "", "ORDER BY id DESC", 25),
  "evidence_recent": rows("evidence_records", "", "ORDER BY id DESC", 12),
  "events_recent": rows("events", "WHERE payload_json LIKE '%project_id%'", "ORDER BY id DESC", 15),
}
print("DIAG-JSON:" + json.dumps(out, ensure_ascii=False, default=str))
'''

CMD_LIST = [
    ("services", "systemctl is-active agentic searxng search-api nginx; true"),
    ("health", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health; echo"),
    ("node_probe", "for c in node nodejs npm npx; do printf '%s: ' $c; command -v $c || echo MISSING; done; echo '---'; ls -d /usr/local/bin/node* /usr/bin/node* /opt/node* 2>/dev/null || echo NO-NODE-DIRS; echo '---'; cat /etc/os-release | head -2"),
    ("pkg_node", "rpm -qa 2>/dev/null | grep -iE 'nodejs|npm' | head -5 || echo NO-RPM-NODE"),
    ("step103_ls", "sudo -n ls -la /opt/agentic-engineering-system/runtime/projects/3/steps/103/ 2>&1 | head -25"),
    ("workspace_ls", "sudo -n ls -la /opt/agentic-engineering-system/runtime/projects/3/ 2>&1 | head -25"),
    ("journal_err", "sudo -n journalctl -u agentic --since '-6 hours' --no-pager -p err 2>/dev/null | tail -25"),
    ("journal_grep", "sudo -n journalctl -u agentic --since '-6 hours' --no-pager 2>/dev/null | grep -iE 'step.?103|npm|node_modules|PLAN_REVISION|INSUFFICIENT|ESCALAT|classify|environmental|GATE' | tail -40"),
    ("prod_head", "cd /opt/agentic-engineering-system && sudo -n git log --oneline -3 && sudo -n git status --short | head -10"),
]


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY, timeout=25)
    collected = {}
    for name, cmd in CMD_LIST:
        try:
            _, stdout, stderr = client.exec_command(cmd, timeout=60)
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            collected[name] = {"out": out[-5000:], "err": err[-800:]}
        except Exception as exc:  # noqa: BLE001
            collected[name] = {"out": "", "err": "SSH-ERROR: %s" % exc}
    try:
        _, stdout, stderr = client.exec_command(
            "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % REMOTE_PY, timeout=90)
        dbout = stdout.read().decode("utf-8", "replace")
        dberr = stderr.read().decode("utf-8", "replace")
        marker = dbout.find("DIAG-JSON:")
        if marker >= 0:
            collected["db"] = json.loads(dbout[marker + len("DIAG-JSON:"):])
        else:
            collected["db"] = {"error": (dbout[-2000:] + "|STDERR:" + dberr[-2000:])}
    except Exception as exc:  # noqa: BLE001
        collected["db"] = {"error": "SSH-ERROR: %s" % exc}
    client.close()

    dest = "/home/z/my-project/download/aes-remediation/P3-NPM-DIAG/diag_readonly.json"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(collected, fh, ensure_ascii=False, indent=1, default=str)

    print("== SERVICES:", collected["services"]["out"].strip().replace("\n", " | "))
    print("== HEALTH:", collected["health"]["out"].strip())
    print("== NODE PROBE:\n" + collected["node_probe"]["out"].strip()[:600])
    print("== RPM NODE:", collected["pkg_node"]["out"].strip()[:200])
    db = collected.get("db", {})
    if isinstance(db, dict) and "error" not in db:
        for p in db.get("project", [])[:1]:
            print("== PROJECT#%s %s status=%s current_step=%s updated=%s" % (
                p.get("id"), p.get("name"), p.get("status"),
                p.get("current_step_id"), p.get("updated_at")))
        for j in db.get("job_p3", [])[:1]:
            print("== JOB#%s status=%s waiting=%s hb=%s" % (
                j.get("id"), j.get("status"), j.get("waiting_kind"),
                j.get("heartbeat_at")))
            print("   waiting_detail:", (j.get("waiting_detail") or "")[:500])
        for s in db.get("step_103", [])[:1]:
            print("== STEP#%s [%s] status=%s attempts=%s completed=%s" % (
                s.get("id"), (s.get("title") or s.get("objective") or "")[:60],
                s.get("status"), s.get("attempts"), s.get("completed_at")))
        for g in db.get("gates_p3", [])[:5]:
            print("== GATE#%s kind=%s status=%s created=%s resolved=%s" % (
                g.get("id"), g.get("kind"), g.get("status"),
                (g.get("created_at") or "")[:19], (g.get("resolved_at") or "")[:19]))
            print("   reason:", (g.get("reason") or "")[:300])
            print("   details:", (g.get("details") or "")[:400])
        for e in db.get("executions_103", [])[:6]:
            print("== EXEC#%s step=%s attempt=%s status=%s %s→%s err=%.200s" % (
                e.get("id"), e.get("step_id"), e.get("attempt"),
                e.get("status"), (e.get("started_at") or "")[:19],
                (e.get("finished_at") or "")[:19], (e.get("error") or "").replace("\n", " ")))
        for t in (db.get("tools_step103") or db.get("tools_recent") or [])[:12]:
            print("== TOOL#%s %s %s/%s cls=%s %.80s %s" % (
                t.get("id"), t.get("tool"), t.get("status"),
                t.get("result_status"), t.get("failure_class"),
                (t.get("query") or "").replace("\n", " "),
                (t.get("created_at") or "")[:19]))
        for ev in db.get("evidence_recent", [])[:6]:
            print("== EVID#%s exec=%s step=%s verdict=%s" % (
                ev.get("id"), ev.get("execution_id"), ev.get("step_id"),
                ev.get("verdict")))
    else:
        print("== DB ERROR:", str(db.get("error"))[:600])
    print("\n== STEP103 LS:\n" + collected["step103_ls"]["out"][:900])
    print("\n== JOURNAL GREP (last 25):\n" + "\n".join(
        collected["journal_grep"]["out"].splitlines()[-25:]))
    print("\n== PROD HEAD:\n" + collected["prod_head"]["out"][:400])
    print("\nFULL JSON →", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
