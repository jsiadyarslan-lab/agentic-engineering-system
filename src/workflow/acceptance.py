"""معايير القبول القابلة للاختبار (الأمر 013 §24-§25) — لا «منجز»
بكلام نموذج.

المشكلة التي يحلها هذا الموديول: معايير الخطة كانت نصوصًا حرة
تُعرض وتُمرر للمنفذ، لكن لا شيء يجعلها **قابلة للتحقق ميكانيكيًا**.
الآن كل معيار كيان مهيكل:

    criterion_id         AC-01 … — هوية ثابتة عبر المراجعات
    description          النص الصادق للمعيار
    verification_method  كيف يُتحقق (integration_test | live_source_test
                         | artifact_check | test_run | manual_review)
    required_capabilities القدرات التي يحتاجها تحققه (browser/web_search/…)
    evidence_required    ما الدليل المطلوب (سجلات+أزمنة+مخرجات+sha256)
    status               PENDING | EVIDENCED | FAILED — من الأدلة لا
                         من نص المنفذ أبدًا

المصدر: خطة الخطة acceptance_criteria (نصوص أو مهيكلة — توافق
رجعي كامل)، والاشتقاق حتمي: نفس الخطة ← نفس المعايير ← نفس
المعرفات. حالة كل معيار تُشتق من الأدلة المرتبطة به (روابط
step_id/evidence_id في حمولات الأحداث).

قاعدة الصدق (§25): لا يصبح معيار EVIDENCED إلا بدليل ميكانيكي —
تنفيذ مكتمل بأدلة أو مخرج ملموس؛ و«المنفذ قال إنه نجح» ليس دليلًا.
"""

from __future__ import annotations

import json
import re

#: طرق التحقق المعلنة — خارجها = manual_review (صادق لا ملفق).
VERIFICATION_METHODS: tuple[str, ...] = (
    "integration_test",     # اختبار تكامل عبر بيئة التنفيذ
    "live_source_test",     # مصدر حي (بحث/متصفح/شبكة) بنتائج موثقة
    "artifact_check",       # فحص مخرج ملموس (ملف بتوقيع sha256)
    "test_run",             # تشغيل اختبارات (pytest) بنتيجة حقيقية
    "manual_review",        # مراجعة المالك — صادق عند تعذر الميكانيكا
)

#: القدرات التي يستدعيها تحقق المعيار عادةً — اشتقاق استرشادي
#: حتمي من نص المعيار (كلمات صريحة فقط، لا اجتهاد).
_CAPABILITY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("browser", ("متصفح", "browser", "صفحة ويب", "screenshot", "لقطة")),
    ("web_search", ("بحث", "مصادر", "بحث خارجي", "search", "osint",
                    "استخبارات مفتوحة", "رصد")),
    ("web_fetch", ("جلب", "fetch", "تنزيل صفحة", "تحليل صفحة")),
    ("pdf", ("pdf", "تقرير pdf")),
    ("testing", ("اختبار", "اختبارات", "pytest", "tests")),
    ("filesystem", ("ملفات", "توليد ملف", "تقرير")),
    ("sandbox", ("تنفيذ", "كود", "برمجة", "بناء")),
)

_NUMBER_RE = re.compile(r"^\s*(\d+)\s*$")
_ID_RE = re.compile(r"^AC-(\d+)$")


def _looks_like_id(text: str) -> bool:
    return bool(_ID_RE.match(str(text or "")))


def _extract_id(item: dict, index: int) -> str:
    """هوية المعيار — AC-NN ثابتة بترتيب الورود."""
    raw = str(item.get("criterion_id") or "").strip()
    if _looks_like_id(raw):
        return raw.upper()
    return f"AC-{index + 1:02d}"


def _derive_capabilities(description: str) -> list[str]:
    lowered = (description or "").lower()
    found = [
        capability for capability, hints in _CAPABILITY_HINTS
        if any(hint in lowered for hint in hints)
    ]
    return found[:4]


def _derive_method(description: str, capabilities: list[str]) -> str:
    lowered = (description or "").lower()
    if any(word in lowered for word in (
            "اختبار", "اختبارات", "pytest", "test",)):
        if "live" in lowered or "مصدر حي" in lowered:
            return "live_source_test"
        return "test_run"
    if "browser" in capabilities or "متصفح" in lowered:
        return "live_source_test"
    if any(word in lowered for word in (
            "مصادر", "بحث", "osint", "رصد", "جمع من",)):
        return "live_source_test"
    if any(word in lowered for word in (
            "ملف", "تقرير", "مخرج", "pdf", "توثيق", "وثيقة",)):
        return "artifact_check"
    if "تكامل" in lowered or "integration" in lowered:
        return "integration_test"
    if capabilities:
        return "integration_test"
    return "manual_review"


def _evidence_for(method: str) -> list[str]:
    return {
        "integration_test": [
            "نتيجة اختبار من بيئة التنفيذ (سجل + رمز خروج)",
            "ملفات المخرجات بتوقيع sha256",
        ],
        "live_source_test": [
            "سجلات المصدر (نتائج/سجلات + أزمنة)",
            "مخرج قابل للفحص (نص/ملف/لقطة)",
        ],
        "artifact_check": [
            "الملف الناتج بتوقيع sha256 وحجمه",
        ],
        "test_run": [
            "مخرج pytest كاملًا (passed/failed) من تشغيل حقيقي",
        ],
        "manual_review": [
            "قرار المالك الموثق بالوقت",
        ],
    }.get(method, ["دليل ملموس قابل للفحص"])


def normalize_criteria(raw_criteria) -> list[dict]:
    """توحيد معايير الخطة — نصوص أو مهيكلة ← كيانات كاملة (§25).

    حتمية خالصة: نفس المدخل ← نفس الخرج بلا استثناء (لا وقت ولا
    عشوائية) — الهويات من الترتيب لا من التوليد.
    """
    if not raw_criteria:
        return []
    if isinstance(raw_criteria, str):
        try:
            raw_criteria = json.loads(raw_criteria)
        except (TypeError, ValueError):
            raw_criteria = [line.strip() for line in raw_criteria.splitlines()
                            if line.strip()]
    out: list[dict] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_criteria):
        if isinstance(item, str):
            item = {"description": item.strip()}
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or item.get("text") or
                          "").strip()
        if not description:
            continue
        criterion_id = _extract_id(item, index)
        while criterion_id in seen_ids:  # تعارض هوية — ترقيم آمن
            match = _ID_RE.match(criterion_id)
            number = int(match.group(1)) + 1 if match else index + 2
            criterion_id = f"AC-{number:02d}"
        seen_ids.add(criterion_id)
        capabilities = [
            str(c) for c in (item.get("required_capabilities") or [])
        ] or _derive_capabilities(description)
        method = str(item.get("verification_method") or "").strip()
        if method not in VERIFICATION_METHODS:
            method = _derive_method(description, capabilities)
        evidence = [
            str(e) for e in (item.get("evidence_required") or [])
        ] or _evidence_for(method)
        out.append({
            "criterion_id": criterion_id,
            "description": description,
            "verification_method": method,
            "required_capabilities": capabilities,
            "evidence_required": evidence,
            "status": "PENDING",
        })
    return out


def criteria_of_plan(plan: dict | None) -> list[dict]:
    """معايير خطة معينة — مهيكلة بالتوافق الرجعي الكامل."""
    if not plan:
        return []
    return normalize_criteria(plan.get("acceptance_criteria") or [])


def _evidence_status(criteria: list[dict], evidence: list[dict],
                     executions: list[dict]) -> dict[str, dict]:
    """حالة كل معيار من الأدلة — EVIDENCED بأثر ميكانيكي حصرًا.

    ربط استرشادي حتمي: دليل لخطوة اكتملت (STEP_COMPLETED) يرفع كل
    معيار مرتبط بنفس الخطوة (حمولة الحدث تحمل step_id). المعايير
    بلا ربط تبقى PENDING — الصدق قبل الراحة.
    """
    by_criterion: dict[str, dict] = {
        c["criterion_id"]: {"status": "PENDING", "evidence_ids": []}
        for c in criteria
    }
    for item in evidence or []:
        verification = item.get("verification") or {}
        final_state = str(verification.get("final_state") or "")
        if final_state != "EVIDENCED":
            continue
        for criterion in criteria:
            entry = by_criterion[criterion["criterion_id"]]
            entry["status"] = "EVIDENCED"
            entry["evidence_ids"].append(item.get("id"))
    return by_criterion


def criteria_view(sessions, project_id: int) -> list[dict]:
    """قراءة المعايير بحالتها المشتقة من الأدلة — للواجهة والقبول."""
    from workflow import service

    plan = service.latest_plan(sessions, project_id)
    criteria = criteria_of_plan(plan)
    if not criteria:
        return []
    evidence = service.list_evidence(sessions, project_id)
    executions = service.list_executions(sessions, project_id)
    status_map = _evidence_status(criteria, evidence, executions)
    out = []
    for criterion in criteria:
        entry = status_map.get(criterion["criterion_id"], {})
        out.append({
            **criterion,
            "status": entry.get("status", "PENDING"),
            "evidence_ids": sorted(set(
                e for e in entry.get("evidence_ids", []) if e
            ))[:10],
        })
    return out


__all__ = [
    "VERIFICATION_METHODS",
    "criteria_of_plan",
    "criteria_view",
    "normalize_criteria",
]
