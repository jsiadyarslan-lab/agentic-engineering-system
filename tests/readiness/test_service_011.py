"""اختبارات مصدر الحقيقة الواحد للجاهزية (الأمر 011 §12-§14).

الجرم المدان: بطاقة «بحث الويب: EXPIRED» بينما «DuckDuckGo: جاهز —
مسبار حقيقي ناجح». هنا: الاشتقاق واحد للمزود والقدرة، الصلاحية
موحدة، والفحص الحقيقي ينقل STALE → READY في كل النظم معًا.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sqlalchemy import select as sa_select  # noqa: E402

from execution.models import ResearchProvider  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)
from readiness import registry, service as readiness_service  # noqa: E402


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "readiness-011.db")
    init_db(engine)
    factory = make_session_factory(engine)
    registry.ensure_capabilities(factory)
    return factory


def _set_provider(sessions, kind, *, status="UNKNOWN", reason="",
                  minutes_ago=None, enabled=True, config=None):
    """كتابة حالة مزود في مصدره الحقيقي (سجل المزود) — 011 §12."""
    from research import service as research_service

    research_service.ensure_seeded(sessions)
    with sessions() as s:
        row = s.scalars(sa_select(ResearchProvider).where(
            ResearchProvider.kind == kind)).first()
        row.last_probe_status = status
        row.failure_reason = reason if status != "READY" else ""
        row.enabled = 1 if enabled else 0
        if minutes_ago is not None:
            row.last_probe_at = (
                _dt.datetime.now(_dt.timezone.utc)
                - _dt.timedelta(minutes=minutes_ago)
            )
        elif status in ("READY", "NOT_READY"):
            row.last_probe_at = _dt.datetime.now(_dt.timezone.utc)
        if config is not None:
            import json

            row.config_json = json.dumps(config, ensure_ascii=False)
        s.commit()


# ------------------------------------------------------------------ #
# §12 — حالة المزود المشتقة: NOT_CONFIGURED / STALE / READY
# ------------------------------------------------------------------ #

def test_provider_not_configured(sessions):
    _set_provider(sessions, "search_searx", status="READY",
                  minutes_ago=1, config={})   # جاهز لكن بلا رابط!
    providers = readiness_service.research_providers_view(sessions)
    searx = [p for p in providers if p["kind"] == "search_searx"][0]
    assert searx["effective_status"] == "NOT_CONFIGURED"
    assert not searx["configured"]


def test_provider_ready_fresh(sessions):
    _set_provider(sessions, "search_ddg", status="READY", minutes_ago=1)
    providers = readiness_service.research_providers_view(sessions)
    ddg = [p for p in providers if p["kind"] == "search_ddg"][0]
    assert ddg["effective_status"] == "READY"
    assert not ddg["stale"]


def test_provider_ready_expired_is_stale(sessions):
    """(§13) مسبار READY انتهت صلاحيته = STALE — ليست READY أبدًا حتى
    إعادة فحص ناجحة."""
    _set_provider(sessions, "search_ddg", status="READY",
                  minutes_ago=30)   # أقدم من TTL (600ث)
    providers = readiness_service.research_providers_view(sessions)
    ddg = [p for p in providers if p["kind"] == "search_ddg"][0]
    assert ddg["effective_status"] == "STALE"
    assert ddg["stale"] is True


def test_provider_disabled(sessions):
    _set_provider(sessions, "search_ddg", status="READY",
                  minutes_ago=1, enabled=False)
    providers = readiness_service.research_providers_view(sessions)
    ddg = [p for p in providers if p["kind"] == "search_ddg"][0]
    assert ddg["effective_status"] == "DISABLED"


# ------------------------------------------------------------------ #
# §12 — قدرة web_search من مزوديها: التناقض مستحيل بنيويًا
# ------------------------------------------------------------------ #

def test_capability_matches_provider_state_exactly(sessions):
    """التناقض التاريخي «مزود جاهز / قدرة منتهية» صار مستحيلًا: حالة
    القدرة = حالة مزودها المشتقة، دائمًا، من المصدر نفسه."""
    # مزود جاهز منتهي الصلاحية → القدرة STALE تسميه (لا NOT_READY عمياء)
    _set_provider(sessions, "search_ddg", status="READY", minutes_ago=30)
    _set_provider(sessions, "search_searx", status="UNKNOWN",
                  config={})
    view = readiness_service.capability_view(sessions, "web_search")
    assert view["readiness_status"] == "STALE"
    assert "DuckDuckGo" in view["reason"]
    assert view["details"]["stale_providers"] == ["DuckDuckGo"]

    # بعد فحص حقيقي ناجح (محاكاة: حالة جديدة حديثة) → READY فورًا
    _set_provider(sessions, "search_ddg", status="READY", minutes_ago=0)
    view = readiness_service.capability_view(sessions, "web_search")
    assert view["readiness_status"] == "READY"
    assert view["details"]["ready_providers"] == ["DuckDuckGo"]


def test_capability_blocked_details_when_nothing_ready(sessions):
    """(§16) لا شيء جاهز = حجب بتفصيل كل مزود (حالته الموحدة) — لا
    READY عمياء ولا NOT_READY بلا تفسير."""
    for kind in ("search_ddg", "search_bing", "search_searx", "search_api"):
        _set_provider(sessions, kind, status="UNKNOWN", config={})
    # DDG معد افتراضيًا (نقطة نهاية) — عطّله: بقية غير معدّين
    _set_provider(sessions, "search_ddg", status="UNKNOWN",
                  enabled=False, config={})
    view = readiness_service.capability_view(sessions, "web_search")
    assert view["readiness_status"] == "NOT_READY"
    per = {p["provider"]: p["status"]
           for p in view["details"]["per_provider"]}
    # (013.2) أربعة مزودين: DDG معطّل، Bing معد بلا مفاتيح لكنه غير
    # مفحوص (UNKNOWN — صار يُعد معدًا افتراضيًا كـDDG)، والبقية غير معدّين
    # (013.5 §L) وخامسها ويكيبيديا: أُضيفت مزودًا حقيقيًا ومفعّلة
    # افتراضيًا (بلا مفتاح)، وهي UNKNOWN حتى تُفحص كـBing.
    assert per == {"DuckDuckGo": "DISABLED",
                   "Bing": "UNKNOWN",
                   "SearXNG": "NOT_CONFIGURED",
                   "Search API": "NOT_CONFIGURED",
                   "Wikipedia": "UNKNOWN"}
    # والمستوى الصادق لـ NOT_CONFIGURED هو المزود (§16)
    providers = readiness_service.research_providers_view(sessions)
    by_kind = {p["kind"]: p["effective_status"] for p in providers}
    assert by_kind["search_searx"] == "NOT_CONFIGURED"


def test_capability_view_sandbox_from_environments(sessions):
    """sandbox من سجل البيئات — نفس مصدر المسبار والمنفذ (010 §19).

    (013.11 §5) العزل يُحاكى بعامل بعيد معلن العزل بأدلة كاملة العقد —
    صف LOCAL المحلي يتبع توفر الركيزة فعليًا (011 §4-§5).
    """
    from execution import service as execution_service

    view = readiness_service.capability_view(sessions, "sandbox")
    assert view["derived_from"] == "execution_environments"
    assert view["readiness_status"] in ("NOT_READY", "UNAVAILABLE")

    import json as _json

    from execution import policy as execution_policy
    from execution.models import ExecutionEnvironment

    detail = execution_policy.valid_evidence("REMOTE_WORKER", True)
    with sessions() as s:
        row = ExecutionEnvironment(
            name="worker-sandbox-seed", backend="REMOTE_WORKER",
            endpoint="http://127.0.0.1:9794", status="READY",
            sandboxed=1, is_default=1,
            last_verified_at=_dt.datetime.now(_dt.timezone.utc),
            last_probe_detail=_json.dumps(detail, ensure_ascii=False),
        )
        s.add(row)
        s.flush()
        detail["profile"]["environment_id"] = row.id
        row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()
    view = readiness_service.capability_view(sessions, "sandbox")
    assert view["readiness_status"] == "READY"
    assert "worker-sandbox-seed" in view["reason"]
    assert view["details"]["environment_id"] == row.id


def test_capabilities_view_and_summary_agree(sessions):
    """(§14) الملخص يعدّ من العرض المشتق نفسه — لا إعادة عد خلافية."""
    _set_provider(sessions, "search_ddg", status="READY", minutes_ago=30)
    caps = readiness_service.capabilities_view(sessions)
    summary = readiness_service.summary(sessions)
    statuses = [c["readiness_status"] for c in caps]
    for status in set(statuses):
        assert statuses.count(status) == summary.get(status, 0)


# ------------------------------------------------------------------ #
# §16 — حفظ التكوين = حفظ ← فحص ← جاهزية محدثة (لا save فقط)
# ------------------------------------------------------------------ #

def test_configure_probes_after_save(sessions, monkeypatch):
    """الزر يعني «أريد مزودًا يعمل» — الفحص يجري فور الحفظ وتحدث
    الحالة، والنتيجة تعاد (نجاح أو فشل بالسبب)."""
    from research import providers as research_providers, service

    def fake_probe(provider):
        return {"status": "READY", "reason": "فحص فوري ناجح (وصفة)",
                "latency_ms": 3}

    monkeypatch.setattr(
        research_providers, "probe_provider", fake_probe
    )
    providers = service.list_providers(sessions)
    searx = [p for p in providers if p["kind"] == "search_searx"][0]
    record = service.configure_provider(
        sessions, searx["id"], config={"base_url": "http://searx.local"},
        enabled=True,
    )
    # الفحص جرى فور الحفظ وكتب نتيجته في المصدر
    assert record["last_probe_status"] == "READY"
    view = readiness_service.capability_view(sessions, "web_search")
    assert view["readiness_status"] == "READY"
