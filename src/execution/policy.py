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


def environment_satisfies(environment: dict, policy: str) -> bool:
    """هل البيئة تفي بسياسة التنفيذ؟ (011 §27)

    STRICT_ISOLATED → جاهزة ومعزولة حصرًا؛ COMPATIBLE_LOCAL → أي
    بيئة جاهزة (المعزولة أفضل لكن غيابها لا يحجب).
    """
    if environment.get("status") != "READY":
        return False
    if policy == "STRICT_ISOLATED":
        return bool(environment.get("sandboxed"))
    if policy == "COMPATIBLE_LOCAL":
        return True
    return False


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
    """نص «المطلوب» الصريح في رسائل الحجب (011 §3+§27)."""
    if policy == "STRICT_ISOLATED":
        return (
            "بيئة تنفيذ معزولة جاهزة — Linux/x86_64 (عامل بعيد: "
            "python scripts/execution_worker.py على أي Linux/WSL2، أو "
            "الركيزة المحلية إن كان المضيف Linux)"
        )
    return "أي بيئة تنفيذ جاهزة (حتى المتوافقة غير المعزولة)"


def policy_note(policy: str) -> str:
    """سطر معلن يرافق التنفيذ والنتائج حسب السياسة (011 §26)."""
    if policy == "STRICT_ISOLATED":
        return "السياسة: عزل صارم — التنفيذ داخل بيئة معزولة حصرًا"
    return (
        "السياسة: توافق محلي — التنفيذ قد يكون بلا عزل وهذا معلن؛ "
        "لا يُدّعى عزل في هذا المسار"
    )


__all__ = [
    "POLICIES",
    "POLICY_LABELS",
    "environment_satisfies",
    "is_valid_policy",
    "policy_note",
    "requirement_text",
    "select_environment_for_policy",
]
