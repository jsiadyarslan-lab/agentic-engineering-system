"""المدقق الميكانيكي (الأمر 007 §11+§12) — لا يثق بنص المنفذ.

التحقق هنا ميكانيكي قدر الإمكان: ماذا كان مخططًا (objective +
acceptance_criteria)؟ ماذا نُفذ فعليًا (ملفات الأدلة وsha256)؟ هل
الاختبارات/التحقق نجحت (verdict + final_state)؟ ما المفقود؟ ما
الغير متوقع؟ — الأدلة والملفات والحالة هي primary evidence، لا
تقرير المنفذ النصي.

ثلاثة مستويات:
- audit_step: بعد كل تنفيذ خطوة (planned vs implemented vs evidenced)
- audit_phase: عند اكتمال المرحلة (كل الخطوات + معايير المرحلة §15)
- audit_final: قبل ترشيح الإكمال (سلامة الأدلة + المسائل المعلقة §16)
"""

from __future__ import annotations

import re
from pathlib import Path

#: الرمز الملفي — اسم ملف بامتغال قابل للفحص داخل نص المعيار.
#: (W2-T25) امتدادات البناء كاملة (mdx/astro/js/ts/tsx/...) + حد خلفي
#: (?!\w) يمنع مطابقة md كبادئة لmdx (قياس 431).
_FILE_TOKEN = re.compile(
    r"[\w\-.]+\.(?:mdx|md|pdf|json|txt|csv|py|html?|xml|log|ya?ml|toml"
    r"|svg|png|jpe?g|webp|gif|ico|mjs|cjs|jsx?|tsx?|css|astro|env)(?!\w)"
)

#: (W2-T25) «Console.log» استدعاء JS API لا اسم ملف — الامتداد log
#: يجذبه زورًا من رمز الملفات (قياس 458: script.js يحقق المعيار
#: فعلًا بسطر console.log والمدقق حكم بالمفقود فتصعيد زور).
_JS_API_DOT = re.compile(r"(?i)\bconsole\.log\b")


def _criterion_files(criterion: str) -> list[str]:
    """الملفات المذكورة حرفيًا في المعيار — القابل للفحص الميكانيكي.

    (W2-T25) استدعاءات console.log تُنزَح أولًا — ليست ملفًا.
    """
    return _FILE_TOKEN.findall(_JS_API_DOT.sub(" ", criterion))


def _name_in_files(name: str, files: dict) -> bool:
    """(W2-T25) الاسم المذكور حاضر؟ الجرد بمسارات نسبية (data/articles.json)
    والاستخراج basename — الأساسي أو لاحقة المسار أو الاسم المجرد كلها
    حضور صادق (قياس 257: «articles.json» لم يطابق data/articles.json)."""
    if name in files:
        return True
    return any(
        key.endswith("/" + name) or Path(key).name == name
        for key in files
    )


def _check_criterion(criterion: str, evidence: dict) -> bool:
    """فحص المعيار: كل ملف مذكور فيه موجود ضمن أدلة التنفيذ.

    المعايير التي لا تذكر أي ملف ليست ميكانيكية — تُعلّق (None)
    لا تُمرَّر كذبًا.
    """
    files = evidence.get("files", {}) or {}
    mentioned = _criterion_files(criterion)
    if not mentioned:
        return False
    return all(_name_in_files(name, files) for name in mentioned)


def _criterion_mechanical(criterion: str, evidence: dict) -> bool:
    """هل المعيار قابل للفحص الميكانيكي أصلًا؟ (يذكر ملفًا واحدًا على الأقل)"""
    return bool(_criterion_files(criterion))


def audit_step(step: dict, execution: dict, evidence: dict) -> dict:
    """تدقيق تنفيذ خطوة — planned/implemented/tested/evidenced/missing."""
    criteria = step.get("acceptance_criteria", []) or []
    files = evidence.get("files", {}) or {}
    verdict_value = (evidence.get("verification", {}) or {}).get(
        "verdict", ""
    ) or evidence.get("verdict", "")
    final_state = (evidence.get("verification", {}) or {}).get(
        "final_state", ""
    ) or evidence.get("final_state", "")

    met: list[str] = []
    missing: list[str] = []
    unverifiable: list[str] = []
    for criterion in criteria:
        if _check_criterion(criterion, evidence):
            met.append(criterion)
        elif _criterion_mechanical(criterion, evidence):
            missing.append(criterion)   # ذكر ملفًا موجودًا في الأدلة؟ لا — مفقود
        else:
            unverifiable.append(criterion)

    # الغير متوقع: ملفات أُنتجت لا يذكرها أي معيار
    expected_names = " | ".join(criteria)
    unexpected = [
        name for name in files
        if expected_names and name not in expected_names
    ]

    tested = verdict_value in ("evidenced", "verified") or \
        final_state in ("EVIDENCED", "ADJUDICATED", "VERIFIED")
    evidenced = bool(evidence.get("evidence_sha256")) and bool(files)

    passed = bool(criteria) and not missing and tested and evidenced
    if not criteria:
        # خطوة بلا معايير: الحكم على الأدلة والحالة فقط
        passed = tested and evidenced

    return {
        "planned": {
            "objective": step.get("objective", ""),
            "acceptance_criteria": criteria,
        },
        "implemented": {
            "files": sorted(files.keys()),
            "tool_calls_count": len(evidence.get("tool_calls", []) or []),
            "execution_status": execution.get("status", ""),
        },
        "tested": tested,
        "evidenced": evidenced,
        "verified": final_state in ("EVIDENCED", "ADJUDICATED", "VERIFIED"),
        "missing": missing,
        "unverifiable": unverifiable,
        "unexpected_changes": unexpected,
        "verdict": "PASS" if passed else ("PARTIAL" if met else "FAIL"),
    }


def audit_phase(phase: dict, steps: list[dict], evidences: list[dict]) -> dict:
    """تدقيق المرحلة عند اكتمالها (§15) — COMPLETED/REVISE/BLOCKED/ESCALATE.

    قاعدة صادقة: المرحلة لا تكتمل إلا إذا كانت كل خطواتها COMPLETED
    ولكل منها دليل، ولا يوجد missing في معاييرها القابلة للفحص.
    """
    steps_completed = [s for s in steps if s["status"] == "COMPLETED"]
    steps_failed = [s for s in steps if s["status"] == "FAILED"]
    steps_blocked = [s for s in steps if s["status"] == "BLOCKED"]
    evidences_by_step = {e["step_id"]: e for e in evidences}
    missing_evidence = [
        s["id"] for s in steps_completed if s["id"] not in evidences_by_step
    ]

    phase_criteria = phase.get("acceptance_criteria", []) or []
    all_files = {}
    for evidence in evidences:
        all_files.update(evidence.get("files", {}) or {})
    phase_missing = [
        c for c in phase_criteria
        if _criterion_mechanical(c, {"files": all_files})
        and not _check_criterion(c, {"files": all_files})
    ]

    if steps_blocked:
        verdict = "BLOCKED"
    elif steps_failed or missing_evidence:
        verdict = "REVISE"
    elif phase_missing:
        verdict = "REVISE"
    elif len(steps_completed) == len(steps) and steps:
        verdict = "COMPLETED"
    else:
        verdict = "BLOCKED"

    return {
        "phase_id": phase["id"],
        "steps_total": len(steps),
        "steps_completed": len(steps_completed),
        "steps_failed": len(steps_failed),
        "steps_blocked": len(steps_blocked),
        "missing_evidence_steps": missing_evidence,
        "phase_criteria_missing": phase_missing,
        "verdict": verdict,
    }


def audit_final(project: dict, phases: list[dict], steps: list[dict],
                evidences: list[dict], audits: list[dict]) -> dict:
    """التدقيق النهائي (§16) — شرط الترشيح للتحقق النهائي للمالك.

    الميكانيكا: كل المراحل COMPLETED، لا خطوات معلقة، كل دليل سليم
    (sha256 يعاد التحقق منه من الملف الفعلي حيث أمكن)، ولا تدقيق
    FAIL معلق.
    """
    phases_completed = [p for p in phases if p["status"] == "COMPLETED"]
    phases_pending = [p for p in phases if p["status"] not in
                      ("COMPLETED", "REVISED")]
    steps_pending = [s for s in steps if s["status"] not in
                     ("COMPLETED", "BLOCKED")]
    failed_audits = [a for a in audits if a.get("verdict") == "FAIL"]

    integrity: dict[str, bool] = {}
    for evidence in evidences:
        # سجلات المنع الإدارية (EXECUTION_BLOCKED) توثيق لقرار لا أدلة
        # تنفيذ — لا تدخل فحص السلامة الميكانيكي
        if evidence.get("verdict") == "EXECUTION_BLOCKED" and not \
                evidence.get("evidence_path"):
            continue
        path = evidence.get("evidence_path", "")
        if path and Path(path).is_file():
            import hashlib

            actual = hashlib.sha256(
                Path(path).read_bytes()
            ).hexdigest()
            integrity[str(evidence["id"])] = (
                actual == evidence.get("evidence_sha256")
            )
        else:
            integrity[str(evidence["id"])] = False

    broken_evidence = [k for k, ok in integrity.items() if not ok]

    passed = (
        len(phases_completed) == len(phases)
        and bool(phases)
        and not steps_pending
        and not failed_audits
        and not broken_evidence
    )
    return {
        "phases_total": len(phases),
        "phases_completed": len(phases_completed),
        "phases_pending": [p["id"] for p in phases_pending],
        "steps_pending": [s["id"] for s in steps_pending],
        "failed_audits": [a["id"] for a in failed_audits],
        "evidence_integrity": integrity,
        "broken_evidence": broken_evidence,
        "unresolved_issues": (
            [p["id"] for p in phases_pending]
            + [s["id"] for s in steps_pending]
            + broken_evidence
        ),
        "verdict": "PASS" if passed else "FAIL",
    }
