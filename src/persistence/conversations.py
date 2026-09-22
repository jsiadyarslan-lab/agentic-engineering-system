"""خدمة المحادثات والرسائل (الأمر 006 §14) — قائمة حقيقية لا وهمية.

كل المحادثات والرسائل في SQLite الموجود (لا قاعدة جديدة): الإنشاء
والإلحاق والقائمة والسجل — بلا منطق نقل (ذلك في api.routes).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from persistence.models import Conversation, Message

#: عنوان المحادثة من أول رسالة — مقتطع بنظافة (بلا قطع كلمة).
_TITLE_MAX = 48


def make_title(text: str) -> str:
    """عنوان بسيط من أول رسالة (الأمر 006 §6) — سطر أول مقتطع."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if len(first_line) <= _TITLE_MAX:
        return first_line or "محادثة جديدة"
    cut = first_line[:_TITLE_MAX]
    # لا نقطع كلمة نصفين إن أمكن — آخر فراغ قبل الحد
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def create_conversation(
    sessions, *, title: str, mode: str = "chat"
) -> Conversation:
    """إنشاء محادثة جديدة — النمط معلن من اللحظة الأولى."""
    with sessions() as session:
        conversation = Conversation(
            title=make_title(title), mode=mode if mode in ("chat", "task") else "chat"
        )
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return conversation


def get_conversation(sessions, conversation_id: int) -> Conversation | None:
    with sessions() as session:
        found = session.get(Conversation, int(conversation_id))
        return found


def touch_conversation(sessions, conversation_id: int) -> None:
    """تحديث updated_at — ترتيب القائمة بالأحدث أولًا."""
    from persistence.models import _utc_now

    with sessions() as session:
        found = session.get(Conversation, int(conversation_id))
        if found is None:
            return
        found.updated_at = _utc_now()
        session.commit()


def list_conversations(sessions, limit: int = 100, *,
                       include_archived: bool = False) -> list[dict]:
    """قائمة المحادثات — الأحدث أولًا، بكل حقول العقد (§14).

    (013.4 §18) project_id معلن في كل صف — انتماء المحادثة لمشروع
    لا يمس تاريخها أبدًا. المؤرشفة تُستثنى افتراضيًا (§46).
    """
    with sessions() as session:
        query = select(Conversation).order_by(
            Conversation.updated_at.desc(), Conversation.id.desc()
        )
        if not include_archived:
            query = query.where(Conversation.archived_at.is_(None))
        rows = session.scalars(query.limit(limit)).all()
        return [
            {
                "conversation_id": row.id,
                "title": row.title,
                "mode": row.mode,
                "project_id": getattr(row, "project_id", None),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]


def project_conversations(sessions, project_id: int) -> list[dict]:
    """محادثات مشروع بعينه (013.4 §18) — بيت المشروع الواحد."""
    with sessions() as session:
        rows = session.scalars(
            select(Conversation)
            .where(Conversation.project_id == int(project_id))
            .order_by(Conversation.updated_at.desc())
            .limit(100)
        ).all()
        return [
            {
                "conversation_id": row.id,
                "title": row.title,
                "mode": row.mode,
                "project_id": row.project_id,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]


def rename_conversation(sessions, conversation_id: int, title: str) -> dict:
    """إعادة تسمية محادثة (013.4 §46) — أمر دائم بسيط."""
    from persistence.models import _utc_now

    title = (title or "").strip()
    if not title:
        raise ValueError("العنوان الجديد مطلوب — لا فراغًا")
    with sessions() as session:
        found = session.get(Conversation, int(conversation_id))
        if found is None:
            raise KeyError(f"محادثة غير معروفة: {conversation_id}")
        found.title = title[:200]
        found.updated_at = _utc_now()
        session.commit()
        session.refresh(found)
        return {
            "conversation_id": found.id, "title": found.title,
            "mode": found.mode, "project_id": found.project_id,
        }


def move_conversation_to_project(
        sessions, conversation_id: int, project_id: int | None) -> dict:
    """نقل محادثة إلى مشروع (013.4 §18) — بلا مساس بالتاريخ أبدًا.

    project_id=None يعني الفك من المشروع (عودة للمساحة العامة).
    المشروع يجب أن يكون معروفًا — لا انتماء لمشروع وهمي.
    """
    from persistence.models import _utc_now

    if project_id is not None:
        from workflow import service as workflow_service

        if workflow_service.get_project(sessions, int(project_id)) is None:
            raise KeyError(f"مشروع غير معروف: {project_id}")
    with sessions() as session:
        found = session.get(Conversation, int(conversation_id))
        if found is None:
            raise KeyError(f"محادثة غير معروفة: {conversation_id}")
        found.project_id = int(project_id) if project_id is not None else None
        found.updated_at = _utc_now()
        session.commit()
        session.refresh(found)
        return {
            "conversation_id": found.id, "title": found.title,
            "mode": found.mode, "project_id": found.project_id,
        }


def archive_conversation(sessions, conversation_id: int) -> dict:
    """أرشفة محادثة (013.4 §46) — تختفي من القائمة وتبقى كاملة."""
    from persistence.models import _utc_now

    with sessions() as session:
        found = session.get(Conversation, int(conversation_id))
        if found is None:
            raise KeyError(f"محادثة غير معروفة: {conversation_id}")
        found.archived_at = _utc_now()
        session.commit()
        session.refresh(found)
        return {
            "conversation_id": found.id, "title": found.title,
            "mode": found.mode, "project_id": found.project_id,
            "archived_at": found.archived_at.isoformat(),
        }


def append_message(
    sessions,
    conversation_id: int,
    *,
    role: str,
    content: str,
    state_badge: str | None = None,
) -> Message:
    """إلحاق رسالة + تحديث updated_at للمحادثة (ذرّيًا في جلسة واحدة)."""
    from persistence.models import _utc_now

    with sessions() as session:
        conversation = session.get(Conversation, int(conversation_id))
        if conversation is None:
            raise KeyError(f"محادثة غير معروفة: {conversation_id}")
        message = Message(
            conversation_id=int(conversation_id),
            role=role,
            content=content,
            state_badge=state_badge,
        )
        session.add(message)
        conversation.updated_at = _utc_now()
        session.commit()
        session.refresh(message)
        return message


def conversation_messages(
    sessions, conversation_id: int, limit: int = 200
) -> list[dict]:
    """سجل رسائل محادثة — الأقدم أولًا (لإعادة عرض التاريخ)."""
    with sessions() as session:
        rows = session.scalars(
            select(Message)
            .where(Message.conversation_id == int(conversation_id))
            .order_by(Message.id.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "state_badge": row.state_badge,
                "created_at": row.created_at.isoformat(),
            }
            for row in reversed(rows)
        ]


__all__ = [
    "append_message",
    "conversation_messages",
    "create_conversation",
    "get_conversation",
    "list_conversations",
    "make_title",
]
