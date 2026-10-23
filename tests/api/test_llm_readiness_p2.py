"""اختبار تكامل P2 (AES-EXP-03) — المحادثة والجاهزية من مصدر واحد.

السيناريو المُدان في AES-EXP-01: رسالة محادثة تصل بنجاح فعلي، ثم
فتح لوحة البيئة يعرض ``llm: UNKNOWN`` — تناقض مؤشرات. هنا: محادثة
ناجحة على المسار الحي نفسه ← قدرة llm تُعرض READY بدليل الاستدعاء
الحي المسجل، عبر نقطة النهاية نفسها التي تستهلكها الواجهة.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api import routes  # noqa: E402
from conftest import sse_events  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


def test_successful_chat_makes_llm_ready(client, api_env):
    """محادثة ناجحة ← llm READY في /api/environment/readiness."""
    resp = client.post("/api/chat/stream", json={
        "message": "ما أسرع طريقة لتعلم البرمجة؟",
        "provider": "zai-test", "model": "glm-test-4.6",
    })
    assert resp.status_code == 200
    events = sse_events(resp)
    completed = [e for e in events
                 if e.get("kind") == "message_completed"]
    assert completed, "المحادثة المخطوطة لم تكمل — الاختبار بلا معنى"

    out = client.get("/api/environment/readiness").json()
    llm = next(c for c in out["capabilities"]
               if c["capability_id"] == "llm")
    assert llm["readiness_status"] == "READY", llm
    assert llm["details"]["evidence_kind"] == "live_call"
    assert llm["details"]["last_live_success"]["provider"] == "zai-test"
    # لا تناقض: نفس الحالة في الملخص المشتق
    assert out["summary"]["READY"] >= 1


def test_chat_failure_shows_not_ready_with_class(client, api_env,
                                                 monkeypatch):
    """فشل حي حديث ← llm NOT_READY بصنفه — لا UNKNOWN ملتبس."""
    from router.model_router import ProviderCallError

    def broken_factory(**_kwargs):
        raise ProviderCallError("مزود مرفوض — محاكاة فشل حي")

    monkeypatch.setattr(routes, "_build_live_router", broken_factory)
    resp = client.post("/api/chat/stream", json={
        "message": "رسالة ستفشل",
        "provider": "zai-test", "model": "glm-test-4.6",
    })
    assert resp.status_code == 200

    out = client.get("/api/environment/readiness").json()
    llm = next(c for c in out["capabilities"]
               if c["capability_id"] == "llm")
    assert llm["readiness_status"] == "NOT_READY", llm
    assert llm["failure_reason"], llm
