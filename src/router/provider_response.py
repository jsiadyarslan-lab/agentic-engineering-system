"""تفسير استجابة المزود غير المتدفقة — تصنيف صادق لا وسم كاذب.

سِجِل القرار (013.5 §B)
=====================
كان هذا المنطق داخل ``router.model_router`` فدفع الملف فوق سقفه
المعلن (<600 سطر، design-principles.md المبدأ 6). المنطق متماسك
بذاته — «اقرأ رد المزود وفسّره» — فلا يخصّ التنسيق الذي يملكه
الموجّه، فنُقل هنا وحدةً مستقلة كما نُقلت سابقًا حزم التبريد
والتبدّل وحد المعدل.

لماذا الفصل مهم وظيفيًا لا تنظيميًا فقط
---------------------------------------
نماذج الاستدلال (reasoning) تعيد ``content=null`` مع
``reasoning_content`` مليء حين تُستنفد ميزانية ``max_tokens`` داخل
مرحلة الاستدلال. العطل الحي المقيس: النموذج المُهيَّأ
``deepseek-ai/deepseek-v4.1-flash`` ردّ ‏200 بهذا الشكل بالضبط
فصُنّف «رد فارغ» — وهو وسم **كاذب**: المزود استجاب فعلًا، والمشكلة
سقف مخرجات لا انقطاع مزود. التصنيف الصادق يفرّق بين:

- «لم يرد المزود»            → رد فارغ (فشل صريح)
- «رد استدلالًا فقط»          → ``REASONING_ONLY_RESPONSE`` مع
  ``finish_reason`` وطول الاستدلال، فيعرف المالك أن العلاج رفع
  السقف أو اختيار نموذج غير استدلالي — لا إعادة محاولة عمياء.
"""

from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any

from router.live_providers import ProviderCallError


def _classify_transport_failure(error: BaseException) -> tuple[str, bool]:
    """(RLR-001 §1) سبب الجذر ← (فئة من taxonomy السبع، قابل للإعادة؟).

    - CONNECT_REFUSED: اتصال مرفوض/منقطع (جسر ميت مثلاً) — عابر: يُعاد.
    - DNS_FAILURE / TLS_FAILURE: تكوين/بيئة — لا إعادة (فشل صريح فوري).
    - REQUEST_TIMEOUT: عابر — يُعاد.
    المجهول النقل يعامل عابرًا (نفس قرار v1 الموثق في failover_chain).
    """
    items: list[BaseException | str] = []
    if isinstance(error, urllib.error.URLError):
        items.append(getattr(error, "reason", error))
    items.append(error)
    cur = getattr(error, "__cause__", None)
    for _ in range(4):
        if cur is None:
            break
        items.append(cur)
        cur = cur.__cause__ or cur.__context__
    for item in items:
        text = str(item).lower()
        if isinstance(item, ConnectionRefusedError) or "connection refused" in text or "actively refused" in text:
            return ("CONNECT_REFUSED", True)
        if isinstance(item, socket.gaierror) or "getaddrinfo" in text or "name or service not known" in text or "temporary failure in name resolution" in text:
            return ("DNS_FAILURE", False)
        if isinstance(item, ssl.SSLError) or "certificate" in text or "handshake" in text or "ssl:" in text:
            return ("TLS_FAILURE", False)
    if isinstance(error, (TimeoutError, socket.timeout)):
        return ("REQUEST_TIMEOUT", True)
    return ("CONNECT_REFUSED", True)


def read_json_response(
    request: Any, timeout: float, base_url: str
) -> dict:
    """ينفّذ النداء ويحوّل فشل HTTP/الشبكة إلى ``ProviderCallError`` مصنَّف.

    التصنيف هو ما يبني عليه المستدعي قراره (اختناق 429 / خطأ خادم 5xx
    / مهلة شبكة / خطأ عميل) — لا رسالة نصية يُخمَّن منها.
    """
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read()[:300].decode("utf-8", "replace")
        code = int(error.code)
        if code == 429:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            raise ProviderCallError(
                f"429 اختناق من {base_url}: {detail}",
                code=code,
                is_throttle=True,
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
                error_class="RATE_LIMITED",
            ) from error
        if code >= 500:
            raise ProviderCallError(
                f"{code} خطأ خادم من {base_url}: {detail}",
                code=code,
                is_server_error=True,
                error_class="SERVER_ERROR",
            ) from error
        if code in (401, 403):
            raise ProviderCallError(
                f"{code} رفض مصادقة من {base_url} (مفتاح؟): {detail}",
                code=code,
                error_class="AUTH_FAILURE",
            ) from error
        raise ProviderCallError(
            f"{code} خطأ عميل من {base_url} (مفتاح/عنوان؟): {detail}",
            code=code,
            error_class="INVALID_RESPONSE",
        ) from error
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        # (RLR-001 §1) التصنيف من سبب الجذر — Connection refused ليس مهلة!
        error_class, retryable = _classify_transport_failure(error)
        raise ProviderCallError(
            f"[{error_class}] فشل نقل مع {base_url}: {error}",
            is_timeout=(error_class == "REQUEST_TIMEOUT"),
            is_server_error=(retryable and error_class != "REQUEST_TIMEOUT"),
            error_class=error_class,
        ) from error


def content_from_body(body: dict, base_url: str) -> str:
    """يستخرج نص الإجابة، ويميّز «رد استدلالي فقط» عن «رد فارغ».

    (013.5 §B) الفرق جوهري: الأول مزود حيّ بسقف مخرجات ضيّق، والثاني
    مزود لم يرد. كلاهما فشل صريح، لكن التسمية الصادقة تحدّد العلاج.
    """
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise ProviderCallError(
            f"استجابة بلا choices/content من {base_url}: "
            f"{json.dumps(body, ensure_ascii=False)[:200]}",
            is_server_error=True,
        ) from error
    content = (message or {}).get("content")
    reasoning = (message or {}).get("reasoning_content")
    try:
        finish_reason = str(
            (body["choices"][0] or {}).get("finish_reason") or "")
    except (KeyError, IndexError, TypeError):
        finish_reason = ""
    if not isinstance(content, str) or not content.strip():
        if reasoning:
            raise ProviderCallError(
                f"رد استدلال فقط بلا مخرجات من {base_url} "
                f"(finish_reason={finish_reason or 'غير معلن'}، "
                f"طول الاستدلال={len(str(reasoning))} حرفًا) — "
                f"ارفع سقف المخرجات للنموذج أو اختر نموذجًا غير "
                f"استدلالي لهذه الخطوة",
                is_server_error=True,
                error_class="REASONING_ONLY_RESPONSE",
            )
        raise ProviderCallError(
            f"رد فارغ من {base_url} — فشل صريح لا تكرار صامت",
            is_server_error=True,
        )
    return content
