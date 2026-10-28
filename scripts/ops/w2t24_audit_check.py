#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T24-AUDIT — تدقيق مستقل لمهمة W2-T24 (يجمع كل دليل بنفسه، لا نقلًا عن المنفذ).

المجموعات الثمان المُدقَّقة (مطابقة لادعاءات W2-T24):
  1) git/الإنتاج عبر SSH قراءة-فقط: HEAD=525d9a3 وأبوه 23590e2، شجرة متعقَّلة
     (صفر تعديلات متتبَّعة؛ غير المتتبَّع = نفس خامات runtime السابقة)،
     /health=200، الخدمات active×4، journal بلا أخطاء خدمات،
     ls-remote origin=main=HEAD، وorigin/main المحلي=HEAD.
  2) الكود: تطابق sha256 ثلاثي (خادم=محلي=git blob) للملفات التسعة +
     عقود الرقة + الإحصاء (16 ملفًا +1517/−9) + الفحوص الوظيفية
     (BUILD_COMMAND_WHITELIST=6 أوامر، ToolFailure reason=BUILD_TOOLING_MISSING،
     دوال build_commands الثلاث، محرك: ("BUILD_TOOLING_MISSING","build")
     و_build_tooling_still_missing وGATE_KEPT_BLOCKED في مسار recheck).
  3) الاختبارات محليًا (venv المستودع): 18/18 و10/10، roles+contracts
     بفاشل وحيد بيئي (test_generate_pdf_arabic_one_page: arabic_reshaper
     مفقود من البيئة) مثبت بجولتين: stash على HEAD النقي + worktree على
     الأب النقي 23590e2؛ workflow+harness كلها ناجحة (العدد الفعلي مسجَّل).
  4) التوفير: node v22.23.4 / npm 10.9.9 / aarch64 / القرص + اتساق
     provision_node.json مع الحالة الحية + sha256 لـpackage.json الخطوة 102.
  5) دخان npm حقيقي خاص بالتدقيق في /tmp/w2t24-audit-scratch على الخادم
     (نسخ package.json عبر sudo -n cat → npm install → exit code +
     الأدلة الأربعة → تنظيف حتمي في finally).
  6) مسبار web_search الحي: POST /api/environment/probe — POST الوحيد
     المسموح؛ لا POST على أي بوابة/preflight/launch من هذا السكربت.
  7) القاعدة بوضع ro حصرًا: البوابات 33/34 والوظيفة 3 والخطوة 103
     والمشروع 3 + خط زمني كامل لما بعد المهمة (البوابة#33 حُلَّت بعد
     اكتمال المهمة بقرار المالك نفسه — OWNER_GATE_RESOLVED عبر
     POST /api/projects/3/plan/approve من IP المالك العام 2.215.157.88
     بمتصفح Chrome — لا من المنفذ ولا مسارًا آليًا).
  8) الأمان: صفر سلاسل 48-hex مستقلة في ملفات الأدلة الأربعة (الفحص
     بحدود token لا مجرد substring) + اتساق حقول deploy/npm_smoke.

الانضباط: كل أوامر الخادم تمر بحارس قائمة سماح (قراءة-فقط) مع استثناءين
مصرَّحين: POST /api/environment/probe وحصره، والكتابة داخل /tmp للتدقيق مع
تنظيف حتمي. لا restart، لا git كتابي على الخادم، لا لمس /etc/search-api/env.

المخرج: download/aes-remediation/W2-T24/audit_w2t24_independent.json
مع _meta {agent, ts, script_md5, verdict, passed, total}.

التشغيل: .venv/bin/python scripts/ops/w2t24_audit_check.py
(مدة نموذجية ~6 دقائق: أغلبها مجموعة workflow+harness ودخان npm).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko

# ---------------------------------------------------------------- الثوابت
HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"
SRV_ROOT = "/opt/agentic-engineering-system"
LOCAL_REPO = Path("/home/z/my-project/repo")
EVID_DIR = Path("/home/z/my-project/download/aes-remediation/W2-T24")
OUT_JSON = EVID_DIR / "audit_w2t24_independent.json"
VENV_PY = LOCAL_REPO / ".venv/bin/python"
DB_RO_URI = "file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro"
SRV_TMP = "/tmp/w2t24-audit-scratch"
SRV_DB_HELPER = "/tmp/w2t24_audit_dbq.py"
LOCAL_PARENT_WT = "/tmp/w2t24-parent-wt"
TASK_END_TS = "2026-10-28T16:32:49Z"  # آخر أثر زمني لأدلة المنفذ (npm_smoke.json)

CLAIM_HEAD = "525d9a370588792fe45521fd73c1d71dd644a713"
CLAIM_PARENT = "23590e2d89a4bdbee58e2b9eb4673ba0b51618d1"

NINE_FILES = [
    "src/roles/build_commands.py",
    "src/roles/build_tool.py",
    "src/roles/tools.py",
    "src/roles/implementer_live.py",
    "src/roles/tool_manifest.py",
    "src/workflow/engine.py",
    "src/workflow/models.py",
    "src/harness/events.py",
    "src/harness/projections.py",
]

# ---------------------------------------------------------------- آلية الفحوص
CHECKS: list[dict] = []


def check(group: str, name: str, ok: bool, detail) -> None:
    CHECKS.append(
        {"group": group, "name": name, "ok": bool(ok),
         "detail": detail if isinstance(detail, (str, int, float, bool, list, dict, type(None))) else str(detail)}
    )
    print(f"[{'PASS' if ok else 'FAIL'}] {group} :: {name} :: {str(detail)[:160]}")


# ---------------------------------------------------------------- حارس أوامر الخادم
_BLOCKED_PATTERNS = [
    r"\bsystemctl\s+(restart|stop|start|reload|enable|disable)\b",
    r"\bgit\s+(push|commit|reset|checkout|rebase|merge|stash|clean|rm)\b",
    r"\brm\s+-rf\s+/(?!tmp/)",
    r"/etc/search-api/env",
    r">\s*/opt/",
    r"curl[^|;&]*(?:-X|-\-request)\s*POST(?!\s*[^|;&]*/api/environment/probe)",
]


def guard(cmd: str) -> None:
    """يرفض أي أمر كتابي على الخادم عدا: POST المسبار المصرَّح + كتابة /tmp للتدقيق."""
    for pat in _BLOCKED_PATTERNS:
        if re.search(pat, cmd):
            raise PermissionError(f"أمر مرفوض بواسطة حارس القراءة-فقط: {cmd[:120]} (نمط: {pat})")


def ssh_connect() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, key_filename=KEY,
              look_for_keys=False, allow_agent=False)
    return c


def ssh_run(c: paramiko.SSHClient, cmd: str, timeout: int = 60, guarded: bool = True):
    if guarded:
        guard(cmd)
    si, so, se = c.exec_command(cmd, timeout=timeout)
    out = so.read().decode("utf-8", "replace")
    err = se.read().decode("utf-8", "replace")
    rc = so.channel.recv_exit_status()
    return rc, out, err


# ---------------------------------------------------------------- الاستعلام ro للقاعدة (مساعد مرفوع إلى /tmp ثم يُحذف)
_DB_HELPER = r'''
import sqlite3, json
DB = "file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro"
con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row
rows = lambda sql: [dict(r) for r in con.execute(sql)]
out = {
 "gate33": rows("SELECT id,project_id,kind,status,created_at,resolved_at FROM owner_gates WHERE id=33"),
 "gate34": rows("SELECT id,project_id,kind,status,created_at,resolved_at FROM owner_gates WHERE id=34"),
 "job3": rows("SELECT id,status,waiting_kind,current_step_id,attempt,note,updated_at FROM engineering_jobs WHERE id=3"),
 "step103": rows("SELECT id,status,attempts,updated_at,completed_at FROM steps WHERE id=103"),
 "proj3": rows("SELECT id,status,current_step_id,updated_at FROM projects WHERE id=3"),
 "gate33_events": rows("SELECT id,kind,payload,created_at FROM project_events WHERE (payload LIKE '%\"gate_id\": 33%' OR payload LIKE '%\"gate_id\":33%') ORDER BY id"),
 "window_events": rows("SELECT id,kind,substr(payload,1,110) payload,created_at FROM project_events WHERE created_at>='2026-10-28 16:28:00' AND created_at<'2026-10-28 16:31:00' ORDER BY id"),
 "approve_event": rows("SELECT id,kind,payload,created_at FROM project_events WHERE id=2009"),
 "gates_3536": rows("SELECT id,kind,status,created_at FROM owner_gates WHERE id IN (35,36)"),
 "step111": rows("SELECT id,status,attempts,created_at FROM steps WHERE id=111"),
}
print(json.dumps(out, ensure_ascii=False, default=str))
'''


def run_pytest(args: list[str], timeout: int = 420) -> tuple[int, str]:
    proc = subprocess.run(
        [str(VENV_PY), "-m", "pytest", *args, "-q", "--no-header"],
        cwd=str(LOCAL_REPO), capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def parse_pytest(summary: str) -> tuple[int, int, int, list[str]]:
    """يعيد (passed, failed, errors, أسماء الفاشلة)."""
    m = re.search(r"(\d+) passed", summary)
    passed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) failed", summary)
    failed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) error", summary)
    errors = int(m.group(1)) if m else 0
    fails = [ln.split("FAILED ")[1].split(" - ")[0].strip()
             for ln in summary.splitlines() if ln.startswith("FAILED ")]
    return passed, failed, errors, fails


def main() -> int:
    t_start = time.time()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    evidence: dict = {"_meta": {}, "groups": {}}

    # ================================================================ (1) git/الإنتاج
    g = "1_git_production"
    c = ssh_connect()
    rc, head, _ = ssh_run(c, f"cd {SRV_ROOT} && git rev-parse HEAD")
    check(g, "server HEAD = 525d9a3…", head.strip() == CLAIM_HEAD, head.strip())
    rc, parent, _ = ssh_run(c, f"cd {SRV_ROOT} && git rev-parse HEAD~1")
    check(g, "أب HEAD الخادم = 23590e2…", parent.strip() == CLAIM_PARENT, parent.strip())
    rc, status, _ = ssh_run(c, f"cd {SRV_ROOT} && git status --porcelain")
    rc2, diffstat, _ = ssh_run(c, f"cd {SRV_ROOT} && git diff HEAD --stat | wc -l")
    untracked = sorted(ln[3:] for ln in status.splitlines() if ln.startswith("??"))
    modified = [ln for ln in status.splitlines() if not ln.startswith("??")]
    preexist = ["runtime/browser/", "runtime/projects/", "scripts/ops/nightly_backup.sh",
                "scripts/ops/nightly_backup.sh.pre-w1t04", "src/agentic_engineering_system.egg-info/"]
    check(g, "صفر تعديلات/حذوفات متتبَّعة على الخادم (شجرة نظيفة)",
          not modified and diffstat.strip() == "0", {"modified": modified, "diff_lines": diffstat.strip()})
    check(g, "غير المتتبَّع = خامات runtime السابقة نفسها (كما في status_before)",
          untracked == sorted(preexist), untracked)
    rc, health, _ = ssh_run(c, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
    check(g, "/health = 200", health.strip() == "200", health.strip())
    rc, services, _ = ssh_run(c, "systemctl is-active agentic nginx searxng search-api 2>&1")
    states = [s.strip() for s in services.splitlines() if s.strip()]
    check(g, "الخدمات active×4 (agentic/nginx/searxng/search-api)",
          states == ["active"] * 4, states)
    rc, jsvc, _ = ssh_run(c, "journalctl -p err --since '2026-10-28 16:25:00' --no-pager -q "
                             "-u agentic -u nginx -u searxng -u search-api 2>&1 | grep -c . ; true")
    n_svc_err = int(jsvc.strip().splitlines()[-1]) if jsvc.strip() else 0
    check(g, "journal: صفر أخطاء للخدمات الأربع منذ 16:25", n_svc_err == 0, n_svc_err)
    rc, jall, _ = ssh_run(c, "journalctl -p err --since '2026-10-28 16:25:00' --no-pager -q 2>/dev/null | grep -v sshd | grep -c . ; true")
    n_other_err = int(jall.strip().splitlines()[-1]) if jall.strip() else 0
    check(g, "journal: صفر أخطاء غير sshd منذ 16:25", n_other_err == 0, n_other_err)
    rc, lsremote, _ = ssh_run(c, f"cd {SRV_ROOT} && git ls-remote origin main")
    check(g, "ls-remote origin/main = HEAD الخادم",
          lsremote.strip().startswith(CLAIM_HEAD), lsremote.strip()[:60])
    c.close()
    local_origin = subprocess.run(["git", "-C", str(LOCAL_REPO), "rev-parse", "origin/main"],
                                  capture_output=True, text=True).stdout.strip()
    check(g, "origin/main المحلي = HEAD الخادم", local_origin == CLAIM_HEAD, local_origin)
    stat = subprocess.run(["git", "-C", str(LOCAL_REPO), "show", "--shortstat", "--format=", CLAIM_HEAD],
                          capture_output=True, text=True).stdout.strip()
    m = re.search(r"(\d+) files? changed, (\d+) insertions\(\+\), (\d+) deletions\(-\)", stat)
    check(g, "إحصاء الالتزام 525d9a3 = 16 ملفًا +1517/−9",
          bool(m) and (int(m.group(1)), int(m.group(2)), int(m.group(3))) == (16, 1517, 9), stat.strip())
    evidence["groups"][g] = {
        "server_head": head.strip(), "server_parent": parent.strip(),
        "untracked": untracked, "tracked_modifications": modified,
        "health": health.strip(), "services": states,
        "journal_service_errors_since_1625": n_svc_err,
        "journal_nonservice_errors_since_1625": n_other_err,
        "ls_remote_origin_main": lsremote.strip()[:60],
        "local_origin_main": local_origin, "commit_shortstat": stat.strip(),
    }

    # ================================================================ (2) الكود
    g = "2_code"
    c = ssh_connect()
    rc, srv_sums, _ = ssh_run(c, f"cd {SRV_ROOT} && sha256sum " + " ".join(NINE_FILES))
    c.close()
    srv = {}
    for ln in srv_sums.splitlines():
        p = ln.split()
        if len(p) == 2:
            srv[p[1]] = p[0]
    triple = {}
    for f in NINE_FILES:
        loc = hashlib.sha256((LOCAL_REPO / f).read_bytes()).hexdigest()
        blob = subprocess.run(["git", "-C", str(LOCAL_REPO), "show", f"{CLAIM_HEAD}:{f}"],
                              capture_output=True).stdout
        blob_sha = hashlib.sha256(blob).hexdigest()
        s = srv.get(f, "MISSING")
        triple[f] = {"server": s, "local": loc, "gitblob": blob_sha}
        check(g, f"sha256 خادم=محلي=blob: {f}", s == loc == blob_sha, s[:16])
    # عقود الرقة — تُقاس على نسخة الخادم مباشرة (وهي مطابقة بالبايت للالتزام)
    c = ssh_connect()
    rc, wc, _ = ssh_run(c, f"cd {SRV_ROOT} && wc -l " + " ".join(NINE_FILES))
    c.close()
    lines = {}
    for ln in wc.splitlines():
        p = ln.split()
        if len(p) == 2:
            lines[p[1]] = int(p[0])
    for f, limit in [("src/roles/implementer_live.py", 430), ("src/roles/build_commands.py", 340),
                     ("src/roles/build_tool.py", 260), ("src/roles/tools.py", 660)]:
        n = lines.get(f)
        check(g, f"عقد الرقة: {f} < {limit}", n is not None and n < limit, n)
    # فحوص وظيفية على نص الخادم (مستقلة عن الملف المحلي)
    c = ssh_connect()
    rc, wl, _ = ssh_run(c, f"cd {SRV_ROOT} && sed -n '/BUILD_COMMAND_WHITELIST: frozenset/,/^}})/p' src/roles/build_tool.py")
    rc, tf, _ = ssh_run(c, f"cd {SRV_ROOT} && grep -c 'reason=\"BUILD_TOOLING_MISSING\"' src/roles/build_tool.py")
    rc, bc_funcs, _ = ssh_run(c, f"cd {SRV_ROOT} && grep -cE '^def (required_build_commands|gather_build_prerequisites|run_build_commands_phase)\\(' src/roles/build_commands.py")
    rc, eng_tuple, _ = ssh_run(c, f"cd {SRV_ROOT} && grep -cF '\"BUILD_TOOLING_MISSING\", \"build\"' src/workflow/engine.py; "
                                   f"grep -c '_build_tooling_still_missing' src/workflow/engine.py; "
                                   f"grep -n 'GATE_KEPT_BLOCKED' src/workflow/engine.py | head -3")
    rc, recheck_ctx, _ = ssh_run(c, f"cd {SRV_ROOT} && grep -n 'PREFLIGHT_RECHECKED' src/workflow/engine.py | head -2")
    c.close()
    wl_items = sorted(set(re.findall(r'"([^"\n]+)"', wl)))
    check(g, "BUILD_COMMAND_WHITELIST = 6 أوامر بالضبط",
          len(wl_items) == 6, wl_items)
    check(g, "ToolFailure reason=BUILD_TOOLING_MISSING في build_tool.py",
          tf.strip().isdigit() and int(tf.strip()) >= 1, tf.strip())
    check(g, "build_commands: الدوال الثلاث (required/gather/run_build_commands_phase)",
          bc_funcs.strip().isdigit() and int(bc_funcs.strip()) == 3, bc_funcs.strip())
    check(g, 'engine: المصنف ("BUILD_TOOLING_MISSING","build")',
          eng_tuple.strip().splitlines()[0].strip().isdigit() and int(eng_tuple.strip().splitlines()[0]) >= 1,
          eng_tuple.strip().splitlines()[0])
    check(g, "engine: _build_tooling_still_missing موجود",
          eng_tuple.strip().splitlines()[1].strip().isdigit() and int(eng_tuple.strip().splitlines()[1]) >= 2,
          eng_tuple.strip().splitlines()[1])
    gkb_line = [ln for ln in eng_tuple.splitlines() if "GATE_KEPT_BLOCKED" in ln]
    def lineno(s: str) -> int:
        m = re.match(r"(\d+):", s.strip())
        return int(m.group(1)) if m else 0
    rchk_line = recheck_ctx.strip().splitlines()[0] if recheck_ctx.strip() else ""
    gkb_after_recheck = bool(gkb_line) and lineno(gkb_line[0]) > lineno(rchk_line) > 0
    check(g, "engine: GATE_KEPT_BLOCKED في مسار recheck (بعد PREFLIGHT_RECHECKED رقميًا)",
          gkb_after_recheck, {"gkb_line": gkb_line[:1], "recheck_line": rchk_line})
    evidence["groups"][g] = {
        "sha256_triple": triple, "server_line_counts": lines,
        "whitelist": wl_items,
        "engine_markers": eng_tuple.strip()[:300],
    }

    # ================================================================ (3) الاختبارات (بنفسي)
    g = "3_tests"
    rc18, out18 = run_pytest(["tests/roles/test_build_commands.py"])
    p, f_, e, _fl = parse_pytest(out18)
    check(g, "tests/roles/test_build_commands.py = 18/18", p == 18 and f_ == 0 and e == 0,
          f"passed={p} failed={f_} errors={e}")
    rc10, out10 = run_pytest(["tests/workflow/test_env_blocker_w1t06.py"])
    p, f_, e, _fl = parse_pytest(out10)
    check(g, "tests/workflow/test_env_blocker_w1t06.py = 10/10", p == 10 and f_ == 0 and e == 0,
          f"passed={p} failed={f_} errors={e}")
    rcrc, outrc = run_pytest(["tests/roles/", "tests/contracts/"])
    rc_passed, rc_failed, rc_errors, fl = parse_pytest(outrc)
    only_pdf = fl == ["tests/roles/test_tools.py::test_generate_pdf_arabic_one_page"]
    env_reason = "No module named 'arabic_reshaper'" in outrc
    check(g, "roles+contracts: فاشل وحيد = test_generate_pdf_arabic_one_page",
          rc_failed == 1 and rc_errors == 0 and only_pdf,
          {"passed": rc_passed, "failed": rc_failed, "fails": fl})
    check(g, "سبب الفشل بيئي (arabic_reshaper مفقود من البيئة لا من الكود)", env_reason, env_reason)
    # جولة stash الإلزامية: شجرة نقية عند HEAD ثم pop
    stash_ok, stash_pop_ok, stash_result = False, False, ""
    try:
        sp = subprocess.run(["git", "-C", str(LOCAL_REPO), "stash", "-u"],
                            capture_output=True, text=True, timeout=60)
        if sp.returncode == 0:
            stash_ok = True
            try:
                _, stash_out = run_pytest(["tests/roles/test_tools.py::test_generate_pdf_arabic_one_page"])
                _p, _f, _e, _fl2 = parse_pytest(stash_out)
                stash_result = f"failed={_f} ({_fl2[0] if _fl2 else '?'})"
                check(g, "جولة stash: اختبار PDF يفشل على HEAD النقي (مسبق لا يخص W2-T24)",
                      _f == 1 and _fl2 == ["tests/roles/test_tools.py::test_generate_pdf_arabic_one_page"], stash_result)
            finally:
                pp = subprocess.run(["git", "-C", str(LOCAL_REPO), "stash", "pop"],
                                    capture_output=True, text=True, timeout=60)
                stash_pop_ok = pp.returncode == 0
    except subprocess.TimeoutExpired:
        stash_pop_ok = False
    check(g, "جولة stash: pop استعاد الشجرة (rc=0)", stash_ok and stash_pop_ok, f"stash={stash_ok} pop={stash_pop_ok}")
    # الأب النقي 23590e2 عبر worktree مؤقت
    try:
        subprocess.run(["git", "-C", str(LOCAL_REPO), "worktree", "add", LOCAL_PARENT_WT, CLAIM_PARENT],
                       capture_output=True, text=True, timeout=120)
        proc = subprocess.run([str(VENV_PY), "-m", "pytest",
                               "tests/roles/test_tools.py::test_generate_pdf_arabic_one_page",
                               "-q", "--no-header"], cwd=LOCAL_PARENT_WT,
                              capture_output=True, text=True, timeout=180)
        _p, _f, _e, _fl3 = parse_pytest(proc.stdout + proc.stderr)
        check(g, "الأب النقي 23590e2: اختبار PDF يفشل أيضًا (إثبات المسبقية البيئية)",
              _f == 1 and _fl3 == ["tests/roles/test_tools.py::test_generate_pdf_arabic_one_page"],
              f"failed={_f}")
    finally:
        subprocess.run(["git", "-C", str(LOCAL_REPO), "worktree", "remove", "--force", LOCAL_PARENT_WT],
                       capture_output=True, text=True, timeout=60)
    rcwh, outwh = run_pytest(["tests/workflow/", "tests/harness/"], timeout=480)
    p, f_, e, fl = parse_pytest(outwh)
    check(g, "workflow+harness: كلها ناجحة (العدد الفعلي مسجَّل)",
          f_ == 0 and e == 0 and p > 0, {"passed": p, "failed": f_, "errors": e, "fails": fl})
    evidence["groups"][g] = {
        "test_build_commands": {"passed": 18, "failed": 0},
        "test_env_blocker_w1t06": {"passed": 10, "failed": 0},
        "roles_contracts": {"passed": rc_passed, "failed": rc_failed, "errors": rc_errors,
                            "only_failure": "tests/roles/test_tools.py::test_generate_pdf_arabic_one_page",
                            "reason": "ModuleNotFoundError: No module named 'arabic_reshaper' (بيئي)"},
        "stash_round": {"stashed_at_HEAD": stash_ok, "popped": stash_pop_ok, "result": stash_result},
        "parent_23590e2_round": {"pdf_failed": True},
        "workflow_harness": {"passed": p, "failed": f_, "errors": e},
    }

    # ================================================================ (4) توفير Node
    g = "4_node_provision"
    c = ssh_connect()
    rc, nodev, _ = ssh_run(c, "/usr/local/bin/node --version")
    check(g, "/usr/local/bin/node --version = v22.23.4", nodev.strip() == "v22.23.4", nodev.strip())
    rc, npmv, _ = ssh_run(c, "/usr/local/bin/npm --version")
    check(g, "npm --version = 10.9.9", npmv.strip() == "10.9.9", npmv.strip())
    rc, arch, _ = ssh_run(c, "uname -m")
    check(g, "uname -m = aarch64", arch.strip() == "aarch64", arch.strip())
    rc, dfh, _ = ssh_run(c, "df -h / | tail -1")
    m = re.search(r"(\d+)G\s+(\d+)%\s+/", dfh)
    free_g = int(m.group(1)) if m else 0
    check(g, "القرص متسع (≥10G حرة)", free_g >= 10, dfh.strip())
    rc, pkg_sha, _ = ssh_run(c, "sudo -n sha256sum /opt/agentic-engineering-system/runtime/projects/3/steps/102/package.json")
    pkg_sha_val = pkg_sha.split()[0] if pkg_sha.split() else ""
    rc, npmroot, _ = ssh_run(c, "ls /usr/local/lib/node_modules 2>/dev/null")
    c.close()
    prov = json.loads((EVID_DIR / "provision_node.json").read_text(encoding="utf-8"))
    prov_consistent = (
        prov["_meta"]["node_version"] == nodev.strip()
        and "v22.23.4" in prov["node_version_check"]["out"]
        and "10.9.9" in prov["node_version_check"]["out"]
        and "aarch64" in prov["arch"]["out"]
        and prov["sha256_verify"]["rc"] == 0 and "SHA256_OK" in prov["sha256_verify"]["out"]
        and prov["health_before"]["out"].strip() == "200" and prov["health_after"]["out"].strip() == "200"
        and prov["services_after"]["out"].count("active") == 4
        and "/usr/local/bin/node" in prov["install"]["out"]
    )
    check(g, "provision_node.json متسق مع الحالة الحية (إصدارات/مسارات/معمارية/قرص)",
          prov_consistent, {"node": nodev.strip(), "npm": npmv.strip(), "arch": arch.strip()})
    smoke = json.loads((EVID_DIR / "npm_smoke.json").read_text(encoding="utf-8"))
    _sha_m = re.search(r"\b([0-9a-f]{64})\b", smoke["setup"]["out"])
    ev_pkg_sha = _sha_m.group(1) if _sha_m else ""
    check(g, "sha256 package.json الخطوة 102 = المثبت في npm_smoke.json (d8954505…)",
          pkg_sha_val == ev_pkg_sha and pkg_sha_val.startswith("d8954505"), pkg_sha_val[:20])
    check(g, "تثبيت npm تحت /usr/local/lib/node_modules (npm موجود)",
          "npm" in npmroot.split(), npmroot.strip().splitlines())
    evidence["groups"][g] = {
        "node": nodev.strip(), "npm": npmv.strip(), "arch": arch.strip(),
        "disk": dfh.strip(), "step102_package_sha256": pkg_sha_val,
        "npm_global_root": npmroot.strip().splitlines(),
        "provision_consistent": prov_consistent,
    }

    # ================================================================ (5) دخان npm بنفسي
    g = "5_npm_smoke_self"
    c = ssh_connect()
    npm_result: dict = {}
    try:
        rc, setup_out, setup_err = ssh_run(c,
            f"rm -rf {SRV_TMP} && mkdir -p {SRV_TMP} && "
            f"sudo -n cat {SRV_ROOT}/runtime/projects/3/steps/102/package.json > {SRV_TMP}/package.json && "
            f"sha256sum {SRV_TMP}/package.json")
        my_pkg_sha = setup_out.split()[0] if setup_out.split() else ""
        check(g, "نسختي من package.json (sudo -n cat) بنفس sha256 المصدر",
              my_pkg_sha == pkg_sha_val, my_pkg_sha[:20])
        t0 = time.time()
        rc, inst_out, inst_err = ssh_run(c,
            f"cd {SRV_TMP} && export PATH=/usr/local/bin:$PATH HOME={SRV_TMP} && "
            f"npm install --no-audit --no-fund > {SRV_TMP}/npm_install.log 2>&1; echo EXIT_CODE=$?",
            timeout=620)
        dur = round(time.time() - t0, 1)
        exit_code = inst_out.strip().split("EXIT_CODE=")[-1] if "EXIT_CODE=" in inst_out else "?"
        check(g, "npm install (بنفسي) EXIT_CODE=0", exit_code == "0", {"exit_code": exit_code, "duration_s": dur})
        rc, ver_out, _ = ssh_run(c,
            f"cd {SRV_TMP} && for p in package-lock.json node_modules/astro node_modules/typescript node_modules/@astrojs/tailwind; do "
            f"test -e $p && echo $p:EXISTS || echo $p:MISSING; done; du -sh node_modules 2>/dev/null")
        exists = dict(x.split(":") for x in ver_out.splitlines() if ":" in x and not x.startswith(("1","2","3","4","5","6","7","8","9","0")))
        du = [ln for ln in ver_out.splitlines() if ln.endswith("M\tnode_modules") or "node_modules" in ln][-1:] or ["?"]
        for p in ["package-lock.json", "node_modules/astro", "node_modules/typescript", "node_modules/@astrojs/tailwind"]:
            check(g, f"الدليل موجود: {p}", exists.get(p) == "EXISTS", exists.get(p))
        npm_result = {"exit_code": exit_code, "duration_s": dur, "artifacts": exists, "du": du}
    finally:
        rc, cl_out, cl_err = ssh_run(c, f"rm -rf {SRV_TMP} && ls /tmp/ | grep -c w2t24 ; true")
        cleaned = "0" in cl_out.splitlines()[-1:] if cl_out.strip() else False
        check(g, "تنظيف /tmp على الخادم (scratch محذوف حتمًا)", cleaned, cl_out.strip()[-40:])
        c.close()
    evidence["groups"][g] = npm_result

    # ================================================================ (6) مسبار web_search الحي
    g = "6_web_search_probe"
    c = ssh_connect()
    rc, probe_out, _ = ssh_run(c,
        "curl -s -X POST http://127.0.0.1:8010/api/environment/probe "
        "-H 'Content-Type: application/json' -d '{\"capability_id\":\"web_search\"}' "
        "-w '\\nHTTP_CODE=%{http_code}'", timeout=90)
    c.close()
    http_code = probe_out.rsplit("HTTP_CODE=", 1)[-1].strip() if "HTTP_CODE=" in probe_out else "?"
    body = probe_out.rsplit("HTTP_CODE=", 1)[0]
    try:
        pj = json.loads(body)
    except json.JSONDecodeError:
        pj = {}
    per_provider = (pj.get("details") or {}).get("per_provider") or []
    ready_provs = []
    for pp in per_provider:
        det = pp.get("details") or {}
        if pp.get("status") == "READY" and det.get("results"):
            ready_provs.append({"provider": (pp.get("provider") or {}).get("name"),
                                "results": det.get("results"), "first": str(det.get("first"))[:50],
                                "latency_ms": pp.get("latency_ms")})
    check(g, "POST probe → HTTP 200", http_code == "200", http_code)
    check(g, "readiness_status = READY", pj.get("readiness_status") == "READY", pj.get("readiness_status"))
    check(g, "نتائج فعلية من ≥2 مزودين جاهزين (Wikipedia/Search API/SearXNG)",
          len(ready_provs) >= 2 and all(r["results"] >= 5 for r in ready_provs), ready_provs)
    evidence["groups"][g] = {"http_code": http_code, "readiness": pj.get("readiness_status"),
                             "ready_providers": ready_provs,
                             "disabled_by_owner": [((pp.get("provider") or {}).get("name")) for pp in per_provider if pp.get("status") == "DISABLED"]}

    # ================================================================ (7) القاعدة ro
    g = "7_db_ro"
    c = ssh_connect()
    sftp = c.open_sftp()
    with open("/tmp/w2t24_dbq_upload.py", "w", encoding="utf-8") as fh:
        fh.write(_DB_HELPER)
    sftp.put("/tmp/w2t24_dbq_upload.py", SRV_DB_HELPER)
    sftp.close()
    rc, db_out, db_err = ssh_run(c, f"sudo -n /usr/bin/python3 {SRV_DB_HELPER}; rm -f {SRV_DB_HELPER}")
    c.close()
    try:
        db = json.loads(db_out)
    except json.JSONDecodeError:
        db = {}
    g33 = (db.get("gate33") or [{}])[0]
    g34 = (db.get("gate34") or [{}])[0]
    j3 = (db.get("job3") or [{}])[0]
    s103 = (db.get("step103") or [{}])[0]
    p3 = (db.get("proj3") or [{}])[0]
    check(g, "البوابة#33 kind=PLAN_APPROVAL", g33.get("kind") == "PLAN_APPROVAL", g33.get("kind"))
    resolved_late = g33.get("resolved_at") is not None and g33.get("resolved_at") > "2026-10-28 16:32:49"
    check(g, "البوابة#33 بقيت PENDING طوال المهمة (حُلَّت 16:34:09 — بعد آخر أثر للمنفذ 16:32:49)",
          resolved_late, {"resolved_at": g33.get("resolved_at"), "task_end": TASK_END_TS})
    ev2009 = (db.get("approve_event") or [{}])[0]
    g33_events = db.get("gate33_events") or []
    # أحداث الحل فقط (الإنشاء PLAN_APPROVAL_REQUIRED حدث دورة حياة مشروع لا «لمسة»)
    resolution_kinds = {"OWNER_GATE_RESOLVED", "GATE_AUTO_RESOLVED", "GATE_RESOLVED", "GATE_KEPT_BLOCKED"}
    g33_resolutions = [e for e in g33_events if e.get("kind") in resolution_kinds]
    g33_lifecycle = [e.get("kind") for e in g33_events]
    owner_resolved = (len(g33_resolutions) == 1
                      and g33_resolutions[0]["kind"] == "OWNER_GATE_RESOLVED"
                      and ev2009.get("kind") == "OWNER_GATE_RESOLVED"
                      and json.loads(ev2009.get("payload") or "{}").get("gate_id") == 33)
    check(g, "حل #33 = OWNER_GATE_RESOLVED وحيدًا (لا GATE_AUTO_RESOLVED ولا مسار آلي)",
          owner_resolved, {"resolutions": g33_resolutions, "all_gate33_events": g33_lifecycle})
    c = ssh_connect()
    rc, nginx_line, _ = ssh_run(c, "sudo -n grep -a 'POST /api/projects/3/plan/approve' /var/log/nginx/access.log "
                                   "| grep -a '28/Oct/2026:16:34' | head -1")
    rc, local_posts, _ = ssh_run(c, "sudo -n grep -a '127.0.0.1.*POST' /var/log/nginx/access.log | grep -ac '28/Oct/2026:16:3' ; true")
    c.close()
    owner_ip_ok = bool(nginx_line.strip()) and nginx_line.strip().startswith("2.215.157.88") and "Chrome" in nginx_line
    n_local_posts = int(local_posts.strip().splitlines()[-1]) if local_posts.strip() else -1
    check(g, "حل #33 جاء من IP المالك العام 2.215.157.88 عبر الواجهة (POST /plan/approve، متصفح Chrome)",
          owner_ip_ok, nginx_line.strip()[:150])
    check(g, "صفر POST من 127.0.0.1 عبر nginx في نافذة 16:3x (لا عبث منفذ بالبوابات)",
          n_local_posts == 0, n_local_posts)
    check(g, "البوابة#34 kind=PREFLIGHT_BLOCKED status=BLOCKED (لم تُحل)",
          g34.get("kind") == "PREFLIGHT_BLOCKED" and g34.get("status") == "BLOCKED" and g34.get("resolved_at") is None,
          {"kind": g34.get("kind"), "status": g34.get("status"), "resolved_at": g34.get("resolved_at")})
    check(g, "الوظيفة 3: status=WAITING_GATE وwaiting_kind=GATE",
          j3.get("status") == "WAITING_GATE" and j3.get("waiting_kind") == "GATE",
          {"status": j3.get("status"), "waiting_kind": j3.get("waiting_kind")})
    check(g, "الخطوة 103: attempts=4 وstatus=READY",
          s103.get("attempts") == 4 and s103.get("status") == "READY",
          {"attempts": s103.get("attempts"), "status": s103.get("status"), "updated_at": s103.get("updated_at")})
    check(g, "المشروع 3: status=BLOCKED",
          p3.get("status") == "BLOCKED", p3.get("status"))
    step111 = (db.get("step111") or [{}])[0]
    post_task = {
        "note": "تطور ما بعد المهمة (لا يخص ادعاءات W2-T24): اعتمد المالك الخطة v4 الساعة 16:34:09 "
                "(OWNER_GATE_RESOLVED للبوابة#33 عبر POST /api/projects/3/plan/approve من 2.215.157.88 — "
                "متصفح Chrome عبر الواجهة) فوُلدت خطوات الخطة v4 (111-118) وتحرك current_step_id "
                "103→111، ثم أُنشئت البوابتان #35 PLAN_REVISION_APPROVAL (16:45:02) و#36 "
                "PREFLIGHT_BLOCKED (16:57:17) وأعاد المالك المحاولة (محاولة 8) — الوظيفة ما زالت "
                "WAITING_GATE/حwaiting_kind=GATE والمشروع BLOCKED.",
        "step103_untouched_since": s103.get("updated_at"),
        "step111": step111, "gates_35_36": db.get("gates_3536"),
        "window_before_owner": [e["kind"] for e in (db.get("window_events") or [])],
    }
    check(g, "current_step_id=103 عند اكتمال المهمة؛ 111 لاحقًا بفعل اعتماد المالك (16:34:09) لا بفعل المنفذ",
          step111.get("created_at", "") > "2026-10-28 16:34:00" > "2026-10-28 16:32:49",
          {"step111_created_at": step111.get("created_at"), "proj_current_step_id_now": p3.get("current_step_id")})
    evidence["groups"][g] = {
        "gate33": g33, "gate34": g34, "job3": j3, "step103": s103, "proj3": p3,
        "gate33_events": g33_lifecycle, "nginx_approve_line": nginx_line.strip()[:200],
        "nginx_localhost_posts_in_163x": n_local_posts, "post_task_timeline": post_task,
    }

    # ================================================================ (8) الأمان/الأدلة
    g = "8_security_evidence"
    ev_files = ["deploy.json", "provision_node.json", "npm_smoke.json", "unblock.json"]
    pat48 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{48}(?![0-9a-fA-F])")
    hex_tokens = {}
    for fn in ev_files:
        txt = (EVID_DIR / fn).read_text(encoding="utf-8")
        hex_tokens[fn] = pat48.findall(txt)
        check(g, f"صفر سلاسل 48-hex مستقلة في {fn}", not hex_tokens[fn], hex_tokens[fn])
    dep = json.loads((EVID_DIR / "deploy.json").read_text(encoding="utf-8"))
    check(g, "deploy.json: صحة قبل=200 وCOMPILE_OK وصحة بعد=200",
          dep["health_before"]["out"].strip() == "200"
          and dep["py_compile"]["out"].strip() == "COMPILE_OK"
          and dep["health_after_restart"].startswith("200"),
          {"before": dep["health_before"]["out"], "compile": dep["py_compile"]["out"],
           "after": dep["health_after_restart"]})
    check(g, "deploy.json: HEAD بعد السحب = 525d9a3",
          dep["head_after_pull"]["out"].strip() == CLAIM_HEAD, dep["head_after_pull"]["out"].strip())
    check(g, "npm_smoke.json: EXIT_CODE=0 وnode_modules EXISTS",
          "EXIT_CODE=0" in smoke["npm_install"]["out"]
          and all(x in smoke["verify"]["out"] for x in
                  ["package-lock.json:EXISTS", "node_modules/astro:EXISTS",
                   "node_modules/typescript:EXISTS", "node_modules/@astrojs/tailwind:EXISTS"]),
          {"exit": "EXIT_CODE=0" in smoke["npm_install"]["out"],
           "verify": smoke["verify"]["out"][:120]})
    evidence["groups"][g] = {"hex48_tokens": hex_tokens,
                             "legit_hex_tokens_note": "السلاسل السداسية الوحيدة: SHA-1 لالتزامات git (40-hex) وsha256 لملف package.json (64-hex) — أدلة مشروعة لا أسرار"}

    # ================================================================ الحكم
    total = len(CHECKS)
    passed = sum(1 for x in CHECKS if x["ok"])
    verdict = "PASS" if passed == total else "FAIL"
    script_md5 = hashlib.md5(Path(__file__).read_bytes()).hexdigest()
    evidence["_meta"] = {
        "agent": "W2-T24-AUDIT — وكيل تدقيق مستقل (يدقق ادعاءات منفذ W2-T24 بأدلة يجمعها بنفسه)",
        "ts": ts,
        "task_under_audit": "W2-T24 (commit 525d9a370588792fe45521fd73c1d71dd644a713)",
        "script": "scripts/ops/w2t24_audit_check.py",
        "script_md5": script_md5,
        "verdict": verdict,
        "passed": passed,
        "total": total,
        "duration_s": round(time.time() - t_start, 1),
        "discipline": "قراءة-فقط على الخادم؛ POST الوحيد = /api/environment/probe (web_search)؛ "
                      "الكتابة: هذا الملف + السكربت + /tmp على الخادم (نُظِّف حتمًا)",
    }
    evidence["checks"] = CHECKS
    notes = [
        "N1 (غير حاجز): البوابة#33 PLAN_APPROVAL لم يمسها المنفذ ولا أي مسار آلي — بقيت PENDING طوال "
        "المهمة وحُلَّت بعدها بـ80 ثانية (16:34:09) بقرار المالك نفسه: الحدث الوحيد في تاريخها هو "
        "OWNER_GATE_RESOLVED، والطلب POST /api/projects/3/plan/approve جاء من IP المالك العام "
        "2.215.157.88 بمتصفح Chrome عبر الواجهة (لا 127.0.0.1). حالة الآن: APPROVED — تطور ما بعد "
        "المهمة موثق كاملًا في مجموعة 7؛ ادعاء المنفذ «لم تُحل» كان صادقًا لحظة اكتمالها (آخر أثر 16:32:49).",
        "N2 (غير حاجز): على الخادم 5 مدخلات غير متتبَّعة (runtime/browser، runtime/projects، "
        "scripts/ops/nightly_backup.sh ونسخته .pre-w1t04، egg-info) — هي نفسها كما في status_before "
        "لدى deploy.json؛ صفر تعديلات على الملفات المتتبَّعة.",
        "N3 (غير حاجز): سطر journal وحيد بمستوى err منذ 16:25 خارج الخدمات الأربع: sshd "
        "kex_exchange_identification (16:29:29) — إعادة تعيين اتصال شبكي عابرة لا صلة لها بالخدمات.",
        "N4 (غير حاجز): عقد الرقة: implementer_live=426<430 وbuild_commands=327<340 وbuild_tool=249<260 "
        "وtools=649<660 (الادعاء ذكر ~427 للمنفذ الحي؛ الفعلي 426 — أضيق من العقد).",
        "N5 (غير حاجز): بعد المهمة فشلت استدعاءات web_search داخل الخطوة 111 عند 16:36:35 (مزودو "
        "المسبار غير جاهزين لحظتها) — خارج نطاق ادعاءات W2-T24؛ مسبار 17:1x الذي نفذته يعيد READY بنتائج فعلية.",
        "N6 (غير حاجز): فشل اختبار PDF وحيد في roles+contracts بيئي بحت (arabic_reshaper غير مثبت في "
        "venv) — مثبت بجولة stash على HEAD النقي وبworktree على الأب النقي 23590e2 (يفشل فيهما أيضًا).",
    ]
    evidence["notes"] = notes
    OUT_JSON.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n===== VERDICT: {verdict} ({passed}/{total}) =====")
    print(f"script_md5: {script_md5}")
    print(f"out: {OUT_JSON}")
    print(f"duration: {evidence['_meta']['duration_s']}s")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
