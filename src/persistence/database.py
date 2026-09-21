"""قاعدة البيانات — SQLite مبسطة، تهيئة نظيفة عند الإقلاع."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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


#: ترحيلات صغيرة معلنة (الأمر 006 §14) — عمود واحد لكل إصدار.
#: create_all لا يعدّل جدولًا قائمًا؛ الترحيل هنا صريح ومحدود.
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    # (وصف، SQL) — conversations.mode لقواعد أنشئت قبل الأمر 006
    (
        "conversations.mode",
        "ALTER TABLE conversations ADD COLUMN mode VARCHAR(10) "
        "DEFAULT 'chat' NOT NULL",
    ),
)


def init_db(engine) -> None:
    """إنشاء الجداول إن لم تكن موجودة + ترحيلات معلنة — آمن للتكرار."""
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    columns = {
        col["name"] for col in inspector.get_columns("conversations")
    }
    with engine.begin() as connection:
        for name, sql in _MIGRATIONS:
            table, column = name.split(".")
            if column in columns:
                continue
            if table in inspector.get_table_names():
                connection.execute(text(sql))


def make_session_factory(engine) -> type[Session]:
    """مصنع الجلسات — جلسة قصيرة لكل طلب."""
    return sessionmaker(bind=engine, expire_on_commit=False)
