#!/usr/bin/env python3
"""E10-RP1 §4 — fresh-process restoration probe.

Simulates a NEW process (this interpreter) taking over a review-gated
mission whose durable state exists on disk:

  1. reads the durable ledger (what any new process CAN see),
  2. builds a fresh engine + fresh MissionController (require_plan_review=True)
     with NO controller-state restoration,
  3. attempts to continue the run,
  4. records whether execution was REFUSED (fail-closed) and whether the
     fresh controller had any review state of its own.

Expected (pre-registered §4 outcome):
  - durable ledger on disk: plan_version v2, 1 replan, 3 plan_reviews;
  - fresh controller state: NOT restored (v1, empty) — recorded NOT PROVEN;
  - continuation: REFUSED with RuntimeError before ANY execution.

Usage: e10rp1_restore_probe.py <state_dir> <mission_id> <run_id>
Writes <state_dir>/restore_probe.json and prints it as one JSON line.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    state_dir, mission_id, run_id = sys.argv[1], sys.argv[2], sys.argv[3]
    state_dir = Path(state_dir)

    ledger_path = state_dir / "mission_controller" / mission_id / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else None

    from unified.execution import ExecutionEngine
    from unified.mission_controller import MissionController

    from e10_common import build_grant_stack
    validator, grant_id = build_grant_stack(str(state_dir))
    engine = ExecutionEngine(artifacts_base_dir=str(state_dir),
                             grant_validator=validator,
                             grant_ids=[grant_id])
    mc = MissionController(engine, state_dir=str(state_dir), require_plan_review=True)

    probe = {
        "probe": "fresh_process_restore",
        "state_dir": str(state_dir),
        "mission_id": mission_id,
        "run_id": run_id,
        "durable_ledger_on_disk": {
            "exists": ledger is not None,
            "plan_version": (ledger or {}).get("plan_version"),
            "n_replans": len((ledger or {}).get("replans", [])),
            "n_plan_reviews": len((ledger or {}).get("plan_reviews", [])),
        },
        "fresh_controller_state": {
            "plan_version": mc.plan_version,
            "n_replans": len(mc.replans),
            "n_plan_reviews": len(mc.plan_reviews),
            "restored_from_ledger": False,  # no restoration code exists (§4: NOT PROVEN)
        },
    }

    events_before = len(engine.event_bus.history)
    try:
        asyncio.run(mc.execute_run(run_id))
        probe["continuation"] = {"refused": False,
                                 "note": "UNEXPECTED: continuation started without review state"}
    except RuntimeError as ex:
        probe["continuation"] = {
            "refused": True,
            "error": str(ex),
            "new_events": len(engine.event_bus.history) - events_before,
        }

    out = state_dir / "restore_probe.json"
    out.write_text(json.dumps(probe, indent=2, default=str), encoding="utf-8")
    print(json.dumps(probe, default=str))
    expected_refused = probe["continuation"].get("refused") is True
    return 0 if expected_refused else 1


if __name__ == "__main__":
    sys.exit(main())
