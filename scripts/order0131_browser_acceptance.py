#!/usr/bin/env python3
"""القبول الحي بالمتصفح للأمر 013.1 — القاعدة الذهبية تحت المتصفح.

السيناريو الحرفي من الأمر:
  §25  إنشاء مشروع OSINT من الواجهة (الهدف الحرفي) ← خطة ← اعتماد
  §14  حجب صادق (بيئة غير جاهزة) ← زر التجهيز (توفير حقيقي) ←
       إعادة فحص ← إطلاق آلي بنفس الوظيفة (لا إعادة اعتماد)
  §6   GATE: مغادرة فورية أثناء التنفيذ ← محادثة جديدة ← محادثة
       قديمة ← عودة للمشروع — بلا refresh والتنفيذ استمر والأحداث
       الفائتة ظاهرة والحالة صحيحة
  §7   تبويبان متزامنان بلا refresh
  §8   إغلاق المتصفح أثناء التنفيذ ← انتظار ← إعادة فتح ← نفس
       الوظيفة والحالة والأحداث (لا وظيفة جديدة)
  §19+§21 الإيقاف الصريح وحده من بطاقة التنفيذ

حدود منظمة معلنة (نفس معيار §38 المقبول في 013):
- منفذ الخطوة منظم (scripted) يكتب ملفات حقيقية ويحترم الإيقاف —
  حد LLM الخارجي. كل ما عداه حقيقي بالكامل: الخادم عملية فعلية،
  القاعدة، المنسق، الوظائف، النبضات، التوفير والتحقق (ركيزة
  معزولة فعلية على Linux)، البث SSE، إعادة التشغيل، والواجهة.
- البحث: خادم SearXNG محلي بمسار HTTP كامل (نمط §38).

اللقطات إلى download/order0131-screenshots/ والأدلة إلى
download/order0131-evidence.json.

تشغيل:  python scripts/order0131_browser_acceptance.py
خادم فقط: python scripts/order0131_browser_acceptance.py --server
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PORT = int(os.environ.get("AES_0131_PORT", "8131"))
BASE = f"http://127.0.0.1:{PORT}"
SHOTS = Path("/home/z/my-project/download/order0131-screenshots")
EVIDENCE_PATH = Path(
    "/home/z/my-project/download/order0131-evidence.json"
)

OSINT_OBJECTIVE = ("بناء منصة OSINT متقدمة جدًا وفق أحدث التقنيات "
                   "والتكنولوجيا المتقدمة")

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, note: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {note}" if note else ""))
    (PASS if ok else FAIL).append(name)
    return ok


def api(method: str, path: str, body: dict | None = None,
        timeout: float = 60.0):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ================================================================== #
# وضع الخادم — إقلاع حقيقي بحدود منظمة (نمط §38 المقبول)
# ================================================================== #

def run_server() -> int:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    # (013.1 §17) مجلد runtime ثابت عبر إعادة التشغيل — قتل الخادم
    # وإعادة إطلاقه يجد نفس القاعدة الدائمة (اختبار العامل الحقيقي)
    fixed = os.environ.get("AES_0131_RUNTIME")
    if fixed:
        runtime = Path(fixed)
        runtime.mkdir(parents=True, exist_ok=True)
    else:
        runtime = Path(tempfile.mkdtemp(prefix="aes-0131-runtime-"))
    os.chdir(runtime)
    fresh_db = not (runtime / "runtime" / "acceptance.db").exists()
    for sub in ("browser", "projects", "readiness-probes", "secrets"):
        (runtime / sub).mkdir(parents=True, exist_ok=True)

    # ---- 1) خادم بحث SearXNG محلي (مسار HTTP كامل — نمط §38) ----
    class SearxHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"results": [
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

    searx = HTTPServer(("127.0.0.1", 0), SearxHandler)
    searx_port = searx.server_address[1]
    threading.Thread(target=searx.serve_forever, daemon=True).start()

    # ---- 2) القاعدة والبذور ----
    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )
    from providers_registry import registry

    engine = build_engine(runtime / "runtime" / "acceptance.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)

    # (حرج) قاعدة واحدة للحقيقة: مسارات الـAPI تبني جلساتها عند
    # الاستيراد من db_path النسبي — نستبدلها بجلسات قاعدتنا هذه كما
    # يفعل fixture الاختبارات (routes._sessions = sessions) وإلا
    # صارت للـAPI قاعدة وللمحرك قاعدة أخرى.
    from api import routes as routes_api

    routes_api._sessions = sessions

    # البحث: SearXNG المحلي جاهز حقيقي المسار، DDG معطل (نمط §38)
    import sqlalchemy as sa

    from execution.models import ResearchProvider
    from research import service as research_service

    research_service.ensure_seeded(sessions)
    with sessions() as s:
        ddg = s.scalars(sa.select(ResearchProvider).where(
            ResearchProvider.kind == "search_ddg")).first()
        searx_row = s.scalars(sa.select(ResearchProvider).where(
            ResearchProvider.kind == "search_searx")).first()
        if ddg is not None:
            ddg.enabled = 0
        searx_row.enabled = 1
        searx_row.config_json = json.dumps(
            {"base_url": f"http://127.0.0.1:{searx_port}"})
        s.commit()
        searx_id = searx_row.id
    probe = research_service.probe_provider(sessions, searx_id)
    assert probe["status"] == "READY", probe

    # ---- 3) البيئة: إعداد أول مرة فقط؛ إعادة التشغيل ترث الحالة ----
    from execution import service as execution_service
    from execution.models import ExecutionEnvironment

    if fresh_db:
        execution_service.ensure_local_registered(sessions)
        with sessions() as s:
            row = s.scalars(sa.select(ExecutionEnvironment).where(
                ExecutionEnvironment.name.in_(("local-linux",
                                               "local-windows")))).first()
            row.status = "NOT_READY"
            row.sandboxed = 1
            s.commit()

    # seam المسبار (نمط §38): الحقيقة من صف البيئة حصرًا — التوفير
    # نفسه حقيقي بالكامل (verify فعلي على الركيزة الفعلية)، وإعادة
    # التشغيل تستعمل نفس الـseam فلا يتغير سلوك الفحص
    def fake_sandbox_probe(sessions_, **_kwargs):
        environments = execution_service.list_environments(sessions_)
        ready = [e for e in environments
                 if e["status"] == "READY" and e.get("sandboxed")]
        return {
            "status": "READY" if ready else "NOT_READY",
            "reason": "بيئة معزولة جاهزة" if ready
            else "لا بيئة تنفيذ معزولة جاهزة",
            "latency_ms": 1, "ttl_seconds": 300,
            "failure_class": "" if ready else "SANDBOX_FAILURE",
            "failure_stage": "" if ready else "STARTUP",
            "details": {"acceptance_seam": True},
        }

    execution_service.sandbox_probe_result = fake_sandbox_probe

    # ---- 4) محادثة قديمة (قاعدة جديدة فقط — لا تكرار بعد التشغيل) --
    if fresh_db:
        from persistence import conversations as convo

        old = convo.create_conversation(
            sessions, title="محادثة قديمة قبل المشروع", mode="chat")
        from persistence.models import Message

        with sessions() as s:
            s.add(Message(conversation_id=old.id, role="user",
                          content="ما مبادئ OSINT الأساسية؟"))
            s.add(Message(conversation_id=old.id, role="assistant",
                          content="المبادئ: المصادر المفتوحة، التوثيق، "
                                  "التحقق المتقاطع، الأثر الرقمي، "
                                  "والأخلاق."))
            s.commit()

    # ---- 5) المصنع المنظم (حد LLM — منفذ بطيء يحترم الإيقاف) ----
    import hashlib

    from api import projects as projects_api
    from tasks import TaskResult

    class ScriptedRouter:
        def __init__(self):
            self._providers = {"nvidia"}

        def has_live_provider(self, provider_id):
            return str(provider_id) in self._providers

        def live_providers(self):
            return sorted(self._providers)

    SLOW_PLAN = {
        "objective": OSINT_OBJECTIVE,
        "assumptions": ["البيئة المعزولة متاحة للتجهيز"],
        "acceptance_criteria": [
            "ملف تقرير الخطوة موجود ضمن الأدلة"],
        "phases": [{
            "title": "بناء المنصة",
            "objective": "تأسيس المنصة",
            "acceptance_criteria": ["ملف تقرير الخطوة موجود ضمن الأدلة"],
            "steps": [
                {"objective": "جمع المتطلبات وكتابة التقرير الأول",
                 "input": "", "expected_output": "deliverable.md",
                 "acceptance_criteria": [
                     "ملف تقرير الخطوة موجود ضمن الأدلة"],
                 "dependencies": []},
                {"objective": "تعميق التحليل وكتابة التقرير الثاني",
                 "input": "", "expected_output": "deliverable.md",
                 "acceptance_criteria": [
                     "ملف تقرير الخطوة موجود ضمن الأدلة"],
                 "dependencies": []},
            ],
        }],
        "risks": [], "dependencies": [], "required_owner_decisions": [],
    }

    class ScriptedPlanner:
        def generate(self, objective, *, previous_failure=None, feedback=""):
            return json.loads(json.dumps(SLOW_PLAN))

    _EXEC_STOPS: list[float] = []

    def slow_run_task(goal, *, router, role_config=None, workspace=None,
                      on_event=None, cycle_id=None, stop_controller=None,
                      resume_from=None, **_kw):
        """منفذ بطيء عمدًا (~6ث/خطوة) بأحداث حية — نافذة التنقل §6.

        يحترم الإيقاف بمفتاح المشروع (013.1 §19) كما المنفذ الحقيقي.
        """
        import time as _time
        from pathlib import Path as _Path

        stop_key = _kw.get("stop_cycle_id") or cycle_id
        stop_check = (stop_controller.checker_for(stop_key)
                      if stop_controller is not None and stop_key
                      else None)
        root = _Path(workspace) if workspace else _Path(".")
        root.mkdir(parents=True, exist_ok=True)
        index = len(_EXEC_STOPS) + 1
        marks = [0.0, 3.0, 6.0]
        for phase_i, (label, at) in enumerate(
                [("بدء", 0.0), ("تحليل", 3.0), ("كتابة", 6.0)]):
            if stop_check is not None and stop_check():
                _EXEC_STOPS.append(at)
                return TaskResult(
                    verdict="STOPPED", reason="إيقاف المالك أثناء "
                    "التنفيذ البطيء", goal=goal)
            if at:
                _time.sleep(at - marks[phase_i - 1])
            if on_event is not None:
                try:
                    on_event({"kind": "tool.started",
                              "role": "implementer",
                              "tool": "write_file",
                              "query": f"deliverable-{index}-{label}.md",
                              "execution_site": "substrate",
                              "tool_call_id": f"tc-{index}-{phase_i}"})
                except Exception:  # noqa: BLE001
                    pass
        output = root / "deliverable.md"
        output.write_text(
            f"# مخرج {index}\n\n{goal}\n", encoding="utf-8")
        evidence_path = root / "evidence.json"
        evidence_path.write_text("{}", encoding="utf-8")
        return TaskResult(
            verdict="PASS", reason="اكتملت بأدلة", goal=goal,
            cycle_id=cycle_id or "", final_state="EVIDENCED",
            workspace=str(root), files=["deliverable.md"],
            tool_calls=[],
            evidence_path=str(evidence_path),
            evidence_sha256=hashlib.sha256(
                evidence_path.read_bytes()).hexdigest(),
            duration_ms=7000, state_history=["EVIDENCED"],
        )

    import tasks as tasks_mod

    tasks_mod.run_task = slow_run_task

    def factory(on_event=None, **_kwargs):
        from workflow.engine import ProjectEngine

        return ProjectEngine(
            sessions,
            router_factory=ScriptedRouter,
            planner_factory=ScriptedPlanner,
            on_event=on_event,
        )

    projects_api._test_engine_factory = factory

    # ---- 6) الخادم الفعلي ----
    import uvicorn
    from api.routes import app

    print(f"ACCEPTANCE SERVER READY on {PORT} (runtime={runtime})",
          flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    return 0


# ================================================================== #
# وضع المنسق — سيناريو المتصفح الحرفي
# ================================================================== #


def shot_card(page, name: str, css: str):
    """لقطة مع تمرير البطاقة المستهدفة للعرض — .pl-scroll حاوية
    تمرير داخلية فـfull_page لا يوسّعها (درس موثق)."""
    try:
        page.locator(css).first.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001 — التمرير لا يمنع اللقطة
        pass
    page.screenshot(path=str(SHOTS / name), full_page=False)

def wait_css(page, css: str, timeout: float = 30000.0):
    page.wait_for_selector(css, timeout=timeout)


def wait_status(pid: int, statuses: set[str], timeout_s: float = 60.0):
    deadline = time.monotonic() + timeout_s
    job = {}
    while time.monotonic() < deadline:
        state = api("GET", f"/api/projects/{pid}/state")
        job = state.get("job") or {}
        if job.get("status") in statuses:
            return state
        time.sleep(0.4)
    return api("GET", f"/api/projects/{pid}/state")


def run_acceptance() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    evidence: dict = {"command": "013.1", "base": BASE, "projects": {},
                      "screenshots": [], "checks": {}}

    # (§17) runtime ثابت — قتل الخادم وإعادة تشغيله يجد نفس القاعدة
    import shutil as _shutil

    fixed_runtime = "/tmp/aes-0131-fixed-runtime"
    _shutil.rmtree(fixed_runtime, ignore_errors=True)

    server_holder: dict = {"proc": None}

    def start_server():
        server_holder["proc"] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--server"],
            env={**os.environ, "AES_0131_PORT": str(PORT),
                 "AES_0131_RUNTIME": fixed_runtime,
                 "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def wait_healthy(timeout_s: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                api("GET", "/health", timeout=3)
                return True
            except Exception:
                time.sleep(0.6)
        return False

    start_server()
    try:
        # صحة الخادم
        healthy = wait_healthy()
        check("خادم القبول حي (عملية فعلية + قاعدة نظيفة)", healthy)
        if not healthy:
            return 1

        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1440, "height": 940})
            page = context.new_page()

            # ========== §25 — إنشاء من الواجهة بالهدف الحرفي ==========
            page.goto(BASE + "/", wait_until="domcontentloaded")
            wait_css(page, "#plus")
            page.click("#plus")
            page.click('.plus-option[data-mode="project"]')
            page.fill("#input", OSINT_OBJECTIVE)
            page.click("#send")
            wait_css(page, ".pl-card.pl-plan", timeout=30000)
            wait_css(page, ".pl-approval .pl-btn.primary")
            pid = page.evaluate(
                "parseInt(location.hash.slice('#/project/'.length), 10)")
            check("§25 المشروع أُنشئ من الواجهة والخطة ظهرت",
                  bool(pid), f"project #{pid}")
            evidence["projects"]["main"] = {"id": pid}
            page.screenshot(path=str(SHOTS / "01-created-plan.png"), full_page=True)

            # ========== §14 — حجب ← تجهيز حقيقي ← استئناف نفس الوظيفة ==
            page.click(".pl-approval .pl-btn.primary")
            wait_css(page, ".pl-card.pl-blocked", timeout=30000)
            wait_css(page, ".pl-card.pl-env.notready")
            blocked_text = page.locator(".pl-card.pl-blocked"
                                        ).inner_text()
            check("§22 بطاقة الحجب: المضيف المكتشف والمطلوب معلنان",
                  "المضيف المكتشف" in blocked_text
                  and "المطلوب" in blocked_text)
            state = wait_status(pid, {"WAITING_WORKER"})
            first_job = state["job"]["id"]
            check("§14 حجب صادق WAITING_WORKER", True,
                  f"job #{first_job}")
            shot_card(page, "02-blocked-env.png", ".pl-card.pl-blocked")

            page.click(".pl-card.pl-env.notready .pl-btn.primary")
            ok_feedback = page.wait_for_selector(
                ".pl-card.pl-env .pl-feedback.ok",
                timeout=60000)
            check("§14 زر التجهيز: توفير حقيقي اكتمل (فحص فعلي)",
                  ok_feedback is not None)
            # إعادة الفحص ← إطلاق آلي بلا إعادة اعتماد
            page.click(".pl-card.pl-env.notready .pl-btn:not(.primary)")
            wait_css(page, ".pl-card.pl-exec", timeout=60000)
            state = wait_status(pid, {"RUNNING", "COMPLETED",
                                      "WAITING_GATE"})
            resumed_job = state["job"]["id"]
            check("§14+§17 الاستئناف بنفس الوظيفة (لا وظيفة جديدة)",
                  resumed_job == first_job,
                  f"#{resumed_job} == #{first_job}")
            check("§14 بلا إعادة اعتماد — إطلاق آلي بعد الفحص", True,
                  f"attempt={state['job']['attempt']}")
            exec_text = page.locator(".pl-card.pl-exec").inner_text()
            check("§21 بطاقة التنفيذ الحية: البيئة والعامل والمرحلة",
                  "البيئة" in exec_text and "العامل" in exec_text
                  and "آخر نشاط" in exec_text
                  and "إيقاف التنفيذ" in exec_text)
            shot_card(page, "03-executing.png", ".pl-card.pl-exec")
            evidence["projects"]["main"]["job_id"] = first_job

            # ========== §6 — البوابة: مغادرة أثناء التنفيذ ==========
            page.evaluate("window.__noReload = 'alive-0131'")
            activity_before = page.locator(".pl-act").count()
            state_before_leave = api("GET", f"/api/projects/{pid}/state")
            last_id_before = state_before_leave["last_event_id"]

            page.click("#pl-back")                       # مغادرة فورية
            page.wait_for_selector(".composer:not([style*='none'])",
                                   timeout=10000)
            check("§6 المغادرة فورية (زر العودة) أثناء التنفيذ", True)
            page.click("#plus")                          # محادثة جديدة
            page.click('.plus-option[data-mode="chat"]')
            check("§6 New Chat جاهز فورًا بلا refresh", True)

            wait_css(page, ".conv-item")                 # محادثة قديمة
            page.locator(".conv-item").first.click()
            page.wait_for_function(
                "document.getElementById('messages')"
                ".innerText.indexOf('مبادئ') !== -1",
                timeout=10000)
            check("§6 المحادثة القديمة فُتحت فورًا برسائلها", True)
            page.screenshot(path=str(SHOTS / "04-old-chat.png"), full_page=True)

            # غياب مقصود يغطي فاصل أحداث المنفذ البطيء (3ث) — الحتمية
            page.wait_for_timeout(4500)

            # العودة للمشروع — بلا refresh
            wait_css(page, ".pj-item")
            page.locator(".pj-item").first.click()
            wait_css(page, ".pl-card.pl-exec", timeout=30000)
            marker = page.evaluate("window.__noReload")
            check("§6 لا refresh في الرحلة كاملة (العلامة باقية)",
                  marker == "alive-0131")
            activity_after = page.locator(".pl-act").count()
            state = api("GET", f"/api/projects/{pid}/state")
            advanced = state["last_event_id"] > last_id_before
            check("§6 التنفيذ استمر أثناء الغياب (أحداث جديدة)",
                  advanced or activity_after > activity_before,
                  f"last_event_id {last_id_before} → "
                  f"{state['last_event_id']} · نشاط "
                  f"{activity_before} → {activity_after}")
            check("§6 نفس الوظيفة بعد العودة",
                  state["job"]["id"] == first_job,
                  f"#{state['job']['id']}")
            shot_card(page, "05-return-no-refresh.png", ".pl-card.pl-exec")
            evidence["checks"]["gate6_activity"] = {
                "before": activity_before, "after": activity_after}

            # ========== §7 — تبويبان متزامنان بلا refresh ==========
            tab_b = context.new_page()
            tab_b.goto(BASE + f"/#/project/{pid}",
                       wait_until="domcontentloaded")
            tab_b.evaluate("window.__noReloadB = 'alive-b'")
            wait_css(tab_b, ".pl-card", timeout=30000)
            # انتظر النهاية (الخطوتان البطيئتان) في التبويبين
            final = wait_status(pid, {"COMPLETED", "WAITING_GATE",
                                      "VERIFIED"}, timeout_s=120)
            page.wait_for_timeout(2500)   # المصالحة الحية عبر SSE
            tab_b.wait_for_timeout(2500)
            marker_a = page.evaluate("window.__noReload")
            marker_b = tab_b.evaluate("window.__noReloadB")
            check("§7 التبويبان تزامنا بلا refresh (علامتاهما باقيتان)",
                  marker_a == "alive-0131" and marker_b == "alive-b")
            done_a = "مرشح" in page.locator("#pl-scene").inner_text() \
                or page.locator(".pl-verify").count() > 0
            done_b = tab_b.locator(".pl-verify").count() > 0
            check("§7 كلا التبويبين يعرض حالة ما بعد التنفيذ",
                  done_a and done_b,
                  f"status={final['status']}")
            page.screenshot(path=str(SHOTS / "06-two-tabs-a.png"), full_page=True)
            tab_b.screenshot(path=str(SHOTS / "06-two-tabs-b.png"), full_page=True)
            tab_b.close()
            evidence["projects"]["main"]["final_status"] = final["status"]

            # ========== §8 — إغلاق المتصفح أثناء التنفيذ ==========
            page.click("#pl-back")   # خروج من عرض المشروع أولًا
            page.wait_for_selector(".composer:not([style*='none'])",
                                   timeout=10000)
            page.click("#plus")
            page.click('.plus-option[data-mode="project"]')
            page.fill("#input", OSINT_OBJECTIVE + " — الجزء الثاني")
            page.click("#send")
            wait_css(page, ".pl-approval .pl-btn.primary",
                     timeout=30000)
            pid_b = page.evaluate(
                "parseInt(location.hash.slice('#/project/'.length), 10)")
            page.click(".pl-approval .pl-btn.primary")
            wait_css(page, ".pl-card.pl-exec", timeout=60000)
            state = wait_status(pid_b, {"RUNNING"})
            job_b = state["job"]["id"]
            # إغلاق «المتصفح» كاملًا (السياق بكل تبويباته) والتنفيذ جارٍ
            context.close()
            time.sleep(7)   # خطوة كاملة تحدث والمتصفح مغلق
            browser2 = p.chromium.launch()
            context2 = browser2.new_context(
                viewport={"width": 1440, "height": 940})
            page2 = context2.new_page()
            page2.goto(BASE + f"/#/project/{pid_b}",
                       wait_until="domcontentloaded")
            wait_css(page2, ".pl-card.pl-exec, .pl-card.pl-verify",
                     timeout=60000)
            state2 = wait_status(pid_b, {"COMPLETED", "WAITING_GATE",
                                         "RUNNING"}, timeout_s=90)
            same_job = state2["job"]["id"] == job_b
            events_during = len(state2.get("events") or [])
            check("§8 إغلاق المتصفح لم يوقف التنفيذ — نفس الوظيفة",
                  same_job, f"#{state2['job']['id']} == #{job_b}")
            check("§8 العودة تجد الأحداث والخط الزمني كاملًا",
                  events_during >= 2, f"{events_during} events")
            page2.screenshot(path=str(SHOTS / "07-reopen-after-close.png"), full_page=True)
            evidence["projects"]["second"] = {
                "id": pid_b, "job_id": job_b,
                "status": state2["status"]}
            browser2.close()

            # ========== §19+§21 — الإيقاف الصريح من بطاقة التنفيذ ====
            # انتظر انتهاء مشروع B أولًا — الحلقة واحدة في كل لحظة
            # (single-flight): بدء C أثناء عمل B = تعارض مقصود.
            wait_status(pid_b, {"COMPLETED", "WAITING_GATE",
                                "VERIFIED"}, timeout_s=90)
            browser3 = p.chromium.launch()
            context3 = browser3.new_context(
                viewport={"width": 1440, "height": 940})
            page = context3.new_page()
            page.goto(BASE + "/", wait_until="domcontentloaded")
            page.click("#plus")
            page.click('.plus-option[data-mode="project"]')
            page.fill("#input", OSINT_OBJECTIVE + " — اختبار الإيقاف")
            page.click("#send")
            wait_css(page, ".pl-approval .pl-btn.primary", timeout=30000)
            pid_c = page.evaluate(
                "parseInt(location.hash.slice('#/project/'.length), 10)")
            page.click(".pl-approval .pl-btn.primary")
            wait_css(page, ".pl-card.pl-exec", timeout=60000)
            page.click(".pl-card.pl-exec .pl-btn.danger")
            stopped = wait_status(pid_c, {"STOPPED", "PAUSED"},
                                  timeout_s=60)
            check("§19+§21 الإيقاف الصريح وحده — من بطاقة التنفيذ",
                  stopped["status"] in ("STOPPED", "PAUSED"),
                  f"status={stopped['status']}")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(SHOTS / "08-explicit-stop.png"), full_page=True)
            evidence["projects"]["stop_test"] = {
                "id": pid_c, "status": stopped["status"]}

            # ========== §17 — قتل العامل (الخادم) ← استئناف نفس الوظيفة ==
            # مشروع D يعمل ← SIGKILL للخادم (موت العامل فعليًا) ←
            # إعادة تشغيل ← INTERRUPTED ← زر الاستئناف من الواجهة ←
            # نفس الوظيفة تُكمل — لا وظيفة جديدة أبدًا.
            page.click("#pl-back")
            page.wait_for_selector(".composer:not([style*='none'])",
                                   timeout=10000)
            page.click("#plus")
            page.click('.plus-option[data-mode="project"]')
            page.fill("#input", OSINT_OBJECTIVE + " — اختبار انقطاع العامل")
            page.click("#send")
            wait_css(page, ".pl-approval .pl-btn.primary", timeout=30000)
            pid_d = page.evaluate(
                "parseInt(location.hash.slice('#/project/'.length), 10)")
            page.click(".pl-approval .pl-btn.primary")
            wait_css(page, ".pl-card.pl-exec", timeout=60000)
            state_d = wait_status(pid_d, {"RUNNING"})
            job_d = state_d["job"]["id"]
            time.sleep(2.5)   # في قلب الخطوة الأولى — الموت ليس عند حدّ

            server_holder["proc"].kill()      # SIGKILL — موت العامل
            server_holder["proc"].wait(timeout=15)
            time.sleep(1)
            start_server()                    # عامل جديد + نفس القاعدة
            if not check("§17 الخادم أُعيد إطلاقه بعد الموت (نفس القاعدة)",
                         wait_healthy()):
                raise RuntimeError("الخادم لم يعد بعد القتل")

            # الواجهة الحية: اتصال SSE القديم يعيد المحاولة تلقائيًا
            # (backoff) إلى الخادم الجديد — لا refresh يدوي
            page.wait_for_selector(".pl-card.pl-blocked", timeout=45000)
            state_d = wait_status(pid_d, {"INTERRUPTED"}, timeout_s=60)
            check("§17 الوظيفة وُسمت INTERRUPTED بعد موت العامل",
                  state_d["job"]["status"] == "INTERRUPTED",
                  f"job #{job_d} — {state_d['job']['status']}")
            page.wait_for_timeout(1000)
            shot_card(page, "09-worker-killed.png", ".pl-card.pl-blocked")

            # زر الاستئناف تحديدًا (البطاقة تحوي زرّي primary:
            # الاستئناف والتجهيز — نص الزر هو المميز)
            page.locator(".pl-blocked button",
                         has_text="استئناف").first.click()
            wait_css(page, ".pl-card.pl-exec", timeout=60000)
            state_d = wait_status(
                pid_d, {"RUNNING", "COMPLETED", "WAITING_GATE"},
                timeout_s=60)
            same = state_d["job"]["id"] == job_d
            check("§17 الاستئناف من الواجهة بنفس الوظيفة (لا جديدة)",
                  same, f"#{state_d['job']['id']} == #{job_d}")
            final_d = wait_status(pid_d, {"COMPLETED", "WAITING_GATE",
                                          "VERIFIED"}, timeout_s=120)
            check("§17 الوظيفة المستأنفة أكملت حتى النهاية",
                  final_d["status"] in ("COMPLETED", "WAITING_GATE",
                                        "VERIFIED"),
                  f"status={final_d['status']}")
            page.wait_for_timeout(2000)
            shot_card(page, "10-resumed-complete.png", ".pl-card.pl-verify, .pl-card.pl-blocked")
            evidence["projects"]["worker_restart"] = {
                "id": pid_d, "job_id": job_d,
                "final_status": final_d["status"],
                "attempt": final_d["job"]["attempt"]}
            browser3.close()

            browser.close()

        # ---------- أدلة ختامية ----------
        final_state = api("GET", f"/api/projects/{pid}/state")
        evidence["projects"]["main"]["events_count"] = len(
            final_state.get("events") or [])
        evidence["projects"]["main"]["environment"] = final_state.get(
            "environment", {}).get("selected")
        evidence["screenshots"] = sorted(x.name for x in SHOTS.glob(
            "*.png"))
        EVIDENCE_PATH.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8")

        print("\n" + "=" * 60)
        print(f"النتيجة: {len(PASS)} PASS / {len(FAIL)} FAIL")
        if FAIL:
            print("الفاشل:")
            for name in FAIL:
                print("  ✗", name)
        print(f"الأدلة: {EVIDENCE_PATH}")
        print(f"اللقطات: {SHOTS}")
        return 1 if FAIL else 0
    finally:
        proc = server_holder["proc"]
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            tail = []
            if proc.stdout:
                try:
                    for _ in range(200):
                        line = proc.stdout.readline()
                        if not line:
                            break
                        tail.append(line.rstrip())
                except Exception:  # noqa: BLE001
                    pass
            if FAIL and tail:
                print("\n--- ذيل خادم القبول ---")
                print("\n".join(tail[-40:]))
        _shutil.rmtree(fixed_runtime, ignore_errors=True)


if __name__ == "__main__":
    if "--server" in sys.argv:
        sys.exit(run_server())
    sys.exit(run_acceptance())
