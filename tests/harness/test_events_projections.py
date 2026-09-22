"""اختبارات المفردة والإسقاطات (012-D) — حتمية خالصة من الأحداث.

المفردة القانونية مكتملة (كل نوع دائم له اسم canonical)، والإسقاط
يعيد نفس النتيجة لنفس الأحداث دائمًا — وهو ما يبني عليه خط الزمن
والسلسلة في الواجهة.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from harness import events as hv  # noqa: E402
from harness import projections  # noqa: E402
from workflow.models import PROJECT_EVENT_KINDS  # noqa: E402


# ---------- اكتمال المفردة ----------

def test_every_project_event_kind_has_canonical_name():
    """كل نوع دائم معلن له اسم قانوني — لا نوع يتسرب بلا مفردة."""
    missing = [kind for kind in PROJECT_EVENT_KINDS
               if kind not in hv.CANONICAL_MAP]
    assert missing == [], missing


def test_job_event_kinds_all_canonical_and_declared():
    for kind in hv.JOB_EVENT_KINDS:
        assert kind in hv.CANONICAL_MAP, kind
        assert kind in PROJECT_EVENT_KINDS, kind
    assert hv.canonical("JOB_WAITING") == "job/waiting"
    assert hv.canonical("SOMETHING_ELSE") == "SOMETHING_ELSE"  # مرور صادق


def test_chain_stages_order_fixed():
    assert hv.CHAIN_STAGES == (
        "OBJECTIVE", "PLAN", "APPROVAL", "PREFLIGHT", "EXECUTION",
        "EVIDENCE", "AUDIT", "VERIFICATION",
    )


def test_every_stage_has_marks():
    for stage in hv.CHAIN_STAGES:
        assert stage in hv._STAGE_OF_KIND.values() or \
            stage in hv._STAGE_DONE_MARKS, stage


# ---------- حالة المرحلة — الأولوية الحتمية ----------

def test_stage_status_priority():
    kinds = {"project/created"}
    assert hv.stage_status("OBJECTIVE", kinds) == "DONE"
    assert hv.stage_status("PLAN", kinds) == "PENDING"

    # الفشل الحاسم يغلب الانتظار، والإنجاز يغلب الاثنين
    assert hv.stage_status(
        "EXECUTION", {"execution/failed"}) == "ACTIVE"  # فشل عابر ليس فشل مرحلة
    assert hv.stage_status(
        "EXECUTION", {"job/failed"}) == "FAILED"
    assert hv.stage_status(
        "EXECUTION", {"job/failed", "job/waiting"}) == "FAILED"
    assert hv.stage_status(
        "EXECUTION",
        {"job/failed", "project/completion_candidate"}) == "DONE"
    assert hv.stage_status(
        "EXECUTION", {"job/waiting"}) == "WAITING"
    assert hv.stage_status(
        "VERIFICATION", {"project/completion_candidate"}) == "WAITING"
    assert hv.stage_status(
        "VERIFICATION", {"project/completion_candidate",
                         "project/verified"}) == "DONE"


# ---------- خط الزمن ----------

def _event(eid, kind, payload=None, at="2026-01-01T00:00:00"):
    return {"id": eid, "kind": kind, "payload": payload or {},
            "created_at": at}


def test_project_timeline_items_and_titles():
    timeline = projections.project_timeline([
        _event(1, "PROJECT_CREATED", {"objective": "هدف"}),
        _event(2, "PLAN_APPROVED"),
        _event(3, "JOB_WAITING", {"waiting_kind": "WORKER",
                                  "summary": "لا بيئة معزولة"}),
        _event(4, "UNDOCUMENTED_KIND"),
    ])
    items = timeline["items"]
    assert [i["canonical"] for i in items] == [
        "project/created", "plan/approved", "job/waiting",
        "UNDOCUMENTED_KIND",
    ]
    assert items[0]["actor"] == "owner"
    assert items[0]["title"] == "إنشاء المشروع"
    assert items[2]["waiting_kind"] == "WORKER"
    assert items[2]["detail"] == "لا بيئة معزولة"
    # غير الموثق يمر كما هو — لا حذف ولا تزيين
    assert items[3]["canonical"] == "UNDOCUMENTED_KIND"
    assert items[3]["actor"] == "system"


def test_acceptance_chain_full_path_done():
    chain = projections.acceptance_chain([
        _event(1, "PROJECT_CREATED"),
        _event(2, "PLAN_CREATED"),
        _event(3, "PLAN_APPROVAL_REQUIRED"),
        _event(4, "PLAN_APPROVED"),
        _event(5, "PREFLIGHT_PASS"),
        _event(6, "JOB_STARTED"),
        _event(7, "EXECUTION_COMPLETED"),
        _event(8, "EVIDENCE_CREATED"),
        _event(9, "AUDIT_COMPLETED"),
        _event(10, "PROJECT_COMPLETION_CANDIDATE"),
        _event(11, "PROJECT_VERIFIED"),
    ])
    by_stage = {s["stage"]: s["status"] for s in chain["stages"]}
    assert by_stage == {
        "OBJECTIVE": "DONE", "PLAN": "DONE", "APPROVAL": "DONE",
        "PREFLIGHT": "DONE", "EXECUTION": "DONE", "EVIDENCE": "DONE",
        "AUDIT": "DONE", "VERIFICATION": "DONE",
    }
    assert chain["complete"] is True


def test_acceptance_chain_honest_stop_with_reason():
    chain = projections.acceptance_chain([
        _event(1, "PROJECT_CREATED"),
        _event(2, "PLAN_CREATED"),
        _event(3, "PLAN_APPROVED"),
        _event(4, "PREFLIGHT_BLOCKED", {"blocked": [
            {"capability_id": "sandbox", "reason": "لا بيئة"}]}),
        _event(5, "JOB_WAITING", {"waiting_kind": "WORKER",
                                  "summary": "لا بيئة معزولة جاهزة"}),
    ])
    by_stage = {s["stage"]: s for s in chain["stages"]}
    assert by_stage["PREFLIGHT"]["status"] == "WAITING"
    assert by_stage["EXECUTION"]["status"] == "WAITING"
    # سبب الانتظار الحرفي يصل — لا إعادة صياغة تخفيه
    assert "لا بيئة" in by_stage["EXECUTION"]["waiting_reason"]
    assert chain["complete"] is False


def test_transient_failure_does_not_fail_stage_forever():
    """فشل خطوة أُعيدت ونجحت لا يسمم المرحلة — الإنجاز يغلب."""
    chain = projections.acceptance_chain([
        _event(1, "PROJECT_CREATED"),
        _event(2, "PLAN_APPROVED"),
        _event(3, "PREFLIGHT_PASS"),
        _event(4, "EXECUTION_FAILED", {"reason": "عابر"}),
        _event(5, "RETRY_REQUESTED"),
        _event(6, "EVIDENCE_CREATED"),
        _event(7, "PROJECT_COMPLETION_CANDIDATE"),
    ])
    by_stage = {s["stage"]: s["status"] for s in chain["stages"]}
    assert by_stage["EXECUTION"] == "DONE"
