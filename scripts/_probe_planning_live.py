"""مسبار: هل يُنتج النموذج المُهيَّأ خطة فعلًا، وكم يستغرق؟ (013.5 §B).

يقيس المسار الحقيقي: طلب تخطيط بحجم واقعي عبر البث المتدفق، مع
تسجيل زمن أول قطعة استدلال وزمن أول مخرج وزمن الإنهاء. الغرض:
تحديد هل الفشل «بطء/سقف مخرجات» أم «نموذج لا يصلح للتخطيط».
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from router.model_router import ChatMessage, ModelRouter  # noqa: E402

router = ModelRouter.build_live()
specs = getattr(router, "_live_specs", {})
spec = dict(specs["nvidia"])
spec["max_tokens"] = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
spec["timeout"] = 600
model = sys.argv[1] if len(sys.argv) > 1 else "deepseek-ai/deepseek-v4.1-flash"

from router.streaming import stream_completion  # noqa: E402

messages = [
    ChatMessage(role="system", content=(
        "أنت مخطط مشاريع. أعد JSON فقط بهذا الشكل: "
        '{"objective": "…", "assumptions": ["…"], '
        '"acceptance_criteria": ["…"], '
        '"phases": [{"title": "…", "objective": "…", '
        '"acceptance_criteria": ["…"], '
        '"steps": [{"id": "S1", "description": "…", '
        '"acceptance_criteria": ["…"], "role": "implementer"}]}], '
        '"risks": ["…"], "dependencies": ["…"], '
        '"required_owner_decisions": ["…"]}'
    )),
    ChatMessage(role="user", content=json.dumps({
        "objective": "بناء منصة osint متقدمة جدا وفق احدث التقنيات والتكنولوجيا"
    }, ensure_ascii=False)),
]

state = {"first_reasoning": None, "last_reasoning": 0, "first_content": None,
         "content_chars": 0}
started = time.monotonic()


def on_reasoning(chars: int) -> None:
    if state["first_reasoning"] is None:
        state["first_reasoning"] = time.monotonic() - started
        print(f"  [{state['first_reasoning']:.1f}s] أول استدلال ({chars} حرفًا)")
    state["last_reasoning"] = chars


def on_delta(piece: str) -> None:
    if state["first_content"] is None:
        state["first_content"] = time.monotonic() - started
        print(f"  [{state['first_content']:.1f}s] أول مخرج")
    state["content_chars"] += len(piece)


print(f"model={model} max_tokens={spec['max_tokens']} timeout=600")
try:
    text = stream_completion(spec, model, messages,
                             on_delta=on_delta, on_reasoning=on_reasoning)
except Exception as error:  # noqa: BLE001
    elapsed = time.monotonic() - started
    print(f"FAILED after {elapsed:.1f}s: {type(error).__name__}: "
          f"{str(error)[:400]}")
    print("reasoning chars:", state["last_reasoning"],
          "content chars:", state["content_chars"])
    raise SystemExit(1)

elapsed = time.monotonic() - started
print(f"OK in {elapsed:.1f}s | reasoning={state['last_reasoning']} "
      f"content={state['content_chars']} chars")
print("first 400:", text[:400])
try:
    import re
    match = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(match.group(0))
    print("JSON parsed OK — phases:", len(data.get("phases", [])),
          "steps:", sum(len(p.get("steps", [])) for p in data.get("phases", [])))
except Exception as error:  # noqa: BLE001
    print("JSON parse:", error)
