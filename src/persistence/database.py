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
    # (011 §26) سياسة تنفيذ المشروع — STRICT_ISOLATED الافتراضية
    (
        "projects.execution_policy",
        "ALTER TABLE projects ADD COLUMN execution_policy VARCHAR(40) "
        "DEFAULT 'STRICT_ISOLATED' NOT NULL",
    ),
    # (013 §19) متانة الوظيفة الدائمة — هوية المنفذ والاسترداد
    (
        "engineering_jobs.worker_id",
        "ALTER TABLE engineering_jobs ADD COLUMN worker_id VARCHAR(64) "
        "DEFAULT 'local' NOT NULL",
    ),
    (
        "engineering_jobs.attempt",
        "ALTER TABLE engineering_jobs ADD COLUMN attempt INTEGER DEFAULT 0",
    ),
    (
        "engineering_jobs.last_event_id",
        "ALTER TABLE engineering_jobs ADD COLUMN last_event_id INTEGER "
        "DEFAULT 0",
    ),
    (
        "engineering_jobs.resume_token",
        "ALTER TABLE engineering_jobs ADD COLUMN resume_token VARCHAR(40) "
        "DEFAULT '' NOT NULL",
    ),
)

#: ترحيلات بيانات معلنة (011 §1-§2): بوابات «OPEN» قبل 011 صارت
#: «PENDING» — نفس المعنى (تنتظر المالك) بمفردات الآلة الجديدة.
_DATA_MIGRATIONS: tuple[tuple[str, str, str, str], ...] = (
    # (جدول، عمود، من، إلى)
    ("owner_gates", "status", "OPEN", "PENDING"),
)


def init_db(engine) -> None:
    """إنشاء الجداول إن لم تكن موجودة + ترحيلات معلنة — آمن للتكرار.

    (الأمر 010) تسجيل عائلات الجداول في الـmetadata هنا حصرًا — المكان
    الوحيد الموثق الذي يضمن create_all يرى كل العائلات الخمس:
    المنتج اليومي (هذا الملف) + workflow + providers_registry +
    readiness + execution + harness (012-E: الوظيفة الدائمة).
    الاستيراد من persistence/models كان يسقط دورانًا استيراديًا مع
    العائلات التي تستورد Base منه.
    """
    import execution.models  # noqa: F401,E402 — تسجيل عائلة التنفيذ
    import providers_registry.models  # noqa: F401,E402
    import readiness.models  # noqa: F401,E402
    import workflow.models  # noqa: F401,E402
    import harness.models  # noqa: F401,E402 — (012) عائلة الوظائف

    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as connection:
        for name, sql in _MIGRATIONS:
            table, column = name.split(".")
            if table not in inspector.get_table_names():
                continue
            existing = {
                col["name"] for col in inspector.get_columns(table)
            }
            if column in existing:
                continue
            connection.execute(text(sql))

    # (011 §1-§2) ترحيل بيانات البوابات: OPEN → PENDING — آمن للتكرار
    with engine.begin() as connection:
        for table, column, old, new in _DATA_MIGRATIONS:
            if table in inspector.get_table_names():
                connection.execute(text(
                    f"UPDATE {table} SET {column} = :new "
                    f"WHERE {column} = :old"
                ), {"new": new, "old": old})


def make_session_factory(engine) -> type[Session]:
    """مصنع الجلسات — جلسة قصيرة لكل طلب."""
    return sessionmaker(bind=engine, expire_on_commit=False)
