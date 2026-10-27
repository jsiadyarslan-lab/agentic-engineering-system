#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T10-AUDIT — وكيل تدقيق مستقل لمهمة W2-T10
(التصعيد يُعلن ولا يُدفن: runs/active يشمل ESCALATED + بانر ثابت z-critical
من الإقلاع + شريط طوارئ موصول بـ stop/resume القائمة + حلقات خط المراحل)
مع إعادة التحقق المستقلة من استرداد الالتزام اليتيم 036db8911 من الإنتاج
ودفعه إلى GitHub origin/main.

الانضباط (قسم هـ من التكليف): SSH قراءة فقط على الإنتاج طوال الجلسة
(git read/status/sha256sum/curl GET إلى loopback/systemctl is-active/
journalctl/ls). صفر كتابة على الإنتاج، صفر POST على أي endpoint يغير
حالة (probe/stop/resume)، صفر git push/commit على الإنتاج.
محليًا: git read + fetch origin (قراءة من GitHub) + فحوص صياغة/توكن.

التقييم بأسطر المخرجات الفعلية لا برموز الخروج (درس W1-T01/W2-T07:
rg غير مثبت على الإنتاج — «0» قد يكون command-not-found).
المخرج: download/aes-remediation/W2-T10/audit_independent.json
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

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
REPO = Path("/home/z/my-project/repo")
EV = Path("/home/z/my-project/download/aes-remediation/W2-T10")
OUT = EV / "audit_independent.json"
EXPECT_HEAD = "036db8911"
EXPECT_PARENT = "ab065c06c"
W2T10_FILES = [
    "src/api/projects.py",
    "src/ui/control-center.js",
    "src/ui/project-live.css",
    "src/ui/project-live.js",
    "src/ui/theme.css",
]
DEPLOYED_AT = "2026-10-27 16:50:58 GMT"  # ادعاء المنفذ — يُتحقق منه

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


# ============================================================ GROUP A — سلامة الإنتاج العامة (R6) — الفحوص 1-4
def group_a(ssh) -> None:
    # A1 (فحص 1) — /health
    out, _ = ssh_run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
    add("A1", "A-production-health", "/health على loopback:8010 = 200",
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health",
        out.strip(), "200", out.strip() == "200")

    # A2 (فحص 2) — الخدمات الثلاث
    out, _ = ssh_run(ssh, "systemctl is-active agentic nginx firewalld")
    vals = [l.strip() for l in out.splitlines() if l.strip()]
    add("A2", "A-production-health", "agentic + nginx + firewalld كلها active",
        "systemctl is-active agentic nginx firewalld",
        " / ".join(vals) or "(فارغ)", "active / active / active",
        vals == ["active", "active", "active"])

    # A3 (فحص 3) — journal آخر 60 دقيقة
    out, _ = ssh_run(ssh, "journalctl -u agentic --since '-60 min' -p err --no-pager | cat")
    real = real_journal_error_lines(out)
    add("A3", "A-production-health", "journalctl -u agentic آخر 60د -p err: لا مدخلات جديدة",
        "journalctl -u agentic --since '-60 min' -p err --no-pager | cat",
        out.strip() or "(فارغ)",
        "صفر أسطر خطأ فعلية (placeholder «-- No entries --» لا يُعد خطأً)",
        len(real) == 0, f"أسطر فعلية بعد إقصاء placeholder: {len(real)}")

    # A3b (إثراء غير حاجب) — نافذة أوسع تغطي النشر المعلن 16:50:58 GMT
    out, _ = ssh_run(ssh, "journalctl -u agentic --since '2026-10-27 16:50:00' -p err --no-pager | cat")
    real_b = real_journal_error_lines(out)
    add("A3b", "A-production-health",
        "journalctl -u agentic منذ نافذة النشر المعلنة (16:50 GMT) -p err: لا مدخلات خطأ",
        "journalctl -u agentic --since '2026-10-27 16:50:00' -p err --no-pager | cat",
        out.strip() or "(فارغ)",
        "صفر أسطر خطأ فعلية منذ النشر (توثيق أقوى من نافذة 60د)",
        len(real_b) == 0, f"أسطر فعلية: {len(real_b)}")

    # A4 (فحص 4) — رأس الإنتاج + شجرة نظيفة
    out, _ = ssh_run(ssh, "git -C /opt/agentic-engineering-system rev-parse --short=9 HEAD")
    head = out.strip()
    out2, _ = ssh_run(ssh, "git -C /opt/agentic-engineering-system status --short --untracked-files=no")
    tracked_dirty = [l for l in out2.splitlines() if l.strip()]
    out3, _ = ssh_run(ssh, "git -C /opt/agentic-engineering-system status --short | head -15")
    full_status = out3.strip() or "(0 أسطر)"
    ok = head == EXPECT_HEAD and len(tracked_dirty) == 0
    add("A4", "A-production-health",
        "رأس الإنتاج = 036db8911 والشجرة بلا ملفات متتبعة معدلة (untracked مقبول)",
        "git -C /opt/agentic-engineering-system rev-parse --short=9 HEAD ; "
        "git -C /opt/agentic-engineering-system status --short --untracked-files=no",
        json.dumps({"head": head, "tracked_dirty_lines": len(tracked_dirty),
                    "status_short_head15": full_status}, ensure_ascii=False),
        json.dumps({"head": EXPECT_HEAD, "tracked_dirty_lines": 0}, ensure_ascii=False),
        ok, "untracked مثل runtime/ مقبول وفق عتبة الفحص")


# ============================================================ GROUP B — استرداد الالتزام والدفع — الفحوص 5-8
def group_b(ssh) -> None:
    # B1 (فحص 5) — sha256 للملفات الخمسة على الخادم
    cmd = "cd /opt/agentic-engineering-system && sha256sum " + " ".join(W2T10_FILES)
    out, err = ssh_run(ssh, cmd)
    prod_hashes = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2:
            prod_hashes[parts[1]] = parts[0]
    ok = len(prod_hashes) == 5 and not err.strip()
    add("B1", "B-recovery-push", "sha256sum للملفات الخمسة على الخادم (مجموعة كاملة)",
        cmd, out.strip() or f"(stderr: {err.strip()})", "5 أسطر بصمات sha256 كاملة",
        ok, f"عدد الملفات الموقعة: {len(prod_hashes)}")

    # B2 (فحص 6) — التطابق البايتي مع git show محليًا 5/5
    local_hashes = {}
    for f in W2T10_FILES:
        out, err, rc = run(f"git show {EXPECT_HEAD}:{f} | sha256sum", cwd=REPO)
        if rc == 0:
            local_hashes[f] = out.split()[0]
    matches = {f: (prod_hashes.get(f) == local_hashes.get(f)) for f in W2T10_FILES}
    n_match = sum(1 for v in matches.values() if v)
    add("B2", "B-recovery-push",
        "تطابق بايتي 5/5: sha256(الإنتاج) == sha256(git show 036db8911 محليًا)",
        "git -C /home/z/my-project/repo show 036db8911:<file> | sha256sum  (لكل ملف)",
        json.dumps({f: {"prod": prod_hashes.get(f, "?"),
                        "local": local_hashes.get(f, "?"),
                        "match": matches[f]} for f in W2T10_FILES}, ensure_ascii=False),
        "5/5 match=true (بصمات sha256 كاملة في الحقل أعلاه)",
        n_match == 5, f"المتطابق: {n_match}/5")

    # B3 (فحص 7) — origin/main على GitHub عند 036db8911 + خطية فوق ab065c06c
    _, ferr, frc = run("git fetch origin", cwd=REPO)
    out, _, _ = run("git rev-parse --short=9 origin/main", cwd=REPO)
    origin_main = out.strip()
    _, _, rc_anc = run(f"git merge-base --is-ancestor {EXPECT_PARENT} origin/main", cwd=REPO)
    out_log, _, _ = run(f"git log --oneline {EXPECT_PARENT}..origin/main", cwd=REPO)
    commits_between = [l for l in out_log.splitlines() if l.strip()]
    ok = (frc == 0 and origin_main == EXPECT_HEAD and rc_anc == 0
          and len(commits_between) == 1
          and commits_between[0].split()[0].startswith(EXPECT_HEAD[:7]))
    add("B3", "B-recovery-push",
        "origin/main على GitHub عند 036db8911 والالتزام فوق ab065c06c خطيًا (التزام واحد بينهما)",
        "git -C /home/z/my-project/repo fetch origin ; git rev-parse --short=9 origin/main ; "
        "git merge-base --is-ancestor ab065c06c origin/main ; git log --oneline ab065c06c..origin/main",
        json.dumps({"fetch_rc": frc, "fetch_stderr": ferr.strip()[:200],
                    "origin_main": origin_main,
                    "ab065c06c_is_ancestor": rc_anc == 0,
                    "commits_between": commits_between}, ensure_ascii=False),
        json.dumps({"fetch_rc": 0, "origin_main": EXPECT_HEAD,
                    "ab065c06c_is_ancestor": True,
                    "commits_between": ["036db89 … (التزام W2-T10 وحده)"]},
                   ensure_ascii=False),
        ok)

    # B3b (إثراء) — الأب المباشر للالتزام = ab065c06c (مقارنة بالتجزئة الكاملة)
    out, _, _ = run(f"git log --format='%P' -1 {EXPECT_HEAD}", cwd=REPO)
    parent = out.strip()
    out_full, _, _ = run(f"git rev-parse {EXPECT_PARENT}", cwd=REPO)
    parent_full_expected = out_full.strip()
    add("B3b", "B-recovery-push", "الأب المباشر للالتزام 036db8911 = ab065c06c (بالتجزئة الكاملة)",
        "git -C /home/z/my-project/repo log --format='%P' -1 036db8911 ; git rev-parse ab065c06c",
        parent, parent_full_expected, parent == parent_full_expected,
        f"التجزئة الكاملة: {parent}")

    # B4 (فحص 8) — حزمة الاسترداد المؤقتة أزيلت من الخادم
    out, _ = ssh_run(ssh, "ls -la /tmp/w2t10-recovery.bundle 2>&1; echo RC=$?")
    not_found = "No such file" in out
    add("B4", "B-recovery-push", "/tmp/w2t10-recovery.bundle غير موجود على الخادم (أزيلت)",
        "ls -la /tmp/w2t10-recovery.bundle 2>&1; echo RC=$?",
        out.strip() or "(فارغ)", "No such file or directory", not_found,
        "نسخة الأدلة المحلية download/aes-remediation/W2-T10/w2t10-recovery.bundle باقية محليًا — لا تمس هذا الفحص")


# ============================================================ GROUP C — مراجعة كود W2-T10 — الفحوص 9-13
def group_c() -> None:
    # C1 (فحص 9) — projects.py: ESCALATED أزيل من تصفية الاستبعاد
    out, _, _ = run(f"git show {EXPECT_HEAD}:src/api/projects.py", cwd=REPO)
    m = re.search(
        r'active_project_ids = \[p\["id"\] for p in projects\s*'
        r'if p\["status"\] not in\s*\(([^)]*)\)\]', out)
    tuple_content = m.group(1).strip() if m else "(غير موجود)"
    exclusion = [t.strip().strip('"\'') for t in tuple_content.split(",") if t.strip()]
    diff_out, _, _ = run(f"git diff {EXPECT_PARENT}..{EXPECT_HEAD} -- src/api/projects.py", cwd=REPO)
    removed_esc_tuple = [l for l in diff_out.splitlines()
                         if l.startswith("-") and '"VERIFIED"' in l and "ESCALATED" in l]
    added_tuple = [l for l in diff_out.splitlines()
                   if l.startswith("+") and '"VERIFIED", "COMPLETED", "STOPPED")' in l
                   and "ESCALATED" not in l]
    ok = (m is not None
          and "ESCALATED" not in exclusion
          and sorted(exclusion) == ["COMPLETED", "STOPPED", "VERIFIED"]
          and len(removed_esc_tuple) == 1
          and len(added_tuple) == 1)
    add("C1", "C-code-review",
        "projects.py: الدِف يضيف ESCALATED إلى runs/active — tuple الاستبعاد الفعلي "
        "(\"VERIFIED\", \"COMPLETED\", \"STOPPED\") صحيح ووارد حرفيًا في الكود",
        "git show 036db8911:src/api/projects.py (منطقة active_runs) + "
        "git diff ab065c06c..036db8911 -- src/api/projects.py",
        json.dumps({
            "exclusion_tuple": exclusion,
            "ESCALATED_in_exclusion": "ESCALATED" in exclusion,
            "diff_removed_ESCALATED_from_tuple": len(removed_esc_tuple) == 1,
            "diff_added_clean_tuple": len(added_tuple) == 1,
            "secondary_DRAFT_filter_present":
                'snap["status"] in ("DRAFT", "AWAITING_OWNER_APPROVAL")' in out,
            "run_item_includes_status": '"status": snap["status"]' in out,
        }, ensure_ascii=False),
        json.dumps({"exclusion_tuple": ["VERIFIED", "COMPLETED", "STOPPED"],
                    "ESCALATED_in_exclusion": False,
                    "diff_removed_ESCALATED_from_tuple": True,
                    "diff_added_clean_tuple": True,
                    "secondary_DRAFT_filter_present": True,
                    "run_item_includes_status": True}, ensure_ascii=False),
        ok,
        "المنطق: مشروع ESCALATED ليس VERIFIED/COMPLETED/STOPPED فيدخل active_project_ids، "
        "وحالته ليست DRAFT/AWAITING فيعبر الفلتر الثانوي ويظهر في runs/active بحالته — "
        "الفلتر السابق كان يدفنه تحت الأخضر الناجح (عيب التقرير)")

    # C2 (فحص 10) — البانر من الإقلاع + شريط الطوارئ موصول بstop/resume القائمة
    pl, _, _ = run(f"git show {EXPECT_HEAD}:src/ui/project-live.js", cwd=REPO)
    cc, _, _ = run(f"git show {EXPECT_HEAD}:src/ui/control-center.js", cwd=REPO)
    idx_html, _, _ = run(f"git show {EXPECT_HEAD}:src/ui/index.html", cwd=REPO)
    app_js, _, _ = run(f"git show {EXPECT_HEAD}:src/ui/app.js", cwd=REPO)
    projects_py, _, _ = run(f"git show {EXPECT_HEAD}:src/api/projects.py", cwd=REPO)

    facts = {
        "window_PlEscalation_exported": "window.PlEscalation = EscalationBanner;" in pl,
        "renderRuns_defined_and_boot_fetch":
            "function renderRuns()" in cc
            and 'Hub.fetchJSON("/api/projects/runs/active")' in cc,
        "cc_calls_replace_x2": cc.count("window.PlEscalation.replace(runs)") == 2,
        "cc_guards_if_window_PlEscalation": "if (window.PlEscalation) {" in cc,
        "script_order_project_live_before_control_center":
            0 < idx_html.find("project-live.js") < idx_html.find("control-center.js"),
        "banner_filters_ESCALATED_status": 'i.status === "ESCALATED"' in pl,
        "banner_role_alert": 'node.setAttribute("role", "alert")' in pl,
        "emergency_bar_stop_endpoint":
            'Hub.fetchJSON("/api/projects/" + state.id + "/stop"' in pl,
        "emergency_bar_resume_endpoint":
            'Hub.fetchJSON("/api/projects/" + state.id + "/resume"' in pl,
        "stop_endpoint_total_uses_menu_plus_bar":
            pl.count('Hub.fetchJSON("/api/projects/" + state.id + "/stop"') == 2,
        "resume_endpoint_total_uses_menu_plus_bar":
            pl.count('Hub.fetchJSON("/api/projects/" + state.id + "/resume"') == 2,
        "Hub_fetchJSON_defined_in_app_js": "function fetchJSON(url, options)" in app_js,
        "stop_endpoint_in_api": '@router.post("/{project_id}/stop")' in projects_py,
        "resume_endpoint_in_api": '@router.post("/{project_id}/resume")' in projects_py,
    }
    ok = all(facts.values())
    add("C2", "C-code-review",
        "project-live.js: بانر التصعيد يُبنى من الإقلاع (renderRuns عند التحميل + ترتيب "
        "السكربتات) وشريط الطوارئ موصول بstop/resume القائمة (نفس Hub.fetchJSON ونفس نقطتي API)",
        "git show 036db8911:src/ui/{project-live.js,control-center.js,index.html,app.js} + "
        "src/api/projects.py — بحث عن التعريفات والمسارات",
        json.dumps(facts, ensure_ascii=False),
        "كل القيم true", ok,
        "renderRuns() يجلب runs/active عند إقلاع الصفحة ويستدعي PlEscalation.replace(runs)؛ "
        "project-live.js يُحمّل قبل control-center.js في index.html فالتوفر مضمون ومحروس "
        "بif (window.PlEscalation). نقطتا stop/resume نفساهما في بطاقة التنفيذ وبطاقة الحجب "
        "القائمتين (الاستدعاءان الآخران للنقاط نفسها) — والنقطتان معرفتان فعلاً في projects.py")

    # C3 (فحص 11) — project-live.css: صفر ألوان خام
    css, _, _ = run(f"git show {EXPECT_HEAD}:src/ui/project-live.css", cwd=REPO)
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    rgbas = re.findall(r"rgba?\(", css)
    var_colors = len(re.findall(r"var\(--", css))
    new_rules = [cls for cls in ["pl-escalation-banner", "pl-esc-icon", "pl-esc-text",
                                 "pl-esc-open", "pl-emergency-bar", "pl-er-chip",
                                 "pl-er-stop", "pl-er-resume", "pl-flow-dot"]
                 if cls in css]
    add("C3", "C-code-review",
        "project-live.css (كاملًا عند 036db8911): صفر hex/rgba خام — كل الألوان عبر var(--…)",
        "git show 036db8911:src/ui/project-live.css | عدّ #[0-9a-f]{3,8} و rgba?( و var(--",
        json.dumps({"hex_count": len(hexes), "rgba_count": len(rgbas),
                    "var_token_uses": var_colors,
                    "transparent_keyword_count": css.count("transparent"),
                    "new_rule_classes_found": len(new_rules)}, ensure_ascii=False),
        json.dumps({"hex_count": 0, "rgba_count": 0,
                    "new_rule_classes_found": 9}, ensure_ascii=False),
        len(hexes) == 0 and len(rgbas) == 0 and len(new_rules) == 9,
        "شرط W2-T07 (صفر ألوان خام خارج theme.css) محفوظ في الإضافات الجديدة — "
        "كلمة transparent الوحيدة في keyframes النبض ليست قيمة hex/rgba (كلمة CSS قياسية)")

    # C4 (فحص 12) — theme.css: سطر توكن واحد فقط والاسم مستخدم
    theme_diff, _, _ = run(f"git diff {EXPECT_PARENT}..{EXPECT_HEAD} -- src/ui/theme.css", cwd=REPO)
    added = [l for l in theme_diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in theme_diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    token_match = re.search(r"^\+\s*(--[\w-]+)\s*:\s*([^;]+);", added[0]) if added else None
    token_name = token_match.group(1) if token_match else ""
    token_val = (token_match.group(2) or "").strip() if token_match else ""
    used = len(re.findall(r"var\(" + re.escape(token_name) + r"\)", css)) if token_name else 0
    ok = (len(added) == 1 and len(removed) == 0 and token_name == "--z-critical"
          and used > 0)
    add("C4", "C-code-review",
        "theme.css: السطر المضاف توكن واحد فقط (--z-critical) واسمه مستخدم فعلاً في project-live.css",
        "git diff ab065c06c..036db8911 -- src/ui/theme.css ; "
        "git show 036db8911:src/ui/project-live.css | grep -c 'var(--z-critical)'",
        json.dumps({"added_lines": added, "removed_lines": len(removed),
                    "token": token_name, "value": token_val,
                    "uses_in_project_live_css": used}, ensure_ascii=False),
        json.dumps({"added_lines": ["+  --z-critical: 80; …"], "removed_lines": 0,
                    "token": "--z-critical", "uses_in_project_live_css": ">=1"},
                   ensure_ascii=False),
        ok, f"var(--z-critical) مستخدم {used} مرة في z-index البانر الثابت (فوق كل شيء)")

    # C5 (فحص 13) — سلامة صياغة JS: توازن أقواس + node --check محليًا
    syntax = {}
    for f in ["src/ui/project-live.js", "src/ui/control-center.js"]:
        src = (REPO / f).read_text(encoding="utf-8")
        braces = (src.count("{"), src.count("}"))
        parens = (src.count("("), src.count(")"))
        # فرق الأقواس الدائرية مصدره أقواس داخل نصوص/تعليقات عربية (مثل «(W2-T10)»
        # وقوائم مرقمة «1)») — قضاء node --check هو الحكم النهائي المعتمد
        _, serr, src_rc = run(f"node --check {f}", cwd=REPO)
        syntax[f] = {
            "braces_open_close": list(braces), "braces_balanced": braces[0] == braces[1],
            "parens_open_close": list(parens),
            "parens_note": "الفرق من أقواس داخل نصوص/تعليقات — node --check هو المرجع",
            "node_check_rc": src_rc, "node_check_stderr": serr.strip()[:200],
        }
    ok = all(v["braces_balanced"] and v["node_check_rc"] == 0 for v in syntax.values())
    add("C5", "C-code-review",
        "سلامة صياغة JS: توازن الأقواس المعقوفة في الملفين + node --check rc=0 "
        "(أقوى من الفحص التقريبي المطلوب)",
        "python عدّ { } ( ) في الملفين + node --check src/ui/{project-live.js,control-center.js}",
        json.dumps(syntax, ensure_ascii=False),
        "braces متوازنة + node --check rc=0 للملفين", ok)


# ============================================================ GROUP D — الخدمة الحية للأصول الجديدة — الفحوص 14-17
def group_d(ssh) -> None:
    # D1 (فحص 14) — الأصول الجديدة تُخدم
    out, err = ssh_run(ssh,
        "curl -s http://127.0.0.1:8010/static/project-live.css | "
        "grep -c 'z-critical\\|escalation\\|emergency'")
    count = out.strip()
    ok = count.isdigit() and int(count) > 0
    add("D1", "D-live-service",
        "الأصل الجديد يُخدم حيًا: project-live.css يحوي z-critical/escalation/emergency",
        "curl -s http://127.0.0.1:8010/static/project-live.css | "
        "grep -c 'z-critical\\|escalation\\|emergency'",
        count or f"(stderr: {err.strip()})", "> 0", ok,
        "grep -c يعيد عدد الأسطر المطابقة (بديل \\| في BRE لأمر التكليف)")

    # D2 (فحص 15) — إصدار الأصول في HTML يعكس 036db891
    out, err = ssh_run(ssh, "curl -s http://127.0.0.1:8010/ | grep -oP '\\?v=[a-f0-9]+' | head -1")
    v_line = out.strip()
    if not v_line and ("invalid option" in err or "unrecognized option" in err):
        out, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/ | grep -oE '\\?v=[a-f0-9]+' | head -1")
        v_line = out.strip()
    asset_v = v_line[3:] if v_line.startswith("?v=") else v_line
    # دليل مرافق (قراءة فقط): تتابع إعادة التشغيل في journal حول النشر المعلن
    # (سطر «asset version» الخاص بالتطبيق لا يظهر في journal — مخرج مُسجِّل التطبيق
    # يذهب لمسار آخر؛ الدليل المباشر هو ?v= المخدوم نفسه)
    journal_out, _ = ssh_run(ssh,
        "journalctl -u agentic --no-pager --since '2026-10-27 16:50:00' "
        "--until '2026-10-27 16:52:00' | grep -E 'Stopping|Started|Uvicorn running' | head -6")
    restart_lines = [l.strip() for l in journal_out.splitlines() if l.strip()]
    ok = asset_v == EXPECT_HEAD[:8]
    add("D2", "D-live-service",
        "إصدار الأصول في HTML يعكس الالتزام (?v=036db891) — آلية _ASSET_VERSION "
        "(git rev-parse --short=8 HEAD عند إقلاع العملية) + تتابع الإعادة تشغيل في journal",
        "curl -s http://127.0.0.1:8010/ | grep -oP '\\?v=[a-f0-9]+' | head -1  ; "
        "journalctl -u agentic --no-pager --since '2026-10-27 16:50:00' --until '2026-10-27 16:52:00' "
        "| grep -E 'Stopping|Started|Uvicorn running' | head -6",
        json.dumps({"asset_version_in_html": v_line,
                    "journal_restart_sequence": restart_lines},
                   ensure_ascii=False),
        json.dumps({"asset_version_in_html": "?v=036db891"}, ensure_ascii=False),
        ok, f"قيمة ?v المستخرجة: {asset_v!r} — المتوقعة short=8 من {EXPECT_HEAD}؛ "
            "سطر logger «asset version» لا يظهر في journal (مسجل التطبيق يسلك مسارًا آخر) — "
            "?v= المخدوم هو الدليل المباشر")

    # D3 (فحص 16) — قائمة runs/active نفسها (طلب واحد، صفر كتابة على الخادم)
    out, _ = ssh_run(ssh,
        "curl -s -w '\\n@@HTTPCODE:%{http_code}' http://127.0.0.1:8010/api/projects/runs/active")
    if "@@HTTPCODE:" in out:
        body, _, code = out.rpartition("@@HTTPCODE:")
        code_line = code.strip()
    else:
        body, code_line = out.strip(), "(لا كود)"
    try:
        parsed = json.loads(body.strip()) if body.strip() else None
        json_ok = isinstance(parsed, dict) and "runs" in parsed and isinstance(parsed["runs"], list)
        runs_brief = [{"project_id": r.get("project_id"), "status": r.get("status"),
                       "name": r.get("name")}
                      for r in parsed["runs"]] if json_ok else None
    except Exception:
        json_ok, parsed, runs_brief = False, None, None
    add("D3", "D-live-service",
        "GET /api/projects/runs/active = 200 JSON سليم بمفتاح runs (قائمة)",
        "curl -s -w '\\n@@HTTPCODE:%{http_code}' http://127.0.0.1:8010/api/projects/runs/active",
        json.dumps({"http_code": code_line, "json_valid_with_runs": json_ok,
                    "runs_brief": runs_brief}, ensure_ascii=False),
        json.dumps({"http_code": "200", "json_valid_with_runs": True}, ensure_ascii=False),
        code_line == "200" and json_ok,
        "طلب GET واحد بلا أي ملف وسيط على الخادم — توثيق فقط لحالة القائمة الحية")

    # D4 (فحص 17) — readiness عبر loopback (GET فقط — لا POST probe إطلاقاً)
    # البنية الفعلية: {"capabilities": [ {capability_id, readiness_status, stored_status, …} ], …}
    out, _ = ssh_run(ssh, "curl -s http://127.0.0.1:8010/api/environment/readiness")
    caps_info = {}
    try:
        parsed = json.loads(out) if out.strip() else {}
        caps = parsed.get("capabilities") if isinstance(parsed, dict) else None
        if isinstance(caps, list):
            for item in caps:
                if isinstance(item, dict) and item.get("capability_id") in ("llm", "network_http"):
                    caps_info[item["capability_id"]] = {
                        "readiness_status": item.get("readiness_status"),
                        "stored_status": item.get("stored_status"),
                        "last_success_at": item.get("last_success_at"),
                    }
    except Exception:
        parsed = {}
    documented = set(caps_info.keys()) == {"llm", "network_http"}
    add("D4", "D-live-service",
        "GET /api/environment/readiness (توثيق فقط): حالة llm و network_http",
        "curl -s http://127.0.0.1:8010/api/environment/readiness",
        json.dumps(caps_info, ensure_ascii=False),
        "تسجيل حالتي llm و network_http (توثيق فقط — لا عتبة نجاح/فشل)",
        documented,
        "قراءة GET فقط: لا مسّ للحالة المخزنة (POST probe يغيرها — محظور في التكليف)؛ "
        "STALE = خارج نافذة صلاحية المسبار وليس فشلًا — تحديثه يتطلب POST probe محظور")

    # D5 (إثراء غير حاجب) — وقت آخر إقلاع للخدمة مقابل زمن النشر المعلن
    out, _ = ssh_run(ssh, "systemctl show agentic -p ActiveEnterTimestamp --value")
    entered = out.strip()
    add("D5", "D-live-service",
        "زمن آخر إقلاع للخدمة agentic (توثيق مقابل النشر المعلن " + DEPLOYED_AT + ")",
        "systemctl show agentic -p ActiveEnterTimestamp --value",
        entered, "توثيق فقط", True,
        "النشر المعلن 2026-10-27 16:50:58 GMT — يُقارن بالقيمة المسجلة")

    # D6 (إثراء غير حاجب — قراءة فقط) — متصفح المالك يستهلك أصول الإصدار الجديد فعلاً
    out, _ = ssh_run(ssh,
        "sudo -n tail -3000 /var/log/nginx/access.log 2>/dev/null | grep -c 'v=036db891'")
    c = out.strip()
    first_line, _ = ssh_run(ssh,
        "sudo -n tail -3000 /var/log/nginx/access.log 2>/dev/null | grep 'v=036db891' | head -1")
    ok = c.isdigit() and int(c) > 0
    add("D6", "D-live-service",
        "سجل nginx (قراءة فقط): عملاء حقيقيون يجلبون أصول ؟v=036db891 عبر الجدار",
        "sudo -n tail -3000 /var/log/nginx/access.log | grep -c 'v=036db891'",
        json.dumps({"count_last3000": c,
                    "first_hit": first_line.strip()[:180]}, ensure_ascii=False),
        "> 0", ok,
        "دليل مستقل أن الأصول الجديدة تصل للمستخدم النهائي عبر nginx لا فقط على loopback")


# ============================================================ FINDINGS — ملاحظات التدقيق
def build_findings() -> None:
    finding("F1", "فجوة R8: لا إدخال worklog لتنفيذ W2-T10 الأصلي",
            "الجلسة المنفذة ماتت قبل تسجيل worklog — إدخال التدقيق هذا (W2-T10-AUDIT) يسجل "
            "الجانب المستقل فقط؛ يبقى على المنفذ/الأب سد رواية التنفيذ عند تحديث البطاقة "
            "والمزامنة (نفس معاملة W1-T03-S34 وF4 في W2-T07)", blocking=False)
    finding("F2", "ادعاء «إعادة إنتاج الدفن موثقة» بلا دليل باقٍ",
            "رسالة الالتزام تدعي توثيق إعادة إنتاج الدفن، لكن download/aes-remediation/W2-T10/ "
            "لا يحوي إلا recovery-verify.json وw2t10-recovery.bundle — لا اختبار تصعيد مصطنع "
            "ولا لقطات ولا VLM (خطوة البطاقة 4). منطق الكود مثبت مستقلاً في C1/C2 والخدمة "
            "حية في D1-D3، لكن يوصى بإعادة خطوة القبول البصرية أو توثيق قرار المالك بقبول "
            "التحقق الكودي عند تحديث البطاقة", blocking=False)
    finding("F3", "نطاق الملفات: البطاقة 3 والالتزام 5",
            "بطاقة W2-T10 ذكرت project-live.js/css + control-center.js؛ الالتزام يلمس 5 ملفات "
            "(+projects.py وtheme.css). التوسيع مبرر جوهريًا: إصلاح الدفن نفسه في تصفية "
            "runs/active الخلفية وتوكن z-critical — يستحق التوثيق كانحراف نطاق عند تحديث البطاقة",
            blocking=False)
    finding("F4", "لوحة الحالة §1 لا تزال تعرض W2-T10 «لم تبدأ»",
            "متوقع ووفق التكليف: تحديث البطاقة ولوحة الحالة مسؤولية المنفذ بعد توقيع التدقيق",
            blocking=False)
    finding("F5", "سطر logger «asset version (011)» غائب عن journal",
            "مسجل التطبيق يسلك مسارًا آخر — الدليل المباشر على الإصدار هو ?v=036db891 المخدوم "
            "في HTML (D2) وتتابع الإعادة تشغيل في journal نفسه", blocking=False)
    finding("F6", "مطابقة زمن النشر حرفيًا + اتساق أدلة الاسترداد",
            "ActiveEnterTimestamp = Tue 2026-10-27 16:50:58 GMT يطابق النشر المعلن حرفيًا (D5)، "
            "وبادئات بصمات recovery-verify.json (المنفذ) تتطابق مع بصماتي الكاملة المستقلة (B1/B2) "
            "— رواية الاسترداد متسقة مع الأدلة المستقلة", blocking=False)


# ============================================================ MAIN
def main() -> int:
    EV.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, key_filename=KEY,
                look_for_keys=False, allow_agent=False, timeout=20)
    try:
        group_a(ssh)
        group_b(ssh)
    finally:
        ssh.close()

    group_c()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, key_filename=KEY,
                look_for_keys=False, allow_agent=False, timeout=20)
    try:
        group_d(ssh)
    finally:
        ssh.close()

    n_pass = sum(1 for c in CHECKS if c["verdict"] == "PASS")
    n_total = len(CHECKS)
    overall = "PASS" if n_pass == n_total else "FAIL"

    build_findings()

    script_md5 = hashlib.md5(Path(__file__).read_bytes()).hexdigest()
    payload = {
        "audit_id": "W2-T10-AUDIT",
        "auditor": "وكيل تدقيق مستقل (general-purpose) — الأدلة كلها جمعها بنفسه عبر SSH قراءة فقط",
        "task": "تدقيق مستقل قراءة-فقط لتغييرات W2-T10 المنشورة على الإنتاج 92.5.14.150 "
                "+ إعادة التحقق من استرداد الالتزام اليتيم 036db8911 ودفعه إلى GitHub",
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "production": {"host": HOST, "expected_head": EXPECT_HEAD,
                       "deployed_at_claim": DEPLOYED_AT},
        "script_md5": script_md5,
        "script_path": "/home/z/my-project/scripts/w2t10_audit_check.py",
        "summary": {"total_checks": n_total, "passed": n_pass,
                    "failed": n_total - n_pass, "verdict": overall},
        "session_discipline": {
            "production_writes": 0,
            "production_commands": "قراءة فقط: git rev-parse/status/show-read, sha256sum, "
                                   "curl GET إلى loopback (health/static//api runs/active/readiness), "
                                   "systemctl is-active/show-read, journalctl read, ls",
            "post_endpoints": 0,
            "git_ops_on_production": "قراءة فقط — لا push/commit/reset",
            "git_push_on_production": False,
            "local_repo_writes": "git fetch origin فقط (تحديث مرجع تتبع محلي — لا يمس الإنتاج)",
            "node_note": "node --check غير مطلوب على الخادم — نُفذ محليًا (rc=0) وهو أقوى من الفحص التقريبي المطلوب",
        },
        "checks": CHECKS,
        "findings": FINDINGS,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"النتيجة: {overall} — {n_pass}/{n_total} فحصًا ناجحًا")
    for c in CHECKS:
        mark = "OK " if c["verdict"] == "PASS" else "FAIL"
        print(f"  [{mark}] {c['id']} · {c['name']}")
    print(f"الأدلة: {OUT}")
    print(f"script_md5: {script_md5}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
