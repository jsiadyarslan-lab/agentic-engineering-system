"""مولّد كود PDF العربي (مستخرج من roles/tools.py — عقد الأمر 008 للنحافة).

الكود نص برمجي يُنفَّذ داخل الركيزة أو في العملية؛ root_expr يحدد جذر
الأدلة: ‎'/artifacts' داخل الركيزة و'.' في العملية. بادئان حتميان:
تخطيط عادي؛ فإن تجاوز صفحة واحدة أعاد البناء مضغوطًا — وبعد
البادئين يظل >1 صفحة = فشل صريح يترك للمنفذ (§4.3 الأمر السادس).
"""

from __future__ import annotations

import json


def build_pdf_code(md_rel: str, out_rel: str, font_path: str,
                   root_expr: str = "pathlib.Path('/artifacts')") -> str:
    return (
        "import json, pathlib, re\n"
        "import arabic_reshaper\n"
        "from bidi.algorithm import get_display\n"
        "from pypdf import PdfReader\n"
        "from reportlab.lib.pagesizes import A4\n"
        "from reportlab.lib.enums import TA_RIGHT\n"
        "from reportlab.lib.styles import ParagraphStyle\n"
        "from reportlab.pdfbase import pdfmetrics\n"
        "from reportlab.pdfbase.ttfonts import TTFont\n"
        "from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer\n"
        f"payload = json.loads({json.dumps({'md': md_rel, 'out': out_rel, 'font': font_path})!r})\n"
        f"root = {root_expr}\n"
        "md = (root / payload['md']).read_text(encoding='utf-8')\n"
        "import re as _re\n"
        # (W2-T25) تنظيف تسلسلات الهروب الحرفية \uXXXX من نص المنفذ
        "md = _re.sub(r'\\\\u[0-9a-fA-F]{4}', '', md)\n"
        # (W2-T25) XML entities تفلسم Paragraph
        "md = md.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')\n"
        "font = pathlib.Path(payload['font'])\n"
        "pdfmetrics.registerFont(TTFont('PlexArabic', str(font)))\n"
        "def ar(t):\n"
        "    return get_display(arabic_reshaper.reshape(str(t)))\n"
        "def build(compact):\n"
        "    lead = 15 if compact else 17\n"
        "    src_size = 9 if compact else 10\n"
        "    title = ParagraphStyle('t', fontName='PlexArabic', fontSize=16 if compact else 17, leading=22 if compact else 26, alignment=TA_RIGHT)\n"
        "    body = ParagraphStyle('b', fontName='PlexArabic', fontSize=11, leading=lead, alignment=TA_RIGHT)\n"
        "    h2 = ParagraphStyle('h', fontName='PlexArabic', fontSize=12.5 if compact else 13, leading=17 if compact else 20, alignment=TA_RIGHT)\n"
        "    small = ParagraphStyle('s', fontName='PlexArabic', fontSize=src_size, leading=src_size + 3, alignment=TA_RIGHT)\n"
        "    story = []\n"
        "    in_sources = False\n"
        "    for block in md.splitlines():\n"
        "        line = block.strip()\n"
        "        if not line:\n"
        "            continue\n"
        "        if line.startswith('# '):\n"
        "            story.append(Paragraph(ar(line[2:]), title)); story.append(Spacer(1, 7 if compact else 10))\n"
        "        elif line.startswith('## '):\n"
        "            head = line[3:]\n"
        "            in_sources = head.startswith('\\u0627\\u0644\\u0645\\u0635\\u0627\\u062f\\u0631')\n"
        "            story.append(Spacer(1, 3 if compact else 6)); story.append(Paragraph(ar(head), h2))\n"
        "        elif line.startswith('- '):\n"
        "            story.append(Paragraph(ar('\\u2022 ' + line[2:]), small if in_sources else body))\n"
        "        else:\n"
        "            story.append(Paragraph(ar(line), small if in_sources else body))\n"
        "    doc = SimpleDocTemplate(str(root / payload['out']), pagesize=A4,\n"
        "        rightMargin=57, leftMargin=57, topMargin=57, bottomMargin=57)\n"
        "    doc.build(story)\n"
        "build(False)\n"
        "if len(PdfReader(str(root / payload['out'])).pages) > 1:\n"
        "    build(True)\n"
        "print('pdf_written pages=' + str(len(PdfReader(str(root / payload['out'])).pages)))\n"
    )
