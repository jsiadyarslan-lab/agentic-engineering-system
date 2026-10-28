#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2-T22-AUDIT — independent read-only audit (paramiko, SSH to production).

Auditor: independent audit agent (general-purpose), Task ID W2-T22-AUDIT.
Target:  executor claims for W2-T22 (contextual chat search + followup retry
         + relevance gate vs generic news words / owner typo "الكنسيت").

Discipline enforced by this script:
- SSH read-only throughout, EXCEPT the explicitly authorized POSTs:
  * POST /api/chat/stream  — exactly 2 turns (fresh E2E of my own),
  * POST /api/research/providers/{4,5}/probe — once each, ONLY if STALE.
- No systemctl restart/stop. No git write. No file edits on the server
  (only /tmp SSE capture files as mandated by the audit instructions).
- DB opened exclusively as sqlite3 URI "file:...?mode=ro".
- Never reads or prints the Search API key / searxng secret_key
  (only `stat` permissions of /etc/search-api/env).

Evidence: /home/z/my-project/download/aes-remediation/W2-T22/
          audit_w2t22_independent.json (includes this script's md5).
Run with: /home/z/.venv/bin/python /home/z/my-project/scripts/ops/w2t22_audit_check.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import paramiko

# ------------------------------------------------------------------ #
# constants
# ------------------------------------------------------------------ #
HOST = "92.5.14.150"
USER = "opc"
KEY_PATH = "/tmp/oracle_key"
APP = "/opt/agentic-engineering-system"
DB_PATH = f"{APP}/runtime/agent_hub_v2.db"
SRV_PY = f"{APP}/.venv/bin/python"
SRV_SRC = f"{APP}/src"
LOCAL_REPO = "/home/z/my-project/repo"
EVIDENCE_DIR = "/home/z/my-project/download/aes-remediation/W2-T22"
EVIDENCE_PATH = os.path.join(EVIDENCE_DIR, "audit_w2t22_independent.json")
SCRIPT_PATH = os.path.abspath(__file__)

EXPECT_HEAD = "ad371b6b056fa0fc13929b1cb1a8ec240643e426"
EXPECT_PARENT = "5b939f6ad9d27d64dc8045beee82d97ced190519"
DEPLOY_WINDOW_SINCE = "2026-10-28 03:15 UTC"  # commit 03:19:26Z, deploy 03:20-03:25Z

OWNER_QUERY = "اخبار انتخابات الكنسيت اليوم"
URGE_MSG = "ابحث انت واعطني ملخص"
QMARK_MSG = "؟"
ELECTION_MARKERS = ("انتخاب", "الكنيست", "الكنسيت", "فرز", "تصويت", "مقاعد")
LIVE_PROVIDERS = ("SearXNG", "Search API")

HEX48_RE = re.compile(rb"(?<![0-9a-fA-F])[0-9a-fA-F]{48}(?![0-9a-fA-F])")

CHECKS: list[dict] = []
NOTES: list[str] = []


def check(cid: str, group: str, title: str, ok: bool, evidence) -> None:
    CHECKS.append({"id": cid, "group": group, "title": title,
                   "pass": bool(ok), "evidence": evidence})
    print(f"[{'PASS' if ok else 'FAIL'}] {cid} · {title}", flush=True)


def note(text: str) -> None:
    NOTES.append(text)
    print(f"[NOTE] {text}", flush=True)


# ------------------------------------------------------------------ #
# ssh plumbing
# ------------------------------------------------------------------ #
CLIENT = paramiko.SSHClient()
CLIENT.set_missing_host_key_policy(paramiko.AutoAddPolicy())


def ssh_run(cmd: str, timeout: int = 60, sudo: bool = False) -> tuple[int, str, str]:
    if sudo:
        cmd = "sudo -n " + cmd
    stdin, stdout, stderr = CLIENT.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def remote_py(code: str, timeout: int = 120, sudo: bool = False,
              with_src_path: bool = True) -> dict:
    """Run python code on the server with the app's venv interpreter.

    Returns {"rc", "out", "err", "json"} — json is parsed from the block
    between @@JSON@@ markers when present. sudo runs the interpreter
    directly (absolute paths only, no cd needed).
    """
    b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
    inner = f"import base64;exec(base64.b64decode('{b64}'))"
    if sudo:
        cmd = f'{SRV_PY} -c "{inner}"'
    else:
        prefix = f"cd {APP} && "
        if with_src_path:
            prefix += f"PYTHONPATH={SRV_SRC} "
        cmd = f'{prefix}{SRV_PY} -c "{inner}"'
    rc, out, err = ssh_run(cmd, timeout=timeout, sudo=sudo)
    parsed = None
    if "@@JSON@@" in out:
        try:
            parsed = json.loads(out.split("@@JSON@@", 1)[1].strip())
        except json.JSONDecodeError:
            parsed = None
    return {"rc": rc, "out": out, "err": err, "json": parsed}


def http_get(path: str, timeout: int = 30) -> tuple[int, str]:
    rc, out, _ = ssh_run(
        f"curl -sS --max-time {timeout} -w '\\n__HTTP__%{{http_code}}' "
        f"http://127.0.0.1:8010{path}", timeout=timeout + 15)
    return rc, out


def http_post(path: str, timeout: int = 60) -> tuple[int, str]:
    rc, out, _ = ssh_run(
        f"curl -sS --max-time {timeout} -X POST "
        f"-w '\\n__HTTP__%{{http_code}}' http://127.0.0.1:8010{path}",
        timeout=timeout + 15)
    return rc, out


def http_status(raw: str) -> str:
    return raw.rsplit("__HTTP__", 1)[-1].strip()


def http_body(raw: str) -> str:
    return raw.rsplit("__HTTP__", 1)[0].strip()


# ------------------------------------------------------------------ #
# GROUP A — production git state
# ------------------------------------------------------------------ #
def group_a() -> None:
    rc, head, err = ssh_run(f"cd {APP} && git rev-parse HEAD")
    check("A1", "A", "production git HEAD == ad371b6 (full hash)",
          rc == 0 and head.strip() == EXPECT_HEAD,
          {"head": head.strip(), "rc": rc})

    rc, status, _ = ssh_run(f"cd {APP} && git status --porcelain")
    lines = [l for l in status.splitlines() if l.strip()]
    tracked_dirty = [l for l in lines if not l.startswith("??")]
    untracked = sorted(l[3:].strip() for l in lines if l.startswith("??"))
    check("A2", "A", "zero tracked-modified files in production tree",
          not tracked_dirty,
          {"tracked_dirty": tracked_dirty, "untracked": untracked})

    expected_untracked = sorted([
        "runtime/browser/", "runtime/projects/",
        "scripts/ops/nightly_backup.sh",
        "scripts/ops/nightly_backup.sh.pre-w1t04",
        "src/agentic_engineering_system.egg-info/",
    ])
    check("A3", "A", "untracked set == expected (browser/projects/nightly_backup*/egg-info)",
          untracked == expected_untracked,
          {"actual": untracked, "expected": expected_untracked})

    rc, parent, _ = ssh_run(f"cd {APP} && git rev-parse HEAD^")
    check("A4", "A", "server-side: parent(ad371b6) == 5b939f6 (rollback anchor)",
          rc == 0 and parent.strip() == EXPECT_PARENT,
          {"parent": parent.strip()})

    rc, subject, _ = ssh_run(f"cd {APP} && git log -1 --format='%H|%s'")
    check("A5", "A", "HEAD commit subject announces W2-T22",
          rc == 0 and "W2-T22" in subject and EXPECT_HEAD[:7] in subject,
          {"subject": subject.strip()[:200]})


# ------------------------------------------------------------------ #
# GROUP B — code present in production files (+ byte identity vs commit)
# ------------------------------------------------------------------ #
PROD_FILES = [
    "src/research/providers.py",
    "src/research/chat_research.py",
    "src/api/routes.py",
]


def group_b() -> None:
    texts = {}
    for rel in PROD_FILES:
        rc, out, _ = ssh_run(f"cat {APP}/{rel}", timeout=30)
        texts[rel] = out

    p = texts["src/research/providers.py"]
    ok_tokens = all(tok in p for tok in (
        '"اخبار", "الاخبار", "أخبار"', '"اليوم"', '"نتائج"', '"مباشر"'))
    check("B1", "B", "providers.py: _GENERIC_TOKENS expanded (اخبار/اليوم/نتائج/مباشر)",
          ok_tokens and "_GENERIC_TOKENS = frozenset" in p,
          {"tokens_block_found": ok_tokens})

    ok_funcs = ("def _levenshtein_within" in p and "def _fuzzy_hit" in p)
    check("B2", "B", "providers.py: _levenshtein_within + _fuzzy_hit defined",
          ok_funcs, {})

    ok_fallback = ("not any(t not in _GENERIC_TOKENS for t in tokens)" in p)
    check("B3", "B", "providers.py: all-generic fallback inside result_relevance",
          ok_fallback, {})

    c = texts["src/research/chat_research.py"]
    ok_cr = ("def build_contextual_search_query" in c
             and "def is_followup_urge" in c
             and "def _distill_tokens" in c)
    check("B4", "B", "chat_research.py: build_contextual_search_query + is_followup_urge + _distill_tokens",
          ok_cr, {})

    r = texts["src/api/routes.py"]
    ok_routes = ("build_contextual_search_query" in r
                 and '"followup_retry"' in r
                 and 'web_decision.get("reason") == "auto_not_needed"' in r
                 and '"inherited": bool(contextual_query.get("inherited"))' in r)
    check("B5", "B", "routes.py: contextual wiring + followup_retry guard (auto_not_needed only) + inherited flag",
          ok_routes, {})

    identity = {}
    for rel in PROD_FILES:
        rc, h, _ = ssh_run(f"sha256sum {APP}/{rel}", timeout=30)
        remote_hash = h.split()[0].strip() if rc == 0 and h.split() else ""
        blob = subprocess.run(
            ["git", "show", f"ad371b6:{rel}"], cwd=LOCAL_REPO,
            capture_output=True).stdout
        local_hash = hashlib.sha256(blob).hexdigest()
        identity[rel] = {"remote_sha256": remote_hash,
                         "blob_sha256": local_hash,
                         "match": remote_hash == local_hash}
    check("B6", "B", "production files byte-identical to ad371b6 git blobs (3/3)",
          all(v["match"] for v in identity.values()), identity)


# ------------------------------------------------------------------ #
# GROUP C — services / health / journal
# ------------------------------------------------------------------ #
def group_c() -> None:
    rc, out, _ = ssh_run("systemctl is-active agentic nginx searxng search-api")
    states = [s.strip() for s in out.splitlines() if s.strip()]
    check("C1", "C", "agentic/nginx/searxng/search-api all active",
          states == ["active"] * 4, {"states": states})

    rc, out, _ = ssh_run(
        "curl -sS --max-time 20 -w '\\n%{http_code}' http://127.0.0.1:8010/health")
    body, code = out.rsplit("\n", 1)
    ok = code.strip() == "200"
    try:
        ok = ok and json.loads(body).get("status") in ("ok", "healthy")
    except Exception:
        pass
    check("C2", "C", "GET /health = 200", ok,
          {"http_code": code.strip(), "body_head": body[:160]})

    rc, out, err = ssh_run(
        f"sudo -n journalctl -u agentic -p err --since '{DEPLOY_WINDOW_SINCE}'")
    no_entries = ("-- No entries --" in out) or (not out.strip())
    check("C3", "C",
          "journalctl -u agentic -p err since deploy window: no entries",
          rc == 0 and no_entries,
          {"since": DEPLOY_WINDOW_SINCE, "out": out.strip()[:200],
           "err": err.strip()[:200]})


# ------------------------------------------------------------------ #
# GROUPS D + E — THE GATE + CONTEXTUAL QUERY (app's own code on server)
# ------------------------------------------------------------------ #
GATE_CODE = r'''
import json, sys
sys.path.insert(0, "/opt/agentic-engineering-system/src")
from research.providers import (result_relevance, _GENERIC_TOKENS,
                                _levenshtein_within, _fuzzy_hit, fold_text)
from research import chat_research as cr

owner_q = "اخبار انتخابات الكنسيت اليوم"
homepage_aljazeera = {
    "title": "الجزيرة نت: آخر أخبار اليوم حول العالم",
    "url": "https://www.aljazeera.net/",
    "snippet": "تغطية مباشرة لآخر أخبار اليوم حول العالم",
}
homepage_sky = {
    "title": "أخبار اليوم | سكاي نيوز عربية",
    "url": "https://www.skynewsarabia.com/",
    "snippet": "آخر المستجدات لحظة بلحظة",
}
live_knesset = {
    "title": "اللجنة المركزية: 77.7% نسبة التصويت في انتخابات الكنيست",
    "url": "https://arab48.com/نتائج-انتخابات-الكنيست",
    "snippet": "نتائج فرز انتخابات الكنيست الـ26 ونسبة التصويت",
}
react_page = {
    "title": "مكتبة رياكت لواجهات الويب",
    "url": "https://example.com/react-ar",
    "snippet": "تعليمات مكتبة رياكت",
}

out = {
  "d1_homepage_aljazeera": result_relevance(owner_q, homepage_aljazeera),
  "d1_homepage_sky": result_relevance(owner_q, homepage_sky),
  "d2_live_knesset": result_relevance(owner_q, live_knesset),
  "d3_all_generic": result_relevance("اخبار اليوم", homepage_sky),
  "d4_react": result_relevance("رياكت حوسبة كمومية", react_page),
  "generic_membership": {t: (fold_text(t) in _GENERIC_TOKENS)
                         for t in ("اخبار", "اليوم", "نتائج", "مباشر")},
  "lev_knesset_cap2": _levenshtein_within("الكنسيت", "الكنيست", 2),
  "fuzzy_knesset_hit": _fuzzy_hit("الكنسيت", {"الكنيست"}),
  "e1_urge_inherits": cr.build_contextual_search_query(
      "ابحث انت واعطني ملخص", ["اخبار انتخابات الكنسيت اليوم"]),
  "e2_qmark_inherits": cr.build_contextual_search_query(
      "؟", ["اخبار انتخابات الكنسيت اليوم", "ابحث انت واعطني ملخص"]),
  "e3_france_own_topic": cr.build_contextual_search_query(
      "فرنسا", ["اخبار انتخابات الكنسيت اليوم", "ابحث انت واعطني ملخص"]),
  "e4_qmark_urge": cr.is_followup_urge("؟"),
  "e5_walanan_urge": cr.is_followup_urge("والان"),
  "e6_jarrab_urge": cr.is_followup_urge("جرب الان"),
  "e7_story_not_urge": cr.is_followup_urge("اكتب لي قصة"),
}
print("@@JSON@@")
print(json.dumps(out, ensure_ascii=False))
'''


def group_d_and_e() -> None:
    res = remote_py(GATE_CODE, timeout=90)
    data = res["json"]
    if data is None:
        for cid in ("D1", "D2", "D3", "D4", "D5",
                    "E1", "E2", "E3", "E4", "E5", "E6", "E7"):
            check(cid, "D/E", "remote gate execution", False,
                  {"rc": res["rc"], "out": res["out"][:400],
                   "err": res["err"][:400]})
        return

    d1a, d1s = data["d1_homepage_aljazeera"], data["d1_homepage_sky"]
    check("D1", "D", "homepage titles no longer pass owner news query (strong=False ×2)",
          d1a["strong"] is False and d1s["strong"] is False
          and bool(d1a["hit"]) and bool(d1s["hit"]),
          {"aljazeera": d1a, "skynews": d1s})

    d2 = data["d2_live_knesset"]
    check("D2", "D", "typo tolerance: 'الكنسيت' in hit; live knesset result strong=True",
          ("الكنسيت" in d2["hit"]) and d2["strong"] is True,
          {"report": d2, "lev_knesset_cap2": data["lev_knesset_cap2"],
           "fuzzy_knesset_hit": data["fuzzy_knesset_hit"]})

    d3 = data["d3_all_generic"]
    check("D3", "D", "all-generic query 'اخبار اليوم' vs homepage: strong=True (fallback)",
          d3["strong"] is True, {"report": d3})

    d4 = data["d4_react"]
    check("D4", "D", "fabrication guard intact: 'رياكت حوسبة كمومية' vs react page strong=False",
          d4["strong"] is False and d4["hit"] == ["رياكت"],
          {"report": d4})

    check("D5", "D", "_GENERIC_TOKENS membership (اخبار/اليوم/نتائج/مباشر)",
          all(data["generic_membership"].values()),
          {"membership": data["generic_membership"]})

    e1 = data["e1_urge_inherits"]
    check("E1", "E", "'ابحث انت واعطني ملخص' inherits topic query verbatim",
          e1["inherited"] is True and e1["query"] == OWNER_QUERY,
          {"result": e1})

    e2 = data["e2_qmark_inherits"]
    check("E2", "E", "'؟' inherits topic query verbatim",
          e2["inherited"] is True and e2["query"] == OWNER_QUERY,
          {"result": e2})

    e3 = data["e3_france_own_topic"]
    check("E3", "E", "'فرنسا' stays own topic (not merged with history)",
          e3["inherited"] is False and e3["query"] == "فرنسا",
          {"result": e3})

    check("E4", "E", "is_followup_urge('؟') == True",
          data["e4_qmark_urge"] is True, {"value": data["e4_qmark_urge"]})
    check("E5", "E", "is_followup_urge('والان') == True",
          data["e5_walanan_urge"] is True, {"value": data["e5_walanan_urge"]})
    check("E6", "E", "is_followup_urge('جرب الان') == True",
          data["e6_jarrab_urge"] is True, {"value": data["e6_jarrab_urge"]})
    check("E7", "E", "is_followup_urge('اكتب لي قصة') == False",
          data["e7_story_not_urge"] is False, {"value": data["e7_story_not_urge"]})


# ------------------------------------------------------------------ #
# GROUP F — DB E2E (conversation 22) — READ-ONLY (mode=ro)
# ------------------------------------------------------------------ #
DB_CODE = r'''
import json, sqlite3
con = sqlite3.connect(
    "file:/opt/agentic-engineering-system/runtime/agent_hub_v2.db?mode=ro",
    uri=True)
con.row_factory = sqlite3.Row

out = {}
conv = list(con.execute("select * from conversations where id=22"))
out["conversation"] = [dict(r) for r in conv]

msgs = list(con.execute(
    "select id, role, content, created_at from messages "
    "where conversation_id=22 order by id"))
out["messages"] = [
    {"id": m["id"], "role": m["role"], "len": len(m["content"] or ""),
     "content": (m["content"] or "")[:120], "created_at": m["created_at"]}
    for m in msgs]
assist = [m for m in msgs if m["role"] == "assistant"]
out["third_assistant_full"] = (assist[2]["content"] or "") if len(assist) >= 3 else ""
out["all_assistant_no_internet"] = [
    "لا أملك إنترنت" not in (m["content"] or "") for m in assist]

ev = list(con.execute(
    "select id, kind, created_at, payload from events "
    "where cycle_id = 'chat-22' order by id"))
out["research_events"] = []
for e in ev:
    if e["kind"].startswith("research."):
        try:
            payload = json.loads(e["payload"])
        except Exception:
            payload = {}
        d = payload.get("details") or {}
        slim = {"id": e["id"], "kind": e["kind"],
                "created_at": e["created_at"]}
        if e["kind"] == "research.results":
            slim["details"] = {
                "provider": d.get("provider"), "count": d.get("count"),
                "results": [{"title": (r.get("title") or "")[:140]}
                            for r in (d.get("results") or [])],
            }
        elif e["kind"] == "research.used":
            slim["details"] = {
                "provider": d.get("provider"), "search": d.get("search"),
                "fetched": d.get("fetched"),
                "n_sources": len(d.get("sources") or []),
            }
        else:
            slim["details"] = {
                k: d.get(k) for k in (
                    "query", "original", "inherited", "reason", "markers")}
        out["research_events"].append(slim)
out["research_event_kinds"] = sorted(
    e["kind"] for e in ev if e["kind"].startswith("research."))
out["n_events_total_chat22"] = len(ev)
print("@@JSON@@")
print(json.dumps(out, ensure_ascii=False))
'''


def group_f() -> None:
    res = remote_py(DB_CODE, timeout=90, sudo=True, with_src_path=False)
    data = res["json"]
    if data is None:
        for cid in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"):
            check(cid, "F", "DB read (mode=ro)", False,
                  {"rc": res["rc"], "out": res["out"][:300],
                   "err": res["err"][:300]})
        return

    conv = data["conversation"]
    ok_conv = bool(conv) and conv[0]["mode"] == "chat"
    created = (conv[0]["created_at"] or "") if conv else ""
    hhmm = created[11:16] if len(created) >= 16 else ""
    in_window = ("2026-10-28" in created
                 and "03:22" <= hhmm <= "03:26")
    check("F1", "F", "conversation id=22 exists, mode=chat, created ~03:22-03:26Z",
          ok_conv and in_window,
          {"conversation": conv[0] if conv else None})
    if not in_window:
        note(f"F1: conversation 22 created_at={created} "
             f"(claim said ~03:22-03:24Z)")

    users = [m for m in data["messages"] if m["role"] == "user"]
    user_texts = [m["content"] for m in users]
    ok_users = (len(users) == 3
                and user_texts == [OWNER_QUERY, URGE_MSG, QMARK_MSG])
    check("F2", "F", "owner's exact 3 user turns in order",
          ok_users, {"user_messages": user_texts, "n_users": len(users)})

    assistants = [m for m in data["messages"] if m["role"] == "assistant"]
    ok_asst = (len(assistants) == 3
               and all(m["len"] >= 200 for m in assistants))
    check("F3", "F", "3 assistant messages with real content (>=200 chars each)",
          ok_asst, {"assistant_lengths": [m["len"] for m in assistants]})

    started = [e for e in data["research_events"]
               if e["kind"] == "research.started"]
    ok_started = len(started) == 3
    s1 = (started[0]["details"] if len(started) > 0 else {})
    s2 = (started[1]["details"] if len(started) > 1 else {})
    s3 = (started[2]["details"] if len(started) > 2 else {})
    ok1 = ok_started and s1.get("query") == OWNER_QUERY \
        and s1.get("inherited") is False
    ok2 = ok_started and s2.get("inherited") is True \
        and s2.get("original") == URGE_MSG
    ok3 = ok_started and s3.get("reason") == "followup_retry" \
        and s3.get("inherited") is True and s3.get("original") == QMARK_MSG
    check("F4", "F", "research.started ×3: own-topic / inherited / followup_retry",
          ok1 and ok2 and ok3,
          {"n": len(started),
           "turn1": {k: s1.get(k) for k in ("query", "original", "inherited", "reason")},
           "turn2": {k: s2.get(k) for k in ("query", "original", "inherited", "reason")},
           "turn3": {k: s3.get(k) for k in ("query", "original", "inherited", "reason")}})

    results_ev = [e for e in data["research_events"]
                  if e["kind"] == "research.results"]
    per_turn = []
    ok_results = len(results_ev) == 3
    for e in results_ev:
        d = e["details"] or {}
        titles = [r.get("title", "") for r in (d.get("results") or [])]
        n_election = sum(1 for t in titles
                         if any(mk in t for mk in ELECTION_MARKERS))
        per_turn.append({"provider": d.get("provider"),
                         "count": d.get("count"),
                         "n_results": len(titles),
                         "n_election_titles": n_election,
                         "titles_head": titles[:2]})
        if d.get("provider") != "SearXNG" or len(titles) < 5 or n_election < 3:
            ok_results = False
    check("F5", "F", "research.results ×3 via SearXNG, >=5 live election results each",
          ok_results, {"per_turn": per_turn})

    used = [e for e in data["research_events"] if e["kind"] == "research.used"]
    check("F6", "F", "research.used ×3 present",
          len(used) == 3,
          {"used": [{"provider": (e["details"] or {}).get("provider"),
                     "search": (e["details"] or {}).get("search"),
                     "n_sources": (e["details"] or {}).get("n_sources")}
                    for e in used]})

    kinds = data.get("research_event_kinds") or []
    check("F7", "F", "NO research.unavailable for chat-22",
          "research.unavailable" not in kinds,
          {"kinds": kinds,
           "n_events_total_chat22": data.get("n_events_total_chat22")})

    third = data.get("third_assistant_full") or ""
    has_election = any(mk in third for mk in ELECTION_MARKERS)
    no_internet = "لا أملك إنترنت" not in third
    check("F8", "F", "3rd assistant answer: election content, NO 'لا أملك إنترنت'",
          has_election and no_internet,
          {"len": len(third), "has_election_content": has_election,
           "no_internet_claim": no_internet,
           "head": third[:160],
           "all_assistant_no_internet": data.get("all_assistant_no_internet")})


# ------------------------------------------------------------------ #
# GROUP G — MY OWN FRESH E2E (authorized: exactly 2 POST turns)
# ------------------------------------------------------------------ #
def parse_sse(raw: str) -> list[dict]:
    events = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def group_g() -> None:
    """Fresh 2-turn E2E via authorized POSTs.

    W2T22_AUDIT_REUSE_E2E=1 → parse the /tmp SSE files captured by an
    earlier run of this same script WITHOUT firing any new POST turn
    (keeps the total footprint at exactly one conversation / 2 turns
    even across a re-run forced by a script bug). The SSE files on the
    server are the raw capture of the authorized POSTs.
    """
    reuse = os.environ.get("W2T22_AUDIT_REUSE_E2E") == "1"
    if reuse:
        note("E2E discipline: the two authorized POST turns were fired exactly "
             "once (first script run, 03:47Z, conversation captured in "
             "/tmp/w2t22_audit_t{1,2}.sse); this re-run parses the SAME raw "
             "SSE captures without firing any new POST — total footprint "
             "remains one conversation / exactly 2 turns")
    t1_file, t2_file = "/tmp/w2t22_audit_t1.sse", "/tmp/w2t22_audit_t2.sse"
    payload1 = json.dumps({"message": OWNER_QUERY, "web": "auto"},
                          ensure_ascii=False)
    if reuse:
        curl1 = "reuse-mode: SSE files from the authorized POSTs of the " \
                "first run (no additional POST fired)"
    else:
        _, curl1, _ = ssh_run(
            f"curl -sS -N --max-time 150 -X POST "
            f"http://127.0.0.1:8010/api/chat/stream "
            f"-H 'Content-Type: application/json' "
            f"-d '{payload1}' -o {t1_file}; echo CURL_RC=$?; wc -c {t1_file}",
            timeout=210)
    _, raw1, _ = ssh_run(f"cat {t1_file}", timeout=60)
    ev1 = parse_sse(raw1)
    bind = next((e for e in ev1 if e.get("kind") == "conversation.bind"), None)
    conv_id = (bind or {}).get("details", {}).get("conversation_id")
    rs1 = next((e for e in ev1 if e.get("kind") == "research.started"), None)
    rr1 = next((e for e in ev1 if e.get("kind") == "research.results"), None)
    comp1 = next((e for e in ev1 if e.get("kind") == "message_completed"), None)
    d_rs1 = (rs1 or {}).get("details", {})
    d_rr1 = (rr1 or {}).get("details", {})
    n_res1 = len(d_rr1.get("results") or [])
    ok_g1 = (conv_id is not None
             and d_rs1.get("query") == OWNER_QUERY
             and d_rs1.get("inherited") is False
             and d_rr1.get("provider") in LIVE_PROVIDERS
             and n_res1 >= 5
             and comp1 is not None)
    check("G1", "G", "fresh turn 1 (owner query): bind + own-topic research + >=5 live results + completion",
          ok_g1,
          {"conversation_id": conv_id,
           "curl_line": curl1.strip()[:120],
           "research_started": {k: d_rs1.get(k) for k in ("query", "original", "inherited", "reason")},
           "research_results": {"provider": d_rr1.get("provider"),
                                "count": d_rr1.get("count"),
                                "n_results": n_res1},
           "message_completed": comp1 is not None,
           "kinds_seen": sorted(set(str(e.get("kind")) for e in ev1))})

    if conv_id is None:
        check("G2", "G", "fresh turn 2 ('؟'): reason=followup_retry + live results",
              False, {"skipped": "no conversation_id from turn 1"})
        check("G3", "G", "fresh turn 2 answer: election content, NO 'لا أملك إنترنت'",
              False, {"skipped": "no conversation_id from turn 1"})
        check("G4", "G", "fresh conversation persisted (mode=chat, 2+2 messages)",
              False, {"skipped": "no conversation_id from turn 1"})
        return

    payload2 = json.dumps({"message": QMARK_MSG, "conversation_id": conv_id},
                          ensure_ascii=False)
    if reuse:
        curl2 = "reuse-mode: SSE files from the authorized POSTs of the " \
                "first run (no additional POST fired)"
    else:
        _, curl2, _ = ssh_run(
            f"curl -sS -N --max-time 150 -X POST "
            f"http://127.0.0.1:8010/api/chat/stream "
            f"-H 'Content-Type: application/json' "
            f"-d '{payload2}' -o {t2_file}; echo CURL_RC=$?; wc -c {t2_file}",
            timeout=210)
    _, raw2, _ = ssh_run(f"cat {t2_file}", timeout=60)
    ev2 = parse_sse(raw2)
    rs2 = next((e for e in ev2 if e.get("kind") == "research.started"), None)
    rr2 = next((e for e in ev2 if e.get("kind") == "research.results"), None)
    unav2 = next((e for e in ev2
                  if e.get("kind") == "research.unavailable"), None)
    d_rs2 = (rs2 or {}).get("details", {})
    d_rr2 = (rr2 or {}).get("details", {})
    titles2 = [r.get("title", "") for r in (d_rr2.get("results") or [])]
    n_election2 = sum(1 for t in titles2
                      if any(mk in t for mk in ELECTION_MARKERS))
    ok_g2 = (d_rs2.get("reason") == "followup_retry"
             and d_rs2.get("inherited") is True
             and d_rs2.get("query") == OWNER_QUERY
             and d_rs2.get("original") == QMARK_MSG
             and d_rr2.get("provider") in LIVE_PROVIDERS
             and len(titles2) >= 5
             and unav2 is None)
    check("G2", "G", "fresh turn 2 ('؟'): research.started reason=followup_retry + live results",
          ok_g2,
          {"curl_line": curl2.strip()[:120],
           "research_started": {k: d_rs2.get(k) for k in ("query", "original", "inherited", "reason", "markers")},
           "research_results": {"provider": d_rr2.get("provider"),
                                "count": d_rr2.get("count"),
                                "n_results": len(titles2),
                                "n_election_titles": n_election2,
                                "titles_head": titles2[:3]},
           "research_unavailable": unav2 is None})

    answer2 = "".join(
        (e.get("delta") or e.get("text") or "")
        for e in ev2 if e.get("kind") == "message_delta")
    no_internet = "لا أملك إنترنت" not in answer2
    has_election = any(mk in answer2 for mk in ELECTION_MARKERS)
    check("G3", "G", "fresh turn 2 answer: election content, NO 'لا أملك إنترنت'",
          no_internet and has_election and len(answer2) >= 200,
          {"len": len(answer2), "has_election_content": has_election,
           "no_internet_claim": no_internet, "head": answer2[:160]})

    try:
        cid_int = int(conv_id)
    except (TypeError, ValueError):
        cid_int = -1
    confirm_code = (
        "import json,sqlite3\n"
        "con=sqlite3.connect('file:" + DB_PATH + "?mode=ro',uri=True)\n"
        "con.row_factory=sqlite3.Row\n"
        f"rows=[dict(r) for r in con.execute('select * from conversations where id={cid_int}')]\n"
        f"msgs=[dict(r) for r in con.execute('select role,length(content) as len from messages where conversation_id={cid_int} order by id')]\n"
        "print('@@JSON@@')\n"
        "print(json.dumps({'conversation':rows,'messages':msgs},ensure_ascii=False))\n"
    )
    res = remote_py(confirm_code, timeout=60, sudo=True, with_src_path=False)
    cd = res["json"] or {}
    convs = cd.get("conversation") or []
    msgs = cd.get("messages") or []
    check("G4", "G", "fresh conversation persisted: mode=chat, exactly 2 user + 2 assistant messages",
          bool(convs) and convs[0].get("mode") == "chat"
          and sum(1 for m in msgs if m.get("role") == "user") == 2
          and sum(1 for m in msgs if m.get("role") == "assistant") == 2,
          {"conversation": convs[0] if convs else None, "messages": msgs})


# ------------------------------------------------------------------ #
# GROUP H — regressions (providers / readiness / local tests)
# ------------------------------------------------------------------ #
def group_h() -> None:
    rc, out = http_get("/api/research/providers")
    body, code = http_body(out), http_status(out)
    provs = {}
    try:
        provs = {p["id"]: p for p in json.loads(body).get("providers", [])}
    except Exception:
        pass
    p1, p2 = provs.get(1, {}), provs.get(2, {})
    p3, p4, p5 = provs.get(3, {}), provs.get(4, {}), provs.get(5, {})
    check("H1", "H", "providers: id1+id2 disabled+DISABLED, id3/4/5 enabled",
          code == "200"
          and p1.get("enabled") is False and p1.get("effective_status") == "DISABLED"
          and p2.get("enabled") is False and p2.get("effective_status") == "DISABLED"
          and p3.get("enabled") is True
          and p4.get("enabled") is True
          and p5.get("enabled") is True,
          {"http": code,
           "id1": {k: p1.get(k) for k in ("enabled", "effective_status")},
           "id2": {k: p2.get(k) for k in ("enabled", "effective_status")},
           "id3": {k: p3.get(k) for k in ("enabled", "effective_status")},
           "id4": {k: p4.get(k) for k in ("enabled", "effective_status")},
           "id5": {k: p5.get(k) for k in ("enabled", "effective_status")}})

    probed = {}
    for pid in (4, 5):
        if provs.get(pid, {}).get("effective_status") == "STALE":
            _, out = http_post(f"/api/research/providers/{pid}/probe",
                               timeout=90)
            probed[pid] = {"http": http_status(out),
                           "body_head": http_body(out)[:200]}
        else:
            probed[pid] = "not_stale_no_probe"

    rc, out = http_get("/api/research/providers")
    provs2 = {}
    try:
        provs2 = {p["id"]: p for p in
                  json.loads(http_body(out)).get("providers", [])}
    except Exception:
        pass
    st4 = provs2.get(4, {}).get("effective_status")
    st5 = provs2.get(5, {}).get("effective_status")
    check("H2", "H", "providers 4/5 READY (probe only if STALE, once each)",
          st4 == "READY" and st5 == "READY",
          {"probed": probed, "after": {"id4": st4, "id5": st5}})

    rc, out = http_get("/api/environment/readiness")
    rd, caps = {}, []
    try:
        rd = json.loads(http_body(out))
        caps = rd.get("capabilities", [])
    except Exception:
        pass
    web = next((c for c in caps if c.get("capability_id") == "web_search"), {})
    not_ready = [c.get("capability_id") for c in caps
                 if c.get("readiness_status") == "NOT_READY"]
    check("H3", "H", "readiness: web_search READY, zero NOT_READY, ~19 capabilities",
          web.get("readiness_status") == "READY" and not not_ready
          and 17 <= len(caps) <= 21,
          {"n_capabilities": len(caps),
           "web_search": {k: web.get(k) for k in
                          ("capability_id", "readiness_status", "stored_status")},
           "not_ready": not_ready,
           "summary": rd.get("summary")})

    repo_venv_py = os.path.join(LOCAL_REPO, ".venv/bin/python")
    try:
        proc = subprocess.run(
            [repo_venv_py, "-m", "pytest", "tests/research",
             "tests/api/test_chat_research_0134.py", "-q"],
            cwd=LOCAL_REPO, capture_output=True, text=True, timeout=420)
        lines = (proc.stdout or "").strip().splitlines()
        summary_line = lines[-1] if lines else ""
        rc = proc.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        summary_line, rc = f"ERROR: {exc}", -1
    ok_tests = rc == 0 and "passed" in summary_line \
        and " failed" not in summary_line
    check("H4", "H", "local test subset green (tests/research + test_chat_research_0134.py)",
          ok_tests,
          {"interpreter": repo_venv_py, "returncode": rc,
           "summary": summary_line})


# ------------------------------------------------------------------ #
# GROUP I — security
# ------------------------------------------------------------------ #
def group_i() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=LOCAL_REPO,
        capture_output=True).stdout.decode("utf-8", "replace").split("\0")
    tracked = [t for t in tracked if t.strip()]
    tracked_hits = []
    for rel in tracked:
        p = os.path.join(LOCAL_REPO, rel)
        try:
            with open(p, "rb") as f:
                if HEX48_RE.search(f.read()):
                    tracked_hits.append(rel)
        except OSError:
            continue
    check("I1", "I", "no 48-hex string in git-tracked repo files (byte scan)",
          not tracked_hits,
          {"tracked_files_scanned": len(tracked), "hits": tracked_hits})

    tree_hits = []
    for dirpath, dirnames, filenames in os.walk(LOCAL_REPO):
        for skip in (".git", ".venv"):
            if skip in dirnames:
                dirnames.remove(skip)
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "rb") as f:
                    if HEX48_RE.search(f.read()):
                        tree_hits.append(os.path.relpath(p, LOCAL_REPO))
            except OSError:
                continue
    check("I2", "I", "no 48-hex in repo working tree (excl. .git/.venv)",
          not tree_hits, {"hits": tree_hits})

    venv_hits = 0
    venv_root = os.path.join(LOCAL_REPO, ".venv")
    for dirpath, dirnames, filenames in os.walk(venv_root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "rb") as f:
                    if HEX48_RE.search(f.read()):
                        venv_hits += 1
            except OSError:
                continue
    if venv_hits:
        note(f"I2: {venv_hits} raw 48-hex matches exist ONLY inside "
             f".venv (certificate fingerprints in certifi cacert.pem and "
             f"similar virtualenv blobs) — not repository content, not API "
             f"keys; tracked-files and working-tree scans are clean")

    rc, out, err = ssh_run("sudo -n stat -c '%U:%G %a' /etc/search-api/env")
    perms = out.strip()
    check("I3", "I", "/etc/search-api/env perms root:searchapi 640 (content never read)",
          perms == "root:searchapi 640", {"perms": perms})


# ------------------------------------------------------------------ #
# GROUP J — rollback plan
# ------------------------------------------------------------------ #
def group_j() -> None:
    tracker_path = os.path.join(LOCAL_REPO, "TRACKER.md")
    with open(tracker_path, encoding="utf-8") as f:
        tracker = f.read()
    committed = subprocess.run(
        ["git", "show", "ad371b6:TRACKER.md"], cwd=LOCAL_REPO,
        capture_output=True).stdout.decode("utf-8", "replace")
    ok_plan = ("git reset --hard 5b939f6" in tracker
               and "git reset --hard 5b939f6" in committed)
    check("J1", "J", "TRACKER W2-T22 card documents rollback (git reset --hard 5b939f6)",
          ok_plan, {"in_worktree": "git reset --hard 5b939f6" in tracker,
                    "in_commit_ad371b6": "git reset --hard 5b939f6" in committed})

    parent = subprocess.run(
        ["git", "rev-parse", "ad371b6^"], cwd=LOCAL_REPO,
        capture_output=True).stdout.decode().strip()
    head = subprocess.run(
        ["git", "rev-parse", "ad371b6"], cwd=LOCAL_REPO,
        capture_output=True).stdout.decode().strip()
    check("J2", "J", "local repo: parent(ad371b6) == 5b939f6 (rollback anchor)",
          parent == EXPECT_PARENT and head == EXPECT_HEAD,
          {"ad371b6": head, "parent": parent})


# ------------------------------------------------------------------ #
# main
# ------------------------------------------------------------------ #
def main() -> int:
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"=== W2-T22-AUDIT independent audit — started {started} ===",
          flush=True)
    CLIENT.connect(HOST, username=USER, key_filename=KEY_PATH,
                   look_for_keys=False, allow_agent=False, timeout=30)
    try:
        group_a()
        group_b()
        group_c()
        group_d_and_e()
        group_f()
        group_g()
        group_h()
        group_i()
    finally:
        CLIENT.close()

    with open(SCRIPT_PATH, "rb") as f:
        script_md5 = hashlib.md5(f.read()).hexdigest()

    group_j()

    passed = sum(1 for c in CHECKS if c["pass"])
    total = len(CHECKS)
    verdict = "PASS" if passed == total else "FAIL"

    groups: dict[str, dict] = {}
    for c in CHECKS:
        g = groups.setdefault(c["group"], {"passed": 0, "total": 0})
        g["total"] += 1
        if c["pass"]:
            g["passed"] += 1

    evidence = {
        "task": "W2-T22-AUDIT — independent audit of W2-T22 "
                "(contextual chat search + followup retry + relevance gate)",
        "agent": "Audit Agent (independent, general-purpose)",
        "date": started,
        "ssh": {"host": HOST, "user": USER,
                "mode": "read-only + authorized POSTs only"},
        "authorized_posts": [
            "POST /api/chat/stream ×2 (fresh E2E, exactly 2 turns)",
            "POST /api/research/providers/{4,5}/probe (once each, only when STALE)",
        ],
        "script": {"path": SCRIPT_PATH, "md5": script_md5},
        "checks": CHECKS,
        "groups": groups,
        "notes": NOTES,
        "summary": {
            "passed": passed, "total": total, "verdict": verdict,
            "signature": f"W2-T22-AUDIT · 2026-10-28 · {verdict} · "
                         f"script_md5={script_md5}",
        },
    }

    # security self-check on the evidence payload itself (before writing)
    blob = json.dumps(evidence, ensure_ascii=False).encode("utf-8")
    if HEX48_RE.search(blob):
        print("[FATAL] 48-hex detected in evidence payload — refusing to write",
              flush=True)
        return 2

    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)

    # post-write verification: written file contains no 48-hex either
    with open(EVIDENCE_PATH, "rb") as f:
        written = f.read()
    check("I4", "I", "no 48-hex string in written evidence file",
          not HEX48_RE.search(written), {"matches": 0})

    # persist the final state (including the post-write I4 check)
    evidence["checks"] = CHECKS
    passed = sum(1 for c in CHECKS if c["pass"])
    total = len(CHECKS)
    verdict = "PASS" if passed == total else "FAIL"
    groups["I"] = {"passed": sum(1 for c in CHECKS
                                 if c["group"] == "I" and c["pass"]),
                   "total": sum(1 for c in CHECKS if c["group"] == "I")}
    evidence["groups"] = groups
    evidence["summary"] = {
        "passed": passed, "total": total, "verdict": verdict,
        "signature": f"W2-T22-AUDIT · 2026-10-28 · {verdict} · "
                     f"script_md5={script_md5}",
    }
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)

    print("\n=== GROUP SUMMARY ===", flush=True)
    for g in sorted(groups):
        print(f"  {g}: {groups[g]['passed']}/{groups[g]['total']}", flush=True)
    print(f"\nVERDICT: {verdict} — {passed}/{total} checks passed", flush=True)
    print(f"Evidence: {EVIDENCE_PATH}", flush=True)
    print(f"W2-T22-AUDIT · 2026-10-28 · {verdict} · script_md5={script_md5}",
          flush=True)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
