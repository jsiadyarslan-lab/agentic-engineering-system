"""فحص يدوي سريع: دورة حياة وظيفة كاملة عبر API مع محرك مخطط.

يُشغَّل خارج pytest: python scripts/order012_job_smoke.py
"""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "api"))

from fastapi.testclient import TestClient  # noqa: E402

from api import projects, routes  # noqa: E402
from persistence.database import (  # noqa: E402
    build_engine, init_db, make_session_factory,
)
from test_projects_api import FakeRouter, ScriptedPlanner  # noqa: E402


def _run_flow(client):
    # إنشاء ← خطة ← اعتماد
    out = client.post("/api/projects", json={
        "name": "وظيفة 012", "objective": "هدف فحص الوظيفة",
    })
    pid = out.json()["id"]
    client.post(f"/api/projects/{pid}/plan/generate")
    client.post(f"/api/projects/{pid}/plan/approve",
                json={"approved": True})
    # تشغيل عبر SSE
    with client.stream(
        "POST", f"/api/projects/{pid}/run/stream"
    ) as response:
        kinds = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                kinds.append(json.loads(line[6:])["kind"])
    print("JOB kinds:", [k for k in kinds if k.startswith("JOB")]
          or "(لا أحداث وظيفة!)", "| run.done:", "run.done" in kinds)
    # الوظيفة الآن
    job = client.get(f"/api/projects/{pid}/job").json()
    print("job:", job["status"], "| waiting:", job["waiting_kind"],
          "| ticks:", job["tick_count"],
          "| checkpoints:", job["checkpoints"],
          "| heartbeat_s:", round(job["heartbeat_age_s"] or -1))
    # تفاصيل المشروع تحمل الوظيفة
    detail = client.get(f"/api/projects/{pid}").json()
    print("detail.job:", bool(detail.get("job")))
    # سلسلة القبول
    chain = client.get(f"/api/projects/{pid}/chain").json()
    for st in chain["stages"]:
        print("  chain:", st["stage"], "→", st["status"])
    # الخط الزمني
    tl = client.get(f"/api/projects/{pid}/timeline").json()
    print("timeline items:", len(tl["items"]))
    # تحقق المالك ← الوظيفة COMPLETED
    verified = client.post(f"/api/projects/{pid}/verify").json()
    print("verify:", verified["status"])
    job2 = client.get(f"/api/projects/{pid}/job").json()
    print("job after verify:", job2["status"])
    assert job2["status"] == "COMPLETED", job2["status"]
    # قائمة الوظائف + الأدوار + القدرات
    jobs = client.get("/api/harness/jobs").json()["jobs"]
    print("jobs list:", len(jobs))
    roles = client.get("/api/harness/roles").json()["roles"]
    print("roles:", [(r["role"], r["live_selection"]["ready"])
                     for r in roles])
    caps = client.get("/api/harness/capabilities").json()["capabilities"]
    print("caps:", [(c["capability_id"], c["blocked_kind"])
                    for c in caps[:6]])
    print("OK — دورة الوظيفة كاملة تعمل")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.chdir(tmp)
        engine = build_engine(Path(tmp) / "jobs-smoke.db")
        init_db(engine)
        sessions = make_session_factory(engine)
        routes._sessions = sessions

        # منفذ مزيف ناجح — نفس عقد run_task (كما في اختبارات API)
        import tasks as tasks_mod

        def fake_run_task(goal, *, router, role_config=None, workspace=None,
                          on_event=None, cycle_id=None,
                          stop_controller=None, **_kw):
            import hashlib

            from tasks import TaskResult

            root = Path(workspace)
            root.mkdir(parents=True, exist_ok=True)
            output = root / "deliverable.md"
            output.write_text(f"# مخرج\n\n{goal}\n", encoding="utf-8")
            evidence_path = root / "evidence.json"
            evidence_path.write_text("{}", encoding="utf-8")
            return TaskResult(
                verdict="PASS", reason="تم", goal=goal,
                cycle_id=cycle_id or "", final_state="EVIDENCED",
                workspace=str(root), files=["deliverable.md"],
                tool_calls=[], evidence_path=str(evidence_path),
                evidence_sha256=hashlib.sha256(
                    evidence_path.read_bytes()).hexdigest(),
                duration_ms=5, state_history=["EVIDENCED"],
            )

        tasks_mod.run_task = fake_run_task

        def factory(on_event=None, **_kwargs):
            from workflow.engine import ProjectEngine

            return ProjectEngine(
                sessions,
                router_factory=FakeRouter,
                planner_factory=ScriptedPlanner,
                on_event=on_event,
            )

        projects._test_engine_factory = factory
        try:
            _run_flow(TestClient(routes.app))
        finally:
            projects._test_engine_factory = None


if __name__ == "__main__":
    main()
