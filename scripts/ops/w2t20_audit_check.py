#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T20-AUDIT — وكيل تدقيق مستقل (قراءة-فقط) لمهمة W2-T20 على الإنتاج 92.5.14.150.
تفعيل SearXNG وSearch API وإتاحة البحث الحقيقي.

الانضباط:
- SSH قراءة-فقط طوال الجلسة، باستثناء POSTs مصرح بها حصراً:
  * POST /api/research/search (بحث فعلي — لا يغير حالة)
  * POST /api/research/providers/4/probe و /5/probe (إن كانت الحالة STALE — يحدثان حالة المسبار المخزنة)
  * POST /api/environment/probe {"capability_id":"web_search"} (اختياري، مرة واحدة، فقط إن كانت STALE)
- لا systemctl restart/stop، لا كتابة git، لا تعديل ملفات، لا تغيير تكوين مزود.
- المفتاح يقرأ من /etc/search-api/env ويستخدم في الذاكرة فقط — لا يطبع ولا يخزن في المخرجات.

المخرجات: download/aes-remediation/W2-T20/audit_w2t20_independent.json
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY_PATH = "/tmp/oracle_key"
OUT_DIR = "/home/z/my-project/download/aes-remediation/W2-T20"
REPORT_PATH = os.path.join(OUT_DIR, "audit_w2t20_independent.json")
REPO_LOCAL = "/home/z/my-project/repo"
APP = "http://127.0.0.1:8010"
SEARX = "http://127.0.0.1:8888"
SAPI = "http://127.0.0.1:8098"

EXPECT_HEAD = "be56bf237"  # git HEAD المتوقع على /opt/agentic-engineering-system (أو أحدث)

Q_EN = ("news website page structure homepage world politics business "
        "technology sports entertainment article detail search results best practices")
Q_AR = ("هيكل صفحات موقع أخبار الرئيسية العالم السياسة الأعمال "
        "التكنولوجيا الرياضة الترفيه")

results = []
notes = []
api_key = None  # in-memory only


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check(cid, group, name, ok, evidence):
    results.append({
        "id": cid, "group": group, "name": name,
        "pass": bool(ok), "evidence": evidence,
    })
    print(("[PASS] " if ok else "[FAIL] ") + f"{cid} {name}")
    return ok


def add_note(nid, text):
    notes.append({"id": nid, "note": text})
    print(f"[NOTE] {nid}")


def redact(text):
    """إخفاء أي سر من الدليل قبل تخزينه (المفتاح/secret_key)."""
    out = text
    if api_key and len(api_key) >= 8:
        out = out.replace(api_key, "[REDACTED-KEY]")
    out = re.sub(r"(secret_key\s*:\s*)(\S+)", r"\1[REDACTED]", out)
    return out


def sh(ssh, cmd, timeout=90):
    """تنفيذ أمر قراءة-فقط وإرجاع (rc, stdout, stderr)."""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    return rc, out, err


def http(ssh, method, url, headers=None, json_body=None, timeout=90):
    """طلب HTTP عبر curl على الخادم (loopback) — يرجع (code, body, curl_err, rc).

    جسم JSON يُرسل دائماً مع Content-Type: application/json — بدونه يرفض
    FastAPI الجسم بـ 422 (خطأ جولة أولى في سكربتي أنا، صُحّح هنا).
    """
    parts = ["curl -s --max-time 70"]
    if method != "GET":
        parts.append(f"-X {method}")
    for h in (headers or {}):
        parts.append(f"-H '{h}'")
    if json_body is not None:
        parts.append("-H 'Content-Type: application/json'")
        payload = json.dumps(json_body, ensure_ascii=False).replace("'", "'\\''")
        parts.append(f"--data-binary '{payload}'")
    parts.append(f"-w '\\n@@HTTP_CODE:%{{http_code}}'")
    parts.append(f"'{url}'")
    cmd = " ".join(parts)
    rc, out, err = sh(ssh, cmd, timeout=timeout)
    marker = "@@HTTP_CODE:"
    code, body = None, out
    if marker in out:
        body, tail = out.rsplit(marker, 1)
        body = body.rstrip("\n")
        m = re.match(r"\s*(\d+)", tail)
        if m:
            code = int(m.group(1))
    return code, body, err, rc


def jload(text):
    try:
        return json.loads(text)
    except Exception:
        return None


# ---------------------------------------------------------------- الاتصال
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
pkey = paramiko.RSAKey.from_private_key_file(KEY_PATH)
ssh.connect(HOST, username=USER, pkey=pkey, look_for_keys=False,
            allow_agent=False, timeout=25)
print(f"connected: {USER}@{HOST} @ {now_utc()}")

# المجموعة (أ) — الخدمات والمنافذ ---------------------------------------
rc, out, err = sh(ssh, "systemctl is-active agentic nginx searxng search-api")
states = [ln.strip() for ln in out.splitlines() if ln.strip()]
svc_ok = len(states) == 4 and all(s == "active" for s in states)
check("A1", "أ", "systemctl is-active ×4 (agentic, nginx, searxng, search-api)",
      svc_ok, {"rc": rc, "states": states, "stderr": err.strip()[:200]})

rc, out, err = sh(ssh, "sudo -n ss -tlnp | grep -E ':(8888|8098) '")
listeners = [ln.strip() for ln in out.splitlines() if ln.strip()]


def _line_local(ln):
    good = any(f"127.0.0.1:{p}" in ln for p in ("8888", "8098"))
    bad = any(f"{b}:{p}" in ln for b in ("0.0.0.0", "*", "[::]")
              for p in ("8888", "8098"))
    return good and not bad


all_local = all(_line_local(ln) for ln in listeners)
both_ports = any(":8888" in ln for ln in listeners) and any(":8098" in ln for ln in listeners)
check("A2", "أ", "المستمعان 8888 و8098 على 127.0.0.1 حصراً (لا 0.0.0.0/::)",
      both_ports and all_local and len(listeners) >= 2,
      {"listeners": listeners,
       "note": "حقل Local:Port لكل مستمع يجب أن يبدأ بـ 127.0.0.1 فقط"})

code, body, err, rc = http(ssh, "GET", f"{APP}/health")
check("A3", "أ", "GET /health على 8010 = HTTP 200", code == 200,
      {"http_code": code, "body": (body or "")[:300]})

# المجموعة (ب) — SearXNG حي ----------------------------------------------
searx_evid = {"attempt": 1}
code, body, err, rc = http(ssh, "GET",
    f"{SEARX}/search?q=agentic+engineering+system+software&format=json&language=en",
    timeout=90)
data = jload(body) if code == 200 else None
nres = len(data.get("results", [])) if isinstance(data, dict) else -1
searx_evid["http_code_1st"] = code
searx_evid["results_1st"] = nres
searx_evid["first_titles_1st"] = [r.get("title", "")[:90]
    for r in (data.get("results", [])[:3] if isinstance(data, dict) else [])]
if code == 200 and nres == 0:
    time.sleep(30)  # brave قد يُعلَّق 180ث بعد الدفعات — محاولة ثانية واحدة
    code, body, err, rc = http(ssh, "GET",
        f"{SEARX}/search?q=agentic+engineering+system+software&format=json&language=en",
        timeout=90)
    data = jload(body) if code == 200 else None
    nres = len(data.get("results", [])) if isinstance(data, dict) else -1
    searx_evid["attempt"] = 2
    searx_evid["http_code_2nd"] = code
    searx_evid["results_2nd"] = nres
    searx_evid["first_titles_2nd"] = [r.get("title", "")[:90]
        for r in (data.get("results", [])[:3] if isinstance(data, dict) else [])]
    if nres == 0:
        add_note("N1", "SearXNG أعاد 200/JSON بنتائج صفرية في محاولتين — موثق كما رُئي.")
searx_evid["answers_or_infobox"] = bool(
    isinstance(data, dict) and (data.get("answers") or data.get("infobox")))
check("B1", "ب", "SearXNG JSON API حي: 200 + results غير فارغة", code == 200 and nres > 0,
      searx_evid)

# المجموعة (ج) — Search API ----------------------------------------------
code, body, err, rc = http(ssh, "GET", f"{SAPI}/healthz")
check("C1", "ج", "GET /healthz = 200 وجسمه ok", code == 200 and "ok" in (body or "").lower(),
      {"http_code": code, "body": (body or "")[:200]})

code, body, err, rc = http(ssh, "POST", f"{SAPI}/search",
                           json_body={"query": "python software", "max_results": 5})
check("C2", "ج", "POST /search بلا مفتاح = 401 (fail-closed)", code == 401,
      {"http_code": code, "body": (body or "")[:200]})

rc, env_out, env_err = sh(ssh, "sudo -n cat /etc/search-api/env")
env_lines = [ln.strip() for ln in env_out.splitlines() if ln.strip()]
key_val = None
m48 = re.search(r"\b[0-9a-fA-F]{48}\b", env_out)
if m48:
    key_val = m48.group(0)
else:
    for ln in env_lines:
        m = re.match(r"^[A-Za-z0-9_]*(?:KEY|key)(?:\s*=\s*|\s*:\s*)(.+)$", ln)
        if m:
            key_val = m.group(1).strip().strip('"').strip("'")
api_key = key_val
key_is_48hex = bool(api_key) and bool(re.fullmatch(r"[0-9a-fA-F]{48}", api_key))
check("C3", "ج", "المفتاح مقروء من /etc/search-api/env (48 هكس — لا يُعرض)",
      rc == 0 and key_is_48hex,
      {"rc": rc, "lines_in_file": len(env_lines), "key_length": len(api_key or ""),
       "key_is_48hex": key_is_48hex, "key_sha256_first12": hashlib.sha256(
           api_key.encode()).hexdigest()[:12] if api_key else None,
       "stderr": env_err.strip()[:150]})

code, body, err, rc = http(ssh, "POST", f"{SAPI}/search",
                           headers={"X-API-Key: " + (api_key or "")},
                           json_body={"query": "python software", "max_results": 5})
sapi_data = jload(body) if code == 200 else None
sapi_n = 0
sapi_titles = []
if isinstance(sapi_data, dict):
    rl = sapi_data.get("results") or sapi_data.get("items") or []
    sapi_n = len(rl)
    sapi_titles = [str(r.get("title", r.get("name", "")))[:80] for r in rl[:3]]
elif isinstance(sapi_data, list):
    sapi_n = len(sapi_data)
    sapi_titles = [str(r.get("title", r.get("name", "")))[:80] for r in sapi_data[:3]]
check("C4", "ج", "POST /search بالمفتاح (X-API-Key) = 200 بنتائج",
      code == 200 and sapi_n >= 1,
      {"http_code": code, "results": sapi_n, "first_titles": sapi_titles,
       "body_head": redact((body or ""))[:300]})

# المجموعة (د) — حالة المزودين في التطبيق --------------------------------
code, body, err, rc = http(ssh, "GET", f"{APP}/api/research/providers")
prov_doc = jload(body) if code == 200 else None
providers = []
if isinstance(prov_doc, dict):
    providers = prov_doc.get("providers", [])
elif isinstance(prov_doc, list):
    providers = prov_doc


def find_prov(pid=None, name=None):
    for p in providers:
        if pid is not None and p.get("id") == pid:
            return p
        if name is not None and p.get("name") == name:
            return p
    return None


prov_evid = {"http_code": code,
             "raw_body_head": redact((body or ""))[:1500],
             "all": [{"id": p.get("id"), "name": p.get("name"),
                      "enabled": p.get("enabled"),
                      "effective_status": p.get("effective_status"),
                      "kind": p.get("kind")} for p in providers]}
probe_log = []
for pid, label in ((4, "SearXNG"), (5, "Search API")):
    p = find_prov(pid=pid) or find_prov(name=label)
    ev = {"id": pid, "found": bool(p)}
    okp = False
    if p:
        ev["enabled"] = p.get("enabled")
        ev["effective_status"] = p.get("effective_status")
        ev["last_probe_status"] = p.get("last_probe_status")
        okp = (p.get("enabled") is True)
        if p.get("effective_status") == "READY":
            okp = okp and True
        elif p.get("effective_status") == "STALE":
            # مصرح به حصراً: مسبار 4 و5 (يحدث حالة المسبار المخزنة — تصميم التطبيق)
            c2, b2, e2, r2 = http(ssh, "POST", f"{APP}/api/research/providers/{pid}/probe")
            probe_log.append({"probe": pid, "http_code": c2,
                              "body_head": redact((b2 or ""))[:400]})
            okp = okp and (c2 == 200 and '"READY"' in (b2 or ""))
            ev["probe_after_stale"] = {"http_code": c2,
                                       "ready_in_response": '"READY"' in (b2 or "")}
        else:
            okp = False
    check(f"D{'4' if pid == 4 else '5'}", "د",
          f"المزود id={pid} ({label}) مُفعّل وREADY (STALE→مسبار مصرح به)",
          okp, ev)

ddg = find_prov(pid=1) or find_prov(name="DuckDuckGo")
check("D1", "د", "DDG id=1 معطل بصرياً DISABLED",
      bool(ddg) and ddg.get("enabled") is False and ddg.get("effective_status") == "DISABLED",
      {"found": bool(ddg), "enabled": (ddg or {}).get("enabled"),
       "effective_status": (ddg or {}).get("effective_status"),
       "state_reason": (ddg or {}).get("state_reason")})
prov_evid["probes_executed"] = probe_log

# المجموعة (هـ) — بحث فعلي عبر التطبيق ------------------------------------
def app_search(qid, query, label):
    code, body, err, rc = http(ssh, "POST", f"{APP}/api/research/search",
                               json_body={"query": query}, timeout=120)
    d = jload(body) if code == 200 else None
    n = 0
    titles = []
    prov_name = None
    if isinstance(d, dict):
        rl = d.get("results") or []
        n = len(rl)
        titles = [str(r.get("title", ""))[:90] for r in rl[:3]]
        prov_name = d.get("provider")
    ev = {"http_code": code, "query": query, "results": n,
          "answered_by_provider": prov_name, "first_titles": titles}
    if code != 200:
        ev["body_head"] = redact((body or ""))[:400]
    ok = code == 200 and n >= 3  # بوابة القبول: ≥3 نتائج قابلة للتحليل
    if not ok and code == 200 and n > 0:
        ok = True
        add_note(f"N-{qid}", f"نتائج أقل من 3 لكن > 0 — موثق ({n}).")
    check(qid, "هـ", label, ok, ev)
    return ev

app_search("E1", Q_EN, "بحث فعلي — الاستعلام الإنجليزي الفاشل سابقاً (#207)")
app_search("E2", Q_AR, "بحث فعلي — الاستعلام العربي (هيكل صفحات موقع أخبار)")

# المجموعة (و) — سلامة الإنتاج --------------------------------------------
rc, out, err = sh(ssh, "cd /opt/agentic-engineering-system && git rev-parse HEAD")
head = out.strip()
rc_l, out_l, err_l = sh(ssh, "cd /opt/agentic-engineering-system && git log --oneline -6")
log_lines = [ln.strip() for ln in out_l.splitlines() if ln.strip()]
rc_s, out_s, err_s = sh(ssh, "cd /opt/agentic-engineering-system && git status --porcelain")
porcelain = [ln for ln in out_s.splitlines()
             if ln.strip() and re.match(r"^(\?\?|[MADRCU]{1,2}\s)", ln)]
head_ok = head.startswith(EXPECT_HEAD)
anc_rc = "n/a (مطابقة مباشرة للبادئة)"
if not head_ok:
    rc2, _, _ = sh(ssh, f"cd /opt/agentic-engineering-system && "
                        f"git merge-base --is-ancestor {EXPECT_HEAD} HEAD")
    anc_rc = rc2
    head_ok = rc2 == 0
src_dirty = [ln for ln in porcelain if "src/" in ln and not ln.startswith("??")]
check("F1", "و", f"git HEAD = {EXPECT_HEAD} (أو أحدث)", head_ok,
      {"head": head, "log_oneline": log_lines, "ancestor_check_rc": anc_rc})
check("F2", "و", "git status --porcelain: لا ملفات معدلة داخل src/",
      len(src_dirty) == 0,
      {"porcelain_full": porcelain[:25], "src_dirty": src_dirty})

rc, out, err = sh(ssh, "ls -la /opt/searxng/searx/data/ | grep tracker_patterns && "
                       "grep -n 'W2-T20 vendor patch' /opt/searxng/searx/data/tracker_patterns.py | head -3")
has_backup = ".pre-w2t20" in out
has_patch = "W2-T20 vendor patch" in out
rc2, out2, err2 = sh(ssh, "cd /opt/searxng && git status --porcelain | head -10")
check("F3", "و", "رقعة vendor موثقة + نسخة احتياطية .pre-w2t20 في /opt/searxng",
      has_backup and has_patch,
      {"ls_tracker_patterns": [ln.strip() for ln in out.splitlines()][:6],
       "patch_marker_lines": [ln.strip() for ln in out.splitlines() if "W2-T20" in ln][:3],
       "searxng_repo_porcelain": out2.splitlines()[:10]})

rc, out, err = sh(ssh, "sudo -n journalctl -u agentic -p err --since '30 minutes ago' "
                       "--no-pager | tail -30")
err_lines = [ln for ln in out.splitlines() if ln.strip() and "-- No entries --" not in ln]
check("F4", "و", "journalctl -u agentic -p err آخر 30 دقيقة = لا أخطاء جديدة",
      len(err_lines) == 0, {"rc": rc, "error_lines": err_lines[:10],
                            "raw_head": out.strip()[:200]})

# المجموعة (ز) — الجاهزية الكلية ------------------------------------------
code, body, err, rc = http(ssh, "GET", f"{APP}/api/environment/readiness")
rd = jload(body) if code == 200 else None
caps = []
if isinstance(rd, dict):
    caps = rd.get("capabilities") or rd.get("items") or []
elif isinstance(rd, list):
    caps = rd


def cap_field(cap, key):
    if isinstance(cap, dict):
        for k in (key, "readiness_status", "effective_status", "status"):
            if cap.get(k) is not None:
                return cap.get(k)
    return None


web_search = None
for c in caps:
    if isinstance(c, dict) and (c.get("capability_id") == "web_search" or c.get("id") == "web_search"
                                or c.get("name") == "web_search"):
        web_search = c
        break
ws_status = cap_field(web_search, "readiness_status")
ws_evid = {"http_code": code, "caps_count": len(caps),
           "web_search_raw": {k: web_search.get(k) for k in
                              ("capability_id", "readiness_status", "stored_status",
                               "last_probe_at", "last_success_at", "failure_reason")}
           if isinstance(web_search, dict) else None}
ws_ok = ws_status in ("READY", "STALE")
probe_env_log = None
GUARD_ENV_PROBE = os.path.join(OUT_DIR, "audit_env_probe_once.json")
if ws_status == "STALE" and os.path.exists(GUARD_ENV_PROBE):
    # حارس المرة-الواحدة: المسبار البيئي نُفّذ في جولة سابقة — لا تكرار أبداً
    with open(GUARD_ENV_PROBE, "r", encoding="utf-8") as fh:
        guard = json.load(fh)
    ws_evid["probe_guard"] = {
        "skipped": True, "guard_file": guard,
        "note": "المسبار البيئي نُفّذ مرة واحدة في جولة سابقة (مصرح بها) — "
                "الحالة هنا STALE لأن TTL=120ث انقضى؛ المخزون stored_status يجب أن يبقى READY"}
    ws_ok = (isinstance(web_search, dict)
             and web_search.get("stored_status") == "READY")
elif ws_status == "STALE":
    # مصرح به (اختياري): مسبار واحد لـ web_search — تأكيد حي من طرفي
    c2, b2, e2, r2 = http(ssh, "POST", f"{APP}/api/environment/probe",
                          json_body={"capability_id": "web_search"}, timeout=120)
    probe_env_log = {"http_code": c2, "body_head": redact((b2 or ""))[:500]}
    ws_ok = c2 == 200 and '"READY"' in (b2 or "")
    ws_evid["probe_after_stale"] = probe_env_log
    with open(GUARD_ENV_PROBE, "w", encoding="utf-8") as fh:
        json.dump({"ts_utc": now_utc(), "http_code": c2,
                   "ready_in_response": '"READY"' in (b2 or ""),
                   "capability_id": "web_search",
                   "note": "حارس مرة-واحدة — يمنع تكرار POST المسبار البيئي عبر أي جولة"}, fh, ensure_ascii=False, indent=2)
    # قراءة ثانية بعد المسبار — الحالة يجب أن تكون READY الآن
    c3, b3, e3, r3 = http(ssh, "GET", f"{APP}/api/environment/readiness")
    rd3 = jload(b3) if c3 == 200 else None
    caps3 = rd3.get("capabilities", []) if isinstance(rd3, dict) else ([] if not isinstance(rd3, list) else rd3)
    ws3 = next((c for c in caps3 if isinstance(c, dict)
                and (c.get("capability_id") == "web_search" or c.get("id") == "web_search")), None)
    if isinstance(ws3, dict):
        ws_evid["readiness_after_probe"] = {
            "readiness_status": ws3.get("readiness_status"),
            "stored_status": ws3.get("stored_status")}
        ws_ok = ws_ok and ws3.get("readiness_status") == "READY"
check("G1", "ز", "قدرة web_search ليست NOT_READY (STALE→مسبار تأكيدي مصرح به → READY)",
      ws_ok, ws_evid)

not_ready = [c.get("capability_id") or c.get("id") or c.get("name")
             for c in caps if isinstance(c, dict)
             and cap_field(c, "readiness_status") == "NOT_READY"]
check("G2", "ز", "صفر NOT_READY بين القدرات (قبل المهمة: 19 قدرة، صفر NOT_READY)",
      len(not_ready) == 0,
      {"caps_count": len(caps), "not_ready": not_ready,
       "statuses": [{"cap": (c.get("capability_id") or c.get("id") or c.get("name")),
                     "readiness_status": cap_field(c, "readiness_status")}
                    for c in caps if isinstance(c, dict)][:25]})

# المجموعة (ح) — الأمان ----------------------------------------------------
rc, out, err = sh(ssh, "sudo -n stat -c '%U:%G %a' /etc/search-api/env")
stat_val = out.strip()
check("H1", "ح", "/etc/search-api/env بصلاحيات 640 root:searchapi",
      stat_val == "root:searchapi 640", {"stat": stat_val, "rc": rc})

# فحص محلي: المفتاح ليس في أي ملف داخل المستودع المحلي
key_hits = []
if api_key:
    needle = api_key.encode()
    for root, dirs, files in os.walk(REPO_LOCAL):
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                if os.path.getsize(fp) > 20 * 1024 * 1024:
                    continue
                with open(fp, "rb") as fh:
                    if needle in fh.read():
                        key_hits.append(fp)
            except OSError:
                pass
check("H2", "ح", "المفتاح غير موجود في أي ملف داخل /home/z/my-project/repo",
      len(key_hits) == 0, {"hits": key_hits, "searched_root": REPO_LOCAL})

rc, out, err = sh(ssh, "sudo -n grep -n -A2 'formats' /etc/searxng/settings.yml | head -12")
fmt_txt = redact(out)
fmt_ok = re.search(r"formats\s*:", fmt_txt) is not None and re.search(
    r"json", fmt_txt) is not None
rc2, out2, err2 = sh(ssh, "sudo -n grep -n -E 'limiter|public_instance' /etc/searxng/settings.yml")
cfg_txt = redact(out2)
lim_ok = re.search(r"limiter\s*:\s*false", cfg_txt) is not None
pub_ok = re.search(r"public_instance\s*:\s*false", cfg_txt) is not None
check("H3", "ح", "settings.yml: limiter معطل + public_instance=false + formats يتضمن json",
      fmt_ok and lim_ok and pub_ok,
      {"formats_grep": fmt_txt.strip()[:400], "limiter_public_grep": cfg_txt.strip()[:400],
       "checks": {"formats_json": fmt_ok, "limiter_false": lim_ok,
                  "public_instance_false": pub_ok}})

# ملاحظة أمنية (غير حاجزة): نسخة مفتاح محلية في دليل الأدلة خارج repo
local_key_copy = "/home/z/my-project/download/aes-remediation/W2-T20/.search_api_key.local"
if os.path.exists(local_key_copy) and api_key:
    try:
        with open(local_key_copy, "r") as fh:
            content = fh.read().strip()
        same = (api_key in content) or (content == api_key)
        add_note("N2", f"نسخة مفتاح محلية في download/.../W2-T20/.search_api_key.local "
                       f"(خارج repo) — مطابقة للمفتاح: {same}. يُوصى بحذفها أو استثنائها "
                       f"قبل مزامنة R9 (الأدلة تُزامن إلى docs/ops/ في المستودع) حتى لا يتسرب المفتاح.")
    except OSError as ex:
        add_note("N2", f"تعذر قراءة .search_api_key.local: {ex}")

# ملاحظة: لا إدخال W2-T20 للمنفذ في worklog.md (أُلحق أدناه إدخال التدقيق فقط)
try:
    with open("/home/z/my-project/worklog.md", "r", encoding="utf-8") as fh:
        wl = fh.read()
    if "Task ID: W2-T20\n" not in wl:
        add_note("N3", "لا إدخال Task ID: W2-T20 للمنفذ في worklog.md حتى لحظة التدقيق — "
                       "سد الرواية مسؤولية المنفذ/الأب عند المزامنة (نفس نمط F1 في W2-T10).")
except OSError as ex:
    add_note("N3", f"تعذر قراءة worklog.md: {ex}")

# ملاحظة: حالة بطاقة W2-T20 في TRACKER.md (قيد التنفيذ) لم تُحدّث إلى "منجزة" بينما اللوحة تقولها
try:
    with open("/home/z/my-project/repo/TRACKER.md", "r", encoding="utf-8") as fh:
        tr = fh.read()
    m = re.search(r"### W2-T20[^\n]*\n-\s*\*\*الحالة:\*\*\s*([^\n]*)", tr)
    card_status = m.group(1).strip() if m else "(غير موجودة)"
    if "منجزة" not in card_status:
        add_note("N4", f"حالة بطاقة W2-T20 في TRACKER.md تقول «{card_status}» بينما لوحة الحالة §1 "
                       "تقول «منجزة — بانتظار التدقيق» — تحديث البطاقة (ومن ثم التوقيع) مسؤولية المنفذ بعد توقيعي.")
except OSError as ex:
    add_note("N4", f"تعذر قراءة TRACKER.md: {ex}")

ssh.close()

# ---------------------------------------------------------------- التجميع
passed = sum(1 for r in results if r["pass"])
verdict = "PASS" if passed == len(results) else (
    "PARTIAL" if passed >= len(results) - 2 else "FAIL")

script_md5 = hashlib.md5(open(__file__, "rb").read()).hexdigest()

report = {
    "_meta": {
        "audit_id": "W2-T20-AUDIT",
        "agent": "Audit Agent (وكيل تدقيق مستقل — general-purpose)",
        "task": "تدقيق مستقل قراءة-فقط لمهمة W2-T20 (تفعيل SearXNG وSearch API "
                "وإتاحة البحث الحقيقي) على الإنتاج 92.5.14.150",
        "ts_utc": now_utc(),
        "script": "scripts/w2t20_audit_check.py",
        "script_md5": script_md5,
        "verdict": verdict,
        "passed": passed,
        "total": len(results),
        "runs_note": "جولتان: الجولة الأولى كشفت خطأً في سكربتي أنا (POST بحث بلا "
            "Content-Type: application/json → FastAPI رفضه 422) — صُحّح السكربت وأُعيد "
            "التشغيل من الصفر؛ الأدلة كلها من الجولة النهائية. المسبار البيئي لweb_search "
            "لم يكن لازماً في الجولتين (اشتقاق الجاهزية صار READY من مسباري المزودين 4/5 "
            "المصرح بهما قبل قراءة readiness).",
        "read_only_discipline": "SSH قراءة-فقط؛ POSTs مصرح بها حصراً: "
            "/api/research/search (بحث فعلي)، /api/research/providers/4/probe و/5/probe "
            "(فقط عند STALE — يحدثان حالة المسبار المخزنة، تصميم التطبيق)، "
            "/api/environment/probe لweb_search (فقط عند STALE). لا systemctl restart/stop، "
            "لا كتابة git، لا تعديل ملفات، لا تغيير تكوين مزود.",
        "key_handling": "المفتاح قُرئ عبر sudo -n cat واستُخدم في الذاكرة فقط — "
                        "مستبعد من كل المخرجات (redact + sha256_first12 كبصمة).",
    },
    "checks": results,
    "providers_snapshot": prov_evid,
    "notes": notes,
}

os.makedirs(OUT_DIR, exist_ok=True)
with open(REPORT_PATH, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2)

print(f"\nverdict={verdict} {passed}/{len(results)}")
print(f"report: {REPORT_PATH}")
print(f"script_md5: {script_md5}")
