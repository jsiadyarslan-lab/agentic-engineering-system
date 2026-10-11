# ORDER 013.9 — تقرير الإصلاح الهندسي والتحقق

**NORMAL-PATH LINUX SUBSTRATE REPAIR & FAILURE-PATH CLOSURE**

| البند | القيمة |
|---|---|
| الأمر | 013.9 — إصلاح مسار استيراد الركيزة على Linux وإغلاق مسار الإبلاغ عن الفشل |
| الفرع | `order0139-linux-substrate-import-repair` (منشأ من خط الأساس المتحقق منه حيًّا، لا من فرع 013.8) |
| الكوميت الأب | `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (main — تحقق حي: محلي + `origin/main` قبل البدء وبعد التسليم) |
| كوميت الإصلاح | `73d8e47` — 5 ملفات، +539/−64 (إحصاء مشتق آليًا من `git diff --numstat`) |
| كوميت التوثيق | التقرير والأدلة هذه (كوميت ثانٍ على الفرع نفسه — لا amend إطلاقًا) |
| حالة `main` | غير محرك: `main == origin/main == 0a26fc70` (تحقق حي قبل العمل وبعده) |
| الحالة النهائية | **`ENGINEERING_FIX_VERIFIED`** — بحدود §8 الحرفية، مع ثلاثة عيوب قائمة مكتشفة موثقة للتحكيم (§9 أدناه) لا تدخل في نطاق هذا الأمر |

**ما لا يدعيه هذا التقرير:** لا يُصدر `READY_FOR_OWNER_REAL_TRIAL` (ممنوع نصًّا في §7)، ولا يثبت جاهزية مفتاح المالك أو جهازه، ولا يعتمد المنتج النهائي، ولا يقترح دمج `main`، ولا يبدأ منصة OSINT.

---

## 1. خط الأساس والتحقق الحي (§2)

كل تحقق أُجري قبل أي تعديل:

1. `git rev-parse main origin/main` → كلاهما `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` — مطابقة حرفية لمرجع الأمر §2.1.
2. `git ls-remote origin refs/heads/main` (حي عبر الشبكة) → `0a26fc70…` — الأصل غير محرك.
3. `git log --format='%H %P' -1 2be533c` → الأب حرفيًّا `0a26fc70…` — فرع 013.8 المحلي سليم كما وصفه المنفّذ السابق، ولم يُبنَ عليه شيء هنا (الفرع الجديد من خط الأساس مباشرة).
4. `e10-rp22r2a2-sanitized-git-environment` عند `c5920c8` — 10 كوميتات أمام main، غير مدموج، لم يُلمس.
5. اسم الفرع الجديد كان غير موجود محليًا ولا على الأصل (تحقق `ls-remote` قبل الإنشاء).
6. شجرة العمل نظيفة عند الإنشاء؛ worktree تنفيذ معزول `/home/z/my-project/order0139_run` من `0a26fc70` حصرًا (النمط المعتمد منذ 013.8).

**حادثة موثقة بشفافية (لا أثر لها في التسليم):** أثناء تهيئة بيئة القبول حُذف دليل `runtime/` بأكمله من worktree التنفيذ ظنًّا أنه حالة اختبارية غير متتبعة؛ تبين أن 90 ملفًا تاريخيًا داخله (أدلة 013.5/013.6) **متتبعة في الكوميت الأب**. استُعيدت كلها حالًا بـ`git checkout HEAD -- runtime/` (عملية على شجرة العمل تعيد الملفات إلى حالتها المت_COMMITted — ليست reset ولا إعادة كتابة تاريخ). النتيجة النهائية: **صفر تغيير تحت `runtime/`** في diff الفرع (تحقق آلي: `git diff --name-only 0a26fc70..HEAD` لا يذكر runtime إطلاقًا).

---

## 2. الإصلاح D1 — سلسلة استيراد الركيزة (§3)

### 2.1 العيب كما ثُبّت من كود main (خط الأساس)

- `src/substrate/__init__.py:4` كان يستورد `windows_executor` بلا حراسة عند تحميل الحزمة.
- `src/substrate/windows_executor.py:677-681` كان يحتوي كتلة ملحقة ميتة تستورد `win32pipe/win32file/win32event/win32con/win32api` **على مستوى الوحدة بلا أي حراسة**.
- النتيجة الحرفية على Linux (دليل خام: `evidence/order0139/BASELINE_D1_import_failure.txt`):

```
File "src/substrate/__init__.py", line 4, in <module>
    from .windows_executor import WindowsExecutor, ExecutionLimits, ExecutionResult
File "src/substrate/windows_executor.py", line 677, in <module>
    import win32pipe
ModuleNotFoundError: No module named 'win32pipe'
```

- الأثر: كل وحدات الركيزة (`limits/sandbox/workspace/local_substrate`) تتعطل على Linux — فيفشل `LocalSandboxBackend.available()` استيرادًا → `_substrate_available()` تعيد False → تسجيل `local-linux` بلا عزل (وضع متوافق) → حجب كل مسارات التنفيذ المعزول. هذا هو جذر سقوط 013.8 (F-1) الذي أكده المحكّم من الكود.

### 2.2 الإصلاح (ملفان)

**`src/substrate/__init__.py`** (+46/−2):
- الاستيراد الفوري لمنفّذ Windows صار **حصريًا** بشرط `sys.platform == "win32"` — السلوك المدعوم على Windows محفوظ حرفيًّا كما كان.
- على غير Windows: `__getattr__` كسول (PEP 562) يوفر الأسماء الثلاثة عند الطلب الصريح فقط، مع رفض واضح لأي اسم آخر — لا ابتلاع صامت ولا حالة جاهزة شكلية.
- تحميل حزمة الركيزة على Linux لم يعد يتطلب pywin32 **إطلاقًا** (يثبته اختبار الانحدار بعملية نظيفة — أدناه).

**`src/substrate/windows_executor.py`** (+16/−54):
- **أُزيلت الكتلة الملحقة الميتة** (الأسطر 672-707 في الأصل) بكاملها: الاستيرادات القياسية المكررة + استيرادات win32 الخمسة غير المحروسة + كتلة `HAS_PYWIN32` المكررة.
- أُزيلت الاستيرادات المكررة في الأعلى (كتلة 47-53 المكررة + تكرار كتلة pywin32 نفسها مرتين).
- `tempfile` — المستخدم فعليًا في `WindowsExecutor` عبر `gettempdir()` (سطر 158) وكان يُستورد **فقط** من الكتلة الميتة — انتقل إلى كتلة الاستيراد العليا. (لو حُذفت الكتلة بدونه لانكسر سلوك Windows).
- استيرادات pywin32 العليا بقيت محروسة كما كانت بعلم `HAS_PYWIN32` — الوحدة الآن قابلة للاستيراد على كل المنصات، والعلم صادق (`False` على هذا المضيف).

### 2.3 الاختبارات الإلزامية (§3) — `tests/substrate/test_linux_import_chain_0139.py` (جديد، 223 سطرًا)

| الاختبار | ما يثبته | النتيجة |
|---|---|---|
| `test_normal_import_chain_succeeds_on_linux` | `import substrate.local_substrate` في **عملية بايثون جديدة نظيفة** (PYTHONPATH=src فقط) — لا وحدات وهمية في `sys.modules` إطلاقًا | PASS |
| `test_import_does_not_load_or_require_win32_modules` | اختبار الانحدار الحرفي المطلوب: بعد استيراد كل وحدات الركيزة، **لا وجود لأي وحدة win32 في `sys.modules`** — الاستيراد لم يحاول حتى لمسها | PASS |
| `test_app_consumed_import_paths` | كل مسارات الاستيراد التي يستهلكها التطبيق فعلًا (من grep موثق): limits/sandbox/workspace/local_substrate/windows_executor بنمطي `substrate.*` و`src.substrate.*` (نمط factory/orchestrator.py:52 الحرفي) | PASS |
| `test_windows_executor_honest_flag_on_linux` | الوحدة قابلة للاستيراد على Linux و`HAS_PYWIN32=False` (علم صادق) والوصول الكسول `from substrate import WindowsExecutor` يعيد الصنف نفسه | PASS |
| `test_package_init_windows_branch_preserved` | فحص بنيوي (AST): الاستيراد الفوري موجود **داخل** شرط `sys.platform == "win32"` + `__getattr__` يغطي الأسماء الثلاثة — سلوك Windows محفوظ بنيويًّا | PASS |

**تصنيف NOT RUN الصادق (§3.3):** الاختبارات التشغيلية الحقيقية لسلوك Windows (pywin32/Job Objects على مضيف Windows) **NOT RUN** — لا مضيف Windows في هذه البيئة؛ التعويض المتاح هو الفحص البنيوي أعلاه + بقاء الاستيرادات المحروسة كما هي. كذلك `tests/substrate/test_bridge.py` (13 اختبارًا) **NOT RUN** — تتطلب `SUBSTRATE_TEST_SOCKET` (خادم ركيزة gRPC اختياري، والوحدة نفسها تحتاج grpc خارج التبعيات المعلنة).

### 2.4 الأثر المقاس على خط الأساس (قبل/بعد — قابل لإعادة التوليد)

| المقياس | خط الأساس 0a26fc70 | بعد 73d8e47 |
|---|---|---|
| `import substrate.local_substrate` | ModuleNotFoundError: win32pipe | نجاح |
| `pytest tests/substrate` (تجميع) | خطأ تجميع كامل (conftest.py:13) | 9 passed / 13 skipped |
| أخطاء تجميع على مستوى المستودع | 19 (منها 5 جذرها win32pipe) | 14 (صفر منها win32؛ كلها تبعيات اختيارية غائبة قائمة أصلًا) |
| اختبارات الركيزة السالبة الحقيقية (no_filesystem_escape / no_network_escape / resource_limits / watchdog) | معطلة (تجميع) | **تعمل واجتيزت 4/4 ضد namespaces+seccomp حقيقية** |

المجموعات الخمس التي فكّها الإصلاح (كلها كانت `ModuleNotFoundError: win32pipe` عند خط الأساس): `tests/substrate`، `tests/eoe`، `tests/api/test_sandbox_integration.py`، `tests/core/test_cycle_stop.py`، `tests/integration/test_full_cycle.py` — نتائجها الكاملة في `evidence/order0139/TESTS_unblocked_and_windows.txt`.

---

## 3. الإصلاح D2 — سلامة الإبلاغ عن الفشل (§4)

### 3.1 العيب كما ثُبّت من كود main

مسارا صياغة تفاصيل الفشل في `src/execution/backends.py` كانا يقرآن مفاتيح تقرير الفشل بلا ضمان وجودها:

- السطر 936 (الأصل): `f" [{failure['code']}/{failure.get('reason', '')}..."` — **الفشل الحرفي الموثق عند خط الأساس**: `tests/execution/test_workspace_0133.py::test_a…` كان يسقط بـ`KeyError: 'code'` في `backends.py:936` (دليل خام من تشغيل خط الأساس — انظر §4.2).
- السطر 759 (الأصل): `f"FAILED_TO_START: {error} — {failure['code']}/{failure['reason']}: … {failure['host']} … {failure['execution_mode']}"` — أربعة مفاتيح بلا حراسة في مسار `_run`.

أي قاموس فشل بلا `code` (أو بقيمة فاسدة) كان يجعل **صياغة التشخيص نفسها** ترفع استثناءً ثانويًّا يحجب السبب الأصلي ويحول الاستجابة إلى HTTP 500.

### 3.2 الإصلاح (`src/execution/backends.py`، +35/−8)

- ثابت معلن `FAILURE_CODE_FALLBACK = "FAILURE_UNCODED"` + دالة `_failure_code(failure)`: تعيد `code` الصالح حرفيًّا، وإلا الرمز البديل المعلن (غياب/None/فارغ/غير نصي) — **لا ترفع أبدًا**.
- الموقعان (759 و936 الأصليان) صارا يقرآن عبر `_failure_code()` و`.get()` لكل المفاتيح — السبب الخام (`{error}`) يبقى ظاهرًا، والتفاصيل الأصلية لا تُستبدل.
- **ما لم يتغير عمدًا**: `exit_code`/`termination`/`stdout`/`stderr`/`artifacts`/`failure` كلها كما هي — لا تحويل فشل إلى نجاح (تؤكده اختبارات `outcome.ok is False` و`exit_code != 0`).
- **D2-b (نفس العائلة، نفس الملف، مسار صياغة نتيجة)**: `LocalSandboxBackend.verify` كان يذكر في معالج الاستثناء اسمًا **غير معرّف** (`substrate_local_substrate` — الربط الفعلي `local_substrate` منذ تعديل سابق أغفل المعالج) فيتحول `SubstrateUnavailable` الصادق إلى `NameError` ثانوي يحجب سبب الاستغناء. صُحح إلى `local_substrate.SubstrateUnavailable` — علاج من عائلة D2 نفسها: «منع استثناء ثانوي يحجب السبب الأصلي أثناء صياغة النتيجة» (§4 وجميع استدعاءات مسار صياغة النتيجة).

### 3.3 الاختبارات الإلزامية (§4) — `tests/execution/test_failure_reporting_0139.py` (جديد، 219 سطرًا)

الحالات الثلاث الإلزامية حرفيًّا + مسارات إضافية، كلها عبر `execute()`/`_run()` الحقيقيين (seam معتمد بنمط 013.1: حقن نتيجة `_run` مباشرة لعزل اختبار الصياغة عن سلوك المضيف):

| الحالة | الاختبار | النتيجة |
|---|---|---|
| `code` صالح | `test_failure_with_valid_code_shown_verbatim` — الرمز يظهر حرفيًّا | PASS |
| لا `code` | `test_failure_without_code_no_secondary_exception` — لا KeyError؛ `FAILURE_UNCODED` معلن؛ التقرير الأصلي محفوظ كما هو (لا يُخترع code مزيف)؛ `ok=False` و`exit_code=-1` (لا نجاح مضلل) | PASS |
| `code` غير صالح (None/رقم/فارغ) | `test_failure_with_invalid_code_safe` (4 حالات معلمات) | PASS |
| مسار `_run` مع تصنيف عدائي بلا مفاتيح إطلاقًا | `test_run_oserror_path_formats_safely_without_code` — السبب الخام ظاهر + الرمز البديل + التقرير سليم | PASS |
| عقد الحقول كاملًا عند الفشل | `test_execute_preserves_success_fields_on_failure` — environment_id/backend/duration/stdout/stderr + توثيق الإصلاح الواحد `repaired_attempted` | PASS |
| `SubstrateUnavailable` بلا NameError (D2-b) | `test_sandbox_verify_substrate_unavailable_honest` — `UNAVAILABLE` بسبب معلن (قبل الإصلاح: NameError حرفيًّا) | PASS |
| عقد المساعد | `test_failure_code_helper_never_raises` — 10 حالات معلمات | PASS |

---

## 4. اختبار القبول عبر مسار المنتج الحقيقي (§5)

### 4.1 المنهجية

- الخادم أُقيل **بالطريقة الحرفية من README**: `python -m venv .venv && .venv/bin/pip install -e ".[test]"` ثم `.venv/bin/python -m uvicorn api.routes:app --port 8010` — على worktree نظيف عند كوميت الإصلاح `73d8e47` نفسه (بعد commit الكود وقبل التوثيق، عمدًا، كي يكون الدليل ناتجًا عن كوميت قابلًا للفحص لا عن شجرة عابرة).
- نقاط النهاية **مكتشفة من الكود** (`src/execution/api.py`)، لا مفترضة: `/api/execution/environments`، `…/{id}/verify`، `…/{id}/test-run`، `/api/execution/runtime-state`، `/api/execution/host-truth`.
- **صفر نسخ تشخيصية معدلة وصفر sys.modules وهمية في هذا القبول كله** — كود المنتج الأصلي كما هو في الفرع. الأدوات التشخيصية لم تُستخدم إلا في الاختبارات المعلمية المعتمدة أعلاه.
- 14 استجابة خام محفوظة مع كود HTTP ومدة كل طلب: `evidence/order0139/api/` (01–14) + تدقيق برمجي آلي: `evidence/order0139/ACCEPTANCE_AUDIT.txt`.

### 4.2 النتائج (كلها HTTP 200 — لا 500 في أي خطوة)

**A. قبل أي تحقق — STRICT_ISOLATED يرفض (03):** على قاعدة تشغيل جديدة، سُجلت `local-linux` بوضع `DETECTED` **و`sandboxed=True`** (مقابل `sandboxed=False` في 013.8 على المضيف نفسه — هذا وحده أثر D1 المباشر في مسار المنتج). `runtime-state?policy=STRICT_ISOLATED` أعادت حالة تجهيز (لا READY) — الحجب قبل الإثبات، **بلا أي سقوط تلقائي إلى الوضع المتوافق**.

**B. التحقق الحقيقي (05) — `READY` بفحوص §6 التسعة المسماة:** boot=COMPLETED، execute=exit 0، write_file، read_file، delete_file، working_directory=`/tmp` (جذر pivot_root الخاص بالركيزة)، architecture=x86_64، **isolation=الشبكة محجوبة داخل الركيزة (namespaces بلا واجهات — فشل DNS داخل العزل هو الدليل الحي على منع الاتصال الخارجي)**، capture=PROBE-JSON ملتقط. `worker_id=local-sandbox:1`.

**C. التنفيذ الحقيقي عبر مسار المنتج (07 + 08):** `POST /api/execution/environments/1/test-run` — نفس الإطلاق الذي يستخدمه التطبيق فعليًّا (توثيق api.py: نفس عقد `create_workspace` لا بناء يدوي):
- `ok=true`, `termination=COMPLETED`, `exit_code=0`, المدة 92ms (والتكرار 98ms — حتمي).
- stdout: `os: Linux`, `arch: x86_64`, `python: (3, 12, 15)`, **`cwd: /tmp` (داخل العزل)**, `file_write_read_delete: True`, `file_gone: True`.
- evidence: `worker_id=local-sandbox:1`, `execution_boundary=POSIX_PROCESS`, `workspace_exists=true`, `failure_code=""` (لا فشل).

**D. مسار الفشل عبر API (09–13):** أُضيفت بيئة عامل بعيد بنقطة نهاية ميتة (`http://127.0.0.1:9/`) عبر الواجهة الرسمية ثم:
- `test-run` عليها → **HTTP 200** (لا 500) بنتيجة صادقة: `ok=false`, `termination=FAILED_TO_START`, `detail="تعذر الوصول للعامل … Connection refused"` — السبب الأصلي ظاهر بلا استثناء ثانوي.
- `verify` عليها → `NOT_READY` بسبب `connectivity` معلن.
- حُذفت عبر الواجهة (13) وتأكد التنظيف (14): `local-linux` وحدها `HEALTHY/sandboxed=True/default`.

**E. host-truth (04):** `isolation=SANDBOXED` و`local_execution=AVAILABLE` و`platform_compatibility_mode=false` — مقابل `UNAVAILABLE`/الوضع المتوافق في 013.8 على المضيف نفسه.

### 4.3 بروتوكول STRICT_ISOLATED (متطلب §5)

- **رفض التنفيذ عند غياب العزل**: مثبت حيًّا في (03) قبل التحقق (لا بيئة READY → حجب معلن بلا سقوط)، ومثبت اختباريًّا في مجموعة الانحدار القائمة `tests/execution/test_policy_no_fallback_0131.py` (**8/8 PASS** في تشغيل هذه الجولة — الدليل الخام: `evidence/order0139/TESTS_policy_no_fallback.txt`: `resolve_executor` لا يسقط أبدًا تحت STRICT، `run_code_unified` يعيد POLICY_BLOCK حرفيًّا، مسبار sandbox يعلن UNAVAILABLE بالسبب، وهوية البيئة تتبع المضيف).
- **منع التحول التلقائي**: `policy.py` (غير معدل في هذا الفرع) لا يعيد بيئة لا تفي بالسياسة أبدًا — والسلوك مثبت بالاختبارات القائمة أعلاه.

---

## 5. فحص الأسرار (§6 + §2 قبل الدفع)

- ماسح نمطي (`scripts/order0139_secret_scan.py` خارج المستودع) فحص **39 ملفًا** في نطاق الدفع (diff الكوميتات + كل ملفات الأدلة): أنماط GitHub/OpenAI/Anthropic/AWS/Google/Slack/Bearer/مفاتيح خاصة/إسنادات api_key عامة/صيغة مفتاح z.ai الداخلية — **صفر إصابات** (النتيجة الخام مع قائمة الملفات في `evidence/order0139/` مسجلة في سجل العمل).
- سجل الخادم (22 سطرًا، INFO فقط) فُحص بالأنماط نفسها: صفر إصابات — منسوخ منقحًا إلى `evidence/order0139/SERVER_LOG_sanitized.log`.
- لا `secrets.json` ولا ملفات تشغيل حساسة في نطاق الدفع (يفرضها الماسح رفضًا لا تنبيهًا)؛ مخزن أسرار runtime أعيد للنظافة بعد الجولة.
- **لم يُطبع أي مفتاح في أي نقطة من هذه الجولة**، ولم تُعدَّل إعدادات مزود ولا روابط نماذج أدوار (لم تكن ضرورية للاختبار المصرّح به).

---

## 6. الاختبارات الكاملة — الأرقام القابلة لإعادة التوليد

كل الأرقام أدناه من تشغيل فعلي عند `73d8e47` على هذا المضيف (Linux x86_64, container, python 3.12.15)، مع مقارن خط الأساس من worktree غير معدل عند `0a26fc70`:

| المجموعة | خط الأساس 0a26fc70 | بعد 73d8e47 | تصنيف الفروق |
|---|---|---|---|
| `tests/substrate` | خطأ تجميع (win32pipe) | **9 passed, 13 skipped** | مفكوك بالكامل؛ الـ13 skip = bridge يحتاج خادم gRPC (NOT RUN) |
| `tests/execution` | 10 failed, 61 passed, 1 skipped | **64 passed, 7 failed, 1 skipped** | 3 إخفاقات خط الأساس أصلحها الكوميت (انظر أدناه)؛ الـ7 الباقية قائمة بالمعرفات نفسها عند خط الأساس (انظر §7) |
| `tests/api/test_sandbox_integration.py` | خطأ تجميع (win32pipe) | **3 passed** | مفكوك |
| `tests/core/test_cycle_stop.py` | خطأ تجميع (win32pipe) | **10 passed** | مفكوك |
| `tests/eoe` | خطأ تجميع (win32pipe) | **49 passed, 2 failed** | مفكوك؛ الفشلان بيئيان (قاعدة خارجية ثابتة المسار غير موجودة — أدناه) |
| `tests/integration/test_full_cycle.py` | خطأ تجميع (win32pipe) | **5 passed** | مفكوك |
| `tests/test_order6_revised.py` | 10 failed, 14 passed | **24 passed** | 10 إخفاقات خط الأساس أصلحها الكوميت |
| `tests/e38/…mission.py` | 1 failed | 1 failed | مطابق — قائم لا علاقة له |
| `tests/factory/tools/test_run_command.py` | 9 failed | 9 failed | مطابق — pytest-asyncio غير مثبت (نقص بيئة قائم) |
| `tests/unified/test_vs003.py` | 12p/3err | 12p/3err | مطابق |
| أخطاء تجميع المستودع | 19 | **14** | −5 كلها win32pipe؛ الـ14 الباقية تبعيات اختيارية غائبة (aiohttp/cryptography/requests) قائمة عند خط الأساس |

**الاختبارات التي فشلت عند خط الأساس بفعل D1/D2 وأصلحها هذا الكوميت (13):** `test_h_workspace_provisioned_before_launch`، `test_j_repair_workspace_resumes_same_job`، `test_test_run_api_uses_same_launcher_and_creates_workspace` (فشلها الحرفي عند خط الأساس كان `KeyError: 'code'` في backends.py:936 — نص D2 بعينه، موثق خامًا في سجل الجولة)، و10 اختبارات في `tests/test_order6_revised.py`.

**NOT RUN المصرّح به (§3.3):** اختبارات Windows التشغيلية (لا مضيف Windows)؛ bridge/gRPC (13)؛ pytest-asyncio-dependent (10)؛ الملفات الـ14 المعطلة التجميع (تبعيات اختيارية). **لا يُدّعى اجتياز أي منها.**

---

## 7. الإخفاقات القائمة الموثقة (قائمة عند خط الأساس — خارج نطاق D1/D2، لا تُصلح هنا)

سبعة اختبارات في `tests/execution` تفشل **قبل الإصلاح وبعده بالمعرفات نفسها** — أسبابها من تشخيص هذه الجولة:

1. **انزياح مفردات الحالة (3 اختبارات في test_service.py):** تتوقع `UNKNOWN/READY/…` بينما المنتج يسجل `DETECTED` عند التسجيل و`HEALTHY` بعد التحقق الناجح (نموذج 013.7 §P1) — الاختبارات لم تُحدّث بعد تغيير 013.7.
2. **عقد `failure` على مسار النجاح (test_a):** `_run` يعيد معلومات PID في خانة الفشل حتى عند النجاح (أثر 013.7 §P14) — الاختبار يتوقع `{}` وفق عقد 013.3 §9 الموثق. هذا الانزياح نفسه يجعل `if failure:` في `execute()` صادقًا على مسار النجاح فيُعاد تشغيل الأمر مرتين ويظهر `[REPAIR_WORKSPACE]` في كل نتيجة متوافقة ناجحة (سلوك قائم عند خط الأساس على مسار COMPATIBLE حصرًا؛ **مسار العزل المعتمد في القبول غير متأثر** — `LocalSandboxBackend.run_code` لا يستخدم هذا النمط).
3. **بيئات اختبار منحرفة (b/f/i):** محاكاة cwd غير الصالح لم تعد تولد OSError المتوقع، وتوقّع `READY` مقابل `HEALTHY` الحالي، وتوقّع عدّاد إطلاق بعد إصلاح لا يُطلق أصلًا في بيئة الاختبار.
4. **اختبارات eoe (2):** تتطلب قاعدة بيانات خارج المستودع في مسار ثابت (`/home/z/my-project/agent-hub/…` في conftest) غير موجودة على هذا المضيف — اعتماد بيئي لا علاقة له بالكوميت.

**قرار النطاق:** هذه ليست من D1/D2، وإصلاحها (تحديث مفردات أو تغيير عقد نتيجة) تغيير سلوك يحتاج تفويضًا خاصًا — تُوثَّق هنا للتحكيم وتُترك لأمر مستقل.

---

## 8. عيوب قائمة مكتشفة أثناء القبول (جديدة الاكتشاف، موثقة بأدلة، **غير مُصلحة** — خارج النطاق)

- **PD-1 (الأهم — فجوة مفردات بوابة السياسة):** `verify` الناجح يكتب `status="HEALTHY"` (013.7 §P1)، بينما بوابة السياسة `environment_satisfies` (policy.py، نموذج 011/013.1) تشترط حرفيًّا `status == "READY"` — **ولا كود في المستودع يكتب READY أبدًا** (grep موثق: الصفوف تُكتب DETECTED/HEALTHY/NOT_READY/UNAVAILABLE فقط، والاختبارات القائمة تزرع READY يدويًّا). النتيجة الحية: بعد تحقق ناجح كامل (05)، `runtime-state?policy=STRICT_ISOLATED` (06) ما زالت تقول DISCOVERING و`selected=null` — أي أن **مهمة حقيقية تحت STRICT_ISOLATED ستبقى محجوبة عند بوابة المهمة حتى مع بيئة معزولة مثبتة الجاهزية**، لسبب مفردات لا لغياب عزل. الدليل: `evidence/order0139/api/06_runtime_state_strict_after_verify.json`. هذا عيب قائم عند 0a26fc70 كان **مخفيًّا** لأن D1 كان يمنع verify من الوصول للركيزة أصلًا على Linux؛ إصلاح D1 كشفه. يحتاج أمرًا مستقلًا (توحيد المفردات عبر compute_environment_state أو تحديث البوابة).
- **PD-2 (تنفيذ مزدوج على المسار المتوافق):** تفصيله في §7.2 أعلاه — أثر جانبي لوضع PID في خانة الفشل.
- **PD-3 (F-3 من 013.8 — ما زال قائمًا):** `snapshot.py:474 project.get()` على ORM يكسر `/api/projects/{id}/runtime` (لم يُمسك — خارج نطاق هذا الأمر حرفيًّا).

---

## 9. جدول CLAIM / OBSERVED / VERIFIED / NOT PROVEN

| الادعاء | الملاحظة الخام | الحكم |
|---|---|---|
| الاستيراد الطبيعي للركيزة يعمل على Linux | عملية نظيفة بلا وهمية: نجاح (اختبار §2.3) | **VERIFIED** |
| الاستيراد لا يعتمد على win32pipe | صفر وحدات win32 في sys.modules بعد التحميل | **VERIFIED** |
| سلوك Windows محفوظ | فحص AST للفرع الحرفي + الاستيرادات المحروسة كما هي | **VERIFIED بنيويًّا** — التشغيل الفعلي على Windows: **NOT RUN** (لا مضيف) |
| فشل بلا code يُعرض دون استثناء ثانوي | 3 حالات إلزامية + تصنيف عدائي + API حي: كلها بلا KeyError وبدون 500 | **VERIFIED** |
| الفشل لا يتحول إلى نجاح | `ok=False` و`exit_code=-1` في كل الحالات المختبرة | **VERIFIED** |
| SubstrateUnavailable بلا NameError | اختبار D2-b: UNAVAILABLE بسبب معلن | **VERIFIED** |
| تنفيذ حقيقي داخل عزل عبر مسار المنتج الأصلي | test-run عبر API: exit 0 داخل pivot_root/netns، والشبكة محجوبة داخل العزل (فحص isolation) | **VERIFIED** |
| STRICT_ISOLATED يرفض عند غياب العزل | حي (03) + 6/6 من مجموعة 013.1 القائمة | **VERIFIED** |
| verify كامل الفحوص التسعة | READY بكل الفحوص المسماة (05) | **VERIFIED** |
| الأسرار لم تُسربب | ماسح 39 ملفًا + سجل خادم: صفر أنماط | **VERIFIED** (بحدود الأنماط المفحوصة) |
| 7 إخفاقات اختبارية | قائمة عند خط الأساس بالمعرفات نفسها — موثقة بأسبابها | **OBSERVED** (ليست من إصلاح هذا الأمر) |
| فجوة HEALTHY/READY تمنع READY عند بوابة المهمة | حي (06) + grep: لا كاتب لREADY | **OBSERVED — عيب قائم للتحكيم** |
| جاهزية تجربة المالك الحقيقية | — | **NOT CLAIMED** — ممنوعة نصًّا في هذا الأمر |

---

## 10. قواعد الحماية الملتزمة

- `main` و`origin/main` غير محركين (تحقق حي قبل البدء وبعد كل كوميت)؛ `e10-rp22r2a2-sanitized-git-environment` (c5920c8) وفرع 013.8 (2be533c) غير ملموسين؛ لا merge ولا reset ولا force-push ولا amend ولا stash.
- لا WSL2/Docker ولا أي تثبيت نظامي؛ لا مهمة OSINT؛ لا تعديل إعدادات مزود أو روابط أدوار (لم تلزم)؛ لا نسخ أسرار إلى الفرع (ماسح يرفض).
- الأدلة كلها من إنتاج كود المنتج الأصلي في الفرز (لا نسخ تشخيصية) — الأدوات التشخيصية استُخدمت داخل اختبارات معلمية معتمدة فقط، وقد وُصفت بصراحة.

---

## 11. الحالة النهائية (§7.6)

**`ENGINEERING_FIX_VERIFIED`**

- **D1 مقبول وفق §8:** الاستيراد الطبيعي يعمل على Linux (اختبار عملية نظيفة بلا وهمية) **و**تجربة الركيزة نجحت عبر مسار المنتج الأصلي (verify 9/9 داخل namespaces+seccomp حقيقية + test-run عبر API بـexit 0 داخل العزل مع حجب الشبكة المثبت) — على كوميت قابل للفحص المستقل (73d8e47).
- **D2 مقبول وفق §8:** حالات الفشل المختبرة الثلاث (صالح/غائب/فاسد) + التصنيف العدائي + SubstrateUnavailable + الفشل الحي عبر API — كلها تُعرض بتشخيص صادق دون استثناء ثانوي ودون نجاح مضلل.
- **حدود الصدق:** 7 إخفاقات اختبارية قائمة (بالمعرفات نفسها عند خط الأساس) وثلاثة عيوب قائمة مكتشفة (PD-1/PD-2/PD-3) موثقة بأدلة لأمر مستقل؛ اختبارات Windows التشغيلية NOT RUN.
- **لا يُصدر هذا التقرير READY_FOR_OWNER_REAL_TRIAL** — يتطلب ذلك تحققًا من إعدادات جهاز المالك وبيئته، وهو صراحة خارج نطاق الإثبات الحالي.

**الخطوة التالية المقترحة للمالك بعد التحكيم:** أمر مستقل صغير لعلاج PD-1 (توحيد مفردات HEALTHY/READY في بوابة السياسة) لأنه المانع البنيوي الوحيد المتبقي بين «ركيزة معزولة مثبتة الجاهزية» و«مهمة STRICT_ISOLATED تنطلق فعلًا من الواجهة» — ثم فحص إعداد المزود على جهاز التجربة وتوفير بيئة العزل هناك وفق بطاقة 013.8.
