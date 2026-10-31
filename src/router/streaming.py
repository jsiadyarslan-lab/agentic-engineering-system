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
    *,
    on_reasoning: Callable[[int], None] | None = None,
) -> Callable[[str, list[ChatMessage]], Generator[str, None, None]]:
    """نقل متدفق لمزود متوافق OpenAI — يُنتج قطع نص فعلية (deltas).

    provider_cfg: {base_url, api_key, model?, headers?, timeout?,
    max_tokens?, extra_body?} — نفس عقد live_transport.

    (013.5 §D) ``on_reasoning``: نماذج الاستدلال تبث ``reasoning_content``
    قبل أي ``content``. تجاهل ذلك كان يجعل النظام يرى «صمتًا» بينما
    المزود يعمل فعلًا — فيُوسم MODEL_TIMEOUT وهو حكم كاذب. النداء هنا
    يُبلّغ عن **نشاط حقيقي** (عدد الأحرف) دون تمرير الاستدلال كنص
    إجابة — الاستدلال لا يُعرض للعميل أبدًا.

    (W2-T25 §D2) ``stream_idle_timeout`` (افتراض 240ث، 0 يعطل): مهلة
    الصمت الحقيقي — القياس الحي 2026-10-31 16:27–16:44Z: مزود تجمّد
    بلا محتوى ولا استدلال 17 دقيقة بينما إطارات الإبقاء على الحياة
    تصل فتعيد ضبط مهلة المقبس فلا تنطلق — والحلقة تجمّدت داخل النداء
    فلا تستطيع التقاط إعادة الطابور ولا الرد على وسم فقدان العامل.
    الآن: المخرجات الفعلية وحدها (محتوى أو استدلال) تمدّد ساعة
    النشاط؛ سكون أبعد من السقف = إحباط صادق مصنّف بدل تجميد صامت —
    والفشل المبكر يعاد عقده من الحلقة ذاتها بلا وسم عامل مفقود.
    """
    base_url = str(provider_cfg["base_url"]).rstrip("/")
    api_key = str(provider_cfg.get("api_key", ""))
    timeout = float(provider_cfg.get("timeout", 120))
    stream_idle = float(provider_cfg.get("stream_idle_timeout", 240) or 0)
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
            reasoning_chars = 0
            last_activity = time.monotonic()
            for raw_line in response:
                # (W2-T25 §D2) حارس الصمت الحقيقي — قبل معالجة السطر:
                if stream_idle > 0:
                    idle = time.monotonic() - last_activity
                    if idle > stream_idle:
                        raise ProviderCallError(
                            f"بث صامت {idle:.0f}ث من {base_url} — بلا "
                            "محتوى ولا استدلال (السقف "
                            f"{stream_idle:.0f}ث) — إحباط صادق بدل "
                            "تجميد حلقة التنفيذ (STREAM_IDLE_TIMEOUT)",
                            is_timeout=True,
                            error_class="STREAM_IDLE_TIMEOUT",
                        )
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
                delta_obj = choices[0].get("delta") or {}
                # (§D) استدلال حيّ = نشاط مزود حقيقي (لا يُعرض كنص)
                reasoning = delta_obj.get("reasoning_content")
                if reasoning:
                    reasoning_chars += len(str(reasoning))
                    last_activity = time.monotonic()
                    if on_reasoning is not None:
                        on_reasoning(reasoning_chars)
                delta = delta_obj.get("content")
                if delta:
                    last_activity = time.monotonic()
                    yield delta

    return transport


def stream_completion(
    provider_cfg: dict,
    model: str,
    messages: list[ChatMessage],
    *,
    on_delta: Callable[[str], None],
    on_reasoning: Callable[[int], None] | None = None,
) -> str:
    """استدعاء متدفق واحد — يغذي on_delta بكل قطعة ويعيد النص الكامل.

    قطعة واحدة فارغة من المزود (بلا deltas إطلاقًا) = فشل صريح —
    لا نجاح بلا مادة (نفس مبدأ live_transport الصادق).

    (013.5 §D) إن كان الصمت مصحوبًا باستدلال حيّ (``reasoning_content``)
    فالتصنيف صادق: المزود استجاب فعلًا والسقف هو ما منع المخرجات —
    لا «فشل خادم» ولا «رد فارغ» المجردين.
    """
    started = time.monotonic()
    reasoning_state = {"chars": 0}

    def _note_reasoning(chars: int) -> None:
        reasoning_state["chars"] = chars
        if on_reasoning is not None:
            on_reasoning(chars)

    transport = streaming_live_transport(
        provider_cfg, on_reasoning=_note_reasoning)
    pieces: list[str] = []
    for delta in transport(model, messages):
        pieces.append(delta)
        if on_delta is not None:
            on_delta(delta)
    text = "".join(pieces)
    if not text.strip():
        if reasoning_state["chars"]:
            raise ProviderCallError(
                f"استدلال فقط بلا مخرجات من "
                f"{provider_cfg.get('base_url', '')} "
                f"({time.monotonic() - started:.1f}ث، استدلال "
                f"{reasoning_state['chars']} حرفًا) — ارفع سقف المخرجات "
                f"أو اختر نموذجًا غير استدلالي لهذه الخطوة",
                is_server_error=True,
                error_class="REASONING_ONLY_RESPONSE",
            )
        raise ProviderCallError(
            f"رد متدفق فارغ من {provider_cfg.get('base_url', '')} "
            f"({time.monotonic() - started:.1f}ث) — فشل صريح",
            is_server_error=True,
        )
    return text
