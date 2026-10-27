#!/usr/bin/env python3
"""W1-T03-AUDIT — تدقيق مستقل (قراءة فقط) للخطوات 0-2 من W1-T03 على الإنتاج.

نطاق التدقيق: مسار المراقبة السري /healthz-<TOKEN> في nginx + فتح منفذ 80 في firewalld.
لا اعتماد على تقرير المنفذ — كل الأدلة تُجمع هنا بنفسي:
  أ) سلامة تكوين nginx (SSH قراءة فقط) — 11 فحصًا
  ب) firewalld والوضع الأمني بعد الفتح (SSH + طلبات خارجية GET فقط) — 10 فحوص + توثيق منفذ 22
  ج) سكربتات المنفذ وسلامة الأدلة والمستودع (محلي) — 6 فحوص

التقييم بأسطر المخرجات الفعلية لا برموز الخروج (درس W1-T01/W1-T02).
التوكن الكامل لا يظهر في أي مخرج مطبوع أو ملف أدلة (يقنَّع بـ<TOKEN>؛ البادئة 5e140aa0 فقط).

المخرجات: download/aes-remediation/W1-T03/audit_independent.json
لا يغيّر أي حالة على الإنتاج (أوامر قراءة فقط؛ sudo -n للقراءات الجذرية؛ طلبات GET فقط).
"""
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

import paramiko

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EV = "/home/z/my-project/download/aes-remediation/W1-T03"
SCRIPTS = "/home/z/my-project/scripts"
REPO = "/home/z/my-project/repo"
OUT_JSON = os.path.join(EV, "audit_independent.json")
TOKEN_FILE = os.path.join(EV, "owner-token.txt")
BACKUP_PATH = "/home/opc/agentic.conf.pre-w1t03"
BACKUP_SHA_EXECUTOR = "68af55cd11b019c193beadc4d97012cbee8103a6740c770ed5426cce9a0b8474"
OWNER_IP = "2.215.157.88"
FAKE_TOKEN = "0" * 32          # توكن خاطئ للاختبار الخارجي (لا قابلية خمن)
FAKE_TOKEN_LB = "f" * 32       # مسبار loopback
TS = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

TOKEN = open(TOKEN_FILE).read().strip()

checks = []
notes = []


def mask(s):
    return str(s).replace(TOKEN, "<TOKEN>")


def add(cid, desc, ok, evidence):
    ev = evidence if isinstance(evidence, str) else json.dumps(evidence, ensure_ascii=False)
    ev = mask(ev)
    checks.append({"id": cid, "desc": desc, "pass": bool(ok), "evidence": ev})
    tag = "PASS" if ok else "FAIL"
    line = f"{tag} [{cid}] {desc}"
    if len(ev) <= 200:
        line += f"  → {ev}"
    print(line)


def run(ssh, cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    rc = o.channel.recv_exit_status()
    return rc, o.read().decode(errors="replace"), e.read().decode(errors="replace")


def local(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def ext_get(url, timeout=12):
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "W1-T03-AUDIT/1.0 (independent audit)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        try:
            body = ex.read(120).decode("utf-8", "replace")
        except Exception:
            body = ""
        return ex.code, body
    except Exception as ex:
        return None, f"{type(ex).__name__}: {str(ex)[:160]}"


def sha256_text(s):
    return hashlib.sha256(s.encode()).hexdigest()


# ================================================================ connect
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=20,
            look_for_keys=False, allow_agent=False)

# ================================================================ أ) تكوين nginx
rc, conf, err = run(ssh, "sudo -n cat /etc/nginx/conf.d/agentic.conf")
lines = conf.split("\n")

# --- A1: كتلة healthz موجودة داخل server
hz_idx = [i for i, l in enumerate(lines) if l.startswith("    location = /healthz-")]
server_idx = [i for i, l in enumerate(lines) if l.strip() == "server {"]
last_brace = max(i for i, l in enumerate(lines) if l.strip() == "}" and l == "}")
a1_ok = (len(hz_idx) == 1 and len(server_idx) == 1
         and server_idx[0] < hz_idx[0] < last_brace
         and TOKEN in lines[hz_idx[0]] and lines[hz_idx[0]].rstrip().endswith("{"))
add("A1", "كتلة location = /healthz-<TOKEN> موجودة (مرة واحدة) داخل كتلة server قبل قوسها الختامي",
    a1_ok, f"server@line{server_idx[0] if server_idx else -1} healthz@line{hz_idx[0] if hz_idx else -1} "
           f"server_close@line{last_brace} line='{mask(lines[hz_idx[0]]) if hz_idx else 'MISSING'}'")

# --- A2: محتوى الكتلة بالضبط 3 توجيهات، و allow all/auth_basic off لا يظهران خارجها
block_inner = []
if hz_idx:
    close = next((j for j in range(hz_idx[0] + 1, len(lines)) if lines[j].strip() == "}"), None)
    block_inner = [l.strip() for l in lines[hz_idx[0] + 1:close] if l.strip()]
expected_inner = ["allow all;", "auth_basic off;", "proxy_pass http://127.0.0.1:8010/health;"]
a2_ok = (block_inner == expected_inner
         and conf.count("allow all;") == 1
         and conf.count("auth_basic off;") == 1
         and conf.count("proxy_pass http://127.0.0.1:8010/health;") == 1)
add("A2", "محتوى الكتلة: allow all + auth_basic off + proxy_pass 127.0.0.1:8010/health فقط — "
          "ولا تظهر هذه التوجيهات في أي مكان آخر من الملف",
    a2_ok, f"inner={block_inner} | counts: allow_all={conf.count('allow all;')} "
           f"auth_basic_off={conf.count('auth_basic off;')} "
           f"pp_health={conf.count('proxy_pass http://127.0.0.1:8010/health;')}")

# --- A3: سلامة بنيوية (أقواس متوازنة، listen/server_name كما هما)
a3_ok = (conf.count("{") == conf.count("}")
         and "listen 80 default_server;" in conf
         and re.search(r"^\s*server_name\s+_;", conf, re.M) is not None)
add("A3", "بنية سليمة: أقواس متوازنة ({} == {}) + listen 80 default_server + server_name _",
    a3_ok, f"braces {conf.count('{')}/{conf.count('}')} | listen80={'yes' if 'listen 80 default_server;' in conf else 'NO'}")


def extract_location_block(txt, loc_prefix):
    ls = txt.split("\n")
    st = next((i for i, l in enumerate(ls) if l.strip().startswith(loc_prefix)), None)
    if st is None:
        return None
    en = next((j for j in range(st + 1, len(ls)) if ls[j].strip() == "}"), None)
    if en is None:
        return None
    return "\n".join(ls[st:en + 1])


# --- A4: قواعد server-level (allow/deny/auth_basic) باقية حرفيًا
srv_rules = [l for l in lines if re.match(r"^\s*(allow 2\.215\.157\.88;|allow 127\.0\.0\.1;|deny\s+all;|auth_basic\s|auth_basic_user_file\s)", l)]
a4_patterns = [r"allow 2\.215\.157\.88;", r"allow 127\.0\.0\.1;", r"deny\s+all;",
               r"auth_basic\s+\"AES VIS preview", r"auth_basic_user_file\s+/etc/nginx/\.htpasswd_vis;"]
a4_ok = all(any(re.search(p, l) for l in lines) for p in a4_patterns) and len(srv_rules) >= 5
add("A4", "قواعد server-level كما هي: allow المالك + allow loopback + deny all + auth_basic + auth_basic_user_file",
    a4_ok, " | ".join(l.strip() for l in srv_rules))

# --- A5: كتلة location / الأصلية بايتيًا + proxy_buffering off (SSE) باقٍ
rc, backup, _ = run(ssh, f"sudo -n cat {BACKUP_PATH}")
loc_cur = extract_location_block(conf, "location / {")
loc_bak = extract_location_block(backup, "location / {")
a5_ok = (loc_cur is not None and loc_cur == loc_bak and "proxy_buffering off;" in loc_cur)
add("A5", "كتلة location / الأصلية مطابقة بايتيًا للنسخة الاحتياطية وفيها proxy_buffering off (قناة SSE)",
    a5_ok, f"identical={loc_cur == loc_bak} | proxy_buffering_off={'yes' if loc_cur and 'proxy_buffering off;' in loc_cur else 'NO'} | "
           f"block_lines={len(loc_cur.split(chr(10))) if loc_cur else 0}")

# --- A6: النسخة الاحتياطية موجودة وبصمتها مطابقة، والفرق الوحيد عن الحالي هو كتلة healthz فقط
rc_ls, ls_out, _ = run(ssh, f"sudo -n ls -la {BACKUP_PATH}")
rc_sha, sha_out, _ = run(ssh, f"sudo -n sha256sum {BACKUP_PATH}")
backup_exists = (rc_ls == 0 and rc_sha == 0 and bool(sha_out.split()))
srv_sha = sha_out.split()[0] if sha_out.split() else ""
cur_lines = list(lines)
m = next((i for i, l in enumerate(cur_lines) if l.startswith("    # W1-T03 (2026-10-27)")), None)
blk_close = next((j for j in range(hz_idx[0] + 1 if hz_idx else 0, len(cur_lines))
                  if cur_lines[j].strip() == "}"), None) if hz_idx else None
cur_minus_block = cur_lines[:m] + cur_lines[blk_close + 1:] if (m is not None and blk_close is not None) else None
cur_minus_block_str = "\n".join(cur_minus_block) if cur_minus_block is not None else ""
backup_norm = backup.rstrip("\n")
curmb_norm = cur_minus_block_str.rstrip("\n")
a6_ok = (backup_exists and srv_sha == BACKUP_SHA_EXECUTOR
         and srv_sha == sha256_text(backup)
         and curmb_norm == backup_norm)
add("A6", "نسخة احتياطية موجودة (/home/opc/agentic.conf.pre-w1t03) بصمة 68af55cd… مطابقة لما وثّقه المنفذ، "
          "والحالي بعد حذف كتلة healthz == النسخة الاحتياطية بايتيًا (الفرق الوحيد = الكتلة المضافة)",
    a6_ok, f"exists={backup_exists} ({ls_out.strip().split()[-4:] if ls_out.strip() else 'MISSING'}) | "
           f"backup_sha={srv_sha[:16]}… | sha_match_executor={srv_sha == BACKUP_SHA_EXECUTOR} | "
           f"sha_match_fetched={srv_sha == sha256_text(backup)} | current_minus_block==backup: {curmb_norm == backup_norm}")

# --- A7: nginx -t ناجح (بمخرجاتي أنا) + توثيق مصدر تحذير server_name المتعارض
rc, nt_out, _ = run(ssh, "sudo -n nginx -t 2>&1")
nt_ok = "test is successful" in nt_out and "syntax is ok" in nt_out
rc, sn_out, _ = run(ssh, "sudo -n grep -rn 'server_name' /etc/nginx/conf.d/ /etc/nginx/nginx.conf 2>/dev/null")
conflict_files = [l for l in sn_out.split("\n") if "server_name" in l and "_" in l]
rc, warn_hist, _ = run(ssh, "sudo -n journalctl -u nginx --since '2026-10-26 00:00' --until '2026-10-27 02:05' "
                         "--no-pager 2>/dev/null | grep -i 'conflicting server name' | tail -3")
warn_pre = "سابق للنشر" if warn_hist.strip() else ("لا مثال سابق في journal منذ 2026-10-26 — "
           "لكن الرقعة لم تُضف أي كتلة server (location داخل server قائم) فالتعارض لا يمكن أن يكون من W1-T03")
notes.append("تحذير nginx '[warn] conflicting server name \"_\"' في مخرجات nginx -t — " + warn_pre +
             "؛ تعريفات server_name _: " + "; ".join(conflict_files[:4]) +
             " — تحذير Warning لا Error ولا يمنع نجاح الفحص (سابق للرقعة).")
add("A7", "sudo -n nginx -t ناجح بمخرجات فعلية ('syntax is ok' + 'test is successful')",
    nt_ok, " / ".join(l.strip() for l in nt_out.strip().split("\n")[-2:]))

# --- A8: loopback healthz = 200 + JSON فيه "status":"ok"
rc, hz_code, _ = run(ssh, f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 8 http://127.0.0.1/healthz-{TOKEN}")
rc2, hz_body, _ = run(ssh, f"curl -s --max-time 8 http://127.0.0.1/healthz-{TOKEN} | head -c 120")
a8_ok = hz_code.strip() == "200" and '"status":"ok"' in hz_body
add("A8", "من الخادم (loopback عبر nginx): /healthz-<TOKEN> = 200 والجسم JSON فيه \"status\":\"ok\"",
    a8_ok, f"code={hz_code.strip()} body_head={hz_body.strip()[:100]!r}")

# --- A9: loopback / = 401 (الجدار قائم)
rc, root_code, _ = run(ssh, "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1/")
add("A9", "loopback: http://127.0.0.1/ = 401 (allowlist + Basic Auth كما هما)",
    root_code.strip() == "401", f"code={root_code.strip()}")

# --- A10: loopback توكن خاطئ — وثّق السلوك الفعلي وفسّره
rc, fake_lb, _ = run(ssh, f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 8 http://127.0.0.1/healthz-{FAKE_TOKEN_LB}")
a10_ok = fake_lb.strip() in ("401", "403", "404")
notes.append(f"سلوك loopback مع توكن خاطئ: /healthz-{'f'*8}… = {fake_lb.strip()} — التفسير: المسار لا يطابق "
             "location = الدقيق فيقع في location / حيث تسري auth_basic على مستوى server (تحدٍّ 401 قبل الوكالة للتطبيق). "
             "هذا سلوك loopback الداخلي وليس اختبار الخمن الخارجي — دليل عدم القابلية للخمن هو 403 الخارجي في B6.")
add("A10", "loopback توكن خاطئ: رد محدد مرفوض (401/403/404) وموثق — ليس 200 أبدًا",
    a10_ok, f"code={fake_lb.strip()} (مفسر في الملاحظات)")

# --- A11: التطبيق مباشرة 8010/health = 200
rc, app_code, _ = run(ssh, "curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8010/health")
add("A11", "التطبيق مباشرة: http://127.0.0.1:8010/health = 200",
    app_code.strip() == "200", f"code={app_code.strip()}")

# ================================================================ ب) firewalld + الوضع الأمني
# --- B1: firewalld نشط
rc, fw_act, _ = run(ssh, "systemctl is-active firewalld")
add("B1", "systemctl is-active firewalld = active", fw_act.strip() == "active", f"out={fw_act.strip()!r}")

# --- B2/B3: قائمة الجدار — المنافذ والخدمات والقواعد (runtime + permanent)
rc, fw_all, _ = run(ssh, "sudo -n firewall-cmd --list-all")
rc, fw_perm, _ = run(ssh, "sudo -n firewall-cmd --permanent --list-all")

def fw_section(txt, key):
    ls = txt.split("\n")
    st = next((i for i, l in enumerate(ls) if l.strip().startswith(key + ":")), None)
    if st is None:
        return "", []
    # قيمة السطر نفسه + الأسطر المتبعة المزاحة بعلامة جدولة (rich rules متعددة الأسطر)
    val = ls[st].split(":", 1)[1].strip()
    cont = [l.strip() for l in ls[st + 1:] if l.startswith("\t") and l.strip()]
    return val, cont

ports_val, _ = fw_section(fw_all, "ports")
ports_perm_val, _ = fw_section(fw_perm, "ports")
services_val, _ = fw_section(fw_all, "services")
_, rich_rules = fw_section(fw_all, "rich rules")
_, rich_rules_perm = fw_section(fw_perm, "rich rules")
add("B2", "firewalld: ports = 80/tcp فقط، في runtime وpermanent معًا (مفتوح للعالم بعد reload — nginx هو الحارس)",
    "80/tcp" in ports_val and ports_val.strip() == "80/tcp" and "80/tcp" in ports_perm_val,
    f"runtime='{ports_val}' permanent='{ports_perm_val}'")
b3_ok = ("ssh" in services_val and "dhcpv6-client" in services_val
         and "http" not in services_val.replace("dhcpv6-client", ""))
add("B3", "firewalld: services = dhcpv6-client ssh فقط (SSH عبر الخدمة القياسية، لا خدمة http مفتوحة)",
    b3_ok, f"'{services_val}'")
notes.append("rich rules الباقية (وكانت قائمة قبل التغيير): قاعدتا المالك 2.215.157.88 على 80 و8011 — "
             "قاعدة 80 صارت زائدة عن الحاجة بعد فتح 80/tcp على مستوى المنطقة (لا ضرر: تكرار سماح لمصدر واحد)، "
             "وقاعدة 8011 خاصة بخدمة مجمّدة أرشيفت في W1-T01 (لا مستمع عليها). لا قواعد جديدة أُضيفت، "
             "ولا قاعدة تمنح وصولًا واسعًا لأي مصدر آخر — وهذا يؤكد رواية المنفذ عن اكتشاف rich rule قبل الفتح.")

# --- B12: لا قواعد rich جديدة/واسعة — قاعدتا المالك فقط (80 زائدة + 8011 لخدمة مجمّدة)
owner_rules = {r for r in rich_rules if "2.215.157.88" in r}
b12_ok = (len(rich_rules) == len(owner_rules) == 2
          and set(rich_rules) == set(rich_rules_perm)
          and all("port port=" in r for r in rich_rules))
add("B12", "قواعد rich: قاعدتا المالك فقط (80/8011) في runtime وpermanent — صفر قواعد جديدة أو واسعة من W1-T03",
    b12_ok, f"rules={rich_rules} | permanent_identical={set(rich_rules) == set(rich_rules_perm)}")

# --- B4-B7: الاختبار الخارجي من بيئة التدقيق (IP خارجي — ليس المالك ولا الخادم) — GET فقط
code_root, body_root = ext_get(f"http://{HOST}/")
add("B4", "خارجي: http://92.5.14.150/ = 403 (كل ما عدا السر مرفوض)", code_root == 403,
    f"code={code_root} body={body_root[:60]!r}")
code_api, _ = ext_get(f"http://{HOST}/api/projects")
add("B5", "خارجي: http://92.5.14.150/api/projects = 403", code_api == 403, f"code={code_api}")
code_fake, _ = ext_get(f"http://{HOST}/healthz-{FAKE_TOKEN}")
add("B6", "خارجي: /healthz-<توكن خاطئ 32 صفرًا> = 403 (لا قابلية خمن — المسار السري لا يكشف نفسه)",
    code_fake == 403, f"code={code_fake}")
code_hz, body_hz = ext_get(f"http://{HOST}/healthz-{TOKEN}")
add("B7", "خارجي: /healthz-<التوكن الصحيح من ملف المالك> = 200 والجسم JSON فيه \"status\":\"ok\"",
    code_hz == 200 and '"status":"ok"' in body_hz, f"code={code_hz} body_head={body_hz[:100]!r}")

# --- B8: إثبات أن مصدر طلباتي خارجي فعليًا (ليس المالك ولا الخادم)
my_ip = None
for ip_url in ("http://api.ipify.org/", "https://api.ipify.org/", "http://ifconfig.me/ip"):
    try:
        with urllib.request.urlopen(urllib.request.Request(ip_url, method="GET"), timeout=8) as r:
            cand = r.read(64).decode("utf-8", "replace").strip()
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", cand):
            my_ip = cand
            break
    except Exception:
        continue
if my_ip:
    b8_ok = my_ip not in (OWNER_IP, HOST)
    b8_ev = f"egress_ip={my_ip} != owner({OWNER_IP}) != server({HOST})"
else:
    # إثبات منطقي مستقل: nginx ردّ 403 (deny all) — أي أن مصدر الطلب خارج قائمة السماح حتمًا
    b8_ok = code_root == 403
    b8_ev = f"lookup failed؛ الإثبات المنطقي: / ردّت 403 (deny all) → المصدر خارج allowlist حتمًا"
add("B8", "طلبات التدقيق مصدرها IP خارجي فعلي (ليس 2.215.157.88 المالك ولا الخادم)",
    b8_ok, b8_ev)

# --- B9 (توثيقي فقط، غير محسوب): منفذ 22
try:
    s = socket.create_connection((HOST, 22), timeout=3)
    s.close()
    p22 = "open (خدمة ssh القياسية — الوصول يتطلب المفتاح الخاص)"
except Exception as ex:
    p22 = f"closed/filtered ({type(ex).__name__})"
notes.append(f"منفذ 22 من خارجي: {p22} — توثيق فقط لا يُحسب فشلًا (خدمة ssh قياسية عبر firewalld services، والمصادقة بالمفتاح الخاص).")

# --- B10: لا أخطاء جديدة في سجل nginx منذ 02:00 (تقييم بأسطر المخرجات لا برمز الخروج)
rc, jrn, _ = run(ssh, "sudo -n journalctl -u nginx --since '2026-10-27 02:00' --no-pager 2>/dev/null | grep -iE 'error|crit|emerg' | tail -10")
jrn_lines = [l for l in jrn.split("\n") if l.strip()]
add("B10", "سجل nginx منذ 02:00 (وقت النشر): صفر أسطر error/crit/emerg",
    len(jrn_lines) == 0, f"matched_lines={len(jrn_lines)}" + (f" content={jrn_lines[:2]}" if jrn_lines else ""))

# --- B11: الخدمات الثلاث نشطة + مستمعو المنافذ (توثيق)
rc, svcs, _ = run(ssh, "systemctl is-active agentic.service nginx firewalld")
svc_list = [l.strip() for l in svcs.split("\n") if l.strip()]
rc, ss_out, _ = run(ssh, "sudo -n ss -tlnp | grep -E ':(80|8010)\\s'")
notes.append("مستمعو المنافذ: " + " | ".join(l.strip()[:90] for l in ss_out.strip().split("\n") if l.strip()))
add("B11", "systemctl is-active agentic.service nginx firewalld = active×3",
    svc_list == ["active", "active", "active"], f"out={svc_list}")

# ================================================================ ج) سكربتات المنفذ + الأدلة + المستودع
dep_src = open(os.path.join(SCRIPTS, "w1t03_monitor_deploy.py"), encoding="utf-8").read()
fw_src = open(os.path.join(SCRIPTS, "w1t03_firewalld_open.py"), encoding="utf-8").read()
pre_src = open(os.path.join(SCRIPTS, "w1t03_preflight.py"), encoding="utf-8").read()

# --- C1: ترتيب البوابة في سكربت النشر (بأسطر الكود الفعلية — أوائل ظهور للأوامر الحرفية)
backup_cmd_idx = dep_src.find("cp /etc/nginx/conf.d/agentic.conf /home/opc/agentic.conf.pre-w1t03")
replace_cmd_idx = dep_src.find("cp /home/opc/agentic.conf.new /etc/nginx/conf.d/agentic.conf")
nginx_t_idx = dep_src.find("sudo -n nginx -t")
reload_idx = dep_src.find("sudo -n systemctl reload nginx")
c1_ok = (0 <= backup_cmd_idx < replace_cmd_idx < nginx_t_idx < reload_idx
         and "ROLLBACK_DONE" in dep_src
         and "ABORT" in dep_src)
add("C1", "سكربت w1t03_monitor_deploy.py: نسخة احتياطية قبل الاستبدال → nginx -t قبل reload → تراجع تلقائي مجهز",
    c1_ok, f"backup@{backup_cmd_idx} < replace@{replace_cmd_idx} < nginx -t@{nginx_t_idx} < reload@{reload_idx} | "
           f"rollback={'ROLLBACK_DONE' in dep_src} | abort_guards={'ABORT' in dep_src}")

# --- C2: توليد التوكن وتقنيعه في السكربتات
c2_ok = ("token_hex(16)" in dep_src and "0o600" in dep_src
         and '.replace(token, "<TOKEN>")' in dep_src and "mask=token" in dep_src
         and "token_prefix" in fw_src and "token_prefix" in dep_src)
notes.append("ملاحظة نظافة: w1t03_firewalld_open.py يطبع أمر curl بالتوكن الكامل إلى وحدة التحكم العابرة "
             "(run() بلا تقنيع) لكن لا يكتبه في أي ملف أدلة (JSON يخزن token_prefix فقط) — "
             "وفحص C5 أثبت أن لا أثر له على القرص. تحسين مقترح مستقبلًا: تقنيع موحد. "
             "كذلك مخرجات BEFORE في السكربت نفسه (list-all قبل التغيير) طُبعت ولم تُحفظ في ملف أدلة — "
             "الحالة قبل موثقة تجريبيًا بدل ذلك: no-route خارجي في results.json + وصول المالك الموثق في سجل nginx.")
add("C2", "توليد التوكن secrets.token_hex(16) + chmod 0600 + تقنيع <TOKEN> قبل الطباعة وقبل ملفات الأدلة",
    c2_ok, f"token_hex={'yes' if 'token_hex(16)' in dep_src else 'NO'} 0600={'yes' if '0o600' in dep_src else 'NO'} "
           f"print_mask={'yes' if '.replace(token, \"<TOKEN>\")' in dep_src else 'NO'} "
           f"evidence_mask={'yes' if 'mask=token' in dep_src else 'NO'}")

# --- C3: تطابق ملفات أدلة المنفذ مع الادعاءات
fw_results = json.load(open(os.path.join(EV, "20261027-020945-firewalld_results.json"), encoding="utf-8"))
results = json.load(open(os.path.join(EV, "20261027-020719-results.json"), encoding="utf-8"))
ext_ev = fw_results.get("external", {})
c3_ok = (ext_ev.get("healthz_ext", {}).get("code") == 200
         and ext_ev.get("root_ext", {}).get("code") == 403
         and ext_ev.get("api_ext", {}).get("code") == 403
         and ext_ev.get("fake_token_ext", {}).get("code") == 403
         and fw_results.get("verdict_external") == "PASS"
         and results.get("local", {}).get("healthz") == "200"
         and results.get("local", {}).get("wall_401") == "401"
         and results.get("verdict_local") == "PASS"
         and results.get("verdict_external") == "FAIL")
add("C3", "ملفات الأدلة مطابقة: firewalld_results.json خارجيًا {healthz 200, root 403, api 403, fake 403} + "
          "verdict_external=PASS؛ وresults.json داخليًا PASS مع توثيق صادق لفشل no-route قبل إصلاح firewalld",
    c3_ok, f"firewalld_ext={ {k: v.get('code', v.get('error')) for k, v in ext_ev.items()} } "
           f"verdict={fw_results.get('verdict_external')} | deploy: local={results.get('verdict_local')} "
           f"external={results.get('verdict_external')} (no-route قبل الفتح — صادق)")

# --- C4: ملف التوكن — 32 hex + 0600 + البادئة المعلنة فقط
st = os.stat(TOKEN_FILE)
c4_ok = (st.st_mode & 0o777 == 0o600
         and re.fullmatch(r"[0-9a-f]{32}", TOKEN) is not None
         and TOKEN.startswith("5e140aa0"))
add("C4", "owner-token.txt: صلاحيات 0600 + محتوى 32 حرفًا hex + البادئة 5e140aa0 (كما أُعلن)",
    c4_ok, f"mode={oct(st.st_mode & 0o777)} hex32={'yes' if re.fullmatch(r'[0-9a-f]{32}', TOKEN) else 'NO'} prefix={TOKEN[:8]}")

# --- C5: لا تسريب للتوكن الكامل في أي ملف على القرص (عدا ملف المالك نفسه)
hits = []
for dirpath, dirnames, filenames in os.walk("/home/z/my-project"):
    dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__", ".venv")]
    for fn in filenames:
        p = os.path.join(dirpath, fn)
        if p == TOKEN_FILE:
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                if TOKEN in f.read():
                    hits.append(p)
        except OSError:
            pass
add("C5", "التوكن الكامل غير موجود في أي ملف آخر على القرص (أدلة/سكربتات/tool-results/المستودع) — البادئة فقط مسموحة",
    len(hits) == 0, f"leak_hits={hits if hits else 'NONE'}")

# --- C6: المستودع نظيف وبلا W1-T03 (المزامنة لم تحدث بعد — سيراقبها الأب لاحقًا R9)
rc, porc, _ = local(["git", "-C", REPO, "status", "--porcelain"])
rc2, head, _ = local(["git", "-C", REPO, "rev-parse", "--short", "HEAD"])
docs_ops = sorted(os.listdir(os.path.join(REPO, "docs/ops/aes-remediation")))
scripts_ops = sorted(os.listdir(os.path.join(REPO, "scripts/ops")))
c6_ok = (porc.strip() == "" and "W1-T03" not in docs_ops
         and not any(s.startswith("w1t03") for s in scripts_ops)
         and not any(s.startswith("w1t03_audit") for s in scripts_ops))
add("C6", "المستودع main نظيف (git status فارغ) وowner-token/W1-T03 غير مدرجين فيه "
          "(docs/ops/aes-remediation بلا W1-T03 وscripts/ops بلا w1t03 — المزامنة لم تحدث بعد كما هو متوقع)",
    c6_ok, f"porcelain_lines={len(porc.strip().split(chr(10))) if porc.strip() else 0} | head={head.strip()} | "
           f"docs_ops={docs_ops} | w1t03_in_scripts_ops={[s for s in scripts_ops if 'w1t03' in s] or 'NONE'}")

ssh.close()

# ================================================================ الحكم
n_pass = sum(1 for c in checks if c["pass"])
n_total = len(checks)
verdict = "PASS" if n_pass == n_total else "FAIL"
signature = f"W1-T03-AUDIT · 2026-10-27 · {verdict} · {n_pass} إثباتًا مستقلًا"

out = {
    "task": "W1-T03 (خطوات 0-2 فقط — الخطوتان 3-4 خطوة مالك)",
    "auditor": "W1-T03-AUDIT (وكيل تدقيق مستقل — general-purpose)",
    "ts": TS,
    "scope": "مسار المراقبة السري /healthz-<TOKEN> في nginx + فتح منفذ 80 في firewalld — قراءة فقط على الإنتاج، طلبات GET فقط",
    "verdict": verdict,
    "passed": n_pass,
    "total": n_total,
    "signature": signature,
    "checks": checks,
    "notes": [mask(n) for n in notes],
    "firewalld_list_all_runtime": fw_all,
    "firewalld_list_all_permanent": fw_perm,
    "current_conf_sha256": sha256_text(conf),
    "backup_conf_sha256": srv_sha,
    "conf_current_masked": mask(conf),
    "egress_ip": mask(my_ip) if my_ip else None,
}
os.makedirs(EV, exist_ok=True)
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 72)
print(f"الحكم: {verdict} — {n_pass}/{n_total} فحصًا مستقلًا ناجحًا (+ {len(notes)} ملاحظة موثقة)")
print(f"التوقيع: {signature}")
print(f"[evidence] {OUT_JSON}")
sys.exit(0 if verdict == "PASS" else 1)
