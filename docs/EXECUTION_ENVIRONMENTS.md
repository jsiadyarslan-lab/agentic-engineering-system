# بيئات التنفيذ — دليل المالك

> الأمر 010: النظام يفصل بين **كشف** القدرة و**توفيرها**. هذه الصفحة
> توثق المسار الهندسي الحقيقي لتوفير بيئة تنفيذ صالحة ثم استئناف
> العمل — لا رسائل «غير متاح» بلا مخرج.

## المعمارية

```
Control Plane (Agentic Engineering System)
        ↓ resolve_executor()  ← المسبار والمنفذ من مصدر واحد
ExecutionBackend
├── LOCAL          ركيزة Linux/x86_64 المحلية (namespaces+seccomp)
└── REMOTE_WORKER  عامل حقيقي عبر HTTP (scripts/execution_worker.py)
```

- **لا خلفية وهمية**: DOCKER/SANDBOX/REMOTE عامة غير مدرجة في خيارات
  الإضافة — المدعوم من الكود فعلًا هو LOCAL وREMOTE_WORKER حصرًا.
- **READY بلا تحقق مستحيل**: كل بيئة تُسجل UNKNOWN ثم يقرر التحقق
  الحقيقي (إقلاع/كتابة/تنفيذ/التقاط) حالتها.
- **المسبار = المنفذ**: كلاهما يمر عبر `resolve_executor()`؛ كل نتيجة
  تحمل `environment_id`، وفشل بدء بعد READY يوسم `ENVIRONMENT_MISMATCH`
  باسم البيئة وزمن تحققها — لا تناقض بلا تفسير.

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
