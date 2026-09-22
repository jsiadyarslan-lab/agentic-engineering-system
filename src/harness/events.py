"""مفردة أحداث الـHarness (012-D) — الأسماء القانونية الموحدة.

طبقة 011 تحفظ أنواعها العليا (PROJECT_EVENT_KINDS في
workflow/models.py — لا تُمس). هذه الوحدة تضيف:

1. **JOB_EVENT_KINDS**: أحداث الوظيفة الدائمة (EngineeringJob) —
   انتقالات الوظيفة فقط، لا ضجيج tick؛ النبضة حقل في صف الوظيفة.

2. **CANONICAL_MAP**: الاسم القانوني المُجرد (namespace/path) لكل
   نوع — لغة واحدة يفهمها الإسقاط والواجهة مهما تكثر الأنواع
   الداخلية: ``plan/approved`` و``evidence/created`` و
   ``owner/gate.requested`` … الأنواع غير المذكورة تمر كما هي.

3. **event_stage()**: المرحلة الهندسية التي ينتمي إليها الحدث في
   سلسلة القبول (OBJECTIVE → PLAN → APPROVAL → PREFLIGHT →
   EXECUTION → EVIDENCE → AUDIT → VERIFICATION) — يستخدمها
   الإسقاط لبناء خط الزمن المرحلي.

القاعدة: إضافة نوع جديد = سطر في المفردة + خريطة canonical؛
استخدام نوع غير معلن في الأحداث الدائمة = خلل بنية يكشفه فحص.
"""

from __future__ import annotations

#: أحداث الوظيفة — انتقالات فقط (012-E). النبضة/العدادات حقول في
#: صف engineering_jobs لا أحداث؛ التفاصيل الكاملة في waiting_detail.
JOB_EVENT_KINDS: tuple[str, ...] = (
    "JOB_QUEUED",          # وُلدت الوظيفة أو أُعيدت للطابور (استئناف)
    "JOB_STARTED",         # بدأت الحلقة الفعلية
    "JOB_WAITING",         # توقفت بأمان: kind=CAPABILITY|WORKER|GATE
    "JOB_RETRYING",        # خطوة فشلت وأعيدت المحاولة
    "JOB_REVISING",        # خطة تُراجع (v جديدة بسياق الفشل)
    "JOB_PAUSED",          # إيقاف المالك كُرّم عند checkpoint
    "JOB_RESUMED",         # استئناف صريح من آخر checkpoint
    "JOB_COMPLETED",       # المشروع VERIFIED — الوظيفة اكتملت حقًا
    "JOB_FAILED",          # فشل صريح (توليد/تنفيذ بلا مخرج)
    "JOB_STOPPED",         # أوقفها المالك نهائيًا
    "JOB_ESCALATED",       # صُعّدت للمالك بلا مسار آلي
    "JOB_INTERRUPTED",     # انقطعت بوفاة العملية — لا حياة كاذبة
    "JOB_RECOVERY_ASSESSED",  # تقييم الاسترداد عند الإقلاع
)

#: الاسم القانوني المجرد لكل نوع دائم — لغة الإسقاط والواجهة.
#: الأنواع غير المذكورة تُمرَّر كما هي (honest passthrough).
CANONICAL_MAP: dict[str, str] = {
    # المشروع والهدف
    "PROJECT_CREATED": "project/created",
    "PROJECT_PAUSED": "project/paused",
    "PROJECT_STOPPED": "project/stopped",
    "PROJECT_RESUMED": "resume/started",
    "PROJECT_COMPLETION_CANDIDATE": "project/completion_candidate",
    "PROJECT_VERIFIED": "project/verified",
    "RECOVERY_ASSESSED": "recovery/assessed",
    # الخطة
    "PLAN_CREATED": "plan/created",
    "PLAN_REVISED": "plan/revised",
    "PLAN_APPROVAL_REQUIRED": "owner/gate.requested",
    "PLAN_APPROVED": "plan/approved",
    # المراحل والخطوات
    "PHASE_STARTED": "phase/started",
    "PHASE_COMPLETED": "phase/completed",
    "STEP_STARTED": "step/started",
    # التنفيذ
    "EXECUTION_STARTED": "execution/started",
    "EXECUTION_COMPLETED": "execution/completed",
    "EXECUTION_FAILED": "execution/failed",
    "EXECUTION_BLOCKED": "execution/blocked",
    "RETRY_REQUESTED": "retry/requested",
    "EXECUTION_POLICY_CHANGED": "policy/changed",
    # الفحص المسبق
    "PREFLIGHT_PASS": "preflight/pass",
    "PREFLIGHT_BLOCKED": "preflight/blocked",
    "PREFLIGHT_RECHECKED": "preflight/rechecked",
    # الأدلة والتدقيق والتحكيم
    "EVIDENCE_CREATED": "evidence/created",
    "TEST_COMPLETED": "verifier/completed",
    "REVIEW_COMPLETED": "review/completed",
    "AUDIT_COMPLETED": "audit/created",
    "ADJUDICATION_COMPLETED": "arbiter/decision",
    "CHECKPOINT_CREATED": "checkpoint/created",
    # بوابات المالك
    "OWNER_GATE_REQUIRED": "owner/gate.requested",
    "OWNER_GATE_RESOLVED": "owner/gate.resolved",
    "GATE_AUTO_RESOLVED": "owner/gate.auto_resolved",
    # الوظيفة (012-E)
    "JOB_QUEUED": "job/queued",
    "JOB_STARTED": "job/started",
    "JOB_WAITING": "job/waiting",
    "JOB_RETRYING": "job/retrying",
    "JOB_REVISING": "job/revising",
    "JOB_PAUSED": "job/paused",
    "JOB_RESUMED": "job/resumed",
    "JOB_COMPLETED": "job/completed",
    "JOB_FAILED": "job/failed",
    "JOB_STOPPED": "job/stopped",
    "JOB_ESCALATED": "job/escalated",
    "JOB_INTERRUPTED": "job/interrupted",
    "JOB_RECOVERY_ASSESSED": "job/recovery_assessed",
}

#: مراحل سلسلة القبول — الترتيب الهندسي الثابت للإسقاط.
CHAIN_STAGES: tuple[str, ...] = (
    "OBJECTIVE",     # المالك والهدف
    "PLAN",          # التوليد والمراجعة
    "APPROVAL",      # قرار المالك على الخطة
    "PREFLIGHT",     # الجاهزية قبل التنفيذ
    "EXECUTION",     # الوظيفة والأدوار والخطوات
    "EVIDENCE",      # الأدلة الميكانيكية
    "AUDIT",         # التدقيق والتحكيم
    "VERIFICATION",  # تحقق المالك النهائي
)

_STAGE_OF_KIND: dict[str, str] = {
    "project/created": "OBJECTIVE",
    "recovery/assessed": "OBJECTIVE",
    "plan/created": "PLAN",
    "plan/revised": "PLAN",
    "owner/gate.requested": "APPROVAL",
    "plan/approved": "APPROVAL",
    "preflight/pass": "PREFLIGHT",
    "preflight/blocked": "PREFLIGHT",
    "preflight/rechecked": "PREFLIGHT",
    "job/queued": "EXECUTION",
    "job/started": "EXECUTION",
    "job/waiting": "EXECUTION",
    "job/retrying": "EXECUTION",
    "job/revising": "PLAN",
    "job/paused": "EXECUTION",
    "job/resumed": "EXECUTION",
    "job/completed": "VERIFICATION",
    "job/failed": "EXECUTION",
    "job/stopped": "EXECUTION",
    "job/escalated": "AUDIT",
    "job/interrupted": "EXECUTION",
    "job/recovery_assessed": "EXECUTION",
    "phase/started": "EXECUTION",
    "phase/completed": "EXECUTION",
    "step/started": "EXECUTION",
    "execution/started": "EXECUTION",
    "execution/completed": "EXECUTION",
    "execution/failed": "EXECUTION",
    "execution/blocked": "EXECUTION",
    "retry/requested": "EXECUTION",
    "policy/changed": "PREFLIGHT",
    "evidence/created": "EVIDENCE",
    "verifier/completed": "EVIDENCE",
    "review/completed": "EVIDENCE",
    "audit/created": "AUDIT",
    "arbiter/decision": "AUDIT",
    "checkpoint/created": "EXECUTION",
    "owner/gate.resolved": "APPROVAL",
    "owner/gate.auto_resolved": "PREFLIGHT",
    "project/paused": "EXECUTION",
    "project/stopped": "EXECUTION",
    "resume/started": "EXECUTION",
    "project/completion_candidate": "VERIFICATION",
    "project/verified": "VERIFICATION",
}


def canonical(kind: str) -> str:
    """الاسم القانوني للنوع — غير المذكور يمر كما هو."""
    return CANONICAL_MAP.get(kind, kind)


def event_stage(kind: str) -> str:
    """مرحلة السلسلة التي ينتمي إليها الحدث — غير المعروف EXECUTION."""
    return _STAGE_OF_KIND.get(canonical(kind), "EXECUTION")


#: أنواع تُعتبر علامة إنجاز للمرحلة (لحساب حالة كل مرحلة).
#: علامة إنجاز EXECUTION هي «مرشح للتحقق» — اكتمال الخطوات
#: والتدقيق النهائي معًا (لا إنجاز جزئي عند خطوة واحدة).
_STAGE_DONE_MARKS: dict[str, tuple[str, ...]] = {
    "OBJECTIVE": ("project/created",),
    "PLAN": ("plan/created", "plan/revised"),
    "APPROVAL": ("plan/approved",),
    "PREFLIGHT": ("preflight/pass",),
    "EXECUTION": ("project/completion_candidate", "project/verified"),
    "EVIDENCE": ("evidence/created",),
    "AUDIT": ("audit/created",),
    "VERIFICATION": ("project/verified",),
}

#: أنواع تُعتبر علامة حجب/انتظار للمرحلة.
_STAGE_WAITING_MARKS: dict[str, tuple[str, ...]] = {
    "PLAN": ("owner/gate.requested",),
    "APPROVAL": ("owner/gate.requested",),
    "PREFLIGHT": ("preflight/blocked",),
    "EXECUTION": ("job/waiting", "execution/blocked", "job/paused",
                  "job/interrupted"),
    "VERIFICATION": ("project/completion_candidate",),
}

#: أنواع فشل حاسمة للمرحلة — الفشل العابر للخطوة الواحدة ليس فشل
#: المرحلة (قد تُعاد فتنجح)؛ الحاسم ما أغلق المسار بلا مخرج.
_STAGE_FAILED_MARKS: dict[str, tuple[str, ...]] = {
    "EXECUTION": ("job/failed", "job/stopped"),
    "PLAN": ("job/failed",),
}


def stage_status(stage: str, canonical_kinds: set[str]) -> str:
    """حالة مرحلة من الأنواع القانونية المرصودة — حتمية خالصة.

    PENDING لم تُرَ بعد / DONE وُلدت علامة إنجازها / WAITING
    علامة انتظارها آخر ما رُؤي لها / FAILED علامة فشلها دون إنجاز /
    ACTIVE بدأت أحداثها دون إنجاز ولا انتظار.
    """
    done = _STAGE_DONE_MARKS.get(stage, ())
    waiting = _STAGE_WAITING_MARKS.get(stage, ())
    failed = _STAGE_FAILED_MARKS.get(stage, ())
    observed = any(k in canonical_kinds for k in done)
    if observed:
        return "DONE"
    if any(k in failed for k in canonical_kinds):
        return "FAILED"
    if any(k in waiting for k in canonical_kinds):
        return "WAITING"
    stage_events = [
        k for k in canonical_kinds if event_stage(k) == stage
    ]
    if stage_events:
        return "ACTIVE"
    return "PENDING"


__all__ = [
    "CANONICAL_MAP",
    "CHAIN_STAGES",
    "JOB_EVENT_KINDS",
    "canonical",
    "event_stage",
    "stage_status",
]
