#!/usr/bin/env python3
"""E10-RP1 CYCLE — one canonical cycle in THIS process, through the REAL
operational path: CanonicalOrchestrator.execute_mission -> real
MissionController + real ExecutionEngine + real ToolExecutor.

Modes:
  full    — deviation at C -> replan v1->v2 -> review #1 REJECTED (C6) ->
            revision (recover C) -> review #2 APPROVED -> continuation ->
            verified outcome. (§3 proofs 1..6)
  blocked — same replan decision, but NO revision after the first v2
            rejection: the orchestrator must return PLAN_REVIEW_REJECTED
            with ZERO execution after the rejection. (§3 proof 2 / §2.4)

Exit code 0 iff EVERY pre-registered expectation for the mode passes.
The expectations are read from the runner-written pre_registered.json
(fixed BEFORE any cycle ran — never changed after outcomes).
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
# Path setup (disclosed invocation dependency, pre-existing at baseline):
#  - HERE        : E10 scenario modules (e10rp1_common)
#  - REPO/src    : the `unified` / `orchestrator` packages (pyproject pythonpath)
#  - REPO (root) : the `llm` package imports `src.factory.tools` at module
#                  load (llm/structured.py) — requires the repo root on the
#                  import path. Without it, GoalDecomposer's LLM boundary
#                  import fails and silently degrades to the hardcoded
#                  fallback plan. Same invocation-dependency class as E8's
#                  known import-path issue — environment, not code.
for _p in (str(HERE), str(REPO / "src"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from e10rp1_common import (  # noqa: E402
    GOAL, C_REALITY, PRE_REGISTERED_EXPECTATIONS,
    ScriptedDecomposerProvider, FullCycleDecisionProvider,
    BlockedDecisionProvider, dedup_attempts, journal_records,
    events_jsonl, durable_write_json, _pv,
)


def find_ids(out: Path, orch):
    mission_id = next((out / "mission_controller").iterdir()).name
    run_id = next(
        rid for rid, g in orch.mc.engine.task_graph.items()
        if any(n.get("mission_id") == mission_id for n in g.values())
    )
    return mission_id, run_id


def attempt_first_ts(events):
    """attempt_id -> timestamp of its first TASK_ASSIGNED emission."""
    out = {}
    for e in events:
        if e.event_type.value != "task.assigned":
            continue
        aid = _pv(e.payload, "attempt_id", "")
        if aid and aid not in out:
            out[aid] = e.timestamp
    return out


def extract_ordering(events, mode: str) -> dict:
    chain: dict = {}
    for e in events:
        et = e.event_type.value
        if et == "state.transition":
            ent = _pv(e.payload, "entity_type")
            if ent == "plan_review":
                ver = _pv(e.payload, "entity_id")
                to = _pv(e.payload, "to_state")
                key = f"review_{ver}_{'approved' if to == 'APPROVED' else 'rejected'}"
                chain.setdefault(key, e.timestamp)
            elif (ent == "task" and _pv(e.payload, "from_state") == "FAILED"
                  and _pv(e.payload, "to_state") == "READY"
                  and _pv(e.payload, "trigger") == "mission_controller_recovery"):
                chain.setdefault("recovered_C", e.timestamp)
        elif et == "replan.requested":
            chain.setdefault("replan_requested", e.timestamp)

    first_ts = attempt_first_ts(events)
    all_ts = sorted(first_ts.values())
    o = {"chain": {k: t.isoformat() for k, t in chain.items()},
         "attempt_count": len(all_ts)}
    if mode == "full":
        o["invariants"] = {
            "no_attempt_before_v1_review": bool(all_ts) and all_ts[0] > chain["review_v1_approved"],
            "no_attempt_between_replan_and_v2_approval": not [
                t for t in all_ts
                if chain["replan_requested"] < t <= chain["review_v2_approved"]
            ],
            "first_continuation_attempt_after_v2_approval": any(
                t > chain["review_v2_approved"] for t in all_ts),
            "replan_lt_reject_lt_recover_lt_approve": (
                chain["replan_requested"] < chain["review_v2_rejected"]
                < chain["recovered_C"] < chain["review_v2_approved"]),
        }
    else:
        o["invariants"] = {
            "zero_attempts_after_rejection": not [
                t for t in all_ts if t > chain["review_v2_rejected"]],
        }
    return o


def collect(out: Path, mode: str, orch, result, provider, decomposer) -> dict:
    mission_id, run_id = find_ids(out, orch)
    mc = orch.mc
    events = [e for e in mc.engine.event_bus.history if e.mission_id == mission_id]
    graph = mc.engine.task_graph.get(run_id, {})
    attempts_by_tid, _ = dedup_attempts(events)

    keymap = dict(mc._key_to_task)  # includes stale entries for removed tasks
    attempts_per_key, states = {}, {}
    for key, tid in keymap.items():
        attempts_per_key[key] = len(attempts_by_tid.get(tid, []))
        node = graph.get(tid)
        states[key] = node["state"].value if node else "REMOVED"

    jr = journal_records(out, mission_id)
    performed = {}
    reconciled = {}
    for rec in jr:
        base = Path(rec.get("path", "")).name
        if rec.get("record_type") == "performed":
            performed[base] = performed.get(base, 0) + 1
        elif rec.get("record_type") == "reconciled":
            reconciled[base] = reconciled.get(base, 0) + 1

    files = {}
    for name in ("task_a.txt", "task_b.txt", "task_c.txt", "task_d.txt",
                  "task_x.txt", "task_e.txt"):
        hits = list(out.rglob(name))
        files[name] = {
            "present": bool(hits),
            "contains_reality": (C_REALITY in hits[0].read_text(encoding="utf-8"))
            if name == "task_c.txt" and hits else None,
        }

    dup = None
    if mode == "full":
        n_events_before = len(mc.engine.event_bus.history)
        journal_before = len(jr)
        ids_before = {k: attempts_per_key[k] for k in attempts_per_key}
        dup_result = asyncio.run(mc.execute_run(run_id))
        jr_after = journal_records(out, mission_id)
        attempts_after = {}
        ev2 = [e for e in mc.engine.event_bus.history if e.mission_id == mission_id]
        a2, _ = dedup_attempts(ev2)
        for key, tid in keymap.items():
            attempts_after[key] = len(a2.get(tid, []))
        dup = {
            "result_success": bool(dup_result.get("success")),
            "zero_new_attempts": attempts_after == ids_before,
            "journal_unchanged": len(jr_after) == journal_before,
            "new_events": len(mc.engine.event_bus.history) - n_events_before,
        }

    bundle = {
        "mode": mode,
        "mission_id": mission_id,
        "run_id": run_id,
        "result": {"success": bool(result.success),
                   "final_state": result.final_state,
                   "error": result.error,
                   "orchestrator_mission_id": result.mission_id,
                   "duration_ms": result.duration_ms,
                   "event_count": len(result.event_trace),
                   "evidence_count": len(result.evidence_chain)},
        "reviews": [asdict(r) for r in mc.plan_reviews],
        "replan": asdict(mc.replans[0]) if mc.replans else None,
        "deviation": asdict(mc.failures[0]) if mc.failures else None,
        "attempts_per_key": attempts_per_key,
        "states": states,
        "journal": {"performed_per_path": performed,
                    "reconciled_per_path": reconciled,
                    "total_records": len(jr)},
        "files": files,
        "ordering": extract_ordering(events, mode),
        "duplicate_continuation": dup,
        "providers": {
            "decomposer_llm_calls": decomposer.calls,
            "decision_log": provider.log,
            "disclosure": ("ScriptedDecomposerProvider (planning boundary) + "
                           "decision provider (replanning decision boundary) — "
                           "predetermined control inputs, disclosed; NOT claimed "
                           "as independent planning or untested self-intelligence"),
        },
        "real_components": {
            "mission_controller": type(mc).__name__,
            "execution_engine": type(mc.engine).__name__,
            "require_plan_review": bool(mc.require_plan_review),
            "grant_validator_supplied": "E9-R test pattern (allow-all, disclosed)",
        },
    }
    return bundle


def check_expectations(facts: dict, exp: dict) -> list:
    """Compare collected facts against the pre-registered block."""
    results = []

    def rec(name, ok, detail=""):
        results.append({"expectation": name, "pass": bool(ok), "detail": detail})

    rec("result.success", facts["result"]["success"] == exp["result"]["success"],
        f"{facts['result']['success']} (want {exp['result']['success']})")
    rec("result.final_state", facts["result"]["final_state"] == exp["result"]["final_state"],
        f"{facts['result']['final_state']!r} (want {exp['result']['final_state']!r})")
    rec("reviews", [r["verdict"] for r in facts["reviews"]] == exp["reviews"],
        str([r["verdict"] for r in facts["reviews"]]))

    if exp.get("review_v2_first_failing_check"):
        first_rejected = next((r for r in facts["reviews"] if r["verdict"] == "rejected"), None)
        failing = [c["check"] for c in (first_rejected or {}).get("checks", []) if not c["passed"]]
        rec("review_v2_first_failing_check", failing == [exp["review_v2_first_failing_check"]], str(failing))
    if exp.get("review_v2_failing_check"):
        rejected = next((r for r in facts["reviews"] if r["verdict"] == "rejected"), None)
        failing = [c["check"] for c in (rejected or {}).get("checks", []) if not c["passed"]]
        rec("review_v2_failing_check", failing == [exp["review_v2_failing_check"]], str(failing))

    rp, erp = facts.get("replan"), exp.get("replan")
    if erp:
        rec("replan.from_version", rp["from_version"] == erp["from_version"], rp["from_version"])
        rec("replan.to_version", rp["to_version"] == erp["to_version"], rp["to_version"])
        rec("replan.invalidated", rp["invalidated_tasks"] == erp["invalidated"], str(rp["invalidated_tasks"]))
        rec("replan.preserved", rp["preserved_tasks"] == erp["preserved"], str(rp["preserved_tasks"]))
        rec("replan.added", [a.get("task_key") for a in rp["added_tasks"]] == erp["added"],
            str([a.get("task_key") for a in rp["added_tasks"]]))
        rec("replan.rewired", {r["task_key"]: r["new_depends_on"] for r in rp["rewired_dependencies"]} == erp["rewired"],
            str(rp["rewired_dependencies"]))
        rec("replan.modified", [m["task_key"] for m in rp["modified_tasks"]] == erp["modified"],
            str([m["task_key"] for m in rp["modified_tasks"]]))
        dev = facts.get("deviation")
        rec("deviation.linked_to_replan",
            dev and dev.get("resolved_by") == f"replan->{rp['to_version']}"
            and list(dev.get("evidence") or []) == list(rp.get("evidence") or []),
            f"resolved_by={dev.get('resolved_by') if dev else None}; "
            f"evidence_match={list(dev.get('evidence') or []) == list(rp.get('evidence') or []) if dev else None}")
        rec("deviation.kind_plan_deviation",
            dev and dev.get("kind") == "plan_deviation" and "Verification failed" in str(dev.get("description", "")),
            str(dev.get("kind")) if dev else None)

    rec("attempts_per_key", facts["attempts_per_key"] == exp["attempts_per_key"],
        str(facts["attempts_per_key"]))
    if exp.get("journal_performed_per_path") is not None:
        rec("journal_performed_per_path",
            facts["journal"]["performed_per_path"] == exp["journal_performed_per_path"],
            str(facts["journal"]["performed_per_path"]))

    if exp.get("journal_reconciled_task_c") is not None:
        rec("journal_reconciled_task_c",
            facts["journal"]["reconciled_per_path"].get("task_c.txt", 0) == exp["journal_reconciled_task_c"],
            str(facts["journal"]["reconciled_per_path"]))

    for name, want in exp.get("files", {}).items():
        f = facts["files"].get(name, {})
        if want == "absent":
            rec(f"files.{name}.absent", f.get("present") is False, str(f))
        elif want == "present":
            rec(f"files.{name}.present", f.get("present") is True, str(f))
        elif isinstance(want, str) and want.startswith("contains "):
            rec(f"files.{name}.{want[:24]}", bool(f.get("contains_reality")) and C_REALITY in want,
                str(f))

    for inv, want in exp.get("ordering_invariants", {}).items():
        got = facts["ordering"]["invariants"].get(inv)
        rec(f"ordering.{inv}", got == want, str(got))

    if exp.get("c_final_state"):
        rec("c_final_state", facts["states"].get("C") == exp["c_final_state"],
            str(facts["states"].get("C")))
    if "zero_attempts_after_rejection" in exp:
        rec("zero_attempts_after_rejection",
            facts["ordering"]["invariants"]["zero_attempts_after_rejection"]
            == exp["zero_attempts_after_rejection"],
            str(facts["ordering"]["invariants"]))

    dup_exp = exp.get("duplicate_continuation")
    if dup_exp and facts.get("duplicate_continuation"):
        dup = facts["duplicate_continuation"]
        rec("duplicate.zero_new_attempts", dup["zero_new_attempts"] == dup_exp["zero_new_attempts"], str(dup))
        rec("duplicate.journal_unchanged", dup["journal_unchanged"] == dup_exp["journal_unchanged"], str(dup))
        rec("duplicate.result_success", dup["result_success"] == dup_exp["result_success"], str(dup))

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "blocked"], required=True)
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
    provider = FullCycleDecisionProvider() if args.mode == "full" else BlockedDecisionProvider()
    orch = create_canonical_orchestrator(
        llm_provider=decomposer,
        artifacts_base_dir=str(out),
        auto_approve_plans=True,
        max_parallel=1,
        require_plan_review=True,       # canonical policy — explicit, default ON
        replan_decision_provider=provider,
        max_review_rounds=3,
        # E9-R construction pattern (same as E9-R/test_production_integration.py
        # and E10-RP build_engine): governed tool execution requires a grant
        # validator. This is the DISCLOSED test validator for the proof; real
        # deployments wire the EOE grant system (recorded as a remaining gap —
        # NOT claimed here).
        grant_validator=lambda grant_id, permission: True,
    )

    # Diagnostics (RP1_DEBUG=1): observe the planning boundary decision.
    import os
    if os.environ.get("RP1_DEBUG"):
        _orig_decompose = orch.decomposer.decompose

        async def _traced_decompose(goal, mission_id, run_id):
            specs = await _orig_decompose(goal, mission_id, run_id)
            print(f"[RP1_DEBUG] decomposed {len(specs)} specs: "
                  f"{[(s.key, s.acceptance_criteria) for s in specs]}")
            print(f"[RP1_DEBUG] provider.llm_calls={decomposer.calls}")
            return specs

        orch.decomposer.decompose = _traced_decompose

        # trace the LLM boundary primitives used inside the thinker's try block
        import llm.providers as _lp
        _orig_lmm = _lp.LLMMessage

        class _TracedLMM(_orig_lmm):
            def __init__(self, *a, **k):
                print(f"[RP1_DEBUG] LLMMessage constructed role={k.get('role', (a or ['?'])[0])}")
                super().__init__(*a, **k)

        _lp.LLMMessage = _TracedLMM

        _orig_complete = decomposer.complete

        async def _traced_complete(messages):
            print(f"[RP1_DEBUG] provider.complete ENTERED")
            try:
                r = await _orig_complete(messages)
                print(f"[RP1_DEBUG] provider.complete returned {r.content[:60]!r}")
                return r
            except Exception as e:
                print(f"[RP1_DEBUG] provider.complete RAISED {type(e).__name__}: {e}")
                raise

        decomposer.complete = _traced_complete

    result = asyncio.run(orch.execute_mission(GOAL))

    if os.environ.get("RP1_DEBUG"):
        print(f"[RP1_DEBUG] execute_mission -> success={result.success} "
              f"final_state={result.final_state!r} error={result.error!r}")
        for a in list(orch.mc.engine.attempts.values()):
            if getattr(a, "error", None):
                print(f"[RP1_DEBUG] attempt {a.attempt_id} task={a.task_id} "
                      f"agent={getattr(a, 'agent_id', '')} state={a.state} "
                      f"err={str(a.error)[:300]!r}")

    facts = collect(out, args.mode, orch, result, provider, decomposer)
    durable_write_json(out / "facts.json", facts)
    durable_write_json(out / "events.jsonl", events_jsonl(
        [e for e in orch.mc.engine.event_bus.history
         if e.mission_id == facts["mission_id"]]))
    checks = check_expectations(facts, exp_all[f"run_a_full_cycle" if args.mode == "full"
                                               else "run_b_blocked_cycle"])
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
