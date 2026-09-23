"""فحص دقيق: هل يبقى لوح المشروع معروضًا بعد الانتقال إلى محادثة (§M/§G)؟

السبب: اللقطة 03 أظهرت ``hash=#/chat/13`` بينما نص «اللوحة» كان لوح
المشروع — والسؤال الصادق: هل ذاك اللوح **مرئي** فعلًا (عطل تنقّل)،
أم أنه حاوية مخفية التقطها المحدِّد (قصور في أداة القياس)؟ الفرق
جوهري: الأول عطل في الواجهة، والثاني خطأ في الاستدلال.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

EDGE = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
BASE = "http://127.0.0.1:8010"
ROOT = Path(__file__).resolve().parents[1]
PORT = 9336

PROBE = r"""
(function(){
  var out = {hash: location.hash, body_class: document.body.className};
  function vis(sel){
    var e = document.querySelector(sel);
    if (!e) return null;
    var r = e.getBoundingClientRect();
    var cs = getComputedStyle(e);
    return {sel: sel, w: Math.round(r.width), h: Math.round(r.height),
            display: cs.display, visibility: cs.visibility,
            opacity: cs.opacity, visible: !!(r.width && r.height &&
            cs.display !== 'none' && cs.visibility !== 'hidden'),
            text: (e.innerText || '').slice(0, 120).replace(/\n+/g, ' / ')};
  }
  out.nodes = [
    vis('#project-view'), vis('.project-view'), vis('#project-panel'),
    vis('#chat-view'), vis('.chat-view'), vis('#chat-panel'),
    vis('#messages'), vis('.messages'), vis('#chat-messages')
  ].filter(Boolean);
  var body = document.body.innerText;
  out.has_react_answer = body.indexOf('مكتبة برمجية') >= 0;
  out.has_cloud_answer = body.indexOf('لا أستطيع أن أؤكد') >= 0;
  out.answer_index = body.indexOf('مكتبة برمجية');
  out.body_len = body.length;
  out.tail = body.slice(-700).replace(/\n{2,}/g, '\n');
  return out;
})()
"""


def edge() -> str:
    for path in EDGE:
        if Path(path).exists():
            return path
    raise SystemExit("no edge")


def ws_url() -> str:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/json/list", timeout=3) as r:
                for target in json.loads(r.read().decode("utf-8", "replace")):
                    if target.get("type") == "page" and \
                            target.get("webSocketDebuggerUrl"):
                        return target["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise SystemExit("no devtools")


async def main() -> int:
    import websockets

    url = ws_url()
    async with websockets.connect(url, max_size=50 * 1024 * 1024) as ws:
        counter = {"n": 0}

        async def send(method, **params):
            counter["n"] += 1
            mine = counter["n"]
            await ws.send(json.dumps({"id": mine, "method": method,
                                      "params": params}))
            while True:
                raw = json.loads(await ws.recv())
                if raw.get("id") == mine:
                    return raw.get("result", {})

        async def js(expr):
            res = await send("Runtime.evaluate", expression=expr,
                             returnByValue=True)
            return res.get("result", {}).get("value")

        await send("Page.enable")
        await send("Runtime.enable")
        await send("Emulation.setDeviceMetricsOverride", width=1600,
                   height=1200, deviceScaleFactor=1, mobile=False)

        report: dict = {}
        # 1) ادخل لوح مشروع
        await send("Page.navigate", url=f"{BASE}/#/project/24")
        await asyncio.sleep(9)
        report["at_project"] = await js(PROBE)
        # 2) انتقل إلى المحادثة عبر تغيير المسار (كما يفعل المستخدم)
        await js("location.hash = '#/chat/13'; true")
        await asyncio.sleep(8)
        report["after_hash_change"] = await js(PROBE)
        # 3) حمّل المحادثة تحميلًا كاملًا من الصفر
        await send("Page.navigate", url=f"{BASE}/#/chat/13")
        await asyncio.sleep(10)
        report["fresh_load_chat"] = await js(PROBE)
        # 4) إعادة تحميل أخرى على نفس المسار (§G)
        await send("Page.reload", ignoreCache=True)
        await asyncio.sleep(10)
        report["after_reload_chat"] = await js(PROBE)

    out = ROOT / "runtime" / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "order0135-navigation-probe.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    for name, data in report.items():
        print(f"== {name}: hash={data.get('hash')} "
              f"class={data.get('body_class')!r} len={data.get('body_len')}")
        print(f"   react_answer={data.get('has_react_answer')} "
              f"cloud_answer={data.get('has_cloud_answer')} "
              f"idx={data.get('answer_index')}")
        for node in data.get("nodes") or []:
            if node["visible"]:
                print(f"   VISIBLE {node['sel']}: {node['w']}x{node['h']} "
                      f"{node['text'][:90]}")
        hidden = [n["sel"] for n in (data.get("nodes") or [])
                  if not n["visible"]]
        print(f"   hidden: {hidden}")
    print(f"\nدليل: {path}")
    return 0


if __name__ == "__main__":
    profile = Path(os.environ.get("TEMP", ".")) / "dsh-edge-nav"
    shutil.rmtree(profile, ignore_errors=True)
    proc = subprocess.Popen(
        [edge(), "--headless=old", "--disable-gpu", "--disable-extensions",
         "--disable-sync", "--no-first-run", "--no-default-browser-check",
         "--hide-scrollbars", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={profile}", "--window-size=1600,1200", BASE + "/"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        sys.exit(asyncio.run(main()))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
