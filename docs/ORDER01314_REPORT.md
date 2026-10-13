# تقرير الأمر 013.14 — تمهيد عامل معزول معتمد + تصحيح ساعة الأدلة

> **الحالة النهائية: `OWNER_INFRA_REQUIRED`** — لا عامل Linux معتمد متاح؛ مطلوب تدخل مالك واحد محدد لتفعيل ركيزة العزل.

---

## 0. ملخص تنفيذي

| البند | القيمة |
|---|---|
| الأمر | 013.14 — AUTHORIZED STRICT WORKER BOOTSTRAP & EVIDENCE-CLOCK CLOSURE |
| الفرع | `order01314-authorized-worker-bootstrap` من `order01313-first-real-owner-mission@6b23366` |
| خط الأساس | `origin/main = 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` ✓ |
| الفرع المصدر | `6b2336697ad0652e3c887aef14cd75d610c5a8dd` ✓ |
| الحكم | **`OWNER_INFRA_REQUIRED`** — لا مورد معزول متاح؛ طلب تدخل موثق |

---

## 1. تحقق خط الأساس (§2)

```bash
origin/main: 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f  ← متطابق
source branch tip: 6b2336697ad0652e3c887aef14cd75d610c5a8dd  ← متطابق
```

- لا reset، لا rebase، لا merge، `main` لم يتحرك.
- ملف `E6-R2/e6_commit_manifest.json` المعدل من جلسة سابقة **لم يُضمن** في الكومِت الجديد (مذكور في git_baseline كـ modified in worktree فقط).
- لا أسرار في ملفات الأمر.

---

## 2. D1 — تصحيح موثوقية الوقت

### 2.1 ساعة المضيف
| الفحص | النتيجة |
|---|---|
| `w32tm /query /status` | **الخدمة غير بدأت** (0x80070426) — مزامنة NTP غير نشطة |
| Python `datetime.datetime.now(timezone.utc)` | 2026-10-13T23:01:xx (وقت حقيقي عند الجمع) |
| تواريخ أدلة 013.13 | **مفبركة** (2025-01-15) — أُصلحت في هذا الأمر |

### 2.2 إعادة التقاط الأدلة بختم زمني حقيقي
جميع ملفات `docs/evidence/order01314/` الآن تحمل `checked_at`/`captured_at` من `datetime.datetime.now(datetime.timezone.utc)` عند الجمع الفعلي، مع حقل `clock_source` موثق.

### 2.3 تقييم موثوقية الساعة
- **ساعة النظام**: تُظهر تاريخ 2026-10-13 (متسق مع "أكتوبر 2026" في الحكم التحكيمي)
- **خدمة وقت Windows**: معطلة → لا دليل على مزامنة NTP حديثة
- **النتيجة**: **`CLOCK_EVIDENCE_UNTRUSTED`** — الطوابع الزمنية حقيقية عند الجمع، لكن مزامنة المصدر غير مثبتة. لا تعديل صامت لأدلة 013.13 القديمة.

### 2.4 نظافة فرق الكومِت vs نظافة شجرة العمل
| المقياس | الحالة |
|---|---|
| **فرق الكومِت (commit diff)** | نظيف — فقط ملفات `order01314/` الجديدة |
| **شجرة العمل (worktree)** | تحتوي على `E6-R2/e6_commit_manifest.json` معدل + آثار جلسات سابقة غير متعقبة — **لا تدخل في الكومِت** |

---

## 3. D2 — البحث عن عامل معتمد

### 3.1 الجرد الشامل

| المورد | فحص | النتيجة | دليل |
|---|---|---|---|
| **WSL2** | `wsl_available()` | ❌ `WSL2_NO_DISTRO` | الافتراضية معطلة: `WSL2 is unable to start since virtualisation is not enabled` |
| **Docker/Container** | `runtime_truth()` | ❌ غير متاح | `container_runtime: ""`, `docker: ""` |
| **Remote Worker** | متغيرات بيئة + DB | ❌ غير مضبوط | `REMOTE_WORKER_*=NOT SET`، صفر بيئات `REMOTE_WORKER` |
| **نشرات سحابية** | glob terraform/k8s/github | ❌ لا توجد | لا ملفات نشر في المستودع |
| **Substrate crates** | قراءة المصدر | ⚠️ stubs فقط | `substrate-docker/remote` = placeholder |

### 3.2 خلاصة
**لا يوجد عامل Linux معتمد ومصرح به متاح** لتسجيله كبيئة `REMOTE_WORKER` مع `sandboxed=true` ومسبار حي يعمل.

---

## 4. D3 — بوابة القبول / طلب تدخل المالك

### 4.1 شروط `STRICT_WORKER_READY` — كلها **غير محققة**
| الشرط | الحالة |
|---|---|
| بيئة `REMOTE_WORKER` مسجلة ومتحقق منها | ❌ لا توجد |
| هوية أدلة مطابقة للبيئة | ❌ لا توجد بيئة |
| فحوص مطلوبة كاملة وحديثة | ❌ لا عامل |
| مسبار عزل حي بتحدي جديد | ❌ لا ركيزة |
| منع الشبكة من العزل لا من المضيف | ❌ لا ركيزة |
| `test_d2_live_substrate_isolation_probe_on_linux` يعمل دون SKIP | ❌ لا ركيزة |
| `test_d3_isolated_success_contract_on_linux` يعمل دون SKIP | ❌ لا ركيزة |
| حالة UI = حالة API | ❌ لا عامل |

### 4.2 طلب تدخل المالك (ملف منفصل: `docs/evidence/order01314/owner_intervention_request.md`)

**الخيار الوحيد للمتابعة:** تفعيل الافتراضية على هذا الجهاز (WSL2) **أو** توفير عامل Linux خارجي معتمد.

لا fallback، لا محاكاة، لا دمج.

---

## 5. التسليم والقبول

### 5.1 الأدلة (`docs/evidence/order01314/`)

| الملف | المحتوى |
|---|---|
| `runtime_truth.json` | جرد المضيف مع `captured_at` حقيقي + `clock_source` + `w32tm_status` |
| `substrate_check.json` | `_substrate_available()=false` مع وقت حقيقي |
| `env_list.json` | بيئة وحيدة `local-windows` (LOCAL, sandboxed=false) مع وقت حقيقي |
| `env_vars_check.json` | `REMOTE_WORKER_*=NOT SET` مع وقت حقيقي |
| `git_baseline.txt` | تحقق المراجع + تمييز نظافة الكومِت vs شجرة العمل |
| `secrets_scan.txt` | نظيف |
| `wsl_detection.json` | `wsl_available()` → `WSL2_NO_DISTRO` بتفاصيل |
| `owner_intervention_request.md` | طلب تدخل مالك واحد محدد |

### 5.2 مقارنة الانحدار
لا كود جديد، لا اختبارات جديدة — صفر انحدار.

---

## 6. القرار التالي

**`OWNER_INFRA_REQUIRED`** — الأمر يكتمل هنا.

الخطوة التالية (خارج هذا الأمر): المالك يختار **خيار أ** (تفعيل الافتراضية على هذا الجهاز) أو **خيار ب** (عامل Linux خارجي). فقط بعد توفر الركيزة يمكن إعادة تشغيل 013.13 (E11) أو أمر لاحق.