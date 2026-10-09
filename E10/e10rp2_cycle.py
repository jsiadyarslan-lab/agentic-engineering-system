#!/usr/bin/env python3
"""E10-RP2 CYCLE — verification-truth cycle in THIS process, through the
REAL operational path (CanonicalOrchestrator -> MissionController ->
ExecutionEngine -> ToolExecutor) WITH the real EOE grant authorization
wired through eoe.engine_bridge (no allow-all test validator anywhere in
this cycle).

Modes:
  resolution     — v1 engine deviation at D -> replan v2 (deliberately
                   WRONG criteria correction on preserved C) -> verifier
                   catches C (mixed state: A evidenced, C not_evidenced)
                   -> replan v3 (criteria corrected to observed reality)
                   -> review approved -> re-verify -> C evidenced under
                   newer valid evidence -> COMPLETE. History preserved.
  mixed-blocked  — same v1->v2, verifier catches C, but NO second
                   decision: the failure stays unresolved and completion
                   MUST fail (no false success — §4.2).

Exit code 0 iff EVERY pre-registered expectation for the mode passes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(HERE), str(REPO / "src"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from e10rp2_common import (  # noqa: E402
    GOAL, C_REALITY, PRE_REGISTERED_EXPECTATIONS,
    ScriptedDecomposerProvider, ResolutionDecisionProvider,
    MixedBlockedDecisionProvider, build_real_authorization,
    dedup_attempts, journal_records, events_jsonl, durable_write_json, _pv,
)


def find_ids(out: Path, orch):
    mission_id = next((out / "mission_controller").iterdir()).name
    run_id = next(
        rid for rid, g in orch.mc.engine.task_graph.items()
        if any(n.get("mission_id") == mission_id for n in g.values())
    )
    return mission_id, run_id


def verification_view(mc, mission_id):
    """Per-task verification history from the durable event log — the
    evidence base for the truth-rule assertions."""
    events = [e for e in mc.engine.event_bus.history
              if e.mission_id == mission_id
              and e.event_type.value == "verification.complete"]
    per_task: dict = {}
    for e in events:
        tid = _pv(e.payload, "task_id", "") or e.correlation_id or ""
        key = mc._task_to_key.get(tid, tid)
        per_task.setdefault(key, []).append({
            "verdict": _pv(e.payload, "verdict", ""),
            "attempt_id": _pv(e.payload, "attempt_id", ""),
            "plan_version": _pv(e.payload, "plan_version", None),
            "source": e.source,
            "timestamp": e.timestamp.isoformat(),
        })
    for k in per_task:
        per_task[k].sort(key=lambda v: v["timestamp"])
    return per_task


def collect(out: Path, mode: str, orch, result, provider, decomposer, grant_id) -> dict:
    mission_id, run_id = find_ids(out, orch)
    mc = orch.mc
    events = [e for e in mc.engine.event_bus.history if e.mission_id == mission_id]
    graph = mc.engine.task_graph.get(run_id, {})
    attempts_by_tid = dedup_attempts(events)

    keymap = dict(mc._key_to_task)
    attempts_per_key, states = {}, {}
    for key, tid in keymap.items():
        attempts_per_key[key] = len(attempts_by_tid.get(tid, []))
        node = graph.get(tid)
        states[key] = node["state"].value if node else "REMOVED"

    verif = verification_view(mc, mission_id)
    c_history = verif.get("C", [])
    a_history = verif.get("A", [])

    # mixed state: at some point A evidenced AND C not_evidenced (current)
    seen_mixed = bool(
        any(v["verdict"] == "evidenced" for v in a_history)
        and any(v["verdict"] == "not_evidenced" for v in c_history)
    )
    verifier_failures = [f for f in mc.failures
                         if "orchestrator verifier" in str(f.description)]
    c_failure = next((f for f in verifier_failures if f.task_key == "C"), None)

    jr = journal_records(out, mission_id)
    performed = {}
    for rec in jr:
        if rec.get("record_type") == "performed":
            base = Path(rec.get("path", "")).name
            performed[base] = performed.get(base, 0) + 1

    files = {}
    for name in ("task_a.txt", "task_c.txt", "task_d.txt", "task_x.txt",
                 "task_e.txt"):
        hits = list(out.rglob(name))
        files[name] = {
            "present": bool(hits),
            "contains_reality": (C_REALITY in hits[0].read_text(encoding="utf-8"))
            if name == "task_c.txt" and hits else None,
        }

    dup = None
    if mode == "resolution":
        n_events_before = len(mc.engine.event_bus.history)
        journal_before = len(jr)
        attempts_before = {k: attempts_per_key[k] for k in attempts_per_key}
        dup_result = asyncio.run(mc.execute_run(run_id))
        jr_after = journal_records(out, mission_id)
        ev2 = [e for e in mc.engine.event_bus.history if e.mission_id == mission_id]
        a2 = dedup_attempts(ev2)
        attempts_after = {}
        for key, tid in keymap.items():
            attempts_after[key] = len(a2.get(tid, []))
        dup = {
            "result_success": bool(dup_result.get("success")),
            "zero_new_attempts": attempts_after == attempts_before,
            "journal_unchanged": len(jr_after) == journal_before,
            "new_events": len(mc.engine.event_bus.history) - n_events_before,
        }

    # completion report (verify_completion) — the truth-rule verdict
    graph_now = mc.engine.task_graph.get(run_id, {})
    required_keys = [k for k, tid in mc._key_to_task.items() if tid in graph_now]
    complete, completion_report = mc.verify_completion(run_id, required_keys)

    bundle = {
        "mode": mode,
        "mission_id": mission_id,
        "run_id": run_id,
        "grant": {"grant_id": grant_id, "validator": "eoe.engine_bridge (REAL)",
                  "grant_ids_passed": list(orch.grant_ids or [])},
        "result": {"success": bool(result.success),
                   "final_state": result.final_state,
                   "error": result.error,
                   "duration_ms": result.duration_ms},
        "completion": {"complete": bool(complete), "report": completion_report},
        "reviews": [asdict(r) for r in mc.plan_reviews],
        "replans": [asdict(r) for r in mc.replans],
        "verifications": verif,
        "verifier_failures": [asdict(f) for f in verifier_failures],
        "c_failure_resolved": (bool(c_failure.resolved) and c_failure.resolved_by)
        if c_failure else None,
        "mixed_state_seen": seen_mixed,
        "c_latest_verdict": c_history[-1]["verdict"] if c_history else None,
        "c_criteria_version": (completion_report.get("checks", {})
                               .get("verification_history", {})
                               .get("per_task", {}).get("C", {})
                               .get("criteria_version")),
        "historical_not_evidenced_preserved": any(
            v["verdict"] == "not_evidenced" for v in c_history),
        "attempts_per_key": attempts_per_key,
        "states": states,
        "journal": {"performed_per_path": performed, "total_records": len(jr)},
        "files": files,
        "duplicate_continuation": dup,
        "providers": {
            "decomposer_llm_calls": decomposer.calls,
            "decision_log": provider.log,
            "disclosure": ("ScriptedDecomposerProvider (planning boundary) + "
                           "decision providers (replanning decision boundary) — "
                           "predetermined control inputs, disclosed; NOT claimed "
                           "as independent planning. The v2 decision's WRONG "
                           "criteria correction for C is deliberate: the "
                           "verifier truth rule (production code), not the "
                           "decision, must protect completion."),
        },
        "real_components": {
            "mission_controller": type(mc).__name__,
            "execution_engine": type(mc.engine).__name__,
            "require_plan_review": bool(mc.require_plan_review),
            "grant_validator": "eoe.engine_bridge.build_engine_grant_validator",
        },
    }
    return bundle


def check_expectations(facts: dict, exp: dict) -> list:
    results = []

    def rec(name, ok, detail=""):
        results.append({"expectation": name, "pass": bool(ok), "detail": detail})

    rec("result.success", facts["result"]["success"] == exp["result"]["success"],
        f"{facts['result']['success']} (want {exp['result']['success']})")
    if exp.get("result", {}).get("final_state"):
        rec("result.final_state",
            facts["result"]["final_state"] == exp["result"]["final_state"],
            f"{facts['result']['final_state']!r} (want {exp['result']['final_state']!r})")
    rec("reviews", [r["verdict"] for r in facts["reviews"]] == exp["reviews"],
        str([r["verdict"] for r in facts["reviews"]]))
    rec("replans",
        [{"from_version": r["from_version"], "to_version": r["to_version"],
          "invalidated": sorted(r["invalidated_tasks"]),
          "modified": sorted(m["task_key"] for m in r["modified_tasks"]),
          "added": sorted(a.get("task_key") or "" for a in r["added_tasks"])}
         for r in facts["replans"]] == exp["replans"],
        str([{"v": r["to_version"], "inv": sorted(r["invalidated_tasks"]),
              "mod": sorted(m["task_key"] for m in r["modified_tasks"])}
             for r in facts["replans"]]))

    rec("verifier_failure_recorded_for_C",
        any(f["task_key"] == "C" for f in facts["verifier_failures"])
        == exp["verifier_failure_recorded_for_C"],
        str([(f["task_key"], f["kind"], f["resolved"], f["resolved_by"])
             for f in facts["verifier_failures"]]))
    rec("verifier_failure_resolved_by_newer_evidence",
        bool(facts["c_failure_resolved"]) == exp["verifier_failure_resolved_by_newer_evidence"],
        str(facts["c_failure_resolved"]))
    if "mixed_state_seen" in exp:
        rec("mixed_state_seen (A evidenced while C not_evidenced)",
            facts["mixed_state_seen"] == exp["mixed_state_seen"],
            f"A history: {[(v['verdict']) for v in facts['verifications'].get('A', [])]}; "
            f"C history: {[(v['verdict']) for v in facts['verifications'].get('C', [])]}")
    rec("C_latest_verdict", facts["c_latest_verdict"] == exp["C_latest_verdict"],
        str(facts["c_latest_verdict"]))
    if exp.get("C_criteria_version"):
        rec("C_criteria_version", facts["c_criteria_version"] == exp["C_criteria_version"],
            str(facts["c_criteria_version"]))
    if "completion_check_failed_reason" in exp:
        reasons = [f.get("reason") for f in (facts["completion"]["report"]
                                             .get("checks", {})
                                             .get("verification_history", {})
                                             .get("verification_failures", []))]
        rec("completion_check_failed_reason",
            exp["completion_check_failed_reason"] in reasons, str(reasons))
    if "historical_not_evidenced_preserved" in exp:
        rec("historical_not_evidenced_preserved",
            facts["historical_not_evidenced_preserved"]
            == exp["historical_not_evidenced_preserved"],
            str(facts["historical_not_evidenced_preserved"]))

    rec("attempts_per_key", facts["attempts_per_key"] == exp["attempts_per_key"],
        str(facts["attempts_per_key"]))
    for name, want in exp.get("files", {}).items():
        f = facts["files"].get(name, {})
        want_present = want == "present"
        rec(f"files.{name}.{'present' if want_present else 'absent'}",
            f.get("present") is want_present, str(f))

    dup_exp = exp.get("duplicate_continuation")
    if dup_exp and facts.get("duplicate_continuation"):
        dup = facts["duplicate_continuation"]
        rec("duplicate.zero_new_attempts", dup["zero_new_attempts"] == dup_exp["zero_new_attempts"],
            str(dup))
        rec("duplicate.journal_unchanged", dup["journal_unchanged"] == dup_exp["journal_unchanged"],
            str(dup))
        rec("duplicate.result_success", dup["result_success"],
            str(dup))

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["resolution", "mixed-blocked"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expectations", required=True)
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    exp_all = json.loads(Path(args.expectations).read_text(encoding="utf-8"))

    from orchestrator.canonical import create_canonical_orchestrator
    from unified.mission_controller import MissionController  # noqa: F401
    from unified.execution import ExecutionEngine  # noqa: F401

    decomposer = ScriptedDecomposerProvider()
    provider = (ResolutionDecisionProvider() if args.mode == "resolution"
                else MixedBlockedDecisionProvider())

    # §2: REAL EOE authorization — owner-approved signed PATH_GRANT
    # covering the artifacts root; the engine validates against the real
    # grants ledger through the bridge (NO allow-all test validator).
    validator, grant_id, ledger, grantor, admission = build_real_authorization(str(out))

    orch = create_canonical_orchestrator(
        llm_provider=decomposer,
        artifacts_base_dir=str(out),
        auto_approve_plans=True,
        max_parallel=1,
        require_plan_review=True,
        replan_decision_provider=provider,
        max_review_rounds=4,
        grant_validator=validator,
        grant_ids=[grant_id],
    )

    result = asyncio.run(orch.execute_mission(GOAL))

    facts = collect(out, args.mode, orch, result, provider, decomposer, grant_id)
    durable_write_json(out / "facts.json", facts)
    durable_write_json(out / "events.jsonl", events_jsonl(
        [e for e in orch.mc.engine.event_bus.history
         if e.mission_id == facts["mission_id"]]))
    checks = check_expectations(
        facts, exp_all["run_resolution_cycle" if args.mode == "resolution"
                       else "run_mixed_blocked_cycle"])
    durable_write_json(out / "expectations_check.json", checks)

    failed = [c for c in checks if not c["pass"]]
    verdict = "CYCLE_PROVEN" if not failed else "CYCLE_FAILED"
    print(f"[CYCLE mode={args.mode}] verdict={verdict} "
          f"checks={len(checks) - len(failed)}/{len(checks)}")
    for c in checks:
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"  [{mark}] {c['expectation']}: {c['detail']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
