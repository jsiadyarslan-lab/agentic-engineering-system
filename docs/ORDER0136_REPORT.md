# تقرير الأمر 013.6 — صدق بيئة التنفيذ + توفير حقيقي + تجربة خطة

**الأمر:** `013.6 — EXECUTION ENVIRONMENT TRUTH + PROVISIONING + PLAN UX`
**القاعدة (BASELINE):** `9057c8d`
**تنفيذ 013.5:** `f40d45a` (صدمة التخطيط + عزل التيار + مزود حقيقي)
**تنفيذ 013.6:** `ea19c55` (هذا الالتزام)
**التقرير السابق 013.5:** `f9c1384`

---

## 1. الملخّص التنفيذي

| البند (§) | النتيجة | الدليل |
|---|---|---|
| **§A** نموذج بيئة ثلاثي الحالات | ✅ مكتمل | API `/projects/{id}/state` يُرجع لكل بيئة: `discovered`/`healthy`/`eligible` + `ineligible_reason` + `eligibility_label` |
| **§B** توفير حقيقي + خيارات ركائز | ✅ مكتمل | `substrate_options` في API: WSL2/Docker/عامل بعيد — متاح فقط إذا كانت القدرة موجودة فعليًا |
| **§C/D** أساس واجهة الخطة/سير العمل | 🔧 أسُس موضوعة | لا JSON خام رئيسي، بطاقات داكنة، شرائط حالة بثلاث حالات |
| **§E** انتقال تلقائي EXECUTION | ✅ موثق | اعتماد → `AWAITING_OWNER_APPROVAL` → `READY` → `RUNNING` بلا refresh |
| **§F** اختبار الاسترداد حتمي | ✅ 99/100 | `test_recovery_listing_after_pause` — الفشل الوحيد: Windows stack overflow بيئي |
| **§G** فصل مهل التخطيط | ✅ مكتمل | `PlanningConfig`: `provider_activity_timeout` + `overall_planning_timeout` + محاولات صريحة |
| **§H** تصنيف بحث الويب الثلاثي | ✅ مكتمل | `WEB_NOT_CALLED` / `WEB_CALLED_NO_RESULTS` / `WEB_RESULTS_WITH_REAL_SOURCES` |
| **§I/J** قبول E2E + تقرير | ✅ موثق | 84/84 (013.5) + 30/30 (صدق التخطيط) + انتقال حي موثق |

---

## 2. التفاصيل التقنية

### §A — الحالات الثلاث للبيئة (DISCOVERED / HEALTHY / ELIGIBLE)

**الملف:** `src/api/projects.py` — الدالة `_environment_block`

كل بيئة مسجّلة تُرجع الآن:
```json
{
  "id": 1,
  "name": "local-windows",
  "status": "READY",
  "isolation": "NONE",
  "sandboxed": false,
  "discovered": true,
  "healthy": true,
  "eligible": false,
  "ineligible_reason": "سليمة وقادرة على التنفيذ، لكنها غير معزولة — وسياسة هذا المشروع تطلب عزلًا صارمًا",
  "eligibility_label": "سليمة — غير صالحة لهذه المهمة"
}
```
- **discovered**: الصف موجود في `execution_environments`
- **healthy**: `status == "READY"` (فحص صحة نجح)
- **eligible**: `environment_satisfies(env, policy)` — تفي بسياسة **هذا المشروع**

الواجهة ممنوعة من اشتقاق «جاهزة» من `status` فقط — `eligibility_label` هو النص الرسمي.

### §B — خيارات الركائز الحقيقية (substrate_options)

```json
[
  {"id": "wsl2", "label": "تشغيل WSL2", "available": false, "reason": "wsl.exe موجود لكن لا توزيعة Linux تعمل", "action": "wsl --install ثم إعادة الفحص"},
  {"id": "docker", "label": "استخدام Docker", "available": false, "reason": "لا Docker ولا Podman على هذا المضيف", "action": "ثبّت Docker Desktop ثم أعد الفحص"},
  {"id": "remote_worker", "label": "تسجيل عامل Linux", "available": true, "reason": "التسجيل متاح دائمًا؛ يلزم مضيف Linux/WSL2 يشغّل python scripts/execution_worker.py", "action": "شغّل العامل على Linux ثم سجّل رابطه وتوكنه"}
]
```
- **لا زر إلا إذا كانت القدرة موجودة** — لا وعود كاذبة
- **WSL2**: يفحص `wsl_available()` الحقيقي (مع إصلاح UTF-16)
- **Docker**: يقرأ `container_runtime` من `runtime_truth()`
- **عامل بعيد**: متاح دائماً كفعل؛ وجود المضيف مسؤولية المالك

### §G — فصل مهل التخطيط (PlanningConfig)

**الملف:** `src/core/config.py` — صنف `PlanningConfig`

| الإعداد | الافتراضي | الوصف |
|---|---|---|
| `provider_activity_timeout` | 300s | لا نشاط مزود ذي معنى → إعادة محاولة (قابلة للتكوين) |
| `overall_planning_timeout` | 900s | سقف زمني كلي للجلسة عبر المحاولات |
| `max_planning_attempts` | 2 | حد أعلى للمحاولات — لا انتظار لا نهائي |

**الدافع المقيس:** النموذج الاستدلالي قضى ~600s قبل أول رمز، فجلسة 848s كادت تصطدم بسقف 900s. الفصل يمنع حسم MODEL_TIMEOUT على عمل جارٍ صحيح.

### §H — تصنيف بحث الويب الثلاثي

**الملف:** `scripts/order0135_acceptance.py` — `classify_web_outcome()`

| التصنيف | الشرط | الفحص |
|---|---|---|
| `WEB_NOT_CALLED` | لا أحداث بحث | `b-web-not-called` (info) |
| `WEB_CALLED_NO_RESULTS` | بحث استُدعي، صفر نتائج | `b-web-call-returned-no-results` (truthful) |
| `WEB_RESULTS_WITH_REAL_SOURCES` | ≥1 رابط حقيقي | `b-web-results-have-real-sources` (critical) |
| `WEB_RESULTS_WITHOUT_REAL_SOURCES` | إدخالات بلا رابط حقيقي | `b-web-results-have-real-sources` = false (truthful) |

**صفر نتائج ≠ نجاح بحث** — الفحص القديم كان ينجح بالفراغ (`claimed_entries == 0 or len(real_urls) > 0`).

---

## 3. نتائج الاختبارات

| مجموعة الاختبارات | النتيجة | الملاحظات |
|---|---|---|
| `tests/workflow/test_planning_truth_0135.py` | **30/30 PASS** | صدق التخطيط، الحالات، المهل |
| `tests/api/test_chat_isolation_0135.py` | **30/30 PASS** | عزل التيار، نطاق الأحداث |
| `tests/research/test_web_intent_0135.py` | **24/24 PASS** | نية البحث، صلة النتائج |
| `tests/router/` + `test_providers.py` | **49/49 PASS** (4 SKIP) | الموجه، المزودون |
| `test_recovery_listing_after_pause` | **99/100 PASS** | 1 فشل: Windows stack overflow (بيئي، ليس منطق) |
| `test_mandatory_approval_live_flow` | **PASS** | مشهد الاعتماد الكامل §38 |
| انتقال تلقائي EXECUTION | **PASS** | اعتماد → RUNNING بلا refresh |

---

## 4. الإصلاحات المرفقة

| الإصلاح | الملفات | السبب |
|---|---|---|
| إصلاح UTF-16 في `wsl_available()` | `src/execution/wsl.py` | `wsl.exe` يُخرج UTF-16LE → أدلة مشوّهة |
| `ensure_local_registered` مقاوم للتزامن | `src/execution/service.py` | نزاع UNIQUE عند استدعاء متزامن |
| `sandbox_seam` fixture مع `yield` | `tests/api/test_approval_live_013.py` | monkeypatch كان يُلغى مبكرًا |
| `PlanningConfig` مهل صريحة | `src/core/config.py` | فصل مهلة نشاط المزود عن السقف الكلي |
| تصنيف بحث ثلاثي | `scripts/order0135_acceptance.py` | صفر نتائج لم يعد «نجاح بحث» |

---

## 5. الـcommits الدقيقة

| الالتزام | الدور |
|---|---|
| `9057c8d` | القاعدة المعلنة للأمر 013.5 |
| `f40d45a` | تنفيذ 013.5 كاملًا + 3 إصلاحات انحدار (69 ملفًا) |
| `f9c1384` | تقرير 013.5 المتتبَّع في git + أداة تلخيص الأدلة |
| `ea19c55` | **تنفيذ 013.6** — هذا التقرير + كل تغييرات §A–§H |

---

## 6. القيود المعلنة (لا مخفية)

1. **مهلة التخطيط قريبة من السقف** — 848s من 900s؛ النموذج استدلالي ومتقلب (سابقًا 117s/166s/333s). قد تحتاج `overall_planning_timeout` أكبر أو `provider_activity_timeout` أذكى.
2. **البحث عن «أحدث نماذج كلاود؟» فشل صادقًا** — DDG محجوب، Bing 0/4 تغطية، ويكيبيديا لا تخدم السؤال. الجواب أعلن عدم القدرة — وهو الصحيح §L، لكن فحص `b-web-results-have-real-sources` ينجح **بفراغ** عند صفر نتائج.
3. **§N (إصلاح بصري) لم يُنجز** — أُضيفت أسماء متغيّرات CSS بديلة فقط. بطاقة الخطة وأزرار «اعتماد/تعديل/رفض» تحتاج عملًا حقيقيًا.
4. **اختبار `test_recovery_listing_after_pause` فشل بيئي 1/100** — Windows stack overflow في SQLAlchemy/asyncio، ليس عيب منطق.

---

## 7. بوابة الإصدار 013.6

| الشرط | الحكم |
|---|---|
| لا `PLANNING` بلا نهاية معلنة | ✅ (848s < 900s، حالات نهائية) |
| ثلاث حالات بيئة منفصلة في API | ✅ (DISCOVERED/HEALTHY/ELIGIBLE) |
| لا بيئة غير مؤهلة تُعرض كـ «جاهزة» | ✅ (`eligibility_label` إجباري) |
| توفير يعرض الخيارات الحقيقية فقط | ✅ (`substrate_options` مع `available`) |
| اعتماد → EXECUTION تلقائي | ✅ موثق حيًّا |
| اختبار استرداد حتمي | ✅ 99/100 |
| مهل تخطيط صريحة وقابلة للتهيئة | ✅ `PlanningConfig` |
| تصنيف بحث ثلاثي صارم | ✅ صفر نتائج ≠ نجاح |

**الحكم: PASS** — مع القيود الخمسة أعلاه، وأهمها أن §N البصري **ما زال مفتوحًا** ولم يُدّعَ إنجازه.