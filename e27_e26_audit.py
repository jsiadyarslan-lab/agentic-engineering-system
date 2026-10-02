"""
E27 — E26 EVIDENCE AUDIT
Verify all E26 evidence files exist and are parseable.
"""

import json
import os
import sys

def audit_e26_evidence():
    evidence_dir = "docs/evidence/e26"
    
    expected_files = [
        "E26_BASELINE.json",
        "FINAL_REPORT.md",
        "E26_REPRODUCTION.json",
        "E26_MULTI_RUN_ISOLATION.json",
        "E26_FAILURE_MATRIX.json",
        "E26_CHECKPOINT_INTEGRITY.json",
        "E26_EVENT_INTEGRITY.json",
        "E26_STATE_EVENT_CONSISTENCY.json",
        "E26_TASK_GRAPH_STRESS.json",
    ]
    
    # Also check phase trace files
    expected_traces = [
        "phase_1_create_missions_trace.json",
        "phase_2_checkpoint_isolation_trace.json",
        "f01_task_failure_trace.json",
        "f02_dependent_blocked_trace.json",
        "f03_tool_failure_trace.json",
        "f04_timeout_trace.json",
        "f05_retry_trace.json",
        "f06_checkpoint_resume_trace.json",
        "f07_invalid_transition_trace.json",
        "f08_duplicate_resume_trace.json",
        "f09_duplicate_completion_trace.json",
        "f10_partial_artifact_trace.json",
        "f11_verification_failure_trace.json",
        "f12_replan_trace.json",
        "f13_human_gate_trace.json",
        "f14_cancellation_trace.json",
        "f15_resource_limits_trace.json",
        "phase_1_initial_execution_trace.json",
        "phase_2_resume_trace.json",
        "phase_3_execute_remaining_trace.json",
        "phase_4_replan_trace.json",
        "phase_4_execute_recovery_trace.json",
        "phase_5_human_gate_trace.json",
        "phase_6_second_checkpoint_trace.json",
        "phase_7_second_resume_trace.json",
        "phase_8_final_execution_trace.json",
        "phase_9_final_verification_trace.json",
        "cp01_checkpoint_completeness_trace.json",
        "cp02_checkpoint_serialization_trace.json",
        "cp03_checkpoint_state_accuracy_trace.json",
        "cp04_checkpoint_evidence_trace.json",
        "cp05_checkpoint_corruption_trace.json",
        "ev01_event_sequence_trace.json",
        "ev02_event_payloads_trace.json",
        "ev03_event_causality_trace.json",
        "ev04_no_duplicate_events_trace.json",
        "ev05_events_across_resume_trace.json",
        "sc01_mission_state_events_trace.json",
        "sc02_task_state_events_trace.json",
        "sc03_invalid_transitions_trace.json",
        "sc04_state_after_resume_trace.json",
        "sc05_no_orphan_events_trace.json",
        "tg01_large_graph_trace.json",
        "tg02_deep_chain_trace.json",
        "tg03_concurrent_missions_trace.json",
        "tg04_replan_under_load_trace.json",
        "tg05_cycle_detection_trace.json",
    ]
    
    all_expected = expected_files + expected_traces
    
    results = []
    
    for filename in all_expected:
        filepath = os.path.join(evidence_dir, filename)
        result = {
            "artifact": filename,
            "exists": os.path.exists(filepath),
            "parseable": False,
            "claim": "E26 test artifact",
            "observed": "",
            "verdict": "MISSING"
        }
        
        if result["exists"]:
            try:
                if filename.endswith(".json"):
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    result["parseable"] = True
                    result["observed"] = f"JSON parsed, {len(data)} top-level keys" if isinstance(data, dict) else f"JSON parsed, {len(data)} items"
                else:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    result["parseable"] = True
                    result["observed"] = f"Text file, {len(content)} chars"
                result["verdict"] = "VERIFIED"
            except Exception as e:
                result["observed"] = f"Parse error: {str(e)}"
                result["verdict"] = "PARSE_FAILED"
        
        results.append(result)
        mark = "OK" if result['verdict'] == 'VERIFIED' else "FAIL"
        print(f"[{mark}] {filename}: {result['verdict']}")
    
    # Summary
    verified = sum(1 for r in results if r["verdict"] == "VERIFIED")
    missing = sum(1 for r in results if r["verdict"] == "MISSING")
    parse_failed = sum(1 for r in results if r["verdict"] == "PARSE_FAILED")
    
    print(f"\n=== AUDIT SUMMARY ===")
    print(f"Total: {len(results)}")
    print(f"Verified: {verified}")
    print(f"Missing: {missing}")
    print(f"Parse Failed: {parse_failed}")
    
    # Save audit
    audit = {
        "timestamp": "2026-10-03T02:00:00.000000+00:00",
        "e26_evidence_dir": evidence_dir,
        "summary": {
            "total": len(results),
            "verified": verified,
            "missing": missing,
            "parse_failed": parse_failed
        },
        "artifacts": results
    }
    
    with open("docs/evidence/e27/e27_e26_audit.json", "w") as f:
        json.dump(audit, f, indent=2)
    
    print(f"\nAudit saved to docs/evidence/e27/e27_e26_audit.json")
    return audit

if __name__ == "__main__":
    os.makedirs("docs/evidence/e27", exist_ok=True)
    audit_e26_evidence()