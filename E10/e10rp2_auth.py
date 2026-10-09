#!/usr/bin/env python3
"""E10-RP2 §4.1/§4.5 — AUTHORIZATION CASES + TOOL-FAILURE CASE.

All cases start from the ACTUAL creation point
(create_canonical_orchestrator) and run a real 2-task mission through the
real operational path.

Auth cases (§4.1, §2.4):
  allow            — real owner-approved READ_WRITE PATH_GRANT covering the
                     artifacts root: governed writes admitted, mission
                     completes, files on disk.
  deny-revoked     — grant revoked in the ledger BEFORE the run: every
                     governed write denied; mission fails; ZERO files.
  deny-read-only   — READ-only scope grant: write denied; ZERO files.
  deny-path        — grant covering a DIFFERENT directory: writes to the
                     artifacts root denied; ZERO files.
  missing-validator— grant_validator=None: fail-closed
                     ("no validator available"); ZERO files.
  missing-grants   — real validator but grant_ids=[]: fail-closed
                     ("lacks required permission"); ZERO files.

Tool-failure case (§4.5):
  tool-fail        — task B injects a REAL first-attempt tool/runtime
                     failure; the ENGINE retry loop must recover it; NO
                     replan, NO verifier failure (tool failures stay in
                     the retry path — never auto-classified as deviation).

Side-effect proof (§2.5): on every deny/missing case the artifacts tree
is scanned — zero sandbox files, zero performed journal records.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for _p in (str(HERE), str(REPO / "src"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from e10rp2_common import (  # noqa: E402
    PRE_REGISTERED_EXPECTATIONS,
    ScriptedDecomposerProvider, build_real_authorization,
    PLAN_JSON_SIMPLE, PLAN_JSON_TOOLFAIL,
    journal_records, events_jsonl, durable_write_json, dedup_attempts,
)


def scan_artifacts(out: Path) -> dict:
    """Side-effect inventory: sandbox files written + performed journal
    records (the §2.5 no-side-effect proof)."""
    sandbox_files = sorted(
        str(p.relative_to(out)) for p in out.rglob("*")
        if p.is_file() and "sandbox-" in str(p.relative_to(out))
    )
    performed = 0
    mc_dir = out / "mission_controller"
    if mc_dir.exists():
        for mission_dir in mc_dir.iterdir():
            for rec in journal_records(out, mission_dir.name):
                if rec.get("record_type") == "performed":
                    performed += 1
    return {"sandbox_files": sandbox_files, "performed_journal_records": performed}


def count_permission_errors(orch, mission_id) -> int:
    n = 0
    for e in orch.mc.engine.event_bus.history:
        if e.mission_id != mission_id:
            continue
        if e.event_type.value == "task.failed":
            err = ""
            p = e.payload
            err = p.get("error", "") if hasattr(p, "get") else getattr(p, "error", "")
            if "PermissionError" in str(err):
                n += 1
    return n


def find_mission_id(out: Path) -> str:
    mc_dir = out / "mission_controller"
    return next(mc_dir.iterdir()).name


def run_case(case: str, out: Path) -> dict:
    from orchestrator.canonical import create_canonical_orchestrator

    decomposer = ScriptedDecomposerProvider(
        PLAN_JSON_TOOLFAIL if case == "tool-fail" else PLAN_JSON_SIMPLE)

    validator = grant_id = None
    grant_ids = None
    admission = None
    ledger = None
    if case == "allow":
        validator, grant_id, ledger, _g, admission = build_real_authorization(str(out))
        grant_ids = [grant_id]
    elif case == "deny-revoked":
        validator, grant_id, ledger, _g, admission = build_real_authorization(str(out), revoke=True)
        grant_ids = [grant_id]
    elif case == "deny-read-only":
        validator, grant_id, ledger, _g, admission = build_real_authorization(str(out), scope="read")
        grant_ids = [grant_id]
    elif case == "deny-path":
        validator, grant_id, ledger, _g, admission = build_real_authorization(str(out), cover_other_dir=True)
        grant_ids = [grant_id]
    elif case == "missing-validator":
        grant_id = "grant-not-wired"
        grant_ids = [grant_id]  # ids present, validator absent
    elif case == "missing-grants":
        validator, grant_id, ledger, _g, admission = build_real_authorization(str(out))
        grant_ids = []           # validator present, NO grants issued
    elif case == "tool-fail":
        validator, grant_id, ledger, _g, admission = build_real_authorization(str(out))
        grant_ids = [grant_id]
    else:
        raise ValueError(f"unknown case {case}")

    orch = create_canonical_orchestrator(
        llm_provider=decomposer,
        artifacts_base_dir=str(out),
        auto_approve_plans=True,
        max_parallel=1,
        require_plan_review=True,
        replan_decision_provider=None,   # NO replan for these cases
        max_review_rounds=3,
        grant_validator=validator,
        grant_ids=grant_ids,
    )

    goal = ("E10-RP2 auth case: " + case)
    result = asyncio.run(orch.execute_mission(goal))
    mission_id = find_mission_id(out)

    attempts_by_tid = dedup_attempts(
        [e for e in orch.mc.engine.event_bus.history if e.mission_id == mission_id])
    b_attempts = 0
    for key, tid in orch.mc._key_to_task.items():
        if key == "B":
            b_attempts = len(attempts_by_tid.get(tid, []))

    facts = {
        "case": case,
        "mission_id": mission_id,
        "result": {
            "success": bool(result.success),
            "final_state": result.final_state,
            "error": (result.error or "")[:400],
        },
        "permission_errors": count_permission_errors(orch, mission_id),
        "side_effects": scan_artifacts(out),
        "replans": len(orch.mc.replans),
        "verifier_failures": len(orch.mc.failures),
        "B_attempts": b_attempts,
        "grant": {
            "grant_id": grant_id,
            "validator": ("eoe.engine_bridge (REAL)" if validator else None),
            "grant_ids_passed": list(grant_ids or []),
            # DURABLE proof the REAL validator was actually consulted (not an
            # allow-all): the admission's usage log records every admitted
            # grant.used access; denials raise AccessDenied inside the bridge.
            "admission_usage_log_entries": len(admission.usage_log) if admission else 0,
            "admission_usage_log": list(admission.usage_log) if admission else [],
            "ledger_events": list(ledger.events) if ledger else [],
        },
    }
    events = [e for e in orch.mc.engine.event_bus.history
              if e.mission_id == mission_id]
    durable_write_json(out / "events.jsonl", events_jsonl(events))
    return facts


def gather_error_texts(facts: dict, out: Path) -> str:
    """All error texts: the result error + every task.failed payload —
    the permission errors surface in task events, not in result.error."""
    texts = [facts["result"]["error"] or ""]
    events_file = out / "events.jsonl"
    if events_file.exists():
        evs = json.loads(events_file.read_text(encoding="utf-8"))
        for e in evs:
            if e["event_type"] == "task.failed":
                texts.append(str((e.get("payload") or {}).get("error", "")))
    return "\n".join(texts)


def check_case(facts: dict, exp: dict, out: Path) -> list:
    results = []

    def rec(name, ok, detail=""):
        results.append({"expectation": name, "pass": bool(ok), "detail": detail})

    rec("result.success", facts["result"]["success"] == exp["result_success"],
        f"{facts['result']['success']} (want {exp['result_success']})")
    if "files_written" in exp:
        files_written = bool(facts["side_effects"]["sandbox_files"])
        rec("files_written", files_written == exp["files_written"],
            f"files={facts['side_effects']['sandbox_files'][:4]}")
    if "permission_errors_min" in exp:
        rec("permission_errors",
            facts["permission_errors"] >= exp["permission_errors_min"],
            str(facts["permission_errors"]))
    if "permission_errors" in exp:
        rec("permission_errors_exact",
            facts["permission_errors"] == exp["permission_errors"],
            str(facts["permission_errors"]))
    if "error_contains" in exp:
        rec("error_contains",
            exp["error_contains"] in gather_error_texts(facts, out),
            gather_error_texts(facts, out)[:200].replace("\n", " | "))
    if "no_side_effects" in exp and exp["no_side_effects"]:
        rec("zero_performed_journal_records",
            facts["side_effects"]["performed_journal_records"] == 0,
            str(facts["side_effects"]))
    if "B_attempts" in exp:
        rec("B_attempts", facts["B_attempts"] == exp["B_attempts"],
            f"{facts['B_attempts']} (want {exp['B_attempts']})")
    if "replans" in exp:
        rec("replans", facts["replans"] == exp["replans"], str(facts["replans"]))
    if "verifier_failures" in exp:
        rec("verifier_failures", facts["verifier_failures"] == exp["verifier_failures"],
            str(facts["verifier_failures"]))
    return results


CASES = ["allow", "deny-revoked", "deny-read-only", "deny-path",
         "missing-validator", "missing-grants", "tool-fail"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=CASES, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expectations", required=True)
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    exp_all = json.loads(Path(args.expectations).read_text(encoding="utf-8"))

    facts = run_case(args.case, out)
    durable_write_json(out / "facts.json", facts)

    exp_key = {"tool-fail": "tool_fail_case",
               "deny-path": "deny_path_uncovered"}.get(args.case,
                                                         args.case.replace("-", "_"))
    if exp_key == "tool_fail_case":
        base_exp = dict(exp_all[exp_key])
    else:
        base_exp = dict(exp_all["auth_cases"].get(exp_key, {}))
    if args.case in ("deny-revoked", "deny-read-only", "deny-path",
                     "missing-validator", "missing-grants"):
        base_exp["no_side_effects"] = True

    checks = check_case(facts, base_exp, out)
    durable_write_json(out / "expectations_check.json", checks)

    failed = [c for c in checks if not c["pass"]]
    verdict = "CASE_PROVEN" if not failed else "CASE_FAILED"
    print(f"[AUTH case={args.case}] verdict={verdict} "
          f"checks={len(checks) - len(failed)}/{len(checks)}")
    for c in checks:
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"  [{mark}] {c['expectation']}: {c['detail']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
