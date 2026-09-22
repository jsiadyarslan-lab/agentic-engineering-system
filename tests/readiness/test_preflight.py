"""اختبارات الفحص المسبق (الأمر 009 §16-§17+§25+§28).

السيناريوهات الأربعة الإلزامية: كل شيء جاهز ← PASS وبدء؛ مطلوب
غير جاهز ← BLOCKED بسبب معروف وخطة استرداد؛ اختياري غائب ←
استمرار؛ متدهور ← قرار سياسة. + أحداث حية + TTL (لا إعادة فحص
بلا انتهاء صلاحية).
"""

from __future__ import annotations

import sys
import datetime as _dt
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from persistence.database import build_engine, init_db, make_session_factory
from readiness import preflight, probes, registry
from readiness.probes import ProbeResult
from sqlalchemy import select as sa_select


def _sandbox_ready(sessions):
    """بيئة تنفيذ معزولة جاهزة في السجل — مصدر قدرة sandbox الحقيقي
    (011 §14: الاشتقاق من البيئات لا من مسبار مُفخخ)."""
    from execution import service as execution_service
    from execution.models import ExecutionEnvironment

    execution_service.ensure_local_registered(sessions)
    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.backend == "LOCAL")).first()
        row.status = "READY"
        row.sandboxed = 1
        s.commit()


def _ddg(sessions, status, reason=""):
    """حالة مزود DDG في مصدره الحقيقي (011 §12) — سجل المزود نفسه."""
    from execution.models import ResearchProvider
    from research import service as research_service

    research_service.ensure_seeded(sessions)
    with sessions() as s:
        row = s.scalars(sa_select(ResearchProvider).where(
            ResearchProvider.kind == "search_ddg")).first()
        row.last_probe_status = status
        row.failure_reason = "" if status == "READY" else reason
        row.last_probe_at = (
            _dt.datetime.now(_dt.timezone.utc)
            if status in ("READY", "NOT_READY") else None
        )
        s.commit()


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "preflight-test.db")
    init_db(engine)
    factory = make_session_factory(engine)
    registry.ensure_capabilities(factory)
    return factory


def _ready(capability_id="filesystem", reason="مضبوط"):
    return ProbeResult(
        status="READY", reason=reason,
        checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        expires_at=(_dt.datetime.now(_dt.timezone.utc)
                    + _dt.timedelta(hours=1)).isoformat(),
        ttl_seconds=3600,
    )


def _not_ready(reason="الشبكة مقطوعة", failure_class="NETWORK_FAILURE"):
    return ProbeResult(
        status="NOT_READY", reason=reason,
        checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        failure_class=failure_class, failure_stage="TOOL_EXECUTION",
    )


def _fast_probe(results: dict):
    """مسبار مضبوط: يقرر حسب خريطة القدرة → النتيجة."""

    def probe(sessions, capability_id, **_kwargs):
        result = results.get(capability_id, _ready(capability_id))
        return registry.record_probe(sessions, capability_id, result)

    return probe


def test_all_ready_passes(sessions):
    _sandbox_ready(sessions)
    _ddg(sessions, "READY")
    result = preflight.task_preflight(
        sessions, "ابحث عن مشروع مفتوح المصدر واكتب ملخصًا",
        run_probe_fn=_fast_probe({}),
    )
    assert result["verdict"] == "PASS"
    assert all(c["ok"] for c in result["capabilities"])
    assert not result["blocked"]


def test_required_missing_blocks_with_reason_and_recovery(sessions):
    _sandbox_ready(sessions)
    # (011 §12) البحث يُشتق من مزوديه — DDG فاشل بمسبار حقيقي مسجل
    _ddg(sessions, "NOT_READY", "لم تُرجع الأداة مادة قابلة للتحليل")
    result = preflight.task_preflight(
        sessions, "مهمة بحث",
        run_probe_fn=_fast_probe({}),
    )
    assert result["verdict"] == "BLOCKED"
    blocked = result["blocked"]
    assert [b["capability_id"] for b in blocked] == ["web_search"]
    assert blocked[0]["status"] == "NOT_READY"
    assert blocked[0]["reason"]
    assert blocked[0]["recovery"]      # خطة استرداد معلنة (§16)
    assert result["summary"].startswith("الحواجز")


def test_required_llm_unresolvable_has_owner_action(sessions):
    """غياب مزود قابل للحل = قرار مالك (§25) — لا فشل صامت."""
    result = preflight.task_preflight(
        sessions, "مهمة", llm_ready=False,
        run_probe_fn=_fast_probe({}),
    )
    assert result["verdict"] == "BLOCKED"
    llm = [b for b in result["blocked"] if b["capability_id"] == "llm"][0]
    assert llm["owner_action"] is not None
    assert "مفتاح" in llm["owner_action"] or "الإعدادات" in llm["owner_action"]


def test_optional_capability_missing_does_not_block(sessions):
    """الاختياري الغائب لا يحجب (§28) — القدرات المطلوبة فقط تحكم."""
    _sandbox_ready(sessions)
    result = preflight.task_preflight(
        sessions, "مهمة",
        run_probe_fn=_fast_probe({"git": _not_ready("git غائب",
                                                    "DEPENDENCY_FAILURE")}),
    )
    # git ليس في required_capabilities — غيابه لا يظهر أصلًا في المطلوب
    assert result["verdict"] == "PASS"


def test_ttl_fresh_ready_skips_reprobe(sessions):
    """جاهزية صالحة (داخل TTL) لا تُعاد فحصها (§24) — قراءة من القاعدة."""
    probe_calls = {"n": 0}

    def counting_probe(sessions_, capability_id, **kwargs):
        probe_calls["n"] += 1
        return registry.record_probe(sessions_, capability_id, _ready())

    _sandbox_ready(sessions)
    first = preflight.task_preflight(
        sessions, "مهمة", run_probe_fn=counting_probe)
    assert first["verdict"] == "PASS"
    # (011 §14) sandbox جاهزتها من سجل البيئات (READY) — لا مسبار لها؛
    # البقية (llm/ملفات/شبكة/قشدة/قاعدة) فُحصت فعليًا
    assert probe_calls["n"] == len(first["required"]) - 1

    second = preflight.task_preflight(
        sessions, "مهمة", run_probe_fn=counting_probe)
    assert second["verdict"] == "PASS"
    assert probe_calls["n"] == len(first["required"]) - 1  # لا إعادة فحص


def test_stale_ready_is_reprobed(sessions):
    calls = {"n": 0}

    def probe(sessions_, capability_id, **kwargs):
        calls["n"] += 1
        return registry.record_probe(
            sessions_, capability_id,
            ProbeResult(
                status="READY", reason="ok",
                checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
                expires_at=(_dt.datetime.now(_dt.timezone.utc)
                            - _dt.timedelta(seconds=1)).isoformat(),
                ttl_seconds=1,
            ),
        )

    _sandbox_ready(sessions)
    preflight.task_preflight(sessions, "مهمة", run_probe_fn=probe)
    preflight.task_preflight(sessions, "مهمة", run_probe_fn=probe)
    # منتهية الصلاحية أُعيد فحصها (لا جاهزية أبدية §24) — sandbox مستثناة
    # (جاهزيتها من سجل البيئات لا من مسبار قابل للانتهاء — 011 §14)
    assert calls["n"] == 2 * (len(preflight.required_capabilities("مهمة")) - 1)


def test_preflight_events_shape():
    ok = {"verdict": "PASS", "required": ["llm"],
          "capabilities": [{"capability_id": "llm", "status": "READY"}],
          "blocked": [], "summary": "جاهز"}
    events = preflight.preflight_events(ok)
    kinds = [e["kind"] for e in events]
    assert kinds == ["preflight.started", "preflight.passed"]

    blocked = {"verdict": "BLOCKED", "required": ["llm"],
               "capabilities": [], "blocked": [
                   {"capability_id": "llm", "status": "NOT_READY",
                    "reason": "لا مفتاح", "recovery": "احفظ المفتاح",
                    "owner_action": "قرار مطلوب"}],
               "summary": "الحواجز: llm"}
    events = preflight.preflight_events(blocked)
    assert events[-1]["kind"] == "preflight.blocked"
    assert events[-1]["details"]["blocked"][0]["owner_action"]


def test_required_capabilities_from_real_inventory():
    required = preflight.required_capabilities("اريد بناء منصة OSINT")
    inventory_ids = {c["capability_id"] for c in registry.CAPABILITY_INVENTORY}
    # المطلوب من الجرد المعلن حصرًا — لا قدرة مخترعة (§3)
    assert set(required) <= inventory_ids
    assert "llm" in required and "web_search" in required
