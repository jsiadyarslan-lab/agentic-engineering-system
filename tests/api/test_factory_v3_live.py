"""Contract checks for the isolated AES V3 live workspace."""
from html.parser import HTMLParser
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "src" / "ui" / "factory_v3_live.html"


class _Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.forms = set()
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "form" and a.get("id"):
            self.forms.add(a["id"])
        if tag == "script":
            self.scripts += 1


def test_live_workspace_is_a_real_ui_asset():
    source = PAGE.read_text(encoding="utf-8")
    parser = _Structure()
    parser.feed(source)
    assert {"app", "main"} - parser.ids == {"main"}  # main is rendered client-side
    assert parser.scripts == 1
    assert 'const DOCS=' not in source
    assert 'manifest.json: MISSING' not in source
    assert "mock" not in source.lower()
    assert "محاكاة" not in source


def test_real_api_wiring_and_approval_confirmations_are_explicit():
    source = PAGE.read_text(encoding="utf-8")
    for path in (
        "/api/projects",
        "/api/projects/",
        "/api/chat/stream",
        "/api/conversations/",
        "/artifacts/content",
        "/plan/generate",
        "/plan/approve",
        "/gates/",
        "/resume",
        "/stop",
    ):
        assert path in source, path
    assert "window.confirm(warning)" in source
    assert "credentials:'same-origin'" in source
    assert "data-action=" in source
    assert "حالة الإطلاق" in source
