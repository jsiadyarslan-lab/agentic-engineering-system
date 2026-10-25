"""اختبارات RLR-001 §4-ج — بنية مساحة التنفيذ الحية (لوحان متزامنان).

نفس منهجية اختبار بنية 006: فحوص بنيوية على ملفات الواجهة تعكس عقد
الأمر — لوحان متزامنان، سجل أحداث حقيقي، مرآة متصفح موسومة، حالات
اتصال صريحة، تجاوب هاتف، واستعادة أحداث عند الانقطاع.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HTML = (REPO / "src" / "ui" / "index.html").read_text(encoding="utf-8")
WV_JS = (REPO / "src" / "ui" / "workflow-view.js").read_text(encoding="utf-8")
WV_CSS = (REPO / "src" / "ui" / "workflow-view.css").read_text(encoding="utf-8")
PROJECTS_JS = (REPO / "src" / "ui" / "projects.js").read_text(encoding="utf-8")
LIVE_EVENTS = (REPO / "src" / "ui" / "live-events.js").read_text(
    encoding="utf-8")


def test_live_workspace_tab_registered():
    """تبويب مساحة التنفيذ الحية موجود ومربوط بالإرسال فعليًا."""
    assert 'data-tab="live"' in HTML
    assert "مساحة التنفيذ الحية" in HTML
    assert "renderLiveWorkspaceTab" in WV_JS
    assert 'tab === "live"' in PROJECTS_JS
    assert "wv.renderLiveWorkspaceTab" in PROJECTS_JS


def test_two_pane_split_layout():
    """لوحان جنباً إلى جنب على سطح المكتب مع إمكانية تعديل العرض."""
    assert "wf-live-split" in WV_JS
    assert ".wf-live-split" in WV_CSS
    assert "grid-template-columns" in WV_CSS
    # تعديل عرض كل لوح: مقبض تحجيم أصلي على اللوح الأيسر
    assert "resize: horizontal" in WV_CSS
    assert "wf-live-log-pane" in WV_JS and ".wf-live-log-pane" in WV_CSS
    assert "wf-live-browser-pane" in WV_JS and ".wf-live-browser-pane" in WV_CSS


def test_mobile_stacked_no_horizontal_scroll():
    """الهاتف: ترتيب عمودي بلا تمرير أفقي."""
    assert "@media (max-width: 900px)" in WV_CSS
    mobile = WV_CSS.split("@media (max-width: 900px)")[1]
    assert "grid-template-columns: minmax(0, 1fr)" in mobile
    assert "resize: none" in mobile


def test_left_pane_real_engine_events():
    """اللوح الأيسر: أحداث محرك فعلية — أدوات وملفات ونموذج وبوابات."""
    for kind in ("TOOL_EXECUTION", "FILE_WRITTEN", "MODEL_CALL_STARTED",
                 "MODEL_CALL_FAILED", "EXECUTION_BLOCKED",
                 "PROVIDER_TRANSIENT_FAILURE", "RETRY_REQUESTED",
                 "BROWSER_NAVIGATE", "BROWSER_SCREENSHOT"):
        assert kind in WV_JS, f"نوع حدث {kind} مفقود من السجل الحي"
    # الحالة الحالية + الخطوة والزمن
    assert "/state" in WV_JS
    assert "LIVE_STATE_LABELS" in WV_JS


def test_right_pane_honest_mirror():
    """اللوح الأيمن: مرآة موسومة صراحة — لا ادعاء متصفح تفاعلي مُبثّ."""
    assert "مرآة عرض من الجلسة الفعلية" in WV_JS
    assert "ليست متصفحًا تفاعليًا مُبثًّا" in WV_JS
    assert "/browser-activity" in WV_JS
    assert "/preview" in WV_JS
    # شريط URL/الحالة + آخر لقطة من الجلسة نفسها
    assert "wf-live-strip" in WV_JS and ".wf-live-strip" in WV_CSS
    assert "آخر تنقل" in WV_JS


def test_explicit_connection_states_and_replay():
    """حالات اتصال صريحة + استعادة أحداث بعد انقطاع قصير."""
    assert "متصل · بث حي" in WV_JS
    assert "منقطع — يعيد الاتصال ويستعيد الأحداث الفائتة" in WV_JS
    # المصدر: مدير البث (SSE + Last-Event-ID + backoff) لا تخمين محلي
    assert "live-disconnected" in LIVE_EVENTS
    assert "after_id=" in LIVE_EVENTS
    assert "scheduleReconnect" in LIVE_EVENTS
    assert "/events?limit=300" in WV_JS  # استعادة من الدائم


def test_no_cross_project_event_mixing():
    """أحداث المشروع تُرشّح بمعرفه — لا خلط أحداث مشروع بآخر."""
    assert "event.project_id" in WV_JS


def test_version_bumped_and_consistent():
    """رفع الإصدار عند النشر موحد عبر كل الأصول (عقد 006)."""
    import re
    versions = set(re.findall(
        r"\?v=([0-9]+\.[0-9]+\.[0-9]+[a-z0-9.-]*)", HTML))
    assert len(versions) == 1, f"إصدارات غير موحدة: {sorted(versions)}"
    assert "v=3.9.0-lf2" in HTML
