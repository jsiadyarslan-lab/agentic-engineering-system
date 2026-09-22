"""اختبارات معايير القبول القابلة للاختبار (013 §24-§25).

القاعدة (§25): كل معيار كيان مهيكل {criterion_id, description,
verification_method, required_capabilities, evidence_required, status}
— لا PASSED بكلام نموذج أبدًا؛ الحالة من الأدلة الميكانيكية.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from workflow import acceptance  # noqa: E402


def test_string_criteria_normalized_to_structured():
    """نص حر ← كيانات كاملة بهويات ثابتة (AC-01…) وطرق تحقق مشتقة."""
    criteria = acceptance.normalize_criteria([
        "المنصة تجمع من خمس مصادر OSINT",
        "توليد تقرير PDF عربي",
    ])
    assert len(criteria) == 2
    first, second = criteria
    assert first["criterion_id"] == "AC-01"
    assert second["criterion_id"] == "AC-02"
    assert first["description"] == "المنصة تجمع من خمس مصادر OSINT"
    # طريقة التحقق من الطرق المعلنة حصرًا
    assert first["verification_method"] in acceptance.VERIFICATION_METHODS
    assert second["verification_method"] in acceptance.VERIFICATION_METHODS
    # OSINT في النص ← قدرة البحث مطلوبة
    assert "web_search" in first["required_capabilities"]
    # PDF في النص ← فحص مخرج ملموس
    assert second["verification_method"] == "artifact_check"
    # كل معيار يحدد الدليل المطلوب
    assert first["evidence_required"]
    assert second["evidence_required"]
    assert all(c["status"] == "PENDING" for c in criteria)


def test_structured_criteria_pass_through_with_ids():
    """معايير مهيكلة من المخطط الحي تمر كما هي — توافق رجعي كامل."""
    criteria = acceptance.normalize_criteria([
        {"criterion_id": "AC-07", "description": "اختبارات أمنية",
         "verification_method": "test_run",
         "required_capabilities": ["testing"],
         "evidence_required": ["مخرج pytest"]},
    ])
    assert criteria[0]["criterion_id"] == "AC-07"
    assert criteria[0]["verification_method"] == "test_run"
    assert criteria[0]["required_capabilities"] == ["testing"]


def test_deterministic_ids_and_dedup():
    """نفس المدخل ← نفس الخرج؛ تعارض الهويات يُحل بلا تصادم."""
    once = acceptance.normalize_criteria(["أ", "ب"])
    twice = acceptance.normalize_criteria(["أ", "ب"])
    assert [c["criterion_id"] for c in once] == \
           [c["criterion_id"] for c in twice]
    clashed = acceptance.normalize_criteria([
        {"criterion_id": "AC-01", "description": "أ"},
        {"criterion_id": "AC-01", "description": "ب"},
    ])
    ids = [c["criterion_id"] for c in clashed]
    assert len(ids) == len(set(ids)), f"تصادم هويات: {ids}"


def test_empty_and_invalid_input_honest():
    """مدخل فارغ/فاسد ← قائمة فارغة/معايير صالحة حصرًا — لا اختراع."""
    assert acceptance.normalize_criteria([]) == []
    assert acceptance.normalize_criteria("") == []
    assert acceptance.normalize_criteria(None) == []
    # عناصر بلا وصف تُسقط بلا اختراع
    out = acceptance.normalize_criteria([{"x": 1}, "  ", "صالح"])
    assert len(out) == 1 and out[0]["description"] == "صالح"


def test_criteria_view_status_from_evidence(wf_env):
    """(§25) الحالة من الأدلة الميكانيكية لا من نص المنفذ.

    مشروع بخطة وخطوة منجزة بدليل EVIDENCED ← معياره EVIDENCED؛
    مشروع بلا أدلة ← معاييره PENDING — الصدق قبل الراحة.
    """
    sessions = wf_env["sessions"]
    engine = wf_env["build_engine"]()
    project = engine.create_project("معايير", "هدف بمعايير قبول")
    engine.generate_plan(project["id"])
    engine.approve_plan(project["id"], approved=True)
    engine.run(project["id"])

    view = acceptance.criteria_view(sessions, project["id"])
    assert view, "لا معايير في القراءة"
    assert view[0]["criterion_id"] == "AC-01"
    # الخطوة نفذت بأدلة ميكانيكية (EVIDENCED) — المعيار ثبت
    statuses = {c["status"] for c in view}
    assert statuses <= {"EVIDENCED", "PENDING"}
    assert any(c["status"] == "EVIDENCED" for c in view), \
        "دليل ميكانيكي موجود والمعايير كلها PENDING — الربط مكسور"
    evidenced = next(c for c in view if c["status"] == "EVIDENCED")
    assert evidenced["evidence_ids"], "EVIDENCED بلا هوية دليل"

    # مشروع آخر بلا تنفيذ: كل المعايير PENDING صادقة
    project2 = engine.create_project("معايير بلا تنفيذ", "هدف آخر")
    engine.generate_plan(project2["id"])
    fresh = acceptance.criteria_view(sessions, project2["id"])
    assert fresh and all(c["status"] == "PENDING" for c in fresh)
