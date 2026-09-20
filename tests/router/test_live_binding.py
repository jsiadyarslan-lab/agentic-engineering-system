"""اختبارات الربط الحي (الأمر السادس §1.7) — خادم وهمي محلي حقيقي.

الخادم خادم HTTP حقيقي (http.server) يحاكي واجهة OpenAI — الاستدعاء
يمر بالنقل الحقيقي urllib وطبقات الحماية الثلاث كاملة؛ الوهمية في
الاستجابة فقط، لا في المسار (اختبار مسار حي صادق).

ثلاثة اختبارات:
1. live_chat_mock_server — استدعاء حي ناجح عبر خادم محلي.
2. failover_on_503_live — 503 مرتين ثم نجاح العضو التالي بالسلسلة.
3. cooling_on_429_live — 429 ثم نجاح بعد تبريد واحد (Retry-After: 0).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from router.cooling_loop import CoolingLoop
from router.failover_chain import FailoverChain
from router.model_router import (
    ChatMessage,
    ModelRouter,
    live_transport,
)
from router.rate_limiter import RateLimiter


def _openai_body(content: str) -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-test",
            "model": "test-model",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}}
            ],
        }
    ).encode("utf-8")


class _ScriptedHandler(BaseHTTPRequestHandler):
    """خادم بنص برمجي للاستجابات — قائمة استجابات تُستهلك بالترتيب.

    كل استجابة: (status, headers, body) — والخادم يسجل كل طلب استقبله.
    """

    script: list[tuple[int, dict, bytes]] = []
    received: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 — توقيع http.server
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization", ""),
                "payload": payload,
            }
        )
        if not type(self).script:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"script exhausted")
            return
        status, headers, body = type(self).script.pop(0)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # إسكات سجل الاختبار
        pass


@pytest.fixture()
def scripted_server():
    """خادم محلي بنص برمجي — يعيد (host_url, script, received)."""

    def start(script: list[tuple[int, dict, bytes]]):
        _ScriptedHandler.script = list(script)
        _ScriptedHandler.received = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ScriptedHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", (
            lambda: list(_ScriptedHandler.script)
        ), (lambda: list(_ScriptedHandler.received))
        server.shutdown()
        server.server_close()

    return start


def _fast_router(base_urls: dict[str, str], chain: list[str],
                 events: list | None = None) -> ModelRouter:
    """موجّه حي لأغراض الاختبار — حدود صفرية وأزمنة لحظية.

    أحداث الحزم (تبريد/تبدّل) تُوصل بمخرج واحد كما يفعل build_live —
    توصيل الأحداث مسؤولية الباني لا الموجّه.
    """
    on_event = events.append if events is not None else None
    transports = {
        name: live_transport(
            {"base_url": url, "api_key": "test-key", "model": "test-model",
             "timeout": 10}
        )
        for name, url in base_urls.items()
    }
    router = ModelRouter(
        rate_limiter=RateLimiter(
            {"rpm": 0, "min_interval": 0.0, "cooldown": 0.05, "concurrency": 1}
        ),
        failover_chain=FailoverChain(
            chain, {"max_retries": 2, "backoff_base": 0.01},
            on_event=on_event,
        ),
        cooling_loop=CoolingLoop(
            {"cooldown_base": 0.05, "cooldown_max": 0.1, "max_waits": 3,
             "budget_seconds": 5},
            on_event=on_event,
        ),
        default_provider=chain[0],
        transports=transports,
        on_event=on_event,
    )
    router._live_default_model = "test-model"
    return router


def test_live_chat_mock_server(scripted_server):
    """استدعاء حي ناجح — المسار كامل: حد معدل ← تبريد ← نقل urllib."""
    for base_url, _left, received in scripted_server(
        [(200, {}, _openai_body('{"ok": true, "word": "سلام"}'))]
    ):
        router = _fast_router({"local": base_url}, ["local"])
        result = router.chat_live(
            [ChatMessage(role="user", content="أعد JSON فقط: {\"ok\": true}")]
        )
        assert result["text"] == '{"ok": true, "word": "سلام"}'
        assert result["provider"] == "local"
        assert result["failed_over"] is False
        # الطلب وصل فعليًا بالترويسة والجسم الصحيحين
        assert len(received()) == 1
        request = received()[0]
        assert request["path"] == "/v1/chat/completions"
        assert request["auth"] == "Bearer test-key"
        assert request["payload"]["model"] == "test-model"
        assert request["payload"]["messages"][0]["role"] == "user"


def test_failover_on_503_live(scripted_server):
    """503 مرتين (إعادتان داخليتان) ثم فشل العضو والتبدّل للثاني."""
    for base_url, _left, received in scripted_server(
        [
            (503, {}, b'{"error": "overloaded"}'),
            (503, {}, b'{"error": "overloaded"}'),
            (503, {}, b'{"error": "overloaded"}'),
            (200, {}, _openai_body("from-backup")),
        ]
    ):
        events: list[dict] = []
        router = _fast_router(
            {"primary": base_url, "backup": base_url},
            ["primary", "backup"],
            events,
        )
        result = router.chat_live(
            [ChatMessage(role="user", content="سلام")]
        )
        assert result["text"] == "from-backup"
        assert result["provider"] == "backup"
        assert result["failed_over"] is True
        assert result["failover_from"] == "primary"
        # أربعة طلبات فعلية على السلك: 3 محاولات الأساس (1+2 إعادة)
        # ثم نجاح الاحتياطي من محاولته الأولى
        assert len(received()) == 4
        kinds = [e["kind"] for e in events]
        assert "failover.logged" in kinds
        assert "router.call.logged" in kinds


def test_cooling_on_429_live(scripted_server):
    """429 مع Retry-After: 0 ← تبريد واحد ← نجاح بنفس المزود."""
    for base_url, _left, received in scripted_server(
        [
            (429, {"Retry-After": "0"}, b'{"error": "rate limited"}'),
            (200, {}, _openai_body("after-cooling")),
        ]
    ):
        events: list[dict] = []
        router = _fast_router(
            {"throttled": base_url}, ["throttled"], events
        )
        result = router.chat_live(
            [ChatMessage(role="user", content="سلام")]
        )
        assert result["text"] == "after-cooling"
        assert result["cooled"] is True
        assert result["cooling_waits"] == 1
        kinds = [e["kind"] for e in events]
        assert "cooling.cooldown" in kinds
