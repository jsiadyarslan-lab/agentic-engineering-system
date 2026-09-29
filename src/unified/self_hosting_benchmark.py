"""
Self-Hosting Benchmark Definition — Unified Engineering Agents System

The ultimate test: Can the system build itself?
This defines benchmarks for the system to implement its own features.

Based on: EAS v2 self-hosting goal + AgentFactory dogfooding
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import json


# ============================================================
# BENCHMARK PHILOSOPHY
# ============================================================

BENCHMARK_PHILOSOPHY = """
SELF-HOSTING BENCHMARK PRINCIPLE:
=================================

"The system must be capable of implementing its own features."

If the Engineering Agents System cannot build the Engineering Agents System,
it is not fit for purpose.

This is the ultimate dogfooding test. Every feature we build must be
implementable by the agents themselves.

BENCHMARK LEVELS:
- Level 0: Hello World (VS-001) - Create a file
- Level 1: Single Agent - Implement one agent role
- Level 2: Multi-Agent - Implement planner + implementer + verifier
- Level 3: Full Feature - Implement a complete subsystem (e.g., grants)
- Level 4: Self-Build - System builds the unified system from scratch
- Level 5: Self-Improve - System improves its own codebase

SUCCESS CRITERIA PER LEVEL:
- Mission reaches VERIFIED with human approval
- All code passes existing tests
- No mock in production paths
- Evidence chain complete for all artifacts
"""


# ============================================================
# BENCHMARK LEVELS
# ============================================================

class BenchmarkLevel(Enum):
    LEVEL_0_HELLO_WORLD = "level_0_hello_world"
    LEVEL_1_SINGLE_AGENT = "level_1_single_agent"
    LEVEL_2_MULTI_AGENT = "level_2_multi_agent"
    LEVEL_3_SUBSYSTEM = "level_3_subsystem"
    LEVEL_4_SELF_BUILD = "level_4_self_build"
    LEVEL_5_SELF_IMPROVE = "level_5_self_improve"


@dataclass
class BenchmarkMission:
    """A self-hosting benchmark mission."""
    level: BenchmarkLevel
    name: str
    description: str
    user_request: str
    expected_artifacts: List[str]
    expected_agents: List[str]
    success_criteria: List[str]
    estimated_tokens: int
    estimated_duration_minutes: int
    dependencies: List[str] = field(default_factory=list)


SELF_HOSTING_BENCHMARKS: List[BenchmarkMission] = [
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_0_HELLO_WORLD,
        name="Hello World File",
        description="Create hello.txt with 'Hello, World!'",
        user_request="Create a file hello.txt in the workspace with content 'Hello, World!'",
        expected_artifacts=["hello.txt"],
        expected_agents=["planner", "implementer", "verifier"],
        success_criteria=[
            "Mission reaches VERIFIED",
            "hello.txt exists with exact content",
            "VerificationReport: evidenced",
            "Human approved",
        ],
        estimated_tokens=5000,
        estimated_duration_minutes=2,
    ),
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_1_SINGLE_AGENT,
        name="Implement Verifier Agent",
        description="System implements its own Verifier agent role",
        user_request="""
        Implement the Verifier agent role in src/roles/verifier.py.
        The Verifier must:
        1. Accept VerifierInput (task criteria, artifacts, evidence)
        2. Perform mechanical checks (file_exists, file_hash_matches, file_contains)
        3. Return VerificationResult with verdict, checks_performed, missing_evidence
        4. Use verification_standard.py Verifier class
        5. Follow AgentRole protocol from agent_contract.py
        """,
        expected_artifacts=[
            "src/roles/verifier.py",
            "tests/roles/test_verifier.py",
        ],
        expected_agents=["explorer", "analyst", "planner", "implementer", "verifier", "reviewer"],
        success_criteria=[
            "Mission reaches VERIFIED",
            "Verifier agent passes all contract tests",
            "Mechanical verification works (no LLM for checks)",
            "Integration with orchestrator works",
            "All existing tests still pass",
        ],
        estimated_tokens=50000,
        estimated_duration_minutes=30,
        dependencies=["verification_standard.py", "agent_contract.py"],
    ),
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_1_SINGLE_AGENT,
        name="Implement Planner Agent",
        description="System implements its own Planner agent role",
        user_request="""
        Implement the Planner agent role in src/roles/planner.py.
        The Planner must:
        1. Accept PlannerInput (user_request, exploration_report, analysis)
        2. Generate Plan with task DAG (PlanTask objects)
        3. Each task has acceptance_criteria with file-based checks
        4. Follow AgentRole protocol from agent_contract.py
        5. Use UnifiedLLMClient.structured_chat() with Plan schema
        """,
        expected_artifacts=[
            "src/roles/planner.py",
            "tests/roles/test_planner.py",
        ],
        expected_agents=["explorer", "analyst", "planner", "implementer", "verifier", "reviewer"],
        success_criteria=[
            "Mission reaches VERIFIED",
            "Planner generates valid Plan with DAG",
            "Acceptance criteria are mechanically verifiable",
            "Integration with orchestrator works",
        ],
        estimated_tokens=50000,
        estimated_duration_minutes=30,
        dependencies=["agent_contract.py", "llm_gateway.py"],
    ),
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_1_SINGLE_AGENT,
        name="Implement Implementer Agent",
        description="System implements its own Implementer agent role",
        user_request="""
        Implement the Implementer agent role in src/roles/implementer.py.
        The Implementer must:
        1. Accept ImplementerInput (plan, design_spec, task, sandbox_root)
        2. Generate code/commands to execute in sandbox
        3. Write artifacts to /artifacts via sandbox
        4. Return ImplementationResult with artifact_ids, evidence_refs
        5. Follow AgentRole protocol from agent_contract.py
        6. Handle retry with previous_attempts context
        """,
        expected_artifacts=[
            "src/roles/implementer.py",
            "tests/roles/test_implementer.py",
        ],
        expected_agents=["explorer", "analyst", "planner", "implementer", "verifier", "reviewer"],
        success_criteria=[
            "Mission reaches VERIFIED",
            "Implementer runs in sandbox (not host)",
            "Artifacts written to /artifacts with sha256",
            "Grant validation at admission + execution",
            "Retry logic works with previous attempts",
        ],
        estimated_tokens=80000,
        estimated_duration_minutes=45,
        dependencies=["agent_contract.py", "sandbox.py", "grants.py"],
    ),
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_2_MULTI_AGENT,
        name="Implement Agent Runtime + Orchestrator Integration",
        description="System implements agent runtime and orchestrator wiring",
        user_request="""
        Implement the agent runtime that executes AgentRole agents:
        1. src/runtime/agent_runtime.py - executes agent with token budget, grants
        2. src/orchestrator/unified_orchestrator.py - coordinates mission flow
        3. Integrate state machine, event bus, checkpoint manager
        4. Handle AWAITING_APPROVAL human gate
        5. Handle Arbiter decisions (retry/escalate/terminate)
        """,
        expected_artifacts=[
            "src/runtime/agent_runtime.py",
            "src/orchestrator/unified_orchestrator.py",
            "tests/orchestrator/test_unified_orchestrator.py",
        ],
        expected_agents=["explorer", "analyst", "planner", "implementer", "verifier", "reviewer", "arbiter"],
        success_criteria=[
            "Mission reaches VERIFIED",
            "Full mission flow: intake → plan → execute → verify → approve",
            "State machine transitions validated",
            "Checkpoint/resume works",
            "Event bus emits all FactoryEvents",
        ],
        estimated_tokens=100000,
        estimated_duration_minutes=60,
        dependencies=["state_machine.py", "event_catalog.py", "agent_contract.py"],
    ),
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_3_SUBSYSTEM,
        name="Implement Grants System",
        description="System implements its own grant authorization system",
        user_request="""
        Implement the grants system in src/core/grants.py:
        1. Grant model: typed, HMAC-signed, expiring, revocable
        2. GrantorService: issues grants with HMAC-SHA256
        3. AccessAdmission: validates at admission + execution
        4. RevocationChannel: fail-closed if unavailable
        4. Integration with sandbox (grant_validate tool)
        5. Permission classes: read, write, execute, admin
        6. Domains: codebase, infrastructure, data, security, testing, deployment
        """,
        expected_artifacts=[
            "src/core/grants.py",
            "tests/core/test_grants.py",
        ],
        expected_agents=["explorer", "analyst", "planner", "implementer", "verifier", "reviewer", "designer", "arbiter"],
        success_criteria=[
            "Mission reaches VERIFIED",
            "Grants issued with valid HMAC signatures",
            "Validation at admission AND execution",
            "Revocation works (fail-closed)",
            "Sandbox grant_validate tool integrated",
            "All existing grant tests pass",
        ],
        estimated_tokens=80000,
        estimated_duration_minutes=45,
        dependencies=["domain_model.py", "sandbox.py"],
    ),
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_3_SUBSYSTEM,
        name="Implement Sandbox Abstraction",
        description="System implements cross-platform sandbox interface",
        user_request="""
        Implement the sandbox abstraction in src/unified/sandbox.py:
        1. ExecutionSandbox protocol (execute, write_artifact, read_artifact)
        2. LocalSubstrateAdapter (Linux: namespaces, seccomp, pivot_root)
        3. WindowsExecutorAdapter (Job Objects: memory/CPU/process limits)
        4. SandboxManager: single execute per sandbox_id, teardown always
        5. NetworkMode.NONE enforcement
        6. Image allowlist with pinned digests
        7. Resource limits: memory, CPU, wall time, processes
        """,
        expected_artifacts=[
            "src/unified/sandbox.py",
            "src/core/substrate.py",
            "src/core/windows_executor.py",
            "tests/sandbox/test_sandbox.py",
        ],
        expected_agents=["explorer", "analyst", "planner", "implementer", "verifier", "reviewer", "designer", "arbiter"],
        success_criteria=[
            "Mission reaches VERIFIED",
            "WindowsExecutorAdapter works on Windows",
            "LocalSubstrateAdapter works on Linux (CI)",
            "No host execution fallback (fail-closed)",
            "Resource limits enforced",
            "Artifact custody maintained",
        ],
        estimated_tokens=100000,
        estimated_duration_minutes=60,
        dependencies=["domain_model.py", "grants.py"],
    ),
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_4_SELF_BUILD,
        name="Full Self-Build: Implement Unified System from Scratch",
        description="System builds the complete unified system from architecture.md",
        user_request="""
        Implement the complete Unified Engineering Agents System as defined in:
        - src/unified/architecture.md
        - src/unified/execution_tracker.json (all workstreams)
        - All 15 E1 artifacts in src/unified/

        This mission will:
        1. Explorer: Analyze architecture.md and execution_tracker.json
        2. Analyst: Identify all components, dependencies, interfaces
        3. Planner: Generate complete task graph for all workstreams
        4. Designer: Create interface specifications for all protocols
        5. Reviewer: Review plan and design (max 3 cycles)
        6. Implementer: Implement each component in order
        7. Verifier: Verify each component against acceptance criteria
        8. Arbiter: Resolve conflicts during implementation

        The system builds itself completely from the blueprint.
        """,
        expected_artifacts=[
            "src/unified/*.py (all 15 artifacts)",
            "src/factory/*.py (unified orchestrator, CLI, API)",
            "src/core/*.py (grants, sandbox, substrate, checkpoints)",
            "src/roles/*.py (all 8 agent roles)",
            "src/runtime/*.py (agent runtime)",
            "tests/**/*.py (all contract and integration tests)",
        ],
        expected_agents=["explorer", "analyst", "planner", "designer", "reviewer", "implementer", "verifier", "arbiter"],
        success_criteria=[
            "All 15 E1 artifacts exist and are valid",
            "All existing tests pass (112 factory + 112 EAS v2)",
            "No mock in production paths",
            "Vertical slice VS-001 passes",
            "Self-hosting benchmarks Level 0-3 pass",
            "System can run a mission to build a new feature",
        ],
        estimated_tokens=500000,
        estimated_duration_minutes=480,
        dependencies=["All Level 0-3 benchmarks complete"],
    ),
    BenchmarkMission(
        level=BenchmarkLevel.LEVEL_5_SELF_IMPROVE,
        name="Self-Improvement: Optimize Token Usage",
        description="System analyzes its own token usage and optimizes",
        user_request="""
        Analyze the system's token usage patterns and implement optimizations:
        1. Explorer: Collect token usage data from TokenUsageEvent events
        2. Analyst: Identify high-token operations (planner, implementer)
        3. Planner: Design optimization strategies (caching, smaller contexts, better prompts)
        4. Implementer: Implement optimizations
        5. Verifier: Verify token reduction with benchmarks
        6. Reviewer: Review changes
        7. Run benchmark suite before/after, report savings

        Target: 30% token reduction for equivalent missions.
        """,
        expected_artifacts=[
            "src/optimization/token_optimizer.py",
            "benchmarks/token_benchmark.py",
            "reports/token_optimization_report.md",
        ],
        expected_agents=["explorer", "analyst", "planner", "implementer", "verifier", "reviewer"],
        success_criteria=[
            "Mission reaches VERIFIED",
            "Token reduction >= 30% on benchmark missions",
            "No regression in verification quality",
            "All existing tests pass",
        ],
        estimated_tokens=100000,
        estimated_duration_minutes=60,
        dependencies=["Level 4 complete", "TokenUsageEvent implemented"],
    ),
]


# ============================================================
# BENCHMARK RUNNER
# ============================================================

@dataclass
class BenchmarkResult:
    """Result of running a benchmark mission."""
    level: BenchmarkLevel
    name: str
    mission_id: str
    success: bool
    final_state: str
    duration_seconds: float
    tokens_used: int
    artifacts_produced: List[str]
    verification_report: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SelfHostingBenchmarkRunner:
    """Runs self-hosting benchmarks and collects results."""

    def __init__(self, orchestrator: Any):  # UnifiedOrchestrator
        self.orchestrator = orchestrator
        self.results: List[BenchmarkResult] = []

    async def run_benchmark(self, benchmark: BenchmarkMission) -> BenchmarkResult:
        """Run a single benchmark mission."""
        import time
        start = time.time()

        # Create mission
        mission = self.orchestrator.create_mission(benchmark.user_request)

        # Execute
        try:
            result = await self.orchestrator.execute_mission(mission.mission_id)
            duration = time.time() - start

            benchmark_result = BenchmarkResult(
                level=benchmark.level,
                name=benchmark.name,
                mission_id=mission.mission_id,
                success=result.final_state == "VERIFIED",
                final_state=result.final_state,
                duration_seconds=duration,
                tokens_used=result.total_tokens,
                artifacts_produced=result.artifact_ids,
                verification_report=result.verification_report,
            )
        except Exception as e:
            duration = time.time() - start
            benchmark_result = BenchmarkResult(
                level=benchmark.level,
                name=benchmark.name,
                mission_id=mission.mission_id,
                success=False,
                final_state="FAILED",
                duration_seconds=duration,
                tokens_used=0,
                artifacts_produced=[],
                error=str(e),
            )

        self.results.append(benchmark_result)
        return benchmark_result

    async def run_level(self, level: BenchmarkLevel) -> List[BenchmarkResult]:
        """Run all benchmarks for a level."""
        benchmarks = [b for b in SELF_HOSTING_BENCHMARKS if b.level == level]
        results = []
        for bm in benchmarks:
            result = await self.run_benchmark(bm)
            results.append(result)
            if not result.success:
                # Stop on first failure in level
                break
        return results

    async def run_all(self) -> Dict[BenchmarkLevel, List[BenchmarkResult]]:
        """Run all benchmark levels in order."""
        all_results = {}
        for level in BenchmarkLevel:
            results = await self.run_level(level)
            all_results[level] = results
            # Stop if level fails
            if not all(r.success for r in results):
                break
        return all_results

    def generate_report(self) -> str:
        """Generate benchmark report."""
        lines = ["SELF-HOSTING BENCHMARK REPORT", "=" * 50, ""]
        for result in self.results:
            status = "✓ PASS" if result.success else "✗ FAIL"
            lines.append(f"{status} {result.level.value}: {result.name}")
            lines.append(f"  Mission: {result.mission_id}")
            lines.append(f"  State: {result.final_state}")
            lines.append(f"  Duration: {result.duration_seconds:.1f}s")
            lines.append(f"  Tokens: {result.tokens_used}")
            lines.append(f"  Artifacts: {len(result.artifacts_produced)}")
            if result.error:
                lines.append(f"  Error: {result.error}")
            lines.append("")
        return "\n".join(lines)


# ============================================================
# CONTINUOUS BENCHMARKING
# ============================================================

CONTINUOUS_BENCHMARK_CONFIG = {
    "schedule": "daily",
    "levels": [
        BenchmarkLevel.LEVEL_0_HELLO_WORLD,
        BenchmarkLevel.LEVEL_1_SINGLE_AGENT,
    ],
    "alert_on_failure": True,
    "alert_on_regression": {
        "token_increase_percent": 20,
        "duration_increase_percent": 50,
    },
    "history_retention_days": 30,
    "report_output": "benchmarks/reports/self_hosting_{date}.json",
}


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "BENCHMARK_PHILOSOPHY",
    "BenchmarkLevel",
    "BenchmarkMission",
    "SELF_HOSTING_BENCHMARKS",
    "BenchmarkResult",
    "SelfHostingBenchmarkRunner",
    "CONTINUOUS_BENCHMARK_CONFIG",
]