# تقرير الأمر 013.15 — OPTION-A: تفعيل ركيزة معزولة وإثبات العزل

> **الحالة النهائية:** `STRICT_WORKER_READY` **على ركيزة جلسة المنفّذ الحالية**
> (عامل Linux حي في وضع substrate، عزل مثبت بمسبار حي، الاختباران دون
> SKIP، الساعة مثبتة عند الالتقاط بإجماع NTP) — مع بقاء مسار
> WSL2-على-Windows (جهاز المالك) في `OWNER_ACTION_REQUIRED` بتدخل واحد
> محدد بدقة (تفعيل الافتراضية من BIOS/UEFI + إعادة تشغيل).
> لا دمج إلى `main`، ولا بدء E11 في هذا الأمر (§9).

---

## 0. ملخص تنفيذي

| البند | القيمة |
|---|---|
| الأمر | 013.15 — OPTION-A WSL2 SUBSTRATE ACTIVATION & ISOLATION PROOF |
| الفرع | `order01315-wsl2-substrate-activation` من `order01314-authorized-worker-bootstrap@622be149` |
| خط الأساس | `origin/main = 0a26fc70ce13e69932db7fe54c810fcbf0f99d3f` ✓ حرفيًا (ls-remote حي) |
| الفرع المصدر | `622be149ce86e054c77431f14594705f8d5327dc` ✓ حرفيًا |
| مضيف الجلسة | Linux x86_64 (حاوية) — **ليس Windows**؛ دليل قاطع: `executor_host_truth.json` |
| العامل | حي في وضع substrate (namespaces+seccomp) على قناة 127.0.0.1 محمية |
| مسبار العزل | `verdict=BLOCKED` بتحدٍّ متكرر + `control_proof.ok=true` (التحكم خارج العزل) |
| التحقق عبر مسار المنتج | 8/8 فحوص ok — `last_probe_detail.status = READY` — `isolation_probe: منع شبكة مؤكد` |
| اختبارا D2/D3 | **PASS دون SKIP** (كانا يفشلان بعناد عند خط الأساس — دليل موثق) |
| الساعة | مثبتة عند الالتقاط: إجماع 5 سلطات NTP مستقلة، إزاحة +0.0002s، تشتت ≤2ms |
| مطابقة API/واجهة | مثبتة عبر Chromium حي (DOM == API على كل الحقول) |
| الأسرار | 30 ملفًا في نطاق الكوميت = نظيف؛ التوكن وُلّد وقت التشغيل ولم يُطبع أبدًا |
| الانحدار | صفر جديد؛ 4 حالات مُصلحة؛ 4 فشول قائمة موثقة (افتراضات مضيف Windows) |

---

## 1. حقيقة المضيفين — فصل صادق بين جهازين (§3)

**هذه الجلسة تعمل على Linux، لا على Windows.** الدليل القاطع
(`executor_host_truth.json`):

- `uname`: `Linux … 5.10.134-013.15.kangaroo.al8.x86_64` — نواة Linux
  حقيقية (ليست نواة WSL ولا Windows).
- لا `wsl.exe`، لا `/mnt/c`، `systemd-detect-virt = docker` — حاوية.
- أي أمر Windows (الإصدار/الصلاحيات/الميزات/`w32tm`) **غير قابل للتنفيذ
  من هنا إطلاقًا** — هذا حد وصول فيزيائي، لا رفض.

**حقائق جهاز المالك (Windows)** كما أثبتها ORDER013.14 على ذلك المضيف
(مصدر: فرع `order01314`، أدلته) — تُعاد هنا كحقائق طرف-المالك، لا
يدّعي هذا التقرير إعادة التحقق منها: Windows 10 / AMD64، WSL2 مثبت
لكن لا يبدأ: `virtualisation is not enabled` (BIOS/UEFI)، وخدمة
Windows Time متوقفة (0x80070426) → `CLOCK_EVIDENCE_UNTRUSTED` هناك.
التدخل الواحد المطلوب لذلك المسار محدد بدقة في
`owner_action_request.md` (تفعيل VT-x/SVM من BIOS/UEFI + إعادة تشغيل)،
وتغيير إعدادات firmware عن بُعد مرفوض نصًّا (§4.3) — لم يُحاول ولم
يُدّعَ.

**ما أثبته هذا الأمر فعليًا** هو جوهر الهدف (§1): ركيزة Linux حقيقية
معزولة على الجهاز الحالي — الجهاز الحالي لجلسة المنفّذ هو Linux أصلًا،
فكان المسار المحلي ممكنًا دون WSL2 (WSL2 آلية Windows لا معنى لها
على مضيف Linux). كل ما يلي قياس حي لا استنتاج من اسم توزيعة.

## 2. خط الأساس (§2)

- `git fetch origin --prune` حي؛ `origin/main = 0a26fc70…` مطابق حرفيًا؛
  رأس `origin/order01314-authorized-worker-bootstrap = 622be149…` مطابق.
- الفرع أُنشئ من `622be149` حصرًا داخل worktree معزول نظيف
  (`order01315_work`) + worktree خط أساس للمقارنات (`order01315_run`).
- الحالة قبل التنفيذ مسجلة في `git_prestate.json` (رأس كامل + شجرة + رؤوس
  الأصل الحية)؛ لا reset/rebase/force-push/دمج؛ `main` لم يتحرك.
- الجرائد الكاملة: `git log --oneline` يظهر سلسلة 013.9→013.14 خطية
  من `main` (تحقق `merge-base --is-ancestor`).

## 3. الساعة (§3.3–3.4)

- **داخل الجلسة** (`clock_inventory.json` + `clock_external_comparison.json`):
  لا خفيض ساعات داخل الحاوية؛ المصدر ساعة نواة المضيف. المقارنة الخارجية:
  **5/5 سلطات NTP مستقلة** (Google/Cloudflare/Aliyun/Windows/pool)
  استجابت؛ إجماع إزاحة **+0.0002s** بتشتت **≤2.0ms**؛ رؤوس HTTP Date
  المتسقة مع الإجماع 2 (دقتها 1ث)؛ شاذّ وحيد
  (api.github.com ‎−14.295s) انحرافه منسوب لساعة ذلك الخادم البعيد —
  البرهان: إجماع NTP المستقل بمستوى الملّي ثانية.
- **النتيجة**: `PROVEN_AT_CAPTURE` — دقة الساعة عند الالتقاط مثبتة ضمن
  ملّي ثانية. آلية المزامنة نفسها غير مرئية من داخل الحاوية (تُدار من
  المضيف) — وهذا حدّ معلن لا ادعاء تجاوزه.
- لا إعادة تشغيل حدثت في هذا الأمر؛ شرط «الساعة بعد أي إعادة تشغيل»
  ينطبق على مسار WSL2-على-Windows (داخل `owner_action_request.md` §3).

## 4. قدرات الركيزة الفعلية — قياس لا اسم توزيعة (§4.5)

من `substrate_capabilities_linux.json` (كلها قياسات حية):

| القدرة | القياس |
|---|---|
| المعمارية / Python | `x86_64` / `3.12.15` |
| user namespaces | **حي**: `unshare -Ur` نجح (`USERNS_OK`، uid داخلها 0) |
| seccomp | وضع 2 (مرشَّح) + `NoNewPrivs`؛ ويعمل متداخلًا داخل unshare |
| الصلاحيات | uid=1001، `CapEff=0` — بلا أي صلاحية |
| cgroups v2 + controllers | **غير مفعّلة هنا**: `/sys/fs/cgroup` tmpfs للقراءة فقط بنمط v1 هجين (`0::/` فارغة من controllers) — موثق كما هو |
| حدود الموارد في الركيزة | **RLIMITs لا cgroups** — نص المصدر نفسه (`local_substrate.py:45-46`: «cgroupfs للقراءة فقط ولا يُدَّعى أي تحكم cgroup») |
| | وبيان العامل: `RLIMIT_AS/NPROC/FSIZE/CPU + watchdog` |

فحص الوصول الحي: الركيزة الفعلية للمنتج (`substrate.local_substrate.
default_local_images()`) = **True** على هذا المضيف — وهو نفس شرط دخول
العامل وضع substrate.

## 5. الإثبات الحي (§5) — كله عبر مسار المنتج، لا mock

### 5.1 العامل الحي (النقاط الأربع)

`scripts/execution_worker.py` من المصدر الحالي، على قناة 127.0.0.1
محلية محمية، توكن وُلّد وقت التشغيل (`secrets.token_urlsafe`) ولم
يُطبع ولم يُكتب في أي ملف (الأدلة تحمل بصمة sha256 فقط):

- `/health` → `ok:true`, **`backend_mode: "substrate"`**
- `/capabilities` → `sandboxed:true`, `isolation:"linux-namespaces+seccomp"`,
  `artifacts_root:"/artifacts"`, `network_policy: jobs blocked by sandbox`
- `/probe` → الفحوص الثلاثة (boot/write+execute/capture) كلها ok
- `/probe_isolation` (بتحدٍّ جديد) → **`ok:true, verdict:BLOCKED`**،
  التحدي مكرر في الرد، **`control_proof.ok=true`** — أي: قناة التحكم
  المصرح بها تخدم نداء API نفسه من خارج العزل، بينما محاولة الاتصال
  نفسها من داخل الركيزة محجوبة — هذا هو مسبار §5 المطلوب نصًّا.

### 5.2 التسجيل والتحقق عبر مسار المنتج (uvicorn من README الحرفي)

قاعدة تشغيل معزولة نظيفة (متجاهَلة عبر `.gitignore:29` — لا تدخل Git
أبدًا): تسجيل `REMOTE_WORKER` (backend/endpoint/token) → تحقق حقيقي:

- الاستجابة لا تُرجع التوكن قط (فحص آلي: `token_leak_in_response=false`)
- الفحوص **8/8 ok** بينها `isolation_probe: منع شبكة مؤكد من داخل
  الركيزة بتحدي هذا التحقق`، و`last_probe_detail.status = READY`
- الصف: `sandboxed:true`، `isolation:WORKER_DECLARED` (مفردات الواجهة)،
  `profile.worker_id` حاضر، و`host-truth`: `isolation:SANDBOXED`
  و`local_execution:AVAILABLE`
- سلم المفردات المعلن (`service.py:355-385`): الصف يكتب HEALTHY على
  محور الصحة بعد تحقق ناجح؛ READY تُوثقها البوابة داخل
  `last_probe_detail` — وهذا ما ظهر حيًّا.

### 5.3 مطابقة API ↔ واجهة (Chromium حي)

تبويب الإعدادات ← بيئات التنفيذ: بطاقة البيئة تطابق API على كل الحقول
(الاسم/الخلفية/الحالة HEALTHY/العامل endpoint/النظام Linux / x86_64/
آخر تحقق/مفردة العزل «حسب إعلان العامل»)، ولوحة حقيقة المضيف تعرض
«العزل المحلي: متاح (ركيزة namespaces+seccomp)». التوكن لم يُرسم
أبدًا في الصفحة. اللقطة: `ui_settings_execution.png`؛ التفصيل:
`api_ui_consistency.json`.

### 5.4 اختبارا D2/D3 دون SKIP (طلب §5 الحرفي)

| الاختبار | عند خط الأساس 622be149 | على الفرع |
|---|---|---|
| `test_d2_live_substrate_isolation_probe_on_linux` | **FAILED** — `AssertionError: NOT RUN` (tripwire) | **PASSED** — العامل الحقيقي على ركيزة: مسبار BLOCKED بتحدٍّ متكرر + إثبات تحكم |
| `test_d3_isolated_success_contract_on_linux` | **FAILED** — `AssertionError: NOT RUN` (tripwire) | **PASSED** — نجاح معزول عبر /run: exit 0، COMPLETED، مخرجات وartifacts فعلية، `sandboxed:true` من الوضع الفعلي، لا FAILURE_UNCODED |

لا تحويل SKIP إلى PASS: skipif(not-linux) باقٍ كما هو (Windows = NOT RUN
صادق)، وعلى Linux بلا ركيزة: skip صادق معلن «لا ركيزة على هذا المضيف».

## 6. الإصلاحات (ضمن نطاق §6) — كلٌّ بدليل انحدار

### 6.1 عيب حقيقي كشفه هذا التشغيل: مسبار العزل (سكربت العامل)

- **العيب**: قالب `_ISOLATION_PROBE_TEMPLATE` كان يستقبل الهدف **سلسلة**
  `"host:port"` بينما `socket.create_connection` يشترط **زُبعًا**
  `(host, port)` — ينفجر داخل الركيزة بـ
  `ValueError('too many values to unpack (expected 2)')` ويرجع
  `INCONCLUSIVE`.
- **دليل الفشل عند خط الأساس** (حي): `worker_probe_bug_baseline_622be149.json`
  (قبل أي تعديل) — وأثره امتد لمسار ثانٍ: فحص `isolation_probe` في
  تحقق الخلفية (`test_remote_worker_protocol_real_over_http`:
  `NOT_READY` بسبب المسبار نفسه).
- **الإصلاح**: سطر واحد (`target=(target[0], target[1])`) بتعليق يوثق
  العيب والدليل.
- **الانحدار**: الأساس = فشل (المسبار INCONCLUSIVE + تحقق الخلفية
  NOT_READY)؛ بعد = نجاح (BLOCKED + READY). الاختباران الحيّان
  الجديدان يضمنان عدم عودته.

### 6.2 الاختباران الحيّان (استبدال tripwolves)

- **السبب (نص §5)**: تشغيل الاختبارين في Linux دون SKIP — الجسد
  القديم كان يفشل بعناد بالتصميم حتى يُستبدل ببرهان حي عند توفر
  مضيف ركيزة؛ توفر المضيف فتح الطريق.
- **الحفاظ على الدلالة**: لا SKIP→PASS؛ حارس توفر الركيزة skip صادق؛
  التوكن وقت-تشغيل بلا نص حرفي في Git.
- **الانحدار**: فشل عند الأساس (موثق `d2_d3_baseline_fail.txt`) →
  نجاح على الفرع.

### 6.3 عيب كامن أُحيي: ذيل `test_f_strict_windows_wsl_ready…`

- كان الفرع المحمي بـ`if verify.ok` **ميتًا خاملًا** (التحقق لم يكن
  ينجح أبدًا قبل إصلاح المسبار) — نجاحًا فارغًا عند الأساس. الإصلاح
  أحياه فانكشف أن توقعه القديم (`status=="READY"` على صف البيئة)
  يخالف عقد المفردات المعلن بعد 013.10.
- **الإصلاح**: في الاختبار لا المنتج — يطابق الآن العقد المعلن
  ويُثبت أكثر (HEALTHY على الصف + READY داخل `last_probe_detail`).
- **الانحدار**: الأساس = نجاح فارغ؛ قبل التذييل = فشل (`HEALTHY != READY`
  بالتوقع القديم)؛ بعد = نجاح حقيقي أعمق.

## 7. جرد الأدلة (`docs/evidence/order01315/`)

| الملف | المحتوى |
|---|---|
| `git_prestate.json` | مراجع Git + حالة الشجرة قبل التنفيذ (رؤوس الأصل حية) |
| `executor_host_truth.json` | صدق المضيف: الجلسة Linux لا Windows (أدلة قاطعة) + حقائق 013.14 لجهاز المالك كمصدر منفصل |
| `substrate_capabilities_linux.json` | قياسات §4.5 (userns حي/seccomp/cgroups/rlimits) |
| `clock_inventory.json` + `clock_external_comparison.json` | جرد الساعة + المقارنة الخارجية (NTP + HTTP Date) |
| `worker_live_health/capabilities/probe/isolation_probe.json` | النقاط الأربع للعامل الحي بمسبار BLOCKED |
| `worker_probe_bug_baseline_622be149.json` | دليل فشل عيب المسبار عند خط الأساس (قبل أي تعديل) |
| `app_register/verify/env_list/host_truth.json` | التسجيل والتحقق عبر مسار المنتج + لا تسريب توكن |
| `api_ui_consistency.json` + `ui_settings_execution.png` | مطابقة API ↔ واجهة (Chromium حي) |
| `d2_d3_baseline_fail.txt` | فشل الاختبارين عند خط الأساس (نصف إثبات الانحدار) |
| `regression_baseline_622be149.txt` / `regression_branch_fixed.txt` | المقارنة الكاملة قبل/بعد |
| `regression_synthesis.json` | توليف الانحدار (كل الحالات مع التفسير) |
| `secrets_scan.json` | 30 ملفًا = نظيف (12 نمطًا + لا نص توكن حرفي) |
| `live_session_summary.json` | خلاصة الجلسة الحية (مراحل/بصمة توكن/فحص تسرب) |
| `owner_action_request.md` | التدخل الواحد المطلوب من المالك (لمسار WSL2-على-Windows) |

## 8. مقارنة الانحدار مقابل خط الأساس

- النطاق: `tests/execution` + `tests/substrate` كاملين +
  `tests/readiness/test_preflight_matrix.py` +
  `tests/api/test_ui_structure_order010.py` +
  `tests/api/test_sandbox_integration.py` — على خط الأساس والفرع.
- **صفر فشل جديد**؛ 4 حالات مُصلحة (2 بطلب §5، 1 بنفس جذر عيب
  المسبار، 1 عيبًا كامنًا أُحيي وصُحح)؛ 4 فشول قائمة بلا إخفاء
  (افتراضات مضيف Windows بلا ركيزة — منها `test_d2_real_worker…
  subprocess_mode` الذي يفترض العامل في وضع subprocess، وهنا العامل
  صراحة في وضع substrate فيرفض بطريقة أخرى صادقة).

## 9. القرار (§8)

1. **`STRICT_WORKER_READY` — على ركيزة الجلسة الحالية**: كل شروط §5
   مثبتة حيًّا (عامل Linux حي في وضع substrate، `sandboxed=true` من
   الركيزة الفعلية، النقاط الأربع، مسبار العزل BLOCKED مع قناة تحكم
   متاحة خارجها، الاختباران دون SKIP، مطابقة API/واجهة، لا تسريب)،
   وموثوقية الساعة مثبتة عند الالتقاط (إجماع NTP ≤2ms). وفق نص §8:
   يُفتح بعدها أمر مستقل لاحق وحده لتنفيذ E11 — **لم يُبدأ هنا**.
2. **`OWNER_ACTION_REQUIRED` — لمسار WSL2-على-Windows حصرًا** (جهاز
   المالك): التدخل الواحد: تفعيل الافتراضية (VT-x/SVM) من BIOS/UEFI
   ثم إعادة تشغيل — الخطوات الدقيقة وما يُفحص بعدها في
   `owner_action_request.md`. لم يُدَّع تنفيذه ولم تُلمس إعدادات
   firmware عن بُعد.
3. لا دمج إلى `main`؛ لا إعلان `E11=PASS`؛ لا تجربة مالك حقيقية من
   هذا الأمر؛ `main` وكل المراجع المحمية لم تتحرك (تحقق حي قبل
   الدفع وبعده).

## 10. الخطوة التالية المقترحة (خارج هذا الأمر)

أمر مستقل واحد يفتح E11: يشغّل عاملًا حيًا + تسجيل بيئة عبر مسار
المنتج (النمط المُثبت هنا) ثم مهمة المالك الحقيقية من واجهة المصنع
على مضيف الجلسة — أو، إن أراد المالك جهازه Windows/WSL2 مكان التنفيذ،
فينفذ `owner_action_request.md` أولًا (تفعيل الافتراضية + إعادة تشغيل)
ثم يعاد نفس الفحص هناك (الاختباران الحيّان يعملان تلقائيًا دون SKIP
على أي Linux بركيزة متاحة).

---

## 10-م (ملحق تصحيحي — أمر 013.16): ظهور `src/agentic_engineering_system.egg-info/` غير متعقب

اقتباس من حكم التحكيم على 013.15: «أضف ملحقًا تصحيحيًا صغيرًا يفسر ظهور
`src/agentic_engineering_system.egg-info/` كملف غير متعقب في دليل ما قبل
التنفيذ، ويميّز نظافة شجرة العمل عن نظافة فرق الكوميت».

**التفسير**: التثبيت القابل للتحرير الحرفي من README
(‎`pip install -e ".[test,pdf]"`‎) يولّد بصفة أثر جانبي مجلد بيانات تعريف
الحزمة `src/agentic_engineering_system.egg-info/` داخل شجرة المصدر — وهو
ناتج بناء وقت-تشغيل لا ملف مصدر، ولا يمس أي ملف متعقب. و`.gitignore` كان
يتجاهل الصنف الأقدم `src/agent_hub_v2.egg-info/` حصرًا، فظهر الصنف الجديد
في `git status` كغير متعقب رغم أن شجرة العمل لم تتغير فيها أي ملفات
متعقبة.

**التمييز المطلوب**:

- **نظافة شجرة العمل** (work tree): تعني «لا تغيير في الملفات المتعقبة» —
  كانت نظيفة فعلاً في 013.15 قبل التنفيذ وبعده (صفر staged/unstaged)؛
  العنصر غير المتعقب الوحيد كان أثر بناء من نوع لا يصل Git أصلًا.
- **نظافة فرق الكوميت** (commit diff): تعني «ما في الكوميت نفسه» — كوميتا
  013.15 لم يضيفا ولا ملف أثر بناء واحدًا؛ `egg-info` لم يدخلهما أبدًا.

أي أن «غير متعقب» هنا ليست «قذارة» بل تصنيف ناقص في `.gitignore` لمألوف
بناءٍ. **العلاج** (في أمر 013.16): أُضيف
`src/agentic_engineering_system.egg-info/` إلى `.gitignore` فتعود شجرة
عمل أي جلسة تثبيتٍ نظيفة تمامًا في `git status`، ويبقى التمييز مفهومًا:
أثر البناء لا يعدل المتعقب ولا يدخل الكوميتات.
