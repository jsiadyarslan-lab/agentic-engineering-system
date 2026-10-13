"""سياسة تنفيذ المهمة (الأمر 011 §26) — عزل صارم أو توافق معلن.

    STRICT_ISOLATED     تطلب بيئة معزولة (sandboxed=True) — Linux/x86_64
                        worker (ركيزة محلية على Linux أو عامل بعيد)؛
                        لا تعمل محليًا بلا عزل مهما كانت الظروف.

    COMPATIBLE_LOCAL    تقبل أي بيئة جاهزة معلنة (حتى غير المعزولة)
                        — تُوسم النتائج «وضع متوافق بلا عزل» صراحة،
                        ولا يُدّعى عزل أبدًا (011 §28: لا خفض للسقف).

السياسة قرار المالك (عمود projects.execution_policy) — لا تخمين:
STRICT_ISOLATED هي الافتراضية لأن النظام هندسي والادعاء أرخص من
الإثبات، والمالك يخفضها صراحة حين يريد التنفيذ المتوافق.
"""

from __future__ import annotations

POLICIES: tuple[str, ...] = ("STRICT_ISOLATED", "COMPATIBLE_LOCAL")

POLICY_LABELS: dict[str, str] = {
    "STRICT_ISOLATED": "عزل صارم — بيئة معزولة إلزامية",
    "COMPATIBLE_LOCAL": "توافق محلي — بلا عزل، معلن",
}


def is_valid_policy(policy: str) -> bool:
    return policy in POLICIES


# ------------------------------------------------------------------ #
# (013.10 §3) التعريف القانوني الواحد للجاهزية — مصدر واحد يقرأه
# بوابة السياسة وحالة العرض والتجهيز والمسبار:
#
#   HEALTHY   نجاح فحص الصحة (إقلاع/كتابة/تنفيذ/التقاط) بأدلة دائمة.
#   ELIGIBLE  صحة ناجحة + مطابقة متطلب السياسة (العزل تحت الصارم).
#   READY     السماح الفعلي ببدء التنفيذ = صحة + أدلة تحقق + أهلية.
#
# ثلاثة مفاهيم منفصلة لا تُدمج أبدًا: «سليمة» ليست «مؤهلة»،
# و«مؤهلة» بلا أدلة تحقق دائمة ليست «جاهزة». (يغلق شق 013.9:
# verify يكتب HEALTHY بينما البوابة تشترط READY فتبقى المهمة
# محجوبة بعد نجاح التحقق نفسه.)
# ------------------------------------------------------------------ #

#: حالات الصحة الصادقة: HEALTHY (نموذج 013.7 §P1) أو READY المخزنة
#: تاريخيًا من النظام القديم — الثانية تعامل كصحة ناجحة عندما تحمل
#: أدلتها (لا تُبطل تلقائيًا، ولا تكفي بلا أدلة لمجرد اسمها).
HEALTH_STATUSES: tuple[str, ...] = ("HEALTHY", "READY")


def health_ok(environment: dict) -> bool:
    """هل فحص الصحة ناجح؟ — HEALTHY أو READY التاريخية، لا غير."""
    return environment.get("status") in HEALTH_STATUSES


def verification_evidence(environment: dict) -> dict:
    """أدلة التحقق الدائمة (013.10 §3-3) — العقد المعتمد:
    last_verified_at حاضر + فحوص مسماة من التحقق الحقيقي كلها ناجحة.

    المصدر last_probe_detail — إما {verify: {checks: [...]}} (رد
    verify) أو {checks: [...]} (to_dict للنتيجة). لا صحة بلا أدلة:
    HEALTHY/READY بلا last_verified_at أو بلا فحوص = سجل غير متحقق
    منه لا يحصل على الجاهزية لمجرد اسمه.
    """
    detail = environment.get("last_probe_detail") or {}
    verify = detail.get("verify") or detail
    checks = verify.get("checks") or []
    checks_ok = bool(checks) and all(
        bool(c.get("ok")) for c in checks if isinstance(c, dict)
    )
    last_verified_at = environment.get("last_verified_at")
    return {
        "last_verified_at": last_verified_at,
        "checks_count": len(checks),
        "checks_ok": checks_ok,
        "complete": bool(last_verified_at) and checks_ok,
    }


def policy_eligibility(environment: dict, policy: str) -> tuple[bool, str]:
    """أهلية البيئة لسياسة معينة — الصحة شرط مسبق للأهلية (013.10 §3-1).

    STRICT_ISOLATED   عزل فعلي (sandboxed) إلزامي — بلا استثناء.
    COMPATIBLE_LOCAL  تقبل غير المعزولة، لكن لا تُهلّك بيئة لم تجتز
                      الصحة بعد (DETECTED ليست مؤهلة).
    تعيد (مؤهلة؟، سبب عدم الأهلية الحرفي).
    """
    if not health_ok(environment):
        status = environment.get("status")
        return False, (
            f"لم تجتز فحص الصحة بعد (status={status!r}) — "
            "الأهلية بعد الصحة في السلم القانوني"
        )
    if policy == "STRICT_ISOLATED":
        if bool(environment.get("sandboxed")):
            return True, ""
        return False, "سليمة لكن غير معزولة — السياسة تطلب عزلًا صارمًا"
    if policy == "COMPATIBLE_LOCAL":
        return True, ""
    return False, f"سياسة غير معروفة: {policy}"


def readiness(environment: dict, policy: str) -> dict:
    """حكم الجاهزية الكامل — التعريف القانوني الواحد (013.10 §3).

    ready = صحة ناجحة ∧ أدلة تحقق دائمة مكتملة ∧ أهلية السياسة.
    blockers قائمة أسباب حرفية قابلة للفحص — تُعرض عند الحجب.
    """
    h = health_ok(environment)
    evidence = verification_evidence(environment)
    eligible, ineligibility = policy_eligibility(environment, policy)
    blockers: list[str] = []
    if not h:
        blockers.append(
            "حالة البيئة "
            f"{environment.get('status')!r} ليست صحة ناجحة "
            f"({'/'.join(HEALTH_STATUSES)})"
        )
    if not evidence["complete"]:
        blockers.append(
            "أدلة التحقق الدائمة ناقصة — يلزم last_verified_at "
            "وفحوص مسماة ناجحة من التحقق الحقيقي"
        )
    if not eligible and h:
        # سبب الأهلية يُذكر صراحة عندما تكون الصحة قائمة (غيره مكرر)
        blockers.append(ineligibility)
    return {
        "health_ok": h,
        "evidence": evidence,
        "eligible": eligible,
        "ready": h and evidence["complete"] and eligible,
        "blockers": blockers,
    }


def environment_satisfies(environment: dict, policy: str) -> bool:
    """هل البيئة جاهزة فعلًا وتفي بسياسة التنفيذ؟ (011 §27 + 013.10 §3)

    التعريف القانوني الموحد — لا يكفي status=="READY" الخام:
    HEALTHY بعد تحقق ناجح بأدلة كاملة تُختار تحت STRICT_ISOLATED،
    وسجل قديم بلا أدلة لا يحصل على الجاهزية لمجرد اسمه.
    """
    return readiness(environment, policy)["ready"]


def select_environment_for_policy(
    environments: list[dict], policy: str,
) -> dict | None:
    """اختيار بيئة وفق السياسة — الافتراضية الجاهزة الموافقة أولًا.

    لا تعيد بيئة لا تفي بالسياسة أبدًا؛ غياب الموافق = None والسبب
    يعرضه preflight (011 §18+§27).
    """
    satisfying = [
        env for env in environments if environment_satisfies(env, policy)
    ]
    if not satisfying:
        return None
    for env in satisfying:
        if env.get("is_default"):
            return env
    # للتوافق المحلي: فضّل المعزولة إن وُجدت (أمان أعلى بلا كلفة إضافية)
    if policy == "COMPATIBLE_LOCAL":
        for env in satisfying:
            if env.get("sandboxed"):
                return env
    return satisfying[0]


def requirement_text(policy: str) -> str:
    """نص «المطلوب» الصريح (011 §3+§27 + 013.2 §2).

    (013.2 §2) هذا نص *متطلب* لا نص *حالة*: ممنوع أن يحمل كلمة
    «جاهزة» أو أي صياغة توحي بحالة تشغيل — فالذي عرض سابقًا تحت
    «غير جاهزة» كان يقول «بيئة معزولة جاهزة» فنشأ التناقض الذي
    رفضه المالك. الصياغة الآن: مطلوب + كيف يوفره المالك.
    """
    if policy == "STRICT_ISOLATED":
        return (
            "المطلوب: بيئة تنفيذ Linux/x86_64 معزولة فعليًا — "
            "الركيزة المحلية على مضيف Linux، أو عامل بعيد على أي "
            "Linux/WSL2 (python scripts/execution_worker.py). "
            "لم تُوفَّر بعد على هذا المضيف"
        )
    return "المطلوب: أي بيئة تنفيذ تعمل فعليًا (حتى المتوافقة غير المعزولة) — لم تُتحقق بعد"


def policy_note(policy: str) -> str:
    """سطر معلن يرافق التنفيذ والنتائج حسب السياسة (011 §26)."""
    if policy == "STRICT_ISOLATED":
        return "السياسة: عزل صارم — التنفيذ داخل بيئة معزولة حصرًا"
    return (
        "السياسة: توافق محلي — التنفيذ قد يكون بلا عزل وهذا معلن؛ "
        "لا يُدّعى عزل في هذا المسار"
    )


__all__ = [
    "HEALTH_STATUSES",
    "POLICIES",
    "POLICY_LABELS",
    "environment_satisfies",
    "health_ok",
    "is_valid_policy",
    "policy_eligibility",
    "policy_note",
    "readiness",
    "requirement_text",
    "select_environment_for_policy",
    "verification_evidence",
]
