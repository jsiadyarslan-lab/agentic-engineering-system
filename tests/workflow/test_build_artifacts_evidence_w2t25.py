"""اختبارات W2-T25 2026-11-01 — نواتج البناء في جرد الأدلة.

الدافع المقيس (الخطوة 1003، التنفيذان 637/638): المعيار «Build produces
/dist/layout-test.html that renders without errors» والبناء أنتج
dist/html/layout-test.html فعلًا (npm run build نجح exit=0) — لكن جرد
الأدلة كان يتخطى dist/ وbuild/ كليًا فرآهما «not found in evidence
facts» مرتين، فاستنفدت المحاولات وأُعيدت كتابة الخطة كلها من
«Empty workspace» (v104→v107 في ثلاث ساعات دون تقدم).

العقد: dist/ وbuild/ يدخلان الجرد (سقف 400 ملف يبقى) — node_modules
و.astro وحدهما يتخطيان. مطابقة basename في المدقق تشبع معيار المسار
المختلف الدليل (dist/layout-test.html ↔ dist/html/layout-test.html)
كما تشبع المسار المطابق تمامًا.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from workflow.auditor import _check_criterion  # noqa: E402
from workflow.engine import _EVIDENCE_SKIP_DIRS, _files_with_sha  # noqa: E402


def test_skip_dirs_no_longer_hide_build_output():
    """dist/ وbuild/ خارج قائمة التخطي — عصيان معايير البناء انتهى."""
    assert "dist" not in _EVIDENCE_SKIP_DIRS
    assert "build" not in _EVIDENCE_SKIP_DIRS
    # الحرجان الثقيلان حقًا يبقيان (آلاف الملفات لا هدف قبول).
    assert "node_modules" in _EVIDENCE_SKIP_DIRS
    assert ".astro" in _EVIDENCE_SKIP_DIRS


def test_files_with_sha_includes_dist_and_build(tmp_path):
    """نواتج البناء تُجرد بمساراتها النسبية، وnode_modules يبقى محجوبًا."""
    (tmp_path / "dist" / "html").mkdir(parents=True)
    (tmp_path / "dist" / "html" / "layout-test.html").write_text(
        "<html></html>", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.css").write_text("a{}", encoding="utf-8")
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "pkg.js").write_text(
        "m", encoding="utf-8")
    files = _files_with_sha(str(tmp_path))
    assert "dist/html/layout-test.html" in files
    assert "build/out.css" in files
    assert not any(k.startswith("node_modules/") for k in files)


def test_build_output_criterion_satisfied_measure_1003():
    """قياس 1003 حرفيًا: المعيار يشير dist/layout-test.html والمنتج
    في dist/html/layout-test.html — مطابقة basename تشبع المطلب."""
    evidence = {"files": {
        "dist/html/layout-test.html": {"sha256": "a" * 64, "bytes": 340},
        "src/css/layout.css": {"sha256": "b" * 64, "bytes": 900},
    }}
    assert _check_criterion(
        "Build produces /dist/layout-test.html that renders without errors",
        evidence)
    assert _check_criterion(
        "dist/html/layout-test.html exists in dist output", evidence)


def test_cap_still_bounds_inventory(tmp_path):
    """سقف 400 ملف يبقى — dist مزدحم لا يبتلع الجرد كله."""
    (tmp_path / "dist").mkdir()
    for i in range(450):
        (tmp_path / "dist" / f"f{i}.html").write_text("x", encoding="utf-8")
    files = _files_with_sha(str(tmp_path))
    assert len(files) <= 400
