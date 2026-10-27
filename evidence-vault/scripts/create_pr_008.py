#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AES-UI-PREMIUM-REDESIGN-008 — create the DRAFT review PR.

Reads the GitHub token from the git remote URL (never prints it).
POSTs /repos/{owner}/{repo}/pulls with draft=true. Prints PR number + URL only.
"""
import json
import re
import subprocess
import sys
import urllib.request

REPO = "jsiadyarslan-lab/agentic-engineering-system"
TITLE = "AES-UI-PREMIUM-REDESIGN-007 — Visual Architecture Review"

url = subprocess.check_output(
    ["git", "-C", "/home/z/my-project/ui007", "config", "--get", "remote.origin.url"],
    text=True).strip()
m = re.match(r"https://([^@]+)@github\.com", url)
if not m:
    sys.exit("could not extract token from remote url")
TOKEN = m.group(1)

BODY = """## الالتزام الدقيق (Pin)

- **تزامن التصميم المرشح — غير معدول: `56e42ba460356b326a0fdd9da01f9c840a24bd11`**
- الالتزامان فوق `main`: `d380078` (إعادة تأسيس النظام البصري الكامل، 13 ملفًا) ← `56e42ba` (معالجة ملاحظات المراجعة المستقلة N-1..N-6، 7 ملفات).
- ملفات التصميم المتغيرة مقابل `main`: **14 ملفًا، كلها داخل `src/ui/`، صفر خارجها** (مطابق لتحقق المالك على GitHub).
- الالتزام `f720d7f` (فوق المرشح، من مهمة الأدلة 008) يضيف **حزمة الأدلة فقط** تحت `docs/evidence/UI007_evidence/` — `git diff 56e42ba..f720d7f -- src/` فارغ، ولا تاريخ أُعيد كتابته.

## ملخص المعمارية البصرية

من «مجموعة لهجات متعايشة» إلى **نظام بصري واحد**: ثلاث لوحات ألوان متصارعة (ذهبي/كحلي مصنع/بقايا فاتحة) انهارت في مصدر رموز واحد `theme.css` (327 سطرًا، 27 رمزًا معلنًا) يستهلكه كل ملفات الواجهة؛ سلّم تباين AA مقيس رقميًا (رفع أرضية النصوص الخافتة من 3.26:1 الفاشلة إلى ≥4.5:1، والمحدِّد placeholder من 3.26:1 إلى 7.0:1)؛ ستة أنظمة أزرار أصبحت تطبيقات لهندسة زر واحدة؛ ثلاثة أنظمة تبويبات بقاعدة خط سفلي ذهبي واحدة (rgb(212,172,85))؛ ~15 نظام شارة إلى مفردة دلالية واحدة (حي=أزرق الوكيل #58A6FF عبر رمز `--accent-agent` الموحّد، مكتمل=أخضر، منتظر=كهرماني، فاشل=أحمر)؛ خمسة مداخل mono إلى رمز `--font-mono` واحد؛ خمس نقاط انكسار متنافرة إلى مقياس موثق (480/720/900/1100)؛ مخططا z المتداخلان إلى سلّم واحد **بصفر قيم حرفية**؛ طبقة الترقيع الداكنة (79 سطرًا) وبقايا اللوحة الفاتحة (26 قيمة rgba + fallbacks ميتة) سقطتا بتعريب الجذر؛ أربع أخطاء وظيفية سابقة (ReferenceError تحت strict، تكدس أغلفة الأحداث، غياب مزامنة resize، فراغ صامت للمحادثة الفارغة) أُصلحت وموثقة داخل الكود. خرق النحافة الموروث لـ`styles.css` (1513 > سقف 1200) أُصلح إلى 1000.

## الأدلة — كلها داخل هذا الـPR، قابلة للفحص والاعتراض

| الأداة | المسار |
|---|---|
| **البيان** (التثبيت + الجرد + تصحيحات العدّ + دليل التحقق خطوة بخطوة) | `docs/evidence/UI007_evidence/README.md` |
| التقرير الجنائي (المرحلة 1) | `docs/evidence/UI007_evidence/reports/01-forensic-audit.md` |
| المصفوفة التنافسية + ملحق الروابط المؤكدة | `reports/02-competitive-matrix.md` + `sources-annex.md` |
| نظام التصميم وقرارات هندسة المعلومات | `reports/03-design-system.md` |
| سجل التغييرات + معاينة/تراجع | `reports/04-change-log.md` |
| الملاحظات N-1..N-6 بأدلة معالجة قابلة للتكرار | `notes-N1-N6-evidence.md` |
| ملخص الاختبارات بالفصل الثلاثي | `test-summary.md` |
| القيود المتبقية وأسبابها | `remaining-constraints.md` |
| صور قبل/بعد (44 + 37 على 6 مقاسات) + 10 لقطات إعادة إثبات | `baseline/` · `after/` · `reproof-008/shots/` |
| قياسات العناصر/التباين/الانحرافات (JSON) | `reproof-008/measurements.json` |
| تحليلات VLM الخام (4 نقدية + 6 مقارنات) | `audit-vlm/` |
| السكربتات القابلة للتكرار (007 + 008) | `scripts/` |
| بصمات السلامة | `SHA256SUMS` |

## نتائج الاختبارات — أعيد تشغيلها فعليًا عند `56e42ba` نفسه

| الفئة | النتيجة | رمز الخروج | الدليل |
|---|---|---|---|
| عقود البنية/النحافة/الجودة (pytest) | **97 passed · 0 failed · 0 skipped** (15.08s) | 0 | `reproof-008/contract-tests.txt` |
| عقود API (pytest) | **27 passed · 0 failed · 0 skipped** (120.16s) | 0 | `reproof-008/api-tests.txt` |
| متصفح حي (Chromium، جلسة واحدة متصلة) | كل الفحوص ناجحة؛ **صفر أخطاء console**؛ **صفر تجاوز أفقي** في 1920/1440/1280/768/390/360 | — | `reproof-008/browser-session.txt` (+`-extra.txt`) |
| **الإجمالي المعاد إثباته** | **124 = 97 + 27 — بلا تكرار عدّ** | | |

- **الحد المعتمد لـ`styles.css`:** معرف تعاقديًا في `tests/contracts/test_thinness.py:121-123` — `_count_lines(...) < 1200` (طريقة `splitlines`). القياس عند المرشح: **1000** بهذه الطريقة (و**1001** باصطلاح عرض GitHub — نفس الملف). ناجح بهامش ~17٪؛ وكان **1513 فاشلًا** عند خط الأساس `main@b38dbaf`.
- **تصحيح عدّ معلن (شفافية):** لقطات «بعد» = **37** لا 45 كما ورد نصيًا في تقريري 05/07 — قائمة اللقطات في `after_007.sh` تُنتج 37 فريدة تطابق الملفات حرفيًا؛ الإجمالي الحقيقي 81، وكل شاشة مغطاة قبل/بعد، واللقطة الأساسية الناقصة الوحيدة (`chat-1440`) استُكملت في `reproof-008/shots/`.
- اختبارات لم تُنفّذ وأسبابها موثقة في `test-summary.md` §2 (ركيزة bwrap للـcore/factory؛ واختبار تصفح خارجي من أمر 013 خارج النطاق).

## القيود المتبقية (معرفة كاملة في `remaining-constraints.md`)

1. مسارات التنفيذ الحي بوكيل فعلي غير قابلة للتوليد في بيئة الفحص (لا مزود مُهيأ ولا bwrap) — بنيتها وعقودها خضراء.
2. بوابة CI تحتاج عدّاءً self-hosted بـbwrap (انظر الملاحظة أدناه).
3. قرارات مؤجلة للمالك: الدمج، النشر على Oracle، رفع الإصدار 4.0.0.

## ملاحظة CI (بيئية، موثقة سلفًا)

تدقيق 004/005 أثبت بالسجلات الخام أن المجموعة الموثوقة تفشل **بيئيًا** على عدّاءات GitHub المستضافة (`bwrap: loopback: Failed RTM_NEWADDR`) بتوقيع مطابق (8 failed / 243 passed / 14 skipped) عبر 4 تزامنات شملت خط أساس ما قبل الواجهة والتكامل — لا صلة لهذا الفرع الذي لم يلمس ملفًا واحدًا خارج `src/ui/`.

## الحدود

- **مسودة عمدًا — قرار الدمج والنشر للمالك حصرًا.** لا نشر على Oracle ولا تغيير Nginx من هذه المهمة.
- كل ادعاء في هذا الـPR مربوط بأمر قابل للتكرار أو ملف خام مرفق؛ إعادة الإثبات 008 مستقلة عن تقرير المنفذ.
"""

payload = json.dumps({
    "title": TITLE,
    "head": "aes-ui-premium-redesign-007",
    "base": "main",
    "body": BODY,
    "draft": True,
}).encode("utf-8")

req = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/pulls",
    data=payload,
    headers={
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(f"PR #{data['number']} created: {data['html_url']}")
        print(f"draft={data['draft']}  state={data['state']}  head={data['head']['sha'][:12]}  base={data['base']['ref']}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")
    print(f"HTTP {e.code}: {body[:400]}", file=sys.stderr)
    sys.exit(1)
