"""اختبارات بنية واجهة الأمر 011 — العناصر الجديدة موجودة وموصولة.

فحص بنيوي سريع (نمط 006/010): الملفات تحمل العناصر والعقود
الجديدة — بطاقة بوابة التنفيذ، إعادة الفحص، السياسة، تيار الأحداث،
لوحة حقيقة المضيف، الحالات الموحدة للمزودين.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

UI = REPO / "src" / "ui"


def _read(name: str) -> str:
    return (UI / name).read_text(encoding="utf-8")


# ---------- §3 — بطاقة بوابة التنفيذ والنص الصادق ----------

def test_projects_js_has_execution_gate_card():
    js = _read("projects.js")
    assert "executionGateHtml" in js
    assert "التنفيذ محجوب مؤقتًا" in js          # النص الحرفي §3
    assert "APPROVED_BUT_BLOCKED" in js
    assert "التنفيذ مفتوح" in js
    # العبارة المضللة التاريخية غير موجودة في أي ملف واجهة
    for name in ("projects.js", "app.js", "task-cards.js", "settings.js"):
        assert "ليست مفتوحة" not in _read(name), name


def test_projects_js_recheck_and_policy():
    js = _read("projects.js")
    assert "/preflight" in js                     # زر إعادة الفحص
    assert "إعادة الفحص" in js
    assert "execution-policy" in js               # محدد السياسة
    assert "STRICT_ISOLATED" in js and "COMPATIBLE_LOCAL" in js
    assert "بلا إعادة اعتماد" in js               # عقد §19 معلن للمالك


def test_projects_js_subscribes_events_stream():
    js = _read("projects.js")
    assert "events/stream" in js                  # تيار §21
    assert "EventSource" in js
    # الأحداث المفصلية للتزامن موجودة في قائمة التحديث
    for kind in ("PREFLIGHT_PASS", "PREFLIGHT_BLOCKED", "GATE_AUTO_RESOLVED",
                 "EXECUTION_POLICY_CHANGED", "PROJECT_RESUMED"):
        assert kind in js


def test_projects_js_gate_statuses_and_provisioning():
    js = _read("projects.js")
    # مفردات آلة الحالة الجديدة (011 §2)
    for status in ("PENDING", "BLOCKED", "APPROVED", "REJECTED"):
        assert status in js
    assert "gate-recheck" in js                   # بوابات التوفير: زر فحص لا قرار
    assert "PREFLIGHT_BLOCKED" in js              # نوع البوابة الجديد معروض


# ---------- §24-§25 — لوحة حقيقة المضيف ----------

def test_execution_env_js_host_truth():
    js = _read("execution-env.js")
    assert "host-truth" in js                     # نقطة النهاية
    assert "hostTruthHtml" in js
    assert "حقيقة المضيف" in js
    assert "المنصة المضيفة" in js
    assert "وضع متوافق" in js                     # إعلان الوضع المتوافق
    # أعمدة §24: Host/Backend/OS/Isolation/Network/Capabilities
    for label in ("المضيف", "الخلفية", "العزل", "الشبكة", "القدرات"):
        assert label in js


def test_execution_env_js_worker_ladder_note():
    js = _read("execution-env.js")
    assert "سلم جاهزية العامل" in js              # §10 معلن في الواجهة
    assert "connectivity" in js and "authentication" in js


# ---------- §12-§16 — الحالات الموحدة للبحث ----------

def test_research_ui_effective_states():
    js = _read("research-ui.js")
    assert "effective_status" in js
    assert "منتهي الصلاحية — أعد الفحص" in js     # STALE معلنة
    assert "غير معد — عيّن تكوينه" in js          # NOT_CONFIGURED
    assert "state_reason" in js


def test_environment_ui_not_configured_chip():
    js = _read("environment.js")
    assert "NOT_CONFIGURED" in js


# ---------- CSS للعناصر الجديدة ----------

def test_css_new_components():
    css = _read("projects.css")
    assert ".pj-exec-gate" in css
    assert ".pj-policy" in css
    assert ".host-truth" in css
    assert ".env-compat" in css
