"""تحقق حي §L + §E/§F/§G: بحث ويب حقيقي في محادثة عادية + ثبات الرسائل.

يقيس ثلاث حقائق في مسار واحد:

‏§L — سؤال ويب عربي حقيقي: هل وصلت مصادر ويب فعلية (روابط حقيقية)،
      أم أعلن النظام صراحةً أنه لا مصادر (لا تلفيق)؟
‏§E — هل أُعطيت الرسالة النطاق الصحيح (scope) في كل حدث؟
‏§G — بعد اكتمال الإجابة: هل تعيد قراءة الرسائل من القاعدة النص نفسه
      (لا اختفاء ولا ارتداد)؟
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "http://127.0.0.1:8010"
ROOT = Path(__file__).resolve().parents[1]


def call(method: str, path: str, body: dict | None = None,
         timeout: float = 60.0) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, headers=headers,
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, raw
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw


def send_and_stream(message: str, conversation_id: int | None,
                    *, timeout: float = 600.0) -> dict:
    """أرسل سؤالًا واقرأ تيار SSE كاملًا — الأحداث نفسها التي تراها الواجهة."""
    body: dict[str, Any] = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    request = urllib.request.Request(
        BASE + "/api/chat/stream",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream"},
        method="POST",
    )
    events: list[dict] = []
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                events.append(json.loads(payload))
            except ValueError:
                continue
    return {"events": events, "seconds": round(time.monotonic() - started, 1)}


def _answer_text(events: list[dict]) -> str:
    """نص الجواب من أحداث البث.

    (013.5 §E) الغلاف الموحَّد يضع القطعة في ``delta``/``text`` على
    **مستوى الحدث** لا داخل ``payload`` — قراءة ``payload`` وحدها كانت
    تعيد صفرًا فتبدو المقارنة فاشلة وهي ليست كذلك. القياس من الحدث
    نفسه هو ما تراه الواجهة لحظة البث.
    """
    out = []
    for event in events:
        if event.get("kind") != "message_delta":
            continue
        payload = event.get("payload") or {}
        out.append(str(
            event.get("delta") or event.get("text")
            or payload.get("delta") or payload.get("text") or ""))
    return "".join(out)


def _scope_audit(conversation_id: int) -> dict:
    """§E: تدقيق نطاق كل حدث محادثة محفوظ — من القاعدة مباشرة."""
    import sqlite3

    db = ROOT / "runtime" / "agent_hub_v2.db"
    rows = sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute(
        "SELECT seq, kind, payload FROM events WHERE cycle_id = ? ORDER BY seq",
        (f"chat-{conversation_id}",),
    ).fetchall()
    missing: list[dict] = []
    conversations: set = set()
    message_ids: set = set()
    kinds_without: dict[str, int] = {}
    for seq, kind, payload in rows:
        try:
            data = json.loads(payload or "{}")
        except ValueError:
            data = {}
        scope = data.get("scope") or {}
        if scope.get("conversation_id"):
            conversations.add(scope["conversation_id"])
            if scope.get("message_id"):
                message_ids.add(scope["message_id"])
        else:
            missing.append({"seq": seq, "kind": kind})
            kinds_without[kind] = kinds_without.get(kind, 0) + 1
    return {
        "events": len(rows),
        "missing_scope": len(missing),
        "missing_sample": missing[:5],
        "kinds_without_scope": kinds_without,
        "conversations": sorted(conversations),
        "message_ids": len(message_ids),
        "all_scoped": bool(rows) and not missing,
    }


def main() -> int:
    evidence: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    status, providers = call("GET", "/api/research/providers")
    rows = providers.get("providers") if isinstance(providers, dict) else []
    evidence["research_providers"] = [
        {"name": p.get("name"), "kind": p.get("kind"),
         "enabled": p.get("enabled"),
         "effective_status": p.get("effective_status"),
         "reason": (p.get("state_reason") or "")[:120]}
        for p in (rows or [])
    ]
    print("مزودو البحث:")
    for row in evidence["research_providers"]:
        print(f"  {row['name']:<12} {row['effective_status']:<16} "
              f"{row['reason'][:80]}")

    conversation_id: int | None = None
    evidence["cases"] = []
    questions = [
        "ما هو React؟",
        "ما هي أحدث نماذج كلاود؟",
    ]
    for question in questions:
        print(f"\n--- سؤال: {question}", flush=True)
        case: dict[str, Any] = {"question": question}
        result = send_and_stream(question, conversation_id)
        events = result["events"]
        case["seconds"] = result["seconds"]
        case["event_count"] = len(events)
        kinds = [e.get("kind") for e in events]
        case["kinds"] = kinds
        if conversation_id is None:
            for event in events:
                scope = event.get("scope") or {}
                if scope.get("conversation_id"):
                    conversation_id = scope["conversation_id"]
                    break
        case["conversation_id"] = conversation_id
        print(f"  {len(events)} حدث في {case['seconds']}ث | "
              f"أنواع={kinds}", flush=True)

        # §E: نطاق الرسالة في الأحداث المحفوظة داخل القاعدة (المصدر
        # الموثوق — لا تحليل الغلاف الحيّ). كل حدث محادثة يجب أن يحمل
        # نطاقًا كاملًا يشير إلى نفس المحادثة ونفس الرسالة.
        case["scope_audit"] = _scope_audit(conversation_id)
        print(f"  نطاق الأحداث: {case['scope_audit']['events']} حدث | "
              f"بلا نطاق={case['scope_audit']['missing_scope']} | "
              f"محادثات={case['scope_audit']['conversations']} | "
              f"رسائل={case['scope_audit']['message_ids']}")

        # §L: أحداث البحث كما تصل الواجهة — النوع والحمولة الدالة
        research = [e for e in events
                    if str(e.get("kind", "")).startswith("research.")]
        case["research_events"] = [
            {"kind": e.get("kind"),
             "details": {k: v for k, v in (e.get("details") or {}).items()
                         if k in ("query", "original", "provider", "sources",
                                  "reason", "count", "markers", "results")},
             "detail_keys": sorted((e.get("details") or {}).keys())}
            for e in research
        ]
        case["research_kinds"] = [e.get("kind") for e in research]

        answer = _answer_text(events)
        case["answer_chars"] = len(answer)
        case["answer_head"] = answer[:400]
        print(f"  بحث: {json.dumps(case['research_kinds'], ensure_ascii=False)} "
              f"{json.dumps(case['research_events'], ensure_ascii=False)[:300]}")
        print(f"  الجواب ({len(answer)} حرفًا): {answer[:280]}", flush=True)

        # §G: اقرأ من القاعدة — نفس النص، لا اختفاء
        status, msgs = call(
            "GET", f"/api/conversations/{conversation_id}/messages")
        rows = msgs if isinstance(msgs, list) else msgs.get("messages", [])
        assistant = [m for m in rows if m.get("role") == "assistant"]
        case["persisted_assistant_count"] = len(assistant)
        persisted = (assistant[-1].get("content") or "") if assistant else ""
        case["persisted_chars"] = len(persisted)
        case["persisted_matches_answer_tail"] = (
            bool(persisted) and bool(answer)
            and persisted.strip()[-120:] == answer.strip()[-120:])
        case["persisted_head"] = persisted[:200]
        # (013.5 §G) التطابق الكامل: ما بُثّ للمستخدم == ما حُفظ.
        case["persisted_equals_stream"] = bool(answer) and (
            persisted.strip() == answer.strip())
        print(f"  من القاعدة: {len(persisted)} حرفًا | مطابق للبث تمامًا="
              f"{case['persisted_equals_stream']}", flush=True)

        status, again = call(
            "GET", f"/api/conversations/{conversation_id}/messages")
        rows2 = again if isinstance(again, list) else again.get("messages", [])
        assistant2 = [m for m in rows2 if m.get("role") == "assistant"]
        reread = (assistant2[-1].get("content") or "") if assistant2 else ""
        case["reread_stable"] = bool(persisted) and reread == persisted
        print(f"  إعادة القراءة: مطابق={case['reread_stable']}", flush=True)
        evidence["cases"].append(case)

    evidence["conversation_id"] = conversation_id
    status, hist = call("GET", f"/api/conversations/{conversation_id}/messages")
    hist_rows = hist if isinstance(hist, list) else hist.get("messages", [])
    evidence["history_final"] = {
        "count": len(hist_rows),
        "roles": [m.get("role") for m in hist_rows],
        "assistant_chars": [len(m.get("content") or "") for m in hist_rows
                            if m.get("role") == "assistant"],
    }
    print(f"\nالتاريخ النهائي: "
          f"{json.dumps(evidence['history_final'], ensure_ascii=False)}")

    out_dir = ROOT / "runtime" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"order0135-l-chat-web-{stamp}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"دليل: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
