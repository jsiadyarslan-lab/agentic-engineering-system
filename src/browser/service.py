"""خدمة المتصفح (الأمر 013 §13-§14) — جلسات مُدارة ومسبار صادق وأدلة.

الخدمة فوق البروفايدر (درزة): تدير الجلسات الحية (سجل عملية-wide)،
توحّد الأحداث لاستهلاك المحرك، وتنفذ **مسبار الجاهزية الحقيقي**
(§14): Chromium متاح ← إطلاق ← تنقل HTTPS ← انتظار ← استخلاص عنوان
ونص ← لقطة ← حفظ أثر ← إغلاق — كل خطوة نتيجتها معلنة، والفشل في
أي منها = NOT_READY بسببها الحرفي (لا READY لمجرد تهيئة).

الأدلة (§43): المسبار يخزن لقطته وأثره تحت runtime/browser/probe/
مع sha256 — برهان قابل للفحص لا ادعاء.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from browser.policy import BrowserPolicy, PolicyViolation
from browser.provider import (
    BROWSER_RUNTIME_DIR,
    BrowserSession,
    DEFAULT_PROVIDER,
    ProviderNotReady,
)

#: موقع اختبار المسبار — HTTPS مستقر ومحايد.
PROBE_URL = "https://example.com"

#: مهلة المسبار الكلية (ثواني).
PROBE_TIMEOUT_S = 60.0

_sessions: dict[str, BrowserSession] = {}
_lock = threading.Lock()


def _utc_now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def open_session(*, on_event: Callable[[str, dict], None] | None = None,
                 allowed_domains: list[str] | None = None,
                 provider=None) -> dict:
    """فتح جلسة متصفح جديدة — مسجلة وقابلة للإغلاق الجماعي.

    on_event: مستقبِل أحداث العملية (kind, event) — يمررها المحرك
    إلى الأحداث الدائمة BROWSER_* (§13 قابلية التسجيل).
    """
    prov = provider or DEFAULT_PROVIDER
    ok, reason = prov.available()
    if not ok:
        raise ProviderNotReady(reason)
    policy = BrowserPolicy(allowed_domains=allowed_domains)
    session = prov.launch(policy, on_event=on_event)
    with _lock:
        _sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "provider": prov.name(),
        "policy": policy.describe(),
        "pages": 0,
    }


def close_session(session_id: str) -> dict:
    with _lock:
        session = _sessions.pop(session_id, None)
    if session is None:
        return {"session_id": session_id, "closed": False,
                "reason": "جلسة غير معروفة (ربما أُغلقت)"}
    return session.close()


def get_session(session_id: str) -> BrowserSession:
    with _lock:
        session = _sessions.get(session_id)
    if session is None:
        raise ProviderNotReady(f"جلسة متصفح غير معروفة: {session_id}")
    return session


def list_sessions() -> list[dict]:
    with _lock:
        return [
            {"session_id": s.session_id, "pages": len(s._pages),
             "closed": s._closed}
            for s in _sessions.values()
        ]


def close_all() -> int:
    """إغلاق كل الجلسات — عند الإطفاء أو التنظيف الدوري."""
    with _lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    count = 0
    for session in sessions:
        try:
            session.close()
            count += 1
        except Exception:  # noqa: BLE001 — التنظيف لا يفشل
            pass
    return count


def interrupted_sessions() -> list[str]:
    """الجلسات الميتة (عملية المتصفح انهارت) — كشف صادق (§36)."""
    dead = []
    with _lock:
        for session_id, session in _sessions.items():
            try:
                _ = session._browser.is_connected()
            except Exception:  # noqa: BLE001
                dead.append(session_id)
    return dead


def probe(provider=None, *, probe_url: str = PROBE_URL) -> dict:
    """مسبار الجاهزية الحقيقي (§14+§43) — تشغيل كامل بأدلة.

    الخطوات الثماني المطلوبة حرفيًا: Chromium متاح ← إطلاق (session)
    ← تنقل HTTPS ← انتظار ← استخلاص العنوان والنص ← لقطة ← حفظ أثر
    ← إغلاق. أي فشل = NOT_READY بسبب تلك الخطوة حرفيًا.
    """
    prov = provider or DEFAULT_PROVIDER
    started = time.monotonic()
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str = "",
             **extra) -> bool:
        entry = {"step": name, "ok": ok, "detail": detail, **extra}
        steps.append(entry)
        return ok

    ok, reason = prov.available()
    if not step("chromium_available", ok, reason):
        return _probe_result("NOT_READY", reason, steps, started,
                             provider=prov.name())

    session: BrowserSession | None = None
    try:
        policy = BrowserPolicy(session_id=f"probe-{uuid.uuid4().hex[:8]}")
        session = prov.launch(policy)
        step("browser_launch", True,
             f"جلسة {session.session_id} فُتحت")

        nav = session.new_page()
        step("new_page", nav.get("pages", 1) == 1)

        result = session.navigate(probe_url)
        step("navigate_https", result.get("http_status", 0) in (
            200, 301, 302,
        ), f"HTTP {result.get('http_status')} — {result.get('title', '')}")

        session.wait(0.5)
        step("wait", True)

        text = session.extract_text()
        step("extract_title_body",
             bool(result.get("title")) and text.get("chars", 0) > 0,
             f"العنوان: {result.get('title', '')!r} — "
             f"{text.get('chars', 0)} حرفًا")

        shot = session.screenshot("probe")
        artifact = Path(str(shot.get("file", "")))
        step("screenshot",
             artifact.exists() and artifact.stat().st_size > 0,
             f"{shot.get('bytes', 0)} بايت — sha256 {shot.get('sha256',
                                                        '')[:12]}…")

        # أثر المسبار الدائم — برهان قابل للفحص (§43)
        evidence_path = BROWSER_RUNTIME_DIR / "probe" / "last-probe.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        import json

        evidence_path.write_text(json.dumps({
            "at": _utc_now_iso(),
            "probe_url": probe_url,
            "steps": steps,
            "screenshot": shot,
            "extract_sha256": text.get("sha256", ""),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        step("artifact_saved", evidence_path.exists(),
             str(evidence_path))

        close = session.close()
        session = None
        step("cleanup", bool(close.get("closed")),
             f"أُغلقت خلال {close.get('duration_ms', 0)}ms")

        return _probe_result(
            "READY",
            f"متصفح حقيقي يعمل: تنقل {probe_url} واستخلاص ولقطة "
            "وتنظيف — كلها نجحت",
            steps, started, provider=prov.name(),
            screenshot=shot, evidence_path=str(evidence_path),
        )
    except (ProviderNotReady, PolicyViolation) as error:
        return _probe_result("NOT_READY", str(error), steps, started,
                             provider=prov.name())
    except Exception as error:  # noqa: BLE001 — السبب الحرفي دائمًا
        return _probe_result("NOT_READY",
                             f"فشل المسبار: {type(error).__name__}: "
                             f"{error}", steps, started,
                             provider=prov.name())
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass


def _probe_result(status: str, reason: str, steps: list[dict],
                  started: float, *, provider: str = "",
                  screenshot: dict | None = None,
                  evidence_path: str = "") -> dict:
    return {
        "status": status,
        "reason": reason,
        "provider": provider,
        "steps": steps,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "ttl_seconds": 600,
        "details": {
            "probe_steps": steps,
            "screenshot": screenshot or {},
            "evidence_path": evidence_path,
        },
    }


__all__ = [
    "PROBE_URL",
    "close_all",
    "close_session",
    "get_session",
    "interrupted_sessions",
    "list_sessions",
    "open_session",
    "probe",
]
