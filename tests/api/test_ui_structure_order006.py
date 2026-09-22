"""اختبارات بنية واجهة الأمر 006 — عقد الـUX كما نصّ الأمر.

فحوص بنيوية على index.html وapp.js (نفس منهجية اختبارات الأوامر
السابقة): زر ＋ وقائمته، خيارا محادثة/مهمة، موضع زر الإرسال يمين
صندوق الإدخال بصريًا (RTL — أول عنصر في DOM)، Shift+Enter لسطر
جديد، الشريط الجانبي، لوحة إعدادات النماذج، وألا أسماء داخلية في
الواجهة الأساسية (خارج القسم التقني).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HTML = (REPO / "src" / "ui" / "index.html").read_text(encoding="utf-8")
APP_JS = (REPO / "src" / "ui" / "app.js").read_text(encoding="utf-8")


def test_plus_button_and_menu_present():
    """زر ＋ بجانب مربع الكتابة — وقائمته: محادثة ومهمة (§2+§7)."""
    assert 'id="plus"' in HTML
    assert 'id="plus-menu"' in HTML
    assert 'data-mode="chat"' in HTML
    assert 'data-mode="task"' in HTML
    menu_area = HTML.split('id="plus-menu"')[1].split("</div>")[0]
    assert "محادثة" in menu_area
    assert "مهمة" in menu_area


def test_send_button_visually_right_of_input_in_rtl():
    """الإرسال يمين صندوق الإدخال بصريًا (RTL): أول عنصر في الـDOM.

    في صف RTL أول عنصر flex يُرسم عند الحافة اليمنى — لذا زر الإرسال
    يجب أن يسبق الـtextarea في الـDOM (والـ＋ بعدها = يسار بصريًا).
    """
    inner = HTML.split('class="composer-inner"')[1].split("</div>")[0]
    send_pos = inner.index('id="send"')
    input_pos = inner.index('id="input"')
    plus_pos = inner.index('id="plus"')
    assert send_pos < input_pos < plus_pos, (
        "الترتيب يجب أن يكون: إرسال ثم الإدخال ثم ＋ (إرسال يمينًا، ＋ يسارًا)"
    )


def test_enter_sends_shift_enter_newline():
    """Enter للإرسال وShift+Enter لسطر جديد — حرفيًا في المعالج (§7)."""
    assert "e.key === \"Enter\"" in APP_JS or "e.key === 'Enter'" in APP_JS
    assert "e.shiftKey" in APP_JS
    assert "preventDefault" in APP_JS  # Enter لا يضيف سطرًا


def test_textarea_autogrow():
    """التمدد التلقائي للـtextarea حتى حد معقول (§7)."""
    assert "autoGrow" in APP_JS
    assert "scrollHeight" in APP_JS
    assert "Math.min" in APP_JS  # حد أقصى


def test_sidebar_with_real_conversations():
    """شريط جانبي + زر محادثة جديدة + قائمة محادثات حقيقية (§6)."""
    assert 'id="sidebar"' in HTML
    assert 'id="new-chat"' in HTML
    assert 'id="conversations"' in HTML
    # الواجهة تسحب المحادثات من الـAPI الحقيقي لا قائمة وهمية
    assert "/api/conversations" in APP_JS


def test_settings_drawer_with_role_model_config():
    """لوحة إعدادات حقيقية (لا modal بدائي) بنموذج لكل دور (§5)."""
    assert 'id="settings-drawer"' in HTML
    assert "drawer" in HTML
    assert 'id="role-models"' in HTML
    assert 'id="models-save"' in HTML
    assert "/api/models/config" in (REPO / "src/ui/settings.js").read_text(
        encoding="utf-8"
    )


def test_task_settings_bar_above_composer():
    """إعدادات المهمة قابلة للطي فوق الـcomposer (§8)."""
    assert 'id="task-settings"' in HTML
    assert 'id="task-settings-toggle"' in HTML
    settings_pos = HTML.index('id="task-settings"')
    composer_pos = HTML.index('class="composer"')
    assert settings_pos < composer_pos


def test_execution_card_steps_not_role_symbols():
    """بطاقة تنفيذ بمراحل بأسماء عربية — لا رموز أدوار كواجهة أساسية (§9)."""
    task_cards = (REPO / "src/ui/task-cards.js").read_text(encoding="utf-8")
    for step in ("التخطيط", "المراجعة", "التنفيذ", "التحقق", "التحكيم"):
        assert step in task_cards, f"مرحلة {step} مفقودة من بطاقة التنفيذ"
    # (الأمر 008 §12) علامات المراحل: ✓ اكتمل / ● جارٍ / ○ بانتظار / ✕ فشل
    for mark in ("✓", "●", "○", "✕"):
        assert mark in task_cards


def test_no_internal_names_in_primary_ui():
    """لا أسماء داخلية في الواجهة الأساسية — حصرًا في القسم التقني (§6)."""
    # القسم التقني المعلن (010: قسم «متقدم» في التبويبات)
    tech_section = HTML.split('id="tab-advanced"')[1].split("</section>")[0]
    # الواجهة الأساسية = كل HTML ما عدا القسم التقني
    primary = HTML.replace(tech_section, "")
    for internal in ("EOE", "router demo", "mock", "build demo", "textstats"):
        assert internal.lower() not in primary.lower(), (
            f"اسم داخلي '{internal}' في الواجهة الأساسية — للقسم التقني حصرًا"
        )
    # الأسماء العربية للأدوات المتقدمة موجودة في القسم التقني
    assert "تنفيذ أمر تنفيذي" in tech_section
    assert "أحداث الموجّه" in tech_section


def test_chat_and_task_stream_endpoints_wired():
    """المساران موصولان فعليًا: /api/chat/stream و/api/cycle/stream."""
    assert "/api/chat/stream" in APP_JS
    assert "/api/cycle/stream" in APP_JS


def test_versioned_assets_and_new_modules():
    """(الأمر 008+010) أصول مرقمة + الوحدات بالترتيب — العارض قبل
    النواة، وحدود الأخطاء قبل الإعدادات، والبحث وبيئات التنفيذ قبل
    المشاريع."""
    assert "styles.css?v=3.3.0" in HTML
    assert "app-shell.css?v=3.3.0" in HTML
    assert "markdown.js?v=3.3.0" in HTML
    md_pos = HTML.index("markdown.js?v=3.3.0")
    app_pos = HTML.index("app.js?v=3.3.0")
    chat_pos = HTML.index("chat-stream.js?v=3.3.0")
    task_pos = HTML.index("task-cards.js?v=3.3.0")
    picker_pos = HTML.index("model-picker.js?v=3.3.0")
    boundary_pos = HTML.index("error-boundary.js?v=3.3.0")
    settings_pos = HTML.index("settings.js?v=3.3.0")
    env_pos = HTML.index("environment.js?v=3.3.0")
    research_pos = HTML.index("research-ui.js?v=3.3.0")
    exec_pos = HTML.index("execution-env.js?v=3.3.0")
    projects_pos = HTML.index("projects.js?v=3.3.0")
    assert md_pos < app_pos < chat_pos < task_pos < picker_pos
    assert picker_pos < boundary_pos < settings_pos < env_pos
    assert env_pos < research_pos < exec_pos < projects_pos


def test_mode_chip_shows_current_selection():
    """الاختيار الحالي (محادثة/مهمة) ظاهر في الـcomposer (§7)."""
    assert 'id="mode-chip"' in HTML
    assert "محادثة" in APP_JS.split("modeChipEl.textContent =")[1][:80]
    assert "مهمة" in APP_JS.split("modeChipEl.textContent =")[1][:120]
