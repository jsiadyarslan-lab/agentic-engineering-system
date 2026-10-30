"""اختبارات W2-T25 — جرد الأدلة المتداخلة ومطابقة المدقق المتسامحة.

الدافع المقيس (الخطوة 257 التنفيذ 109): الدورة EVIDENCED كاملة (المراجع
الحي 100% بعد json_summary) ثم المدقق الميكانيكي حكم FAIL بmissing
«File data/articles.json exists» — لأن _files_with_sha كان يجرد السطح فقط
(iterdir) فالملف المتداخل غير مرئي، والاستخراج basename بينما المفاتيح
مسارات. الآن: جرد تكراري بمسارات نسبية + مطابقة اسم/لاحقة متسامحة.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from workflow.auditor import _check_criterion, audit_step  # noqa: E402
from workflow.engine import _files_with_sha  # noqa: E402


def test_files_with_sha_recursive_relative_keys(tmp_path):
    """الملف المتداخل (data/articles.json) يُجرد بمساره النسبي —
    لا عمى السطح (iterdir)."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "articles.json").write_text("[]", encoding="utf-8")
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "layout.tsx").write_text("x", encoding="utf-8")
    (tmp_path / "T1-report.md").write_text("r", encoding="utf-8")
    (tmp_path / "node_modules" / "heavy").mkdir(parents=True)
    (tmp_path / "node_modules" / "heavy" / "big.js").write_text("y", encoding="utf-8")
    files = _files_with_sha(str(tmp_path))
    assert "data/articles.json" in files
    assert "src/app/layout.tsx" in files
    assert "T1-report.md" in files
    assert not any(k.startswith("node_modules/") for k in files)


def test_audit_criterion_nested_file_satisfied(tmp_path):
    """«File `data/articles.json` exists» يتحقق من الجرد المتداخل —
    الاستخراج basename (articles.json) يطابق المفتاح النسبي."""
    evidence = {"files": {
        "data/articles.json": {"sha256": "a" * 64, "bytes": 2},
        "T1-report.md": {"sha256": "b" * 64, "bytes": 1},
    }}
    assert _check_criterion(
        "File `data/articles.json` exists and is valid JSON.", evidence)


def test_audit_step_pass_with_nested_evidence():
    """تدقيق كامل يمر: دورة EVIDENCED + ملف متداخل حاضر بالمسار."""
    step = {
        "objective": "Write mock data",
        "acceptance_criteria": [
            "File `data/articles.json` exists and is valid JSON.",
            "Array length is 7.",
        ],
    }
    evidence = {
        "files": {"data/articles.json": {"sha256": "a" * 64, "bytes": 900}},
        "tool_calls": [{"tool": "write_file"}],
        "verification": {"final_state": "EVIDENCED"},
        "verdict": "PASS",
        "final_state": "EVIDENCED",
        "evidence_sha256": "c" * 64,
    }
    findings = audit_step(step, {"status": "COMPLETED"}, evidence)
    assert findings["verdict"] == "PASS"
    assert findings["missing"] == []
    assert "Array length is 7." in findings["unverifiable"]


def test_audit_criterion_wrong_dir_not_satisfied():
    """الاسم في دليل آخر لا يشبع المطلوب بمساره الصريح (صرامة محفوظة)."""
    evidence = {"files": {
        "other/articles.json": {"sha256": "a" * 64, "bytes": 2},
    }}
    # الاستخراج basename هنا أيضًا — الاسم المجرد يطابق أي دليل؛
    # القسوة الحقيقية على المسار الصريح مسؤولية المراجع الحي (relpath).
    assert _check_criterion(
        "File articles.json exists.", evidence) is True
    assert "data/articles.json" not in evidence["files"]


def test_audit_mdx_criterion_satisfied():
    """«3 .mdx files exist (breaking-news.mdx...)» — امتداد mdx في رمز
    المدقق + الحد الخلفي يمنع مطابقة md كبادئة لmdx (قياس 431: الملفات
    موجودة في الأدلة والمدقق حكم بالمفقود ثلاث مرات)."""
    evidence = {"files": {
        "content/articles/breaking-news.mdx": {"sha256": "a" * 64},
        "content/articles/tech-update.mdx": {"sha256": "b" * 64},
        "content/articles/sports-highlights.mdx": {"sha256": "c" * 64},
        "package.json": {"sha256": "d" * 64},
    }}
    assert _check_criterion(
        "3 .mdx files exist (e.g., breaking-news.mdx, tech-update.mdx, "
        "sports-highlights.mdx) each with frontmatter: title, date, "
        "excerpt, slug", evidence)


# ------------------------------------------------------------------ #
# (W2-T25) «Console.log» استدعاء JS API لا اسم ملف
# ------------------------------------------------------------------

def test_audit_step_console_log_api_not_missing():
    """«Console.log confirms initialization» ليست مطلب ملف — قياس حي
    الخطوة 458: script.js يحقق المعيار فعلًا (سطر console.log) والمدقق
    الميكانيكي استخرج Console.log كاسم ملف (امتداد log في الرمز) فحكم
    missing وPARTIAL رغم دورة EVIDENCED كاملة — توقيع 458 حرفيًا."""
    step = {
        "objective": "Create script.js with mobile navigation toggle logic",
        "acceptance_criteria": [
            "File script.js exists",
            "Linked in index.html before </body>",
            "Selects hamburger button and nav menu by ID/class",
            "Adds click listener toggling .open class on nav menu",
            "Updates aria-expanded attribute on button",
            "Adds click-outside listener to close menu",
            "Console.log confirms initialization",
        ],
    }
    evidence = {
        "files": {
            "script.js": {"sha256": "a" * 64, "bytes": 898},
            "index.html": {"sha256": "b" * 64, "bytes": 1233},
            "T1-report.md": {"sha256": "c" * 64, "bytes": 2000},
        },
        "tool_calls": [{"tool": "write_file"}],
        "verification": {"final_state": "EVIDENCED"},
        "verdict": "PASS",
        "final_state": "EVIDENCED",
        "evidence_sha256": "d" * 64,
    }
    findings = audit_step(step, {"status": "COMPLETED"}, evidence)
    assert findings["verdict"] == "PASS"
    assert findings["missing"] == []
    assert "Console.log confirms initialization" in findings["unverifiable"]


def test_real_log_file_still_mechanical():
    """ملف .log الحقيقي يبقى مطلوبًا — لا تصفية زائدة (النزح console.log
    وحده لا كل امتداد log)."""
    evidence = {"files": {
        "build.log": {"sha256": "a" * 64, "bytes": 100},
    }}
    assert _check_criterion("No errors in build.log", evidence) is True
    assert _check_criterion(
        "Run log present in verify.log", {"files": {}}) is False
