# تقرير الأمر 013.17-R1 — صدق كشف الركيزة، عقد العامل، وترتيب بوابة E11

> البيئة المنفِّذة لهذا التسليم: مضيف Windows للمالك (الجلسة نفسها).
> بيئة الإشكال الأصلية: Google Cloud Shell (Linux/Python 3.12) — أدلة
> OBSERVED من تشغيل المالك + أوامر إعادة تشغيل حية أدناه.

## 1. CLAIMED — ما يدعي المنفّذ أنه أصلحه

1. **(§3) كشف دعم الركيزة**: `LocalSandboxBackend.available()` صار
   يحكم من `substrate_capabilities()["supported"]` + توافر الصور —
   وجود تعريفات الصور وحده لم يعد دليلًا على العزل. عند عدم الدعم:
   وصف UNAVAILABLE بالسبب الفعلي (seccomp_self_mode=0) بدل RuntimeError
   غير معالج. `LocalSubstrateAdapter` لا ينهار عند الإنشاء: يسجل رفض
   القدرات وكل طلب تنفيذ يُردّ بسجل FAILED_TO_START صادق (fail-closed
   لكل طلب) — عاجز عن التنفيذ بكل الأحوال.
2. **(§4) وضع العامل**: العامل يعلن `substrate` فقط عند اجتياز فحص
   القدرات نفسه؛ وإلا يعلن `subprocess` بصدق مع `substrate_refusal`
   الحرفي في `/capabilities`. علم `--mode` جديد: `subprocess` يفرض
   الوضع الصادق، `substrate` على مضيف غير مستوفٍ = خروج 2 فوري (لا
   تخفيض صامت). كل مسارات الطلبات محصنة: أي خطأ داخلي = JSON 500
   صريح + تشخيص في سجل العامل — لا `RemoteDisconnected`، ولا أسرار
   ولا جسم طلب في الرد أو السجل.
3. **(§5) الاختبارات الحية**: `_substrate_ok_on_this_host()` وconftest
   الركيزة واختبارات البذر والتكامل الحية كلها تشترط فحص القدرات
   الفعلي — على مضيف غير مدعوم تُسجَّل `SKIPPED — NOT RUN` بالسبب
   المحدد. اختبار عقد الرفض الصادق يعمل على كل مضيف (فرض
   `--mode subprocess` صراحة). الاختبارات الوحدوية واختبارات الرفض
   الصادق ظلت تعمل.
4. **(§6) اختبارات مساحة العمل**: المحاكاة على واجهة الإطلاق الفعلية
   (`Popen` لا `run` المهجورة): B وI يثبتان التصنيف الصحيح
   (RUNTIME_WORKSPACE_INVALID/WINDOWS_CWD_INVALID) والمحاولتين حصرًا
   والفشل النهائي FAILED_TO_START. C يمرر المسار بنصه الخام (شكل
   الإدخال الواقعي) ويحظر واجهتي الإطلاق معًا. التقاط الأدلة في
   اختبار البروتوكول صار واعيًا بوضعي العامل (نمط test_e المجرب).
5. **(§6-ملحق) المجهز**: مسار الفجوة البنيوية يسجل خطوة PROVISIONING
   (فاشلة بسبب حرفي) قبل PROVISIONING_UNAVAILABLE — لا قفزة صامتة من
   DISCOVERING إلى UNAVAILABLE، وعقد §44 (لا READY بلا فحوص) محفوظ.
6. **(§7) بوابة E11**: `preflight_strict_requirements()` قبل أي إعادة
   ضبط: فحص القدرات الفعلي هو البوابة؛ الرمز يُؤمَّن قبل إعادة الضبط
   (موجود فيُتحقق، غائب فيولَّد وقت التشغيل بصلاحيات 0600 ولا يُطبع)،
   وعند عدم الدعم: أدلة صادقة + خروج غير صفري **قبل** حذف أي حالة
   تشغيلية. playwright استيراد كسول (البوابة لا تتطلب متصفحًا)، وأي
   فشل تهيئة يُسجل سببه المسمّى في الملخص لا استثناء خام. لا موافقة
   آلية (التدقيق الذاتي AST ما زال يمر)، ولا مهمة في وضع subprocess.
7. **(§8) إصلاح حامل الاختبار للجري الكامل**: اعتماديات ناقصة على
   المضيف (aiohttp/requests/cryptography) ثُبتت، وتصادم أسماء وحدات
   الاختبار بين المجلدات (e36/e41 test_real_mission.py وe35/e42
   test_long_mission.py — كان يُسقط الجري الكامل كله بـ«import file
   mismatch») أُصلح بإعلان المجلدات المتضاربة حزمًا (`__init__.py`)
   — مع الحفاظ على استيرادات tests/unified الشقيقة كما هي.

## 2. OBSERVED — ما أظهرته الاختبارات والسجلات فعليًا

- **المجموعة المستهدفة §8 (هذا المضيف)**: `50 passed, 8 skipped,
  0 failed, 0 errors` (`targeted_tests_windows_host.txt`) — مقابل
  أساس ما قبل الإصلاح على Cloud Shell: 16 failed + 4 errors.
- **الجري الكامل §8 (هذا المضيف) — سجل جزئي صادق**: الجري الكامل
  (1139 اختبارًا) يزحف بنيويًا على هذا المضيف: حلقات مهام حية تعلق
  بصدق على `blocked_kind=preflight` (بيئة بلا sandbox) وتستهلك
  ~4 دقائق لكل اختبار عبر مسار المهلة الكامل — 6% في ~62 دقيقة
  (التفصيل الكامل في `full_pytest_windows_host.txt`). أُوقف عمدًا
  بعد توثيق الفشل الأربعة المصادفة ومقارنتها بالأساس:
  ثلاثة فاشلة بالطريقة نفسها على الأساس 1755015 (ما قبل R1 — تحقق
  worktree مستقل)، والرابع ينجح منفردًا على الفرعين (رفرفة حمل من
  pytest متداخل تسرب داخل الجري). **صفر انحدارات من R1**، ولا يُدّعى
  جري كامل لم يكتمل — والجري الكامل الموثق من طرف المالك على
  Cloud Shell (أوامر §7).
- **العامل الحي عبر HTTP (إثبات تنفيذي، `worker_mode_and_protocol.json`)**:
  - الوضع التلقائي على مضيف غير مدعوم: `backend_mode=subprocess`،
    `sandboxed=false`، `isolation="none — declared"`، سبب الرفض معلن.
  - `/probe_isolation` في الوضع المعلن: `NOT_ISOLATED_MODE`،
    `ok=false`، التحدي مُصدَر — لا انتحال نتيجة عزل.
  - `--mode substrate` على نفس المضيف: **خروج 2** برسالة FATAL —
    لا تخفيض صامت.
- **بوابة الجلسة (إثبات تنفيذي، §9)** — القيم صادرة من التنفيذ لا من
  كتابة يدوية (`strict_session_preflight.json` + `session_summary.json`
  من إخراج الجلسة نفسها):
  ```
  substrate_supported: false
  strict_worker_authorized: false
  mission_started: false
  runtime_state_reset: false
  verdict: BLOCKED_NO_AUTHORIZED_STRICT_WORKER
  ```
  والإثبات الملفي: قاعدة البيانات كانت موجودة قبل التشغيل **وبقيت**
  بعده (`runtime_db_deleted: false`) — فشل ما قبل التشغيل لم يحذف
  حالة تشغيلية. التدقيق الذاتي AST مرَّ ("no auto-approval call ✓").

## 3. VERIFIED — ما تثبته أدلة مستقلة قابلة لإعادة الفحص

- كل ما في §2 أعلاه ملفات في `docs/evidence/order01317-r1/`:
  `git_state.txt`، `cloud_shell_capabilities.json`،
  `targeted_tests_windows_host.txt` + رمز الخروج،
  `full_pytest_windows_host.txt` (سجل جزئي صادق + مقارنة الأساس) +
  `full_pytest_exit_code.txt` (بلا رمز — جري موقوف عمدًا)،
  `worker_mode_and_protocol.json` (إثباتات العامل الثلاثة + بوابة
  الجلسة)، `strict_session_preflight.json` + `session_summary.json`
  (من إخراج الجلسة ذاتها).
- مقارنة الأساس للفشل المصادف في الجري الجزئي: worktree منفصل عند
  `1755015` أنتج 3 failed + 1 passed على نفس الاختبارات الأربعة —
  مطابق لفرع R1 (لا انحدار).
- `git diff --check` نظيف (`git_state.txt`).
- إعادة التقاط قدرات Cloud Shell حية ممكنة بأمر واحد موثق داخل
  `cloud_shell_capabilities.json` (`recapture_command`).

## 4. NOT RUN — ما لم يُنفَّذ لغياب الركيزة

- اختبارات العزل الحية داخل الركيزة (8 متخطاة صادقًا في المجموعة
  المستهدفة: escapes/limits/watchdog/seed/builder/tools): تُشغَّل على
  مضيف يجتاز فحص القدرات فقط — لا محاكاة ولا تخفيض معيار.
- تجربة E11 الحية الكاملة: لا تُبدأ قبل عامل STRICT مخوّل (§1).
- الجري الكامل حتى الاكتمال على هذا المضيف: غير عملي (زحف بنيوي
  موثق أعلاه 6-12 ساعة من حلقات حية معلقة بصدق) — يُستكمل لدى المالك
  على Cloud Shell حيث تُنهى حلقات المهام بسرعة أو يغلق المضيف تجربته
  بأمان بنفس البوابة.
- كل ما سبق على Cloud Shell تحديدًا: بانتظار إعادة تشغيل المالك
  (أوامر §7 أدناه) — أرقام هذا التسليم من مضيف Windows، ولا يُدّعى
  إعادة تنفيذها على Cloud Shell.

## 5. BLOCKERS — متطلبات لا يوفرها Cloud Shell الحالي

- `seccomp_self_mode=0`: العملية بلا فلتر seccomp — سياسة نواة/منصة
  لا ترفعها بالكود، والأمر نفسه يمنع تخفيف المعيار. فيستمر
  `supported=false` ويبقى إغلاق التجربة الحية بأمان هو المخرج الصحيح.
- لا Docker/عامل Linux مخوّل مسجل في البيئة الحالية، وبيئة 013.15/
  013.16 (حاوية Linux بالركيزة) هي ما يزال المسار الوحيد المصرح به
  للاختبارات الصارمة وتجربة E11.

## 6. GIT STATE

- الفرع: `order01317-e11-fixture-owner-gate-closure` (worktree معزول
  نظيف من `1755015` — رأس 013.17 المنشور).
- الأساس قبل التعديل: HEAD `1755015988bb6e3bfde7cfcf336852ce0381f62a`
  (مُثبت في `git_state.txt` مع حالة العمل و`diff --check`).
- `origin/main = 0a26fc70…` — لم يتحرك؛ لا دمج؛ لا reset؛ لا force-push.
- الكوميت النهائي وSHA بعد الجري الكامل والمراجعة الذاتية — انظر
  `git_state.txt` المحدَّث بعد الدفع.

## 7. أوامر إعادة التحقق على Cloud Shell (للمالك/المحكّم)

```bash
cd ~/order01317_work
git pull origin order01317-e11-fixture-owner-gate-closure
git log --oneline -1          # كوميت R1 (انظر GIT STATE)

# (§8) المجموعة المستهدفة ثم الكامل — مع حفظ الرموز
source .venv/bin/activate
pytest -q tests/execution/test_backends.py tests/execution/test_provisioner_013.py \
  tests/execution/test_trust_boundary_01312.py tests/execution/test_workspace_0133.py \
  tests/substrate/test_worker_seed_v11_01316.py tests/api/test_sandbox_integration.py \
  tests/readiness/test_preflight_matrix.py; echo "TARGETED EXIT=$?"
pytest -q; echo "FULL EXIT=$?"

# (§3/§9) قدرات الركيزة الحية — يجب أن تبقى supported=false بصدق
python -c "import sys,json; sys.path.insert(0,'src'); from substrate.local_substrate import substrate_capabilities; print(json.dumps(substrate_capabilities(), indent=1))"

# (§9) بوابة الجلسة: يجب BLOCKED_NO_AUTHORIZED_STRICT_WORKER وخروج
# غير صفري وبقاء حالة runtime كما هي (لا reset)
ORDER01317_WORK=~/order01317_work ORDER01317_EVID=docs/evidence/order01317-r1 \
  python scripts/e11_session_01317.py; echo "SESSION EXIT=$?"
```

## 8. FINAL VERDICT

**CONDITIONAL** — عيوب كشف الركيزة وعقد العامل واختبارات مساحة العمل
وبوابة ما قبل التشغيل مُصلَحة ومُثبتة تنفيذيًا على مضيف المنفّذ
(صفر فشل في المجموعة المستهدفة؛ بوابة الجلسة تغلق بأمان دون مساس
بالحالة التشغيلية). المشروط:
1. إعادة تشغيل §7 أعلاه على Cloud Shell لتوثيق نفس السلوك الصادق هناك
   (supported=false متوقعًا — وهذا نجاح الصدق لا فشله).
2. اختبارات العزل الحية وتجربة E11 الكاملة تبقى محجوزة لعامل Linux
   مخوّل بالركيزة — لا PASS نهائي ولا إغلاق لـE11 قبلها.
