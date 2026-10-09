#!/usr/bin/env python3
"""E10-RP INDEPENDENT VERIFIER — a real separate OS process.

Reads ONLY persistent state (no engine import, no in-memory state):
  evidence/*.json                      (phase records + pre-registered expectations)
  main_artifacts/  s2_artifacts/       (engine durable trees)
  main_mc_state/   s2_mc_state/        (controller ledgers)

Re-derives the full causal chain from raw durable records and asserts it
against the PRE-REGISTERED expectations. Exit 0 == all checks VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SESSION = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def jload(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_events(mission_artifacts: Path) -> List[Dict[str, Any]]:
    """All event logs under a mission artifacts tree, chronological."""
    out: List[Dict[str, Any]] = []
    for f in sorted((mission_artifacts / "events").glob("*/event_log.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    out.sort(key=lambda e: e.get("timestamp") or "")
    return out


def load_journal(mission_artifacts: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for f in sorted((mission_artifacts / "side_effect_journal").glob("*/journal.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_ledger(mc_state: Path) -> Dict[str, Any]:
    files = sorted((mc_state / "mission_controller").glob("*/ledger.json"))
    assert files, f"no ledger under {mc_state}"
    return jload(files[0])


def load_final_checkpoint(mission_artifacts: Path) -> Dict[str, Any]:
    cps = []
    for f in sorted((mission_artifacts / "checkpoints").glob("*/checkpoint-*.json")):
        cps.append((f.stat().st_mtime, f, jload(f)))
    assert cps, "no checkpoints"
    cps.sort(key=lambda t: t[0])
    return cps[-1][2]


def sandbox_file(mission_artifacts: Path, path: str) -> Optional[Path]:
    for cand in sorted((mission_artifacts).glob(f"sandbox-task-*/{path}")):
        if cand.exists():
            return cand
    return None


class Check:
    def __init__(self, name: str):
        self.name = name
        self.problems: List[str] = []
        self.facts: Dict[str, Any] = {}

    def expect(self, cond: bool, msg: str) -> None:
        if not cond:
            self.problems.append(msg)

    def done(self) -> Dict[str, Any]:
        return {
            "check": self.name,
            "verdict": "VERIFIED" if not self.problems else "FAILED",
            "problems": self.problems,
            "facts": self.facts,
        }


def verify_main(expectations: Dict[str, Any], scen: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    art = SESSION / "main_artifacts"
    events = load_events(art)
    journal = load_journal(art)
    ledger = load_ledger(SESSION / "main_mc_state")
    exp = expectations["main"]
    exp_s1 = expectations["s1_insufficient_evidence"]

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        by_type.setdefault(e["event_type"], []).append(e)
    # E10 lesson (E10 phase-1): this engine never emits task.started —
    # TASK_ASSIGNED is the real execution-start marker.
    task_created = by_type.get("task.created", [])
    task_started = by_type.get("task.assigned", [])
    task_completed = by_type.get("task.completed", [])
    task_failed = by_type.get("task.failed", [])
    plan_reviews = [
        e for e in by_type.get("state.transition", [])
        if isinstance(e.get("payload"), dict) and e["payload"].get("entity_type") == "plan_review"
    ]
    markers = {
        e["payload"]["trigger"]: e
        for e in by_type.get("state.transition", [])
        if isinstance(e.get("payload"), dict)
        and str(e["payload"].get("trigger", "")).startswith("E10RP")
    }

    # task_key -> task_id: the engine's task.created payload carries no
    # task_key, so the durable source is the controller ledger key_map
    # (written by _persist_ledger on every decision).
    key_of: Dict[str, str] = {k: v for k, v in ledger.get("key_map", {}).items() if k}
    id_by_key: Dict[str, str] = {v: k for k, v in key_of.items()}

    # ---- V1 plan v1 definition (from raw event log) ----
    # plan v1 = the tasks that existed BEFORE the replan decision marker;
    # X exists only after the replan, so it must be absent from plan v1.
    c = Check("V1_plan_v1_definition")
    t_replan = markers["E10RP_REPLAN_DECISION"]["timestamp"]
    pre_replan_created = [
        e for e in task_created if (e.get("timestamp") or "") < t_replan
    ]
    v1_keys = {id_by_key.get(e["payload"].get("task_id"), e["payload"].get("task_id"))
               for e in pre_replan_created if isinstance(e.get("payload"), dict)}
    c.facts["plan_v1_tasks"] = sorted(v1_keys)
    c.expect(sorted(v1_keys) == ["A", "B", "C", "D", "E"], f"plan v1 tasks: {sorted(v1_keys)}")
    x_id = key_of.get("X", "")
    c.expect(x_id and all(
        (e.get("timestamp") or "") >= t_replan
        for e in task_created
        if isinstance(e.get("payload"), dict) and e["payload"].get("task_id") == x_id
    ), "X may only be created after the replan decision")
    c_p = next((e for e in pre_replan_created if isinstance(e.get("payload"), dict)
                and any("E10RP_C_PLAN_V1_EXPECTED" in x
                        for x in e["payload"].get("acceptance_criteria", []))), None)
    c.expect(c_p is not None, "no plan-v1 task carries the plan assumption criteria")
    if c_p:
        c.expect(id_by_key.get(c_p["payload"].get("task_id")) == "C",
                 "the task carrying the plan-v1 assumption must be C")
        c.facts["c_criteria_v1"] = c_p["payload"].get("acceptance_criteria")
    results.append(c.done())

    # ---- V2 review chain (durable, ordered) ----
    c = Check("V2_review_chain")
    seq = [(p["payload"].get("entity_id"), p["payload"].get("to_state"), p["payload"].get("review_id"))
           for p in plan_reviews]
    c.facts["review_events"] = seq
    c.expect(seq[0][:2] == ("v1", "APPROVED"), f"first review must be v1 APPROVED: {seq}")
    c.expect([s[:2] for s in seq[1:]] == [("v2", "REJECTED"), ("v2", "APPROVED")],
             f"v2 reviews must be REJECTED then APPROVED: {seq}")
    first_started = task_started[0]["timestamp"] if task_started else None
    c.expect(first_started is not None and seq[0][2] is not None
             and plan_reviews[0]["timestamp"] <= first_started,
             "v1 review must precede the first task execution")
    # ledger reviews agree with the events
    lr = [(r["plan_version"], r["verdict"]) for r in ledger.get("plan_reviews", [])]
    c.expect(lr == [("v1", "approved"), ("v2", "rejected"), ("v2", "approved")],
             f"ledger reviews: {lr}")
    c.facts["ledger_reviews"] = lr
    results.append(c.done())

    # ---- V3 phase 1 execution + deviation evidence (pre-replan window) ----
    c = Check("V3_phase1_deviation_evidence")
    t_replan_v3 = markers["E10RP_REPLAN_DECISION"]["timestamp"]
    p1_started = [e for e in task_started if (e.get("timestamp") or "") < t_replan_v3]
    p1_completed = [e for e in task_completed if (e.get("timestamp") or "") < t_replan_v3]
    started_keys = {id_by_key.get(e["correlation_id"], e["correlation_id"]) for e in p1_started}
    completed_keys = {id_by_key.get(e["correlation_id"], e["correlation_id"]) for e in p1_completed}
    c.facts["started"] = sorted(started_keys)
    c.facts["completed"] = sorted(completed_keys)
    c.expect("A" in completed_keys and "B" in completed_keys, "A,B must complete in phase 1")
    c.expect("D" not in started_keys and "E" not in started_keys,
             "D,E must never start (blocked by the deviation)")
    c.expect("X" not in started_keys, "X must not exist before the replan")
    c_id = key_of.get("C", "")
    c_fail = next((e for e in task_failed if e.get("correlation_id") == c_id), None)
    c.expect(c_fail is not None, "C TASK_FAILED missing")
    if c_fail:
        err = str(c_fail["payload"].get("error", ""))
        c.expect("Verification failed: not_evidenced" in err, f"C failure must be not_evidenced: {err}")
        c.facts["c_error"] = err
    c.expect(scen["phase1"]["agent_claim_overturned"]["verifier_verdict"] == "not_evidenced",
             "S1b: agent claim overturned by verifier")
    c.expect(exp_s1["agent_claim_success_overturned_by_verification"] is True, "S1b expectation")
    results.append(c.done())

    # ---- V4 causality windows (evidence -> decision -> review -> continuation) ----
    c = Check("V4_causality_windows")
    replan_marker = markers.get("E10RP_REPLAN_DECISION")
    approved_marker = markers.get("E10RP_CONTINUATION_APPROVED")
    deviation_marker = markers.get("E10RP_DEVIATION_OBSERVED")
    c.expect(deviation_marker is not None and replan_marker is not None
             and approved_marker is not None, f"markers: {sorted(markers)}")
    if deviation_marker and replan_marker and approved_marker:
        t_dev = deviation_marker["timestamp"]
        t_replan = replan_marker["timestamp"]
        t_approved_review = next(p["timestamp"] for p in plan_reviews
                                 if p["payload"].get("to_state") == "APPROVED"
                                 and p["payload"].get("entity_id") == "v2")
        t_cont = approved_marker["timestamp"]
        c.expect(t_dev < t_replan, "deviation observed before replan decision")
        # NOTHING may execute between the replan decision and the v2 approval
        started_between = [
            e for e in task_started if t_replan < e["timestamp"] < t_approved_review
        ]
        c.expect(not started_between,
                 f"gate: zero execution between replan and v2 approval: {len(started_between)}")
        c.facts["task_started_between_replan_and_approval"] = len(started_between)
        # continuation only after approval
        started_after = [e for e in task_started if e["timestamp"] > t_replan]
        c.expect(all(e["timestamp"] >= t_approved_review for e in started_after),
                 "every post-replan execution must follow the v2 approval")
        c.expect(t_cont >= t_approved_review, "continuation marker after approval")
        c.facts["post_replan_started"] = sorted(
            {id_by_key.get(e["correlation_id"], e["correlation_id"]) for e in started_after}
        )
        c.expect(c.facts["post_replan_started"] == ["C", "E", "X"],
                 f"phase 2 executes exactly C,X,E: {c.facts['post_replan_started']}")
        c.expect("A" not in c.facts["post_replan_started"]
                 and "B" not in c.facts["post_replan_started"],
                 "A,B must never be re-executed")
    results.append(c.done())

    # ---- V5 ledger decision chain (failures -> replans -> reviews) ----
    c = Check("V5_ledger_decision_chain")
    c.expect(ledger.get("plan_version") == "v2", f"final plan_version: {ledger.get('plan_version')}")
    reps = ledger.get("replans", [])
    c.expect(len(reps) == 1, f"exactly one replan: {len(reps)}")
    r = reps[0] if reps else {}
    c.facts["replan"] = {k: r.get(k) for k in
                         ("from_version", "to_version", "invalidated_tasks", "preserved_tasks",
                          "added_tasks", "rewired_dependencies", "modified_tasks")}
    c.expect(r.get("from_version") == "v1" and r.get("to_version") == "v2", "v1 -> v2")
    c.expect(r.get("invalidated_tasks") == exp["replan_v1_to_v2"]["invalidated"], "invalidated D only")
    c.expect(r.get("preserved_tasks") == exp["replan_v1_to_v2"]["preserved"], "preserved A,B")
    c.expect([a.get("task_key") for a in r.get("added_tasks", [])] == ["X"], "added X")
    c.expect([w.get("task_key") for w in r.get("rewired_dependencies", [])] == ["E"], "rewired E")
    c.expect([m.get("task_key") for m in r.get("modified_tasks", [])] == ["C"], "modified C")
    c.expect(bool(r.get("evidence")), "replan carries evidence")
    # deviation record resolved by THIS replan with the SAME evidence
    dev_failures = [f for f in ledger.get("failures", [])
                     if f.get("kind") == "plan_deviation"]
    c.expect(len(dev_failures) == 1, f"exactly one plan_deviation: {len(dev_failures)}")
    if dev_failures:
        f = dev_failures[0]
        c.facts["deviation"] = {k: f.get(k) for k in
                                ("task_key", "kind", "recovery_action", "resolved_by", "evidence")}
        c.expect(f.get("task_key") == "C", "deviation at C")
        c.expect(f.get("recovery_action") == "replan", "recovery replan")
        c.expect(f.get("resolved_by") == "replan->v2", f"resolved_by: {f.get('resolved_by')}")
        c.expect(list(f.get("evidence", [])) == list(r.get("evidence", [])),
                 "replan evidence == deviation evidence (causal carry)")
    # every ledger failure is backed by a real TASK_FAILED event (S1: no
    # unevidenced classification can enter the durable record)
    for f in ledger.get("failures", []):
        tid = f.get("task_id", "")
        backed = any(e.get("correlation_id") == tid for e in task_failed)
        c.expect(backed, f"failure {f.get('failure_id')} has no TASK_FAILED event — unevidenced!")
    # S1 recorded facts agree
    s1 = scen.get("s1_insufficient_evidence", {})
    c.expect(s1.get("claim_without_failure_record_is_classified") is False
             and exp_s1["claim_without_failure_record_is_classified"] is False,
             "S1: claim without record not classified")
    results.append(c.done())

    # ---- V6 journal: side effects exactly-once; C adopted without rewrite ----
    c = Check("V6_journal_side_effects")
    j_by_path: Dict[str, List[Dict[str, Any]]] = {}
    for rec in journal:
        j_by_path.setdefault(rec["path"], []).append(rec)
    c.facts["journal_types_by_path"] = {p: [r["record_type"] for r in recs]
                                        for p, recs in j_by_path.items()}
    c.expect([r["record_type"] for r in j_by_path.get("task_a.txt", [])] == ["intent", "performed"],
             "A: intent+performed only (never re-executed)")
    c.expect([r["record_type"] for r in j_by_path.get("task_b.txt", [])] == ["intent", "performed"],
             "B: intent+performed only")
    jc = j_by_path.get("task_c.txt", [])
    c.expect([r["record_type"] for r in jc] == ["intent", "performed", "reconciled"],
             f"C: intent+performed+reconciled: {[r['record_type'] for r in jc]}")
    if len(jc) == 3:
        perf, recon = jc[1], jc[2]
        c.expect(recon["mtime_ns"] == perf["mtime_ns"] and recon["inode"] == perf["inode"]
                 and recon["artifact_id"] == perf["artifact_id"],
                 "C re-execution ADOPTED the performed effect (no rewrite)")
    c.expect("task_d.txt" not in j_by_path, "D never performed any side effect (journal empty)")
    c.expect([r["record_type"] for r in j_by_path.get("task_x.txt", [])] == ["intent", "performed"],
             "X: intent+performed once")
    c.expect([r["record_type"] for r in j_by_path.get("task_e.txt", [])] == ["intent", "performed"],
             "E: intent+performed once")
    # no path has more than one intent or more than one effective-origin write
    for p, recs in j_by_path.items():
        intents = [r for r in recs if r["record_type"] == "intent"]
        c.expect(len(intents) <= 1, f"{p}: multiple intents")
    results.append(c.done())

    # ---- V7 artifacts on disk (governed sandbox files) ----
    c = Check("V7_artifacts_on_disk")
    expectations_content = {
        "task_a.txt": b"E10RP_A_OUTPUT",
        "task_b.txt": b"E10RP_B_OUTPUT",
        "task_c.txt": b"E10RP_C_REALITY_ACTUAL",
        "task_x.txt": b"E10RP_X_OUTPUT built-on E10RP_C_REALITY_ACTUAL",
        "task_e.txt": b"E10RP_E_FINAL",
    }
    for path, marker in expectations_content.items():
        f = sandbox_file(art, path)
        c.expect(f is not None, f"{path} missing on disk")
        if f:
            data = f.read_bytes()
            c.expect(marker in data, f"{path} content mismatch: {data[:80]!r}")
            jperf = next((r for r in j_by_path.get(path, [])
                          if r["record_type"] in ("performed", "reconciled")), None)
            if jperf:
                c.expect(sha256_bytes(data) == jperf["content_sha256"],
                         f"{path}: disk sha256 != journal content_sha256")
    d_file = sandbox_file(art, "task_d.txt")
    c.expect(d_file is None, "task_d.txt must NOT exist (D removed before any execution)")
    # stats agree with the phase-1 capture in the scenario record (no rewrite)
    for key, path in (("A", "task_a.txt"), ("B", "task_b.txt"), ("C", "task_c.txt")):
        f = sandbox_file(art, path)
        if f and key in scen.get("phase1", {}).get("artifact_stats", {}):
            st = f.stat()
            now = {"mtime_ns": st.st_mtime_ns, "inode": st.st_ino}
            was = scen["phase1"]["artifact_stats"][key]
            c.expect(now["mtime_ns"] == was["mtime_ns"] and now["inode"] == was["inode"],
                     f"{key}: {path} was rewritten after phase 1 (stat changed)")
    results.append(c.done())

    # ---- V8 final checkpoint + outcome ----
    c = Check("V8_final_outcome")
    cp = load_final_checkpoint(art)
    c.expect(bool(cp.get("hash")), "final checkpoint must carry an integrity hash")
    states = {k: v for k, v in cp.get("task_states", {}).items()}
    key_by_id = {tid: key for key, tid in ledger.get("key_map", {}).items()}
    cp_keys = {key_by_id.get(tid, tid): s for tid, s in states.items()}
    c.facts["final_task_states"] = cp_keys
    c.expect(sorted(cp_keys) == ["A", "B", "C", "E", "X"], f"final plan v2 tasks: {sorted(cp_keys)}")
    c.expect(all(s == "COMPLETED" for s in cp_keys.values()), f"all COMPLETED: {cp_keys}")
    c.expect("D" not in cp_keys, "D must be absent from the final plan")
    att = cp.get("attempt_history", {})
    att_counts = {key_by_id.get(tid, tid): len(v) for tid, v in att.items()}
    c.facts["attempt_counts"] = att_counts
    c.expect(att_counts.get("A") == 1 and att_counts.get("B") == 1, "A/B one attempt each")
    c.expect(att_counts.get("C") == 2, "C: failed attempt + corrected re-execution")
    c.expect(att_counts.get("X") == 1 and att_counts.get("E") == 1, "X/E once")
    vc = scen.get("verify_completion", {})
    c.expect(vc.get("passed") is True, "verify_completion must pass")
    fin = scen.get("finalize", {})
    c.expect("EVIDENCED" in str(fin), f"finalize must reach EVIDENCED: {fin}")
    # duplicate continuation: no execution after the final completion events
    dup = scen.get("duplicate_continuation", {})
    c.expect(dup.get("task_started_after") == dup.get("task_started_before"),
             "duplicate continuation started nothing")
    c.expect(dup.get("journal_counts_after") == dup.get("journal_counts_before"),
             "duplicate continuation: no new journal records")
    c.expect(dup.get("stats_identical") is True, "duplicate continuation: artifacts identical")
    results.append(c.done())

    # ---- V9 pre-registered expectations == recorded outcomes (no drift) ----
    c = Check("V9_expectation_fidelity")
    c.expect(scen["replan_v1_to_v2"]["invalidated"] == exp["replan_v1_to_v2"]["invalidated"],
             "invalidated drift")
    c.expect(scen["replan_v1_to_v2"]["preserved"] == exp["replan_v1_to_v2"]["preserved"],
             "preserved drift")
    c.expect(scen["phase1"]["states"]["C"] == "FAILED"
             and "not_evidenced" in str(scen["phase1"].get("c_error", "")),
             "C phase-1 outcome drift")
    c.expect(scen["review_v2_first"]["verdict"].lower() == exp["review_v2"]["first_verdict"].lower(),
             "first v2 review drift")
    c.expect(scen["review_v2_second"]["verdict"].lower() == exp["review_v2"]["after_recovery_verdict"].lower(),
             "second v2 review drift")
    c.expect(len(scen.get("gate_refusals", [])) == 2
             and all("PLAN_REVIEW_GATE" in g["error"] for g in scen["gate_refusals"]),
             "two gate refusals recorded")
    c.expect(scen["phase2"]["states"]["C"] == "COMPLETED"
             and scen["phase2"]["states"]["X"] == "COMPLETED"
             and scen["phase2"]["states"]["E"] == "COMPLETED", "phase-2 outcome drift")
    c.expect(scen["preservation"]["attempts_after_phase2"]["A"] == 1
             and scen["preservation"]["attempts_after_phase2"]["B"] == 1,
             "A/B never re-executed")
    results.append(c.done())
    return results


def verify_s2(expectations: Dict[str, Any], scen: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    art = SESSION / "s2_artifacts"
    events = load_events(art)
    journal = load_journal(art)
    ledger = load_ledger(SESSION / "s2_mc_state")
    exp = expectations["s2_minimal_scope"]

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        by_type.setdefault(e["event_type"], []).append(e)
    plan_reviews = [
        e for e in by_type.get("state.transition", [])
        if isinstance(e.get("payload"), dict) and e["payload"].get("entity_type") == "plan_review"
    ]
    task_failed = by_type.get("task.failed", [])

    # ---- S2-A classification: non-plan failure retried, never replanned ----
    c = Check("S2A_classification")
    lr = [(r["plan_version"], r["verdict"]) for r in ledger.get("plan_reviews", [])]
    c.facts["ledger_reviews"] = lr
    c.expect(lr == [("v1", "approved"), ("v2", "rejected"), ("v2", "approved")],
             f"review chain: {lr}")
    failures = ledger.get("failures", [])
    fB = next((f for f in failures if f.get("task_key") == "B"), None)
    fE = next((f for f in failures if f.get("task_key") == "E"), None)
    c.expect(fB is not None and fE is not None, "B and E failure records missing")
    if fB:
        c.expect(fB["kind"] == "tool_runtime_failure", f"B kind: {fB['kind']}")
        c.expect(fB["recovery_action"] == "retry", f"B recovery: {fB['recovery_action']}")
        c.expect(fB["resolved"] is True and fB["resolved_by"] == "engine_retry_then_completed",
                 f"B resolution: {fB.get('resolved_by')}")
    if fE:
        c.expect(fE["kind"] == "plan_deviation" and fE["recovery_action"] == "replan",
                 f"E classification: {fE['kind']}/{fE['recovery_action']}")
        c.expect(fE["resolved_by"] == "replan->v2", f"E resolution: {fE.get('resolved_by')}")
    # every ledger failure backed by a TASK_FAILED event
    for f in failures:
        tid = f.get("task_id", "")
        c.expect(any(e.get("correlation_id") == tid for e in task_failed),
                 f"failure {f.get('failure_id')} unevidenced (no TASK_FAILED)")
    results.append(c.done())

    # ---- S2-B minimal scope ----
    c = Check("S2B_minimal_scope")
    reps = ledger.get("replans", [])
    c.expect(len(reps) == 1, "one replan")
    r = reps[0] if reps else {}
    c.facts["replan"] = {k: r.get(k) for k in
                         ("invalidated_tasks", "preserved_tasks", "added_tasks",
                          "rewired_dependencies", "modified_tasks")}
    c.expect(r.get("invalidated_tasks") == [] == exp["replan_v1_to_v2"]["invalidated"],
             "nothing invalidated")
    c.expect(r.get("added_tasks") == [] and r.get("rewired_dependencies") == [],
             "nothing added / rewired")
    c.expect(r.get("preserved_tasks") == exp["replan_v1_to_v2"]["preserved"],
             f"preserved: {r.get('preserved_tasks')}")
    c.expect([m.get("task_key") for m in r.get("modified_tasks", [])] == ["E"],
             "only E modified")
    results.append(c.done())

    # ---- S2-C untouched preservation + journal ----
    c = Check("S2C_preservation")
    j_by_path: Dict[str, List[Dict[str, Any]]] = {}
    for rec in journal:
        j_by_path.setdefault(rec["path"], []).append(rec)
    for path in ("task_s2_a.txt", "task_s2_b.txt", "task_s2_c.txt", "task_s2_d.txt"):
        recs = j_by_path.get(path, [])
        c.expect([r["record_type"] for r in recs] == ["intent", "performed"],
                 f"{path}: intent+performed only (never re-executed)")
    je = j_by_path.get("task_s2_e.txt", [])
    types = [r["record_type"] for r in je]
    c.facts["journal_task_e"] = types
    c.expect(types[:2] == ["intent", "performed"], "E intent+performed first")
    c.expect(all(t == "reconciled" for t in types[2:]), f"E re-executions all adopted: {types}")
    if len(je) >= 2:
        perf = je[1]
        for rec in je[2:]:
            c.expect(rec["mtime_ns"] == perf["mtime_ns"] and rec["inode"] == perf["inode"],
                     "E never rewritten")
    # artifacts untouched for A..D
    for key, path, marker in (
        ("A", "task_s2_a.txt", b"E10RP_S2_A_OUTPUT"),
        ("B", "task_s2_b.txt", b"E10RP_S2_B_OUTPUT"),
        ("C", "task_s2_c.txt", b"E10RP_S2_C_OUTPUT"),
        ("D", "task_s2_d.txt", b"E10RP_S2_D_OUTPUT"),
        ("E", "task_s2_e.txt", b"E10RP_S2_E_REALITY_ACTUAL"),
    ):
        f = sandbox_file(art, path)
        c.expect(f is not None and marker in f.read_bytes(), f"{path} content mismatch")
        if f and key in scen.get("phase1", {}).get("artifact_stats", {}):
            st = f.stat()
            was = scen["phase1"]["artifact_stats"][key]
            c.expect(st.st_mtime_ns == was["mtime_ns"] and st.st_ino == was["inode"],
                     f"{key} rewritten after phase 1")
    # final checkpoint attempt counts
    cp = load_final_checkpoint(art)
    key_by_id = {v: k for k, v in ledger.get("key_map", {}).items()}
    # extend with event-derived map
    for e in by_type.get("task.created", []):
        p = e["payload"]
        if isinstance(p, dict) and p.get("task_key"):
            key_by_id[p["task_id"]] = p["task_key"]
    att = cp.get("attempt_history", {})
    att_counts = {key_by_id.get(tid, tid): len(v) for tid, v in att.items()}
    c.facts["attempt_counts"] = att_counts
    c.expect(att_counts.get("A") == 1 and att_counts.get("C") == 1 and att_counts.get("D") == 1,
             "A/C/D one attempt each")
    c.expect(att_counts.get("B") == 2, "B: tool failure + retry success")
    c.expect(att_counts.get("E") == 3, "E: 2 failed (retried verification) + 1 corrected")
    results.append(c.done())
    return results


def main() -> int:
    expectations = jload(SESSION / "evidence" / "pre_registered_expectations.json")
    scen_main = jload(SESSION / "evidence" / "main_scenario.json")
    scen_s2 = jload(SESSION / "evidence" / "s2_scenario.json")

    results: List[Dict[str, Any]] = []
    results.extend(verify_main(expectations, scen_main))
    results.extend(verify_s2(expectations, scen_s2))

    ok = all(r["verdict"] == "VERIFIED" for r in results)
    out = {
        "session": str(SESSION),
        "verdict": "E10RP_VERIFIED" if ok else "E10RP_VERIFICATION_FAILED",
        "checks": results,
    }
    (SESSION / "evidence" / "verifier.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({"verdict": out["verdict"],
                      "checks": [(r["check"], r["verdict"], r["problems"]) for r in results]},
                     indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
