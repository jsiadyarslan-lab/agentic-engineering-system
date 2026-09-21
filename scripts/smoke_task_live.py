"""Smoke 2+3+4: مهمة حية كاملة عبر HTTP — سجل يُقرأ تدريجيًا."""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8010"


def post_sse(path: str, body: dict) -> list[dict]:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=1200) as response:
        raw = response.read().decode("utf-8")
    return [json.loads(b[6:]) for b in raw.split("\n\n") if b.startswith("data: ")]


def main() -> int:
    roles_cfg = {
        "thinker": {"provider": "zai_internal", "model": "glm-4.6"},
        "reviewer": {"provider": "zai_internal", "model": "glm-4.6"},
        "implementer": {"provider": "zai_internal", "model": "glm-4.6"},
        "verifier": {"provider": "zai_internal", "model": "glm-4.6"},
        "arbiter": {"provider": "zai_internal", "model": "glm-4.6"},
    }
    task_events = post_sse("/api/cycle/stream", {
        "goal": (
            "اكتب تقريرًا قصيرًا من صفحة واحدة عن أثر الذكاء الاصطناعي "
            "على التعليم، من 5-8 مصادر موثقة، عربي RTL، PDF بحجم A4"
        ),
        "roles": roles_cfg,
    })
    kinds = [e["kind"] for e in task_events]
    print("kinds:", json.dumps(kinds, ensure_ascii=False))
    done = next(e for e in task_events if e["kind"] == "task_done")
    print("verdict:", done["verdict"])
    print("reasons:", done["details"].get("verdict_reasons"))
    print("final_state:", done["details"].get("final_state"))
    print("evidence:", done["details"].get("evidence_path"))
    print("tool_calls:", done["details"].get("tool_calls_count"))

    calls = [e for e in task_events if e.get("kind") == "router.call.logged"]
    print("live_calls:", len(calls))
    for c in calls:
        d = c.get("details", c)
        print("  call:", d.get("provider"), "/", d.get("model"),
              "—", d.get("duration_ms"), "ms")

    evidence_path = done["details"].get("evidence_path", "")
    if evidence_path:
        with open(evidence_path, encoding="utf-8") as handle:
            evidence = json.load(handle)
        print("role_models:", json.dumps(
            evidence.get("role_models", {}), ensure_ascii=False))
        print("state_history:", evidence.get("state_history"))
        substrate_calls = [
            t for t in evidence.get("tool_calls", [])
            if t.get("execution_site") == "substrate"
        ]
        print("substrate_calls:", len(substrate_calls))
        for t in substrate_calls:
            print("  substrate:", t.get("tool"), "—", t.get("duration_ms"), "ms")
        print("files:", sorted(evidence.get("files", {}).keys()))

    # Smoke 5: صدق الفشل
    cfg_events = post_sse("/api/cycle/stream", {
        "goal": "مهمة بمزود غائب",
        "roles": {"thinker": {"provider": "nvidia", "model": "x"}},
    })
    req = [e for e in cfg_events if e["kind"] == "CONFIGURATION_REQUIRED"]
    assert req, "يجب أن يظهر CONFIGURATION_REQUIRED"
    assert "المفكر" in req[0]["text"]
    print("SMOKE-5 CONFIG_REQUIRED:", req[0]["text"][:100])
    print("ALL TASK SMOKES DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
