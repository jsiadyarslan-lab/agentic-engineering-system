# تقرير الأمر 013.11 — تحصين بوابة أدلة الجاهزية (READINESS EVIDENCE GATE)

> **حسم التنفيذ: `READINESS_EVIDENCE_GATE_VERIFIED`** — البوابة المحصّنة
> منفذة ومختبَرة (13 حالة إلزامية خضراء) ومطبقة على كل مستهلكي الجاهزية،
> والفشل مغلق عند كل عيب بنية/اكتمال/حداثة/هوية/إثبات عزل وُجد في §2+§3
> من الأمر. الأوجه المتبقية المعلنة كلها خارج نطاق هذا الأمر (§6-7 أدناه).

---

## 0. ملخص تنفيذي

| البند | القيمة |
|---|---|
| الأمر | 013.11 — تحصين بوابة أدلة الجاهزية |
| الفرع | `order01311-readiness-evidence-hardening` (من رأس 013.10 `e5998b6`) |
| رأس الأمر 013.10 المتحقق منه | `e5998b62bea01322c724d1bf74be587675deaac8` |
| الأصل المتحقق من نسبه | `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (= `origin/main` حيًّا وقت §1، لم يتحرك) |
| النسب المتحقق منها | `e5998b6 → 3c2a68a → 4bd5ada → 73d8e47 → 0a26fc7` (نظيفة، بلا دمج/إعادة ضبط) |
| الوضع النهائي | HEAD = آخر كومِت على فرع 013.11 (انظر §1-3)؛ **لم يُدمج في main إطلاقًا** |
| النطاق المعدل | `src/execution/policy.py` (+`service.py` مساران، `runtime_state.py` مسار عرض) + الاختبارات + هذا التقرير |
| الاختبار الإلزامي الجديد | `tests/execution/test_readiness_evidence_01311.py` — 28 اختبارًا (12 حالة إلزامية بأشكالها البارامترية + تكامل + توثيق عقود) **كلها ناجحة** |
| المفردات | لا حالة جديدة أُضيفت للسلم (§3-6)؛ التقادم يُعرض بحالة قائمة (`DEGRADED`) بسبب حرفي قابل للفحص |
| العيوب المتبقية | PD-2 (`FAILURE_UNCODED` في رد test-run الناجح) — **خارج نطاق 013.11 صراحةً ولم يُطالب بإصلاحه**؛ وقائمة انجراف ما قبل الوجود (§5) |

---

## 1. التحقق من الأساس (§1 من الأمر — تم قبل أي تعديل)

1. **رأس 013.10 حيًّا**: `git rev-parse HEAD` على الفرع الأصلي = `e5998b6…` ✓
2. **النسب إلى 0a26fc7**: `git log --oneline e5998b6..0a26fc7` معكوس = السلسلة أعلاه، بلا كومِتات أجنبية ✓
3. **main/origin/main لم يتحركا**: `git ls-remote origin main` حيًّا = `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` = المحلي ✓ (لم يتطلب الأمر التوقف) — وأعيد التحقق عند الإغلاق: origin/main ما يزال `0a26fc7` حرفيًا.
4. **التفريع**: `git checkout -b order01311-readiness-evidence-hardening` من `e5998b6`، مؤكَّد بـ `git rev-parse` ✓
5. الملفات المتسخة الموروثة من جلسات سابقة (E2-R/، E5/، E6-R2/، E7/، E8-R/، `tests/orchestrator/test_e5_agent_runtime_integration.py`، …) **لم تُمس ولم تُكومِت** — استُبعدت حصرًا.
6. **ملاحظة إغلاق موثقة (لا فعل عليها)**: `main` **المحلي** على هذا القرص عند انحراف سابق للجلسة (`d814f83` «E4-RATIFICATION-CORRECTION-4» بتاريخ 2026-10-07 — كومِت جلسة عمل أقدم؛ ليس سليلًا لـ origin/main). هذا الأمر لم يأنس `main` المحلي أو البعيد بأي شكل؛ الشرط الوحيد في §1 (عدم تحرك origin/main) لم ينكسر — والانحراف المحلي سابق لهذا الأمر ومسجل هنا للشفافية لا لإصلاحه (خارج النطاق: لا دمج ولا إعادة ضبط).

## 2. العقد المطبق — بوابة الأدلة المحصّنة (§2)

الموقع الوحيد للحكم: `src/execution/policy.py` — `readiness()` =
**صحة ناجحة ∧ أدلة تحقق مكتملة وصالحة البنية وحديثة ∧ أهلية السياسة (∧ إثبات عزل صريح تحت STRICT)**.

### 2-1. شكل الدليل (رفض مغلق — لا تجاهل العيب واحتساب البقية)

`verification_evidence()` يرفض الدليل كله عند **أي** مما يلي (كود: `policy.py` — `verification_evidence` + `readiness`):

| العيب | الكود الحرفي في blockers | الاختبار |
|---|---|---|
| عنصر فحص غير قاموسي | `VERIFICATION_MALFORMED` | حالة 4 |
| اسم فحص غائب/فارغ/مكرر | `VERIFICATION_MALFORMED` | حالة 3 |
| نجاح غير منطقي صريح (`ok` غائب/None/`"true"`/1) — يقبل `ok is True` حصرًا | `VERIFICATION_MALFORMED` | حالة 5 |
| أي فحص `ok=False` | `VERIFICATION_MALFORMED` (نجاح غير منطقي) | حالة 6 |
| فحص مطلوب غائب من عقد الخلفية | `VERIFICATION_REQUIRED_MISSING` (+ سرد الأسماء الغائبة) | حالات 2+3 |
| خلفية غير معروفة (لا عقد لها) | لا تُحقق أبدًا — `VERIFICATION_MALFORMED` | `required_check_names` + اختبار العقود |

### 2-2. مجموعات الفحوص المطلوبة لكل خلفية — مستخرجة من الكود لا بالتخمين (§2-2)

المصدر الوحيد: `src/execution/backends.py` (التحققات الحقيقية الثلاث) — والثابت `REQUIRED_CHECKS_DOC` في `policy.py` يوثقها للاستهلاك:

| الخلفية | المجموعة المطلوبة (بالترتيب الحرفي من الكود) | مرجع الكود | إثبات العزل |
|---|---|---|---|
| **LOCAL + sandboxed** (ركيزة Linux معزولة) | `boot, execute, write_file, read_file, delete_file, working_directory, architecture, isolation, capture` (9) | `LocalSandboxBackend.verify` — backends.py:396 (وسم 013.2 §6 في :432) | فحص `isolation` نفسه = إثبات حي: `ok` تعني شبكة محجوبة داخل namespaces (التفصيل الحرفي «شبكة العزل محجوبة» — backends.py:467؛ نجاح DNS يعني أن العزل مكسور) |
| **LOCAL بلا عزل** (وضع متوافق) | `preflight, boot, execute, write_file, read_file, delete_file, working_directory, architecture, isolation, capture` (10) | `LocalProcessBackend.verify` — backends.py:792 (وسم 013.2 §6 في :830) | **لا شيء** — فحص `isolation` هنا معكوس الدلالة عمدًا: `ok` تعني أن الشبكة تعمل («معلن: بلا عزل — وضع متوافق، الشبكة تعمل» — backends.py:861)؛ صدق إعلان لا إثبات عزل |
| **REMOTE_WORKER** | `connectivity, authentication, heartbeat, environment_probe, workspace_probe, execute_probe, artifact_probe` (7) | `RemoteWorkerBackend.verify` — backends.py:1151 (سلم 011 §10) | **لا فحص عزل في السلم إطلاقًا** (فرق عقد موثق) — الإعلان من العامل نفسه (`network_policy: worker-declared` — backends.py:1130) |

**التحقق من عدم التخمين**: عقد المتوافق (10 أسماء بالترتيب) مطابق حرفيًا لأدلة التحقق الحية المسجلة في 013.10 — `docs/evidence/order01310/api/05_verify_local.json` (`preflight,boot,execute,…,capture`). سلم العامل: الاسم الأول `connectivity` مطابق لأول فحص في الدليل الجزئي الحي المسجل (`docs/evidence/order0139/api/11_verify_dead_worker.json` — السلم يتوقف عند أول فشل فلا تسجيل كامل) والترتيب الكامل من الكود المنتج. الركيزة المعزولة لا تُشغَّل على مضيف Windows هذا (بلا ادعاء) — أسماؤها من الكود المنتج حصرًا، وهي مطابقة لعقد المتوافق مطروحًا منه `preflight` كما يقول الكود نفسه (:830 «نفس مفردات الركيزة المعزولة»).

### 2-3. إثبات العزل الصريح تحت STRICT (§2-3) — `sandboxed=True` وحده لا يكفي

| مسار | الإثبات المطلوب داخل الأدلة |
|---|---|
| LOCAL معزولة | فحص `isolation` حاضر بنجاح (`ok is True`) — دلالته في هذا العقد = شبكة محجوبة حيًّا |
| REMOTE_WORKER | `profile.sandboxed = True` **داخل `last_probe_detail`** (إعلان العامل المسجل لحظة التحقق الحقيقي) + اكتمال السلم — **موثّق كحدّ بروتوكول v1**: العامل لا يقدم بعد إثباتًا شبكيًا حيًّا للعزل، وما يقدم إعلانًا موقّعًا بزمن التحقق داخل الأدلة |
| LOCAL بلا عزل | لا يُطالب أصلًا — الأهلية تحت STRICT ترفضه قبل العقد |

الحجب بسبب حرفي: `VERIFICATION_ISOLATION_PROOF_MISSING` (اختبار الحالة 10-ج: عامل سلمه كامل وأعلن العزل في الصف لكن الأدلة بلا الإعلان → محجوب).

### 2-4. هوية البيئة داخل الأدلة (§2-4)

إن حملت الأدلة `profile.environment_id` وجازت المقارنة فيجب أن يطابق معرف البيئة الحاملة — وإلا `VERIFICATION_IDENTITY_MISMATCH`. سجلات قديمة بلا المعرف تُقبل بلا حكم هوية (الربط البنيوي: الأدلة مخزنة على صف البيئة نفسه كتبه `verify_environment`) — **موثق كتسامح توافق رجعي** في docstring الدالة (013.11 §6-2).

### 2-5. المستهلكون المحدثون كلهم (§2-5 + §3-5)

| المستهلك | الموقع | كيف يخضع للحكم المحصّن |
|---|---|---|
| اختيار البيئة بسياسة | `execution/policy.py::select_environment_for_policy` | عبر `environment_satisfies → readiness` مباشرة |
| اختيار البيئة بلا سياسة (المسار العام) | `execution/service.py::select_environment` + `owner_action_for_missing_environment` | **رُقّي في هذا الأمر**: كان `status=="READY"` خامًا — صار الصحة ∧ الأدلة المكتملة الحديثة |
| المسبار/المنفذ (مصدر واحد) | `resolve_executor` → `select_environment` | موروث |
| runtime-state | `execution/runtime_state.py::_state_from_environments` | **رُقّي**: جاهز عبر `readiness()` الكامل؛ الحجب يعرض أول سبب `VERIFICATION_*` حرفيًا (`DEGRADED` — لا مفردة جديدة) |
| الفحص المسبق | `readiness/preflight.py` (مسار sandbox + مسار COMPATIBLE) | عبر `select_environment`/`environment_satisfies` |
| قدرة sandbox المشتقة | `readiness/service.py::capability_view` | الصحة ∧ `verification_evidence()["complete"]` (يشمل الحداثة) |
| التجهيز | `execution/provisioner.py:357` + `:700` | عبر `environment_satisfies` |
| حالة العرض لكل بيئة | `execution/service.py::compute_environment_state` | عبر `readiness()`؛ `ineligible_reason` يحمل الأكواد الحرفية |

## 3. الصلاحية الزمنية TTL (§3)

### 3-1. تعريف قائم؟ (§3-1) — لا

فُحص `src/` و`docs/` بالأنماط `ttl|stale|max_age|verification`: التعريفات القائمة كلها لنطاقات أخرى — مسبارات المزودين (`readiness/service.py::_is_expired` + `readiness/probes.py ttl_seconds`)، نبضة الوظائف (`harness/jobs.py STALE_HEARTBEAT_S`)، ووسم STALE الودعي لفشل بدء بعد جاهزية (`execution/service.py::_mark_stale` — حدثي لا زمني). **لا تعريف موحد لعمر أدلة تحقق البيئة** — فأُضيف المركزي التالي.

### 3-2. القيمة المركزية (§3-2)

```python
VERIFICATION_MAX_AGE_S = 300.0   # src/execution/policy.py
```

مصدر القيمة: **اتساق مع مهلة مسبار بيئة التنفيذ نفسه** — `sandbox_probe_result` يعيد `ttl_seconds: 300` في ثلاثة مواضع؛ دُمجت في ثابت واحد `PROBE_TTL_S = 300` في `execution/service.py` وأصبح المسبار يقرأه، فالعلاقة معلنة بالكود: **عمر الدليل المقبول = مهلة المسبار الذي ينتجه** (`PROBE_TTL_S == VERIFICATION_MAX_AGE_S` — مثبتة في الاختبار الأول بالملف الإلزامي). لا وثيقة معمارية تحدد قيمة أخرى.

### 3-3. قواعد الزمن (§3-3) — `_parse_verified_at` في policy.py

- غائب/فارغ → غير صالح (`VERIFICATION_TIME_INVALID:زمن التحقق غائب`).
- غير قابل للتحليل → غير صالح (`…زمن غير قابل للتحليل`).
- مستقبلي أكثر من تسامح 120ث (انحراف ساعة بين الكاتب والقارئ) → غير صالح (`…زمن مستقبلي غير معقول`).
- Naive يُعامل UTC (حفظ SQLite يجرّد المنطقة عن `_utc_now()` الق aware — نفس ما تعرضه الـAPI).
- العمر > 300ث → `fresh=False` والحجب بسبب `VERIFICATION_STALE` مع عمر الدليل رقمًا في النص.
- عند الحد نفسه (≤300) يبقى الدليل صالحًا (الشرط `>` حصري — حالة 8).

### 3-4. حالة الصحة التاريخية تبقى — ولا حالة عرض جديدة (§3-4)

عند التقادم: **لا يُمس** `status` المخزن (HEALTHY/READY يبقيان)، ولا أُضيفت أي مفردة للسلم (`RUNTIME_STATES` لم تتغير). العرض: `compute_environment_state` يبقي `health_state` ويحجب `ready` بسبب `VERIFICATION_STALE` في `ineligible_reason`؛ runtime-state يعرض `DEGRADED` (حالة قائمة في المفردات) والسبب الحرفي أول blocker. التاريخي `READY` بأدلة صالحة حديثة يبقى جاهزًا (توافق رجعي — الحالة 11).

## 4. الاختبار الإلزامي (§4) — `tests/execution/test_readiness_evidence_01311.py`

**النتيجة: 28/28 ناجحة.** القائمة الإلزامية (12) + التكامل + إضافات:

| # | الحالة الإلزامية (نص الأمر) | الاختبار | النتيجة |
|---|---|---|---|
| 1 | أدلة كاملة صحيحة حديثة → READY فقط عند الأهلية | `test_complete_fresh_evidence_ready_when_eligible` | ✓ |
| 2 | فحص واحد من المجموعة المطلوبة → لا READY | `test_single_check_of_required_set_not_ready` | ✓ |
| 3 | مطلوب غائب/مكرر/بلا اسم → لا READY | `test_missing_duplicate_unnamed_required_check_not_ready` (4 أشكال) | ✓ |
| 4 | عنصر غير قاموسي → لا READY | `test_non_dict_element_not_ready` | ✓ |
| 5 | `ok` غائب/None/`"true"` → لا READY | `test_ok_missing_none_or_string_not_ready` (4 أشكال، شامل 1-int) | ✓ |
| 6 | أي `ok=False` → لا READY | `test_any_false_check_not_ready` | ✓ |
| 7 | `last_verified_at` غائب/غير قابل للتحليل/مستقبلي → لا READY | `test_missing_or_unparseable_verified_at_not_ready` (4 أشكال) | ✓ |
| 8 | تجاوز TTL → لا READY بسبب `VERIFICATION_STALE` (وعند الحد صالح) | `test_stale_beyond_ttl_not_ready_with_expiry_reason` (250/301/3600ث) | ✓ |
| 9 | صالح حديث لكن غير معزول تحت STRICT → محجوب (متوافق 10 فحوص + عامل معلن False) | `test_fresh_valid_non_isolated_strict_blocked` | ✓ |
| 10 | صالح حديث + إثبات عزل → الاختيار مسموح (ركيزة/عامل؛ وبلا إعلان داخل الأدلة → محجوب) | `test_fresh_valid_proven_isolated_strict_selected` | ✓ |
| 11 | `READY` تاريخية بأدلة كاملة حديثة → توافق رجعي | `test_legacy_ready_with_valid_complete_fresh_evidence` | ✓ |
| 12 | جزئي/قديم/بلا زمن لا يفتح بوابة المهمة ولا يطلق المنفذ | `test_partial_or_stale_evidence_never_opens_mission_gate` (3 أشكال: resolve_executor=(None,None) + task_preflight=BLOCKED) | ✓ |
| 13 | **التكامل الإلزامي** (ليس وحدويًا حصرًا): خدمة اختيار البيئة + runtime-state + preflight على قاعدة واحدة — فتح صادق ثم تقادم صادق على الأسطح الثلاثة معها | `test_integration_selection_runtime_state_preflight_fresh_then_stale` | ✓ |

إضافات توثيقية: القيمة المركزية 300 واتساقها مع `PROBE_TTL_S`، وفروق العقود الثلاثة موثقة كاختبار (`test_backend_contracts_match_documented_differences`).

**نزاهة البيانات الاصطناعية (§5)**: كل بذور الأدلة تمر عبر `execution_policy.valid_evidence(backend, sandboxed)` — دالة تعكس العقد الحرفي الكامل للخلفية (لا قائمة مختزلة يُتوقع منها READY). ولا مخدّعات تُستعمل لإثبات اكتمال الأدلة على الركيزة الحقيقية: إثبات الركيزة الحي لم يُشغَّل هنا (مضيف بلا ركيزة — §5 من الأمر يمنع تثبيت WSL2/Docker)، وإثباته في هذا الأمر هو تطابق أسماء/ترتيب الفحوص مع الكود المنتج ومع الأدلة الحية المسجلة سلفًا (§2-2 أعلاه).

## 5. المقارنة مع الأساس ونتائج الاختبارات (§6-3)

**المنهجية**: شجرة أساس worktree عند `e5998b6` (نفس رأس 013.10) — نفس الاختيار من الاختبارات على الطرفين، بذور الاختبارات كما هي عند كل طرف (الأساس ببذوره القديمة والفرع بالبذور المرقّاة للعقد الكامل). السجلات الحية كاملة في `docs/evidence/order01311/`.

### 5-1. المجموعات المتأثرة (execution + readiness + regression + snapshot_0134 + provisioning_011 + stop_api)

| | الأساس `e5998b6` | فرع 013.11 | الفرق |
|---|---|---|---|
| ناجح | 135 | **174** | +39 |
| فاشل | 22 | **11** | **−11 (صفر فشل جديد)** |

### 5-2. مجموعة tests/api (نُفذ منفصلًا — خلط جذري conftest بين tests/api وtests/workflow في نداء واحد يكسر التجميع: قيد تنظيمي معلن لا عيب منتج)

| | الأساس `e5998b6` | فرع 013.11 | الفرق |
|---|---|---|---|
| ناجح | 149 | **155** | +6 |
| فاشل | 20 | **14** | **−6 (صفر فشل جديد)** |

### 5-3. الحصيلة الإجمالية

| | الأساس | الفرع |
|---|---|---|
| مجموع الفاشل | 42 | **25** |
| مجموع الناجح | 284 | **329** |
| فشل جديد بفعل التحصين | — | **صفر** (مجموعتا فشل الفرع جزئيتان حرفيًا من مجموعة الأساس) |
| فشل موروث أُصلح بترقية البذور للعقد الكامل | — | **17** (10 في المجموعات المتأثرة + 6 في api + إصلاح خطأ ترقية داخلي) |

- الفشلان الوحيدان اللذان أدخلهما التحصين أثناء التطوير (جدول اتساق 013.10: `NameError` في ترقية البذرة؛ `test_preflight::test_stale_ready_is_reprobed`: تضارب عقد البذرة مع تصحيح العزل الصادق 011 §4-§5) صُحّحا قبل الكومِت — السجلان في الأدلة (`intermediate_nameerror_fixed.txt`، `run1_affected_first_pass.txt`).
- **المتبقي 25 = مجموعة ما قبل الوجود المطابقة للأساس حرفيًا** (انجراف موثق سلفًا في تقرير 013.10 §5.4): `workspace_0133` ×5، `backends::test_remote_worker_protocol_real_over_http`، `provisioner_013::test_provision_full_cycle_real`، `provisioning_011` ×2، `stop_api` ×2، و14 في api (بينها دورات التخطيط الحية الطويلة: `approval_live`، `task_live` ×2، `sse_013` ×3، `control_actions_0134` ×2، `lifecycle_0131`، `projects_api` ×2، `providers_crud`، `restart_013`) — كلها مسارات حية تتطلب ركيزة/عاملًا/شبكة حقيقية أو شجرات جلسات سابقة، بلا علاقة ببوابة الأدلة.

## 6. العيوب المتبقية والحدود المعلنة (§6-5)

1. **PD-2 — `FAILURE_UNCODED` في رد test-run الناجح**: حقل `failure` يحمل بيانات العملية حتى عند النجاح. تصنيفه من حكم التحكيم على 013.10 نفسه: **خارج نطاق 013.11 صراحةً**. لم يُطالب بإصلاحه ولم يُمس كوده. (مرجع: `src/execution/backends.py` — تعبئة `failure` غير المشروطة في مسار run_code).
2. **حد بروتوكول العامل v1 (موثق لا مُختلق)**: سلم العامل البعيد بلا فحص عزل شبكي حي؛ إثبات العزل للعامل = إعلان العامل داخل الأدلة لحظة التحقق + اكتمال السلم. رفع السقف يتطلب تطويرًا في بروتوكول العامل نفسه (خارج النطاق).
3. **تسامح التوافق الرجعي للهوية**: سجلات أقدم من 013.11 بلا `profile.environment_id` تُقبل بلا حكم هوية (الربط البنيوي بصف البيئة). يُغلق تلقائيًا مع أول تحقق جديد لكل بيئة.
4. **انجراف ما قبل الوجود (11 اختبارًا في المجموعات المتأثرة + ما يقابله في api)**: مطابق للأساس حرفيًا — قائمته الكاملة ومبرراته في تقرير 013.10 §5.4؛ لم يُصحح هنا لخروجه عن النطاق (لا يخص بوابة الأدلة).
5. **قيود بيئة التحقق**: مضيف Windows بلا ركيزة عزل — لا إثبات حي لبوابة الركيزة المعزولة (9 فحوص) على هذا المضيف؛ صحتها البنيوية مثبتة بمطابقة الكود والأدلة الحية المسجلة سلفًا. لا بيانات مالك ولا OSINT استُعملت.

## 7. شروط الإغلاق (§7) — محققة

- ✓ جزئي/فاسد/قديم لا يمنح READY (الحالات 2-8+12: كل أشكال العيب محجوبة بأكواد حرفية).
- ✓ دليل صالح كامل لا يحجب عندما تتحقق الشروط فعلًا (الحالات 1+10+11+13: اختيار/بوابة/حالة عرض تفتح معًا).
- ✓ القديم يمنح حجبًا صادقًا مع بقاء الصحة التاريخية وإظهار `VERIFICATION_STALE` (الحالة 8 + التكامل 13).
- ✓ سرّ القبول: **الدليل الجاهز الصحيح لا يُظلم، والدليل المعيب لا يُؤتمن** — بوابة واحدة يقرأها الجميع.

---

## الملحق A — سجل أوامر التحقق النهائي

السجلات الحية الكاملة في `docs/evidence/order01311/`:

| الملف | المحتوى |
|---|---|
| `mandatory_tests_28_passed.txt` | الاختبار الإلزامي 28/28 (الفرع) |
| `baseline_e5998b6_affected.txt` + `baseline_failures.txt` | المجموعات المتأثرة على الأساس (22 فشلًا) |
| `affected_run1_first_pass.txt` | أول جري على الفرع (23 فشلًا — قبل تصحيح خللَي الترقية) |
| `intermediate_nameerror_fixed.txt` | سجل الخلل الوسيط المصحح (NameError) |
| `affected_final_nonapi.txt` | الجري النهائي للمجموعات المتأثرة (11 فشلًا = مجموعة الأساس الموروثة حصرًا) |
| `api_baseline_e5998b6.txt` + `api_baseline_failures.txt` | api على الأساس (20 فشلًا) |
| `api_branch_final.txt` + `api_branch_failures.txt` | api على الفرع (14 فشلًا، جزئية من الأساس) |
| `commit_file_list.txt` | قائمة الملفات المؤهلة للكومِت (18) |
| `secrets_scan.txt` | فحص الأسرار — نظيف |

## الملحق B — فحص الأسرار (§7)

الأنماط المفحوصة على الملفات المؤهلة للكومِت (المصدر والاختبارات والتقرير والأدلة): `sk-`، `nvapi-`، `AIza`، `ghp_`، `xox`، `Bearer`، `api_key`، `secret`، `password`، `token_ref =` — النتيجة: **لا قيم أسرار**؛ الأسماء الرمزية فقط (`token_ref` كاسم عمود، أسماء مزودين `nvidia/openai_compatible` بلا مفاتيح). سجل الفحص في دليل الأدلة.
