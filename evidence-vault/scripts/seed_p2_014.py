#!/usr/bin/env python3
"""AES-014 Phase 2 — seed conversation exercising the new message structure:
orphan '?' user msg, code fence, FAILED verdict, long technical reason."""
import sys

sys.path.insert(0, "/home/z/my-project/wt-014/src")

from sqlalchemy.orm import sessionmaker  # noqa: E402

from persistence.database import build_engine, init_db  # noqa: E402
from persistence.models import Conversation, Message  # noqa: E402

DB = "/home/z/my-project/wt-014/runtime/ui-014p2.db"

engine = build_engine(DB)
init_db(engine)
Session = sessionmaker(bind=engine)
s = Session()

s.query(Message).delete()
s.query(Conversation).delete()

c1 = Conversation(title="محادثة اختبار المرحلة الثانية", mode="chat")
s.add(c1)
s.flush()

msgs = [
    (c1.id, "user", "؟"),
    (c1.id, "user", "أريد منك كتابة دالة جمع آمنة بلغة Python."),
    (c1.id, "assistant",
     "إليك دالة جمع آمنة مع فحص الأنواع:\n\n"
     "```python\ndef safe_sum(a, b):\n    if not all(isinstance(x, (int, float)) for x in (a, b)):\n        raise TypeError(\"numbers only\")\n    return a + b\n```\n\n"
     "التحقق قبل الجمع يمنع انصهار الأنواع."),
    (c1.id, "assistant", "تعذر استدعاء النموذج بعد ثلاث محاولات.", "FAILED"),
]
for m in msgs:
    kw = dict(conversation_id=m[0], role=m[1], content=m[2])
    if len(m) > 3:
        kw["state_badge"] = m[3]
    s.add(Message(**kw))

s.commit()
print("seeded:", DB)
