"""مسبار حي: بحث ويب حقيقي من المحادثة العادية (013.5 §L).

يقرأ قاعدة الإنتاج، ويشغّل ``search_for_chat`` على سؤال المالك الحرفي،
ويطبع الروابط كما أعادها المزود. لا تلفيق: الفشل يُطبع بسببه.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from persistence.database import (  # noqa: E402
    build_engine, make_session_factory,
)
from research import chat_research as cr  # noqa: E402

QUESTIONS = [
    "ما هي احدث نماذج كلاود؟",
    "ما هي أحدث نماذج Claude؟",
]


def main() -> int:
    engine = build_engine(ROOT / "runtime" / "agent_hub_v2.db")
    sessions = make_session_factory(engine)
    report = {"questions": []}
    for question in QUESTIONS:
        decision = cr.decide_web_mode(question)
        entry = {"question": question, "decision": decision}
        outcome = cr.search_for_chat(sessions, question)
        entry["ok"] = outcome.get("ok")
        entry["provider"] = outcome.get("provider")
        entry["error"] = outcome.get("error")
        entry["attempts"] = outcome.get("attempts")
        entry["results"] = [
            {"title": r.get("title"), "url": r.get("url")}
            for r in (outcome.get("results") or [])
        ]
        report["questions"].append(entry)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
