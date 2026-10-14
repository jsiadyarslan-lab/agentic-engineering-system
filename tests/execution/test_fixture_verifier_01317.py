# -*- coding: utf-8 -*-
"""الأمر 013.17 D1-3 — اختبارات المدقق الميكانيكي المستقل للبيانات.

كل اختبار يُجرّب انحرافًا محددًا عن البيانات المعتمدة حرفيًا ويُلزم
المدقق بفشله: غياب عمود date، تغيير تاريخ/فئة/مبلغ، إعادة ترتيب، عدد
خاطئ، صف زائد، ملف فارغ. ويشمل عينة عدم المطابقة التاريخية من 013.16
(category,amount بلا date) لتثبت أن العيب التاريخي يُكتشف آليًا.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from order01317_fixture import (  # noqa: E402
    APPROVED_CSV, REFERENCE, totals_match_reference, verify_fixture,
)


def _write(tmp_path: Path, text: str, name: str = "transactions.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_exact_approved_data_passes(tmp_path):
    """المطابقة الحرفية الكاملة تنجح — والمجاميع المرجعية صحيحة."""
    p = _write(tmp_path, APPROVED_CSV)
    report = verify_fixture(p)
    assert report["ok"], report
    assert report["findings"] == []
    assert totals_match_reference(report["totals"]) == []
    assert report["totals"]["total"] == REFERENCE["total"]
    assert report["totals"]["food"] == REFERENCE["food"]
    assert report["totals"]["travel"] == REFERENCE["travel"]
    assert report["totals"]["tools"] == REFERENCE["tools"]


def test_missing_date_column_fails(tmp_path):
    """غياب عمود date (عيب 013.16 التاريخي) يجب أن يفشل."""
    prior = (
        "category,amount\nfood,10.00\nfood,15.00\ntravel,20.00\n"
        "travel,20.00\ntools,10.00\ntools,10.00\n"
    )
    report = verify_fixture(_write(tmp_path, prior))
    assert not report["ok"]
    kinds = {f["kind"] for f in report["findings"]}
    assert "header_mismatch" in kinds


def test_changed_date_fails(tmp_path):
    """تغيير أي تاريخ (بنفس المجاميع!) يجب أن يفشل — لا اكتفاء بالمجاميع."""
    mutated = APPROVED_CSV.replace("2026-10-02", "2026-11-02")
    report = verify_fixture(_write(tmp_path, mutated))
    assert not report["ok"]
    bad = [f for f in report["findings"] if f["kind"] == "cell_mismatch"]
    assert any(f["column"] == "date" and f["row"] == 2 for f in bad)


def test_changed_amount_fails_even_if_totals_match(tmp_path):
    """تبديل مبالغ داخل نفس الفئة: المجاميع ثابتة والانحراف يُكتشف."""
    mutated = APPROVED_CSV.replace(
        "2026-10-01,food,12.50", "2026-10-01,food,10.00").replace(
        "2026-10-06,food,5.00", "2026-10-06,food,7.50")
    report = verify_fixture(_write(tmp_path, mutated))
    assert not report["ok"]
    bad = [f for f in report["findings"] if f["kind"] == "cell_mismatch"]
    assert len(bad) == 2  # مبالغ الصفين الأول والأخير فقط


def test_reordered_rows_fail(tmp_path):
    """إعادة ترتيب صفوف (نفس المحتوى) يجب أن تفشل."""
    lines = APPROVED_CSV.strip().splitlines()
    header, body = lines[0], lines[1:]
    shuffled = "\n".join([header, body[1], body[0], *body[2:]]) + "\n"
    report = verify_fixture(_write(tmp_path, shuffled))
    assert not report["ok"]
    assert any(f["kind"] == "cell_mismatch" for f in report["findings"])


def test_wrong_record_count_fails(tmp_path):
    """خمسة صفوف بدل ستة يجب أن تفشل (عيب «خمسة سُلّمت» من 013.16)."""
    lines = APPROVED_CSV.strip().splitlines()
    five = "\n".join([lines[0], *lines[1:6]]) + "\n"
    report = verify_fixture(_write(tmp_path, five))
    assert not report["ok"]
    assert any(f["kind"] == "record_count" for f in report["findings"])


def test_extra_row_fails(tmp_path):
    """صف سابع زائد يجب أن يفشل حتى لو توافق المتوسط."""
    extra = APPROVED_CSV + "2026-10-07,food,0.00\n"
    report = verify_fixture(_write(tmp_path, extra))
    assert not report["ok"]
    assert any(f["kind"] == "unexpected_row" for f in report["findings"])


def test_empty_file_fails(tmp_path):
    """ملف فارغ يجب أن يفشل."""
    report = verify_fixture(_write(tmp_path, ""))
    assert not report["ok"]


def test_missing_file_fails(tmp_path):
    """مسار غير موجود يفشل بلا استثناء."""
    report = verify_fixture(tmp_path / "nope.csv")
    assert not report["ok"]
    assert report["findings"][0]["kind"] == "missing_file"


def test_crlf_and_bom_tolerated_cells_still_strict(tmp_path):
    """نهايات أسطر Windows وBOM تُتقبل — الخلايا تبقى صارمة."""
    p = tmp_path / "crlf.csv"
    p.write_bytes(b"\xef\xbb\xbf" + APPROVED_CSV.replace(
        "\n", "\r\n").encode("utf-8"))
    report = verify_fixture(p)
    assert report["ok"], report


def test_totals_reference_detector(tmp_path):
    """كاشف الإجماليات الثانوي يعلن الانحراف عند تغيير مجاميع."""
    mutated = APPROVED_CSV.replace("12.50", "13.50")
    report = verify_fixture(_write(tmp_path, mutated))
    assert not report["ok"]
    problems = totals_match_reference(report["totals"])
    assert problems and "food" in problems[0]
