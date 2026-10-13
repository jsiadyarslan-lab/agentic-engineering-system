# ORDER 013.10 — تقرير الإصلاح والقبول الحي

**STRICT READINESS RUNTIME FIX & LIVE MISSION-PATH ACCEPTANCE**

| البند | القيمة |
|---|---|
| الأمر | 013.10 — توحيد دلالة الصحة/الجاهزية (PD-1) + إصلاح لقطة runtime (PD-3) + قبول حي كامل عبر مسار المنتج |
| الفرع | `order01310-strict-readiness-runtime-fix` (منشأ من رأس 013.9 المتحقق منه حيًّا `4bd5ada` الذي يتضمن كوميت الإصلاح `73d8e47` — لا من main مباشرة) |
| مرجع خط الأساس | `origin/main == 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` (تحقق حي محليًا وعبر الشبكة قبل البدء) |
| كوميت 013.9 الأب | `4bd5ada` — التقرير: `docs/ORDER0139_REPORT.md` |
| الحالة النهائية | **`BLOCKED_WITH_EXACT_TECHNICAL_CAUSE`** — إصلاحا PD-1 وPD-3 مُنجزان ومُتحقق منهما حيًّا؛ مسار المهمة المعزول (STRICT) محجوب حجبًا صادقًا بسببه التقني الدقيق (§7) |

**ما لا يدعيه هذا التقرير:** لا يُصدر `READY_FOR_OWNER_REAL_TRIAL` (ممنوع نصًّا في §7)، ولا يدّعي تنفيذ مهمة معزولة حقيقية على هذا المضيف (لا ركيزة عزل — §7)، ولا يعتبر أدلة `COMPATIBLE_LOCAL` تحققًا بديلًا عن العزل (وسم صريح في كل دليل — §6)، ولا يعالج PD-2 (يبقى عيبًا مفتوحًا — §8)، ولا يعدّل ملفات المالك أو قاعدة بياناته (قاعدة بيانات نظيفة في مجلد مؤقت خارج المستودع).

---

## 1. خط الأساس والتحقق الحي (§2)

1. `git rev-parse main` → `d814f83` محليًا؛ `git rev-parse origin/main` → `0a26fc70…` — **المطابق لمرجع الأمر §2.1**. الفحص: `d814f83` أصلٌ سابق لـ`0a26fc70` (merge-base = `d814f83`؛ `main` المحلي متأخر، غير منحرف) — فرق توثيقي في بيئة العمل لا يخالف شرط الأمر على `origin/main`.
2. `git ls-remote origin refs/heads/main` → `0a26fc70…` — الأصل غير محرك عند البدء.
3. فرع 013.9 غير موجود محليًا؛ جُلب حيًّا: `origin/order0139-linux-substrate-import-repair` → رأسه `4bd5ada` (يتضمن `73d8e47`). الفروع الثلاثة (main، فرع 013.9، `e10-rp22r2a2-sanitized-git-environment` عند `c5920c8`) **لم تُلمس**.
4. الفرع الجديد أُنشئ من `4bd5ada` حصرًا؛ الشجرة نظيفة عند الإنشاء عدا ملفات جلسات سابقة غير متتبعة (`E2-R/ E5/ E6-R2/ E7/ E8-R/`) وترميم واحد متتبع سابق (`E6-R2/e6_commit_manifest.json` من جلسة سابقة) — **لم تُضمَّ لالتزامات هذا الأمر إطلاقًا** (§10).
5. worktree تحقق معزول للأساس النظيف: `C:\Users\jaber\Documents\GitHub\aes-baseline-0139` عند `4bd5ada` (استُخدم للمقارنة قبل/بعد وحذف بعد التسليم).

---

## 2. الإصلاح PD-1 — توحيد دلالة HEALTHY/READY والبوابة الموحدة (§3)

### 2.1 العيب كما ثُبّت من كود 013.9 ودليل قبوله

دليل 013.9 الحي (`docs/evidence/order0139/10_environment_verified.json`): التحقق الحقيقي نجح وكتب `status=HEALTHY` مع `last_verified_at` وفحوص مسماة. بعده بقليل:

- `GET /api/execution/runtime-state?policy=STRICT_ISOLATED` عاد `DISCOVERING`/`selected=null` — لأن المُجمِّع كان ينتظر حرفيًّا `status=="READY"`.
- بوابة preflight على مشروع معتمد عادت `BLOCKED` **لأن السبب كان «بيئة سليمة» لا «بيئة غير معزولة»** — أي أن الحجب صدر عن خلل مفردات لا عن غياب العزل الفعلي.

الجذر: ثلاث تعريفات متنافقة لـ«جاهز»:
1. `sandbox_probe_result` تكتب `status=READY` (المسبار القديم).
2. `VerifyResult.status` عند النجاح = `READY` (backends.py:483/872/1276) بينما مسار `verify_environment` يكتب `HEALTHY`.
3. `environment_satisfies`/`_state_from_environments` تقرأ حرفيًّا `status=="READY"` وتتجاهل أدلة التحقق.

### 2.2 العقد الموحد الجديد — `src/execution/policy.py` (إعادة كتابة)

```
ready = health_ok ∧ verification_evidence.complete ∧ policy_eligibility
```

| الدالة | العقد |
|---|---|
| `health_ok(env)` | `status ∈ {"HEALTHY", "READY"}` — READY مقبولة فقط كإرث قرائي (توافق خلفي، لا كتابة جديدة بها) |
| `verification_evidence(env)` | أدلة التحقق: `last_verified_at` + فحوص مسماة كلها ناجحة من `last_probe_detail` (بالأشكال `{"verify":{"checks":[…]}}` و`{"checks":[…]}`) → `complete: bool` |
| `policy_eligibility(env, policy)` | STRICT ⟵ `sandboxed=True` إلزامًا؛ COMPATIBLE ⟵ الصحة فقط. يعيد `(bool, reason)` |
| `readiness(env, policy)` | الخلاصة: `{health_ok, evidence, eligible, ready, blockers[]}` — مصدر الحقيقة الوحيد |
| `environment_satisfies(env, policy)` | تفويض حرفي إلى `readiness(...)["ready"]` |

### 2.3 مستهلكو البوابة (كل مسارات القراءة)

- **`src/execution/service.py`** — `compute_environment_state()` أعيدت: السلبيات النهائية تُعاد كما هي، والحالة النهائية `READY` **فقط إذا** `verdict["ready"]` — لا إصدار `ELIGIBLE` مع `eligible=False` إطلاقًا. `sandbox_probe_result` تكتب `HEALTHY` عند النجاح (لا READY). شرط عدم التطابق و`_mark_stale` يقرآن المفردات الموحدة.
- **`src/execution/runtime_state.py`** — `_state_from_environments()`: الاستنتاج عبر `environment_satisfies(selected, policy)` بدل مقارنة الحالة الحرفية؛ لا `READY` زائفة ولا `DISCOVERING` مع بيئة مستوفية.
- **`src/readiness/preflight.py`** — مسار COMPATIBLE_LOCAL عبر `environment_satisfies(env, policy) and not env.get("sandboxed")`.
- **`src/readiness/service.py`** — قدرة sandbox: `health_ok(e) and verification_evidence(e)["complete"]`.

---

## 3. الإصلاح PD-3 — لقطة runtime عبر السلسلة القانونية (§4)

### 3.1 العيب كما ثُبّت من كود 013.9

`src/workflow/snapshot.py:474` في `_execution_detail()`:

```python
project = session.get(Project, ...)
current_execution_id = project.get("current_execution_id")   # ‼️ ORM لا dict
```

`Project` كائن ORM — `.get()` يرمي `AttributeError: 'Project' object has no attribute 'get'` → **`GET /api/projects/{id}/runtime` ينهار 500** (دليل 013.9: 6 اختبارات snapshot تفشل بالخطأ نفسه). والخطأ البنيوي: `current_execution_id` **عمود Step لا Project** — القيم كانت ستكون None حتى لو لم ينهر الكود.

### 3.2 الإصلاح

`_execution_detail()` تتبع السلسلة القانونية المعمول بها في المحرك (`harness/jobs.py::_current_execution`، `engine.py:1120-1126`):

```
project.current_step_id → step.current_execution_id → session.get(Execution)
```

+ تنظيف: مفتاحا `command_type/status` المكرران في القاموس توحيدا، واستيراد ميّت أزيل.

**دليل القبول الحي (§6 خطوات 13/14/15):** نقطة النهاية ردت **HTTP 200 قبل التنفيذ** (`execution=null`)، **أثناء** تنفيذ حي، و**بعد** تسجيل تنفيذ حقيقي (`execution={id:2, status:FAILED, command:"…", command_type:"step_execution", cwd:"runtime\projects\1\steps\1", started_at, finished_at, agent_role:"implementer"}`) — بيانات المتجر الحقيقية حرفيًا (تنفيذ فاشل صادق لا نجاح مفبرك).

---

## 4. عيبان إضافيان اكتُشفا حيًّا وأُصلحا (داخل نطاق §4 «جميع المسارات المتعلقة بلقطة runtime»)

### 4.1 `create_execution() لا يقبل حقول الأمر — انهيار إطلاق المهمة الحي`

أول إطلاق حي بعد فك حاجز PD-1 كشف العيب التالي (لم يُصل إطلاقًا لأن 013.9 كان محجوبًا عند preflight قبل هذه الطبقة):

```
JOB_FAILED: create_execution() got an unexpected keyword argument 'command'
```

- الجذر: نموذج `Execution` يحمل حقول 013.7 §P14 (`command/cwd/pid/parent_pid/command_type`) والمحرك يمررها (`engine.py:1117`)، لكن توقيع `workflow/service.py::create_execution` لم يُحدَّث قط.
- **الإصلاح**: توقيع موسع بمعاملات اختيارية تُخزَّن في الصف الدائم — متصلو القديم (`_block_on_providers`) محفوظون.
- **الدليل الحي**: بعد الإصلاح، صف التنفيذ الدائم سُجّل بحقول الأمر كاملة وظهر في لقطة runtime (§3.2 أعلاه). بلا هذا الإصلاح لا يوجد «عرض حالة التشغيل» أصلًا.

### 4.2 `delete_environment يحمي اسمًا مثبتًا (local-linux) فقط — حقيقة المضيف قابلة للحذف على Windows`

- اختبار العقد المُصلح `test_local_environment_cannot_be_deleted` (باسم `local_environment_name()` الحقيقي) كشف أن DELETE على البيئة المحلية **على Windows** ينجح 200 — لأن الحارس كان `row.name == "local-linux"` حرفيًّا، والبيئة المحلية هنا `local-windows`، والقائمة تعيد تسجيلها تلقائيًا فلا يُلاحظ النقص.
- **الإصلاح** (`src/execution/service.py`): الحارس يشمل `local_environment_name()` والاسم القديم معًا → 422 على كل المضيفين.

---

## 5. الاختبارات الإلزامية والمقارنة الصامتة (§5)

### 5.1 ملفا الاختبار الإلزاميان (جديدان)

**`tests/execution/test_readiness_gate_01310.py`** — حالات الأمر الثماني + جدول التوافق:

| الحالة الإلزامية (§5) | الاختبار | النتيجة |
|---|---|---|
| بيئة DETECTED لا تعتبر READY ولو سُجل مسبار | `test_detected_without_verification_is_not_ready_under_strict` | PASS |
| UNAVAILABLE لا تعتبر READY أبدًا | `test_unavailable_is_never_ready_under_any_policy` | PASS |
| HEALTHY بأدلة تتحقق لكن لا تُنتقى تحت STRICT إن لم تكن معزولة | `test_healthy_verified_unisolated_not_selected_under_strict` | PASS |
| HEALTHY بأدلة تتحقق وتُنتقى تحت STRICT إن كانت معزولة | `test_healthy_verified_isolated_selected_under_strict` | PASS |
| بلا أدلة تحقق: HEALTHY لا تتجاوز بوابة STRICT ولا COMPATIBLE | `test_healthy_without_evidence_fails_both_policies` | PASS |
| مسبار صحي + تحقق قديم منتهي → STALE لا READY | `test_stale_verification_is_not_ready` | PASS |
| طلب STRICT على مضيف بلا مسار عزل → رفض صادق بالسبب الحرفي `POLICY_BLOCK` | `test_strict_on_host_without_isolation_block_with_exact_reason` | PASS |
| توافق الحالة/الأهلية عبر مصفوفة (8×2) | `test_state_eligibility_agreement_table` | PASS |
| المُوَفِّر لا يمر عبر STRICT بلا عزل | `test_provisioner_refuses_strict_without_isolation` | PASS |

**`tests/workflow/test_snapshot_runtime_01310.py`** — نقطة النهاية المصلحة (SQLite حقيقي، لا mocks):

| الحالة | الاختبار | النتيجة |
|---|---|---|
| 200 قبل التنفيذ `execution=null` | `test_runtime_endpoint_before_execution_returns_200` | PASS |
| 200 بعد تنفيذ حقيقي بتفاصيله المخزنة | `test_runtime_endpoint_after_real_execution_returns_200` | PASS |
| مشروع مجهول → 404 | `test_runtime_endpoint_unknown_project_404` | PASS |
| معرف غير صالح → 404/422 | `test_runtime_endpoint_invalid_id_rejected` | PASS |
| فشل قراءة حقيقي يصل كما هو (لا snapshot مفبرك) | `test_runtime_read_failure_propagates_honestly` | PASS |

### 5.2 إصلاح عقود الاختبارات المتأثرة بتوحيد المفردات (لا تخفيض معايير)

| الملف | الإصلاح |
|---|---|
| `tests/execution/test_policy_no_fallback_0131.py` | البذور تزرع أدلة تحقق كاملة (`last_verified_at` + `last_probe_detail` JSON) |
| `tests/readiness/test_preflight.py` | `_sandbox_ready` عبر البوابة الموحدة |
| `tests/api/conftest.py` | وصفة fast_probe عبر البوابة الموحدة |
| `tests/execution/test_service.py` | تأكيدات منصة صادقة (`local_environment_name()`)، التحقق يكتب HEALTHY + البوابة تُجيز |
| `tests/workflow/test_snapshot_0134.py` | بذر صف REMOTE_WORKER مُتحقق معزول داخل الاختبار (المشترك يبقى بلا بيئات لاختبارات الحجب) |
| `tests/api/test_execution_research_api.py` | اسم محلي من المضيف الفعلي (§10)؛ التحقق عبر API يكتب HEALTHY + `last_verified_at` |
| `tests/api/test_projects_011.py` | بذر الجاهزية القانونية (HEALTHY+أدلة) في اختبار إعادة الفحص؛ وصفة المسبار عبر البوابة |

### 5.3 المقارنة الصامتة قبل/بعد (§5.4 — نفس مجموعات الملفات، نفس الأوامر، القائمتان الحرفيتان محفوظتان كأدلة)

| المجموعة | خط الأساس 4bd5ada (worktree نظيف) | فرع 013.10 | الحكم |
|---|---|---|---|
| tests/execution + tests/workflow + tests/readiness | **46 فاشل** / 150 ناجح | **37 فاشل** / 189 ناجح | **9 أُصلحت، صفر جديد** (test_service×3 + test_snapshot_0134×6 — عائلة PD-3/PD-1) |
| tests/regression + tests/harness + tests/core + tests/contracts | **20 فاشل** / 133 ناجح | **18 فاشل** / 135 ناجح | **صفر جديد على الفرع**؛ واختباران في harness (test_jobs_lifecycle دورة إيقاف/استئناف) يفشلان على الأساس وينجحان على الفرع |
| tests/integration | صفر فاشل | صفر فاشل | خضراء على الطرفين |
| tests/eoe | 3 فاشل + 15 error إعداد («substrate…») | مطابقة حرفيًا | مسبق، خارج النطاق |

**الإجمالي عبر كل المجموعات: 69 فاشلًا على الأساس ← 58 فاشلًا على الفرع — 11 إصلاحًا، صفر انحدارات** (المعرفات متطابقة إلا المُصلح).

الأدلة الحرفية: `docs/evidence/order01310/test_comparison/{baseline,branch}_…{failures.txt,.out}`.

ملاحظة مقاسة: `test_planning_events_are_explicit_not_silent` متذبذب تحت الحمل (ينجح 3/3 معزولًا على الطرفين) — متذبذب بيئي موثق، ليس انحدارًا.

### 5.4 المخزون المسبق الموثق (فاشل قبل هذا الأمر وعليه — سياق 013.9 §7)

كل ما تبقى فاشلًا على الفرع (58 معرفًا) مطابق للأساس بمعرف: عائلة execution/workflow/readiness المذكورة أعلاه (37)، regression×2 وcore×3 وharness×13 (دورات وظائف دائمة — انجراف مفردات/منصة)، و`test_recheck_after_provisioning_opens_without_reapproval` (يستمر بالدوران `blocked=preflight` 200 نبضة **على الطرفين** — مُتحقق منه حيًّا على الأساس النظيف)، وeoe: `test_access_denied_without_grant`×3 فاشل + 15 error إعداد («substrate…» يتطلب ركيزة عزل حقيقية) — **كلها مطابقة بين الأساس والفرع**، وintegration خضراء على الطرفين.

---

## 6. القبول الحي عبر مسار المنتج (§6) — أدلة `docs/evidence/order01310/api/`

**بيئة التنفيذ الحي:** خادم المنتج نفسه (`uvicorn api.routes:app --port 8010`)، قاعدة بيانات نظيفة في مجلد مؤقت خارج المستودع (`%TEMP%\aes-acceptance-01310`) — لا ملفات المالك ولا قاعدته. انحراف موثق (§9): تثبيت README القابل للتحرير غير صالح في هذا الـvenv (يشير لنسخة قديمة `agent-hub-v2` في مسار آخر) — أُقلع بـ`PYTHONPATH` (جذر المستودع + `src/`) وهو نفس نمط الاستيراد الذي يستهلكه التطبيق فعليًا.

| # | الخطوة | النتيجة الحية | الدليل |
|---|---|---|---|
| 01 | `GET /health` | ok؛ `substrate.available=false` معلنة بصدق | `01_health.json` |
| 02 | `GET /api/execution/host-truth` | `host=Windows/AMD64`، `local_execution=AVAILABLE_COMPATIBLE_ONLY`، `isolation=UNAVAILABLE` | `02_host_truth.json` |
| 03 | جرد البيئات | `local-windows/LOCAL/DETECTED/sandboxed=False/isolation=NONE` — تسجيل تلقائي صادق | `03_environments_before_verify.json` |
| 04 | runtime-state STRICT قبل التحقق | `UNAVAILABLE`، `selected=null` | `04_…strict_before_verify.json` |
| 05 | `POST …/1/verify` (تحقق حقيقي) | `HEALTHY`، فحوص 10/10 ناجحة (boot/execute/write/read/delete/working_directory/architecture/isolation/capture/preflight)، `last_verified_at` مسجل | `05_verify_local.json` |
| 06 | runtime-state STRICT بعد التحقق | **لا READY زائفة**: `UNAVAILABLE`/`selected=null` مع الفجوات البنيوية المعلنة حرفيًا: «لا مسار توفير يوافق السياسة على هذا المضيف — الفجوات معلنة» + `need/detected/action` بثلاثة مسارات مالك (WSL2/Docker أو عامل بعيد أو خفض معلن) | `06_…strict_after_verify.json` |
| 07 | runtime-state COMPATIBLE بعد التحقق | **`READY` + `selected=local-windows (id=1)` + `environment_id=1` مطابق** — هذه هي لحظة PD-1 التي كانت `DISCOVERING`/`selected=null` في 013.9 | `07_…compatible_after_verify.json` |
| 08 | `POST /api/environment/provision` (COMPATIBLE) | دورة توفير كاملة → `READY` (2382ms) | `08_provision_compatible.json` |
| 09 | `POST …/1/test-run` (تنفيذ فعلي) | `ok=True`، `exit_code=0`، `termination=COMPLETED`، حد التنفيذ `WINDOWS_PROCESS` (وسم صادق — لا ادعاء عزل) | `09_test_run_local.json` |
| 10 | إنشاء مشروع اختبار | 201، سياسة `COMPATIBLE_LOCAL` (وسم صريح: ليس مسار STRICT) | `10_project_create.json` |
| 10b | توليد خطة **بمزود حي** | فشل أول بمصنّف حرفي `PROVIDER_NOT_CONFIGURED` (مخزن الأسرار نسبة لـCWD) — أُعيد من مجلد مؤقت بنسخة مشفرة DPAPI لنفس المستخدم (لا سر في أي سجل/دليل) → نجاح: `nvidia/nemotron-3-ultra-550b-a55b` | `10b_project_after_plan.json` |
| 11 | اعتماد المالك | `AWAITING_OWNER_APPROVAL → READY` (بوابة `PLAN_APPROVAL`) | `10b/…` |
| 12 | preflight المشروع | COMPATIBLE: `verdict=PASS` + البيئة `local-windows/HEALTHY` + بوابة التنفيذ OPEN + **إطلاق آلي** | `12_preflight_compatible.json` |
| 13 | runtime قبل التنفيذ | HTTP 200، `execution=null` | `13_project_runtime_before_execution.json` |
| 14 | **تشغيل المهمة الحية** | الحلقة المصنعية اشتغلت كاملة: `IMPLEMENTER/THINKER/REVIEWER` نداءات نموذج حقيقية (جودة 9.0/10، مراجعة approved)، `write_file` ناجح داخل مساحة العمل، تصنيف فشل صادق («الدورة لم تكتمل أدلةً»)، إعادة محاولة حقيقية (attempt=2,3,4)، ثم **بوابة مالك حقيقية** `PLAN_REVISION_APPROVAL` — لا سقوط صامت ولا نجاح مفبرك ولا انهيار | `14_project_runtime_during_execution.json` |
| 15 | runtime بعد التنفيذ | HTTP 200 بصف التنفيذ الدائم الحقيقي (§3.2) | `15_project_runtime_after_execution.json` |
| 16-17 | مشروع ثانٍ بسياسة STRICT | preflight: **`BLOCKED`** — sandbox: «المطلوب: بيئة تنفيذ Linux/x86_64 معزولة فعليًا…لم تُوفَّر بعد على هذا المضيف»، `env=null`، المشروع `BLOCKED` — **لا سقوط إلى متوافق تحت STRICT** | `16_project2_create_strict.json`، `17_preflight_project2_strict.json` |
| 18 | الحالة النهائية | `local-windows/HEALTHY` (متحقق 10/10)؛ COMPATIBLE `READY` مستقر | `18_environments_final.json` |

**سجل تنفيذ حي إضافي:** أدلة تدقيق مصنوعة فعليًا داخل مساحة عمل المشروع (`%TEMP%\aes-acceptance-01310\runtime\projects\1\steps\{1,2,3}\evidence.json`) بـ`role_models` (المزود/النموذج الحقيقيان) و`final_state` صادق — مخطوطة كاملة بلا تعديل.

### 6.1 بند §6 «اختبار رفض الاتصال الخارجي من داخل العزل» — NOT RUN

لا يوجد عزل فعلي على هذا المضيف (§7) — لا يمكن اختبار رفض الشبكة داخل عزل غير موجود. التصريح صريح، ولا تعويض وهمي.

---

## 7. الحكم: `BLOCKED_WITH_EXACT_TECHNICAL_CAUSE` (§7)

**ما أُنجز وأُثبت حيًّا:** إصلاحا PD-1 وPD-3 مُتحقق منهما عبر مسار المنتج نفسه (لا اختبارات فقط): التحقق الحقيقي يكتب HEALTHY بأدلة، والجاهزية تُحسب بالبوابة الموحدة، وruntime-state يعيد READY مع `selected`+`environment_id` مطابقين تحت السياسة المستوفاة على هذا المضيف، ولا يزوّر READY تحت STRICT، ولقطة runtime تعمل 200 قبل/أثناء/بعد تنفيذ حقيقي، وإطلاق المهمة الحي يمر كل بواباته حتى بوابة قرار المالك بلا انهيار.

**السبب التقني الدقيق للحجب (معلن من المنتج نفسه — دليل 02/06/17):**

> المضيف `Windows/AMD64` — **ركيزة العزل غير متاحة بنيويًا**: الافتراضية معطلة على هذا الجهاز (`WSL2 is unable to start since virtualisation is not enabled on this machine` — `WSL2_NO_DISTRO`)، لا حاويات Docker، لا عامل بعيد مسجَّل.

- النتيجة: تحت `STRICT_ISOLATED` يُرفض كل مسار توفير بفجوة واحدة معلنة (`coherent.missing` بـneed/detected/action)، ولا يُنتقى أي backend، والمشروع الصارم يُحجب عند preflight بالسبب الحرفي — **هذا سلوك صحيح مطلوب، ليس عيبًا**.
- لماذا لا يصلح هذا الأمر السبب؟ معالجته إجراء مالك على العتاد/البنية (تفعيل الافتراضية في BIOS/VM، أو توفير Linux/WSL2/Docker، أو تسجيل عامل بعيد عبر `python scripts/execution_worker.py`) — خارج نطاق أمر برمجي وحده، ولا يجوز تزييفه بخفض السياسة الافتراضية (ممنوع §3.6).
- مسارات المالك الثلاثة الحرفية (من دليل 06): (1) تفعيل WSL2/Docker على هذا المضيف وإعادة التجهيز، (2) تشغيل عامل بعيد على أي Linux/WSL2 ثم تسجيله، (3) خفض سياسة المشروع إلى توافق محلي **معلن** من إعدادات المشروع.

---

## 8. العيوب المفتوحة المرحَّاة بصدق (§7.2 من 013.9 + جديد موثق)

| العيب | الحالة | المرجع |
|---|---|---|
| **PD-2** (ازدواج تنفيذ محتمل في COMPATIBLE_LOCAL — قفل job/worker) | **مفتوح — خارج نطاق هذا الأمر حرفيًا** (§4 من الأمر) | 013.9 §7.2 |
| مخزون الاختبارات المسبق (§5.4 أعلاه) — انجراف مفردات/منصة في 31+ اختبارًا | مفتوح — مطابق للأساس معرفًا بمعرف | 013.9 §7 |
| `test_recheck_after_provisioning_opens_without_reapproval` — الدوران المستمر | مفتوح — يتكرر على الأساس النظيف حرفيًا (متحقق حيًّا في هذا الأمر) | هذا التقرير §5.4 |
| تثبيت README القابل للتحرير يشير لنسخة قديمة خارج المستودع | مفتوح — انحراف بيئي موثق (§9) | هذا التقرير §9 |

---

## 9. الانحرافات والقيود الصادقة (§8)

1. **تثبيت venv القابل للتحرير غير مستعمل**: `.venv` يحمل `agent-hub-v2 2.1.0` (قابل للتحرير) يشير إلى `C:\Users\jaber\Documents\GitHub\agent-hub-v2` (نسخة قديمة بمعزل عن هذا المستودع). الإقلاع الحي تم بـ`PYTHONPATH` (جذر المستودع + `src/`) — وهو شرط الاستيراد الفعلي للتطبيق (`secrets_store/__init__` يستورد بنمط `src.*` بينما باقي الحزم بالأسماء العارية).
2. **مخزن الأسرار نسبةً لـCWD**: `RUNTIME_DIR = Path("runtime")` نسبي لمجلد العمل — الخادم بقاعدة نظيفة في مجلد مؤقت لا يرى مفاتيح المالك. عولج بنسخة واحدة من ملف المخزن **المشفّر DPAPI** إلى المجلد المؤقت (نفس مستخدم Windows — فك حي فقط هناك)؛ ملف المالك الأصلي لم يُقرأ محتواه ولا يُعدَّل، ولا قيمة سرية ظهرت في أي سجل/دليل/تقرير (فحص أنماط أسرار على كامل الفرق + مجلد الأدلة: **صفر إصابات**).
3. **النداءات الحية المحدودة**: مهمة الاختبار الحية استدعاءات نموذج قليلة (planner/roles) على مفتاح `nvidia` الموجود لدى المالك — ضمن تفويض §6 («مهمة اختبار صغيرة وآمنة»). مهمة التنفيذ لم تُغلق دورة أدلة ميكانيكية (سلوك نموذج: بحث ويب بدل كتابة الملف؛ منع DDG حقيقي من المضيف + خطأ ASCII في `fetch_page` لعناوين عربية — مُدوّنان كأحداث TOOL_EXECUTION صادقة) — والحلقة توقفت عند بوابة المالك كما صُممت.
4. **تذبذب بيئي واحد**: `test_planning_events_are_explicit_not_silent` ينجح 3/3 معزولًا على الطرفين؛ يفشل أحيانًا تحت تشغيل متوازٍ ثقيل (مسابر شبكة حقيقية) — موثق وليس انحدارًا.
5. **`NOT RUN` صادق**: مسار العزل الحقيقي كاملًا (تجهيز Linux حقيقي، تنفيذ داخل عزل namespaces+seccomp، رفض الشبكة من داخل العزل، دورة عامل بعيد حي) — يستحيل بنيويًا على هذا المضيف (§7)؛ تعويضه: الاختبارات الإلزامية الوحدوية للمسار المعزول على هذا الجهاز + دليل السلوك الصادق للبوابة تحت STRICT حيًّا.

---

## 10. النظافة الهندسية (§9)

- **لا reset/amend/force-push إطلاقًا** — تاريخ 013.9 (`4bd5ada`, `73d8e47`) كما هو حرفيًا.
- `main` و`origin/main` غير محركين (`0a26fc70…` تحقق حي قبل وبعد).
- التسليم: `src/`×8 + `tests/`×8 معدلة + اختباران جديدان + التقرير والأدلة (`docs/`) — **حصرًا**. ملفات جلسات سابقة (`E2-R/ E5/ E6-R2/ E7/ E8-R/` وترميم `E6-R2/e6_commit_manifest.json`) لم تُضمَّ ولم تُلمس.
- `runtime/` في المستودع: صفر تغيير (تحقق `git status -- src/ tests/ docs/` + قائمة التسليم) — قاعدة القبول الحية خارج المستودع كليًا.
- فحص الأسرار: أنماط (sk-/nvapi-/AIza/ghp_/xox/Bearer/api_key/secret/password) على **كامل الفرق (1599 سطرًا) وعلى ملفات الأدلة الـ33**: صفر إصابات؛ الأدلة تحمل أسماء مزودين فقط (`nvidia`, `openai_compatible`) بلا قيم.
