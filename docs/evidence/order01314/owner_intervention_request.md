# طلب تدخل مالك — مورد عامل Linux معزول مطلوب

## الملخص
لا يوجد عامل Linux معتمد (`REMOTE_WORKER` مع `sandboxed=true` ومسبار حي) متاح للمصادقة تحت سياسة `STRICT_ISOLATED`. جميع المسارات المحلية محجوبة بنيويًا على مضيف Windows الحالي.

## لماذا لا يكفي Windows الحالي
1. **لا ركيزة عزل**: `runtime_truth()` → `wsl=false, docker="", container_runtime=""`؛ `_substrate_available()=false`
2. **WSL2 مثبت لكن معطل**: `wsl.exe` موجود، لكن الافتراضية غير مفعلة على الجهاز → `WSL2 is unable to start since virtualisation is not enabled on this machine`
3. **لا حاويات**: Docker غير مثبت، لا container runtime
4. **لا عامل بعيد مسجل**: لا `REMOTE_WORKER_ENDPOINT`، لا بيئة `REMOTE_WORKER` في قاعدة البيانات

## المورد/الإذن الوحيد المطلوب للمتابعة
**خيار واحد فقط من التالي (اختيار المالك):**

| الخيار | الوصف | يتطلب من المالك |
|---|---|---|
| **أ. تفعيل الافتراضية على هذا الجهاز** | تفعيل "Virtual Machine Platform" و "WSL" في Windows Features، أو تفعيل VT-x/AMD-V في BIOS/UEFI، ثم تشغيل Ubuntu في WSL2. | إذن/وصول للجهاز لتفعيل الافتراضية وإعادة التشغيل |
| **ب. توفير عامل Linux خارجي معتمد** | جهاز/VM Linux (x86_64) مع `scripts/execution_worker.py` يعمل، قناة HTTPS/TLS محمية، توكن مشترك. | توفير الجهاز، إعداد الشبكة، مشاركة `ENDPOINT` و `TOKEN` بأمان |
| **ج. نشر substrate-docker على Linux** | إذا توفر Docker على جهاز Linux، نشر substrate-docker وتشغيل العامل داخله. | جهاز Linux مع Docker، نشر الحاوية |

## المواصفات الدنيا للعامل المطلوب
- **OS**: Linux (x86_64 أو aarch64)
- **Python**: 3.10+
- **العامل**: `scripts/execution_worker.py` من هذا المستودع (يعلن `sandboxed=true` داخل الركيزة)
- **الشبكة**: منفذ تحكم قابل للوصول من المضيف (مثلاً 8900/8901)
- **الأمان**: قناة خاصة أو TLS + توكن Bearer مشترك
- **الركيزة**: namespaces + seccomp + cgroups v2 (لتحقيق `sandboxed=true` حقيقي)

## ما سيحدث بعد توفير المورد
1. تسجيل بيئة `REMOTE_WORKER` عبر واجهة إعدادات بيئات التنفيذ
2. تحقق حي عبر `RemoteWorkerBackend.verify()` → فحوص مطلوبة + `isolation_probe` بتحدي جديد
3. تشغيل الاختبارين المتخطيين في 013.12:
   - `test_d2_live_substrate_isolation_probe_on_linux`
   - `test_d3_isolated_success_contract_on_linux`
4. إعلان `STRICT_WORKER_READY` فقط بعد نجاح كل الشروط

## لا بديل ولا fallback
- لن يُستخدم `COMPATIBLE_LOCAL` بصمت
- لن يُشغل مهمة E11 دون عامل معزول موثق
- لن يُدمج إلى `main`

---
*تم إنشاؤه تلقائيًا بواسطة أمر 013.14 — `OWNER_INFRA_REQUIRED`*