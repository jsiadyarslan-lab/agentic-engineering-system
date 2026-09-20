# textstats

أداة بسيطة لحساب الأسطر، الكلمات، والأحرف في ملف نصي.

## الاستخدام

لتشغيل الأداة، استخدم الأمر التالي من سطر الأوامر:

```bash
python textstats/cli.py <path_to_file>
```

## مثال

إذا كان لديك ملف باسم `sample.txt` يحتوي على:
```
hello world
second line
```

فإن تشغيل الأمر:

```bash
python textstats/cli.py sample.txt
```

سيعطيك المخرجات التالية:

```
lines: 2
words: 4
chars: 23