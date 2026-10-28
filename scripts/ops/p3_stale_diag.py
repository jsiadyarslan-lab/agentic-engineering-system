# -*- coding: utf-8 -*-
"""P3-STALE-DIAG — تشخيص قراءة-فقط لعائق المشروع #3 (web_search STALE + الوظيفة المنتظرة).

يجمع عبر SSH (بلا أي تغيير إنتاجي):
  A) حالة الخدمات + /health + المنافذ
  B) ركيزة bwrap على المضيف (نسخة + إطلاق حقيقي)
  C) قاعدة البيانات: الوظيفة، البيئات، المزودون، القدرات، الخطوات،
     استدعاءات الأدوات، الأحداث، بوابات المالك
  D) سجل الأخطاء الأخيرة + الكلمات المفتاحية للبوابة
  E) جاهزية القدرات عبر API التطبيق (STALE مطبقة)
  F) محتوى مسار الخطوة 102
كل المخرجات JSON واحد في stdout + نسخة في download/aes-remediation/P3-STALE-DIAG/
"""
import json
import sys
import time

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"

REMOTE_PY = r'''
import sqlite3, json, datetime
DB = "file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro"
con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row

def trunc(v):
    s = str(v)
    return s if len(s) <= 260 else s[:260] + "…<%d chars>" % len(s)

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
  "jobs_p3": rows("engineering_jobs", "WHERE project_id=3", "ORDER BY id DESC", 3),
  "envs": rows("execution_environments", "", "ORDER BY id", 10),
  "providers": rows("research_providers", "", "ORDER BY id", 10),
  "caps": rows("capability_records", "", "ORDER BY capability_id", 30),
  "steps_p3_recent": rows("steps", "WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3)", "ORDER BY id DESC", 8),
  "tools_recent": rows("tool_invocations", "", "ORDER BY id DESC", 14),
  "events_p3": rows("events", "WHERE payload_json LIKE '%\"project_id\": 3%' OR payload_json LIKE '%\"project_id\":3%'", "ORDER BY id DESC", 12),
  "gates_p3": rows("owner_gates", "WHERE project_id=3", "ORDER BY id DESC", 6),
  "executions_p3": rows("executions", "WHERE step_id=(SELECT MAX(id) FROM steps)", "ORDER BY id DESC", 3),
}
print("DIAG-JSON:" + json.dumps(out, ensure_ascii=False, default=str))
'''

CMD_LIST = [
    ("services", "systemctl is-active agentic searxng search-api nginx; true"),
    ("health", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health; echo"),
    ("ports", "sudo -n ss -tlnp | grep -E ':(8010|8888|8098)\\s' | awk '{print $4, $6}'"),
    ("bwrap_version", "bwrap --version 2>&1 || echo NO-BWRAP"),
    ("bwrap_launch", "timeout 10 bwrap --ro-bind / / --proc /proc --dev /dev echo bwrap-launch-ok 2>&1 || echo BWRAP-LAUNCH-FAILED"),
    ("agentic_user", "ps -o user=,pid=,etimes= -p $(systemctl show -p MainPID --value agentic) 2>/dev/null || true"),
    ("readiness_api", "curl -s http://127.0.0.1:8010/api/environment/readiness | head -c 4000; echo"),
    ("step102_ls", "sudo -n ls -la /opt/agentic-engineering-system/runtime/projects/3/steps/102/ 2>&1 | head -20"),
    ("workspace_ls", "sudo -n ls -la /opt/agentic-engineering-system/runtime/projects/3/ 2>&1 | head -25"),
    ("journal_err", "sudo -n journalctl -u agentic --since '-8 hours' --no-pager -p err 2>/dev/null | tail -25"),
    ("journal_grep", "sudo -n journalctl -u agentic --since '-8 hours' --no-pager 2>/dev/null | grep -iE 'STALE|POLICY_BLOCK|ESCALAT|INSUFFICIENT|GATE|heartbeat' | tail -30"),
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
            collected[name] = {"out": out[-4000:], "err": err[-800:]}
        except Exception as exc:  # noqa: BLE001
            collected[name] = {"out": "", "err": "SSH-ERROR: %s" % exc}
    try:
        _, stdout, _ = client.exec_command(
            "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % REMOTE_PY, timeout=90)
        dbout = stdout.read().decode("utf-8", "replace")
        marker = dbout.find("DIAG-JSON:")
        if marker >= 0:
            collected["db"] = json.loads(dbout[marker + len("DIAG-JSON:"):])
        else:
            collected["db"] = {"error": dbout[-3000:]}
    except Exception as exc:  # noqa: BLE001
        collected["db"] = {"error": "SSH-ERROR: %s" % exc}
    client.close()

    dest = "/home/z/my-project/download/aes-remediation/P3-STALE-DIAG/diag_readonly.json"
    import os
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(collected, fh, ensure_ascii=False, indent=1, default=str)

    # ---- ملخص سريع للقراءة ----
    print("== SERVICES:", collected["services"]["out"].strip().replace("\n", " | "))
    print("== HEALTH:", collected["health"]["out"].strip())
    print("== BWRAP:", collected["bwrap_version"]["out"].strip(),
          "/", collected["bwrap_launch"]["out"].strip().replace("\n", " "))
    print("== PORTS:", collected["ports"]["out"].strip().replace("\n", " ; "))
    db = collected.get("db", {})
    if isinstance(db, dict) and "error" not in db:
        for job in db.get("jobs_p3", [])[:2]:
            print("== JOB#%s status=%s waiting=%s step=%s hb=%s retries=%s" % (
                job.get("id"), job.get("status"), job.get("waiting_kind"),
                job.get("current_step_id"), job.get("heartbeat_at"),
                job.get("retries")))
            det = job.get("waiting_detail") or ""
            print("   waiting_detail:", det[:400])
        for env in db.get("envs", []):
            print("== ENV#%s %s backend=%s status=%s sandboxed=%s verified=%s reason=%s" % (
                env.get("id"), env.get("name"), env.get("backend"),
                env.get("status"), env.get("sandboxed"),
                env.get("last_verified_at"), (env.get("failure_reason") or "")[:160]))
        for p in db.get("providers", []):
            print("== PROVIDER#%s %s kind=%s enabled=%s probe=%s at=%s" % (
                p.get("id"), p.get("name"), p.get("kind"), p.get("enabled"),
                p.get("last_probe_status"), p.get("last_probe_at")))
        for c in db.get("caps", []):
            if c.get("capability_id") in ("web_search", "web_fetch", "sandbox",
                                          "llm", "network_dns", "network_https",
                                          "persistence", "filesystem", "shell"):
                print("== CAP %-16s status=%-9s probe_at=%s expires=%s" % (
                    c.get("capability_id"), c.get("readiness_status"),
                    c.get("last_probe_at"), c.get("expires_at")))
        for s in db.get("steps_p3_recent", [])[:5]:
            print("== STEP#%s %s status=%s evid=%s" % (
                s.get("id"), (s.get("title") or "")[:60], s.get("status"),
                s.get("evidence_count")))
        for t in db.get("tools_recent", [])[:8]:
            print("== TOOL#%s %s %s/%s cls=%s stage=%s q=%.50s n=%s %s" % (
                t.get("id"), t.get("tool"), t.get("status"),
                t.get("result_status"), t.get("failure_class"),
                t.get("failure_stage"), (t.get("query") or "").replace("\n", " "),
                t.get("result_count"), (t.get("created_at") or "")[:19]))
        for g in db.get("gates_p3", [])[:4]:
            print("== GATE#%s kind=%s status=%s %s" % (
                g.get("id"), g.get("kind"), g.get("status"),
                str(g.get("reason") or g.get("question") or "")[:200]))
    else:
        print("== DB ERROR:", str(db.get("error"))[:500])
    print("\n== READINESS API (first 1200):")
    print(collected["readiness_api"]["out"][:1200])
    print("\n== STEP102 LS:")
    print(collected["step102_ls"]["out"][:800])
    print("\n== JOURNAL GREP (last 15 lines):")
    print("\n".join(collected["journal_grep"]["out"].splitlines()[-15:]))
    print("\nFULL JSON →", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
