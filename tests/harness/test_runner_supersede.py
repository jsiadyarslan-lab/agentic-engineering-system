"""اختبار تسليم المنفّذ الوحيد بين البيئات (AES-EXP-04 §6).

العقد المطلوب: حلقة سير العمل خيط وحيد لكل العملية (single-flight).
حين تستلم بيئة أخرى (قاعدة أخرى — حال الاختبارات المعزولة) المنفّذ،
تسلّم الحلقةُ اليتيمة الخيطَ عند نقطة أمان بين النبضات خلال نافذة
قصيرة — لا تحتجزه طوال نافذة توفير المالك (120ث افتراضيًا) — وبلا
أي كتابة كاذبة: حالة الوظيفة السابقة باقية كما كتبتها آخر نبضة
صادقة، والاستئناف قرار صريح. الإنتاج بقاعدة واحدة لا يمر بهذا
المسار أبدًا (المسار نفسه هو ما جعل اختبارات API المترابطة على
المنفّذ المشترك تتضور سابقًا).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "workflow"))

from plans import SCRIPTED_PLAN  # noqa: E402


class _Router:
    """موجّه اختباري — حد صادق فقط: مزود حي معلن."""

    def __init__(self, providers=("nvidia",)):
        self._providers = set(providers)

    def has_live_provider(self, provider_id):
        return str(provider_id) in self._providers

    def live_providers(self):
        return sorted(self._providers)


class _Planner:
    """مخطط منظم — الخطة المعطاة كما هي (نسخة جديدة كل استدعاء)."""

    def __init__(self, plan=None):
        self.plan = plan or SCRIPTED_PLAN
        self.calls = 0

    def generate(self, objective, *, previous_failure=None, feedback=""):
        self.calls += 1
        return json.loads(json.dumps(self.plan, ensure_ascii=False))


class _FakeHTTPSResponse:
    """استجابة https محقونة — عبر آلية الحقن المعلنة للاختبارات حصرًا."""

    status = 200
    headers = {"Content-Type": "text/plain"}

    def read(self, *_args, **_kwargs):
        return b"aes-supersede-test-ok"

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _fake_https_getter(url, timeout=None):  # noqa: ARG001
    return _FakeHTTPSResponse()


def _wait_until(predicate, timeout_s: float, what: str) -> bool:
    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:  # noqa: BLE001 — إعادة محاولة حتى المهلة
            pass
        time.sleep(0.1)
    return False


def test_superseded_loop_yields_single_executor(
        tmp_path, harness_env, sandbox_seam):  # noqa: ARG001
    """(§6) بيئة ب تستلم المنفّذ — حلقة أ المحجوبة تسلّمه عند نبضتها
    التالية (نافذة قصيرة ≪ 120ث)، حالة أ باقية صادقة (WAITING_WORKER
    + ملاحظة تسليم)، ودورة ب تكتمل حتى مرشح الاكتمال."""
    from sqlalchemy import select as sa_select

    from execution import service as execution_service
    from execution.models import ExecutionEnvironment
    from harness.jobs import JobManager
    from harness.seams import HarnessSeams
    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )
    from providers_registry import registry
    from workflow import runner as wf_runner
    from workflow.engine import ProjectEngine

    sessions_a = harness_env["sessions"]
    # sandbox_seam: الافتراض بيئة أ غير جاهزة (لا بيئة معزولة) — حجب صادق

    # ---------------------------------------------------------------- #
    # بيئة أ: مشروع معتمد ← إطلاق على المنفّذ الوحيد ← حجب ← انتظار عامل
    # ---------------------------------------------------------------- #
    # مسبار https محقون لأيضًا: حاجبها الوحيد sandbox (وصفة سجل البيئات
    # — المهيأ الوحيد للاختبار)؛ بدون الحقن كانت كل نبضة تنتظر مهلة
    # المسبار الشبكي الحقيقي (~13ث على مضيف بلا خروج) فتضيع حدة إثبات
    # «التسليم عند النبضة التالية» خلف زمن المسبار لا زمن العقد.
    planner_a = _Planner()

    def build_engine_a(on_event=None):
        return ProjectEngine(
            sessions_a,
            router_factory=lambda: _Router(),
            planner_factory=lambda: planner_a,
            on_event=on_event,
            probe_injections={"https_fn": _fake_https_getter},
        )

    engine_a = build_engine_a()
    project_a = engine_a.create_project(
        "محجوب ينتظر التوفير", "هدف يحجب على بيئة غير جاهزة"
    )
    engine_a.generate_plan(project_a["id"])
    engine_a.approve_plan(project_a["id"], approved=True)

    launched_a = wf_runner.launch(
        project_a["id"],
        engine_factory=build_engine_a,
        sessions=sessions_a, reason="اختبار الاستلام — بيئة أ",
    )
    assert launched_a["launched"] is True, launched_a

    ledger_a = JobManager(HarnessSeams(sessions_a))

    def _job_a():
        return ledger_a.job_for_project(project_a["id"]) or {}

    # الحجب الصادق وصل: الوظيفة في انتظار محجوب بالفحص المسبق وحلقتها
    # حية محتجزة للمنفّذ. نوع الانتظار يتبع الحاجز المهيمن: بيئة فقط
    # ⟶ WORKER (الحالة المهيمنة هنا مع مسبار شبكة محقون)، بيئة + شبكة
    # ⟶ CAPABILITY — كلاهما انتظار توفير صادق قائم.
    assert _wait_until(
        lambda: _job_a().get("status") in ("WAITING_WORKER",
                                           "WAITING_CAPABILITY"),
        30.0, "وظيفة أ لم تصل انتظارًا محجوبًا",
    ), f"وظيفة أ لم تصل انتظارًا محجوبًا — الحجب الصادق لم يصل: {_job_a()}"
    assert wf_runner.active_run(sessions_a) is not None, (
        "حلقة أ يجب أن تكون حية محتجزة للمنفّذ قبل الاستلام"
    )

    # ---------------------------------------------------------------- #
    # بيئة ب: قاعدة معزولة ثانية + بيئة تنفيذ جاهزة معزولة + مشروع معتمد
    # ---------------------------------------------------------------- #
    engine_b_db = build_engine(tmp_path / "env-b.db")
    init_db(engine_b_db)
    sessions_b = make_session_factory(engine_b_db)
    registry.ensure_seeded(sessions_b)
    execution_service.ensure_local_registered(sessions_b)
    with sessions_b() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.name.in_(("local-linux", "local-windows"))
        )).first()
        row.status = "READY"
        row.sandboxed = 1
        s.commit()

    planner_b = _Planner()

    def build_engine_b(on_event=None):
        return ProjectEngine(
            sessions_b,
            router_factory=lambda: _Router(),
            planner_factory=lambda: planner_b,
            on_event=on_event,
            # مسبار network_https محقون عبر العقد المعلن (registry.
            # run_probe «الحقن للاختبارات حصرًا») — هدف هذا الاختبار عقد
            # تسليم المنفّذ لا وصول المضيف للإنترنت؛ على مضيف بلا خروج
            # كان المسبار الحقيقي سيحجب بيئة ب أيضًا فيضيع مضمون
            # «اكتمال الدورة بعد الاستلام».
            probe_injections={"https_fn": _fake_https_getter},
        )

    engine_b = build_engine_b()
    project_b = engine_b.create_project(
        "يكمل بعد الاستلام", "هدف يثبت تحرر المنفّذ الوحيد"
    )
    engine_b.generate_plan(project_b["id"])
    engine_b.approve_plan(project_b["id"], approved=True)

    # ---------------------------------------------------------------- #
    # الاستلام: إطلاق ب ← أ تسلّم خلال نافذة قصيرة بلا كتابة كاذبة
    # ---------------------------------------------------------------- #
    t_handoff = time.monotonic()
    launched_b = wf_runner.launch(
        project_b["id"], engine_factory=build_engine_b,
        sessions=sessions_b, reason="اختبار الاستلام — بيئة ب",
    )
    assert launched_b["launched"] is True, launched_b

    yielded = _wait_until(
        lambda: "سلّمت المنفّذ" in (_job_a().get("note") or ""),
        15.0, "حلقة أ لم تسلّم المنفّذ",
    )
    handoff_s = time.monotonic() - t_handoff
    assert yielded, (
        f"حلقة أ لم تسلّم المنفّذ خلال 15ث (استغرق الفحص {handoff_s:.1f}s) "
        "— المنفّذ محتجز طوال نافذة التوفير (120ث)"
    )
    job_a = _job_a()
    assert job_a["status"] in ("WAITING_WORKER", "WAITING_CAPABILITY"), (
        f"حالة أ لم تبق صادقة بعد التسليم: {job_a['status']}"
    )
    assert handoff_s < 15.0, (
        f"التسليم استغرق {handoff_s:.1f}s — أقرب إلى نافذة التوفير "
        "من كونه استلامًا عند النبضة التالية"
    )

    # ---------------------------------------------------------------- #
    # ب: أخذت المنفّذ وأكملت دورتها حتى مرشح الاكتمال (انتظار التحقق)
    # ---------------------------------------------------------------- #
    ledger_b = JobManager(HarnessSeams(sessions_b))

    def _job_b():
        return ledger_b.job_for_project(project_b["id"]) or {}

    completed = _wait_until(
        lambda: _job_b().get("status") == "WAITING_GATE",
        60.0, "وظيفة ب لم تكمل دورتها",
    )
    assert completed, (
        f"وظيفة ب لم تكمل دورتها بعد الاستلام — الحالة: "
        f"{_job_b().get('status')}"
    )
    assert planner_b.calls >= 1, "مخطط ب لم يُستدعَ — دورة ب لم تبدأ فعلًا"
    assert planner_a.calls >= 1, "مخطط أ لم يُستدعَ — تجهيز أ لم يمرّ بمخططه"
