#!/usr/bin/env python3
"""AES-DESIGN-IMPL-012 — seed realistic demo data into the isolated test DB."""
import sys

sys.path.insert(0, "/home/z/my-project/repo/src")

from sqlalchemy.orm import sessionmaker  # noqa: E402

from persistence.database import build_engine, init_db  # noqa: E402
from persistence.models import Conversation, Message  # noqa: E402

DB = "/home/z/my-project/repo/runtime/ui-012.db"

engine = build_engine(DB)
init_db(engine)
Session = sessionmaker(bind=engine)
s = Session()

s.query(Message).delete()
s.query(Conversation).delete()

c1 = Conversation(title="بناء منصة OSINT معيارية بلغة Python", mode="project")
c2 = Conversation(title="مراجعة معمارية الركيزة المعزولة", mode="chat")
c3 = Conversation(title="تقرير جيوسياسي أسبوعي", mode="task")
s.add_all([c1, c2, c3])
s.flush()

msgs = [
    (c1.id, "user", "أريد بناء منصة OSINT معيارية تبدأ بهيكل قابل للتوسع وتنتهي بوحدات جمع بيانات أساسية من مصادر عامة."),
    (c1.id, "assistant",
     "سأبدأ بتأسيس الهيكل والعقود أولًا، ثم وحدات الجمع والتطبيع، وأخيرًا اختبار التكامل.\n\n"
     "| المرحلة | الحالة | المخرج |\n|---|---|---|\n"
     "| تأسيس الهيكل | مكتملة | هيكل مشروع قابل للتوسع |\n"
     "| وحدات الجمع | قيد التنفيذ | جامعو RSS والموقع الرسمي |\n"
     "| اختبار التكامل | معلقة | تقرير نهائي بتغطية كاملة |\n\n"
     "الخطوة الحالية: `collector/rss.py` يعمل داخل الرمل ويحفظ الأدلة."),
    (c2.id, "user", "راجع معمارية الركيزة المعزولة على المضيف."),
    (c2.id, "assistant",
     "الركيزة تعتمد namespaces + seccomp عبر bubblewrap — المثبت فعليًا على المضيف.\n\n"
     "```bash\nbwrap --unshare-net --ro-bind /usr /usr python3 -c 'print(1)'\n```"),
    (c3.id, "user", "جهّز تقريرًا جيوسياسيًا أسبوعيًا بالعربية مع PDF."),
    (c3.id, "assistant", "اكتمل جمع المصادر وبدأ التوليد — سيُسلَّم PDF عربي بتنسيق نهائي."),
]
for cid, role, body in msgs:
    s.add(Message(conversation_id=cid, role=role, content=body))

s.commit()
print("seeded:", DB)
