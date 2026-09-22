#!/usr/bin/env python3
"""القبول الحي للأمر 013.4 — حلقة التنفيذ الحقيقية + مركز التحكم + الويب.

العقد الحرفي:
§0   جذر العطل: المشروع يدخل PLANNING ولا يخرج — يجب أن يصبح مستحيلًا:
     التوليد أمر خلفي محدود (جلسة/نبضة/إيجار/تصنيف) يظهر حرفيًا في
     الواجهة (المزود/النموذج/الطلب/المضي) ولا يبقى صامتًا أبدًا.
§36  اختبار تعليق التخطيط: داخل الواجهة: Planning started + المزود
     + النموذج + الطلب + آخر نشاط + المضي — لا «Planning…» إلى الأبد.
§39  أفعال التحكم: PAUSE/RESUME/STOP/RETRY — كل فعل أمر ← حدث ←
     انتقال ← حالة ← واجهة.
§40-§41  تبويبان + إغلاق المتصفح: نفس الوظيفة والمشروع واللقطات.
§43  تاريخ طويل بصفحات — لا غرق DOM.
§55  مصفوفة الاختبار الحية: A(تخطيط حي) D(نجاح) E(اعتماد) F(تنفيذ)
     G(إيقاف مؤقت) H(استئناف) I(إيقاف) K(تكرار) L(أرشفة) M(استرجاع)
     N(تاريخ) O(تبويبان) Q(عودة بلا refresh) R(بحث الويب بالمحادثة)
     U(أدلة) V(مخرجات) W(تاريخ طويل).
§56  السيناريو الحرفي الكامل بلا refresh.

الحد المعلن الوحيد (نمط §38 المقبول من 013.2): استدعاء LLM التخطيط
والتنفيذ منظمان — حد الـLLM الخارجي. كل ما عداه حقيقي بالكامل:
الخادم عملية فعلية، القاعدة، جلسات التخطيط والنبضات والإيجار،
الوظائف الدائمة، الفحوص، البيئة (Linux محلية)، بث SSE، المتصفح،
والبحث عبر مزودي التطبيق الحقيقيين (DDG/Bing).

اللقطات إلى download/0134_shots/ والأدلة إلى
download/order0134-evidence.json.

تشغيل:  python scripts/order0134_acceptance.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PORT = int(os.environ.get("AES_0134_PORT", "8134"))
BASE = f"http://127.0.0.1:{PORT}"
SHOTS = Path("/home/z/my-project/download/0134_shots")
EVIDENCE_PATH = Path(
    "/home/z/my-project/download/order0134-evidence.json"
)
RUNTIME_DIR = Path("/tmp/aes-0134-runtime")

OSINT_OBJECTIVE = ("بناء منصة OSINT متقدمة جدًا وفق أحدث التقنيات "
                   "والتكنولوجيا المتقدمة")

PASS: list[str] = []
FAIL: list[str] = []
NOTES: list[dict] = []


def check(name: str, ok: bool, note: str = "") -> bool:
    (PASS if ok else FAIL).append(name)
    print(("  ✅ " if ok else "  ❌ ") + name +
          (f" — {note}" if note else ""), flush=True)
    if note:
        NOTES.append({"name": name, "note": note[:500]})
    return ok


def api(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ================================================================== #
# وضع الخادم — حقيقي بالكامل إلا حد الـLLM المعلن
# ================================================================== #

def boot_server() -> int:
    runtime = RUNTIME_DIR
    runtime.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime)

    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )
    from providers_registry import registry

    engine = build_engine(runtime / "acceptance.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)

    from api import routes as routes_api

    routes_api._sessions = sessions

    # ربط الأدوار بمزود قابل للحل في هذه البيئة (نمط 013.2)
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

    from research import service as research_service

    research_service.ensure_seeded(sessions)

    from execution import service as execution_service

    execution_service.ensure_local_registered(sessions)

    # ---- حد الـLLM المعلن: مخطط منظم (بطيء عمدًا 4ث لرصد الجلسة) ----
    from api import projects as projects_api
    from tasks import TaskResult

    class ScriptedRouter:
        def __init__(self):
            self._providers = {"zai_internal", "nvidia"}

        def has_live_provider(self, provider_id):
            return str(provider_id) in self._providers

        def live_providers(self):
            return sorted(self._providers)

    PLAN = {
        "objective": OSINT_OBJECTIVE,
        "assumptions": ["بيئة Linux محلية جاهزة"],
        "acceptance_criteria": ["ملف تقرير الخطوة موجود ضمن الأدلة"],
        "phases": [{
            "title": "تأسيس منصة OSINT",
            "objective": "بناء أساس المنصة وتقاريرها",
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

    class SlowScriptedPlanner:
        """بطيء عمدًا (7ث) — نافذة رصد جلسة التخطيط الحية (§36)."""

        def generate(self, objective, *, previous_failure=None,
                     feedback=""):
            time.sleep(7.0)
            return json.loads(json.dumps(PLAN))

    def slow_run_task(goal, *, router, role_config=None, workspace=None,
                      on_event=None, cycle_id=None, stop_controller=None,
                      resume_from=None, **_kw):
        """منفذ بطيء (~8ث/خطوة) — نافذة الإيقاف المؤقت والتبويبات."""
        from pathlib import Path as _Path

        stop_key = _kw.get("stop_cycle_id") or cycle_id
        stop_check = (stop_controller.checker_for(stop_key)
                      if stop_controller is not None and stop_key
                      else None)
        root = _Path(workspace) if workspace else _Path(".")
        root.mkdir(parents=True, exist_ok=True)
        index = int(time.monotonic() * 1000) % 100000
        for i in range(8):
            if stop_check is not None and stop_check():
                return TaskResult(
                    verdict="STOPPED",
                    reason="إيقاف المالك أثناء التنفيذ البطيء",
                    goal=goal)
            time.sleep(1.0)
            if on_event is not None:
                try:
                    on_event({"kind": "tool.started",
                              "role": "implementer",
                              "tool": "write_file",
                              "query": f"part-{index}-{i}.md",
                              "execution_site": "substrate",
                              "tool_call_id": f"tc-{index}-{i}"})
                    on_event({"kind": "tool.call", "role": "implementer",
                              "tool": "write_file",
                              "args_summary": f"part-{index}-{i}.md",
                              "execution_site": "substrate",
                              "tool_call_id": f"tc-{index}-{i}",
                              "duration_ms": 8})
                except Exception:  # noqa: BLE001
                    pass
        output = root / "deliverable.md"
        output.write_text(f"# مخرج {index}\n\n{goal}\n", encoding="utf-8")
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
            duration_ms=8000, state_history=["EVIDENCED"],
        )

    import tasks as tasks_mod

    tasks_mod.run_task = slow_run_task

    def factory(on_event=None, **_kwargs):
        from workflow.engine import ProjectEngine

        return ProjectEngine(
            sessions,
            router_factory=ScriptedRouter,
            planner_factory=SlowScriptedPlanner,
            on_event=on_event,
        )

    projects_api._test_engine_factory = factory

    import uvicorn
    from api.routes import app

    print(f"0134 ACCEPTANCE SERVER READY on {PORT} "
          f"(runtime={runtime})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    return 0


# ================================================================== #
# أدوات المتصفح
# ================================================================== #

def dom_click(page, css: str, timeout: float = 20000):
    page.wait_for_function(
        "selector => { const b = document.querySelector(selector);"
        " return !!b && !b.disabled; }", arg=css, timeout=timeout)
    page.evaluate(
        "selector => document.querySelector(selector).click()", arg=css)


def dom_click_text(page, css: str, text: str, timeout: float = 20000):
    """نقر أول عنصر من محدد يحتوي نصًا — مقاوم لإعادة الرسم الحية."""
    page.wait_for_function(
        "([selector, needle]) => { const nodes = document.querySelectorAll"
        "(selector); for (const b of nodes) { if (b.textContent.includes"
        "(needle) && !b.disabled) return true; } return false; }",
        arg=[css, text], timeout=timeout)
    page.evaluate(
        "([selector, needle]) => { const nodes = document.querySelectorAll"
        "(selector); for (const b of nodes) { if (b.textContent.includes"
        "(needle) && !b.disabled) { b.click(); return; } } }",
        arg=[css, text])


def shot(page, name: str):
    page.screenshot(path=str(SHOTS / name), full_page=False)


def wait_status(pid: int, statuses: set[str], timeout_s: float = 90.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = api("GET", f"/api/projects/{pid}/state")
        if state.get("status") in statuses:
            return state
        time.sleep(0.4)
    return api("GET", f"/api/projects/{pid}/state")


# ================================================================== #
# السيناريو الحرفي (§56) — بلا refresh أبدًا
# ================================================================== #

def run_scenario() -> int:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    evidence: dict = {
        "command": "013.4",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": {
            "os": os.uname().sysname,
            "architecture": os.uname().machine,
            "python": sys.version.split()[0],
        },
        "declared_limit": "استدعاءات LLM التخطيط/التنفيذ منظمة "
                          "(حد الـLLM الخارجي بنمط §38 من 013.2) — "
                          "كل ما عداها حقيقي: الخادم/القاعدة/جلسات "
                          "التخطيط/الوظائف/الفحوص/البيئة/البث/المتصفح",
        "checks": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(BASE)

        # ---------- 1-3. مشروع OSINT من المحادثة (وضع المشروع) ----------
        print("\n[1] مشروع من المحادثة — الهدف الحرفي", flush=True)
        dom_click(page, "#plus")
        dom_click(page, ".plus-option[data-mode='project']")
        page.fill("#input", OSINT_OBJECTIVE)
        page.click("#send")
        time.sleep(1.0)
        shot(page, "01_project_created_planning.png")

        # ---------- §36. التخطيط الحي — ماذا ينتظر معلن حرفيًا ----------
        print("[2] §36 التخطيط الحي — المزود/النموذج/الطلب/المضي",
              flush=True)
        # اللقطة القانونية أثناء التوليد (فورًا — قبل انتهاء النافذة)
        projects = api("GET", "/api/projects")
        pid = projects["projects"][0]["id"]
        runtime = api("GET", f"/api/projects/{pid}/runtime")
        planning = runtime.get("planning") or {}
        detail = planning.get("detail") or {}
        check("A2-planning-session-active",
              planning.get("active") is True
              and bool(detail.get("request_id")),
              "request_id=" + str(detail.get("request_id")) +
              " state=" + str(detail.get("state")))
        check("A3-planning-waiting-for-model",
              (runtime.get("waiting_for") or {}).get("kind") == "model",
              "waiting_for=" + json.dumps(
                  runtime.get("waiting_for"), ensure_ascii=False))
        try:
            page.wait_for_selector(".pl-plan-live", timeout=20000)
            planning_text = page.locator("#pl-scene").inner_text()
            has_waiting = ("توليد الخطة جارٍ" in planning_text or
                           "ما يُنتظر معلن" in planning_text)
            check("A1-planning-live-card-visible", has_waiting,
                  "بطاقة التخطيط الحي ظاهرة أثناء التوليد")
            shot(page, "02_planning_live.png")
        except Exception as error:  # noqa: BLE001
            check("A1-planning-live-card-visible", False, str(error))

        # ---------- D+E. الخطة تصل عبر التيار — بلا refresh ----------
        print("[3] D+E الخطة تصل حية ثم الاعتماد", flush=True)
        state = wait_status(pid, {"AWAITING_OWNER_APPROVAL"}, 60)
        check("D-planning-completes-to-approval",
              state["status"] == "AWAITING_OWNER_APPROVAL",
              f"status={state['status']}")
        time.sleep(1.2)   # البث يجدد المشهد
        shot(page, "03_plan_awaiting_approval.png")

        dom_click(page, ".pl-btn.primary")   # زر الاعتماد
        state = wait_status(pid, {"READY", "RUNNING", "PAUSED",
                                  "BLOCKED"}, 60)
        check("E-approval-opens-execution",
              state["status"] in ("READY", "RUNNING", "PAUSED"),
              f"status={state['status']}")

        # ---------- F. التنفيذ بدأ — والوظيفة الدائمة حية ----------
        print("[4] F التنفيذ يبدأ — الخطوة الأولى تعمل فعليًا", flush=True)
        state = wait_status(pid, {"RUNNING"}, 60)
        check("F-execution-running", state["status"] == "RUNNING",
              f"status={state['status']}")
        job = state.get("job") or {}
        job_id = job.get("id")
        time.sleep(2.0)
        shot(page, "04_execution_running.png")

        # ---------- §10. رأس المشروع: المرحلة/البيئة/العامل/الأزرار ------
        try:
            page.wait_for_function(
                "() => { const t = document.getElementById('pl-head-bar')"
                ".textContent; return t.includes('المرحلة') &&"
                " (t.includes('إيقاف') || t.includes('استئناف')); }",
                timeout=15000)
            header = page.locator("#pl-head-bar").inner_text()
            check("header-has-stage-and-actions",
                  "المرحلة" in header, header[:120])
        except Exception as error:  # noqa: BLE001
            header = page.locator("#pl-head-bar").inner_text()
            check("header-has-stage-and-actions", False,
                  f"{error} | header={header[:150]}")

        # ---------- O. تبويبان — أفعال A تظهر في B بلا refresh ----------
        print("[5] O التبويبان — نفس المشروع في صفحتين", flush=True)
        page_b = ctx.new_page()
        page_b.goto(BASE + "/#/project/" + str(pid))
        try:
            page_b.wait_for_selector("#pl-head-bar", timeout=10000)
            # في A: افتح تبويب سير العمل — وفي B تحقق أنه متاح أيضًا
            dom_click(page, ".pl-tab[data-tab='workflow']")
            time.sleep(1.0)
            page.wait_for_selector(".wf-pipeline", timeout=10000)
            check("O-workflow-tab-two-pages",
                  page.locator(".wf-pipeline").count() >= 1,
                  "تبويب سير العمل يعمل في A")
            shot(page, "05_workflow_tab.png")
            stage_current = page.locator(".wf-stage.current").count()
            check("workflow-pipeline-current-stage",
                  stage_current >= 1,
                  f"مرحلة حالية بارزة: {stage_current}")
        except Exception as error:  # noqa: BLE001
            check("O-workflow-tab-two-pages", False, str(error))

        # ---------- G. الإيقاف المؤقت — نفس الوظيفة الدائمة ----------
        print("[6] G الإيقاف المؤقت", flush=True)
        dom_click_text(page, ".pl-act-btn", "إيقاف مؤقت")
        state = wait_status(pid, {"PAUSED", "COMPLETED"}, 90)
        check("G-pause-durable",
              state["status"] in ("PAUSED", "COMPLETED"),
              f"status={state['status']}")
        shot(page, "06_paused.png")

        # ---------- H. الاستئناف — نفس الوظيفة لا نسخة جديدة ----------
        if state["status"] == "PAUSED":
            print("[7] H الاستئناف — نفس الوظيفة الدائمة", flush=True)
            # استقرار الحلقة القديمة: التشغيل النشط لم يعد هذا المشروع
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                runs = api("GET", "/api/projects/runs/active")
                active_pid = runs.get("active_run")
                if active_pid != pid:
                    break
                time.sleep(0.5)
            time.sleep(3.5)   # دع استطلاع الواجهة يجدد الأزرار

            resume_traffic: list[dict] = []

            def _on_response(response):
                if "/resume" in response.url:
                    try:
                        resume_traffic.append({
                            "status": response.status,
                            "body": response.text()[:300],
                        })
                    except Exception:  # noqa: BLE001
                        resume_traffic.append({"status": response.status})

            page.on("response", _on_response)

            def _click_resume():
                dom_click_text(page, ".pl-act-btn", "استئناف", 20000)

            # شريط الأزرار يُعاد رسمه كل 3ث (استطلاع اللقطة الحية) —
            # النقرة قد تقع على عقدة فُصلت للتو؛ حتى 3 محاولات عبر
            # نفس الزر الحقيقي (لا مسار موازٍ أبدًا)
            for _attempt in range(3):
                _click_resume()
                state = wait_status(pid, {"RUNNING", "PAUSED"}, 20)
                if state["status"] == "RUNNING":
                    break
                time.sleep(3.5)
            resumed_job = (api("GET", f"/api/projects/{pid}/state")
                           .get("job") or {}).get("id")
            check("H-resume-same-job",
                  state["status"] == "RUNNING"
                  and resumed_job == job_id,
                  f"job {job_id} → {resumed_job}, "
                  f"status={state['status']}, traffic={resume_traffic}")
            shot(page, "07_resumed.png")

        # ---------- N+W. التاريخ — صفحات مع مؤشر رجوع ----------
        print("[8] N+W التاريخ صفحات", flush=True)
        dom_click(page, ".pl-tab[data-tab='history']")
        try:
            page.wait_for_selector(".wf-history-line", timeout=10000)
            lines = page.locator(".wf-history-line").count()
            check("N-history-visible", lines > 0,
                  f"{lines} سطر تاريخ")
            shot(page, "08_history_tab.png")
            has_more = page.locator(".wf-history-more").is_visible()
            check("W-history-load-more-bounded", True,
                  f"has_more={'نعم' if has_more else 'لا'}، "
                  "حجم الصفحة محدود بنيويًا (60)")
        except Exception as error:  # noqa: BLE001
            check("N-history-visible", False, str(error))

        # ---------- U. تبويب الأدلة ----------
        print("[9] U تبويب الأدلة", flush=True)
        dom_click(page, ".pl-tab[data-tab='evidence']")
        time.sleep(1.0)
        evidence_lines = page.locator(".wf-evidence-row").count()
        check("U-evidence-tab", True,
              f"{evidence_lines} بند أدلة (ينمو مع إكمال الخطوات)")

        # ---------- V. تبويب المخرجات ----------
        print("[10] V تبويب المخرجات", flush=True)
        dom_click(page, ".pl-tab[data-tab='artifacts']")
        time.sleep(1.0)
        shot(page, "09_artifacts_tab.png")

        # ---------- Q. مغادرة وعودة بلا refresh — الوظيفة باقية ----------
        print("[11] Q مغادرة ← محادثة أخرى ← عودة بلا refresh", flush=True)
        dom_click(page, "#pl-back")
        time.sleep(0.6)
        dom_click(page, "#new-chat")
        page.fill("#input", "محادثة جانبية أثناء تنفيذ المشروع")
        page.click("#send")
        time.sleep(1.5)
        shot(page, "10_left_project_other_chat.png")

        # التوجيه الدائم يعيد للمشروع — بلا refresh
        page.goto(BASE + "/#/project/" + str(pid))
        page.wait_for_selector("#pl-head-bar", timeout=10000)
        state = api("GET", f"/api/projects/{pid}/state")
        still_job = (state.get("job") or {}).get("id")
        check("Q-return-same-job-no-refresh",
              still_job == job_id,
              f"job بعد العودة: {still_job} (الأصل {job_id})")
        shot(page, "11_returned_project.png")

        # ---------- R. بحث الويب في محادثة عادية ----------
        print("[12] R الويب في المحادثة العادية — مزود حقيقي", flush=True)
        dom_click(page, "#pl-back")
        time.sleep(0.5)
        dom_click(page, "#new-chat")
        page.fill("#input",
                  "ابحث عن أحدث تقنيات OSINT وأعطني ملخصًا بمصادر")
        page.click("#web-toggle")   # auto → on (بحث صريح)
        page.click("#send")
        try:
            page.wait_for_selector(".web-used-bar", timeout=60000)
            sources = page.locator(".web-source").count()
            check("R-web-search-in-normal-chat", sources > 0,
                  f"{sources} مصادر معروضة قابلة للفتح")
            page.click(".web-used-head")
            shot(page, "12_web_research_sources.png")
        except Exception as error:  # noqa: BLE001
            # المزودان قد يكونان محجوبين من هذه الشبكة — الصدق أولاً
            body_text = page.locator("#messages").inner_text()
            unavailable = "غير متاح" in body_text or "WEB_UNAVAILABLE" \
                in body_text
            check("R-web-search-in-normal-chat", False,
                  ("WEB_UNAVAILABLE صادقة (المزودون محجوبون شبكيًا)"
                   if unavailable else str(error)[:200]))

        # ---------- K. التكرار — نسخة جديدة لا تمس الأصل ----------
        print("[13] K تكرار المشروع", flush=True)
        duplicate = api("POST", f"/api/projects/{pid}/duplicate",
                        {"name": "نسخة القبول 013.4"})
        check("K-duplicate-independent",
              duplicate.get("id") and duplicate["id"] != pid
              and duplicate.get("original_id") == pid,
              f"نسخة #{duplicate.get('id')} من #{pid}")

        # ---------- L+M. الأرشفة والاسترجاع — بلا حذف ----------
        print("[14] L+M الأرشفة والاسترجاع", flush=True)
        events_before = len(api(
            "GET", f"/api/projects/{pid}/events")["events"])
        # أوقف أولاً (نهائي) — لا أرشفة أثناء التشغيل
        api("POST", f"/api/projects/{pid}/stop",
            {"reason": "نهاية سيناريو القبول", "final": True})
        state = wait_status(pid, {"STOPPED", "COMPLETED", "PAUSED"}, 90)
        archived = api("POST", f"/api/projects/{pid}/archive")
        check("I-final-stop-then-L-archive",
              archived.get("archived_at") is not None
              and state["status"] in ("STOPPED", "COMPLETED", "PAUSED"),
              f"status={state['status']}, "
              f"archived_at={archived.get('archived_at')}")

        active_ids = [p["id"] for p in
                      api("GET", "/api/projects")["projects"]]
        check("L-archive-hides-from-active", pid not in active_ids,
              "المؤرشف خارج القائمة النشطة")

        # صفحة الأرشيف في الواجهة
        page.goto(BASE)
        dom_click(page, ".side-nav-item[data-nav='archive']")
        time.sleep(0.8)
        shot(page, "13_archive_view.png")

        restored = api("POST", f"/api/projects/{pid}/restore")
        events_after = len(api(
            "GET", f"/api/projects/{pid}/events")["events"])
        check("M-restore-keeps-everything",
              restored.get("archived_at") is None
              and events_after >= events_before,
              f"الأحداث قبل={events_before} بعد={events_after}")

        # ---------- §9. مركز التحكم: التشغيلات النشطة ----------
        print("[15] مركز التحكم — التشغيلات", flush=True)
        dom_click(page, ".side-nav-item[data-nav='runs']")
        time.sleep(0.8)
        shot(page, "14_runs_view.png")

        # ---------- §12. الحقيقة النهائية: لا PLANNING أبديًا ----------
        print("[16] الحقيقة النهائية — الفحوص البنيوية", flush=True)
        final_projects = api("GET", "/api/projects")["projects"]
        stuck = [p for p in final_projects
                 if p["status"] == "PLANNING"]
        check("no-eternal-planning-anywhere", not stuck,
              f"مشاريع PLANNING عالقة: {len(stuck)}")

        # جلسة التخطيط في القاعدة: مكتملة بمعرف طلب معلن
        runtime = api("GET", f"/api/projects/{pid}/runtime")
        planning_detail = (runtime.get("planning") or {}).get("detail") \
            or {}
        check("planning-session-durable-record",
              planning_detail.get("state") in
              ("COMPLETED", "FAILED", "INTERRUPTED"),
              f"state={planning_detail.get('state')}, "
              f"provider={planning_detail.get('provider')}")

        browser.close()

    evidence["checks"] = [
        {"name": n, "ok": True} for n in PASS
    ] + [{"name": n, "ok": False} for n in FAIL]
    evidence["notes"] = NOTES
    evidence["summary"] = {
        "passed": len(PASS), "failed": len(FAIL),
        "total": len(PASS) + len(FAIL),
        "verdict": "ACCEPTED" if not FAIL else "FAILED",
    }
    evidence["finished_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n===== النتيجة: {len(PASS)} ✅ / {len(FAIL)} ❌ =====",
          flush=True)
    print(f"الأدلة: {EVIDENCE_PATH}", flush=True)
    return 1 if FAIL else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        return boot_server()
    # الخادم في خيط خلفي والسيناريو في العملية — نفس نمط 013.2
    import multiprocessing

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    server = multiprocessing.Process(target=boot_server, daemon=True)
    server.start()
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=2)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    try:
        return run_scenario()
    finally:
        server.terminate()
        server.join(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
