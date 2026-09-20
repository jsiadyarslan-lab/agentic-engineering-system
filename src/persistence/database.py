"""قاعدة البيانات — SQLite مبسطة، تهيئة نظيفة عند الإقلاع."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from persistence.models import Base

#: مسار قاعدة البيانات الافتراضي — داخل runtime/ (متجاهل في git).
DEFAULT_DB_PATH = Path("runtime") / "agent_hub_v2.db"


def build_engine(db_path: Path | None = None):
    """إنشاء المحرك — ديركتوريات runtime تُنشأ عند الحاجة."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def init_db(engine) -> None:
    """إنشاء الجداول إن لم تكن موجودة — آمن للتنفيذ المتكرر."""
    Base.metadata.create_all(engine)


def make_session_factory(engine) -> type[Session]:
    """مصنع الجلسات — جلسة قصيرة لكل طلب."""
    return sessionmaker(bind=engine, expire_on_commit=False)
