"""كيان الوظيفة الدائمة (012-E) — EngineeringJob فوق المحرك لا مكانه.

الوظيفة هي «الحلقة الدائمة» ككيان قابل للملاحظة: مشروع ← خطة ←
اعتماد ← فحص مسبق ← **وظيفة تعمل** ← أدوار ← أدلة ← تدقيق ←
بوابات ← استئناف ← تحقق المالك. كل ما تملكه الوظيفة قابل
للاستنباط من الحقيقة الدائمة (مشروع/خطوات/بوابات/أحداث) لكنها
تعطي المسار كله هوية واحدة قابلة للنبض والانقطاع والاستئناف:

- **نبضة** heartbeat_at: أثبت أن الحلقة حية بين الخطوات الطويلة.
- **انتظار صادق** waiting_kind: CAPABILITY (مزود/قدرة) أو WORKER
  (بيئة تنفيذ/عامل) أو GATE (قرار مالك) — مع waiting_detail
  الحرفي (المصفوفة/السلم/إجراء المالك).
- **انقطاع** INTERRUPTED: وفاة العملية لا تترك RUNNING كاذبة.
- **استئناف** resumable: من آخر checkpoint — الخطة لم تتغير فلا
  إعادة اعتماد (011 §19 محفوظ).

الحقيقة تبقى في جداول 011؛ صف الوظيفة ملاحظة منظمة فوقها — لذلك
لا يكرر حالة المشروع بل يحمل حالة الحلقة نفسها.
"""

from __future__ import annotations

import datetime as _dt
import json

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from persistence.models import Base


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


#: حالات الوظيفة (012-E) — مفردة مقفلة.
JOB_STATES: tuple[str, ...] = (
    "QUEUED",             # في الطابور — تشغيل قريب (أو استئناف معلن)
    "RUNNING",            # الحلقة تدور الآن (نبضة حديثة)
    "WAITING_CAPABILITY", # توقفت بأمان: قدرة/مزود غير جاهز
    "WAITING_WORKER",     # توقفت بأمان: بيئة تنفيذ/عامل مطلوب
    "WAITING_GATE",       # توقفت بأمان: قرار مالك معلق
    "RETRYING",           # خطوة فشلت وأعيدت — الحلقة مستمرة
    "REVISING",           # خطة تُراجع بسياق الفشل
    "PAUSED",             # إيقاف المالك كُرّم عند checkpoint
    "COMPLETED",          # المشروع VERIFIED — اكتمال حقيقي وحده
    "FAILED",             # فشل صريح بلا مخرج
    "STOPPED",            # أوقفها المالك نهائيًا
    "ESCALATED",          # صُعّدت بلا مسار آلي
    "INTERRUPTED",        # انقطعت بوفاة العملية — لا حياة كاذبة
)

#: أنواع الانتظار الصادق — حكرًا هذه الثلاثة.
WAITING_KINDS: tuple[str, ...] = ("CAPABILITY", "WORKER", "GATE")

#: الحالات غير النهائية — الوظيفة فيها «حية» أو قابلة للاستئناف.
JOB_NON_TERMINAL: tuple[str, ...] = (
    "QUEUED", "RUNNING", "WAITING_CAPABILITY", "WAITING_WORKER",
    "WAITING_GATE", "RETRYING", "REVISING", "PAUSED", "INTERRUPTED",
)

#: الحالات النهائية — لا انتقال منها إلا بصف جديد.
JOB_TERMINAL: tuple[str, ...] = (
    "COMPLETED", "FAILED", "STOPPED", "ESCALATED",
)


class EngineeringJob(Base):
    """الوظيفة الدائمة — ملاحظة منظمة فوق حالة 011 (لا بديل عنها).

    صف واحد لكل تشغيل/استئناف متصل: التشغيل بعد انتظار (توفير/
    قرار) يعيد استخدام الصف غير النهائي نفسه — استمرارية «توقف
    ثم استئناف من آخر checkpoint». التشغيل بعد حالة نهائية يفتح
    صفًّا جديدًا (تاريخ تشغيلات حقيقي).
    """

    __tablename__ = "engineering_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)

    #: حالة الحلقة من JOB_STATES — ليست حالة المشروع.
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")

    #: نوع الانتظار الصادق ("" حين لا تنتظر) + تفصيله الحرفي.
    waiting_kind: Mapped[str] = mapped_column(String(16), default="")
    waiting_detail: Mapped[str] = mapped_column(Text, default="{}")

    #: مؤشرات الموضع الحالي — من حقول المشروع الدائمة نفسها.
    current_phase_id: Mapped[int] = mapped_column(Integer, nullable=True)
    current_step_id: Mapped[int] = mapped_column(Integer, nullable=True)
    current_execution_id: Mapped[int] = mapped_column(Integer, nullable=True)
    current_role: Mapped[str] = mapped_column(String(24), default="")
    checkpoint_id: Mapped[int] = mapped_column(Integer, nullable=True)

    #: عدادات صادقة — النبضات والإعادات ونقاط الحفظ.
    tick_count: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    checkpoints: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    #: آخر نتيجة tick مختصرة — {action, reason, status, at}.
    last_tick: Mapped[str] = mapped_column(Text, default="{}")

    resumable: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")

    started_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    finished_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_utc_now
    )
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_utc_now, onupdate=_utc_now
    )

    @property
    def waiting_detail_dict(self) -> dict:
        try:
            return json.loads(self.waiting_detail or "{}")
        except (TypeError, ValueError):
            return {}


HARNESS_TABLES = ("engineering_jobs",)
