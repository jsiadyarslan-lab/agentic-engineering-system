"""اختبار تكاملي: مهمة حية كاملة بخطة أدوات بيانات (الأمر 003).

النقل مزيف (بنية اختبار المهمة نفسها)، لكن ما عدا الجلب حقيقي: بروتوكول
الأسطر بأزواج مفتاح=قيمة، الموزّع والقائمة البيضاء، إنزال الأدلة داخل
المنحة، بناء sources.json من مصادر البيانات، والدورة الحية كاملة حتى
الحكم. يثبت أن أدوات البيانات تُغذّي المهمة حقيقةً لا عرضًا.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import roles.tools as tools
from missions import run_mission
from router.model_router import ChatMessage

# ---- خطة أدوات بيانات + بحث (بروتوكول الأسطر بالصيغة الجديدة) ----
TOOL_PLAN = (
    "fred_csv | DGS10\n"
    "worldbank_indicator | FP.CPI.TOTL.ZG countries=SA;US;DE dates=2023:2024\n"
    "http_get_text | https://example.com/rates.csv\n"
    "web_search | أسعار الفائدة العالمية\n"
    "fetch_page | https://example.com/analysis\n"
)

REPORT_MD = (
    "# تقرير التضخم وأسعار الفائدة\n\n"
    "## المسار النقدي\n\n"
    "تُبطئ البنوك المركزية الكبرى وتيرة الرفع بعد ذروة التضخم.\n\n"
    "## المسار السعري\n\n"
    "تراجع التضخم في الاقتصادات الكبرى مع صمود أسعار الطاقة.\n\n"
    "## المصادر\n\n"
    "- FRED — https://fred.stlouisfed.org/data/DGS10\n"
    "- البنك الدولي — https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG\n"
    "- تحليل — https://example.com/analysis\n"
)


class DataMissionRouter:
    """موجّه مسجَّل يوزّع حسب حِمل الطلب (عقد الأدوار)."""

    def __init__(self):
        self.live_calls = 0
        self.seen_plan_payload: dict = {}

    def chat_live(self, messages, **_kwargs):
        self.live_calls += 1
        user = messages[-1].content
        if '"phase": "plan_tools"' in user:
            self.seen_plan_payload = json.loads(user)
            return self._wrap(TOOL_PLAN)
        if '"phase": "write_report"' in user:
            return self._wrap(REPORT_MD)
        if '"previous_reviews"' in user:  # المفكر
            return self._wrap(
                '{"tasks": [{"id": "T1", "description": "اكتب تقرير التضخم '
                'والفائدة من البيانات الرسمية والبحث", "acceptance_criteria": '
                '["الملف T1-report.md موجود ضمن الأدلة", '
                '"الملف T1-report.pdf موجود ضمن الأدلة", '
                '"الملف sources.json موجود ضمن الأدلة"]}], '
                '"risks": ["مصادر ناقصة"], "assumptions": ["الشبكة متاحة"], '
                '"evidence_required": ["مسار PDF"]}'
            )
        if '"previous_gaps"' in user:  # المدقق
            return self._wrap(
                '{"verdict": "approved", "issues": [], '
                '"required_changes": [], "score": 9.0, "evolution_score": 8.0}'
            )
        if '"criteria"' in user:  # المراجع
            return self._wrap(
                '{"verdict": "evidenced", "checks_performed": '
                '["الملفات موجودة", "PDF صفحة واحدة", "المصادر كافية"], '
                '"missing_evidence": [], "confidence": 1.0}'
            )
        if '"conflict_type"' in user:  # المُحكَّم
            return self._wrap(
                '{"decision": "retry_with_constraints", "rationale": "نقص '
                'قابل للمعالجة", "escalation_to_human": false, '
                '"max_retries_remaining": 1}'
            )
        raise AssertionError(f"طلب غير متوقع: {user[:120]}")

    @staticmethod
    def _wrap(text):
        return {"text": text, "provider": "fake", "model": "fake",
                "tokens": 10, "duration_ms": 1}


# ---- جالبو بيانات مزيفون (النقل فقط) — العقد كامل ----

def _fake_fred_csv(ctx, series_id, start=None, end=None, base_url=""):
    return {
        "tool": "fred_csv", "url": f"fred:{series_id}",
        "sha256": "a" * 64, "execution_site": "in_process_declared",
        "series_id": series_id, "rows": 3, "columns": ["date", "value"],
        "sample_rows": [["2024-01-02", 3.95]],
        "artifacts": {"raw": "data/raw/fred-DGS10.csv",
                      "normalized": "data/normalized/fred-DGS10.csv"},
        "duration_ms": 5,
    }


def _fake_worldbank(ctx, indicator, countries="all", dates=None, base_url=""):
    return {
        "tool": "worldbank_indicator", "url": f"worldbank:{indicator}",
        "sha256": "b" * 64, "execution_site": "in_process_declared",
        "indicator": indicator, "countries": countries, "rows": 2,
        "columns": ["country", "iso3", "year", "value", "indicator"],
        "sample_rows": [["Saudi Arabia", "SA", "2023", 2.1, indicator]],
        "artifacts": {"raw": "data/raw/wb.json",
                      "normalized": "data/normalized/wb.csv"},
        "duration_ms": 5,
    }


def _fake_http_get_text(ctx, url):
    return {
        "tool": "http_get_text", "url": url, "sha256": "c" * 64,
        "execution_site": "in_process_declared", "chars": 42,
        "head": "date,rate", "artifact": "data/raw/text-x.txt",
        "duration_ms": 5,
    }


@pytest.fixture()
def fake_fetchers(monkeypatch):
    from tools import data_tools

    monkeypatch.setattr(data_tools, "fred_csv", _fake_fred_csv)
    monkeypatch.setattr(data_tools, "worldbank_indicator", _fake_worldbank)
    monkeypatch.setattr(data_tools, "http_get_text", _fake_http_get_text)

    def fake_search(query, **_kwargs):
        return [{"title": "نتيجة بحث", "url": "https://example.com/s/1",
                 "snippet": "مقتطف"}]

    def fake_fetch(url, **_kwargs):
        return ("نص تحليلي طويل عن التضخم وأسعار الفائدة في الاقتصادات "
                "الكبرى ومسارات السياسة النقدية. " * 8)

    monkeypatch.setattr(tools, "web_search", fake_search)
    monkeypatch.setattr(tools, "fetch_page", fake_fetch)


def test_mission_with_data_tool_plan_passes(tmp_path, fake_fetchers):
    """دورة كاملة بخطة أدوات بيانات: PASS + أدلة معلنة + مصادر بيانات."""
    router = DataMissionRouter()
    result = run_mission(
        "تقرير من صفحة واحدة عن التضخم وأسعار الفائدة، من 5-8 مصادر "
        "موثقة، عربي RTL، PDF بحجم A4",
        router=router,
        mission_dir=tmp_path,
    )
    assert result.verdict == "PASS", result.reason
    assert result.final_state in ("EVIDENCED", "ADJUDICATED")

    # خطة الأدوات حُلّت بالصيغة الموسعة (مفتاح=قيمة) وحُقنت المصادر الرسمية
    payload = router.seen_plan_payload
    assert "official_sources" in payload
    assert any(t["tool"] == "fred_csv" for t in payload["tools"])

    # الأدلة: كل استدعاء أداة بيانات موثق بالموقع المعلن وsha256 خام
    evidence = json.loads(
        Path(result.evidence_path).read_text(encoding="utf-8")
    )
    data_calls = [
        c for c in evidence["tool_calls"]
        if c.get("tool") in ("fred_csv", "worldbank_indicator", "http_get_text")
    ]
    assert len(data_calls) == 3
    assert all(
        c["execution_site"] == "in_process_declared" for c in data_calls
    )
    assert all(len(c["output_sha256"]) == 64 for c in data_calls)

    # sources.json يضم مصادر البيانات الرسمية (فك قيد البحث الحي)
    sources = {s["url"] for s in result.sources}
    assert "https://fred.stlouisfed.org/data/DGS10" in sources
    assert "https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG" in sources
    assert 5 <= len(result.sources) <= 8
