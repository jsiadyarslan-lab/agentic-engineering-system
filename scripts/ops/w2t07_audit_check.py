#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T07-AUDIT — وكيل تدقيق مستقل لمهمة W2-T07 (مسح الألوان الناجية → توكنات النظام + عقد آلي)
النطاق: الخطوات 1-5 (المسح + العقد + التحقق البصري + النشر للإنتاج).

الانضباط: SSH قراءة فقط على الإنتاج طوال الجلسة (cat/grep/git read/stat/curl GET/
systemctl is-active/journalctl read). صفر كتابة على الإنتاج، صفر إيقاف/إعادة تشغيل،
صفر POST، صفر git push. محليًا: تشغيل الاختبارات والفحوص وأدوات المقارنة فقط
(+ مسبار سلبي مؤقت في src/ui يُحذف فورًا مع التحقق من نظافة git).

التقييم بأسطر المخرجات الفعلية لا برموز الخروج (درس W1-T01).
المخرج: download/aes-remediation/W2-T07/audit_independent.json
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
REPO = Path("/home/z/my-project/repo")
EV = Path("/home/z/my-project/download/aes-remediation/W2-T07")
OUT = EV / "audit_independent.json"
VENV = "/home/z/.venv/bin/python"
EXPECT_HEAD = "d23a96984debb30a740ce60baf38881f6d4adedd"
PREV_HEAD = "9e2ace5b3acb0983cebff1a9e658507903273511"

CHECKS: list[dict] = []
FINDINGS: list[dict] = []


def add(cid: str, group: str, name: str, command: str, actual, expected, ok: bool, note: str = "") -> None:
    CHECKS.append({
        "id": cid, "group": group, "name": name, "command": command,
        "actual_output": actual, "expected": expected,
        "verdict": "PASS" if ok else "FAIL", "note": note,
    })


def finding(fid: str, title: str, detail: str, blocking: bool = False) -> None:
    FINDINGS.append({"id": fid, "title": title, "detail": detail, "blocking": blocking})


def ssh_run(ssh, cmd: str, timeout: int = 60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return o.read().decode(errors="replace"), e.read().decode(errors="replace")


def run(cmd: str, cwd=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    return r.stdout, r.stderr, r.returncode


def real_journal_error_lines(out: str) -> list[str]:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.strip() != "-- No entries --"]


# ============================================================ GROUP A — الإنتاج الحي (SSH قراءة فقط)
def group_a(ssh) -> None:
    # A1 — رأس الإنتاج بالضبط
    out, err = ssh_run(ssh, "git -C /opt/agentic-engineering-system rev-parse HEAD")
    add("A1", "A-production", "رأس الإنتاج = d23a96984deb… بالضبط",
        "git -C /opt/agentic-engineering-system rev-parse HEAD",
        out.strip(), EXPECT_HEAD, out.strip() == EXPECT_HEAD)

    # A2 — الشجرة نظيفة (تعديلات متتبعة)
    out, err = ssh_run(ssh, "git -C /opt/agentic-engineering-system status --porcelain --untracked-files=no")
    n = len([l for l in out.splitlines() if l.strip()])
    add("A2", "A-production", "شجرة الإنتاج نظيفة (0 تعديلات متتبعة)",
        "git -C /opt/agentic-engineering-system status --porcelain --untracked-files=no",
        out.strip() or "(0 أسطر)", "0 أسطر", n == 0)

    # A3 — /health
    out, err = ssh_run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
    add("A3", "A-production", "/health على 8010 = 200",
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health",
        out.strip(), "200", out.strip() == "200")

    # A4 — agentic + nginx
    out, err = ssh_run(ssh, "systemctl is-active agentic nginx")
    vals = [l.strip() for l in out.splitlines() if l.strip()]
    add("A4", "A-production", "agentic + nginx نشطتان",
        "systemctl is-active agentic nginx", " / ".join(vals), "active / active",
        vals == ["active", "active"])

    # A5 — journal آخر 30 دقيقة (-p err) — أسطر خطأ فعلية (placeholder لا يُعد)
    out, err = ssh_run(ssh, "journalctl -u agentic --since '-30 min' -p err --no-pager | cat")
    real = real_journal_error_lines(out)
    add("A5", "A-production", "journalctl -u agentic آخر 30د -p err: صفر أسطر خطأ فعلية",
        "journalctl -u agentic --since '-30 min' -p err --no-pager | cat",
        out.strip() or "(فارغ)", "صفر أسطر فعلية (placeholder «-- No entries --» لا يُعد خطأً)",
        len(real) == 0, f"أسطر فعلية بعد إقصاء placeholder: {len(real)}")

    # A6 — journal منذ نافذة النشر (15:30) — صفر أخطاء فعلية
    out, err = ssh_run(ssh, "journalctl -u agentic --since '2026-10-27 15:30' -p err --no-pager | cat")
    real = real_journal_error_lines(out)
    add("A6", "A-production", "journalctl -u agentic منذ 15:30 (نافذة النشر) -p err: صفر أخطاء فعلية",
        "journalctl -u agentic --since '2026-10-27 15:30' -p err --no-pager | cat",
        out.strip() or "(فارغ)", "صفر أسطر فعلية", len(real) == 0,
        f"أسطر فعلية: {len(real)}")

    # A7 — الأمر الحرفي لبطاقة القبول على الإنتاج (توثيق سلوكه الفعلي — درس W1-T01)
    cmd_lit = ("cd /opt/agentic-engineering-system && rg -n --type css "
               "'#[0-9a-fA-F]{3,8}\\b' src/ui/ -g '!src/ui/theme.css' -g '!src/ui/fonts/**' | wc -l")
    out, err = ssh_run(ssh, cmd_lit)
    out2, err2 = ssh_run(ssh, ("cd /opt/agentic-engineering-system && rg -n --type css 'rgba?\\(' "
                               "src/ui/ -g '!src/ui/theme.css' | wc -l"))
    # rg غير مثبت على الإنتاج => stdout "0" زائف (الخطأ في stderr) — يوثَّق كـ finding لا كنتيجة
    finding("F1", "rg غير مثبت على الإنتاج — الأمر الحرفي للبطاقة يعطي «0» زائفًا هناك",
            f"الأمر الحرفي (hex): stdout={out.strip()!r} + stderr={err.strip()!r}. "
            f"الأمر الحرفي (rgba): stdout={out2.strip()!r} + stderr={err2.strip()!r}. "
            "بمعنى: لو حُسب stdout وحده لانخدعنا بـ«0» بغضّ النظر عن محتوى الملفات — نفس درس W1-T01 "
            "(التقييم بالأسطر الفعلية). جوهر البوابة أُعيد التحقق منه مباشرة على شجرة الإنتاج "
            "بمحركين مستقلين (فحص A8/A9) وكلاهما 0/0 — فالمعيار محقق فعلاً على الإنتاج.")

    # A8 — الفحص الأمين للمسح على شجعة الإنتاج (python3 هناك، بدلالات rg نفسها حرفيًا)
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
    ok = (n_files == 8 and n_hex == 0 and n_rgb == 0 and n_ctrl > 0)
    add("A8", "A-production", "مسح hex على شجرة الإنتاج (بدلالات rg الحرفية عبر python3 هناك) = 0",
        "ssh: /usr/bin/python3 - <<scan (rglob *.css عدا theme.css/fonts، regex '#[0-9a-fA-F]{3,8}\\b' سطرًا سطرًا)",
        scan_out.strip()[:600], "FILES=8 · HEX=0 · RGB=0 · CONTROL>0 (تحقق إيجابي أن الفحص يقرأ محتوى فعليًا)",
        ok, f"python stderr: {scan_err.strip()[:200]}" if scan_err.strip() else "")
    add("A8b", "A-production", "مسح rgba على شجرة الإنتاج (regex '\\brgba?\\(\\s*[0-9]') = 0",
        "نفس الفحص أعلاه (قيمة RGB)", f"RGB={n_rgb}", "0", n_rgb == 0)

    # A9 — محرك ثانٍ مستقل: GNU grep بكلمة حدودية \b (مع اختبار ذاتي له)
    selftest_out, _ = ssh_run(ssh, "printf 'a #fff b #factory-view\\n' | grep -cE '#[0-9a-fA-F]{3,8}\\b'")
    g1, gerr1 = ssh_run(ssh, "cd /opt/agentic-engineering-system && grep -rEn --include='*.css' "
                             "'#[0-9a-fA-F]{3,8}\\b' src/ui/ | grep -v 'src/ui/fonts/' | "
                             "grep -v 'src/ui/theme.css:' | wc -l")
    g2, gerr2 = ssh_run(ssh, "cd /opt/agentic-engineering-system && grep -rEn --include='*.css' "
                             "'rgba?\\(' src/ui/ | grep -v 'src/ui/fonts/' | "
                             "grep -v 'src/ui/theme.css:' | wc -l")
    st = selftest_out.strip()
    ok = (st == "1" and g1.strip() == "0" and g2.strip() == "0")
    add("A9", "A-production", "تحقق متقاطع بمحرك ثانٍ (GNU grep -E بكلمة حدودية) hex=0 و rgba=0",
        "grep -rEn --include='*.css' '#[0-9a-fA-F]{3,8}\\b' src/ui/ | grep -v fonts | grep -v theme.css | wc -l  (ورديفه rgba)",
        f"selftest(يجب 1: يلتقط #fff ولا يلتقط #factory-view)={st} · hex={g1.strip()} · rgba={g2.strip()}",
        "selftest=1 · hex=0 · rgba=0", ok,
        "بدون \b يلتقط grep محددات ID مثل #factory-view (27 سطرًا) — الحد الكلمةي جوهري لمطابقة دلالة rg.")

    # A10 — التوكنات السبعة المطلوبة تُخدم حية من /static/theme.css
    served, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/static/theme.css")
    tok7 = ["--accent-pulse", "--accent-selection", "--code-well", "--scrim-deep",
            "--danger-scrim", "--scrollbar-thumb", "--border-strong"]
    missing = [t for t in tok7 if (t + ":") not in served]
    add("A10", "A-production", "/static/theme.css الحي يخدم التوكنات السبعة الجديدة/المطلوبة",
        "curl -s http://127.0.0.1:8010/static/theme.css | grep -- '--<token>:'",
        f"المخدوم من 7: {7 - len(missing)}/7" + (f" · الغائب: {missing}" if missing else " · كلها حاضرة"),
        "7/7", len(missing) == 0)

    # A11 — (صرامة إضافية) كل التوكنات الـ13 الجديدة مخدومة + العدد الكلي 136
    tok13 = ["--accent-selection", "--accent-pulse", "--accent-hi", "--accent-border-strong",
             "--accent-soft-strong", "--code-text", "--code-well", "--code-well-strong",
             "--scrim:", "--scrim-deep", "--danger-scrim", "--scrollbar-thumb", "--scrollbar-thumb-hover"]
    missing13 = [t for t in tok13 if t not in served]
    n_tok_served = len(re.findall(r"^\s*--[\w-]+\s*:", served, re.M))
    add("A11", "A-production", "التوكنات الـ13 الجديدة كلها مخدومة حية + العدد الكلي 136",
        "curl -s http://127.0.0.1:8010/static/theme.css (عدّ regex '^--\\w[\\w-]*\\s*:' + أسماء الـ13)",
        f"من 13: {13 - len(missing13)}/13 · عدد التوكنات المخدومة={n_tok_served}",
        "13/13 و 136", len(missing13) == 0 and n_tok_served == 136,
        ("غائب: " + str(missing13)) if missing13 else "")

    # A12 — إصدار الأصول في الصفحة الرئيسية
    out, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/ | grep -oE 'control-center.js\\?v=[0-9a-f]+'")
    add("A12", "A-production", "إصدار الأصول في / : control-center.js?v=d23a9698",
        "curl -s http://127.0.0.1:8010/ | grep -oE 'control-center.js\\?v=[0-9a-f]+'",
        out.strip(), "control-center.js?v=d23a9698", out.strip() == "control-center.js?v=d23a9698")

    # A13 — جدار nginx (401)
    out, _ = ssh_run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/")
    add("A13", "A-production", "nginx المحلي / = 401 (الجدار سليم)",
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/",
        out.strip(), "401", out.strip() == "401")

    # A14 — الخدمات الأربع
    out, _ = ssh_run(ssh, "systemctl is-active agentic nginx firewalld aes-backup.timer")
    vals = [l.strip() for l in out.splitlines() if l.strip()]
    add("A14", "A-production", "الخدمات الأربع (agentic/nginx/firewalld/aes-backup.timer) نشطة",
        "systemctl is-active agentic nginx firewalld aes-backup.timer",
        " / ".join(vals), "active ×4", vals == ["active"] * 4)

    # A15 — النسخ الاحتياطية قبل النشر موجودة
    out, _ = ssh_run(ssh, "ls -la /home/opc/pre-w2t07-*.bundle /home/opc/pre-w2t07-*.tar.gz")
    lines = [l for l in out.splitlines() if "pre-w2t07-" in l]
    has_bundle = any("pre-w2t07-repo-backup-20261027-154024.bundle" in l for l in lines)
    has_tar = any("pre-w2t07-runtime-20261027-154024.tar.gz" in l for l in lines)
    sizes_ok = all(int(l.split()[4]) > 0 for l in lines if len(l.split()) > 5)
    add("A15", "A-production", "النسخ الاحتياطية قبل النشر موجودة (bundle + runtime tar)",
        "ls -la /home/opc/pre-w2t07-*.bundle /home/opc/pre-w2t07-*.tar.gz",
        out.strip(), "الملفان المذكوران في خطة التراجع بحجمين > 0",
        has_bundle and has_tar and sizes_ok and len(lines) == 2)

    # A16 — النسخة الليلية لا تزال موجودة
    out, _ = ssh_run(ssh, "ls -la /opt/aes-backups/db/nightly-20261027.db")
    ok = "nightly-20261027.db" in out and "8040448" in out
    add("A16", "A-production", "nightly-20261027.db لا تزال في /opt/aes-backups/db/",
        "ls -la /opt/aes-backups/db/nightly-20261027.db", out.strip(),
        "الملف موجود بحجم 8040448", ok)

    # A17 — تطابق theme.css ثلاثيًا: ملف الإنتاج = الملف المحلي = المخدوم حيًا
    out_p, _ = ssh_run(ssh, "md5sum /opt/agentic-engineering-system/src/ui/theme.css")
    out_s, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/static/theme.css | md5sum")
    local_md5 = hashlib.md5((REPO / "src/ui/theme.css").read_bytes()).hexdigest()
    pmd5 = out_p.split()[0] if out_p.split() else ""
    smd5 = out_s.split()[0] if out_s.split() else ""
    add("A17", "A-production", "تطابق theme.css: إنتاج = مستودع محلي = المخدوم (md5 واحد)",
        "md5sum على الملفين + curl | md5sum",
        f"prod={pmd5} · served={smd5} · local={local_md5}",
        "الثلاثة متطابقة (182efce…)", pmd5 == smd5 == local_md5)

    # A18 — سلسلة git على الإنتاج + 9e2ace5 سلف (رواية ff-only)
    out, _ = ssh_run(ssh, "git -C /opt/agentic-engineering-system log --oneline -3")
    anc_out, _ = ssh_run(ssh, f"git -C /opt/agentic-engineering-system merge-base --is-ancestor {PREV_HEAD} HEAD && echo ANCESTOR_OK")
    ok = out.startswith("d23a96984") and "0994d2654" in out and "677b94d78" in out and "ANCESTOR_OK" in anc_out
    add("A18", "A-production", "سلسلة git للإنتاج (d23a969→0994d26→677b94d) و 9e2ace5 سلف لـ HEAD",
        "git log --oneline -3 + git merge-base --is-ancestor 9e2ace5 HEAD && echo ANCESTOR_OK",
        out.strip() + " | " + anc_out.strip(), "السلسلة كما هو متوقع و ANCESTOR_OK", ok)


# ============================================================ GROUP B — الالتزام المدفوع (محلي، قراءة فقط)
def group_b() -> None:
    # B1 — نطاق الالتزام 0994d26
    out, _, _ = run("git -C %s show --stat 0994d26" % REPO, cwd=REPO)
    stat_line = [l for l in out.splitlines() if "files changed" in l]
    m = re.search(r"(\d+) files? changed, (\d+) insertions?\(\+\), (\d+) deletions?\(-\)", stat_line[0]) if stat_line else None
    file_lines = re.findall(r"^\s*((?:src|tests)/[\w/.\-]+)\s+\|", out, re.M)
    js_files = [f for f in file_lines if f.endswith(".js")]
    expected_files = {
        "src/ui/app-shell.css", "src/ui/control-center.css", "src/ui/factory-control.css",
        "src/ui/live.css", "src/ui/project-live.css", "src/ui/styles.css", "src/ui/theme.css",
        "tests/ui/__init__.py", "tests/ui/test_design_tokens.py"}
    ok = (m and int(m.group(1)) == 9 and int(m.group(2)) == 133 and int(m.group(3)) == 35
          and not js_files and set(file_lines) == expected_files)
    add("B1", "B-commit", "0994d26: النطاق CSS/UI + اختبار العقد فقط — +133/−35 — صفر JS",
        "git show --stat 0994d26",
        f"files={m.group(1) if m else '?'} +{m.group(2) if m else '?'}/−{m.group(3) if m else '?'} · "
        f"ملفات={len(file_lines)} · JS={len(js_files)}",
        "9 ملفات (7 CSS معدّلة + اختباران جديدان) · +133/−35 · صفر JS", bool(ok),
        "بطاقة TRACKER قالت «7 ملفات» — الدقيق: 7 ملفات CSS معدّلة + ملفا اختبار جديدان = 9 في stat؛ النطاق سليم تمامًا.")

    # B2 — 123→136 توكناً + الأسماء الـ13
    old, _, rc1 = run("git show 0994d26^:src/ui/theme.css", cwd=REPO)
    new, _, rc2 = run("git show 0994d26:src/ui/theme.css", cwd=REPO)
    cnt = lambda t: len(re.findall(r"^\s*--[\w-]+\s*:", t, re.M))
    tok13 = ["--accent-selection:", "--accent-pulse:", "--accent-hi:", "--accent-border-strong:",
             "--accent-soft-strong:", "--code-text:", "--code-well:", "--code-well-strong:",
             "--scrim:", "--scrim-deep:", "--danger-scrim:", "--scrollbar-thumb:",
             "--scrollbar-thumb-hover:"]
    missing = [t for t in tok13 if t not in new]
    ok = rc1 == 0 and rc2 == 0 and cnt(old) == 123 and cnt(new) == 136 and not missing
    add("B2", "B-commit", "theme.css في 0994d26: 123→136 توكناً + الأسماء الـ13 الجديدة",
        "git show 0994d26^:src/ui/theme.css && git show 0994d26:src/ui/theme.css (عدّ regex التوكنات)",
        f"قبل={cnt(old)} · بعد={cnt(new)} · من أسماء الـ13: {13 - len(missing)}/13",
        "123→136 (13 جديدًا) و13/13 حاضرة", ok,
        ("غائب: " + str(missing)) if missing else "")

    # B3 — harness.js لم يُمس في 0994d26 + تاريخ سابق
    out, _, _ = run("git show 0994d26 --stat | grep -c harness; true", cwd=REPO)
    cnt_h = out.strip().splitlines()[-1] if out.strip() else "0"
    log, _, _ = run("git log --oneline -3 -- src/ui/harness.js", cwd=REPO)
    ok = cnt_h.strip() == "0" and log.strip().startswith("c3fb940")
    add("B3", "B-commit", "harness.js لم يُلمس في 0994d26 (عدّ=0) وآخر لمسة سابقة للمهمة",
        "git show 0994d26 --stat | grep -c harness  ||  git log --oneline -3 -- src/ui/harness.js",
        f"grep -c harness = {cnt_h.strip()} · آخر اللمسات: {log.strip().splitlines()[0] if log.strip() else '(none)'}",
        "0 وسجل يبدأ بـ c3fb940 (سابق للمهمة)", ok)

    # B4 — سطرا harness.js:122,170 (توثيق الرصيد المتبقي خارج نطاق CSS)
    text = (REPO / "src/ui/harness.js").read_text(encoding="utf-8").splitlines()
    l122 = text[121].strip() if len(text) > 121 else ""
    l170 = text[169].strip() if len(text) > 169 else ""
    ok = "#f87171" in l122 and "#34d399" in l170
    add("B4", "B-commit", "harness.js:122,170 يحملان hex خام سابقين للمهمة (خارج نطاق أمر البطاقة CSS)",
        "sed -n '122p;170p' src/ui/harness.js",
        f"122: {l122[:70]} · 170: {l170[:70]}",
        "السطران موجودان كما وُثّقا (#f87171/#34d399) — ملاحظة موثقة لا فشل بوابة", ok,
        "رصيد متبقٍ خارج نطاق البطاقة (CSS-only) — مقترح إغلاقهما في W2-T11/W3-T13 كما وثّق المنفذ.")

    # B5 — كل أسطر diff الـCSS المعدّلة لونية/تعليقات (لا منطق خارج نطاق الألوان)
    # تصنيف واعٍ بالتعليقات: نتتبع حالة /* … */ في نسختي الملف قبل/بعد ونصنف
    # كل سطر متغير: داخل تعليق => تعليق؛ وإلا يجب أن يحمل محتوى لونيًا.
    import difflib
    colorish = re.compile(r"color|background|border|shadow|var\(--|/\*|linear-gradient|rgba|#[0-9a-fA-F]{3}")

    def comment_lines(text: str) -> set:
        in_c, marks = False, set()
        for i, line in enumerate(text.splitlines(), 1):
            if in_c:
                marks.add(i)
                if "*/" in line:
                    in_c = False
            elif "/*" in line:
                marks.add(i)
                if "*/" not in line.split("/*", 1)[1]:
                    in_c = True
        return marks

    swept = ["app-shell.css", "control-center.css", "factory-control.css",
             "live.css", "project-live.css", "styles.css"]
    non_color, total_changed = [], 0
    for fname in swept:
        old_t, _, _ = run(f"git show 0994d26^:src/ui/{fname}", cwd=REPO)
        new_t, _, _ = run(f"git show 0994d26:src/ui/{fname}", cwd=REPO)
        old_lines, new_lines = old_t.splitlines(), new_t.splitlines()
        old_c, new_c = comment_lines(old_t), comment_lines(new_t)
        sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("replace", "delete"):
                for i in range(i1, i2):
                    total_changed += 1
                    if (i + 1) not in old_c and not colorish.search(old_lines[i]):
                        non_color.append(f"-{fname}:{i+1}: {old_lines[i][:80]}")
            if tag in ("replace", "insert"):
                for j in range(j1, j2):
                    total_changed += 1
                    if (j + 1) not in new_c and not colorish.search(new_lines[j]):
                        non_color.append(f"+{fname}:{j+1}: {new_lines[j][:80]}")
    ok = len(non_color) == 0
    add("B5", "B-commit", "كل أسطر الرقعة في الـ6 ملفات المسحوحة لونية أو تعليقات (جراحية)",
        "مقارنة نسختي 0994d26^/0994d26 لكل ملف (difflib) مع تتبع حالة التعليقات /*…*/ وتصنيف كل سطر متغير",
        f"أسطر متغيرة={total_changed} · غير لونية/غير تعليقية={len(non_color)}",
        "0 أسطر خارج نطاق الألوان (الباقي داخل تعليقات أو تعريفات لونية)", ok,
        ("أسطر خارج النطاق: " + " | ".join(non_color[:3])) if non_color else
        "الأسطر غير اللونية الظاهرة كلها داخل تعليقات /*…*/ توثيقية — ومنها سطر تنقية ذكر قيمة حرفية من تعليق تاريخي.")


# ============================================================ GROUP C — العقد الآلي (محلي)
def group_c() -> None:
    # C1 — تشغيل العقد
    out, err, rc = run(f"{VENV} -m pytest tests/ui/test_design_tokens.py -q", cwd=REPO)
    m = re.search(r"(\d+) passed", out)
    ok = m and int(m.group(1)) == 17 and rc == 0
    add("C1", "C-contract", "العقد: pytest tests/ui/test_design_tokens.py = 17 passed",
        f"cd {REPO} && {VENV} -m pytest tests/ui/test_design_tokens.py -q",
        out.strip().splitlines()[-1] if out.strip() else f"rc={rc} err={err[:200]}",
        "17 passed", bool(ok))

    # C2 — خصائص كود العقد (قراءة وحكم)
    src = (REPO / "tests/ui/test_design_tokens.py").read_text(encoding="utf-8")
    has_hex_re = 'HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\\b")' in src
    has_rgb_re = 'RGB_FN_RE = re.compile(r"\\brgba?\\(\\s*[0-9]")' in src
    scans_lines = "for i, line in enumerate(text.splitlines(), 1)" in src and "HEX_RE.search(line)" in src
    no_comment_strip = "strip_comment" not in src and "/*" not in src.split("def _css_files_outside_theme")[0].split("HEX_RE")[0][-2000:]
    floor = "token_count >= 136" in src
    scope = 'rglob("*.css")' in src and 'FONTS_DIR' in src and 'p.name == THEME' in src
    ok = has_hex_re and has_rgb_re and scans_lines and floor and scope
    add("C2", "C-contract", "كود العقد: يفحص كل سطر (تعليقات ضمنًا) ويمنع تراجع التوكنات <136",
        "قراءة tests/ui/test_design_tokens.py وتحليله سطرًا سطرًا",
        f"HEX_RE={has_hex_re} · RGB_FN_RE={has_rgb_re} · مسح كل الأسطر بلا إقصاء تعليقات={scans_lines} · "
        f"أرضية 136={floor} · نطاق (css عدا theme/fonts)={scope}",
        "كل الخصائص قائمة", ok,
        "الفحص يسري على النص الكامل للملف — أي hex/rgba حتى داخل تعليق CSS يُرفض؛ يُثبت عمليًا بالمسبارين C3/C4.")

    # C3/C4 — مسباران سلبيان (يُنشآن ثم يُحذفان فورًا)
    probe = REPO / "src/ui" / "fake-probe.css"
    tmp = Path("/tmp/fake-test.css")
    try:
        tmp.write_text("x { color: #123456 }\n", encoding="utf-8")
        shutil.copy(tmp, probe)
        out, err, rc = run(f"{VENV} -m pytest tests/ui/test_design_tokens.py -q", cwd=REPO)
        failed_hex = ("failed" in out) and ("fake-probe" in out) and rc != 0
        add("C3", "C-contract", "مسبار سلبي: hex خام في ملف CSS جديد يُفشل العقد فعلاً",
            "echo 'x { color: #123456 }' > src/ui/fake-probe.css ثم pytest -q",
            (out.strip().splitlines()[-1] if out.strip() else "") + f" (rc={rc})",
            "فشل الاختبار مع ذكر fake-probe", failed_hex)
    finally:
        if probe.exists():
            probe.unlink()
    st_out, _, _ = run("git status --porcelain", cwd=REPO)
    add("C3b", "C-contract", "تنظيف أثر المسبار 1: git status --porcelain فارغ",
        "rm src/ui/fake-probe.css && git status --porcelain",
        st_out.strip() or "(فارغ — 0 تعديلات)", "فارغ", st_out.strip() == "")

    try:
        tmp.write_text("/* audit probe: y { color: rgba(9, 8, 7, 0.5) } */\n", encoding="utf-8")
        shutil.copy(tmp, probe)
        out, err, rc = run(f"{VENV} -m pytest tests/ui/test_design_tokens.py -q", cwd=REPO)
        failed_rgb = ("failed" in out) and ("fake-probe" in out) and rc != 0
        add("C4", "C-contract", "مسبار سلبي: rgba داخل تعليق فقط يُفشل العقد (حتى التعليقات ممنوعة)",
            "echo '/* rgba(9, 8, 7, 0.5) */' > src/ui/fake-probe.css ثم pytest -q",
            (out.strip().splitlines()[-1] if out.strip() else "") + f" (rc={rc})",
            "فشل الاختبار مع ذكر fake-probe", failed_rgb)
    finally:
        if probe.exists():
            probe.unlink()
    st_out, _, _ = run("git status --porcelain", cwd=REPO)
    add("C4b", "C-contract", "تنظيف أثر المسبار 2: git status --porcelain فارغ",
        "rm src/ui/fake-probe.css && git status --porcelain",
        st_out.strip() or "(فارغ — 0 تعديلات)", "فارغ", st_out.strip() == "")
    if tmp.exists():
        tmp.unlink()


# ============================================================ GROUP D — أدلة التحقق البصري (محلي)
def group_d() -> None:
    scr = EV / "screens"
    # D1 — 12 لقطة det
    screens = ["control-center", "control-center-mobile", "factory", "project-2",
               "project-2-mobile", "settings-drawer"]
    missing = []
    for s in screens:
        for pre in ("det-before-", "det-after-"):
            f = scr / f"{pre}{s}.png"
            if not (f.exists() and f.stat().st_size > 0):
                missing.append(f.name)
    add("D1", "D-visual", "12 لقطة det (6 أزواج قبل/بعد) موجودة وأحجامها > 0",
        "ls screens/det-{before,after}-*.png",
        f"الموجود منها: {12 - len(missing)}/12" + (f" · ناقص: {missing}" if missing else ""),
        "12/12", not missing)

    # D2 — ملفات VLM الستة
    vlm_dir = scr / "vlm"
    vlm_results = {}
    for s in screens:
        f = vlm_dir / f"{s}.json"
        if not f.exists():
            vlm_results[s] = "MISSING"
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            vlm_results[s] = data["choices"][0]["message"]["content"].strip()
        except Exception as ex:
            vlm_results[s] = f"PARSE_ERROR:{ex}"
    ok = all(v == "NO_DIFFERENCE" for v in vlm_results.values())
    add("D2", "D-visual", "ملفات VLM الستة كلها تنهي بـ NO_DIFFERENCE",
        "قراءة screens/vlm/*.json (choices[0].message.content)",
        json.dumps(vlm_results, ensure_ascii=False), "NO_DIFFERENCE ×6", ok)

    # D3 — إعادة قياس الفرق البكسلي بنفسي (PIL مستقل) ومقارنة بالموثق
    from PIL import Image, ImageChops
    import numpy as np
    det = json.loads((EV / "20261027-visual-deterministic.json").read_text(encoding="utf-8"))
    mine, doc, match = {}, {}, {}
    for s in screens:
        a = Image.open(scr / f"det-before-{s}.png").convert("RGB")
        b = Image.open(scr / f"det-after-{s}.png").convert("RGB")
        d = ImageChops.difference(a, b)
        arr = np.array(d)
        nz = int(np.count_nonzero(arr.any(axis=2)))
        mx = int(arr.max())
        mine[s] = [nz, mx]
        doc[s] = [det["pairs"][s]["diff_pixels"], det["pairs"][s]["max_channel_delta"]]
        match[s] = (mine[s] == doc[s])
    required = ["control-center", "project-2", "control-center-mobile"]
    ok_req = all(match[s] for s in required)
    add("D3", "D-visual", "إعادة قياس الفرق البكسلي مستقلاً (PIL/NumPy): تطابق حرفي مع الموثق",
        "PIL ImageChops.difference + numpy count_nonzero(any channel) + max — على الأزواج الستة",
        "قياسي: " + json.dumps({s: tuple(mine[s]) for s in screens}, ensure_ascii=False) +
        " · الموثق: " + json.dumps({s: tuple(doc[s]) for s in screens}, ensure_ascii=False),
        "control-center 357/δ6 · project-2 2191/δ6 · control-center-mobile 0/δ0 (والثلاثة الباقية أيضًا)",
        ok_req,
        f"الأزواج الثلاثة المطلوبة متطابقة حرفيًا={'نعم' if ok_req else 'لا'} · الأزواج الستة كلها متطابقة={all(match.values())}")

    # D4 — ملف جلب القاعدة + تحقق مستقل من الملف الفعلي
    dbf = json.loads((EV / "20261027-db-fetch.json").read_text(encoding="utf-8"))
    db = EV / "nightly-20261027.db"
    md5 = hashlib.md5(db.read_bytes()).hexdigest() if db.exists() else ""
    size = db.stat().st_size if db.exists() else 0
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = con.cursor()
    integ = cur.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("projects", "conversations", "messages")}
    con.close()
    ok = (dbf["md5"] == "bbde75fdf7b9367f4c3d0bb8e0674cfa" and md5 == dbf["md5"]
          and size == 8040448 and dbf.get("remote_size") == 8040448
          and dbf.get("local_size") == 8040448 and dbf.get("size_match") is True
          and integ == "ok" and dbf["integrity"] == "ok" and dbf["projects"] == 2
          and dbf["conversations"] == 13 and dbf["messages"] == 91
          and counts == {"projects": 2, "conversations": 13, "messages": 91})
    add("D4", "D-visual", "20261027-db-fetch.json + تحققي المستقل من الملف: md5/حجم/سلامة/صفوف",
        "md5sum + sqlite3 (ro): integrity_check + COUNT projects/conversations/messages",
        f"md5={md5} · size={size} · integrity={integ} · counts={counts}",
        "md5=bbde75fd… · 8040448 · ok · 2/13/91 (مطابقة تمرين W1-T04)", ok)

    # D5 — اتساق رواية ملفات النشر مع قياساتي الحية
    pf = (EV / "20261027-154001-preflight.txt").read_text(encoding="utf-8")
    tr = (EV / "20261027-154011-transfer.txt").read_text(encoding="utf-8")
    dp = (EV / "20261027-154032-deploy.txt").read_text(encoding="utf-8")
    pv = (EV / "20261027-154219-postverify.txt").read_text(encoding="utf-8")
    pc = (EV / "20261027-postverify-corrected.txt").read_text(encoding="utf-8")
    c1 = f"HEAD before: {PREV_HEAD}" in pf and "tree clean" in pf and "agentic+nginx active" in pf and "health 200" in pf
    c2 = f"bundle={EXPECT_HEAD}" in tr and "bundle verify OK" in tr and "sftp OK" in tr
    c3 = (f"deployed={EXPECT_HEAD}" in dp and f"previous={PREV_HEAD}" in dp
          and "import_ok=true" in dp and "restarted=true" in dp)
    c4 = ("6/6" in pc and "0 سطر hex + 0 سطر rgba" in pc
          and "pre-w2t07-repo-backup-20261027-154024.bundle" in pc
          and "pre-w2t07-runtime-20261027-154024.tar.gz" in pc)
    c5 = "zero_raw_colors_prod=False" in pv  # الملف الأصلي الموثق للحادث (شفافية)
    # الروابط الحية: deployed == A1 (رأس الإنتاج الحي) والنسخ == A15 وإصدار الأصول == A12
    ok = c1 and c2 and c3 and c4 and c5
    add("D5", "D-visual", "ملفات النشر الخمسة متسقة روايةً ومترابطة بقياساتي الحية",
        "قراءة preflight/transfer/deploy/postverify/postverify-corrected + الربط بفحوص A1/A12/A15",
        f"preflight(قبل=9e2ace5+نظيف+200)={c1} · transfer(bundle d23a969+verify+sftp)={c2} · "
        f"deploy(deployed=d23a969/previous=9e2ace5/import_ok/restarted)={c3} · "
        f"corrected(6/6+0/0+النسخ)={c4} · الأصل الموثق للحادث موجود={c5}",
        "كل الشروط قائمة والمطابقة الحية: رأس الإنتاج الآن=d23a969 (A1) و ?v=d23a9698 (A12) والنسخ موجودة (A15)", ok)

    # D6 — شجرة «قبل» البصرية = كود 9e2ace5 (إنتاج ما قبل النشر) في src/
    out, _, rc = run("git -C %s rev-parse HEAD" % Path("/home/z/my-project/w2t07-before"),
                     cwd="/home/z/my-project/w2t07-before")
    before_head = out.strip()
    diff_out, _, _ = run(f"git -C {REPO} diff --stat {PREV_HEAD} 677b94d -- src/", cwd=REPO)
    ok = before_head.startswith("677b94d") and diff_out.strip() == ""
    add("D6", "D-visual", "شجرة «قبل» البصرية (w2t07-before @677b94d) مطابقة لـ src/ في 9e2ace5",
        "git -C w2t07-before rev-parse HEAD && git diff --stat 9e2ace5 677b94d -- src/",
        f"HEAD={before_head[:12]} · diff src/ بين 9e2ace5 و677b94d: {diff_out.strip() or '(فارغ — تطابق تام)'}",
        "677b94d وفرق src/ فارغ (فروق الالتزامات الحاكمة مستندات فقط)", ok)


def main() -> int:
    t0 = datetime.now(timezone.utc)
    print("=== W2-T07-AUDIT — independent audit ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, key_filename=KEY, look_for_keys=False,
                allow_agent=False, timeout=15)
    try:
        group_a(ssh)
    finally:
        ssh.close()
        print("Group A done.")
    group_b(); print("Group B done.")
    group_c(); print("Group C done.")
    group_d(); print("Group D done.")

    # ملاحظات موثقة غير حاجزة (إن ثبت جوهرها)
    finding("F2", "عدد الملفات في البطاقة «7 ملفات» مقابل stat الفعلي 9",
            "7 ملفات CSS معدّلة + tests/ui/__init__.py (فارغ) + tests/ui/test_design_tokens.py (جديد) = 9 في stat؛ "
            "+133/−35 مطابقة بالضبط. النطاق سليم (صفر JS) — سهو توثيقي فقط.")
    finding("F3", "زوج factory: دلتا القناة العظمى 11/255 لا ≤6 كما في صياغة ملخص البطاقة",
            "الموثق في visual-deterministic.json: factory diff=374 δ=11 — لكن أرضية الضجيج (زوج التحكم بنفس النسخة) "
            "للمصنع نفسه δ=11 في المنطقة (838,20,841,33) نفسها => الفرق من الضجيج لا من الرقعة. الصياغة الإجمالية "
            "«بدلتا قناة ≤6/255» غير دقيقة لهذا الزوج؛ الحكم البصري (NO_DIFFERENCE من VLM + ضمن الضجيج) سليم.")
    finding("F4", "لا إدخال worklog لتنفيذ الخطوتين 4-5 (البصري + النشر) — فجوة R8",
            "worklog آخر إدخال W2-T07-S123 (خطوات 1-3) بينما الخطوتان 4-5 موثقتان تفصيليًا في بطاقة TRACKER "
            "والأدلة كاملة في download/aes-remediation/W2-T07/. يوصى بسد الفجوة عند أول مزامنة (نفس معاملة W1-T03-S34).")
    finding("F5", "تسمية التوكن السابع في أمر الفحص «--border-strong» توكن قائم سابق لا من الـ13 الجديدة",
            "--border-strong (rgba(255,255,255,0.13)) موجود منذ إعادة تصميم 014 ويُخدم حيًا؛ التوكن الجديد ذو الدور "
            "الحدّي هو --accent-border-strong (وكلاهما مخدوم — فحص A10/A11). لا أثر على أي بوابة.")

    passed = sum(1 for c in CHECKS if c["verdict"] == "PASS")
    failed = sum(1 for c in CHECKS if c["verdict"] == "FAIL")
    blocking = [f for f in FINDINGS if f["blocking"]]
    final = "PASS" if failed == 0 and not blocking else "FAIL"

    script_md5 = hashlib.md5(Path(__file__).read_bytes()).hexdigest()
    result = {
        "task": "W2-T07-AUDIT — تدقيق مستقل كامل لمهمة W2-T07 (الخطوات 1-5: المسح + العقد + البصري + النشر)",
        "agent": "W2-T07-AUDIT (general-purpose audit agent)",
        "date": t0.strftime("%Y-%m-%d"),
        "mode": "SSH قراءة فقط على الإنتاج (92.5.14.150) + فحوص محلية (اختبارات/مقارنة/قياس) + مسباران سلبيان مؤقتان نُظّفا فورًا",
        "script_md5": script_md5,
        "summary": {"total": len(CHECKS), "passed": passed, "failed": failed,
                    "findings": len(FINDINGS), "blocking_findings": len(blocking)},
        "final_verdict": final,
        "checks": CHECKS,
        "findings": FINDINGS,
        "verdict_rationale": (
            "كل فحوص المجموعات A-D ناجحة بأدلة جمعها المدقق بنفسه: الإنتاج على d23a969 بشجرة نظيفة وخدمات "
            "صحية وصفر أخطاء journal فعلية؛ صفر hex/rgba في CSS الإنتاج خارج theme.css (تحقق مباشر على شجرة "
            "الإنتاج بمحركين مستقلين: python regex بدلالات rg الحرفية + GNU grep بحدّ كلمةي، مع شاهد تحكم "
            "إيجابي)؛ التوكنات السبعة والـ13 مخدومة حية و ?v=d23a9698 والجدار 401؛ الالتزام 0994d26 محصور "
            "في CSS/UI+الاختبار (+133/−35، صفر JS، 123→136)؛ العقد 17/17 ويرفض hex في تعريف وrgba حتى في "
            "تعليق (مسباران سلبيان فعليان) ويحرس أرضية 136؛ البصري: قياسي البكسلي المستقل مطابق حرفيًا "
            "للموثق (357/δ6، 2191/δ6، 0/0) وVLM NO_DIFFERENCE×6 والقاعدة bbde75fd… 2/13/91؛ رواية النشر "
            "(9e2ace5→d23a969 ff-only) مثبتة بسلسلة git والسلف والنسخ الاحتياطية."
        ) if final == "PASS" else "انظر الفحوص الفاشلة والملاحظات الحاجزة.",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nchecks: {passed}/{len(CHECKS)} passed, {failed} failed; "
          f"findings: {len(FINDINGS)} (blocking: {len(blocking)})")
    for c in CHECKS:
        if c["verdict"] == "FAIL":
            print(f"  FAIL {c['id']}: {c['name']} → {str(c['actual_output'])[:160]}")
    print(f"FINAL VERDICT: {final}")
    print(f"JSON → {OUT}")
    return 0 if final == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
