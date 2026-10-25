"""أدوات المتصفح للمنفذ (الأمر 013 §13+§28) — نشاط متصفح حي في الدورة.

الأدوات بيضاء (تُوثق وتصنف ككل أداة) وتنفذ عبر خدمة المتصفح مع
السياسة الكاملة (§15): فحص النطاقات، رمل التنزيلات، سقوف الصفحات،
ومهل معلنة. كل عملية تُبث حدث browser.* عبر ToolContext.emit فتصل
المحرك ويكتبها حدثًا دائمًا BROWSER_* — النشاط يظهر حيًّا في
الواجهة (🌐 فتح الموقع… 📸 لقطة…).

الجلسة تُدار لكل سياق أدوات (جلسة واحدة تكفي الدورة): أول أداة
متصفح تفتحها، وأدوات الدورة اللاحقة تشاركها.
"""

from __future__ import annotations

from typing import Any

from browser import service as browser_service
from browser.provider import ProviderNotReady
from roles.tools import ToolFailure

#: مفتاح جلسة المتصفح داخل ToolContext (سعة ديناميكية موثقة).
_SESSION_KEY = "_browser_session"


def _session_of(ctx) -> Any:
    """جلسة المتصفح للسياق — تُفتح كسولة عند أول استخدام."""
    session = getattr(ctx, _SESSION_KEY, None)
    if session is not None:
        return session
    return _open_fresh_session(ctx)


def _open_fresh_session(ctx) -> Any:
    """فتح جلسة جديدة وتثبيتها في السياق (RLR-001 §4d)."""
    opened = browser_service.open_session(on_event=_emitter_of(ctx))
    session = browser_service.get_session(opened["session_id"])
    try:
        setattr(ctx, _SESSION_KEY, session)
    except (AttributeError, TypeError):  # pragma: no cover — كائن مقيد
        pass
    return session


def _emitter_of(ctx):
    def emit(kind: str, event: dict) -> None:
        ctx.emit({"kind": kind, "role": "implementer", **{
            k: v for k, v in event.items() if k != "kind"
        }})
    return emit


def _fail(tool: str, error: Exception) -> ToolFailure:
    return ToolFailure(
        tool, f"فشل المتصفح: {error}",
        failure_class="BROWSER_FAILURE",
        reason=type(error).__name__,
        stage="BROWSER_EXECUTION",
        retryable=True,
    )


def browser_navigate(url: str, ctx) -> dict:
    """التنقل إلى رابط — فحص السياسة ثم تنقل فعلي وحدث حي.

    (RLR-001 §4d) جلسة ميتة (بعد استئناف دورة/إغلاق سابق) تفشل فورًا
    (‎~4ms) فيتكرر الفشل حتى يحكم المحكم بالركود. الفشل الفوري هنا
    يستعيد جلسة حية ويحاول مرة واحدة — والفشل بعدها صادق مفصّل.
    """
    try:
        session = _session_of(ctx)
        if not getattr(session, "_pages", None):
            session.new_page()
        result = session.navigate(url)
        ctx.fetched_urls = list(getattr(ctx, "fetched_urls", [])) + [url]
        return {"ok": True, **result}
    except Exception as error:  # noqa: BLE001 — استرداد جلسة ثم صدق
        try:
            fresh = _open_fresh_session(ctx)
            if not getattr(fresh, "_pages", None):
                fresh.new_page()
            result = fresh.navigate(url)
            ctx.fetched_urls = list(
                getattr(ctx, "fetched_urls", [])) + [url]
            return {"ok": True, "session_recovered": True, **result}
        except Exception:
            raise _fail("browser_navigate", error) from error


def browser_click(selector: str, ctx) -> dict:
    try:
        return {"ok": True, **_session_of(ctx).click(selector)}
    except Exception as error:  # noqa: BLE001
        raise _fail("browser_click", error) from error


def browser_type(selector: str, text: str, ctx) -> dict:
    try:
        return {"ok": True, **_session_of(ctx).type(selector, text)}
    except Exception as error:  # noqa: BLE001
        raise _fail("browser_type", error) from error


def browser_extract(mode: str = "text", limit: int = 50, ctx=None) -> dict:
    """استخلاص المحتوى — نص الصفحة أو روابطها."""
    try:
        session = _session_of(ctx)
        if mode == "links":
            return {"ok": True, **session.extract_links(limit=limit)}
        return {"ok": True, **session.extract_text()}
    except Exception as error:  # noqa: BLE001
        raise _fail("browser_extract", error) from error


def browser_screenshot(name: str = "", ctx=None) -> dict:
    """لقطة شاشة — أثر ملموس بـsha256 داخل أدلة الجلسة."""
    try:
        result = _session_of(ctx).screenshot(name)
        return {"ok": True, **result}
    except Exception as error:  # noqa: BLE001
        raise _fail("browser_screenshot", error) from error


def browser_download(url: str, ctx) -> dict:
    """تنزيل ملف — داخل رمل الجلسة حصرًا وبسقف الحجم."""
    try:
        return {"ok": True, **_session_of(ctx).download(url)}
    except Exception as error:  # noqa: BLE001
        raise _fail("browser_download", error) from error


def browser_wait(seconds: float = 1.0, ctx=None) -> dict:
    try:
        return {"ok": True, **_session_of(ctx).wait(seconds)}
    except Exception as error:  # noqa: BLE001
        raise _fail("browser_wait", error) from error


def close_browser(ctx) -> dict:
    """إغلاق جلسة المتصفح — تنظيف صريح عند نهاية الدورة."""
    session = getattr(ctx, _SESSION_KEY, None)
    if session is None:
        return {"ok": True, "closed": False, "reason": "لا جلسة مفتوحة"}
    result = browser_service.close_session(session.session_id)
    try:
        delattr(ctx, _SESSION_KEY)
    except AttributeError:
        pass
    return {"ok": True, **result}


__all__ = [
    "browser_click",
    "browser_download",
    "browser_extract",
    "browser_navigate",
    "browser_screenshot",
    "browser_type",
    "browser_wait",
    "close_browser",
]


def run_browser_tool(name: str, args: dict, ctx) -> dict:
    """موزّع أدوات المتصفح الموحد (013 §13) — نقطة استدعاء واحدة
    من roles/tools.run_tool تُبقي ملف الأدوات رقيقًا (عقد الرقة)."""
    if name == "browser_navigate":
        return browser_navigate(str(args.get("url", "")), ctx)
    if name == "browser_click":
        return browser_click(str(args.get("selector", "")), ctx)
    if name == "browser_type":
        return browser_type(str(args.get("selector", "")),
                            str(args.get("text", "")), ctx)
    if name == "browser_extract":
        return browser_extract(mode=str(args.get("mode", "text")),
                               limit=int(args.get("limit", 50)), ctx=ctx)
    if name == "browser_screenshot":
        return browser_screenshot(str(args.get("name", "")), ctx=ctx)
    if name == "browser_download":
        return browser_download(str(args.get("url", "")), ctx)
    if name == "browser_wait":
        return browser_wait(float(args.get("seconds", 1.0)), ctx=ctx)
    raise ToolFailure(
        name, f"أداة متصفح غير معروفة: {name}",
        failure_class="INPUT_FAILURE", reason="TOOL_NOT_WHITELISTED",
        stage="TOOL_START", retryable=False,
    )
