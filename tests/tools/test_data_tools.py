"""اختبارات أدوات البيانات (الأمر التنفيذي 003).

خادم وهمي محلي حقيقي (http.server على 127.0.0.1) — كل جلب يمر بمسار
urllib الكامل (بناء الروابط/الترويسات/الرموز/الأنواع)، بلا شبكة خارجية.

تغطية القبول: نجاح الجلب لكل أداة، فشل الشبكة/الرمز/الحجم/الصيغة،
توثيق الأدلة (sha256 للمحتوى المستلم + execution_site معلن)، عدم تسرب
صلاحية شبكة إلى الركيزة (قنبلة على local_sandbox_manager)، وإيقاف
أدوات v1 غير المنقولة عند القائمة البيضاء.
"""

from __future__ import annotations

import http.server
import json
import socket
import threading
import urllib.parse

import pytest

from roles.tools import ToolContext, ToolError, run_tool
from tools import data_tools

FRED_CSV = (
    "DATE,DGS10\n"
    "2024-01-02,3.95\n"
    "2024-01-03,3.90\n"
    "2024-01-04,.\n"
    "2024-01-05,4.02\n"
    "2024-01-08,4.03\n"
)

WB_PAYLOAD = [
    {"page": 1, "pages": 1, "total": 4},
    [
        {"country": {"value": "Saudi Arabia"}, "countryiso3code": "SA",
         "date": "2023", "value": 2.1, "indicator": {"id": "TEST.CPI"}},
        {"country": {"value": "Saudi Arabia"}, "countryiso3code": "SA",
         "date": "2024", "value": 1.8, "indicator": {"id": "TEST.CPI"}},
        {"country": {"value": "United States"}, "countryiso3code": "USA",
         "date": "2023", "value": 4.1, "indicator": {"id": "TEST.CPI"}},
        {"country": {"value": "Germany"}, "countryiso3code": "DEU",
         "date": "2023", "value": 5.9, "indicator": {"id": "TEST.CPI"}},
    ],
]

HTML_PAGE = (
    "<html><head><title>إحصاءات</title><script>var x=1;</script>"
    "<style>.a{color:red}</style></head><body>"
    "<nav>قائمة تصفح تجريبية</nav>"
    "<h1>إحصاءات الأسواق</h1>"
    "<p>الفقرة الأولى عن أسعار الفائدة العالمية.</p>"
    "<p>الفقرة الثانية عن التضخم في الاقتصادات الكبرى.</p>"
    "<footer>تذييل</footer></body></html>"
)

JSON_BODY = {"status": "ok", "rates": [{"code": "USD", "value": 3.67},
                                       {"code": "EUR", "value": 3.97}]}


class _StubHandler(http.server.BaseHTTPRequestHandler):
    """خادم وهمي — المسار يحدد الاستجابة (بلا شبكة خارجية)."""

    def do_GET(self) -> None:  # noqa: N802 — توقيع http.server
        route = urllib.parse.urlparse(self.path).path
        body, ctype = self._route(route)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _route(route: str):
        if route == "/fred.csv":
            return FRED_CSV, "text/csv"
        if route == "/fred-missing":
            return "<html>series not found</html>", "text/html"
        if route.startswith("/country/bad"):
            return json.dumps({"error": "shape"}), "application/json"
        if route.startswith("/country/"):
            return json.dumps(WB_PAYLOAD), "application/json"
        if route == "/text.csv":
            return "date,rate\n2024-01,4.0\n", "text/csv"
        if route == "/api.json":
            return json.dumps(JSON_BODY), "application/json"
        if route == "/page.html":
            return HTML_PAGE, "text/html"
        if route == "/not-json":
            return "هذا ليس JSON", "text/plain"
        if route == "/big":
            return b"x" * (data_tools.MAX_FETCH_BYTES + 10), "text/plain"
        return None, ""

    def log_message(self, *args) -> None:  # كتم سجل الخادم في الاختبارات
        pass


@pytest.fixture()
def stub_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture()
def ctx(tmp_path):
    events: list[dict] = []
    context = ToolContext(grant_root=tmp_path, on_event=events.append)
    context._test_events = events  # noqa: SLF001 — اختبار يفحص الأحداث
    return context


def _closed_port() -> int:
    """منفذ مضمون الإغلاق — مقبس يُفتح ويُغلق فورًا."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# ------------------------------------------------------------------ #
# نجاح الجلب — كل أداة عبر مسار urllib الكامل
# ------------------------------------------------------------------ #

def test_http_get_text_success_and_evidence(stub_url, ctx):
    result = run_tool("http_get_text", {"url": f"{stub_url}/text.csv"}, ctx)
    assert result["chars"] > 10
    assert result["execution_site"] == "in_process_declared"
    assert result["artifact"].startswith("data/raw/text-")
    assert (ctx.grant_root / result["artifact"]).is_file()
    # الدليل: sha256 للمحتوى المستلم خامًا + الموقع المعلن
    event = [e for e in ctx._test_events if e["kind"] == "tool.call"][-1]
    assert event["tool"] == "http_get_text"
    assert event["execution_site"] == "in_process_declared"
    assert event["output_sha256"] == result["sha256"]
    assert len(event["output_sha256"]) == 64
    assert ctx.data_urls[-1]["url"] == f"{stub_url}/text.csv"


def test_http_get_json_success_with_structure(stub_url, ctx):
    result = run_tool("http_get_json", {"url": f"{stub_url}/api.json"}, ctx)
    assert result["count"] == 1
    assert "rates" in result["structure"] and "status" in result["structure"]
    # عينة القاموس: سلّمية كما هي ومركّبة بطولها — بنية مرئية بلا حمولة
    assert result["sample"]["status"] == "ok"
    assert result["sample"]["rates"] == "<list len=2>"


def test_page_to_text_extracts_paragraphs_only(stub_url, ctx):
    result = run_tool("page_to_text", {"url": f"{stub_url}/page.html"}, ctx)
    text = (ctx.grant_root / result["artifact"]).read_text(encoding="utf-8")
    assert "أسعار الفائدة العالمية" in text
    assert "التضخم في الاقتصادات الكبرى" in text
    assert "var x=1" not in text          # script محذوف
    assert "color:red" not in text        # style محذوف
    assert "قائمة تصفح" not in text       # nav محذوف
    assert result["words"] >= 10


def test_fred_csv_success_normalized(stub_url, ctx, monkeypatch):
    monkeypatch.setattr(data_tools, "FRED_BASE_URL", f"{stub_url}/fred.csv")
    result = run_tool("fred_csv", {"series_id": "DGS10"}, ctx)
    assert result["series_id"] == "DGS10"
    assert result["rows"] == 5
    assert result["columns"] == ["date", "value"]
    # القيمة المفقودة «.» صارت None (تطبيع رقمي — درس v1)
    values = [row[1] for row in result["sample_rows"]]
    assert None in values or 4.03 in values
    normalized = (ctx.grant_root / result["artifacts"]["normalized"]).read_text(
        encoding="utf-8")
    assert normalized.startswith("date,value\n")
    assert "2024-01-04," in normalized
    # مصدر البيانات يسجل للـsources.json
    assert any("fred.stlouisfed.org" in item["url"] for item in ctx.data_urls)


def test_worldbank_success_normalized(stub_url, ctx, monkeypatch):
    monkeypatch.setattr(
        data_tools, "WORLDBANK_BASE_URL", f"{stub_url}"
    )
    result = run_tool(
        "worldbank_indicator",
        {"indicator": "TEST.CPI", "countries": "SA;US;DE", "dates": "2023:2024"},
        ctx,
    )
    assert result["rows"] == 4
    assert result["columns"][0] == "country"
    assert any("data.worldbank.org" in item["url"] for item in ctx.data_urls)
    normalized = (ctx.grant_root / result["artifacts"]["normalized"]).read_text(
        encoding="utf-8")
    assert "Saudi Arabia,SA,2023,2.1,TEST.CPI" in normalized


# ------------------------------------------------------------------ #
# فشل صريح — رمز/شبكة/حجم/صيغة
# ------------------------------------------------------------------ #

def test_http_404_is_explicit_failure(stub_url, ctx):
    with pytest.raises(ToolError, match="HTTP 404"):
        run_tool("http_get_text", {"url": f"{stub_url}/missing"}, ctx)


def test_network_refused_is_explicit_failure(ctx):
    with pytest.raises(ToolError, match="فشل"):
        run_tool(
            "http_get_text", {"url": f"http://127.0.0.1:{_closed_port()}/x"}, ctx
        )


def test_oversized_response_rejected_with_guidance(stub_url, ctx):
    with pytest.raises(ToolError, match="تجاوزت"):
        run_tool("http_get_text", {"url": f"{stub_url}/big"}, ctx)


def test_not_json_rejected(stub_url, ctx):
    with pytest.raises(ToolError, match="ليست JSON"):
        run_tool("http_get_json", {"url": f"{stub_url}/not-json"}, ctx)


def test_fred_missing_series_rejected(stub_url, ctx, monkeypatch):
    monkeypatch.setattr(data_tools, "FRED_BASE_URL", f"{stub_url}/fred-missing")
    with pytest.raises(ToolError, match="لم يجد السلسلة"):
        run_tool("fred_csv", {"series_id": "NOSUCH"}, ctx)


def test_worldbank_bad_shape_rejected(stub_url, ctx, monkeypatch):
    monkeypatch.setattr(data_tools, "WORLDBANK_BASE_URL", f"{stub_url}")
    with pytest.raises(ToolError, match="غير متوقعة"):
        run_tool(
            "worldbank_indicator", {"indicator": "BAD.SHAPE",
                                     "countries": "bad"}, ctx,
        )


def test_invalid_series_id_rejected_before_network(ctx):
    with pytest.raises(ToolError, match="معرف سلسلة"):
        run_tool("fred_csv", {"series_id": "DROP TABLE"}, ctx)


def test_invalid_indicator_rejected_before_network(ctx):
    with pytest.raises(ToolError, match="رمز مؤشر"):
        run_tool("worldbank_indicator", {"indicator": "!!"}, ctx)


def test_non_http_scheme_rejected(ctx):
    with pytest.raises(ToolError, match="رابط غير مدعوم"):
        run_tool("http_get_text", {"url": "file:///etc/passwd"}, ctx)


# ------------------------------------------------------------------ #
# العزل: لا تسرب صلاحية شبكة إلى الركيزة (قرار المالك — النمط المعلن)
# ------------------------------------------------------------------ #

def test_data_tools_never_touch_the_substrate(stub_url, ctx, monkeypatch):
    """قنبلة على مدير الركيزة: أي استدعاء له يفشل الاختبار فورًا."""
    def _bomb(*args, **kwargs):  # pragma: no cover — الانفجار هو الفشل
        raise AssertionError("أداة بيانات لمست مدير الركيزة!")

    monkeypatch.setattr(
        "substrate.local_substrate.local_sandbox_manager", _bomb
    )
    monkeypatch.setattr(data_tools, "FRED_BASE_URL", f"{stub_url}/fred.csv")
    monkeypatch.setattr(data_tools, "WORLDBANK_BASE_URL", f"{stub_url}")
    calls = [
        ("http_get_text", {"url": f"{stub_url}/text.csv"}),
        ("http_get_json", {"url": f"{stub_url}/api.json"}),
        ("page_to_text", {"url": f"{stub_url}/page.html"}),
        ("fred_csv", {"series_id": "DGS10"}),
        ("worldbank_indicator", {"indicator": "TEST.CPI", "countries": "SA"}),
    ]
    for name, args in calls:
        run_tool(name, args, ctx)  # لا انفجار = الركيزة لم تُمَس
    sites = {
        e["execution_site"] for e in ctx._test_events
        if e["kind"] == "tool.call"
    }
    assert sites == {"in_process_declared"}  # معلن حصرًا — لا ادعاء عزل


def test_v1_unported_tools_stay_out_of_whitelist(ctx):
    """أدوات v1 غير المنقولة (yfinance/rss) خارج القائمة البيضاء."""
    for tool in ("yfinance_series", "rss_fetch", "browser_fetch"):
        with pytest.raises(ToolError, match="خارج القائمة البيضاء"):
            run_tool(tool, {"symbols": "AAPL"}, ctx)
