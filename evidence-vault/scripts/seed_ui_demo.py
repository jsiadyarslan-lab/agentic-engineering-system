# -*- coding: utf-8 -*-
"""بذر بيانات عرض حقيقية لجلسات تصوير الواجهة.

البيانات تُكتب عبر نماذج SQLAlchemy الفعلية للتطبيق (نفس طبقة الحقيقة)،
في قاعدة اختبار معزولة — لا علاقة للإنتاج.
"""
import os
import sys

sys.path.insert(0, "/home/z/my-project/ui-work/src")

from sqlalchemy.orm import sessionmaker  # noqa: E402

from persistence.database import build_engine, init_db  # noqa: E402
from persistence.models import Conversation, Message  # noqa: E402


def seed() -> None:
    engine = build_engine()
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        if s.query(Conversation).count() > 0:
            print("seed: already seeded, skip")
            return

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

        c1 = ids[0]
        msgs = [
            (c1, "user", "لخص لي قرار EXP-04 حول الركيزة في ثلاث نقاط."),
            (c1, "coordinator",
             "**قرار AES-EXP-04 — الركيزة المعزولة:**\n\n"
             "1. **bubblewrap مثبت فعلياً** على aarch64 من مستودع Oracle الرسمي "
             "— ادعاء القيد المعماري سقط بالدليل.\n"
             "2. **عشر قدرات مثبتة** كمستخدم الخدمة: عزل namespaces، حجب الشبكة، "
             "الكتابة في مساحة العمل، والإيقاف بالمهلة.\n"
             "3. **المصنع الآن ينفذ خطوات حقيقية** داخل الرمل ويحفظ الأدلة، "
             "والعقد الجاهزية صادق: لا READY بلا فحص فعلي.\n\n"
             "التفاصيل في `src/substrate/bwrap_substrate.py` والاختبارات خضراء 15/15."),
            (c1, "user", "ممتاز. ماذا عن مهلة الإيقاف؟"),
            (c1, "coordinator",
             "الإيقاف بالمهلة يعمل برمز خروج `124` — نفس عقد timeout(1) "
             "المعروف، والـ watchdog يقتل بقايا العمليات بعد التفكيك."),
        ]
        for cid, role, content in msgs:
            s.add(Message(conversation_id=cid, role=role, content=content))
        s.commit()
        print("seed: done (4 conversations, 4 messages) →",
              os.environ.get("AGenthubV2_DB_PATH", "default db"))
    finally:
        s.close()


if __name__ == "__main__":
    seed()
