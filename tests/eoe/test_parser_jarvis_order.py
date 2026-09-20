"""§10.1 — test_parser_jarvis_order: أمر المالك → spec مطابق.

المطابقة المطلوبة حرفيًا: 10 أقسام، 9+ شروط توقف، 6 قرارات مالك
(D1–D6)، قالب §10 حقول بالترتيب، access_requests و execution_mode.
"""
from __future__ import annotations

from eoe.order_parser import ExecutionMode, GrantKind, parse_order


def test_jarvis_order_parses_to_matching_spec(jarvis_order):
    result = parse_order(jarvis_order)
    assert result.ok, f"فشل التحليل: {result.reason}"
    spec = result.spec
    # عقد التنفيذ — حرفيًا من §0
    assert spec.repository == "jsiadyarslan-lab/agent-hub"
    assert spec.branch == "main"
    assert spec.execution_mode is ExecutionMode.READ_ONLY
    # 10 أقسام بالضبط: §0..§9
    assert len(spec.sections) == 10
    assert [s.number for s in spec.sections] == list(range(10))
    # 9+ شروط توقف
    assert len(spec.hard_stop_conditions) >= 9
    # 6 قرارات مالك D1–D6
    assert [d[0] for d in spec.owner_decisions] == [f"D{i}" for i in range(1, 7)]
    # قالب التقرير: 10 حقول بالترتيب الحرفي مع الربط الصريح
    names = [name for name, _ in spec.report_template]
    assert names == [
        "VERDICT", "MAP", "LESSONS", "CONSISTENCY", "QUALITY",
        "ORPHANS", "DECISIONS", "HONESTY BOUNDS", "ZERO-WRITE PROOF",
        "HARD STOPS FIRED",
    ]
    sources = {name: source for name, source in spec.report_template}
    assert sources["MAP"] == 1 and sources["LESSONS"] == 2
    assert sources["HONESTY BOUNDS"] == 7 and sources["ZERO-WRITE PROOF"] == 8
    assert sources["VERDICT"] == 0 and sources["HARD STOPS FIRED"] == 0
    # طلبات الوصول: منحة قراءة واحدة على مخزن v1
    assert len(spec.access_requests) == 1
    request = spec.access_requests[0]
    assert request.kind is GrantKind.PATH_GRANT
    assert request.scope == "read"
    assert request.target == "/home/z/my-project/agent-hub/runtime/db"
    # القائمة البيضاء: python حصرًا
    assert spec.command_whitelist == ["python"]


def test_parser_does_not_invent_what_is_not_written():
    """المحلل لا يستنتج — الوضع الغائب يبقى READ_ONLY بقرار معلن،
    والمنح الغائبة تبقى غائبة."""
    minimal = (
        "# EXECUTION ORDER\n"
        "### §0 — عقد التنفيذ\n"
        "1. المستودع: owner/repo — الفرع: main.\n"
        "### §9 — القالب\n"
        "```\nVERDICT: x\n```\n"
    )
    result = parse_order(minimal)
    assert result.ok
    spec = result.spec
    assert spec.execution_mode is ExecutionMode.READ_ONLY  # §1: إن لم يُذكر
    assert spec.access_requests == []
    assert spec.command_whitelist == []
    assert spec.push_policy == ""


def test_parser_rejects_orders_without_contract_or_template():
    """بلا §0 أو بلا قالب = رفض صريح بسبب مقروء — لا تخمين."""
    no_contract = "# ORDER\n### §1 — عمل\n1. بند.\n"
    result = parse_order(no_contract)
    assert not result.ok
    assert "§0" in result.reason

    no_template = (
        "### §0 — عقد\n1. المستودع: owner/repo — الفرع: main.\n"
    )
    result = parse_order(no_template)
    assert not result.ok
    assert "القالب" in result.reason
