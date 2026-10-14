# -*- coding: utf-8 -*-
"""مسبار مزود النموذج الحي (013.16 §3) — عبر مسار المنتج حصرًا.

يبني ModelRouter.build_live() (نفس ما تبنيه المهمة) ويُجري نداءً
حيًا واحدًا صغيرًا على zai_internal/glm-4.6: يوثق الهوية والكمون
وحجم الرد — بلا طباعة أي سر إطلاقًا.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from router.model_router import ChatMessage, ModelRouter  # noqa: E402


def main() -> int:
    started = time.monotonic()
    router = ModelRouter.build_live()
    resolved = sorted(router.live_providers())
    print("resolved live providers:", resolved)
    if "zai_internal" not in resolved:
        print("FATAL: zai_internal did not resolve — no real model provider")
        return 2
    t0 = time.monotonic()
    outcome = router.chat_live(
        [ChatMessage(role="user", content="أجب بكلمة واحدة فقط: جاهز")],
        provider_id="zai_internal",
        model="glm-4.6",
    )
    latency = time.monotonic() - t0
    text = outcome.get("text", "")
    result = {
        "provider": "zai_internal",
        "base_url": "https://internal-api.z.ai/v1",
        "auth_source": "/etc/.z-ai-config (container-provisioned, declared)",
        "model": "glm-4.6",
        "latency_s": round(latency, 1),
        "response_chars": len(text),
        "response_head": text[:120].replace("\n", " "),
        "identity_fields": {
            k: outcome.get(k) for k in ("provider", "model") if k in outcome
        },
        "secrets_printed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print("total script seconds:", round(time.monotonic() - started, 1))
    return 0 if text.strip() else 3


if __name__ == "__main__":
    sys.exit(main())
