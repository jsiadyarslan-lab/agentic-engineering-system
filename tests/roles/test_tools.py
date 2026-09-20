"""اختبارات أدوات المنفذ (الأمر السادس §3+§4) — بيضاء/منحة/PDF.

أدوات الملفات وPDF تنفَّذ فعليًا داخل الركيزة المعزولة (نفس ركيزة
المنفذ mock) — الاختبارات هنا تمر بالمسار الحقيقي كاملًا.
"""

from __future__ import annotations

import json

import pytest

from roles.tools import (
    PDF_FONT_PATH,
    ToolContext,
    ToolError,
    run_tool,
    web_search,
)


def _ctx(tmp_path, events=None):
    return ToolContext(grant_root=tmp_path, on_event=events)


def test_whitelist_enforcement(tmp_path):
    """أداة خارج القائمة البيضاء = فشل خطوة صريح — لا تجاهل."""
    ctx = _ctx(tmp_path)
    with pytest.raises(ToolError, match="خارج القائمة البيضاء"):
        run_tool("shell_exec", {"cmd": "rm -rf /"}, ctx)
    with pytest.raises(ToolError, match="خارج القائمة البيضاء"):
        run_tool("http_client", {"url": "http://x"}, ctx)


def test_write_read_within_grant_and_escape_refused(tmp_path):
    """كتابة وقراءة داخل المنحة عبر الركيزة — وخارجها مرفوض قبل التنفيذ."""
    events: list[dict] = []
    ctx = _ctx(tmp_path, events.append)
    run_tool("write_file", {"path": "note.md", "content": "# عنوان\nنص"},
             ctx)
    content = run_tool("read_file", {"path": "note.md"}, ctx)
    assert "عنوان" in content
    assert (tmp_path / "note.md").read_text(encoding="utf-8").startswith("# عنوان")
    # الهروب من المنحة مرفوض صراحةً
    with pytest.raises(ToolError, match="خارج المجلد الممنوح"):
        run_tool("write_file", {"path": "../escape.txt", "content": "x"}, ctx)
    with pytest.raises(ToolError, match="خارج المجلد الممنوح"):
        run_tool("read_file", {"path": "../../etc/passwd"}, ctx)
    # كل استدعاء ناجح وثّق sha256 وموقع التنفيذ (§3.3)
    kinds = [e["kind"] for e in events]
    assert kinds.count("tool.call") >= 2
    for event in events:
        if event["kind"] == "tool.call":
            assert event["output_sha256"]
            assert event["execution_site"] == "substrate"


@pytest.mark.skipif(not PDF_FONT_PATH.is_file(), reason="الخط غير مضمّن")
def test_generate_pdf_arabic_one_page(tmp_path):
    """توليد PDF عربي RTL حقيقي — صفحة واحدة بالضبط ونص قابل للاستخراج."""
    events: list[dict] = []
    ctx = _ctx(tmp_path, events.append)
    md = (
        "# تقرير الوضع الجيوسياسي\n\n"
        "## المحور الأول\n\n"
        "فقرة عربية سليمة التشكيل والاتجاه داخل ملف PDF بحجم A4.\n\n"
        "## المصادر\n\n"
        "- مصدر أول\n"
    )
    run_tool("write_file", {"path": "report.md", "content": md}, ctx)
    run_tool("generate_pdf_arabic",
             {"md_path": "report.md", "out_path": "report.pdf"}, ctx)
    pages = run_tool("verify_pdf_pages", {"path": "report.pdf"}, ctx)
    assert pages == 1  # §4.3: أي أكثر = فشل صريح
    pdf_path = tmp_path / "report.pdf"
    assert pdf_path.is_file() and pdf_path.stat().st_size > 1000
    # النص قابل للاستخراج (عربي مُشكَّل — اختُبر في v1)
    from pypdf import PdfReader

    extracted = PdfReader(str(pdf_path)).pages[0].extract_text() or ""
    assert len(extracted.strip()) > 10


def test_web_search_parses_ddg_html():
    """محلل نتائج DDG — على HTML حقيقي مجمد (بدون شبكة)."""
    import roles.tools as tools

    frozen = """
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=xyz">عنوان النتيجة الأولى</a>
    <a class="result__snippet" href="">مقتطف عن الوضع في المنطقة</a>
    <a rel="nofollow" class="result__a" href="https://example.org/b">Second result</a>
    <a class="result__snippet" href="">snippet two</a>
    """
    original = tools.urllib.request.urlopen

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self, _n=-1):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        assert request.get_method() == "POST"  # POST لا GET
        return FakeResponse(frozen.encode("utf-8"))

    tools.urllib.request.urlopen = fake_urlopen
    try:
        results = web_search("الشرق الأوسط")
    finally:
        tools.urllib.request.urlopen = original
    assert len(results) == 2
    # فُكّ رابط التوجيه إلى الأصل
    assert results[0]["url"] == "https://example.com/a"
    assert results[0]["title"] == "عنوان النتيجة الأولى"
    assert "مقتطف" in results[0]["snippet"]
