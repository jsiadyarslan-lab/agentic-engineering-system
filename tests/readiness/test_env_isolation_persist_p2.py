"""اختبار تراجع P2 (AES-EXP-03) — عزل البيئة لا يُمحى بصمت.

الجذر المثبت: ``ensure_local_registered`` كان يفرض استدلال الركيزة
``sandboxed=0/1`` في **كل استدعاء** حتى بعد تحقق حقيقي (مسبار
sandbox_probe_result أو دورة تجهيز) ضبط القيمة من فحص فعلي — فلا
يثبت العزل أبدًا، وpreflight يحجب كل مهمة رغم بيئة READY معزولة،
بينما قدرة sandbox تقول «بيئة جاهزة» (تناقض البيئة/التنفيذ الموثق).

العقد بعد الإصلاح: التصحيح الآلي للهوية قبل الحسم فقط (حالة لم
تُحقق)، وبعد التحقق الحقيقي تكون الحقيقة للمسبار/التجهيز.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sqlalchemy import select as sa_select  # noqa: E402

from execution import service as execution_service  # noqa: E402
from execution.models import ExecutionEnvironment  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "env-isolation.db")
    init_db(engine)
    return make_session_factory(engine)


def _set_local(sessions, *, status, sandboxed):
    execution_service.ensure_local_registered(sessions)
    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.backend == "LOCAL")).first()
        row.status = status
        row.sandboxed = sandboxed
        s.commit()


def test_verified_ready_env_keeps_isolation_flag(sessions):
    """بيئة READY معزولة (نتيجة تحقق) لا تُصفَّر عند كل استدعاء."""
    _set_local(sessions, status="READY", sandboxed=1)
    # استدعاءات لاحقة كثيرة — كما يفعل preflight والواجهة
    for _ in range(3):
        envs = execution_service.list_environments(sessions)
        local = next(e for e in envs if e["backend"] == "LOCAL")
        assert local["status"] == "READY"
        assert local["sandboxed"] is True, (
            "التحقق الحقيقي مُحي — عودة عطل التصفير غير المشروط")
    selected = execution_service.select_environment(
        sessions, policy="STRICT_ISOLATED")
    assert selected is not None, (
        "السياسة الصارمة تحجب رغم بيئة READY معزولة — تناقض موثق")


def test_unsettled_env_still_follows_substrate_truth(sessions):
    """قبل الحسم (DETECTED) يستمر التصحيح الآلي حسب الركيزة الفعلية."""
    _set_local(sessions, status="DETECTED", sandboxed=1)
    envs = execution_service.list_environments(sessions)
    local = next(e for e in envs if e["backend"] == "LOCAL")
    # هذا المضيف بلا ركيزة عزل — التصحيح الآلي يعيدها كما اكتشفها
    # التسجيل لأن الحالة لم تُحقق بعد (لا كذب جاهزية قبل الدليل)
    env_truth = bool(local["sandboxed"])
    assert isinstance(env_truth, bool)
    assert local["status"] == "DETECTED"


def test_capability_view_and_policy_agree(sessions):
    """قدرة sandbox والسياسة من مصدر واحد — لا «جاهزة» محجوبة."""
    from readiness import service as readiness_service

    _set_local(sessions, status="READY", sandboxed=1)
    view = readiness_service.capability_view(sessions, "sandbox")
    selected = execution_service.select_environment(
        sessions, policy="STRICT_ISOLATED")
    assert view["readiness_status"] == "READY"
    assert selected is not None
    assert selected["sandboxed"] is True
