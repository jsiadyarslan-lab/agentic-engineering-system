"""اختبارات زمن تشغيل الأدوار وعقود القدرات (012-B+012-C).

القرار المحفوظ رقم 1 مقفول هنا: الأدوار تتواصل عبر العقود حصرًا —
RoleRuntime يرفض طلبًا أو نتيجة خارج عقد الدور، والقدرات تُحل من
مصدر الحقيقة الواحد بلا اشتقاق موازٍ.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from harness.capabilities import (  # noqa: E402
    capability_catalog, blocked_kind_of, resolve_capability,
)
from harness.roles_runtime import (  # noqa: E402
    ROLE_DEFINITIONS, RoleRuntime, describe_roles, role_runtime_view,
)
from harness.seams import HarnessSeams  # noqa: E402


# ------------------------------------------------------------------ #
# تعريفات الأدوار — الخمسة ككيانات أولى
# ------------------------------------------------------------------ #

def test_five_roles_declared_with_contracts():
    roles = describe_roles()
    assert [r["role"] for r in roles] == [
        "thinker", "reviewer", "implementer", "verifier", "arbiter",
    ]
    for described in roles:
        assert described["request_contract"].endswith("Request")
        assert described["result_contract"].endswith("Result")
        assert described["prompt"].startswith("prompts/")
        assert described["enters_state"] and described["exit_by"]


def test_role_definitions_match_actual_contracts():
    """التعريفات من العقود الفعلية — لا وصفًا منفصلًا يدّعي."""
    from roles.arbiter import ArbiterRequest, ArbiterResult
    from roles.implementer import (
        ImplementerRequest, ImplementerResult,
    )
    from roles.reviewer import ReviewerRequest, ReviewerResult
    from roles.thinker import ThinkerRequest, ThinkerResult
    from roles.verifier import VerifierRequest, VerifierResult

    assert ROLE_DEFINITIONS["thinker"].request_contract is ThinkerRequest
    assert ROLE_DEFINITIONS["thinker"].result_contract is ThinkerResult
    assert ROLE_DEFINITIONS["reviewer"].request_contract is ReviewerRequest
    assert ROLE_DEFINITIONS["reviewer"].result_contract is ReviewerResult
    assert ROLE_DEFINITIONS["implementer"].request_contract \
        is ImplementerRequest
    assert ROLE_DEFINITIONS["implementer"].result_contract \
        is ImplementerResult
    assert ROLE_DEFINITIONS["verifier"].request_contract is VerifierRequest
    assert ROLE_DEFINITIONS["verifier"].result_contract is VerifierResult
    assert ROLE_DEFINITIONS["arbiter"].request_contract is ArbiterRequest
    assert ROLE_DEFINITIONS["arbiter"].result_contract is ArbiterResult


def test_role_prompts_exist_on_disk():
    for described in describe_roles():
        path = REPO / described["prompt"]
        assert path.is_file(), described["prompt"]


def test_only_implementer_carries_tools():
    """المنفذ وحده يحمل أدوات — بقية الأدوار تحليلية (عقد لا أدوات)."""
    for role, definition in ROLE_DEFINITIONS.items():
        if role == "implementer":
            assert len(definition.allowed_tools) >= 10
            assert "web_search" in definition.allowed_tools
            assert "write_file" in definition.allowed_tools
        else:
            assert definition.allowed_tools == (), role


def test_implementer_budget_is_two_live_calls():
    assert ROLE_DEFINITIONS["implementer"].max_live_calls == 2
    for role, definition in ROLE_DEFINITIONS.items():
        if role != "implementer":
            assert definition.max_live_calls == 1, role


# ------------------------------------------------------------------ #
# RoleRuntime — أحداث role/* + إلزام العقد
# ------------------------------------------------------------------ #

class _StubThinker:
    selection = None

    def run(self, request):
        from roles.thinker import ThinkerResult

        return ThinkerResult(plan={
            "objective": request.goal,
            "assumptions": ["فرض"],
            "acceptance_criteria": ["معيار"],
            "phases": [{
                "title": "مرحلة", "objective": "هدف",
                "acceptance_criteria": ["معيار"],
                "steps": [{
                    "objective": "خطوة", "input": "",
                    "expected_output": "مخرج",
                    "acceptance_criteria": ["معيار"],
                    "dependencies": [],
                }],
            }],
            "risks": [], "dependencies": [],
            "required_owner_decisions": [],
        })


class _BrokenThinker(_StubThinker):
    def run(self, request):
        return {"not": "a contract"}


def test_role_runtime_emits_and_enforces_contract():
    from roles.thinker import ThinkerRequest

    events: list[dict] = []
    runtime = RoleRuntime(
        ROLE_DEFINITIONS["thinker"], _StubThinker(),
        on_event=events.append,
    )
    request = ThinkerRequest(goal="هدف", context="", previous_reviews=[])
    result = runtime.run(request)

    from roles.thinker import ThinkerResult

    assert isinstance(result, ThinkerResult)
    kinds = [e["kind"] for e in events]
    assert kinds == ["role/started", "role/completed"]
    assert events[0]["payload"]["request_contract"] == "ThinkerRequest"
    assert events[1]["payload"]["duration_ms"] >= 0


def test_role_runtime_rejects_wrong_result_contract():
    from roles.thinker import ThinkerRequest

    events: list[dict] = []
    runtime = RoleRuntime(
        ROLE_DEFINITIONS["thinker"], _BrokenThinker(),
        on_event=events.append,
    )
    with pytest.raises(TypeError, match="تخرق عقد الدور"):
        runtime.run(ThinkerRequest(goal="هدف", context="",
                                   previous_reviews=[]))
    kinds = [e["kind"] for e in events]
    assert kinds == ["role/started", "role/failed"]
    assert "تخرق عقد الدور" in events[1]["payload"]["error"]


def test_role_runtime_rejects_wrong_request_type():
    events: list[dict] = []
    runtime = RoleRuntime(
        ROLE_DEFINITIONS["thinker"], _StubThinker(),
        on_event=events.append,
    )
    with pytest.raises(TypeError, match="لا يطابق عقد الدور"):
        runtime.run({"goal": "طلب خام"})
    assert [e["kind"] for e in events] == ["role/started", "role/failed"]


# ------------------------------------------------------------------ #
# عقود القدرات — الحل من مصدر الحقيقة + تصنيف الانتظار
# ------------------------------------------------------------------ #

def test_resolve_llm_per_role(harness_env):
    # موجّه صريح للمختبَر: nvidia حي
    from tests.harness.conftest import ScriptedRouter

    seams = HarnessSeams(
        harness_env["sessions"],
        router_factory=lambda: ScriptedRouter(("nvidia",)),
    )
    out = resolve_capability(seams, "llm")
    assert out["blocked_kind"] == "CAPABILITY"
    assert out["status"] == "READY"
    assert len(out["providers"]) == 5       # الأدوار الخمسة
    assert all(p["ready"] for p in out["providers"])

    # دور واحد بعينه — الربط المستقل لا التوريث
    single = resolve_capability(seams, "llm", role="implementer")
    assert len(single["providers"]) == 1
    assert single["providers"][0]["name"] == "implementer"
    assert single["detail"]["role"] == "implementer"

    # مزود غائب → NOT_READY يسمي الأدوار
    broken = HarnessSeams(
        harness_env["sessions"],
        router_factory=lambda: ScriptedRouter(()),
    )
    out = resolve_capability(broken, "llm")
    assert out["status"] == "NOT_READY"
    assert "implementer" in out["reason"]


def test_resolve_sandbox_from_environments(harness_env, sandbox_seam):
    seams = HarnessSeams(harness_env["sessions"])
    out = resolve_capability(seams, "sandbox")
    assert out["blocked_kind"] == "WORKER"
    assert out["resolution"] == "SINGLE"
    assert out["status"] == "NOT_READY"
    assert out["detail"]["readiness_ladder"].startswith("connectivity")
    assert any(p["name"].startswith("local") for p in out["providers"])

    sandbox_seam["provision"]()
    out = resolve_capability(seams, "sandbox")
    assert out["status"] == "READY"
    assert out["selected"]["sandboxed"] is True


def test_capability_catalog_unified(harness_env, sandbox_seam):
    from tests.harness.conftest import ScriptedRouter

    seams = HarnessSeams(
        harness_env["sessions"],
        router_factory=lambda: ScriptedRouter(("nvidia",)),
    )
    catalog = capability_catalog(seams)
    ids = {c["capability_id"] for c in catalog}
    # الجرد كامل: مصادر 011 + تنظيم الـharness
    assert {"llm", "web_search", "sandbox", "browser",
            "filesystem"} <= ids
    by_id = {c["capability_id"]: c for c in catalog}
    assert by_id["sandbox"]["blocked_kind"] == "WORKER"
    assert by_id["web_search"]["blocked_kind"] == "CAPABILITY"
    assert by_id["web_search"]["resolution"] == "FAILOVER"
    assert len(by_id["web_search"]["providers"]) == 4
    # browser صادقة: UNAVAILABLE لا READY أبدًا (009 §3 محفوظ)
    assert by_id["browser"]["status"] in ("UNAVAILABLE", "NOT_READY",
                                          "UNKNOWN")


def test_web_search_failover_orders_ready_first(harness_env):
    """ترتيب السلسلة: الجاهز أولًا — DDG معطل لا يعني البحث معطلًا."""
    from research import service as research_service

    sessions = harness_env["sessions"]
    research_service.ensure_seeded(sessions)
    # عطّل DDG (المزود الأول افتراضيًا) وفعّل SearXNG بتكوين
    providers = research_service.list_providers(sessions)
    for record in providers:
        if record["kind"] == "search_ddg":
            research_service.configure_provider(
                sessions, record["id"], enabled=False, probe_after=False
            )
        if record["kind"] == "search_searx":
            research_service.configure_provider(
                sessions, record["id"],
                config={"base_url": "http://searx.example.local"},
                probe_after=False,
            )
    seams = HarnessSeams(sessions)
    out = resolve_capability(seams, "web_search")
    statuses = [p["status"] for p in out["providers"]]
    # كل جاهز يسبق المعطل صراحةً — ترتيب الجاهزية الفعالة
    assert statuses[-1] in ("DISABLED", "NOT_CONFIGURED")
    if "READY" in statuses:
        assert statuses[0] == "READY"
    assert out["detail"]["failover"]
    # تعطيل الجميع لا يعني READY أبدًا
    for record in research_service.list_providers(sessions):
        research_service.configure_provider(
            sessions, record["id"], enabled=False, probe_after=False
        )
    out = resolve_capability(seams, "web_search")
    assert out["status"] != "READY"
