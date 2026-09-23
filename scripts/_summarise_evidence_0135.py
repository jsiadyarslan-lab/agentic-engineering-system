"""Summarise the 013.5 evidence files without dumping them whole."""
from __future__ import annotations

import json
import sys
from pathlib import Path

EV = Path("runtime/evidence")
WANT = {
    "order0135-q-chaos-20260923T030251Z.json": (
        "chaos", ["verdict", "checks", "summary", "server_killed",
                  "healed_seconds", "error_class", "plan_created_after_crash"]),
    "order0135-k-stop-pause-20260922T231841Z.json": (
        "stop_pause", ["verdict", "checks", "summary", "scenarios"]),
    "order0135-l-chat-web-20260923T054927Z.json": (
        "chat_web", ["verdict", "checks", "summary", "question", "answer_chars",
                     "streamed_chars", "persisted_chars", "scope_events",
                     "scope_missing"]),
    "order0135-real-plan-20260922T215640Z.json": (
        "real_plan", ["verdict", "checks", "summary"]),
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for name, (label, keys) in WANT.items():
        path = EV / name
        print(f"\n===== {label}: {name} =====")
        if not path.exists():
            print("  MISSING")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            if key in data:
                value = data[key]
                text = json.dumps(value, ensure_ascii=False, default=str)
                print(f"  {key}: {text[:700]}")
        for key in ("verdict", "summary"):
            if key not in data:
                for alt in ("result", "outcome", "final", "data"):
                    if alt in data and isinstance(data[alt], dict):
                        text = json.dumps(data[alt], ensure_ascii=False,
                                          default=str)
                        print(f"  {alt}: {text[:900]}")
                        break


if __name__ == "__main__":
    main()
