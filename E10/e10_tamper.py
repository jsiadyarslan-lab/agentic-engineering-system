#!/usr/bin/env python3
"""E10 TAMPER TEST (E10 sections 7 / 25) — negative test on a COPY of the
durable state:

    valid checkpoint (from Process A)
      -> mutate ONE durable field on disk (step: 3 -> 999)
      -> new process attempts resume
      -> integrity check FAILS
      -> RESUME REJECTED
      -> NO task execution

The original durable tree is untouched (the runner passes a copied workdir).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e10_common import build_engine, durable_write_json  # noqa: E402


def main(workdir: str) -> None:
    work = Path(workdir)
    artifacts_dir = work / "artifacts"
    evidence_dir = work / "evidence"

    pid = os.getpid()
    print(f"[TAMPER] pid={pid} workdir={workdir}")

    resume_info = json.loads((evidence_dir / "resume_info.json").read_text())
    mission_id = resume_info["mission_id"]
    checkpoint_id = resume_info["checkpoint_id"]
    original_hash = resume_info["checkpoint_hash"]

    cp_path = Path(artifacts_dir) / "checkpoints" / mission_id / f"{checkpoint_id}.json"

    # --- mutate one durable field: the checkpoint step ---
    data = json.loads(cp_path.read_text())
    original_step = data["step"]
    data["step"] = 999  # tampered durable field (hash NOT recomputed)
    with open(cp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"[TAMPER] mutated step: {original_step} -> 999 in {cp_path}")

    # --- new process resume attempt on the tampered checkpoint ---
    engine = build_engine(artifacts_dir)

    import hashlib
    tampered_bytes = cp_path.read_bytes()
    tampered_file_sha = hashlib.sha256(tampered_bytes).hexdigest()

    resume_result = "UNEXPECTED_SUCCESS"
    rejection_reason = ""
    try:
        engine.resume_from_checkpoint(checkpoint_id, mission_id)
        # reaching here means the integrity gate FAILED to reject
    except Exception as e:  # noqa: BLE001 — record the exact rejection
        resume_result = "REJECTED"
        rejection_reason = f"{type(e).__name__}: {e}"

    # --- no task execution may have started ---
    attempts_created = len(engine.attempts)
    task_graphs = len(engine.task_graph)
    started_events = [
        e for e in engine.event_bus.history
        if e.event_type.value == "TASK_STARTED"
    ]
    no_task_execution = (
        attempts_created == 0 and task_graphs == 0 and len(started_events) == 0
    )

    # recompute the canonical hash of the tampered payload for the record
    tampered_data = json.loads(cp_path.read_text())
    canonical = json.dumps(
        {k: v for k, v in tampered_data.items() if k != "hash"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    mutated_recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    verdict = {
        "status": "TAMPER_TEST_COMPLETE",
        "checkpoint_id": checkpoint_id,
        "mission_id": mission_id,
        "original_hash": original_hash,
        "tampered_stored_hash": tampered_data.get("hash"),
        "mutated_recomputed_hash": mutated_recomputed,
        "detected_mismatch": mutated_recomputed != tampered_data.get("hash"),
        "resume_result": resume_result,
        "rejection_reason": rejection_reason,
        "no_task_execution": no_task_execution,
        "attempts_created": attempts_created,
        "task_graphs_created": task_graphs,
        "task_started_events": len(started_events),
        "tampered_file_sha256": tampered_file_sha,
    }
    durable_write_json(evidence_dir / "tamper.json", verdict)
    print(f"[TAMPER] resume_result={resume_result} mismatch_detected={verdict['detected_mismatch']} no_execution={no_task_execution}")

    if not (resume_result == "REJECTED" and verdict["detected_mismatch"] and no_task_execution):
        raise SystemExit("TAMPER TEST FAILED: tampered checkpoint was not fully rejected")


if __name__ == "__main__":
    main(sys.argv[1])
