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

سِجِل القرار (RLR-001 §1) — عقد تصنيف الشبكة
==========================================
«Connection refused» كان يُوسم ``is_timeout=True`` فيُصنَّف
``MODEL_TIMEOUT`` — وسم كاذب دفع المالك لتشخيص خاطئ (المشكلة وسيط
الشبكة لا مهلة). التصنيف الصريح الآن سبعة أصناف تمر حرفيًا إلى
المحرك والواجهة عبر ``error_class``:

- ``CONNECT_REFUSED``  عابر — الوسيط/المنفذ غير متاح لحظيًا.
- ``DNS_FAILURE``      قاتل داخل النداء — الاسم/المحلّل.
- ``TLS_FAILURE``      قاتل — شهادة/تفاوض غير سليم.
- ``AUTH_FAILURE``     قاتل — 401/403 مفتاح مرفوض/ناقص.
- ``RATE_LIMITED``     429 — ملك حلقة التبريد.
- ``REQUEST_TIMEOUT``  عابر — مهلة بلا رد.
- ``INVALID_RESPONSE`` قاتل — 4xx غير المصادقة.

و``is_transient`` (عابر) يقرر قابلية الإعادة داخل النداء في
``failover_chain._is_retryable`` — بلا إعادة لانهائية ولا تجاوز
لمهلة العملية كلها.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from router.live_providers import ProviderCallError


def classify_network_error(
    error: BaseException, base_url: str
) -> ProviderCallError:
    """تصنيف فشل الشبكة بدقة (RLR-001 §1) — رفض الاتصال ليس مهلة.

    يُبنى منه ``ProviderCallError`` بالصنف الصريح ``error_class`` الذي
    يمرره ``classify_failure`` كما هو إلى المحرك والواجهة، وسمة
    ``is_transient`` التي تقرر قابلية الإعادة داخل النداء.
    """
    reason = getattr(error, "reason", error)
    text = f"{reason or error}".lower()
    if (isinstance(reason, ConnectionRefusedError)
            or "connection refused" in text):
        return ProviderCallError(
            f"رفض اتصال مع {base_url} ({reason}) — الوسيط/المنفذ غير "
            f"متاح لحظيًا؛ الدورة قابلة للاستئناف عند عودة المسار",
            error_class="CONNECT_REFUSED", is_transient=True,
        )
    if (isinstance(reason, socket.gaierror)
            or "name or service not known" in text
            or "nodename nor servname" in text
            or "getaddrinfo" in text):
        return ProviderCallError(
            f"فشل DNS مع {base_url} ({reason}) — تحقق من الاسم/المحلّل",
            error_class="DNS_FAILURE",
        )
    if "certificate" in text or "ssl" in text or "tls" in text:
        return ProviderCallError(
            f"فشل TLS مع {base_url} ({reason}) — شهادة/تفاوض غير سليم",
            error_class="TLS_FAILURE",
        )
    if isinstance(error, (TimeoutError, socket.timeout)) \
            or "timed out" in text:
        return ProviderCallError(
            f"مهلة طلب انتهت مع {base_url} — انقطاع بلا رد",
            error_class="REQUEST_TIMEOUT", is_timeout=True, is_transient=True,
        )
    return ProviderCallError(
        f"فشل شبكة مع {base_url} ({reason}) — لا مسار متاح حاليًا",
        error_class="NETWORK_UNREACHABLE", is_transient=True,
    )


def read_json_response(
    request: Any, timeout: float, base_url: str
) -> dict:
    """ينفّذ النداء ويحوّل فشل HTTP/الشبكة إلى ``ProviderCallError`` مصنَّف.

    التصنيف هو ما يبني عليه المستدعي قراره (اختناق 429 / خطأ خادم 5xx
    / مهلة شبكة / خطأ عميل) — لا رسالة نصية يُخمَّن منها.

    (RLR-001 §1) كل فرع يحمّل ``error_class`` الصريح وفق العقد أعلاه.
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
                error_class="RATE_LIMITED",
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            ) from error
        if code in (401, 403):
            raise ProviderCallError(
                f"{code} فشل مصادقة من {base_url} (مفتاح مرفوض/ناقص): {detail}",
                code=code,
                error_class="AUTH_FAILURE",
            ) from error
        if code >= 500:
            raise ProviderCallError(
                f"{code} خطأ خادم من {base_url}: {detail}",
                code=code,
                is_server_error=True,
                error_class="SERVER_ERROR",
            ) from error
        raise ProviderCallError(
            f"{code} رد غير صالح من {base_url} (مفتاح/عنوان/طلب؟): {detail}",
            code=code,
            error_class="INVALID_RESPONSE",
        ) from error
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        raise classify_network_error(error, base_url) from error
    except OSError as error:
        # انقطاع أثناء القراءة (connection reset…) — نفس مسار التصنيف
        raise classify_network_error(error, base_url) from error


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
            error_class="INVALID_RESPONSE",
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
            error_class="INVALID_RESPONSE",
        )
    return content
