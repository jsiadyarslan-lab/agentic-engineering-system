"""اختبار نقاط نهاية بيئات التنفيذ والبحث (الأمر 010 §24-§28).

CRUD حقيقي عبر الـAPI مع خلفية مضبوطة (الفحوص الحقيقية لها اختباراتها
في tests/execution/) — التحقق من العقد: لا أسرار، لا خلفيات وهمية،
وخيارات مدعومة من الكود فعلًا حصرًا.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from api import routes  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


# ------------------------------------------------------------------ #
# بيئات التنفيذ
# ------------------------------------------------------------------ #

def test_environments_list_registers_local_automatically(client):
    out = client.get("/api/execution/environments")
    assert out.status_code == 200
    data = out.json()
    names = [e["name"] for e in data["environments"]]
    assert "local-linux" in names
    backends = {b["backend"] for b in data["supported_backends"]}
    assert backends == {"LOCAL", "REMOTE_WORKER"}  # لا خلفية وهمية
    # لا مراجع أسرار في أي رد
    for env in data["environments"]:
        assert "token_ref" not in env


def test_add_environment_rejects_unsupported_backend(client):
    out = client.post("/api/execution/environments", json={
        "name": "docker-x", "backend": "DOCKER",
    })
    assert out.status_code == 422
    # الخيارات المدعومة حصرًا معلنة في رسالة الرفض
    assert "LOCAL" in str(out.json()["detail"])
    assert "REMOTE_WORKER" in str(out.json()["detail"])


def test_add_remote_worker_requires_endpoint(client):
    out = client.post("/api/execution/environments", json={
        "name": "w", "backend": "REMOTE_WORKER", "endpoint": "not-a-url",
    })
    assert out.status_code == 422
    assert "رابط العامل" in out.json()["detail"]


def test_verify_environment_via_api_with_seamed_backend(client, monkeypatch):
    from execution import service as execution_service
    from execution.backends import VerifyResult

    added = client.post("/api/execution/environments", json={
        "name": "worker-api-test", "backend": "REMOTE_WORKER",
        "endpoint": "http://127.0.0.1:9995",
    }).json()
    env_id = added["id"]

    class Seam:
        backend_kind = "STUB"

        def describe(self):
            return {"os": "T", "architecture": "t", "sandboxed": False,
                    "available": True}

        def verify(self):
            return VerifyResult(
                ok=True, status="READY",
                checks=[{"name": "boot", "ok": True, "detail": "stub"}],
                profile=self.describe(),
            )

    monkeypatch.setattr(execution_service, "build_backend", lambda env: Seam())
    out = client.post(f"/api/execution/environments/{env_id}/verify")
    assert out.status_code == 200
    data = out.json()
    assert data["status"] == "READY"
    assert data["verify"]["checks"][0]["ok"] is True
    # تنظيف
    assert client.delete(
        f"/api/execution/environments/{env_id}"
    ).status_code == 200


def test_local_environment_cannot_be_deleted(client):
    environments = client.get("/api/execution/environments").json()
    local = [e for e in environments["environments"]
             if e["name"] == "local-linux"][0]
    out = client.delete(f"/api/execution/environments/{local['id']}")
    assert out.status_code == 422


# ------------------------------------------------------------------ #
# مزودو البحث
# ------------------------------------------------------------------ #

def test_research_providers_seeded(client):
    out = client.get("/api/research/providers")
    assert out.status_code == 200
    kinds = {p["kind"] for p in out.json()["providers"]}
    assert kinds == {"search_ddg", "search_searx", "search_api"}


def test_research_configure_and_probe_with_seamed_transport(
    client, monkeypatch,
):
    from research import providers as rp

    providers_list = client.get("/api/research/providers").json()["providers"]
    searx = [p for p in providers_list if p["kind"] == "search_searx"][0]

    out = client.post(
        f"/api/research/providers/{searx['id']}/configure",
        json={"config": {"base_url": "https://searx.example.org"},
              "enabled": True},
    )
    assert out.status_code == 200
    configured = out.json()
    assert configured["config"]["base_url"] == "https://searx.example.org"
    assert configured["enabled"] is True
    # لا مفاتيح في الرد أبدًا
    assert "api_key" not in str(configured)

    # مسبار بمصدر مضبوط (النقل مجمد — نفس المسار)
    class FakeResponse:
        def read(self, _n=-1):
            return (b'{"results": [{"title": "T", '
                    b'"url": "https://x.example/1", "content": "c"}]}')

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        rp.urllib.request, "urlopen",
        lambda req, timeout=None: FakeResponse(),
    )
    probe = client.post(f"/api/research/providers/{searx['id']}/probe")
    assert probe.status_code == 200
    assert probe.json()["status"] == "READY"


def test_research_search_endpoint_reports_all_providers(client, monkeypatch):
    """فشل الجميع = خطأ مفصل لكل مزود لا «إنترنت مقطوع» (§24)."""
    from research import providers as rp

    def failing_open(req, timeout=None):
        raise OSError("timed out")

    monkeypatch.setattr(rp.urllib.request, "urlopen", failing_open)
    out = client.post("/api/research/search", json={"query": "اختبار"})
    assert out.status_code == 503
    detail = out.json()["detail"]
    assert "DuckDuckGo" in detail  # المزود مسمّى
