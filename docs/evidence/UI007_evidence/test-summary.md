# AES-UI-PREMIUM-REDESIGN-008 — ملخص الاختبارات المعاد تشغيلها عند `56e42ba`

> القاعدة: كل نتيجة أدناه من تشغيل فعلي عند رأس المرشح نفسه، بالأمر الحرفي الموثق ورمز الخروج الفعلي. السجلات الكاملة (`-v` بكل اختبار) في `reproof-008/contract-tests.txt` و`reproof-008/api-tests.txt`. لا إعادة إنشاء من الذاكرة.

## 1) الفصل الثلاثي المطلوب

### (أ) اختبارات العقود البنيوية والنحافة — **97 passed / 0 failed / 0 skipped / 0 errors — exit 0 — 15.08s**

```bash
cd <worktree at 56e42ba>
PYTHONPATH=src python3 -m pytest \
  tests/contracts/test_thinness.py \
  tests/api/test_ui_structure_order006.py \
  tests/api/test_ui_structure_order010.py \
  tests/api/test_ui_structure_order011.py \
  tests/harness/test_ui_structure_order012.py \
  tests/test_order005_ui_quality.py \
  tests/test_order6_revised.py -v
```
الملف: `reproof-008/contract-tests.txt` (collect-only: 97 tests collected — العدّ من الجمع الفعلي لا من التقرير).

### (ب) اختبارات عقود API — **27 passed / 0 failed / 0 skipped / 0 errors — exit 0 — 120.16s**

```bash
PYTHONPATH=src python3 -m pytest \
  tests/api/test_conversations.py \
  tests/api/test_conversation_identity.py \
  tests/api/test_projects_011.py \
  tests/api/test_projects_api.py -v
```
الملف: `reproof-008/api-tests.txt` (collect-only: 27 tests collected).

**الإجمالي المعاد إثباته: 124 = 97 + 27 — بلا تكرار عدّ** (المجموعتان منفصلتان بملفات لا تتقاطع)، وبلا اختبار متجاوز يُحسب نجاحًا (صفر skipped في المجموعتين). التحذيران الوحيدان: `DeprecationWarning` من `on_event` في FastAPI — تحذير إطار غير وظيفي، موروث وسابق لإعادة التصميم.

### (ج) اختبارات المتصفح الحي — جلسة واحدة متصلة، **كل الفحوص ناجحة**

الملفات: `reproof-008/browser-session.txt` + `browser-session-extra.txt` (الأوامر النصية في `scripts/reproof_008.sh` و`reproof_extra_008.sh`):
- تحميل الترحيب + بطاقتا اقتراح (عنوان+وصف) — ✓ (2/2/2)
- محادثة بالتاريخ: 4 فقاعات + جدول md + كود — ✓
- إرسال حي بلا مزود → بطاقة خطأ صادقة واحدة بنص فعل — ✓
- الإعدادات: 6 تبويبات، 76 زرًا مقيسة، Esc يغلق — ✓
- المصنع: متصل + مشروعان (بيانات فعلية) + تبويب نشط ذهبي + أول عرض بلا active — ✓
- المشروع: 6 تبويبات تُصيَّر ببيانات فعلية — ✓
- التشغيلات/الأرشيف يظهران (display:flex) — ✓
- محادثة فارغة → إرشاد صادق (BUG-04) — ✓
- تغيير الحجم 1440→390→1440 بلا إعادة تحميل يتزامن مع 900px (BUG-03) — ✓
- **أخطاء console: صفر. أخطاء صفحة: صفر.** في الجلسات الثلاث (reproof + extra).

### (د) الاختبارات البصرية المقارنة

- 44 لقطة «قبل» + 37 «بعد» بنفس المسارات والأحجام (التصحيح العددي موثق في README §3) + 10 لقطات إعادة إثبات 008 منها `chat-1440` المستكملة.
- **صفر تجاوز أفقي في المقاسات الستة** (قياس حي متجدد في `measurements.json` → `viewport_measurements`).
- 6 مقارنات VLM خام (`audit-vlm/cmp-*.json`) + 4 تحليلات نقدية (`audit-vlm/*.json`).

## 2) اختبارات لم تُنفّذ في إعادة الإثبات — وبسبب موثق

| المجموعة | السبب | الموقف |
|---|---|---|
| `tests/core/` + `tests/factory/` + `tests/readiness/` + `ci_trusted_suite.sh` | تتطلب ركيزة عزل `bwrap` غير مثبتة في صندوق الفحص — الفشل الناتج **بيئي وموثق**: توقيع مطابق (8 failed / 243 passed / 14 skipped) على 4 تزامنات مختلفة شملت `ed9e18a` و`d55f4bb` (تدقيق 004/005 وسجلاته في `download/ci-closeout/`) | لا صلة بإعادة التصميم: `git diff --name-only main..56e42ba` = 14 ملفًا كلها `src/ui/` — لا ملف تنفيذ واحد تغيّر. بوابة CI تحتاج عدّاءً self-hosted بـbwrap |
| `tests/browser/test_browser_013.py` | اختبار قدرة تصفح خارجي (HTTPS عام) من الأمر 013 — خارج نطاق 007 أصلًا ويتطلب وصول شبكة خارجي | ليس من الـ124، ولا علاقة له بالمرشح |

## 3) الحد المعتمد لـ`styles.css` — الإثبات الكامل

- **العقد:** `tests/contracts/test_thinness.py:121-123` — `assert _count_lines("src/ui/styles.css") < 1200` حيث `_count_lines = len(Path(...).read_text().splitlines())`.
- **القياس عند `56e42ba`:** `splitlines()` = **1000** (طريقة الاختبار) · `wc -l` = 1000 · `split('\n')` = **1001** (اصطلاح عرض GitHub — نفس ما رصده المالك).
- **النتيجة:** ناجح بهامش ~17%، والاختبار يعمل فعليًا ضمن الـ97 (`test_styles_css_under_1200_lines PASSED` في `contract-tests.txt`).
- **السياق:** عند خط الأساس `main@b38dbaf` كان الملف 1513 سطرًا والاختبار **فاشلًا** (خرق موروث أصلحه 007: 1513→1000).

## 4) بيئة التشغيل

- Python 3.12.15 · pytest 9.0.2 · التبعيات كما في `pyproject.toml` (fastapi/uvicorn/sqlalchemy/pydantic/pydantic-settings/python-dotenv/psutil + httpx).
- المتصفح: agent-browser 0.39.0 (Chromium). الخادوم: uvicorn على منفذ محلي معزول، قاعدة اختبار مستقلة مبذورة بنماذج فعلية.
- أُعيد بناء بيئة الفحص (venv) بين الجلسات؛ أُعيد تثبيت التبعيات قبل إعادة التشغيل — لا تأثير على النتائج (الاختبارات تعمل على مصدر المستودع لا على الحزمة المثبتة).
