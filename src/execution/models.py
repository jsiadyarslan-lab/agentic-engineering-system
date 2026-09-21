"""بيئات التنفيذ — العائلة الرابعة في القاعدة (الأمر 010 §16-§21).

عائلة EXECUTION بقرار معماري موثق (يحدّث اختبار النحافة معه):

- execution_environments: بيئة تنفيذ مسجلة (LOCAL أو REMOTE_WORKER)
  بحالتها الصادقة وآخر تحقق حقيقي — لا «جاهزة» بلا مسبار.
- research_providers: مزودو البحث (ddg/searx/api) بتكوينهم وقراءة
  مسبارهم — البحث قدرة قابلة للتوفير لا علمًا واحدًا.

الفصل الجوهري (§19): المسبار والمنفذ يستعملان نفس المصدر —
service.resolve_executor() — فلا يمكن أن يقول المسبار READY بينما
المنفذ UNAVAILABLE بلا تفسير؛ كل سجل يحمل environment_id.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from persistence.models import Base

#: حالات البيئة الصادقة (§12 دورة حياة معلنة، §17 ExecutionEnvironment)
ENVIRONMENT_STATUSES: tuple[str, ...] = (
    "UNKNOWN",      # مسجلة ولم تُتحقق بعد
    "READY",        # تحقق حقيقي: إقلاع/كتابة/تنفيذ/التقاط نجحت
    "NOT_READY",    # تحقق فشل بسبب معروف (شبكة/توكن/منصة)
    "UNAVAILABLE",  # الخلفية نفسها غير متاحة على هذه المنصة
)

#: أنواع الخلفيات المدعومة من الكود فعلًا (§16 لا implementation وهمية)
BACKEND_KINDS: tuple[str, ...] = ("LOCAL", "REMOTE_WORKER")


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class ExecutionEnvironment(Base):
    """بيئة تنفيذ واحدة (§17) — كيان دائم له هوية ومسبار وقرار.

    لا تُستعمل بيئة في تنفيذ حقيقي إلا بعد verify ناجح؛ كل تنفيذ
    يسجل environment_id صاحبه فالتناقضات تُفسَّر بلا استثناء (§19).
    """

    __tablename__ = "execution_environments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    backend: Mapped[str] = mapped_column(String(40))  # LOCAL | REMOTE_WORKER
    status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    #: وصف البيئة من الخلفية نفسها (os/arch/runtime/…) — تحديث عند التحقق
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    sandboxed: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[int] = mapped_column(Integer, default=0)
    #: REMOTE_WORKER: رابط العامل؛ LOCAL: فارغ
    endpoint: Mapped[str] = mapped_column(String(300), default="")
    #: REMOTE_WORKER: اسم التوكن في مخزن الأسرار (لا القيمة)
    token_ref: Mapped[str] = mapped_column(String(120), default="")
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    last_verified_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_probe_detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class ResearchProvider(Base):
    """مزود بحث واحد (§25) — البحث قابل للتوفير لا كتلة واحدة.

    kind: search_ddg | search_searx | search_api — كل واحد بتنفيذه
    الحقيقي في research/providers.py؛ المسبار بحث فعلي قابل للتحليل.
    """

    __tablename__ = "research_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_probe_status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    last_probe_at: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_probe_detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


EXECUTION_TABLES = ("execution_environments", "research_providers")

__all__ = [
    "BACKEND_KINDS",
    "ENVIRONMENT_STATUSES",
    "EXECUTION_TABLES",
    "ExecutionEnvironment",
    "ResearchProvider",
]
