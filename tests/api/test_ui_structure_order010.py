"""اختبارات بنية واجهة الأمر 010 — عقد §3-§4+§8+§14-§15+§31-§32.

فحوص بنيوية على الملفات (نفس منهجية الأوامر السابقة): القشرة
والتدفق والاتجاهات، التبويبات، جذر الصفحة السوداء (hidden)، التوجيه
الدائم، حدود الأخطاء، وحالات التحميل/الخطأ/الفراغ.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HTML = (REPO / "src" / "ui" / "index.html").read_text(encoding="utf-8")
APP_JS = (REPO / "src" / "ui" / "app.js").read_text(encoding="utf-8")
PROJECTS_JS = (REPO / "src" / "ui" / "projects.js").read_text(encoding="utf-8")
SHELL_CSS = (REPO / "src" / "ui" / "app-shell.css").read_text(encoding="utf-8")
BOUNDARY_JS = (REPO / "src" / "ui" / "error-boundary.js").read_text(
    encoding="utf-8"
)
EXEC_ENV_JS = (REPO / "src" / "ui" / "execution-env.js").read_text(
    encoding="utf-8"
)


def test_project_view_hidden_root_cause_fixed():
    """(§15 جذر الصفحة السوداء) enterProjectMode يزيل hidden — لا وكارك.

    الجذر: #project-view يحمل hidden في HTML و[hidden]{display:none
    !important} تتغلب على قاعدة الوضع غير المهمة — الحل من المصدر.
    """
    assert 'view.hidden = false' in PROJECTS_JS, (
        "enterProjectMode لا يزيل hidden — الصفحة السوداء ستعود"
    )
    assert "جذر الصفحة السوداء" in PROJECTS_JS  # الدرس موثق في الكود
    assert 'view.hidden = true' in PROJECTS_JS  # والخروج يعيده


def test_durable_routing_hash_patterns():
    """(§2+§14) توجيه دائم: #/chat/{id} و#/project/{id} مع hashchange."""
    assert "#/chat/" in APP_JS
    assert "#/project/" in APP_JS
    assert "hashchange" in APP_JS
    assert "applyRoute" in APP_JS
    assert "openConversationById" in APP_JS  # فتح من المعرف وحده


def test_conversation_identity_survives_refresh():
    """(§1) المحادثة الفعالة تُحفظ وتُستعاد — لا هوية ضائعة بعد التحديث."""
    assert "hub:active-conversation" in APP_JS
    assert "localStorage" in APP_JS
    assert "saveActiveConversation" in APP_JS
    assert "savedActiveConversation" in APP_JS


def test_message_stream_width_and_full_use():
    """(§3) التدفق يستعمل المساحة المتاحة بعرض 820-960 لا ضغطًا."""
    assert "max-width: 920px" in SHELL_CSS
    assert ".bubble.assistant" in SHELL_CSS
    assert "align-self: stretch" in SHELL_CSS  # رد المساعد بكامل العرض


def test_rtl_ltr_direction_architecture():
    """(§4) الاتجاه من المحتوى: dir=auto للرسائل، ltr قسري للكود."""
    assert 'body.dir = "auto"' in APP_JS  # فقاعة المستخدم والمساعد
    markdown = (REPO / "src" / "ui" / "markdown.js").read_text(encoding="utf-8")
    assert 'dir="ltr"' in markdown  # كود/روابط/JSON لا تنقلب
    assert "md-table-wrap" in markdown  # الجداول مدعومة


def test_settings_tabs_six_sections():
    """(§8) الإعدادات ستة أقسام منظمة لا كومة حقول."""
    tabs = ("general", "providers", "models", "tools", "execution", "advanced")
    for tab in tabs:
        assert f'data-tab="{tab}"' in HTML, f"تبويب مفقود: {tab}"
        assert f'id="tab-{tab}"' in HTML
    assert "settings-tabs" in HTML
    assert "activateTab" in (REPO / "src" / "ui" / "settings.js").read_text(
        encoding="utf-8"
    )


def test_error_boundary_present_and_wired():
    """(§32) حدود أخطاء عامة: عنصر + معالجان + معرف طلب + إعادة تحميل."""
    assert 'id="error-boundary"' in HTML
    assert "unhandledrejection" in BOUNDARY_JS
    assert '"error"' in BOUNDARY_JS
    assert "Request ID" in BOUNDARY_JS
    assert "location.reload" in BOUNDARY_JS


def test_loading_error_empty_states_present():
    """(§31) لا شاشة سوداء/صامتة: تحميل وخطأ وفراغ معلنة."""
    assert "جارٍ تحميل المحادثات" in APP_JS
    assert "تعذر تحميل المحادثات" in APP_JS
    assert "إعادة المحاولة" in APP_JS  # زر إعادة في القائمة
    assert "جارٍ تحميل المشروع" in PROJECTS_JS
    assert "renderError" in PROJECTS_JS
    assert "جارٍ تحميل الرسائل" in APP_JS


def test_environment_management_ui_wired():
    """(§28) إدارة البيئات في الواجهة: إضافة + تحقق + تنفيذ اختباري."""
    for api in ("/api/execution/environments", "/verify", "/test-run",
                "/default"):
        assert api in EXEC_ENV_JS, f"نقطة نهاية غير موصولة: {api}"
    assert "REMOTE_WORKER" in EXEC_ENV_JS
    assert "execution_worker.py" in EXEC_ENV_JS  # المسار الحقيقي ظاهر


def test_research_providers_ui_wired():
    """(§24-§25) مزودو البحث قابلون للتوفير من الواجهة."""
    research_ui = (REPO / "src" / "ui" / "research-ui.js").read_text(
        encoding="utf-8"
    )
    assert "/api/research/providers" in research_ui
    assert "probe" in research_ui
    assert "base_url" in research_ui  # تكوين searx
    assert "api_key" in research_ui  # مفتاح API (للمخزن لا العرض)


def test_draft_project_is_not_blank_page():
    """(§13) المسودة تعرض الهدف والخطة والإجراء التالي — لا صفحة فارغة."""
    assert "مشروع مسودة" in PROJECTS_JS
    assert "الإجراء التالي" in PROJECTS_JS
    assert "pj-draft-card" in PROJECTS_JS


def test_preflight_readiness_card_in_task_flow():
    """(§29) شاشة جاهزية المهمة: مصفوفة + بيئة + إجراء مالك بأزرار."""
    task_cards = (REPO / "src" / "ui" / "task-cards.js").read_text(
        encoding="utf-8"
    )
    for kind in ("preflight.started", "preflight.passed",
                 "preflight.blocked"):
        assert kind in task_cards
    assert "mx-table" in task_cards  # المصفوفة
    assert "OWNER ACTION REQUIRED" in task_cards
    assert "openTab" in task_cards  # الزر يفتح التبويب الصحيح
