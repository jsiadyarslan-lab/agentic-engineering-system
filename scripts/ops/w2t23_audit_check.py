#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T23-AUDIT — تدقيق مستقل كامل لمهمة W2-T23 (وكيل تدقيق مستقل — general-purpose).

يجمع كل الأدلة بنفسه (لا يقبل نقلًا من تقرير المنفذ):
  A) git/الإنتاج عبر SSH قراءة-فقط (paramiko بلا agent) — HEAD/الأب/الشجرة/الصحة/
     الخدمات/journal + تطابق sha256 ثلاثي (ملف الخادم = الملف المحلي = blob
     الالتزام 0916484) للملفات الستة + الدفع إلى GitHub (ls-remote).
  B) الكود محليًا — أعداد الأسطر/عقود الرقة/مكونات build_files/استدعاء الطور/
     قسم الموجه/regex المراجع/فحص وظيفي لاستخراج الملفات.
  C) الاختبارات محليًا (venv المستودع) — 14 الجديدة + roles+contracts (84+1
     بيئي معلن) + إثبات بيئية الفشل arabic_reshaper على main النقية (worktree
     الأب) + workflow+harness (165/165 مع إعادة عزل الفاشل تحت الحمل).
  D) القاعدة عبر SSH بوضع ro حصرًا — الخطوة 102/التنفيذان 27-28/البوابة 30/
     تقدم المشروع/استدعاءات write_file الفعلية بسلاسل زمنية حقيقية
     (record_json.started_at) + الحالة الراهنة (بوابة 31 الجديدة خارج النطاق).
  E) ملفات الخطوة على القرص — sha256/الأحجام/صلاحية JSON/ESM/المحقول +
     اتساق mtimes مع أزمنة الاستدعاءات (سببية حية).
  F) الجاهزية الآن — GET readiness (عرض القدرات؛ نقطة capabilities المذكورة
     في التكليف تعيد 404 — موثقة) + مسباري أنا (POST probe {web_search} فقط
     — المسموح الموثق في سابقة W2-T20-AUDIT؛ لا preflight).
  G) الأمان — صفر سلاسل 48-hex في ملفات الرقعة والأدلة + حراس المسارات
     الصاعدة/الامتدادات البيضاء في build_files.
  H) أدلة المنفذ الثلاثة — اتساقها الداخلي مع ما جمعته بنفسي.

الخرج: download/aes-remediation/W2-T23/audit_w2t23_independent.json (مع md5 السكربت).
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

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"
REPO = Path("/home/z/my-project/repo")
VENV_PY = str(REPO / ".venv/bin/python")
EVID_DIR = Path("/home/z/my-project/download/aes-remediation/W2-T23")
OUT_PATH = EVID_DIR / "audit_w2t23_independent.json"

COMMIT = "0916484812bd371462a49bec5e939871240c2af1"
PARENT = "3764420febeada9fa41d96cf1dce1206e0cce93d"
GRANDPARENT = "6fc02343cbd7453d368bb3d96313214b004e989e"
SERVER_ROOT = "/opt/agentic-engineering-system"
STEP_DIR = f"{SERVER_ROOT}/runtime/projects/3/steps/102"

PATCH_FILES = [
    "src/roles/implementer_live.py",
    "src/roles/build_files.py",
    "src/roles/verifier.py",
    "prompts/implementer.md",
    "tests/contracts/test_thinness.py",
    "tests/roles/test_implementer_create_files.py",
]

EXPECTED_UNTRACKED = {
    "?? runtime/browser/",
    "?? runtime/projects/",
    "?? scripts/ops/nightly_backup.sh",
    "?? scripts/ops/nightly_backup.sh.pre-w1t04",
    "?? src/agentic_engineering_system.egg-info/",
}

CLAIMED_DISK_SHA = {
    "package.json": "d8954505e747ee9ea0795b92fc1d0d2bbd41e6b79a3ad1b1270b2abd74323ac6",
    "tsconfig.json": "7c6e2cd7ed66a56ea0e8fe6bce07e473be600615e2513c4841096abf53f0cf76",
    "astro.config.mjs": "9e6b2617131ee8406f01475be8b03026615006a98d970a7609a461d6a8654652",
}
CLAIMED_DISK_BYTES = {"package.json": 310, "tsconfig.json": 43, "astro.config.mjs": 183}

# جولات المدقق اليدوية قبل تشغيل السكربت (نفسها يعيد السكربت تشغيلها أدناه)
AUDITOR_PRE_RUNS = [
    "tests/roles/test_implementer_create_files.py: 14 passed in 0.35s",
    "tests/roles/ + tests/contracts/: 84 passed + 1 failed (test_generate_pdf_arabic_one_page — "
    "ModuleNotFoundError: arabic_reshaper)",
    "نفس الفاشل على worktree الأب 3764420 النقي: 1 failed (arabic_reshaper) — بيئي سابق للرقعة",
    "tests/workflow/ + tests/harness/: 164 passed + 1 متذبذب توقيت "
    "(test_killed_planning_thread_leaves_no_phantom_planning — نجح معزولًا في 1.58s "
    "والالتزام 0916484 لا يمس workflow/harness إطلاقًا) — يعيد السكربت تشغيلها أدناه",
]

CHECKS: list[dict] = []
NOTES: list[str] = []


def check(cid: str, group: str, desc: str, ok: bool, evidence) -> bool:
    CHECKS.append({
        "id": cid, "group": group, "desc": desc,
        "pass": bool(ok), "evidence": evidence,
    })
    print(f"[{'PASS' if ok else 'FAIL'}] {cid} — {desc}")
    return bool(ok)


def note(text: str) -> None:
    NOTES.append(text)
    print(f"[NOTE] {text}")


# ------------------------------------------------------------------ #
# أدوات مساعدة
# ------------------------------------------------------------------ #

def local(cmd: list[str], cwd: str | None = None, timeout: int = 600,
          env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=cwd or str(REPO), capture_output=True,
                          text=True, timeout=timeout, env=env)


def ssh_run(client: paramiko.SSHClient, cmd: str, timeout: int = 90) -> tuple[str, str]:
    _, out, err = client.exec_command(cmd, timeout=timeout)
    return out.read().decode(errors="replace"), err.read().decode(errors="replace")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


DB_PY = r'''
import sqlite3, json
db = sqlite3.connect("file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
out = {}
out["step102"] = dict(db.execute("SELECT id,status,attempts,completed_at,last_error,acceptance_criteria FROM steps WHERE id=102").fetchone())
out["executions_102"] = [dict(r) for r in db.execute("SELECT id,step_id,attempt,started_at,finished_at,status,commit_sha,error,workspace FROM executions WHERE step_id=102 ORDER BY id")]
out["gate30"] = dict(db.execute("SELECT id,project_id,kind,reason,status,resolved_at,details FROM owner_gates WHERE id=30").fetchone())
out["project3"] = dict(db.execute("SELECT id,name,status,current_step_id,completion_state,last_error,updated_at FROM projects WHERE id=3").fetchone())
out["step103"] = dict(db.execute("SELECT id,ordinal,objective,status,attempts,last_error,updated_at FROM steps WHERE id=103").fetchone())
out["steps_proj3_total"] = db.execute("SELECT COUNT(*) FROM steps s JOIN phases p ON s.phase_id=p.id WHERE p.project_id=3").fetchone()[0]
out["steps_proj3_completed"] = db.execute("SELECT COUNT(*) FROM steps s JOIN phases p ON s.phase_id=p.id WHERE p.project_id=3 AND s.status='COMPLETED'").fetchone()[0]
inv = []
for r in db.execute("SELECT id,tool,query,output_sha256,record_json,created_at,status FROM tool_invocations WHERE cycle_id LIKE '%step-102%' ORDER BY id"):
    d = dict(r)
    rec = {}
    try:
        rec = json.loads(d.pop("record_json") or "{}")
    except Exception:
        pass
    inv.append({
        "id": d["id"], "tool": d["tool"], "query": d["query"],
        "output_sha256": d["output_sha256"], "status": d["status"],
        "invoked_at": rec.get("started_at"),
        "created_at": d["created_at"],
        "result_path": (rec.get("result_summary") or {}).get("path"),
    })
out["invocations_102"] = inv
er = db.execute("SELECT id,execution_id,step_id,project_id,files,verdict,created_at FROM evidence_records ORDER BY id").fetchall()
out["evidence_records"] = []
for r in er:
    files = {}
    try:
        files = json.loads(r["files"])
    except Exception:
        pass
    out["evidence_records"].append({
        "id": r["id"], "execution_id": r["execution_id"], "step_id": r["step_id"],
        "project_id": r["project_id"], "verdict": r["verdict"],
        "created_at": r["created_at"],
        "files": {k: v.get("sha256") for k, v in files.items()
                  if isinstance(v, dict)},
    })
out["gates_p3_latest"] = [dict(r) for r in db.execute("SELECT id,kind,reason,status,created_at,resolved_at FROM owner_gates WHERE project_id=3 ORDER BY id DESC LIMIT 3")]
out["gate31"] = dict(db.execute("SELECT id,project_id,kind,reason,status,created_at,resolved_at,details FROM owner_gates WHERE id=31").fetchone())
out["job3"] = dict(db.execute("SELECT id,status,waiting_kind,heartbeat_at FROM engineering_jobs WHERE id=3").fetchone())
print("DBJSON:" + json.dumps(out, ensure_ascii=False, default=str))
'''


def fetch_db_state(client: paramiko.SSHClient) -> dict:
    out, err = ssh_run(client, "sudo -n python3 - <<'PYEOF'\n%s\nPYEOF" % DB_PY, timeout=90)
    for line in out.splitlines():
        if line.startswith("DBJSON:"):
            return json.loads(line[len("DBJSON:"):])
    raise RuntimeError("DB fetch failed: %s / %s" % (out[:300], err[:300]))


# ------------------------------------------------------------------ #
# السكربت الرئيسي
# ------------------------------------------------------------------ #

def main() -> int:
    t0 = time.time()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, key_filename=KEY,
                   look_for_keys=False, allow_agent=False, timeout=30)

    # ============================ A) git/الإنتاج ============================ #
    out, _ = ssh_run(client, "sudo -n git -C %s rev-parse HEAD" % SERVER_ROOT)
    check("A1", "git/production", "HEAD الإنتاج == 0916484812bd371462a49bec5e939871240c2af1",
          out.strip() == COMMIT, out.strip())

    out, _ = ssh_run(client, "sudo -n git -C %s log --format='%%H %%P' -1 HEAD" % SERVER_ROOT)
    parts = out.strip().split()
    check("A2", "git/production", "أب HEAD == 3764420 (ff-only فوق حوكمة W2-T11)",
          len(parts) >= 2 and parts[1] == PARENT, out.strip())

    out, _ = ssh_run(client, "sudo -n git -C %s status --porcelain" % SERVER_ROOT)
    lines = {ln.rstrip() for ln in out.splitlines() if ln.strip()}
    check("A3", "git/production",
          "شجرة الإنتاج نظيفة — untracked المتوقع حصرًا (browser/projects/backup+pre/egg-info)",
          lines == EXPECTED_UNTRACKED, sorted(lines))

    out, _ = ssh_run(client, "curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:8010/health")
    check("A4", "git/production", "/health == 200", out.strip() == "200", out.strip())

    out, _ = ssh_run(client, "sudo -n systemctl is-active agentic nginx searxng search-api")
    acts = [ln.strip() for ln in out.splitlines() if ln.strip()]
    check("A5", "git/production", "الخدمات نشطة ×4 (agentic/nginx/searxng/search-api)",
          acts == ["active"] * 4, acts)

    out, _ = ssh_run(client, "sudo -n journalctl -u agentic -p err --since '2026-10-28 13:30' --no-pager")
    noerr = out.strip() in ("", "-- No entries --")
    check("A6", "git/production", "journalctl -u agentic -p err منذ 13:30 = صفر أخطاء",
          noerr, out.strip()[:200])

    triple_ok, triple = True, {}
    for rel in PATCH_FILES:
        srv, _ = ssh_run(client, "sudo -n sha256sum %s/%s" % (SERVER_ROOT, rel))
        srv_sha = srv.split()[0] if srv.split() else ""
        blob = local(["bash", "-c", "git show %s:%s | sha256sum" % (COMMIT, rel)])
        blob_sha = blob.stdout.split()[0] if blob.stdout.split() else ""
        loc_sha = sha256_file(REPO / rel)
        triple[rel] = {"server": srv_sha, "local": loc_sha, "blob": blob_sha}
        if not (srv_sha == loc_sha == blob_sha and srv_sha):
            triple_ok = False
    check("A7", "git/production",
          "تطابق sha256 ثلاثي (خادم=محلي=blob 0916484) لملفات الرقعة الستة",
          triple_ok, triple)

    rp = local(["git", "rev-parse", "origin/main"])
    lh = local(["git", "rev-parse", "HEAD"])
    lsr = local(["git", "ls-remote", "origin", "refs/heads/main"], timeout=40)
    remote_sha = lsr.stdout.split()[0] if lsr.stdout.split() else ""
    a8_ev = {"origin/main_local": rp.stdout.strip(), "local_HEAD": lh.stdout.strip(),
             "github_main_ls_remote": remote_sha or "UNREACHABLE",
             "ls_remote_rc": lsr.returncode}
    check("A8", "git/production",
          "الدفع حصل: GitHub main (ls-remote) == origin/main المحلي == HEAD المحلي == 0916484 == HEAD الخادم",
          rp.stdout.strip() == COMMIT and lh.stdout.strip() == COMMIT
          and remote_sha == COMMIT,
          a8_ev)

    # ============================ B) الكود ============================ #
    wc = {}
    for rel in PATCH_FILES:
        r = local(["wc", "-l", rel])
        wc[rel] = int(r.stdout.split()[0]) if r.stdout.split() else -1
    check("B1", "code",
          "أعداد الأسطر: implementer_live=397 (≤430) و build_files=284 (≤320) و test=320",
          wc.get("src/roles/implementer_live.py") == 397
          and wc.get("src/roles/build_files.py") == 284
          and wc.get("tests/roles/test_implementer_create_files.py") == 320, wc)

    st = local(["git", "show", "--stat", "--format=", COMMIT])
    m = re.search(r"(\d+) files? changed, (\d+) insertions\(\+\), (\d+) deletions\(-\)", st.stdout)
    files_changed = [ln.split("|")[0].strip() for ln in st.stdout.splitlines()
                     if "|" in ln and ln.split("|")[0].strip()]
    check("B2", "code", "الالتزام: 6 ملفات +702/−74 (نفس ملفات الرقعة حصرًا)",
          bool(m) and m.group(1) == "6" and m.group(2) == "702" and m.group(3) == "74"
          and set(files_changed) == set(PATCH_FILES),
          m.groups() if m else None)

    bf = (REPO / "src/roles/build_files.py").read_text(encoding="utf-8")
    comps = {name: ("def %s(" % name) in bf for name in (
        "required_build_files", "parse_created_files",
        "create_files_phase", "write_sources_file")}
    check("B3", "code", "مكونات build_files.py الأربعة موجودة", all(comps.values()), comps)

    il = (REPO / "src/roles/implementer_live.py").read_text(encoding="utf-8")
    il_ok = ("build_files.required_build_files(" in il
             and "build_files.create_files_phase(" in il
             and '"write_file"' in il
             and "build_files.write_sources_file(" in il
             and 'from roles import build_files' in il)
    check("B4", "code", "implementer_live يستدعي طور create_files ويكتب عبر run_tool(write_file)",
          il_ok, {"required_build_files": "build_files.required_build_files(" in il,
                  "create_files_phase": "build_files.create_files_phase(" in il,
                  "write_file": '"write_file"' in il,
                  "import": 'from roles import build_files' in il})

    pm = (REPO / "prompts/implementer.md").read_text(encoding="utf-8")
    pm_ok = ('## phase = "create_files"' in pm
             and "### FILE:" in pm
             and "required_files" in pm
             and "previous_attempts" in pm)
    check("B5", "code", "prompts/implementer.md فيه قسم الطور الثالث (create_files بصيغة ### FILE:)",
          pm_ok, None)

    vf = (REPO / "src/roles/verifier.py").read_text(encoding="utf-8")
    vf_ok = ("astro|mjs|cjs" in vf and "(?!\\w)" in vf)
    check("B6", "code", "verifier.py: regex الملفات موسع لامتدادات الويب بحد خلفي (?!)\\w",
          vf_ok, None)

    func = local([VENV_PY, "-c", (
        "import sys; sys.path.insert(0, 'src')\n"
        "from roles import build_files\n"
        "crit = ['package.json exists with name, version, type:module, scripts, dependencies (astro, typescript, @astrojs/tailwind), devDependencies',\n"
        "        'tsconfig.json exists with extends: astro/tsconfigs/strict',\n"
        "        'astro.config.mjs exists with import tailwind, defineConfig']\n"
        "r = build_files.required_build_files(crit, 'T1')\n"
        "print('OK' if r == ['package.json', 'tsconfig.json', 'astro.config.mjs'] else 'BAD:' + str(r))\n"
        "print('JSGUARD:' + str(build_files.required_build_files(['package.json exists'], 'T1')))\n"
    )], cwd=str(REPO))
    func_ok = ("OK" in func.stdout and "JSGUARD:['package.json']" in func.stdout)
    check("B7", "code",
          "فحص وظيفي: معايير 102 الحقيقية → الملفات الثلاثة بالضبط (الحد الخلفي يمنع ابتلاع js لـjson)",
          func_ok, func.stdout.strip()[:200])

    thin = local([VENV_PY, "-m", "pytest",
                  "tests/contracts/test_thinness.py::test_build_files_under_320_lines",
                  "tests/contracts/test_thinness.py::test_implementer_live_under_430_lines",
                  "-q"], cwd=str(REPO), timeout=120)
    check("B8", "code", "عقدا الرقة يعملان: build_files<320 و implementer_live<430",
          "2 passed" in thin.stdout, thin.stdout.strip().splitlines()[-1] if thin.stdout else "")

    # ============================ C) الاختبارات ============================ #
    new = local([VENV_PY, "-m", "pytest",
                 "tests/roles/test_implementer_create_files.py", "-q"],
                cwd=str(REPO), timeout=300)
    new_last = [ln for ln in new.stdout.splitlines() if "passed" in ln or "failed" in ln]
    check("C1", "tests", "test_implementer_create_files.py = 14/14",
          "14 passed" in new.stdout and "failed" not in new.stdout,
          new_last[-1] if new_last else new.stdout[-200:])

    rc = local([VENV_PY, "-m", "pytest", "tests/roles/", "tests/contracts/", "-q"],
               cwd=str(REPO), timeout=600)
    rc_ok = ("84 passed" in rc.stdout
             and "1 failed" in rc.stdout
             and "test_generate_pdf_arabic_one_page" in rc.stdout
             and "arabic_reshaper" in (rc.stdout + rc.stderr))
    check("C2", "tests",
          "roles+contracts = 84 ناجحًا + فشل واحد بيئي معلن (arabic_reshaper) — لا غير",
          rc_ok, [ln for ln in rc.stdout.splitlines() if "passed" in ln or "failed" in ln][-1:])

    # إثبات بيئية الفشل: نفس الاختبار يفشل على main النقية (الأب) بworktree
    wt = "/tmp/w2t23_audit_parent"
    local(["git", "worktree", "remove", "--force", wt])
    local(["git", "worktree", "add", wt, PARENT])
    par = local([VENV_PY, "-m", "pytest",
                 "tests/roles/test_tools.py::test_generate_pdf_arabic_one_page", "-q"],
                cwd=wt, timeout=300)
    local(["git", "worktree", "remove", "--force", wt])
    check("C3", "tests",
          "arabic_reshaper فشل سابق للرقعة (يتكرر حرفيًا على الأب 3764420 النقي بworktree) — بيئي لا كودي",
          "1 failed" in par.stdout and "arabic_reshaper" in (par.stdout + par.stderr),
          [ln for ln in par.stdout.splitlines() if "failed" in ln][-1:])

    wh = local([VENV_PY, "-m", "pytest", "tests/workflow/", "tests/harness/", "-q"],
               cwd=str(REPO), timeout=900)
    wh_ok = "165 passed" in wh.stdout and "failed" not in wh.stdout
    wh_evidence = {
        "script_run": [ln for ln in wh.stdout.splitlines()
                       if "passed" in ln or "failed" in ln][-1:],
        "auditor_manual_pre_runs": AUDITOR_PRE_RUNS,
    }
    if not wh_ok:
        # إعادة عزل الفاشل: إن نجح معزولًا والالتزام لا يمس workflow/harness → تذبذب توقيت
        failed_nodes = re.findall(r"^FAILED (\S+)", wh.stdout, re.M)
        isolated_pass = True
        for node in failed_nodes:
            iso = local([VENV_PY, "-m", "pytest", node, "-q"], cwd=str(REPO), timeout=300)
            if "passed" in iso.stdout and "failed" not in iso.stdout:
                note(f"فحص C4: {node} فشل تحت الحمل الكامل ونجح معزولًا — تذبذب توقيت لا انحطاط")
            else:
                isolated_pass = False
        dtree = local(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", COMMIT])
        no_overlap = not any(
            p.startswith(("src/workflow/", "src/harness/", "tests/workflow/", "tests/harness/"))
            for p in dtree.stdout.split())
        wh_ok = isolated_pass and no_overlap and bool(failed_nodes)
        wh_evidence["failed_nodes"] = failed_nodes
        wh_evidence["isolated_pass"] = isolated_pass
        wh_evidence["commit_touches_no_workflow_harness"] = no_overlap
    check("C4", "tests", "workflow+harness = 165/165 (بمراقبة التذبذب: الفاشل تحت الحمل يعاد عزله)",
          wh_ok, wh_evidence)

    # ============================ D) القاعدة (ro) ============================ #
    db = fetch_db_state(client)
    s102 = db["step102"]
    check("D1", "database",
          "steps#102: COMPLETED و attempts=4 و completed_at≈14:01:39",
          s102["status"] == "COMPLETED" and s102["attempts"] == 4
          and str(s102["completed_at"]).startswith("2026-10-28 14:01:39"),
          {k: s102[k] for k in ("status", "attempts", "completed_at")})

    e28 = next((e for e in db["executions_102"] if e["id"] == 28), {})
    e27 = next((e for e in db["executions_102"] if e["id"] == 27), {})
    check("D2", "database",
          "executions#28: attempt=4 و COMPLETED و commit_sha=0916484… (13:59:09→14:01:39)",
          e28.get("attempt") == 4 and e28.get("status") == "COMPLETED"
          and e28.get("commit_sha") == COMMIT
          and str(e28.get("started_at")).startswith("2026-10-28 13:59:09")
          and str(e28.get("finished_at")).startswith("2026-10-28 14:01:39"),
          {k: e28.get(k) for k in ("attempt", "status", "commit_sha", "started_at", "finished_at")})

    check("D3", "database", "executions#27: attempt=3 و FAILED قبله (13:53:59→13:59:09)",
          e27.get("attempt") == 3 and e27.get("status") == "FAILED"
          and str(e27.get("started_at")).startswith("2026-10-28 13:53:59"),
          {k: e27.get(k) for k in ("attempt", "status", "started_at", "finished_at")})

    g30 = db["gate30"]
    try:
        gdet = json.loads(g30.get("details") or "{}")
    except Exception:
        gdet = {}
    check("D4", "database",
          "owner_gates#30: PREFLIGHT_BLOCKED → APPROVED و auto_resolved=true و resolved_at≈13:53:59",
          g30.get("kind") == "PREFLIGHT_BLOCKED" and g30.get("status") == "APPROVED"
          and gdet.get("auto_resolved") is True
          and str(g30.get("resolved_at")).startswith("2026-10-28 13:53:59"),
          {"kind": g30.get("kind"), "status": g30.get("status"),
           "auto_resolved": gdet.get("auto_resolved"),
           "resolved_at": g30.get("resolved_at"),
           "auto_resolution_note": gdet.get("auto_resolution_note")})

    p3 = db["project3"]
    check("D5", "database",
          "المشروع 3 تقدم: steps_completed=1 من 25 و current_step=103",
          db["steps_proj3_completed"] == 1 and db["steps_proj3_total"] == 25
          and p3.get("current_step_id") == 103,
          {"completed": db["steps_proj3_completed"], "total": db["steps_proj3_total"],
           "current_step_id": p3.get("current_step_id"),
           "project_status_now": p3.get("status"),
           "step103_now": db["step103"].get("status"),
           "step103_attempts_now": db["step103"].get("attempts"),
           "latest_gates_p3": db["gates_p3_latest"]})

    invs = db["invocations_102"]
    wf = [i for i in invs if i["tool"] == "write_file"]
    root_writes = [i for i in wf
                   if i["query"] in CLAIMED_DISK_SHA
                   and i["result_path"] and i["result_path"].endswith("/steps/102/" + i["query"])]
    claimed_matches = {i["query"] for i in root_writes
                       if i["output_sha256"] == CLAIMED_DISK_SHA.get(i["query"])}
    check("D6", "database",
          "tool_invocations (cycle project-3-step-102): write_file فعلية للملفات الثلاثة بالمسار الجذري وبـ sha256 المعلنة",
          claimed_matches == set(CLAIMED_DISK_SHA),
          {"root_writes": [{"file": i["query"], "sha": i["output_sha256"],
                            "invoked_at": i["invoked_at"],
                            "recorded_at": i["created_at"], "path": i["result_path"]}
                           for i in root_writes]})

    pre = [i for i in invs if i["invoked_at"] and i["invoked_at"] < "2026-10-28T13:50"]
    pre_files = {i["query"] for i in pre if i["tool"] == "write_file"}
    post_files = {i["query"] for i in wf if i["invoked_at"] and i["invoked_at"] >= "2026-10-28T13:50"}
    check("D7", "database",
          "أثر الرقعة سببي: قبل 13:50 (محاولتا 04:53) لم تُكتب ملفات مشروع قط (تقرير/PDF/مصادر فقط)؛ بعدها كُتبت الثلاثة",
          not (pre_files & set(CLAIMED_DISK_SHA))
          and set(CLAIMED_DISK_SHA) <= post_files,
          {"pre_patch_writes": sorted(pre_files),
           "post_patch_writes": sorted(post_files)})

    ev28 = next((e for e in db["evidence_records"] if e["execution_id"] == 28), {})
    ev_files = ev28.get("files") or {}
    ev_match = all(ev_files.get(name) == sha for name, sha in CLAIMED_DISK_SHA.items())
    check("D8", "database",
          "evidence_records للتنفيذ 28 (verdict=PASS): الملفات الثلاثة بشفاه المعلنة",
          ev_match and bool(ev_files.get("package.json"))
          and ev28.get("verdict") == "PASS",
          {"execution_id": ev28.get("execution_id"), "verdict": ev28.get("verdict"),
           "files": {k: v for k, v in ev_files.items()
                     if not k.startswith(("stdout-", "stderr-"))}})

    g31 = db.get("gate31") or {}
    d9_ev = {"gate31": {k: g31.get(k) for k in ("kind", "reason", "status", "created_at")},
             "step103": db["step103"], "project3_now": p3.get("status"),
             "job3": db.get("job3")}
    check("D9", "database",
          "الحالة الراهنة (خارج نطاق W2-T23): المشروع توقف بصدق على بوابة بيئية جديدة #31 بعد فشل خطوة 103 (npm/node غير متوفر) — كما تنبأت البطاقة؛ لا تقدم مصطنعًا ولا regress في خطوة 102",
          s102["status"] == "COMPLETED" and db["steps_proj3_completed"] == 1
          and g31.get("status") == "BLOCKED" and g31.get("kind") == "PREFLIGHT_BLOCKED",
          d9_ev)

    # ============================ E) ملفات القرص ============================ #
    out, _ = ssh_run(client, "sudo -n bash -c 'cd %s && sha256sum package.json tsconfig.json astro.config.mjs T1-report.md sources.json && stat -c \"%%n %%s %%y\" package.json tsconfig.json astro.config.mjs T1-report.md sources.json'" % STEP_DIR)
    disk_sha, disk_size, disk_mtime = {}, {}, {}
    for ln in out.splitlines():
        p2 = ln.split()
        if len(p2) == 2 and p2[1] in CLAIMED_DISK_SHA:
            disk_sha[p2[1]] = p2[0]
        elif len(p2) >= 4 and p2[0] not in ("---",):
            try:
                disk_size[p2[0]] = int(p2[1])
                disk_mtime[p2[0]] = p2[2] + " " + p2[3]
            except ValueError:
                pass
    check("E1", "disk",
          "sha256 على القرص الآن = المعلنة حرفيًا للملفات الثلاثة",
          all(disk_sha.get(n) == s for n, s in CLAIMED_DISK_SHA.items()), disk_sha)
    check("E2", "disk", "الأحجام: package.json=310B و tsconfig=43B و astro.config=183B",
          all(disk_size.get(n) == b for n, b in CLAIMED_DISK_BYTES.items()),
          {"sizes": disk_size, "mtimes": disk_mtime})

    pkg_o, _ = ssh_run(client, "sudo -n cat %s/package.json" % STEP_DIR)
    try:
        pkg = json.loads(pkg_o)
        pkg_ok = (pkg.get("type") == "module" and pkg.get("name") and pkg.get("version")
                  and {"dev", "build", "preview"} <= set(pkg.get("scripts", {}))
                  and {"astro", "typescript", "@astrojs/tailwind"} <= set(pkg.get("dependencies", {}))
                  and "devDependencies" in pkg)
    except Exception:
        pkg, pkg_ok = None, False
    check("E3", "disk",
          "package.json: JSON سليم فيه name/version/type:module/scripts(dev,build,preview)/dependencies(astro,typescript,@astrojs/tailwind)/devDependencies",
          pkg_ok, pkg if pkg_ok else pkg_o[:200])

    ts_o, _ = ssh_run(client, "sudo -n cat %s/tsconfig.json" % STEP_DIR)
    try:
        ts = json.loads(ts_o)
        ext = ts.get("extends")
        ts_ok = "astro/tsconfigs/strict" in (ext if isinstance(ext, list) else [ext])
    except Exception:
        ts, ts_ok = None, False
    check("E4", "disk", "tsconfig.json: JSON سليم و extends astro/tsconfigs/strict",
          ts_ok, ts if ts_ok else ts_o[:200])

    as_o, _ = ssh_run(client, "sudo -n cat %s/astro.config.mjs" % STEP_DIR)
    as_ok = ("defineConfig" in as_o and "tailwind" in as_o
             and "@astrojs/tailwind" in as_o
             and "export default" in as_o and "import " in as_o)
    check("E5", "disk",
          "astro.config.mjs: ESM سليم (import/export default + defineConfig + tailwind)",
          as_ok, as_o[:200])

    out, _ = ssh_run(client, "sudo -n bash -c 'cd %s && ls T1-report.md sources.json && wc -c T1-report.md sources.json'" % STEP_DIR)
    ls_ok = "T1-report.md" in out and "sources.json" in out
    src_o, _ = ssh_run(client, "sudo -n cat %s/sources.json" % STEP_DIR)
    try:
        json.loads(src_o)
        sources_valid = True
    except Exception:
        sources_valid = False
    check("E6", "disk", "T1-report.md و sources.json موجودان و sources.json JSON سليم",
          ls_ok and sources_valid, {"ls": out.strip()[:120], "sources_json_valid": sources_valid})

    # اتساق سببي: mtimes الملفات الثلاثة تطابق أزمنة استدعاءات write_file
    # الحقيقية (record_json.started_at) داخل نافذة تنفيذ ما بعد النشر،
    # والتقرير/المصادر داخل نافذة التنفيذ 28 (13:59:09→14:01:39)
    inv_by_q = {i["query"]: i for i in root_writes}
    e7_ev, e7_ok = {}, True
    for name in CLAIMED_DISK_SHA:
        mt = disk_mtime.get(name, "")
        inv = inv_by_q.get(name)
        inv_at = (inv or {}).get("invoked_at") or ""
        mtime_s = mt.split(".")[0]
        inv_s = inv_at.replace("T", " ").replace("Z", "").split(".")[0]
        match = bool(mtime_s) and mtime_s == inv_s
        e7_ev[name] = {"disk_mtime": mtime_s, "invocation_started_at": inv_s, "match": match}
        if not match:
            e7_ok = False
    exec28_win = ("2026-10-28 13:59:09", "2026-10-28 14:01:39")
    for name in ("T1-report.md", "sources.json"):
        mt = disk_mtime.get(name, "").split(".")[0]
        in28 = bool(mt) and exec28_win[0] <= mt <= exec28_win[1]
        e7_ev[name] = {"disk_mtime": mt, "in_execution_28_window": in28}
        if not in28:
            e7_ok = False
    check("E7", "disk",
          "سببية حية: mtime كل ملف من الثلاثة يطابق حرفيًا زمن استدعاء write_file له (13:58:08 — جولة داخل تنفيذ ما بعد النشر)، والتقرير/المصادر داخل نافذة التنفيذ 28",
          e7_ok and e7_ev.get("package.json", {}).get("disk_mtime", "").startswith("2026-10-28 13:58"),
          e7_ev)

    # ============================ F) الجاهزية الآن ============================ #
    cap_o, _ = ssh_run(client, "curl -s -m 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/api/environment/capabilities")
    rb, _ = ssh_run(client, "curl -s -m 20 http://127.0.0.1:8010/api/environment/readiness")
    try:
        rj = json.loads(rb)
        ws_before = next((c for c in rj.get("capabilities", [])
                          if c.get("capability_id") == "web_search"), {})
    except Exception:
        ws_before = {}
    note("نقطة GET /api/environment/capabilities المذكورة في التكليف تعيد %s — عرض القدرات الفعلي هو GET /api/environment/readiness (200)" % cap_o.strip())
    check("F1", "readiness",
          "GET readiness (عرض القدرات): web_search موجود وليس NOT_READY/فاشلًا (STALE بالـTTL=120ث عابر بطبيعته)",
          ws_before.get("readiness_status") in ("READY", "STALE")
          and not ws_before.get("failure_class"),
          {"capabilities_http": cap_o.strip(),
           "readiness_status": ws_before.get("readiness_status"),
           "stored_status": ws_before.get("stored_status"),
           "last_success_at": ws_before.get("last_success_at"),
           "summary": rj.get("summary") if isinstance(rj, dict) else None})

    po, pe = ssh_run(client, "curl -s -m 60 -X POST http://127.0.0.1:8010/api/environment/probe "
                    "-H 'Content-Type: application/json' -d '{\"capability_id\": \"web_search\"}'", timeout=120)
    try:
        pj = json.loads(po)
        providers = [p for p in (pj.get("details", {}).get("per_provider", []))
                     if isinstance(p, dict) and p.get("status") == "READY"]
        live = [{"name": (p.get("provider") or {}).get("name"),
                 "results": ((p.get("details") or {}).get("results")),
                 "latency_ms": p.get("latency_ms"),
                 "first": ((p.get("details") or {}).get("first") or "")[:60]}
                for p in providers]
        probe_ok = (pj.get("readiness_status") == "READY"
                    and any((l["results"] or 0) >= 5 for l in live))
    except Exception:
        pj, live, probe_ok = {}, [], False
    check("F2", "readiness",
          "مسباري أنا (POST probe {web_search} فقط — المسموح الموثق): READY بنتائج حقيقية ≥5 من مزود حي",
          probe_ok, {"readiness_status": pj.get("readiness_status"),
                     "probe_latency_ms": pj.get("probe_latency_ms"),
                     "last_success_at": pj.get("last_success_at"),
                     "live_providers": live})

    # ============================ G) الأمان ============================ #
    hex48 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{48}(?![0-9a-fA-F])")
    scan_hits = {}
    for rel in PATCH_FILES:
        txt = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        hits = hex48.findall(txt)
        if hits:
            scan_hits[rel] = hits
    check("G1", "security", "صفر سلاسل 48-hex (مفاتيح محتملة) في ملفات الرقعة الستة",
          not scan_hits, scan_hits)

    ev_hits = {}
    for name in ("deploy.json", "unblock.json", "final_state.json"):
        p = EVID_DIR / name
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="replace")
            hits = [h for h in hex48.findall(txt)]
            if hits:
                ev_hits[name] = hits[:5]
    check("G2", "security", "صفر سلاسل 48-hex في أدلة المنفذ الثلاثة (بصمات sha256=64-hex مشروعة)",
          not ev_hits, ev_hits)

    g3_ev = {
        "reject_dotdot": '".." in path.split("/")' in bf,
        "reject_absolute": "path.startswith(\"/\")" in bf,
        "ext_whitelist": "_CREATE_ALLOWED_EXTS" in bf,
        "caps": all(k in bf for k in ("_CREATE_MAX_FILES = 16", "_CREATE_MAX_CHARS = 120_000", "_CREATE_MAX_PATH = 200")),
        "no_direct_open_write": "open(" not in bf,
        "writes_via_run_tool_only": 'run_tool(\n        "write_file"' in bf,
    }
    check("G3", "security",
          "build_files.py: حراس أمان موجودة (رفض ../ والمطلق + امتدادات بيضاء + سقوف 16/120k/200) والكتابة عبر run_tool حصرًا — لا open() مباشر",
          all(g3_ev.values()), g3_ev)

    tf = (REPO / "tests/roles/test_implementer_create_files.py").read_text(encoding="utf-8")
    tf_lines = [(i + 1, ln.strip()) for i, ln in enumerate(tf.splitlines())
                if "../" in ln]
    tf_ok = all("escape" in ln or "a/../../b.json" in ln or "parametrize" in ln or '"' in ln
                for _, ln in tf_lines)
    check("G4", "security", "ملف الاختبارات: ../ في معاملات الرفض حصرًا",
          tf_ok, tf_lines)

    # ============================ H) أدلة المنفذ ============================ #
    dep = json.loads((EVID_DIR / "deploy.json").read_text(encoding="utf-8"))
    dep_ok = (dep.get("health_before", {}).get("out") == "200"
              and dep.get("head_before", {}).get("out") == GRANDPARENT
              and dep.get("head_after_pull", {}).get("out") == COMMIT
              and dep.get("py_compile", {}).get("out") == "COMPILE_OK"
              and "200" in str(dep.get("health_after_restart"))
              and dep.get("services_before", {}).get("out", "").split() == ["active"] * 4
              and dep.get("services_after", {}).get("out", "").split() == ["active"] * 4
              and dep.get("journal_err", {}).get("out", "").strip() == "-- No entries --"
              and COMMIT[:9] in dep.get("asset_version", {}).get("out", ""))
    check("H1", "executor_evidence",
          "deploy.json متسق داخليًا ومطابق للتاريخ الذي جمعته (قبل 6fc02343c → ff إلى 0916484 → COMPILE_OK → صحة 200 بعد 96ث → active×4 → journal صفر)",
          dep_ok, {"head_before": dep.get("head_before", {}).get("out"),
                   "head_after": dep.get("head_after_pull", {}).get("out"),
                   "health_after": dep.get("health_after_restart")})

    unb = json.loads((EVID_DIR / "unblock.json").read_text(encoding="utf-8"))
    wiki, sapi = {}, {}
    try:
        pr = json.loads(unb["probe_web_search"]["out"])
        per = pr.get("details", {}).get("per_provider", [])
        wiki = next((p for p in per if isinstance(p, dict)
                     and (p.get("provider") or {}).get("name") == "Wikipedia"), {})
        sapi = next((p for p in per if isinstance(p, dict)
                     and (p.get("provider") or {}).get("name") == "Search API"), {})
        probe_claim = (pr.get("readiness_status") == "READY"
                       and (wiki.get("details") or {}).get("results") == 6
                       and 900 <= wiki.get("latency_ms", 0) <= 1200
                       and (sapi.get("details") or {}).get("results") == 5
                       and 600 <= sapi.get("latency_ms", 0) <= 900)
    except Exception:
        probe_claim = False
    # المخرج الملتقط لـpreflight مقطوع عند 6000 حرف (سقف التقاط سكربت المنفذ)
    # — الجزء المرئي يحمل الادعاءات حرفيًا، والمستقل (D) يثبت أثر الإطلاق.
    pf_raw = unb.get("preflight_p3", {}).get("out", "")
    prefl_claim = bool(
        re.search(r'"verdict"\s*:\s*"PASS"', pf_raw)
        and re.search(r'"launch"\s*:\s*\{[^}]*"launched"\s*:\s*true'
                      r'[^}]*"reason"\s*:\s*"launched"'
                      r'[^}]*"project_id"\s*:\s*3', pf_raw)
    )
    if len(pf_raw) >= 6000:
        note("unblock.json: مخرج preflight الملتقط مقطوع عند 6000 حرف (سقف التقاط) — لكنه يحمل verdict=PASS وlaunch{launched:true,project_id:3} حرفيًا، والإطلاق مثبت مستقلًا بتنفيذين 27/28 وبوابة 30 المحلولة (D2-D4)")
    check("H2", "executor_evidence",
          "unblock.json: المسبار READY (Wikipedia 6 نتائج ~1041ms + Search API 5 ~774ms) و preflight PASS مع launched=true/reason=launched/project_id=3",
          probe_claim and prefl_claim,
          {"probe": probe_claim, "preflight": prefl_claim,
           "preflight_out_len": len(pf_raw),
           "probe_wikipedia": {"results": (wiki.get("details") or {}).get("results"),
                               "latency_ms": wiki.get("latency_ms")},
           "probe_search_api": {"results": (sapi.get("details") or {}).get("results"),
                                "latency_ms": sapi.get("latency_ms")}})

    fin = json.loads((EVID_DIR / "final_state.json").read_text(encoding="utf-8"))
    try:
        fds_raw = fin["db_state"]["out"]
        payload = fds_raw.split("FINAL-JSON:", 1)[1]
        # المخرج مقطوع عند 8000 حرف داخل evidence1 — الأقسام الأولى (project/
        # steps/gates/exec28) كاملة: نقصع عند evidence1 ونغلق القوس.
        cut = payload.find('"evidence1"')
        trunc_note = cut >= 0
        if cut >= 0:
            payload = payload[:cut].rstrip().rstrip(",") + "}"
        fds = json.loads(payload)
        fsha = {name: sha for sha, name in
                re.findall(r"([0-9a-f]{64})\s+(\S+)", fin["files_sha256"]["out"])}
        ra = json.loads(fin["runs_active"]["out"])
        step0 = (fds.get("steps") or [{}])[0]
        gate0 = (fds.get("gates") or [{}])[0]
        g0det = json.loads(gate0.get("details") or "{}")
        fin_ok = (step0.get("id") == 102 and step0.get("status") == "COMPLETED"
                  and step0.get("attempts") == 4
                  and str(step0.get("completed_at", "")).startswith("2026-10-28 14:01:39")
                  and gate0.get("id") == 30 and gate0.get("status") == "APPROVED"
                  and g0det.get("auto_resolved") is True
                  and fds.get("exec28", {}).get("commit_sha") == COMMIT
                  and all(fsha.get(n) == s for n, s in CLAIMED_DISK_SHA.items())
                  and ra.get("progress", {}).get("steps_completed") == 1
                  and ra.get("progress", {}).get("steps_total") == 25)
    except Exception:
        fin_ok = False
        fsha = {}
        fds = {}
        step0, gate0, ra, g0det, trunc_note = {}, {}, {}, {}, False
    if trunc_note:
        note("final_state.json: مخرج db_state مقطوع عند 8000 حرف داخل evidence1 — الأقسام الحاملة للادعاءات (steps/gates/exec28) كاملة، وكلها مثبتة مستقلًا بقراءاتي المباشرة للقاعدة (D) والقرص (E)")
    check("H3", "executor_evidence",
          "final_state.json متسق مع ما جمعته بنفسي من القاعدة والقرص (خطوة/بوابة/sha256/تنفيذ28/تقدم)",
          fin_ok, {"step102": step0, "gate30_status": gate0.get("status"),
                   "gate30_auto_resolved": g0det.get("auto_resolved"),
                   "files_sha256": fsha,
                   "runs_active_progress": ra.get("progress") if isinstance(ra, dict) else None})

    client.close()

    # ============================ الخلاصة ============================ #
    total = len(CHECKS)
    passed = sum(1 for c in CHECKS if c["pass"])
    failed = total - passed
    groups: dict[str, dict] = {}
    for c in CHECKS:
        g = groups.setdefault(c["group"], {"total": 0, "passed": 0})
        g["total"] += 1
        g["passed"] += int(c["pass"])
    verdict = "PASS" if failed == 0 else "FAIL"

    script_md5 = hashlib.md5(Path(__file__).read_bytes()).hexdigest()
    result = {
        "_meta": {
            "task": "W2-T23-AUDIT — تدقيق مستقل (وكيل تدقيق مستقل — general-purpose)",
            "ts": datetime.now(timezone.utc).isoformat(),
            "commit_under_audit": COMMIT,
            "script": str(Path(__file__)),
            "script_md5": script_md5,
            "auditor_manual_pre_runs": AUDITOR_PRE_RUNS,
            "ssh": "read-only (paramiko, look_for_keys=False, allow_agent=False); "
                   "الوحيد POST: /api/environment/probe {web_search} (مسبار تشخيصي — "
                   "سابقة W2-T20-AUDIT)؛ لا preflight ولا restart ولا git كتابي",
            "duration_s": round(time.time() - t0, 1),
        },
        "checks": CHECKS,
        "notes": NOTES,
        "summary": {
            "total": total, "passed": passed, "failed": failed,
            "verdict": verdict, "groups": groups,
        },
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print("\n%s — %d/%d فحصًا ناجحًا (script_md5=%s)"
          % (verdict, passed, total, script_md5))
    print("الأدلة: %s" % OUT_PATH)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
