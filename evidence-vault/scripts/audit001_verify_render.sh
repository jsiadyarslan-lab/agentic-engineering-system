#!/bin/bash
# AES-AUDIT-001 — final render verification of the docx (page count + VLM visual check)
D=/home/z/my-project/download/aes-audit-001
F=/home/z/my-project/download/AES-AUDIT-001-Comprehensive-Audit-Report.docx

echo "== page count =="
pdfinfo "$D/AES-AUDIT-001-Comprehensive-Audit-Report.pdf" | grep Pages

echo "== VLM page check =="
cd "$D" || exit 1
z-ai vision -p "هذه أول 4 صفحات من تقرير Word عربي RTL (الغلاف الداكن، ثم الفهرس، ثم أول صفحات المتن). تحقق بدقة من: 1) الغلاف: هل النص أبيض واضح على الخلفية الداكنة؟ هل العنوان مقطوع أو متجاوز؟ هل يظهر نص أسود غير مرئي؟ 2) الفهرس: هل يحتوي مداخل فعلية بأرقام صفحات؟ 3) صفحات المتن: هل النص العربي RTL سليم الاتجاه؟ هل الجداول بحدود سليمة؟ هل اللقطات ظاهرة؟ اذكر أي عيب حرفيًا، أو قل 'سليم' لكل نقطة." \
  -i "$D/pagecheck-01.png" -i "$D/pagecheck-02.png" -i "$D/pagecheck-03.png" -i "$D/pagecheck-04.png" \
  -o "$D/vlm-pagecheck.json" 2>&1 | tail -1

/home/z/.venv/bin/python - <<'EOF'
import json
d = json.load(open('/home/z/my-project/download/aes-audit-001/vlm-pagecheck.json'))
print(d['choices'][0]['message']['content'][:1600])
EOF
