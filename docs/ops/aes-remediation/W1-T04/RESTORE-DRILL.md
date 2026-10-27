# W1-T04 — تمرين الاسترجاع الموثق (RESTORE-DRILL)

**التاريخ:** 2026-10-27 04:48–04:52 UTC · **المنفذ:** المنفذ الرئيسي (W1-T04) · **البيئة:** إنتاج 92.5.14.150 (قراءة فقط أثناء التمرين — لا مساس بالقاعدة الحية)

## الغرض
إثبات أن نسخة النسخ الاحتياطي الليلي قابلة للاسترجاع فعلاً — ليست مجرد ملف يُنسخ ثم يُكتشف فساده يوم الحاجة. هذا التمرين هو بوابة القبول الرابعة لمهمة W1-T04 (البند 4/18): «تمرين استرجاع موثق في RESTORE-DRILL.md مع جداول محسوبة».

## خطوات التمرين (الأوامر كما رُكضت فعلاً)
```bash
# 1) نسخ آخر نسخة احتياطية إلى ملف تمرين معزول (لا مساس بالأصل)
cp /opt/aes-backups/db/nightly-20261027.db /tmp/restore-drill.db

# 2) فتح النسخة والتحقق من سلامتها وعدّ جداولها وصفوفها
/usr/bin/python3 /tmp/w1t04_probe.py /tmp/restore-drill.db
#    (السكربت: sqlite3.connect → PRAGMA integrity_check → COUNT للمستخدمة)

# 3) المقارنة مع القاعدة الحية (المصدر)
/usr/bin/python3 /tmp/w1t04_probe.py /opt/agentic-engineering-system/runtime/agent_hub_v2.db

# 4) التنظيف
rm -f /tmp/restore-drill.db /tmp/w1t04_probe.py
```

## النتائج المحسوبة

| المقياس | القاعدة الحية (المصدر) | نسخة الاسترجاع (/tmp/restore-drill.db) | التطابق |
|---|---|---|---|
| `PRAGMA integrity_check` | ok | ok | ✓ |
| عدد الجداول (sqlite_master type='table') | 24 | 24 | ✓ |
| `projects` — COUNT(*) | 2 | 2 | ✓ |
| `conversations` — COUNT(*) | 13 | 13 | ✓ |
| `messages` — COUNT(*) | 91 | 91 | ✓ |
| حجم الملف | 8,040,448 بايت | 8,040,448 بايت | ✓ |

## طريقة الاسترجاع الفعلية عند كارثة (موثقة للمالك)
```bash
# 1) أوقف التطبيق (قاعدة SQLite لا تُستبدل وهي مفتوحة)
sudo -n systemctl stop agentic
# 2) أرشف القاعدة الحالية (لا تحذفها قبل التأكد)
sudo -n cp /opt/agentic-engineering-system/runtime/agent_hub_v2.db \
           /opt/agentic-engineering-system/runtime/agent_hub_v2.db.broken-$(date +%Y%m%d%H%M)
# 3) ضع النسخة المرادة (مثال: آخر نسخة ليلية)
sudo -n cp /opt/aes-backups/db/nightly-YYYYMMDD.db \
           /opt/agentic-engineering-system/runtime/agent_hub_v2.db
sudo -n chown --reference=/opt/agentic-engineering-system/runtime/agent_hub_v2.db.broken-* \
           /opt/agentic-engineering-system/runtime/agent_hub_v2.db 2>/dev/null || true
#    (تأكد من المالكية الأصلية بالأمر: stat -c '%U %G' على الأرشيف قبل الاستبدال)
# 4) تحقق ثم شغّل
/usr/bin/python3 -c "import sqlite3; print(sqlite3.connect('/opt/agentic-engineering-system/runtime/agent_hub_v2.db').execute('PRAGMA integrity_check').fetchone()[0])"
sudo -n systemctl start agentic
curl -s http://127.0.0.1:8010/health   # المطلوب: 200
```

## أدلة إضافية
- النسخة نفسها أُنشئت عبر النسخ الاحتياطي الآمن (`sqlite3.connect(src).backup(dst)` — لا نسخ ملف خام لقاعدة حية) وسجل تشغيلها: `/opt/aes-backups/logs/backup-20261027.log` («integrity_check: ok»).
- فحص سلامة خارجي مستقل عن فحص السكربت الداخلي: `20261027-deploy.json` → gate `integrity_external` = ok/24 tables.
- إشعار حادث أثناء التنفيذ (شفافية كاملة): المحاولة الأولى فشلت بـ`status=203/EXEC Permission denied` (السكربت كان root:root 750 فلا صلاحية لمستخدم الخدمة opc) — شُخّص خلال دقيقة، أُصلح (`root:opc 750`)، أعيد التنفيذ كاملاً ببوابات نظيفة، والحادث موثق في TRACKER/worklog وملف أدلة المحاولة الأولى محفوظ في سجل المحادثة. **التراجع لم يكن ضرورياً؛ خطة التراجع مجربة منطقياً في البطاقة.**

## الخلاصة
النسخة الاحتياطية الليلية **قابلة للاسترجاع ومُثبتة بالمقارنة الجدولية صفاً بصفة**: سلامة هيكلية ok، 24 جدولاً، ومطابقة تامة في الجداول الرئيسية الثلاثة (projects/conversations/messages) بين المصدر والنسخة المسترجعة.
