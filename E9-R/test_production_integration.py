#!/usr/bin/env python3
"""
E9-R Production Integration Test

This test verifies that the production execution path uses ToolExecutor:
Mission → Run → Task → Agent → ToolExecutor → Tool → Sandbox → Artifact → Evidence → Verification

This is the REAL acceptance test for E9-R - it must fail if ToolExecutor is bypassed.
"""

import asyncio
import sys
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from unified.contracts import (
    Mission, Run, Task, TaskState, MissionState, AgentType, ToolRiskLevel,
    Artifact, EvidenceRecord, EventType, FactoryEvent,
    create_mission, create_run, create_task, new_artifact_id, new_evidence_id,
    validate_mission_transition, validate_task_transition,
)
from unified.mission_controller import TaskSpec
from unified.execution import (
    ExecutionEngine, ExecutionContext, ToolExecutor, SandboxManager,
    FileEvidenceStore, SimpleEventBus, create_sandbox_manager,
)
from unified.tool_contract import ToolRegistry, ALL_TOOL_CONTRACTS
from unified.mission_controller import MissionController, register_mission_agent
from unified.agent_role import AgentRegistry, AgentFactory, BaseAgent, AgentContext, AgentTask, AgentResult, AgentDefinition, AgentLifecycleState
from typing import Any


async def run_production_integration_test():
    """Run the production integration test through the full orchestration path."""
    
    print("=" * 80)
    print("E9-R PRODUCTION INTEGRATION TEST")
    print("=" * 80)
    
    # Create engine with temporary artifacts directory
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = os.path.join(tmpdir, "artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        
        def simple_grant_validator(grant_id: str, permission: str) -> bool:
            # For testing: allow all permissions
            return True
        
        # Create engine with grant validator
        engine = ExecutionEngine(artifacts_base_dir=artifacts_dir, grant_validator=simple_grant_validator)
        
        # Register mission agents
        agent_registry = engine.agent_registry
        register_mission_agent(agent_registry, pool_size=5)
        
        # Create mission controller
        mc = MissionController(engine)
        
        # Create a mission with a single task that produces an artifact
        task_spec = TaskSpec(
            key="TASK_A",
            name="produce_artifact",
            description="Produce a test artifact via ToolExecutor",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[],
            acceptance_criteria=["Artifact created via ToolExecutor", "Action record exists"],
            context={
                "task_key": "TASK_A",
                "content": "E9-R Production Test Artifact Content",
                "output_path": "e9r_test_artifact.txt",
                "sleep_s": 0.1,
            }
        )
        
        # Use define_mission to create mission, run, and task graph
        mission, run, key_to_id = mc.define_mission("E9-R Production Integration Test Mission", [task_spec])
        task_id = key_to_id["TASK_A"]
        print(f"Created mission: {mission.mission_id}")
        print(f"Created run: {run.run_id}")
        print(f"Created task: {task_id}")
        
        # Execute the task graph (this is the REAL production path)
        print("\nExecuting task graph via production orchestration...")
        result = await mc.execute_run(run.run_id, max_parallel=1)
        
        print(f"\nExecution result: {json.dumps(result, indent=2, default=str)}")
        
        # Verify the task completed successfully
        task_result = result.get("task_results", {}).get(task_id, {})
        if not task_result.get("success", False):
            print(f"FAIL: Task did not complete successfully: {task_result}")
            return False
            
        print("PASS: Task completed successfully")
        
        # Now verify the ToolExecutor was used by checking:
        # 1. Action record exists with correct tool_name
        # 2. Events include ACTION_REQUESTED, ACTION_VALIDATED, TOOL_COMPLETED
        # 3. Artifact was created with proper evidence
        
        # Check engine's actions
        actions = engine.actions
        print(f"\nTotal actions recorded: {len(actions)}")
        
        tool_executor_actions = [a for a in actions.values() if a.tool_name == "artifact_write"]
        print(f"Actions with tool_name='artifact_write': {len(tool_executor_actions)}")
        
        if len(tool_executor_actions) == 0:
            print("FAIL: No Action record found for artifact_write tool")
            print("   This means ToolExecutor was BYPASSED in production path!")
            return False
            
        action = tool_executor_actions[0]
        print("PASS: Action found: " + action.action_id)
        print("   tool_name: " + action.tool_name)
        print("   attempt_id: " + action.attempt_id)
        print("   success: " + str(action.success))
        print("   completed_at: " + str(action.completed_at))
        
        # Verify action is linked to mission/run/task/attempt
        if action.attempt_id:
            attempt = engine.attempts.get(action.attempt_id)
            if attempt:
                print(f"   attempt.task_id: {attempt.task_id}")
                print(f"   attempt.agent_id: {attempt.agent_id}")
                if attempt.task_id == task_id:
                    print("PASS: Action correctly linked to task")
                else:
                    print("FAIL: Action linked to wrong task: " + attempt.task_id + " != " + task_id)
                    return False
            else:
                print("FAIL: Attempt not found: " + action.attempt_id)
                return False
        else:
            print("FAIL: Action has no attempt_id")
            return False
            
        # Check events for the required sequence
        events = engine.event_bus.history
        event_types = [e.event_type for e in events]
        print(f"\nTotal events: {len(events)}")
        print(f"Event types: {set(event_types)}")
        
        required_events = ["action.requested", "action.validated", "tool.completed"]
        for req_event in required_events:
            if req_event in event_types:
                print("PASS: Event found: " + req_event)
            else:
                print("FAIL: Required event missing: " + req_event)
                return False
                
        # Verify artifact was created
        artifacts = engine.artifacts
        print(f"\nTotal artifacts: {len(artifacts)}")
        
        test_artifacts = [a for a in artifacts.values() if "e9r_test_artifact" in a.path]
        if len(test_artifacts) == 0:
            print("FAIL: No test artifact found")
            return False
            
        artifact = test_artifacts[0]
        print("PASS: Artifact found: " + artifact.artifact_id)
        print(f"   path: {artifact.path}")
        print(f"   sha256: {artifact.sha256}")
        print(f"   size_bytes: {artifact.size_bytes}")
        print(f"   mission_id: {artifact.mission_id}")
        
        # Verify evidence
        evidence_records = engine.evidence
        print(f"\nTotal evidence records: {len(evidence_records)}")
        
        artifact_evidence = [e for e in evidence_records.values() if e.source_id == artifact.artifact_id]
        if len(artifact_evidence) == 0:
            print("FAIL: No evidence record for artifact")
            return False
            
        evidence = artifact_evidence[0]
        print("PASS: Evidence found: " + evidence.evidence_id)
        print(f"   evidence_hash: {evidence.evidence_hash}")
        print(f"   content_type: {evidence.content_type}")
        print(f"   source_id: {evidence.source_id}")
        print(f"   mission_id: {evidence.mission_id}")
        print(f"   run_id: {evidence.run_id}")
        print(f"   task_id: {evidence.task_id}")
        
        # Verify hash integrity - artifact file is in sandbox directory
        sandbox_id = f"sandbox-{task_id}"
        artifact_path = os.path.join(artifacts_dir, sandbox_id, artifact.path)
        if os.path.exists(artifact_path):
            with open(artifact_path, 'rb') as f:
                content = f.read()
            computed_hash = hashlib.sha256(content).hexdigest()
            if computed_hash == artifact.sha256 == evidence.evidence_hash:
                print("PASS: Hash integrity verified: artifact.sha256 == evidence.evidence_hash == computed")
            else:
                print("FAIL: Hash mismatch!")
                print("   artifact.sha256: " + artifact.sha256)
                print("   evidence.evidence_hash: " + evidence.evidence_hash)
                print("   computed: " + computed_hash)
                return False
        else:
            print("FAIL: Artifact file not found: " + artifact_path)
            return False
            
        # Verify the action has the action_id in the tool result
        if hasattr(action, 'output') and action.output:
            print(f"   action.output: {action.output}")
        
        print("\n" + "=" * 80)
        print("PASS: E9-R PRODUCTION INTEGRATION TEST PASSED")
        print("   ToolExecutor was used in the REAL production execution path!")
        print("=" * 80)
        return True


async def run_negative_tests():
    """Run negative tests through the production path."""
    print("\n" + "=" * 80)
    print("E9-R NEGATIVE TESTS (Production Path)")
    print("=" * 80)
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = os.path.join(tmpdir, "artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        
        all_passed = True
        
        # Test 1: Unauthorized tool access (should be rejected by permission check)
        print("\n--- Test 1: Unauthorized Tool (artifact_write without valid grant) ---")
        
        def restrictive_grant_validator(grant_id: str, permission: str) -> bool:
            # Only allow specific test grant
            return grant_id == "valid-test-grant" and permission == "sandbox.write"
        
        engine = ExecutionEngine(artifacts_base_dir=artifacts_dir, grant_validator=restrictive_grant_validator)
        agent_registry = engine.agent_registry
        register_mission_agent(agent_registry, pool_size=5)
        mc = MissionController(engine)
        
        # Task with invalid grant
        task_spec = TaskSpec(
            key="UNAUTH",
            name="unauthorized_write",
            description="Attempt write without valid grant",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[],
            acceptance_criteria=[],
            context={
                "task_key": "UNAUTH",
                "content": "Should fail",
                "output_path": "unauthorized.txt",
            }
        )
        
        mission, run, key_to_id = mc.define_mission("Negative Test - Unauthorized", [task_spec])
        task_id = key_to_id["UNAUTH"]
        # The context will have grant_ids=["test-grant"] which doesn't match "valid-test-grant"
        result = await mc.execute_run(run.run_id, max_parallel=1)
        
        task_result = result.get("task_results", {}).get(task_id, {})
        if not task_result.get("success", True):  # Should fail
            print("PASS: Unauthorized tool correctly rejected")
            # Note: Permission errors occur before Action creation, so no failed action is recorded
            # This is correct security behavior - no action record for unauthorized attempts
            print("   (No action record for permission failure - correct security behavior)")
        else:
            print("FAIL: Unauthorized tool was not rejected")
            all_passed = False
        
        # Test 2: Valid grant should work
        print("\n--- Test 2: Authorized Tool (with valid grant) ---")
        
        def permissive_grant_validator(grant_id: str, permission: str) -> bool:
            return True
        
        engine2 = ExecutionEngine(artifacts_base_dir=artifacts_dir + "2", grant_validator=permissive_grant_validator)
        agent_registry2 = engine2.agent_registry
        register_mission_agent(agent_registry2, pool_size=5)
        mc2 = MissionController(engine2)
        
        task_spec2 = TaskSpec(
            key="AUTH",
            name="authorized_write",
            description="Write with valid grant",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[],
            acceptance_criteria=[],
            context={
                "task_key": "AUTH",
                "content": "Should succeed",
                "output_path": "authorized.txt",
            }
        )
        
        mission2, run2, key_to_id2 = mc2.define_mission("Negative Test - Authorized", [task_spec2])
        task_id2 = key_to_id2["AUTH"]
        result2 = await mc2.execute_run(run2.run_id, max_parallel=1)
        
        task_result2 = result2.get("task_results", {}).get(task_id2, {})
        if task_result2.get("success", False):
            print("PASS: Authorized tool correctly allowed")
        else:
            print("FAIL: Authorized tool was rejected")
            all_passed = False
            
        return all_passed


# Custom agent for human gate test that uses run_command (HIGH risk)
class HumanGateTestAgent(BaseAgent):
    """Agent that executes run_command to trigger human gate."""
    
    def __init__(self):
        super().__init__(AgentType.IMPLEMENTER)
    
    async def execute(self, context: AgentContext, task: AgentTask) -> AgentResult:
        start_time = asyncio.get_event_loop().time()
        started_at = datetime.now(timezone.utc).isoformat()
        
        def _result(success: bool, **kw: Any) -> AgentResult:
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                success=success,
                output={"task_key": task.context.get("task_key", ""), "started_at": started_at,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "process_pid": os.getpid(), "duration_ms": duration_ms, **kw},
                evidence_hash=kw.get("evidence_hash", ""),
                artifacts=kw.get("artifacts", [])
            )
        
        ctx = task.context
        task_key = ctx.get("task_key", "")
        command = ctx.get("command", ["echo", "test"])
        working_dir = str(ctx.get("working_dir", "."))
        
        # Handle case where command might be a string representation of a list
        if isinstance(command, str):
            try:
                import ast
                command = ast.literal_eval(command)
            except:
                command = [command]
        elif not isinstance(command, list):
            command = [str(command)]
        
        # Use ToolExecutor for run_command (HIGH risk - triggers human gate)
        tool_executor = getattr(context, "tool_executor", None)
        print(f"DEBUG HumanGateTestAgent: tool_executor = {tool_executor}")
        if tool_executor is None:
            return _result(False, error="ToolExecutor not available", error_type="ConfigurationError")
        
        try:
            print(f"DEBUG HumanGateTestAgent: Calling tool_executor.execute_tool for run_command")
            tool_result = await tool_executor.execute_tool(
                context=context,
                tool_name="run_command",
                tool_input={
                    "command": command,
                    "working_dir": working_dir,
                    "timeout": 30,
                }
            )
            
            print(f"DEBUG HumanGateTestAgent: tool_result = success={tool_result.success}, error={tool_result.error}, output={tool_result.output}")
            if tool_result.success:
                return _result(True, output=tool_result.output, artifacts=[tool_result.output.get("stdout", "")] if tool_result.output else [])
            else:
                return _result(False, error=tool_result.error or "Tool failed", error_type=tool_result.error_type or "ToolExecutionError")
                
        except Exception as e:
            import traceback
            print(f"DEBUG HumanGateTestAgent: Exception: {traceback.format_exc()}")
            return _result(False, error=f"Execution error: {type(e).__name__}: {e}", error_type=type(e).__name__)


async def run_human_gate_test():
    """Test human gate through production path with a HIGH/CRITICAL risk tool."""
    print("\n" + "=" * 80)
    print("E9-R HUMAN GATE TEST (Production Path)")
    print("=" * 80)
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = os.path.join(tmpdir, "artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        
        def simple_grant_validator(grant_id: str, permission: str) -> bool:
            return True
        
        # Create engine with fresh agent registry to avoid global registry pollution
        from unified.agent_role import AgentRegistry
        fresh_agent_registry = AgentRegistry()
        
        engine = ExecutionEngine(artifacts_base_dir=artifacts_dir, grant_validator=simple_grant_validator)
        # Replace the global registry with our fresh one
        engine.agent_registry = fresh_agent_registry
        engine.agent_factory = AgentFactory(fresh_agent_registry)
        agent_registry = fresh_agent_registry
        
        print(f"DEBUG: Fresh registry definitions: {list(agent_registry._definitions.keys())}")
        print(f"DEBUG: Fresh registry implementations: {list(agent_registry._implementations.keys())}")
        
        # Register ONLY the human gate test agent (no default mission agents)
        from unified.agent_role import AgentDefinition
        agent_def = AgentDefinition(
            agent_id="human-gate-test-agent",
            agent_type=AgentType.IMPLEMENTER,
            name="Human Gate Test Agent",
            description="Agent that uses run_command to trigger human gate",
            implementation="E9-R.test_production_integration.HumanGateTestAgent",
            capabilities=["run_command"],
            lifecycle_state=AgentLifecycleState.AVAILABLE,
        )
        agent_registry.register_definition(agent_def)
        # Enable the agent (transitions from REGISTERED to AVAILABLE)
        agent_registry.enable_agent("human-gate-test-agent")
        # Register the implementation class for IMPLEMENTER type
        agent_registry.register_implementation(AgentType.IMPLEMENTER, HumanGateTestAgent)
        
        print(f"DEBUG: After registration - definitions: {list(agent_registry._definitions.keys())}")
        print(f"DEBUG: After registration - implementations: {list(agent_registry._implementations.keys())}")
        print(f"DEBUG: Agent state: {agent_registry.get_lifecycle_state('human-gate-test-agent')}")
        
        mc = MissionController(engine)
        
        # Create mission and run using define_mission
        task_spec = TaskSpec(
            key="HUMAN_GATE",
            name="human_gate_test",
            description="Test human gate for HIGH risk tool (run_command)",
            agent_type=AgentType.IMPLEMENTER,
            depends_on=[],
            acceptance_criteria=[],
            context={
                "task_key": "HUMAN_GATE",
                "command": ["echo", "hello from run_command"],
                "working_dir": ".",
            }
        )
        
        mission, run, key_to_id = mc.define_mission("Human Gate Test", [task_spec])
        task_id = key_to_id["HUMAN_GATE"]
        
        # Try to execute - should pause for human gate
        print("Executing task with HIGH risk tool (run_command)...")
        result = await mc.execute_run(run.run_id, max_parallel=1)
        
        print(f"Result: {json.dumps(result, default=str, indent=2)}")
        
        # Check if human gate was triggered
        if result.get("human_gate") or result.get("paused"):
            print("PASS: Human gate triggered - execution paused")
            gate_info = result.get("gate_info", result.get("pause_info", {}))
            print("   Gate info: " + str(gate_info))
            
            # Simulate human approval
            gate_id = gate_info.get("gate_id") or mission.metadata.get("human_gate", {}).get("gate_id")
            if gate_id:
                print("Simulating human approval for gate: " + gate_id)
                approve_result = engine.decide_human_gate(
                    mission_id=mission.mission_id,
                    gate_id=gate_id,
                    decision="approve",
                    actor="test_user",
                    feedback="Approved for testing"
                )
                print("Approval result: " + str(approve_result))
                
                # Verify mission state changed back to EXECUTING
                mission_after = engine.missions.get(mission.mission_id)
                if mission_after and mission_after.state == MissionState.EXECUTING:
                    print("PASS: Mission state returned to EXECUTING after approval")
                    print("PASS: Human gate mechanism verified (gate created -> approval -> state restored)")
                    return True
                else:
                    print("FAIL: Mission state not restored after approval: " + str(mission_after.state if mission_after else "None"))
                    return False
            else:
                print("FAIL: No gate_id found")
                return False
        else:
            print("WARN: Human gate not triggered - checking if run_command was used")
            # Check if the agent actually tried to use run_command
            events = engine.event_bus.history
            tool_started = [e for e in events if e.event_type == "tool.started" and getattr(e, 'payload', {}).get('tool_name') == 'run_command']
            if tool_started:
                print("   run_command was attempted but no human gate - checking risk level")
            else:
                print("   run_command was not attempted - agent may not be using ToolExecutor")
            return False


async def main():
    """Main test runner."""
    print("Starting E9-R Production Integration Tests\n")
    
    # Test 1: Positive production integration test
    test1_passed = await run_production_integration_test()
    
    # Test 2: Negative tests
    test2_passed = await run_negative_tests()
    
    # Test 3: Human gate test
    test3_passed = await run_human_gate_test()
    
    print("\n" + "=" * 80)
    print("E9-R TEST SUMMARY")
    print("=" * 80)
    print(f"Production Integration Test: {'PASS' if test1_passed else 'FAIL'}")
    print(f"Negative Tests:              {'PASS' if test2_passed else 'FAIL'}")
    print(f"Human Gate Test:             {'PASS' if test3_passed else 'FAIL'}")
    
    all_passed = test1_passed and test2_passed and test3_passed
    print(f"\nOVERALL: {'PASS' if all_passed else 'FAIL'}")
    
    if all_passed:
        print("\nPASS: E9-R VERIFIED - ToolExecutor integrated into production path!")
    else:
        print("\nFAIL: E9-R REPAIR REQUIRED")
        
    return all_passed


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)