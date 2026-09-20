"""§10.10 — test_section_failure_no_skip: فشل قسم 2/4 → 3 و4 لا يُنفَّذان."""
from __future__ import annotations

from pathlib import Path

from eoe.eoe_engine import EoeEngine

ORDER = """# EXECUTION ORDER — FAIL_CHAIN
### §0 — عقد التنفيذ الصلب
1. المستودع: owner/fail-chain — الفرع: main — الوضع: READ_ONLY.
2. الأوامر المسموحة: python فقط.
### §1 — قسم ناجح
الأوامر:
- python -c "print('section-1-ok')"
### §2 — قسم فاشل
الأوامر:
- python -c "import sys; sys.exit(7)"
### §3 — لا يجب أن ينفَّذ
الأوامر:
- python -c "print('MUST-NOT-RUN')"
### §4 — لا يجب أن ينفَّذ أيضًا
الأوامر:
- python -c "print('MUST-NOT-RUN-2')"
### §9 — القالب الإلزامي للتقرير
```
VERDICT: PASS / HARD STOP
HARD STOPS FIRED: عدد أو NONE
```
**END OF ORDER**
"""


def test_section_failure_stops_everything_after(sandbox_manager, tmp_path):
    """فشل §2 = §3 و§4 لا يُنفَّذان — لا تخطٍّ صامت أبدًا."""
    events: list[tuple[str, dict]] = []
    engine = EoeEngine(
        sandbox_manager,
        grantor_key=b"fc-grantor",
        approval_key=b"fc-approval",
        on_event=lambda kind, payload: events.append((kind, payload)),
        work_base=str(tmp_path / "fc"),
        working_repo=str(tmp_path),
    )
    result = engine.run_order(ORDER, approve_grants=lambda p: [])

    # توقف صلب بسبب فشل §2
    assert result.verdict == "HARD STOP"
    assert any("فشل تنفيذ" in stop for stop in result.hard_stops), result.hard_stops

    # §1 نفذ؛ §2 توقف؛ §3 و§4 لم يبدآ أصلًا
    started = [p["section"] for k, p in events if k == "section.started"]
    assert started == [0, 1, 2], f"أقسام بدأت أكثر من المسموح: {started}"
    executed = result.executed_sections
    assert 1 in executed
    assert 2 not in executed and 3 not in executed and 4 not in executed

    # لا أثر لتنفيذ §3/§4 في مخرجات أي تنفيذ
    stdouts = " ".join(
        getattr(o, "stdout", "") for o in engine._execution.executions
    )
    assert "MUST-NOT-RUN" not in stdouts

    # حدث التوقف الصلب صدر بسبب فشل §2
    hard_stops = [p for k, p in events if k == "hard_stop.fired"]
    assert hard_stops and "§2" in hard_stops[0]["detail"]

    # التقرير الجزئي حتى لحظة التوقف — §1 نفذ و§2 لم
    assert result.report is not None
    assert result.report.verdict == "HARD STOP"
