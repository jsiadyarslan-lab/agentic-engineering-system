"""اختبارات سجل المصادر الرسمي (الأمر التنفيذي 003)."""

from __future__ import annotations

import json

import pytest

from sources import (
    REGISTRY_PATH,
    SUPPORTED_CONNECTORS,
    list_sources,
    load_sources,
    search_sources,
    suggest_sources,
)


def test_registry_loads_25_official_sources():
    rows = load_sources()
    assert len(rows) == 25
    assert all(s["connector_tool"] in SUPPORTED_CONNECTORS for s in rows)


def test_list_by_category_and_connector_and_country():
    assert len(list_sources(category="بنوك مركزية")) == 8
    assert len(list_sources(connector="fred_csv")) == 11
    assert len(list_sources(connector="worldbank_indicator")) == 3
    saudi = list_sources(country="SA")
    assert {s["id"] for s in saudi} == {"sama_rates", "mkt_saudi_exchange"}


def test_search_by_text():
    rows = search_sources("التضخم")
    assert any(s["id"] == "wb_cpi" for s in rows)
    rows = search_sources("DGS10")
    assert any(s["id"] in ("fed_h15", "fred_dgs10") for s in rows)


def test_suggest_for_data_mission_has_ready_calls():
    rows = suggest_sources(
        "تقرير عن التضخم وأسعار الفائدة وأسعار النفط في الاقتصادات الكبرى"
    )
    assert rows, "مهمة بيانات اقتصادية يجب أن تقترح مصادر رسمية"
    ids = {r["id"] for r in rows}
    assert "wb_cpi" in ids          # التضخم → جسر cpi
    assert "fred_oil" in ids        # النفط → جسر oil/wti
    calls = {r["call"] for r in rows}
    assert any(c.startswith("worldbank_indicator | FP.CPI.TOTL.ZG") for c in calls)
    assert any(c == "fred_csv | DCOILWTICO" for c in calls)
    # كل اقتراح يحمل سطر استدعاء جاهزًا — ما يظهر للنموذج حرفي
    assert all(r["call"] for r in rows)


def test_suggest_unrelated_task_returns_empty():
    assert suggest_sources("وصفة كيك بالشوكولاتة") == []


def test_call_hints_derived_from_registry_urls():
    rows = {s["id"]: s for s in load_sources()}
    hints = {
        r["id"]: r["call"]
        for r in suggest_sources("الفائدة والناتج والبطالة والصرف والذهب", limit=25)
    }
    assert hints.get("fed_h15") == "fred_csv | DGS10"
    assert hints.get("wb_gdp") == "worldbank_indicator | NY.GDP.MKTP.CD"


def test_unsupported_connector_fails_closed(tmp_path):
    """سجل بأداة غير منقولة = رفض صريح عند التحميل (لا تجاهل صامت)."""
    bad = tmp_path / "sources.json"
    bad.write_text(json.dumps({
        "sources": [{"id": "x", "connector_tool": "yfinance_series",
                     "url": "^GSPC", "name": "x", "category": "c",
                     "country": "US", "protocol": "json", "notes": ""}],
    }, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="أدوات غير منقولة"):
        load_sources(bad)


def test_registry_file_is_pristine_data_only():
    """السجل بيانات صرفة — لا كود ولا مفاتيح ولا شيء خارج الحقول."""
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"_تعليق", "sources"}
    allowed = {"id", "name", "category", "country", "protocol",
               "url", "connector_tool", "notes"}
    for source in data["sources"]:
        assert set(source.keys()) <= allowed
        assert " " not in source["id"]
