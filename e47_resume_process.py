#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from unified.execution import ExecutionEngine
from unified.mission_controller import MissionController, AgentType, register_mission_agent
from unified.agent_role import AgentRegistry, AgentDefinition, AgentFactory
from unified.operational import OperationalVerifierAgent
from unified.contracts import MissionState, TaskState, EventType
from unified.domain_model import Mission, Run, Task

async def resume():
    print("=" * 70)
    print("E47 - PROCESS B: RESUME FROM CHECKPOINT")
    print("=" * 70)
    
    process_b_pid = os.getpid()
    print(f"Process B PID: {process_b_pid}")
    
    # Load resume info
    with open("docs/evidence/e47/e47_resume_info.json") as f:
        resume_info = json.load(f)
    
    mission_id = resume_info["mission_id"]
    run_id = resume_info["run_id"]
    checkpoint_id = resume_info["checkpoint_id"]
    process_a_pid = resume_info["process_a_pid"]
    
    print(f"Resuming mission: {mission_id}")
    print(f"Run: {run_id}")
    print(f"Checkpoint: {checkpoint_id}")
    print(f"Process A was: {process_a_pid}")
    print(f"Process B is:  {process_b_pid}")
    print(f"Different processes: {process_a_pid != process_b_pid}")
    
    # Initialize new engine
    engine = ExecutionEngine(artifacts_base_dir="artifacts/e47")
    
    # Register agents (same as Process A)
    registry = AgentRegistry()
    
    implementer_ids = register_mission_agent(registry, pool_size=4)
    print(f"  Registered implementers: {implementer_ids}")
    
    verifier_def = AgentDefinition(
        agent_id="e47-verifier-01",
        agent_type=AgentType.VERIFIER,
        name="E47 Operational Verifier",
        version="1.0",
        description="Independent mechanical verifier",
        tools=["verify_artifact", "read_artifact"],
        permissions=["read"],
        max_tokens=10000,
        timeout_seconds=120,
        requires_sandbox=True,
        supported_domains=["verification", "evidence_validation"],
        implementation_class="unified.operational.OperationalVerifierAgent",
    )
    registry.add_definition(verifier_def)
    registry.enable_agent("e47-verifier-01")
    verifier_ids = ["e47-verifier-01"]
    
    registry.register_implementation(AgentType.VERIFIER, OperationalVerifierAgent)
    
    engine.agent_registry = registry
    engine.agent_factory = AgentFactory(registry)
    # Use engine's built-in evidence store
    
    controller = MissionController(engine, state_dir="artifacts/e47/mission_controller")
    
    # Resume from checkpoint
    print("\n[RESUME FROM CHECKPOINT]")
    resumed_run = engine.resume_from_checkpoint(checkpoint_id, mission_id)
    
    if not resumed_run:
        print("  FAILED: Could not resume from checkpoint")
        return False
    
    # CRITICAL: Use the NEW run_id returned by resume_from_checkpoint
    resumed_run_id = resumed_run.run_id
    print(f"  Resumed run: {resumed_run_id}")
    
    # RESTORE _key_to_task mapping from checkpoint task_definitions
    # This is needed for verify_completion to work correctly
    checkpoint = engine.checkpoints.get(checkpoint_id)
    if checkpoint and checkpoint.task_definitions:
        controller._key_to_task = {}
        for tid, tdef in checkpoint.task_definitions.items():
            key = tdef.get("key")
            if key:
                controller._key_to_task[key] = tid
        print(f"  Restored _key_to_task mapping: {controller._key_to_task}")
    
    # Check restored state (using new run_id)
    graph = engine.task_graph.get(resumed_run_id, {})
    for tid, node in graph.items():
        key = controller._task_to_key.get(tid, tid)
        print(f"    Task {key} ({tid}): state={node['state']}")
    
    # Continue execution from where we left off (using new run_id)
    print("\n[CONTINUE EXECUTION AFTER RESUME]")
    result = await controller.execute_run(resumed_run_id, max_parallel=2)
    
    print(f"  Continued execution success: {result['success']}")
    
    # Check final states (using new run_id)
    graph = engine.task_graph.get(resumed_run_id, {})
    for tid, node in graph.items():
        key = controller._task_to_key.get(tid, tid)
        print(f"    Task {key} ({tid}): state={node['state']}")
    
    # Verify completion (using new run_id)
    required_keys = ["A", "B"]
    ok, report = controller.verify_completion(resumed_run_id, required_keys)
    
    print(f"\n[COMPLETION VERIFICATION]")
    print(f"  Verdict: {report['verdict']}")
    for check_name, check_result in report['checks'].items():
        print(f"    {check_name}: passed={check_result['passed']}")
    
    if ok:
        print("\n[FINALIZE MISSION]")
        finalize_result = controller.finalize_mission(mission_id, resumed_run_id, "E47 autonomous completion verified")
        print(f"  Final state: {finalize_result['final_state']}")
        print(f"  State path: {finalize_result['state_path']}")
        
        # Save truth
        truth = {
            "mission_id": mission_id,
            "run_id": resumed_run_id,
            "process_a_pid": process_a_pid,
            "process_b_pid": process_b_pid,
            "checkpoint_id": checkpoint_id,
            "verdict": "COMPLETE",
            "final_state": finalize_result['final_state'],
            "process_a_ne_process_b": process_a_pid != process_b_pid
        }
        
        with open("docs/evidence/e47/e47_completion_truth.json", "w") as f:
            json.dump(truth, f, indent=2)
        
        print("\nE47 PROCESS B: COMPLETE - MISSION VERIFIED")
        return True
    else:
        print("\nE47 PROCESS B: INCOMPLETE")
        return False

if __name__ == "__main__":
    result = asyncio.run(resume())
    sys.exit(0 if result else 1)
