"""نماذج البيانات — ثلاثة جداول بعد الأمر الثاني (هدف دائم: <10 جداول).

v1 حمل 13 جدولًا تراكمت عبر 19 مرحلة. v2 تبدأ بالحد الأدنى الصادق
وتنمو مع الأوامر لا قبلها:

- conversations: المحادثات (المحادثة هي التطبيق)
- messages: الرسائل — بوسم الدور وشارة الحالة الصادقة
- events: سجل نشاط كل دور داخل كل دورة (الأمر الثاني) — مرجع التدقيق
  والواجهة: خطة/حكم مراجعة/تنفيذ مهمة/تحقق/قرار محكَّم/تغيير حالة.
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


class Event(Base):
    """حدث دور واحد داخل دورة — نشاط كل دور يُسجَّل هنا (الأمر الثاني).

    kind: goal | plan | plan_revised | review_verdict | task_execution |
          task_verification | verification_rollup | arbiter_decision |
          state_change | cycle_done | cycle_error | user_verification
    state: الحالة الصادقة التي يحملها الحدث (قيم PlanState) أو الحكم
           الفرعي (NOT_EVIDENCED / STAGNANT) — NULL للأحداث المحايدة.
    payload: تفاصيل الحدث الكاملة JSON (العقد كما رُدَّت) — للتفصيل والعرض.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(64), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(40))
    state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utc_now)


TABLE_COUNT = 3  # هدف دائم: <10 (design-principles.md المبدأ 6)
