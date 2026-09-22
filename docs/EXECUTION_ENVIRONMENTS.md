# بيئات التنفيذ — دليل المالك

> الأمر 010: النظام يفصل بين **كشف** القدرة و**توفيرها**. هذه الصفحة
> توثق المسار الهندسي الحقيقي لتوفير بيئة تنفيذ صالحة ثم استئناف
> العمل — لا رسائل «غير متاح» بلا مخرج.
>
> الأمر 013.3: **عقد مساحة العمل وحد التشغيل** — مصدر واحد لحل
> المسارات قبل أي إطلاق عملية (انظر «عقد حل مساحة العمل 013.3»).

## المعمارية

```
Control Plane (Agentic Engineering System)
        ↓ resolve_executor()  ← المسبار والمنفذ من مصدر واحد
        ↓ resolve_execution_workspace()  ← 013.3: حل مسار موحد قبل أي إطلاق
ExecutionBackend
├── LOCAL          ركيزة Linux/x86_64 المحلية (namespaces+seccomp)
│                  WINDOWS_PROCESS (على Windows) أو POSIX_PROCESS
└── REMOTE_WORKER  عامل حقيقي عبر HTTP (scripts/execution_worker.py)
                   REMOTE_PROCESS — cwd يُحل لدى العامل
```

- **لا خلفية وهمية**: DOCKER/SANDBOX/REMOTE عامة غير مدرجة في خيارات
  الإضافة — المدعوم من الكود فعلًا هو LOCAL وREMOTE_WORKER حصرًا.
- **READY بلا تحقق مستحيل**: كل بيئة تُسجل UNKNOWN ثم يقرر التحقق
  الحقيقي (إقلاع/كتابة/تنفيذ/التقاط) حالتها.
- **المسبار = المنفذ**: كلاهما يمر عبر `resolve_executor()`؛ كل نتيجة
  تحمل `environment_id`، وفشل بدء بعد READY يوسم `ENVIRONMENT_MISMATCH`
  باسم البيئة وزمن تحققها — لا تناقض بلا تفسير.

## عقد حل مساحة العمل (013.3 §7) — جذر WinError 267 الذي عولج

قبل أي إطلاق عملية، يمر كل مسار عبر `execution/workspace.py`:

| وضع التنفيذ | host_path | runtime_path | القاعدة |
|---|---|---|---|
| `WINDOWS_PROCESS` | مسار Windows مطلق **موجود** | نفسه | مسار Linux (`/workspace`…) على Windows = **رفض قبل CreateProcess** |
| `POSIX_PROCESS` | مسار POSIX موجود | نفسه | إنشاء ← تحقق ← إطلاق |
| `WSL_PROCESS` | مسار Windows | يُحل **داخل WSL** عبر `wslpath` | عملية `wsl.exe` بلا cwd بنمط Linux أبدًا |
| `REMOTE_PROCESS` | (فارغ) | يُدار لدى العامل | يُبرهن عبر سلم `/probe` |

- **التسلسل الإلزامي**: SELECT RUNTIME ← CREATE WORKSPACE ← VERIFY ←
  START WORKER ← HEALTH_CHECK ← READY — لا «إطلاق ثم رجاء أن cwd موجود».
- **WinError 267 ونظائره** (`ENOTDIR`/`ENOENT` على cwd) ليست «فشل تنفيذ»
  عامًا بل `RUNTIME_WORKSPACE_INVALID` بتقرير مهيكل (host/cwd/
  environment_id/worker_id/execution_mode) — ثم **إصلاح واحد وإعادة
  محاولة واحدة**، لا حلقة إعادة (`tests/execution/test_workspace_0133.py`).
- زر «إعادة تجهيز البيئة» في بطاقة الفشل يعيد دورة التجهيز كاملة.

## عامل WSL2 التلقائي (013.3 §3) — لمضيف Windows تحت عزل صارم

عند التجهيز على Windows بسياسة STRICT_ISOLATED: يكتشف النظام WSL2
فعليًا (`wsl.exe ← uname ← python3`)، وإن وُجد يعبر الحد الصريح:

```
Windows ← wsl.exe ← Linux ← python scripts/execution_worker.py ← HTTP
```

- المسار يُحل **داخل WSL** (`wslpath`) ويُتحقق داخله (pwd/test -d/
  python3) قبل الإطلاق — لا تخمين ترجمة أبدًا.
- البيئة تُسجل باسم `wsl2-linux` (REMOTE_WORKER على 127.0.0.1:8901)
  وتخضع لسلم الجاهزية الكامل — READY فقط عبر فحوص حقيقية.
- إن كان العامل داخل WSL يعلن `sandboxed: false` (توزيعة بلا user
  namespaces) — يُعلن ذلك بسببه الحرفي، لا READY كاذبة.
- لا WSL2؟ التوقف الصادق `ENVIRONMENT_UNAVAILABLE` بالفجوة والفعل
  (host/required/available/missing/action).

## تشغيل عامل على Linux/WSL2 (المسار الحقيقي لغير Linux)

على أي جهاز Linux (أو WSL2 على Windows) فيه Python 3.10+:

```bash
# من جذر المستودع (للتنفيذ المعزول عبر الركيزة):
python scripts/execution_worker.py --port 8900 --token سر-مشترك

# أو من أي مكان ببايثون فقط (وضع subprocess معلن بلا عزل):
python execution_worker.py --port 8900 --token سر-مشترك
```

الوضعان معلنان بصدق في `/capabilities` (`sandboxed: true/false`) —
بطاقة البيئة في الواجهة تعرضهما كما هما.

## إضافة البيئة من الواجهة

```
الإعدادات ← بيئات التنفيذ ← إضافة بيئة
    الاسم:    linux-worker-1
    الخلفية:  REMOTE_WORKER
    الرابط:   http://<ip-الجهاز>:8900
    التوكن:   سر-مشترك        (يُخزن محليًا في مخزن الأسرار — لا يُعاد أبدًا)
← إضافة ← تحقق (فحوص حقيقية عبر الشبكة) ← READY
```

ثم «تعيين افتراضية» ليختارها preflight والمنفذ تلقائيًا. زر
«تنفيذ اختباري» يثبت المنفذ نفسه (طباعة os/arch/python من داخل البيئة).

## بروتوكول العامل (v1)

| الطرف | المسار | الوظيفة |
|---|---|---|
| عامل | `GET /health` | نبضات: {ok, uptime_s, active_runs, backend_mode} |
| عامل | `GET /capabilities` | وصف البيئة الفعلي من العامل نفسه |
| عامل | `POST /probe` | فحوص boot/write+execute/capture حقيقية |
| عامل | `POST /run` | {run_id, code, timeout_s} → سجل تنفيذ + أدلة base64 |
| عامل | `POST /cancel` | {run_id} → SIGKILL لمجموعة العملية |

- التوثيق: `Authorization: Bearer <token>` — بدونه 401 صريح.
- stream events في v1: النتيجة سجل واحد يعاد نشره أحداثًا من مستوى
  التحكم (معلن لا مفترض)؛ checkpoint مسؤولية مستوى التحكم.
- اصطلاح الأدلة داخل الركيزة: `/artifacts/<name>` (مطلق) — معلن في
  `capabilities.artifacts_root`.

## استئناف المهمة بعد توفير البيئة

المهمة المحجوبة تحفظ حالتها (لقطة استئناف) — بعد أن تصبح البيئة
READY: افتح المحادثة ← زر الاستئناف (أو `POST /api/cycle/resume`)
فتكمل من اللقطة داخل البيئة الجديدة.

## الحالة القانونية الواحدة (013.2 §1-§7)

مصدر واحد للحقيقة تشتق منه كل الواجهات وسكربتات القبول — لا بطاقة
ولا تقرير يخترع حالة:

| الطرف | المسار | الوظيفة |
|---|---|---|
| تحكم | `GET /api/execution/runtime-state?policy=X&project_id=Y` | الحالة القانونية: state/coherent/required/actual/missing/evidence |
| تحكم | `POST /api/environment/provision` `{policy}` | دورة التجهيز الواعية بالسياسة (تسجل كل خطوة في الدائم مع تقدم٪) |
| تحكم | `GET /api/projects/{id}/state` | اللقطة تحمل `environment.runtime_state` — نفس القراءة حصرًا |

- آلة الحالة المقفلة: DISCOVERING → PROVISIONING → BOOTING →
  HEALTH_CHECK → READY → RUNNING (+DEGRADED/INTERRUPTED/FAILED/
  UNAVAILABLE). لا نص «جاهزة» عامًّا خارجها.
- READY قانونية فقط ببرهان: بيئة (id دائم) + فحوص مسماة ناجحة
  (boot/execute/write_file/read_file/delete_file/working_directory/
  architecture/isolation/capture) + توافق السياسة + هوية مسجلة.
- المطلوب (REQUIRED) والفعلي (ACTUAL) مفصولان حرفيًا — نص المتطلب
  لا يحمل كلمة «جاهزة» أبدًا (درس 013.1: عنوان «غير جاهزة» مع
  متطلب يقول «بيئة معزولة جاهزة» = تناقض مرفوض).
- STRICT_ISOLATED على مضيف بلا مسار عزل (Windows بلا WSL2/Docker
  وبلا عامل بعيد) = UNAVAILABLE بفجوات حرفية {need/detected/action}
  — لا READY كاذبة للبيئة المتوافقة ولا فشل ملفق.

## البحث (013.2 — إصلاح «الف مرة»)

- DDG متعدد الاستراتيجيات: lite-get ← lite-post ← html-post بترويسات
  متصفح كاملة؛ صفحة التحدّ (anomaly) تُصنّف باسمها لا «0 روابط خام».
- Bing (بلا مفاتيح) مزود رابع مبذور مفعّلًا: تحليل b_algo + فك روابط
  ck/a (base64url) — الاحتياط الذي يجعل البحث يعمل حين يحجب DDG.
- الترتيب: ddg → bing → searx (بمثيلك) → api (بمفتاحك)؛ البحث بأول
  جاهز والفشل يعاد مفصلًا لكل مزود.
