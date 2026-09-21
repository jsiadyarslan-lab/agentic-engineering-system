# البيئة والجاهزية — دليل القدرات (الأمر 009)

> **القاعدة الذهبية (§27):** وجود التكوين ≠ جاهزية · HTTP 200 ≠ نجاح أداة ·
> عمل `/models` ≠ عمل الاستدلال · وجود الركيزة ≠ ركيزة قابلة للاستخدام.
> `READY` تُعلن بمسبار حقيقي ناجح حصرًا — والجاهزية تنتهي صلاحيتها.

## المعمارية

```
Workflow/Chat Event → Event Store (events) → Live Event Bus → SSE → UI
        ↘ Tool Failure Classification → ToolEvidence (tool_invocations)
        ↘ Readiness Probes → CapabilityRecord (capability_records)
                                            ↓
                          Task Preflight → PASS (ابدأ) / BLOCKED (لا تبدأ)
```

- **سجل القدرات** (`src/readiness/registry.py`): جرد حقيقي من الكود —
  أدوات القائمة البيضاء، الركيزة، الويب، الشبكة، git، الملفات، LLM من
  سجل المزودين. الأداة غير المنفذة (browser) تظهر `UNAVAILABLE` بسبب
  `NOT_IMPLEMENTED` — لا `READY` أبدًا.
- **المسبارات** (`src/readiness/probes.py`): DNS حقيقي، HTTPS حقيقي،
  بحث حقيقي يفحص قابلية النتائج للتحليل (نجاح النقل ≠ نتيجة صالحة)،
  ركيزة تُقلع وتكتب وتقرأ وتنفذ وتلتقط، git حقيقي، واستدلال LLM فعلي
  (توكن واحد — `/models` وحده لا يكفي).
- **انتهاء الصلاحية (§24):** كل `READY` تحمل `expires_at`؛ بعد انقضائها
  تُعرض `STALE` ويُعاد الفحص قبل الاعتماد — لا جاهزية أبدية.
- **الفحص المسبق** (`src/readiness/preflight.py`): قبل بدء أي مهمة —
  القدرات المطلوبة تُفحص؛ الحاجز يوقف البدء بسبب معروف وخطة استرداد
  ومسار مالك إن لزم («الإجراء قبل البدء، لا بعده»).

## الواجهات

| النقطة | الوظيفة |
|---|---|
| `GET /api/environment/readiness` | كل القدرات بآخر قراءة (STALE مطبقة) |
| `POST /api/environment/probe` | مسبار واحد حقيقي `{capability_id}` |
| `POST /api/environment/probe/all` | الفحص الكامل |
| `GET /api/environment/inventory` | جرد البيئة الفعلي (OS/CPU/شبكة/أدوات) |
| `GET /api/environment/metrics` | مقاييس حية: استدعاءات/فشل بالتصنيف/تعافٍ/زمن |

## تصنيف فشل الأدوات (إضافة الأمر 008)

كل استدعاء أداة يخلف `ToolInvocation` دائمًا يفصل:

- `transport_status` (SUCCESS/FAILED) عن `result_status` (USABLE/NOT_USABLE)
- `failure_class`: TOOL / EXECUTOR / PROVIDER / SANDBOX / NETWORK / AUTH /
  INPUT / VALIDATION / DEPENDENCY / TIMEOUT / POLICY_BLOCK /
  INSUFFICIENT_EVIDENCE
- `failure_stage`: PROVIDER_RESOLUTION … TOOL_RESULT … ARBITRATION
- `failure_reason` الدقيق: NO_RESULTS ≠ RESULTS_NOT_ANALYZABLE ≠
  PROVIDER_ERROR ≠ TIMEOUT (تمييز إلزامي)

سياسة الإعادة (لا إعادة عمياء): المهلة/الشبكة/الحد تعاد؛ «لا مادة»
تُعاد باستعلام مراجَع أو أداة بديلة مسجلة فقط (لا تكرار حرفي أبدًا)؛
المصادقة/السياسة لا تعاد. المحكَّم يستلم كتلة الفشل كاملة فيقرر
(RETRY/REVISE/GATE/HARD STOP) على السبب الحقيقي.

## كيف تجهّز بيئة لمهام هندسية ذاتية معقدة

1. **LLM**: أضف مزودًا من ⚙ الإعدادات ← المزودون (Base URL + مفتاح)،
   اربط كل دور بمزود/تكوين/نموذج، ثم «اختبار الاتصال» — ثم «فحص» قدرة
   «استدلال النموذج الفعلي» في قسم البيئة (توكن حقيقي واحد).
2. **البحث الخارجي**: يتطلب وصول HTTPS خارجيًا؛ تحقق من قدرة
   `web_search` (بحث فعلي بنتائج قابلة للتحليل). محجوب؟ المهام
   البحثية تُحجب قبل البدء بسبب معروف.
3. **الركيزة المعزولة**: Linux/x86_64 (WSL2 على Windows). على منصات
   أخرى القدرة `UNAVAILABLE` بصدق — كتابة الملفات داخل العزل تتطلبها.
4. **Git/الملفات/القاعدة**: قراءة/كتابة فعليّة في مجلد المشروع.
5. قبل المهمة: شغّل «فحص كامل للبيئة» واقرأ الشارات — كل شيء
   `READY`؟ ابدأ. هناك `NOT_READY`؟ اقرأ السبب والإجراء المعروضين.

## الأسرار

لا قيمة مفتاح تعبر أي مسار عرض: لا UI ولا logs ولا أحداث ولا أدلة
ولا أخطاء ولا SSE — مرجع/قناع فقط (`secrets_store`).
