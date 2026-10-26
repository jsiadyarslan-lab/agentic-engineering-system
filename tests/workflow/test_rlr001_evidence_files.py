"""RLR-001 §4d-4 — أدلة تكرارية بمفاتيح نسبية + مطابقة مدقق مسارية."""
from workflow.auditor import _check_criterion, _criterion_files
from workflow.engine import _files_with_sha


def test_files_with_sha_recursive_relative(tmp_path):
    """css/main.css المتداخل يدخل الأدلة بمفتاحه النسقي."""
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "main.css").write_text(":root{}", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "_versions").mkdir()
    (tmp_path / "_versions" / "main.css.v1").write_text("old",
                                                        encoding="utf-8")
    (tmp_path / "evidence.json").write_text("{}", encoding="utf-8")

    files = _files_with_sha(str(tmp_path))
    assert "css/main.css" in files, files
    assert "package.json" in files, files
    assert "evidence.json" not in files
    assert not any(k.startswith("_versions/") for k in files), files
    assert files["css/main.css"]["bytes"] == 7


def test_auditor_matches_pathed_criterion():
    """معيار «css/main.css موجود» يُطابق مفتاح css/main.css."""
    ev = {"files": {"css/main.css": {"sha256": "a", "bytes": 600},
                    "package.json": {"sha256": "b", "bytes": 10}}}
    assert _check_criterion("css/main.css موجود ويحتوي :root", ev) is True
    assert _check_criterion("حجم css/main.css > 500 بايت", ev) is True


def test_auditor_extracts_full_path_not_basename():
    """الاستخراج يلتقط المسار كاملاً لا الاسم بعد الشرطة."""
    assert _criterion_files("css/main.css موجود") == ["css/main.css"]
    assert _criterion_files("src/styles/base.css يحدد") == \
        ["src/styles/base.css"]


def test_auditor_missing_still_honest():
    """ملف مذكور وغير موجود = مفقود (لا نجاح زائف)."""
    ev = {"files": {"css/other.css": {"sha256": "a", "bytes": 1}}}
    assert _check_criterion("css/main.css موجود", ev) is False
