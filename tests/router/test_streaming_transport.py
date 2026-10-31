"""اختبارات النقل المتدفق (الأمر 008 §3) — فك أسطر SSE الحقيقية.

المزود الداخلي z.ai يرفض stream:true حاليًا (429 موثق)، لذا يُثبت
النقل هنا بمصدر SSE مضبوط بالبنية الحرفية لمزودات OpenAI-compatible
(نفس ما يعيده NVIDIA/OpenRouter) — المسار نفسه، المصدر معلن. مسار
التراجع الصادق (نقل كامل معلن) مثبت حيًا في المتصفح واختبارات API.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from router.model_router import ChatMessage, ProviderCallError
from router.streaming import stream_completion


def _sse(frames: list[str]) -> list[bytes]:
    return [frame.encode("utf-8") for frame in frames]


def _install_sse(monkeypatch, chunks: list[bytes], status: int = 200):
    """تثبيت استجابة SSE مضبوطة على urlopen — بنية OpenAI الحرفية."""
    import router.streaming as streaming_mod

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body
            self.status = status

        def __iter__(self):
            return iter(self._body.splitlines(keepends=True))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    body = b"".join(chunks)

    def fake_urlopen(request, timeout=None):
        return FakeResponse(body)

    monkeypatch.setattr(streaming_mod.urllib.request, "urlopen", fake_urlopen)


CFG = {
    "base_url": "https://stub.example/v1",
    "api_key": "k-test",
    "model": "stub-model",
    "max_tokens": 100,
}


def test_stream_completion_yields_real_deltas(monkeypatch):
    """قطع فعلية تصل لحظة وصولها — التجميع = النص الكامل (§3)."""
    _install_sse(monkeypatch, _sse([
        'data: {"choices":[{"delta":{"content":"بناء "}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"منصة "}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"OSINT"}}]}\n\n',
        "data: [DONE]\n\n",
    ]))
    pieces: list[str] = []
    text = stream_completion(CFG, "stub-model", [
        ChatMessage(role="user", content="اكتب")], on_delta=pieces.append)
    assert pieces == ["بناء ", "منصة ", "OSINT"]
    assert text == "بناء منصة OSINT"


def test_stream_completion_skips_empty_and_done_frames(monkeypatch):
    _install_sse(monkeypatch, _sse([
        'data: {"choices":[{"delta":{}}]}\n\n',           # delta فارغ
        'data: {"choices":[]}\n\n',                        # بلا choices
        ": keep-alive\n\n",                                # تعليق SSE
        'data: not-json\n\n',                              # سطر تالف يتخطى
        'data: {"choices":[{"delta":{"content":"نص"}}]}\n\n',
        "data: [DONE]\n\n",
    ]))
    text = stream_completion(CFG, "stub-model", [
        ChatMessage(role="user", content="x")], on_delta=lambda d: None)
    assert text == "نص"


def test_stream_completion_empty_is_explicit_failure(monkeypatch):
    """رد متدفق فارغ = فشل صريح — لا نجاح بلا مادة (نفس مبدأ live)."""
    _install_sse(monkeypatch, _sse(["data: [DONE]\n\n"]))
    with pytest.raises(ProviderCallError):
        stream_completion(CFG, "stub-model", [
            ChatMessage(role="user", content="x")], on_delta=lambda d: None)


def test_stream_completion_classifies_http_errors(monkeypatch):
    """تصنيف أخطاء النقل المتدفق — 429 اختناق/4xx عميل (نفس العقد)."""
    import router.streaming as streaming_mod

    def raise_429(request, timeout=None):
        error = urllib.error.HTTPError(
            request.full_url, 429, "Too Many Requests",
            {"Retry-After": "2"}, None)
        error.read = lambda: b'{"error":"rate"}'
        raise error

    monkeypatch.setattr(
        streaming_mod.urllib.request, "urlopen", raise_429)
    with pytest.raises(ProviderCallError) as caught:
        stream_completion(CFG, "stub-model", [
            ChatMessage(role="user", content="x")], on_delta=lambda d: None)
    assert caught.value.is_throttle is True


def test_streaming_transport_sends_stream_true(monkeypatch):
    """الطلب الفعلي يحمل stream:true — البث حقيقي لا مزعوم."""
    import router.streaming as streaming_mod

    seen = {}

    class FakeResponse:
        status = 200

        def __iter__(self):
            return iter([
                'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'.encode("utf-8"),
                b"data: [DONE]\n\n",
            ])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        seen["body"] = request.data.decode("utf-8")
        seen["headers"] = dict(request.header_items())
        return FakeResponse()

    monkeypatch.setattr(
        streaming_mod.urllib.request, "urlopen", fake_urlopen)
    stream_completion(CFG, "stub-model", [
        ChatMessage(role="user", content="x")], on_delta=lambda d: None)
    import json

    body = json.loads(seen["body"])
    assert body["stream"] is True
    assert body["model"] == "stub-model"
    assert body["max_tokens"] == 100


def _install_ticking_sse(monkeypatch, frames: list[str], step_s: float):
    """SSE بساعة زمنية مضبوطة: كل سطر يُقدّم الساعة step_s ثانية.

    (W2-T25 §D2) يثبت مهلة الصمت الحقيقي: الإطارات تجيء (إبقاء حياة)
    والساعة تجري — والمخرجات الفعلية وحدها تمدّد ساعة النشاط.
    """
    import router.streaming as streaming_mod

    clock = {"now": 1000.0}

    def fake_monotonic():
        return clock["now"]

    monkeypatch.setattr(streaming_mod.time, "monotonic", fake_monotonic)

    class TickingResponse:
        status = 200

        def __init__(self, body_frames: list[str]):
            self._frames = body_frames

        def __iter__(self):
            for frame in self._frames:
                clock["now"] += step_s
                yield frame.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        return TickingResponse(frames)

    monkeypatch.setattr(streaming_mod.urllib.request, "urlopen", fake_urlopen)


IDLE_CFG = {**CFG, "stream_idle_timeout": 240}


def test_stream_idle_timeout_aborts_silent_keepalive_stream(monkeypatch):
    """إبقاء حياة بلا مخرجات يخدع مهلة المقبس — حارس الصمت يُحبط صادقًا.

    القياس الحي 2026-10-31 16:27–16:44Z: تجمّد مزود 17 دقيقة بلا محتوى
    ولا استدلال بينما إطارات الإبقاء تصل فتُبقي المقبس حيًا — الحلقة
    تجمّدت داخل النداء فتعذّر التقاط إعادة الطابور. الآن: 3 دقائق صمت
    فأبعد = ProviderCallError مصنّف مهلة بلا تجميد.
    """
    _install_ticking_sse(monkeypatch, [
        ": keep-alive\n\n",
        ": keep-alive\n\n",
        ": keep-alive\n\n",   # هنا الساعة تجاوزت 240ث من آخر مخرج
        'data: {"choices":[{"delta":{"content":"متأخر"}}]}\n\n',
        "data: [DONE]\n\n",
    ], step_s=100.0)
    with pytest.raises(ProviderCallError) as caught:
        stream_completion(IDLE_CFG, "stub-model", [
            ChatMessage(role="user", content="x")], on_delta=lambda d: None)
    assert caught.value.is_timeout is True
    assert "STREAM_IDLE_TIMEOUT" in str(caught.value)


def test_stream_reasoning_activity_extends_idle_clock(monkeypatch):
    """الاستدلال الحيّ نشاط حقيقي يمدّد الساعة — لا إحباط كاذب (§D+§D2).

    فجوات الاستدلال 100ث (< السقف 240ث) تنعش الساعة مع كل دلتا،
    والصمت الكلي لا يتجاوز السقف أبدًا حتى اكتمال المحتوى.
    """
    _install_ticking_sse(monkeypatch, [
        'data: {"choices":[{"delta":{"reasoning_content":"تفكير"}}]}\n\n',
        ": keep-alive\n\n",
        'data: {"choices":[{"delta":{"reasoning_content":"مزيد"}}]}\n\n',
        ": keep-alive\n\n",
        'data: {"choices":[{"delta":{"content":"جواب"}}]}\n\n',
        "data: [DONE]\n\n",
    ], step_s=100.0)
    text = stream_completion(IDLE_CFG, "stub-model", [
        ChatMessage(role="user", content="x")], on_delta=lambda d: None)
    assert text == "جواب"


def test_stream_idle_zero_disables_guard(monkeypatch):
    """stream_idle_timeout=0 يعطل الحارس صراحة — العقد القديم كما هو."""
    _install_ticking_sse(monkeypatch, [
        ": keep-alive\n\n",
        ": keep-alive\n\n",
        ": keep-alive\n\n",
        ": keep-alive\n\n",
        'data: {"choices":[{"delta":{"content":"نص"}}]}\n\n',
        "data: [DONE]\n\n",
    ], step_s=100.0)
    off_cfg = {**CFG, "stream_idle_timeout": 0}
    text = stream_completion(off_cfg, "stub-model", [
        ChatMessage(role="user", content="x")], on_delta=lambda d: None)
    assert text == "نص"
