"""آلة حالة البوابات (الأمر 011 §1-§3+§18-§19) — لا «معتمدة لكن مغلقة».

المشكلة التي يحلها هذا الموديول (011 §1): الواجهة قالت APPROVED ثم
قالت «البوابة ليست مفتوحة» — لأن حالة قرار المالك وحالة فتح
التنفيذ كانتا مفهومًا واحدًا مبتورًا. هنا الفصل الصريح:

    gate.status            قرار المالك على البوابة نفسها
                           PENDING → APPROVED | REJECTED
                           BLOCKED (بيئة/توفير — تُحل بإعادة الفحص)
                           CANCELLED (حُلّت بلا قرار — خطة أحدث مثلًا)

    open_for_execution     مشتق، لا يُخزن (011 §1):
                           APPROVED + preflight PASS + متطلبات مستوفاة
                           = OPEN
                           APPROVED + بيئة التنفيذ غير متاحة
                           = APPROVED_BUT_BLOCKED (وليس «البوابة ليست
                             مفتوحة» الغامضة)

مسار الاستئناف بلا إعادة اعتماد (011 §19): الخطة لم تتغير → قرار
المالك قائم → يكفي إعادة الفحص بعد توفير البيئة:

    BLOCKED → RECHECK → PASS → OPEN → resume
    (لا PLAN_APPROVAL جديدًا أبدًا ما لم تتغير الخطة)
"""

from __future__ import annotations

#: حالات البوابة المخزنة (011 §2) — مقفلة هنا، الانتقالات أسفلها.
GATE_STATUSES: tuple[str, ...] = (
    "PENDING",     # تنتظر قرار المالك (كانت OPEN قبل 011)
    "APPROVED",    # قرر المالك الموافقة
    "REJECTED",    # قرر المالك الرفض
    "BLOCKED",     # تنتظر توفيرًا (بيئة/مزود) — تُحل بإعادة الفحص
    "CANCELLED",   # حُلّت بلا قرار (خطة أحدث/مشروع أوقف نهائيًا)
    "EXPIRED",     # انتهت صلاحيتها بلا قرار
)

#: الانتقالات الصريحة — كل انتقال خارج هذا الجدول مرفوض.
GATE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PENDING": ("APPROVED", "REJECTED", "CANCELLED"),
    "BLOCKED": ("PENDING", "APPROVED", "CANCELLED", "EXPIRED"),
    "APPROVED": (),          # القرار نهائي — إعادة الحل idempotent فقط
    "REJECTED": (),
    "CANCELLED": (),
    "EXPIRED": (),
}

#: حالات بوابة التنفيذ المشتقة (011 §1-§3) — للعرض والقرار.
EXECUTION_GATE_STATES: tuple[str, ...] = (
    "AWAITING_APPROVAL",      # الخطة لم تُعتمد بعد
    "PENDING_PREFLIGHT",      # معتمدة ولم يُفحص التنفيذ بعد
    "OPEN",                   # معتمدة + فحص ناجح = التنفيذ مفتوح
    "APPROVED_BUT_BLOCKED",   # معتمدة + حاجب توفير (بيئة/قدرة)
)

_STATE_LABELS: dict[str, str] = {
    "AWAITING_APPROVAL": "الخطة تنتظر اعتمادك",
    "PENDING_PREFLIGHT": "الخطة معتمدة — فحص ما قبل التنفيذ لم يجري بعد",
    "OPEN": "التنفيذ مفتوح",
    "APPROVED_BUT_BLOCKED": "التنفيذ محجوب مؤقتًا",
    "PENDING": "تنتظر قرارك",
    "APPROVED": "معتمدة",
    "REJECTED": "مرفوضة",
    "BLOCKED": "محجوبة — تنتظر توفيرًا",
    "CANCELLED": "ملغاة",
    "EXPIRED": "منتهية",
}


def state_label(state: str) -> str:
    """تسمية عربية واحدة لكل حالة — الواجهة كلها تقرؤها من هنا."""
    return _STATE_LABELS.get(state, state)


def can_transition(current: str, target: str) -> bool:
    """هل الانتقال مسموح؟ — خارج الجدول = لا (011 §2)."""
    return target in GATE_TRANSITIONS.get(current, ())


def plan_execution_state(
    *,
    plan_approved: bool | None,
    preflight_verdict: str | None,
    blocked_reason: str = "",
    required_environment: str = "",
    owner_action: str = "",
) -> dict:
    """حالة بوابة التنفيذ المشتقة (011 §1+§3) — القرار والعرض معًا.

    plan_approved: هل الخطة الحالية معتمدة من المالك؟
    preflight_verdict: آخر فحص مسبق (PASS | BLOCKED | None).
    blocked_reason/required_environment/owner_action: من نتيجة
    preflight المحجوبة — تصل النصوص الصريحة إلى الواجهة حرفيًا.
    """
    if plan_approved is None:
        return {
            "state": "AWAITING_APPROVAL",
            "open_for_execution": False,
            "label": state_label("AWAITING_APPROVAL"),
            "reason": "لا خطة بعد — أولّد الخطة ثم اعتمدها",
            "required": "",
            "owner_action": "",
        }
    if not plan_approved:
        return {
            "state": "AWAITING_APPROVAL",
            "open_for_execution": False,
            "label": state_label("AWAITING_APPROVAL"),
            "reason": "الخطة بانتظار اعتماد المالك",
            "required": "",
            "owner_action": "اعتمد الخطة أو ارفضها من بطاقة القرار",
        }
    if preflight_verdict is None:
        return {
            "state": "PENDING_PREFLIGHT",
            "open_for_execution": False,
            "label": state_label("PENDING_PREFLIGHT"),
            "reason": "الخطة معتمدة — شغّل فحص ما قبل التنفيذ",
            "required": "",
            "owner_action": "شغّل الفحص المسبق (زر الفحص/التشغيل)",
        }
    if preflight_verdict == "PASS":
        return {
            "state": "OPEN",
            "open_for_execution": True,
            "label": state_label("OPEN"),
            "reason": "الخطة معتمدة والقدرات المطلوبة جاهزة — التنفيذ مفتوح",
            "required": "",
            "owner_action": "",
        }
    # (011 §3) النص المطلوب حرفيًا — لا «البوابة ليست مفتوحة» الغامضة
    return {
        "state": "APPROVED_BUT_BLOCKED",
        "open_for_execution": False,
        "label": state_label("APPROVED_BUT_BLOCKED"),
        "reason": blocked_reason
        or "لا توجد بيئة تنفيذ متوافقة وجاهزة.",
        "required": required_environment
        or "Linux/x86_64 Execution Worker",
        "owner_action": owner_action or (
            "إضافة بيئة تنفيذ ← التحقق منها ← إعادة الفحص ← "
            "استئناف المهمة"
        ),
    }


__all__ = [
    "EXECUTION_GATE_STATES",
    "GATE_STATUSES",
    "GATE_TRANSITIONS",
    "can_transition",
    "plan_execution_state",
    "state_label",
]
