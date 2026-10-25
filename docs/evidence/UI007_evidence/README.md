# AES-UI-PREMIUM-REDESIGN-008 — Final Evidence Package (Review Gate)

> **الغرض:** جعل كل أدلة التسليم الخاصة بإعادة الهيكلة البصرية 007 قابلة للفحص داخل المستودع نفسه، مربوطة بالالتزام المرشح، وقابلة للتكرار بأوامر موثقة — بدل الاعتماد على تقرير المنفذ أو ملفات محلية لا يصل إليها المراجع.

## 1) التثبيت (Pin)

| العنصر | القيمة |
|---|---|
| **التزام التصميم المرشح (غير قابل للتعديل)** | `56e42ba460356b326a0fdd9da01f9c840a24bd11` |
| الالتزامات فوق `main` (تصميم فقط) | `d380078` (إعادة التأسيس، 13 ملفًا) ← `56e42ba` (معالجة N-1..N-6، 7 ملفات) |
| ملفات التصميم المتغيرة مقابل `main` | **14 ملفًا، كلها داخل `src/ui/`، صفر خارجها** (تحقق مطابق لتحقق المالك على GitHub) |
| التزامات الأدلة (هذه الحزمة) | تُضاف **فوق** `56e42ba` على الفرع نفسه، وتضيف ملفات تحت `docs/evidence/UI007_evidence/` **حصرًا** — لا تلمس أي ملف تصميم ولا تعيد كتابة أي تاريخ (`git diff 56e42ba..HEAD -- src/` فارغ) |
| القاعدة | `main` عند `b38dbaf` — لم يُلمس؛ لا نشر على Oracle؛ قرار الدمج والنشر للمالك |

## 2) جرد الحزمة

| المسار | المحتوى | العدد |
|---|---|---|
| `reports/` | تقارير 007 الأصلية كما كُتبت (01 جنائي، 02 تنافسية، 03 نظام تصميم، 04 سجل تغييرات، 05 اختبارات، 06 مراجعة مستقلة، 07 حكم) | 7 |
| `baseline/` | لقطات «قبل» عند خط الأساس `main@b38dbaf` — 6 مقاسات | 44 |
| `after/` | لقطات «بعد» عند `56e42ba` — نفس المسارات والأحجام | 37 |
| `audit-vlm/` | تحليلات VLM الخام (4 نقدية على خط الأساس + 6 مقارنات) | 10 |
| `scripts/` | سكربتات 007 القابلة للتكرار كما نُفذت + سكربتات إعادة الإثبات 008 | 8 + 4 |
| `reproof-008/` | إعادة الإثبات المستقلة عند `56e42ba` (انظر §4) | سجلات + قياسات + لقطات |
| `SHA256SUMS` | بصمات كل ملفات الحزمة للتحقق من عدم التبديل | 1 |

## 3) تصحيحات العدّ (شفافية كاملة — الأدلة أصدق من نص التقرير)

1. **عدد اللقطات:** ذكر تقريرا 05 و07 «44 قبل + 45 بعد = 89». **الحقيقة على القرص: 44 + 37 = 81 ملفًا.** قائمة اللقطات المعرفة في سكربت `after_007.sh` تُنتج 37 لقطة فريدة بالضبط (تطابق الملفات حرفيًا)، منها 35 مقابلًا مباشرًا للقطات «قبل» الأساسية + لقطة الصفحة الكاملة + لقطتان جديدتان (settings-providers-verify وchat-empty-conv). لقطة `chat-1440` الأساسية كانت بلا مقابل «بعد» — **أُعيد التقاطها في `reproof-008/shots/chat-1440.png`**. لقطات «قبل» الثمان ذات البادئة `pop` (حالات منبثقة) لها مقابل «بعد» بأسماء أساسية للشاشات نفسها. خطأ العدّ كان في نصّ التقرير فقط، لا في الأدلة.
2. **قياس `styles.css`:** الحد المعتمد محدد تعاقديًا في `tests/contracts/test_thinness.py:121-123`: **`_count_lines("src/ui/styles.css") < 1200`** حيث `_count_lines = len(text.splitlines())`. القياس عند `56e42ba`: **1000 بطريقة الاختبار (`splitlines`)**، و**1001 بطريقة `split('\n')`** (اصطلاح عرض واجهة GitHub الذي رصده المالك) — نفس الملف، وكلا الاصطلاحين تحت السقف بهامش ~17%. الاختبار ناجح فعليًا ضمن الـ97 (انظر `reproof-008/contract-tests.txt`).

## 4) إعادة الإثبات المستقلة (reproof-008) — كلها عند `56e42ba` بالضبط

| الملف | المحتوى | الأمر/الرمز |
|---|---|---|
| `contract-tests.txt` | 97 عقود بنيوية/نحافة/جودة — **97 passed, exit 0, 15.08s** | `PYTHONPATH=src /home/z/.venv/bin/python3 -m pytest <الحزمة> -v` |
| `api-tests.txt` | 27 عقد API (محادثات/هوية/مشاريع) — **27 passed, exit 0, 120.16s** | نفس النمط |
| `static-checks.txt` | فحوص ساكنة قابلة للتكرار: صفر z حرفية، صفر بقايا اللوحة الفاتحة، جرد hex الكامل، تباين N-6 محسوبًا **4.59:1**، إثبات BUG-01..04 في الكود | `bash scripts/static_checks_008.sh` |
| `browser-session.txt` | جلسة متصفح حي كاملة: إعادة تحقق N-1..N-6 وBUG-01..04، قياسات MEASURE، **صفر أخطاء console، صفر تجاوز أفقي في 6 مقاسات** | `bash scripts/reproof_008.sh` |
| `browser-session-extra.txt` | نص الحالة الفارغة الحرفي + نص بطاقة الخطأ الصادقة كاملًا | `bash scripts/reproof_extra_008.sh` |
| `measurements.json` | قياسات العناصر/التباين/الانحرافات مجمّعة آليًا من السجلات | `python3 scripts/assemble_measurements_008.py` |
| `shots/` | 10 لقطات إعادة إثبات (بينها `chat-1440` المستكملة) | — |

## 5) كيف يتحقق المراجع بنفسه

```bash
git clone https://github.com/jsiadyarslan-lab/agentic-engineering-system.git
cd agentic-engineering-system && git checkout aes-ui-premium-redesign-007
git log --oneline main..HEAD            # d380078 + 56e42ba + التزامات الأدلة
git diff --name-only main..56e42ba      # 14 ملفًا كلها src/ui/
git diff --stat 56e42ba..HEAD -- src/   # فارغ: الأدلة لم تلمس التصميم

# 1) إعادة الاختبارات (124 = 97 + 27)
PYTHONPATH=src python3 -m pytest tests/contracts/test_thinness.py \
  tests/api/test_ui_structure_order006.py tests/api/test_ui_structure_order010.py \
  tests/api/test_ui_structure_order011.py tests/harness/test_ui_structure_order012.py \
  tests/test_order005_ui_quality.py tests/test_order6_revised.py -v
PYTHONPATH=src python3 -m pytest tests/api/test_conversations.py \
  tests/api/test_conversation_identity.py tests/api/test_projects_011.py \
  tests/api/test_projects_api.py -v

# 2) المعاينة الحية المحلية (لا تلمس الإنتاج)
PYTHONPATH=src python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port 8090
# ثم افتح http://127.0.0.1:8090/

# 3) سلامة الحزمة
sha256sum -c docs/evidence/UI007_evidence/SHA256SUMS
```

التبعيات المطلوبة للاختبارات: `fastapi uvicorn sqlalchemy pydantic pydantic-settings python-dotenv psutil httpx` (ملائمة من `pyproject.toml`).

## 6) قواعد المنهج الملتزمة

- لا بيانات وهمية: كل الجلسات بقاعدة معزولة مبذورة بنماذج SQLAlchemy فعلية (`scripts/seed_ui_007.py`) + مشروعان عبر `POST /api/projects`؛ حالات الفشل تُعرض بفشلها الصادق.
- لا ادعاء «تحقق مستقل» بلا دليل: كل ادعاء في هذه الحزمة مربوط بأمر قابل للتكرار أو ملف خام مُرفق.
- الاختبارات المتجاوزة لا تُحسب نجاحًا: في المجموعتين المعاد تشغيلهما **صفر تخطٍّ**؛ والاختبارات غير المنفذة وأسبابها موثقة في `test-summary.md`.
- الملاحظات N-1..N-6: لكل ملاحظة دليل معالجة قابل للتكرار في `notes-N1-N6-evidence.md`.
