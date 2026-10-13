# تقرير الأمر 013.12 — إغلاق حدود الثقة قبل التجربة الحقيقية

> **حسم التنفيذ: `REAL_TRIAL_TRUST_BOUNDARY_VERIFIED`** — الإصلاحات
> الثلاثة المحددة (D1+D2+D3) منفذة ومختبَرة بالحالات الإلزامية كلها،
> والقبول المتكامل عبر API مثبت. أوجه القياس الحي غير الممكنة على هذا
> المضيف مسجلة `NOT RUN` حرفيًا ولا تُوصف بأنها متحققة حيًا (§4).
> لا دمج إلى main، ولا ادعاء `READY_FOR_OWNER_REAL_TRIAL` في هذا الأمر.

---

## 0. ملخص تنفيذي

| البند | القيمة |
|---|---|
| الأمر | 013.12 — إغلاق حدود الثقة (D1 هوية الدليل، D2 اختبار عزل العامل الحي، D3 صدق نتيجة التنفيذ) |
| الأصل | حكم التحكيم على 013.11: `ACCEPTED WITH CORRECTIVE ADDENDUM REQUIRED` |
| الفرع | `order01312-real-trial-trust-closure` من رأس 013.11 المتحقق منه حيًّا |
| رأس 013.11 المتحقق منه | `07d5e4e08027f1bc60e39391218e556c329e0526` (3 كومِتات كاملة الأسماء فوق `e5998b6` — مستخرجة من Git لا من التقرير: `5aa602cb…`، `702ac1fb…`، `07d5e4e0…`) |
| origin/main | `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` حيًّا عبر `git ls-remote` عند الفتح — لم يتحرك (لا توقف) |
| الوضع النهائي | آخر كومِت على فرع 013.12؛ **لم يُدمج في main إطلاقًا**؛ main المحلي المنحرف تاريخيًا (`d814f83`) لم يُمس |
| الاختبار الجديد | `tests/execution/test_trust_boundary_01312.py` (D1 ستة + D2 ثمانية + D3 أربعة) + `tests/api/test_trust_boundary_01312.py` (§6 تكامل) |
| العيوب المتبقية | §6 أدناه (بلا ادعاء إغلاق كل مخاطر الجاهزية — حد بروتوكول العامل موثق، والحي المسجل NOT RUN) |

## 1. تثبيت خط الأساس (§2)

1. **origin/main**: `git ls-remote origin main` = `0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` = المتوقع حرفيًا ✓ (لم يتحرك — لا توقف).
2. **رأس 013.11 وكومِتاته الثلاثة** (استخراج كامل من `git log --format=%H`):
   - `07d5e4e08027f1bc60e39391218e556c329e0526` docs(013.11) ملاحظة إغلاق §1
   - `702ac1fb2f5723f992d155e40e899ea4a4acbc14` 013.11 §6 تقرير وأدلة
   - `5aa602cb31cb236eb79b5da2d7bf84d29b2e9f90` 013.11 §2+§3+§4 التحصين
   - وفوقهما مباشرة `e5998b6…` (رأس 013.10) ✓
3. **الفرع الجديد**: `git checkout -b order01312-real-trial-trust-closure 07d5e4e0…` ✓
4. main المحلي المنحرف (`d814f83`، E4-ratification سابق للجلسة) وorigin/main لم يُمسا؛ لا reset/amend/force-push.
5. ملفات الجلسات السابقة (E2-R/، E5/، E6-R2/، E7/، E8-R/، `tests/orchestrator/test_e5_agent_runtime_integration.py`) لم تُكومِت. ملاحظة تشغيلية: القرص كان ممتلئًا لحظة إنشاء الفرع (`No space left on device`) — نُظف مؤقت pytest (38.8MB) وأُعيد الإنشاء بنجاح؛ لا أثر على المستودع.

## 2. D1 — إلزامية هوية أدلة الجاهزية تحت STRICT (§3)

**الموقع**: `src/execution/policy.py` (البوابة الموحدة) + `src/execution/service.py` (الكاتب).

- `verification_evidence()` يعيد الآن `identity_missing` و`identity_ok` إلى جانب `identity_reject`:
  - **مختلف** (`profile.environment_id ≠ row.id`) → `VERIFICATION_IDENTITY_MISMATCH` — فاسد تحت **أي** سياسة (كما كان).
  - **غير قابل للتحليل** (مثل `{"bad": "shape"}`) → `VERIFICATION_IDENTITY_MISMATCH:معرف غير قابل للمقارنة`.
  - **غائب** → `identity_missing=True` — ويُحجب تحت STRICT بحرف جديد `VERIFICATION_IDENTITY_MISSING` (أُضيف إلى `EVIDENCE_BLOCKERS`).
- `readiness()`: تحت `STRICT_ISOLATED` فقط، `ready` تشترط `identity_ok`؛ الحجب يعرض الحرف. **توافق COMPATIBLE_LOCAL موثق صراحةً**: سجل قديم بلا هوية يُقبل هناك بلا ادعاء عزل ولا خرق لعقد السلامة — والفرق مثبت باختبار (نفس السجل: STRICT محجوب، COMPATIBLE يمر).
- **الكاتب يربط الهوية**: `verify_environment` يحقن `result.profile["environment_id"] = environment_id` قبل حفظ الأدلة — كل تحقق جديد يولّد دليل هوية حاضرًا (تخزين الأدلة على الصف ليس بديلًا عن الحقن الصريح — §3 حرفيًا). لا تُعدل بيانات قديمة ولا تُحذف: السجل القديم بلا هوية يبقى محفوظًا ويحتاج تحققًا جديدًا.
- **المستهلكون كلهم عبر البوابة الموحدة** (لا دوال منفردة): `select_environment_for_policy` / `select_environment` العام / `resolve_executor` / `task_preflight` (فرع sandbox) / `runtime-state` / `compute_environment_state` / التجهيز — كلها تُحجب بلا تجاوز، وruntime-state يعرض الحرف.

### عيب منتج اكتشفه D1 وأُصلح

حلقة عرض سبب الحجب في `runtime_state._state_from_environments` كانت تحكم على قواميس مختزلة من `_actual_profile` (بلا `last_probe_detail`) فتحوّل **أي** حجب أدلة إلى `VERIFICATION_REQUIRED_MISSING` مضلل. أُصلحت لتقرأ القواميس الكاملة من الخدمة — فأصبح الحجب يظهر سببه الحقيقي (`VERIFICATION_IDENTITY_MISSING`/`VERIFICATION_STALE`/…).

### حالات D1 الإلزامية الست — كلها عبر البوابة الموحدة

| الحالة (نص الأمر) | الاختبار | النتيجة |
|---|---|---|
| هوية صحيحة ومطابقة ← يُسمح بالاختيار | `test_d1_matching_identity_allows_selection` | PASS |
| هوية غائبة ← حجب صادق (+ توافق COMPATIBLE موثق) | `test_d1_missing_identity_blocks_under_strict` | PASS |
| هوية غير صالحة/غير قابلة للتحليل ← حجب | `test_d1_unparseable_identity_blocks` | PASS |
| هوية تخص بيئة أخرى ← حجب (تحت السياستين) | `test_d1_foreign_identity_blocks` | PASS |
| دليل A لا يجهز B (استعارة حرفية للأدلة) | `test_d1_evidence_of_a_cannot_provision_b` | PASS |
| runtime-state وpreflight وresolve_executor لا يتجاوزون | `test_d1_no_consumer_bypasses_identity_rejection` | PASS |

## 3. D2 — اختبار العزل الحي للعامل البعيد (§4)

**العقد الجديد** (`scripts/execution_worker.py` + `src/execution/backends.py` + `policy.py`):

1. **نقطة نهاية جديدة** `POST /probe_isolation {challenge_id}` — التحدي إلزامي (422 بدونه).
2. **التنفيذ داخل الركيزة نفسها**: في وضع substrate يُشغَّل المسبار عبر `_run_in_substrate` — **آلية تنفيذ المهام ذاتها** (NetworkMode.NONE داخل namespaces) — لا عملية مضيف ولا مسبار خارجي.
3. **التمييز بين منع الشبكة وغيابها** («إثبات التحكم»): العامل يتصل بالهدف من عمليته الخاصة أولًا (الهدف = منفذ العامل نفسه الذي تصل إليه قناة التحكم أصلًا)؛ فشل إثبات التحكم → `INCONCLUSIVE` (ليس نجاحًا). داخل العزل: اتصال نجح → `BROKEN` (العزل مكسور)؛ errno من عائلة المنع/مهلة → `BLOCKED` (نجاح)؛ `ECONNREFUSED` أو خطأ غير مصنف → `INCONCLUSIVE` — **الغموض ليس نجاحًا أبدًا**.
4. **تحدي جديد لكل تحقق**: uuid يصدره الخادم، يُكرره الرد (`challenge_echoed`)، ويرتبط بـ`worker_id` و`verified_at` حاضر (سماح 120ث — `ISOLATION_PROBE_FRESHNESS_S`). إعادة استعمال نتيجة قديمة تُرفض (تحدي غير مطابق/زمن قديم/مستقبلي/بلا هوية عامل) عبر `validate_isolation_probe_response` — دالة خالصة قابلة للاختبار.
5. **`RemoteWorkerBackend.verify()`**: للعامل المعلن العزل (`profile.sandboxed=True`) يُلحق فحص `isolation_probe` بعد السلم — فشل الطلب/التحقق = فحص فاشل (السلم يكمل، النتيجة NOT_READY — فشل المسبار لا يفتح شيئًا). العامل subprocess المعلن بلا عزل يبقى على عقده المتوافق (7 فحوص) — **لا تحويل صامت إلى معزول**.
6. **`policy.py`**: `("REMOTE_WORKER", True)` = سلم 7 + `isolation_probe` (8)؛ `("REMOTE_WORKER", False)` = 7. **إثبات العزل للعامل أصبح الفحص الحي** (`profile.sandboxed ∧ "isolation_probe" in ok_names`) — إعلان sandboxed وحده لم يعد يكفي إطلاقًا. `REQUIRED_CHECKS_DOC` محدث بعقدي العامل (subprocess/isolated) مع حد الثقة.
7. **حد الثقة الموثق (§4-8)**: اختبار العزل إثبات سلوكي حي لمنع الشبكة داخل الركيزة — **ليس إثباتًا تشفيريًا لهوية مشغّل العامل**؛ مصادقة القناة (توكن مشترك Bearer) ضمن نموذج الثقة المعلن نفسه (موثق في docstring العامل و`REQUIRED_CHECKS_DOC["REMOTE_WORKER_isolated"]["trust_boundary"]`).

### حالات D2 الإلزامية — النتائج

| الحالة (نص الأمر) | الاختبار | النتيجة |
|---|---|---|
| عامل بالركيزة يجتاز المسبار الحي ← دليل عزل صالح (عبر HTTP فعلي + بوابة STRICT) | `test_d2_isolated_worker_with_live_probe_is_valid` | PASS |
| عامل subprocess يعلن عدم العزل ← لا أهلية STRICT | `test_d2_subprocess_worker_declared_not_isolated` | PASS |
| يدّعي sandboxed=True دون المسبار ← مرفوض (بروتوكول قديم 404 + أدلة بلا الفحص) | `test_d2_sandboxed_claim_without_probe_rejected` | PASS |
| نتيجة قديمة/غير مرتبطة بالتحدي ← مرفوضة (تحدي آخر/بلا تحدي/زمن قديم/مستقبلي/غير قابل للتحليل/بلا هوية عامل) | `test_d2_stale_or_unbound_challenge_rejected` | PASS |
| فشل المنع (BROKEN) أو عدم الحسم (INCONCLUSIVE) ← لا READY | `test_d2_probe_fail_or_inconclusive_never_ready` | PASS |
| فشل اتصال أو رفض مصادقة ← لا READY | `test_d2_connectivity_or_auth_failure_never_ready` | PASS |
| بقية الفحوص ناجحة + فشل المسبار ← بوابة المهمة مغلقة (resolve=None + preflight BLOCKED) | `test_d2_probe_failure_keeps_mission_gate_closed` | PASS |
| **العامل الحقيقي (السكربت الفعلي لا stub) على HTTP فعلي** في وضع subprocess المعلن يرفض أي ادعاء عزل (NOT_ISOLATED_MODE ok=False، التحدي والهوية والزمن موثقة) | `test_d2_real_worker_script_refuses_isolation_claim_in_subprocess_mode` | PASS |
| **العامل الحقيقي على Linux/ركيزة — المسبار الحي داخل الركيزة** | `test_d2_live_substrate_isolation_probe_on_linux` | **NOT RUN** (مضيف Windows بلا ركيزة — §4 حرفيًا: لا يُوصف بأنه متحقق حيًا) |

## 4. D3 — إزالة FAILURE_UNCODED من نتائج النجاح (§5)

**الجذر**: `_run` في `LocalProcessBackend` كان يعيد بيانات العملية (`pid/parent_pid`) في **خانة قاموس الفشل** حتى في النجاح، فألحق `run_code` بتفصيل النتيجة الناجحة `[FAILURE_UNCODED/…]` وبطّن API رد test-run بفشل زائف (عيب PD-2 الموثق منذ 013.10).

**الفصل الصادق** (`src/execution/backends.py` + `src/execution/api.py`):

- عقد `_run` سداسي الآن: الخامس **تقرير فشل الإطلاق/مساحة العمل حصرًا** (فارغ في النجاح والمهلة)، والسادس `process_info` (pid/parent_pid) في موقعه الصحيح — **لا تُمحى معلومات العملية**.
- `ExecutionOutcome`: حقلا `repair` و`process_info` مستقلان إضافيان؛ `ok`/`exit_code` بلا تغيير في المعنى.
- `run_code`: بيانات الإصلاح (§10) في `repair` (`attempted`/`followup_failed`) — لا تُطُن داخل قاموس الفشل؛ النتيجة الناجحة `failure={}` وبلا أي وسم فشل في التفصيل؛ فشل ما بعد محاولة إصلاح يحفظ التقرير الأصلي كما هو.
- `_workspace_invalid_outcome` (RUNTIME_WORKSPACE_INVALID) كما هو — تشخيص فشل حقيقي بفئة معلنة.
- رد test-run عبر API: `failure` يظهر `null` في النجاح فقط، ويضاف `repair` و`process_info` كحقول مستقلة.

### حالات D3 الإلزامية — النتائج

| الحالة (نص الأمر) | الاختبار | النتيجة |
|---|---|---|
| نجاح محلي متوافق ← لا حقل فشل مضلل ولا FAILURE_UNCODED (+pid محفوظ) | `test_d3_success_has_no_fake_failure_and_keeps_process_info` | PASS |
| فشل إطلاع بلا failure.code ← رمز بديل صريح مع السبب الأصلي وبلا بيانات عملية | `test_d3_launch_failure_without_code_gets_fallback_and_keeps_cause` | PASS |
| نجاح بعد إصلاح مساحة عمل ← الإصلاح مصنف إصلاحًا (repair.attempted) والفشل فارغ | `test_d3_success_after_repair_keeps_repair_out_of_failure` | PASS |
| تنفيذ معزول ناجح على Linux (إذا توفرت الركيزة) | `test_d3_isolated_success_contract_on_linux` | **NOT RUN** (مضيف Windows) |

اختبارات 013.9/013.3 القائمة التي توثق العقد القديم رُقّيت للعقد الصادق الجديد (فصل الإصلاح عن الفشل + ستية `_run`) — بمراجع: `test_failure_reporting_0139.py`، `test_workspace_0133.py::test_no_infinite_repair_loop` (الإصلاح في حقه المستقل والتقرير الأصلي سليم).

## 5. القبول المتكامل عبر API (§6)

قاعدة نظيفة عبر `project_env` + مساحات مؤقتة — `tests/api/test_trust_boundary_01312.py` عبر مسار المنتج الأصلي:

| المطلوب (نص §6) | الاختبار | النتيجة |
|---|---|---|
| (1+2) دليل بلا هوية → preflight BLOCKED + runtime-state DEGRADED بالحرف؛ تحقق جديد كامل (هوية+فحوص+مسبار ضمن العقد) → PASS + بوابة OPEN | `test_api_identityless_evidence_blocks_then_full_evidence_opens` | **PASS** |
| (3) الأسطح تتفق: preflight BLOCKED + runtime-state بالحرف MISMATCH + resolve_executor=(None,None) | `test_api_identity_mismatch_blocks_all_surfaces` | **PASS** |
| (4+5) test-run ناجح عبر API: `failure=null`، بلا FAILURE_UNCODED، `process_info.pid`، `evidence.environment_id` | `test_api_test_run_success_is_honest` | **PASS** |
| (6) لا mock/stub دليلًا على عزل حي | مسبار البروتوكول وحدوي/HTTP فعلي مع السكربت الحقيقي؛ الحي داخل الركيزة NOT RUN | موثق |

**حصيلة الملفات الإلزامية**: `tests/execution/test_trust_boundary_01312.py` = **17 ناجحًا / 2 NOT RUN (skip موثق)**؛ `tests/api/test_trust_boundary_01312.py` = **3 ناجحة** (سجلات الأدلة).

### 5-1. مقارنة الانحدار مع رأس 013.11 (نفس الاختيار على الطرفين)

| المجموعات | رأس 013.11 `07d5e4e` | فرع 013.12 | الحكم |
|---|---|---|---|
| execution+readiness+regression+workflow-subset+stop | 11 ف / 174 ن | **10 ف / 192 ن** | **صفر فشل جديد** — واختبار موروث واحد إضافي أُصلح (`test_a_valid_cwd…` — فصل بيانات العملية عن الفشل D3) |
| tests/api | 14 ف / 155 ن | **14 ف / 155 ن** | **المجموعة نفسها حرفيًا** (Compare-Object: فارغ) — صفر جديد |

المتبقي 24 = مجموعة ما قبل الوجود الموروثة نفسها الموثقة في 013.11 §5-3 (مسارات حية تتطلب ركيزة/عاملًا/شبكة — خارج نطاق هذا الأمر).

## 6. العيوب المتبقية وحدود الثقة (§7-7)

1. **المسبار الحي داخل ركيزة Linux: NOT RUN** — مضيف هذا التنفيذ Windows بلا ركيزة (الأمر يمنع تثبيت WSL2/Docker). ما تحقق: عقد الخادم كاملًا (تحدي/حداثة/honest-refusal) على HTTP فعلي مع السكربت الحقيقي في وضعه المعلن، ومنطق الحكم خالص ومختبَر. يُشغَّل `test_d2_live_substrate_isolation_probe_on_linux` على مضيف ركيزة عند توفره.
2. **حد نموذج الثقة**: اختبار العزل سلوكي لا تشفيري — لا يثبت هوية مشغّل العامل؛ القناة الموثقة (توكن مشترك) كما هي معلنة. (D2-8)
3. **PD-2**: أُغلق — نتائج النجاح عبر مسار المنتج لا تحمل `failure` ولا `FAILURE_UNCODED` (مثبت عبر API).
4. **انجراف ما قبل الوجود**: مجموعة الفشل الموروثة من 013.11 (25 اختبارًا: workspace_0133/provisioner/provisioning/stop_api + 14 في api — قائمة 013.11 §5-3) لم تُمس — خارج نطاق هذا الأمر.
5. **تسامح COMPATIBLE_LOCAL**: سجل بلا هوية يُقبل في المسار المتوافق بلا ادعاء عزل — موثق ومثبت باختبار (مطلوب §3 حرفيًا).
6. **لا تغييرات** على مفاتيح المالك، ولا مهمة إنتاجية، ولا قاعدة بيانات المالك؛ لا `READY_FOR_OWNER_REAL_TRIAL` في هذا الأمر.

## 7. فحص الأسرار (§7-6)

الأنماط: `sk-`، `nvapi-`، `AIza`، `ghp_`، `xox*`، `Bearer <قيمة>`، `api_key=`, `secret=`, `password=` — على ملفات الكومِت (المصدر + الاختبارات + التقرير + الأدلة): **نظيف، بلا أي قيمة سر** (توكنات الاختبارات قيم رمزية معلنة: `test-token-01312`/`s3cret` في أجهزة stub معزولة). السجل: `docs/evidence/order01312/secrets_scan.txt`.

## الملحق — أدلة التشغيل

`docs/evidence/order01312/`:

| الملف | المحتوى |
|---|---|
| `mandatory_unit_runs.txt` | الاختبارات الإلزامية الوحدوية (D1+D2+D3) + إعادة تأكيد 013.11 — 45 ناجحًا / 2 NOT RUN |
| `api_trust_integration_3_passed.txt` | التكامل عبر API (§6) — 3 ناجحة |
| `affected_final_nonapi_10_preexisting.txt` + `branch_failures_nonapi.txt` | المجموعات المتأثرة النهائية (10 = مجموعة ما قبل الوجود) |
| `api_final_14_preexisting.txt` + `api_failures_list.txt` | api النهائي (14 = مجموعة 013.11 نفسها حرفيًا) |
| `commit_file_list.txt` | قائمة ملفات الكومِت (14) |
| `secrets_scan.txt` | فحص الأسرار — نظيف (ملاحظة الإنذار الكاذب موثقة) |
