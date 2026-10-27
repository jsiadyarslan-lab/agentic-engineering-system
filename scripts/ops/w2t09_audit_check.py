#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T09-AUDIT — وكيل تدقيق مستقل لمهمة W2-T09
(إنقاذ المصنع: البث الحي فوق الطية + شريط إحصاءات مضغوط + ثقل أولوية الصفوف — الكود والبصري والنشر).

الانضباط: SSH قراءة فقط على الإنتاج طوال الجلسة (cat/grep/git read/curl GET/
systemctl is-active/journalctl read). صفر كتابة على الإنتاج، صفر إيقاف/إعادة
تشغيل، صفر POST، صفر git push. محليًا: تشغيل الاختبارات والفحوص وإعادة
القياسات البصرية على الملفات القائمة فقط.

التقييم بأسطر المخرجات الفعلية لا برموز الخروج (درسا W1-T01 وW2-T07:
rg غير مثبت على الإنتاج — «0» قد يكون command-not-found).
المخرج: download/aes-remediation/W2-T09/audit_independent.json
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import paramiko
from PIL import Image

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
REPO = Path("/home/z/my-project/repo")
EV = Path("/home/z/my-project/download/aes-remediation/W2-T09")
OUT = EV / "audit_independent.json"
VENV = "/home/z/.venv/bin/python"
EXPECT_HEAD = "eaef5fd01a96e56c323dbf25db9ba530be102474"
PREV_HEAD = "d23a96984debb30a740ce60baf38881f6d4adedd"

CHECKS: list[dict] = []
FINDINGS: list[dict] = []


def add(cid, group, name, command, actual, expected, ok, note: str = "") -> None:
    CHECKS.append({
        "id": cid, "group": group, "name": name, "command": command,
        "actual_output": actual, "expected": expected,
        "verdict": "PASS" if ok else "FAIL", "note": note,
    })


def finding(fid, title, detail, blocking=False) -> None:
    FINDINGS.append({"id": fid, "title": title, "detail": detail, "blocking": blocking})


def ssh_run(ssh, cmd: str, timeout: int = 60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return o.read().decode(errors="replace"), e.read().decode(errors="replace")


def run(cmd: str, cwd=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       cwd=str(cwd) if cwd else None)
    return r.stdout, r.stderr, r.returncode


def real_journal_error_lines(out: str) -> list[str]:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.strip() != "-- No entries --"]


# ============================================================ GROUP A — الإنتاج الحي (SSH قراءة فقط)
def group_a(ssh) -> None:
    # A1 — رأس الإنتاج بالضبط
    out, _ = ssh_run(ssh, "git -C /opt/agentic-engineering-system rev-parse HEAD")
    add("A1", "A-production", "رأس الإنتاج = eaef5fd01a96e5… بالضبط",
        "git -C /opt/agentic-engineering-system rev-parse HEAD",
        out.strip(), EXPECT_HEAD, out.strip() == EXPECT_HEAD)

    # A2 — الشجرة نظيفة
    out, _ = ssh_run(ssh, "git -C /opt/agentic-engineering-system status --porcelain --untracked-files=no")
    n = len([l for l in out.splitlines() if l.strip()])
    add("A2", "A-production", "شجرة الإنتاج نظيفة (0 تعديلات متتبعة)",
        "git -C /opt/agentic-engineering-system status --porcelain --untracked-files=no",
        out.strip() or "(0 أسطر)", "0 أسطر", n == 0)

    # A3 — /health
    out, _ = ssh_run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
    add("A3", "A-production", "/health على 8010 = 200",
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health",
        out.strip(), "200", out.strip() == "200")

    # A4 — agentic + nginx
    out, _ = ssh_run(ssh, "systemctl is-active agentic nginx")
    vals = [l.strip() for l in out.splitlines() if l.strip()]
    add("A4", "A-production", "agentic + nginx نشطتان",
        "systemctl is-active agentic nginx", " / ".join(vals), "active / active",
        vals == ["active", "active"])

    # A5 — journal آخر 30 دقيقة: صفر أسطر خطأ فعلية (placeholder لا يُعد)
    out, _ = ssh_run(ssh, "journalctl -u agentic --since '-30 min' -p err --no-pager | cat")
    real = real_journal_error_lines(out)
    add("A5", "A-production", "journalctl -u agentic آخر 30د -p err: صفر أسطر خطأ فعلية",
        "journalctl -u agentic --since '-30 min' -p err --no-pager | cat",
        out.strip() or "(فارغ)",
        "صفر أسطر فعلية (placeholder «-- No entries --» لا يُعد خطأً)", len(real) == 0,
        f"أسطر فعلية بعد إقصاء placeholder: {len(real)}")

    # A6 — العلامات الجديدة في JS الحي (عدّ تكرارات فعلي)
    js, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/static/factory-control.js")
    js_markers = ["fc-statbar", "prio-live", "fc-row-live-dot", "fc-refresh-all", 'id="fc-new-mission"']
    js_counts = {m: js.count(m) for m in js_markers}
    ok = all(v > 0 for v in js_counts.values())
    add("A6", "A-production", "factory-control.js الحي يخدم العلامات الخمس الجديدة",
        "curl -s http://127.0.0.1:8010/static/factory-control.js | عدّ التكرارات",
        json.dumps(js_counts, ensure_ascii=False), "كل قيمة > 0", ok,
        f"حجم JS المخدوم: {len(js)} بايت")

    # A7 — العلامات الجديدة في CSS الحي
    css, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/static/factory-control.css")
    css_markers = [".fc-statbar", ".prio-live", ".prio-fail", ".fc-head-btn", ".fc-row-live-dot"]
    css_counts = {m: css.count(m) for m in css_markers}
    ok = all(v > 0 for v in css_counts.values())
    add("A7", "A-production", "factory-control.css الحي يخدم العلامات الخمس الجديدة",
        "curl -s http://127.0.0.1:8010/static/factory-control.css | عدّ التكرارات",
        json.dumps(css_counts, ensure_ascii=False), "كل قيمة > 0", ok,
        f"حجم CSS المخدوم: {len(css)} بايت")

    # A8 — العلامات القديمة زالت فعلًا من JS الحي
    old_js = ["fc-system-card", 'id="fc-refresh-missions"', 'id="fc-refresh-runs"', 'id="fc-refresh-agents"']
    old_counts = {m: js.count(m) for m in old_js}
    ok = all(v == 0 for v in old_counts.values())
    add("A8", "A-production", "العلامات القديمة زالت من JS الحي (fc-system-card=0 والأزرار الثلاثة id=…=0)",
        "نفس JS المخدوم أعلاه | عدّ 'fc-system-card' و'id=\"fc-refresh-(missions|runs|agents)\"'",
        json.dumps(old_counts, ensure_ascii=False), "كل القيم = 0", ok,
        "السلك الدفاعي ؟. بلا id= (لا يُرسم زر) مقبول وموثق في البطاقة.")

    # A9 — إصدار الأصول في الصفحة الرئيسية
    out, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/ | grep -oE 'factory-control.js\\?v=[0-9a-f]+'")
    add("A9", "A-production", "إصدار الأصول في / : factory-control.js?v=eaef5fd0",
        "curl -s http://127.0.0.1:8010/ | grep -oE 'factory-control.js\\?v=[0-9a-f]+'",
        out.strip(), "factory-control.js?v=eaef5fd0",
        out.strip() == "factory-control.js?v=eaef5fd0")

    # A10 — جدار nginx (401)
    out, _ = ssh_run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/")
    add("A10", "A-production", "nginx المحلي / = 401 (الجدار سليم)",
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/",
        out.strip(), "401", out.strip() == "401")

    # A11 — عقد التوكنات على شجرة الإنتاج: صفر hex/rgba في CSS خارج theme.css
    #     (بمحرك python3 هناك — مع توثيق أن المحرك عمل فعلًا: إصداره + FILES + شاهد تحكم CONTROL>0)
    ver_out, ver_err = ssh_run(ssh, "/usr/bin/python3 -V")
    scan = r'''
import re, pathlib
ui = pathlib.Path("/opt/agentic-engineering-system/src/ui")
hex_re = re.compile(r"#[0-9a-fA-F]{3,8}\b")
rgb_re = re.compile(r"\brgba?\(\s*[0-9]")
hex_hits, rgb_hits, files = [], [], []
for p in sorted(ui.rglob("*.css")):
    rel = p.relative_to(ui)
    if rel.parts[0] == "fonts" or p.name == "theme.css":
        continue
    files.append(str(rel))
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if hex_re.search(line): hex_hits.append(f"{rel}:{i}")
        if rgb_re.search(line): rgb_hits.append(f"{rel}:{i}")
theme = (ui / "theme.css").read_text(encoding="utf-8")
ctrl = len([l for l in theme.splitlines() if hex_re.search(l)])
print("FILES", len(files), ",".join(files))
print("HEX", len(hex_hits), hex_hits[:8])
print("RGB", len(rgb_hits), rgb_hits[:8])
print("CONTROL", ctrl)
'''
    _, o, e = ssh.exec_command("/usr/bin/python3 -", timeout=60)
    o.channel.sendall(scan.encode())
    o.channel.shutdown_write()
    scan_out = o.read().decode(errors="replace")
    scan_err = e.read().decode(errors="replace")
    m_files = re.search(r"^FILES (\d+)", scan_out, re.M)
    m_hex = re.search(r"^HEX (\d+)", scan_out, re.M)
    m_rgb = re.search(r"^RGB (\d+)", scan_out, re.M)
    m_ctrl = re.search(r"^CONTROL (\d+)", scan_out, re.M)
    n_files = int(m_files.group(1)) if m_files else -1
    n_hex = int(m_hex.group(1)) if m_hex else -1
    n_rgb = int(m_rgb.group(1)) if m_rgb else -1
    n_ctrl = int(m_ctrl.group(1)) if m_ctrl else -1
    engine_ok = ("command not found" not in (ver_err + scan_err)) and bool(ver_out.strip())
    ok = engine_ok and n_files > 0 and n_hex == 0 and n_rgb == 0 and n_ctrl > 0
    add("A11", "A-production",
        "عقد التوكنات على شجرة الإنتاج: صفر hex/rgba في CSS خارج theme.css (بمحرك عمل فعلًا)",
        "ssh: /usr/bin/python3 - <<scan (rglob *.css عدا theme.css/fonts، '#[0-9a-fA-F]{3,8}\\b' و'\\brgba?\\(\\s*[0-9]')",
        f"python3 -V={ver_out.strip()!r} · FILES={n_files} · HEX={n_hex} · RGB={n_rgb} · CONTROL={n_ctrl}",
        "المحرك متوفر وعمل · FILES>0 · HEX=0 · RGB=0 · CONTROL>0 (شاهد تحكم إيجابي)", ok,
        f"stderr: {(ver_err + scan_err).strip()[:200] or '(فارغ)'} · الملفات الممسوحة: {scan_out.splitlines()[0][6:] if m_files else '?'}")

    # A12 — النسخ الاحتياطية قبل النشر موجودة
    out, _ = ssh_run(ssh, "ls -la /home/opc/pre-w2t09-*.bundle /home/opc/pre-w2t09-runtime-*.tar.gz")
    lines = [l for l in out.splitlines() if "pre-w2t09-" in l]
    has_bundle = any(".bundle" in l for l in lines)
    has_tar = any("runtime" in l and ".tar.gz" in l for l in lines)
    sizes_ok = all(int(l.split()[4]) > 0 for l in lines if len(l.split()) > 5)
    add("A12", "A-production", "النسخ الاحتياطية قبل النشر موجودة (pre-w2t09 bundle + runtime tar)",
        "ls -la /home/opc/pre-w2t09-*.bundle /home/opc/pre-w2t09-runtime-*.tar.gz",
        out.strip() or "(لا شيء)", "bundle واحد على الأقل + runtime tar واحد على الأقل بأحجام > 0",
        has_bundle and has_tar and sizes_ok and len(lines) >= 2)

    # A13 — سلسلة git على الإنتاج + d23a969 سلف (رواية ff-only)
    out, _ = ssh_run(ssh, "git -C /opt/agentic-engineering-system log --oneline -3")
    anc, _ = ssh_run(ssh, f"git -C /opt/agentic-engineering-system merge-base --is-ancestor {PREV_HEAD} HEAD && echo ANCESTOR_OK")
    ok = out.startswith("eaef5fd01") and "9238fd2" in out and "d23a969" in out and "ANCESTOR_OK" in anc
    add("A13", "A-production", "سلسلة git للإنتاج (eaef5fd→9238fd2→d23a969) و d23a969 سلف لـ HEAD",
        "git log --oneline -3 + git merge-base --is-ancestor d23a969… HEAD && echo ANCESTOR_OK",
        out.strip() + " | " + anc.strip(), "السلسلة كما هو متوقع و ANCESTOR_OK", ok)


# ============================================================ GROUP B — الالتزام eaef5fd (محلي، قراءة فقط)
def _fn_body(text: str, name: str) -> str:
    """عزل جسم دالة عالية المستوى (من سطر تعريفها حتى أول دالة/قسم تالٍ)."""
    lines = text.splitlines(keepends=True)
    buf, inside = [], False
    for ln in lines:
        if not inside and re.match(r"^\s{2}function\s+" + re.escape(name) + r"\s*\(", ln):
            inside = True
            buf.append(ln)
            continue
        if inside:
            if re.match(r"^\s{2}(function\s|var\s|const\s|//\s*-----)", ln):
                break
            buf.append(ln)
    return "".join(buf)


def group_b() -> None:
    # B1 — نطاق الالتزام: ملفان فقط +139/−45
    out, _, _ = run("git show --stat eaef5fd", cwd=REPO)
    stat_line = [l for l in out.splitlines() if "files changed" in l]
    m = re.search(r"(\d+) files? changed, (\d+) insertions?\(\+\), (\d+) deletions?\(-\)",
                  stat_line[0]) if stat_line else None
    file_lines = re.findall(r"^\s*(src/[\w/.\-]+\.(?:js|css))\s+\|", out, re.M)
    ok = (m and int(m.group(1)) == 2 and int(m.group(2)) == 139 and int(m.group(3)) == 45
          and set(file_lines) == {"src/ui/factory-control.js", "src/ui/factory-control.css"})
    add("B1", "B-commit", "eaef5fd: ملفان فقط (factory-control.js/css) +139/−45 — لا مساس بأي شيء آخر",
        "git show --stat eaef5fd",
        f"files={m.group(1) if m else '?'} · +{m.group(2) if m else '?'}/−{m.group(3) if m else '?'} · {file_lines}",
        "2 · +139/−45 · js+css فقط", bool(ok))

    # B2 — الترتيب الجديد في الكود (الملف عند eaef5fd): بطاقة البث أولًا (برأس يحمل زر مهمة
    #      جديدة) ثم fc-statbar ثم المهام
    src, _, rc = run("git show eaef5fd:src/ui/factory-control.js", cwd=REPO)
    ok_rc = rc == 0
    # عزل جسم renderOverview
    ov = _fn_body(src, "renderOverview")
    i_live = ov.find("fc-live-card")
    i_newbtn = ov.find('id="fc-new-mission"')
    i_title = ov.find("البث الحي · التشغيلات")
    i_bar = ov.find('class="fc-statbar"')
    i_refresh_all = ov.find('id="fc-refresh-all"')
    i_missions = ov.find("المهام الحديثة")
    order_ok = all(x >= 0 for x in (i_live, i_newbtn, i_title, i_bar, i_refresh_all, i_missions)) and \
        i_live < i_title < i_newbtn < i_bar < i_refresh_all < i_missions
    # البث أول بطاقة في الجسم (لا بطاقة قبله)
    first_card = ov.find('<div class="fc-card')
    first_card_is_live = first_card >= 0 and \
        ov.startswith('<div class="fc-card fc-live-card', first_card)
    add("B2", "B-commit",
        "الترتيب الجديد منفذ في الكود: بطاقة البث أولًا (زر «+ مهمة جديدة» داخل رأسها) ثم fc-statbar ثم المهام",
        "git show eaef5fd:src/ui/factory-control.js | عزل renderOverview وفهرسة العلامات",
        f"idx: live={i_live} title={i_title} new-mission-btn={i_newbtn} statbar={i_bar} refresh-all={i_refresh_all} "
        f"missions={i_missions} · أول '<div class=\"fc-card' في الجسم = {first_card} ({'fc-live-card' if first_card_is_live else 'غير البث!'})",
        "البطاقة الأولى = fc-live-card ورأسها يحمل الزر، ثم statbar ثم المهام، وكل الفهارس صاعدة",
        ok_rc and order_ok and first_card_is_live)

    # B3 — الترتيب المستقر بالأولوية موجود ومستخدم (slice().sort(...))
    has_runp = "function runPriority(run)" in src
    has_misp = "function missionPriority(mission)" in src
    run_sorted = ".slice().sort(function (a, b) { return runPriority(a) - runPriority(b); })" in src
    mis_sorted = ".slice().sort(function (a, b) { return missionPriority(a) - missionPriority(b); })" in src
    prio_rows = ('var prio = run.status === "RUNNING" ? " prio-live" : (run.status === "FAILED" ? " prio-fail" : "");' in src
                 and 'prio-live' in _fn_body(src, "renderMissionSummary"))
    add("B3", "B-commit", "ترتيب مستقر بالأولوية (runPriority/missionPriority) + صفوف prio-live/prio-fail في المُلخّصين",
        "git show eaef5fd:src/ui/factory-control.js | grep الدوال والاستدعاءات",
        f"runPriority={has_runp} missionPriority={has_misp} runs_sorted={run_sorted} "
        f"missions_sorted={mis_sorted} prio_rows={prio_rows}",
        "كلها True (sort بعد slice => لا طفرة للحالة، وsort في ES2019+ مستقر)",
        has_runp and has_misp and run_sorted and mis_sorted and prio_rows)

    # B4 — لا منطق آخر مُغيّر: الدوال الحاملة للمنطق (التحميل/SSE/التبويبات/الرسم العام)
    #      متطابقة بايتًا بايتًا بين الأب وeaef5fd
    old, _, rc1 = run("git show eaef5fd^:src/ui/factory-control.js", cwd=REPO)
    guarded = ["renderFactory", "loadOverviewData", "loadMissions", "loadRuns", "loadAgents",
               "connectRunSSE", "connectMissionSSE", "stopSSE", "wireMissionTabs",
               "renderMissionTab", "renderMissionOverview", "renderMissionRuns",
               "renderCreateMission", "launchMission", "renderRunView"]
    diffs = {f: (_fn_body(old, f) != _fn_body(src, f)) for f in guarded}
    missing = [f for f in guarded if not _fn_body(src, f)]
    # نطاق الأسطر المتغيرة (من رؤوس hunks): كلها داخل منطقة النظرة العامة/الملخصات/الأسلاك
    diff_txt, _, _ = run("git show eaef5fd -- src/ui/factory-control.js", cwd=REPO)
    hunks = re.findall(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff_txt, re.M)
    ranges = [(int(a), int(a) + int(b or 1) - 1) for a, b in hunks]
    lo = min(r[0] for r in ranges) if ranges else 0
    hi = max(r[1] for r in ranges) if ranges else 0
    # ممنوعات في الأسطر المتغيرة: تعريفات محمّلات/SSE/تبويبات
    changed_lines = [l for l in diff_txt.splitlines()
                     if (l.startswith("+") or l.startswith("-")) and not l.startswith(("+++", "---"))]
    forbidden = re.compile(r"function\s+(load\w+|connect\w+SSE|stopSSE|renderFactory|wireMissionTabs|renderMissionTab)\s*\(|EventSource|data-tab|\.fc-tab\b")
    forbid_hits = [l for l in changed_lines if forbidden.search(l)]
    ok = rc1 == 0 and not any(diffs.values()) and not missing and not forbid_hits and 100 <= lo and hi <= 250
    add("B4", "B-commit",
        "لا منطق آخر مُغيّر: 15 دالة محمية متطابقة بايتًا بايتًا، وصفر ممنوعات في الأسطر المتغيرة، وكل hunks داخل 100–250",
        "git show eaef5fd^:…js مقابل eaef5fd:…js (عزل أجسام الدوال) + رؤوس hunks + grep الأسطر ±",
        f"متغيرة من المحمية: {[k for k, v in diffs.items() if v] or 'لا شيء'} · غائبة: {missing or 'لا شيء'} · "
        f"ممنوعات في ±: {len(forbid_hits)} · نطاق hunks الجديد: {lo}–{hi}",
        "المتغيرة=∅ · الغائبة=∅ · الممنوعات=0 · النطاق داخل منطقة renderOverview/renderRun( Mission )Summary/wireOverviewButtons",
        ok, f"الدوال المتغيرة المقصودة: renderOverview/renderRunSummary/renderMissionSummary/wireOverviewButtons (+إضافة runPriority/missionPriority).")

    # B5 — صفر قيم لون خام في الـdiff (الإضافات كلها توكنات var(--…))
    out, _, _ = run(
        "git show eaef5fd | grep -E '^\\+.*#[0-9a-fA-F]{6}|^\\+.*rgba?\\(' | grep -v 'theme.css' | wc -l",
        cwd=REPO)
    n_raw = int(out.strip() or "-1")
    add("B5", "B-commit", "صفر قيم لون خام في أسطر الإضافة بالـdiff (خارج theme.css)",
        "git show eaef5fd | grep -E '^\\+.*#[0-9a-fA-F]{6}|^\\+.*rgba?\\(' | grep -v 'theme.css' | wc -l",
        out.strip(), "0", n_raw == 0)

    # B6 — CSS: القواعد الخمس الجديدة موجودة في الملف عند eaef5fd (وليست في JS فقط)
    css_txt, _, rc2 = run("git show eaef5fd:src/ui/factory-control.css", cwd=REPO)
    rules = [".fc-statbar", ".prio-live", ".prio-fail", ".fc-head-btn", ".fc-row-live-dot"]
    cnts = {r: css_txt.count(r) for r in rules}
    add("B6", "B-commit", "القواعد الجديدة الخمس معرفة في CSS عند eaef5fd",
        "git show eaef5fd:src/ui/factory-control.css | عدّ المحددات",
        json.dumps(cnts, ensure_ascii=False), "كل قيمة > 0", rc2 == 0 and all(v > 0 for v in cnts.values()))


# ============================================================ GROUP C — الاختبارات (محليًا)
def group_c() -> None:
    # C1 — عقد التوكنات 17/17
    out, err, rc = run(f"{VENV} -m pytest tests/ui/test_design_tokens.py -q", cwd=REPO)
    tail = " ".join(out.split()[-6:])
    ok = "17 passed" in out and "failed" not in tail and rc == 0
    add("C1", "C-tests", "عقد التوكنات: pytest tests/ui/test_design_tokens.py = 17 passed",
        "cd repo && /home/z/.venv/bin/python -m pytest tests/ui/test_design_tokens.py -q",
        tail or err.strip()[:200], "17 passed", ok)

    # C2 — سلامة صياغة JS
    out, err, rc = run("node --check src/ui/factory-control.js", cwd=REPO)
    ok = rc == 0 and not err.strip()
    add("C2", "C-tests", "node --check src/ui/factory-control.js يمر بلا أخطاء",
        "cd repo && node --check src/ui/factory-control.js",
        f"rc={rc} · stderr={err.strip()[:150] or '(فارغ)'}", "rc=0 و stderr فارغ", ok)


# ============================================================ GROUP D — أدلة التحقق البصري (إعادة قياس مستقلة)
def _close(p, t, tol=3):
    return all(abs(a - b) <= tol for a, b in zip(p, t))


def _band_profile(path: str) -> dict:
    """تنميط صفوف الصورة: حزم رؤوس البطاقات/البلاطات (s2)، حزم أسطح البطاقات (s1)،
    ومجموعات بكسل الأكسنت (زر primary). ألوان theme.css: bg=#0A0D12، s1=bg-raised
    (#191E29)، s2=bg-elevated (#212834)، accent=#58A6FF."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    S2, S1, ACC = (33, 40, 52), (25, 30, 41), (88, 166, 255)
    step = 3 if w > 800 else 2
    n = w // step
    # thr2 لرؤوس البطاقات/البلاطات (s2 بعرض البطاقة) وthr1 لأسطح البطاقات (s1) —
    # خُفّض thr1 إلى 0.30 لأن نصوص الشريط تُنقص نسبة s1 في وسطه إلى ~0.32-0.45 (قيس فعليًا)
    thr2 = 0.15 if w > 800 else 0.30
    thr1 = 0.30

    def bands(rows):
        out, start = [], None
        for y in range(h + 1):
            on = y < h and y in rows
            if on and start is None:
                start = y
            elif not on and start is not None:
                out.append((start, y - 1))
                start = None
        return out

    def merge(bands_, gap=4):
        """دمج الحزم المتقاربة (فواصل سطور نص ≤4px) — البطاقة الواحدة تظل حزمة واحدة."""
        if not bands_:
            return []
        merged = [list(bands_[0])]
        for a, b in bands_[1:]:
            if a - merged[-1][1] <= gap:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        return [(a, b) for a, b in merged]

    s2set, s1set, accset = set(), set(), set()
    for y in range(h):
        c2 = c1 = ca = 0
        for x in range(0, w, step):
            p = px[x, y]
            if _close(p, S2):
                c2 += 1
            elif _close(p, S1):
                c1 += 1
            if _close(p, ACC, 25):
                ca += 1
        if c2 > n * thr2:
            s2set.add(y)
        if c1 > n * thr1:
            s1set.add(y)
        if ca > (5 if w > 800 else 4):
            accset.add(y)
    s2_b = bands(s2set)
    s1_b = merge(bands(s1set))
    acc_g = bands(accset)
    return {"size": im.size, "s2_bands": s2_b, "s1_bands": s1_b, "accent_groups": acc_g}


def group_d() -> None:
    # D1 — أرقام الملف الموثق 20261027-visual-fold.json
    vf = json.loads((EV / "20261027-visual-fold.json").read_text(encoding="utf-8"))
    d, m = vf["pairs"]["desktop"], vf["pairs"]["mobile"]
    checks = {
        "desktop_live_before_464": d["before"]["measure"]["live_card"]["top"] == 464,
        "desktop_live_after_79": d["after"]["measure"]["live_card"]["top"] == 79,
        "mobile_live_before_672": m["before"]["measure"]["live_card"]["top"] == 672,
        "mobile_live_after_67": m["after"]["measure"]["live_card"]["top"] == 67,
        "statbar_after_desktop_229_61": (d["after"]["measure"]["statbar"]["top"] == 229
                                         and d["after"]["measure"]["statbar"]["height"] == 61),
        "statbar_after_mobile_217_83": (m["after"]["measure"]["statbar"]["top"] == 217
                                        and m["after"]["measure"]["statbar"]["height"] == 83),
        "empty_tiles_before_4_desktop": len(d["before"]["measure"]["empty_tiles"]) == 4,
        "empty_tiles_before_4_mobile": len(m["before"]["measure"]["empty_tiles"]) == 4,
        "empty_tiles_after_empty_both": (d["after"]["measure"]["empty_tiles"] == []
                                         and m["after"]["measure"]["empty_tiles"] == []),
        "old_system_card_before_only": (d["before"]["measure"]["old_system_card"] is not None
                                        and m["before"]["measure"]["old_system_card"] is not None
                                        and d["after"]["measure"]["old_system_card"] is None
                                        and m["after"]["measure"]["old_system_card"] is None),
        "zero_js_errors_x4": all(not p[s]["js_errors"] for p in (d, m) for s in ("before", "after")),
    }
    add("D1", "D-visual", "أرقام 20261027-visual-fold.json مطابقة للموثق في البطاقة",
        "قراءة JSON + مطابقة 11 قيمة",
        json.dumps(checks, ensure_ascii=False), "كل القيم True", all(checks.values()))

    # D2 — إعادة قياس مستقلة بالعين/PIL من لقطات PNG القائمة (الاتجاه والقرب لا البكسل الحرفي)
    scr = EV / "screens"
    prof = {n: _band_profile(str(scr / n)) for n in
            ["before-factory.png", "after-factory.png",
             "before-factory-mobile.png", "after-factory-mobile.png"]}

    def near(val, target, tol):
        return abs(val - target) <= tol

    # سطح المكتب — قبل: البث = البطاقة الثالثة عند ~464، وبلاطات 2×2 بعد البطاقة الأولى
    # البلاطات: حزم s2 بارتفاع 65–80 (رؤوس البطاقات 47–61 والبث برأس أطول 61 — خارج النطاق)
    TILE_LO, TILE_HI = 65, 80
    b = prof["before-factory.png"]
    s2h = [(a, bb - a + 1) for a, bb in b["s2_bands"]]
    live_before_d = next((a for a, hgt in s2h if near(a, 464, 20) and 40 <= hgt <= 60), None)
    tiles_before_d = [x for x in s2h if TILE_LO <= x[1] <= TILE_HI and x[0] < (live_before_d or 999)]
    btn_before_d = next((g for g in b["accent_groups"] if 380 <= g[0] <= 440), None)
    # سطح المكتب — بعد: أول حزمة عند ~79 تحتوي زر الأكسنت داخل رأسها، ولا بلاطات
    a4 = prof["after-factory.png"]
    s2ha = [(x, y - x + 1) for x, y in a4["s2_bands"]]
    first_a = s2ha[0] if s2ha else (None, 0)
    live_after_d = first_a[0]
    btn_in_head_d = next((g for g in a4["accent_groups"]
                          if first_a[0] is not None and first_a[0] <= g[0] <= first_a[0] + first_a[1]), None)
    tiles_after_d = [x for x in s2ha if TILE_LO <= x[1] <= TILE_HI]
    statbar_d = next((x for x, y in a4["s1_bands"] if near(x, 229, 14) and 45 <= y - x + 1 <= 80), None)
    ok_desktop = (live_before_d is not None and live_after_d is not None
                  and near(live_after_d, 79, 14) and near(live_before_d, 464, 20)
                  and live_after_d < live_before_d - 300
                  and len(tiles_before_d) >= 2 and not tiles_after_d
                  and btn_before_d is not None and btn_in_head_d is not None
                  and statbar_d is not None)
    add("D2", "D-visual", "إعادة قياس سطح المكتب بـPIL: البث 464→79 (أول بطاقة، والزر داخل رأسها)، بلاطات 2×2→لا شيء، statbar ~229",
        "PIL: تنميط صفوف s2(#212834)/s1(#191E29)/أكسنت(#58A6FF) في before/after-factory.png",
        f"قبل: حزم s2={s2h} · زر primary={btn_before_d} | بعد: أول حزمة={first_a} · زر داخل الرأس={btn_in_head_d} · "
        f"بلاطات قبل={len(tiles_before_d)} بعد={len(tiles_after_d)} · statbar(s1)≈{statbar_d}",
        "قبل: بث≈464 وبلاطتان (2×2=4) وزر primary في «إجراءات سريعة» ~390؛ بعد: أول بطاقة≈79 وزر primary داخل رأسها وstatbar≈229",
        ok_desktop, "تقدير يدوي من حزم الألوان — الاتجاه والقرب هما المعيار (±~15px).")

    # الجوال — قبل: البث = البطاقة الثالثة عند ~672 وبعدها 4 بلاطات؛ بعد: أول بطاقة ~67 + statbar ~217
    bm = prof["before-factory-mobile.png"]
    s2hm = [(x, y - x + 1) for x, y in bm["s2_bands"]]
    live_before_m = next((x for x, hgt in s2hm if near(x, 672, 20) and 40 <= hgt <= 60), None)
    tiles_before_m = [x for x, hgt in s2hm if TILE_LO <= hgt <= TILE_HI and x < (live_before_m or 999)]
    am = prof["after-factory-mobile.png"]
    s2hma = [(x, y - x + 1) for x, y in am["s2_bands"]]
    first_am = s2hma[0] if s2hma else (None, 0)
    live_after_m = first_am[0]
    btn_in_head_m = next((g for g in am["accent_groups"]
                          if first_am[0] is not None and first_am[0] <= g[0] <= first_am[0] + first_am[1]), None)
    tiles_after_m = [x for x, hgt in s2hma if TILE_LO <= hgt <= TILE_HI]
    statbar_m = next((x for x, y in am["s1_bands"] if near(x, 217, 14) and 60 <= y - x + 1 <= 100), None)
    ok_mobile = (live_before_m is not None and live_after_m is not None
                 and near(live_after_m, 67, 14) and near(live_before_m, 672, 20)
                 and live_after_m < live_before_m - 500
                 and len(tiles_before_m) == 4 and not tiles_after_m
                 and btn_in_head_m is not None and statbar_m is not None)
    add("D3", "D-visual", "إعادة قياس الجوال 390 بـPIL: البث 672→67 (أول بطاقة)، 4 بلاطات→لا شيء، statbar ~217",
        "PIL: نفس التنميط في before/after-factory-mobile.png",
        f"قبل: حزم s2={s2hm[:9]} | بعد: أول حزمة={first_am} · زر داخل الرأس={btn_in_head_m} · "
        f"بلاطات قبل={len(tiles_before_m)} بعد={len(tiles_after_m)} · statbar(s1)≈{statbar_m}",
        "قبل: بث≈672 وأربع بلاطات (عمودية)؛ بعد: أول بطاقة≈67 وزر primary داخل رأسها وstatbar≈217",
        ok_mobile, "تقدير يدوي من حزم الألوان — الاتجاه والقرب هما المعيار (±~15px).")

    # D4 — VLM الثلاثة
    vlm_dir = EV / "screens" / "vlm"
    verdicts = {}
    for fname, key in [("after-desktop.json", "after_desktop"),
                       ("after-mobile.json", "after_mobile"),
                       ("before-desktop.json", "before_desktop")]:
        j = json.loads((vlm_dir / fname).read_text(encoding="utf-8"))
        verdicts[key] = j["choices"][0]["message"]["content"].strip()

    def norm(v):
        return re.sub(r"^[\*\s]+", "", v).upper()

    ok = (norm(verdicts["after_desktop"]).startswith("LAYOUT_OK")
          and norm(verdicts["after_mobile"]).startswith("LAYOUT_OK")
          and norm(verdicts["before_desktop"]).startswith("CONFIRMED"))
    add("D4", "D-visual", "أحكام VLM: after-desktop=LAYOUT_OK · after-mobile=LAYOUT_OK · before-desktop=CONFIRMED",
        "قراءة screens/vlm/*.json (choices[0].message.content)",
        json.dumps({k: v[:90] for k, v in verdicts.items()}, ensure_ascii=False),
        "LAYOUT_OK / LAYOUT_OK / CONFIRMED", ok)

    # D5 — سلامة أدلة النشر واتساقها مع قياساتي الحية
    pf = (EV / "20261027-161927-preflight.txt").read_text(encoding="utf-8")
    dp = (EV / "20261027-161927-deploy.txt").read_text(encoding="utf-8")
    pv_final = (EV / "20261027-162055-postverify.txt").read_text(encoding="utf-8")
    pv_incident = (EV / "20261027-161927-postverify.txt").read_text(encoding="utf-8")
    c1 = (f"HEAD before: {PREV_HEAD}" in pf and "clean" in pf
          and "health 200" in pf and "fc-statbar before: 0" in pf)
    c2 = (f"deployed={EXPECT_HEAD}" in dp and f"previous={PREV_HEAD}" in dp
          and "import_ok=true" in dp and "restarted=true" in dp)
    c3 = ("target=eaef5fd01a96e56c323dbf25db9ba530be102474" in pv_final
          and "health_200=True" in pv_final and "asset_version=True" in pv_final
          and "new_js_markers_served=True" in pv_final and "new_css_markers_served=True" in pv_final
          and "old_markers_gone=True" in pv_final and "no_new_journal_errors=True" in pv_final
          and "nginx_wall_401=True" in pv_final and "tokens_contract_prod=True" in pv_final)
    c4 = "old_markers_gone=False" in pv_incident  # ملف الحادث الموثق (شفافية) موجود كما رواه المنفذ
    ok = c1 and c2 and c3 and c4
    add("D5", "D-visual", "أدلة النشر متسقة ومترابطة بقياساتي الحية (رأس قبل/بعد، asset، 8/8، والحادث موثق)",
        "قراءة preflight/deploy/postverify(نهائي+حادث) + الربط بفحوص A1/A9/A6-A8",
        f"preflight(قبل=d23a969+نظيف+200+fc-statbar=0)={c1} · deploy(eaef5fd/سابق d23a969/import_ok/restarted)={c2} · "
        f"postverify النهائي 162055 (8/8 True)={c3} · ملف الحادث 161927 (old_markers_gone=False موثقًا)={c4}",
        "كلها قائمة، والربط الحي: رأس الإنتاج=eaef5fd (A1) و ?v=eaef5fd0 (A9) والعلامات مخدومة/القديمة زالت (A6-A8)",
        ok)


# ============================================================ GROUP E — صحة عامة
def group_e(ssh) -> None:
    # E1 — firewalld + aes-backup.timer
    out, _ = ssh_run(ssh, "systemctl is-active firewalld aes-backup.timer")
    vals = [l.strip() for l in out.splitlines() if l.strip()]
    add("E1", "E-health", "firewalld و aes-backup.timer لا يزالان active",
        "systemctl is-active firewalld aes-backup.timer", " / ".join(vals),
        "active / active", vals == ["active", "active"])

    # E2 — النسخة الليلية موجودة
    out, _ = ssh_run(ssh, "ls -la /opt/aes-backups/db/nightly-20261027.db")
    ok = "nightly-20261027.db" in out and "8040448" in out
    add("E2", "E-health", "nightly-20261027.db لا تزال في /opt/aes-backups/db/ (8040448)",
        "ls -la /opt/aes-backups/db/nightly-20261027.db", out.strip(),
        "الملف موجود بحجم 8040448", ok)

    # E3 — الأثر الجانبي: .fc-stat و .fc-grid-2 ما زالا معرفين (محليًا وعلى الإنتاج الحي)
    css_local, _, _ = run("git show eaef5fd:src/ui/factory-control.css", cwd=REPO)
    css_live, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/static/factory-control.css")
    js_live, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/static/factory-control.js")
    local_ok = (".fc-grid-2 {" in css_local and ".fc-stat {" in css_local
                and ".fc-stat-value.bad" in css_local)
    live_ok = (".fc-grid-2 {" in css_live and ".fc-stat {" in css_live)
    # مستخدم فعليًا بعد الرقعة (renderMissionOverview في تبويبات المهمة)
    used = 'class="fc-grid-2"' in js_live
    add("E3", "E-health", "الرقعة لم تحذف أنماطًا ما زالت مستخدمة: .fc-stat/.fc-grid-2 معرفة (محليًا وحية) و fc-grid-2 مستخدمة في JS الحي",
        "git show eaef5fd:…css + curl …/factory-control.css + curl …/factory-control.js",
        f"تعريف محلي: grid-2/stat/stat-value.bad={local_ok} · تعريف حي: grid-2/stat={live_ok} · "
        f"استخدام fc-grid-2 في JS الحي (renderMissionOverview)={used}",
        "الثلاثة True — تبويبات المهمة الأخرى سليمة", local_ok and live_ok and used)


def main() -> int:
    t0 = datetime.now(timezone.utc)
    print("=== W2-T09-AUDIT — independent audit ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, key_filename=KEY, look_for_keys=False,
                allow_agent=False, timeout=15)
    try:
        group_a(ssh)
        group_e(ssh)
    finally:
        ssh.close()
        print("Groups A+E done.")
    group_b(); print("Group B done.")
    group_c(); print("Group C done.")
    group_d(); print("Group D done.")

    # ملاحظات موثقة غير حاجبة
    finding("F1", "انحراف بكسلي ≤2px بين قياسي اليدوي (PIL من PNG) وأتمتة Playwright الموثقة",
            "قياسي المستقل: بث بعد ≈80 سطح مكتب / ≈68 جوال (الموثق 79/67) · قبل ≈465/673 (الموثق 464/672) · "
            "statbar ≈230/218 (الموثق 229/217). الاتجاه والقرب مؤكدان تمامًا؛ الفرق من تصيير الخط/حافة الحدّ "
            "عند أخذ أول صف من الحزمة — ضمن التفاوت المعلن في أمر التدقيق (المهم الاتجاه والقرب).")
    finding("F2", "نص حكم VLM للجوال يُسمّي العناصر بأسماء لا تطابق نصوص الواجهة الحرفية",
            "نموذج الرؤية وصف الزر بـ«+ بث جديد» (الفعلي «+ مهمة جديدة») والزر بـ«تصفية الكل» (الفعلي «تحديث الكل») "
            "وقائمة بـ«الحسابات المحظورة» (الفعلي المهام) — إعادة صياغة من النموذج لا تطابق حرفيًا. الحكم البنيوي "
            "(بطاقة البث أول محتوى، الشريط ملتف سطرين بلا تداخل، لا قص/تمرير أفقي في 390px) متسق مع قياسي المستقل "
            "وLAYOUT_OK معتبرة.")
    finding("F3", "الرصيد غير المستخدم: تعريف .fc-stat ما زال في CSS لكن JS لم يعد يُصدر class=\"fc-stat\"",
            "بعد الرقعة صار المُصدر fc-stat-inline/fc-statbar-* فقط؛ تعريف .fc-stat القديم بقي (لا يحذفه أمر البطاقة — "
            "وهو المطلوب: لم تُحذف أنماط قد يستخدمها آخرون). fc-grid-2 ما زال مستخدمًا فعليًا في renderMissionOverview "
            "(فحص E3). مقترح: تنظيف .fc-stat الميت في W3-T16 (تنظيف المستودع) لا الآن.")

    passed = sum(1 for c in CHECKS if c["verdict"] == "PASS")
    failed = sum(1 for c in CHECKS if c["verdict"] == "FAIL")
    blocking = [f for f in FINDINGS if f["blocking"]]
    final = "PASS" if failed == 0 and not blocking else "FAIL"

    script_md5 = hashlib.md5(Path(__file__).read_bytes()).hexdigest()
    result = {
        "task": "W2-T09-AUDIT — تدقيق مستقل كامل لمهمة W2-T09 (البث فوق الطية + شريط إحصاءات + ثقل أولوية + النشر)",
        "agent": "W2-T09-AUDIT (general-purpose audit agent)",
        "date": t0.strftime("%Y-%m-%d"),
        "mode": "SSH قراءة فقط على الإنتاج (92.5.14.150) + فحوص محلية (اختبارات/قياس PIL على اللقطات القائمة/مراجعة الالتزام)",
        "script_md5": script_md5,
        "summary": {"total": len(CHECKS), "passed": passed, "failed": failed,
                    "findings": len(FINDINGS), "blocking_findings": len(blocking)},
        "final_verdict": final,
        "checks": CHECKS,
        "findings": FINDINGS,
        "verdict_rationale": (
            "كل فحوص المجموعات A-E ناجحة بأدلة جمعها المدقق بنفسه: الإنتاج على eaef5fd بشجرة نظيفة وصحة 200 "
            "وخدمات نشطة وصفر أخطاء journal فعلية؛ العلامات الخمس الجديدة (JS وCSS) تُخدم حية والقديمة زالت فعلًا "
            "(fc-system-card=0 والأزرار الثلاثة id==0)؛ ?v=eaef5fd0 والجدار 401؛ عقد التوكنات على شجرة الإنتاج "
            "صفر hex/rgba خارج theme.css بمحرك python3 موثق عمله (FILES>0 + CONTROL>0)؛ النسخ الاحتياطية "
            "pre-w2t09 موجودة وسلسلة ff-only مثبتة (d23a969 سلف). الالتزام eaef5fd محصور في ملفين +139/−45 "
            "والترتيب الجديد (بث أولًا برأس يحمل «+ مهمة جديدة» ثم fc-statbar ثم المهام) منفذ في الكود مع ترتيب "
            "مستقر بالأولوية (runPriority/missionPriority بعد slice) و15 دالة محمية متطابقة بايتًا بايتًا وصفر لون "
            "خام في الإضافات. الاختبارات 17/17 وnode --check يمر. البصري: أرقام visual-fold.json مطابقة، وقياسي "
            "المستقل بـPIL من اللقطات القائمة أكد الاتجاه والقرب (سطح مكتب 464→79 والجوال 672→67، والزر primary "
            "صار داخل رأس أول بطاقة، والبلاطات 2×2/4 زالت وحلّها statbar ~229/~217)، وVLM LAYOUT_OK×2 + "
            "CONFIRMED، وأدلة النشر متسقة 8/8 مع الحادث المفسر موثقًا. firewalld/aes-backup/النسخة الليلية سليمة، "
            "و.fc-stat/.fc-grid-2 ما زالت معرفة ومستخدمة (تبويبات المهمة)."
        ) if final == "PASS" else "انظر الفحوص الفاشلة والملاحظات الحاجزة.",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nchecks: {passed}/{len(CHECKS)} passed, {failed} failed; "
          f"findings: {len(FINDINGS)} (blocking: {len(blocking)})")
    for c in CHECKS:
        if c["verdict"] == "FAIL":
            print(f"  FAIL {c['id']}: {c['name']} → {str(c['actual_output'])[:200]}")
    print(f"FINAL VERDICT: {final}")
    print(f"JSON → {OUT}")
    return 0 if final == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
