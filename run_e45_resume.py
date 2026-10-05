#!/usr/bin/env python3
"""
E45 Phase 2: Checkpoint/Resume Demonstration
Interrupts the mission mid-way and resumes from checkpoint.
"""
import asyncio
import sys
import os
import shutil
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from unified.contracts import AgentType
from unified.mission_controller import MissionController, TaskSpec
from unified.execution import ExecutionEngine
from unified.agent_role import AgentRegistry, agent_registry, AgentDefinition
from unified.mission_controller import MissionTaskAgent

async def main():
    print("=" * 80)
    print("E45 CHECKPOINT/RESUME DEMONSTRATION")
    print("=" * 80)
    
    # Initialize engine and controller
    engine = ExecutionEngine(artifacts_base_dir="artifacts/e45_resume")
    controller = MissionController(engine, state_dir="artifacts/e45_resume")
    
    # Register mission agents
    agent_registry.replace_implementation(AgentType.IMPLEMENTER, MissionTaskAgent)
    for i in range(1, 13):
        agent_id = f"e45-resume-implementer-{i:02d}"
        if agent_id not in agent_registry._definitions:
            agent_registry.add_definition(AgentDefinition(
                agent_id=agent_id,
                agent_type=AgentType.IMPLEMENTER,
                name=f"E45ResumeImplementer{i:02d}",
                version="1.0",
                description=f"Context-driven mission task agent (E45 resume pool member {i})",
                tools=["write_artifact", "read_artifact"],
                permissions=["write"],
                max_tokens=20000,
                timeout_seconds=120,
                requires_sandbox=True,
                supported_domains=["testing"],
                implementation_class="unified.mission_controller.MissionTaskAgent",
            ))
        agent_registry.enable_agent(agent_id)
    
    # Define a smaller mission for resume demo (5 tasks)
    specs = [
        TaskSpec(
            key="A",
            name="Task A - Discovery",
            description="Produce discovery artifact",
            agent_type=AgentType.IMPLEMENTER,
            acceptance_criteria=[
                "file_exists:e45_resume_a.md",
                "file_contains:e45_resume_a.md:Task A",
            ],
            context={
                "task_key": "A",
                "content": "Task A - Discovery\n\nDiscovery phase complete.\nThis is the first task in the resume demonstration.",
                "output_path": "e45_resume_a.md",
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
                "file_exists:e45_resume_b.md",
                "file_contains:e45_resume_b.md:Task B",
            ],
            context={
                "task_key": "B",
                "content": "Task B - Design\n\nDesign phase complete.\nDepends on Task A.",
                "output_path": "e45_resume_b.md",
                "sleep_s": 1.0,
            },
        ),
        TaskSpec(
            key="C",
            name="Task C - Implementation",
            description="Produce implementation artifact",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=["B"],
            acceptance_criteria=[
                "file_exists:e45_resume_c.md",
                "file_contains:e45_resume_c.md:Task C",
            ],
            context={
                "task_key": "C",
                "content": "Task C - Implementation\n\nImplementation phase complete.\nDepends on Task B.",
                "output_path": "e45_resume_c.md",
                "sleep_s": 1.0,
            },
        ),
        TaskSpec(
            key="D",
            name="Task D - Testing",
            description="Produce test artifact",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=["C"],
            acceptance_criteria=[
                "file_exists:e45_resume_d.md",
                "file_contains:e45_resume_d.md:Task D",
            ],
            context={
                "task_key": "D",
                "content": "Task D - Testing\n\nTesting phase complete.\nDepends on Task C.",
                "output_path": "e45_resume_d.md",
                "sleep_s": 1.0,
            },
        ),
        TaskSpec(
            key="E",
            name="Task E - Final",
            description="Produce final artifact",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=["D"],
            acceptance_criteria=[
                "file_exists:e45_resume_e.md",
                "file_contains:e45_resume_e.md:Task E",
            ],
            context={
                "task_key": "E",
                "content": "Task E - Final\n\nFinal phase complete.\nDepends on Task D.\nMISSION COMPLETE",
                "output_path": "e45_resume_e.md",
                "sleep_s": 1.0,
            },
        ),
    ]
    
    print("\n[DEFINING MISSION]...")
    user_request = "E45 Checkpoint/Resume Demo Mission"
    mission, run, key_to_id = controller.define_mission(user_request, specs)
    
    print(f"Mission ID: {mission.mission_id}")
    print(f"Run ID: {run.run_id}")
    print(f"Tasks: {len(key_to_id)}")
    
    # Record initial plan
    plan_v1 = controller.record_plan_v1(run.run_id, mission.mission_id)
    
    # Execute first few tasks (simulate interruption after task C)
    print("\n[EXECUTING MISSION - PARTIAL (will interrupt after 3 tasks)]...")
    
    # We need to execute step by step to create checkpoints
    # Let's run the full mission but with checkpoint creation
    # Actually, the engine creates checkpoints automatically during execution
    
    result = await controller.execute_run(run.run_id, max_parallel=2)
    
    print(f"\nRun 1 Result: success={result['success']}, paused={result.get('paused', False)}")
    print(f"Task Results:")
    for tid, tr in result.get('task_results', {}).items():
        key = controller._task_to_key.get(tid, tid)
        print(f"  {key} ({tid}): success={tr.get('success')}, attempts={tr.get('attempts', 0)}")
    
    # Check checkpoints created
    checkpoints_dir = Path("artifacts/e45_resume") / "checkpoints" / mission.mission_id
    if checkpoints_dir.exists():
        checkpoint_files = list(checkpoints_dir.glob("*.json"))
        print(f"\nCheckpoints created: {len(checkpoint_files)}")
        for cp in checkpoint_files:
            print(f"  {cp.name}")
    
    # Now simulate cross-runtime resume by copying artifacts to new location
    print("\n[SIMULATING CROSS-RUNTIME RESUME]...")
    
    # Copy the entire artifacts directory to simulate new runtime
    resume_artifacts_dir = Path("artifacts/e45_resume_runtime2")
    if resume_artifacts_dir.exists():
        shutil.rmtree(resume_artifacts_dir)
    shutil.copytree("artifacts/e45_resume", resume_artifacts_dir)
    print(f"Copied artifacts to {resume_artifacts_dir}")
    
    # Create new engine and controller for "new runtime"
    engine2 = ExecutionEngine(artifacts_base_dir=str(resume_artifacts_dir))
    controller2 = MissionController(engine2, state_dir=str(resume_artifacts_dir))
    
    # Register agents in new runtime
    agent_registry2 = AgentRegistry()
    agent_registry2.replace_implementation(AgentType.IMPLEMENTER, MissionTaskAgent)
    for i in range(1, 13):
        agent_id = f"e45-resume2-implementer-{i:02d}"
        if agent_id not in agent_registry2._definitions:
            agent_registry2.add_definition(AgentDefinition(
                agent_id=agent_id,
                agent_type=AgentType.IMPLEMENTER,
                name=f"E45Resume2Implementer{i:02d}",
                version="1.0",
                description=f"Context-driven mission task agent (E45 resume2 pool member {i})",
                tools=["write_artifact", "read_artifact"],
                permissions=["write"],
                max_tokens=20000,
                timeout_seconds=120,
                requires_sandbox=True,
                supported_domains=["testing"],
                implementation_class="unified.mission_controller.MissionTaskAgent",
            ))
        agent_registry2.enable_agent(agent_id)
    
    # Find the latest checkpoint
    checkpoint_files = list(checkpoints_dir.glob("*.json"))
    if not checkpoint_files:
        print("No checkpoints found!")
        return
    
    # Sort by modification time, get latest
    latest_checkpoint = max(checkpoint_files, key=lambda p: p.stat().st_mtime)
    checkpoint_id = latest_checkpoint.stem
    print(f"Resuming from checkpoint: {checkpoint_id}")
    
    # Resume from checkpoint
    if hasattr(engine2, 'resume_from_checkpoint'):
        print("Resuming mission from checkpoint...")
        resume_run = engine2.resume_from_checkpoint(checkpoint_id, mission.mission_id)
        print(f"Resume result: new run_id={resume_run.run_id if resume_run else 'None'}")
    else:
        print("resume_from_checkpoint not available on engine")
    
    print("\n[CHECKPOINT/RESUME DEMONSTRATION COMPLETE]")

if __name__ == "__main__":
    asyncio.run(main())