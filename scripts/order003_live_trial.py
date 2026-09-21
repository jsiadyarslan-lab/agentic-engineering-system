"""المهمة الحية التجريبية للأمر التنفيذي 003 — أدوات البيانات وسجل المصادر.

الجزء A (معيار القبول): جلب 3-5 مصادر رسمية حقيقية من السجل عبر
run_tool — المسار الإنتاجي نفسه (قائمة بيضاء + توثيق sha256 + نمط
معلن)، والأدلة في runtime/missions/order003_trial/.

الجزء B (إثبات إضافي): مهمة حية كاملة بالأدوار الخمسة عبر zai_internal
بهدف بيانات اقتصادية — المصادر الرسمية المقترحة تُحقن في خطة الأدوات.

تشغيل: ‎.venv/bin/python scripts/order003_live_trial.py [--b-only|--a-only]
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from roles.tools import ToolContext, ToolError, run_tool  # noqa: E402
from sources import load_sources  # noqa: E402

TRIAL_DIR = REPO / "runtime" / "missions" / "order003_trial"
MISSION_DIR = REPO / "runtime" / "missions" / "order003"

#: خمسة مصادر رسمية متنوعة الأدوات (معرفات من السجل).
TRIAL_PLAN = [
    ("fed_h15", "fred_csv",
     {"series_id": "DGS10", "start": "2024-01-01"}),
    ("wb_cpi", "worldbank_indicator",
     {"indicator": "FP.CPI.TOTL.ZG", "countries": "SA;US;DE;CN",
      "dates": "2022:2024"}),
    ("ecb_exr_usd", "http_get_text", {}),
    ("boj_stat", "page_to_text", {}),
    ("cbu_rates", "http_get_json", {}),
]


def part_a() -> dict:
    """جلب حي لخمسة مصادر رسمية — الأدلة والحكم الصادق."""
    print("=" * 62)
    print("الجزء A — جلب حي لخمسة مصادر رسمية من السجل")
    print("=" * 62)
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    ctx = ToolContext(grant_root=TRIAL_DIR, on_event=events.append)
    registry = {s["id"]: s for s in load_sources()}
    calls: list[dict] = []
    failures: list[dict] = []
    for source_id, tool, extra_args in TRIAL_PLAN:
        source = registry[source_id]
        args = {"url": source["url"], **extra_args}
        started = time.monotonic()
        try:
            value = run_tool(tool, args, ctx)
            duration = int((time.monotonic() - started) * 1000)
            calls.append({
                "source_id": source_id,
                "tool": tool,
                "ok": True,
                "duration_ms": duration,
                "sha256": value["sha256"],
                "summary": {
                    k: value.get(k) for k in
                    ("rows", "chars", "words", "count", "series_id",
                     "indicator", "artifact", "artifacts")
                    if k in value
                },
            })
            print(f"  ✓ {source_id} ({tool}) — {duration}ms")
        except ToolError as error:
            failures.append({"source_id": source_id, "tool": tool,
                             "error": str(error)[:300]})
            print(f"  ✗ {source_id} ({tool}) — {str(error)[:120]}")
    evidence = {
        "order": "003 — الجزء A: جلب حي لمصادر السجل",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "plan": [
            {"source_id": sid, "tool": tool, "args": args}
            for sid, tool, args in
            [(s, t, {"url": registry[s]["url"], **x}) for s, t, x in TRIAL_PLAN]
        ],
        "ok_count": len(calls),
        "failed": failures,
        "tool_calls": [e for e in events if e.get("kind") == "tool.call"],
        "files": {
            p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                     "bytes": p.stat().st_size}
            for p in sorted(TRIAL_DIR.rglob("*"))
            if p.is_file() and p.name != "evidence.json"
        },
    }
    #: الحكم الصادق: PASS إذا نجح 3 من 5 على الأقل (المعيار) بلا صمت.
    reasons = []
    if len(calls) < 3:
        reasons.append(f"نجح {len(calls)}/5 فقط — دون حد القبول 3")
    evidence["verdict"] = "PASS" if not reasons else "HARD STOP"
    evidence["verdict_reasons"] = reasons
    path = TRIAL_DIR / "evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"  الأدلة: {path}")
    print(f"  الحكم: {evidence['verdict']} ({len(calls)}/5 مصادر)")
    return evidence


def part_b() -> None:
    """مهمة حية كاملة عبر zai_internal — هدف بيانات اقتصادية."""
    print("=" * 62)
    print("الجزء B — مهمة حية كاملة (zai_internal/glm-4.6)")
    print("=" * 62)
    from core.config import LiveModelConfig
    from missions import run_mission
    from router.model_router import ModelRouter

    #: إعدادات معلنة لا افتراضية: في هذه الحاوية المزود الحي الوحيد
    #: القابل للحل هو zai_internal (منشأة الحاوية — §0.3)؛ مفتاح nvidia
    #: عند المالكة في مخزنها (DPAPI) ويعمل على جهازها.
    live_cfg = LiveModelConfig(
        default_provider="zai_internal", default_model="glm-4.6"
    )
    router = ModelRouter.build_live(live_cfg)
    goal = (
        "تقرير من صفحة واحدة عن التضخم وأسعار الفائدة في الاقتصادات "
        "الكبرى، من 5-8 مصادر موثقة تشمل بيانات رسمية من FRED والبنك "
        "الدولي، عربي RTL، PDF بحجم A4"
    )
    stream_path = MISSION_DIR.parent / "order003_stream.log"

    def on_event(event: dict) -> None:
        line = json.dumps(event, ensure_ascii=False)[:220]
        with stream_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    result = run_mission(goal, router=router, mission_dir=MISSION_DIR,
                         on_event=on_event)
    print(f"  الحكم: {result.verdict} — {result.reason[:160]}")
    print(f"  الحالة النهائية: {result.final_state}")
    print(f"  PDF: {result.pdf_path} (صفحات: {result.pdf_pages})")
    print(f"  المصادر: {len(result.sources)}")
    print(f"  الأدلة: {result.evidence_path}")
    print(f"  EVIDENCE_SHA256: {result.evidence_sha256}")
    evidence = json.loads(Path(result.evidence_path).read_text(encoding="utf-8"))
    data_calls = [
        c for c in evidence.get("tool_calls", [])
        if c.get("tool") in ("fred_csv", "worldbank_indicator",
                             "http_get_text", "http_get_json", "page_to_text")
    ]
    print(f"  استدعاءات أدوات بيانات في المهمة: {len(data_calls)}")
    for call in data_calls:
        print(f"    - {call['tool']} ({call['execution_site']}, "
              f"{call.get('duration_ms', 0)}ms)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--all"
    if mode in ("--all", "--a-only"):
        part_a()
    if mode in ("--all", "--b-only"):
        part_b()
