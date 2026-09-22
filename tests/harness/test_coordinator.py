"""اختبارات المنسق الحتمي (012-F) — القرار رقم 2: لا LLM في التنسيق.

كل قواعد classify_tick وجدول الانتقالات مقفلة باختبارات: نفس
المدخلات ← نفس القرار. أي تغيير سلوكي هنا يكسر اختبارًا صريحًا.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from harness import coordinator  # noqa: E402
from harness.coordinator import classify_tick  # noqa: E402
from harness.models import JOB_STATES, JOB_TERMINAL  # noqa: E402


# ---------- تصنيف القدرات: WORKER حكرًا على بيئة التنفيذ ----------

def test_blocked_kind_worker_is_sandbox_only():
    assert coordinator.blocked_kind_of("sandbox") == "WORKER"
    for capability in ("llm", "web_search", "network_dns", "git",
                       "browser", "filesystem"):
        assert coordinator.blocked_kind_of(capability) == "CAPABILITY", \
            capability


# ---------- جدول الانتقالات — مقفل ومكتمل ----------

def test_transitions_cover_all_states_and_terminal_locked():
    for state in JOB_STATES:
        assert state in coordinator.JOB_TRANSITIONS, state
    for terminal in JOB_TERMINAL:
        assert coordinator.JOB_TRANSITIONS[terminal] == (), terminal


def test_can_transition_rules():
    assert coordinator.can_transition("QUEUED", "RUNNING")
    assert coordinator.can_transition("RUNNING", "WAITING_WORKER")
    assert coordinator.can_transition("WAITING_WORKER", "QUEUED")
    assert coordinator.can_transition("INTERRUPTED", "QUEUED")
    assert coordinator.can_transition("WAITING_GATE", "COMPLETED")
    # النهائية لا تفتح أبدًا
    assert not coordinator.can_transition("COMPLETED", "RUNNING")
    assert not coordinator.can_transition("FAILED", "QUEUED")
    # RUNNING لا يعود للطابور (هو أصلًا يعمل)
    assert not coordinator.can_transition("RUNNING", "QUEUED")


# ---------- تصنيف tick — كل مسار حتمي ----------

def test_classify_terminal_project_states():
    for project_status, expected in (
        ("VERIFIED", "COMPLETED"), ("STOPPED", "STOPPED"),
        ("ESCALATED", "ESCALATED"),
    ):
        out = classify_tick(
            {"action": "none", "reason": "نهائية"},
            project={"status": project_status}, open_gates=[],
        )
        assert out["status"] == expected, project_status
        assert out["terminal"] is True


def test_classify_completed_candidate_waits_for_owner_verify():
    """مرشح (COMPLETED/CANDIDATE) لا يكمل الوظيفة — التحقق للمالك.

    إعادة تشغيل مشروع مرشح تعيد WAITING_GATE لا COMPLETED —
    قناة COMPLETED الوحيدة تحقق المالك (الصدق 012-E).
    """
    out = classify_tick(
        {"action": "none", "reason": "نهائية"},
        project={"status": "COMPLETED", "completion_state": "CANDIDATE"},
        open_gates=[{"kind": "FINAL_VERIFICATION", "status": "PENDING"}],
    )
    assert out["status"] == "WAITING_GATE"
    assert out["waiting_kind"] == "GATE"
    assert out["terminal"] is False
    assert "FINAL_VERIFICATION" in out["waiting_detail"]["gate_kinds"]
    assert "قرار المالك" in out["waiting_detail"]["summary"]


def test_classify_paused_failed_wait_owner():
    out = classify_tick({"action": "paused", "reason": "إيقاف"},
                        project={"status": "PAUSED"}, open_gates=[])
    assert out["status"] == "PAUSED" and out["stop"] \
        and not out["terminal"]

    out = classify_tick({"action": "failed", "reason": "فشل"},
                        project={"status": "DRAFT"}, open_gates=[])
    assert out["status"] == "FAILED" and out["terminal"]

    out = classify_tick(
        {"action": "wait_owner", "reason": "الخطة تنتظر اعتماد المالك"},
        project={"status": "AWAITING_OWNER_APPROVAL"},
        open_gates=[{"kind": "PLAN_APPROVAL", "status": "PENDING"}],
    )
    assert out["status"] == "WAITING_GATE"
    assert out["waiting_kind"] == "GATE"
    assert "PLAN_APPROVAL" in out["waiting_detail"]["gate_kinds"]


def test_classify_provider_gate_is_capability():
    """PROVIDER_ACTION_REQUIRED = مزود غير جاهز — قدرة لا قرار مالك."""
    out = classify_tick(
        {"action": "blocked", "reason": "مزود غير جاهز"},
        project={"status": "BLOCKED"},
        open_gates=[{
            "kind": "PROVIDER_ACTION_REQUIRED", "status": "PENDING",
            "details": {"unready": [{"role": "implementer"}],
                        "required_action": "راجع المزود من الإعدادات"},
        }],
    )
    assert out["status"] == "WAITING_CAPABILITY"
    assert out["waiting_kind"] == "CAPABILITY"
    assert out["waiting_detail"]["unready_roles"] == ["implementer"]
    assert "الإعدادات" in out["waiting_detail"]["owner_action"]


def test_classify_preflight_sandbox_is_worker():
    out = classify_tick(
        {"action": "blocked", "blocked_kind": "preflight",
         "reason": "لا بيئة تنفيذ",
         "preflight": {"blocked": [
             {"capability_id": "sandbox", "status": "NOT_READY",
              "required_environment": "Linux/x86_64 Execution Worker",
              "owner_action": "أضف بيئة ← تحقق ← أعد الفحص"},
         ]}},
        project={"status": "BLOCKED"},
        open_gates=[{"kind": "PREFLIGHT_BLOCKED", "status": "BLOCKED"}],
    )
    assert out["status"] == "WAITING_WORKER"
    assert out["waiting_kind"] == "WORKER"
    detail = out["waiting_detail"]
    assert detail["blocked"][0]["capability_id"] == "sandbox"
    assert detail["required_environment"] == "Linux/x86_64 Execution Worker"
    assert "بلا إعادة اعتماد" in detail["recovery"]


def test_classify_preflight_search_is_capability():
    out = classify_tick(
        {"action": "blocked", "blocked_kind": "preflight",
         "reason": "البحث غير جاهز",
         "preflight": {"blocked": [
             {"capability_id": "web_search", "status": "NOT_READY",
              "owner_action": "جهّز SearXNG/API"},
         ]}},
        project={"status": "BLOCKED"}, open_gates=[],
    )
    assert out["status"] == "WAITING_CAPABILITY"
    assert out["waiting_kind"] == "CAPABILITY"


def test_classify_preflight_mixed_prefers_capability_with_both_visible():
    """اختلاط العامل والقدرة = قدرة (التفصيل يُظهر الاثنين — لا إخفاء)."""
    out = classify_tick(
        {"action": "blocked", "blocked_kind": "preflight",
         "reason": "مختلط",
         "preflight": {"blocked": [
             {"capability_id": "web_search", "status": "NOT_READY"},
             {"capability_id": "sandbox", "status": "NOT_READY",
              "required_environment": "عامل Linux"},
         ]}},
        project={"status": "BLOCKED"}, open_gates=[],
    )
    assert out["status"] == "WAITING_CAPABILITY"
    kinds = {b["capability_id"]
             for b in out["waiting_detail"]["blocked"]}
    assert kinds == {"web_search", "sandbox"}


def test_classify_decision_gate_is_gate():
    out = classify_tick(
        {"action": "blocked", "reason": "استنفدت المحاولات"},
        project={"status": "BLOCKED"},
        open_gates=[{"kind": "PLAN_REVISION_APPROVAL",
                     "status": "PENDING"}],
    )
    assert out["status"] == "WAITING_GATE"
    assert out["waiting_kind"] == "GATE"


def test_classify_continue_variants():
    base = {"action": "continue", "reason": "استمرار"}
    out = classify_tick(base, project={"status": "RUNNING"},
                        open_gates=[])
    assert out["status"] == "RUNNING" and not out["stop"]

    out = classify_tick(base, project={"status": "REVISING"},
                        open_gates=[])
    assert out["status"] == "REVISING"

    out = classify_tick({"action": "continue",
                         "reason": "إعادة محاولة الخطوة"},
                        project={"status": "RUNNING"}, open_gates=[],
                        retry_requested=True)
    assert out["status"] == "RETRYING"


# ---------- الدور الحالي — من الحالة الدائمة ----------

def test_current_role_of():
    assert coordinator.current_role_of(
        {"status": "RUNNING"},
        {"status": "RUNNING", "agent_role": "implementer"},
    ) == "implementer"
    assert coordinator.current_role_of(
        {"status": "PLANNING"}, None) == "thinker"
    assert coordinator.current_role_of(
        {"status": "REVISING"}, None) == "thinker"
    assert coordinator.current_role_of(
        {"status": "READY"}, None) == "coordinator"


def test_waiting_unblock_path_names_action():
    for kind in ("CAPABILITY", "WORKER", "GATE"):
        path = coordinator.waiting_unblock_path(kind)
        assert path and len(path) > 10, kind
