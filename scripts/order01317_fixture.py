# -*- coding: utf-8 -*-
"""البيانات المعتمدة لمهمة 013.17 + مدقق مطابقة مستقل صفًا بصف.

الأمر 013.17 D1: بيانات ORDER013.13 الأصلية حرفيًا — بالأعمدة والصفوف
والترتيب والتواريخ والمبالغ نفسها. هذا الوحدة المصدر الوحيدة للحقيقة:

  1. ``APPROVED_CSV``  — النص الحرفي المعتمد (header + 6 صفوف).
  2. ``verify_fixture`` — مقارنة ميكانيكية مستقلة: ملف فعلي مقابل
     المعتمد، صفًا بصف وبالترتيب. تفشل عند غياب عمود date أو تغيّر أي
     تاريخ/فئة/مبلغ أو ترتيب أو عدد السجلات. لا تكتفي بالإجماليات
     أبدًا — الإجماليات فحص ثانوي إضافي بعد تطابق الصفوف.

واجهة الأوامر:
    python scripts/order01317_fixture.py <transactions.csv>
خروج 0 عند المطابقة الكاملة، و1 مع JSON النتائج عند أي انحراف.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from decimal import Decimal
from pathlib import Path

#: البيانات المعتمدة حرفيًا (ORDER013.13 ← 013.17 D1) — لا تعديل يُسمح
#: به هنا أبدًا: أي تغيير يبطل أمر 013.13 وأمر 013.17 معًا.
APPROVED_CSV = """date,category,amount
2026-10-01,food,12.50
2026-10-02,travel,30.00
2026-10-03,food,7.50
2026-10-04,tools,20.00
2026-10-05,travel,10.00
2026-10-06,food,5.00
"""

#: القيم المرجعية الصحيحة (ثانوية — بعد تطابق الصفوف صفًا بصف)
REFERENCE = {
    "records": 6,
    "food": "25.00",
    "travel": "40.00",
    "tools": "20.00",
    "total": "85.00",
}

HEADER = ["date", "category", "amount"]


def _parse_rows(text: str) -> list[list[str]]:
    """تحليل CSV ببساطة صارمة: خلايا مقصوصة، بلا تجاهل أسطر فارغة جزئية."""
    rows: list[list[str]] = []
    for row in csv.reader(io.StringIO(text)):
        if not row or all(not cell.strip() for cell in row):
            continue
        rows.append([cell.strip() for cell in row])
    return rows


def approved_rows() -> list[list[str]]:
    """صفوف المعتمد (header أولاً) — من النص الحرفي أعلاه."""
    return _parse_rows(APPROVED_CSV)


def verify_fixture(path: str | Path) -> dict:
    """مقارنة ميكانيكية صفًا بصف للملف الفعلي مقابل المعتمد.

    يعيد تقريرًا (dict): ``ok`` و``findings`` (كل انحراف بحقله وترتيبه)
    و``totals`` (فحص ثانوي بعد المطابقة). لا استثناءات: كل خلل يصير
    نتيجة موثقة.
    """
    findings: list[dict] = []
    target = Path(path)
    if not target.is_file():
        return {"ok": False, "findings": [{
            "kind": "missing_file", "detail": str(target),
        }], "totals": None}
    text = target.read_text(encoding="utf-8-sig", errors="replace")
    actual = _parse_rows(text)
    expected = approved_rows()

    exp_header, exp_body = expected[0], expected[1:]
    act_header = actual[0] if actual else []
    act_body = actual[1:] if actual else []

    # (D1-3) العمود date إلزامي: الهيدر يجب أن يطابق حرفيًا
    if act_header != HEADER:
        findings.append({
            "kind": "header_mismatch", "expected": HEADER,
            "actual": act_header,
            "note": "عمود date مطلوب بالترتيب date,category,amount",
        })
    # عدد السجلات
    if len(act_body) != len(exp_body):
        findings.append({
            "kind": "record_count", "expected": len(exp_body),
            "actual": len(act_body),
        })
    # مقارنة صفًا بصف بالترتيب — لا اكتفاء بعدّ ولا بمجاميع
    for idx in range(max(len(exp_body), len(act_body))):
        if idx >= len(exp_body):
            findings.append({
                "kind": "unexpected_row", "row": idx + 1,
                "actual": act_body[idx],
            })
            continue
        if idx >= len(act_body):
            findings.append({
                "kind": "missing_row", "row": idx + 1,
                "expected": exp_body[idx],
            })
            continue
        for col, (e_cell, a_cell) in enumerate(
                zip(exp_body[idx], act_body[idx])):
            if e_cell != a_cell:
                findings.append({
                    "kind": "cell_mismatch", "row": idx + 1,
                    "column": HEADER[col] if col < len(HEADER)
                    else f"col{col}",
                    "expected": e_cell, "actual": a_cell,
                })
        if len(act_body[idx]) != len(exp_body[idx]):
            findings.append({
                "kind": "row_width", "row": idx + 1,
                "expected": len(exp_body[idx]),
                "actual": len(act_body[idx]),
            })

    # فحص ثانوي: الإجماليات محسوبة من الملف الفعلي نفسه
    totals = _totals(act_body)
    return {"ok": not findings, "findings": findings, "totals": totals,
            "compared_rows": len(exp_body),
            "source": "APPROVED_CSV literal in order01317_fixture.py"}


def _totals(rows: list[list[str]]) -> dict:
    """مجاميع من الصفوف (عمود amount بالفئات) — قراءة لا حكم."""
    sums: dict[str, Decimal] = {}
    total = Decimal("0")
    for row in rows:
        if len(row) < 3:
            continue
        try:
            amount = Decimal(row[2])
        except Exception:  # noqa: BLE001 — خلية غير رقمية تُحصى كما هي
            continue
        sums[row[1]] = sums.get(row[1], Decimal("0")) + amount
        total += amount
    out = {k: f"{v:.2f}" for k, v in sorted(sums.items())}
    out["total"] = f"{total:.2f}"
    return out


def totals_match_reference(totals: dict | None) -> list[str]:
    """مطابقة الإجماليات مع القيم المرجعية (ثانوي) — قائمة انحرافات."""
    if totals is None:
        return ["totals: no file"]
    problems: list[str] = []
    for key in ("food", "travel", "tools"):
        if totals.get(key) != REFERENCE[key]:
            problems.append(
                f"{key}: expected {REFERENCE[key]}, got {totals.get(key)}")
    if totals.get("total") != REFERENCE["total"]:
        problems.append(
            f"total: expected {REFERENCE['total']}, got {totals.get('total')}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python order01317_fixture.py <transactions.csv>",
              file=sys.stderr)
        return 2
    report = verify_fixture(argv[1])
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if not report["ok"]:
        return 1
    ref_problems = totals_match_reference(report["totals"])
    if ref_problems:
        print(json.dumps({"totals_reference_mismatch": ref_problems},
                         ensure_ascii=False, indent=1))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
