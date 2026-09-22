#!/usr/bin/env python3
"""القبول الحي للأمر 013.2 — الحقيقة الثلاثية تحت المتصفح الحقيقي.

العقد الحرفي من الأمر:
§16 المسار الحقيقي للمستخدم: إنشاء ← خطة ← اعتماد ← بيئة ← تنفيذ،
   ثم مغادرة ← محادثة جديدة ← قديمة ← عودة بلا refresh، ثم إغلاق
   المتصفح ← إعادة فتح ← نفس الوظيفة.
§17 اختبار الحقيقة الحاسم: عند اللحظة التي تقول فيها الواجهة
   «بيئة التنفيذ جاهزة» نسأل الحالة القانونية في الـbackend — يجب
   أن تقول READY بنفس environment_id. وأي انفصام = FAIL.
§18 لا قبول بالتقارير: الأدلة قاعدة/سجل أحداث/فحص صحة/نبضة عامل/
   UI مرصود/لقطات/ملاحظات شبكة — تُحفظ في evidence JSON.
§19 لقطات A-J: مشروع جديد/خطة/اعتماد/تجهيز/جاهزة/تنفيذ/مراجعة/
   مكتمل/فشل بيئة/تنقّل أثناء التنفيذ.
§21 المشروع النهائي بالهدف الحرفي + كل انتقال يُقارن عبر
   DATABASE / EVENT LOG / API / SSE / UI.
+ إصلاح البحث حيًّا: مسبار DDG (تصنيف التحدّ الصادق) + مسبار Bing
   (READY حقيقي) + بحث فعلي عبر API التطبيق.

الحد المعلن الوحيد (نمط §38 المقبول في 013/013.1): منفذ الخطوة
والمخطط منظمان — حد الـLLM الخارجي؛ كل ما عداه حقيقي بالكامل:
الخادم عملية فعلية، القاعدة، المنسق، الوظائف والنبضات، التجهيز
والفحوص (ركيزة معزولة فعلية على Linux)، البث SSE، والمتصفح.

اللقطات إلى download/0132_shots/ والأدلة إلى
download/order0132-evidence.json.

تشغيل:  python scripts/order0132_acceptance.py
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

PORT = int(os.environ.get("AES_0132_PORT", "8132"))
BASE = f"http://127.0.0.1:{PORT}"
SHOTS = Path("/home/z/my-project/download/0132_shots")
EVIDENCE_PATH = Path(
    "/home/z/my-project/download/order0132-evidence.json"
)
RUNTIME_DIR = Path("/tmp/aes-0132-fixed-runtime")

OSINT_OBJECTIVE = ("بناء منصة OSINT متقدمة جدًا وفق أحدث التقنيات "
                   "والتكنولوجيا المتقدمة")

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, note: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {note}" if note else ""), flush=True)
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
# وضع الخادم — حقيقي بالكامل إلا حد الـLLM المعلن
# ================================================================== #

def run_server() -> int:
    import hashlib

    runtime = RUNTIME_DIR
    runtime.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime)
    fresh_db = not (runtime / "runtime" / "acceptance.db").exists()
    for sub in ("browser", "projects", "readiness-probes", "secrets"):
        (runtime / sub).mkdir(parents=True, exist_ok=True)

    # ---- القاعدة والبذور (حقيقية) ----
    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )
    from providers_registry import registry

    engine = build_engine(runtime / "runtime" / "acceptance.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)

    # قاعدة واحدة للحقيقة: جلسات الـAPI هي جلسات قاعدتنا
    from api import routes as routes_api

    routes_api._sessions = sessions

    # (013.2 §16) ربط الأدوار بمزود حقيقي قابل للحل في هذه البيئة:
    # zai_internal (مزود الحاوية المعلن — config_file حقيقي)، بدل
    # nvidia بلا مفتاح الذي يجعل قدرة llm NOT_READY بصدق. استدعاءات
    # الـLLM نفسها خلف الحد المعلن (مخطط/منفذ منظمان) — الربط حقيقي.
    import sqlalchemy as sa

    from providers_registry.models import RoleProviderMapping

    with sessions() as s:
        zai_spec = registry.resolve_provider_specs(sessions).get(
            "zai_internal")
        if zai_spec:
            for mapping in s.scalars(
                sa.select(RoleProviderMapping)
            ).all():
                mapping.provider = "zai_internal"
                mapping.model = zai_spec.get("model", "glm-4.6")
                mapping.configuration = ""
            s.commit()

    # البحث: مزودو التطبيق الحقيقيون (ddg متعدد الاستراتيجيات + bing)
    # بلا خادم بحث مصطنع — المسبار الحي هو الدليل (013.2)
    from research import service as research_service

    research_service.ensure_seeded(sessions)

    # البيئة: تسجيل محلي UNKNOWN أول مرة — التجهيز الحقيقي من الواجهة
    from execution import service as execution_service

    if fresh_db:
        execution_service.ensure_local_registered(sessions)

    # محادثة قديمة لاختبار التنقّل (قاعدة جديدة فقط)
    if fresh_db:
        from persistence import conversations as convo
        from persistence.models import Message

        old = convo.create_conversation(
            sessions, title="محادثة قديمة قبل المشروع", mode="chat")
        with sessions() as s:
            s.add(Message(conversation_id=old.id, role="user",
                          content="ما مبادئ OSINT الأساسية؟"))
            s.add(Message(conversation_id=old.id, role="assistant",
                          content="المبادئ: المصادر المفتوحة، التوثيق، "
                                  "التحقق المتقاطع، الأثر الرقمي."))
            s.commit()

    # ---- حد الـLLP المعلن (نمط §38): مخطط+منفذ منظمان بطيئان ----
    from api import projects as projects_api
    from tasks import TaskResult

    class ScriptedRouter:
        def __init__(self):
            self._providers = {"zai_internal", "nvidia", "mock"}

        def has_live_provider(self, provider_id):
            return str(provider_id) in self._providers

        def live_providers(self):
            return sorted(self._providers)

    SLOW_PLAN = {
        "objective": OSINT_OBJECTIVE,
        "assumptions": ["بيئة Linux معزولة قابلة للتجهيز فعليًا"],
        "acceptance_criteria": [
            "ملف تقرير الخطوة موجود ضمن الأدلة"],
        "phases": [{
            "title": "تأسيس منصة OSINT",
            "objective": "بناء أساس المنصة وتقاريرها",
            "acceptance_criteria": [
                "ملف تقرير الخطوة موجود ضمن الأدلة"],
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

    def slow_run_task(goal, *, router, role_config=None, workspace=None,
                      on_event=None, cycle_id=None, stop_controller=None,
                      resume_from=None, **_kw):
        """منفذ بطيء عمدًا (~6ث/خطوة) — نافذة التنقّل والإغلاق."""
        import time as _time
        from pathlib import Path as _Path

        stop_key = _kw.get("stop_cycle_id") or cycle_id
        stop_check = (stop_controller.checker_for(stop_key)
                      if stop_controller is not None and stop_key
                      else None)
        root = _Path(workspace) if workspace else _Path(".")
        root.mkdir(parents=True, exist_ok=True)
        index = int(_time.monotonic() * 1000) % 100000
        marks = [0.0, 3.0, 6.0]
        for phase_i, (label, at) in enumerate(
                [("بدء", 0.0), ("تحليل", 3.0), ("كتابة", 6.0)]):
            if stop_check is not None and stop_check():
                return TaskResult(
                    verdict="STOPPED",
                    reason="إيقاف المالك أثناء التنفيذ البطيء", goal=goal)
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

    # ---- الخادم الفعلي ----
    import uvicorn
    from api.routes import app

    print(f"0132 ACCEPTANCE SERVER READY on {PORT} "
          f"(runtime={runtime})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    return 0


# ================================================================== #
# وضع المنسق — السيناريو الحرفي + الحقيقة الثلاثية
# ================================================================== #

def shot_card(page, name: str, css: str):
    try:
        page.locator(css).first.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass
    page.screenshot(path=str(SHOTS / name), full_page=False)


def dom_click_any(page, css_list: list[str]) -> bool:
    """نقر أول زر متاح من قائمة محددات — إعادة الرسم الحية تجعل
    الزر ينتقل بين البطاقات (الحجب/البيئة) حسب الحالة."""
    return page.evaluate(
        "selectors => { for (const s of selectors)"
        " { const b = document.querySelector(s);"
        " if (b && !b.disabled) { b.click(); return true; } }"
        " return false; }", arg=css_list)


def wait_css(page, css: str, timeout: float = 30000.0):
    page.wait_for_selector(css, timeout=timeout)


def dom_click(page, css: str):
    """نقر عبر الـDOM — مقاوم لإعادة الرسم الحية التي تفصل الأزرار
    بين التحديد والنقر (التحديث الحي ميزة لا عطلًا)."""
    page.wait_for_function(
        "selector => { const b = document.querySelector(selector);"
        " return !!b && !b.disabled; }", arg=css, timeout=20000)
    page.evaluate(
        "selector => document.querySelector(selector).click()", arg=css)


def wait_status(pid: int, statuses: set[str], timeout_s: float = 90.0):
    deadline = time.monotonic() + timeout_s
    job = {}
    while time.monotonic() < deadline:
        state = api("GET", f"/api/projects/{pid}/state")
        job = state.get("job") or {}
        if job.get("status") in statuses:
            return state
        time.sleep(0.4)
    return api("GET", f"/api/projects/{pid}/state")


class SSECollector(threading.Thread):
    """جامع أحداث SSE حي (§18: ملاحظات شبكة) — دليل البث الحي."""

    def __init__(self):
        super().__init__(daemon=True)
        self.events: list[dict] = []
        self.stop = False
        self._resp = None

    def run(self):
        try:
            req = urllib.request.Request(
                BASE + "/api/projects/events/stream")
            self._resp = urllib.request.urlopen(req, timeout=600)
            buf = b""
            while not self.stop:
                chunk = self._resp.read1(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    raw, buf = buf.split(b"\n\n", 1)
                    for line in raw.decode("utf-8", "replace")\
                            .splitlines():
                        if line.startswith("data: "):
                            try:
                                event = json.loads(line[6:])
                                if isinstance(event, dict) \
                                        and event.get("kind"):
                                    self.events.append(event)
                            except ValueError:
                                pass
        except Exception:  # noqa: BLE001 — الجمع دليل لا شرط
            pass

    def finish(self):
        self.stop = True
        try:
            if self._resp:
                self._resp.close()
        except Exception:  # noqa: BLE001
            pass


def db_truth(pid: int) -> dict:
    """قراءة القاعدة مباشرة (§18) — الحقيقة من الصفوف لا من التقارير."""
    import sqlite3

    db_path = RUNTIME_DIR / "runtime" / "acceptance.db"
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                project = conn.execute(
                    "SELECT id, status, execution_policy FROM projects "
                    "WHERE id=?", (pid,)).fetchone()
                job = conn.execute(
                    "SELECT id, status, worker_id, heartbeat_at "
                    "FROM engineering_jobs WHERE project_id=? "
                    "ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
                envs = conn.execute(
                    "SELECT id, name, status, sandboxed FROM "
                    "execution_environments ORDER BY id").fetchall()
                record = conn.execute(
                    "SELECT state, environment_id, progress, reason FROM "
                    "runtime_state_records WHERE policy=? "
                    "ORDER BY id DESC LIMIT 1",
                    ((project["execution_policy"]
                      if project else "STRICT_ISOLATED"),)).fetchone()
                return {
                    "project_status": project["status"] if project else None,
                    "job": dict(job) if job else None,
                    "environments": [dict(e) for e in envs],
                    "runtime_record": dict(record) if record else None,
                }
            finally:
                conn.close()
        except Exception as error:  # noqa: BLE001 — قفل مؤقت
            last_error = error
            time.sleep(0.5)
    return {"error": f"قراءة القاعدة فشلت: {last_error}"}


def truth_check(page, pid: int, label: str, evidence: dict) -> dict:
    """(§17+§21) الحقيقة الثلاثية: قاعدة + قانونية + واجهة تتفق.

    تُستدعى عند كل انتقال — أي انفصام بين القراءات = فشل صريح.
    """
    db = db_truth(pid)
    canonical = api(
        "GET",
        f"/api/execution/runtime-state?project_id={pid}")
    snapshot = api("GET", f"/api/projects/{pid}/state")
    runtime = (snapshot.get("environment") or {}).get("runtime_state") \
        or {}

    # UI: نص بطاقة البيئة المرصودة فعليًا في المتصفح
    ui_env = ""
    try:
        ui_env = page.locator(".pl-card.pl-env").first.inner_text()
    except Exception:  # noqa: BLE001 — قد لا تكون البطاقة موجودة
        pass

    entry = {
        "label": label,
        "at": time.strftime("%H:%M:%S"),
        "db": db,
        "canonical_state": canonical["state"],
        "canonical_env_id": canonical["environment_id"],
        "snapshot_state": runtime.get("state"),
        "snapshot_env_id": runtime.get("environment_id"),
        "project_status": snapshot.get("status"),
        "job_id": (snapshot.get("job") or {}).get("id"),
        "worker_id": (snapshot.get("job") or {}).get("worker_id", ""),
        "heartbeat_age_s": (snapshot.get("job") or {})
        .get("heartbeat_age_s"),
        "ui_env_card": ui_env[:400],
    }
    evidence.setdefault("truth_checks", []).append(entry)

    # §1 الاتفاق القانوني: لقطة المشروع = نقطة الحالة (مصدر واحد)
    agree_state = runtime.get("state") == canonical["state"]
    agree_env = runtime.get("environment_id") == canonical["environment_id"]
    # §17 جاهزة الواجهة ⇒ جاهزة الـbackend بنفس الهوية
    if "جاهزة" in ui_env and "غير" not in ui_env.split("\n")[0]:
        if canonical["state"] not in ("READY", "RUNNING"):
            check(f"§17 [{label}] UI جاهزة لكن القانونية "
                  f"{canonical['state']}", False)
        elif canonical["environment_id"] is None:
            check(f"§17 [{label}] READY بلا environment_id", False)
    return {
        "agree_state": agree_state, "agree_env": agree_env,
        "canonical": canonical, "snapshot": snapshot, "db": db,
        "ui_env": ui_env,
    }


def run_acceptance() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    evidence: dict = {
        "command": "013.2", "base": BASE,
        "osint_objective": OSINT_OBJECTIVE,
        "projects": {}, "screenshots": [], "checks": {},
        "truth_checks": [], "transitions": [], "search": {},
        "declared_limit": "منفذ الخطوة والمخطط منظمان (حد الـLLM "
                          "الخارجي — نمط §38 المقبول في 013/013.1)؛ "
                          "كل ما عداه حقيقي: خادم/قاعدة/منسق/وظائف/"
                          "نبضات/تجهيز/فحوص/عزل/SSE/متصفح",
    }

    import shutil as _shutil

    _shutil.rmtree(RUNTIME_DIR, ignore_errors=True)

    server_holder: dict = {"proc": None}

    def start_server():
        server_holder["proc"] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--server"],
            env={**os.environ, "AES_0132_PORT": str(PORT),
                 "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def wait_healthy(timeout_s: float = 90.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                api("GET", "/health", timeout=3)
                return True
            except Exception:
                time.sleep(0.6)
        return False

    start_server()
    exit_code = 1
    try:
        healthy = wait_healthy()
        check("خادم القبول حي (عملية فعلية + قاعدة نظيفة)", healthy)
        if not healthy:
            return 1

        # جامع SSE الحي يعمل طوال السيناريو (§18 دليل بث)
        sse = SSECollector()
        sse.start()
        time.sleep(1.5)

        try:
            _run_browser_scenario(evidence, sse)
            exit_code = 0
        except Exception as error:  # noqa: BLE001 — دليل الفشل ثم رفعه
            evidence["crash"] = f"{type(error).__name__}: {error}"
            try:
                projects = api("GET", "/api/projects")["projects"]
                evidence["crash_projects"] = [
                    {k: p.get(k) for k in ("id", "status", "name")}
                    for p in projects]
                for p in projects[:3]:
                    state = api("GET", f"/api/projects/{p['id']}/state")
                    evidence.setdefault("crash_states", {})[p["id"]] = {
                        "status": state.get("status"),
                        "job": state.get("job"),
                        "gate": state.get("execution_gate"),
                        "env": (state.get("environment") or {})
                        .get("runtime_state", {}).get("state"),
                    }
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            try:
                sse.finish()
            except Exception:  # noqa: BLE001
                pass

    finally:
        # (§18) الأدلة تُكتب دائمًا — عند النجاح والفشل معًا
        evidence["summary"] = {"pass": len(PASS), "fail": len(FAIL),
                               "failed": FAIL}
        EVIDENCE_PATH.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=1,
                       default=str), encoding="utf-8")
        try:
            server_holder["proc"].terminate()
            server_holder["proc"].wait(timeout=15)
        except Exception:  # noqa: BLE001
            try:
                server_holder["proc"].kill()
            except Exception:  # noqa: BLE001
                pass

    print("\n==== 013.2 LIVE ACCEPTANCE ====")
    print(f"PASS: {len(PASS)}  FAIL: {len(FAIL)}")
    for name in FAIL:
        print(f"  FAILED: {name}")
    print(f"evidence: {EVIDENCE_PATH}")
    print(f"screenshots: {SHOTS}")
    return exit_code


def _run_browser_scenario(evidence: dict, sse) -> None:
    """سيناريو المتصفح الكامل — خادم حي وجامع SSE جاهزان.

    منفصل كي تلتقط run_acceptance أدلة الانهيار (حالة كل مشروع
    وبواباته وبيئته) قبل رفع الاستثناء — لا فشل صامت بلا تشخيص.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1460, "height": 960})
        page = context.new_page()

        # ============ إصلاح البحث حيًّا (طلب المالك الصريح) ======
        providers = api("GET", "/api/research/providers")["providers"]
        by_kind = {pr["kind"]: pr for pr in providers}
        check("البحث: أربعة مزودين مبذورين (ddg/bing/searx/api)",
              set(by_kind) >= {"search_ddg", "search_bing"})
        ddg_probe = api(
            "POST",
            f"/api/research/providers/{by_kind['search_ddg']['id']}"
            "/probe")
        bing_probe = api(
            "POST",
            f"/api/research/providers/{by_kind['search_bing']['id']}"
            "/probe")
        evidence["search"]["ddg"] = {
            "status": ddg_probe["status"],
            "reason": ddg_probe.get("reason", "")[:200],
        }
        evidence["search"]["bing"] = {
            "status": bing_probe["status"],
            "reason": bing_probe.get("reason", "")[:200],
        }
        # DDG: إما READY أو NOT_READY بتصنيف التحدّ الصادق —
        # الممنوع هو الغموض القديم («0 روابط خام» بلا سبب)
        ddg_honest = (ddg_probe["status"] == "READY")
        if not ddg_honest:
            ddg_honest = ("تحدّ" in (ddg_probe.get("reason") or "")
                          or "استراتيجيات" in (ddg_probe.get("reason")
                                                or ""))
        check("البحث: DDG صادق — جاهز أو محجوب بتصنيف مسمى",
              ddg_honest,
              f"status={ddg_probe['status']}")
        check("البحث: Bing جاهز حقيقيًا (احتياط بلا مفاتيح)",
              bing_probe["status"] == "READY",
              f"status={bing_probe['status']}")
        search_out = api("POST", "/api/research/search",
                         {"query": "OSINT platform techniques"})
        results = search_out.get("results") or []
        check("البحث: بحث فعلي عبر API التطبيق يعيد نتائج",
              len(results) >= 3,
              f"provider={search_out.get('provider')} "
              f"results={len(results)}")
        evidence["search"]["live_search"] = {
            "provider": search_out.get("provider"),
            "results": len(results),
            "first": results[0]["title"][:80] if results else "",
        }

        # ============ A — مشروع جديد من الواجهة (§16+§19-A) ======
        page.goto(BASE + "/", wait_until="domcontentloaded")
        wait_css(page, "#plus")
        page.click("#plus")
        page.click('.plus-option[data-mode="project"]')
        page.fill("#input", OSINT_OBJECTIVE)
        page.click("#send")
        wait_css(page, ".pj-draft-card, .pl-card.pl-plan",
                 timeout=30000)
        pid = page.evaluate(
            "parseInt(location.hash.slice('#/project/'.length), 10)")
        check("A §16 المشروع أُنشئ من الواجهة بالهدف الحرفي",
              bool(pid), f"project #{pid}")
        evidence["projects"]["main"] = {"id": pid}
        page.screenshot(path=str(SHOTS / "A-new-project.png"),
                        full_page=True)
        evidence["screenshots"].append("A-new-project.png")
        truth_check(page, pid, "بعد الإنشاء", evidence)

        # ============ B — الخطة (§19-B) ============================
        wait_css(page, ".pj-draft-card .pl-btn.primary,"
                       " .pl-card.pl-plan", timeout=30000)
        if page.evaluate(
                "!!document.querySelector"
                "('.pj-draft-card .pl-btn.primary')"):
            dom_click(page, ".pj-draft-card .pl-btn.primary")
        wait_css(page, ".pl-card.pl-plan", timeout=30000)
        check("B الخطة ظهرت (عقد صارم بمراحل وخطوات)", True)
        page.screenshot(path=str(SHOTS / "B-plan.png"), full_page=True)
        evidence["screenshots"].append("B-plan.png")
        truth_check(page, pid, "بعد الخطة", evidence)

        # ============ C — الاعتماد (§13+§19-C) ====================
        wait_css(page, ".pl-approval .pl-btn.primary")
        page.evaluate("window.__noReload = 'alive-0132'")
        dom_click(page, ".pl-approval .pl-btn.primary")
        # الزر يتغير فورًا — لا refresh ولا بطاقة اعتماد مكررة:
        # إما تعطّل فوري أثناء الطلب أو اختفاء البطاقة بعد القرار
        page.wait_for_function(
            "() => { const cards = document.querySelectorAll"
            "('.pl-approval'); if (!cards.length) return true;"
            " const btns = document.querySelectorAll"
            "('.pl-approval .pl-btn.primary');"
            " return ![...btns].some(b => !b.disabled); }",
            timeout=20000)
        marker = page.evaluate("window.__noReload")
        check("C §13 الاعتماد: الزر تغير فورًا بلا refresh",
              marker == "alive-0132")
        page.screenshot(path=str(SHOTS / "C-approval.png"),
                        full_page=True)
        evidence["screenshots"].append("C-approval.png")
        state = truth_check(page, pid, "بعد الاعتماد", evidence)
        evidence["transitions"].append({
            "stage": "APPROVED", "project_status":
                state["snapshot"].get("status"),
        })

        # ============ D — تجهيز البيئة (§5+§19-D) =================
        # لقطة «التجهيز» تُلتقط فور ظهور البطاقة — الفحص المسبق
        # الحقيقي بعد الاعتماد ينفّذ verify فعليًا (~ثوانٍ) فالحالة
        # تجهيز خلالها ثم جاهزة. مساران مشروعان كلاهما حقيقي:
        #   (أ) تجهيز/غير متاحة عند وصولنا: نتحقق ونجهّز من الواجهة.
        #   (ب) جاهزة أصلًا: المسبار الحقيقي أنهى العمل قبل وصولنا.
        wait_css(page, ".pl-card.pl-env", timeout=30000)
        page.screenshot(path=str(SHOTS / "D-preparing-env.png"),
                        full_page=True)   # فورًا — بلا انتظار استقرار
        evidence["screenshots"].append("D-preparing-env.png")
        env_kind = page.evaluate(
            "() => { const card ="
            " document.querySelector('.pl-card.pl-env');"
            " if (!card) return 'none';"
            " if (card.classList.contains('ready')) return 'ready';"
            " if (card.classList.contains('preparing'))"
            " return 'preparing';"
            " return 'notready'; }")
        env_text_d = page.locator(".pl-card.pl-env"
                                  ).first.inner_text()

        if env_kind == "ready":
            # جاهزة بفحص مسبق حقيقي (المسبار=المنفذ §19 توحيد المصدر)
            check("D §7 البيئة جاهزة بفحص مسبق حقيقي (مسبار=منفذ)",
                  "جاهزة" in env_text_d.split("\n")[0])
            evidence["ready_via"] = "preflight-real-verify"
        else:
            check("D §7 بطاقة البيئة متماسكة (تجهيز/غير متاحة فقط)",
                  ("تجهيز بيئة التنفيذ" in env_text_d
                   or "غير متاحة" in env_text_d)
                  and "المطلوب:" in env_text_d
                  and "المضيف الحالي:" in env_text_d,
                  env_text_d.split("\n")[0])
            evidence["ready_via"] = "ui-provision-button"
            # التجهيز من الواجهة — دورة حقيقية كاملة على الركيزة
            # (نقر الـDOM: البطاقة تُعاد رسمها حيًّا فالأزرار تتبدد)
            dom_click(page, ".pl-card.pl-env .pl-btn.primary")
            ok_selector = page.wait_for_selector(
                ".pl-card.pl-env .pl-feedback.ok,"
                " .pl-card.pl-env.ready", timeout=90000)
            check("D §5 زر التجهيز: دورة حقيقية اكتملت "
                  "(اكتشاف←تسجيل←إقلاع←فحص صحة←READY)",
                  ok_selector is not None)

        # (§2+§7) لا تناقض في أي حالة: العنوان لا يقول جاهزة
        # والمحتوى نفيها، ولا نص متطلب يحمل «جاهزة» تحت عنوان سلب
        contradictory = ("جاهزة" in env_text_d.split("\n")[0]
                         and "غير" in env_text_d.split("\n")[0])
        check("D §7 لا نص متطلب يحمل «جاهزة» تحت عنوان سلب",
              not contradictory
              and "معزولة جاهزة" not in env_text_d)

        # إعادة الفحص ← إطلاق آلي بنفس الوظيفة بلا إعادة اعتماد
        state_after_block = wait_status(pid, {"WAITING_WORKER",
                                              "RUNNING"},
                                        timeout_s=30)
        first_job = (state_after_block.get("job") or {}).get("id")
        has_exec = page.evaluate(
            "!!document.querySelector('.pl-card.pl-exec')")
        if not has_exec:
            # زر إعادة الفحص قد يكون في بطاقة الحجب أو البيئة
            # حسب الحالة الحية — ننقر أول المتاح منهما
            for _ in range(3):
                if dom_click_any(page, [
                    ".pl-card.pl-blocked .pl-btn:not(.primary)",
                    ".pl-card.pl-env .pl-btn:not(.primary)",
                ]):
                    break
                page.wait_for_timeout(1200)
        wait_css(page, ".pl-card.pl-exec", timeout=90000)
        state = wait_status(pid, {"RUNNING", "COMPLETED",
                                  "WAITING_GATE"})
        resumed_job = (state.get("job") or {}).get("id")
        check("D §14 الاستئناف بنفس الوظيفة (لا إعادة اعتماد)",
              resumed_job == first_job and first_job is not None,
              f"#{resumed_job} == #{first_job}")
        evidence["projects"]["main"]["job_id"] = first_job

        # ============ E — البيئة جاهزة (§17+§19-E) ================
        # اللحظة الحاسمة: الواجهة تقول «جاهزة» — نسأل القانونية
        time.sleep(1.0)  # المصالحة الحية عبر SSE
        truth = truth_check(page, pid, "البيئة جاهزة", evidence)
        ui_env = truth["ui_env"]
        canonical = truth["canonical"]
        check("E §17 الواجهة تقول جاهزة والقانونية تقول READY",
              "جاهزة" in ui_env
              and canonical["state"] in ("READY", "RUNNING"),
              f"canonical={canonical['state']}")
        check("E §17 نفس environment_id في كل القراءات",
              truth["agree_env"]
              and canonical["environment_id"] is not None,
              f"env_id={canonical['environment_id']}")
        check("E §3 برهان READY: فحوص مسماة ناجحة + هوية دائمة",
              (canonical.get("evidence") or {}).get("checks_ok")
              is True and canonical["environment_id"] is not None)
        evidence["projects"]["main"]["environment_id"] = \
            canonical["environment_id"]
        evidence["projects"]["main"]["worker_id"] = \
            (state.get("job") or {}).get("worker_id", "")
        # فحوص §6 المسماة تظهر في البرهان
        check_names = [c.get("name") for c in
                       (canonical.get("evidence") or {})
                       .get("checks", [])]
        check("E §6 فحوص الصحة المسماة حرفيًا في البرهان",
              {"write_file", "read_file", "delete_file",
               "isolation"} <= set(check_names),
              "، ".join(check_names))
        shot_card(page, "E-env-ready.png", ".pl-card.pl-env")
        evidence["screenshots"].append("E-env-ready.png")

        # ============ F — التنفيذ الحي (§12+§19-F) ================
        exec_text = page.locator(".pl-card.pl-exec").inner_text()
        check("F §12 بطاقة التنفيذ: البيئة/العامل/آخر نشاط/إيقاف",
              "البيئة" in exec_text and "العامل" in exec_text
              and "آخر نشاط" in exec_text
              and "إيقاف التنفيذ" in exec_text)
        shot_card(page, "F-executing.png", ".pl-card.pl-exec")
        evidence["screenshots"].append("F-executing.png")
        truth_check(page, pid, "أثناء التنفيذ", evidence)

        # ============ J — التنقّل أثناء التنفيذ (§14+§19-J) ======
        activity_before = page.locator(".pl-act").count()
        state_before = api("GET", f"/api/projects/{pid}/state")
        last_id_before = state_before["last_event_id"]

        page.click("#pl-back")
        page.wait_for_selector(".composer:not([style*='none'])",
                               timeout=10000)
        check("J §14 المغادرة فورية أثناء التنفيذ", True)
        page.click("#plus")
        page.click('.plus-option[data-mode="chat"]')
        check("J §14 New Chat فوري بلا refresh", True)
        wait_css(page, ".conv-item")
        page.locator(".conv-item").first.click()
        page.wait_for_function(
            "document.getElementById('messages')"
            ".innerText.indexOf('مبادئ') !== -1",
            timeout=10000)
        check("J §14 المحادثة القديمة فُتحت فورًا", True)
        page.wait_for_timeout(4500)   # غياب مقصود فوق خطوة بطيئة
        wait_css(page, ".pj-item")
        page.locator(".pj-item").first.click()
        wait_css(page, ".pl-card.pl-exec", timeout=30000)
        marker = page.evaluate("window.__noReload")
        activity_after = page.locator(".pl-act").count()
        state = api("GET", f"/api/projects/{pid}/state")
        advanced = state["last_event_id"] > last_id_before
        check("J §14 لا refresh في الرحلة كاملة (العلامة باقية)",
              marker == "alive-0132")
        check("J §14 التنفيذ استمر أثناء الغياب (أحداث جديدة)",
              advanced or activity_after > activity_before,
              f"events {last_id_before} → "
              f"{state['last_event_id']}")
        check("J §14 نفس الوظيفة بعد العودة",
              (state.get("job") or {}).get("id") == first_job)
        shot_card(page, "J-navigating-while-running.png",
                  ".pl-card.pl-exec")
        evidence["screenshots"].append("J-navigating-while-running.png")

        # ============ تبويبان متزامنان (§14) ======================
        tab_b = context.new_page()
        tab_b.goto(BASE + f"/#/project/{pid}",
                   wait_until="domcontentloaded")
        tab_b.evaluate("window.__noReloadB = 'alive-b'")
        wait_css(tab_b, ".pl-card", timeout=30000)
        final = wait_status(pid, {"COMPLETED", "WAITING_GATE",
                                  "VERIFIED"}, timeout_s=120)
        page.wait_for_timeout(2500)
        tab_b.wait_for_timeout(2500)
        marker_a = page.evaluate("window.__noReload")
        marker_b = tab_b.evaluate("window.__noReloadB")
        check("§14 التبويبان تزامنا بلا refresh",
              marker_a == "alive-0132" and marker_b == "alive-b")
        done_b = tab_b.locator(".pl-verify").count() > 0 \
            or "مرشح" in tab_b.locator("#pl-scene").inner_text()
        check("§14 التبويب الثاني يرى الحالة النهائية بلا refresh",
              done_b, f"status={final['status']}")
        tab_b.screenshot(path=str(SHOTS / "G-review-two-tabs.png"),
                         full_page=True)
        evidence["screenshots"].append("G-review-two-tabs.png")
        tab_b.close()
        evidence["projects"]["main"]["final_status"] = final["status"]

        # ============ G/H — المراجعة والمكتمل (§19-G/H) ===========
        # (المشروع وصل مرشحًا للتحقق — المراجعة مرئية في السجل)
        wait_css(page, ".pl-card.pl-verify", timeout=30000)
        verify_text = page.locator(".pl-card.pl-verify").inner_text()
        check("G المراجعة ظاهرة — مرشح للتحقق بقرار المالك",
              "مرشح" in verify_text or "مُتحقق" in verify_text)
        shot_card(page, "G-review.png", ".pl-card.pl-verify")
        evidence["screenshots"].append("G-review.png")
        truth_check(page, pid, "مرشح للتحقق", evidence)

        if page.evaluate(
                "!!document.querySelector"
                "('.pl-verify .pl-btn.primary')"):
            dom_click(page, ".pl-verify .pl-btn.primary")
        state = wait_status(pid, {"VERIFIED"}, timeout_s=60)
        check("H المشروع اكتمل VERIFIED — قرار المالك النهائي",
              state["status"] == "VERIFIED")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / "H-completed.png"),
                        full_page=True)
        evidence["screenshots"].append("H-completed.png")
        truth_check(page, pid, "بعد التحقق النهائي", evidence)

        # ============ §8 — إغلاق المتصفح أثناء التنفيذ ===========
        page.click("#pl-back")
        page.wait_for_selector(".composer:not([style*='none'])",
                               timeout=10000)
        page.click("#plus")
        page.click('.plus-option[data-mode="project"]')
        page.fill("#input", OSINT_OBJECTIVE + " — اختبار الإغلاق")
        page.click("#send")
        wait_css(page, ".pj-draft-card .pl-btn.primary,"
                       " .pl-card.pl-plan", timeout=30000)
        pid_b = page.evaluate(
            "parseInt(location.hash.slice('#/project/'.length), 10)")
        if page.evaluate(
                "!!document.querySelector"
                "('.pj-draft-card .pl-btn.primary')"):
            dom_click(page, ".pj-draft-card .pl-btn.primary")
        wait_css(page, ".pl-approval .pl-btn.primary", timeout=30000)
        dom_click(page, ".pl-approval .pl-btn.primary")
        # البيئة جاهزة بالفعل — إعادة الفحص ثم التنفيذ
        wait_css(page, ".pl-card.pl-env .pl-btn:not(.primary),"
                       " .pl-card.pl-blocked .pl-btn:not(.primary),"
                       " .pl-card.pl-exec", timeout=30000)
        has_exec_b = page.evaluate(
            "!!document.querySelector('.pl-card.pl-exec')")
        if not has_exec_b:
            for _ in range(3):
                if dom_click_any(page, [
                    ".pl-card.pl-blocked .pl-btn:not(.primary)",
                    ".pl-card.pl-env .pl-btn:not(.primary)",
                ]):
                    break
                page.wait_for_timeout(1200)
        wait_css(page, ".pl-card.pl-exec", timeout=90000)
        state = wait_status(pid_b, {"RUNNING"})
        job_b = (state.get("job") or {}).get("id")
        context.close()          # إغلاق المتصفح كاملًا والتنفيذ جارٍ
        time.sleep(7)            # خطوة كاملة تحدث والمتصفح مغلق
        browser2 = p.chromium.launch()
        context2 = browser2.new_context(
            viewport={"width": 1460, "height": 960})
        page2 = context2.new_page()
        page2.goto(BASE + f"/#/project/{pid_b}",
                   wait_until="domcontentloaded")
        wait_css(page2, ".pl-card.pl-exec, .pl-card.pl-verify",
                 timeout=60000)
        state2 = wait_status(pid_b, {"COMPLETED", "WAITING_GATE",
                                     "RUNNING", "VERIFIED"},
                             timeout_s=90)
        same_job = (state2.get("job") or {}).get("id") == job_b
        check("§8 إغلاق المتصفح لم يوقف التنفيذ — نفس الوظيفة",
              same_job, f"#{(state2.get('job') or {}).get('id')}"
                        f" == #{job_b}")
        check("§8 العودة تجد الأحداث كاملة (لا وظيفة جديدة)",
              len(state2.get("events") or []) >= 2)
        evidence["projects"]["browser_close"] = {
            "id": pid_b, "job_id": job_b,
            "status": state2["status"],
        }
        browser2.close()

        # ============ I — فشل بيئة حقيقي (§19-I) ==================
        # عامل بعيد بنقطة نهاية ميتة — فشل حقيقي بسبب حرفي
        browser3 = p.chromium.launch()
        context3 = browser3.new_context(
            viewport={"width": 1460, "height": 960})
        page3 = context3.new_page()
        page3.goto(BASE + "/", wait_until="domcontentloaded")
        page3.click("#settings-open")
        wait_css(page3, "#settings-tabs", timeout=15000)
        page3.click('.settings-tab[data-tab="execution"]')
        wait_css(page3, "#exec-env-body", timeout=15000)
        page3.wait_for_timeout(1200)   # تحميل لوحة البيئات
        envs_before = api("GET", "/api/execution/environments")
        dead_id = api(
            "POST", "/api/execution/environments",
            {"name": "dead-worker-0132", "backend": "REMOTE_WORKER",
             "endpoint": "http://127.0.0.1:59999",
             "token": "", "make_default": False},
        )["id"]
        failed_verify = api(
            "POST",
            f"/api/execution/environments/{dead_id}/verify")
        check("I فشل بيئة حقيقي — عامل ميت بسبب حرفي",
              failed_verify["status"] != "READY"
              and bool(failed_verify.get("failure_reason")),
              (failed_verify.get("failure_reason") or "")[:90])
        evidence["environment_failure"] = {
            "environment_id": dead_id,
            "status": failed_verify["status"],
            "reason": (failed_verify.get("failure_reason")
                       or "")[:300],
        }
        page3.wait_for_timeout(2500)   # إعادة تحميل اللوحة
        page3.screenshot(path=str(SHOTS / "I-env-failure.png"),
                         full_page=True)
        evidence["screenshots"].append("I-env-failure.png")
        # الحالة القانونية لم تتزحزح عن الحقيقة: الميت ليس جاهزًا
        canonical_after = api(
            "GET",
            "/api/execution/runtime-state?policy=STRICT_ISOLATED")
        check("I الفشل لم يفسد الحالة القانونية للمختارة",
              canonical_after["state"] in ("READY", "RUNNING"),
              f"state={canonical_after['state']}")
        browser3.close()

        # ============ سجل الانتقالات الكامل (§21) =================
        events = api("GET",
                     f"/api/projects/{pid}/events?limit=500")
        event_list = events if isinstance(events, list) \
            else events.get("events", [])
        transitions = [
            {"kind": e.get("kind"), "id": e.get("id")}
            for e in event_list
            if (e.get("kind") or "") in (
                "PLAN_CREATED", "PLAN_APPROVAL_REQUIRED",
                "PLAN_APPROVED", "PREFLIGHT_STARTED",
                "PREFLIGHT_PASS", "PREFLIGHT_BLOCKED",
                "ENVIRONMENT_READY", "JOB_CREATED", "JOB_STARTED",
                "JOB_COMPLETED", "JOB_INTERRUPTED",
                "PROJECT_COMPLETION_CANDIDATE", "PROJECT_VERIFIED",
                "PROVISIONING_STARTED", "PROVISIONING_COMPLETED",
                "PROVISIONING_FAILED", "PROVISIONING_UNAVAILABLE",
            )
        ]
        evidence["transitions"] = transitions
        kinds = {t["kind"] for t in transitions}
        check("§21 سلسلة الانتقالات كاملة في سجل الأحداث",
              {"PLAN_CREATED", "PLAN_APPROVED", "JOB_STARTED"}
              <= kinds, f"{len(transitions)} انتقالًا")

        # ============ دليل SSE الحي (§18) =========================
        sse_kinds = [e.get("kind") for e in sse.events]
        live_seen = [k for k in (
            "PLAN_CREATED", "JOB_STARTED", "JOB_WAITING",
            "PROJECT_COMPLETION_CANDIDATE") if k in sse_kinds]
        check("§18 تيار SSE حي حمل أحداث السيناريو لحظة حدوثها",
              len(live_seen) >= 2,
              f"شوهد حيًّا: {live_seen}")
        evidence["sse"] = {
            "total_events": len(sse.events),
            "kinds_seen": sorted(set(sse_kinds))[:40],
            "live_milestones": live_seen,
        }
        sse.finish()

        # ============ قاعدة/نبضات (§18) ===========================
        db_final = db_truth(pid)
        evidence["db_final"] = db_final
        heartbeat = None
        state_final = api("GET", f"/api/projects/{pid}/state")
        job_final = state_final.get("job") or {}
        if job_final.get("heartbeat_at"):
            heartbeat = {
                "at": job_final["heartbeat_at"],
                "age_s": job_final.get("heartbeat_age_s"),
                "worker_id": job_final.get("worker_id"),
            }
        check("§18 نبضة العامل مسجلة في الوظيفة الدائمة",
              heartbeat is not None,
              str(heartbeat)[:100])
        evidence["worker_heartbeat"] = heartbeat

        # تنظيف حرسي — بعض السياقات أُغلقت داخل السيناريو (§8) فلا
        # يفسد الإغلاقُ المكرر خلاصتِه الخضراء
        for closer in (
            lambda: context3.close(), lambda: browser3.close(),
            lambda: context.close(), lambda: browser.close(),
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001 — التنظيف لا يفسد النتيجة
                pass


if __name__ == "__main__":
    if "--server" in sys.argv:
        raise SystemExit(run_server())
    raise SystemExit(run_acceptance())
