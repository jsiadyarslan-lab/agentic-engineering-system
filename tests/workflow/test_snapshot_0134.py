"""اختبارات اللقطة القانونية (013.4 §8) — المصدر الوحيد للواجهة.

اللقطة تحمل كل ما تحتاجه الواجهة: الحالة/المرحلة/التقدم الحقيقي/
ما الذي يُنتظر/سبب الحجب/الدور النشط/الأفعال المتاحة — ولا مكوّن
يشتق حالة سير العمل من مصدر آخر.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from workflow import service  # noqa: E402
from workflow.snapshot import runtime_snapshot  # noqa: E402


def _approved(wf_env):
    engine = wf_env["build_engine"]()
    project = engine.create_project("مشروع لقطة", "هدف اختبار اللقطة")
    engine.generate_plan(project["id"])
    engine.approve_plan(project["id"], approved=True)
    return engine, project


def test_snapshot_has_the_full_contract(wf_env):
    """(§8) كل حقول العقد موجودة — لا حقل غائب يضطر الواجهة للاشتقاق."""
    env = wf_env
    engine = wf_env["build_engine"]()
    project = engine.create_project("مشروع عقد", "هدف")
    snap = runtime_snapshot(env["sessions"], project["id"])

    for field in (
        "project_id", "job", "stage", "status", "progress",
        "started_at", "updated_at", "heartbeat_at", "elapsed_s",
        "waiting_for", "blocking_reason", "planning", "activity",
        "environment", "worker", "last_event", "recent_events",
        "available_actions", "last_error",
    ):
        assert field in snap, f"حقل العقد §8 مفقود: {field}"


def test_snapshot_waiting_for_owner_approval(wf_env):
    """خطة تنتظر الاعتماد ← waiting_for=owner_approval معلنة حرفيًا."""
    env = wf_env
    engine = wf_env["build_engine"]()
    project = engine.create_project("انتظار اعتماد", "هدف")
    engine.generate_plan(project["id"])
    snap = runtime_snapshot(env["sessions"], project["id"])
    assert snap["status"] == "AWAITING_OWNER_APPROVAL"
    assert snap["waiting_for"]["kind"] == "owner_approval"
    assert snap["stage"] == "APPROVAL"
    assert "run" in snap["available_actions"]


def test_snapshot_waiting_for_model_during_planning(wf_env):
    """(§3) أثناء التوليد: waiting_for يسمي المزود/النموذج/الطلب."""
    env = wf_env
    engine = wf_env["build_engine"]()
    project = engine.create_project("تخطيط حي", "هدف")

    release = __import__("threading").Event()
    original_generate = engine._build_planner().generate
    import json as _json

    from tests.workflow.plans import SCRIPTED_PLAN

    class SlowPlanner:
        def generate(self, *args, **kwargs):
            release.wait(timeout=10)
            return _json.loads(_json.dumps(SCRIPTED_PLAN))

    engine._build_planner = lambda: SlowPlanner()  # type: ignore
    engine.start_plan_generation(project["id"])

    snap = runtime_snapshot(env["sessions"], project["id"])
    assert snap["status"] == "PLANNING"
    assert snap["waiting_for"]["kind"] == "model"
    assert snap["planning"]["active"] is True
    assert snap["planning"]["detail"]["request_id"].startswith("plan-")

    release.set()
    from workflow import planning_runtime

    planning_runtime.wait_for_planning(
        env["sessions"], project["id"], timeout=10.0
    )


def test_snapshot_progress_is_real_not_invented(wf_env):
    """(§50) التقدم من الخطوات الفعلية — لا نسب مخترعة."""
    env = wf_env
    engine, project = _approved(env)
    result = engine.run(project["id"])
    assert result["action"] in ("none", "wait_owner")

    snap = runtime_snapshot(env["sessions"], project["id"])
    assert snap["progress"]["steps_total"] >= 1
    assert snap["progress"]["steps_completed"] == \
        snap["progress"]["steps_total"]
    assert snap["progress"]["percent"] == 100.0


def test_snapshot_actions_follow_state(wf_env):
    """(§11) الأفعال المتاحة مشتقة من الحالة القانونية حصرًا."""
    env = wf_env
    engine = wf_env["build_engine"]()
    project = engine.create_project("أفعال", "هدف")
    snap = runtime_snapshot(env["sessions"], project["id"])
    assert "pause" not in snap["available_actions"]  # DRAFT لا يُوقف
    assert "duplicate" in snap["available_actions"]
    assert "archive" in snap["available_actions"]


def test_snapshot_blocking_reason_is_literal(wf_env):
    """سبب الحجب حرفي من الحالة — لا نص عام ملفق."""
    env = wf_env
    engine = wf_env["build_engine"]()
    project = engine.create_project("حجب", "هدف")
    service.update_project(
        env["sessions"], project["id"], status="PAUSED",
        last_error="سبب حرفي محدد للاختبار",
    )
    snap = runtime_snapshot(env["sessions"], project["id"])
    assert snap["blocking_reason"] == "سبب حرفي محدد للاختبار"
    assert "resume" in snap["available_actions"]
