"""اختبارات W2-T25 — حكم المراجع يصل evidence.json (قياس 728).

الدافع: verdict_reasons كانت تحمل الرسالة العامة «الدورة لم تكتمل
أدلةً» وتبتلع missing_evidence الحرفي — فلا سبب قابل للتشخيص في
الأدلة الدائمة. العقد الجديد: كل حدث تحقق (task_verification /
verification_rollup) يُسجل بحكمه ونقصه المعلن.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from tasks import _verification_block  # noqa: E402


def test_extracts_verifier_events_with_missing():
    events = [
        {"kind": "task_execution", "details": {"task_id": "T1"}},
        {"kind": "task_verification", "details": {
            "task_id": "T1", "verdict": "not_evidenced",
            "confidence": 0.4,
            "missing_evidence": ["grep output not recorded", "x" * 300]}},
        {"kind": "verification_rollup", "details": {
            "verdict": "NOT_EVIDENCED", "confidence": 0.5,
            "missing_evidence": ["W1", "W2", "W3", "W4", "W5", "W6",
                                 "W7", "W8", "W9", "W10"]}},
    ]
    out = _verification_block(events)
    assert len(out) == 2
    assert out[0]["task_id"] == "T1"
    assert out[0]["verdict"] == "not_evidenced"
    assert out[0]["missing_evidence"][0] == "grep output not recorded"
    assert len(out[0]["missing_evidence"][1]) <= 200
    assert len(out[1]["missing_evidence"]) == 8  # مقصوصة للسقف


def test_empty_when_no_verifier_events():
    assert _verification_block([]) == []
    assert _verification_block(
        [{"kind": "task_execution", "details": {}}]) == []
