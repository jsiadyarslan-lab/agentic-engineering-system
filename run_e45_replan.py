#!/usr/bin/env python3
"""
E45 Phase 3: Replanning & Human Gate Demonstration
Shows:
1. Plan deviation failure → replanning
2. Human gate during mission
3. Full evidence graph traceability
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from unified.contracts import AgentType
from unified.mission_controller import MissionController, TaskSpec
from unified.execution import ExecutionEngine
from unified.agent_role import AgentRegistry, agent_registry, AgentDefinition
from unified.mission_controller import MissionTaskAgent

async def main():
    print("=" * 80)
    print("E45 REPLANNING & HUMAN GATE DEMONSTRATION")
    print("=" * 80)
    
    # Initialize engine and controller
    engine = ExecutionEngine(artifacts_base_dir="artifacts/e45_replan")
    controller = MissionController(engine, state_dir="artifacts/e45_replan")
    
    # Register mission agents
    agent_registry.replace_implementation(AgentType.IMPLEMENTER, MissionTaskAgent)
    for i in range(1, 13):
        agent_id = f"e45-replan-implementer-{i:02d}"
        if agent_id not in agent_registry._definitions:
            agent_registry.add_definition(AgentDefinition(
                agent_id=agent_id,
                agent_type=AgentType.IMPLEMENTER,
                name=f"E45ReplanImplementer{i:02d}",
                version="1.0",
                description=f"Context-driven mission task agent (E45 replan pool member {i})",
                tools=["write_artifact", "read_artifact"],
                permissions=["write"],
                max_tokens=20000,
                timeout_seconds=120,
                requires_sandbox=True,
                supported_domains=["testing"],
                implementation_class="unified.mission_controller.MissionTaskAgent",
            ))
        agent_registry.enable_agent(agent_id)
    
    # Define mission with plan_deviation failure injection
    specs = [
        TaskSpec(
            key="A",
            name="Task A - Discovery",
            description="Produce discovery artifact",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:e45_replan_a.md",
                "file_contains:e45_replan_a.md:Task A",
            ],
            context={
                "task_key": "A",
                "content": "Task A - Discovery\n\nDiscovery phase complete.",
                "output_path": "e45_replan_a.md",
                "sleep_s": 1.0,
            },
        ),
        TaskSpec(
            key="B",
            name="Task B - Design",
            description="Produce design artifact",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=["A"],
            acceptance_criteria=[
                "file_exists:e45_replan_b.md",
                "file_contains:e45_replan_b.md:Task B",
            ],
            context={
                "task_key": "B",
                "content": "Task B - Design\n\nDesign phase complete.\nDepends on Task A.",
                "output_path": "e45_replan_b.md",
                "sleep_s": 1.0,
            },
        ),
        TaskSpec(
            key="C",
            name="Task C - Implementation",
            description="Produce implementation artifact - will trigger plan_deviation on attempt 1",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=["B"],
            acceptance_criteria=[
                "file_exists:e45_replan_c.md",
                "file_contains:e45_replan_c.md:Task C",
            ],
            context={
                "task_key": "C",
                "content": "Task C - Implementation\n\nImplementation phase complete.\nDepends on Task B.",
                "output_path": "e45_replan_c.md",
                "sleep_s": 1.0,
                "inject_plan_deviation": True,  # Trigger plan deviation on first attempt
            },
        ),
        TaskSpec(
            key="D",
            name="Task D - Testing",
            description="Produce test artifact",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=["C"],
            acceptance_criteria=[
                "file_exists:e45_replan_d.md",
                "file_contains:e45_replan_d.md:Task D",
            ],
            context={
                "task_key": "D",
                "content": "Task D - Testing\n\nTesting phase complete.\nDepends on Task C.",
                "output_path": "e45_replan_d.md",
                "sleep_s": 1.0,
            },
        ),
        TaskSpec(
            key="E",
            name="Task E - Human Gate",
            description="Human gate task - requires human decision",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=["D"],
            acceptance_criteria=[
                "file_exists:e45_replan_e.md",
                "file_contains:e45_replan_e.md:HUMAN_APPROVED",
            ],
            context={
                "task_key": "E",
                "content": "Task E - Human Gate\n\nAwaiting human decision...",
                "output_path": "e45_replan_e.md",
                "sleep_s": 1.0,
                "human_gate": True,
            },
        ),
        TaskSpec(
            key="F",
            name="Task F - Final",
            description="Produce final artifact after human approval",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=["E"],
            acceptance_criteria=[
                "file_exists:e45_replan_f.md",
                "file_contains:e45_replan_f.md:FINAL_COMPLETE",
            ],
            context={
                "task_key": "F",
                "content": "Task F - Final\n\nFinal phase complete.\nHUMAN_APPROVED\nMISSION COMPLETE",
                "output_path": "e45_replan_f.md",
                "sleep_s": 1.0,
            },
        ),
    ]
    
    print("\n[DEFINING MISSION]...")
    user_request = "E45 Replanning & Human Gate Demo Mission"
    mission, run, key_to_id = controller.define_mission(user_request, specs)
    
    print(f"Mission ID: {mission.mission_id}")
    print(f"Run ID: {run.run_id}")
    print(f"Tasks: {len(key_to_id)}")
    
    # Record initial plan
    plan_v1 = controller.record_plan_v1(run.run_id, mission.mission_id)
    print(f"Initial plan recorded with {len(plan_v1.get('tasks', []))} tasks")
    
    # Execute mission
    print("\n[EXECUTING MISSION]...")
    result = await controller.execute_run(run.run_id, max_parallel=2)
    
    print(f"\nRun Result: success={result['success']}, paused={result.get('paused', False)}")
    print(f"Task Results:")
    for tid, tr in result.get('task_results', {}).items():
        key = controller._task_to_key.get(tid, tid)
        print(f"  {key} ({tid}): success={tr.get('success')}, attempts={tr.get('attempts', 0)}, error={tr.get('error', 'none')}")
    
    # Check failures
    failures = controller.get_failures(run.run_id)
    print(f"\nFailures detected: {len(failures)}")
    for f in failures:
        print(f"  {f.failure_id}: {f.failure_type.value} - {f.task_key} - recovery={f.recovery_action}")
    
    # Check replans
    replans = controller.get_replans(run.run_id)
    print(f"\nReplans: {len(replans)}")
    for r in replans:
        print(f"  {r.replan_id}: trigger={r.trigger.value}, added={len(r.added_tasks)}, removed={len(r.removed_tasks)}")
    
    # Check human gates
    human_gates = engine.get_human_gates(mission.mission_id)
    print(f"\nHuman Gates: {len(human_gates)}")
    for hg in human_gates:
        print(f"  {hg['gate_id']}: state={hg['state']}, decision={hg.get('decision', 'pending')}")
    
    # Check checkpoints
    checkpoints_dir = Path("artifacts/e45_replan") / "checkpoints" / mission.mission_id
    if checkpoints_dir.exists():
        checkpoint_files = list(checkpoints_dir.glob("*.json"))
        print(f"\nCheckpoints created: {len(checkpoint_files)}")
        for cp in checkpoint_files:
            print(f"  {cp.name}")
    
    # Check evidence chain
    evidence = engine.evidence_store.get_evidence_for_mission(mission.mission_id)
    print(f"\nEvidence chain records: {len(evidence)}")
    
    # Check events
    events = engine.event_bus.get_events_for_mission(mission.mission_id)
    print(f"Event trace: {len(events)} events")
    
    print("\n[REPLANNING & HUMAN GATE DEMONSTRATION COMPLETE]")
    
    # Now demonstrate human gate resolution
    if human_gates:
        gate_id = human_gates[0]['gate_id']
        print(f"\n[RESOLVING HUMAN GATE: {gate_id}]...")
        # Simulate human decision
        decision_result = controller.resolve_human_gate(mission.mission_id, gate_id, "approve", "Human approved after review")
        print(f"Human gate resolved: {decision_result}")
        
        # Resume execution after human approval
        print("\n[RESUMING MISSION AFTER HUMAN APPROVAL]...")
        # The mission should now continue from the human gate
        # Find the current run and continue
        mission_obj = engine.missions.get(mission.mission_id)
        if mission_obj:
            # Check current state
            print(f"Mission state: {mission_obj.state}")
            # If paused at human gate, resume
            if mission_obj.state.value == "human_required":
                # Request resume
                engine.missions[mission.mission_id].metadata["human_decision"] = {"decision": "approve", "reason": "Human approved after review", "decided_at": "2024-01-01T00:00:00Z"}
                result2 = await controller.execute_run(run.run_id, max_parallel=2)
                print(f"Run 2 Result: success={result2['success']}")
                print(f"Task Results:")
                for tid, tr in result2.get('task_results', {}).items():
                    key = controller._task_to_key.get(tid, tid)
                    print(f"  {key}: success={tr.get('success')}")

if __name__ == "__main__":
    asyncio.run(main())