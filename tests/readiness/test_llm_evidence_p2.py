"""اختبارات P2 (AES-EXP-03) — جاهزية LLM مشتقة من أدلة حقيقية.

التناقض الموثق: محادثة حية ناجحة بينما ``readiness_status: UNKNOWN``.
السبب: قدرة llm كانت تُقرأ من سجل المسبار وحده — لا مسبار = UNKNOWN
حتى مع نجاح استخدام فعلي مسجل. هنا تُشتق الحالة من أحدث دليل:

- نجاح حي حديث ← READY بدليل live_call (لا مسبار جديد مكلف).
- نجاح حي منتهي الصلاحية ← STALE بعمر الدليل.
- فشل حي أحدث ← NOT_READY بصنفه.
- لا دليل إطلاقًا ← UNKNOWN **بسبب معلن** (لا ادعاء بلا دليل).
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)
from readiness import registry, service as readiness_service  # noqa: E402


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "llm-evidence.db")
    init_db(engine)
    factory = make_session_factory(engine)
    registry.ensure_capabilities(factory)
    return factory


def _add_event(sessions, kind, details, minutes_ago=0.0):
    """كتابة حدث محادثة في مصدره الحقيقي (جدول events)."""
    from persistence.models import Event

    at = (_dt.datetime.now(_dt.timezone.utc)
          - _dt.timedelta(minutes=minutes_ago))
    payload = _json.dumps(
        {"kind": kind, "details": details}, ensure_ascii=False)
    with sessions() as s:
        s.add(Event(cycle_id="chat-test", seq=1, role="chat", kind=kind,
                    payload=payload, created_at=at))
        s.commit()


def _llm_view(sessions):
    view = readiness_service.capability_view(sessions, "llm")
    assert view is not None
    return view


def test_no_evidence_is_unknown_with_reason(sessions):
    """لا دليل إطلاقًا ← UNKNOWN بسبب معلن لا صمت ولا ادعاء."""
    view = _llm_view(sessions)
    assert view["readiness_status"] == "UNKNOWN"
    assert "لا مسبار حديث ولا استدعاء حي" in view["reason"]
    assert view["derived_from"] == "live_call_evidence"
    assert view["details"]["last_live_success"] is None
    assert view["details"]["last_live_failure"] is None


def test_fresh_live_success_is_ready_without_probe(sessions):
    """نجاح حي حديث ← READY بدليل live_call — بلا مسبار جديد مكلف."""
    _add_event(sessions, "message_completed", {
        "provider": "nvidia", "model": "nemotron-test",
        "tokens": 42, "duration_ms": 900,
    }, minutes_ago=2)
    view = _llm_view(sessions)
    assert view["readiness_status"] == "READY"
    assert view["details"]["evidence_kind"] == "live_call"
    assert view["details"]["last_live_success"]["provider"] == "nvidia"
    assert "دليل استخدام فعلي" in view["reason"]
    assert view["failure_reason"] == ""


def test_old_live_success_is_stale_not_ready(sessions):
    """نجاح حي خارج نافذة الصلاحية ← STALE بعمر الدليل المعلن."""
    _add_event(sessions, "message_completed", {
        "provider": "nvidia", "model": "nemotron-test",
    }, minutes_ago=20)
    view = _llm_view(sessions)
    assert view["readiness_status"] == "STALE"
    assert view["details"]["evidence_kind"] == "live_call"
    assert view["details"]["evidence_age_s"] > 600


def test_newer_live_failure_is_not_ready_with_class(sessions):
    """فشل حي أحدث من آخر نجاح ← NOT_READY بصنف الخطأ ومزوده."""
    _add_event(sessions, "message_completed", {
        "provider": "nvidia", "model": "nemotron-test",
    }, minutes_ago=30)
    _add_event(sessions, "chat.error", {
        "provider": "nvidia", "model": "nemotron-test",
        "error_class": "AUTH_FAILURE", "error": "401",
    }, minutes_ago=1)
    view = _llm_view(sessions)
    assert view["readiness_status"] == "NOT_READY"
    assert view["failure_reason"] == "AUTH_FAILURE"
    assert "فشل" in view["reason"]


def test_older_failure_does_not_mask_newer_success(sessions):
    """فشل قديم لا يُقنّع نجاحًا حديثًا — أحدث دليل هو الحكم."""
    _add_event(sessions, "chat.error", {
        "provider": "nvidia", "error_class": "PROVIDER_ERROR",
    }, minutes_ago=30)
    _add_event(sessions, "message_completed", {
        "provider": "nvidia", "model": "nemotron-test",
    }, minutes_ago=1)
    view = _llm_view(sessions)
    assert view["readiness_status"] == "READY"
    assert view["failure_reason"] == ""


def test_consistency_summary_matches_view(sessions):
    """الملخص يُحسب من العرض المشتق نفسه — لا تناقض عدّ ثانٍ."""
    _add_event(sessions, "message_completed", {
        "provider": "nvidia", "model": "nemotron-test",
    }, minutes_ago=1)
    summary = readiness_service.summary(sessions)
    view = _llm_view(sessions)
    assert summary[view["readiness_status"]] >= 1
