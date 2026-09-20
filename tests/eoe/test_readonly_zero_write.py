"""§10.2 — test_readonly_zero_write: أمر READ_ONLY على مخزن v1 الحقيقي.

الإثبات المزدوج المتطابق: من داخل الركيزة (مسبار الكتابة يُحجب EROFS)
ومن خارجها (بصمة git + عدّادات الجداول + جرد الملفات قبل/بعد) —
وتقرير §9 بأمر المالك حرفيًا.
"""
from __future__ import annotations

from pathlib import Path

from eoe.eoe_engine import EoeEngine


def _run(jarvis_order, sandbox_manager, tmp_path):
    events: list[tuple[str, dict]] = []
    engine = EoeEngine(
        sandbox_manager,
        grantor_key=b"test-grantor-key",
        approval_key=b"test-approval-key",
        on_event=lambda kind, payload: events.append((kind, payload)),
        work_base=str(tmp_path / "work"),
        working_repo=str(Path(__file__).resolve().parents[2]),
    )
    result = engine.run_order(
        jarvis_order,
        approve_grants=lambda proposals: [
            engine._grantor.approve(g) for g in proposals
        ],
    )
    return engine, result, events


def test_readonly_audit_on_v1_store_produces_literal_report(
    jarvis_order, sandbox_manager, tmp_path
):
    """الدورة الكاملة: تقرير بالقالب الحرفي + إثبات مزدوج متطابق."""
    engine, result, events = _run(jarvis_order, sandbox_manager, tmp_path)
    assert result.verdict == "PASS", f"توقفات: {result.hard_stops}"
    assert result.hard_stops == []

    # التقرير == القالب حرفيًا: نفس الحقول بالترتيب
    report = result.report
    names = [name for name, _ in
             __import__("eoe.order_parser", fromlist=["parse_order"])
             .parse_order(jarvis_order).spec.report_template]
    assert [line.split(":", 1)[0] for line in report.lines] == names

    # الأقسام الثمانية المنفذة كلها accounted-for
    assert result.executed_sections == [0, 1, 2, 3, 4, 5, 6, 7, 8]
    assert result.section_states[9] == "مُعلن (بلا تنفيذ)"

    # الإثبات المزدوج: مسبار داخلي محجوب + بصمات خارجية متطابقة
    probe_events = [p for k, p in events if k == "section.proof"
                    and "inside_probe" in p]
    assert probe_events, "لا مسبار كتابة داخلي"
    for probe in probe_events:
        assert "PROBE-BLOCKED" in probe["inside_probe"], probe
    proof_events = [p for k, p in events if k == "section.proof"
                    and "identical" in p]
    assert proof_events
    for proof in proof_events:
        assert proof["identical"] is True, proof
        assert proof["diffs"] == []

    # أدلة حقيقية من قاعدة v1: أرقام فعلية لا فراغ
    less = "\n".join(report.lines)
    assert "total" in less and "orphan" in less.lower()
    assert "HARD STOPS FIRED: NONE" in less


def test_readonly_zero_write_double_proof_counters(
    jarvis_order, sandbox_manager, tmp_path
):
    """عدّادات الجداول قبل/بعد متطابقة — لا صفح واحد يتحرك في v1."""
    import sqlite3

    def counters():
        con = sqlite3.connect(
            "file:/home/z/my-project/agent-hub/runtime/db/agent_hub.db?mode=ro",
            uri=True,
        )
        try:
            return {
                row[0]: con.execute(f"SELECT COUNT(*) FROM {row[0]}").fetchone()[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            con.close()

    before = counters()
    _run(jarvis_order, sandbox_manager, tmp_path)
    after = counters()
    assert before == after, "العدّادات تحركت — خرق كتابة في READ_ONLY!"
