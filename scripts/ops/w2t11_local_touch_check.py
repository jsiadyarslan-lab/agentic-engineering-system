# -*- coding: utf-8 -*-
"""W2-T11 — تحقق محلي سريع لكتلة pointer:coarse قبل النشر.

يخدم src/ui محليًا (ترجمة /static/*) ويقيس أهداف اللمس تحت محاكاة
الجوال — الأصداف الثابتة فقط (القوائم تفرغ بلا API) لكنه يثبت أن
كتلة اللمس تعمل وأن المنتقيات تكفي قبل لمس الإنتاج.
"""
from __future__ import annotations

import http.server
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

UI = Path("/home/z/my-project/repo/src/ui")
PORT = 18911


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        path = path.split("?", 1)[0]  # اجرّد سلسلة الاستعلام (?v=…)
        if path.startswith("/static/"):
            path = path[len("/static/"):]
        if path in ("/", "/index.html"):
            return str(UI / "index.html")
        if not path.startswith("/") and path != "":
            return str(UI / path)
        return str(UI / path.lstrip("/"))

    def log_message(self, *args):
        pass


def main() -> int:
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[static] http://127.0.0.1:{PORT}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        mob = browser.new_context(viewport={"width": 390, "height": 844},
                                  is_mobile=True, has_touch=True,
                                  device_scale_factor=2)
        page = mob.new_page()
        page.goto(f"http://127.0.0.1:{PORT}", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        coarse = page.evaluate("() => matchMedia('(pointer: coarse)').matches")
        print(f"[probe] pointer:coarse = {coarse}")
        res = page.evaluate("""
        () => {
          const out = {checked: 0, failures: []};
          const sel = 'button, a[href], input:not([type=hidden]), select, textarea';
          for (const el of document.querySelectorAll(sel)) {
            if (!(el.getClientRects().length)) continue;
            if (el.disabled) continue;
            const r = el.getBoundingClientRect();
            const w = Math.round(r.width), h = Math.round(r.height);
            out.checked++;
            if (w < 44 || h < 44) out.failures.push(
              el.tagName.toLowerCase() + (el.id ? '#'+el.id : '') +
              (el.classList.length ? '.'+[...el.classList].slice(0,2).join('.') : '') +
              ` ${w}x${h}`);
          }
          return out;
        }""")
        print(f"[touch local] {res['checked']} عنصرًا · {len(res['failures'])} دون 44px")
        for f in res["failures"]:
            print("   -", f)
        page.screenshot(path="/home/z/my-project/download/aes-remediation/W2-T11/shots_local/mobile_local.png")
        browser.close()
    srv.shutdown()
    return 0 if coarse else 1


if __name__ == "__main__":
    sys.exit(main())
