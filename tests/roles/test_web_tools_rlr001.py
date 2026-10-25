"""اختبارات RLR-001 §4-ب — أدوات الويب: web_read/web_open + البحث الصادق.

وحدة، بلا شبكة خارجية: خادم HTTP محلي للقراءة، ومزودو بحث مزيفون
يرفعون ProviderNotReady لتحديد الحالة الصادقة WEB_SEARCH_NOT_CONFIGURED.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

try:
    from roles.web_tools import web_open, web_read, web_search
    from roles.tool_failures import ToolFailure
    from roles.tools import ToolContext, run_tool
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from roles.web_tools import web_open, web_read, web_search
    from roles.tool_failures import ToolFailure
    from roles.tools import ToolContext, run_tool


# ------------------------------------------------------------ #
# خادم محلي — صفحة خارجية مصغّرة
# ------------------------------------------------------------ #

class _Page(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = (
            b"<html><head><title>AES RLR Test Page</title></head><body>"
            b"<p>hello external world</p>"
            b"<p>This is a deliberately long paragraph so the extracted "
            b"text comfortably exceeds the honest minimum length guard of "
            b"the fetch_page contract, which rejects pages that are nearly "
            b"empty after HTML stripping. Agentic engineering systems "
            b" deserve verifiable tooling evidence, not fabricated activity "
            b"or silent downgrades of transient provider failures.</p>"
            b"</body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def local_page():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    yield f"http://127.0.0.1:{server.server_address[1]}/page"
    server.shutdown()


# ------------------------------------------------------------ #
# web_read / web_open — مصدر + تاريخ + حالة + وسم عدم الثقة
# ------------------------------------------------------------ #

def test_web_read_documents_source_date_status(local_page):
    out = web_read(local_page)
    assert out["source"] == local_page
    assert out["status"] == "FETCHED"
    assert out["trust"] == "EXTERNAL_UNTRUSTED"
    assert out["chars"] > 0
    assert "fetched_at" in out and "T" in out["fetched_at"]
    assert "hello external world" in out["content"]


def test_web_open_is_web_read_alias(local_page):
    assert web_open is web_read


def test_web_read_empty_url_is_input_failure():
    with pytest.raises(ToolFailure) as ei:
        web_read("  ")
    assert ei.value.reason == "INVALID_QUERY"


def test_web_read_dispatch_records_meta(local_page, tmp_path):
    """run_tool يسجل المصدر/التاريخ/الحالة في ملخص الاستدعاء (§2-5)."""
    events = []
    ctx = ToolContext(grant_root=tmp_path, on_event=events.append)
    value = run_tool("web_read", {"url": local_page}, ctx)
    assert value["source"] == local_page
    assert value["trust"] == "EXTERNAL_UNTRUSTED"
    calls = [e for e in events if e.get("kind") == "tool.call"
             and e.get("tool") == "web_read"]
    assert calls, "لا حدث tool.call للأداة"
    summary = calls[-1].get("args_summary") or {}
    assert summary.get("source") == local_page
    assert summary.get("status") == "FETCHED"
    assert summary.get("fetched_at")
    assert local_page in ctx.fetched_urls


# ------------------------------------------------------------ #
# web_search — الحالة الصادقة WEB_SEARCH_NOT_CONFIGURED
# ------------------------------------------------------------ #

def _fake_provider(reason: str):
    """صنف مزود مزيف يرفع ProviderNotReady بسبب محدد."""
    from research.providers import ProviderNotReady

    class _Fake:
        def __init__(self, *a, **k):
            pass

        def search(self, query, *, timeout=None):
            raise ProviderNotReady(
                f"فشل نقل وهمي ({reason})", reason=reason,
                details={"fake": True})
    return _Fake


@pytest.fixture()
def _failing_chain(monkeypatch):
    from research import providers as rp

    monkeypatch.setattr(rp, "DuckDuckGoSearchProvider",
                        _fake_provider("PROBE_REFUSED"))
    monkeypatch.setattr(rp, "BingSearchProvider",
                        _fake_provider("PROBE_REFUSED"))


def test_search_without_provider_is_honestly_not_configured(_failing_chain):
    with pytest.raises(ToolFailure) as ei:
        web_search("أخبار اليوم", sessions=None)
    assert ei.value.reason == "WEB_SEARCH_NOT_CONFIGURED"
    assert ei.value.failure_class == "DEPENDENCY_FAILURE"
    assert "missing_requirement" in (ei.value.details or {})
    assert "SearXNG" in ei.value.details["missing_requirement"]


def test_search_zero_results_is_not_configuration_error(monkeypatch):
    """بحث عمل وأعطى صفر نتائج ≠ بحث غير مهيأ — تسميات لا تختلط."""
    from research import providers as rp
    monkeypatch.setattr(rp, "DuckDuckGoSearchProvider",
                        _fake_provider("NO_RESULTS"))
    monkeypatch.setattr(rp, "BingSearchProvider",
                        _fake_provider("NO_RESULTS"))
    with pytest.raises(ToolFailure) as ei:
        web_search("استعلام نادر", sessions=None)
    assert ei.value.reason == "NO_RESULTS"
    assert ei.value.failure_class == "TOOL_FAILURE"


def test_search_empty_query_is_input_failure():
    with pytest.raises(ToolFailure) as ei:
        web_search("   ")
    assert ei.value.reason == "INVALID_QUERY"


# ------------------------------------------------------------ #
# القائمة البيضاء والبيان — الاسم الجديد معلن للنموذج
# ------------------------------------------------------------ #

def test_web_read_in_whitelist_and_manifest():
    from roles.tools import TOOL_WHITELIST
    from roles.tool_manifest import TOOLS_MANIFEST

    assert "web_read" in TOOL_WHITELIST
    assert "web_open" in TOOL_WHITELIST
    names = {t["tool"] for t in TOOLS_MANIFEST}
    assert {"web_read", "web_open"} <= names
    search_entry = next(t for t in TOOLS_MANIFEST if t["tool"] == "web_search")
    assert "WEB_SEARCH_NOT_CONFIGURED" in search_entry["desc"]
