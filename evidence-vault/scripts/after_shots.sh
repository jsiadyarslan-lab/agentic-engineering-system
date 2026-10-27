#!/bin/bash
# جلسة تصوير "بعد" — نفس مسارات جلسة "قبل" تماماً للمقارنة العادلة
set -u
cd /home/z/my-project/ui-work
DB=runtime/ui-redesign.db
PORT=8020
OUT=/home/z/my-project/download/ui-redesign/after

PYTHONPATH=src AGenthubV2_DB_PATH=$DB python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-ui.log 2>&1 &
SRV=$!
for i in $(seq 1 30); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
curl -s -o /dev/null -w "server: %{http_code}\n" http://127.0.0.1:$PORT/ || { echo "SERVER FAILED"; kill $SRV 2>/dev/null; exit 1; }

ab() { agent-browser "$@"; }

# كسر التخزين المؤقت للمتصفح من الجلسات السابقة
STAMP=$(date +%s)
ab open "http://127.0.0.1:$PORT/?fresh=$STAMP" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1

# سطح المكتب 1440×900
ab set viewport 1440 900 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 1200 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-welcome.png > /dev/null 2>&1
echo "shot: welcome"

ab open "http://127.0.0.1:$PORT/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1; ab wait 1500 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-chat-messages.png > /dev/null 2>&1
echo "shot: chat-messages"

# الإعدادات — الشكوى الأساسية
ab find role button click --name "الإعدادات: المزودون والنماذج والقدرات وبيئات التنفيذ" > /dev/null 2>&1 || ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-settings-drawer.png > /dev/null 2>&1
echo "shot: settings-drawer"

ab eval "var t=document.querySelectorAll('.settings-tab'); t[1]&&t[1].click()" > /dev/null 2>&1
ab wait 1800 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-settings-providers.png > /dev/null 2>&1
echo "shot: settings-providers"

# اختبار مفتاح Esc
ab press Escape > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
ESC=$(ab eval "document.getElementById('settings-drawer').hidden" 2>&1 | head -1)
echo "esc-closes-drawer: $ESC"

ab eval "document.querySelector('[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2500 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-factory.png > /dev/null 2>&1
echo "shot: factory"

ab eval "document.querySelector('[data-nav=runs]').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-runs.png > /dev/null 2>&1
echo "shot: runs"

# 1280×800
ab set viewport 1280 800 > /dev/null 2>&1
ab open "http://127.0.0.1:$PORT/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1; ab wait 1200 > /dev/null 2>&1
ab screenshot $OUT/laptop-1280-chat.png > /dev/null 2>&1
echo "shot: laptop-1280"

# لوحي 768×1024
ab set viewport 768 1024 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 1500 > /dev/null 2>&1
ab screenshot $OUT/tablet-768-chat.png > /dev/null 2>&1
ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot $OUT/tablet-768-settings.png > /dev/null 2>&1
ab eval "document.getElementById('settings-close').click()" > /dev/null 2>&1
echo "shot: tablet-768"

# هاتف 390×844 — إعادة تحميل ليطبق الطي التلقائي
ab set viewport 390 844 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 1800 > /dev/null 2>&1
ab screenshot $OUT/mobile-390-chat.png > /dev/null 2>&1
echo "shot: mobile-390"

# فحص عدم وجود تمرير أفقي عام على الجوال
HZ=$(ab eval "document.documentElement.scrollWidth > document.documentElement.clientWidth ? 'OVERFLOW' : 'ok'" 2>&1 | head -1)
echo "mobile-horizontal-scroll: $HZ"

echo "=== console errors ==="
ab console 2>&1 | grep -iE "error" | head -8 || echo "(none)"
echo "=== page errors ==="
ab errors 2>&1 | head -5 || echo "(none)"

kill $SRV 2>/dev/null
echo "AFTER SESSION DONE"
