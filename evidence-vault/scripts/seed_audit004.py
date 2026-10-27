# -*- coding: utf-8 -*-
"""AES-UI-PREMIUM-REDESIGN-004: بذر صريح للقاعدة المعزولة runtime/ui-redesign.db.

build_engine() بلا وسيطة يتجاهل متغير البيئة (سلوك اكتشفناه في التدقيق)؛
هنا نمرر المسار صراحة. نفس نماذج SQLAlchemy الحقيقية — طبقة الحقيقة ذاتها.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/home/z/my-project/ui-work/src")

from sqlalchemy.orm import sessionmaker  # noqa: E402

from persistence.database import build_engine, init_db  # noqa: E402
from persistence.models import Conversation, Message  # noqa: E402

DB = Path("/home/z/my-project/ui-work/runtime/ui-redesign.db")


def seed() -> None:
    engine = build_engine(db_path=DB)
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        existing = s.query(Conversation).count()
        if existing >= 4:
            print(f"explicit-seed: {existing} conversations already present, skip")
            return
        print(f"explicit-seed: topping up from {existing} to 4 conversations")
        convs = [
            ("مراجعة معمارية الركيزة المعزولة", "chat"),
            ("مهمة: توليد تقرير أداء API", "task"),
            ("أفكار لوحة معاينة المتصفح", "chat"),
            ("إعداد مزود zai الداخلي", "chat"),
        ]
        ids = []
        for title, mode in convs:
            c = Conversation(title=title, mode=mode)
            s.add(c)
            s.flush()
            ids.append(c.id)
        msgs = [
            (ids[0], "user", "لخص لي قرار EXP-04 حول الركيزة في ثلاث نقاط."),
            (ids[0], "coordinator",
             "**قرار AES-EXP-04:**\n\n1. bubblewrap مثبت فعلياً على aarch64.\n"
             "2. عشر قدرات مثبتة كمستخدم الخدمة.\n3. المصنع ينفذ خطوات حقيقية "
             "داخل الرمل ويحفظ الأدلة."),
            (ids[0], "user", "ممتاز. ماذا عن مهلة الإيقاف؟"),
            (ids[0], "coordinator",
             "الإيقاف بالمهلة يعمل برمز خروج 124 — نفس عقد timeout(1) المعروف."),
        ]
        for cid, role, content in msgs:
            s.add(Message(conversation_id=cid, role=role, content=content))
        s.commit()
        print(f"explicit-seed: done → 4 conversations, 4 messages in {DB}")
    finally:
        s.close()


if __name__ == "__main__":
    seed()
