#!/usr/bin/env python3
"""E10-CW1-R1 RUNNER — orchestrates the pre-journal crash proof as REAL OS
processes, witnessing every fact from OUTSIDE any participant.

    [RUNNER pid R]  one session = all 6 scenarios x N chains (default 2)
       per (scenario, chain):
       |-- subprocess A  (e10cw1r1_process_a.py workdir scenario) -> SIGKILLed (-9)
       |      dies at the scenario's REAL crash boundary of TASK_D's governed
       |      artifact write (see e10cw1r1_common for the boundary map).
       |-- RUNNER post-crash witness: crash-point validation from DURABLE
       |      records only; journal raw scan + D-file stat snapshot;
       |      resume_info.json = IDs ONLY across the process boundary.
       |-- [D scenarios] CORRUPTOR (in-process, outside participants):
       |      D1  append torn trailing fragment to journal.jsonl
       |      D2a byte-corrupt the trailing intent line (invalid JSON)
       |      D2b byte-corrupt a MIDDLE prior performed record
       |      corruption.json records exactly what was done; journal sha256
       |      snapshot before/after.
       |-- subprocess B  (e10cw1r1_process_b.py workdir scenario) -> exit 0
       |      new OS process; durable-only restore; scenario-specific
       |      expectations (success or explicit fail-closed).
       |-- RUNNER post-resume witness: D-file stat + journal sha256 again.
       `-- subprocess V  (e10cw1r1_verifier.py workdir scenario) -> exit 0

    Timing fields are honest: started_at_utc at the runner's actual start,
    consolidated_at_utc at the end (E10-CW1 order §8 discipline).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e10_common import durable_write_json  # noqa: E402
from e10cw1r1_common import (  # noqa: E402
    CRASH_WINDOW_TASK, D_REL_PATH, SCENARIO_CORRUPTION, SCENARIOS,
    SCENARIO_INJECTION, journal_path, scan_journal, side_effect_file,
    stat_snapshot,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_stage(name: str, script: str, *args):
    cmd = [sys.executable, str(HERE / script), *[str(a) for a in args]]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pid = proc.pid
    out, _ = proc.communicate()
    rc = proc.returncode
    wall = round(time.time() - t0, 3)
    print(f"\n{'=' * 78}\n[{name}] pid={pid} exit={rc} wall={wall}s\n{'=' * 78}")
    print(out)
    return {
        "stage": name, "script": script, "command": cmd,
        "runner_observed_pid": pid, "exit_code": rc, "wall_seconds": wall,
        "started_at_utc": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
        "ended_at_utc": datetime.fromtimestamp(t0 + wall, tz=timezone.utc).isoformat(),
        "termination_reason": (
            "SIGKILL (self, runner-observed)" if rc == -9
            else "exit" if rc == 0 else "failure"
        ),
        "stdout_tail": out[-3000:],
    }


def load_events(artifacts_dir: Path, mission_id: str):
    p = artifacts_dir / "events" / mission_id / "event_log.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def latest_checkpoint(artifacts_dir: Path, mission_id: str):
    cp_dir = artifacts_dir / "checkpoints" / mission_id
    best = None
    for p in sorted(cp_dir.glob("checkpoint-*.json")):
        data = json.loads(p.read_text())
        if best is None or data.get("created_at", "") >= best.get("created_at", ""):
            best = data
            best["__path"] = str(p)
    return best


def key_to_task_from_durable(cp: dict, events: list) -> dict:
    key_to_task = {}
    for tid, tdef in (cp.get("task_definitions") or {}).items():
        name = tdef.get("name", "") or ""
        if " - " in name:
            key_to_task.setdefault(name.split(" - ")[0].strip(), tid)
    for e in events:
        if e["event_type"] == "task.created":
            payload = e.get("payload") or {}
            name = payload.get("name", "") or ""
            if " - " in name and payload.get("task_id"):
                key_to_task.setdefault(name.split(" - ")[0].strip(), payload["task_id"])
    return key_to_task


def validate_crash_point(artifacts_dir: Path, evidence_dir: Path, mission_id: str, scenario: str):
    """Runner-side proof that the kill landed at the scenario's boundary."""
    injection_point = SCENARIO_INJECTION[scenario]
    events = load_events(artifacts_dir, mission_id)
    cp = latest_checkpoint(artifacts_dir, mission_id)
    key_to_task = key_to_task_from_durable(cp, events)
    if set(key_to_task) != {"TASK_A", "TASK_B", "TASK_C", "TASK_D", "TASK_E"}:
        return False, {"key_mapping_incomplete": key_to_task}, None
    task_to_key = {v: k for k, v in key_to_task.items()}
    task_d_id = key_to_task[CRASH_WINDOW_TASK]
    d_file = side_effect_file(artifacts_dir, f"sandbox-{task_d_id}", D_REL_PATH)

    injection = json.loads((evidence_dir / "injection.json").read_text())
    bs = injection.get("boundary_state") or {}
    d_completed_events = [e for e in events
                          if e["event_type"] == "task.completed" and e.get("correlation_id") == task_d_id]
    cp_states = {task_to_key.get(t, t): s for t, s in cp["task_states"].items()}

    in_window = {
        "injection_reached": bool(injection.get("reached_at_utc")),
        "injection_task_is_crash_window_task": injection.get("task_id") == task_d_id,
        "injection_point_matches_scenario": injection.get("injection_point") == injection_point,
        "last_checkpoint_states": cp_states,
        "completed_tasks_in_checkpoint": all(
            cp_states.get(k) == "COMPLETED" for k in ("TASK_A", "TASK_B", "TASK_C")
        ),
        "crash_window_task_not_completed_in_checkpoint": cp_states.get(CRASH_WINDOW_TASK) not in (
            "COMPLETED", "FAILED", "CANCELLED"
        ),
        "no_durable_task_completed_for_crash_window_task": len(d_completed_events) == 0,
    }

    # boundary-specific durable facts, witnessed by the runner AFTER the crash
    scan = scan_journal(artifacts_dir, mission_id)
    d_records = [r for r in scan["records"]
                 if r.get("task_id") == task_d_id and r.get("path") == D_REL_PATH]
    d_intent = [r for r in d_records if r.get("record_type") == "intent"]
    d_performed = [r for r in d_records if r.get("record_type") == "performed"]

    if injection_point == "A_pre_effect":
        in_window["journal_intent_present"] = len(d_intent) == 1
        in_window["journal_performed_absent"] = len(d_performed) == 0
        in_window["file_absent"] = not d_file.exists()
        in_window["marker_witnessed_same"] = bool(
            bs.get("d_intent_records") and not bs.get("d_performed_records")
            and bs.get("d_file") is None
        )
        valid = all([in_window["injection_reached"], in_window["injection_point_matches_scenario"],
                     in_window["journal_intent_present"], in_window["journal_performed_absent"],
                     in_window["file_absent"], in_window["marker_witnessed_same"],
                     in_window["completed_tasks_in_checkpoint"],
                     in_window["crash_window_task_not_completed_in_checkpoint"],
                     in_window["no_durable_task_completed_for_crash_window_task"]])
    elif injection_point == "B_pre_journal":
        in_window["journal_intent_present"] = len(d_intent) == 1
        in_window["journal_performed_absent"] = len(d_performed) == 0
        in_window["file_present"] = d_file.exists()
        in_window["marker_witnessed_same"] = bool(
            bs.get("d_intent_records") and not bs.get("d_performed_records")
            and bs.get("d_file") is not None
        )
        in_window["intent_recorded_before_kill"] = bool(
            d_intent and injection.get("reached_at_utc")
            and d_intent[0].get("recorded_at_utc", "") <= injection["reached_at_utc"]
        )
        valid = all([in_window["injection_reached"], in_window["injection_point_matches_scenario"],
                     in_window["journal_intent_present"], in_window["journal_performed_absent"],
                     in_window["file_present"], in_window["marker_witnessed_same"],
                     in_window["intent_recorded_before_kill"],
                     in_window["completed_tasks_in_checkpoint"],
                     in_window["crash_window_task_not_completed_in_checkpoint"],
                     in_window["no_durable_task_completed_for_crash_window_task"]])
    else:  # C_post_journal
        in_window["journal_intent_present"] = len(d_intent) == 1
        in_window["journal_performed_present"] = len(d_performed) == 1
        in_window["file_present"] = d_file.exists()
        in_window["performed_recorded_before_kill"] = bool(
            d_performed and injection.get("reached_at_utc")
            and d_performed[0].get("recorded_at_utc", "") <= injection["reached_at_utc"]
        )
        valid = all([in_window["injection_reached"], in_window["injection_point_matches_scenario"],
                     in_window["journal_intent_present"], in_window["journal_performed_present"],
                     in_window["file_present"], in_window["performed_recorded_before_kill"],
                     in_window["completed_tasks_in_checkpoint"],
                     in_window["crash_window_task_not_completed_in_checkpoint"],
                     in_window["no_durable_task_completed_for_crash_window_task"]])

    return valid, in_window, {
        "mission_id": mission_id,
        "run_id": cp["run_id"],
        "checkpoint_id": cp["checkpoint_id"],
        "checkpoint_path": cp["__path"],
        "task_ids": key_to_task,
        "crash_window_task_id": task_d_id,
        "side_effect_file": str(d_file),
        "injection": injection,
        "journal_sha256": scan["sha256"],
        "journal_line_status": scan["line_status"],
    }


def apply_corruption(artifacts_dir: Path, evidence_dir: Path, mission_id: str, scenario: str, task_ids: dict):
    """D-scenario corruption injection, applied OUTSIDE any participant."""
    kind = SCENARIO_CORRUPTION[scenario]
    p = journal_path(artifacts_dir, mission_id)
    raw = p.read_bytes()
    sha_before = hashlib.sha256(raw).hexdigest()
    task_d_id = task_ids[CRASH_WINDOW_TASK]

    if kind == "torn_trailing_line":
        # a partial append that never became durable truth (no trailing newline)
        fragment = b'{"record_type": "perfor'
        with open(p, "ab") as f:
            f.write(fragment)
            f.flush()
            os.fsync(f.fileno())
        desc = {
            "kind": kind,
            "appended_fragment": fragment.decode(),
            "position": "trailing",
            "rationale": "a torn FINAL record never became durable truth — it "
                         "must be ignored while the intent that precedes it "
                         "still governs reconciliation (order §4-D)",
        }
    elif kind == "corrupt_trailing_intent":
        # byte-corrupt the LAST line (TASK_D's intent) so it is unparseable
        lines = raw.splitlines(keepends=True)
        target_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                target_idx = i
                break
        if target_idx is None:
            raise SystemExit("FATAL: journal empty — cannot corrupt")
        original = lines[target_idx]
        try:
            rec = json.loads(original)
            assert rec.get("task_id") == task_d_id and rec.get("record_type") == "intent", rec
        except Exception as e:
            raise SystemExit(f"FATAL: last journal line is not TASK_D's intent: {e}")
        corrupted = original[:25] + b"CORRUPTED_BYTES:::" + original[40:]
        lines[target_idx] = corrupted
        data = b"".join(lines)
        with open(p, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        desc = {
            "kind": kind,
            "position": "trailing",
            "corrupted_line_index": target_idx,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "rationale": "the intent record is destroyed while its effect file "
                         "exists — unreconcilable ambiguity must be REJECTED "
                         "explicitly, never silently overwritten (order §4-D)",
        }
    elif kind == "corrupt_middle_record":
        # byte-corrupt a MIDDLE prior record (a completed task's performed
        # record — the durable proof of a PROVEN effect) followed by valid ones
        lines = [l for l in raw.splitlines(keepends=True)]
        # find TASK_C's performed line (a prior PROVEN effect, non-trailing:
        # TASK_D's intent+performed lines follow it)
        target_idx = None
        task_c_id = task_ids["TASK_C"]
        for i, l in enumerate(lines):
            try:
                rec = json.loads(l)
            except json.JSONDecodeError:
                continue
            if rec.get("task_id") == task_c_id and rec.get("record_type") == "performed":
                target_idx = i
        if target_idx is None:
            raise SystemExit("FATAL: TASK_C performed record not found for corruption")
        if target_idx >= len(lines) - 1:
            raise SystemExit("FATAL: corruption target is not a MIDDLE record")
        original = lines[target_idx]
        corrupted = original[:25] + b"CORRUPTED_BYTES:::" + original[40:]
        lines[target_idx] = corrupted
        data = b"".join(lines)
        with open(p, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        desc = {
            "kind": kind,
            "position": "middle",
            "corrupted_line_index": target_idx,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "rationale": "a PRIOR record that may be the only proof of a proven "
                         "effect is corrupt — the journal must FAIL CLOSED, "
                         "never skip it silently (order §4-D)",
        }
    else:
        raise SystemExit(f"FATAL: scenario {scenario} has no corruption")

    sha_after = hashlib.sha256(p.read_bytes()).hexdigest()
    record = {
        **desc,
        "scenario": scenario,
        "journal_path": str(p),
        "journal_sha256_before": sha_before,
        "journal_sha256_after": sha_after,
        "applied_at_utc": utcnow(),
        "applied_by": "runner (outside any participant process)",
    }
    durable_write_json(evidence_dir / "corruption.json", record)
    return record


def run_chain(session: Path, scenario: str, index: int) -> dict:
    workdir = session / scenario / f"chain{index}"
    evidence_dir = workdir / "evidence"
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"\n{'#' * 78}\n[RUNNER] scenario={scenario} chain={index} workdir={workdir}\n{'#' * 78}")

    # ---- PROCESS A: die at the scenario's real crash boundary ----
    a = run_stage(f"{scenario}_C{index}_PROCESS_A", "e10cw1r1_process_a.py", workdir, scenario)
    if a["exit_code"] != -9:
        raise SystemExit(f"FATAL [{scenario}/{index}]: Process A did not die by SIGKILL (exit={a['exit_code']})")
    pid_a = a["runner_observed_pid"]

    artifacts_dir = workdir / "artifacts"
    mission_dirs = sorted((artifacts_dir / "checkpoints").iterdir())
    if len(mission_dirs) != 1:
        raise SystemExit(f"FATAL [{scenario}/{index}]: expected exactly one mission")
    mission_id = mission_dirs[0].name

    ok_window, in_window, ids = validate_crash_point(artifacts_dir, evidence_dir, mission_id, scenario)
    if not ok_window:
        durable_write_json(evidence_dir / "runner_chain.json", {
            "status": "CRASH_POINT_INVALID", "scenario": scenario, "in_window": in_window,
        })
        raise SystemExit(f"FATAL [{scenario}/{index}]: crash point invalid: {json.dumps(in_window)}")

    task_d_id = ids["crash_window_task_id"]
    d_file = Path(ids["side_effect_file"])
    pre_resume = stat_snapshot(d_file)
    pre_corruption_scan = scan_journal(artifacts_dir, mission_id)

    durable_write_json(evidence_dir / "crash_window_snapshot.json", {
        "mission_id": mission_id,
        "scenario": scenario,
        "task_key": CRASH_WINDOW_TASK,
        "task_id": task_d_id,
        "side_effect_file": str(d_file),
        "snapshot_taken_at_utc": utcnow(),
        "pre_resume_side_effect_file": pre_resume,
        "pre_corruption_journal_sha256": pre_corruption_scan["sha256"],
        "pre_corruption_journal_line_status": pre_corruption_scan["line_status"],
        "crash_point_in_window": in_window,
    })
    # IDs ONLY cross the process boundary — never state objects.
    durable_write_json(evidence_dir / "resume_info.json", {
        "scenario": scenario,
        "mission_id": mission_id,
        "run_id": ids["run_id"],
        "checkpoint_id": ids["checkpoint_id"],
        "checkpoint_path": ids["checkpoint_path"],
        "process_a_pid": pid_a,
        "task_ids": ids["task_ids"],
        "crash_window_task_key": CRASH_WINDOW_TASK,
    })
    print(f"[RUNNER] {scenario}/{index}: crash point VALID; file={'present' if pre_resume else 'ABSENT'}")

    # ---- corruption injection (D scenarios), outside any participant ----
    corruption = None
    if SCENARIO_CORRUPTION[scenario]:
        corruption = apply_corruption(artifacts_dir, evidence_dir, mission_id, scenario, ids["task_ids"])
        post_corr = scan_journal(artifacts_dir, mission_id)
        corruption["journal_line_status_after"] = post_corr["line_status"]
        corruption["journal_sha256_after_rescan"] = post_corr["sha256"]
        print(f"[RUNNER] {scenario}/{index}: corruption applied: {corruption['kind']}")

    # ---- PROCESS B: new OS process, resume through the boundary ----
    b = run_stage(f"{scenario}_C{index}_PROCESS_B", "e10cw1r1_process_b.py", workdir, scenario)
    if b["exit_code"] != 0:
        raise SystemExit(f"FATAL [{scenario}/{index}]: Process B failed (exit={b['exit_code']})")
    pid_b = b["runner_observed_pid"]
    if pid_b == pid_a:
        raise SystemExit(f"FATAL [{scenario}/{index}]: PID_B == PID_A")

    post_resume = stat_snapshot(d_file)
    post_scan = scan_journal(artifacts_dir, mission_id)

    # ---- INDEPENDENT VERIFIER ----
    v = run_stage(f"{scenario}_C{index}_VERIFIER", "e10cw1r1_verifier.py", workdir, scenario)
    if v["exit_code"] != 0:
        raise SystemExit(f"FATAL [{scenario}/{index}]: verifier failed (exit={v['exit_code']})")

    chain_record = {
        "scenario": scenario,
        "chain_index": index,
        "workdir": str(workdir),
        "process_a": {
            "runner_observed_pid": pid_a,
            "exit_code": a["exit_code"],
            "termination_reason": a["termination_reason"],
            "started_at_utc": a["started_at_utc"],
            "ended_at_utc": a["ended_at_utc"],
        },
        "process_b": {
            "runner_observed_pid": pid_b,
            "exit_code": b["exit_code"],
        },
        "verifier": {"runner_observed_pid": v["runner_observed_pid"], "exit_code": v["exit_code"]},
        "pid_difference": pid_b != pid_a,
        "crash_point_in_window": in_window,
        "corruption": {k: corruption[k] for k in ("kind", "position", "journal_sha256_before", "journal_sha256_after")} if corruption else None,
        "side_effect_file": {
            "pre_resume": pre_resume,
            "post_resume": post_resume,
            "no_physical_rewrite": bool(
                pre_resume and post_resume
                and pre_resume["mtime_ns"] == post_resume["mtime_ns"]
                and pre_resume["inode"] == post_resume["inode"]
                and pre_resume["sha256"] == post_resume["sha256"]
            ) if pre_resume else None,
        },
        "journal_sha256": {
            "pre_corruption": pre_corruption_scan["sha256"],
            "post_resume": post_scan["sha256"],
        },
        "status": "SCENARIO_VERIFIED",
    }

    def _append(rec: dict) -> None:
        chains_path = session / "evidence" / "chains.jsonl"
        chains_path.parent.mkdir(parents=True, exist_ok=True)
        with open(chains_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

    _append(chain_record)
    print(f"[RUNNER] {scenario}/{index}: VERIFIED (pids A={pid_a} B={pid_b})")
    return chain_record


def main() -> int:
    started_at_utc = utcnow()
    t0 = time.time()
    n_chains = 2
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].split(",")

    session = Path(tempfile.mkdtemp(prefix="e10cw1r1_"))
    (session / "evidence").mkdir(parents=True, exist_ok=True)
    print(f"[RUNNER] session={session} chains_per_scenario={n_chains}")

    chains = []
    failed = []
    for scenario in SCENARIOS:
        if only and scenario not in only:
            continue
        for i in range(1, n_chains + 1):
            try:
                chains.append(run_chain(session, scenario, i))
            except SystemExit as e:
                failed.append({"scenario": scenario, "chain": i, "error": str(e)})
                print(f"[RUNNER] FAILED: {scenario}/{i}: {e}")
                break  # no point running chain 2 of a broken scenario

    by_scenario: dict = {}
    for c in chains:
        by_scenario.setdefault(c["scenario"], []).append(c)
    scenario_summaries = {
        s: {
            "chains": len(v),
            "all_verified": all(c["status"] == "SCENARIO_VERIFIED" for c in v),
            "pids": [(c["process_a"]["runner_observed_pid"], c["process_b"]["runner_observed_pid"]) for c in v],
        } for s, v in by_scenario.items()
    }
    consolidated = {
        "status": "E10_CW1_R1_CHAINS_COMPLETE" if not failed and len(by_scenario) == len(SCENARIOS)
        else "E10_CW1_R1_INCOMPLETE",
        "scenarios": SCENARIOS,
        "runner_pid": os.getpid(),
        "started_at_utc": started_at_utc,
        "consolidated_at_utc": utcnow(),
        "session": str(session),
        "scenario_summaries": scenario_summaries,
        "failed": failed,
        "total_wall_seconds": round(time.time() - t0, 3),
    }
    durable_write_json(session / "evidence" / "runner.json", consolidated)
    print(f"\n[RUNNER] {consolidated['status']}")
    for s, summ in scenario_summaries.items():
        print(f"[RUNNER]   {s}: chains={summ['chains']} all_verified={summ['all_verified']}")
    for f in failed:
        print(f"[RUNNER]   FAILED {f['scenario']}/{f['chain']}: {f['error'][:200]}")
    return 0 if not failed and len(by_scenario) == len(SCENARIOS) else 1


if __name__ == "__main__":
    sys.exit(main())
