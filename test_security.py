import asyncio
import sys
sys.path.insert(0, 'src')
from tests.e43.test_adversarial import E43TestHarness, MissionType, MissionSize
import tempfile
from pathlib import Path

async def test():
    artifacts_dir = str(Path(tempfile.gettempdir()) / 'e43_test')
    harness = E43TestHarness(artifacts_dir)
    await harness.setup_engine()
    specs = harness.build_mission_specs(MissionType.STANDARD, MissionSize.SMALL)
    mission, run, _ = harness.mc.define_mission('Test Security', specs)
    result = await harness.mc.execute_run(run.run_id)
    for tid, task in harness.engine.tasks.items():
        if task.mission_id == mission.mission_id:
            print(f'{task.name}: {task.state}')
    print(f'Result success: {result["success"]}')

asyncio.run(test())