# EXECUTION ORDER — JARVIS PRIME
## LESSON POPULATION REALITY AUDIT — مخزن v1 المحلي

### §0 — عقد التنفيذ الصلب

1. المستودع: jsiadyarslan-lab/agent-hub — الفرع: main — الوضع: READ_ONLY.
2. الهدف الوحيد: تدقيق واقعي لتعبيئة الدروس في مخزن v1 المحلي — هل سجل
   تطور الخطط (الدرس المكتسب من كل جولة) يعكس ما حدث فعلًا في المخزن،
   أم أنه تراكم صامت بلا واقع يسنده. التقرير يقرأ الواقع كما هو، لا كما
   ينبغي أن يكون.
3. المنح المطلوبة:
   - PATH_GRANT قراءة على /home/z/my-project/agent-hub/runtime/db
4. أي كتابة على المخزن الهدف أو على مستودع العمل = HARD STOP فوري.
5. انحراف الأساس عن origin/main قبل البدء = HARD STOP.
6. لا استنتاج: الأرقام تُقرأ من المخزن كما هي؛ ما ليس في المخزن لا يدخل
   التقرير. حذف أي جدول من الخريطة = HARD STOP.
7. الأوامر المسموحة: python فقط — كل أمر خارجها = HARD STOP قبل التنفيذ.
8. الدفع: لا دفع — هذا أمر قراءة صرفة.

### §1 — خريطة الجداول

المتطلبات:
1. عدّ صفوف كل جدول في المخزن الهدف وعرض الخريطة كاملة.
2. الخريطة أساس كل ما بعدها؛ أي قسم يُقرأ منه رقم لا يمر عبر هذه
   الخريطة = HARD STOP.
القيود: قراءة فقط. لا استعلام يكتب ولو جدولًا مؤقتًا.
الأوامر:
- python -c "import sqlite3;c=sqlite3.connect('file:/work/agent_hub.db?mode=ro',uri=True);print(sorted((t,c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]) for t in [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]))"

### §2 — سكان الدروس

المتطلبات:
1. إجمالي صفوف plan_evolutions (الدروس) وتوزيعها على الخطط.
2. عدّ الدروس الجديدة (new_count>0) والمحلولة (resolved_count>0)
   والمتكررة (recurring_count>0) — كما هي في الأعمدة، لا إعادة تصنيف.
القيود: القراءة من عمود المخزن مباشرة؛ أي إعادة حساب من خارج المخزن
تُدخل رقمًا غير مسند = HARD STOP.
الأوامر:
- python -c "import sqlite3;c=sqlite3.connect('file:/work/agent_hub.db?mode=ro',uri=True);q=lambda s:c.execute(s).fetchone();print('total',q('SELECT COUNT(*) FROM plan_evolutions')[0]);print('new',q('SELECT COUNT(*) FROM plan_evolutions WHERE new_count>0')[0]);print('resolved',q('SELECT COUNT(*) FROM plan_evolutions WHERE resolved_count>0')[0]);print('recurring',q('SELECT COUNT(*) FROM plan_evolutions WHERE recurring_count>0')[0]);print('plans_with_lessons',q('SELECT COUNT(DISTINCT plan_id) FROM plan_evolutions')[0])"

### §3 — التطابق الزمني

المتطلبات:
1. لكل خطة: هل عدد رسائلها (messages) يتناسب مع عدد جولات تطورها
   (plan_evolutions)؟ عرض الخطة والرسائل والجولات جنبًا إلى جنب.
2. أي جولة تطور بلا رسائل في الخطة نفسها = شاذ، يُدرج في الأدلة
   كما هو — التصنيف قرار مالك (انظر D3).
القيود: الدليل يعرض الحقائق المجاورة بلا حكم عليها.
الأوامر:
- python -c "import sqlite3;c=sqlite3.connect('file:/work/agent_hub.db?mode=ro',uri=True);rows=c.execute('SELECT p.id,p.code,(SELECT COUNT(*) FROM messages m WHERE m.plan_id=p.id),(SELECT COUNT(*) FROM plan_evolutions e WHERE e.plan_id=p.id) FROM plans p ORDER BY p.id').fetchall();print([tuple(r) for r in rows])"

### §4 — الجودة والركود

المتطلبات:
1. متوسط quality_score وreviewer_evolution_score لكل خطة.
2. عدّ الجولات التي رصد فيها المخزن ركودًا (stagnation_detected=1)
   وعدّ البصمات المتكررة (recurring_count الأقصى لكل خطة).
القيود: «ركود» يعني قيمة العمود حصرًا؛ أي تفسير للقيمة خارج المخزن
= HARD STOP.
الأوامر:
- python -c "import sqlite3;c=sqlite3.connect('file:/work/agent_hub.db?mode=ro',uri=True);q=lambda s:c.execute(s).fetchall();print('per_plan_avg',q('SELECT plan_id,ROUND(AVG(quality_score),2),ROUND(AVG(reviewer_evolution_score),2) FROM plan_evolutions GROUP BY plan_id ORDER BY plan_id'));print('stagnant_rounds',q('SELECT COUNT(*) FROM plan_evolutions WHERE stagnation_detected=1')[0][0]);print('max_recurring',q('SELECT plan_id,MAX(recurring_count) FROM plan_evolutions GROUP BY plan_id ORDER BY plan_id'))"

### §5 — الأيتام والانفصال

المتطلبات:
1. جولات تطور لخطط غير موجودة في plans = يتيمة، تُعدّ وتُعرض معرفاتها.
2. رسائل بلا خطة (plan_id=NULL أو خطة غير موجودة) = منفصلة، تُعدّ.
3. خطة بلا جولة تطور واحدة = خطة بلا درس، تُعدّ وتُعرض.
القيود: الإحصاء بالانتماء الحرفي للمفاتيح؛ لا «تخمين انتماء».
الأوامر:
- python -c "import sqlite3;c=sqlite3.connect('file:/work/agent_hub.db?mode=ro',uri=True);q=lambda s:c.execute(s).fetchall();print('orphan_evolutions',q('SELECT COUNT(*) FROM plan_evolutions WHERE plan_id NOT IN (SELECT id FROM plans)')[0][0]);print('orphan_ids',q('SELECT DISTINCT plan_id FROM plan_evolutions WHERE plan_id NOT IN (SELECT id FROM plans)'));print('messages_no_plan',q('SELECT COUNT(*) FROM messages WHERE plan_id IS NULL OR plan_id NOT IN (SELECT id FROM plans)')[0][0]);print('plans_no_lesson',q('SELECT COUNT(*) FROM plans WHERE id NOT IN (SELECT DISTINCT plan_id FROM plan_evolutions)')[0][0])"

### §6 — حزم أدلة قرارات المالك — لا قرارات من النظام

المتطلبات:
1. كل قرار في هذا القسم يُنتج حزمة أدلة فقط: الأرقام والحقائق التي
   يفرضها الواقع، بلا خيار مرشح ولا قيمة مقترحة.
2. أي دور يُصدر قرارًا أو قيمة مقترحة في حقل قرار = HARD STOP آلي.
3. البوابة تسجل كل قرار بحالته «بانتظار المالك» حتى يقرر المالك بنفسه.
القرارات:
D1: مصير جولات التطور اليتيمة — الأدلة: العدد والمعرفات وحجم أثرها.
D2: عتبة الركود التي تستوجب إعادة توليد خطة — الأدلة: توزيع
     stagnation_detected ومتوسط الجودة لكل خطة.
D3: تصنيف الخطة ذات الرسائل الكثيرة والجولات القليلة — الأدلة:
     جدول الخطة/الرسائل/الجولات كما عُرض في §3.
D4: سياسة الاحتفاظ بالرسائل المنفصلة عن خططها — الأدلة: عددها
     ونطاقها الزمني.
D5: تفسير هبوط quality_score المتكرر (delta سالب في جولات متتالية)
     — الأدلة: تتابع الدلتا لكل خطة.
D6: ما إذا كان التقرير يُرفق كرسالة ختام في المحادثة أو يُسلَّم
     خارجها — الأدلة: لا أدلة — قرار إجرائي خالص للمالك.
القيود: حزم الأدلة تُبنى من مخرجات §2-§5 حرفيًا؛ لا إضافة.
الأوامر:
- python -c "import sqlite3;c=sqlite3.connect('file:/work/agent_hub.db?mode=ro',uri=True);q=lambda s:c.execute(s).fetchall();print('D5_evidence',q('SELECT plan_id,quality_score_delta FROM plan_evolutions WHERE quality_score_delta<0 ORDER BY plan_id,id LIMIT 40'))"

### §7 — حدود الصدق

المتطلبات:
1. عرض الخطط المؤرشفة (archived=1) والمتوقفة (stop_requested=1)
     وعدّ الرسائل المعلمة is_error=1 — كما هي.
2. أي تطبيع أو تجميل لهذه الأعداد في التقرير = HARD STOP.
القيود: هذه الأعداد حدود صدق التقرير؛ تُعرض سلبًا وإيجابًا معًا.
الأوامر:
- python -c "import sqlite3;c=sqlite3.connect('file:/work/agent_hub.db?mode=ro',uri=True);q=lambda s:c.execute(s).fetchall();print('archived',q('SELECT COUNT(*) FROM plans WHERE archived=1')[0][0]);print('stop_requested',q('SELECT COUNT(*) FROM plans WHERE stop_requested=1')[0][0]);print('error_messages',q('SELECT COUNT(*) FROM messages WHERE is_error=1')[0][0]);print('escalated',q('SELECT COUNT(*) FROM plans WHERE escalation_flags IS NOT NULL AND escalation_flags != \'\'')[0][0])"

### §8 — إثبات الكتابة-صفر قبل وبعد

المتطلبات:
1. إثبات مزدوج قبل التنفيذ وبعده: من داخل الركيزة (محاولة كتابة على
   التحميل للقراءة فقط يجب أن تفشل) ومن خارجها (بصمة git وعدّادات
   الجداول وقائمة الملفات).
2. تطابق الطرفين شرط نجاح؛ أي اختلاف = HARD STOP.
3. فشل محاولة الكتابة الداخلية (أي نجاح الكتابة) = HARD STOP فوري.
الأوامر:
- python -c "import sqlite3;c=sqlite3.connect('file:/work/agent_hub.db?mode=ro',uri=True);print('tables',len(c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()));print('plans',c.execute('SELECT COUNT(*) FROM plans').fetchone()[0])"

### §9 — القالب الإلزامي للتقرير

التقرير يُبنى من هذه الحقول بهذا الترتيب حرفيًا — لا حقل يُحذف ولا
حقل يُضاف. الأدلة تُملأ من مخرجات الأقسام كما هي.

```
VERDICT: PASS / HARD STOP
MAP (§1): جداول × صفوف
LESSONS (§2): total/new/resolved/recurring/plans_with_lessons
CONSISTENCY (§3): خطة × رسائل × جولات
QUALITY (§4): متوسط الجودة + الجولات الراكدة
ORPHANS (§5): يتيمة/منفصلة/بلا درس
DECISIONS (§6): D1-D6 بانتظار المالك
HONESTY BOUNDS (§7): archived/stop_requested/error_messages/escalated
ZERO-WRITE PROOF (§8): before/after
HARD STOPS FIRED: عدد أو NONE
```

**END OF ORDER**
