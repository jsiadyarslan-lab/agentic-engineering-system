"""كيانات الجاهزية الدائمة (الأمر 009 §2+§20 + إضافة 008 §2).

عائلتان:
- tool_invocations: سجل كل استدعاء أداة حقيقي (ToolEvidence) — الفشل
  والنجاح سواء، transport منفصل عن usability، بلا أسرار أبدًا.
- capability_records: سجل القدرات وقراءات المسبارات (status/ttl/
  failure_class/…) — القاعدة مصدر الحقيقة، لا الذاكرة.

readiness_status مفردات صادقة مقفلة (009 §2): UNKNOWN/READY/DEGRADED/
NOT_READY/UNAVAILABLE/DISABLED + STALE عند انتهاء الصلاحية (§24).
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from persistence.models import Base

READINESS_STATUSES: tuple[str, ...] = (
    "UNKNOWN",       # لم يُفحص بعد
    "READY",         # مسبار حقيقي نجح (لا وجود إعداد — 009 §27)
    "DEGRADED",      # يعمل مع تحفظ (بطء/نتائج جزئية)
    "NOT_READY",     # فُحص وفشل بسبب معروف
    "UNAVAILABLE",   # غير منفذ في هذه البيئة أصلًا
    "DISABLED",      # معطّل بقرار
    "STALE",         # كانت READY وانتهت صلاحيتها — يُعاد الفحص (§24)
)

CAPABILITY_CATEGORIES: tuple[str, ...] = (
    "RESEARCH", "NETWORK", "WEB", "FILESYSTEM", "GIT", "CODE_EXECUTION",
    "SHELL", "PACKAGE_MANAGEMENT", "TESTING", "BUILD", "REPOSITORY",
    "SANDBOX", "LLM", "ARTIFACTS", "PERSISTENCE", "OBSERVABILITY",
)


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class ToolInvocation(Base):
    """سجل استدعاء أداة دائم (إضافة 008 §2 + 009 §20).

    كل استدعاء حقيقي يخلف صفًّا هنا — نجح أم فشل — مع الفصل الصارم
    بين transport_status وresult_status (نجاح HTTP ≠ مادة قابلة
    للاستخدام). لا أسرار: query قد يحتوي نصًا عامًا فقط.
    """

    __tablename__ = "tool_invocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(40), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12))  # SUCCEEDED|FAILED
    transport_status: Mapped[str] = mapped_column(String(12), default="")
    result_status: Mapped[str] = mapped_column(String(12), default="")
    failure_class: Mapped[str] = mapped_column(String(32), default="")
    failure_stage: Mapped[str] = mapped_column(String(24), default="")
    failure_reason: Mapped[str] = mapped_column(String(40), default="")
    query: Mapped[str] = mapped_column(Text, default="")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzable: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    retryable: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    execution_site: Mapped[str] = mapped_column(String(32), default="")
    output_sha256: Mapped[str] = mapped_column(String(64), default="")
    record_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class CapabilityRecord(Base):
    """سجل قدرة واحدة (الأمر 009 §2) — جرد حقيقي لا افتراض وجود.

    readiness_status لا تكون READY إلا بمسبار فعلي ناجح (§27)؛
    expires_at يجعل الجاهزية قابلة للانتهاء (§24) — لا جاهزية أبدية.
    """

    __tablename__ = "capability_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    required: Mapped[int] = mapped_column(Integer, default=1)
    readiness_status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    provider_id: Mapped[str] = mapped_column(String(64), default="")
    configuration_id: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[str] = mapped_column(String(64), default="")
    last_probe_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_success_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_failure_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    failure_class: Mapped[str] = mapped_column(String(32), default="")
    failure_stage: Mapped[str] = mapped_column(String(24), default="")
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[str] = mapped_column(Text, default="{}")
    probe_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=300)
    expires_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


READINESS_TABLES = ("tool_invocations", "capability_records")
