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

def test_conversation_is_the_default_project_surface():
    source = PAGE.read_text(encoding="utf-8")
    assert ":'chat',conversationId:" in source
    assert "url(x.id,'chat')" in source
    assert "function chat()" in source
    assert 'class="aes-chat-layout"' in source
    assert "conversation-" in source
    assert "await loadChat(n,p,r.conversationId)" in source
    assert "await inspectChat(id,currentRequest)" in source
    assert "project_id:projectAtStart" in source  # atomic project-scoped chat


def test_chat_reply_is_streamed_from_actual_backend_with_fail_closed_scoping():
    source = PAGE.read_text(encoding="utf-8")
    assert "ev.kind==='message_delta'" in source
    assert "ev.kind==='message_completed'" in source
    assert "ev.kind==='chat.error'" in source
    assert "ev.scope?.conversation_id" in source
    assert "if(cid&&cid!==candidate)return" in source
    assert "if(!finished&&!wasError)throw" in source
    assert "state.pendingText=message" in source
    assert "state.liveText+=" in source
    assert "document.getElementById('aes-chat-thread')" in source
    assert "window.confirm(warning)" in source


def test_inline_javascript_parses_under_node_if_available(tmp_path):
    import re
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    source = PAGE.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", source, flags=re.S)
    assert len(scripts) == 1
    script = tmp_path / "factory-v3-live.js"
    script.write_text(scripts[0], encoding="utf-8")
    proc = subprocess.run([node, "--check", str(script)], capture_output=True,
                          text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr

def test_node_browser_smoke_contract():
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    script = Path(__file__).with_name("factory_v3_smoke.cjs")
    result = subprocess.run([node, str(script)], text=True, capture_output=True,
                            timeout=25)
    assert result.returncode == 0, result.stdout + "\\n" + result.stderr
    assert "AES_CHAT_UI_SMOKE_PASS" in result.stdout

def test_html_artifact_preview_is_sandboxed_and_never_claims_site_accepted():
    source = PAGE.read_text(encoding="utf-8")
    assert 'sandbox=""' in source
    assert 'referrerpolicy="no-referrer"' in source
    assert "script-src &#39;none&#39;" in source
    assert "connect-src &#39;none&#39;" in source
    assert "form-action &#39;none&#39;" in source
    assert "E(isolatedDoc)" in source
    assert "state.previewMode" in source
    assert "معاينة مرئية آمنة" in source
    assert "لا يمثل اختبار قبول" in source
    assert "تعذّر جلب قائمة المخرجات" in source


def test_stream_updates_message_without_rebuilding_the_composer_on_each_token():
    source = PAGE.read_text(encoding="utf-8")
    assert 'class="aes-stream-content" aria-live="polite"' in source
    assert "live.textContent=state.liveText" in source
    assert "const nearBottom=thread&&" in source
    assert "if(nearBottom)thread.scrollTop=thread.scrollHeight" in source
    assert "else paint();" in source
