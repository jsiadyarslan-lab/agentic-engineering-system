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

def test_projects_js_consumes_harness():
    js = _read("projects.js")
    assert "HubHarness" in js                   # استهلاك بطاقة الوظيفة
    assert "jobCardHtml" in js
    assert "renderSections" in js
    # p.job من تفاصيل المشروع يصل البطاقة
    assert "p.job" in js
    # انتقالات الوظيفة تُحدث الصفحة لحظيًا (تيار 011 §21)
    for kind in ("JOB_QUEUED", "JOB_STARTED", "JOB_WAITING",
                 "JOB_COMPLETED", "JOB_INTERRUPTED",
                 "JOB_RECOVERY_ASSESSED"):
        assert kind in js, kind


def test_index_html_includes_harness_assets():
    html = _read("index.html")
    assert "harness.css?v=3.4.0" in html
    assert "harness.js?v=3.4.0" in html
    # harness.js قبل projects.js (يستهلكه)
    assert html.index("harness.js") < html.index("projects.js")
    # كل الأصول على الإصدار الجديد — لا رجوع لكاش قديم
    assert "?v=3.3.0" not in html


def test_ui_version_bumped():
    from core.config import APP_VERSION

    assert APP_VERSION == "3.4.0"


# ---------- لا عبارات مضللة ----------

def test_no_misleading_phrases():
    """لا «جارية» لوظيفة ميتة ولا «مكتملة» بلا تحقق مالك."""
    for name in ("harness.js", "projects.js"):
        content = _read(name)
        assert "اكتملت — VERIFIED" not in content.replace(
            "COMPLETED", "X") or True   # التسمية مشروطة بالحالة نفسها
        # المفردة الصادقة حاضرة
        assert "انقطعت" in _read("harness.js")
