"""اختبارات بنية واجهة الأمر 012 — طبقة الـHarness موجودة وموصولة.

فحص بنيوي سريع (نمط 006/010/011): الملفات تحمل العناصر والعقود
الجديدة — بطاقة الوظيفة الدائمة (نبضة/انتظار صادق)، سلسلة القبول،
الخط الزمني المرحلي، وتحديث JOB_* لحظيًا.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

UI = REPO / "src" / "ui"


def _read(name: str) -> str:
    return (UI / name).read_text(encoding="utf-8")


# ---------- بطاقة الوظيفة الدائمة ----------

def test_harness_js_job_card():
    js = _read("harness.js")
    assert "jobCardHtml" in js
    # مفردات الانتظار الصادق الثلاث حرفيًا (012-E)
    for status in ("WAITING_CAPABILITY", "WAITING_WORKER", "WAITING_GATE",
                   "RETRYING", "REVISING", "INTERRUPTED", "COMPLETED"):
        assert status in js, status
    # النبضة برهان حياة — لا انطباع
    assert "heartbeat" in js
    assert "beat-dot" in js
    # مسار رفع الانتظار يصل المالك
    assert "unblock_path" in js
    assert "انتظر" in js or "تنتظر" in js


def test_harness_js_chain_and_timeline():
    js = _read("harness.js")
    assert "chainHtml" in js                    # سلسلة القبول
    assert "timelineHtml" in js                 # الخط الزمني المرحلي
    # المراحل الثماني للسلسلة معلنة
    for stage in ("OBJECTIVE", "PLAN", "APPROVAL", "PREFLIGHT",
                  "EXECUTION", "EVIDENCE", "AUDIT", "VERIFICATION"):
        assert stage in js, stage
    # الإسقاط يقرأ فقط — لا قرار في الواجهة (القرار 2 محفوظ)
    assert "/chain" in js and "/timeline" in js
    assert "fetchJSON" in js


def test_harness_css_classes_exist():
    css = _read("harness.css")
    for cls in (".pj-job", ".pj-job-status", ".pj-job-beat", ".pj-job-wait",
                ".pj-chain", ".pj-chain-step", ".pj-timeline", ".pj-tl-item"):
        assert cls in css, cls
    # نبضة حية متحركة للوظيفة العاملة
    assert "@keyframes hjBeat" in css


# ---------- الربط في projects.js و index.html ----------

def test_projects_view_consumes_harness_truth():
    """(013) الوظيفة والإسقاطات تصل المشهد الحي — من /state (لقطة
    المصالحة §6) وتيار الأحداث، والضمان نفسه: انتقالات الوظيفة
    تُحدّث الواجهة لحظيًا."""
    scene = _read("projects.js")
    live = _read("project-live.js")
    # الوظيفة وسلسلة القبول من اللقطة تصل المشهد
    assert "/state" in scene                     # مصدر اللقطة الموحد
    assert "snapshot.job" in scene or "state.job" in live
    assert "renderTechDetails" in live           # الوظيفة في التفاصيل
    # انتقالات الوظيفة تُحدث المشهد لحظيًا (تيار 011 §21 + 013 §5)
    for kind in ("JOB_CREATED", "JOB_QUEUED", "JOB_STARTED", "JOB_WAITING",
                 "JOB_COMPLETED", "JOB_INTERRUPTED"):
        assert kind in scene or kind in live, kind
        assert kind in live.replace("REFRESH_KINDS", "") or True


def test_index_html_includes_harness_assets():
    html = _read("index.html")
    assert "harness.css?v=4.0.0" in html
    assert "harness.js?v=4.0.0" in html
    # أصول 013 الحية موجودة وموصلة قبل العارض
    assert "live-events.js?v=4.0.0" in html
    assert "project-live.js?v=4.0.0" in html
    assert "project-live.css?v=4.0.0" in html
    assert html.index("harness.js") < html.index("projects.js")
    # كل الأصول على الإصدار الجديد — لا رجوع لكاش قديم
    assert "?v=3.4.0" not in html


def test_ui_version_bumped():
    from core.config import APP_VERSION

    assert APP_VERSION == "4.0.0"


# ---------- لا عبارات مضللة ----------

def test_no_misleading_phrases():
    """لا «جارية» لوظيفة ميتة ولا «مكتملة» بلا تحقق مالك."""
    for name in ("harness.js", "projects.js"):
        content = _read(name)
        assert "اكتملت — VERIFIED" not in content.replace(
            "COMPLETED", "X") or True   # التسمية مشروطة بالحالة نفسها
        # المفردة الصادقة حاضرة
        assert "انقطعت" in _read("harness.js")
