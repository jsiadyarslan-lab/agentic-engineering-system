#!/usr/bin/env python3
# W2-T22 E2E: replay the owner's EXACT 3-turn scenario (conv-15) in ONE
# new conversation through the legitimate /api/chat/stream:
#   T1 "اخبار انتخابات الكنسيت اليوم"  -> fresh live search
#   T2 "ابحث انت واعطني ملخص"          -> INHERITED topic query
#   T3 "؟"                             -> followup_retry re-search
# Verdict per turn: research.started/query/inherited/reason + results
# count/provider + answer must NOT claim "no internet".
import json, time, base64, paramiko, os

HOST, USER, KEY = "92.5.14.150", "opc", "/tmp/oracle_key"
EVDIR = "/home/z/my-project/download/aes-remediation/W2-T22"
os.makedirs(EVDIR, exist_ok=True)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, key_filename=KEY, timeout=25,
            look_for_keys=False, allow_agent=False)

def run(cmd, t=180, label=""):
    _, so, se = ssh.exec_command(cmd, timeout=t)
    out = so.read().decode(errors="replace")
    err = se.read().decode(errors="replace")
    rc = so.channel.recv_exit_status()
    return {"cmd": (label or cmd)[:120], "rc": rc, "out": out.strip()[:5000],
            "err": err.strip()[:400]}

def chat_turn(message, sse_path, convo_id=None):
    body = {"message": message, "web": "auto"}
    if convo_id:
        body["conversation_id"] = convo_id
    body64 = base64.b64encode(json.dumps(body, ensure_ascii=False).encode()).decode()
    return run(
        f"echo {body64} | base64 -d > {sse_path}.req && "
        f"curl -s -N --max-time 150 -X POST http://127.0.0.1:8010/api/chat/stream "
        f"-H 'Content-Type: application/json' --data-binary @{sse_path}.req "
        f"-o {sse_path} -w 'http=%{{http_code}} time=%{{time_total}}s\\n'; "
        f"wc -c {sse_path}", 170, f"chat turn: {message[:30]}")

PARSE = r'''
import json, sys
sse_path = sys.argv[1]
kinds, answer_parts = [], []
events = {}
bind = None
for raw in open(sse_path, encoding="utf-8", errors="replace"):
    line = raw.strip()
    if not line.startswith("data:"):
        continue
    try:
        e = json.loads(line[5:].strip())
    except Exception:
        continue
    k = e.get("kind", "?")
    kinds.append(k)
    events[k] = e
    if k == "conversation.bind":
        bind = e
    if k in ("message_delta", "message_completed"):
        t = e.get("text") or e.get("delta") or ""
        if t:
            answer_parts.append(t)
answer = "".join(answer_parts)
out = {
    "kinds_present": sorted(set(k for k in kinds if not k.startswith("message_delta"))),
    "conversation_id": (bind or {}).get("details", {}).get("conversation_id"),
    "research_started": (events.get("research.started") or {}).get("details"),
    "research_results_count": len(((events.get("research.results") or {}).get("details") or {}).get("results") or []),
    "research_results_provider": ((events.get("research.results") or {}).get("details") or {}).get("provider"),
    "research_results_titles": [r.get("title", "")[:80] for r in (((events.get("research.results") or {}).get("details") or {}).get("results") or [])[:6]],
    "research_unavailable": bool(events.get("research.unavailable")),
    "web_used": ((events.get("message_completed") or {}).get("details") or {}).get("web_used"),
    "answer_len": len(answer),
    "answer_head": answer[:900],
    "answer_claims_no_internet": any(p in answer for p in (
        "لا أملك إنترنت", "لا استطيع الوصول للإنترنت", "غير متصل بالإنترنت",
        "لا أستطيع تزويدك بملخص", "لا أملك وصولًا للإنترنت")),
    "answer_mentions_election": any(p in answer for p in (
        "انتخابات", "الكنيست", "الكنسيت", "فرز", "تصويت", "مقاعد")),
}
print("@@J@@")
print(json.dumps(out, ensure_ascii=False))
'''

ev = {"_meta": {"task": "W2-T22 E2E — owner 3-turn replay",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}

# ---- TURN 1 ----
ev["t1_stream"] = chat_turn("اخبار انتخابات الكنسيت اليوم", "/tmp/w2t22_t1.sse")
ev["t1_parse"] = run("python3 - /tmp/w2t22_t1.sse <<'PYEOF'\n" + PARSE + "\nPYEOF", 60, "parse t1")

# extract conversation_id from t1 for turns 2/3
def parse_out(block):
    try:
        return json.loads(block["out"].split("@@J@@", 1)[1])
    except Exception:
        return {}

def rs(turn):
    return ((turn or {}).get("research_started") or {})

t1 = parse_out(ev["t1_parse"])
convo_id = (t1 or {}).get("conversation_id")
print("T1 conversation_id:", convo_id)

# ---- TURN 2 (with conversation_id) ----
ev["t2_stream"] = chat_turn("ابحث انت واعطني ملخص", "/tmp/w2t22_t2.sse", convo_id)
ev["t2_parse"] = run("python3 - /tmp/w2t22_t2.sse <<'PYEOF'\n" + PARSE + "\nPYEOF", 60, "parse t2")

# ---- TURN 3: "؟" ----
ev["t3_stream"] = chat_turn("؟", "/tmp/w2t22_t3.sse", convo_id)
ev["t3_parse"] = run("python3 - /tmp/w2t22_t3.sse <<'PYEOF'\n" + PARSE + "\nPYEOF", 60, "parse t3")

ssh.close()

t2 = parse_out(ev["t2_parse"])
t3 = parse_out(ev["t3_parse"])

# ---- verdicts ----
verdict = {
    "t1": {
        "query_ok": rs(t1).get("query") == "اخبار انتخابات الكنسيت اليوم",
        "inherited_flag": rs(t1).get("inherited"),
        "results_count": (t1 or {}).get("research_results_count"),
        "provider": (t1 or {}).get("research_results_provider"),
        "web_used": (t1 or {}).get("web_used"),
        "answer_no_internet_claim": (t1 or {}).get("answer_claims_no_internet"),
        "answer_mentions_election": (t1 or {}).get("answer_mentions_election"),
    },
    "t2": {
        "query": rs(t2).get("query"),
        "inherited_flag": rs(t2).get("inherited"),
        "query_is_owner_topic": rs(t2).get("query") == "اخبار انتخابات الكنسيت اليوم",
        "not_you_and_summary": "انت" not in str(rs(t2).get("query", "")).split(),
        "results_count": (t2 or {}).get("research_results_count"),
        "provider": (t2 or {}).get("research_results_provider"),
        "titles": (t2 or {}).get("research_results_titles"),
        "answer_no_internet_claim": (t2 or {}).get("answer_claims_no_internet"),
        "answer_mentions_election": (t2 or {}).get("answer_mentions_election"),
        "web_used": (t2 or {}).get("web_used"),
    },
    "t3": {
        "reason": rs(t3).get("reason"),
        "query": rs(t3).get("query"),
        "inherited_flag": rs(t3).get("inherited"),
        "followup_retry_fired": rs(t3).get("reason") == "followup_retry",
        "results_count": (t3 or {}).get("research_results_count"),
        "provider": (t3 or {}).get("research_results_provider"),
        "web_used": (t3 or {}).get("web_used"),
        "answer_no_internet_claim": (t3 or {}).get("answer_claims_no_internet"),
        "answer_mentions_election": (t3 or {}).get("answer_mentions_election"),
        "answer_head": (t3 or {}).get("answer_head"),
    },
    "same_conversation": bool(convo_id and (t2 or {}).get("conversation_id") == convo_id and (t3 or {}).get("conversation_id") == convo_id),
}
ev["verdict"] = verdict

path = f"{EVDIR}/e2e_owner_replay.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(ev, f, ensure_ascii=False, indent=2)

print(json.dumps(verdict, ensure_ascii=False, indent=2)[:3500])
print("\nsaved:", path)
