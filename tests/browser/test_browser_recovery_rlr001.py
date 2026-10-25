"""اختبارات استرداد جلسة المتصفح الميتة + الفحص المباشر (AES-RLR-001 §4d).

العقود المختبرة:
- الجلسة الميتة بالإيجاب (``_closed=True`` أو ``is_connected() is False``)
  تُغلق محاولةً وتُستبدل بجلسة جديدة — لا فشل 4ms متكرر بعد الاستئناف.
- الجلسة الحية تُعاد كما هي بلا إعادة فتح ولا إغلاق.
- الكائنات بلا سمات فحص (مقلدات الاختبارات القديمة) لا تُقتل زورًا.
- فشل إغلاق الجلسة الميتة لا يمنع الاستبدال.
- ``available()`` يجد Chromium من القرص مباشرة **بلا تشغيل تعريف**
  (لا عملية node في كل إطلاق — جذر «تعذر فحص Chromium») ويعيد
  NOT_READY الصادق عند غياب المسار عن جميع الجذور المعروفة.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import roles.browser_tools as bt  # noqa: E402


class _FakeBrowser:
    def __init__(self, connected: bool = True):
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected


class _FakeSession:
    """جلسة شبيهة بالحقيقية — ``_browser`` حقيقي الشكل."""

    def __init__(self, session_id: str, *, closed: bool = False,
                 connected: bool = True):
        self.session_id = session_id
        self._closed = closed
        self._browser = _FakeBrowser(connected)
        self._pages = []


class _PlainFake:
    """كائن بلا سمات فحص — مثل مقلدات الاختبارات القديمة."""

    def __init__(self, session_id: str):
        self.session_id = session_id


class _Ctx:
    pass


@pytest.fixture()
def seeded(monkeypatch):
    """تثبيت خدمة المتصفح بمصنع فكيات قابل للتتبع."""
    made: list = []
    closed_ids: list = []

    def fake_open(*, on_event=None, allowed_domains=None, provider=None):
        session = _FakeSession(f"brs-fake-{len(made) + 1}")
        made.append(session)
        return {"session_id": session.session_id, "pages": 0}

    def fake_get(session_id: str):
        for s in made:
            if s.session_id == session_id:
                return s
        raise bt.browser_service.ProviderNotReady(
            f"جلسة متصفح غير معروفة: {session_id}")

    def fake_close(session_id: str):
        closed_ids.append(session_id)
        return {"session_id": session_id, "closed": True}

    monkeypatch.setattr(bt.browser_service, "open_session", fake_open)
    monkeypatch.setattr(bt.browser_service, "get_session", fake_get)
    monkeypatch.setattr(bt.browser_service, "close_session", fake_close)
    return {"made": made, "closed": closed_ids}


def test_dead_session_is_replaced_once(seeded):
    ctx = _Ctx()
    stale = _FakeSession("brs-dead", closed=True)
    ctx._browser_session = stale
    session = bt._session_of(ctx)
    assert session is not stale
    assert session.session_id == "brs-fake-1"
    assert seeded["closed"] == ["brs-dead"]
    again = bt._session_of(ctx)
    assert again is session
    assert len(seeded["made"]) == 1


def test_disconnected_browser_is_replaced(seeded):
    ctx = _Ctx()
    ctx._browser_session = _FakeSession("brs-disc", connected=False)
    session = bt._session_of(ctx)
    assert session._browser.is_connected() is True
    assert seeded["closed"] == ["brs-disc"]


def test_alive_session_is_reused(seeded):
    ctx = _Ctx()
    alive = _FakeSession("brs-alive", connected=True)
    ctx._browser_session = alive
    assert bt._session_of(ctx) is alive
    assert seeded["made"] == []
    assert seeded["closed"] == []


def test_plain_mock_like_session_is_not_killed(seeded):
    ctx = _Ctx()
    plain = _PlainFake("brs-plain")
    ctx._browser_session = plain
    assert bt._session_of(ctx) is plain
    assert seeded["made"] == []


def test_stale_close_failure_does_not_block_reopen(seeded, monkeypatch):
    def broken_close(session_id: str):
        raise RuntimeError("ميت ولا يُغلق")

    monkeypatch.setattr(bt.browser_service, "close_session", broken_close)
    ctx = _Ctx()
    ctx._browser_session = _FakeSession("brs-zombie", closed=True)
    session = bt._session_of(ctx)
    assert session.session_id == "brs-fake-1"


def test_no_session_opens_lazy(seeded):
    ctx = _Ctx()
    session = bt._session_of(ctx)
    assert session.session_id == "brs-fake-1"
    assert len(seeded["made"]) == 1


# --------------------------------------------------------------------------- #
# available() — الفحص المباشر من القرص بلا تشغيل تعريف Playwright
# --------------------------------------------------------------------------- #


def _fake_chromium_root(tmp_path: Path) -> Path:
    root = tmp_path / "pw-browsers"
    exe_dir = root / "chromium-9999" / "chrome-linux"
    exe_dir.mkdir(parents=True)
    (exe_dir / "chrome").write_bytes(b"#!/bin/sh\n")
    return root


def test_direct_path_found_without_driver_spawn(monkeypatch, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    import browser.provider as prov_mod

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                       str(_fake_chromium_root(tmp_path)))

    def _boom(*args, **kwargs):
        raise RuntimeError("spawn يجب ألا يحدث — المسار المباشر يكفي")

    monkeypatch.setattr(playwright, "sync_playwright", _boom)
    ok, reason = prov_mod.PlaywrightBrowserProvider().available()
    assert ok is True
    assert "chromium-9999" in reason


def test_direct_path_none_when_roots_missing(monkeypatch, tmp_path):
    import browser.provider as prov_mod

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                       str(tmp_path / "absent-root"))
    monkeypatch.setattr(prov_mod.Path, "home",
                        lambda: tmp_path / "absent-home")
    provider = prov_mod.PlaywrightBrowserProvider()
    assert provider._chromium_direct_path() is None


def test_headless_variants_are_ignored(monkeypatch, tmp_path):
    import browser.provider as prov_mod

    root = tmp_path / "pw-browsers"
    shell = root / "chromium_headless_shell-1248" / "chrome-linux"
    shell.mkdir(parents=True)
    (shell / "headless_shell").write_bytes(b"x")
    real = root / "chromium-1248" / "chrome-linux"
    real.mkdir(parents=True)
    (real / "chrome").write_bytes(b"x")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))
    found = prov_mod.PlaywrightBrowserProvider()._chromium_direct_path()
    assert found is not None and "chromium_headless_shell" not in str(found)


def test_arm64_layout_is_found(monkeypatch, tmp_path):
    import browser.provider as prov_mod

    root = tmp_path / "pw-browsers"
    exe_dir = root / "chromium-1248" / "chrome-linux-arm64"
    exe_dir.mkdir(parents=True)
    (exe_dir / "chrome").write_bytes(b"x")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))
    found = prov_mod.PlaywrightBrowserProvider()._chromium_direct_path()
    assert found is not None and "chrome-linux-arm64" in str(found)
