"""اختبارات P1 (AES-EXP-03) — جرد البيئة يعيد نتيجة محددة ضمن مهلة.

الجذر الموثق: ``GET /api/environment/inventory`` كان يشغّل مسبارات
شبكية غير محدودة (``gethostbyname`` بلا مهلة + فحوص متسلسلة) داخل
مسار الطلب المتزامن — مُحلِّل متعثر = تعليق غير محدود للواجهة.

العقد بعد الإصلاح: كل عنصر بحد زمني صارم، والتجاوز نتيجة صريحة
(NOT_READY بسبب «تجاوز مهلة»)، والرد كله ضمن ميزانية معلنة.
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api import routes  # noqa: E402
import browser.provider as browser_provider  # noqa: E402
import readiness.environment as env_mod  # noqa: E402
import readiness.probes as probes  # noqa: E402
from readiness.probes import ProbeResult  # noqa: E402


@pytest.fixture()
def client(api_env):
    return TestClient(routes.app)


@pytest.fixture()
def no_network_probes(monkeypatch):
    """فصل كل المسبارات الشبكية عن الشبكة الحية — اختبار حتمي."""

    def fast_dns(host="example.com", timeout=None):
        return ProbeResult(
            status="READY", reason=f"حلّ {host} ← 93.184.216.34",
            checked_at="2020-01-01T00:00:00+00:00", ttl_seconds=120,
            details={"host": host, "address": "93.184.216.34"})

    def fast_https(url="https://example.com", fetch=None):
        return ProbeResult(
            status="READY", reason="HTTP 200 · 1024 بايت مقروءة",
            checked_at="2020-01-01T00:00:00+00:00", ttl_seconds=120)

    def fast_repo():
        return ProbeResult(
            status="READY", reason="المستودع متاح",
            checked_at="2020-01-01T00:00:00+00:00", ttl_seconds=600)

    monkeypatch.setattr(probes, "probe_dns", fast_dns)
    monkeypatch.setattr(probes, "probe_https", fast_https)
    monkeypatch.setattr(env_mod.probes, "probe_dns", fast_dns)
    monkeypatch.setattr(env_mod.probes, "probe_https", fast_https)
    monkeypatch.setattr(
        browser_provider.DEFAULT_PROVIDER, "available",
        lambda: (False, "معطل للاختبار"))
    return None


def test_inventory_success_fast_and_complete(client, api_env,
                                             no_network_probes):
    """النجاح: رد 200 كامل خلال مهلة معلومة، بكل العناصر والملخص."""
    t0 = time.monotonic()
    resp = client.get("/api/environment/inventory")
    elapsed = time.monotonic() - t0
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("budget_seconds", 0) > 0
    assert elapsed < body["budget_seconds"] + 10
    items = body["items"]
    for key in ("os", "python", "cpu", "ram", "disk", "git", "pip",
                "shell", "network", "network_dns", "network_https",
                "repository_access", "filesystem", "process_execution"):
        assert key in items, f"عنصر الجرد {key} مفقود"
    assert items["os"]["status"] == "READY"
    assert items["python"]["status"] == "READY"
    assert body["summary"]["ready"] >= 2
    # لا بيانات قديمة تُقدَّم كفحص حديث: طابع زمني لكل عنصر
    for key, item in items.items():
        assert item.get("checked_at"), f"{key} بلا طابع زمني"


def test_slow_dns_cannot_hang_inventory(client, api_env, monkeypatch):
    """التأخير: مُحلِّل بطيء ← NOT_READY بسبب تجاوز المهلة، لا تعليق."""
    def slow_resolve(host):
        time.sleep(4)
        return "1.2.3.4"

    monkeypatch.setattr(socket, "gethostbyname", slow_resolve)
    monkeypatch.setattr(probes, "DNS_RESOLVE_TIMEOUT", 0.4)
    monkeypatch.setattr(
        browser_provider.DEFAULT_PROVIDER, "available",
        lambda: (False, "معطل للاختبار"))

    def fast_https(url="https://example.com", fetch=None):
        return ProbeResult(status="NOT_READY", reason="معطل للاختبار",
                           checked_at="2020-01-01T00:00:00+00:00")

    monkeypatch.setattr(probes, "probe_https", fast_https)
    monkeypatch.setattr(env_mod.probes, "probe_https", fast_https)

    t0 = time.monotonic()
    resp = client.get("/api/environment/inventory")
    elapsed = time.monotonic() - t0
    assert resp.status_code == 200
    assert elapsed < 20, f"الجرد تعلق {elapsed:.1f}ث — العقد مكسور"
    net_dns = resp.json()["items"]["network_dns"]
    assert net_dns["status"] == "NOT_READY"
    assert "تجاوز" in net_dns["reason"]
    assert net_dns["details"]["timeout_s"] == 0.4


def test_probe_failure_is_a_result_not_a_500(client, api_env, monkeypatch):
    """الفشل: مسبار يرفع استثناء ← عنصر NOT_READY بسبب، والرد 200."""
    def boom_https(url="https://example.com", fetch=None):
        raise RuntimeError("انفجار محاكى في مسبار HTTPS")

    monkeypatch.setattr(probes, "probe_https", boom_https)
    monkeypatch.setattr(env_mod.probes, "probe_https", boom_https)
    monkeypatch.setattr(
        browser_provider.DEFAULT_PROVIDER, "available",
        lambda: (True, "Playwright + Chromium جاهز (اختبار)"))

    resp = client.get("/api/environment/inventory")
    assert resp.status_code == 200
    https = resp.json()["items"]["network_https"]
    assert https["status"] == "NOT_READY"
    assert "انفجار" in https["reason"]


def test_missing_tool_reports_unavailable(client, api_env, monkeypatch):
    """تعذر الوصول: أداة غائبة ← UNAVAILABLE بسبب صريح لا صمت."""
    def fail_version(args):
        return False, ""

    monkeypatch.setattr(env_mod, "_cmd_version", fail_version)
    resp = client.get("/api/environment/inventory")
    assert resp.status_code == 200
    items = resp.json()["items"]
    for tool in ("node", "npm", "docker", "podman"):
        assert items[tool]["status"] == "UNAVAILABLE"
        assert items[tool]["reason"]


def test_process_execution_timeout_is_result_not_500(
        client, api_env, monkeypatch):
    """مهلة تنفيذ العملية الصغيرة ← NOT_READY بسبب، لا استثناء مكشوف."""
    import subprocess as _subprocess

    def slow_run(*args, **kwargs):
        raise _subprocess.TimeoutExpired(cmd="python", timeout=0.01)

    monkeypatch.setattr(env_mod.subprocess, "run", slow_run)
    resp = client.get("/api/environment/inventory")
    assert resp.status_code == 200
    proc = resp.json()["items"]["process_execution"]
    assert proc["status"] == "NOT_READY"
    assert proc["reason"]
