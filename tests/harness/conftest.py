"""بنية اختبارات الـHarness (012) — قاعدة معزولة + محرك حقيقي بحدود منظمة.

نفس فلسفة tests/workflow: كل شيء حقيقي (المحرك، القاعدة، البوابات،
الوظيفة، المنسق الحتمي، الإسقاطات) إلا الحدود الخارجية: موجّه
منظم، مخطط منظم، منفذ خطوة موجَّه يكتب ملفات وsha256 حقيقية،
ومسبار sandbox من سجل البيئات (وصفة 011) — حتمية عبر المنصات.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "workflow"))

#: خطط workflow المنظمة — من وحدة plans لا من conftest (تفادي
#: تضارب اسم conftest بين حزمتي الاختبار على sys.path).
from plans import SCRIPTED_PLAN  # noqa: E402


class _FakeHTTPSResponse:
    """استجابة https محقونة — عبر آلية الحقن المعلنة للاختبارات حصرًا."""

    status = 200
    headers = {"Content-Type": "text/plain"}

    def read(self, *_args, **_kwargs):
        return b"aes-harness-test-ok"

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _fake_https_getter(url, timeout=None):  # noqa: ARG001
    return _FakeHTTPSResponse()


class ScriptedRouter:
    """موجّه اختباري — حدود صادقة فقط (من له نقل حي)."""

    def __init__(self, providers=("nvidia",)):
        self._providers = set(providers)

    def has_live_provider(self, provider_id):
        return str(provider_id) in self._providers

    def live_providers(self):
        return sorted(self._providers)


class SteerableExecutor:
    """منفذ خطوة موجَّه — فشل قابل للجدولة ثم نجاح بأدلة حقيقية.

    fail_first: أول N تنفيذات تفشل (لمحاكاة فشل عابر ثم نجاح).
    fail_prefixes: أهداف تبدأ بها تفشل دائمًا (لمحاكاة الفشل
    المستنفد ← مراجعة الخطة). الحالة قابلة للتغيير بين التشغيلات
    (المالك «أصلح» البيئة فنجحت خطة v2).
    """

    def __init__(self, fail_first=0, fail_prefixes=()):
        self.fail_first = fail_first
        self.fail_prefixes = tuple(fail_prefixes)
        self.runs: list[str] = []

    def run_task(self, goal, *, router, role_config=None, workspace=None,
                 on_event=None, cycle_id=None, stop_controller=None,
                 resume_from=None, **_kw):
        from tasks import TaskResult

        self.runs.append(goal)
        index = len(self.runs)
        if index <= self.fail_first or goal.startswith(self.fail_prefixes):
            return TaskResult(
                verdict="HARD STOP", reason="فشل منظم موجَّه", goal=goal,
                cycle_id=cycle_id or "", final_state="FAILED",
                workspace=str(workspace or "."), files=[], tool_calls=[],
                evidence_path="", evidence_sha256="", duration_ms=3,
                state_history=["FAILED"],
            )
        root = Path(workspace) if workspace else Path(".")
        root.mkdir(parents=True, exist_ok=True)
        output = root / "deliverable.md"
        output.write_text(f"# مخرج {index}\n\n{goal}\n", encoding="utf-8")
        evidence_path = root / "evidence.json"
        evidence = {"goal": goal, "files": {
            output.name: {
                "sha256": hashlib.sha256(
                    output.read_bytes()).hexdigest(),
                "bytes": output.stat().st_size,
            }
        }}
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False), encoding="utf-8"
        )
        return TaskResult(
            verdict="PASS", reason="اكتملت بأدلة", goal=goal,
            cycle_id=cycle_id or "", final_state="EVIDENCED",
            workspace=str(root), files=[output.name], tool_calls=[],
            evidence_path=str(evidence_path),
            evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()).hexdigest(),
            duration_ms=10, state_history=["DRAFT", "EVIDENCED"],
        )


class ScriptedPlanner:
    """مخطط منظم — يعيد الخطة المعطاة (v جديدة عند كل استدعاء)."""

    def __init__(self, plan=None):
        self.plan = plan or SCRIPTED_PLAN
        self.calls = 0

    def generate(self, objective, *, previous_failure=None, feedback=""):
        self.calls += 1
        return json.loads(json.dumps(self.plan, ensure_ascii=False))


@pytest.fixture()
def harness_env(tmp_path, monkeypatch):
    """بيئة وظائف معزولة: قاعدة + محرك حقيقي + منفذ موجَّه + مسبار وصفة."""
    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )
    from providers_registry import registry

    monkeypatch.chdir(tmp_path)
    engine = build_engine(tmp_path / "harness-test.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)

    executor = SteerableExecutor()
    planner = ScriptedPlanner()

    import tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "run_task", executor.run_task)

    def build_engine(on_event=None, providers=("nvidia",)):
        from workflow.engine import ProjectEngine

        router_holder = {"router": ScriptedRouter(providers)}

        return ProjectEngine(
            sessions,
            router_factory=lambda: router_holder["router"],
            planner_factory=lambda: planner,
            on_event=on_event,
            # (AES-EXP-04 §6) مسبار network_https محقون عبر العقد
            # المعلن (registry.run_probe «الحقن للاختبارات حصرًا») —
            # هدف سلسلة الـharness دورة الوظيفة لا وصول المضيف؛ بلا
            # الحقن كان المسبار الحقيقي على مضيف بلا خروج يحجب كل
            # دورة (حاجب شبكة إضافي فوق حاجب sandbox المقصود) فيقلب
            # التصنيف WAITING_WORKER إلى WAITING_CAPABILITY.
            probe_injections={"https_fn": _fake_https_getter},
        )

    def build_manager(engine=None, on_event=None):
        from harness.jobs import JobManager
        from harness.seams import HarnessSeams

        return JobManager(
            HarnessSeams(sessions), engine=engine, on_event=on_event
        )

    yield {
        "sessions": sessions,
        "executor": executor,
        "planner": planner,
        "build_engine": build_engine,
        "build_manager": build_manager,
        "tmp_path": tmp_path,
    }


@pytest.fixture()
def sandbox_seam(monkeypatch, harness_env):
    """مسبار sandbox من سجل البيئات (وصفة 011) + توفير حقيقي للصف.

    الحقيقة عند 011: حكم preflight للبيئة يقرأ سجل البيئات عبر
    select_environment (المسبار والمنفذ من مصدر واحد) — لذا
    «التوفير» هنا = ضبط صف البيئة المحلية جاهزًا معزولًا، تمامًا
    كما يفعل المالك من بيئات التنفيذ ← تحقق. لا إقلاع ركيزة فعلي
    (له اختباراته المستقلة) — حتمية عبر المنصات.
    """
    from sqlalchemy import select as sa_select

    from execution import service as execution_service
    from execution.models import ExecutionEnvironment

    sessions = harness_env["sessions"]

    def _set(status, sandboxed):
        execution_service.ensure_local_registered(sessions)
        with sessions() as s:
            row = s.scalars(sa_select(ExecutionEnvironment).where(
                ExecutionEnvironment.name.in_(
                    ("local-linux", "local-windows"))
            )).first()
            row.status = status
            row.sandboxed = sandboxed
            s.commit()

    def fake_sandbox_probe(sessions_, **_kwargs):
        environments = execution_service.list_environments(sessions_)
        ready = [
            e for e in environments
            if e["status"] == "READY" and e.get("sandboxed")
        ]
        return {
            "status": "READY" if ready else "NOT_READY",
            "reason": "بيئة معزولة جاهزة (وصفة)" if ready
            else "لا بيئة تنفيذ معزولة جاهزة (وصفة)",
            "latency_ms": 1, "ttl_seconds": 300,
            "failure_class": "" if ready else "SANDBOX_FAILURE",
            "failure_stage": "" if ready else "STARTUP",
            "details": {"test_seam": True},
        }

    monkeypatch.setattr(
        execution_service, "sandbox_probe_result", fake_sandbox_probe
    )

    # الافتراضي: لا بيئة جاهزة (كمضيف بلا ركيزة) — حتمية عبر المنصات
    _set("NOT_READY", 0)

    return {
        "provision": lambda: _set("READY", 1),
        "deprovision": lambda: _set("NOT_READY", 0),
    }
