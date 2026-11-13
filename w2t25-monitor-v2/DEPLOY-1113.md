# W2-T25 Monitor — Security Update (AES-P0-CONTAINMENT-1113)

**التاريخ:** 2026-11-13 · **الأمر:** AES-P0-MONITOR-CREDENTIAL-CONTAINMENT-1113-R0

## ما الذي تغيّر على الخادم (منفَّذ بالفعل قبل هذا PR)

1. **nginx**: مسار `/w2t25-monitor/` لم يعد يتجاوز حمايات الخادم. حُذفت `allow all` و`auth_basic off` من الكتلة، فورث المسار قائمة عناوين المالك (2.215.157.88 + loopback) + Basic Auth — نفس حماية `/` تمامًا.
2. **خدمة المراقبة (8765)**:
   - التوكن القديم (المنشور سابقًا في هذا المستودع العام) **مبطل من جهة الخدمة المستقبلة** — مرفوض على كل القنوات (query/header/cookie).
   - التوكن الجديد (256-bit) يُقرأ عند الإقلاع من `/etc/w2t25-monitor/monitor_token` (root:root 600، خارج المستودع).
   - قنوات المصادقة المقبولة الآن: ترويسة `X-Access-Key` أو كوكي `w2t25k` فقط. **قناة `?k=` في الاستعلام أُلغيت نهائيًا** — التوكن لا يظهر في URLs ولا access logs ولا browser history.
   - HTML المُقدَّم لم يعد يضم التوكن (كان يزرعه في مصدر الصفحة)، وروابط preview لم تعد تحمله.
3. **الفحص الآلي**: `scripts/ops/secret_guard.py` يعمل في CI (`.github/workflows/secret-guard.yml`) على كل push وPR — يفشل البناء عند اكتشاف اعتماد ثابت (token/password/api_key/credential)، أو قيمة سرية طويلة في query string، أو location بـ `allow all` + `auth_basic off` مع proxy_pass.

## تشغيل سكربتات النشر بعد هذا التغيير

- `apply_monitor_v2.py` و`apply_owner_console_v3.py` يقرآن التوكن من `W2T25_MONITOR_TOKEN` أو من ملف الأسرار — **لا يقبلان قيمة حرفية ولا يطبعانها**.
- إقلاع المتصفح (bootstrap): `curl -s -H "X-Access-Key: <token>" http://127.0.0.1:8765/` — يستجيب بـ Set-Cookie `w2t25k` (24 ساعة)، بعدها تعمل الصفحة بالكوكي دون أي قيمة في الرابط.
- كل تحققات النشر تنتقل إلى الترويسة/الكوكي — أي `?k=` يُرفض (403) حتى لو كانت القيمة صحيحة.

## تحذيرات

- **لا تُعِد تشغيل سكربتات النشر من نسخ قديمة** — النسخ الحاملة للتوكن القديم ستفشل تحققاتها (التوكن مبطل)، وقد تعيد كودًا قديمًا يتجاوز الحمايات.
- التوكن القديم ما زال في **تاريخ Git العام**؛ تدوير الاعتماد هو المعالجة الأساسية (نُفِّذ)، وتنظيف التاريخ قرار منفصل للمالك — انظر تقرير الأمر.
- النتائج المجاورة (W1-T03 healthz بمسار توكن عام، W1-T02 htpasswd sha) مسجلة في `.secretguard-allow` بانتظار أمر معالجة مستقل.

## التراجع (الخادم — للحالات الطارئة الموثقة فقط)

```bash
# nginx (يعيد المسار العام القديم — لا تفعل إلا بقرار موثق):
sudo cp -a /etc/nginx/conf.d/agentic.conf.pre-containment-1113.bak /etc/nginx/conf.d/agentic.conf
sudo nginx -t && sudo systemctl reload nginx
# الخدمة (يعيد التوكن القديم المبطل):
sudo cp -a /home/opc/w2t25_monitor.py.bak-pre-containment-1113 /home/opc/w2t25_monitor.py
sudo systemctl restart w2t25-monitor.service
```
