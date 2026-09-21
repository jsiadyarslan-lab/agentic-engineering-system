"""بنية تحتية مشتركة لاختبارات الأمر 006 — test wiring صريح (§12).

كل اختبارات الـAPI الحية تحقن موجّهًا مخطوطًا (استجابات مسجلة حتمية)
عبر ``routes._test_router_factory`` — فصل صريح بين production wiring
(مزودات المالك حصرًا) وtest wiring (نقلات مسجلة). كل ما عدا النقل
حقيقي: المنسق والأدوار الحية والركيزة والقاعدة والحكم.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
# ملاحظة: لا تُدخل tests/ نفسها في المسار أبدًا — تحجب core/api الحقيقية


class ScriptedLiveRouter:
    """موجّه اختباري — يسجل كل استدعاء ويوزع استجابات مسجلة حسب الحمل.

    chat: أي رسالة لا تطابق حمولة دور = رد محادثة عام يحمل
    provider/model كما وُصلا (إثبات التمرير الصريح §3+§4).
    """

    def __init__(self, *, providers=("nvidia", "zai-test", "openrouter-test")):
        self._providers = set(providers)
        self.calls: list[dict] = []
        self.chat_calls: list[dict] = []

    def has_live_provider(self, provider_id):
        return str(provider_id) in self._providers

    def live_providers(self):
        return sorted(self._providers)

    def chat_live(self, messages, *, provider_id=None, model=None, **_kw):
        record = {"provider": str(provider_id), "model": str(model)}
        self.calls.append(record)
        user = messages[-1].content
        if '"phase": "plan_tools"' in user:
            return self._wrap(TOOL_PLAN, provider_id, model)
        if '"phase": "write_report"' in user:
            return self._wrap(REPORT_MD, provider_id, model)
        if '"previous_reviews"' in user:  # المفكر
            return self._wrap(THINKER_JSON, provider_id, model)
        if '"previous_gaps"' in user:  # المدقق
            return self._wrap(REVIEWER_JSON, provider_id, model)
        if '"criteria"' in user:  # المراجع
            return self._wrap(VERIFIER_JSON, provider_id, model)
        if '"conflict_type"' in user:  # المُحكَّم
            return self._wrap(ARBITER_JSON, provider_id, model)
        # محادثة عامة — رد يحمل الاختيار كما وصل (إثبات التمرير)
        self.chat_calls.append(record)
        return self._wrap(
            "رد المحادثة الحية: فهمت رسالتك وجاوبت عليها فعليًا.",
            provider_id,
            model,
        )

    def chat_live_stream(self, messages, *, provider_id=None, model=None,
                         on_delta=None, **_kw):
        """بث متدفق (الأمر 008 §3) — نفس رد chat_live مقطّعًا فعليًا."""
        record = {"provider": str(provider_id), "model": str(model)}
        self.calls.append(record)
        user = messages[-1].content
        if '"phase"' not in user and '"previous_reviews"' not in user:
            self.chat_calls.append(record)
        outcome = self.chat_live(
            messages, provider_id=provider_id, model=model
        )
        text = outcome["text"]
        step = max(1, len(text) // 3)
        pieces = [text[i:i + step] for i in range(0, len(text), step)]
        for piece in pieces:
            if on_delta is not None:
                on_delta(piece)
        return {**outcome, "streamed": True}

    @staticmethod
    def _wrap(text, provider_id, model):
        return {
            "text": text,
            "provider": str(provider_id),
            "model": str(model),
            "tokens": 10,
            "duration_ms": 1,
        }


THINKER_JSON = (
    '{"tasks": [{"id": "T1", "description": "اكتب تقريرًا قصيرًا من '
    'المصادر المجلوبة", "acceptance_criteria": '
    '["الملف T1-report.md موجود ضمن الأدلة", '
    '"الملف T1-report.pdf موجود ضمن الأدلة", '
    '"الملف sources.json موجود ضمن الأدلة"]}], '
    '"risks": ["مصادر ناقصة"], "assumptions": ["الشبكة متاحة"], '
    '"evidence_required": ["مسار PDF"]}'
)
REVIEWER_JSON = (
    '{"verdict": "approved", "issues": [], "required_changes": [], '
    '"score": 9.0, "evolution_score": 8.0}'
)
VERIFIER_JSON = (
    '{"verdict": "evidenced", "checks_performed": ["الملفات الثلاثة '
    'موجودة"], "missing_evidence": [], "confidence": 1.0}'
)
ARBITER_JSON = (
    '{"decision": "retry_with_constraints", "rationale": "نقص قابل '
    'للمعالجة", "escalation_to_human": false, "max_retries_remaining": 1}'
)
TOOL_PLAN = (
    "web_search | موضوع المهمة\n"
    "web_search | topic english\n"
    "fetch_page | https://example.com/topic"
)
REPORT_MD = (
    "# تقرير المهمة\n\n"
    "## السياق\n\nشرح وافٍ للموضوع بجوانبه المختلفة وسياقه الأوسع.\n\n"
    "## التحليل\n\nتحليل متوازن يغطي الأطراف والاتجاهات والمآلات.\n\n"
    "## المصادر\n\n"
    "- مصدر أول — https://example.com/topic\n"
    "- مصدر ثانٍ — https://example.org/b\n"
    "- مصدر ثالث — https://example.net/c\n"
    "- مصدر رابع — https://example.io/d\n"
    "- مصدر خامس — https://example.dev/e\n"
)
FAKE_SEARCH = [
    {"title": f"مصدر رقم {i}", "url": f"https://example.com/topic/{i}",
     "snippet": "مقتطف عن الموضوع"}
    for i in range(6)
]


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    """بيئة API معزولة: قاعدة مؤقتة + موجّه مخطوط + ويب مجمد + CWD معزول.

    يعيد صندوقًا يملك الموجّه — الاختبار يقرأ calls/chat_calls بعده.
    """
    import roles.tools as tools
    from api import routes
    from persistence.database import build_engine, init_db, make_session_factory

    engine = build_engine(tmp_path / "api-test.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)
    monkeypatch.chdir(tmp_path)

    def fake_search(query, **_kwargs):
        return list(FAKE_SEARCH)

    def fake_fetch(url, **_kwargs):
        return ("نص صفحة طويل بما يكفي عن الموضوع المطلوب "
                "بجوانبه المتعددة. " * 6)

    monkeypatch.setattr(tools, "web_search", fake_search)
    monkeypatch.setattr(tools, "fetch_page", fake_fetch)

    router = ScriptedLiveRouter()

    def factory(**_kwargs):
        return router

    monkeypatch.setattr(routes, "_test_router_factory", factory)

    # (الأمر 009) مسبار preflight مضبوط لاختبارات API — نفس مسار
    # الكتابة الحقيقي (record_probe) بنتائج معلنة: بيئة الاختبار
    # معزولة عن الشبكة الحية عمدًا، والفحص الحقيقي له اختباراته
    # الخاصة (tests/readiness/) بمسبارات حقيقية.
    from readiness import registry as readiness_registry

    def fast_probe(sessions, capability_id, **_kwargs):
        from readiness.probes import ProbeResult
        import datetime as _dt
        return readiness_registry.record_probe(
            sessions, capability_id,
            ProbeResult(
                status="READY",
                reason="مضبوط لبيئة الاختبار المعزولة",
                checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                ttl_seconds=3600,
                details={"test_seam": True},
            ),
        )

    monkeypatch.setattr(routes, "_preflight_probe_fn", fast_probe)
    yield {"router": router, "sessions": sessions}


def sse_events(resp):
    """تفكيك استجابة SSE إلى قائمة أحداث JSON."""
    import json as _json

    return [
        _json.loads(line[5:])
        for line in resp.text.split("\n\n")
        if line.startswith("data: ")
    ]
