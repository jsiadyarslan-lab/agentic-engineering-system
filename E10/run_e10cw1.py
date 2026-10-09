#!/usr/bin/env python3
"""E10-CW1 RUNNER — orchestrates the crash-window proof as REAL OS processes.

    [RUNNER pid R]  (one session = N consecutive chains; default 2)
       per chain:
       |-- subprocess A  (e10cw1_process_a.py chaindir)  -> SIGKILLed (-9)
       |      dies INSIDE the crash window: after TASK_D's governed side
       |      effect + its fsynced journal record, before any durable
       |      record of TASK_D's completion.
       |-- RUNNER post-crash witnesses (outside any participant):
       |      * locates the mission + latest durable checkpoint
       |      * validates the crash point (in-window, not after completion)
       |      * snapshots the side-effect file (sha256/mtime_ns/inode)
       |      * writes resume_info.json (IDs ONLY — no state objects)
       |-- subprocess B  (e10cw1_process_b.py chaindir)  -> exit 0
       |      restores from durable storage only; TASK_D re-executes and
       |      must reconcile (fixed) — or re-perform the write (baseline).
       |-- RUNNER post-resume witness: re-stats the side-effect file and
       |      compares mtime_ns/inode/sha256 with the pre-resume snapshot.
       `-- subprocess V  (e10cw1_verifier.py chaindir)  -> exit 0 (fixed mode)

    Modes:
      fixed     — against the E10-CW1 fix (default). Success requires the
                  side effect NOT re-performed (mtime_ns/inode unchanged).
      baseline  — against pre-fix code (gap demonstration). Success means
                  the gap is DEMONSTRATED: the physical write re-performed
                  (mtime_ns changed by the resume). This documents the
                  pre-existing failure the order targets (section 7), never
                  as a pass of E10-18.

    Timing fields are honest (E10-CW1 order section 8): started_at_utc is
    captured at the runner's actual start; consolidated_at_utc at the end.
"""
from __future__ import annotations

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
from e10cw1_common import (  # noqa: E402
    CRASH_WINDOW_TASK, journal_index, read_journal, side_effect_file,
    stat_snapshot,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_stage(name: str, script: str, workdir: Path):
    cmd = [sys.executable, str(HERE / script), str(workdir)]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pid = proc.pid
    out, _ = proc.communicate()
    rc = proc.returncode
    wall = round(time.time() - t0, 3)
    print(f"\n{'=' * 78}\n[{name}] pid={pid} exit={rc} wall={wall}s\n{'=' * 78}")
    print(out)
    return {
        "stage": name,
        "script": script,
        "command": cmd,
        "runner_observed_pid": pid,
        "exit_code": rc,
        "wall_seconds": wall,
        "started_at_utc": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
        "ended_at_utc": datetime.fromtimestamp(t0 + wall, tz=timezone.utc).isoformat(),
        "termination_reason": (
            "SIGKILL (external, runner-observed)" if rc == -9
            else "exit" if rc == 0 else "failure"
        ),
        "stdout_tail": out[-2500:],
    }


def load_events(artifacts_dir: Path, mission_id: str):
    p = artifacts_dir / "events" / mission_id / "event_log.jsonl"
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
    """key -> task_id from DURABLE records only.

    Task names carry the scenario key (e10_common TaskSpec: name=f"{key} - {desc}").
    Sources: the checkpoint's task_definitions names and the TASK_CREATED
    event payloads (both durable, both engine-written).
    """
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


def validate_crash_point(artifacts_dir: Path, evidence_dir: Path, mission_id: str, mode: str):
    """Runner-side proof that the kill landed INSIDE the crash window."""
    events = load_events(artifacts_dir, mission_id)
    cp = latest_checkpoint(artifacts_dir, mission_id)

    key_to_task = key_to_task_from_durable(cp, events)
    if set(key_to_task) != {"TASK_A", "TASK_B", "TASK_C", "TASK_D", "TASK_E"}:
        return False, {"key_mapping_incomplete": key_to_task}, None
    task_to_key = {v: k for k, v in key_to_task.items()}
    task_d_id = key_to_task[CRASH_WINDOW_TASK]
    d_rel_path = "task_d_output.txt"
    d_file = side_effect_file(artifacts_dir, f"sandbox-{task_d_id}", d_rel_path)

    injection = json.loads((evidence_dir / "injection.json").read_text())
    d_completed_events = [
        e for e in events
        if e["event_type"] == "task.completed" and e.get("correlation_id") == task_d_id
    ]

    cp_states = {task_to_key.get(t, t): s for t, s in cp["task_states"].items()}
    in_window = {
        "injection_reached": bool(injection.get("reached_at_utc")),
        "injection_task_is_crash_window_task": injection.get("task_id") == task_d_id,
        "last_checkpoint_states": cp_states,
        "crash_window_task_not_completed_in_checkpoint": cp_states.get(CRASH_WINDOW_TASK) not in (
            "COMPLETED", "FAILED", "CANCELLED"
        ),
        "completed_tasks_in_checkpoint": all(
            cp_states.get(k) == "COMPLETED" for k in ("TASK_A", "TASK_B", "TASK_C")
        ),
        "no_durable_task_completed_for_crash_window_task": len(d_completed_events) == 0,
        "side_effect_file_exists": d_file.exists(),
    }

    journal_records = read_journal(artifacts_dir, mission_id)
    jidx = journal_index(journal_records)
    d_journal = jidx.get((task_d_id, d_rel_path), [])
    d_performed = [r for r in d_journal if r["record_type"] == "performed"]

    if mode == "fixed":
        in_window["journal_performed_exists"] = len(d_performed) == 1
        in_window["journal_recorded_before_kill"] = bool(
            d_performed
            and injection.get("reached_at_utc")
            and d_performed[0].get("recorded_at_utc", "") <= injection["reached_at_utc"]
        )
        in_window["checkpoint_covers_no_completion_for_crash_window_task"] = (
            cp_states.get(CRASH_WINDOW_TASK) != "COMPLETED"
        )
        valid = (
            in_window["injection_reached"]
            and in_window["injection_task_is_crash_window_task"]
            and in_window["crash_window_task_not_completed_in_checkpoint"]
            and in_window["completed_tasks_in_checkpoint"]
            and in_window["no_durable_task_completed_for_crash_window_task"]
            and in_window["side_effect_file_exists"]
            and in_window["journal_performed_exists"]
            and in_window["journal_recorded_before_kill"]
        )
    else:
        # baseline: no journal exists (pre-fix code) — the crash point is
        # proven by the injection marker + file existence + not-completed.
        in_window["journal_absent_as_expected"] = len(journal_records) == 0
        valid = (
            in_window["injection_reached"]
            and in_window["injection_task_is_crash_window_task"]
            and in_window["crash_window_task_not_completed_in_checkpoint"]
            and in_window["completed_tasks_in_checkpoint"]
            and in_window["no_durable_task_completed_for_crash_window_task"]
            and in_window["side_effect_file_exists"]
            and in_window["journal_absent_as_expected"]
        )

    return valid, in_window, {
        "mission_id": mission_id,
        "run_id": cp["run_id"],
        "checkpoint_id": cp["checkpoint_id"],
        "checkpoint_path": cp["__path"],
        "task_ids": key_to_task,
        "crash_window_task_id": task_d_id,
        "side_effect_file": str(d_file),
        "journal_performed_record": d_performed[0] if d_performed else None,
        "injection": injection,
    }


def run_chain(session: Path, index: int, mode: str) -> dict:
    workdir = session / f"chain{index}"
    evidence_dir = workdir / "evidence"
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"\n{'#' * 78}\n[RUNNER] chain {index} mode={mode} workdir={workdir}\n{'#' * 78}")

    # ---- PROCESS A: execute A/B/C, start D, die inside the crash window ----
    a = run_stage(f"CHAIN{index}_PROCESS_A", "e10cw1_process_a.py", workdir)
    if a["exit_code"] != -9:
        print(f"[RUNNER] FATAL: Process A did not die by SIGKILL (exit={a['exit_code']})")
        raise SystemExit(2)
    pid_a = a["runner_observed_pid"]

    # ---- post-crash witnesses (outside any participant process) ----
    artifacts_dir = workdir / "artifacts"
    mission_dirs = sorted((artifacts_dir / "checkpoints").iterdir())
    if len(mission_dirs) != 1:
        raise SystemExit(f"FATAL: expected exactly one mission, found {len(mission_dirs)}")
    mission_id = mission_dirs[0].name

    ok_window, in_window, ids = validate_crash_point(artifacts_dir, evidence_dir, mission_id, mode)
    if not ok_window:
        durable_write_json(evidence_dir / "runner_chain.json", {
            "status": "CRASH_POINT_INVALID", "mode": mode, "in_window": in_window,
        })
        raise SystemExit(f"FATAL: crash point invalid: {json.dumps(in_window)}")

    task_d_id = ids["crash_window_task_id"]
    d_file = Path(ids["side_effect_file"])
    pre_resume = stat_snapshot(d_file)
    if pre_resume is None:
        raise SystemExit("FATAL: side-effect file vanished before snapshot")

    durable_write_json(evidence_dir / "crash_window_snapshot.json", {
        "mission_id": mission_id,
        "task_key": CRASH_WINDOW_TASK,
        "task_id": task_d_id,
        "side_effect_file": str(d_file),
        "snapshot_taken_at_utc": utcnow(),
        "pre_resume_side_effect_file": pre_resume,
        "journal_performed_record": ids["journal_performed_record"],
        "injection": ids["injection"],
        "crash_point_in_window": in_window,
    })
    # IDs ONLY cross the process boundary — never state objects.
    durable_write_json(evidence_dir / "resume_info.json", {
        "mode": mode,
        "mission_id": mission_id,
        "run_id": ids["run_id"],
        "checkpoint_id": ids["checkpoint_id"],
        "checkpoint_path": ids["checkpoint_path"],
        "process_a_pid": pid_a,
        "task_ids": ids["task_ids"],
        "crash_window_task_key": CRASH_WINDOW_TASK,
    })
    print(f"[RUNNER] chain {index}: crash point VALID (in-window); snapshot mtime_ns={pre_resume['mtime_ns']}")

    # ---- PROCESS B: new OS process, restore + resume through the window ----
    b = run_stage(f"CHAIN{index}_PROCESS_B", "e10cw1_process_b.py", workdir)
    if b["exit_code"] != 0:
        raise SystemExit(3)
    pid_b = b["runner_observed_pid"]
    if pid_b == pid_a:
        raise SystemExit(4)

    # ---- post-resume witness: was the physical write re-performed? ----
    post_resume = stat_snapshot(d_file)
    no_physical_rewrite = bool(
        post_resume
        and post_resume["mtime_ns"] == pre_resume["mtime_ns"]
        and post_resume["inode"] == pre_resume["inode"]
        and post_resume["sha256"] == pre_resume["sha256"]
    )
    if mode == "fixed" and not no_physical_rewrite:
        durable_write_json(evidence_dir / "runner_chain.json", {
            "status": "SIDE_EFFECT_RE_PERFORMED", "mode": mode,
            "pre_resume": pre_resume, "post_resume": post_resume,
        })
        raise SystemExit("FATAL: crash-window side effect was re-performed after resume")
    if mode == "baseline" and no_physical_rewrite:
        raise SystemExit("FATAL: baseline demo expected a duplicate write but file was untouched")

    # ---- chain record: appended BEFORE the verifier runs (the verifier
    # identifies its own chain as the LAST record and checks prior chains
    # for repeatability); rewritten after with the verifier exit code. ----
    chain_record = {
        "chain_index": index,
        "mode": mode,
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
        "pid_difference": pid_b != pid_a,
        "crash_point_in_window": in_window,
        "side_effect_file": {
            "pre_resume": pre_resume,
            "post_resume": post_resume,
            "no_physical_rewrite": no_physical_rewrite,
        },
        "verifier_exit_code": None,
        "status": (
            "GAP_DEMONSTRATED" if mode == "baseline"
            else "CRASH_WINDOW_IDEMPOTENT"
        ),
    }

    def _append_chain_record(rec: dict) -> None:
        chains_path = session / "evidence" / "chains.jsonl"
        with open(chains_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _rewrite_last_chain_record(rec: dict) -> None:
        chains_path = session / "evidence" / "chains.jsonl"
        lines = [l for l in chains_path.read_text().splitlines() if l.strip()]
        if lines:
            lines[-1] = json.dumps(rec, default=str)
        with open(chains_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())

    _append_chain_record(chain_record)

    # ---- INDEPENDENT VERIFIER (fixed mode only) ----
    v = None
    if mode == "fixed":
        v = run_stage(f"CHAIN{index}_VERIFIER", "e10cw1_verifier.py", workdir)
        if v["exit_code"] != 0:
            raise SystemExit(6)
        chain_record["verifier_exit_code"] = v["exit_code"]
        _rewrite_last_chain_record(chain_record)

    print(f"[RUNNER] chain {index}: no_physical_rewrite={no_physical_rewrite} -> {chain_record['status']}")
    return chain_record


def main() -> int:
    # E10-CW1 section 8: honest timing fields — captured at the actual moments.
    started_at_utc = utcnow()
    t0 = time.time()
    mode = "fixed"
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if mode not in ("fixed", "baseline"):
        raise SystemExit(f"unknown mode: {mode}")
    n_chains = 2

    session = Path(tempfile.mkdtemp(prefix=f"e10cw1_{mode}_"))
    (session / "evidence").mkdir(parents=True, exist_ok=True)
    print(f"[RUNNER] session={session} mode={mode} chains={n_chains}")

    chains = [run_chain(session, i + 1, mode) for i in range(n_chains)]

    consolidated = {
        "status": (
            "E10_CW1_GAP_DEMONSTRATED" if mode == "baseline"
            else "E10_CW1_CHAIN_COMPLETE"
        ),
        "mode": mode,
        "runner_pid": os.getpid(),
        "started_at_utc": started_at_utc,
        "consolidated_at_utc": utcnow(),
        "session": str(session),
        "chains": chains,
        "all_chains_no_physical_rewrite": all(
            c["side_effect_file"]["no_physical_rewrite"] for c in chains
        ),
        "pid_differences": [c["pid_difference"] for c in chains],
        "total_wall_seconds": round(time.time() - t0, 3),
    }
    durable_write_json(session / "evidence" / "runner.json", consolidated)

    print(f"\n[RUNNER] {consolidated['status']} ({n_chains} chains, {mode} mode)")
    for c in chains:
        print(f"[RUNNER] chain {c['chain_index']}: {c['status']} "
              f"(no_physical_rewrite={c['side_effect_file']['no_physical_rewrite']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
