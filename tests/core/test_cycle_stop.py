"""اختبارات الإيقاف الفوري للدورة (الأمر 004) — السيناريوهات الأربعة.

التغطية المطلوبة بالأمر حرفيًا:
1. إيقاف أثناء التفكير (المفكر يعمل والمدقق لم يُستدعَ بعد).
2. إيقاف أثناء التنفيذ (المهام اللاحقة لا تُنفذ — عدّاد المنفذ دليل).
3. إيقاف أثناء التحقق (بين تحقق مهمة والتالية).
4. إعادة التشغيل بعد الإيقاف (الاستئناف من اللقطة) — بخطة موقّعة
   وبلا خطة، مع إثبات أن الموقوفة تبقى مجمّدة.

كل الإيقاف عبر خيط آخر يطلب أثناء نوم دور بطيء — نفس سباق الإنتاج،
لا محاكاة مبسطة.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from core.roles import RoleType
from core.state import PlanState, StateTransitionError
from core.stop_controller import StopController
from core.wiring import build_mock_orchestrator
from substrate.factory import substrate_available, substrate_failure_reason

pytestmark = pytest.mark.skipif(
    not substrate_available(),
    reason=(
        "لا ركيزة عزل متاحة على هذا المضيف — " + substrate_failure_reason()
    ),
)


def _wait_for(predicate, timeout=20.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class _SlowCounting:
    """غلاف دور: عدّاد استدعاءات + نوم مضبوط يخلق نافذة سباق حقيقية."""

    def __init__(self, inner, *, delay=0.0):
        self._inner = inner
        self.delay = delay
        self.calls: list = []

    def run(self, request):
        self.calls.append(request)
        if self.delay:
            time.sleep(self.delay)
        return self._inner.run(request)

    @property
    def count(self):
        return len(self.calls)


def _cycle_id_of(events):
    for e in events:
        if e.get("cycle_id"):
            return e["cycle_id"]
    return None


def _run_in_thread(orchestrator, **kwargs):
    """تشغيل الدورة في خيط — يعيد (صندوق النتيجة، الخيط، الأحداث)."""
    events: list[dict] = []
    box: dict = {}

    def run():
        box["result"] = orchestrator.run_cycle(
            kwargs.pop("goal", "هدف اختبار الإيقاف"),
            on_event=events.append,
            **kwargs,
        )

    thread = threading.Thread(target=run)
    thread.start()
    return box, thread, events


# ------------------------------------------------------------------ #
# 1) إيقاف أثناء التفكير
# ------------------------------------------------------------------ #


def test_stop_during_thinking(tmp_path):
    thinker = _SlowCounting(__import__("roles.thinker", fromlist=["Thinker"]).Thinker(), delay=1.5)
    reviewer = _SlowCounting(__import__("roles.reviewer", fromlist=["Reviewer"]).Reviewer())
    orchestrator = build_mock_orchestrator(
        {RoleType.THINKER: thinker, RoleType.REVIEWER: reviewer}
    )
    box, thread, events = _run_in_thread(
        orchestrator, workspace_root=tmp_path, cycle_id="stop-think-1"
    )
    assert _wait_for(lambda: _cycle_id_of(events) is not None)

    outcome = orchestrator.request_stop("stop-think-1", by="owner", reason="اختبار")
    assert outcome["accepted"] is True
    assert outcome["status"] == "STOPPING"
    assert outcome["receipt"]["requested_by"] == "owner"
    assert outcome["receipt"]["reason"] == "اختبار"

    thread.join(timeout=15)
    result = box["result"]
    assert result.final_state is PlanState.STOPPED
    assert result.state_history == ["DRAFT", "UNDER_REVIEW", "STOPPING", "STOPPED"]
    # المدقق لم يُستدعَ أبدًا — أُوقفنا بين المفكر والمدقق
    assert reviewer.count == 0

    stop_events = [e for e in result.events if e["kind"] == "cycle.stopped"]
    assert len(stop_events) == 1
    details = stop_events[0]["details"]
    assert details["stopped_by"] == "owner"
    assert details["honored_at_step"] == "after_thinker"
    assert details["state_at_stop"] == "UNDER_REVIEW"
    assert details["resumable"] is True
    assert len(details["snapshot_sha256"]) == 64

    # اللقطة: خطة موجودة لكنها غير موقّعة (قبل موافقة المدقق)
    snapshot = json.loads(
        (tmp_path / "stop_snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["plan"] is not None
    assert snapshot["plan_signed"] is False
    assert snapshot["review_issues"] == []

    # cycle_done الصادق: لا can_verify لموقوفة
    done = [e for e in result.events if e["kind"] == "cycle_done"][-1]
    assert done["details"]["final_state"] == "STOPPED"
    assert done["details"]["can_verify"] is False


# ------------------------------------------------------------------ #
# 2) إيقاف أثناء التنفيذ
# ------------------------------------------------------------------ #


def test_stop_during_execution(tmp_path):
    implementer = _SlowCounting(
        __import__("roles.implementer", fromlist=["Implementer"]).Implementer(),
        delay=1.2,
    )
    orchestrator = build_mock_orchestrator({RoleType.IMPLEMENTER: implementer})
    box, thread, events = _run_in_thread(
        orchestrator, workspace_root=tmp_path, cycle_id="stop-exec-1"
    )
    # انتظر إثبات T1 (محاولتها الثانية) ثم اطلق أثناء نوم محاولة T2 الأولى
    assert _wait_for(
        lambda: any(
            e["kind"] == "task_verification"
            and e["details"].get("task_id") == "T1"
            and e["details"].get("verdict") == "evidenced"
            for e in events
        )
    )
    time.sleep(0.3)  # داخل نوم منفذ T2 (محاولتها الأولى) الآن
    outcome = orchestrator.request_stop("stop-exec-1", by="owner", reason="")
    assert outcome["accepted"] is True

    thread.join(timeout=25)
    result = box["result"]
    assert result.final_state is PlanState.STOPPED
    # T1 (محاولتان) + T2 (محاولتها الأولى) — T3 لم تُمس إطلاقًا
    assert implementer.count == 3
    # التحقق الكلي لم يحدث
    assert not any(e["kind"] == "verification_rollup" for e in result.events)

    snapshot = json.loads(
        (tmp_path / "stop_snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["plan_signed"] is True
    assert snapshot["state_at_stop"] == "EXECUTING"
    # المخرجات المسجلة: T1 فقط (المهمة الجارية T2 لا نتيجة لها — تعاد من
    # نقطة نظيفة عند الاستئناف، موثق في اللقطة)
    assert [o["task_id"] for o in snapshot["outcomes"]] == ["T1"]
    assert snapshot["outcomes"][0]["evidenced"] is True

    stop_events = [e for e in result.events if e["kind"] == "cycle.stopped"]
    assert (
        stop_events[0]["details"]["honored_at_step"] == "after_execution:T2"
    )


# ------------------------------------------------------------------ #
# 3) إيقاف أثناء التحقق
# ------------------------------------------------------------------ #


def test_stop_during_verification(tmp_path):
    verifier = _SlowCounting(
        __import__("roles.verifier", fromlist=["Verifier"]).Verifier(), delay=1.5
    )
    orchestrator = build_mock_orchestrator({RoleType.VERIFIER: verifier})
    box, thread, events = _run_in_thread(
        orchestrator, workspace_root=tmp_path, cycle_id="stop-verify-1"
    )
    # انتظر تنفيذ T1 (تحقق T1 نائم الآن) ثم اطلب الإيقاف
    assert _wait_for(
        lambda: any(
            e["kind"] == "task_execution" and e["details"].get("task_id") == "T1"
            for e in events
        )
    )
    time.sleep(0.3)  # داخل نوم تحقق T1
    assert orchestrator.request_stop("stop-verify-1", by="owner")["accepted"]

    thread.join(timeout=20)
    result = box["result"]
    assert result.final_state is PlanState.STOPPED
    # تحقق T1 اكتمل (كان جاريًا — لا قتل خيوط)، ثم أُوقفنا قبل T2
    assert verifier.count == 1
    implementer_calls = [
        e for e in result.events if e["kind"] == "task_execution"
    ]
    assert [e["details"]["task_id"] for e in implementer_calls] == ["T1"]

    stop_events = [e for e in result.events if e["kind"] == "cycle.stopped"]
    assert (
        stop_events[0]["details"]["honored_at_step"] == "before_attempt:2:T1"
    )


# ------------------------------------------------------------------ #
# الرفض الصادق: دورة منتهية/مجهولة + الحالة
# ------------------------------------------------------------------ #


def test_stop_request_rejected_for_finished_and_unknown(tmp_path):
    orchestrator = build_mock_orchestrator()
    result = orchestrator.run_cycle(
        "دورة كاملة حتى النهاية", workspace_root=tmp_path
    )
    assert result.final_state is PlanState.EVIDENCED

    outcome = orchestrator.request_stop(result.cycle_id, by="owner")
    assert outcome["accepted"] is False
    assert outcome["status"] == "finished"
    assert outcome["final_state"] == "EVIDENCED"

    unknown = orchestrator.request_stop("cycle-nonexistent", by="owner")
    assert unknown == {"accepted": False, "status": "unknown"}


def test_cycle_status_reports_running_and_receipt(tmp_path):
    orchestrator = build_mock_orchestrator()
    result = orchestrator.run_cycle("دورة للحالة", workspace_root=tmp_path)
    status = orchestrator.cycle_status(result.cycle_id)
    assert status == {
        "cycle_id": result.cycle_id,
        "state": "EVIDENCED",
        "running": False,
        "stop_requested": False,
        "stop_receipt": None,
    }
    assert orchestrator.cycle_status("cycle-unknown") is None


def test_stopped_cycle_cannot_be_verified(tmp_path):
    """لا VERIFIED لموقوفة — القاعدة الذهبية تُفرض عبر جدول الانتقالات."""
    thinker = _SlowCounting(
        __import__("roles.thinker", fromlist=["Thinker"]).Thinker(), delay=1.2
    )
    orchestrator = build_mock_orchestrator({RoleType.THINKER: thinker})
    box, thread, events = _run_in_thread(
        orchestrator, workspace_root=tmp_path, cycle_id="stop-nv-1"
    )
    assert _wait_for(lambda: _cycle_id_of(events) is not None)
    orchestrator.request_stop("stop-nv-1", by="owner")
    thread.join(timeout=15)
    assert box["result"].final_state is PlanState.STOPPED
    with pytest.raises(StateTransitionError):
        orchestrator.user_verifies("stop-nv-1")


# ------------------------------------------------------------------ #
# 4) إعادة التشغيل بعد الإيقاف — الاستئناف من اللقطة
# ------------------------------------------------------------------ #


def _stop_cycle_mid_execution(tmp_path, cycle_id):
    """إيقاف دورة أثناء T2 — يعيد (النتيجة، اللقطة، عدّادات الأدوار)."""
    roles = {
        RoleType.THINKER: _SlowCounting(
            __import__("roles.thinker", fromlist=["Thinker"]).Thinker()
        ),
        RoleType.REVIEWER: _SlowCounting(
            __import__("roles.reviewer", fromlist=["Reviewer"]).Reviewer()
        ),
        RoleType.IMPLEMENTER: _SlowCounting(
            __import__("roles.implementer", fromlist=["Implementer"]).Implementer(),
            delay=1.2,
        ),
        RoleType.VERIFIER: _SlowCounting(
            __import__("roles.verifier", fromlist=["Verifier"]).Verifier()
        ),
    }
    orchestrator = build_mock_orchestrator(roles)
    box, thread, events = _run_in_thread(
        orchestrator, workspace_root=tmp_path, cycle_id=cycle_id
    )
    assert _wait_for(
        lambda: any(
            e["kind"] == "task_verification"
            and e["details"].get("task_id") == "T1"
            and e["details"].get("verdict") == "evidenced"
            for e in events
        )
    )
    time.sleep(0.3)
    assert orchestrator.request_stop(cycle_id, by="owner")["accepted"]
    thread.join(timeout=25)
    snapshot = json.loads(
        (tmp_path / "stop_snapshot.json").read_text(encoding="utf-8")
    )
    return box["result"], snapshot, roles, orchestrator


def test_resume_with_signed_plan_skips_think_review_and_evidenced(tmp_path):
    result, snapshot, roles, stopped_orchestrator = _stop_cycle_mid_execution(
        tmp_path, "stop-res-1"
    )
    assert result.final_state is PlanState.STOPPED
    thinker_calls_before = roles[RoleType.THINKER].count
    reviewer_calls_before = roles[RoleType.REVIEWER].count
    implementer_calls_before = roles[RoleType.IMPLEMENTER].count

    orchestrator = build_mock_orchestrator(roles)
    resumed = orchestrator.run_cycle(
        "هدف الاستئناف",
        workspace_root=tmp_path,
        cycle_id="resume-1",
        resume_from=snapshot,
    )

    assert resumed.final_state is PlanState.EVIDENCED
    assert resumed.resumed_from == "stop-res-1"
    # المرحلتان 1 تُخطيتا: المفكر والمدقق لم يُستدعيا مرة إضافية
    assert roles[RoleType.THINKER].count == thinker_calls_before
    assert roles[RoleType.REVIEWER].count == reviewer_calls_before
    # T1 المثبتة لا تُعاد إطلاقًا — الطلبات الجديدة كلها لT2/T3 فقط
    new_task_ids = [
        r.task.id
        for r in roles[RoleType.IMPLEMENTER].calls[implementer_calls_before:]
    ]
    assert set(new_task_ids) == {"T2", "T3"}
    # كل منهما بمحاولتين (المحاولة الأولى لا سجل تشغيل — حلقة الإصلاح)
    assert roles[RoleType.IMPLEMENTER].count == implementer_calls_before + 4
    # التاريخ يبدأ من APPROVED (نقطة الاستئناف المعلنة)
    assert resumed.state_history[0] == "APPROVED"
    resumed_events = [e for e in resumed.events if e["kind"] == "cycle.resumed"]
    assert len(resumed_events) == 1
    assert resumed_events[0]["details"]["from_cycle_id"] == "stop-res-1"
    assert resumed_events[0]["details"]["seeded_evidenced"] == ["T1"]
    # النتائج: الثلاث مهام مثبتة (T1 من البذر + T2/T3 من الجولة)
    evidenced = {t.task_id for t in resumed.tasks if t.evidenced}
    assert evidenced == {"T1", "T2", "T3"}
    # الموقوفة بقيت موقوفة — لا إحياء
    assert stopped_orchestrator.cycle_status("stop-res-1")["state"] == "STOPPED"


def test_resume_without_plan_restarts_thinking(tmp_path):
    thinker = _SlowCounting(
        __import__("roles.thinker", fromlist=["Thinker"]).Thinker(), delay=1.5
    )
    orchestrator = build_mock_orchestrator({RoleType.THINKER: thinker})
    box, thread, events = _run_in_thread(
        orchestrator, workspace_root=tmp_path, cycle_id="stop-rt-1"
    )
    assert _wait_for(lambda: _cycle_id_of(events) is not None)
    orchestrator.request_stop("stop-rt-1", by="owner")
    thread.join(timeout=15)
    snapshot = json.loads(
        (tmp_path / "stop_snapshot.json").read_text(encoding="utf-8")
    )
    assert snapshot["plan_signed"] is False

    fresh = build_mock_orchestrator()
    resumed = fresh.run_cycle(
        "هدف استئناف بلا خطة",
        workspace_root=tmp_path,
        cycle_id="resume-rt-1",
        resume_from=snapshot,
    )
    assert resumed.final_state is PlanState.EVIDENCED
    assert resumed.resumed_from == "stop-rt-1"
    assert resumed.state_history[0] == "DRAFT"  # تفكير من جديد


def test_resume_rejects_corrupt_snapshot(tmp_path):
    orchestrator = build_mock_orchestrator()
    with pytest.raises(ValueError):
        orchestrator.run_cycle(
            "هدف",
            workspace_root=tmp_path,
            resume_from={"schema": "stop-snapshot/999", "cycle_id": "x"},
        )


def test_double_stop_request_idempotent_during_run(tmp_path):
    """طلبا إيقاف متتاليان أثناء دورة — إيصال واحد، والدورة تتوقف مرة."""
    thinker = _SlowCounting(
        __import__("roles.thinker", fromlist=["Thinker"]).Thinker(), delay=1.5
    )
    orchestrator = build_mock_orchestrator({RoleType.THINKER: thinker})
    box, thread, events = _run_in_thread(
        orchestrator, workspace_root=tmp_path, cycle_id="stop-dbl-1"
    )
    assert _wait_for(lambda: _cycle_id_of(events) is not None)
    first = orchestrator.request_stop("stop-dbl-1", by="owner", reason="الأول")
    second = orchestrator.request_stop("stop-dbl-1", by="owner", reason="الثاني")
    assert first["receipt"] == second["receipt"]  # إيصال واحد بعينه
    thread.join(timeout=15)
    assert box["result"].final_state is PlanState.STOPPED
