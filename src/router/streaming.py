"""النقل المتدفق الحقيقي (الأمر 008 §3) — SSE من المزود إلى الواجهة.

النقل القائم (live_transport) ينتظر الرد كاملًا ثم يعيده دفعة واحدة؛
هذا النقل يطلب stream:true ويفك أسطر SSE من المزود ويُغذّي قطعًا
حقيقية لحظة وصولها — الواجهة ترى الرد ينمو تدريجيًا فعليًا.

نفس تصنيف أخطاء live_transport (429 اختناق/5xx خادم/4xx عميل/مهلة)
لكل قطعة تصل عبر مولّد — بلا تبعيات جديدة (urllib فقط).
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Generator

from router.model_router import ChatMessage, ProviderCallError


def streaming_live_transport(
    provider_cfg: dict,
) -> Callable[[str, list[ChatMessage]], Generator[str, None, None]]:
    """نقل متدفق لمزود متوافق OpenAI — يُنتج قطع نص فعلية (deltas).

    provider_cfg: {base_url, api_key, model?, headers?, timeout?,
    max_tokens?, extra_body?} — نفس عقد live_transport.
    """
    base_url = str(provider_cfg["base_url"]).rstrip("/")
    api_key = str(provider_cfg.get("api_key", ""))
    timeout = float(provider_cfg.get("timeout", 120))
    max_tokens = int(provider_cfg.get("max_tokens", 4000) or 0)

    def transport(model: str, messages: list[ChatMessage]):
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages
            ],
            "stream": True,
        }
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens
        payload.update(dict(provider_cfg.get("extra_body", {}) or {}))
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/event-stream",
        }
        headers.update(dict(provider_cfg.get("headers", {}) or {}))
        request = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode("utf-8", "replace")
            code = int(error.code)
            if code == 429:
                raise ProviderCallError(
                    f"429 اختناق من {base_url}: {detail}",
                    code=code, is_throttle=True,
                ) from error
            if code >= 500:
                raise ProviderCallError(
                    f"{code} خطأ خادم من {base_url}: {detail}",
                    code=code, is_server_error=True,
                ) from error
            raise ProviderCallError(
                f"{code} خطأ عميل من {base_url} (مفتاح/عنوان؟): {detail}",
                code=code,
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise ProviderCallError(
                f"مهلة/اتصال فشل مع {base_url}: {error}", is_timeout=True,
            ) from error

        with response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta

    return transport


def stream_completion(
    provider_cfg: dict,
    model: str,
    messages: list[ChatMessage],
    *,
    on_delta: Callable[[str], None],
) -> str:
    """استدعاء متدفق واحد — يغذي on_delta بكل قطعة ويعيد النص الكامل.

    قطعة واحدة فارغة من المزود (bلا deltas إطلاقًا) = فشل صريح —
    لا نجاح بلا مادة (نفس مبدأ live_transport الصادق).
    """
    started = time.monotonic()
    transport = streaming_live_transport(provider_cfg)
    pieces: list[str] = []
    for delta in transport(model, messages):
        pieces.append(delta)
        if on_delta is not None:
            on_delta(delta)
    text = "".join(pieces)
    if not text.strip():
        raise ProviderCallError(
            f"رد متدفق فارغ من {provider_cfg.get('base_url', '')} "
            f"({time.monotonic() - started:.1f}ث) — فشل صريح",
            is_server_error=True,
        )
    return text
