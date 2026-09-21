"""نماذج سجل المزودين الدائمة (الأمر 007.1 §2+§5+§10) — ثلاثة جداول.

- ProviderRecord: المزود نفسه (كيان قابل للإنشاء من الواجهة — القائمة
  ليست مغلقة §2).
- ProviderConfiguration: تكوينات المزود — أكثر من Base URL للمزود
  الواحد (§5): «NVIDIA Production» و«NVIDIA Custom Endpoint» مثلًا.
- RoleProviderMapping: ربط كل دور بمزوده وتكوينه ونموذجه — علاقة
  دائمة تُستعاد بعد إعادة التشغيل (§10+§15).

لا مفاتيح API في أي جدول أبدًا: المفاتيح في مخزن الأسرار حصرًا
(§13) — الجداول تحمل secret_ref (اسم مرجعي) لا القيمة.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from persistence.models import Base


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


#: أنماط API المدعومة (§6) — المحول مسؤول عن بناء الطلب.
API_STYLES: tuple[str, ...] = ("openai_compatible", "custom")

#: أنواع المصادقة: bearer (مفتاح في مخزن الأسرار) | none | config_file.
AUTH_TYPES: tuple[str, ...] = ("bearer", "none", "config_file")

#: حالات الجاهزية (§8) — لا تُقال LIVE إلا لنجاح مسبار حقيقي.
READINESS_STATES: tuple[str, ...] = (
    "READY",
    "AUTH_FAILED",
    "NOT_FOUND",
    "RATE_LIMITED",
    "MODEL_NOT_FOUND",
    "NETWORK_ERROR",
    "INVALID_CONFIGURATION",
    "UNSUPPORTED",
    "UNKNOWN_ERROR",
    "UNTESTED",
)


class ProviderRecord(Base):
    """مزود — كيان دائم قابل للإدارة من الواجهة (§2)."""

    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    type: Mapped[str] = mapped_column(String(40), default="custom")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    api_style: Mapped[str] = mapped_column(String(40), default="openai_compatible")
    auth_type: Mapped[str] = mapped_column(String(20), default="bearer")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class ProviderConfiguration(Base):
    """تكوين مزود — Base URL واحد بجاهزيته ونماذجه (§4+§5+§8).

    models: JSON قائمة (نماذج معلنة يدويًا + المكتشفة حيًا) — الإدخال
    اليدوي مسموح دائمًا وdiscovery ليست شرطًا للتشغيل (§12).
    """

    __tablename__ = "provider_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120), default="default")
    base_url: Mapped[str] = mapped_column(String(500))
    api_style: Mapped[str] = mapped_column(String(40), default="openai_compatible")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_model: Mapped[str] = mapped_column(String(200), default="")
    models: Mapped[str] = mapped_column(Text, default="[]")
    #: ملف مصادقة معلن (منشأة الحاوية) — للـauth_type=config_file حصرًا.
    config_file: Mapped[str] = mapped_column(String(500), default="")
    last_readiness_status: Mapped[str] = mapped_column(String(40), default="UNTESTED")
    last_readiness_check: Mapped[_dt.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_readiness_detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class RoleProviderMapping(Base):
    """ربط دور ← مزود + تكوين + نموذج — دائم (§10+§15).

    role: thinker|reviewer|implementer|verifier|arbiter|chat
    configuration: اسم التكوين داخل المزود ("" = التكوين الأساسي).
    """

    __tablename__ = "role_provider_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
