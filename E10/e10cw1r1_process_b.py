#!/usr/bin/env python3
"""E10-CW1-R1 PROCESS B — fresh OS process; restores from durable storage
ONLY (resume_info.json carries IDs, never state objects) and resumes through
the scenario's crash boundary. Scenario-specific expectations:

  A   — the intent is durable, the effect file is absent: the effect provably
        never happened. B must perform the write ONCE with the PLANNED
        identity from the intent (first execution, not a re-run), record
        performed(direct), and complete the mission. NO ARTIFACT_RECONCILED.
  B   — intent durable, file present (fsynced by A's adapter), NO performed
        record: B must DETECT the existing effect, ADOPT it with the planned
        identity WITHOUT rewriting (mtime_ns/inode/sha256 unchanged from the
        pre-crash snapshot), record performed(adopted_after_crash), emit
        ARTIFACT_RECONCILED(intent_adoption), and complete the mission.
  C   — intent+performed durable, completion not: B must reconcile from the
        performed record (CW1 contract), never rewrite.
  D1  — like B, but the journal carries a torn TRAILING line after the
        intent: B must ignore it (never durable truth), still adopt via the
        intent, and its own append must repair the file (torn tail truncated).
  D2a — the trailing intent line was corrupted away (invalid JSON) while the
        effect file exists: unreconcilable ambiguity — B must FAIL CLOSED
        with SideEffectReconciliationError (never silently overwrite).
  D2b — a MIDDLE prior journal record is corrupt (may hide the only proof of
        a proven effect): B must FAIL CLOSED with
        SideEffectJournalCorruptionError (never skip it silently).

Expected-failure scenarios (D2a/D2b) exit 0 when the failure is the EXPLICIT
fail-closed one with the right error type; any other outcome is a failure.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import (  # noqa: E402
    TASK_KEYS, artifacts_snapshot, attempts_snapshot, build_controller,
    build_engine, durable_write_json, evidence_snapshot, fsync_file,
)
from e10cw1r1_common import (  # noqa: E402
    CRASH_WINDOW_TASK, D_REL_PATH, journal_records_for, read_journal,
    scan_journal, side_effect_file, stat_snapshot,
)
from unified.contracts import EventType  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def event_payload(e):
    p = e.payload
    return p if isinstance(p, dict) else p.model_dump(mode="json")


async def main(workdir: str, scenario: str) -> None:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"
    pid = os.getpid()
    resume_info = json.loads((evidence_dir / "resume_info.json").read_text())
    print(f"[R1_PROCESS_B] pid={pid} scenario={scenario} start={utcnow()}")

    mission_id = resume_info["mission_id"]
    run_1 = resume_info["run_id"]
    checkpoint_id = resume_info["checkpoint_id"]
    task_ids = resume_info["task_ids"]
    task_to_key = {v: k for k, v in task_ids.items()}
    task_d_id = task_ids[CRASH_WINDOW_TASK]
    task_e_id = task_ids["TASK_E"]
    pid_a = resume_info["process_a_pid"]
    d_sandbox = f"sandbox-{task_d_id}"
    d_file = side_effect_file(artifacts_dir, d_sandbox, D_REL_PATH)

    engine = build_engine(artifacts_dir)
    controller = build_controller(engine, artifacts_dir / "mc_state")

    # --- 1. durable-only restore (IDs only crossed the boundary) ---
    resumed_run = engine.resume_from_checkpoint(checkpoint_id, mission_id)
    if resumed_run is None:
        raise SystemExit("FATAL: resume_from_checkpoint returned no run")
    run_2 = resumed_run.run_id
    controller._key_to_task = dict(task_ids)
    controller._task_to_key = dict(task_to_key)

    graph = engine.task_graph[run_2]
    restored_states = {task_to_key[t]: node["state"].value for t, node in graph.items()}
    pre_scan = scan_journal(artifacts_dir, mission_id)
    pre_d_records = journal_records_for(pre_scan["records"], task_d_id, D_REL_PATH)
    pre_intent = [r for r in pre_d_records if r["record_type"] == "intent"]
    pre_effective = [r for r in pre_d_records if r["record_type"] in ("performed", "reconciled")]
    pre_file = stat_snapshot(d_file)
    pre_snapshot_ref = json.loads((evidence_dir / "crash_window_snapshot.json").read_text())

    restoration = {
        "restored_states": restored_states,
        "completed_preserved": all(restored_states[k] == "COMPLETED" for k in ("TASK_A", "TASK_B", "TASK_C")),
        "crash_window_task_not_completed": restored_states.get(CRASH_WINDOW_TASK) not in ("COMPLETED", "FAILED", "CANCELLED"),
        "run_lineage_preserved": engine.runs[run_2].parent_run_id == run_1,
        "pre_resume_journal": {
            "d_intent": len(pre_intent),
            "d_effective": len(pre_effective),
            "line_status": pre_scan["line_status"],
        },
        "pre_resume_file": pre_file,
        "file_matches_pre_crash_snapshot": (
            # matching ABSENCE is as decisive as matching presence (scenario A)
            (pre_file is None and pre_snapshot_ref["pre_resume_side_effect_file"] is None)
            or bool(
                pre_file and pre_snapshot_ref["pre_resume_side_effect_file"]
                and pre_file["mtime_ns"] == pre_snapshot_ref["pre_resume_side_effect_file"]["mtime_ns"]
                and pre_file["inode"] == pre_snapshot_ref["pre_resume_side_effect_file"]["inode"]
            )
        ),
    }
    print(f"[R1_PROCESS_B] restored: {restored_states}; journal D: intent={len(pre_intent)} effective={len(pre_effective)}; file={'present' if pre_file else 'absent'}")

    fatal_pre: list = []
    if not restoration["completed_preserved"]:
        fatal_pre.append("completed tasks not preserved at restore")
    if not restoration["crash_window_task_not_completed"]:
        fatal_pre.append("crash-window task already completed at restore")
    if not restoration["run_lineage_preserved"]:
        fatal_pre.append("run lineage broken")
    if not restoration["file_matches_pre_crash_snapshot"]:
        fatal_pre.append("side-effect file changed between crash and resume")
    if fatal_pre:
        durable_write_json(evidence_dir / "process_b.json", {
            "status": "RESTORATION_FAILED", "scenario": scenario, "fatal": fatal_pre,
        })
        raise SystemExit(f"RESTORATION_FAILED: {fatal_pre}")

    # --- 2. RESUME through the crash boundary on the production path ---
    result = await controller.execute_run(run_2, max_parallel=1)
    continuation_success = bool(result.get("success"))

    # --- 3. scenario-specific accounting ---
    post_scan = scan_journal(artifacts_dir, mission_id)
    post_records = post_scan["records"]
    d_records = journal_records_for(post_records, task_d_id, D_REL_PATH)
    e_records = journal_records_for(post_records, task_e_id, "task_e_output.txt")
    d_intents = [r for r in d_records if r["record_type"] == "intent"]
    d_performed = [r for r in d_records if r["record_type"] == "performed"]
    d_reconciled = [r for r in d_records if r["record_type"] == "reconciled"]
    post_file = stat_snapshot(d_file)

    graph_after = engine.task_graph[run_2]
    final_states = {task_to_key[t]: node["state"].value for t, node in graph_after.items()}

    def history(event_type: EventType, correlation: str):
        return [e for e in engine.event_bus.history
                if e.event_type == event_type
                and e.mission_id == mission_id
                and e.correlation_id == correlation]

    d_created = history(EventType.ARTIFACT_CREATED, task_d_id)
    d_reconciled_events = history(EventType.ARTIFACT_RECONCILED, task_d_id)
    tool_failed = [e for e in engine.event_bus.history
                   if e.event_type == EventType.TOOL_FAILED and e.mission_id == mission_id]

    accounting = {
        "continuation_success": continuation_success,
        "final_states": final_states,
        "journal_d": {
            "types": [r["record_type"] for r in d_records],
            "intent": d_intents,
            "performed": d_performed,
            "reconciled": d_reconciled,
        },
        "journal_e_types": [r["record_type"] for r in e_records],
        "file": {"pre_resume": pre_file, "after_resume": post_file},
        "events": {
            "artifact_created_for_d": len(d_created),
            "artifact_created_ids": [event_payload(e).get("artifact_id") for e in d_created],
            "artifact_reconciled_for_d": len(d_reconciled_events),
            "artifact_reconciled_modes": [event_payload(e).get("mode") for e in d_reconciled_events],
            "tool_failed_errors": [event_payload(e).get("error") for e in tool_failed],
        },
        "attempts": attempts_snapshot(engine),
        "journal_line_status_after": post_scan["line_status"],
        "journal_sha256_after": post_scan["sha256"],
    }

    fatal: list = []
    ok_verify = None
    finalize = None
    final_cp_info = None

    if scenario in ("A", "B", "C", "D1"):
        # --- success scenarios: mission must complete with exactly-once effects
        if not continuation_success:
            fatal.append(f"continuation failed: {result}")
        if final_states != {k: "COMPLETED" for k in TASK_KEYS}:
            fatal.append(f"not all tasks completed: {final_states}")

        if scenario == "A":
            # effect provably never happened -> ONE physical write by B with
            # the PLANNED identity; performed(direct); NO reconciliation.
            if not (len(d_intents) == 1 and len(d_performed) == 1 and not d_reconciled):
                fatal.append(f"A: journal for D must be [intent, performed]; got {accounting['journal_d']['types']}")
            if d_intents:
                planned = d_intents[0]["artifact_id"]
                if not (d_performed and d_performed[0]["artifact_id"] == planned):
                    fatal.append("A: performed record must carry the PLANNED artifact id from the intent")
                if d_performed and d_performed[0].get("performed_via") != "direct":
                    fatal.append("A: performed must be performed_via=direct (first execution, not adoption)")
                if d_performed and d_performed[0].get("process_pid") != pid:
                    fatal.append("A: the single performed record must be written by Process B")
                if accounting["events"]["artifact_created_ids"] != [planned]:
                    fatal.append("A: ARTIFACT_CREATED must fire once with the planned identity")
            if accounting["events"]["artifact_reconciled_for_d"] != 0:
                fatal.append("A: no ARTIFACT_RECONCILED expected (nothing was reconciled — first execution)")
            if not (post_file and d_intents and post_file["sha256"] == d_intents[0]["content_sha256"]):
                fatal.append("A: the effect file must exist with the intent's content fingerprint")

        if scenario in ("B", "D1"):
            # effect happened, outcome record lost with A -> ADOPT without rewrite
            no_rewrite = bool(
                post_file and pre_file
                and post_file["mtime_ns"] == pre_file["mtime_ns"]
                and post_file["inode"] == pre_file["inode"]
                and post_file["sha256"] == pre_file["sha256"]
            )
            if not no_rewrite:
                fatal.append(f"{scenario}: the side-effect file was REWRITTEN across the resume")
            if not (len(d_intents) == 1 and len(d_performed) == 1 and not d_reconciled):
                fatal.append(f"{scenario}: journal for D must be [intent, performed(adopted)]; got {accounting['journal_d']['types']}")
            if d_intents and d_performed:
                planned = d_intents[0]["artifact_id"]
                if d_performed[0]["artifact_id"] != planned:
                    fatal.append(f"{scenario}: adopted artifact must keep the PLANNED identity")
                if d_performed[0].get("performed_via") != "adopted_after_crash":
                    fatal.append(f"{scenario}: performed must be performed_via=adopted_after_crash")
                if d_performed[0].get("performed_by_pid") != pid_a:
                    fatal.append(f"{scenario}: performed_by_pid must be Process A (the process that wrote the file)")
                if d_performed[0].get("intent_journal_record_id") != d_intents[0].get("journal_record_id"):
                    fatal.append(f"{scenario}: performed must link to the intent record")
                if accounting["events"]["artifact_created_ids"] != [planned]:
                    fatal.append(f"{scenario}: ARTIFACT_CREATED must fire once with the planned identity")
            if accounting["events"]["artifact_reconciled_for_d"] != 1 or \
               accounting["events"]["artifact_reconciled_modes"] != ["intent_adoption"]:
                fatal.append(f"{scenario}: expected exactly 1 ARTIFACT_RECONCILED(mode=intent_adoption)")
            if scenario == "D1":
                # the torn trailing line must be GONE after B's own append
                if "torn_or_corrupt" in accounting["journal_line_status_after"]:
                    fatal.append("D1: torn trailing line still present after resume appends")
                if not post_scan["ends_with_newline"]:
                    fatal.append("D1: journal file must end with a newline after repair")

        if scenario == "C":
            # CW1 window: reconcile from the durable performed record
            no_rewrite = bool(
                post_file and pre_file
                and post_file["mtime_ns"] == pre_file["mtime_ns"]
                and post_file["inode"] == pre_file["inode"]
            )
            if not no_rewrite:
                fatal.append("C: the side-effect file was REWRITTEN across the resume")
            if not (len(d_intents) == 1 and len(d_performed) == 1 and len(d_reconciled) == 1):
                fatal.append(f"C: journal for D must be [intent, performed, reconciled]; got {accounting['journal_d']['types']}")
            if d_reconciled and not d_reconciled[0].get("no_physical_rewrite"):
                fatal.append("C: reconciled record lacks no_physical_rewrite=true")
            if accounting["events"]["artifact_reconciled_for_d"] != 1 or \
               accounting["events"]["artifact_reconciled_modes"] != ["performed_record"]:
                fatal.append("C: expected exactly 1 ARTIFACT_RECONCILED(mode=performed_record)")

        # TASK_E executes fresh post-resume on every success scenario
        if accounting["journal_e_types"] != ["intent", "performed"]:
            fatal.append(f"{scenario}: TASK_E must execute fresh [intent, performed]; got {accounting['journal_e_types']}")

        if not fatal:
            ok_verify, report = controller.verify_completion(run_2, required_keys=TASK_KEYS)
            if not ok_verify:
                fatal.append(f"verify_completion failed: {report}")
            finalize = controller.finalize_mission(mission_id, run_2, f"E10-CW1-R1 scenario {scenario} resume completion verified")
            final_cp = controller.create_full_checkpoint(mission_id, run_2, step=5)
            final_cp_path = Path(artifacts_dir) / "checkpoints" / mission_id / f"{final_cp.checkpoint_id}.json"
            fsync_file(final_cp_path)
            fsync_file(Path(artifacts_dir) / "events" / mission_id / "event_log.jsonl")
            ev_store = Path(artifacts_dir) / "evidence_store" / mission_id
            fsync_file(ev_store / "artifacts.json")
            fsync_file(ev_store / "evidence.json")
            final_cp_info = {
                "checkpoint_id": final_cp.checkpoint_id,
                "path": str(final_cp_path),
                "hash": final_cp.hash,
            }

    else:
        # --- expected-failure scenarios: explicit fail-closed refusal
        expected_type = "SideEffectJournalCorruptionError" if scenario == "D2b" else "SideEffectReconciliationError"
        if continuation_success:
            fatal.append(f"{scenario}: continuation SUCCEEDED but a fail-closed refusal was required")
        if final_states.get(CRASH_WINDOW_TASK) != "FAILED":
            fatal.append(f"{scenario}: crash-window task must end FAILED, got {final_states.get(CRASH_WINDOW_TASK)}")
        err_types = []
        for e in tool_failed:
            err = event_payload(e).get("error") or ""
            if expected_type in err or err.startswith("SIDE_EFFECT"):
                err_types.append(err)
        if not err_types:
            fatal.append(f"{scenario}: no TOOL_FAILED carrying the expected fail-closed error {expected_type}")
        # the durable world must be UNTOUCHED by the refusal
        if post_file and pre_file:
            if (post_file["mtime_ns"], post_file["inode"]) != (pre_file["mtime_ns"], pre_file["inode"]):
                fatal.append(f"{scenario}: the effect file was modified despite fail-closed refusal")
        if scenario == "D2b":
            # B must have appended NOTHING to the journal (corruption fires at load)
            if post_scan["sha256"] != pre_scan["sha256"]:
                fatal.append("D2b: journal file changed during the fail-closed run (nothing may be appended)")
        if scenario == "D2a":
            # the corrupt trailing line remains (B never appended; nothing repaired)
            if post_scan["sha256"] != pre_scan["sha256"]:
                fatal.append("D2a: journal file changed during the fail-closed run")

    evidence_payload = {
        "status": "PROCESS_B_COMPLETE" if not fatal else "PROCESS_B_FAILED",
        "scenario": scenario,
        "process_b_pid": pid,
        "process_a_pid": pid_a,
        "pid_difference": pid != pid_a,
        "resumed_run_id": run_2,
        "restoration": restoration,
        "side_effect_accounting": accounting,
        "verify_completion_report": ok_verify if ok_verify is not None else (False, {"skipped": "expected-failure scenario"}) if scenario.startswith("D2") else None,
        "finalize_mission": finalize,
        "final_checkpoint": final_cp_info,
    }
    durable_write_json(evidence_dir / "process_b.json", evidence_payload)
    from e10cw1r1_common import fsync_journal
    fsync_journal(artifacts_dir, mission_id)
    if fatal:
        raise SystemExit(f"PROCESS_B_FAILED: {fatal}")
    print(f"[R1_PROCESS_B] scenario {scenario}: OK (continuation_success={continuation_success})")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
