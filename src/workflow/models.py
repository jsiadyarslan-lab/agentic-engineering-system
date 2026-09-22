"""كيانات الـworkflow الدائمة (الأمر 007 §3-§8+§12+§13+§17).

القاعدة مصدر الحقيقة الوحيد لحالة المشروع (§9) — لا _task_state في
الذاكرة إلا للبث اللحظي. كل كيان قابل للرجوع إليه بمعرفه:

Project → Plan (versioned) → Phase → Step → Execution → Evidence
                                              ↘ Audit ↘ Retry
Checkpoint (استئناف بعد إعادة التشغيل) · OwnerGate (بوابات المالك)
ProjectEvent (سجل الأحداث الدائم — §17)

الحالات صادقة حصرًا (لا SUCCESS وهمية §3): كل حالة لها مفردات
مقفلة في هذا الملف — الانتقالات في engine.py تتبع جدولًا صريحًا.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from persistence.models import Base


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


# ------------------------------------------------------------------ #
# مفردات الحالات — مقفلة، صادقة (§3+§5+§6)
# ------------------------------------------------------------------ #

PROJECT_STATES: tuple[str, ...] = (
    "DRAFT",                    # أُنشئ، لا خطة بعد
    "PLANNING",                 # توليد الخطة جارٍ
    "AWAITING_OWNER_APPROVAL",  # خطة جاهزة تنتظر اعتماد المالك
    "READY",                    # خطة معتمدة، جاهز للتشغيل
    "RUNNING",                  # الحلقة الذاتية تعمل
    "PAUSED",                   # أوقف مؤقتًا بلقطة قابلة للاستئناف
    "BLOCKED",                  # يحتاج قرار مالك (بوابة مفتوحة)
    "REVISING",                 # مراجعة الخطة جارٍ (v جديد)
    "COMPLETED",                # كل المراحل + التدقيق النهائي نجح
    "VERIFIED",                 # المالك تحقق — القرار النهائي له وحده (§16)
    "STOPPED",                  # أوقفه المالك إيقافًا صريحًا
    "ESCALATED",                # تصعيد بعد ركود/فشل متكرر
)

PLAN_STATES: tuple[str, ...] = (
    "DRAFT", "AWAITING_OWNER_APPROVAL", "ACTIVE", "SUPERSEDED", "REJECTED",
)

PHASE_STATES: tuple[str, ...] = (
    "PLANNED", "READY", "RUNNING", "REVIEWING", "COMPLETED", "FAILED",
    "BLOCKED", "REVISED",
)

STEP_STATES: tuple[str, ...] = (
    "PENDING", "READY", "RUNNING", "COMPLETED", "FAILED", "BLOCKED",
)

EXECUTION_STATES: tuple[str, ...] = (
    "RUNNING", "COMPLETED", "FAILED", "BLOCKED", "STOPPED",
)

#: أنواع بوابات المالك (§14 + 011 §27) — التدخل عند القرارات الجوهرية.
GATE_KINDS: tuple[str, ...] = (
    "PLAN_APPROVAL",            # اعتماد Master Plan
    "PLAN_REVISION_APPROVAL",   # خطة جديدة بعد فشل جوهري
    "PROVIDER_ACTION_REQUIRED", # مزود غير جاهز يتطلب تدخلًا (007.1 §18)
    "PREFLIGHT_BLOCKED",        # حاجب توفير قبل التنفيذ (011 §2+§27) —
                                # يُحل بإعادة الفحص لا بإعادة الاعتماد
    "ESCALATION",               # تصعيد بعد ركود
    "FINAL_VERIFICATION",       # التحقق النهائي (§16)
    "OBJECTIVE_CHANGE",         # تغيير جوهري في الهدف
)

#: حالات البوابة (011 §1-§2) — القرار مفصول عن فتح التنفيذ؛ المفردات
#: والانتقالات في workflow/gates.py (المصدر الوحيد لها).
GATE_STATUS_VALUES: tuple[str, ...] = (
    "PENDING", "APPROVED", "REJECTED", "BLOCKED", "CANCELLED", "EXPIRED",
)

#: أحداث المشروع الدائمة (§17) — كل انتقال مهم سجلٌ باقٍ.
PROJECT_EVENT_KINDS: tuple[str, ...] = (
    "PROJECT_CREATED",
    "PLAN_CREATED",
    "PLAN_REVISED",
    "PLAN_APPROVAL_REQUIRED",
    "PLAN_APPROVED",
    "PHASE_STARTED",
    "STEP_STARTED",
    "EXECUTION_STARTED",
    "EXECUTION_COMPLETED",
    "EXECUTION_FAILED",
    "EVIDENCE_CREATED",
    "TEST_COMPLETED",
    "REVIEW_COMPLETED",
    "AUDIT_COMPLETED",
    "ADJUDICATION_COMPLETED",
    "RETRY_REQUESTED",
    "CHECKPOINT_CREATED",
    "PROJECT_PAUSED",
    "PROJECT_STOPPED",
    "PROJECT_RESUMED",
    "PHASE_COMPLETED",
    "OWNER_GATE_REQUIRED",
    "OWNER_GATE_RESOLVED",
    "PROJECT_COMPLETION_CANDIDATE",
    "PROJECT_VERIFIED",
    "RECOVERY_ASSESSED",        # §19: تقييم الاسترداد عند الإقلاع
    "EXECUTION_BLOCKED",        # 007.1 §17: مزود غير جاهز
    "PREFLIGHT_PASS",           # 011 §2: فحص ما قبل التنفيذ نجح
    "PREFLIGHT_BLOCKED",        # 011 §2+§27: حاجب توفير قبل التنفيذ
    "PREFLIGHT_RECHECKED",      # 011 §19: المالك أعاد الفحص بعد توفير
    "GATE_AUTO_RESOLVED",       # 011 §19: بوابة حُلّت آليًا بعد recheck
    "EXECUTION_POLICY_CHANGED", # 011 §26: المالك غيّر سياسة التنفيذ
)


class Project(Base):
    """مشروع — الكيان الأول (§3): هدف دائم بحالة صادقة ومؤشرات موقع التقدم."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="مشروع جديد")
    objective: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="DRAFT")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    current_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_phase_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    completion_state: Mapped[str] = mapped_column(String(40), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    #: سياسة التنفيذ (011 §26): STRICT_ISOLATED (الافتراضية) أو
    #: COMPATIBLE_LOCAL — قرار المالك، لا تخمين النظام.
    execution_policy: Mapped[str] = mapped_column(
        String(40), default="STRICT_ISOLATED"
    )


class Plan(Base):
    """خطة رئيسية versioned (§4) — غير immutable: v2 تحل محل v1 ولا تمسحها.

    كل مراجعة تحتفظ بسببها وأدلتها (revision_reason/revision_evidence).
    """

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    objective: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[str] = mapped_column(Text, default="[]")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="[]")
    phases: Mapped[str] = mapped_column(Text, default="[]")  # هيكل المراحل JSON
    risks: Mapped[str] = mapped_column(Text, default="[]")
    dependencies: Mapped[str] = mapped_column(Text, default="[]")
    required_owner_decisions: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="DRAFT")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    supersedes_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision_reason: Mapped[str] = mapped_column(Text, default="")
    revision_evidence: Mapped[str] = mapped_column(Text, default="{}")
    approved_by_owner: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Phase(Base):
    """مرحلة (§5) — وحدة مراجعة: تبدأ وتُراجَع عند نهايتها (§15)."""

    __tablename__ = "phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(300), default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")
    current_step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="")
    completed_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Step(Base):
    """خطوة (§6) — الوحدة التي تنفذها الحلقة الذاتية وتعود بعدها."""

    __tablename__ = "steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phase_id: Mapped[int] = mapped_column(Integer, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=1)
    objective: Mapped[str] = mapped_column(Text, default="")
    input: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="[]")
    dependencies: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    current_execution_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    completed_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Execution(Base):
    """تنفيذ خطوة (§7) — دائم: كل محاولة سجلٌ مستقل لا يُعاد استخدامه."""

    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_id: Mapped[int] = mapped_column(Integer, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    finished_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    agent_role: Mapped[str] = mapped_column(String(20), default="implementer")
    provider: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    workspace: Mapped[str] = mapped_column(String(500), default="")
    commit_sha: Mapped[str] = mapped_column(String(80), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    checkpoint_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EvidenceRecord(Base):
    """دليل قابل للرجوع إليه (§8) — ليس ملفًا محليًا فقط.

    evidence.json يبقى artifact في مساحة العمل — وهذا السجل الدائم
    يربطه بالمشروع والخطوة والتنفيذ بمعرفات قابلة للاستعلام.
    """

    __tablename__ = "evidence_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(Integer, index=True)
    step_id: Mapped[int] = mapped_column(Integer, index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    files: Mapped[str] = mapped_column(Text, default="{}")  # {name: {sha256, bytes}}
    tests: Mapped[str] = mapped_column(Text, default="{}")
    commands: Mapped[str] = mapped_column(Text, default="[]")
    artifacts: Mapped[str] = mapped_column(Text, default="[]")
    logs: Mapped[str] = mapped_column(Text, default="[]")
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")
    verification: Mapped[str] = mapped_column(Text, default="{}")
    review_result: Mapped[str] = mapped_column(Text, default="{}")
    audit_result: Mapped[str] = mapped_column(Text, default="{}")
    commit: Mapped[str] = mapped_column(String(80), default="")
    evidence_path: Mapped[str] = mapped_column(String(500), default="")
    evidence_sha256: Mapped[str] = mapped_column(String(80), default="")
    verdict: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class AuditRecord(Base):
    """تدقيق مستقل (§12) — مقارنة ميكانيكية بين المخطط والمنفذ.

    لا يعتمد على نص تقرير المنفذ: findings تُبنى من الأدلة والملفات
    والاختبارات (planned/implemented/tested/evidenced/verified/
    missing/unexpected).
    """

    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    phase_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    findings: Mapped[str] = mapped_column(Text, default="{}")
    evidence_refs: Mapped[str] = mapped_column(Text, default="[]")
    commit_sha: Mapped[str] = mapped_column(String(80), default="")
    tests: Mapped[str] = mapped_column(Text, default="{}")
    verdict: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class RetryRecord(Base):
    """قرار إعادة/مراجعة (§13) — كل قرار مسجل بسببخه وتشخيصه."""

    __tablename__ = "retry_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_id: Mapped[int] = mapped_column(Integer, index=True)
    previous_execution_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    diagnosis: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(String(30), default="RETRY")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class CheckpointRecord(Base):
    """نقطة استئناف (§9) — بعد restart يستمر المشروع من حيث توقف."""

    __tablename__ = "checkpoint_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phase_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_count: Mapped[int] = mapped_column(Integer, default=0)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class OwnerGate(Base):
    """بوابة مالك (§14) — القرارات الجوهرية فقط، والباقي تلقائي."""

    __tablename__ = "owner_gates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="PLAN_APPROVAL")
    reason: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    resolved_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ProjectEvent(Base):
    """حدث مشروع دائم (§17) — لا logs وحدها: كل انتقال مهم سجل باقٍ."""

    __tablename__ = "project_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


#: كل جداول الـworkflow — للعد والتحقق البنيوي.
WORKFLOW_TABLES = (
    Project, Plan, Phase, Step, Execution, EvidenceRecord, AuditRecord,
    RetryRecord, CheckpointRecord, OwnerGate, ProjectEvent,
)
