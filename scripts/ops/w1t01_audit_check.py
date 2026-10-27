#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W1-T01-AUDIT — تدقيق مستقل لمهمة W1-T01 (تجميد agentic-vis 8011 + aes-shim 8099 مع الأرشفة).
الوكيل: وكيل تدقيق مستقل (general-purpose) · التاريخ: 2026-10-27
الوضع: SSH قراءة فقط مطلقاً (لا systemctl start/stop، لا mv/rm، لا أي كتابة على الخادم)
       + مراجعة سلامة الأدلة المحلية. التقييم بأسطر المُخرجات الفعلية لا رموز الخروج.
المخرجات: /home/z/my-project/download/aes-remediation/W1-T01/audit_independent.json
"""
import json
import re
import sys

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY = "/tmp/oracle_key"
EVID = "/home/z/my-project/download/aes-remediation/W1-T01"
OUT = EVID + "/audit_independent.json"
TRACKER = "/home/z/my-project/TRACKER.md"
WORKLOG = "/home/z/my-project/worklog.md"
STAMP = "20261027"


def run(ssh, cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    return {"rc": rc, "out": out, "err": err}


def main():
    ssh_checks = []

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, key_filename=KEY,
                 look_for_keys=False, allow_agent=False, timeout=25)

    def add(name, cmd, res, passed, expected, note=""):
        ssh_checks.append({
            "name": name, "cmd": cmd, "rc": res["rc"],
            "out": res["out"][:4000], "err": res["err"][:600],
            "expected": expected, "passed": bool(passed), "note": note,
        })
        print(("PASS " if passed else "FAIL ") + name)

    # ===== قراءات تعريفية (توثيق فقط، ليست فحوصاً) =====
    meta_srv = run(ssh, "date -u '+%Y-%m-%d %H:%M:%S UTC' && hostname")
    print("server:", meta_srv["out"].replace("\n", " · "))

    # ================= أ) صحة التغييرات المزعومة =================

    # --- حالات الخدمات الأربع (أمر واحد يُفكك إلى 4 فحوص) ---
    cmd_states = ("for s in agentic agentic-vis aes-shim nginx; do "
                  "printf '%s active=' $s; systemctl is-active $s 2>&1; "
                  "printf ' enabled='; systemctl is-enabled $s 2>&1; done")
    r = run(ssh, cmd_states)
    svc, cur = {}, None
    for line in r["out"].splitlines():
        m = re.match(r"^(.*?)\s*active=(\S+)\s*$", line.strip()) if " active=" in line else None
        if m:
            cur = m.group(1).strip()
            svc[cur] = {"active": m.group(2)}
            continue
        m2 = re.match(r"^enabled=(\S+)\s*$", line.strip())
        if m2 and cur:
            svc[cur]["enabled"] = m2.group(1)
    states_raw = r["out"]
    add("agentic_active_enabled", cmd_states, r,
        svc.get("agentic") == {"active": "active", "enabled": "enabled"},
        "agentic: active + enabled (الإنتاج لم يتأثر)",
        note="parsed: " + json.dumps(svc, ensure_ascii=False))
    add("agentic_vis_inactive_disabled", cmd_states, r,
        svc.get("agentic-vis") == {"active": "inactive", "enabled": "disabled"},
        "agentic-vis: inactive + disabled (مجمدة)")
    add("aes_shim_inactive_disabled", cmd_states, r,
        svc.get("aes-shim") == {"active": "inactive", "enabled": "disabled"},
        "aes-shim: inactive + disabled (مجمدة)")
    add("nginx_active_enabled", cmd_states, r,
        svc.get("nginx") == {"active": "active", "enabled": "enabled"},
        "nginx: active + enabled (الجدار سليم)")

    # --- المنافذ: 8010 وحده مستمع، ولا 8011/8099 مستمعين ولا اتصالات ---
    cmd_l = "sudo -n ss -tln | grep -E ':8010|:8011|:8099'"
    r = run(ssh, cmd_l)
    add("port_8010_listening", cmd_l, r,
        (":8010" in r["out"]) and r["err"] == "",
        "8010 (uvicorn الإنتاج) وحده المستمع ضمن 8010/8011/8099")

    cmd_nl = "sudo -n ss -tln | grep -E ':8011|:8099'"
    r = run(ssh, cmd_nl)
    add("no_listener_8011_8099", cmd_nl, r,
        r["out"] == "" and r["err"] == "",
        "لا مستمع على 8011/8099")

    cmd_nc = "sudo -n ss -tn | grep -E ':8011|:8099'"
    r = run(ssh, cmd_nc)
    add("no_connections_8011_8099", cmd_nc, r,
        r["out"] == "" and r["err"] == "",
        "لا اتصالات قائمة على 8011/8099")

    sudo_ok = any(":8010" in c["out"] for c in ssh_checks if c["name"] == "port_8010_listening")

    # --- زوال الدليلين الأصليين ---
    cmd_orig = "ls -d /opt/aes-vis /opt/aes-shim 2>&1"
    r = run(ssh, cmd_orig)
    add("origins_removed", cmd_orig, r,
        r["out"].count("No such file or directory") == 2
        and "/opt/aes-vis" in r["out"] and "/opt/aes-shim" in r["out"],
        "الدليلان الأصليان زالا من /opt (الرسالة: No such file × 2)")

    # --- الأرشفة ---
    cmd_arch = "sudo -n ls /opt/aes-archive/ && sudo -n du -sh /opt/aes-archive/*"
    r = run(ssh, cmd_arch, timeout=90)
    m_vis = re.search(r"([0-9.]+)\s*([KMGT]?)\s*/opt/aes-archive/aes-vis-frozen-" + STAMP, r["out"])
    m_shim = re.search(r"([0-9.]+)\s*([KMGT]?)\s*/opt/aes-archive/aes-shim-frozen-" + STAMP, r["out"])
    vis_sz = (m_vis.group(1) + m_vis.group(2)) if m_vis else "غير موجود"
    shim_sz = (m_shim.group(1) + m_shim.group(2)) if m_shim else "غير موجود"
    vis_ok = bool(m_vis) and (m_shim is not None) and (
        m_vis.group(2) == "G" or (m_vis.group(2) == "M" and float(m_vis.group(1)) >= 300))
    shim_ok = bool(m_shim) and (m_shim.group(2) == "K" or (m_shim.group(2) == "M" and float(m_shim.group(1)) <= 1))
    add("archive_vis_frozen_present", cmd_arch, r, vis_ok,
        "aes-vis-frozen-20261027 في /opt/aes-archive/ (نحو 346M)",
        note="الحجم المقاس: " + vis_sz)
    add("archive_shim_frozen_present", cmd_arch, r, shim_ok,
        "aes-shim-frozen-20261027 في /opt/aes-archive/ (نحو 44K)",
        note="الحجم المقاس: " + shim_sz)

    # --- بقاء ملفي الوحدتين للتراجع ---
    cmd_units = "ls /etc/systemd/system/agentic-vis.service /etc/systemd/system/aes-shim.service"
    r = run(ssh, cmd_units)
    add("unit_files_kept_for_rollback", cmd_units, r,
        r["rc"] == 0 and "agentic-vis.service" in r["out"] and "aes-shim.service" in r["out"],
        "ملفا الوحدتين موجودان في /etc/systemd/system/ (للتراجع)")

    # --- /health للإنتاج: JSON سليم + كود 200 ---
    cmd_health = "curl -s --max-time 8 http://127.0.0.1:8010/health"
    r = run(ssh, cmd_health, timeout=20)
    try:
        hj = json.loads(r["out"])
        h_ok = isinstance(hj, dict) and hj.get("status") == "ok"
    except Exception:
        h_ok = False
    add("health_json_status_ok", cmd_health, r, h_ok,
        'JSON صالح يحوي "status":"ok"')

    cmd_hc = "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health"
    r = run(ssh, cmd_hc, timeout=20)
    add("health_http_200", cmd_hc, r, r["out"].strip() == "200",
        "كود HTTP = 200 مباشرة على 8010")

    # --- جدار nginx Basic Auth: 401 من loopback بلا اعتماديات ---
    cmd_nginx = "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1/"
    r = run(ssh, cmd_nginx, timeout=20)
    add("nginx_basic_auth_401", cmd_nginx, r, r["out"].strip() == "401",
        "401 على المنفذ 80 من loopback بلا بيانات اعتماد (الجدار سليم)")

    # --- لا عمليات فيز/شِم حية ---
    cmd_ps = "ps aux | grep -E 'aes-vis|aes_shim|aes_local_shim' | grep -v grep"
    r = run(ssh, cmd_ps)
    add("no_frozen_processes", cmd_ps, r,
        r["out"] == "" and r["err"] == "",
        "لا أي عملية aes-vis/aes_shim/aes_local_shim حية")

    # --- الإنتاج git لم يُمسّ ---
    cmd_git = "cd /opt/agentic-engineering-system && git rev-parse --short HEAD"
    r = run(ssh, cmd_git)
    add("production_git_0f2d9c6", cmd_git, r,
        r["out"].strip().startswith("0f2d9c6"),
        "HEAD في /opt/agentic-engineering-system = 0f2d9c6 (لم يُمسّ)")

    # --- لا أخطاء جديدة ذات معنى في journal agentic (آخر ساعتان تغطي التجميد) ---
    cmd_jcnt = ("sudo -n journalctl -u agentic --since '-2h' --no-pager | "
                "grep -icE 'error|traceback'")
    rc_ = run(ssh, cmd_jcnt, timeout=120)
    cmd_jlines = ("sudo -n journalctl -u agentic --since '-2h' --no-pager | "
                  "grep -iE 'error|traceback' | head -40")
    rl_ = run(ssh, cmd_jlines, timeout=120)
    try:
        cnt = int(rc_["out"].strip())
    except Exception:
        cnt = None
    lines = [l for l in rl_["out"].splitlines() if l.strip()]
    meaningful = [l for l in lines if " 200 OK" not in l]
    if cnt == 0:
        j_ok, j_note = True, "صفر أسطر error/traceback في آخر ساعتين"
    elif cnt is not None and cnt <= 40 and len(meaningful) == 0:
        j_ok = True
        j_note = ("العدد=" + str(cnt) + " لكن كل الأسطر المطابقة أسطر وصول 200 OK حميدة "
                  "(لا أخطاء ذات معنى)")
    else:
        j_ok = False
        j_note = "أسطر تحتوي error/traceback تستوجب مراجعة (العدد=" + str(cnt) + ")"
    ssh_checks.append({
        "name": "journal_no_meaningful_errors", "cmd": cmd_jcnt,
        "rc": rc_["rc"],
        "out": ("count=" + str(cnt) + "\n--- matching lines (head-40) ---\n"
                + rl_["out"])[:4000],
        "err": (rc_["err"] + " " + rl_["err"])[:600],
        "expected": "لا أخطاء جديدة ذات معنى في journal خدمة agentic (طلبات 200 OK ليست أخطاء)",
        "passed": bool(j_ok), "note": j_note,
    })
    print(("PASS " if j_ok else "FAIL ") + "journal_no_meaningful_errors")

    # ================= ب) إعادة فحص الأمان قبل التنفيذ (مستقلاً) =================

    cmd_env = ("sudo -n grep -rnE ':8099|:8011' "
               "/opt/agentic-engineering-system/.env* 2>/dev/null | head -5")
    r = run(ssh, cmd_env)
    env_pass = r["out"] == ""
    env_note = "لا مرجع للشِم/الفيس في ملفات .env"
    if env_pass:  # تحقق متقن: نسخة بلا كتم stderr لكشف أي فشل sudo/قراءة
        r2 = run(ssh, "sudo -n grep -rnE ':8099|:8011' /opt/agentic-engineering-system/.env* 2>&1 | head -5")
        env_pass = r2["out"] == "" or all(
            l.strip() in ("", "EXIT_0") or "No such file" in l for l in r2["out"].splitlines())
        if not env_pass:
            env_note = "أُبلغ عن فارغ لكن النسخة غير المكتمة أظهرت: " + r2["out"][:200]
    add("env_no_8011_8099_refs", cmd_env, r, env_pass and sudo_ok,
        "لا مرجع :8099/:8011 في .env* للإنتاج", note=env_note)

    cmd_src = ("grep -rnE ':8099|:8011' "
               "/opt/agentic-engineering-system/src/ 2>/dev/null | head -5")
    r = run(ssh, cmd_src)
    src_pass = r["out"] == ""
    src_note = "لا مرجع :8099/:8011 في src/ للإنتاج"
    if src_pass:  # نسخة بلا كتم stderr للتحقق من قابلية القراءة
        r2 = run(ssh, "grep -rnE ':8099|:8011' /opt/agentic-engineering-system/src/ 2>&1 | head -5; echo RC_EOF")
        bad = [l for l in r2["out"].splitlines()
               if l.strip() and l.strip() != "RC_EOF"
               and ("ermission denied" in l or "No such file" in l)]
        if bad:
            src_pass = False
            src_note = "خطأ قراءة: " + bad[0][:200]
    add("src_no_8011_8099_refs", cmd_src, r, src_pass,
        "لا مرجع :8099/:8011 في src/ (أو توثيق ما يوجد)", note=src_note)

    cmd_db = ("sudo -n strings /opt/agentic-engineering-system/runtime/agent_hub_v2.db | "
              "grep -cE '127.0.0.1:8099|localhost:8099'")
    r = run(ssh, cmd_db, timeout=120)
    add("db_no_shim_refs", cmd_db, r,
        r["out"].strip() == "0" and r["err"] == "" and sudo_ok,
        "عدد إشارات 127.0.0.1:8099/localhost:8099 في قاعدة البيانات = 0")

    ssh.close()

    # ================= ج) سلامة الأدلة المحلية =================
    local_checks = []

    with open(EVID + "/results_postverify.json", encoding="utf-8") as f:
        pv = json.load(f)
    verdict = pv.get("verdict", {})
    pv_checks = verdict.get("checks", {})
    c1 = (verdict.get("passed") is True and len(pv_checks) == 13
          and all(v is True for v in pv_checks.values()))
    local_checks.append({
        "name": "postverify_verdict_13_checks",
        "source": "results_postverify.json",
        "expected": "verdict.passed=true مع 13 فحصاً كلها true",
        "found": {"passed": verdict.get("passed"), "checks_count": len(pv_checks),
                  "all_true": all(v is True for v in pv_checks.values()) if pv_checks else False,
                  "check_names": list(pv_checks.keys())},
        "passed": bool(c1),
    })
    print(("PASS " if c1 else "FAIL ") + "postverify_verdict_13_checks")

    with open(TRACKER, encoding="utf-8") as f:
        tracker = f.read()
    mk2 = ["الجولة 1", "الجولة 2", "الجولة 3", "إنذار كاذب",
           "مهلة bash المحلية", "13/13 فحصًا ناجحًا"]
    c2 = all(m in tracker for m in mk2)
    local_checks.append({
        "name": "tracker_three_rounds_honest",
        "source": "TRACKER.md (بطاقة W1-T01 — سجل التنفيذ)",
        "expected": "توثيق الجولات الثلاث بشفافية: الإيقاف الكاذب للجولة 1 + مهلة الجولة 2 + 13/13 للجولة 3",
        "found": {m: (m in tracker) for m in mk2},
        "passed": bool(c2),
    })
    print(("PASS " if c2 else "FAIL ") + "tracker_three_rounds_honest")

    with open(WORKLOG, encoding="utf-8") as f:
        wl = f.read()
    i = wl.find("Task ID: W1-T01\n")
    w1 = wl[i:] if i >= 0 else ""
    mk3 = ["الجولة 1", "الجولة 2", "الجولة 3", "إنذار كاذب", "مهلة bash المحلية"]
    c3 = (i >= 0) and all(m in w1 for m in mk3)
    local_checks.append({
        "name": "worklog_w1t01_documented",
        "source": "worklog.md (إدخال W1-T01)",
        "expected": "إدخال W1-T01 موجود ويوثق الجولات الثلاث (بما فيها الإيقاف الكاذب والمهلة)",
        "found": {"entry_found": i >= 0,
                  "markers": {m: (m in w1) for m in mk3} if i >= 0 else {}},
        "passed": bool(c3),
    })
    print(("PASS " if c3 else "FAIL ") + "worklog_w1t01_documented")

    # ================= الخلاصة =================
    ssh_passed = sum(1 for c in ssh_checks if c["passed"])
    local_passed = sum(1 for c in local_checks if c["passed"])
    final = "PASS" if (ssh_passed == len(ssh_checks)
                       and local_passed == len(local_checks)) else "FAIL"

    doc = {
        "audit": {
            "id": "W1-T01-AUDIT",
            "date": "2026-10-27",
            "auditor": "وكيل تدقيق مستقل (general-purpose)",
            "mode": "SSH قراءة فقط مطلقاً + مراجعة أدلة محلية",
            "ssh_target": "opc@92.5.14.150 (مفتاح /tmp/oracle_key)",
            "server_time_host": meta_srv["out"],
            "evaluation_method": "أسطر المُخرجات الفعلية (match lines) لا رموز الخروج",
            "readonly_guarantee": "لا أوامر حالة-تغيير على الإطلاق (فقط قراءة/فحص/GET)",
        },
        "states_raw": states_raw,
        "ssh_checks": ssh_checks,
        "local_checks": local_checks,
        "summary": {
            "ssh_total": len(ssh_checks), "ssh_passed": ssh_passed,
            "local_total": len(local_checks), "local_passed": local_passed,
            "verdict": final,
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print("\n===== SUMMARY =====")
    print("SSH checks: %d/%d passed" % (ssh_passed, len(ssh_checks)))
    print("Local evidence checks: %d/%d passed" % (local_passed, len(local_checks)))
    print("VERDICT:", final)
    print("Evidence:", OUT)
    sys.exit(0 if final == "PASS" else 1)


if __name__ == "__main__":
    main()
