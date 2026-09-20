# substrate — ركيزة العزل المعزولة عن النظام

## المصدر والنزاهة

كل ملفات هذه الحزمة (وكذلك `src/grants/` و`src/evidence/` و`src/contracts/`)
منسوخة **حرفيًا** من `jarvis-engineering-capability` v0.8.0 (مستودع نفس
المالك؛ 702 اختبارًا أخضر عند النسخ). التعديل الوحيد المطبَّق على النسخ:
**إعادة توجيه مسارات الاستيراد** من `engineering.*` إلى مسارات v2
(`substrate.*` / `grants.*` / `evidence.*` / `contracts.*`) — منطق الكود
لم يُمس سطرًا. للتدقيق: قارن أي ملف بالمصدر وتجاهل فروق أسطر الاستيراد
والإشارات التوثيقية للمسارات.

## الملفات المنسوخة (20 = 8 مطلوبة + 12 لغلق الاعتماديات)

| الحزمة | الملفات |
| --- | --- |
| `substrate/` (المطلوبة) | local_substrate، sandbox، workspace، limits |
| `grants/` (المطلوبة) | grant، admission |
| `evidence/` (المطلوبة) | evidence، verification |
| `contracts/` (غلق الاعتماديات) | capability، contract، domain، result، implementation + high_impact، mission، objective، operations، static_analysis، testing_domain، write_operations |

**لماذا الملفات الاثنا عشر الإضافية؟** الوحدات الثماني المطلوبة تستوردها
مباشرة أو عبر السلسلة (سجل العمليات `implementation.py` هو مركز يستورد
كل محللات العقود) — بلاها لا تعمل النسخة الحرفية إطلاقًا. هذا غلق
اعتماديات ضروري لا توسيع نطاق.

## آلية العزل (من local_substrate.py)

- خمس namespaces عبر `unshare` بلا صلاحيات root: user / uts / net / mount / pid
- `pivot_root` مع ربط للقراءة فقط — نظام ملفات المضيف غير مرئي
- seccomp بقائمة **23 syscall ممنوعة** (ptrace, mount, unshare, setns, bpf, kexec…) + `NO_NEW_PRIVS`
- rlimits: الذاكرة (RLIMIT_AS)، العمليات (NPROC)، حجم الملف (FSIZE)، المعالج (CPU)، الملفات المفتوحة (NOFILE)، core = 0
- شبكة = لا شيء (network namespace بلا واجهات)
- مراقب watchdog بقتل جماعي حتمي للعملية العالقة

## قيد المنصة — مهم

الركيزة تعمل على **Linux/x86_64 فقط** (فحصها الذاتي `_SUPPORTED_ARCH`
يرجع False خارجهما). على Windows يجب تشغيل النظام عبر **WSL2**. خارج
المنصة المدعومة يظل الكود مستوردًا لكن تنفيذ العزل يرفض — والنظام أعلى
يعلن الوضع المتوافق صراحة ولا يدّعي عزلًا غير موجود.

## الاختبارات السالبة

`tests/substrate/` تُثبت أربع ضمانات عمليًا (تعمل على Linux/WSL2 فقط):

1. `test_no_network_escape` — لا اتصال شبكي خارج العزل
2. `test_no_filesystem_escape` — لا وصول لملفات المضيف
3. `test_resource_limits_enforced` — حدود الموارد مفروضة
4. `test_watchdog_kills_stuck_process` — المراقب يقتل العملية العالقة

## ملاحظات نزاهة النسخ

- تعليقات ثلاثة مواضع في `grants/admission.py` و`contracts/capability.py`
  تشير إلى `engineering.high_impact*` — إشارات توثيقية للوحدات التي بقيت
  في المستودع المصدر ولم تُنسخ إلى v2 (سلسلة E4 كاملة لم تُطلب في
  التأسيس). أُبقيت حرفية كتوثيق منشأ.
- الوحدة تُنشئ عمليات عبر posix_spawn داخل `local_substrate.py` حصرًا —
  لا وحدة أخرى في النسخة تنشئ عمليات (حرس بنيوي في المستودع المصدر).
