"""اختبارات W2-T25 — التحليل المتسامح لخطة أدوات المنفذ (roles/tool_plan).

الدافع المقيس (الخطوة 138، التنفيذ 46، الجولة 2): النموذج أعاد ردًا
بلا أسطر «أداة | وسيطة» (أسوار كود أو مصفوفة JSON) فأُعلن
RoleSystemFault «لا أسطر استدعاء صالحة في الرد» رغم أن الاستدعاءات
نفسها قانونية — الجولة تُهدر والمحاولات تُستنزف.

العقد: ثلاثة تنويعات صادقة (أنابيب → بعد نزع الأسوار → JSON) كلها
تخدم العقد نفسه (أداة معروفة + وسيطة قانونية) — لا تمرير أوسع.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from roles import tool_plan  # noqa: E402

LINE_TOOLS = {
    "web_search": "query",
    "fetch_page": "url",
    "http_get_text": "url",
    "http_get_json": "url",
    "page_to_text": "url",
}
KV_LINE_TOOLS = {"fred_csv": "series_id", "worldbank_indicator": "indicator"}
KV_ALLOWED = {
    "fred_csv": {"start", "end"},
    "worldbank_indicator": {"countries", "dates"},
}
STRIP = "`'\""


def parse(text: str) -> list[dict]:
    return tool_plan.parse_tool_calls(
        text, line_tools=LINE_TOOLS, kv_line_tools=KV_LINE_TOOLS,
        kv_allowed_keys=KV_ALLOWED, strip_arg_chars=STRIP,
    )


def test_pipe_lines_as_before():
    calls = parse(
        "web_search | الأخبار العالمية اليوم\n"
        "fetch_page | https://example.com/doc\n"
    )
    assert calls == [
        {"tool": "web_search", "args": {"query": "الأخبار العالمية اليوم"}},
        {"tool": "fetch_page", "args": {"url": "https://example.com/doc"}},
    ]


def test_kv_lines_with_pairs():
    calls = parse("fred_csv | DGS10 start=2024-01-01")
    assert calls == [{"tool": "fred_csv", "args": {
        "series_id": "DGS10", "start": "2024-01-01"}}]


def test_outer_fences_stripped():
    text = "```\nweb_search | استعلام ما\nfetch_page | https://a.example/x\n```"
    calls = parse(text)
    assert len(calls) == 2
    assert calls[0]["args"]["query"] == "استعلام ما"


def test_json_array_fallback():
    text = (
        'المصادر المقترحة:\n'
        '[{"tool": "web_search", "args": {"query": "Next.js 14 tsconfig"}},'
        ' {"tool": "fetch_page", "url": "https://nextjs.org/docs"}]'
    )
    calls = parse(text)
    assert calls == [
        {"tool": "web_search", "args": {"query": "Next.js 14 tsconfig"}},
        {"tool": "fetch_page", "args": {"url": "https://nextjs.org/docs"}},
    ]


def test_json_with_unknown_tool_rejected():
    """أداة خارج القائمة في مصفوفة JSON = تنويع مرفوض — لا تمرير أوسع."""
    text = '[{"tool": "rm_rf", "args": {"query": "/"}}]'
    with pytest.raises(ValueError):
        parse(text)


def test_json_without_legal_argument_rejected():
    text = '[{"tool": "web_search", "args": {"q": "استعلام"}}]'
    with pytest.raises(ValueError):
        parse(text)


def test_garbage_still_fails():
    with pytest.raises(ValueError):
        parse("لا شيء مفهوم هنا إطلاقًا")


def test_strip_outer_fences_only_outer():
    text = "```json\nweb_search | x\n```"
    assert tool_plan.strip_outer_fences(text) == "web_search | x"
    inner = "intro\n```\nweb_search | x\n```\noutro"
    # الأسوار الداخلية لا تُمس — النزع للحافة الخارجية حصرًا
    assert tool_plan.strip_outer_fences(inner) == inner
