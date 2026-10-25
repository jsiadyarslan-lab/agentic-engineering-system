"""(AES-LIVE-FACTORY-E2E-001 المرحلة 4+§6) اختبارات مصدرية لسطح المشاهدة.

طبقة ثابتة على المصدر تعمل دائمًا (بلا node):
- التبويبات الثلاثة موجودة وموجهة: المعاينة/متصفح الوكيل/الطرفية.
- نقاط النهاية الجديدة مرتبطة فعليًا في JS (لا أزرار لأطراف معدومة).
- الطرفية تعرض أنواع أحداث محددة بيضاء — لا سلسلة تفكير خام.
- إصدار الأصول مرفوع فلا يخدم المتصفح نسخة قديمة بعد النشر.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI = REPO / "src" / "ui"
INDEX = UI / "index.html"
WV = UI / "workflow-view.js"
PJ = UI / "projects.js"


def test_new_tabs_present_and_routed():
    """التبويبات الثلاثة في index.html وموجهة في projects.js."""
    html = INDEX.read_text(encoding="utf-8")
    for tab in ("preview", "browser", "terminal"):
        assert f'data-tab="{tab}"' in html, tab
    js = PJ.read_text(encoding="utf-8")
    assert "renderPreviewTab" in js
    assert "renderBrowserTab" in js
    assert "renderTerminalTab" in js


def test_panels_bound_to_real_endpoints():
    """كل لوحة تستهلك نقطة نهاية موجودة فعلاً في الواجهة الخلفية."""
    js = WV.read_text(encoding="utf-8")
    api = (REPO / "src" / "api" / "projects.py").read_text(
        encoding="utf-8")
    for endpoint in ("/preview", "/browser-activity", "/events?limit="):
        assert endpoint in js, endpoint
    # رابط اللقطة يأتي من الخادم (event-bound) — الواجهة تستهلكه لا تبنيه
    assert "shot.image_url" in js
    for route_marker in ('"/{project_id}/preview"',
                         '"/{project_id}/browser-activity"',
                         '"/{project_id}/browser-screenshots/{event_id}"',
                         '"/{project_id}/workspace-files"'):
        assert route_marker in api, route_marker


def test_terminal_whitelist_no_raw_chain_of_thought():
    """الطرفية بيضاء الأنواع — ما يُعرض محدد لا تدفق تفكير خام."""
    js = WV.read_text(encoding="utf-8")
    start = js.find("function terminalKind")
    assert start != -1
    chunk = js[start:js.find("}", start) + 1]
    for kind in ("TOOL_EXECUTION", "FILE_WRITTEN", "STEP_STARTED",
                 "MODEL_CALL_STARTED", "BROWSER_SCREENSHOT"):
        assert kind in chunk, kind
    # لا مفتاح سلسلة تفكير خام في أي مكان من الملف
    assert "reasoning_raw" not in js
    assert "chain_of_thought" not in js


def test_preview_iframe_and_honest_empty_state():
    """إطار معاينة حي + حالة فراغ صادقة قبل أول index.html."""
    js = WV.read_text(encoding="utf-8")
    assert 'el("iframe", "wf-preview-frame")' in js
    assert "meta.reason" in js  # نص السبب الحرفي من الخادم
    assert "available" in js


def test_browser_panel_shows_only_durable_events():
    """لوحة المتصفح تستهلك الأحداث الدائمة عبر browser-activity فقط."""
    js = WV.read_text(encoding="utf-8")
    assert "/browser-activity" in js
    # لا إنشاء لقطات محليًا في الواجهة — اللقطة من حدث فقط
    assert "html2canvas" not in js
    assert "toDataURL" not in js


def test_panels_stop_polling_after_leaving_tab():
    """النبض يتوقف حين تغادر اللوحة المستند — لا مؤقتات يتيمة."""
    js = WV.read_text(encoding="utf-8")
    assert "inDocument(" in js
    assert "clearInterval(timer)" in js


def test_asset_version_bumped_no_stale_refs():
    """إصدار الأصول الجديد موحد — لا مرجع للإصدار القديم."""
    html = INDEX.read_text(encoding="utf-8")
    assert "v=3.9.0-lf1" in html
    assert "v=3.8.1-ui2" not in html
    assert "v=3.6.0" not in html


def test_write_file_versions_snapshot_source():
    """(المرحلة 4د) منطق نسخ الفروق داخل كود الركيزة المولَّد."""
    tools = (REPO / "src" / "roles" / "tools.py").read_text(
        encoding="utf-8")
    assert "'_versions'" in tools
    assert "snapshot.write_bytes(target.read_bytes())" in tools
    # الحدث الدائم FILE_WRITTEN يُبث من المحرك على كتابة فعلية
    engine = (REPO / "src" / "workflow" / "engine.py").read_text(
        encoding="utf-8")
    assert '"FILE_WRITTEN"' in engine
    assert "output_sha256" in engine
