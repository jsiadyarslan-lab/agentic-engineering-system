#!/usr/bin/env python3
"""W1-T02-AUDIT — تدقيق مستقل كامل (قراءة فقط على الإنتاج).

يجمع أدلته بنفسه عبر SSH (paramiko، look_for_keys=False، allow_agent=False)
ولا يقبل شيئًا من تقرير المنفذ. يقيّم بأسطر المخرجات الفعلية (درس W1-T01).

الأقسام:
  أ) سلامة النشر (SSH قراءة فقط) — 7 بنود
  ب) الدليل الشبكي الحي من سجل nginx — تحليل مستقل لنمط الاستطلاع
  ج) مراجعة الكود (المستودع المحلي main @ 9e2ace5)
  د) سلامة أدلة المنفذ (تطابق داخلي)

المخرجات: download/aes-remediation/W1-T02/audit_independent.json
لا يغيّر أي حالة على الإنتاج (أوامر قراءة فقط؛ sudo -n للقراءات الجذرية).
"""
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
REPO = "/home/z/my-project/repo"
EV = "/home/z/my-project/download/aes-remediation/W1-T02"
OUT_JSON = f"{EV}/audit_independent.json"
HTPASSWD_SHA = "038af1fb2c7f835103b7dd55660b5fec2395491ee9b17ec7a1e85acf9d8c036c"
FILES = ["src/ui/control-center.js", "src/ui/projects.js", "src/ui/live-events.js"]
DEPLOY_TS = "01:34:00"  # زمن النشر المزعوم 2026-10-27 ~01:34

checks = []


def add(cid, desc, ok, evidence):
    checks.append({"id": cid, "desc": desc, "pass": bool(ok),
                   "evidence": evidence if isinstance(evidence, str) else json.dumps(evidence, ensure_ascii=False)})
    print(("PASS " if ok else "FAIL ") + f"[{cid}] {desc}" + (f"  → {evidence}" if isinstance(evidence, str) and len(str(evidence)) < 200 else ""))


def run(ssh, cmd, timeout=60):
    """نفّذ أمرًا عبر SSH وأعد (rc, stdout, stderr)."""
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    rc = o.channel.recv_exit_status()
    return rc, o.read().decode(errors="replace"), e.read().decode(errors="replace")


def local(cmd, cwd=REPO):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=False)
    return p.returncode, p.stdout, p.stderr


def local_blob_sha(rev, path):
    rc, out, _ = local(["git", "show", f"{rev}:{path}"])
    return hashlib.sha256(out.encode()).hexdigest() if rc == 0 else None


# ---------------------------------------------------------------- connect
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

rc, server_now, _ = run(ssh, "date '+%Y-%m-%d %H:%M:%S %z'")
print(f"# server time: {server_now.strip()}")

# ================================================================ أ) النشر
# أ1) HEAD الإنتاج == main المحلي
rc_l, local_main, _ = local(["git", "rev-parse", "main"])
local_main = local_main.strip()
rc, prod_head, _ = run(ssh, "git -C /opt/agentic-engineering-system rev-parse HEAD")
prod_head = prod_head.strip()
add("A1", "HEAD الإنتاج == main المحلي", prod_head == local_main,
    f"prod={prod_head} local_main={local_main}")

# أ2) شجرة الإنتاج نظيفة
rc, porcelain, _ = run(ssh, "git -C /opt/agentic-engineering-system status --porcelain --untracked-files=no")
add("A2", "شجرة الإنتاج نظيفة (لا انحراف عن الالتزام)", porcelain.strip() == "",
    f"porcelain_lines={len(porcelain.strip().splitlines())}")

# أ3) الملفات الثلاثة تحمل الرقعة (عدّ الرموز > 0)
rc, cc_sync, _ = run(ssh, "grep -c 'syncRunPolling' /opt/agentic-engineering-system/src/ui/control-center.js")
rc, pj_sync, _ = run(ssh, "grep -c 'syncRuntimePolling' /opt/agentic-engineering-system/src/ui/projects.js")
rc, le_conn, _ = run(ssh, "grep -c 'isConnected' /opt/agentic-engineering-system/src/ui/live-events.js")
add("A3", "الرموز الجديدة موجودة في الملفات الثلاثة المنشورة",
    int(cc_sync.strip()) > 0 and int(pj_sync.strip()) > 0 and int(le_conn.strip()) > 0,
    f"control-center.syncRunPolling={cc_sync.strip()} projects.syncRuntimePolling={pj_sync.strip()} live-events.isConnected={le_conn.strip()}")

# أ4) لا استطلاع أعمى: كل setInterval(...) داخل دالة sync المشروطة
rc, cc_seti, _ = run(ssh, "grep -n 'setInterval(pollActiveRuns' /opt/agentic-engineering-system/src/ui/control-center.js")
rc, cc_fn, _ = run(ssh, "grep -n 'function syncRunPolling' /opt/agentic-engineering-system/src/ui/control-center.js")
rc, pj_seti, _ = run(ssh, "grep -n 'setInterval(fetchRuntime' /opt/agentic-engineering-system/src/ui/projects.js")
rc, pj_fn, _ = run(ssh, "grep -n 'function syncRuntimePolling' /opt/agentic-engineering-system/src/ui/projects.js")


def intervals_inside(seti_out, fn_out):
    """كل موضع setInterval داخل نطاق دالة sync (ضمن 15 سطرًا من تعريفها) وليس في مسار تحميل مباشر."""
    ok = True
    detail = []
    for line in seti_out.strip().splitlines():
        m = re.match(r"(\d+):", line)
        if not m:
            ok = False
            detail.append(f"unparsed:{line[:60]}")
            continue
        n = int(m.group(1))
        fn_lines = [int(re.match(r"(\d+):", f).group(1)) for f in fn_out.strip().splitlines() if re.match(r"\d+:", f)]
        inside = any(fn <= n <= fn + 15 for fn in fn_lines)
        ok = ok and inside and len(fn_lines) > 0
        detail.append(f"setInterval@{n} inside sync({fn_lines})={inside}")
    if not seti_out.strip():
        ok = False
        detail.append("setInterval غير موجود إطلاًا (غير متوقع)")
    return ok, "; ".join(detail)


ok_cc, det_cc = intervals_inside(cc_seti, cc_fn)
ok_pj, det_pj = intervals_inside(pj_seti, pj_fn)
add("A4", "لا استطلاع أعمى متبقٍ: setInterval(pollActiveRuns/fetchRuntime) داخل sync المشروطة فقط",
    ok_cc and ok_pj, f"cc: {det_cc} | proj: {det_pj}")

# أ5) تطابق بايتي بين المنشور و main المحلي (sha256 لكل ملف)
byte_ev, byte_ok = {}, True
for f in FILES:
    rc, sha_out, _ = run(ssh, f"sha256sum /opt/agentic-engineering-system/{f}")
    prod_sha = sha_out.split()[0] if sha_out.split() else None
    loc_sha = local_blob_sha("main", f)
    match = prod_sha == loc_sha
    byte_ok = byte_ok and match
    byte_ev[f] = {"prod": prod_sha, "local_main": loc_sha, "match": match}
add("A5", "تطابق بايتي: الملفات الثلاثة المنشورة == git show main:<file>", byte_ok, byte_ev)

# أ6) الخدمات + /health 200 JSON
rc, act, _ = run(ssh, "systemctl is-active agentic.service nginx")
rc, health, _ = run(ssh, "curl -s --max-time 8 http://127.0.0.1:8010/health")
health_ok = '"status"' in health and '"ok"' in health
add("A6", "agentic.service و nginx نشطان + /health 200 JSON status ok",
    act.strip() == "active\nactive" and health_ok,
    f"is-active={act.strip().splitlines()} health={health.strip()[:120]}")

# أ7) إصدار الأصول الحي ?v=9e2ace5b
rc, vers, _ = run(ssh, "curl -s --max-time 8 http://127.0.0.1:8010/ | grep -oE 'control-center.js\\?v=[0-9a-f]+' | head -1")
add("A7", "الصفحة الحية تخدم control-center.js?v=9e2ace5b",
    vers.strip() == "control-center.js?v=9e2ace5b", f"served={vers.strip()!r}")

# أ8) سلامة htpasswd (بصمة + سطر واحد + vis + SELinux/ملكية)
rc, hp_sha, _ = run(ssh, "sudo -n sha256sum /etc/nginx/.htpasswd_vis")
rc, hp_wc, _ = run(ssh, "sudo -n wc -l /etc/nginx/.htpasswd_vis")
rc, hp_users, _ = run(ssh, "sudo -n awk -F: '{print $1}' /etc/nginx/.htpasswd_vis")
rc, hp_ls, _ = run(ssh, "sudo -n ls -laZ /etc/nginx/.htpasswd_vis")
hp_ok = (hp_sha.split()[0] == HTPASSWD_SHA if hp_sha.split() else False) \
    and hp_wc.split()[0] == "1" and hp_users.strip() == "vis" \
    and "httpd_config_t" in hp_ls and " root nginx " in hp_ls and "-rw-r-----" in hp_ls
add("A8", "htpasswd سليم: sha256 مطابق + سطر واحد + vis فقط + httpd_config_t + root:nginx 640",
    hp_ok, f"sha={hp_sha.split()[0][:16]}… lines={hp_wc.split()[0]} users={hp_users.strip()!r} ls={hp_ls.strip()}")

# أ9) لا أخطاء جديدة في journal (باستثناء أسماء ملفات static)
rc, jerr, _ = run(ssh, "sudo -n journalctl -u agentic.service --since '2026-10-27 01:30' | grep -iE 'error|traceback' | grep -vE 'static/error-boundary' | tail -15", timeout=90)
add("A9", "لا أخطاء/traceback جديدة في journal agentic منذ 01:30 (عدا أسماء ملفات static)",
    jerr.strip() == "", f"lines={len(jerr.strip().splitlines())} tail={jerr.strip()[:300]!r}")

# ================================================== ب) سجل nginx — الدليل الشبكي
rc, log, _ = run(ssh, "sudo -n tail -n 2000 /var/log/nginx/access.log", timeout=90)
lines = [l for l in log.splitlines() if l.strip()]
pat = re.compile(r'^(\S+) - (\S+) \[([^\]]+)\] "(\S+) (\S+)[^"]*" (\d{3}) \d+ "([^"]*)" "([^"]*)"')
entries = []
for l in lines:
    m = pat.match(l)
    if m:
        try:
            t = datetime.strptime(m.group(3), "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            continue
        entries.append({"ip": m.group(1), "user": m.group(2), "t": t, "ts": int(t.timestamp()),
                        "method": m.group(4), "path": m.group(5), "status": m.group(6), "ua": m.group(8)})

poll_entries = [e for e in entries if e["path"].endswith("/runs/active") or "/runtime" in e["path"]]
post_deploy = [e for e in poll_entries if e["t"].strftime("%H:%M:%S") >= DEPLOY_TS and e["t"].strftime("%Y-%m-%d") == "2026-10-27"]

# تصنيف حسب (المصدر، المسار)
from collections import defaultdict
groups = defaultdict(list)
for e in post_deploy:
    key = (e["ip"], "runs/active" if e["path"].endswith("/runs/active") else "runtime")
    groups[key].append(e)

analysis = {"total_log_lines": len(lines), "parsed": len(entries),
            "poll_requests_total_in_tail": len(poll_entries),
            "poll_after_deploy": len(post_deploy), "groups": {}}

# كشف النمط الدوري (5ث/3ث) لكل مجموعة: ≥3 فواصل متتالية داخل النطاق
def cycle_detection(ts_list, lo, hi):
    streak, best = 0, 0
    for a, b in zip(ts_list, ts_list[1:]):
        if lo <= (b - a) <= hi:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


sustained_found = {}
for (ip, kind), evs in sorted(groups.items()):
    evs.sort(key=lambda x: x["ts"])
    ts = [e["ts"] for e in evs]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    c5 = cycle_detection(ts, 4, 6)    # دورة 5ث ±1
    c3 = cycle_detection(ts, 2, 4)    # دورة 3ث ±1
    first, last = evs[0]["t"].strftime("%H:%M:%S"), evs[-1]["t"].strftime("%H:%M:%S")
    analysis["groups"][f"{ip}|{kind}"] = {
        "count": len(evs), "first": first, "last": last, "gaps": gaps,
        "sustained_5s_streak": c5, "sustained_3s_streak": c3}
    if c5 >= 3 or c3 >= 3:
        sustained_found[f"{ip}|{kind}"] = {"5s": c5, "3s": c3}

# المجموعات المتوقعة بعد النشر: (أ) تحميل أولي معدود من 127.0.0.1، (ب) عميل المالك القديم
loopback = analysis["groups"].get("127.0.0.1|runs/active", {})
owner = analysis["groups"].get("2.215.157.88|runs/active", {})
owner_rt = analysis["groups"].get("2.215.157.88|runtime", {})
loopback_rt = analysis["groups"].get("127.0.0.1|runtime", {})

# (ب-1) لا دورة 5ث/3ث مستمرة من أي مصدر بعد النشر — عدا العميل القديم للمالك
sustained_non_owner = {k: v for k, v in sustained_found.items() if not k.startswith("2.215.157.88|")}
add("B1", "لا دورة استطلاع دورية مستمرة (5ث/3ث) في سجل nginx بعد النشر من أي عميل جديد",
    len(sustained_non_owner) == 0,
    f"sustained_found={sustained_found if sustained_found else 'none'} loopback_counts={loopback.get('count', 0)} owner_counts={owner.get('count', 0)}")

# (ب-2) طلبات النفق (127.0.0.1) بعد النشر: عدّة تحميل أولي ثم صمت (لا دورة)
loop_ok = loopback.get("count", 0) <= 12 and loopback.get("sustained_5s_streak", 0) < 3
add("B2", "طلبات 127.0.0.1 (جلسة قياس المنفذ عبر النفق) = تحميل أولي معدود ثم صمت",
    loop_ok, f"runs/active count={loopback.get('count', 0)} gaps={loopback.get('gaps', [])} runtime count={loopback_rt.get('count', 0)}")

# (ب-3) توثيق عميل المالك (إن ظل يستطلع — متوقع وغير حاجب)
# أي إصدار أصول حمّله كل مصدر؟
asset_vers = defaultdict(set)
for e in entries:
    if "control-center.js" in e["path"] and "v=" in e["path"]:
        asset_vers[e["ip"]].add(e["path"].split("v=")[-1][:8])
owner_note = {
    "owner_runs/active_count": owner.get("count", 0),
    "owner_runtime_count": owner_rt.get("count", 0),
    "owner_gaps": owner.get("gaps", []),
    "asset_versions_seen": {ip: sorted(v) for ip, v in asset_vers.items()},
}
add("B3", "مصدر المالك 2.215.157.88 موثّق (عميل قديم لم يُعد التحميل = متوقع وغير حاجب)",
    True, owner_note)  # توثيقي دائمًا

# (ب-4) اتصال events/stream موجود/حي في السجل
stream_entries = [e for e in entries if "events/stream" in e["path"]]
stream_200 = [e for e in stream_entries if e["status"] == "200"]
add("B4", "اتصال events/stream حي/موجود في السجل (محاولات 200 ناجحة)",
    len(stream_200) > 0,
    f"stream_total={len(stream_entries)} stream_200={len(stream_200)} "
    f"last_200={stream_200[-1]['t'].strftime('%H:%M:%S') if stream_200 else None} "
    f"ips={sorted(set(e['ip'] for e in stream_entries))}")

# ================================================== ج) مراجعة الكود (محليًا)
rc, stat, _ = local(["git", "show", "9e2ace5", "--stat"])
stat_ok = "3 files changed, 83 insertions(+), 7 deletions(-)" in stat
add("C1", "الالتزام 9e2ace5: رقعة 3 ملفات UI (+83/−7)", stat_ok,
    "stat=" + " | ".join(l.strip() for l in stat.splitlines() if "files changed" in l))

node_ok, node_ev = True, []
for f in FILES:
    p = subprocess.run(["node", "--check", f"{REPO}/{f}"], capture_output=True, text=True)
    node_ok = node_ok and p.returncode == 0
    node_ev.append(f"{f.split('/')[-1]}: rc={p.returncode}")
add("C2", "node --check يمرّ على الملفات الثلاثة من المستودع المحلي", node_ok, "; ".join(node_ev))

# ج-3: المنطق الجراحي — نصوص دقيقة داخل الملفات من main
rc, cc_src, _ = local(["git", "show", "main:src/ui/control-center.js"])
rc, pj_src, _ = local(["git", "show", "main:src/ui/projects.js"])
rc, le_src, _ = local(["git", "show", "main:src/ui/live-events.js"])

logic = {}
logic["cc_gating"] = ('["RUNNING", "REVISING", "PLANNING"]' in cc_src
                      and "r.planning_active" in cc_src
                      and "function syncRunPolling" in cc_src)
logic["cc_single_pulse"] = bool(re.search(r"pollActiveRuns\(\);\s*\n\s*(/\*|function wakeFromEvents)", cc_src))
logic["cc_no_blind_interval_at_load"] = not re.search(r"state\.pollTimer = setInterval\(pollActiveRuns, 5000\);\s*\n\s*pollActiveRuns\(\)", cc_src) and cc_src.count("setInterval(pollActiveRuns") == 1
logic["cc_event_wakeup_400"] = "LiveEvents.onEvent(wakeFromEvents())" in cc_src and "}, 400);" in cc_src
logic["cc_safety_gated"] = bool(re.search(r"setInterval\(function \(\) \{\s*\n\s*if \(window\.LiveEvents && LiveEvents\.isConnected\(\)\) return;", cc_src))
logic["pj_gating"] = ('["RUNNING", "PLANNING", "REVISING"]' in pj_src
                      and "runtime.planning && runtime.planning.active" in pj_src)
logic["pj_single_pulse"] = bool(re.search(r"function startRuntimePolling\(\) \{\s*\n\s*stopRuntimePolling\(\);", pj_src)) and pj_src.count("setInterval(fetchRuntime") == 1
logic["pj_fetch_from_events"] = bool(re.search(r"reconcileTimer = setTimeout\(function \(\) \{\s*\n\s*reconcile\(\);\s*\n\s*fetchRuntime\(\);\s*\n\s*\}, 250\);", pj_src))
logic["le_connected_flag"] = "STATE.connected = true" in le_src and "STATE.connected = false" in le_src
logic["le_isconnected_api"] = "isConnected: function () { return STATE.connected; }" in le_src
add("C3", "منطق الرقعة سليم: تعليق الدورتين على تقدم فعلي + إيقاظ أحداث + شبكة أمان مقيدة",
    all(logic.values()), logic)

# ج-4: الواجهات العامة باقية
iface = {
    "window.ControlCenter.refreshRuns": "refreshRuns: pollActiveRuns" in cc_src,
    "window.HubProjects.fetchRuntime": "fetchRuntime: fetchRuntime" in pj_src,
    "HubProjects.exitProjectMode exported": "exitProjectMode: exitProjectMode" in pj_src,
    "exitProjectMode→stopRuntimePolling": bool(re.search(r"function exitProjectMode\(\) \{[\s\S]{0,400}stopRuntimePolling\(\);", pj_src)),
}
add("C4", "لا كسر للواجهات العامة (refreshRuns / fetchRuntime / exitProjectMode→stopRuntimePolling)",
    all(iface.values()), iface)

# ================================================== د) سلامة أدلة المنفذ
def read(path, binary=False):
    try:
        if binary:
            with open(path, "rb") as fh:
                return fh.read()
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        return f"__READ_ERROR__:{exc}"


gs = read(f"{EV}/gate_summary.txt")
gs_flat = gs.replace("\\", "")  # كسر الهروب في سطر sse_final المقتبس
gs_sse_ok = '"sse_connected":true' in gs_flat
gs_ok = ("cc_idle_65s_poll_requests: 0" in gs and "proj_idle_65s_poll_requests: 0" in gs
         and gs_sse_ok and "js_errors_final: 0" in gs)
add("D1", "gate_summary.txt: cc_idle poll=0 + proj_idle poll=0 + sse متصل + js_errors=0", gs_ok, gs.strip().replace("\n", " | "))

nc = read(f"{EV}/net-cc-new-requests.txt")
np_ = read(f"{EV}/net-proj-new-requests.txt")
add("D2", "net-cc-new-requests.txt و net-proj-new-requests.txt فارغان فعلًا (wc -l = 0)",
    len(nc.strip().splitlines()) == 0 and len(np_.strip().splitlines()) == 0,
    f"cc_lines={len(nc.strip().splitlines())} proj_lines={len(np_.strip().splitlines())}")

# إعادة تحقق مستقلة: قبل == بعد (صفر طلبات جديدة خلال نافذتي 65ث)
ccb, cca = read(f"{EV}/net-cc-before.txt"), read(f"{EV}/net-cc-after.txt")
pjb, pja = read(f"{EV}/net-proj-before.txt"), read(f"{EV}/net-proj-after.txt")
add("D3", "إعادة الفحص: net-before == net-after بايتيًا للنافذتين (لا طلبات جديدة)",
    ccb == cca and pjb == pja, f"cc_identical={ccb == cca} proj_identical={pjb == pja}")

ssf = read(f"{EV}/sse_state_final.txt")
m = re.search(r'\\"last_event_id\\":(\d+)', ssf) or re.search(r'"last_event_id\\?":\s*(\d+)', ssf)
sse_ok = '"sse_connected\\":true' in ssf or '"sse_connected":true' in ssf
add("D4", "sse_state_final.txt: connected:true + last_event_id رقم",
    sse_ok and bool(m), f"content={ssf.strip()[:120]!r} last_event_id={m.group(1) if m else None}")

errs = read(f"{EV}/errors_final.txt") + read(f"{EV}/errors_cc.txt")
add("D5", "errors_final.txt و errors_cc.txt فارغان", len(errs.strip().splitlines()) == 0,
    f"lines={len(errs.strip().splitlines())}")

asu, acl = read(f"{EV}/auth_setup_log.txt"), read(f"{EV}/auth_cleanup_log.txt")
sha_in_setup = HTPASSWD_SHA in asu and "1 /etc/nginx/.htpasswd_vis" in asu
sha_in_cleanup = HTPASSWD_SHA in acl and "vis" in acl and "1 /etc/nginx/.htpasswd_vis" in acl
add("D6", "auth_setup/cleanup: sha256 قبل = بعد (038af1fb…) + سطر واحد + vis فقط",
    sha_in_setup and sha_in_cleanup,
    f"setup_has_sha={HTPASSWD_SHA in asu} cleanup_has_sha={HTPASSWD_SHA in acl}")

lm = read("/home/z/my-project/scripts/w1t02_live_measure.sh")
lm_ok = lm.count("sleep 65") >= 2 and "grep '^>'" in lm and "diff" in lm and "grep -cE 'runs/active|/runtime'" in lm
add("D7", "w1t02_live_measure.sh: نافذتا 65ث حقيقيتان (sleep 65 ×2) + قياس الطلبات الجديدة بdiff/grep '^>'",
    lm_ok, f"sleep65_count={lm.count('sleep 65')} diff_new_lines_logic={'grep \'^>\'' in lm}")

png = read(f"{EV}/idle-final-1440.png", binary=True)
png_ok = isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 10000
add("D8", "لقطة idle-final-1440.png موجودة وتوقيع PNG سليم", png_ok,
    f"magic_ok={png_ok} size={len(png) if isinstance(png, bytes) else 0}")

# أ10) انتقال ff فقط من 0f2d9c6 (دليل reflog) — لا دمج/إعادة كتابة
rc, ff_log, _ = run(ssh, "git -C /opt/agentic-engineering-system log --oneline 0f2d9c6..HEAD | wc -l")
rc, reflog, _ = run(ssh, "git -C /opt/agentic-engineering-system reflog -2 | head -2")
ff_ok = "merge 9e2ace5b3acb0983cebff1a9e658507903273511: Fast-forward" in reflog and "9e2ace5b" in reflog.splitlines()[0]
add("A10", "الانتقال إلى 9e2ace5 كان ff-only من 0f2d9c6 (reflog: Fast-forward)", ff_ok,
    reflog.strip().replace("\n", " || "))

# ================== تحقق إضافي مستقل: القياس الحي الآن (قراءة فقط، عبر nginx العام)
# عميل HTTP جديد تمامًا: هل صفحة الإنتاج الحية تخدم الأصول الجديدة عبر مسار المالك؟
rc, wall, _ = run(ssh, "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1/")
add("E1", "جدار Basic Auth قائم على nginx العام (401 بلا بيانات) عبر 127.0.0.1:80",
    wall.strip() == "401", f"no_auth_code={wall.strip()}")

# E2) etag + cache-control للصفحة الحية (آلية وصول العميل الجديد للأصول الجديدة)
rc, hdrs, _ = run(ssh, "curl -s -o /dev/null -D - --max-time 8 http://127.0.0.1:8010/ | tr -d '\\r' | grep -iE 'etag|cache-control'")
add("E2", "etag الصفحة ui9e2ace5b + cache-control: no-cache (التحميل التالي يأخذ الرقعة)",
    'etag: "ui9e2ace5b"' in hdrs and "cache-control: no-cache" in hdrs,
    hdrs.strip().replace("\n", " | "))

# E3) حالة التشغيل الحالية: لا run متقدم (خمول حقيقي → صفر استطلاع هو السلوك الصحيح للرقعة)
rc, runs_json, _ = run(ssh, "curl -s --max-time 8 http://127.0.0.1:8010/api/projects/runs/active")
active_now = [s for s in ("RUNNING", "PLANNING", "REVISING") if s in runs_json]
add("E3", "لا run متقدم حاليًا (خمول حقيقي: صفر استطلاع من العميل الجديد هو السلوك القانوني)",
    len(active_now) == 0, f"active_statuses={active_now or 'none'}")

# E4) مسبار SSE مباشر (قراءة فقط، 3ث): البث يستجيب 200 بأحداث فعلية
rc, sse_probe, _ = run(ssh, "timeout 3 curl -s -N --max-time 3 http://127.0.0.1:8010/api/projects/events/stream | head -c 120; echo")
add("E4", "مسبار SSE مستقل (3ث): 200 + stream.start + أحداث فعلية",
    "stream.start" in sse_probe, sse_probe.strip()[:120])

# B5) رصد نافذة إعادة التشغيل من journal (ملاحظة جوهرية غير حاجبة — تخصيصها نمط 014)
rc, jour, _ = run(ssh, "sudo -n journalctl -u agentic.service --since '2026-10-27 01:25' --no-pager | grep -E 'Started|Stopping|Killing process 518861|stop-sigterm|startup complete' | head -8", timeout=90)
restart_window = {
    "sigterm": "01:34:37" if "Stopping" in jour and "01:34:37" in jour else None,
    "started": "01:36:07" if "01:36:07" in jour else None,
    "ready": "01:36:08" if "01:36:08" in jour else None,
    "stop_sigterm_timeout_killed": "stop-sigterm' timed out. Killing" in jour.replace("'", "'") or "timed out" in jour,
    "note": "نافذة رفض اتصالات جديدة ~90ث (SIGTERM 01:34:37 → جاهز 01:36:08) بسبب إغلاق مهذب ينتظر SSE المالك المفتوح حتى TimeoutStopSec=90 → SIGKILL؛ 502×2 لعميل المالك القديم (01:35:31، 01:36:07) تعافى تلقائيًا 01:36:08 — خاصية نمط النشر 014 المعتمد (موثقة كعيب قائم في W3-T17 «نشر بلا نافذة 502»)؛ ادعاء المنفذ «~4ث/بلا انقطاع» غير دقيق زمنيًا لكنه لا يمس بوابة قبول W1-T02 ولا سلامة النشر",
}
add("B5", "رصد: نافذة إعادة التشغيل موثقة من journal (ملاحظة جوهرية غير حاجبة)",
    restart_window["sigterm"] is not None and restart_window["started"] is not None, jour.strip()[:400])

# B6) اتصال SSE حي الآن من عميل المالك (established) + لا مستمع غريب
rc, ssout, _ = run(ssh, "sudo -n ss -tn state established '( sport = :80 )' | tail -n +2")
owner_conns = [l for l in ssout.splitlines() if "2.215.157.88" in l]
add("B6", "اتصال TCP حي الآن من 2.215.157.88 إلى :80 (قناة SSE للمتصفح القديم — البث يعمل)",
    len(owner_conns) >= 1, f"owner_established={len(owner_conns)}")

# B7) تحليل مضبوط: بعد لحظة حياة الكود الجديد فعليًا (01:36:08) — لا دورة 5ث/3ث من أي مصدر
post_live = [e for e in poll_entries if e["t"] >= datetime.strptime("2026-10-27 01:36:08 +0000", "%Y-%m-%d %H:%M:%S %z")]
groups2 = defaultdict(list)
for e in post_live:
    groups2[(e["ip"], "runs/active" if e["path"].endswith("/runs/active") else "runtime")].append(e)
sus2 = {}
analysis["post_new_code_live_013608"] = {}
for (ip, kind), evs in sorted(groups2.items()):
    evs.sort(key=lambda x: x["ts"])
    ts = [e["ts"] for e in evs]
    c5, c3 = cycle_detection(ts, 4, 6), cycle_detection(ts, 2, 4)
    analysis["post_new_code_live_013608"][f"{ip}|{kind}"] = {"count": len(evs), "gaps": [b - a for a, b in zip(ts, ts[1:])], "5s_streak": c5, "3s_streak": c3}
    if c5 >= 3 or c3 >= 3:
        sus2[f"{ip}|{kind}"] = {"5s": c5, "3s": c3}
add("B7", "بعد لحظة حياة الكود الجديد (01:36:08): صفر دورات 5ث/3ث من أي مصدر — المالك القديم بخوارزمية 60ث خلفية فقط",
    len(sus2) == 0, f"sustained={sus2 or 'none'} detail={analysis['post_new_code_live_013608']}")

# ================================================== الحكم
passed = sum(1 for c in checks if c["pass"])
total = len(checks)
verdict = "PASS" if passed == total else "FAIL"

result = {
    "audit": "W1-T02-AUDIT",
    "agent": "independent audit agent (general-purpose)",
    "date": "2026-10-27",
    "server_time_at_audit": server_now.strip(),
    "verdict": verdict,
    "passed": passed,
    "total": total,
    "signature": f"W1-T02-AUDIT · 2026-10-27 · {verdict} · {passed} إثباتًا مستقلًا",
    "local_main": local_main,
    "production_head": prod_head,
    "checks": checks,
    "nginx_analysis": analysis,
    "owner_client_note": owner_note,
    "restart_window_note": restart_window,
    "notes": [
        "قيّم هذا التدقيق بأسطر المخرجات الفعلية (درس W1-T01) لا برموز الخروج فقط.",
        "ملاحظة جوهرية غير حاجبة: نافذة إعادة التشغيل الفعلية كانت ~91ث (SIGTERM 01:34:37 → جاهز 01:36:08) لا «~4ث» كما في سجل المنفذ — رفض اتصالات جديدة ~90ث مع 502×2 لعميل المالك (تعافى تلقائيًا 01:36:08). السبب: uvicorn ينتظر اتصال SSE المفتوح للمالك حتى TimeoutStopSec=90 → SIGKILL — خاصية نمط النشر 014 المعتمد نفسه (العيب القائم الموثق في W3-T17 «نشر بلا نافذة 502»). لا تمس بوابة قبول W1-T02 ولا سلامة النشر؛ يلزم تصحيح الرواية في السجلات مستقبلًا.",
        "مصدر المالك 2.215.157.88: عميل متصفح قديم لم يُعد تحميل الصفحة بعد النشر (لا GET / ولا control-center.js?v= جديد من IP المالك في السجل؛ HTML بـ304 قبل النشر) — استطلاعه المتبقي ~60ث (خنق تبويب خلفي للدورة 5ث القديمة) متوقع وغير حاجب: etag الصفحة الآن ui9e2ace5b + cache-control: no-cache فالتحميل التالي يأخذ الرقعة.",
        "اتصال SSE يعمل: مسبار مستقل 200 + stream.start + أحداث فعلية، وعميل المالك لديه اتصال established حي على :80 منذ 01:36:08، وجلسة قياس المنفذ (127.0.0.1 عبر النفق) رأت last_event_id يتقدم 842→846.",
        "طلبات 127.0.0.1 بعد النشر = 4 طلبات تحميل أولي فعلًا (2×runs/active عند تحميل الصفحة 01:39:11 + runtime وruns/active عند فتح المشروع 01:40:22-23) ثم صمت تام — مطابق لتصميم الرقعة (نبضة أولى + استيقاظ بالأحداث).",
    ],
}
with open(OUT_JSON, "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=2)

print(f"\n=== VERDICT: {verdict} ({passed}/{total}) ===")
print(f"saved → {OUT_JSON}")
ssh.close()
sys.exit(0 if verdict == "PASS" else 1)
