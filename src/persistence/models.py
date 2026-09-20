"""نماذج البيانات — جدولان فقط في التأسيس (هدف دائم: <10 جداول).

v1 حمل 13 جدولًا تراكمت عبر 19 مرحلة. v2 تبدأ بالحد الأدنى الصادق
وتنمو مع الأوامر لا قبلها:

- conversations: المحادثات (المحادثة هي التطبيق)
- messages: الرسائل — بوسم الدور وشارة الحالة الصادقة
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.state import PlanState


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class Base(DeclarativeBase):
    """قاعدة SQLAlchemy الموحدة."""


class Conversation(Base):
    """محادثة — وعاء العمل اليومي للمستخدم."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="محادثة جديدة")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


class Message(Base):
    """رسالة داخل محادثة — من المستخدم أو من دور.

    role: "user" | "thinker" | "reviewer" | "implementer" | "verifier" |
          "arbiter" | "coordinator"
    state_badge: شارة الحالة الصادقة إن كانت الرسالة تحمل قرار حالة
                 (قيم PlanState) — NULL للرسائل العادية.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    state_badge: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)

    def badge_is_honest(self) -> bool:
        """الشارة من مفردات الحالات الصادقة حصرًا."""
        return self.state_badge in {s.value for s in PlanState}


TABLE_COUNT = 2  # هدف دائم: <10 (design-principles.md المبدأ 6)
