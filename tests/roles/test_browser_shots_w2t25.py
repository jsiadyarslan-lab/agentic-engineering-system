"""اختبارات W2-T25 — الشواهد البصرية المحلية (قياس 745).

الدافع المقيس (الخطوة 745، المحاولة 1): معايير «أدلة بصرية» تطلب
‎evidence/list-mobile.png وأخواتها — ثلاثة جدران ميكانيكية:
(1) أدوات المتصفح خارج بروتوكول خطة الأدوات (لا _LINE_TOOLS ولا
_KV_LINE_TOOLS) فلا يستطيع النموذج تخطيطها أصلًا؛
(2) browser_screenshot يكتب في أدلة الجلسة لا مساحة الخطوة، وبشاشة
ثابتة 1280×800 (لا وسائط عرض 375/1280)؛
(3) create_files يطالب النموذج كتابة PNG نصًا فيرفضه «امتداد غير
مسموح» بعد إعادة واحدة — ROLE_SYSTEM_FAULT متكرر أبدًا.

العقد الجديد: browser_open_local يفتح صفحة من مساحة الخطوة
(file:// محلي بامتداد صفحة حصرًا)، browser_screenshot يقبل
name/width/height ويحفظ نسخة داخل مساحة الخطوة، والمنفذ يفصل
اللقطات عن الملفات النصية (لا مطالبة نصية بصورة أبدًا — تحقق
وجود على القرص) والأداتان في القائمة البيضاء والمانيفست
وبروتوكول السطر.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from roles import browser_tools  # noqa: E402
from roles.browser_tools import (  # noqa: E402
    browser_open_local,
    browser_screenshot,
    run_browser_tool,
)
from roles.implementer_live import _SHOT_EXTS  # noqa: E402
from roles.tool_failures import ToolFailure  # noqa: E402
from roles.tool_manifest import TOOLS_MANIFEST  # noqa: E402
from roles.tools import BROWSER_TOOLS, TOOL_WHITELIST  # noqa: E402


class _FakeSession:
    """جلسة متصفح وهمية — تسجل النداءات وتكتب PNG حقيقية صغيرة."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.shot_calls: list[tuple] = []
        self.local_calls: list[str] = []
        self._pages = [object()]  # صفحة مفتوحة افتراضيًا

    def screenshot(self, name: str = "", width: int = 0,
                   height: int = 0) -> dict:
        self.shot_calls.append((name, width, height))
        path = self.tmp / ("fake-" + (name or "x").replace("/", "-") + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        return {"file": str(path), "bytes": path.stat().st_size,
                "sha256": "ab" * 16}

    def open_local(self, abs_path: str) -> dict:
        self.local_calls.append(abs_path)
        return {"file": abs_path, "url": "file://" + abs_path,
                "title": "صفحة الاختبار", "duration_ms": 3}


class _Ctx:
    def __init__(self, root: Path):
        self.grant_root = root


@pytest.fixture()
def ctx(tmp_path):
    return _Ctx(tmp_path)


@pytest.fixture()
def session(tmp_path, monkeypatch):
    fake = _FakeSession(tmp_path / "session-artifacts")
    monkeypatch.setattr(browser_tools, "_session_of", lambda c: fake)
    return fake


# ------------------------------------------------------------------ #
# 1) browser_screenshot: name مسار نسبي ⇒ نسخة داخل مساحة الخطوة
# ------------------------------------------------------------------ #

def test_screenshot_copies_into_step_workspace(tmp_path, ctx, session):
    out = browser_screenshot("evidence/list-mobile", 375, 667, ctx=ctx)
    step_png = tmp_path / "evidence" / "list-mobile.png"
    assert step_png.is_file()
    assert step_png.read_bytes().startswith(b"\x89PNG")
    assert out["step_file"] == str(step_png)
    assert out["step_bytes"] == step_png.stat().st_size
    assert session.shot_calls == [("evidence/list-mobile", 375, 667)]


def test_screenshot_png_suffix_not_doubled(tmp_path, ctx, session):
    browser_screenshot("evidence/x.png", 1280, 800, ctx=ctx)
    assert (tmp_path / "evidence" / "x.png").is_file()
    assert not (tmp_path / "evidence" / "x.png.png").exists()


def test_screenshot_without_viewport_keeps_zero(tmp_path, ctx, session):
    browser_screenshot("plain-shot", ctx=ctx)
    assert session.shot_calls == [("plain-shot", 0, 0)]
    assert (tmp_path / "plain-shot.png").is_file()


def test_screenshot_bad_width_falls_to_zero(ctx, session):
    out = browser_screenshot("s", "big", None, ctx=ctx)
    assert session.shot_calls[-1] == ("s", 0, 0)
    assert out["ok"] is True


# ------------------------------------------------------------------ #
# 2) browser_open_local: صفحة من مساحة الخطوة حصرًا
# ------------------------------------------------------------------ #

def test_open_local_accepts_step_page(tmp_path, ctx, session):
    (tmp_path / "index.html").write_text(
        "<html><body>مرحبا</body></html>", encoding="utf-8")
    out = browser_open_local("index.html", ctx=ctx)
    assert out["ok"] is True
    assert session.local_calls == [str(tmp_path / "index.html")]


@pytest.mark.parametrize("bad", ["../outside.html", "/abs.html", "", "a/../b.html"])
def test_open_local_rejects_unsafe_path(bad, ctx, session):
    with pytest.raises(ToolFailure) as err:
        browser_open_local(bad, ctx=ctx)
    assert err.value.failure_class == "INPUT_FAILURE"
    assert session.local_calls == []


def test_open_local_rejects_non_page_ext(ctx, session):
    with pytest.raises(ToolFailure) as err:
        browser_open_local("data/articles.json", ctx=ctx)
    assert err.value.reason == "BAD_EXT"


def test_open_local_rejects_missing_file(ctx, session):
    with pytest.raises(ToolFailure) as err:
        browser_open_local("ghost.html", ctx=ctx)
    assert err.value.reason == "FILE_MISSING"


# ------------------------------------------------------------------ #
# 3) الموزّع والقوائم والمانيفست وبروتوكول السطر
# ------------------------------------------------------------------ #

def test_dispatcher_passes_viewport_args(ctx, session, monkeypatch):
    seen = {}

    def fake(name, width, height, ctx=None):
        seen.update(name=name, width=width, height=height)
        return {"ok": True}

    monkeypatch.setattr(browser_tools, "browser_screenshot", fake)
    run_browser_tool("browser_screenshot",
                     {"name": "evidence/x", "width": "375", "height": "667"},
                     ctx)
    assert seen == {"name": "evidence/x", "width": "375", "height": "667"}


def test_dispatcher_routes_open_local(ctx, session, monkeypatch):
    seen = {}

    def fake(path, ctx=None):
        seen.update(path=path)
        return {"ok": True}

    monkeypatch.setattr(browser_tools, "browser_open_local", fake)
    run_browser_tool("browser_open_local", {"path": "index.html"}, ctx)
    assert seen == {"path": "index.html"}


def test_whitelists_include_open_local():
    assert "browser_open_local" in TOOL_WHITELIST
    assert "browser_open_local" in BROWSER_TOOLS


def test_manifest_documents_both_tools():
    by_tool = {t["tool"]: t for t in TOOLS_MANIFEST}
    shot = by_tool["browser_screenshot"]
    assert "width" in shot["args"] and "height" in shot["args"]
    assert "مساحة الخطوة" in shot["desc"]
    assert "browser_open_local" in by_tool


def test_line_protocol_knows_browser_tools():
    from roles.implementer_live import LiveImplementer
    assert LiveImplementer._LINE_TOOLS.get("browser_open_local") == "path"
    assert LiveImplementer._KV_LINE_TOOLS.get("browser_screenshot") == "name"
    assert LiveImplementer._KV_ALLOWED_KEYS["browser_screenshot"] == {
        "width", "height"}


def test_shot_exts_split_contract():
    assert ".png" in _SHOT_EXTS and ".jpg" in _SHOT_EXTS
    assert ".html" not in _SHOT_EXTS and ".js" not in _SHOT_EXTS


def test_kv_line_parses_screenshot_call():
    """سطر النموذج «browser_screenshot | evidence/x width=375 height=667»."""
    from roles.tool_plan import parse_tool_calls
    calls = parse_tool_calls(
        "browser_screenshot | evidence/x width=375 height=667",
        line_tools={"browser_open_local": "path"},
        kv_line_tools={"browser_screenshot": "name"},
        kv_allowed_keys={"browser_screenshot": {"width", "height"}},
        strip_arg_chars="`'\"",
    )
    assert calls == [{"tool": "browser_screenshot",
                      "args": {"name": "evidence/x", "width": "375",
                               "height": "667"}}]
