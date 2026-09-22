"""اختبارات الأمر 013.2 — الحقيقة الثلاثية عبر الـAPI والواجهة.

الاختبار الحاسم (§17): عند اللحظة التي تقول فيها الواجهة «جاهزة»،
يجب أن يقول الـbackend نفسه READY بنفس environment_id — والجميع
يقرأ من نقطة واحدة (/api/execution/runtime-state + لقطة المشروع).

يغطي أيضًا (§7+§8+§10) ضمانات الواجهة ساكنةً:
- لا تناقض نصي بين عنوان البطاقة ومحتواها (لا «جاهزة» تحت «غير»)
- تدفق الماكرو حاضر والمسار التقني مطوي
- لا كشف لسلسلة تفكير خام
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from api import routes  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)

UI = REPO / "src" / "ui"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = build_engine(tmp_path / "truth-0132.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)
    yield TestClient(routes.app)


@pytest.fixture()
def live_client(tmp_path, monkeypatch):
    """عميل ببيئة مجهزة فعلًا (تجهيز حقيقي على مضيف الاختبار)."""
    engine = build_engine(tmp_path / "truth-live-0132.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)
    from execution import provisioner

    provisioner.provision(sessions, policy="STRICT_ISOLATED")
    yield TestClient(routes.app)


def test_runtime_state_endpoint_exists_and_coherent(client):
    """§1 نقطة الحالة القانونية موجودة وتعيد العرض المتماسك."""
    response = client.get("/api/execution/runtime-state")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] in (
        "DISCOVERING", "PROVISIONING", "BOOTING", "HEALTH_CHECK",
        "READY", "RUNNING", "DEGRADED", "INTERRUPTED", "FAILED",
        "UNAVAILABLE",
    )
    assert body["coherent"]["kind"] in ("READY", "PREPARING",
                                        "UNAVAILABLE")
    # §2 المطلوب والفعلي مفصولان حرفيًا في الرد نفسه
    assert "required" in body and "actual" in body
    assert body["required"]["requirement_text"]
    assert body["actual"]["host"]["platform"]


def test_truth_agreement_when_ready(live_client):
    """§17 الاختبار الحاسم: UI-ready ⇒ backend-ready بنفس الهوية.

    لقطة المشروع ونقطة runtime-state — القراءتان من مصدر واحد،
    فمستحيل أن تقول إحداهما READY والأخرى لا.
    """
    # 1) نقطة الحالة القانونية
    canonical = live_client.get(
        "/api/execution/runtime-state?policy=STRICT_ISOLATED").json()
    # 2) لقطة مشروع جديد — نفس الحقيقة من مسار الواجهة
    project = live_client.post("/api/projects", json={
        "name": "مشروع الحقيقة",
        "objective": "اختبار تطابق الحقيقة الثلاثية",
    }).json()
    snapshot = live_client.get(
        f"/api/projects/{project['id']}/state").json()
    env_block = snapshot["environment"]
    runtime = env_block["runtime_state"]

    assert runtime["state"] == canonical["state"], (
        "انفصام: لقطة المشروع تقول غير ما تقوله نقطة الحالة القانونية"
    )
    assert runtime["coherent"]["kind"] == canonical["coherent"]["kind"]
    assert runtime["environment_id"] == canonical["environment_id"]
    if runtime["state"] == "READY":
        # §3 READY بلا هوية دائمة = مستحيلة
        assert runtime["environment_id"] is not None
        assert runtime["evidence"]["checks_ok"] is True
        assert runtime["selected"]["name"]


def test_environment_block_has_no_contradictory_texts(live_client):
    """§7 ممنوع «غير جاهزة» كعنوان مع وصف «جاهزة» تحته — الواجهة
    تقتبس coherent.label من الحالة القانونية حصرًا."""
    project = live_client.post("/api/projects", json={
        "name": "مشروع التماسك", "objective": "اختبار لا تناقض",
    }).json()
    snapshot = live_client.get(
        f"/api/projects/{project['id']}/state").json()
    env = snapshot["environment"]
    runtime = env["runtime_state"]

    # العنوان المعروض يأتي من coherent.label — مفردات متماسكة فقط
    label = runtime["coherent"]["label"]
    kind = runtime["coherent"]["kind"]
    if kind == "READY":
        assert "جاهزة" in label and "غير" not in label
    elif kind == "UNAVAILABLE":
        # غير متاحة — لا وصف جاهزية داخل نفس البطاقة
        assert "غير متاحة" in label
    else:
        assert "تجهيز" in label
    # نص المتطلب لا يحمل كلمة «جاهزة» (§2)
    assert "جاهزة" not in env["requirement"]


def test_provision_endpoint_accepts_policy(client):
    """§5 التجهيز يقبل السياسة — والرد يحملها مع النتيجة."""
    response = client.post("/api/environment/provision", json={
        "policy": "COMPATIBLE_LOCAL",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["policy"] == "COMPATIBLE_LOCAL"
    # التجهيز إما نجح فعليًا أو فشل بسبب حرفي — لا حالة ثالثة
    assert body["state"] in ("READY", "FAILED",
                             "PROVISIONING_UNAVAILABLE")
    if body["state"] != "READY":
        assert body["reason"]


# ------------------------- فحوص الواجهة الساكنة ------------------------- #

def _read(name: str) -> str:
    return (UI / name).read_text(encoding="utf-8")


def test_ui_macro_flow_replaces_technical_checklist():
    """§8 تدفق الماكرو حاضر في الواجهة الأساسية."""
    live = _read("project-live.js")
    for label in ("المحادثة", "الخطة", "الاعتماد", "تجهيز البيئة",
                  "التنفيذ", "المراجعة", "مكتمل"):
        assert label in live, f"خطوة الماكرو «{label}» غائبة"
    assert "renderMacroFlow" in live
    # المسار التقني مطوي داخل التفاصيل لا أساسيًا
    assert "renderTechnicalPipeline" in live
    assert "renderTechDetails" in live


def test_ui_environment_card_quotes_coherent_state_only():
    """§7 بطاقة البيئة تقتبس الحالة المتماسكة — لا تركيب محلي."""
    live = _read("project-live.js")
    assert "runtime_state" in live
    assert "coherent" in live
    # العناوين الثلاثة المتماسكة حرفيًا من المصدر الواحد
    assert "بيئة التنفيذ جاهزة" in live
    assert "تجهيز بيئة التنفيذ" in live
    assert "بيئة التنفيذ غير متاحة" in live
    # لا يعود عنوان «غير جاهزة» القديم المنفصم
    assert 'pl-title",\n        "⚠ بيئة التنفيذ غير جاهزة' not in live


def test_ui_no_raw_chain_of_thought():
    """§10 لا كشف لسلسلة تفكير خام — ملخصات تنفيذ آمنة فقط."""
    live = _read("project-live.js")
    for forbidden in ("THINKING", "PROMPT", "RAW_MODEL",
                      "chain-of-thought", "internal deliberation"):
        assert forbidden not in live, f"كشف تفكير خام: {forbidden}"
    # ملخصات آمنة مسماة بدلًا عنها
    assert "آخر نشاط" in live or "النشاط الحي" in live


def test_ui_failure_loop_visible():
    """§11 حلقة الفشل: فشل ← تشخيص ← تعديل ← إعادة المحاولة."""
    live = _read("project-live.js")
    assert "renderFailureLoop" in live
    for label in ("تشخيص", "إعادة المحاولة"):
        assert label in live


def test_ui_provision_sends_policy():
    """§5 زر التجهيز يمرر سياسة المشروع — التجهيز واعٍ بالسياسة."""
    live = _read("project-live.js")
    assert "wireProvisionButtons" in live
    assert "policy: policy" in live or "policy: (state.environment"
    assert 'JSON.stringify({ policy' in live or \
        "JSON.stringify({\n          policy" in live


def test_css_supports_macro_flow_and_coherent_env():
    """الأنماط موجودة للتدفق الماكرو والبطاقة المتماسكة وشريط التقدم."""
    css = _read("project-live.css")
    for cls in (".pl-flow", ".pl-flow-step", ".pl-env-progress",
                ".pl-env-progress-fill", ".pl-env-reqact",
                ".pl-env-missing", ".pl-failloop"):
        assert cls in css, f"نمط مفقود: {cls}"
