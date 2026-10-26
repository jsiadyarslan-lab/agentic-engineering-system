"""RLR-001 §4d — اختبار استخراج ملفات ومجلدات التسليم (علة حلقة الخطوة 208)."""
from roles.implementer_live import _deliverable_names, _declared_dirs


def test_package_json_is_deliverable():
    """امتداد json يفعّل نمط البناء — علة الحلقة اللانهائية في مشروع 21."""
    payload = {
        "description": "إنشاء هيكل المجلدات وكتابة package.json بسكريبتات التشغيل",
        "acceptance_criteria": [
            "المجلدات pages/, assets/css/, assets/js/, scripts/, evidence/, templates/ موجودة",
            "package.json يحتوي على: name، version، scripts",
        ],
        "context_goal": "",
    }
    names = _deliverable_names(payload)
    assert "package.json" in names, names


def test_declared_dirs_from_criteria():
    """المجلدات المصرّح بها تُستخرج بترتيبها وبلا تكرار."""
    payload = {
        "description": "إنشاء هيكل المجلدات وكتابة package.json",
        "acceptance_criteria": [
            "المجلدات pages/, assets/css/, assets/js/, scripts/, evidence/, templates/ موجودة",
        ],
        "context_goal": "",
    }
    dirs = _declared_dirs(payload)
    assert dirs == ["pages", "assets/css", "assets/js", "scripts",
                    "evidence", "templates"], dirs


def test_report_only_task_stays_report_path():
    """مهمة تقرير بلا ملفات صريحة تبقى على المسار الأصلي (لا انزلاق)."""
    payload = {
        "description": "اكتب تقريراً عن أسعار الفائدة",
        "acceptance_criteria": ["تقرير. md واحد على الأقل"],  # md مُستبعد
        "context_goal": "",
    }
    assert _deliverable_names(payload) == []
    assert _declared_dirs(payload) == []


def test_step218_comma_dirs_and_pathed_files():
    """علة خطوة 218: مجلدات بفواصل بلا شرطة نهائية + ملف بمسار كامل."""
    payload = {
        "description": "إنشاء هيكل المجلدات وقاعدة CSS للثيم الداكن",
        "acceptance_criteria": [
            "المجلدات src/pages, src/styles, src/assets, src/components موجودة",
            "src/styles/base.css يحدد :root مع متغيرات ألوان داكنة",
        ],
        "context_goal": "",
    }
    names = _deliverable_names(payload)
    assert "src/styles/base.css" in names, names
    dirs = _declared_dirs(payload)
    for d in ("src/pages", "src/styles", "src/assets", "src/components"):
        assert d in dirs, (d, dirs)


def test_traversal_rejected():
    """مسارات الهروب تُرفض صراحة."""
    payload = {
        "description": "أنشئ ../etc/passwd و ../../tmp/x/ مجلدات",
        "acceptance_criteria": [],
        "context_goal": "",
    }
    dirs = _declared_dirs(payload)
    assert all(".." not in d for d in dirs), dirs
    names = _deliverable_names({"description": "../x/../../evil.css",
                                "acceptance_criteria": [],
                                "context_goal": ""})
    assert all(".." not in n for n in names), names
