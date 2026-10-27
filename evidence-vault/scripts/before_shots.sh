#!/bin/bash
# جلسة تصوير "قبل" — خادم + بذر + متصفح في استدعاء واحد (البيئة تقتل العمليات بين الاستدعاءات)
set -u
cd /home/z/my-project/ui-work
DB=runtime/ui-redesign.db
PORT=8020
OUT=/home/z/my-project/download/ui-redesign/before

# 1) إقلاع الخادم
PYTHONPATH=src AGenthubV2_DB_PATH=$DB python3 -m uvicorn src.api.routes:app --host 127.0.0.1 --port $PORT > /tmp/aes-ui.log 2>&1 &
SRV=$!
for i in $(seq 1 30); do curl -s -o /dev/null http://127.0.0.1:$PORT/health && break; sleep 0.5; done
curl -s -o /dev/null -w "server: %{http_code}\n" http://127.0.0.1:$PORT/ || { echo "SERVER FAILED"; kill $SRV 2>/dev/null; exit 1; }

# 2) بذر بيانات حقيقية (محادثات + رسائل عبر نماذج التطبيق)
AGenthubV2_DB_PATH=$DB python3 /home/z/my-project/scripts/seed_ui_demo.py "$DB"

# 3) جلسة المتصفح — صور قبل
ab() { agent-browser "$@"; }

ab open "http://127.0.0.1:$PORT/" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1

# سطح المكتب 1440×900
ab set viewport 1440 900 > /dev/null 2>&1
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 1200 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-welcome.png > /dev/null 2>&1
echo "shot: welcome"

# محادثة حقيقية بمحتوى
ab open "http://127.0.0.1:$PORT/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1; ab wait 1500 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-chat-messages.png > /dev/null 2>&1
echo "shot: chat-messages"

# الإعدادات — الشكوى الأساسية
ab find role button click --name "الإعدادات: المزودون والنماذج والقدرات وبيئات التنفيذ" > /dev/null 2>&1 || ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-settings-drawer.png > /dev/null 2>&1
echo "shot: settings-drawer"

# تبويب المزودين داخل الإعدادات
ab eval "var t=document.querySelectorAll('.settings-tab'); t[1]&&t[1].click()" > /dev/null 2>&1
ab wait 1500 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-settings-providers.png > /dev/null 2>&1
echo "shot: settings-providers"

# إغلاق الإعدادات ثم مصنع الوكلاء
ab eval "document.getElementById('settings-close').click()" > /dev/null 2>&1
ab wait 600 > /dev/null 2>&1
ab eval "document.querySelector('[data-nav=factory]').click()" > /dev/null 2>&1
ab wait 2000 > /dev/null 2>&1
ab screenshot $OUT/desktop-1440-factory.png > /dev/null 2>&1
echo "shot: factory"

# التشغيلات
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
ab reload > /dev/null 2>&1; ab wait --load networkidle > /dev/null 2>&1; ab wait 1200 > /dev/null 2>&1
ab screenshot $OUT/tablet-768-chat.png > /dev/null 2>&1
ab find role button click --name "الإعدادات: المزودون والنماذج والقدرات وبيئات التنفيذ" > /dev/null 2>&1 || ab eval "document.getElementById('settings-open').click()" > /dev/null 2>&1
ab wait 1200 > /dev/null 2>&1
ab screenshot $OUT/tablet-768-settings.png > /dev/null 2>&1
ab eval "document.getElementById('settings-close').click()" > /dev/null 2>&1
echo "shot: tablet-768"

# هاتف 390×844
ab set viewport 390 844 > /dev/null 2>&1
ab open "http://127.0.0.1:$PORT/#/chat/1" > /dev/null 2>&1
ab wait --load networkidle > /dev/null 2>&1; ab wait 1500 > /dev/null 2>&1
ab screenshot $OUT/mobile-390-chat.png > /dev/null 2>&1
echo "shot: mobile-390"

# أخطاء وحدة التحكم
echo "=== console errors ==="
ab console 2>&1 | grep -iE "error|warn" | head -10 || echo "(none)"

kill $SRV 2>/dev/null
echo "BEFORE SESSION DONE"
