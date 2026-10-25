# -*- coding: utf-8 -*-
"""AES-UI-PREMIUM-REDESIGN-007 — بذر بيانات واقعية غنية لجلسات خط الأساس.

يُكتب عبر نماذج SQLAlchemy الفعلية في قاعدة اختبار معزولة (runtime/ui-007.db).
يشمل: عناوين طويلة، نصوص عربية/إنجليزية طويلة، Markdown (جدول+كود+قوائم).
"""
import os
import sys

sys.path.insert(0, "/home/z/my-project/ui007/src")

from sqlalchemy.orm import sessionmaker  # noqa: E402

from persistence.database import build_engine, init_db  # noqa: E402
from persistence.models import Conversation, Message  # noqa: E402


LONG_AR_TITLE = ("مراجعة معمارية شاملة للركيزة المعزولة bubblewrap على مضيف "
                 "Oracle Linux aarch64 وتقييم جاهزية المصنع للإنتاج")

MD_RICH = (
    "**قرار AES-EXP-04 — الركيزة المعزولة:**\n\n"
    "1. **bubblewrap مثبت فعلياً** على aarch64 من مستودع Oracle الرسمي — "
    "ادعاء القيد المعماري سقط بالدليل.\n"
    "2. **عشر قدرات مثبتة** كمستخدم الخدمة: عزل namespaces، حجب الشبكة، "
    "الكتابة في مساحة العمل، والإيقاف بالمهلة.\n"
    "3. **المصنع ينفذ خطوات حقيقية** داخل الرمل ويحفظ الأدلة.\n\n"
    "| القدرة | المسبار | النتيجة |\n|---|---|---|\n"
    "| عزل namespaces | unshare -Umrf | PASS |\n"
    "| حجب الشبكة | --unshare-net | PASS |\n"
    "| مهلة الإيقاف | timeout 124 | PASS |\n\n"
    "المصدر في `src/substrate/bwrap_substrate.py`:\n\n"
    "```python\n"
    "def probe(self) -> ProbeReport:\n"
    "    rc = self._run(['bwrap', '--ro-bind', '/', '/', 'true'])\n"
    "    return ProbeReport(supported=(rc == 0))\n"
    "```\n\n"
    "الاختبارات خضراء 15/15، والعقد صادق: لا READY بلا فحص فعلي."
)

LONG_EN = (
    "The execution engine now persists an immutable evidence chain per cycle. "
    "Each cycle records: the plan digest, the substrate probe report, tool "
    "invocations with exit codes, and the reviewer verdict. Recovery after a "
    "hard stop replays the chain from the last checkpoint instead of "
    "re-running completed steps. This cuts wasted work on resume by ~70% in "
    "the E10 stress runs and makes the audit trail reproducible end-to-end."
)

VERY_LONG_AR = (
    "فيما يلي ملخص تفصيلي للنتائج المرحلية للمهمة الثالثة بعد تنفيذ اثني عشر "
    "اختباراً متكاملاً على بيئة التشغيل الحقيقية: أولاً، ثبت أن طبقة العزل تعمل "
    "باستقرار كامل تحت حمل متزامن يصل إلى ثماني مهام في اللحظة الواحدة دون أي "
    "تسرب في المسارات أو تصاعد صلاحيات؛ ثانياً، أظهرت قياسات الأداء أن زمن "
    "الإقلاع البارد للعامل المتخصص انخفض من تسع وأربعين ثانية إلى إحدى عشرة "
    "ثانية بعد إعادة ترتيب التبعيات وتأجيل تحميل النماذج الثقيلة؛ ثالثاً، "
    "سجلت المراجعة الآلية ثلاث ملاحظات جوهرية على جودة الشيفرة تتعلق بمعالجة "
    "الأخطاء العابرة للحدود بين الوحدات، وكلها أُصلحت ضمن نفس الدورة مع أدلة "
    "اختبار مرتبطة بكل إصلاح. التوصية النهائية: الرفع إلى مرحلة الإنتاج "
    "المحكوم ببوابات المالك الثلاث."
)


def seed() -> None:
    engine = build_engine(os.environ.get("AGenthubV2_DB_PATH"))
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        if s.query(Conversation).count() > 0:
            print("seed: already seeded, skip")
            return

        convs = [
            (LONG_AR_TITLE, "task"),
            ("مهمة: توليد تقرير أداء API الأسبوعي", "task"),
            ("أفكار لوحة معاينة المتصفح", "chat"),
            ("إعداد مزود zai الداخلي ونماذج الأدوار", "chat"),
            ("Performance regression triage — sprint 47", "chat"),
        ]
        ids = []
        for title, mode in convs:
            c = Conversation(title=title, mode=mode)
            s.add(c)
            s.flush()
            ids.append(c.id)

        # الأدوار المرئية في التاريخ: user/assistant فقط (coordinator يُخفى عمداً)
        msgs = [
            (ids[0], "user", "لخص لي قرار EXP-04 حول الركيزة في نقاط موثقة."),
            (ids[0], "assistant", MD_RICH),
            (ids[0], "user", "ممتاز. ماذا عن مهلة الإيقاف والاسترداد؟"),
            (ids[0], "assistant", VERY_LONG_AR),
            (ids[1], "user", "Generate the weekly API performance report with p50/p95 latency."),
            (ids[1], "assistant", LONG_EN),
        ]
        for cid, role, content in msgs:
            s.add(Message(conversation_id=cid, role=role, content=content))
        s.commit()
        print("seed: done (5 conversations, 6 messages) →",
              os.environ.get("AGenthubV2_DB_PATH", "default db"))
    finally:
        s.close()


if __name__ == "__main__":
    seed()
