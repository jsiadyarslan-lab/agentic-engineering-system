"""اختبار المهمة الحية كاملة (الأمر السادس §5) — مسار حي مزيف النقل.

النقل مزيف (استجابات مسجلة — بنية تحتية اختبار مثل خادم §1.7)، لكن
كل ما عدا النقل حقيقي: دورة الأدوار الحية كاملة، أدوات الملفات وPDF
داخل الركيزة، أدوات الويب مزيفة الشبكة فقط، والحكم والأدلة حقيقيان.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import roles.tools as tools
from missions import DEFAULT_MISSION_GOAL, run_mission
from router.model_router import ChatMessage

# ---- استجابات مسجلة: خطة أدوات (بروتوكول الأسطر) ← تقرير ← مراجع ----
TOOL_PLAN = (
    "web_search | الوضع الجيوسياسي الشرق الأوسط\n"
    "web_search | Middle East geopolitics\n"
    "fetch_page | https://example.com/mideast"
)

REPORT_MD = (
    "# تقرير الوضع الجيوسياسي في الشرق الأوسط\n\n"
    "## المسار العسكري\n\n"
    "تشهد المنطقة تحولات متسارعة في موازين القوى الإقليمية.\n\n"
    "## المسار الدبلوماسي\n\n"
    "تتحرك وساطات متعددة لتخفيف حدة التوترات بين الأطراف الرئيسية.\n\n"
    "## المسار الاقتصادي\n\n"
    "تؤثر مضائق الطاقة على أسعار النفط وأسعار الشحن العالمية.\n\n"
    "## المصادر\n\n"
    "- مصدر أول — https://example.com/mideast\n"
    "- مصدر ثانٍ — https://example.org/b\n"
    "- مصدر ثالث — https://example.net/c\n"
    "- مصدر رابع — https://example.io/d\n"
    "- مصدر خامس — https://example.dev/e\n"
)

SOURCES = [
    {"title": f"مصدر {i}", "url": f"https://example.com/{i}"}
    for i in range(6)
]

FAKE_SEARCH = [
    {"title": f"مصدر رقم {i}", "url": f"https://example.com/mideast/{i}",
     "snippet": "مقتطف عن الوضع"}
    for i in range(6)
]


class MissionScriptRouter:
    """موجّه مسجَّل يوزّع الاستجابات حسب حِمل الطلب (phase/عقد الدور)."""

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
                '{"tasks": [{"id": "T1", "description": "اكتب تقرير الوضع '
                'الجيوسياسي من المصادر المجلوبة", "acceptance_criteria": '
                '["الملف T1-report.md موجود ضمن الأدلة", '
                '"الملف T1-report.pdf موجود ضمن الأدلة", '
                '"الملف sources.json موجود ضمن الأدلة"]}], '
                '"risks": ["مصادر ناقصة"], "assumptions": ["الشبكة متاحة"], '
                '"evidence_required": ["مسار PDF"]}'
            )
        if '"previous_gaps"' in user:  # المدقق
            return self._wrap(
                '{"verdict": "approved", "issues": [], '
                '"required_changes": [], "score": 9.0, '
                '"evolution_score": 8.0}'
            )
        if '"criteria"' in user:  # المراجع
            return self._wrap(
                '{"verdict": "evidenced", "checks_performed": '
                '["الملفات الثلاثة موجودة", "PDF صفحة واحدة", '
                '"المصادر 6"], "missing_evidence": [], "confidence": 1.0}'
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


@pytest.fixture()
def fake_web(monkeypatch):
    """أدوات الويب بلا شبكة — نتائج مجمدة معلنة (بنية تحتية اختبار)."""

    def fake_search(query, **_kwargs):
        return list(FAKE_SEARCH)

    def fake_fetch(url, **_kwargs):
        return ("نص صفحة طويل بما يكفي عن الوضع الجيوسياسي في المنطقة "
                "ومسارات التصعيد والتهدئة والأطراف الإقليمية والدولية. " * 6)

    tools.fetched_urls.clear() if hasattr(tools, "fetched_urls") else None

    monkeypatch.setattr(tools, "web_search", fake_search)
    monkeypatch.setattr(tools, "fetch_page", fake_fetch)


def test_mission_full_cycle_pass(tmp_path, fake_web):
    """الدورة الحية كاملة تنتهي PASS: PDF صفحة واحدة + 5-8 مصادر + أدلة."""
    events: list[dict] = []
    result = run_mission(
        DEFAULT_MISSION_GOAL,
        router=MissionScriptRouter(),
        mission_dir=tmp_path,
        on_event=events.append,
    )
    assert result.verdict == "PASS", result.reason
    assert result.final_state in ("EVIDENCED", "ADJUDICATED")
    assert result.pdf_pages == 1
    assert 5 <= len(result.sources) <= 8
    # المخرجات التعاقدية موجودة فعليًا (§5.3)
    assert (tmp_path / "mideast_report.pdf").is_file()
    evidence = json.loads(
        (tmp_path / "evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["verdict"] == "PASS"
    assert evidence["files"]["mideast_report.pdf"]["sha256"]
    # كل استدعاء أداة داخل الأدلة بـ sha256 (§3.3)
    tool_calls = evidence["tool_calls"]
    assert tool_calls, "لا استدعاءات أدوات موثقة"
    for call in tool_calls:
        assert call.get("output_sha256")
        assert call.get("execution_site") in (
            "substrate", "in_process_declared"
        )
    # الأحداث الحية بُثت فورًا: دورة + أدوات + ختام
    kinds = [e.get("kind") for e in events]
    assert "mission.start" in kinds
    assert "tool.call" in kinds
    assert "mission_done" in kinds


def test_mission_hard_stop_when_pdf_missing(tmp_path, fake_web):
    """دورة فاشلة (المراجع يرفض) = HARD STOP صريح بسبب موثق — لا ترقيع."""

    class RejectingVerifierRouter(MissionScriptRouter):
        def chat_live(self, messages, **kwargs):
            user = messages[-1].content
            if '"criteria"' in user:
                return self._wrap(
                    '{"verdict": "not_evidenced", "checks_performed": '
                    '["الملفات ناقصة"], "missing_evidence": ["PDF غائب"], '
                    '"confidence": 0.0}'
                )
            return super().chat_live(messages, **kwargs)

    result = run_mission(
        DEFAULT_MISSION_GOAL,
        router=RejectingVerifierRouter(),
        mission_dir=tmp_path,
    )
    # not_evidenced ← المحكَّم الحي يعيد بميزانيته ← الفشل الصريح النهائي
    assert result.verdict == "HARD STOP"
    assert result.reason
    evidence = json.loads(
        (tmp_path / "evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["verdict"] == "HARD STOP"
    assert evidence["verdict_reasons"]


def test_mission_tolerates_failing_fetch(tmp_path, monkeypatch):
    """فشل fetch_page على رابط يحجب الروبوتات لا يقتل المهمة —
    يُسجَّل حدث tool.failed والمهمة تكمل من نتائج البحث (الأمر السادس)."""

    def fake_search(query, **_kwargs):
        return [
            {"title": f"مصدر {i}", "url": f"https://example.com/s/{i}",
             "snippet": "مقتطف مهم عن المنطقة"}
            for i in range(6)
        ]

    def broken_fetch(url, **_kwargs):
        raise tools.ToolError("403 يحجب الروبوتات")

    monkeypatch.setattr(tools, "web_search", fake_search)
    monkeypatch.setattr(tools, "fetch_page", broken_fetch)

    events: list[dict] = []
    result = run_mission(
        DEFAULT_MISSION_GOAL,
        router=MissionScriptRouter(),
        mission_dir=tmp_path,
        on_event=events.append,
    )
    assert result.verdict == "PASS", result.reason
    kinds = [e.get("kind") for e in events]
    assert "tool.failed" in kinds  # الإخفاق موثق لا مُخفى
    assert result.pdf_pages == 1
