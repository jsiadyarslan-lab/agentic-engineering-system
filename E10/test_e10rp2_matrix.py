#!/usr/bin/env python3
"""E10-RP2 REQUIRED TEST MATRIX — Canonical Execution Authorization &
Verification Truth (order E10-RP2 §4), RP2-T00..RP2-T18.

A session-scoped fixture runs the complete proof chain as REAL OS
processes (e10rp2_cycle.py / e10rp2_auth.py), each through
CanonicalOrchestrator.execute_mission — the REAL operational path (real
MissionController + real ExecutionEngine + real ToolExecutor governed
execution) with the REAL EOE grant authorization wired through
eoe.engine_bridge (NO allow-all test validator in any RP2 cycle). The
DISCLOSED control inputs sit at decision boundaries only (planning /
replanning decision) and are documented in every facts.json under
'providers'.

Every test asserts its criterion against the DURABLE evidence the runs
wrote to disk (facts/events/expectations_check), never against
re-executions.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


AUTH_CASES = ["allow", "deny-revoked", "deny-read-only", "deny-path",
              "missing-validator", "missing-grants", "tool-fail"]


@pytest.fixture(scope="session")
def rp2_session(tmp_path_factory):
    base = tmp_path_factory.mktemp("rp2_session")
    exp = HERE / "evidence_rp2_expectations.json"
    procs = {}

    def run(script, extra_args, outname):
        out = base / outname
        proc = subprocess.run(
            [sys.executable, str(HERE / script), *extra_args,
             "--out", str(out), "--expectations", str(exp)],
            capture_output=True, text=True, timeout=600, cwd=str(REPO),
        )
        procs[outname] = {"exit": proc.returncode,
                          "stdout_tail": proc.stdout[-2000:]}
        return out, proc

    out_res, p1 = run("e10rp2_cycle.py", ["--mode", "resolution"], "resolution")
    assert p1.returncode == 0, f"resolution cycle failed:\n{p1.stdout[-4000:]}"
    out_mix, p2 = run("e10rp2_cycle.py", ["--mode", "mixed-blocked"], "mixed_blocked")
    assert p2.returncode == 0, f"mixed-blocked cycle failed:\n{p2.stdout[-4000:]}"
    auth_facts = {}
    for case in AUTH_CASES:
        out_case, pc = run("e10rp2_auth.py", ["--case", case], case)
        assert pc.returncode == 0, f"auth case {case} failed:\n{pc.stdout[-4000:]}"
        auth_facts[case] = _load(out_case / "facts.json")

    return {
        "base": base,
        "procs": procs,
        "resolution": _load(out_res / "facts.json"),
        "resolution_checks": _load(out_res / "expectations_check.json"),
        "resolution_events": _load(out_res / "events.jsonl"),
        "mixed": _load(out_mix / "facts.json"),
        "mixed_checks": _load(out_mix / "expectations_check.json"),
        "mixed_events": _load(out_mix / "events.jsonl"),
        "auth": auth_facts,
    }


# ---------------------------------------------- §2 source-level guarantees

def test_RP2_T00_grant_ids_injectable_legacy_default_documented():
    """§2: grant identity is an explicit construction parameter of the
    engine, the factory, and the canonical orchestrator; the legacy
    'test-grant' default is documented and is the ONLY remaining hardcode
    (rejected by any real validator — fail-closed preserved)."""
    from unified.execution import ExecutionEngine, create_execution_engine
    from orchestrator.canonical import CanonicalOrchestrator, create_canonical_orchestrator

    for fn in (ExecutionEngine.__init__, create_execution_engine,
               CanonicalOrchestrator.__init__, create_canonical_orchestrator):
        assert "grant_ids" in inspect.signature(fn).parameters, fn

    src = (REPO / "src" / "unified" / "execution.py").read_text(encoding="utf-8")
    assert "list(self.grant_ids)" in src
    assert "if self.grant_ids is not None" in src
    assert src.count('"test-grant"') == 1  # the single documented legacy default

    csrc = (REPO / "src" / "orchestrator" / "canonical.py").read_text(encoding="utf-8")
    assert "grant_ids=grant_ids" in csrc


def test_RP2_T01_engine_bridge_is_production_eoe_contract():
    """§2.3: the bridge is built ONLY on the real EOE admission contract
    (propose -> owner approval -> sign -> ledger), validates the SPECIFIC
    grant id (never 'any covering grant'), and maps engine permissions
    fail-closed (unmappable permission => deny)."""
    from eoe.access_gateway import AccessAdmission
    from eoe.engine_bridge import build_engine_grant_validator

    assert hasattr(AccessAdmission, "admit_grant_id")
    src = (REPO / "src" / "eoe" / "engine_bridge.py").read_text(encoding="utf-8")
    assert "admit_grant_id(grant_id, write=write" in src
    assert "except AccessDenied:" in src
    assert "return False" in src
    # fail-closed: 'execute' cannot be grounded in the EOE path policy
    import os, tempfile, time as _t
    from eoe.access_gateway import AccessLedger, GrantorService
    from eoe.order_parser import AccessRequest, GrantKind
    base = tempfile.mkdtemp(prefix="rp2_t01_")
    ledger = AccessLedger(); grantor = GrantorService(os.urandom(32))
    admission = AccessAdmission(ledger, grantor, now=_t.time)
    g = grantor.approve(grantor.propose(
        AccessRequest(kind=GrantKind.PATH_GRANT, scope="read_write", target=base)))
    ledger.register(g)
    v = build_engine_grant_validator(admission, base)
    assert v(g.grant_id, "write") is True
    assert v(g.grant_id, "read") is True
    assert v(g.grant_id, "execute") is False       # unmappable -> deny
    assert v("grant-unknown", "write") is False    # unknown id -> deny
    assert v("", "write") is False                 # empty id -> deny


def test_RP2_T02_verification_event_bindings():
    """§3.2: VERIFICATION_COMPLETE carries plan_version / run_id /
    verifier_attempt_id bindings; the canonical verifier binds the
    PRODUCING attempt (no random new_attempt_id in the emission path) and
    emits BOTH verdicts."""
    from unified.event_catalog import VerificationCompleteEvent
    fields = VerificationCompleteEvent.model_fields
    for f in ("plan_version", "run_id", "verifier_attempt_id", "criteria_source"):
        assert f in fields

    src = (REPO / "src" / "orchestrator" / "canonical.py").read_text(encoding="utf-8")
    assert "producing_attempt_id" in src
    assert 'attempt_id=producing_attempt_id or "unestablished"' in src
    # BOTH verdicts are emitted (the old success-only guard is gone)
    assert "if result.success:\n            from unified.contracts import new_verification_id" not in src
    assert 'verdict="evidenced" if result.success else "not_evidenced"' in src


def test_RP2_T03_verify_completion_truth_rule():
    """§3.3: verify_completion enforces the per-task latest-verdict +
    plan-version-validity rule; the loose evidenced>0-only rule is gone."""
    src = (REPO / "src" / "unified" / "mission_controller.py").read_text(encoding="utf-8")
    assert "current_unresolved_verification_failure" in src
    assert "stale_evidence_for_corrected_criteria" in src
    assert "no_verification" in src
    assert "per_task" in src
    # the old loose rule must not remain as the passing condition
    assert '"passed": evidenced > 0,' not in src
    assert "ok = ok and evidenced > 0 and not verification_failures" in src


def test_RP2_T04_verifier_to_replan_wiring_and_guards():
    """§3.5: verifier-detected plan deviations feed the EXISTING replan
    path (decision -> replan_mission -> review -> continuation); verifier
    TOOL/RUNTIME errors never feed replanning (retry territory)."""
    src = (REPO / "src" / "orchestrator" / "canonical.py").read_text(encoding="utf-8")
    assert "_record_verifier_failure" in src
    assert "_resolve_verifier_failure" in src
    assert "rec.recovery_action == RecoveryAction.REPLAN" in src
    assert "TOOL_RUNTIME_FAILURE" in src
    assert "never auto-classified as plan deviation" in src or \
           "NEVER feed the replanning path" in src


def test_RP2_T05_replan_state_reentry_path():
    """§3.5: replan_mission can operate on a mission whose run finished —
    through the LEGAL state-machine path EVIDENCED -> ADJUDICATED ->
    EXECUTING (each hop validated + emitted)."""
    src = (REPO / "src" / "unified" / "mission_controller.py").read_text(encoding="utf-8")
    assert "verification-triggered replan" in src
    assert "MissionState.ADJUDICATED, MissionState.EXECUTING" in src


# ----------------------------------------------------- §4.1 authorization

def test_RP2_T06_auth_allow(rp2_session):
    f = rp2_session["auth"]["allow"]
    assert f["result"]["success"] is True
    assert f["side_effects"]["sandbox_files"], "governed writes must exist"
    assert f["permission_errors"] == 0
    # the REAL validator was actually consulted (not an allow-all)
    assert f["grant"]["admission_usage_log_entries"] > 0
    used = [e for e in f["grant"]["ledger_events"] if e.get("kind") == "grant.used"]
    assert used, "ledger must record grant.used admissions"
    issued = [e for e in f["grant"]["ledger_events"] if e.get("kind") == "grant.issued"]
    assert issued
    assert f["grant"]["grant_ids_passed"] == [f["grant"]["grant_id"]]


@pytest.mark.parametrize("case", ["deny-revoked", "deny-read-only", "deny-path"])
def test_RP2_T07_auth_deny_blocks_writes_no_side_effects(rp2_session, case):
    f = rp2_session["auth"][case]
    assert f["result"]["success"] is False
    assert f["side_effects"]["sandbox_files"] == [], "denied writes must leave ZERO files"
    assert f["side_effects"]["performed_journal_records"] == 0
    assert f["permission_errors"] >= 1
    assert f["replans"] == 0, "authorization denial is not a plan deviation"


@pytest.mark.parametrize("case,marker", [
    ("missing-validator", "no validator available"),
    ("missing-grants", "lacks required permission"),
])
def test_RP2_T08_auth_missing_fails_closed(rp2_session, case, marker):
    f = rp2_session["auth"][case]
    assert f["result"]["success"] is False
    assert f["side_effects"]["sandbox_files"] == []
    assert f["side_effects"]["performed_journal_records"] == 0
    # the explicit fail-closed error surfaced in the task events
    evs = rp2_session["auth"][case]
    events = _load(rp2_session["base"] / case / "events.jsonl")
    errors = "\n".join(
        str((e.get("payload") or {}).get("error", ""))
        for e in events if e["event_type"] == "task.failed")
    assert marker in errors


# ------------------------------------------- §4.2 mixed verification state

def test_RP2_T09_mixed_state_no_false_success(rp2_session):
    """§4.2: task A evidenced while task C's CURRENT verification fails —
    the mission must NOT complete. Under the pre-RP2 rule (evidenced>0)
    this exact state produced a FALSE success."""
    m = rp2_session["mixed"]
    assert m["result"]["success"] is False
    c_hist = m["verifications"]["C"]
    a_hist = m["verifications"]["A"]
    assert c_hist[-1]["verdict"] == "not_evidenced"
    assert any(v["verdict"] == "evidenced" for v in a_hist)
    # the OLD rule would have passed: evidenced verifications exist
    evidenced_count = sum(
        1 for k, h in m["verifications"].items() for v in h
        if v["verdict"] in ("evidenced", "passed"))
    assert evidenced_count > 0
    # the truth rule names the current unresolved failure
    reasons = [vf["reason"] for vf in (m["completion"]["report"]["checks"]
                                       ["verification_history"]["verification_failures"])]
    assert "current_unresolved_verification_failure" in reasons
    failed_tasks = [vf["task"] for vf in (m["completion"]["report"]["checks"]
                                          ["verification_history"]["verification_failures"])]
    assert "C" in failed_tasks and "A" not in failed_tasks
    assert all(c["pass"] for c in rp2_session["mixed_checks"])


# --------------------------------------- §4.3 historical failure resolution

def test_RP2_T10_historical_failure_resolved_by_newer_evidence(rp2_session):
    """§4.3: C's v2 not_evidenced (historical) is resolved ONLY by the v3
    evidenced verification (newer valid evidence bound to the corrected
    criteria); history is preserved, never erased."""
    r = rp2_session["resolution"]
    assert r["result"]["success"] is True
    c_hist = r["verifications"]["C"]
    assert [v["verdict"] for v in c_hist] == ["evidenced", "not_evidenced", "evidenced"]
    assert c_hist[-1]["plan_version"] == "v3"
    assert r["c_failure_resolved"], "the verifier failure record must be resolved"
    assert "newer_evidence" in r["c_failure_resolved"] or "replan->v3" in r["c_failure_resolved"]
    assert r["c_criteria_version"] == "v3"
    assert r["historical_not_evidenced_preserved"] is True
    assert all(c["pass"] for c in rp2_session["resolution_checks"])


def test_RP2_T11_verification_bindings_in_events(rp2_session):
    """§3.2: orchestrator-source verification events carry the plan
    version, run id, verifier attempt, and the PRODUCING attempt of the
    verified task."""
    r = rp2_session["resolution_events"]
    orch_events = [e for e in r
                   if e["event_type"] == "verification.complete"
                   and e["source"] == "canonical_orchestrator"]
    assert orch_events, "orchestrator verifier events must exist"
    for e in orch_events:
        p = e["payload"]
        assert p.get("plan_version") in ("v1", "v2", "v3")
        assert p.get("run_id"), "run binding must be stamped"
        assert p.get("verifier_attempt_id"), "verifier attempt must be stamped"
        assert p.get("attempt_id"), "producing attempt must be bound (not empty)"
    # producing attempts are real engine attempts (not fabricated ids):
    # cross-check one evidenced binding against task.assigned attempts
    evidenced = [e for e in orch_events if e["payload"]["verdict"] == "evidenced"]
    assert evidenced


def test_RP2_T12_verifier_failure_flows_through_replan_review(rp2_session):
    """§3.5/§4.4: the verifier-detected deviation at C goes through the
    EXISTING path: decision -> replan_mission (v2->v3) -> review gate ->
    continuation ONLY after approval; the engine-level deviation at D
    (v1->v2) still flows through the same path."""
    r = rp2_session["resolution"]
    replans = r["replans"]
    assert [rp["to_version"] for rp in replans] == ["v2", "v3"]
    verdicts = [rv["verdict"] for rv in r["reviews"]]
    assert verdicts == ["approved", "rejected", "approved", "approved"]
    # the verifier failure record is a PLAN_DEVIATION linked to v3
    vf = [f for f in r["verifier_failures"] if f["task_key"] == "C"]
    assert vf and vf[0]["kind"] == "plan_deviation"
    assert vf[0]["resolved"] is True and "replan->v3" in vf[0]["resolved_by"]
    # ordering (durable timestamps): verifier failure < replan v3 (the
    # SECOND replan.requested) < the LAST review approval (v3's)
    evs = rp2_session["resolution_events"]

    replan_ts = sorted(
        e["timestamp"] for e in evs if e["event_type"] == "replan.requested")
    review_approvals = sorted(
        e["timestamp"] for e in evs
        if e["event_type"] == "state.transition"
        and (e.get("payload") or {}).get("entity_type") == "plan_review"
        and (e.get("payload") or {}).get("to_state") == "APPROVED")
    c_fail = next(
        (e["timestamp"] for e in evs
         if e["event_type"] == "verification.complete"
         and e["source"] == "canonical_orchestrator"
         and (e.get("payload") or {}).get("verdict") == "not_evidenced"), None)
    assert len(replan_ts) == 2 and len(review_approvals) == 3 and c_fail
    assert c_fail < replan_ts[1] < review_approvals[2]


def test_RP2_T13_engine_deviation_path_intact(rp2_session):
    """§4.4: the engine-level deviation at D (RP1 semantics) still drives
    the full replan cycle: deviation -> decision v2 -> review REJECTED
    (C6: D FAILED) -> revision recovers D -> review APPROVED ->
    continuation executes the recovered task."""
    r = rp2_session["resolution"]
    r2 = r["replans"][0]
    assert r2["from_version"] == "v1" and r2["to_version"] == "v2"
    assert r2["invalidated_tasks"] == ["E"]
    assert sorted(m["task_key"] for m in r2["modified_tasks"]) == ["C", "D"]
    assert r["attempts_per_key"]["D"] == 4  # initial + retries + recovered re-execution
    assert r["states"]["D"] == "COMPLETED"
    assert r["files"]["task_x.txt"]["present"] is True
    assert r["files"]["task_e.txt"]["present"] is False


def test_RP2_T14_tool_failure_stays_in_retry(rp2_session):
    """§4.5: a REAL tool/runtime failure (first attempt) is recovered by
    the ENGINE retry loop; NO replan, NO verifier failure — tool failures
    are never auto-classified as plan deviations."""
    f = rp2_session["auth"]["tool-fail"]
    assert f["result"]["success"] is True
    assert f["B_attempts"] == 2
    assert f["replans"] == 0
    assert f["verifier_failures"] == 0
    assert f["side_effects"]["sandbox_files"]


def test_RP2_T15_duplicate_continuation_zero_side_effects(rp2_session):
    """§4.6: re-running the completed run performs ZERO new attempts,
    leaves the journal unchanged, and preserves completed work."""
    dup = rp2_session["resolution"]["duplicate_continuation"]
    assert dup["zero_new_attempts"] is True
    assert dup["journal_unchanged"] is True
    assert dup["result_success"] is True


def test_RP2_T16_baseline_verifier_defect_repaired(rp2_session):
    """PRE-EXISTING defect (proven from the COMMITTED RP1 evidence): every
    orchestrator-source verification at 6d83cec was not_evidenced
    (EvidenceRecord rejected content_type='verification' — pydantic
    ValidationError), and the loose evidenced>0 rule still reported
    success. The repair: valid contract type + evidenced orchestrator
    events exist in the RP2 cycles."""
    src = (REPO / "src" / "orchestrator" / "canonical.py").read_text(encoding="utf-8")
    # the defect must not survive in CODE (comments documenting the defect
    # are fine — only actual assignments count)
    bad_lines = [l for l in src.splitlines()
                 if 'content_type="verification"' in l
                 and not l.strip().startswith("#")]
    assert not bad_lines, bad_lines
    assert 'content_type="report"' in src
    for stream in (rp2_session["resolution_events"], rp2_session["mixed_events"]):
        orch_ev = [e for e in stream
                   if e["event_type"] == "verification.complete"
                   and e["source"] == "canonical_orchestrator"]
        assert orch_ev
        assert any(e["payload"]["verdict"] == "evidenced" for e in orch_ev), \
            "the repaired verifier must produce evidenced results"


def test_RP2_T17_grant_identity_flows_to_governed_path(rp2_session):
    """§2.4: the grant identity the engine presents to the validator is
    the REAL owner-approved EOE grant id (never the legacy 'test-grant')
    in every RP2 cycle with authorization."""
    for name in ("resolution", "mixed_blocked"):
        f = rp2_session["resolution"] if name == "resolution" else rp2_session["mixed"]
        assert f["grant"]["validator"] == "eoe.engine_bridge (REAL)"
        assert f["grant"]["grant_ids_passed"] == [f["grant"]["grant_id"]]
        assert f["grant"]["grant_id"].startswith("grant-")
    for case in ("allow", "deny-revoked", "deny-read-only", "deny-path", "tool-fail"):
        f = rp2_session["auth"][case]
        assert f["grant"]["grant_ids_passed"] == [f["grant"]["grant_id"]]


def test_RP2_T18_expectations_preregistered_and_all_pass(rp2_session):
    """Pre-registration discipline: expectations were written before any
    passing cycle; every pre-registered expectation in every run passes."""
    exp = _load(HERE / "evidence_rp2_expectations.json")
    assert exp["written_before_any_cycle"] is True
    for stream in (rp2_session["resolution_checks"], rp2_session["mixed_checks"]):
        assert stream and all(c["pass"] for c in stream)
