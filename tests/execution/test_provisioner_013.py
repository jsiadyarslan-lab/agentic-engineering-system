"""اختبارات مزوّد بيئة التنفيذ (013 §16-§17+§44) — دورة معلنة صادقة."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from execution import provisioner  # noqa: E402


@pytest.fixture()
def env_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from persistence.database import build_engine, init_db, make_session_factory

    engine = build_engine(tmp_path / "prov013.db")
    init_db(engine)
    return make_session_factory(engine)


def test_provision_states_vocabulary():
    """(§16) مفردة الحالات مقفلة بالترتيب الهندسي المعلن."""
    assert provisioner.PROVISION_STATES == (
        "DISCOVERING", "PROVISIONING", "BOOTING", "HEALTH_CHECK",
        "READY", "DEGRADED", "FAILED", "STOPPED",
    )


def test_provision_full_cycle_real(env_db):
    """(§44) تجهيز ← صحة ← تنفيذ معزول ← التقاط — دورة حقيقية.

    في بيئة فيها ركيزة حقيقية (Linux/container) تكتمل الدورة إلى
    READY بفحوص فعلية؛ في بيئة بلا ركيزة تكون النتيجة صادقة
    (FAILED/PROVISIONING_UNAVAILABLE بسبب حرفي) — كلاهما مقبول،
    المرفوض هو READY بلا فحص.
    """
    result = provisioner.provision(env_db)
    states = [s["state"] for s in result["steps"]]

    assert "DISCOVERING" in states and "PROVISIONING" in states
    if result["state"] == "READY":
        # الدورة الكاملة: BOOTING + HEALTH_CHECK ناجحان وبيئة جاهزة
        assert "BOOTING" in states and "HEALTH_CHECK" in states
        health = next(s for s in result["steps"]
                      if s["state"] == "HEALTH_CHECK")
        assert health["ok"] is True
        checks = health.get("checks") or []
        check_names = {c["name"] for c in checks}
        assert {"boot", "execute", "capture"} <= check_names, \
            f"فحوص الصحة ناقصة: {check_names}"
        assert all(c["ok"] for c in checks)
        assert result["environment"]["name"]
        assert result["heartbeat"]["ok"] is True
    else:
        # صادق: FAILED أو PROVISIONING_UNAVAILABLE بسبب حرفي + متطلب
        assert result["state"] in ("FAILED", "PROVISIONING_UNAVAILABLE")
        assert result["reason"], "فشل بلا سبب حرفي — غير صادق"
        if result["state"] == "PROVISIONING_UNAVAILABLE":
            assert result["requirement"], "المتطلب الخارجي غير معلن"

    # كل خطوة موقوتة ومعلنة (§17 عرض خطوة بخطوة)
    for step in result["steps"]:
        assert "detail" in step and step["detail"], \
            f"خطوة بلا نص معلن: {step}"


def test_heartbeat_records_time_and_truth(env_db):
    """(§16) النبضة: فحص حقيقي بالوقت والنتيجة — لا نبضة بلا فحص."""
    beat = provisioner.heartbeat(env_db)
    assert beat["at"], "النبضة بلا وقت"
    assert isinstance(beat["ok"], bool)
    assert beat["latency_ms"] >= 0
    # النبضة الأخيرة تُقرأ كما كتبت
    assert provisioner.last_heartbeat()["at"] == beat["at"]


def test_provisioner_endpoint_registered():
    """نقاط التجهيز مسجلة في التطبيق (§17 واجهة التجهيز)."""
    from api import routes

    schema_paths = []
    try:
        from fastapi.testclient import TestClient

        schema_paths = TestClient(routes.app).get(
            "/openapi.json"
        ).json()["paths"]
    except Exception:  # noqa: BLE001 — تكوين الإنتاج قد يفتقد مزودًا
        pytest.skip("التطبيق لا يقلع في هذه البيئة الاختبارية")
    assert "/api/environment/provision" in schema_paths
    assert "/api/environment/provision/heartbeat" in schema_paths
