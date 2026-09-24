import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from fastapi.testclient import TestClient
from api import routes
from api import projects as projects_mod
from workflow import service
from persistence.database import build_engine, init_db, make_session_factory
from providers_registry import registry
import tempfile, hashlib
from pathlib import Path

tmp = tempfile.mkdtemp()
engine = build_engine(tmp + '/test.db')
init_db(engine)
sessions = make_session_factory(engine)
projects_mod._sessions = lambda: sessions
registry.ensure_seeded(sessions)

runs = []
def fake_run_task(goal, *, router, role_config=None, workspace=None,
                  on_event=None, cycle_id=None, stop_controller=None,
                  resume_from=None, **_kw):
    from tasks import TaskResult
    from pathlib import Path
    runs.append(goal)
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    output = root / 'deliverable.md'
    output.write_text(f'# مخرج\n\n{goal}\n', encoding='utf-8')
    evidence_path = root / 'evidence.json'
    evidence_path.write_text('{}', encoding='utf-8')
    return TaskResult(
        verdict='PASS', reason='تم', goal=goal, cycle_id=cycle_id or '',
        final_state='EVIDENCED', workspace=str(root),
        files=['deliverable.md'], tool_calls=[],
        evidence_path=str(evidence_path),
        evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        duration_ms=500, state_history=['EVIDENCED'],
    )

import tasks as tasks_mod
tasks_mod.run_task = fake_run_task

class FakeRouter:
    def has_live_provider(self, p): return True
    def live_providers(self): return ['nvidia']

def factory(on_event=None, **_kwargs):
    from workflow.engine import ProjectEngine
    return ProjectEngine(sessions, router_factory=FakeRouter, on_event=on_event)

projects_mod._test_engine_factory = factory

client = TestClient(routes.app)
created = client.post('/api/projects', json={'name': 'test', 'objective': 'test', 'execution_policy': 'COMPATIBLE_LOCAL'})
print('create:', created.status_code, created.json())
pid = created.json()['id']

from tests.api.planning_wait import generate_plan_and_wait
plan, _ = generate_plan_and_wait(client, pid)
print('plan:', plan.status_code)

approved = client.post(f'/api/projects/{pid}/plan/approve', json={'approved': True})
print('approve:', approved.status_code, approved.json().get('launch'))

# poll state
for i in range(50):
    state = client.get(f'/api/projects/{pid}/state').json()
    rt = state.get('environment', {}).get('runtime_state', {})
    print(f'poll {i}: state={rt.get("state")}, status={state.get("status")}, coherent={rt.get("coherent")}')
    if rt.get('state') == 'RUNNING':
        print('RUNNING reached')
        break
    time.sleep(0.1)
else:
    print('TIMEOUT')
listing = client.get('/api/projects').json()
print('recovery:', listing.get('recovery'))