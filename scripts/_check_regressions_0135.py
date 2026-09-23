"""فحص انحدارات محتملة: هل هذه الاختبارات فاشلة أصلًا في الأساس؟

لا يُقبل «لا انحدارات» بلا مقارنة نصية مع قائمة الأساس (‏9057c8d).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "runtime" / "_baseline_9057c8d.txt"

SUSPECTS = [
    "test_research_providers_seeded",
    "test_snapshot_progress_is_real_not_invented",
    "test_pause_and_resume_same_durable_job",
    "test_final_stop_is_durable_and_preserves_everything",
    "test_resume_continues_from_checkpoint",
    "test_provision_ready_resumes_same_job",
    "test_only_explicit_owner_stop_terminates",
    "test_live_event_replay_after_disconnect",
    "test_state_snapshot_reconciliation",
    "test_server_restart_preserves_workflow",
    "test_mandatory_approval_live_flow",
    "test_task_each_role_receives_its_own_provider_and_model",
    "test_live_task_never_calls_mock_factory",
    "test_cycle_events_replay_after_seq",
    "test_provider_not_ready_blocks_step_then_resumes",
    "test_projects_api",
]


def load(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-16", "utf-8", "utf-8-sig", "cp1256"):
        try:
            text = raw.decode(encoding)
            if text.count("\x00") < 10:
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def main() -> int:
    if not BASE.exists():
        print(f"لا ملف أساس: {BASE}")
        return 2
    text = load(BASE)
    failed = set(re.findall(r"FAILED\s+(\S+)", text))
    print(f"أساس 9057c8d: {len(failed)} اختبارًا فاشلًا (نص القائمة)")
    print()
    for name in SUSPECTS:
        hits = [f for f in failed if name in f]
        state = "فاشل في الأساس" if hits else "ناجح في الأساس → فحص!"
        print(f"  {name:<58} {state}")
        for hit in hits[:2]:
            print(f"      {hit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
