"""§10.9 — test_report_shape: التقرير == القالب حرفيًا + حقول WRITE."""
from __future__ import annotations

import pytest

from eoe.report_builder import Report, ReportRejected, build_report


READ_TEMPLATE = ["VERDICT", "MAP", "LESSONS", "HARD STOPS FIRED"]
WRITE_TEMPLATE = [
    "VERDICT", "MAP", "GRANTS_USED", "FILES_CHANGED", "PUSHES",
    "HARD STOPS FIRED",
]


def test_report_matches_template_keys_and_order():
    """نفس الحقول، نفس الترتيب — حرفيًا."""
    report = build_report(
        template=READ_TEMPLATE,
        values={
            "VERDICT": "PASS", "MAP": "13 جدولًا", "LESSONS": "2439",
            "HARD STOPS FIRED": "NONE",
        },
        verdict="PASS",
    )
    assert [line.split(":", 1)[0] for line in report.lines] == READ_TEMPLATE
    assert report.verdict == "PASS"
    assert len(report.artifact_hash) == 64  # sha256 موقّع


def test_missing_field_rejected():
    """حقل ناقص = رفض صريح."""
    with pytest.raises(ReportRejected) as excinfo:
        build_report(
            template=READ_TEMPLATE,
            values={"VERDICT": "PASS", "MAP": "x", "LESSONS": "y"},
            verdict="PASS",
        )
    assert "HARD STOPS FIRED" in str(excinfo.value)


def test_extra_field_rejected():
    """حقل زائد = رفض — القالب عقد لا اقتراحات."""
    with pytest.raises(ReportRejected) as excinfo:
        build_report(
            template=READ_TEMPLATE,
            values={
                "VERDICT": "PASS", "MAP": "x", "LESSONS": "y",
                "HARD STOPS FIRED": "NONE", "BONUS": "غير مصرح",
            },
            verdict="PASS",
        )
    assert "زائدة" in str(excinfo.value)


@pytest.mark.parametrize("bad", ["FAIL", "pass", "OK", "PARTIAL", ""])
def test_verdict_vocabulary_enforced(bad):
    """VERDICT ∈ {PASS, HARD STOP} حصرًا — لا قيمة أخرى تمر."""
    with pytest.raises(ReportRejected):
        build_report(
            template=["VERDICT"],
            values={"VERDICT": bad},
            verdict=bad,
        )


def test_write_mode_mandatory_fields():
    """وضع الكتابة: القالب بلا الحقول الثلاثة الإلزامية = رفض."""
    with pytest.raises(ReportRejected) as excinfo:
        build_report(
            template=["VERDICT", "MAP"],   # بلا GRANTS_USED/FILES_CHANGED/PUSHES
            values={"VERDICT": "PASS", "MAP": "x"},
            verdict="PASS",
            write_mode=True,
        )
    assert "GRANTS_USED" in str(excinfo.value)


def test_write_report_full_shape():
    """تقرير كتابة كامل الشكل — الحقول الثلاثة بالترتيب الحرفي."""
    report = build_report(
        template=WRITE_TEMPLATE,
        values={
            "VERDICT": "PASS",
            "MAP": "خريطة",
            "GRANTS_USED": "PATH_GRANT→docs (كتابة)",
            "FILES_CHANGED": "docs/output.txt",
            "PUSHES": "abc1234→def5678 pushed=True rollback_cert=لا",
            "HARD STOPS FIRED": "NONE",
        },
        verdict="PASS",
        write_mode=True,
    )
    assert report.write_mode is True
    assert [line.split(":", 1)[0] for line in report.lines] == WRITE_TEMPLATE


def test_hash_signature_detects_tampering():
    """أي تغيير بعد البناء يُكشف بإعادة حساب الهاش."""
    report = build_report(
        template=READ_TEMPLATE,
        values={
            "VERDICT": "PASS", "MAP": "13", "LESSONS": "2439",
            "HARD STOPS FIRED": "NONE",
        },
        verdict="PASS",
    )
    original = report.artifact_hash
    report.lines[1] = "MAP: 999"
    import hashlib
    recomputed = hashlib.sha256(
        "\n".join(report.lines).encode("utf-8")
    ).hexdigest()
    assert recomputed != original


def test_report_rejects_decision_in_evidence_field():
    """قرار مالك في حقل أدلة = رفض التقرير كله."""
    with pytest.raises(ReportRejected) as excinfo:
        build_report(
            template=["VERDICT", "DECISIONS"],
            values={
                "VERDICT": "PASS",
                "DECISIONS": {"choice": "أرشفة"},   # قرار متسلل!
            },
            verdict="PASS",
        )
    assert "قرار مالك" in str(excinfo.value)
