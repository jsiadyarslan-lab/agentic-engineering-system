"""اختبارات بنية تحتية مشتركة لاختبارات workflow (الأمر 007).

فلسفة العزل نفسها المتبعة في tests/api/conftest.py: كل شيء حقيقي إلا
الحدود الخارجية — المخطط منظم (scripted)، ومنفذ الخطوة (run_task)
منظم يكتب ملفات حقيقية ويحسب sha256 حقيقية، والموجّه وهمي بحدود
صادقة (has_live_provider). المحرك والقاعدة والخدمة والمدقق كلها
حقيقية بالكامل — لهذا تثبت هذه الاختبارات الحالة الدائمة فعليًا.
"""

from __future__ import annotations

import hashlib
import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


class ScriptedRouter:
    """موجّه اختباري — حدود صادقة فقط (من له نقل حي)."""

    def __init__(self, providers=("nvidia",)):
        self._providers = set(providers)

    def has_live_provider(self, provider_id):
        return str(provider_id) in self._providers

    def live_providers(self):
        return sorted(self._providers)


from plans import SCRIPTED_PLAN, TWO_PHASE_PLAN  # noqa: F401


class ScriptedPlanner:
    """مخطط منظم — يعيد الخطة المعطاة (أو يفشل عند الطلب)."""

    def __init__(self, plan=None, fail_times=0):
        self.plan = plan or SCRIPTED_PLAN
        self.fail_times = fail_times
        self.calls = 0

    def generate(self, objective, *, previous_failure=None, feedback=""):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("فشل النموذج المنظم")
        return json.loads(json.dumps(self.plan, ensure_ascii=False))


class ScriptedExecutor:
    """منفذ خطوة منظم — يكتب ملفًا حقيقيًا ويحسب أدلة حقيقية.

    fail_prefixes: أهداف تبدأ بها تُفشل (لمحاكاة فشل التنفيذ).
    stop_prefixes: أهداف تبدأ بها تُوقف (لمحاكاة إيقاف المالك).
    audit_fail_steps: أعداد تنفيذات تكتب ملفًا خاطئًا (يفشل التدقيق
    الميكانيكي §11).
    """

    def __init__(self, fail_prefixes=(), stop_prefixes=(), audit_fail_execs=()):
        self.fail_prefixes = tuple(fail_prefixes)
        self.stop_prefixes = tuple(stop_prefixes)
        self.audit_fail_execs = set(audit_fail_execs)
        self.runs: list[dict] = []

    def run_task(self, goal, *, router, role_config=None, workspace=None,
                 on_event=None, cycle_id=None, stop_controller=None,
                 resume_from=None, **_kw):
        from tasks import TaskResult

        self.runs.append({"goal": goal, "workspace": str(workspace)})
        index = len(self.runs)
        if goal.startswith(self.stop_prefixes):
            return TaskResult(verdict="STOPPED", reason="إيقاف منظم",
                              goal=goal)
        if goal.startswith(self.fail_prefixes):
            return TaskResult(verdict="HARD STOP", reason="فشل منظم",
                              goal=goal)
        root = Path(workspace) if workspace else Path(".")
        root.mkdir(parents=True, exist_ok=True)
        # تنفيذ يفشل التدقيق: يكتب ملفًا غير المذكور في المعايير
        if index in self.audit_fail_execs:
            output = root / "wrong-file.txt"
        else:
            output = root / "deliverable.md"
        output.write_text(f"# مخرج {index}\n\n{goal}\n", encoding="utf-8")
        evidence_path = root / "evidence.json"
        evidence = {"goal": goal, "files": {
            output.name: {"sha256": hashlib.sha256(
                output.read_bytes()).hexdigest(), "bytes": output.stat().st_size}
        }}
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False),
                                 encoding="utf-8")
        return TaskResult(
            verdict="PASS", reason="اكتملت بأدلة", goal=goal,
            cycle_id=cycle_id or "", final_state="EVIDENCED",
            workspace=str(root), files=[output.name], tool_calls=[],
            evidence_path=str(evidence_path),
            evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()).hexdigest(),
            duration_ms=10, state_history=["DRAFT", "EVIDENCED"],
        )


@pytest.fixture()
def wf_env(tmp_path, monkeypatch):
    """بيئة محرك معزولة: قاعدة مؤقتة + بذر مزودين + منفذ منظم."""
    from persistence.database import build_engine, init_db, make_session_factory
    from providers_registry import registry

    monkeypatch.chdir(tmp_path)
    engine = build_engine(tmp_path / "wf-test.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)

    executor = ScriptedExecutor()
    planner = ScriptedPlanner()

    def fake_run_task(*args, **kwargs):
        return executor.run_task(*args, **kwargs)

    import tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "run_task", fake_run_task)

    def build_engine_instance(on_event=None, plan=None, providers=("nvidia",)):
        from workflow.engine import ProjectEngine

        router_holder = {"router": ScriptedRouter(providers)}

        def router_factory():
            return router_holder["router"]

        nonlocal planner
        selected_planner = ScriptedPlanner(plan=plan) if plan else planner

        return ProjectEngine(
            sessions,
            router_factory=router_factory,
            planner_factory=lambda: selected_planner,
            on_event=on_event,
        )

    yield {
        "sessions": sessions,
        "executor": executor,
        "planner": planner,
        "build_engine": build_engine_instance,
        "tmp_path": tmp_path,
    }
