"""اختبارات القبول الإلزامية للأمر 013 — دورة الاعتماد الحية.

المشهد الكامل (§38): الهدف OSINT الحرفي ← خطة ← اعتماد ← سلسلة
الأحداث المعلنة ← حجب صادق ← توفير ← إعادة فحص تلقائية ← تنفيذ بلا
إعادة اعتماد ← أدلة ← مراجعة/تدقيق — **بلا أي refresh يدوي**: كل
قراءة من /state (لقطة المصالحة) أو من التيار الحي.

الحدود الخارجية منظمة فقط (المخطط والمنفذ والمسارات الشبكية عبر
وصفات الجرد المعتمدة في 011) — المحرك والمنسق والوظائف والقاعدة
والبث كلها حقيقية بالكامل.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import routes  # noqa: E402
from api import projects  # noqa: E402
from test_projects_api import client, project_env  # noqa: E402,F401 — fixtures

#: الهدف الحرفي من الأمر (§38.1) — كلمات البحث تجعل web_search مطلوبة.
OSINT_OBJECTIVE = "بناء منصة OSINT متقدمة جدًا وفق أحدث التقنيات والتكنولوجيا المتقدمة"

#: سلسلة الأحداث المطلوبة بعد الاعتماد حرفيًا (013 §4) — بالترتيب.
REQUIRED_CHAIN_AFTER_APPROVAL = [
    "PLAN_APPROVED",
    "JOB_CREATED",
    "JOB_QUEUED",
    "JOB_STARTED",
    "PREFLIGHT_STARTED",
    "CAPABILITIES_EVALUATED",
    "ENVIRONMENT_CHECK_STARTED",
]


def _consume_run(client: TestClient, pid: int, after: int,
                 timeout_s: float = 30.0) -> list[dict]:
    """استهلاك بث التشغيل حتى run.done — الأحداث الكاملة بلا refresh."""
    kinds: list[dict] = []
    deadline = time.monotonic() + timeout_s
    with client.stream(
        "POST", f"/api/projects/{pid}/run/stream?after={after}"
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if time.monotonic() > deadline:
                break
            if line.startswith("data: "):
                try:
                    kinds.append(json.loads(line[6:]))
                except ValueError:
                    continue
    return kinds


def _event_kinds(events: list[dict]) -> list[str]:
    return [e.get("kind", "") for e in events]


def _local_search_source(sessions):
    """مصدر بحث حي محلي — SearXNG بمسار HTTP حقيقي كامل.

    خادم HTTP فعلي داخل الاختبار يقدم نتائج SearXNG صحيحة؛ المزود
    الحقيقي (SearxJsonSearchProvider) يستعلمه عبر HTTP ويفك نتائجه —
    جاهزية البحث هنا حقيقية المسار كاملًا لا سجلًا مزورًا. DDG يُعطل
    (غير متاح فعليًا في بيئة الاختبار) — نفس قرار المالك في الإنتاج.
    """
    import json as _json
    import threading as _threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import sqlalchemy as sa

    from execution.models import ResearchProvider
    from research import service as research_service

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — واجهة المكتبة
            body = _json.dumps({"results": [
                {"title": "OSINT Intelligence Platform Guide",
                 "url": "https://example.com/osint-guide",
                 "content": "دليل منصات الاستخبارات مفتوحة المصدر"},
                {"title": "Advanced OSINT Techniques",
                 "url": "https://example.com/osint-techniques",
                 "content": "تقنيات OSINT متقدمة وأدواتها"},
            ]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    _threading.Thread(target=server.serve_forever, daemon=True).start()

    research_service.ensure_seeded(sessions)
    with sessions() as s:
        ddg = s.scalars(sa.select(ResearchProvider).where(
            ResearchProvider.kind == "search_ddg")).first()
        searx = s.scalars(sa.select(ResearchProvider).where(
            ResearchProvider.kind == "search_searx")).first()
        if ddg is not None:
            ddg.enabled = 0
        searx.enabled = 1
        searx.config_json = _json.dumps(
            {"base_url": f"http://127.0.0.1:{port}"})
        s.commit()
        searx_id = searx.id
    # مسبار حقيقي عبر المسار الرسمي: HTTP فعلي + تحليل فعلي
    result = research_service.probe_provider(sessions, searx_id)
    assert result["status"] == "READY", result
    return server


def _sandbox_env(sessions, *, status, sandboxed):
    """ضبط صف البيئة المحلية (نمط 011) — الحتمية عبر المنصات."""
    import sqlalchemy as sa

    from execution.models import ExecutionEnvironment
    from execution import service as execution_service

    execution_service.ensure_local_registered(sessions)
    with sessions() as s:
        row = s.scalars(sa.select(ExecutionEnvironment).where(
            ExecutionEnvironment.name.in_(("local-linux",
                                           "local-windows")))).first()
        row.status = status
        row.sandboxed = sandboxed
        s.commit()
        return row.id


@pytest.fixture()
def sandbox_seam(monkeypatch):
    """وصفة مسبار sandbox (نمط 011 المعتمد): الحقيقة من صف البيئة
    حصرًا — حتمية كاملة عبر المنصات؛ لا علاقة لركيزة المضيف بالاختبار.
    الدورة الحقيقية الكاملة لها اختبارات التجهيز الحية."""
    from execution import service as execution_service

    def fake_sandbox_probe(sessions_, **_kwargs):
        environments = execution_service.list_environments(sessions_)
        ready = [e for e in environments
                 if e["status"] == "READY" and e.get("sandboxed")]
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


# ------------------------------------------------------------------ #
# §38 — اختبار القبول الإلزامي: الاعتماد الحي بلا refresh
# ------------------------------------------------------------------ #

def test_mandatory_approval_live_flow(client, project_env, sandbox_seam):
    """المشهد الكامل (§38 خطوة بخطوة) — الهدف الحرفي للمالك."""
    sessions = project_env["sessions"]
    # مصدر بحث حي (HTTP فعلي) كي يكون الحاجب الوحيد هو البيئة —
    # جاهزية البحث هنا حقيقية المسار لا موضع ثقة
    _local_search_source(sessions)
    # البيئة غير مجهزة بعد — مسار §38 خطوة 11 (blocked + provisioning)
    _sandbox_env(sessions, status="NOT_READY", sandboxed=1)

    # 1-2. إرسال الهدف وانتظار توليد الخطة
    created = client.post("/api/projects", json={
        "name": "منصة OSINT", "objective": OSINT_OBJECTIVE,
    })
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    from tests.api.planning_wait import wait_for_plan

    generated = client.post(f"/api/projects/{pid}/plan/generate")
    assert generated.status_code == 200, generated.text
    wait_for_plan(client, pid)

    # 3-4. لا refresh: لقطة المصالحة تُظهر بطاقة الاعتماد فورًا
    state = client.get(f"/api/projects/{pid}/state").json()
    approval_gate = next(
        (g for g in state["gates"]
         if g["kind"] == "PLAN_APPROVAL" and g["status"] == "PENDING"),
        None,
    )
    assert approval_gate is not None, "بطاقة الاعتماد غائبة عن اللقطة"
    before_id = state["last_event_id"]

    # 5-9. اضغط اعتماد — لا refresh: السلسلة تتدفق بترتيبها المعلن
    approved = client.post(f"/api/projects/{pid}/plan/approve",
                           json={"approved": True})
    assert approved.status_code == 200, approved.text
    assert approved.json()["launch"]["launched"] is True

    events = _consume_run(client, pid, before_id)
    kinds = _event_kinds(events)

    # (§4) الترتيب المعلن حرفيًا بعد OWNER_GATE_RESOLVED
    assert "OWNER_GATE_RESOLVED" in kinds
    chain_positions = [kinds.index(k) for k in REQUIRED_CHAIN_AFTER_APPROVAL
                       if k in kinds]
    assert len(chain_positions) == len(REQUIRED_CHAIN_AFTER_APPROVAL), (
        f"سلسلة ناقصة: {set(REQUIRED_CHAIN_AFTER_APPROVAL) - set(kinds)}"
    )
    assert chain_positions == sorted(chain_positions), \
        f"ترتيب السلسلة مكسور: {[k for k in kinds if k.startswith(('PLAN', 'JOB', 'PREFLIGHT', 'ENVIRONMENT', 'EXECUTION_OPEN'))]}"

    # 10-11. البيئة غير جاهزة → حجب صادق مع السبب وإجراء المالك
    assert "PREFLIGHT_BLOCKED" in kinds
    state = client.get(f"/api/projects/{pid}/state").json()
    assert state["status"] == "BLOCKED"
    assert state["execution_gate"]["state"] == "APPROVED_BUT_BLOCKED"
    assert state["execution_gate"]["open_for_execution"] is False
    assert "البيئة" in state["execution_gate"]["reason"] \
        or "معزولة" in state["execution_gate"]["reason"] \
        or "بيئة" in state["execution_gate"]["reason"]
    blocked_gate = next(
        (g for g in state["gates"]
         if g["kind"] == "PREFLIGHT_BLOCKED"), None,
    )
    assert blocked_gate is not None
    # الوظيفة توقفت بأمان WAITING_WORKER — لا موت صامت (§19)
    job = state["job"]
    assert job["status"] == "WAITING_WORKER"
    assert job["waiting_kind"] == "WORKER"
    assert job["worker_id"], "هوية المنفذ مفقودة (§19)"
    assert job["resume_token"], "رمز الاستئناف مفقود (§19)"

    # 12. المالك جهز البيئة (توفير — صف البيئة يصبح جاهزًا معزولًا)
    _sandbox_env(sessions, status="READY", sandboxed=1)
    blocked_before = state["last_event_id"]

    # 13. إعادة الفحص → نجاح → تنفيذ تلقائي **بلا إعادة اعتماد**
    rechecked = client.post(f"/api/projects/{pid}/preflight").json()
    assert rechecked["preflight"]["verdict"] == "PASS", rechecked
    assert rechecked["launch"]["launched"] is True, rechecked["launch"]

    events2 = _consume_run(client, pid, blocked_before)
    kinds2 = _event_kinds(events2)

    # السلسلة الكاملة حتى المرشح — والأدلة والأدوار والأدوات ظاهرة
    for required in (
        "PREFLIGHT_RECHECKED", "ENVIRONMENT_READY", "EXECUTION_OPENED",
        "GATE_AUTO_RESOLVED", "PHASE_STARTED", "STEP_STARTED",
        "ROLE_EXECUTING", "TOOL_EXECUTION", "EXECUTION_COMPLETED",
        "EVIDENCE_CREATED", "AUDIT_COMPLETED", "STEP_COMPLETED",
        "STAGE_REVIEW", "PROJECT_COMPLETION_CANDIDATE",
    ):
        assert required in kinds2, \
            f"{required} غائب عن السلسلة بعد التوفير: {kinds2}"

    # لا إعادة اعتماد أبدًا: لا بوابة اعتماد جديدة ولا PLAN_APPROVAL ثانية
    assert "PLAN_APPROVAL_REQUIRED" not in kinds2
    assert "PLAN_APPROVED" not in kinds2
    state = client.get(f"/api/projects/{pid}/state").json()
    assert state["plan"]["approved_by_owner"] is True
    assert not [g for g in state["gates"]
                if g["kind"] == "PLAN_APPROVAL" and g["status"] == "PENDING"]

    # 15-19. الوظيفة والأدلة والمراجعة — كلها في اللقطة نفسها (لا refresh)
    assert state["job"]["status"] == "WAITING_GATE"  # التحقق النهائي للمالك
    assert state["evidence"], "لا أدلة بعد التنفيذ"
    assert state["audits"], "لا تدقيق بعد التنفيذ"
    criteria = state["acceptance_criteria"]
    assert criteria and criteria[0]["criterion_id"] == "AC-01"
    assert criteria[0]["verification_method"] in (
        "artifact_check", "test_run", "integration_test",
        "live_source_test", "manual_review",
    )
    # 20. التحقق النهائي — قرار المالك وحده (§51)
    verified = client.post(f"/api/projects/{pid}/verify")
    assert verified.status_code == 200
    assert verified.json()["status"] == "VERIFIED"


# ------------------------------------------------------------------ #
# §39 — الاعتماد بعد إغلاق المتصفح وفتحه من جديد
# ------------------------------------------------------------------ #

def test_approval_after_reload(client, project_env, sandbox_seam):
    """إنشاء الخطة ← إغلاق المتصفح ← فتحه ← الاعتماد ← التنفيذ."""
    _sandbox_env(project_env["sessions"], status="READY", sandboxed=1)
    created = client.post("/api/projects", json={
        "name": "بعد الفتح", "objective": "هدف اختبار إعادة الفتح",
    })
    pid = created.json()["id"]
    assert client.post(
        f"/api/projects/{pid}/plan/generate").status_code == 200
    from tests.api.planning_wait import wait_for_plan

    wait_for_plan(client, pid)

    # «إغلاق المتصفح وفتحه»: عميل جديد كليًا — الحالة من القاعدة وحدها
    fresh_client = TestClient(routes.app)
    state = fresh_client.get(f"/api/projects/{pid}/state").json()
    gate = next((g for g in state["gates"]
                 if g["kind"] == "PLAN_APPROVAL"
                 and g["status"] == "PENDING"), None)
    assert gate is not None, "الخطة لم تبق بانتظار الاعتماد بعد الفتح"
    before = state["last_event_id"]

    approved = fresh_client.post(
        f"/api/projects/{pid}/plan/approve", json={"approved": True}
    )
    assert approved.status_code == 200
    assert approved.json()["launch"]["launched"] is True

    events = _consume_run(fresh_client, pid, before)
    kinds = _event_kinds(events)
    assert "JOB_CREATED" in kinds and "PREFLIGHT_STARTED" in kinds


# ------------------------------------------------------------------ #
# §40 — ازدواج الاعتماد: نقرتان سريعتان = قرار منطقي واحد
# ------------------------------------------------------------------ #

def test_approval_duplication_single_logical_effect(client, project_env,
                                                    sandbox_seam):
    _sandbox_env(project_env["sessions"], status="READY", sandboxed=1)
    created = client.post("/api/projects", json={
        "name": "ازدواج", "objective": "هدف اختبار الازدواج",
    })
    pid = created.json()["id"]
    from tests.api.planning_wait import wait_for_plan

    client.post(f"/api/projects/{pid}/plan/generate")
    wait_for_plan(client, pid)

    # نقرتان متتاليتان بأسرع ما يمكن — قبل اكتمال الأولى نظاهريًا
    first = client.post(f"/api/projects/{pid}/plan/approve",
                        json={"approved": True})
    second = client.post(f"/api/projects/{pid}/plan/approve",
                         json={"approved": True})
    assert first.status_code == 200
    assert first.json()["launch"]["launched"] is True
    # الثانية: idempotent — لا إطلاق ثانٍ ولا خطأ (011 §1)
    assert second.status_code in (200, 409)
    if second.status_code == 200:
        assert second.json()["launch"]["launched"] is False

    # انتظر اكتمال الدورة ثم اثبت: وظيفة واحدة، تنفيذ واحد، قرار واحد
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/projects/{pid}/state").json()
        if state["job"] and state["job"]["status"] in (
            "WAITING_GATE", "WAITING_WORKER", "COMPLETED", "FAILED",
        ):
            break
        time.sleep(0.2)
    jobs = client.get("/api/harness/jobs").json()["jobs"]
    project_jobs = [j for j in jobs if j["project_id"] == pid]
    assert len(project_jobs) == 1, \
        f"ازدواج وظيفي: {[(j['id'], j['status']) for j in project_jobs]}"
    assert len(project_env["runs"]) == 1, \
        f"ازدواج تنفيذ: {len(project_env['runs'])} تشغيلات"
    events = client.get(f"/api/projects/{pid}/events?limit=500").json()
    kinds = _event_kinds(events["events"])
    assert kinds.count("JOB_CREATED") == 1
    assert kinds.count("PLAN_APPROVED") == 1
    assert kinds.count("OWNER_GATE_RESOLVED") == 1
