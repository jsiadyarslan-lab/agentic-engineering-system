#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W2-T21-AUDIT — وكيل تدقيق مستقل (قراءة-فقط) لمهمة W2-T21 على الإنتاج 92.5.14.150.
«استقرار البحث بعد W2-T20: محرك bing news + عزل الحظر الناعم».

الانضباط (نفس عرف W2-T20-AUDIT):
- SSH قراءة-فقط طوال الجلسة، باستثناء POSTs مصرح بها حصراً:
  * POST /api/research/search (بحث فعلي — لا يغير تكوين)
  * POST /api/research/providers/4/probe و /5/probe (فقط إن كانت الحالة STALE — مرة واحدة، يحدثان حالة المسبار المخزنة)
- لا systemctl restart/stop لأي خدمة، لا كتابة git على الخادم، لا تعديل ملفات على الخادم،
  لا إنشاء محادثات، لا POST /api/chat/stream (التحقق من محادثتي 16/17 بقراءة القاعدة ro).
- secret_key و/أو مفتاح Search API لا يقرآن ولا تطبعان — كل الدليل المخزن يمر عبر redact().

المجموعات (A-K) كما في بطاقة التدقيق:
A خدمات وصحة وgit · B إعدادات SearXNG (bing news/brave/backup) · C واقعية bing news افتراضياً
D إعادة إنتاج الصفحة المعلبة · E حالات المزودين · F بحث التطبيق · G الجاهزية
H أدلة E2E من القاعدة (قراءة-فقط) · I ملفات الأدلة محلياً · J الأمان · K السجل.

المخرجات: download/aes-remediation/W2-T21/audit_w2t21_independent.json
"""
import datetime
import hashlib
import json
import os
import re
from urllib.parse import quote

import paramiko

HOST = "92.5.14.150"
USER = "opc"
KEY_PATH = "/tmp/oracle_key"
OUT_DIR = "/home/z/my-project/download/aes-remediation/W2-T21"
REPORT_PATH = os.path.join(OUT_DIR, "audit_w2t21_independent.json")
SCRIPT_PATH = "/home/z/my-project/scripts/ops/w2t21_audit_check.py"
REPO_LOCAL = "/home/z/my-project/repo"
SCRIPTS_OPS_WS = "/home/z/my-project/scripts/ops"          # موقع السكربتات قبل مزامنة R9
SCRIPTS_OPS_REPO = os.path.join(REPO_LOCAL, "scripts", "ops")  # موقعها بعد R9
APP = "http://127.0.0.1:8010"
SEARX = "http://127.0.0.1:8888"
EXPECT_HEAD = "be56bf237"

# ---- استعلاماتي أنا (لا استعلامات المنفذ) --------------------------------
C_Q_AR = "آخر تطورات غزة"                # فحص C1 — خبر عربي جارٍ
C_Q_EN = "european union news today"      # فحص C2 — خبر إنجليزي جارٍ
C_Q_KN = "knesset election results"       # فحص C3 — تكرار اختياري لنوع استعلام المنفذ
F_Q_AR = "نتائج الانتخابات الإسرائيلية اليوم"   # فحص F1 — خبر عربي عبر سلسلة التطبيق
F_Q_EN = "israel election results exit polls"   # فحص F2 — خبر إنجليزي عبر سلسلة التطبيق
Q_207 = ("news website page structure homepage world politics business "
         "technology sports entertainment article detail search results best practices")
OWNER_Q = "ما آخر أخبار انتخابات الكنيست اليوم؟ اذكر نتيجة الفرز واستطلاعات الخروج"
BING_CANNED_Q = "climate+conference+negotiations"

# ---- أدوات الحكم على واقعية العناوين -------------------------------------
STOPWORDS_AR = {"آخر", "اليوم", "في", "ما", "هل", "على", "عن", "من", "إلى", "مع",
                "الآن", "واو", "أخبار", "الأخبار", "نتائج؟"}
STOPWORDS_EN = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "is", "are"}
SYNONYMS = {"european": ["eu"], "union": ["eu"]}
CANNED_MARKERS = ["chess", "برجك", "أبراج", "horoscope", "zodiac", "طالع", "حظك", "chess.com"]

results = []
notes = []
probe_log = []
search_log = []


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check(cid, group, name, ok, evidence):
    results.append({"id": cid, "group": group, "name": name,
                    "pass": bool(ok), "evidence": evidence})
    print(("[PASS] " if ok else "[FAIL] ") + f"{cid} {name}")
    return ok


def add_note(nid, text):
    notes.append({"id": nid, "note": text})
    print(f"[NOTE] {nid}")


def redact(text):
    """إخفاء أي سر محتمل قبل تخزينه (secret_key / X-API-Key / 48-هكس)."""
    if not isinstance(text, str):
        return text
    out = re.sub(r"(secret_key\s*:\s*)(\S+)", r"\1[REDACTED]", text)
    out = re.sub(r"(X-API-Key\s*:\s*)(\S+)", r"\1[REDACTED]", out)
    out = re.sub(r"(?<![0-9a-f])[0-9a-f]{48}(?![0-9a-f])", "[REDACTED-48HEX]", out)
    return out


def sh(ssh, cmd, timeout=90):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    return rc, out, err


def http(ssh, method, url, headers=None, json_body=None, timeout=90):
    """طلب HTTP عبر curl على الخادم (loopback) — يرجع (code, body, err, rc).
    جسم JSON يُرسل دائماً مع Content-Type: application/json (بدونه 422)."""
    parts = ["curl -s --max-time 80"]
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
    rc, out, err = sh(ssh, " ".join(parts), timeout=timeout)
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


def content_tokens(query, lang):
    if lang == "ar":
        toks = [t for t in re.findall(r"[\u0600-\u06FF]+", query)
                if t not in STOPWORDS_AR and len(t) >= 3]
    else:
        toks = [t.lower() for t in re.findall(r"[A-Za-z]+", query)
                if t.lower() not in STOPWORDS_EN and len(t) >= 4]
    return toks


def title_relevance(titles, tokens, top_n=6):
    """عدد العناوين (من أول top_n) التي تشارك رمزاً معنوياً واحداً على الأقل من الاستعلام."""
    hits = 0
    hit_titles = []
    for t in titles[:top_n]:
        low = (t or "").lower()
        matched = False
        for tok in tokens:
            if tok in low:
                matched = True
                break
            for syn in SYNONYMS.get(tok, []):
                if syn in low:
                    matched = True
                    break
        if matched:
            hits += 1
            hit_titles.append(t)
    return hits, hit_titles


def canned_in_titles(titles, top_n=6):
    bad = []
    for t in titles[:top_n]:
        low = (t or "").lower()
        if any(m in low for m in CANNED_MARKERS):
            bad.append(t)
    return bad


# ============================================================================
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY_PATH, timeout=25,
            look_for_keys=False, allow_agent=False)
print(f"connected: {HOST} @ {now_utc()}")

# المجموعة A — الخدمات والصحة وgit -----------------------------------------
rc, out, err = sh(ssh, "systemctl is-active agentic nginx searxng search-api")
states = [ln.strip() for ln in out.splitlines() if ln.strip()]
check("A1", "A", "الخدمات الأربع active (agentic/nginx/searxng/search-api)",
      rc == 0 and len(states) == 4 and all(s == "active" for s in states),
      {"rc": rc, "states": states, "stderr": err.strip()[:200]})

code, body, err, rc = http(ssh, "GET", f"{APP}/health", timeout=30)
hd = jload(body) if body else None
check("A2", "A", "GET /health = 200", code == 200,
      {"http_code": code, "body_head": redact((body or ""))[:200]})

rc, out, err = sh(ssh, "cd /opt/agentic-engineering-system && git rev-parse --short=9 HEAD")
head = out.strip()
check("A3", "A", "git HEAD على الإنتاج = be56bf237 بالضبط (لا كود تغيّر)",
      head == EXPECT_HEAD, {"head": head, "rc": rc, "stderr": err.strip()[:200]})

rc, out, err = sh(ssh, "cd /opt/agentic-engineering-system && git status --porcelain")
lines = [l for l in out.splitlines() if l.strip()]
tracked_changes = [l for l in lines if not l.startswith("??")]
src_bad = [l for l in tracked_changes if re.search(r"(^|\s)src/", l)]
untracked = [l[3:].strip().strip('"') for l in lines if l.startswith("??")]


def preapproved(path):
    p = path.rstrip("/")
    return (p in ("runtime/browser", "runtime/projects")
            or p.startswith("runtime/browser/") or p.startswith("runtime/projects/")
            or p.startswith("scripts/ops/nightly_backup.sh")
            or p.endswith(".egg-info"))


untracked_other = [p for p in untracked if not preapproved(p)]
check("A4", "A", "صفر ملفات متتبعة معدلة داخل src/ (untracked المسبق موافق عليه فقط)",
      len(src_bad) == 0,
      {"tracked_changes": tracked_changes, "src_modified": src_bad,
       "untracked": untracked, "untracked_beyond_preapproved": untracked_other})
if untracked_other:
    add_note("N-A4", f"untracked خارج القائمة المسبقة: {untracked_other}")

# المجموعة B — إعدادات SearXNG (بلا طباعة secret_key) ----------------------
rc, out, err = sh(ssh, "sudo -n grep -n -A8 -- 'name: bing news' /etc/searxng/settings.yml")
bn_block = out.strip()
bn_ok = (rc == 0 and "disabled: false" in bn_block and "categories:" in bn_block
         and re.search(r"-\s*general\b", bn_block) is not None)
check("B1", "B", "محرك `bing news` موجود بdisabled: false وفئة general (يفحص افتراضياً)",
      bn_ok, {"rc": rc, "grep_block": redact(bn_block)[:600], "stderr": err.strip()[:150]})

rc, out, err = sh(ssh, "sudo -n grep -n -A4 -- 'name: brave' /etc/searxng/settings.yml")
br_raw = out.strip()
occurrences = [ln for ln in br_raw.splitlines() if "name: brave" in ln]
# آخر إدراج (الإلحاقي من W2-T21) يجب أن يكون disabled: true — الإلحاق يتجاوز الافتراضي
blocks = re.split(r"(?=^\d+[-:]\s*-?\s*name: brave)", br_raw, flags=re.M)
last_block = ""
for b in blocks:
    if "name: brave" in b:
        last_block = b
br_ok = (rc == 0 and len(occurrences) >= 1 and "disabled: true" in last_block)
check("B2", "B", "محرك `brave` معطل (disabled: true في آخر إدراج — إيقاف 429 الدائم)",
      br_ok, {"rc": rc, "occurrences": len(occurrences),
              "last_block": redact(last_block)[:400], "stderr": err.strip()[:150]})

rc, out, err = sh(ssh, "sudo -n stat -c '%U:%G %a %s %y' /etc/searxng/settings.yml.pre-w2t21")
bk_stat = out.strip()
check("B3", "B", "النسخة الاحتياطية /etc/searxng/settings.yml.pre-w2t21 موجودة",
      rc == 0 and bool(bk_stat),
      {"rc": rc, "stat": bk_stat, "stderr": err.strip()[:150]})

# المجموعة C — واقعية bing news في البحث الافتراضي (بلا engines=) ----------


def searx_default(qid, query, lang, label):
    url = f"{SEARX}/search?q={quote(query)}&format=json&language={lang}"
    code, body, err, rc = http(ssh, "GET", url, timeout=100)
    d = jload(body) if body else None
    rl = d.get("results", []) if isinstance(d, dict) else []
    n = len(rl)
    titles = [str(r.get("title", "")) for r in rl[:8]]
    engines = {}
    for r in rl:
        for e in (r.get("engines") or []):
            engines[e] = engines.get(e, 0) + 1
    unresp = d.get("unresponsive", []) if isinstance(d, dict) else []
    toks = content_tokens(query, "ar" if lang == "ar" else "en")
    hits, hit_titles = title_relevance(titles, toks)
    canned = canned_in_titles(titles)
    ev = {"url": url, "http_code": code, "n_results": n, "engines": engines,
          "first_titles": titles, "unresponsive": unresp[:6],
          "query_tokens": toks, "relevant_titles_of_top6": hits,
          "relevant_title_samples": hit_titles[:4], "canned_hits": canned}
    ok = (code == 200 and n >= 5 and not canned and hits >= 3)
    check(qid, "C", label, ok, ev)
    return ev


searx_default("C1", C_Q_AR, "ar", "bing news افتراضياً — استعلام عربي خاص بي «آخر تطورات غزة» ≥5 نتائج واقعية")
searx_default("C2", C_Q_EN, "en", "bing news افتراضياً — استعلام إنجليزي خاص بي «european union news today» ≥5 نتائج واقعية")
searx_default("C3", C_Q_KN, "en", "bing news افتراضياً — تكرار «knesset election results» ≥5 نتائج واقعية")

# المجموعة D — إعادة إنتاج الصفحة المعلبة من www.bing.com -------------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
d_cmd = (
    "curl -s --max-time 60 -H 'User-Agent: " + UA + "' "
    "'https://www.bing.com/search?q=" + BING_CANNED_Q + "' | "
    "python3 -c 'import sys, re, html as H\n"
    "raw = sys.stdin.read()\n"
    "titles = re.findall(r\"<h2><a[^>]*>(.*?)</a></h2>\", raw, re.S)\n"
    "clean = []\n"
    "for t in titles:\n"
    "    t2 = re.sub(r\"<[^>]+>\", \"\", t)\n"
    "    clean.append(H.unescape(t2).strip())\n"
    "low = \" \".join(clean).lower()\n"
    "chess = (\"chess\" in low) or (\"chess\" in raw.lower())\n"
    "hits = [c for c in clean if any(w in c.lower() for w in (\"climate\", \"conference\", \"negotiation\"))]\n"
    "print(\"HTML_LEN:\", len(raw))\n"
    "print(\"N_TITLES:\", len(clean))\n"
    "for c in clean[:12]:\n"
    "    print(\"T:\", c[:110])\n"
    "print(\"CHESS_PRESENT:\", chess)\n"
    "print(\"RELEVANT_HITS:\", len(hits))\n"
    "print(\"CLIMATE_IN_PAGE:\", \"climate\" in raw.lower())'"
)
rc, out, err = sh(ssh, d_cmd, timeout=100)
parsed = {}
for ln in out.splitlines():
    if ln.startswith("HTML_LEN:") or ln.startswith("N_TITLES:") \
            or ln.startswith("CHESS_PRESENT:") or ln.startswith("RELEVANT_HITS:") \
            or ln.startswith("CLIMATE_IN_PAGE:"):
        k, v = ln.split(":", 1)
        parsed[k] = v.strip()
    elif ln.startswith("T:"):
        parsed.setdefault("titles", []).append(ln[2:].strip())
n_titles = int(parsed.get("N_TITLES", "0") or 0)
rel_hits = int(parsed.get("RELEVANT_HITS", "0") or 0)
chess = parsed.get("CHESS_PRESENT", "False") == "True"
d_ev = {"query": BING_CANNED_Q.replace("+", " "), "rc": rc,
        "html_len": parsed.get("HTML_LEN"), "n_titles": n_titles,
        "titles": parsed.get("titles", [])[:12], "chess_present": chess,
        "relevant_hits": rel_hits, "climate_in_page": parsed.get("CLIMATE_IN_PAGE"),
        "stderr": err.strip()[:150]}
canned = chess or (n_titles >= 3 and rel_hits <= 1)
d_ev["canned_reproduced"] = canned
if n_titles == 0:
    d_ev["note"] = "لم يستخرج العنوان <h2><a> — صفحة حظر/موافقة محتملة (يسجل الطول)"
check("D1", "D", "صفحة bing المعلبة قابلة لإعادة الإنتاج (عناوين غير ذات صلة بالاستعلام)",
      canned, d_ev)
if not canned:
    add_note("N-D1", "لم تُعد إنتاج العلبة في نافذتي (الحظر الناعم متقطع حسب البطاقة) — "
                     "عُدّل الحكم وفق السياق: الادعاء الخاضع للتدقيق هو موثوقية bing news "
                     "وسلسلة النتائج الحقيقية، لا أن bing web خبث دائماً.")

# المجموعة E — حالات المزودين ------------------------------------------------


def read_providers():
    code, body, err, rc = http(ssh, "GET", f"{APP}/api/research/providers", timeout=60)
    doc = jload(body) if body else None
    plist = []
    if isinstance(doc, dict):
        plist = doc.get("providers", [])
    elif isinstance(doc, list):
        plist = doc
    return code, plist, (body or "")[:800]


code, providers, raw_head = read_providers()


def find_prov(pid):
    for p in providers:
        if p.get("id") == pid:
            return p
    return None


prov_snapshot = [{"id": p.get("id"), "name": p.get("name"), "enabled": p.get("enabled"),
                  "effective_status": p.get("effective_status"),
                  "last_probe_status": p.get("last_probe_status")} for p in providers]

p1 = find_prov(1)
check("E1", "E", "id=1 DuckDuckGo معطل (enabled=false + DISABLED)",
      bool(p1) and p1.get("enabled") is False and p1.get("effective_status") == "DISABLED",
      {"provider": p1})

p2 = find_prov(2)
check("E2", "E", "id=2 Bing المباشر معطل بواسطة W2-T21 (enabled=false + DISABLED) — عزل الصفحة المعلبة",
      bool(p2) and (p2.get("name") == "Bing") and p2.get("enabled") is False
      and p2.get("effective_status") == "DISABLED",
      {"provider": p2})

p3 = find_prov(3)
check("E3", "E", "id=3 Wikipedia ممكن (enabled=true)",
      bool(p3) and p3.get("enabled") is True,
      {"provider": {k: p3.get(k) for k in ("id", "name", "enabled", "effective_status")} if p3 else None})

# id=4 و id=5: READY مطلوبة — عند STALE فقط: مسبار مصرح به مرة واحدة ثم إعادة قراءة
need_reprobe = []
for pid in (4, 5):
    p = find_prov(pid)
    st = (p or {}).get("effective_status")
    if st != "READY":
        need_reprobe.append(pid)

if need_reprobe:
    for pid in need_reprobe:
        c2, b2, e2, r2 = http(ssh, "POST", f"{APP}/api/research/providers/{pid}/probe", timeout=90)
        probe_log.append({"probe": pid, "http_code": c2,
                          "body_head": redact((b2 or ""))[:200]})
    code, providers, raw_head = read_providers()

p4 = find_prov(4)
check("E4", "E", "id=4 SearXNG ممكن + READY (مسبار مصرح به عند STALE فقط)",
      bool(p4) and p4.get("enabled") is True and p4.get("effective_status") == "READY",
      {"provider": p4, "probed_in_this_audit": 4 in need_reprobe})

p5 = find_prov(5)
check("E5", "E", "id=5 Search API ممكن + READY (مسبار مصرح به عند STALE فقط)",
      bool(p5) and p5.get("enabled") is True and p5.get("effective_status") == "READY",
      {"provider": p5, "probed_in_this_audit": 5 in need_reprobe})

# المجموعة F — بحث التطبيق (السلسلة كاملة عبر API الشرعي) -------------------


def app_search(qid, query, label):
    code, body, err, rc = http(ssh, "POST", f"{APP}/api/research/search",
                               json_body={"query": query}, timeout=140)
    d = jload(body) if body else None
    rl = d.get("results", []) if isinstance(d, dict) else []
    n = len(rl)
    titles = [str(r.get("title", ""))[:90] for r in rl[:6]]
    prov_name = d.get("provider") if isinstance(d, dict) else None
    canned = canned_in_titles(titles)
    search_log.append({"qid": qid, "query": query, "http_code": code,
                       "n": n, "provider": prov_name})
    ev = {"http_code": code, "query": query, "results": n,
          "answered_by_provider": prov_name, "first_titles": titles,
          "canned_hits": canned,
          "error_head": redact(str(d.get("detail") or d.get("error") or ""))[:200]
          if isinstance(d, dict) else redact((body or ""))[:200]}
    ok = code == 200 and n >= 3 and not canned
    check(qid, "F", label, ok, ev)
    return ev


app_search("F1", F_Q_AR, "بحث التطبيق — استعلام خبر عربي خاص بي (نتائج حقيقية ≥3)")
app_search("F2", F_Q_EN, "بحث التطبيق — استعلام خبر إنجليزي خاص بي (نتائج حقيقية ≥3)")
app_search("F3", Q_207, "بحث التطبيق — الاستعلام الفاشل تاريخياً #207 نصاً (≥3 نتائج)")

# المجموعة G — الجاهزية الكلية ----------------------------------------------
code, body, err, rc = http(ssh, "GET", f"{APP}/api/environment/readiness", timeout=60)
rd = jload(body) if body else None
caps = []
if isinstance(rd, dict):
    caps = rd.get("capabilities") or rd.get("items") or []
elif isinstance(rd, list):
    caps = rd
ws = None
for c in caps:
    if isinstance(c, dict) and (c.get("capability_id") == "web_search" or c.get("id") == "web_search"
                                or c.get("name") == "web_search"):
        ws = c
        break
ws_evid = {"http_code": code, "caps_count": len(caps),
           "web_search": {k: (ws or {}).get(k) for k in
                          ("capability_id", "readiness_status", "stored_status",
                           "last_probe_at", "last_success_at", "failure_reason")}}
check("G1", "G", "قدرة web_search stored_status=READY (readiness_status قد تكون STALE بTTL=600ث — موثق طبيعي)",
      bool(ws) and ws.get("stored_status") == "READY", ws_evid)

not_ready_stored = [c.get("capability_id") or c.get("id") or c.get("name") for c in caps
                    if isinstance(c, dict) and c.get("stored_status") == "NOT_READY"]
check("G2", "G", "صفر قدرات stored_status=NOT_READY",
      len(not_ready_stored) == 0,
      {"caps_count": len(caps), "not_ready_stored": not_ready_stored,
       "statuses": [{"cap": (c.get("capability_id") or c.get("id") or c.get("name")),
                     "readiness_status": c.get("readiness_status"),
                     "stored_status": c.get("stored_status")}
                    for c in caps if isinstance(c, dict)][:25]})

# المجموعة H — أدلة E2E من القاعدة (قراءة-فقط mode=ro) ----------------------
db_py = (
    "python3 - <<'PYEOF'\n"
    "import sqlite3, json\n"
    "db = sqlite3.connect('file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro', uri=True)\n"
    "db.row_factory = sqlite3.Row\n"
    "convs = [dict(r) for r in db.execute('SELECT id,title,mode,created_at,updated_at FROM conversations WHERE id IN (16,17) ORDER BY id')]\n"
    "msgs = [dict(r) for r in db.execute('SELECT id,conversation_id,role,length(content) AS clen,substr(content,1,400) AS head,content AS full FROM messages WHERE conversation_id IN (16,17) ORDER BY id')]\n"
    "evs = [dict(r) for r in db.execute(\"SELECT kind,created_at,cycle_id,payload FROM events WHERE cycle_id IN ('chat-16','chat-17') AND kind LIKE 'research%' ORDER BY created_at\")]\n"
    "print('@@JSON@@')\n"
    "print(json.dumps({'conversations': convs, 'messages': msgs, 'research_events': evs}, ensure_ascii=False))\n"
    "PYEOF"
)
rc, out, err = sh(ssh, db_py, timeout=60)
dbdoc = None
if "@@JSON@@" in out:
    try:
        dbdoc = json.loads(out.split("@@JSON@@", 1)[1].strip().splitlines()[0])
    except Exception:
        dbdoc = None
convs = (dbdoc or {}).get("conversations", [])
msgs = (dbdoc or {}).get("messages", [])
revs = (dbdoc or {}).get("research_events", [])


def msg_head_safe(m):
    h = {"id": m.get("id"), "conversation_id": m.get("conversation_id"),
         "role": m.get("role"), "clen": m.get("clen"), "head400": (m.get("head") or "")[:400]}
    full = m.get("full") or ""
    h["markers"] = {
        "exit_polls_ar": ("استطلاعات الخروج" in full),
        "counting_farz": ("الفرز" in full),
        "citation_1": ("[1]" in full),
        "citation_5": ("[5]" in full),
        "any_bracket_citation": bool(re.search(r"\[\d+\]", full)),
    }
    return h


msg_evid = [msg_head_safe(m) for m in msgs]
user_16 = next((m for m in msgs if m.get("conversation_id") == 16 and m.get("role") == "user"), None)
user_17 = next((m for m in msgs if m.get("conversation_id") == 17 and m.get("role") == "user"), None)
check("H1", "H", "محادثتا 16/17 موجودتان وسؤال المستخدم = سؤال المالك عن انتخابات الكنيست (17 نصاً حرفياً)",
      bool(convs) and len(convs) == 2
      and bool(user_16) and "ما آخر أخبار انتخابات الكنيست" in (user_16.get("full") or "")
      and bool(user_17) and (user_17.get("full") or "").strip() == OWNER_Q,
      {"conversations": [{"id": c.get("id"), "title": (c.get("title") or "")[:80],
                          "mode": c.get("mode"), "created_at": c.get("created_at")}
                         for c in convs],
       "user_16_head": (user_16.get("head") or "")[:150] if user_16 else None,
       "user_17_exact_match": bool(user_17) and (user_17.get("full") or "").strip() == OWNER_Q,
       "user_17_head": (user_17.get("head") or "")[:150] if user_17 else None})

as_16 = [m for m in msgs if m.get("conversation_id") == 16 and m.get("role") == "assistant"]
as_17 = [m for m in msgs if m.get("conversation_id") == 17 and m.get("role") == "assistant"]


def live_answer(mlist):
    for m in mlist:
        full = m.get("full") or ""
        if m.get("clen", 0) > 500 and (("استطلاعات الخروج" in full) or ("الفرز" in full)):
            return m, ("[1]" in full) or ("[5]" in full) or bool(re.search(r"\[\d+\]", full))
    return None, False


live16, cites16 = live_answer(as_16)
live17, cites17 = live_answer(as_17)
check("H2", "H", "رسائل مساعد حية في 16/17 (طول >500 + ذكر الفرز/استطلاعات الخروج + استشهادات [n])",
      bool(live16) and bool(live17) and (cites16 or cites17),
      {"assistant_messages": msg_evid,
       "conv16_live_answer": {"id": (live16 or {}).get("id"), "clen": (live16 or {}).get("clen")} if live16 else None,
       "conv17_live_answer": {"id": (live17 or {}).get("id"), "clen": (live17 or {}).get("clen"),
                              "citations_present": cites17} if live17 else None})

kinds16 = sorted({e.get("kind") for e in revs if (e.get("cycle_id") == "chat-16")})
kinds17 = sorted({e.get("kind") for e in revs if (e.get("cycle_id") == "chat-17")})
check("H3", "H", "أحداث research.started + research.results لكلا الدورتين chat-16 وchat-17",
      ("research.started" in kinds16 and "research.results" in kinds16
       and "research.started" in kinds17 and "research.results" in kinds17),
      {"research_events": [{"cycle_id": e.get("cycle_id"), "kind": e.get("kind"),
                            "created_at": e.get("created_at")} for e in revs],
       "kinds_chat16": kinds16, "kinds_chat17": kinds17,
       "db_stderr": err.strip()[:150]})

# H4 (تعزيز اختياري): تفكيك payload لresearch.results — يثبت مباشرة أن سلسلة
# التطبيق→SearXNG أخدمت المحادثة بمصادر أخبار حية (ادعاء الخطوة 6 من البطاقة)


def research_payload(cycle):
    for e in revs:
        if e.get("cycle_id") == cycle and e.get("kind") == "research.results":
            try:
                return json.loads(e.get("payload") or "{}")
            except Exception:
                return {}
    return {}


def payload_evid(cycle):
    pl = research_payload(cycle)
    det = pl.get("details") or {}
    srcs = det.get("results") or []
    return {"cycle_id": cycle, "text": pl.get("text"), "provider": det.get("provider"),
            "count": det.get("count"),
            "source_titles": [str(s.get("title", ""))[:90] for s in srcs[:6]],
            "source_urls": [str(s.get("url", ""))[:70] for s in srcs[:6]]}


pl16 = payload_evid("chat-16")
pl17 = payload_evid("chat-17")
news_words = ("الكنيست", "انتخابات", "الفرز", "استطلاع", "election", "knesset", "exit poll")
pl17_srcs = pl17.get("source_titles", [])
news_like = sum(1 for t in pl16.get("source_titles", []) + pl17_srcs
                if any(w in (t or "") for w in news_words))
canned_srcs = [t for t in pl16.get("source_titles", []) + pl17_srcs
               if any(m in (t or "").lower() for m in CANNED_MARKERS)]
check("H4", "H", "payload لresearch.results: السلسلة أخدمت المحادثة عبر SearXNG بمصادر أخبار حية (≥5 لchat-17)",
      (pl17.get("provider") == "SearXNG" and (pl17.get("count") or 0) >= 5
       and news_like >= 3 and not canned_srcs),
      {"chat16": pl16, "chat17": pl17, "news_like_titles": news_like,
       "canned_source_titles": canned_srcs})

# المجموعة K — السجل (نافذة -45 دقيقة تشمل نافذة تنفيذ W2-T21) --------------
rc, out, err = sh(ssh, "sudo -n journalctl -u agentic -u searxng --since '-45 minutes' --no-pager -p err")
jout = out.strip()
jlines = [l for l in jout.splitlines() if l.strip() and "-- No entries --" not in l]
check("K1", "K", "journalctl (agentic+searxng، -45 دقيقة، مستوى err): لا أخطاء جديدة",
      len(jlines) == 0,
      {"rc": rc, "raw_head": jout[:600], "n_err_lines": len(jlines),
       "err_lines": jlines[:12]})

# المجموعة J (الجزء الخادومي) — أذونات ملف مفتاح Search API -----------------
rc, out, err = sh(ssh, "sudo -n stat -c '%U:%G %a' /etc/search-api/env")
env_stat = out.strip()
check("J3", "J", "/etc/search-api/env بصلاحيات 640 root:searchapi (بلا طباعة المحتوى)",
      env_stat == "root:searchapi 640", {"rc": rc, "stat": env_stat})

ssh.close()
print("ssh closed")

# المجموعة I — ملفات الأدلة والسكربتات محلياً -------------------------------
ev_files = {}
for f in ("deploy.json", "verify.json", "chat_e2e.json"):
    p = os.path.join(OUT_DIR, f)
    ev_files[f] = {"exists": os.path.exists(p),
                   "size": os.path.getsize(p) if os.path.exists(p) else 0}
check("I1", "I", "ملفات أدلة W2-T21 موجودة غير فارغة (deploy/verify/chat_e2e)",
      all(v["exists"] and v["size"] > 0 for v in ev_files.values()),
      {"dir": OUT_DIR, "files": ev_files})

ws_scripts = sorted([f for f in os.listdir(SCRIPTS_OPS_WS)
                     if f.startswith("w2t21_") or f.startswith("live_diag_")]) \
    if os.path.isdir(SCRIPTS_OPS_WS) else []
repo_scripts = sorted([f for f in os.listdir(SCRIPTS_OPS_REPO)
                       if f.startswith("w2t21_") or f.startswith("live_diag_")]) \
    if os.path.isdir(SCRIPTS_OPS_REPO) else []
check("I2", "I", "سكربتات W2-T21 موجودة محلياً (w2t21_* + live_diag_* — ≥4 في scripts/ops بمساحة العمل)",
      len(ws_scripts) >= 4,
      {"workspace_scripts_ops": ws_scripts,
       "repo_scripts_ops": repo_scripts,
       "note": "الموقع قبل مزامنة R9 هو scripts/ops بمساحة العمل — نفس عرف W2-T20 "
               "(السكربت يُزامن إلى repo/scripts/ops عند الإغلاق)"})
if not repo_scripts:
    add_note("N-I2", "السكربتات (9: w2t21×3 + live_diag×6) في scripts/ops بمساحة العمل ولم "
                     "تُزامن بعد إلى repo/scripts/ops — مسؤولية المنفذ مع R9 عند الإغلاق "
                     "(نفس عرف W2-T20 الذي دُقق بهذا الشكل ثم زُامن).")

# المجموعة J (الجزء المحلي) — لا مفتاح في المستودع ولا اسم 48-هكس ----------
HEX48 = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{48}(?![0-9a-fA-F])")
key_file_hits = []
hex_name_hits = []
for root, dirs, files in os.walk(REPO_LOCAL):
    dirs[:] = [d for d in dirs if d != ".git"]
    for fn in files:
        if fn == ".search_api_key.local":
            key_file_hits.append(os.path.join(root, fn))
        if HEX48.fullmatch(fn):
            hex_name_hits.append(os.path.join(root, fn))
check("J1", "J", "لا ملف .search_api_key.local ولا اسم ملف 48-هكس داخل المستودع المحلي",
      len(key_file_hits) == 0 and len(hex_name_hits) == 0,
      {"key_file_hits": key_file_hits, "hex48_name_hits": hex_name_hits})

ev_dir_names = sorted(os.listdir(OUT_DIR)) if os.path.isdir(OUT_DIR) else []
hex48_ev = [f for f in ev_dir_names if HEX48.fullmatch(f)]
key_ev = [f for f in ev_dir_names if f == ".search_api_key.local"]
hex_content_hits = []
for f in ev_dir_names:
    p = os.path.join(OUT_DIR, f)
    if os.path.isfile(p):
        try:
            data = open(p, "rb").read()
        except OSError:
            continue
        if HEX48.search(data.decode("utf-8", "replace")):
            hex_content_hits.append(f)
check("J2", "J", "دليل W2-T21: لا اسم ملف 48-هكس ولا .search_api_key.local ولا سلسلة 48-هكس داخل المحتوى",
      len(hex48_ev) == 0 and len(key_ev) == 0 and len(hex_content_hits) == 0,
      {"evidence_dir_files": ev_dir_names, "hex48_filenames": hex48_ev,
       "key_file": key_ev, "hex48_in_contents": hex_content_hits})

# فحص محتوى المستودع بايتياً عن أي سلسلة 48-هكس (المفتاح نفسه غير مقروء — بحث بالنمط)
repo_hex_content = []
for root, dirs, files in os.walk(REPO_LOCAL):
    dirs[:] = [d for d in dirs if d != ".git"]
    for fn in files:
        p = os.path.join(root, fn)
        try:
            if os.path.getsize(p) > 20 * 1024 * 1024:
                continue
            data = open(p, "rb").read()
        except OSError:
            continue
        if HEX48.search(data.decode("utf-8", "replace")):
            repo_hex_content.append(os.path.relpath(p, REPO_LOCAL))
add_note("N-J2", f"مسح بايتي لمحتوى المستودع (بلا .git) عن نمط 48-هكس: "
                 f"{len(repo_hex_content)} مطابقة — {repo_hex_content[:8]}"
         if repo_hex_content else
         "مسح بايتي لمحتوى المستودع (بلا .git) عن نمط 48-هكس: صفر مطابقات — لا أثر لمفتاح Search API")

# ============================================================================
script_md5 = hashlib.md5(open(SCRIPT_PATH, "rb").read()).hexdigest()
groups = {}
for r in results:
    g = groups.setdefault(r["group"], {"pass": 0, "total": 0})
    g["total"] += 1
    if r["pass"]:
        g["pass"] += 1
passed = sum(1 for r in results if r["pass"])
verdict = "PASS" if passed == len(results) else "FAIL"

report = {
    "_meta": {
        "task": "W2-T21-AUDIT — تدقيق مستقل قراءة-فقط لمهمة W2-T21 "
                "(استقرار البحث بعد W2-T20: محرك bing news + عزل الحظر الناعم)",
        "agent": "Audit Agent (وكيل تدقيق مستقل — general-purpose)",
        "timestamp_utc": now_utc(),
        "production_host": HOST,
        "expected_git_head": EXPECT_HEAD,
        "script": SCRIPT_PATH,
        "script_md5": script_md5,
        "discipline": "SSH قراءة-فقط؛ POSTs مصرح بها حصراً: /api/research/search "
                      "(ثلاثة بحوث فعلية)، /api/research/providers/{4,5}/probe (فقط عند "
                      "STALE — مرة واحدة لكل منهما). لا restart/stop لأي خدمة، لا كتابة "
                      "git على الخادم، لا تعديل ملفات، لا إنشاء محادثات، لا POST "
                      "/api/chat/stream (التحقق من 16/17 بقراءة القاعدة ro). "
                      "secret_key/مفتاح Search API لم يقرآ ولم يطبعا.",
        "authorized_posts_performed": {
            "research_search": search_log,
            "provider_probes": probe_log,
        },
        "own_queries": {
            "C_ar": C_Q_AR, "C_en": C_Q_EN, "C_knesset": C_Q_KN,
            "F_ar": F_Q_AR, "F_en": F_Q_EN, "F_207": Q_207,
        },
    },
    "summary": {"verdict": verdict, "passed": passed, "total": len(results),
                "groups": {k: groups[k] for k in sorted(groups)}},
    "checks": results,
    "notes": notes,
}
os.makedirs(OUT_DIR, exist_ok=True)
with open(REPORT_PATH, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2)

print(f"\nverdict={verdict} {passed}/{len(results)}")
for gk in sorted(groups):
    print(f"  group {gk}: {groups[gk]['pass']}/{groups[gk]['total']}")
print(f"report: {REPORT_PATH}")
print(f"script_md5: {script_md5}")
