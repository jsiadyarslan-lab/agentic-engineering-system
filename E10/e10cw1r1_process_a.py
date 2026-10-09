#!/usr/bin/env python3
"""E10-CW1-R1 PROCESS A — executes the mission until the scenario's crash
boundary, then dies by a REAL self-SIGKILL witnessed by the external runner.

Injection points (all are REAL lifecycle boundaries on the production path,
inside engine._governed_artifact_write):

  A_pre_effect   — the engine has durably appended the `intent` record and is
      about to perform the physical write. Kill BEFORE the adapter writes.
      Wrapper intercepts engine.sandbox_manager.write_artifact for TASK_D's
      sandbox and kills before delegating to the real adapter.

  B_pre_journal  — the real adapter COMPLETED the physical write (fsynced);
      the engine has NOT yet run _journal_performance. Kill AFTER the real
      write, BEFORE returning control to the engine. THIS IS THE ORDER §2
      GAP BOUNDARY: file exists, journal has intent only, no outcome record.

  C_post_journal — the `performed` record is durable and ARTIFACT_CREATED is
      being emitted; kill at the emission (the CW1 injection point — kept to
      re-prove CW1's window, order §4-C).

The kill in the first two modes happens INSIDE a wrapper around the engine's
sandbox_manager.write_artifact. The wrapper NEVER performs or plants the
effect itself: for the A mode it kills before the real adapter runs; for the
B mode the REAL production adapter performs the write and the wrapper only
observes + kills before the engine can journal. The physical side effect is
always produced by the production adapter on the production path.

The durable injection marker (evidence/injection.json) records the PROVABLE
boundary state at the kill moment: raw journal scan (intent/performed counts
for the crash-window task), file existence + stat, planned artifact id.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import build_controller, build_engine, durable_write_json, e10_specs  # noqa: E402
from e10cw1r1_common import (  # noqa: E402
    CRASH_WINDOW_TASK, D_REL_PATH, SCENARIO_INJECTION, journal_path,
    scan_journal, side_effect_file, stat_snapshot,
)

from unified.contracts import EventType  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main(workdir: str, scenario: str) -> None:
    injection_point = SCENARIO_INJECTION[scenario]
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    pid = os.getpid()
    print(f"[R1_PROCESS_A] pid={pid} scenario={scenario} injection={injection_point} start={utcnow()}")

    engine = build_engine(artifacts_dir)
    controller = build_controller(engine, artifacts_dir / "mc_state")
    mission, run, key_to_task = controller.define_mission(
        f"E10-CW1-R1 intent-first pre-journal crash proof, scenario {scenario}: "
        "same five-task graph as E10/CW1, SIGKILLed inside the crash window of "
        "TASK_D at a real lifecycle boundary of the governed artifact write.",
        e10_specs(),
    )
    print(f"[R1_PROCESS_A] mission={mission.mission_id} run={run.run_id}")
    task_d_id = key_to_task[CRASH_WINDOW_TASK]
    d_sandbox = f"sandbox-{task_d_id}"
    d_file = side_effect_file(artifacts_dir, d_sandbox, D_REL_PATH)

    def boundary_state() -> dict:
        """PROVABLE state of the durable world at this exact moment."""
        scan = scan_journal(artifacts_dir, mission.mission_id)
        d_records = [r for r in scan["records"]
                     if r.get("task_id") == task_d_id and r.get("path") == D_REL_PATH]
        return {
            "journal_exists": scan["exists"],
            "journal_sha256": scan["sha256"],
            "journal_line_status": scan["line_status"],
            "d_intent_records": [r for r in d_records if r.get("record_type") == "intent"],
            "d_performed_records": [r for r in d_records if r.get("record_type") == "performed"],
            "d_file": stat_snapshot(d_file),
        }

    # ------------------------------------------------------------------
    # C_post_journal: event subscriber kills at the ARTIFACT_CREATED
    # emission (AFTER performed is durable, BEFORE completion records).
    # ------------------------------------------------------------------
    if injection_point == "C_post_journal":
        def on_event(event) -> None:
            if (
                event.event_type == EventType.ARTIFACT_CREATED
                and event.mission_id == mission.mission_id
                and event.correlation_id == task_d_id
            ):
                payload = event.payload
                artifact_id = (
                    payload.get("artifact_id") if isinstance(payload, dict)
                    else getattr(payload, "artifact_id", None)
                )
                bs = boundary_state()
                marker = {
                    "injection_point": injection_point,
                    "scenario": scenario,
                    "task_key": CRASH_WINDOW_TASK,
                    "task_id": task_d_id,
                    "artifact_id": artifact_id,
                    "reached_at_utc": utcnow(),
                    "process_pid": pid,
                    "kill_signal": "SIGKILL",
                    "boundary_state": bs,
                    "lifecycle_position": (
                        "after the durable performed record, at the "
                        "ARTIFACT_CREATED emission, before any durable record "
                        "of task/attempt completion"
                    ),
                }
                durable_write_json(evidence_dir / "injection.json", marker)
                print(f"[R1_PROCESS_A] INJECTION ({injection_point}) at {utcnow()}: performed durable; killing")
                os.kill(pid, signal.SIGKILL)
        engine.event_bus.subscribe(on_event)

    # ------------------------------------------------------------------
    # A_pre_effect / B_pre_journal: wrapper around the engine's
    # sandbox_manager.write_artifact — the REAL boundary between the
    # physical write and the outcome journaling.
    # ------------------------------------------------------------------
    if injection_point in ("A_pre_effect", "B_pre_journal"):
        real_write = engine.sandbox_manager.write_artifact

        async def wrapped_write(sandbox_id, path, content, artifact_id=None):
            if sandbox_id == d_sandbox and path == D_REL_PATH:
                if injection_point == "A_pre_effect":
                    bs = boundary_state()
                    marker = {
                        "injection_point": injection_point,
                        "scenario": scenario,
                        "task_key": CRASH_WINDOW_TASK,
                        "task_id": task_d_id,
                        "planned_artifact_id": artifact_id,
                        "reached_at_utc": utcnow(),
                        "process_pid": pid,
                        "kill_signal": "SIGKILL",
                        "boundary_state": bs,
                        "lifecycle_position": (
                            "after the durable intent record, BEFORE the "
                            "physical side effect (the adapter has not run)"
                        ),
                    }
                    durable_write_json(evidence_dir / "injection.json", marker)
                    print(f"[R1_PROCESS_A] INJECTION ({injection_point}) at {utcnow()}: intent durable, file absent; killing")
                    os.kill(pid, signal.SIGKILL)
                # B_pre_journal: let the REAL production adapter perform the
                # write (fsynced), then die BEFORE the engine journals it.
                if artifact_id is not None:
                    artifact = await real_write(sandbox_id, path, content, artifact_id=artifact_id)
                else:
                    # baseline-compat: engine predating the planned-identity
                    # parameter calls without it
                    artifact = await real_write(sandbox_id, path, content)
                bs = boundary_state()
                marker = {
                    "injection_point": injection_point,
                    "scenario": scenario,
                    "task_key": CRASH_WINDOW_TASK,
                    "task_id": task_d_id,
                    "planned_artifact_id": artifact_id,
                    "adapter_artifact_id": artifact.artifact_id,
                    "reached_at_utc": utcnow(),
                    "process_pid": pid,
                    "kill_signal": "SIGKILL",
                    "boundary_state": bs,
                    "lifecycle_position": (
                        "the physical write COMPLETED (real adapter, fsynced); "
                        "the engine has NOT yet written the performed record — "
                        "the order §2 gap boundary"
                    ),
                }
                durable_write_json(evidence_dir / "injection.json", marker)
                print(f"[R1_PROCESS_A] INJECTION ({injection_point}) at {utcnow()}: file written, journal has intent only; killing")
                os.kill(pid, signal.SIGKILL)
            if artifact_id is not None:
                return await real_write(sandbox_id, path, content, artifact_id=artifact_id)
            return await real_write(sandbox_id, path, content)

        engine.sandbox_manager.write_artifact = wrapped_write

    result = await controller.execute_run(run.run_id, max_parallel=1)
    # Unreachable when the injection fires; kept as an honest failure marker.
    durable_write_json(evidence_dir / "process_a.json", {
        "status": "INJECTION_NEVER_FIRED",
        "execute_run_result": {"success": result.get("success")},
    })
    raise SystemExit("FATAL: injection never fired — crash boundary not reached")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
