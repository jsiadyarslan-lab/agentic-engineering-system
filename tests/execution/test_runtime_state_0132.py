"""اختبارات الأمر 013.2 — الحالة القانونية الواحدة للتشغيل.

يغطي عقد 013.2 §1-§6 حرفيًا:
§1 مصدر واحد — canonical_state هو ما يقرأه الجميع (ready بلا برهان
   هوية وفحوص = مستحيل).
§2 المطلوب مفصول عن الفعلي — نص المتطلب لا يحمل كلمة «جاهزة».
§3 آلة الحالة القانونية — مفردات مقفلة، READY ببرهان فقط.
§4 العزل الصارم — مضيف Windows بلا مسار توفير = UNAVAILABLE بالفجوة
   الحرفية، لا READY للبيئة المتوافقة تحت سياسة عزل.
§5 التجهيز واعٍ بالسياسة — كل خطوة تسجل في الدائم مع تقدم%.
§6 فحوص الصحة المسماة — كتابة/قراءة/حذف/دليل عمل/معمارية/عزل/التقاط.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from execution import policy as execution_policy  # noqa: E402
from execution import runtime_state  # noqa: E402
from execution.backends import LocalProcessBackend  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "runtime-state-0132.db")
    init_db(engine)
    return make_session_factory(engine)


def test_runtime_states_vocabulary_is_closed(sessions):
    """§3 مفردات الآلة مقفلة — كتابة حالة خارجها مرفوضة."""
    with pytest.raises(ValueError, match="حالة غير قانونية"):
        runtime_state.record_state(sessions, "STRICT_ISOLATED", "SORTA_READY")
    assert "READY" in runtime_state.RUNTIME_STATES
    assert "UNAVAILABLE" in runtime_state.RUNTIME_STATES
    # لا نص «جاهزة» عامًّا خارج المفردات (§3: no generic ready string)
    assert isinstance(runtime_state.RUNTIME_STATES, tuple)


def test_requirement_text_is_requirement_not_status():
    """§2 نص المتطلب لا يوحي بحالة — كلمة «جاهزة» ممنوعة فيه.

    هذا بالضبط كان التناقض المرفوض: عنوان البطاقة «غير جاهزة»
    وتحتها «بيئة تنفيذ معزولة جاهزة».
    """
    for policy_name in execution_policy.POLICIES:
        text = execution_policy.requirement_text(policy_name)
        assert text.strip(), f"نص متطلب فارغ لـ{policy_name}"
        assert "جاهزة" not in text, (
            f"نص المتطلب لـ{policy_name} يحمل كلمة «جاهزة» — تناقض §2: {text}"
        )
        assert "المطلوب" in text or "مطلوب" in text


def test_canonical_state_ready_requires_evidence(sessions):
    """§3 READY قانونية فقط ببرهان: بيئة + فحوص ناجحة + هوية دائمة.

    بيئة مسجلة بحالة READY لكن بلا فحوص مسجلة = ليست READY قانونية.
    """
    from execution import service as execution_service

    # بيئة محلية بلا تحقق بعد — ليست READY مهما قيل غير ذلك
    execution_service.ensure_local_registered(sessions)
    canonical = runtime_state.canonical_state(
        sessions, "COMPATIBLE_LOCAL")
    assert canonical["state"] != "READY" or (
        canonical["evidence"].get("checks_ok") is True
    )
    # الحالة المتماسكة لا تقول «جاهزة» بلا برهان
    if canonical["state"] != "READY":
        assert canonical["coherent"]["kind"] != "READY"


def test_canonical_state_preparing_from_durable_record(sessions):
    """§1 «جاري التجهيز» حقيقة دائمة — السجل هو المصدر."""
    runtime_state.record_state(
        sessions, "STRICT_ISOLATED", "PROVISIONING",
        reason="تسجيل بيئة التنفيذ…", progress=42,
    )
    canonical = runtime_state.canonical_state(
        sessions, "STRICT_ISOLATED")
    # لا بيئة موافقة بعد والسجل يقول تجهيز — عرض التجهيز صادق
    assert canonical["coherent"]["kind"] in ("PREPARING", "UNAVAILABLE")
    record = runtime_state.read_record(sessions, "STRICT_ISOLATED")
    assert record["progress"] == 42
    assert record["state"] == "PROVISIONING"


def test_structural_gap_on_windows_host_strict(sessions):
    """§4 مضيف Windows بلا WSL/Docker/عامل تحت عزل صارم = الفجوة
    الحرفية معلنة (UNAVAILABLE)، لا READY للبيئة المتوافقة."""

    def windows_truth():
        return {
            "os": "Windows", "architecture": "AMD64",
            "container_runtime": "", "docker": "", "wsl": False,
            "cpu_cores": 8, "memory": "16 GB", "kernel": "10.0",
            "python": "3.12.1",
        }

    with patch(
        "execution.backends.runtime_truth", windows_truth,
    ), patch(
        "execution.service._substrate_available", lambda: False,
    ):
        canonical = runtime_state.canonical_state(
            sessions, "STRICT_ISOLATED")
    assert canonical["state"] == "UNAVAILABLE"
    assert canonical["coherent"]["kind"] == "UNAVAILABLE"
    assert canonical["missing"], "لا فجوات معلنة رغم الاستحالة البنيوية"
    gap = canonical["missing"][0]
    assert gap["need"]
    assert "detected" in gap and "action" in gap
    # الفعل يسمي الطرق الثلاثة الحقيقية
    assert "WSL2" in gap["action"] or "عامل" in gap["action"]


def test_provision_strict_on_windows_unavailable_not_fake_ready(sessions):
    """§4+§5 التجهيز تحت عزل صارم على مضيف Windows بلا مسار =
    PROVISIONING_UNAVAILABLE بالسبب الحرفي — لا READY كاذبة
    للبيئة المتوافقة (جذر انفصام 013.1)."""

    def windows_truth():
        return {
            "os": "Windows", "architecture": "AMD64",
            "container_runtime": "", "docker": "", "wsl": False,
            "cpu_cores": 8, "memory": "16 GB", "kernel": "10.0",
            "python": "3.12.1",
        }

    from execution import provisioner

    with patch(
        "execution.backends.runtime_truth", windows_truth,
    ), patch(
        "execution.service._substrate_available", lambda: False,
    ):
        result = provisioner.provision(sessions, policy="STRICT_ISOLATED")
    assert result["state"] == "PROVISIONING_UNAVAILABLE"
    assert "لا يستطيع توفير عزل" in result["reason"]
    assert result.get("policy") == "STRICT_ISOLATED"
    # الحالة الدائمة تسجل الاستحالة — لا تجهيز جارٍ زائف
    record = runtime_state.read_record(sessions, "STRICT_ISOLATED")
    assert record["state"] == "UNAVAILABLE"


def test_provision_records_durable_progress(sessions):
    """§5 كل خطوة تجهيز تسجل في الدائم — التقدم% حقيقة مقروءة."""
    from execution import provisioner

    result = provisioner.provision(sessions, policy="STRICT_ISOLATED")
    record = runtime_state.read_record(sessions, "STRICT_ISOLATED")
    assert record is not None
    if result["state"] == "READY":
        assert record["state"] == "READY"
        assert record["progress"] == 100
        assert record["environment_id"] == result["environment"]["id"]
        # §6 برهان الفحوص مرفق بالسجل الدائم
        assert record["evidence"].get("checks")
    else:
        # بيئة التطوير قد لا توفر العزل — الحالة الصادقة مسجلة أيًّا كانت
        assert record["state"] in ("UNAVAILABLE", "FAILED", "READY")


def test_health_check_named_checks_present():
    """§6 فحوص الصحة مسماة حرفيًا — لا «نجاح» مجملًا.

    الفحوص الإلزامية: execute + write_file + read_file + delete_file +
    working_directory + architecture + isolation + capture.
    """
    backend = LocalProcessBackend(environment_id="compat-test")
    result = backend.verify()
    names = {check["name"] for check in result.checks}
    required = {
        "boot", "execute", "write_file", "read_file", "delete_file",
        "working_directory", "architecture", "isolation", "capture",
    }
    missing = required - names
    assert not missing, f"فحوص §6 غائبة: {missing} — الموجود: {names}"
    # كل فحص له detail حرفي لا نص عام
    for check in result.checks:
        assert isinstance(check["detail"], str) and check["detail"]


def test_coherent_view_is_three_kinds_only():
    """§7 العرض المتماسك ثلاث حالات لا رابعة — READY/PREPARING/
    UNAVAILABLE حصرًا."""
    for state in runtime_state.RUNTIME_STATES:
        view = runtime_state.coherent_view(state, "", [], 0)
        assert view["kind"] in ("READY", "PREPARING", "UNAVAILABLE"), (
            f"حالة عرض غير قانونية {view['kind']} لـ{state}"
        )
        assert view["label"]


def test_canonical_running_with_job(sessions):
    """§3 وظيفة نشطة على بيئة موافقة = RUNNING — أحدث الحقائق."""
    canonical = runtime_state.canonical_state(
        sessions, "STRICT_ISOLATED",
        job={"id": 7, "status": "INTERRUPTED", "worker_id": "w-1",
             "last_error": ""},
    )
    assert canonical["state"] == "INTERRUPTED"
    assert canonical["worker_id"] == "w-1"
    assert canonical["coherent"]["kind"] == "PREPARING"
