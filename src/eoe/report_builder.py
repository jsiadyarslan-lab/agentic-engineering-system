"""باني التقارير — §8 من الأمر الرابع المعدل (و§5 من الأصل).

يبني التقرير من ``report_template`` حرفيًا: نفس الحقول، نفس الترتيب،
نفس العناوين. التحقق الآلي قبل التسليم:

1. كل حقل مطلوب موجود — حقل ناقص = رفض.
2. لا حقل زائد — القالب عقد لا قائمة اقتراحات.
3. حقول الأدلة خالية من القرارات (فحص OwnerGate نفسه يُعاد هنا).
4. ``VERDICT ∈ {PASS, HARD STOP}`` — لا قيمة أخرى تمر.

في أوضاع الكتابة تُضاف الحقول الإلزامية الثلاثة (§8 من الأمر المعدل):
``GRANTS_USED`` و``FILES_CHANGED`` (بها sha قبل/بعد) و``PUSHES``
(sha قبل/بعد + شهادة الاسترجاع أو NONE). التقرير الناتج artifact
موقّع الهاش — أي تغيير بعده يُكشف بإعادة الحساب.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from eoe.owner_gate import OwnerDecisionViolation, _scan_value


VALID_VERDICTS = ("PASS", "HARD STOP")

#: حقول أوضاع الكتابة الإلزامية — تُطلب في WRITE_LOCAL/WRITE_AND_PUSH.
WRITE_MANDATORY_FIELDS = ("GRANTS_USED", "FILES_CHANGED", "PUSHES")


class ReportRejected(Exception):
    """التقرير خالف القالب — يُرفض بسبب مقروء قبل التسليم."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Report:
    """تقرير نهائي — نص حرفي بالقالب + توقيع هاش + بيانات بنيوية."""

    verdict: str
    lines: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    template: tuple[str, ...] = ()
    artifact_hash: str = ""
    write_mode: bool = False

    def text(self) -> str:
        return "\n".join(self.lines)

    def first_lines(self, count: int = 20) -> str:
        return "\n".join(self.lines[:count])


def build_report(
    *,
    template: list[str] | tuple[str, ...],
    values: dict[str, Any],
    verdict: str,
    write_mode: bool = False,
) -> Report:
    """بناء التقرير من القالب والقيم — التحقق الآلي ثم التوقيع."""
    if verdict not in VALID_VERDICTS:
        raise ReportRejected(
            f"VERDICT غير صالح: {verdict!r} — المسموح {VALID_VERDICTS}"
        )
    required = list(template)
    if not required:
        raise ReportRejected("قالب فارغ — لا تقرير بلا عقد قالب")
    missing = [name for name in required if name not in values]
    if missing:
        raise ReportRejected(f"حقول ناقصة عن القالب: {missing}")
    extra = [name for name in values if name not in required]
    if extra:
        raise ReportRejected(f"حقول زائدة عن القالب: {extra}")
    if write_mode:
        absent_mandatory = [
            name for name in WRITE_MANDATORY_FIELDS if name not in required
        ]
        if absent_mandatory:
            raise ReportRejected(
                f"قالب وضع الكتابة ينقصه الحقول الإلزامية: {absent_mandatory}"
            )
    for name, value in values.items():
        try:
            _scan_value(
                value if isinstance(value, dict) else {"text": str(value)},
                f"field:{name}",
                name,
            )
        except OwnerDecisionViolation as violation:
            raise ReportRejected(
                f"قرار مالك في حقل أدلة: {violation}"
            ) from violation

    lines: list[str] = []
    rendered: dict[str, str] = {}
    for name in required:
        rendered[name] = (
            " ".join(str(values[name]).split())
            if not isinstance(values[name], str) or "\n" not in values[name]
            else values[name]
        )
        lines.append(f"{name}: {rendered[name]}")
    artifact_hash = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return Report(
        verdict=verdict,
        lines=lines,
        fields=rendered,
        template=tuple(required),
        artifact_hash=artifact_hash,
        write_mode=write_mode,
    )
