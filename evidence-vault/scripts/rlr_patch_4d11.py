#!/usr/bin/env python3
"""RLR-001 §4d-11 hotfix — browser actor self-deadlock (surgical patch).

Root cause (py-spy evidence, 2026-10-26 06:26):
  Thread aes-workflow-run_0: result() at browser/provider.py:60
  Thread aes-browser-actor_0: result() at browser/provider.py:60 (inside a task)
  => a browser_threaded-decorated call made FROM the actor thread itself
     re-submits to the SAME single-worker executor and waits forever.

Fix: calls arriving ON the actor thread execute inline (same thread keeps
Playwright ownership — the actor's entire purpose), and the outer wait
gets a 240s safety timeout (below the 300s heartbeat staleness threshold).
"""
import py_compile
import shutil
import sys
import time

PATH = "/opt/aes-vis/src/browser/provider.py"
BAK = f"{PATH}.bak-rlr4d11-{time.strftime('%H%M%S')}"

OLD = '''def _on_browser_thread(fn, *args, **kwargs):
    """تنفيذ دالة متصفح على خيط الممثل الوحيد — بلا مهلة إضافية
    (المهل تحكمها سياسة الجلسة نفسها).

    (RLR-001 §4d-7) السياق يُعزل عن المستدعي: الممثل ينسخ contextvars
    المستدعي — ومن داخل مهمة asyncio ينسخ معها أثر sniffio/asyncio
    فيرفض Playwright Sync العمل ("inside the asyncio loop") رغم أن
    الخيط الممثل بلا حلقة. الحل: سياق فارغ يُنشأ على خيط الممثل
    نفسه (بلا أي متغيرات موروثة) تُنفَّذ داخله الدالة.
    """
    def _isolated():
        return _cv.Context().run(fn, *args, **kwargs)

    return _BROWSER_ACTOR.submit(_isolated).result()'''

NEW = '''def _on_browser_thread(fn, *args, **kwargs):
    """تنفيذ دالة متصفح على خيط الممثل الوحيد.

    (RLR-001 §4d-7) السياق يُعزل عن المستدعي: الممثل ينسخ contextvars
    المستدعي — ومن داخل مهمة asyncio ينسخ معها أثر sniffio/asyncio
    فيرفض Playwright Sync العمل ("inside the asyncio loop") رغم أن
    الخيط الممثل بلا حلقة. الحل: سياق فارغ يُنشأ على خيط الممثل
    نفسه (بلا أي متغيرات موروثة) تُنفَّذ داخله الدالة.

    (RLR-001 §4d-11 hotfix 2026-10-26 — جلسة الاستئناف): النداء الوارد
    من خيط الممثل نفسه كان يُعيد التسليم إلى المنفّذ الأحادي ثم ينتظر
    نتيجته — مهمة على الخيط تنتظر مهمة على نفس الخيط = جمود أبديّ
    (أثبته py-spy: خيطا aes-workflow-run_0 و aes-browser-actor_0
    محبوسان في result() هنا بعد دفعة تنقلات متوازية + تنظيف الجلسة).
    الآن: النداء من خيط الممثل يُنفَّذ مباشرة — نفس الخيط يعني نفس
    ملكية Playwright فيبقى عقد الممثل محفوظًا — والانتظار الخارجي
    بمهلة 240ث صمام أمان تحت عتبة نبض الوظيفة (300ث) فلا يتجوّع
    العامل أبدًا بصمت.
    """
    def _isolated():
        return _cv.Context().run(fn, *args, **kwargs)

    if threading.current_thread().name.startswith("aes-browser-actor"):
        return _isolated()
    return _BROWSER_ACTOR.submit(_isolated).result(timeout=240)'''

with open(PATH, encoding="utf-8") as fh:
    src = fh.read()

if OLD not in src:
    print("ABORT: original block not found verbatim — file changed?")
    sys.exit(1)
if NEW.splitlines()[10] in src:
    print("ABORT: hotfix already applied")
    sys.exit(0)

shutil.copy2(PATH, BAK)
patched = src.replace(OLD, NEW, 1)

# ensure threading import exists
if "\nimport threading" not in patched:
    patched = patched.replace(
        "import concurrent.futures as _cf",
        "import concurrent.futures as _cf\nimport threading",
        1,
    )

with open(PATH, "w", encoding="utf-8") as fh:
    fh.write(patched)

py_compile.compile(PATH, doraise=True)
print("PATCHED + COMPILED OK")
print("backup:", BAK)

# show the applied diff context
import difflib
diff = list(difflib.unified_diff(
    src.splitlines(), patched.splitlines(),
    fromfile="provider.py (before)", tofile="provider.py (after)", lineterm=""))
print("\n".join(diff[:40]))
