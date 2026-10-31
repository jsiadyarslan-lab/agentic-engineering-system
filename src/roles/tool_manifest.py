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
    {"tool": "run_build_command",
     "args": {"command": "npm install", "timeout_s": 600},
     "desc": "أوامر بناء حقيقية (W2-T24) — قائمة بيضاء مغلقة تنفذ فعليًا "
             "بأدلة exit_code/stdout/stderr؛ يستدعيها طور build_commands "
             "النظامي لا خطة الأدوات الحرة"},
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
    {"tool": "browser_screenshot",
     "args": {"name": "evidence/list-mobile", "width": 375, "height": 667},
     "desc": "متصفح حي: لقطة بشاشة width/height — name مسار نسبي بلا .png"
             " يُنسخ داخل مساحة الخطوة (375 جوال / 1280 حاسوب)"},
    {"tool": "browser_open_local", "args": {"path": "index.html"},
     "desc": "متصفح حي: فتح صفحة HTML من مساحة الخطوة (file://)"},
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
