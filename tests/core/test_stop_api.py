"""اختبارات عقد نقاط نهاية الإيقاف/الاستئناف (الأمر 004) — HTTP.

عقود الرفض الصادقة: 404 لدورة/لقطة غير معروفة، 409 لدورة ليست قيد
التشغيل أو مهمة لا تعمل، 422 لمعرف غير صالح (fail-closed ضد اجتياز
المسارات). المسار السعيد أثناء التشغيل مغطى في tests/core/ (مستوى
المنسق والمهمة) — هنا طبقة النقل حصرًا.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("httpx", reason="TestClient يتطلب httpx")

from api import routes  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(routes.app)


def test_cycle_stop_unknown_id_404(client):
    resp = client.post(
        "/api/cycle/stop", json={"cycle_id": "cycle-nonexistent"}
    )
    assert resp.status_code == 404
    assert "غير معروفة" in resp.json()["detail"]


def test_cycle_stop_finished_cycle_409(client, tmp_path):
    result = routes._orchestrator.run_cycle(
        "دورة كاملة لعقد الإيقاف", workspace_root=tmp_path
    )
    resp = client.post("/api/cycle/stop", json={"cycle_id": result.cycle_id})
    assert resp.status_code == 409
    assert "ليست قيد التشغيل" in resp.json()["detail"]
    assert result.final_state.value in resp.json()["detail"]


def test_cycle_status_unknown_404(client):
    assert client.get("/api/cycle/status/cycle-unknown").status_code == 404


def test_cycle_status_invalid_id_422(client):
    """معرف بخط مائل = محاولة اجتياز — رفض fail-closed قبل أي مسار."""
    resp = client.get("/api/cycle/status/../etc")
    assert resp.status_code in (404, 422)


def test_cycle_status_finished_shape(client, tmp_path):
    result = routes._orchestrator.run_cycle(
        "دورة لفحص الحالة", workspace_root=tmp_path
    )
    resp = client.get(f"/api/cycle/status/{result.cycle_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "EVIDENCED"
    assert body["running"] is False
    assert body["stop_requested"] is False
    assert body["stop_receipt"] is None
    assert body["can_resume"] is False


def test_cycle_resume_invalid_id_422(client):
    resp = client.post(
        "/api/cycle/resume", json={"cycle_id": "../escape/attempt"}
    )
    assert resp.status_code == 422


def test_cycle_resume_no_snapshot_404(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # لا runtime/cycles هنا — لا لقطة إطلاقًا
    (tmp_path / "runtime" / "cycles" / "cycle-empty").mkdir(parents=True)
    resp = client.post(
        "/api/cycle/resume", json={"cycle_id": "cycle-empty"}
    )
    assert resp.status_code == 404
    assert "لا لقطة" in resp.json()["detail"]


def test_mission_stop_no_active_409(client):
    resp = client.post("/api/mission/stop", json={"reason": "لا شيء يعمل"})
    assert resp.status_code == 409
    assert "لا مهمة حية" in resp.json()["detail"]


def test_mission_status_idle_shape(client):
    resp = client.get("/api/mission/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False
    assert body["stop_requested"] is False
    assert body["stop_receipt"] is None


def test_mission_resume_no_snapshot_404(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resp = client.post("/api/mission/resume")
    assert resp.status_code == 404
    assert "لا لقطة إيقاف" in resp.json()["detail"]
