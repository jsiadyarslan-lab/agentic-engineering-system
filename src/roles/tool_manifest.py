"""وصف الأدوات للنموذج (مستخرج من roles/tools.py — يُدمج في برومبت المنفذ).
"""

from __future__ import annotations

TOOLS_MANIFEST: list[dict] = [
    {"tool": "web_search", "args": {"query": "نص الاستعلام"},
     "desc": "بحث ويب (DuckDuckGo) — يعيد عناوين وروابط ومقتطفات"},
    {"tool": "fetch_page", "args": {"url": "https://…"},
     "desc": "جلب صفحة واستخلاص نصها"},
    {"tool": "write_file", "args": {"path": "report.md", "content": "…"},
     "desc": "كتابة ملف داخل المجلد الممنوح (داخل الركيزة)"},
    {"tool": "read_file", "args": {"path": "report.md"},
     "desc": "قراءة ملف من المجلد الممنوح (داخل الركيزة)"},
    {"tool": "run_python",
     "args": {"path": "tool.py", "args": ["وسيطة-اختيارية"]},
     "desc": "تشغيل ملف Python من المجلد الممنوح داخل الركيزة المعزولة — "
             "يعيد exit_code/stdout/stderr الفعلية (013.16)"},
    {"tool": "generate_pdf_arabic",
     "args": {"md_path": "report.md", "out_path": "report.pdf"},
     "desc": "توليد PDF عربي RTL بحجم A4 من ملف Markdown (داخل الركيزة)"},
    {"tool": "verify_pdf_pages", "args": {"path": "report.pdf"},
     "desc": "عدّ صفحات ملف PDF (داخل الركيزة)"},
    {"tool": "http_get_text", "args": {"url": "https://…/data.csv"},
     "desc": "جلب نص/CSV خام من رابط (معلن خارج الركيزة)"},
    {"tool": "http_get_json", "args": {"url": "https://…/api.json"},
     "desc": "جلب JSON من واجهة عامة (معلن خارج الركيزة)"},
    {"tool": "page_to_text", "args": {"url": "https://…/page"},
     "desc": "صفحة HTML → نص فقرات منسق (معلن خارج الركيزة)"},
    {"tool": "fred_csv", "args": {"series_id": "DGS10"},
     "desc": "سلسلة FRED رسمية بلا مفتاح — مثل DGS10/CPIAUCSL (معلن)"},
    {"tool": "worldbank_indicator",
     "args": {"indicator": "FP.CPI.TOTL.ZG", "countries": "SA;US", "dates": "2020:2024"},
     "desc": "مؤشر البنك الدولي — قيّد countries وdates (معلن)"},
    # (013 §13) متصفح ميكانيكي حي — للصفحات التي تحتاج DOM/تفاعلًا،
    # والبحث/الجلب لا يكفيان
    {"tool": "browser_navigate", "args": {"url": "https://…/page"},
     "desc": "متصفح حي: فتح صفحة فعليًا (DOM كامل) — عند تعذر الجلب الثابت"},
    {"tool": "browser_extract",
     "args": {"mode": "text|links", "limit": 50},
     "desc": "متصفح حي: استخلاص نص الصفحة الحالية أو روابطها"},
    {"tool": "browser_screenshot", "args": {"name": "page-shot"},
     "desc": "متصفح حي: لقطة شاشة للصفحة الحالية (دليل بـsha256)"},
    {"tool": "browser_click", "args": {"selector": "a.next"},
     "desc": "متصفح حي: نقر عنصر بمحدد CSS"},
    {"tool": "browser_type",
     "args": {"selector": "input[name=q]", "text": "استعلام"},
     "desc": "متصفح حي: إدخال نص في حقل"},
    {"tool": "browser_download", "args": {"url": "https://…/file.pdf"},
     "desc": "متصفح حي: تنزيل ملف داخل رمل الجلسة"},
    {"tool": "browser_wait", "args": {"seconds": 1.0},
     "desc": "متصفح حي: انتظار تحميل الديناميكي"},
]
