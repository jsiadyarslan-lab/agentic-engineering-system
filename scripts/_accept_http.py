"""أدوات HTTP/SSE/قاعدة للقبول الحي — الأمر 013.5 §P.

مكتبة بايثون القياسية وحدها (urllib/sqlite3/socket/json): لا تبعية
جديدة، ولا استيراد من src هنا — هذه وحدة نقل صرفة.

القاعدة الأخلاقية لهذه الأدوات — الصدق قبل الراحة:

- كل دالة تعيد **مغلّفًا صادقًا**::

      {"ok": bool, "status": int|None, "data": obj|None,
       "error": str|None, "at": iso, "url": str, "method": str,
       "duration_ms": float|None, "extra": {...}}

  الفشل يُعلن في ``error`` ولا يُبتلع؛ والقيمة غير المتاحة تبقى
  ``None`` ولا تُستبدل بصفر أو نص مخترع.
- ``unreachable`` في ``extra`` تفرّق بين «الخادم غير متاح» (لا رد
  أصلًا) و«الخادم رد بخطأ» (4xx/5xx) — فرق جوهري في الحكم (§P.3).
- ``post_sse`` يقرأ بث SSE حقيقي سطرًا سطرًا ويتوقف عند الأحداث
  الخاتمة المعلنة، ويسجّل انتهاء المهلة بصدق (``timed_out``).

تشغيل: يُستورد فقط من ``scripts/order0135_acceptance.py``.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

#: رؤوس الطلب الموحدة — JSON صريح، والرد يُقبل JSON أو SSE.
_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json, text/event-stream",
    "User-Agent": "order0135-acceptance/1.0 (stdlib urllib)",
}


# ------------------------------------------------------------------ #
# الزمن — الطوابع الحقيقية المعلنة في الأدلة
# ------------------------------------------------------------------ #

def utc_now() -> str:
    """طابع UTC بصيغة ISO-8601 بالثواني (زمن الجدار الحقيقي)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stamp() -> str:
    """طابع اسم الملف: 20260922T203600Z."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _envelope(
    ok: bool,
    *,
    status: int | None = None,
    data=None,
    error: str | None = None,
    at: str | None = None,
    url: str = "",
    method: str = "",
    duration_ms: float | None = None,
    extra: dict | None = None,
) -> dict:
    """بناء المغلّف الموحد — كل حقل معلن حتى لو كان None."""
    return {
        "ok": bool(ok),
        "status": status,
        "data": data,
        "error": error,
        "at": at or utc_now(),
        "url": url,
        "method": method,
        "duration_ms": duration_ms,
        "extra": extra or {},
    }


def join(base: str, path: str) -> str:
    """دمج عنوان أساسي بمسار بلا شرطتين مكررتين."""
    return base.rstrip("/") + "/" + path.lstrip("/")


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000.0, 1)


# ------------------------------------------------------------------ #
# JSON عبر HTTP
# ------------------------------------------------------------------ #

def request_json(
    method: str,
    base: str,
    path: str,
    body: dict | None = None,
    *,
    timeout: float = 30.0,
) -> dict:
    """طلب HTTP يعيد JSON — الفشل يُعلن ولا يرفع استثناءً للقبول."""
    url = join(base, path)
    at = utc_now()
    start = time.monotonic()
    payload = (
        json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is not None
        else None
    )
    request = urllib.request.Request(
        url, method=method, data=payload, headers=dict(_HEADERS)
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200) or 200)
            text = raw.decode("utf-8", "replace")
            parsed = None
            parse_error = None
            if text.strip():
                try:
                    parsed = json.loads(text)
                except ValueError as error:
                    parse_error = f"رد ليس JSON: {error}"
            return _envelope(
                parse_error is None,
                status=status,
                data=parsed,
                error=parse_error,
                at=at,
                url=url,
                method=method,
                duration_ms=_elapsed_ms(start),
                extra={
                    "content_type": response.headers.get("content-type", ""),
                    "bytes": len(raw),
                    "text_head": None if parsed is not None else text[:400],
                },
            )
    except urllib.error.HTTPError as error:
        body_text = ""
        try:
            body_text = error.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — قراءة جسم الخطأ كمالية
            body_text = ""
        return _envelope(
            False,
            status=int(getattr(error, "code", 0) or 0) or None,
            data=None,
            error=f"HTTP {getattr(error, 'code', '?')}: {body_text[:400]}",
            at=at,
            url=url,
            method=method,
            duration_ms=_elapsed_ms(start),
            extra={"unreachable": False, "text_head": body_text[:400]},
        )
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        return _envelope(
            False,
            status=None,
            data=None,
            error=f"{type(error).__name__}: {error}",
            at=at,
            url=url,
            method=method,
            duration_ms=_elapsed_ms(start),
            extra={"unreachable": True},
        )


def get_json(base: str, path: str, *, timeout: float = 30.0) -> dict:
    """GET يعيد JSON (مغلّف صادق)."""
    return request_json("GET", base, path, None, timeout=timeout)


def post_json(
    base: str, path: str, body: dict | None = None, *, timeout: float = 60.0
) -> dict:
    """POST يعيد JSON (مغلّف صادق)."""
    return request_json("POST", base, path, body if body is not None else {},
                        timeout=timeout)


def health(base: str, *, timeout: float = 5.0) -> dict:
    """فحص حياة الخادم — ``GET /health`` (src/api/routes.py:226)."""
    return get_json(base, "/health", timeout=timeout)


# ------------------------------------------------------------------ #
# بث SSE — قراءة حقيقية سطرًا سطرًا
# ------------------------------------------------------------------ #

def post_sse(
    base: str,
    path: str,
    body: dict | None = None,
    *,
    timeout: float = 600.0,
    terminal_kinds: tuple[str, ...] = ("message_completed", "chat.error"),
    max_events: int = 20000,
    on_event=None,
) -> dict:
    """POST يبث SSE (‎/api/chat/stream) — يقرأ حتى نهاية معلنة أو EOF.

    العقد المقروء: كل حدث سطر واحد ``data: {json}`` بلا أسطر متعددة
    (src/api/routes.py:_sse_response + live_stream). الأسطر ``id:``
    و``event:`` والتعليقات ``:`` تُتخطى وتُعدّ.

    التوقف: حدث خاتم من ``terminal_kinds``، أو EOF (الخادم أغلق البث)،
    أو انتهاء المهلة (``timed_out=True``)، أو سقف الأحداث.
    """
    url = join(base, path)
    at = utc_now()
    start = time.monotonic()
    payload = (
        json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is not None
        else None
    )
    request = urllib.request.Request(
        url, method="POST", data=payload, headers=dict(_HEADERS)
    )
    events: list[dict] = []
    unparsed: list[str] = []
    counters = {"lines": 0, "data_lines": 0, "comments": 0, "id_lines": 0,
                "event_lines": 0, "unparsed": 0}
    terminal_kind = None
    timed_out = False
    status = None
    content_type = ""
    error = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            content_type = response.headers.get("content-type", "")
            while True:
                try:
                    raw = response.readline()
                except (socket.timeout, TimeoutError):
                    timed_out = True
                    break
                except OSError as read_error:
                    error = f"انقطاع القراءة: {type(read_error).__name__}: {read_error}"
                    break
                if not raw:
                    break
                counters["lines"] += 1
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if not line:
                    continue
                if line.startswith(":"):
                    counters["comments"] += 1
                    continue
                if line.startswith("id:"):
                    counters["id_lines"] += 1
                    continue
                if line.startswith("event:"):
                    counters["event_lines"] += 1
                    continue
                if not line.startswith("data:"):
                    unparsed.append(line[:200])
                    counters["unparsed"] += 1
                    continue
                counters["data_lines"] += 1
                chunk = line[5:].strip()
                if not chunk:
                    continue
                try:
                    event = json.loads(chunk)
                except ValueError:
                    unparsed.append(chunk[:200])
                    counters["unparsed"] += 1
                    continue
                if not isinstance(event, dict):
                    unparsed.append(chunk[:200])
                    counters["unparsed"] += 1
                    continue
                events.append(event)
                if on_event is not None:
                    try:
                        on_event(event)
                    except Exception:  # noqa: BLE001 — المراقب لا يكسر البث
                        pass
                if event.get("kind") in terminal_kinds:
                    terminal_kind = event.get("kind")
                    break
                if len(events) >= max_events:
                    error = f"بلغنا سقف الأحداث ({max_events}) — أوقفنا القراءة"
                    break
    except urllib.error.HTTPError as http_error:
        body_text = ""
        try:
            body_text = http_error.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body_text = ""
        return _envelope(
            False, status=int(getattr(http_error, "code", 0) or 0) or None,
            data={"events": events, "counters": counters,
                  "unparsed": unparsed, "terminal_kind": terminal_kind,
                  "timed_out": False},
            error=f"HTTP {getattr(http_error, 'code', '?')}: {body_text[:400]}",
            at=at, url=url, method="POST", duration_ms=_elapsed_ms(start),
            extra={"unreachable": False, "terminal_kind": terminal_kind},
        )
    except (urllib.error.URLError, OSError, TimeoutError) as connect_error:
        return _envelope(
            False, status=None,
            data={"events": events, "counters": counters,
                  "unparsed": unparsed, "terminal_kind": None,
                  "timed_out": False},
            error=f"{type(connect_error).__name__}: {connect_error}",
            at=at, url=url, method="POST", duration_ms=_elapsed_ms(start),
            extra={"unreachable": True},
        )
    ok = terminal_kind is not None and error is None
    return _envelope(
        ok, status=status,
        data={"events": events, "counters": counters, "unparsed": unparsed,
              "terminal_kind": terminal_kind, "timed_out": timed_out,
              "streamed_bytes": None},
        error=error, at=at, url=url, method="POST",
        duration_ms=_elapsed_ms(start),
        extra={"unreachable": False, "content_type": content_type,
               "terminal_kind": terminal_kind, "timed_out": timed_out,
               "events": len(events)},
    )


# ------------------------------------------------------------------ #
# المصادر الحقيقية — «نتيجة بلا مصدر حقيقي = فشل» (§P.2)
# ------------------------------------------------------------------ #

def is_real_url(value) -> bool:
    """رابط حقيقي: مخطط http/https ومضيف غير فارغ (لا نص يشبه رابطًا)."""
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urllib.parse.urlparse(value.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def real_source_urls(items) -> list[str]:
    """الروابط الحقيقية وحدها من قائمة نتائج/مصادر — بالترتيب وبلا تكرار."""
    out: list[str] = []
    for item in items or []:
        url = item.get("url") if isinstance(item, dict) else item
        if is_real_url(url):
            clean = str(url).strip()
            if clean not in out:
                out.append(clean)
    return out


def normalized_provider(name) -> str:
    """اسم المزود بلا لاحقة التكوين — nvidia::default ← nvidia."""
    return str(name or "").split("::", 1)[0]


def transport_key(provider: str, configuration: str | None) -> str:
    """مفتاح النقل كما يبنيه الخادم (src/router/role_config.py:62-66)."""
    if configuration and configuration != "default":
        return f"{provider}::{configuration}"
    return provider


# ------------------------------------------------------------------ #
# القاعدة — قراءة فقط، بلا أي كتابة
# ------------------------------------------------------------------ #

def db_connect_ro(path: Path | str) -> sqlite3.Connection:
    """اتصال قراءة-فقط (mode=ro) — القبول لا يكتب في قاعدة التشغيل."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=15.0)
    connection.row_factory = sqlite3.Row
    return connection


def db_rows(connection: sqlite3.Connection, sql: str,
            params: tuple = ()) -> list[dict]:
    """كل الصفوف كقواميس — بلا تحويل صامت لأي قيمة."""
    return [dict(row) for row in connection.execute(sql, params)]


def db_one(connection: sqlite3.Connection, sql: str,
           params: tuple = ()) -> dict | None:
    """صف واحد أو None — الصدق عند الغياب."""
    rows = db_rows(connection, sql, params)
    return rows[0] if rows else None


def safe_db(connection: sqlite3.Connection, sql: str,
            params: tuple = ()) -> tuple[list[dict], str | None]:
    """قراءة تتحمل غياب الجدول/العمود — تعيد (صفوف, سبب الفشل أو None)."""
    try:
        return db_rows(connection, sql, params), None
    except sqlite3.Error as error:
        return [], f"{type(error).__name__}: {error}"


__all__ = [
    "db_connect_ro",
    "db_one",
    "db_rows",
    "get_json",
    "health",
    "is_real_url",
    "join",
    "normalized_provider",
    "post_json",
    "post_sse",
    "real_source_urls",
    "request_json",
    "safe_db",
    "stamp",
    "transport_key",
    "utc_now",
]
