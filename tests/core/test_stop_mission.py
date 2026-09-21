"""اختبارات إيقاف المهمة الحية (الأمر 004) — الحكم STOPPED والاستئناف.

النقل مزيف (نمط tests/test_mission_data.py نفسه) لكن المسار الإنتاجي
حقيقي: نقاط التفتيش داخل المنفذ الحي (بين الأدوات وقبل التقرير)،
تكريم الإيقاف عند المنسق، لقطة الاستئناف في مجلد المهمة، حكم STOPPED
المستقل في evidence.json، ثم استئناف كامل من اللقطة حتى PASS.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import roles.tools as tools
from core.stop_controller import StopController
from missions import run_mission
from router.model_router import ChatMessage

pytest.importorskip("pypdf", reason="التحقق من صفحات PDF يتطلب pypdf")

GOAL = (
    "تقرير من صفحة واحدة عن التضخم وأسعار الفائدة، من 5-8 مصادر "
    "موثقة، عربي RTL، PDF بحجم A4"
)

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


class StopMissionRouter:
    """موجّه مسجَّل — المفكر والمدقق فوريان والمنفذ يعمل بأدوات مزيفة."""

    def __init__(self):
        self.live_calls = 0

    def chat_live(self, messages, **_kwargs):
        self.live_calls += 1
        user = messages[-1].content
        if '"phase": "plan_tools"' in user:
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


# ---- جالبون مزيفون: أداة كلمة المرور نائمة لخلق نافذة الإيقاف ----


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


def _sleeping_worldbank(ctx, indicator, countries="all", dates=None, base_url=""):
    time.sleep(2.5)  # نافذة السباق: الإيقاف يُطلب أثناء هذه الأداة
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
    monkeypatch.setattr(data_tools, "worldbank_indicator", _sleeping_worldbank)
    monkeypatch.setattr(data_tools, "http_get_text", _fake_http_get_text)

    def fake_search(query, **_kwargs):
        return [{"title": "نتيجة بحث", "url": "https://example.com/s/1",
                 "snippet": "مقتطف"}]

    def fake_fetch(url, **_kwargs):
        return ("نص تحليلي طويل عن التضخم وأسعار الفائدة في الاقتصادات "
                "الكبرى ومسارات السياسة النقدية. " * 8)

    monkeypatch.setattr(tools, "web_search", fake_search)
    monkeypatch.setattr(tools, "fetch_page", fake_fetch)


def _wait_for(predicate, timeout=30.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_mission_stop_then_resume_completes(tmp_path, fake_fetchers):
    """إيقاف حي أثناء أدوات المنفذ ثم استئناف من اللقطة حتى PASS.

    السيناريو الكامل للأمر 004 عند مستوى المهمة:
    (أ) الإيقاف أثناء حلقة أدوات المنفذ الحي → تكريم عند نقطة آمنة.
    (ب) حكم STOPPED مستقل (لا HARD STOP ولا PASS) + أدلة جزئية + لقطة.
    (ج) الاستئناف دورة جديدة محقونة بالخطة الموقّعة تكمل حتى PASS.
    """
    # ---- (أ) الإيقاف ----
    router = StopMissionRouter()
    stop = StopController()
    events: list[dict] = []
    box: dict = {}

    def run():
        box["res"] = run_mission(
            GOAL,
            router=router,
            mission_dir=tmp_path,
            on_event=events.append,
            cycle_id="mission-stop-1",
            stop_controller=stop,
        )

    thread = threading.Thread(target=run)
    thread.start()
    # الأداة الأولى (fred_csv سريعة) تُوثق حدثًا، ثم العالمية تنام 2.5ث
    assert _wait_for(
        lambda: any(e.get("kind") == "tool.call" for e in events)
    ), "لم تصل أداة أولى — المهمة لم تبلغ التنفيذ"
    receipt = stop.request_stop(
        "mission-stop-1", by="owner", reason="إيقاف اختباري"
    )
    assert receipt.requested_by == "owner"
    thread.join(timeout=60)
    assert not thread.is_alive(), "المهمة لم تتوقف عند النقطة الآمنة"

    result = box["res"]
    # ---- (ب) الحكم الصادق واللقطة ----
    assert result.verdict == "STOPPED", result.reason
    assert result.final_state == "STOPPED"
    snapshot_path = tmp_path / "stop_snapshot.json"
    assert snapshot_path.is_file()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["plan_signed"] is True
    assert snapshot["stopped_by"] == "owner"
    assert snapshot["stop_reason"] == "إيقاف اختباري"

    evidence = json.loads(
        Path(result.evidence_path).read_text(encoding="utf-8")
    )
    assert evidence["verdict"] == "STOPPED"
    assert evidence["stop"]["stopped_by"] == "owner"
    assert evidence["stop"]["state_at_stop"] == "EXECUTING"
    assert evidence["stop"]["phase"].startswith("implementer.")
    # أدلة جزئية فعلية: لقطة + أحداث الأدوات الموثقة قبل الإيقاف
    assert evidence["files"], "لا أدلة جزئية محفوظة"
    tool_calls_before_stop = [
        c for c in evidence.get("tool_calls", []) if c.get("kind") != "x"
    ]
    assert tool_calls_before_stop, "لا استدعاءات أدوات موثقة قبل الإيقاف"

    done = [e for e in events if e.get("kind") == "mission_done"][-1]
    assert done["verdict"] == "STOPPED"
    assert done["details"]["stop"]["stopped_by"] == "owner"
    # تسلسل الحالات الصادق ينتهي بزوج الإيقاف
    assert evidence["state_history"][-2:] == ["STOPPING", "STOPPED"]

    # ---- (ج) الاستئناف من اللقطة — دورة جديدة تكمل ----
    router2 = StopMissionRouter()
    events2: list[dict] = []
    resumed = run_mission(
        router=router2,
        mission_dir=tmp_path,
        on_event=events2.append,
        cycle_id="mission-resume-1",
        stop_controller=StopController(),
        resume_from=snapshot,
    )
    assert resumed.verdict == "PASS", resumed.reason
    assert resumed.final_state in ("EVIDENCED", "ADJUDICATED")
    evidence2 = json.loads(
        Path(resumed.evidence_path).read_text(encoding="utf-8")
    )
    assert evidence2["resumed_from"] == "mission-stop-1"
    # الخطة الموقّعة حُقنت: المفكر الحي لم يُستدعَ في الاستئناف
    # (كل استدعاءات الموجّه في الاستئناف من المنفذ/المراجع فقط)
    assert evidence2["state_history"][0] == "APPROVED"
    resumed_events = [
        e for e in events2 if e.get("kind") == "cycle.resumed"
    ]
    assert len(resumed_events) == 1
    assert resumed_events[0]["details"]["from_cycle_id"] == "mission-stop-1"
