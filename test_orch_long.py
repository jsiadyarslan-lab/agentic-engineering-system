import asyncio, sys, os, time
sys.path.insert(0, '.')
from src.factory.orchestrator import AgentFactoryOrchestrator

async def main():
    if os.path.exists("greeting.txt"): os.remove("greeting.txt")
    orch = await AgentFactoryOrchestrator.create_for_production()
    orch.human_gate.test_mode = True

    t0 = time.time()
    mission = await orch.start_mission(
        user_request="Create greeting.txt containing: hello from factory"
    )
    last = None
    for i in range(1800):  # 180 ثانية
        await asyncio.sleep(0.1)
        if mission.state.value != last:
            print(f"[{time.time()-t0:.1f}s] STATE: {mission.state.value}")
            last = mission.state.value
        if mission.state.value in ('COMPLETED','ABORTED','ESCALATED'):
            break
    print(f"[{time.time()-t0:.1f}s] FINAL: {mission.state.value}")
    print("LAST_ERROR:", getattr(mission, 'last_error', None))
    print("FILE_EXISTS:", os.path.exists("greeting.txt"))
    if os.path.exists("greeting.txt"):
        print("FILE_CONTENT:", repr(open("greeting.txt").read()))

asyncio.run(main())
