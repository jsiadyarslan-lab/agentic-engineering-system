"""SSE keepalive is transport-only and never claims a completed model answer."""
import asyncio
import json

from api import streaming


def test_idle_stream_emits_comment_without_persisting_fake_events(monkeypatch):
    written = []
    monkeypatch.setattr(streaming.BUS, "subscribe", lambda *_args: 5)
    monkeypatch.setattr(streaming.BUS, "unsubscribe", lambda sub: written.append(sub))
    monkeypatch.setattr(streaming, "load_events_after", lambda *_args: [])
    clock = {"t": 0.0}
    def fast_clock():
        clock["t"] += 16.0
        return clock["t"]
    monkeypatch.setattr(streaming, "_sse_now", fast_clock)
    async def no_event(coro, *, timeout):
        coro.close()
        raise asyncio.TimeoutError()
    monkeypatch.setattr(streaming.asyncio, "wait_for", no_event)
    active = iter([True, False])
    async def collect():
        result = []
        async for block in streaming.live_stream(
            None, "chat-51", is_running=lambda: next(active),
        ):
            result.append(block)
        return result
    output = asyncio.run(collect())
    assert output[0] == ": keepalive\n\n"
    assert output[0].startswith(":")
    assert len(output) == 2
    last = json.loads(output[1].removeprefix("data: "))
    assert last["kind"] == "stream.done"
    assert written == [5]
