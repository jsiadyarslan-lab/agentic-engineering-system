"""اختبارات وحدة الإيقاف (الأمر 004) — المتحكم والإيصالات واللقطة.

المتحكم يجب أن يكون آمنًا خيطيًا (سباقات الطلب المتزامن)، idempotent
(طلبان = إيصال واحد)، واللقطة fail-closed (مخطط مجهول أو حقول فاسدة
= رفض صريح لا استئناف أعمى).
"""

from __future__ import annotations

import json
import threading

import pytest

from core.stop_controller import (
    SNAPSHOT_NAME,
    SNAPSHOT_SCHEMA,
    CycleStopSignal,
    StopController,
    StopReceipt,
    build_stop_snapshot,
    load_resume_point,
    plan_signed_at,
    snapshot_summary,
)


# ------------------------------------------------------------------ #
# المتحكم — العلم الذرّي والإيصالات
# ------------------------------------------------------------------ #


def test_request_stop_creates_receipt():
    controller = StopController()
    receipt = controller.request_stop("cycle-x", by="owner", reason="اختبار")
    assert receipt.cycle_id == "cycle-x"
    assert receipt.requested_by == "owner"
    assert receipt.reason == "اختبار"
    assert receipt.at  # طابع زمني ISO موجود
    assert controller.is_stopped("cycle-x")
    assert not controller.is_stopped("cycle-y")


def test_request_stop_is_idempotent():
    """طلبان متتاليان = الإيصال نفسه — لا إيصالان لدورة واحدة."""
    controller = StopController()
    first = controller.request_stop("cycle-x", by="owner", reason="أول")
    second = controller.request_stop("cycle-x", by="owner", reason="ثانٍ")
    assert first is second  # الكائن نفسه — الطلب الثاني لا يُنشئ شيئًا


def test_concurrent_stop_requests_merge_into_one_receipt():
    """8 خيوط تطلب الإيقاف معًا — إيصال واحد فقط (حماية السباقات)."""
    controller = StopController()
    receipts: list[StopReceipt] = []
    barrier = threading.Barrier(8)

    def request():
        barrier.wait()  # كل الخيوط تضرب في اللحظة نفسها
        receipts.append(
            controller.request_stop("cycle-race", by="owner", reason="")
        )

    threads = [threading.Thread(target=request) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(receipts) == 8
    assert all(r is receipts[0] for r in receipts)  # إيصال واحد بعينه


def test_clear_resets_the_flag():
    controller = StopController()
    controller.request_stop("cycle-x", by="owner")
    controller.clear("cycle-x")
    assert not controller.is_stopped("cycle-x")
    assert controller.receipt("cycle-x") is None


def test_checker_for_closure_tracks_the_flag():
    controller = StopController()
    check = controller.checker_for("cycle-x")
    assert check() is False
    controller.request_stop("cycle-x", by="owner")
    assert check() is True  # الإغلاق يرى العلم لحظيًا (للمنفذ الحي)


# ------------------------------------------------------------------ #
# اللقطة — البناء والتحميل fail-closed
# ------------------------------------------------------------------ #


def _snapshot(**overrides):
    base = dict(
        cycle_id="cycle-abc",
        goal="هدف الاختبار",
        state_at_stop="EXECUTING",
        phase="before_task:T2",
        plan_dump={"tasks": [], "risks": [], "assumptions": []},
        plan_signed=True,
        outcomes=[{"task_id": "T1", "attempts": 1, "evidenced": True,
                   "execution_failed": False, "artifacts": ["a.txt"]}],
        review_cycles=1,
        review_issues=["ملاحظة"],
        evidence_refs=["sha256:x:a.txt"],
        artifacts=["a.txt"],
        events_count=12,
        receipt=StopReceipt("cycle-abc", "owner", "2026-01-01T00:00:00+00:00",
                            "سبب"),
    )
    base.update(overrides)
    return build_stop_snapshot(**base)


def test_build_snapshot_round_trips_through_loader():
    snapshot = _snapshot()
    assert snapshot["schema"] == SNAPSHOT_SCHEMA
    point = load_resume_point(snapshot)
    assert point.stopped_cycle_id == "cycle-abc"
    assert point.goal == "هدف الاختبار"
    assert point.plan_signed is True
    assert point.outcomes[0]["task_id"] == "T1"
    assert point.review_issues == ["ملاحظة"]


def test_loader_rejects_unknown_schema():
    snapshot = _snapshot()
    snapshot["schema"] = "stop-snapshot/999"
    with pytest.raises(ValueError, match="مخطط"):
        load_resume_point(snapshot)


def test_loader_rejects_missing_goal_or_id():
    snapshot = _snapshot()
    snapshot["goal"] = "   "
    with pytest.raises(ValueError, match="هدف"):
        load_resume_point(snapshot)
    snapshot = _snapshot()
    snapshot["cycle_id"] = ""
    with pytest.raises(ValueError, match="معرف"):
        load_resume_point(snapshot)


def test_loader_rejects_non_dict():
    with pytest.raises(ValueError):
        load_resume_point(["ليست", "لقطة"])


def test_plan_signed_inferred_from_state_when_flag_missing():
    """الخطة الموقّعة تُستنتج من حالة الإيقاف حتى لو غاب العلم الصريح."""
    snapshot = _snapshot()
    del snapshot["plan_signed"]
    assert load_resume_point(snapshot).plan_signed is True
    snapshot2 = _snapshot(state_at_stop="UNDER_REVIEW")
    del snapshot2["plan_signed"]
    assert load_resume_point(snapshot2).plan_signed is False


def test_plan_signed_at_helper():
    assert plan_signed_at("EXECUTING", True) is True
    assert plan_signed_at("UNDER_REVIEW", True) is False
    assert plan_signed_at("EXECUTING", False) is False


def test_snapshot_summary_excludes_full_plan():
    snapshot = _snapshot()
    summary = snapshot_summary(snapshot)
    assert "plan" not in summary
    assert summary["state_at_stop"] == "EXECUTING"
    assert summary["stopped_by"] == "owner"


def test_stop_signal_carries_step():
    signal = CycleStopSignal("before_task:T3")
    assert signal.at_step == "before_task:T3"
    assert "before_task:T3" in str(signal)


def test_snapshot_name_constant():
    """اسم ملف اللقطة ثابت ومعلن — عقد القراءة من الـAPI والاختبارات."""
    assert SNAPSHOT_NAME == "stop_snapshot.json"
    assert json.dumps({"schema": SNAPSHOT_SCHEMA})  # قابل للتسلسل
