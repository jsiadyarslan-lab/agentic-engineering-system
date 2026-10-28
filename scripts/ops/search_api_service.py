#!/usr/bin/env python3
"""W2-T20: Search API — نقطة نهاية JSON يملكها المالك فوق SearXNG المحلي.

العقد (مطابق src/research/providers.ApiSearchProvider · style=generic_results):
- POST <endpoint> · جسم JSON {"query"/"q": str, "max_results": int<=10}
- ترويسات: X-API-Key أو Authorization: Bearer — يجب أن تطابق SEARCH_API_KEY
- الرد: {"query":..., "results":[{"title","url","snippet"}]}
- GET /healthz (بلا مفتاح): {"ok":true,"searx":"up|down"}
stdlib فقط — لا تبعيات.
"""
import json
import os
import re
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEARX = os.environ.get("SEARX_BASE_URL", "http://127.0.0.1:8888").rstrip("/")
KEY = os.environ.get("SEARCH_API_KEY", "")
PORT = int(os.environ.get("SEARCH_API_PORT", "8098"))
MAX_RESULTS = 10
UPSTREAM_TIMEOUT = 12.0
UA = "aes-search-api/1.0 (agentic research)"

#: (W2-T20) لغة الاستعلام من كتابته — عربي → ar (وإلا en): الصلب على
#: لغة واحدة كان يجلب نتائج لا تطابق رموز الاستعلام الآخر فترفضها
#: بوابة الصلة بصدق.
_ARABIC_SCRIPT_RE = re.compile(r"[\u0621-\u064a]")


def searx_search(query: str, max_results: int) -> list:
    language = "ar" if _ARABIC_SCRIPT_RE.search(query) else "en"
    url = SEARX + "/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "language": language})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    out = []
    for item in data.get("results", [])[:max_results]:
        title = str(item.get("title", "")).strip()
        link = str(item.get("url", ""))
        if title and link.startswith("http"):
            out.append({
                "title": title,
                "url": link,
                "snippet": str(item.get("content", ""))[:300],
            })
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "aes-search-api/1.0"

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not KEY:
            return False  # fail-closed: بلا مفتاح مضبوط = لا وصول إطلاقًا
        got = self.headers.get("X-API-Key", "")
        if not got:
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
        return got == KEY

    def do_GET(self):  # noqa: N802 — stdlib naming
        if self.path == "/healthz":
            up = False
            try:
                req = urllib.request.Request(SEARX + "/healthz", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    up = resp.status == 200
            except Exception:  # noqa: BLE001
                up = False
            return self._json(200, {"ok": True, "searx": "up" if up else "down"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            return self._json(401, {"error": "invalid or missing API key"})
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:  # noqa: BLE001
            return self._json(400, {"error": "invalid JSON body"})
        query = str(body.get("query") or body.get("q") or "").strip()
        if not query:
            return self._json(400, {"error": "missing 'query'/'q'"})
        try:
            n = int(body.get("max_results", 8) or 8)
        except (TypeError, ValueError):
            n = 8
        n = max(1, min(n, MAX_RESULTS))
        try:
            results = searx_search(query, n)
        except Exception as exc:  # noqa: BLE001
            return self._json(502, {"error": f"upstream searxng failed: {exc}"[:200]})
        return self._json(200, {"query": query, "results": results})

    def log_message(self, fmt, *args):  # noqa: A003
        print("[search-api] " + (fmt % args), flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[search-api] listening on 127.0.0.1:{PORT} -> {SEARX}", flush=True)
    server.serve_forever()
