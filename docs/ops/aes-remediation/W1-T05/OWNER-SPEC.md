# W1-T05 — مواصفة خطوة المالك: قاعدة الخروج TCP 80 في Oracle Cloud

**التاريخ:** 2026-10-27 · **لماذا:** قدرة `network_http` في المصنع معطلة (NOT_READY) — قاعدة الخروج الوحيدة في VCN تغطي TCP 443 فقط، والخادم لا يملك `oci` CLI مهيأ فلا يمكن إضافتها تقنيًا إلا من Oracle Console (كما فعل المالك سابقًا في RLR-003 لقاعدة 443).

## الإثبات (2026-10-27، قراءة فقط — `20261027-steps01.json`)
| الفحص من الخادم | النتيجة |
|---|---|
| `curl http://example.com/` (منفذ 80) | **000 · Connection timed out** (6.1ث، RC=28) |
| `curl http://neverssl.com/` (منفذ 80) | **000 · Connection timed out** (4.2ث) |
| `curl https://example.com/` (منفذ 443) | **200 في 0.025ث** — نفس المضيف! الفرق المنفذ وحده |
| مسبار المصنع `network_http` | **NOT_READY** — «تعذر HTTP المباشر إلى http://example.com: Errno 101 Network is unreachable» |
| `oci` CLI / `~/.oci` | غير موجودين |

المضيف نفسه يستجيب فورًا عبر 443 ويفشل عبر 80 → الحجب في قاعدة خروج VCN حصراً (ليس DNS وليس firewalld المحلي وليس التطبيق).

## المطلوب من المالك في Oracle Console (5 دقائق)

**Networking → Virtual Cloud Networks → (اختر VCN الخادم) → Security Lists → (نفس Security List التي تحوي قاعدة خروج TCP 443 القائمة) → Add Egress Rules:**

| الحقل | القيمة |
|---|---|
| Stateless | **مكتفٍ بالحالة (Stateless = غير محدد/مقصوص)** |
| Destination Type | CIDR |
| Destination CIDR | **0.0.0.0/0** |
| IP Protocol | **TCP** |
| Source Port Range | (اتركه فارغًا/All) |
| Destination Port Range | **80** |
| Description | `AES W1-T05: outbound HTTP 80 for network_http capability (companion to 443 rule)` |

> ملاحظة: القاعدة **خروج (Egress)** وليست دخولًا — لا تفتح أي شيء نحو الخادم؛ هي تسمح للتطبيق بالوصول إلى موارد HTTP خارجية (قدرة `network_http` وأدوات الجلب التي تستخدم منفذ 80).

## بعد الإضافة (يتولاه المنفذ فورًا)
1. `curl http://example.com/` من الخادم → المتوقع 200.
2. `POST /api/environment/probe` للقدرة `network_http` → المتوقع READY.
3. تدقيق مستقل + توقيع + إغلاق المهمة (الخطوتان 3-4 من البطاقة).

## التراجع
حذف القاعدة من Console — لا أثر تراكمي على الخادم نفسه.
