#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W1-T04-AUDIT — تدقيق مستقل لمهمة W1-T04 (النسخ الاحتياطي الليلي المؤتمت 03:30 + الاحتفاظ 7 أيام + تمرين الاسترجاع).
الوكيل: W1-T04-AUDIT (وكيل تدقيق مستقل — general-purpose) · التاريخ: 2026-10-27
الوضع: SSH قراءة فقط على الإنتاج 92.5.14.150 (sudo -n للقراءات فقط: cat/systemctl/journalctl/stat/ls)
مع الاستثناءين المسموحين حصراً:
  (أ) فحص استرجاعي خاص بي: cp نسخة النسخ الاحتياطي إلى /tmp/w1t04-audit-drill.db → فحصها → حذفها.
  (ب) اختبار طُعم احتفاظ خاص بي: إنشاء /opt/aes-backups/db/nightly-20201010.db بتاريخ قديم (touch -d)
      وتشغيل أمر الحذف نفسه (find ... -mtime +7 -print -delete) والتأكد أنه يمسح الطُعم القديم فقط
      ويبقي نسخة اليوم — ثم التأكد من نظافة الحالة النهائية.
ممنوع منعاً باتاً: أي مساس بالقاعدة الحية، إيقاف/إعادة تشغيل أي خدمة، تعديل السكربت/الوحدات، أي git/push.
التقييم بأسطر المخرجات الفعلية لا برموز الخروج (درس W1-T02).
المخرجات: /home/z/my-project/download/aes-remediation/W1-T04/audit_independent.json
"""
import json
import re
import sys
import traceback

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"
EVID = "/home/z/my-project/download/aes-remediation/W1-T04"
OUT = EVID + "/audit_independent.json"

SCRIPT_PATH = "/opt/agentic-engineering-system/scripts/ops/nightly_backup.sh"
SRC_DB = "/opt/agentic-engineering-system/runtime/agent_hub_v2.db"
BK_DB = "/opt/aes-backups/db/nightly-20261027.db"
DRILL_TMP = "/tmp/w1t04-audit-drill.db"
DECOY = "/opt/aes-backups/db/nightly-20201010.db"
FIND_LITERAL = "find /opt/aes-backups/db -name 'nightly-*.db' -mtime +7 -print -delete"


def run(ssh, cmd, timeout=90):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    return {"rc": rc, "out": out, "err": err}


def main():
    checks = []
    notes = []

    def add(name, cmd, res, passed, expected, phase, note=""):
        checks.append({
            "phase": phase, "name": name, "cmd": cmd, "rc": res["rc"],
            "out": res["out"][:6000], "err": res["err"][:600],
            "expected": expected, "passed": bool(passed), "note": note,
        })
        print(("PASS " if passed else "FAIL ") + "[" + phase + "] " + name
              + ("" if passed else "  <<< expected: " + expected))

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, key_filename=KEY,
                 look_for_keys=False, allow_agent=False, timeout=25)

    meta = run(ssh, "date -u '+%Y-%m-%d %H:%M:%S UTC' && hostname && date +%Z")
    print("server meta:", meta["out"].replace("\n", " · "))

    # ============ ب) الوحدتان (systemd) — قراءة فقط ============
    P = "units"
    r_svc = run(ssh, "systemctl cat aes-backup.service")
    add("svc_unit_type_oneshot", "systemctl cat aes-backup.service", r_svc,
        "Type=oneshot" in r_svc["out"], "Type=oneshot", P)
    add("svc_unit_user_opc", "systemctl cat aes-backup.service", r_svc,
        "User=opc" in r_svc["out"] and "Group=opc" in r_svc["out"], "User=opc + Group=opc", P)
    add("svc_unit_execstart_script", "systemctl cat aes-backup.service", r_svc,
        "ExecStart=" + SCRIPT_PATH in r_svc["out"], "ExecStart=/opt/agentic-engineering-system/scripts/ops/nightly_backup.sh", P)
    r_show = run(ssh, "systemctl show aes-backup.service -p Type -p User -p ExecStart")
    add("svc_show_user_type_execstart", "systemctl show aes-backup.service -p Type -p User -p ExecStart", r_show,
        "Type=oneshot" in r_show["out"] and "User=opc" in r_show["out"] and SCRIPT_PATH in r_show["out"],
        "show: Type=oneshot · User=opc · ExecStart=script", P)

    r_timer = run(ssh, "systemctl cat aes-backup.timer")
    add("timer_unit_oncalendar_0330", "systemctl cat aes-backup.timer", r_timer,
        "OnCalendar=*-*-* 03:30:00" in r_timer["out"], "OnCalendar=*-*-* 03:30:00", P)
    add("timer_unit_persistent_true", "systemctl cat aes-backup.timer", r_timer,
        "Persistent=true" in r_timer["out"], "Persistent=true", P)

    r_en = run(ssh, "systemctl is-enabled aes-backup.timer")
    add("timer_is_enabled", "systemctl is-enabled aes-backup.timer", r_en,
        r_en["out"] == "enabled", "enabled", P)
    r_act = run(ssh, "systemctl is-active aes-backup.timer")
    add("timer_is_active", "systemctl is-active aes-backup.timer", r_act,
        r_act["out"] == "active", "active", P)

    r_lt = run(ssh, "systemctl list-timers aes-backup.timer --no-pager")
    add("timer_next_elapse_20261028_0330_GMT", "systemctl list-timers aes-backup.timer --no-pager", r_lt,
        ("Wed 2026-10-28 03:30:00 GMT" in r_lt["out"]) and ("aes-backup.timer" in r_lt["out"])
        and ("1 timers listed" in r_lt["out"]),
        "الموعد القادم Wed 2026-10-28 03:30:00 GMT + 1 timers listed", P,
        note="LAST='-': المؤقت أُنشئ اليوم بعد 03:30 فأول إطلاق تلقائي غداً (متوقع)")
    r_link = run(ssh, "ls -l /etc/systemd/system/timers.target.wants/aes-backup.timer")
    add("timer_wants_symlink", "ls -l /etc/systemd/system/timers.target.wants/aes-backup.timer", r_link,
        ("-> /etc/systemd/system/aes-backup.timer" in r_link["out"]), "symlink → /etc/systemd/system/aes-backup.timer", P)

    # ============ ج) السكربت — قراءة فقط + مراجعة سطراً سطراً ============
    P = "script"
    r_st = run(ssh, "sudo -n stat -c '%U %G %a' " + SCRIPT_PATH)
    add("script_owner_root_opc_750", "sudo -n stat -c '%U %G %a' " + SCRIPT_PATH, r_st,
        r_st["out"] == "root opc 750", "root opc 750", P,
        note="معالجة حادث 203/EXEC: المجموعة opc تملك قراءة+تنفيذ (r-x)")

    r_rx = run(ssh, "test -r " + SCRIPT_PATH + " && test -x " + SCRIPT_PATH + " && echo OPC_RX_OK")
    add("script_opc_readable_executable", "test -r && test -x (as opc)", r_rx,
        r_rx["out"] == "OPC_RX_OK", "OPC_RX_OK — قابل للقراءة/التنفيذ من opc (يمنع تكرار 203/EXEC)", P)

    r_cat = run(ssh, "sudo -n cat " + SCRIPT_PATH)
    sc = r_cat["out"]
    r_md5 = run(ssh, "sudo -n md5sum " + SCRIPT_PATH + " && sudo -n wc -l -c " + SCRIPT_PATH)

    add("script_src_dst_paths", "sudo -n cat " + SCRIPT_PATH, r_cat,
        ('SRC="/opt/agentic-engineering-system/runtime/agent_hub_v2.db"' in sc)
        and ('DEST_DIR="/opt/aes-backups/db"' in sc)
        and ('LOG_DIR="/opt/aes-backups/logs"' in sc),
        "المصدر=runtime/agent_hub_v2.db · الوجهة=/opt/aes-backups/db · السجل=/opt/aes-backups/logs", P)

    add("script_safe_sqlite_backup_api", "sudo -n cat " + SCRIPT_PATH, r_cat,
        ("sqlite3.connect(src)" in sc) and ("con.backup(dcon)" in sc)
        and (re.search(r"^\s*cp\s+\S", sc, re.M) is None),
        "sqlite3.connect(src).backup(dst) — لا نسخ ملف خام (لا أوامر cp)", P)

    add("script_internal_integrity_check", "sudo -n cat " + SCRIPT_PATH, r_cat,
        "integrity_check" in sc, "PRAGMA integrity_check داخلي على النسخة الناتجة", P)

    add("script_partial_delete_on_fail", "sudo -n cat " + SCRIPT_PATH, r_cat,
        ('rm -f "$DEST"' in sc) and ("removing partial file" in sc),
        'عند فشل rc≠0: rm -f "$DEST" (الملف الجزئي داخل /opt/aes-backups/db فقط)', P)

    add("script_retention_find_line", "sudo -n cat " + SCRIPT_PATH, r_cat,
        (re.search(r"find\s+\"\$DEST_DIR\"\s+-name\s+'nightly-\*\.db'\s+-mtime\s+\+7\s+-print\s+-delete", sc) is not None)
        and ('DEST_DIR="/opt/aes-backups/db"' in sc),
        'find "$DEST_DIR" -name \'nightly-*.db\' -mtime +7 -print -delete (DEST_DIR=/opt/aes-backups/db)', P)

    add("script_logging", "sudo -n cat " + SCRIPT_PATH, r_cat,
        ('LOG="${LOG_DIR}/backup-${DATE}.log"' in sc) and ('>> "$LOG" 2>&1' in sc),
        "سجل تشغيل /opt/aes-backups/logs/backup-YYYYMMDD.log (كل المخرجات إليه)", P)

    add("script_skip_if_today_exists", "sudo -n cat " + SCRIPT_PATH, r_cat,
        ("if os.path.exists(dst):" in sc) and ("SKIP" in sc),
        "تخطي النسخ إن وُجدت نسخة اليوم (os.path.exists(dst) → SKIP)", P)

    # لا أوامر خطرة: لا systemctl/sudo، rm فقط على $DEST، لا كتابة على المصدر/الرنتايم
    rm_lines = [ln for ln in sc.splitlines() if re.search(r"(^|\s|;)rm\s", ln)]
    rm_ok = all('"$DEST"' in ln for ln in rm_lines)
    dangerous_tokens = [t for t in ("systemctl", "sudo", "mkfs", "dd if=", "shutdown", "reboot", "kill ")
                        if t in sc]
    src_write = re.search(r">\s*\"?\$?SRC|>\s*/opt/agentic-engineering-system/runtime", sc) is not None
    add("script_no_dangerous_ops", "sudo -n cat " + SCRIPT_PATH, r_cat,
        rm_ok and (not dangerous_tokens) and (not src_write),
        "rm فقط على $DEST داخل /opt/aes-backups · لا systemctl/sudo · لا كتابة على المصدر",
        P, note="rm lines: " + json.dumps(rm_lines) + " · dangerous: " + json.dumps(dangerous_tokens))

    add("script_uses_app_venv_python", "sudo -n cat " + SCRIPT_PATH, r_cat,
        'PY="/opt/agentic-engineering-system/.venv/bin/python"' in sc,
        "PY=/opt/agentic-engineering-system/.venv/bin/python (بايثون التطبيق نفسه)", P)

    # ============ د) النسخة الناتجة — قراءة فقط ============
    P = "artifact"
    r_ls = run(ssh, "ls -la /opt/aes-backups/db/ /opt/aes-backups/logs/")
    add("backup_file_present", "ls -la /opt/aes-backups/db/ /opt/aes-backups/logs/", r_ls,
        "nightly-20261027.db" in r_ls["out"], "nightly-20261027.db موجود", P)

    r_sz = run(ssh, "stat -c '%s|%y' " + BK_DB + " ; stat -c '%s|%y' " + SRC_DB)
    lines = [ln.strip() for ln in r_sz["out"].splitlines() if "|" in ln]
    b_sz = int(lines[0].split("|")[0]) if len(lines) >= 1 else -1
    s_sz = int(lines[1].split("|")[0]) if len(lines) >= 2 else -2
    b_mt = lines[0].split("|")[1] if len(lines) >= 1 else ""
    s_mt = lines[1].split("|")[1] if len(lines) >= 2 else ""
    add("backup_size_equals_source_bytes", "stat -c '%s|%y' نسخة ; مصدر", r_sz,
        b_sz == s_sz,
        "حجم النسخة = حجم المصدر بالبايت (8040448=8040448)", P,
        note="backup=" + str(b_sz) + " mtime=" + b_mt + " · source=" + str(s_sz) + " mtime=" + s_mt
             + (" · المصدر لم يُعدَّل بعد النسخة (mtime المصدر أقدم)" if s_mt < b_mt else ""))
    add("backup_size_8040448", "stat -c '%s' " + BK_DB, r_sz,
        b_sz == 8040448, "8,040,448 بايت كما ادُّعي", P)

    r_own = run(ssh, "stat -c '%U %G %a' " + BK_DB)
    add("backup_owner_opc_644", "stat -c '%U %G %a' " + BK_DB, r_own,
        r_own["out"] == "opc opc 644", "opc opc 644 (أنشئها المستخدم opc كما في الخدمة)", P)

    r_log = run(ssh, "cat /opt/aes-backups/logs/backup-20261027.log")
    add("backup_log_integrity_ok", "cat /opt/aes-backups/logs/backup-20261027.log", r_log,
        ("integrity_check: ok" in r_log["out"]) and ("size=8040448" in r_log["out"])
        and ("=== aes-backup started" in r_log["out"]),
        "في السجل: integrity_check: ok + size=8040448 + ترويسة تشغيل", P)

    # ============ هـ) فحصي الخارجي المستقل للنسخة (الاستثناء أ) ============
    P = "drill(أ)"
    r_cp = run(ssh, "cp " + BK_DB + " " + DRILL_TMP + " && stat -c '%s' " + DRILL_TMP)
    add("drill_copy_to_tmp", "cp نسخة → /tmp/w1t04-audit-drill.db + stat", r_cp,
        r_cp["out"] == str(b_sz) and b_sz == 8040448,
        "نسخة طبق الأصل في /tmp بحجم 8040448 (لا مساس بالأصل)", P)

    drill_py = (
        "/usr/bin/python3 - <<'PYEOF'\n"
        "import sqlite3, os, json\n"
        "p = '" + DRILL_TMP + "'\n"
        "con = sqlite3.connect('file:' + p + '?mode=ro', uri=True)\n"
        "res = {}\n"
        "res['integrity'] = con.execute('PRAGMA integrity_check').fetchone()[0]\n"
        "tabs = [r[0] for r in con.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\")]\n"
        "res['tables_all'] = tabs\n"
        "res['tables_all_count'] = len(tabs)\n"
        "res['tables_user_count'] = len([t for t in tabs if not t.startswith('sqlite_')])\n"
        "for t in ('projects', 'conversations', 'messages'):\n"
        "    res['count_' + t] = con.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]\n"
        "con.close()\n"
        "res['size'] = os.path.getsize(p)\n"
        "print('DRILLJSON:' + json.dumps(res))\n"
        "PYEOF"
    )
    r_dr = run(ssh, drill_py)
    dj = None
    m = re.search(r"DRILLJSON:(\{.*\})", r_dr["out"])
    if m:
        try:
            dj = json.loads(m.group(1))
        except Exception as e:
            notes.append("drill JSON parse error: " + repr(e))
    add("drill_integrity_check_ok", "/usr/bin/python3 (mode=ro) PRAGMA integrity_check", r_dr,
        dj is not None and dj.get("integrity") == "ok", "integrity_check = ok", P,
        note="فحصي أنا على نسخة /tmp — مستقل عن فحص السكربت الداخلي")
    add("drill_tables_count_24", "sqlite_master type='table'", r_dr,
        dj is not None and dj.get("tables_user_count") == 24, "24 جدولاً (كما في RESTORE-DRILL.md)", P,
        note="tables_all_count=" + str(dj.get("tables_all_count")) if dj else "no json")
    add("drill_projects_count_2", "COUNT(*) projects", r_dr,
        dj is not None and dj.get("count_projects") == 2, "projects = 2", P)
    add("drill_conversations_count_13", "COUNT(*) conversations", r_dr,
        dj is not None and dj.get("count_conversations") == 13, "conversations = 13", P)
    add("drill_messages_count_91", "COUNT(*) messages", r_dr,
        dj is not None and dj.get("count_messages") == 91, "messages = 91", P)
    add("drill_size_8040448", "os.path.getsize(/tmp/w1t04-audit-drill.db)", r_dr,
        dj is not None and dj.get("size") == 8040448, "8,040,448 بايت", P)

    r_rm = run(ssh, "rm -f " + DRILL_TMP + " && test ! -e " + DRILL_TMP + " && echo DRILL_CLEANED")
    add("drill_tmp_cleanup", "rm -f /tmp/w1t04-audit-drill.db + test ! -e", r_rm,
        r_rm["out"] == "DRILL_CLEANED", "ملف التمرين حُذف من /tmp", P)

    # ============ و) اختبار الطُعم الخاص بي (الاستثناء ب) ============
    P = "retention(ب)"
    r_before = run(ssh, "ls -1 /opt/aes-backups/db/")
    before_set = set(x for x in r_before["out"].splitlines() if x.strip())
    r_mk = run(ssh, "touch " + DECOY + " && touch -d '2020-10-10 03:30:00' " + DECOY
               + " && stat -c '%y %s' " + DECOY)
    add("decoy_created_old_mtime", "touch + touch -d '2020-10-10 03:30:00' + stat", r_mk,
        "2020-10-10" in r_mk["out"], "طُعمي nightly-20201010.db بتاريخ mtime قديم (2020-10-10)", P,
        note="طُعم خاص بي — ملف جديد من إنشائي، لا يمس أي ملف للمنفذ")

    r_find = run(ssh, FIND_LITERAL)
    add("retention_deletes_old_decoy_only", FIND_LITERAL, r_find,
        r_find["out"] == DECOY, "أمر الحذف نفسه يطبع ويحذف الطُعم القديم وحده", P)

    r_gone = run(ssh, "test ! -e " + DECOY + " && echo DECOY_GONE ; test -e " + BK_DB
                 + " && echo TODAY_KEPT ; ls -1 /opt/aes-backups/db/")
    after_set = set(x for x in r_gone["out"].splitlines() if x.strip() and not x.endswith("_GONE") and not x.endswith("_KEPT"))
    add("decoy_deleted_after_find", "test ! -e nightly-20201010.db", r_gone,
        "DECOY_GONE" in r_gone["out"], "الطُعم القديم حُذف", P)
    add("today_backup_kept_after_find", "test -e nightly-20261027.db", r_gone,
        "TODAY_KEPT" in r_gone["out"], "نسخة اليوم nightly-20261027.db بقيت", P)
    add("db_dir_final_state_clean", "ls -1 /opt/aes-backups/db/ (بعد الاختبار)", r_gone,
        after_set == before_set,
        "الدليل عاد لحالته قبل الطُعم تماماً (لا حذف/إضافة غير متوقعة)", P,
        note="before=" + json.dumps(sorted(before_set)) + " after=" + json.dumps(sorted(after_set)))

    # ============ ز) صحة الإنتاج R6 — قراءة فقط ============
    P = "health-R6"
    r_h = run(ssh, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health")
    add("health_loopback_200", "curl -w '%{http_code}' http://127.0.0.1:8010/health", r_h,
        r_h["out"] == "200", "/health = 200 من loopback", P)

    r_svcs = run(ssh, "for s in agentic nginx firewalld aes-backup.timer; do printf '%s=' $s; "
                      "systemctl is-active $s; done")
    add("services_all_active", "is-active agentic nginx firewalld aes-backup.timer", r_svcs,
        all(("=" + "active") in r_svcs["out"] for _ in [1])
        and r_svcs["out"].count("=active") == 4,
        "agentic=nginx=firewalld=aes-backup.timer=active", P)

    r_jerr = run(ssh, "sudo -n journalctl -u agentic --since '-30 min' -p err --no-pager")
    add("journal_agentic_no_errors_30min", "sudo -n journalctl -u agentic --since '-30 min' -p err", r_jerr,
        r_jerr["out"] in ("", "-- No entries --"), "صفر أسطر أخطاء (err+) للخدمة agentic آخر 30 دقيقة", P)

    r_jb = run(ssh, "sudo -n journalctl -u aes-backup.service --no-pager -n 100")
    add("journal_backup_success_finished", "sudo -n journalctl -u aes-backup.service -n 100", r_jb,
        ("Finished AES nightly SQLite backup" in r_jb["out"])
        and ("Deactivated successfully" in r_jb["out"]),
        "التشغيل اليدوي الناجح موثق في journal (Finished + Deactivated successfully @ 04:48:53)", P)
    add("journal_backup_203_incident_documented", "sudo -n journalctl -u aes-backup.service -n 100", r_jb,
        ("status=203/EXEC" in r_jb["out"]) and ("Permission denied" in r_jb["out"])
        and ("Failed to start AES nightly SQLite backup" in r_jb["out"]),
        "حادث المحاولة الأولى 203/EXEC ظاهر في journal (04:46:42) ثم نجاح لاحق — كلاهما موثق", P,
        note="الحادث كما وُثّق في البطاقة حقيقي: Failed at step EXEC ... Permission denied → status=203/EXEC")

    # ============ ح) venv السكربت يعمل من opc (فحص صرامة إضافي) ============
    P = "extra"
    r_v = run(ssh, "test -x /opt/agentic-engineering-system/.venv/bin/python && "
                   "/opt/agentic-engineering-system/.venv/bin/python --version")
    add("venv_python_runs_as_opc", "test -x venv/bin/python && venv/bin/python --version", r_v,
        "Python 3." in r_v["out"], "بايثون venv التطبيق قابل للتنفيذ من opc ويعمل (" + r_v["out"] + ")", P)

    ssh.close()

    # ============ ط) سلامة أدلة المنفذ المحلية (مقارنة بقياساتي أنا) ============
    P = "evidence"
    with open(EVID + "/20261027-deploy.json", encoding="utf-8") as f:
        dep = json.load(f)
    gates = dep.get("gates", {})
    n_ok = sum(1 for g in gates.values() if g.get("ok") is True)
    add("deploy_json_18_gates_all_ok", "local: 20261027-deploy.json", {"rc": 0, "out": "gates=" + str(len(gates)) + " ok=" + str(n_ok) + " verdict=" + str(dep.get("verdict")), "err": ""},
        len(gates) == 18 and n_ok == 18 and dep.get("verdict") == "PASS",
        "18 بوابة كلها ok=true وverdict=PASS", P)

    with open(EVID + "/20261027-preflight.json", encoding="utf-8") as f:
        pre = json.load(f)
    add("preflight_json_consistent", "local: 20261027-preflight.json", {"rc": 0, "out": "db_files=" + pre.get("db_files", "")[:40] + " health=" + pre.get("health_before", ""), "err": ""},
        ("8040448" in pre.get("db_files", "")) and (pre.get("health_before") == "200")
        and ("could not be found" in pre.get("aes_backup_units", ""))
        and ("READ-ONLY" in pre.get("_meta", {}).get("mode", "")),
        "preflight: قاعدة 8040448 · /health 200 · الوحدتان لم تكونا موجودتين · وضع قراءة فقط", P)

    with open(EVID + "/RESTORE-DRILL.md", encoding="utf-8") as f:
        md = f.read()
    my = dj or {}
    add("restore_drill_md_matches_my_measurements", "local: RESTORE-DRILL.md × قياساتي", {"rc": 0, "out": "md rows vs my drill: tables/2/13/91/8040448", "err": ""},
        ("24 | 24" in md) and ("| 2 | 2 |" in md) and ("| 13 | 13 |" in md) and ("| 91 | 91 |" in md)
        and ("8,040,448" in md) and ("integrity_check" in md)
        and my.get("tables_user_count") == 24 and my.get("count_projects") == 2
        and my.get("count_conversations") == 13 and my.get("count_messages") == 91
        and my.get("size") == 8040448,
        "أرقام RESTORE-DRILL.md (24/2/13/91/8040448) = قياساتي المستقلة نفسها", P)

    steps = dep.get("steps", {})
    add("deploy_json_numbers_match_my_measurements", "local: 20261027-deploy.json × قياساتي", {"rc": 0, "out": "rowcounts=" + steps.get("rowcounts_before", "") + " · integrity=" + steps.get("integrity_external", "").replace("\n", "/") + " · db_stat=" + steps.get("db_stat", ""), "err": ""},
        (steps.get("rowcounts_before") == "projects=2;conversations=13;messages=91")
        and (steps.get("integrity_external") == "ok\ntables: 24")
        and (steps.get("db_stat") == "opc opc 644 8040448")
        and ("nightly-20261027.db" in steps.get("backup_listing", ""))
        and ("8040448" in steps.get("backup_listing", ""))
        and my.get("count_projects") == 2 and my.get("count_conversations") == 13
        and my.get("count_messages") == 91 and my.get("tables_user_count") == 24,
        "أرقام ملف النشر (2/13/91 · ok/24 · opc opc 644 8040448) متسقة مع قياساتي", P)

    # ============ ملاحظات غير حاجبة ============
    if dj:
        notes.append("عدد الجداول: user=" + str(dj.get("tables_user_count"))
                     + " · all(incl sqlite_*)=" + str(dj.get("tables_all_count"))
                     + " — بطاقة TRACKER ذكرت «25 جدولاً» في سجل التنفيذ بينما preflight نفسه يسرد 24 اسماً؛"
                       " قياسي يحسم: " + ("25 كلها (24 مستخدم + sqlite_sequence) — الرقمان متصالحان"
                                          if dj.get("tables_all_count") == 25 else
                                          "24 فقط — رقم 25 في البطاقة سهو توثيقي غير حاجب"))
    notes.append("المؤقت لم يُطلق تلقائياً بعد (LAST='-'): أُنشئ اليوم 04:46 بعد مرور 03:30 — أول تشغيل"
                 " تلقائي غير مراقب غداً 2026-10-28 03:30 GMT؛ يوصى الأب/المالك بالتحقق صباحاً من وجود"
                 " nightly-20261028.db وسجلها (متابعة لاحقة، غير حاجبة — التشغيل عبر الوحدة نفسها مثبت RC=0 يدوياً)")
    notes.append("سكربت النسخ مراجَع سطراً سطراً (49 سطراً): لا systemctl/sudo، rm فقط على $DEST الجزئي داخل"
                 " /opt/aes-backups، لا كتابة على المصدر، mkdir -p للمجلدين، الاحتفاظ find -mtime +7 -delete")
    notes.append("md5 السكربت: " + r_md5["out"].split()[0] + " (49 سطراً / 1424 بايت) — للتوثيق")

    total = len(checks)
    passed = sum(1 for c in checks if c["passed"])
    failed = total - passed
    verdict = "PASS" if failed == 0 else "FAIL"

    out = {
        "audit": "W1-T04-AUDIT",
        "auditor": "وكيل تدقيق مستقل (general-purpose) — W1-T04-AUDIT",
        "date": "2026-10-27",
        "server_meta": meta["out"],
        "mode": "SSH قراءة فقط (sudo -n للقراءات) + استثناءان مسموحان فقط: "
                "(أ) تمرين استرجاع خاص في /tmp/w1t04-audit-drill.db ثم حذفه؛ "
                "(ب) طُعم احتفاظ خاص nightly-20201010.db بتاريخ 2020-10-10 عبر أمر الحذف نفسه ثم التحقق من نظافة الحالة",
        "script_md5": r_md5["out"].split()[0] if r_md5["out"] else "",
        "script_full_content": sc,
        "drill_measurements": dj,
        "size_backup_vs_source": {"backup": b_sz, "source": s_sz, "backup_mtime": b_mt, "source_mtime": s_mt},
        "checks": checks,
        "summary": {"total": total, "passed": passed, "failed": failed},
        "notes_non_blocking": notes,
        "verdict": verdict,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 62)
    print("TOTAL:", total, "· PASSED:", passed, "· FAILED:", failed)
    for c in checks:
        if not c["passed"]:
            print("  FAIL:", c["name"], "→", c["expected"])
    print("VERDICT:", verdict)
    print("written:", OUT)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
