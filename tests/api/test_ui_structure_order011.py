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
# (013) المشهد انتقل لمحادثة حية: الضمانات نفسها في project-live.js
# (البطاقات) + projects.js (التنسيق) + live-events.js (البث).

def test_execution_gate_honest_state_card():
    live = _read("project-live.js")
    scene = _read("projects.js")
    # بطاقة الحجب الصادقة: الحالة والسبب والمطلوب من /state
    assert "renderBlockedCard" in live
    assert "execution_gate" in live
    assert "التنفيذ متوقف" in live                # النص الصادق (013 §27)
    assert "APPROVED_BUT_BLOCKED" in live or "execution_gate" in live
    # العبارة المضللة التاريخية غير موجودة في أي ملف واجهة
    for name in ("projects.js", "project-live.js", "app.js",
                 "task-cards.js", "settings.js"):
        assert "ليست مفتوحة" not in _read(name), name


def test_recheck_and_provisioning_actions():
    live = _read("project-live.js")
    scene = _read("projects.js")
    assert "/preflight" in scene                  # مسار إعادة الفحص موصول
    assert "إعادة الفحص" in live                  # الزر في بطاقة الحجب
    assert "/api/environment/provision" in live   # زر التجهيز (013 §17)
    assert "تجهيز بيئة التنفيذ" in live
    assert "بلا إعادة اعتماد" in live             # عقد §19 معلن للمالك


def test_live_events_stream_subscription():
    stream = _read("live-events.js")
    live = _read("project-live.js")
    assert "events/stream" in stream              # تيار §21 (013 §5)
    assert "EventSource" in stream
    assert "after_id" in stream                   # Last-Event-ID/replay
    assert "visibilitychange" in stream           # استرداد العودة (§5)
    # الأحداث المفصلية للتزامن في قائمة تغيّر المشهد (project-live)
    for kind in ("PREFLIGHT_PASS", "PREFLIGHT_BLOCKED", "GATE_AUTO_RESOLVED",
                 "PROJECT_RESUMED", "JOB_WAITING", "PLAN_APPROVED"):
        assert kind in live, kind


def test_gate_statuses_and_decision_buttons():
    live = _read("project-live.js")
    # مفردات آلة الحالة الجديدة (011 §2) — بطاقة القرار (013 §11)
    for status in ("PENDING", "APPROVED", "REJECTED"):
        assert status in live, status
    assert "PREFLIGHT_BLOCKED" in live            # نوع البوابة معروض
    assert "اعتماد الخطة" in live                 # زر القرار §7
    assert "جاري الاعتماد" in live                # loading — لا نقر مزدوج
    assert "تعذر اعتماد الخطة" in live            # فشل صريح بلا صمت


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
