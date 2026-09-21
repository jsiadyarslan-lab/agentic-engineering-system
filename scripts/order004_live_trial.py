"""المهمة الحية التجريبية للأمر التنفيذي 004 — الإيقاف الفوري والاستئناف.

الجزء A (إيقاف حي): مهمة حية كاملة عبر zai_internal/glm-4.6 — عند أول
استدعاء أداة فعلي داخل المنفذ الحي يُطلب الإيقاف، ويُقاس زمن التكريم
(طلب → cycle.stopped)، ثم فحص اللقطة والحكم STOPPED والأدلة الجزئية.

الجزء B (استئناف حي): استئناف المهمة من اللقطة — دورة جديدة تُحقن
بالخطة الموقّعة (تخطي التفكير والمراجعة) وتكمل حتى الحكم النهائي.

تشغيل: ‎.venv/bin/python scripts/order004_live_trial.py [--a-only|--b-only]
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from core.stop_controller import StopController, snapshot_summary  # noqa: E402
from missions import run_mission  # noqa: E402

MISSION_DIR = REPO / "runtime" / "missions" / "order004_trial"
STREAM_LOG = MISSION_DIR.parent / "order004_stream.log"

GOAL = (
    "تقرير من صفحة واحدة عن التضخم وأسعار الفائدة في الاقتصادات "
    "الكبرى، من 5-8 مصادر موثقة تشمل بيانات رسمية من FRED والبنك "
    "الدولي، عربي RTL، PDF بحجم A4"
)

#: مهلة انتظار بلوغ مرحلة التنفيذ (ثوان) — بعدها فشل صريح معلن.
EXEC_PHASE_TIMEOUT_S = 480.0
#: مهلة اكتمال الجزء كله.
JOIN_TIMEOUT_S = 900.0


def _build_router():
    from core.config import LiveModelConfig
    from router.model_router import ModelRouter

    live_cfg = LiveModelConfig(
        default_provider="zai_internal", default_model="glm-4.6"
    )
    return ModelRouter.build_live(live_cfg)


def _log(event: dict) -> None:
    line = json.dumps(event, ensure_ascii=False)[:260]
    with STREAM_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def part_a() -> dict:
    print("=" * 62)
    print("الجزء A — إيقاف حي لمهمة حية أثناء أدوات المنفذ (glm-4.6)")
    print("=" * 62)
    MISSION_DIR.mkdir(parents=True, exist_ok=True)
    router = _build_router()
    stop = StopController()
    events: list[dict] = []
    state = {"tool_seen": False, "stop_requested_at": None,
             "stopped_at": None, "res": None}

    def on_event(event: dict) -> None:
        events.append(event)
        _log(event)
        kind = event.get("kind", "")
        if kind == "tool.call" and not state["tool_seen"]:
            state["tool_seen"] = True
            print(f"  ✓ أول استدعاء أداة حي: {event.get('tool')} — "
                  f"طلب الإيقاف الآن")
            state["stop_requested_at"] = time.monotonic()
            stop.request_stop(
                "order004-stop", by="owner",
                reason="إثبات حي للأمر 004 — إيقاف أثناء الأدوات",
            )
        if kind == "cycle.stopped":
            state["stopped_at"] = time.monotonic()

    def run() -> None:
        state["res"] = run_mission(
            GOAL,
            router=router,
            mission_dir=MISSION_DIR,
            on_event=on_event,
            cycle_id="order004-stop",
            stop_controller=stop,
        )

    thread = threading.Thread(target=run)
    started = time.monotonic()
    thread.start()

    deadline = time.monotonic() + EXEC_PHASE_TIMEOUT_S
    while time.monotonic() < deadline and state["res"] is None:
        time.sleep(0.5)
        if state["tool_seen"]:
            break
    if not state["tool_seen"] and state["res"] is None:
        print("  ✗ لم تبلغ المهمة مرحلة الأدوات خلال المهلة — فشل صريح")
        stop.request_stop("order004-stop", by="owner", reason="مهلة")
    thread.join(timeout=JOIN_TIMEOUT_S)
    if thread.is_alive():
        print("  ✗ الخيط لم ينته — إخفاق الإيقاف (هذا عيب إن حدث)")
        return {"ok": False, "reason": "thread_alive"}

    result = state["res"]
    latency_ms = (
        int((state["stopped_at"] - state["stop_requested_at"]) * 1000)
        if state["stopped_at"] and state["stop_requested_at"]
        else None
    )
    print(f"  الحكم: {result.verdict} — {result.reason[:140]}")
    print(f"  الحالة النهائية: {result.final_state}")
    print(f"  زمن التكريم (طلب → cycle.stopped): {latency_ms}ms")
    snapshot_path = MISSION_DIR / "stop_snapshot.json"
    print(f"  اللقطة: {snapshot_path.is_file()}")
    if snapshot_path.is_file():
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        summary = snapshot_summary(snapshot)
        print(f"    {json.dumps(summary, ensure_ascii=False)[:200]}")
    evidence = json.loads(
        Path(result.evidence_path).read_text(encoding="utf-8")
    )
    stop_block = evidence.get("stop") or {}
    print(f"  الأدلة: verdict={evidence['verdict']} "
          f"stopped_by={stop_block.get('stopped_by')} "
          f"phase={stop_block.get('phase')}")
    print(f"  أدلة جزئية (ملفات): {len(evidence.get('files', {}))}")
    print(f"  أحداث الأدوات قبل الإيقاف: "
          f"{len(evidence.get('tool_calls', []))}")
    ok = (
        result.verdict == "STOPPED"
        and result.final_state == "STOPPED"
        and snapshot_path.is_file()
        and stop_block.get("stopped_by") == "owner"
    )
    print(f"  PART A VERDICT: {'PASS' if ok else 'HARD STOP'}")
    return {"ok": ok, "result": result,
            "latency_ms": latency_ms, "events": len(events)}


def part_b() -> dict:
    print("=" * 62)
    print("الجزء B — استئناف حي من اللقطة (دورة جديدة محقونة بالخطة)")
    print("=" * 62)
    snapshot_path = MISSION_DIR / "stop_snapshot.json"
    if not snapshot_path.is_file():
        print("  ✗ لا لقطة — شغّل الجزء A أولًا")
        return {"ok": False}
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    router = _build_router()
    events: list[dict] = []
    resumed_seen = {"v": False}
    thinker_calls = {"n": 0}

    def on_event(event: dict) -> None:
        events.append(event)
        _log(event)
        if event.get("kind") == "cycle.resumed" and not resumed_seen["v"]:
            resumed_seen["v"] = True
            d = event.get("details", {})
            print(f"  ✓ cycle.resumed: من {d.get('from_cycle_id')} — "
                  f"مهام مزروعة: {d.get('seeded_outcomes')}")
        if event.get("kind") == "plan" and event.get("role") == "thinker":
            thinker_calls["n"] += 1

    started = time.monotonic()
    result = run_mission(
        router=router,
        mission_dir=MISSION_DIR,
        on_event=on_event,
        cycle_id="order004-resume",
        stop_controller=StopController(),
        resume_from=snapshot,
    )
    duration = int(time.monotonic() - started)
    print(f"  الحكم: {result.verdict} — {result.reason[:140]}")
    print(f"  الحالة النهائية: {result.final_state}")
    print(f"  PDF: {result.pdf_path} (صفحات: {result.pdf_pages})")
    print(f"  المصادر: {len(result.sources)}")
    print(f"  المدة: {duration}s")
    print(f"  cycle.resumed مرئي: {resumed_seen['v']} | "
          f"استدعاءات مفكر (يجب 0): {thinker_calls['n']}")
    evidence = json.loads(
        Path(result.evidence_path).read_text(encoding="utf-8")
    )
    print(f"  resumed_from في الأدلة: {evidence.get('resumed_from')}")
    print(f"  EVIDENCE_SHA256: {result.evidence_sha256}")
    ok = (
        result.verdict == "PASS"
        and resumed_seen["v"]
        and thinker_calls["n"] == 0
    )
    print(f"  PART B VERDICT: {'PASS' if ok else 'HARD STOP'}")
    return {"ok": ok, "result": result}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--all"
    if mode in ("--all", "--a-only"):
        part_a()
    if mode in ("--all", "--b-only"):
        part_b()
