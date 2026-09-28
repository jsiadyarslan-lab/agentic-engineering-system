import asyncio, sys, os
sys.path.insert(0, '.')
from src.factory.orchestrator import AgentFactoryOrchestrator
from src.factory.context.memory import SharedContextManager

async def main():
    if os.path.exists("hello.py"): os.remove("hello.py")
    orch = await AgentFactoryOrchestrator.create_for_test(test_mode=True)
    print(f"human_gate.test_mode = {orch.human_gate.test_mode}")
    mission = await orch.start_mission(
        user_request="Create a file hello.py containing: print('hello world'). Then run it and verify the output."
    )
    for i in range(500):
        await asyncio.sleep(0.1)
        if mission.state.value in ('COMPLETED','ABORTED','ESCALATED'):
            print(f"  Iteration {i}: state={mission.state.value}")
            break
        if i % 10 == 0:
            print(f"  Iteration {i}: state={mission.state.value}")
    print("STATE:", mission.state.value)
    print("VERIFICATION:", mission.verification.passed if mission.verification else None)
    print("EVIDENCE_COUNT:", len(mission.evidence_hashes))
    print("HELLO_EXISTS:", os.path.exists("hello.py"))
    if os.path.exists("hello.py"):
        print("HELLO_CONTENT:", open("hello.py").read().strip())
    if mission.last_error:
        print("LAST_ERROR:", mission.last_error)
    print("human_decision:", mission.human_decision)

asyncio.run(main())