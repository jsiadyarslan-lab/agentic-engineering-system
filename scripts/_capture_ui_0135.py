"""لقطات الواجهة الحقيقية في مسار المستخدم (013.5 §G/§J/§R).

يشغّل Edge حقيقيًا (headless) عبر CDP ويلتقط:
1. المسار الحقيقي: مشروع حقيقي أثناء التوليد ← شرح الانتظار (§J).
2. المشروع بعد اكتمال الخطة ← حالة صادقة + خطة محفوظة.
3. محادثة فيها إجابة حقيقية بمصادر (§L).
4. نفس المحادثة **بعد إعادة تحميل الصفحة** ← الإجابة باقية (§G).
5. شاشة مزودي البحث ← ويكيبيديا READY بعد الفحص.

كل لقطة من محرك الرسم نفسه بعد تنفيذ JavaScript وانتظار الشبكة —
لا لقطة مركّبة ولا HTML مصطنع.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EDGE = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
BASE = "http://127.0.0.1:8010"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runtime" / "evidence" / "shots"
PORT = 9334


# ------------------------------------------------------------------ #
# HTTP مساعد
# ------------------------------------------------------------------ #

def api(method: str, path: str, body: dict | None = None, timeout: float = 60.0):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    request = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(
                response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")[:400]


def edge_path() -> str:
    for path in EDGE:
        if Path(path).exists():
            return path
    raise SystemExit("لم يُعثر على Edge")


def wait_devtools(timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/json/version", timeout=3
            ) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit("DevTools لم يستجب")


def page_ws() -> str:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{PORT}/json/list", timeout=5
    ) as response:
        targets = json.loads(response.read().decode("utf-8", "replace"))
    for target in targets:
        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
            return target["webSocketDebuggerUrl"]
    raise SystemExit("لا هدف صفحة")


class CDP:
    def __init__(self, ws) -> None:
        self.ws = ws
        self._id = 0

    async def send(self, method: str, **params):
        self._id += 1
        await self.ws.send(json.dumps(
            {"id": self._id, "method": method, "params": params}))
        while True:
            raw = json.loads(await self.ws.recv())
            if raw.get("id") == self._id:
                if "error" in raw:
                    raise RuntimeError(f"{method}: {raw['error']}")
                return raw.get("result", {})

    async def js(self, expression: str, await_promise: bool = False):
        result = await self.send(
            "Runtime.evaluate", expression=expression, returnByValue=True,
            awaitPromise=await_promise)
        return result.get("result", {}).get("value")

    async def goto(self, url: str, settle: float = 6.0) -> None:
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(settle)

    async def shot(self, name: str, note: str) -> dict:
        data = await self.send("Page.captureScreenshot", format="png",
                               captureBeyondViewport=True)
        blob = base64.b64decode(data["data"])
        path = OUT / f"{name}.png"
        path.write_bytes(blob)
        text = await self.js(
            "document.body.innerText.replace(/\\n{3,}/g,'\\n\\n').slice(0,1600)")
        # نص اللوحة الرئيسة وحدها — الشريط الجانبي يطغى على body.innerText
        panel = await self.js(
            "(function(){var s=['#project-view','.project-view',"
            "'#project-panel','.project-panel','#view-project','main',"
            "'#app-main','.main-content','.content'];"
            "for(var i=0;i<s.length;i++){var e=document.querySelector(s[i]);"
            "if(e&&e.innerText&&e.innerText.trim().length>60)return "
            "e.innerText.replace(/\\n{3,}/g,'\\n\\n').slice(0,1800)}"
            "return null})()")
        mode = await self.js(
            "document.body.className + ' | hash=' + location.hash")
        entry = {"name": name, "note": note, "file": path.name,
                 "bytes": len(blob), "mode": mode, "panel_text": panel,
                 "text_excerpt": text}
        print(f"  ✓ {name} ({len(blob)} بايت) — {note} [{mode}]", flush=True)
        if panel:
            print(f"     لوحة: {panel[:220]}", flush=True)
        return entry


# ------------------------------------------------------------------ #
# السيناريو
# ------------------------------------------------------------------ #

async def run(ws_url: str, evidence: dict) -> None:
    import websockets

    async with websockets.connect(ws_url, max_size=100 * 1024 * 1024) as ws:
        cdp = CDP(ws)
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        await cdp.send("Emulation.setDeviceMetricsOverride", width=1600,
                       height=1200, deviceScaleFactor=1, mobile=False)
        screens: list[dict] = []

        # ---- مشروع حقيقي: أنشئ وابدأ التوليد قبل فتح الصفحة ----
        status, project = api("POST", "/api/projects", {
            "name": "تحقق 013.5 §J — شرح الانتظار",
            "objective": "قياس شرح الانتظار في الواجهة أثناء توليد حقيقي",
        })
        project_id = (project or {}).get("id") or (project or {}).get("project_id")
        evidence["project_id"] = project_id
        evidence["project_create"] = {"http": status, "body": project}
        print(f"مشروع {project_id} أُنشئ (HTTP {status})", flush=True)
        status, started = api("POST",
                              f"/api/projects/{project_id}/plan/generate", {})
        evidence["plan_generate"] = {"http": status,
                                     "body": str(started)[:300]}
        print(f"توليد الخطة: HTTP {status}", flush=True)

        # ---- 1) أثناء التوليد: شرح الانتظار (§J) ----
        await cdp.goto(f"{BASE}/#/project/{project_id}", settle=6.0)
        # المسار وحده لا يكفي: افتح المشروع من الشريط الجانبي إن لم يُفتح
        opened = await cdp.js(
            "(function(){var h=location.hash;"
            "if(/^#\\/project\\/\\d+$/.test(h)&&"
            "document.body.classList.contains('mode-project'))return 'route';"
            "var items=[].slice.call(document.querySelectorAll("
            "'[data-project-id],.project-item,.project-card,a,button'));"
            "for(var i=0;i<items.length;i++){var t=(items[i].textContent||'');"
            "if(/شرح الانتظار/.test(t)){items[i].click();return 'clicked'}}"
            "return 'not-found'})()")
        evidence["project_open_mode"] = opened
        await asyncio.sleep(5.0)
        # انتظر حتى يظهر طور انتظار حقيقي (توليد فعلي، لا شاشة فاضية)
        phase = ""
        for _ in range(30):
            status, runtime = api("GET", f"/api/projects/{project_id}/runtime")
            planning = (runtime or {}).get("planning") or {}
            phase = str(planning.get("wait_phase") or "")
            if phase in ("REASONING", "GENERATING", "AWAITING_PROVIDER"):
                break
            await asyncio.sleep(2.0)
        evidence["wait_phase_observed"] = phase
        evidence["runtime_planning"] = {
            k: v for k, v in (planning or {}).items()
            if k in ("state", "wait_phase", "reasoning_chars", "silence_s",
                     "provider", "model", "owner_pid")}
        evidence["waiting_for"] = planning.get("waiting_for")
        wait_text = await cdp.js(
            "(function(){var m=document.body.innerText.match("
            "/[^\\n]*(انتظار|ننتظر|طور|توليد|تفكير|REASONING|GENERATING|"
            "AWAITING_PROVIDER)[^\\n]*/g);"
            "return m?m.slice(0,10).join(' | '):null})()")
        evidence["wait_text"] = wait_text
        screens.append(await cdp.shot(
            "01-project-planning-wait",
            f"أثناء توليد حقيقي — طور الانتظار المعروض: {phase}"))

        # ---- 2) بعد اكتمال الخطة ----
        final = ""
        for _ in range(90):
            status, proj = api("GET", f"/api/projects/{project_id}")
            final = str((proj or {}).get("status") or "")
            if final in ("AWAITING_OWNER_APPROVAL", "READY", "STOPPED",
                         "BLOCKED", "COMPLETED"):
                break
            await asyncio.sleep(3.0)
        evidence["project_final_status"] = final
        await cdp.goto(f"{BASE}/#/project/{project_id}", settle=8.0)
        await cdp.js(
            "(function(){if(document.body.classList.contains('mode-project'))"
            "return 'route';var items=[].slice.call(document.querySelectorAll("
            "'[data-project-id],.project-item,.project-card,a,button'));"
            "for(var i=0;i<items.length;i++){if(/شرح الانتظار/.test("
            "items[i].textContent||'')){items[i].click();return 'clicked'}}"
            "return 'not-found'})()")
        await asyncio.sleep(5.0)
        screens.append(await cdp.shot(
            "02-project-after-plan", f"بعد انتهاء التوليد — {final}"))
        # نفس اللقطة بعد إعادة تحميل كاملة — استمرار الحالة (§G للمشروع)
        await cdp.send("Page.reload", ignoreCache=True)
        await asyncio.sleep(12.0)
        await cdp.js(
            "(function(){if(document.body.classList.contains('mode-project'))"
            "return 'route';var items=[].slice.call(document.querySelectorAll("
            "'[data-project-id],.project-item,.project-card,a,button'));"
            "for(var i=0;i<items.length;i++){if(/شرح الانتظار/.test("
            "items[i].textContent||'')){items[i].click();return 'clicked'}}"
            "return 'not-found'})()")
        await asyncio.sleep(6.0)
        screens.append(await cdp.shot(
            "02b-project-after-reload",
            f"نفس المشروع بعد إعادة تحميل — {final}"))

        # ---- 3) محادثة فيها إجابة حقيقية بمصادر (§L) ----
        status, convs = api("GET", "/api/conversations")
        rows = convs if isinstance(convs, list) else convs.get("conversations", [])
        target = None
        for row in rows:
            cid = row.get("conversation_id")
            status, msgs = api("GET", f"/api/conversations/{cid}/messages")
            items = msgs if isinstance(msgs, list) else msgs.get("messages", [])
            if any((m.get("role") == "assistant" and len(m.get("content") or "") > 400)
                   for m in items):
                target = cid
                break
        evidence["chat_conversation_id"] = target
        if target:
            await cdp.goto(f"{BASE}/#/chat/{target}", settle=10.0)
            screens.append(await cdp.shot(
                "03-chat-answer-with-sources",
                "محادثة حقيقية بإجابة ومصادر"))
            # ---- 4) إعادة تحميل: الإجابة باقية (§G) ----
            before = await cdp.js(
                "document.body.innerText.length")
            await cdp.send("Page.reload", ignoreCache=True)
            await asyncio.sleep(10.0)
            after = await cdp.js("document.body.innerText.length")
            evidence["reload_text_len"] = {"before": before, "after": after}
            screens.append(await cdp.shot(
                "04-chat-after-reload",
                f"بعد إعادة تحميل الصفحة — نص {before} ← {after}"))

        # ---- 5) إعدادات البحث: مزودو البحث ----
        await cdp.goto(f"{BASE}/", settle=6.0)
        clicked = await cdp.js(
            "(function(){var b=[].slice.call(document.querySelectorAll("
            "'button,a')).filter(function(e){return /إعدادات|الإعدادات/.test("
            "e.textContent)});if(b[0]){b[0].click();return b[0].textContent}"
            "return null})()")
        evidence["settings_click"] = clicked
        await asyncio.sleep(4.0)
        scrolled = await cdp.js(
            "(function(){var t=[].slice.call(document.querySelectorAll('*'))"
            ".filter(function(e){return /ويكيبيديا|Wikipedia|مزودو البحث/.test("
            "e.textContent)&&e.children.length<12});"
            "if(t.length){t[t.length-1].scrollIntoView({block:'center'});"
            "return t[t.length-1].textContent.slice(0,300)}return null})()")
        evidence["providers_section"] = scrolled
        await asyncio.sleep(2.0)
        screens.append(await cdp.shot("05-research-providers",
                                      "مزودو البحث في الإعدادات"))
        evidence["screens"] = screens


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    profile = Path(os.environ.get("TEMP", ".")) / "dsh-edge-cdp2"
    shutil.rmtree(profile, ignore_errors=True)
    edge = edge_path()
    proc = subprocess.Popen(
        [edge, "--headless=old", "--disable-gpu", "--disable-extensions",
         "--disable-sync", "--no-first-run", "--no-default-browser-check",
         "--hide-scrollbars", f"--remote-debugging-port={PORT}",
         f"--user-data-dir={profile}", "--window-size=1600,1200", BASE + "/"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    evidence: dict = {"started_at": datetime.now(timezone.utc).isoformat(),
                      "engine": edge, "base": BASE}
    try:
        evidence["browser"] = wait_devtools().get("Browser")
        print(f"محرك: {evidence['browser']}", flush=True)
        asyncio.run(run(page_ws(), evidence))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    ok = [s for s in evidence.get("screens", []) if s["bytes"] > 10000]
    evidence["screens_captured"] = len(ok)
    evidence["all_screens_rendered"] = (
        len(ok) == len(evidence.get("screens", [])) and bool(ok))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "runtime" / "evidence" / f"order0135-r-screens-{stamp}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"\nلقطات: {len(ok)} | كلها مرسومة="
          f"{evidence['all_screens_rendered']}")
    print(f"دليل: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
