"""اختبارات سجل القدرات والمسبارات (الأمر 009 §28).

المسبارات حقيقية حيث يكون الفحص محليًا (ملفات/git/قشدة/قاعدة)،
ومحقونة بمصادر مضبوطة حيث الشبكة (بحث/جلب/HTTPS/LLM) — المسار
نفسه، المصدر معلن. لا READY بلا مسبار ناجح (§27).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from persistence.database import build_engine, init_db, make_session_factory
from readiness import probes, registry
from readiness.models import CapabilityRecord, ToolInvocation
from roles.tool_failures import ToolFailure


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "readiness-test.db")
    init_db(engine)
    return make_session_factory(engine)


# ------------------------------------------------------------------ #
# Registry (§28: registration/discovery/missing/transitions)
# ------------------------------------------------------------------ #

def test_capability_registration_and_inventory(sessions):
    caps = registry.get_capabilities(sessions)
    ids = {c["capability_id"] for c in caps}
    # جرد حقيقي من الكود: أدوات القائمة البيضاء + الركيزة + الشبكة…
    assert {"web_search", "sandbox", "llm", "git", "filesystem",
            "persistence"} <= ids
    by_id = {c["capability_id"]: c for c in caps}
    assert by_id["web_search"]["category"] == "RESEARCH"
    assert by_id["web_search"]["required"] is True
    # الأداة غير المنفذة تظهر UNAVAILABLE بسبب صريح (§3) — لا READY
    assert by_id["browser"]["readiness_status"] == "UNAVAILABLE"
    assert "NOT_IMPLEMENTED" in by_id["browser"]["failure_reason"]


def test_status_transition_unknown_to_ready_to_stale(sessions):
    result = probes.ProbeResult(
        status="READY", reason="مسبار حقيقي نجح",
        checked_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-01T00:00:01+00:00",  # منتهية فورًا
        ttl_seconds=1,
    )
    registry.record_probe(sessions, "filesystem", result)
    cap = registry.get_capability(sessions, "filesystem")
    # (§24) READY منتهية الصلاحية تُعرض STALE — لا جاهزية أبدية
    assert cap["readiness_status"] == "STALE"
    assert cap["stored_status"] == "READY"


def test_failure_records_class_and_stage(sessions):
    result = probes.ProbeResult(
        status="NOT_READY", reason="الشبكة مقطوعة",
        checked_at="2026-01-01T00:00:00+00:00",
        failure_class="NETWORK_FAILURE", failure_stage="TOOL_EXECUTION",
    )
    registry.record_probe(sessions, "network_dns", result)
    cap = registry.get_capability(sessions, "network_dns")
    assert cap["readiness_status"] == "NOT_READY"
    assert cap["failure_class"] == "NETWORK_FAILURE"
    assert cap["failure_stage"] == "TOOL_EXECUTION"
    assert cap["last_failure_at"] is not None
    assert cap["last_success_at"] is None


# ------------------------------------------------------------------ #
# المسبارات الفعلية (§6+§11-§14)
# ------------------------------------------------------------------ #

def test_filesystem_probe_real():
    result = probes.probe_filesystem()
    assert result.status == "READY"   # إنشاء/قراءة/تعديل/حذف فعلي
    assert result.latency_ms >= 0


def test_git_probe_real():
    result = probes.probe_git()
    assert result.status == "READY"
    assert "git version" in result.details["version"].lower()


def test_dns_probe_real():
    result = probes.probe_dns()
    assert result.status in ("READY", "NOT_READY")  # صدق حسب الشبكة
    if result.status == "READY":
        assert result.details["address"]


def test_web_search_probe_with_injected_source(sessions):
    """مسبار البحث بمصدر مضبوط (§6): نتائج قابلة للتحليل = READY،
    بلا نتائج = NOT_READY/TOOL_FAILURE — لا READY بلا دليل."""
    good = lambda q: [  # noqa: E731
        {"title": f"نتيجة {i}", "url": f"https://example.com/{i}",
         "snippet": "مقتطف"} for i in range(4)
    ]
    result = probes.probe_web_search(search_fn=good)
    assert result.status == "READY"
    assert result.details["usable_count"] == 4

    def no_material(_q):
        raise ToolFailure(
            "web_search", "لا مادة", failure_class="TOOL_FAILURE",
            reason="RESULTS_NOT_ANALYZABLE", stage="TOOL_RESULT",
        )

    result = probes.probe_web_search(search_fn=no_material)
    assert result.status == "NOT_READY"
    assert result.failure_class == "TOOL_FAILURE"
    assert result.failure_stage == "TOOL_RESULT"


def test_web_search_probe_degraded_on_few_results():
    few = lambda q: [  # noqa: E731
        {"title": "واحدة", "url": "https://example.com/1", "snippet": "s"}
    ]
    result = probes.probe_web_search(search_fn=few)
    assert result.status == "DEGRADED"   # يعمل مع تحفظ — لا كذب بأي اتجاه


def test_https_probe_with_stub():
    class Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def read(self, _n=-1):
            return b"<html>ok</html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    result = probes.probe_https(fetch=lambda url, timeout=None: Response())
    assert result.status == "READY"
    assert result.details["http_status"] == 200


def test_sandbox_probe_real_or_unavailable():
    """الركيزة: جاهزة فعليًا (لينكس) أو UNAVAILABLE صادقة — لا READY كاذب."""
    result = probes.probe_sandbox()
    assert result.status in ("READY", "DEGRADED", "NOT_READY", "UNAVAILABLE")
    if result.status == "READY":
        assert result.details["artifact_persisted"] is True
        assert result.details["exit_code"] == 0
    if result.status == "UNAVAILABLE":
        assert result.failure_class == "SANDBOX_FAILURE"
        assert result.failure_stage == "STARTUP"


def test_model_inference_probe_classifies_failure():
    """استدلال فعلي (§10): فشل مصنَّف PROVIDER_FAILURE — لا /models دليلًا."""
    def boom(cfg, model):
        raise RuntimeError("connection refused")

    result = probes.probe_model_inference({"base_url": "http://x"}, "m")
    assert result.status == "NOT_READY"
    assert result.failure_class == "PROVIDER_FAILURE"


def test_run_probe_unimplemented_stays_unavailable(sessions):
    result = registry.run_probe(sessions, "browser")
    assert result["readiness_status"] == "UNAVAILABLE"
    assert "NOT_IMPLEMENTED" in result["failure_reason"]


def test_probe_all_covers_whole_inventory(sessions):
    results = registry.probe_all(sessions)
    ids = {r["capability_id"] for r in results}
    assert ids == {s["capability_id"] for s in registry.CAPABILITY_INVENTORY}


# ------------------------------------------------------------------ #
# سجل الاستدعاءات الدائم (§20)
# ------------------------------------------------------------------ #

def test_tool_invocation_table_persists(sessions):
    from tasks import _persist_tool_invocations
    from roles.tools import ToolContext, run_tool

    ctx = ToolContext(grant_root=Path("/tmp/ti-probe"))
    Path("/tmp/ti-probe").mkdir(exist_ok=True)
    with pytest.raises(ToolFailure):
        run_tool("shell_exec", {"cmd": "x"}, ctx)  # خارج القائمة البيضاء
    _persist_tool_invocations(sessions, "cycle-test", ctx.tool_records)
    with sessions() as session:
        rows = session.scalars(
            select(ToolInvocation).where(
                ToolInvocation.cycle_id == "cycle-test")
        ).all()
    assert len(rows) == 1
    assert rows[0].status == "FAILED"
    assert rows[0].failure_class == "POLICY_BLOCK"
    assert rows[0].failure_reason == "TOOL_NOT_WHITELISTED"
