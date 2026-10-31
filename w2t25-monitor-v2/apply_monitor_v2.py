#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T25 MONITOR v2 deployment (runs ON the server as opc).
Surgical patch of /home/opc/w2t25_monitor.py:
  1) backup -> w2t25_monitor.py.bak_v1
  2) insert build_now() before class H
  3) add /api/now route after /api/status route
  4) replace INDEX with control-room HTML (raw string, backslashes preserved)
  5) py_compile, restart systemd unit, verify endpoints
Rollback: cp /home/opc/w2t25_monitor.py.bak_v1 /home/opc/w2t25_monitor.py && sudo systemctl restart w2t25-monitor.service
"""
import io, os, subprocess, sys, time

SRC = "/home/opc/w2t25_monitor.py"
BAK = "/home/opc/w2t25_monitor.py.bak_v1"
HTML = "/home/opc/monitor_v2_index.html"
TOKEN = "c9a39cb0a520d0d380c5136ca86b18f5"

BUILD_NOW = '''

def build_now():
    """W2-T25 v2: unified control-room payload — everything the page needs in ONE call.
    Read-only (DB mode=ro + filesystem reads). Never writes to the factory."""
    with _lock:
        t0, cached = _cache.get("now", (0, None))
        if cached is not None and now_utc() - t0 < 2:
            return cached
    out = {"server_now": int(now_utc())}
    p = q("SELECT id,name,status,current_step_id,current_phase_id,current_plan_id,last_error,updated_at FROM projects WHERE id=3")
    out["project"] = p[0] if p else {}
    j = q("SELECT status,waiting_kind,waiting_detail,current_step_id,current_role,retries,attempt,heartbeat_at,last_error,tick_count FROM engineering_jobs WHERE project_id=3 ORDER BY id DESC LIMIT 1")
    out["job"] = j[0] if j else {}
    out["heartbeat_age"] = age_of(out["job"].get("heartbeat_at"))
    csid = out["project"].get("current_step_id")
    out["cur_step"] = q("SELECT id,phase_id,ordinal,status,attempts,updated_at FROM steps WHERE id=?", (csid,))[0] if csid else {}
    out["cur_step_full"] = q("SELECT id,objective,input,expected_output,acceptance_criteria,status,attempts,last_error,updated_at FROM steps WHERE id=?", (csid,))[0] if csid else {}
    phid = out["project"].get("current_phase_id")
    out["cur_phase"] = q("SELECT id,plan_id,ordinal,title,status FROM phases WHERE id=?", (phid,))[0] if phid else {}
    plid = out["project"].get("current_plan_id")
    out["cur_plan"] = q("SELECT id,version,status,revision_reason,approved_at FROM plans WHERE id=?", (plid,))[0] if plid else {}
    out["gates"] = q("SELECT id,kind,status,reason,created_at,resolved_at FROM owner_gates WHERE project_id=3 ORDER BY id DESC LIMIT 6")
    out["counts"] = {}
    try:
        con = db()
        out["counts"]["steps_total"] = con.execute("SELECT count(*) FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3)").fetchone()[0]
        out["counts"]["steps_done"] = con.execute("SELECT count(*) FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3) AND status='COMPLETED'").fetchone()[0]
        out["counts"]["steps_failed"] = con.execute("SELECT count(*) FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3) AND status='FAILED'").fetchone()[0]
        out["counts"]["phases_total"] = con.execute("SELECT count(*) FROM phases WHERE project_id=3").fetchone()[0]
        out["counts"]["phases_done"] = con.execute("SELECT count(*) FROM phases WHERE project_id=3 AND status='COMPLETED'").fetchone()[0]
        out["counts"]["plans_total"] = con.execute("SELECT count(*) FROM plans WHERE project_id=3").fetchone()[0]
        con.close()
    except Exception:
        pass
    exe = q("SELECT id,step_id,attempt,status,agent_role,command,started_at,finished_at,provider,model FROM executions ORDER BY id DESC LIMIT 1")
    out["cur_exec_full"] = exe[0] if exe else {}
    out["recent_tools"] = q("SELECT id,tool,status,result_status,failure_class,failure_reason,query,duration_ms,created_at FROM tool_invocations ORDER BY id DESC LIMIT 15")
    out["story"] = q("SELECT id,kind,payload,created_at FROM project_events WHERE project_id=3 ORDER BY id DESC LIMIT 14")
    out["recent_closed"] = q("SELECT id,status,attempts,objective,completed_at FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3) AND completed_at IS NOT NULL ORDER BY id DESC LIMIT 12")
    out["errors"] = q("SELECT id,ordinal,status,attempts,last_error,updated_at FROM steps WHERE phase_id IN (SELECT id FROM phases WHERE project_id=3) AND COALESCE(last_error,'')<>'' ORDER BY updated_at DESC LIMIT 6")
    if csid:
        out["step_files"] = step_files(csid)
        out["cur_evidence"] = {}
        try:
            with open(os.path.join(STEPS_BASE, str(csid), "evidence.json"), "r", errors="replace") as fh:
                ev = json.load(fh)
            tc = ev.get("tool_calls") or []
            if len(tc) > 30:
                ev = dict(ev)
                ev["tool_calls"] = tc[-30:]
            out["cur_evidence"] = ev
        except Exception:
            pass
        raws = []
        try:
            pdir = os.path.join(STEPS_BASE, str(csid))
            for fn in os.listdir(pdir):
                if fn.startswith(("stdout-", "stderr-")):
                    fp = os.path.join(pdir, fn)
                    try:
                        st = os.stat(fp)
                    except Exception:
                        continue
                    if st.st_size == 0 or st.st_size > 200000:
                        continue
                    try:
                        with open(fp, "r", errors="replace") as fh:
                            txt = fh.read(1500)
                        raws.append({"name": fn, "text": txt, "size": st.st_size, "age": int(now_utc() - st.st_mtime)})
                    except Exception:
                        pass
            raws.sort(key=lambda x: -x["age"])
        except Exception:
            pass
        out["raw_outputs"] = raws[:6]
    try:
        t = get_tree()
        out["merged_files_count"] = len(t["files"])
        out["merged_html_count"] = len([k for k in t["files"] if k.endswith(".html")])
    except Exception:
        pass
    try:
        r = subprocess.run(["pgrep", "-f", "w2t25_server_drive.py"], capture_output=True, timeout=4)
        alive = r.returncode == 0
    except Exception:
        alive = False
    log_age = None
    try:
        log_age = int(now_utc() - os.path.getmtime(DRIVE_LOG))
    except Exception:
        pass
    out["driver"] = {"alive": alive, "log_age": log_age}
    with _lock:
        _cache["now"] = (now_utc(), out)
    return out

'''

ROUTE_OLD = '''        if path == "/api/status":
            self._json(build_status(), cookie=want_cookie)
            return
'''
ROUTE_NEW = ROUTE_OLD + '''        if path == "/api/now":
            self._json(build_now(), cookie=want_cookie)
            return
'''
CLASS_MARK = "class H(BaseHTTPRequestHandler):"


def main():
    with io.open(SRC, "r", encoding="utf-8") as f:
        src = f.read()
    if "/api/now" in src:
        print("PATCH-ALREADY-APPLIED"); return 0
    for mark, what in ((CLASS_MARK, "class H"), (ROUTE_OLD, "/api/status route block"), ('INDEX = """', "INDEX start")):
        if src.count(mark) < 1:
            print("MARKER-MISSING:", what); return 1
    if src.count(ROUTE_OLD) != 1:
        print("ROUTE-BLOCK-NOT-UNIQUE", src.count(ROUTE_OLD)); return 1
    with io.open(HTML, "r", encoding="utf-8") as f:
        html = f.read()
    if '"""' in html:
        print("HTML-CONTAINS-TRIPLE-QUOTE — abort"); return 1
    if html.rstrip().endswith("\\"):
        print("HTML-ENDS-BACKSLASH — abort"); return 1

    # backup
    with io.open(BAK, "w", encoding="utf-8") as f:
        f.write(src)
    print("backup ->", BAK, len(src), "bytes")

    # 1) insert build_now before class H
    i = src.index(CLASS_MARK)
    src = src[:i] + BUILD_NOW + src[i:]
    # 2) insert route
    src = src.replace(ROUTE_OLD, ROUTE_NEW, 1)
    # 3) replace INDEX string
    a = src.index('INDEX = """')
    b = src.index('"""', a + len('INDEX = """')) + 3
    new_index = 'INDEX = r"""' + html.rstrip() + '\n"""'
    src = src[:a] + new_index + src[b:]
    # sanity
    assert src.count("def build_now()") == 1
    assert '"/api/now"' in src
    with io.open(SRC, "w", encoding="utf-8") as f:
        f.write(src)
    print("patched:", len(src), "bytes")

    # compile check
    r = subprocess.run([sys.executable, "-m", "py_compile", SRC], capture_output=True, text=True)
    print("py_compile rc=", r.returncode, r.stderr[:400])
    if r.returncode != 0:
        with io.open(BAK, "r", encoding="utf-8") as f:
            orig = f.read()
        with io.open(SRC, "w", encoding="utf-8") as f:
            f.write(orig)
        print("ROLLED-BACK (compile failed)")
        return 1

    # restart
    r = subprocess.run(["sudo", "-n", "systemctl", "restart", "w2t25-monitor.service"], capture_output=True, text=True)
    print("restart rc=", r.returncode, r.stderr[:200])
    time.sleep(3)
    # verify
    checks = [
        ("healthz", 'curl -s -m 6 http://127.0.0.1:8765/healthz'),
        ("page-v2", 'curl -s -m 8 "http://127.0.0.1:8765/?k=%s" | grep -c "غرفة التحكم"' % TOKEN),
        ("api-now", 'curl -s -m 8 "http://127.0.0.1:8765/api/now?k=%s" | head -c 300' % TOKEN),
        ("api-status", 'curl -s -m 8 "http://127.0.0.1:8765/api/status?k=%s" | head -c 160' % TOKEN),
        ("api-steps", 'curl -s -m 8 "http://127.0.0.1:8765/api/steps?k=%s" | head -c 120' % TOKEN),
        ("preview", 'curl -s -m 8 -o /dev/null -w "%%{http_code}" "http://127.0.0.1:8765/preview/index.html?k=%s"' % TOKEN),
        ("nginx-path", 'curl -s -m 8 "http://127.0.0.1/w2t25-monitor/api/now?k=%s" | head -c 200' % TOKEN),
        ("service", 'systemctl is-active w2t25-monitor.service'),
    ]
    for name, cmd in checks:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        print("[check]", name, "=>", (r.stdout or r.stderr).strip()[:300])
    print("DEPLOY-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
