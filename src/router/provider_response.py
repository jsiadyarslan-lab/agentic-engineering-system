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
import urllib.error
import urllib.request
from typing import Any

from router.live_providers import ProviderCallError


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
            ) from error
        if code >= 500:
            raise ProviderCallError(
                f"{code} خطأ خادم من {base_url}: {detail}",
                code=code,
                is_server_error=True,
            ) from error
        raise ProviderCallError(
            f"{code} خطأ عميل من {base_url} (مفتاح/عنوان؟): {detail}",
            code=code,
        ) from error
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        raise ProviderCallError(
            f"مهلة/اتصال فشل مع {base_url}: {error}",
            is_timeout=True,
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
