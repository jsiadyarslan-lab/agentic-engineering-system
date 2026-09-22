"""اختبار قدرة المتصفح الحقيقي (013 §43) — smoke بأدلة ملموسة.

المشهد الحرفي من الأمر (§43):
1. launch browser ← 2. navigate إلى HTTPS ← 3. wait ← 4. extract title
← 5. extract body ← 6. screenshot ← 7. save artifact ← 8. close browser
كل خطوة evidence-backed: لقطة بـsha256 وحجم، نص ببصمة، أثر JSON.

تُتخطى الاختبارات الحية بصدق (skip مع السبب) إذا كان Chromium غير
متاح في بيئة التشغيل — القدرة تظهر NOT_READY بسببها، لا READY مزيف.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from browser import service as browser_service  # noqa: E402
from browser.policy import (  # noqa: E402
    BrowserPolicy,
    PolicyViolation,
)
from browser.provider import DEFAULT_PROVIDER  # noqa: E402


def _browser_available() -> tuple[bool, str]:
    return DEFAULT_PROVIDER.available()


pytestmark = pytest.mark.skipif(
    not _browser_available()[0],
    reason=f"Chromium غير متاح في هذه البيئة — {_browser_available()[1]}",
)


def test_browser_smoke_real_navigation_evidence(tmp_path, monkeypatch):
    """(§43) البند الحرفي: تشغيل ← تنقل HTTPS ← انتظار ← عنوان ونص ←
    لقطة ← أثر ← إغلاق — كل خطوة بنتيجة قابلة للفحص."""
    monkeypatch.chdir(tmp_path)

    # 1. launch browser — جلسة حية بأحداث مسجلة
    events: list[tuple[str, dict]] = []
    opened = browser_service.open_session(
        on_event=lambda kind, event: events.append((kind, event))
    )
    session = browser_service.get_session(opened["session_id"])
    assert opened["provider"] == "playwright-chromium"
    assert any(k == "browser.session.created" for k, _ in events)

    try:
        # 2. navigate إلى موقع HTTPS حقيقي
        session.new_page()
        nav = session.navigate("https://example.com")
        assert nav["http_status"] == 200
        assert "Example" in nav["title"]
        assert any(k == "browser.navigate" for k, _ in events)
        assert any(k == "browser.page.loaded" for k, _ in events)

        # 3. wait
        waited = session.wait(0.5)
        assert waited["waited_s"] == 0.5

        # 4. extract title (من نتيجة التنقل) + 5. extract body
        text = session.extract_text()
        assert text["chars"] > 50, "نص الصفحة فارغ — الاستخلاص مكسور"
        assert "Example" in text["excerpt"]
        assert len(text["sha256"]) == 64

        # 6. screenshot — دليل ملموس بحجم وبصمة
        shot = session.screenshot("smoke")
        shot_path = Path(shot["file"])
        assert shot_path.exists()
        assert shot["bytes"] > 5000
        assert len(shot["sha256"]) == 64
        # 7. save artifact — البصمة تطابق الملف فعليًا
        import hashlib

        digest = hashlib.sha256(shot_path.read_bytes()).hexdigest()
        assert digest == shot["sha256"], "بصمة اللقطة لا تطابق ملفها"
    finally:
        # 8. close browser — تنظيف صريح
        closed = browser_service.close_session(opened["session_id"])
        assert closed["closed"] is True
        assert any(k == "browser.session.closed" for k, _ in events)

    # كل عمليات §13 الثماني موثقة أحداثًا
    kinds = [k for k, _ in events]
    for required in ("browser.session.created", "browser.navigate",
                     "browser.page.loaded", "browser.extract",
                     "browser.screenshot", "browser.session.closed"):
        assert required in kinds


def test_browser_readiness_probe_real(tmp_path, monkeypatch):
    """(§14) المسبار الرسمي: تشغيل فعلي كامل — READY بخطوات موثقة."""
    monkeypatch.chdir(tmp_path)
    result = browser_service.probe()
    assert result["status"] == "READY", result["reason"]
    steps = {s["step"]: s["ok"] for s in result["steps"]}
    # الخطوات الثماني الحرفية كلها ناجحة
    for step_name in ("chromium_available", "browser_launch", "new_page",
                      "navigate_https", "wait", "extract_title_body",
                      "screenshot", "artifact_saved", "cleanup"):
        assert steps.get(step_name) is True, \
            f"خطوة المسبار فشلت: {step_name} — {result['steps']}"
    evidence = Path(result["details"]["evidence_path"])
    assert evidence.exists(), "أثر المسبار لم يُحفظ"


def test_browser_policy_blocks_private_networks(tmp_path, monkeypatch):
    """(§15) الأمان: الشبكات الخاصة محجوبة — لا وصول للمضيف الداخلي."""
    monkeypatch.chdir(tmp_path)
    opened = browser_service.open_session()
    session = browser_service.get_session(opened["session_id"])
    try:
        for url in ("http://localhost:8000/api",
                    "http://127.0.0.1:22",
                    "http://169.254.169.254/latest/meta-data",
                    "file:///etc/passwd",
                    "ftp://example.com/file"):
            with pytest.raises(PolicyViolation):
                session.policy.check_url(url)
    finally:
        browser_service.close_session(opened["session_id"])


def test_browser_policy_allowlist(tmp_path, monkeypatch):
    """(§15) قائمة نطاقات صريحة: خارجها مرفوض."""
    monkeypatch.chdir(tmp_path)
    policy = BrowserPolicy(allowed_domains=["example.com", "iana.org"])
    assert policy.check_url("https://example.com/page") == "example.com"
    assert policy.check_url("https://sub.iana.org/why") == "sub.iana.org"
    with pytest.raises(PolicyViolation):
        policy.check_url("https://evil.example.net/")

    # وسقف التنزيل مرفوض صريحًا
    with pytest.raises(PolicyViolation):
        policy.check_download_size(policy.max_download_mb * 1024 * 1024 + 1)


def test_browser_session_page_cap(tmp_path, monkeypatch):
    """(§15) سقف الصفحات المفتوحة — لا انفجار تبويبات."""
    monkeypatch.chdir(tmp_path)
    opened = browser_service.open_session()
    session = browser_service.get_session(opened["session_id"])
    try:
        for _ in range(session.policy.max_pages):
            session.new_page()
        with pytest.raises(PolicyViolation):
            session.new_page()
    finally:
        browser_service.close_session(opened["session_id"])
