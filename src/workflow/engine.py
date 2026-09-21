"""محرك المشروع (الأمر 007 §10) — الحلقة الذاتية الدائمة فوق run_task.

    while project not terminal:
        1. load durable project state   (القاعدة مصدر الحقيقة §9)
        2. determine current phase
        3. determine current step
        4. if no plan → Planner          (حي — لا خطة ملفقة)
        5. if plan requires approval → WAIT (بوابة مالك)
        6. if step ready → execute       (run_task منفذ الخطوة §10)
        7. collect evidence              (سجل دائم §8)
        8. test                          (دورة الأدوار تتكفل)
        9. review                        (المدقق داخل الدورة)
       10. audit                         (ميكانيكي §11+§12)
       11. adjudicate if required        (المحكَّم داخل الدورة)
       12. determine next step
       13. checkpoint                    (سجل دائم §9)
       14. continue

tick() = وحدة عمل واحدة ذرّية: تحمّل الحالة من القاعدة، خطوة واحدة،
كتابة كل الانتقالات والأحداث، ثم checkpoint. الحلقة run() تستدعيها
حتى حالة نهائية أو انتظار مالك — بعد crash/restart، tick() الأولى
تُكمل من حيث توقف كل شيء (لا _task_state في الذاكرة كمصدر حقيقة).

التصنيف الصادق للفشل (§13):
- TRANSIENT/EXECUTION FAILURE → RetryRecord(RETRY) + محاولة جديدة
- استنفاد المحاولات → OwnerGate(PLAN_REVISION_APPROVAL) + BLOCKED
- مزود غير جاهز (007.1 §17) → EXECUTION_BLOCKED + OwnerGate
  (PROVIDER_ACTION_REQUIRED) — لا mock أبدًا ولا تنفيذ بلا نموذج.
"""

from __future__ import annotations

import hashlib
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from router.role_config import RoleSelection
from workflow import auditor, service
from workflow.models import GATE_KINDS, _utc_now
from workflow.service import PROJECT_ROLES

#: الحالات التي تُوقف الحلقة (نهائية أو انتظار قرار).
WAITING_STATES = ("AWAITING_OWNER_APPROVAL", "BLOCKED", "PAUSED")
TERMINAL_STATES = ("VERIFIED", "COMPLETED", "STOPPED", "ESCALATED")

#: سقف المحاولات الفاشلة لكل خطوة قبل بوابة المالك (§13).
MAX_STEP_FAILURES = 2

PROJECTS_DIR = Path("runtime") / "projects"


class EngineError(RuntimeError):
    """خطأ محرك صريح — يسمي المشروع والسبب."""


class ProjectEngine:
    """محرك المشاريع — حلقة ذاتية checkpointed فوق run_task."""

    def __init__(
        self,
        sessions,
        *,
        router_factory: Callable[[], Any],
        planner_factory: Callable[[], Any] | None = None,
        on_event: Callable[[dict], None] | None = None,
        role_mappings_provider: Callable[[], dict] | None = None,
        max_step_failures: int = MAX_STEP_FAILURES,
    ):
        self._sessions = sessions
        self._router_factory = router_factory
        self._planner_factory = planner_factory
        self._on_event = on_event
        self._role_mappings_provider = role_mappings_provider
        self._max_step_failures = max(1, int(max_step_failures))

    # ------------------------------------------------------------------ #
    # الأحداث — دائمة + بث لحظي
    # ------------------------------------------------------------------ #

    def _emit(self, project_id: int, kind: str, payload: dict) -> None:
        service.add_event(self._sessions, project_id, kind, payload)
        if self._on_event is not None:
            try:
                self._on_event({
                    "project_id": project_id, "kind": kind,
                    "payload": payload,
                })
            except Exception:  # noqa: BLE001 — المستقبِل لا يكسر الحلقة
                pass

    # ------------------------------------------------------------------ #
    # العمليات العليا — يستدعيها الـAPI
    # ------------------------------------------------------------------ #

    def create_project(self, name: str, objective: str) -> dict:
        if not objective or not objective.strip():
            raise EngineError("الهدف مطلوب — المشروع بلا هدف لا معنى له")
        return service.create_project(
            self._sessions, name=name.strip(), objective=objective.strip()
        )

    def generate_plan(self, project_id: int) -> dict:
        """توليد الخطة (§4) — حي حصرًا: فشل النموذج = فشل صريح لا خطة ملفقة."""
        project = self._project(project_id)
        if project["status"] in TERMINAL_STATES:
            raise EngineError(
                f"المشروع في حالة نهائية ({project['status']}) — لا توليد خطة"
            )
        previous = service.latest_plan(self._sessions, project_id)
        return self._generate_plan(project, previous_failure=None)

    def _generate_plan(self, project: dict, *,
                       previous_failure: dict | None = None) -> dict:
        """توليد خطة جديدة (v1 أو مراجعة) — PLANNING → نتيجة صادقة."""
        project_id = project["id"]
        service.update_project(self._sessions, project_id, status="PLANNING")
        try:
            planner = self._build_planner()
            plan_data = planner.generate(
                project["objective"], previous_failure=previous_failure
            )
        except Exception as error:  # noqa: BLE001 — فشل صريح موثق
            service.update_project(
                self._sessions, project_id, status="DRAFT",
                last_error=f"فشل توليد الخطة: {error}",
            )
            raise EngineError(f"فشل توليد الخطة: {error}") from error

        previous = service.latest_plan(self._sessions, project_id)
        supersedes = previous["id"] if previous else None
        plan = service.create_plan(
            self._sessions, project_id, plan_data,
            supersedes_plan_id=supersedes,
            revision_reason=(
                (previous_failure or {}).get("reason", "") if supersedes else ""
            ),
            revision_evidence=previous_failure or {},
        )
        if supersedes:
            service.supersede_plan(self._sessions, supersedes)
        service.update_project(
            self._sessions, project_id,
            status="AWAITING_OWNER_APPROVAL", last_error="",
        )
        gate_id = service.open_gate(
            self._sessions, project_id, "PLAN_APPROVAL",
            f"اعتماد الخطة v{plan['version']} — {len(plan['phases'])} مرحلة",
            {"plan_id": plan["id"], "version": plan["version"]},
        )
        self._emit(project_id, "PLAN_APPROVAL_REQUIRED",
                   {"plan_id": plan["id"], "gate_id": gate_id})
        return plan

    def approve_plan(self, project_id: int, *, approved: bool,
                     feedback: str = "") -> dict:
        """قرار المالك على الخطة — اعتماد يفعّل، ورفض يعيد التوليد بتغذية راجعة."""
        project = self._project(project_id)
        plan = service.latest_plan(self._sessions, project_id)
        if plan is None:
            raise EngineError("لا خطة للاعتماد — ولّدها أولًا")
        if plan["status"] != "AWAITING_OWNER_APPROVAL":
            raise EngineError(
                f"الخطة v{plan['version']} في حالة {plan['status']} — لا قرار"
            )
        gate = self._gate_of_plan(project_id, plan["id"])
        if gate is not None and gate["status"] == "OPEN":
            service.resolve_gate(self._sessions, gate["id"], approved=approved)
            self._emit(project_id, "OWNER_GATE_RESOLVED",
                       {"gate_id": gate["id"], "approved": approved})
        if not approved:
            # رفض = إعادة توليد بتغذية المالك الراجعة (خطة v جديدة)
            service.update_project(self._sessions, project_id,
                                   status="REVISING", last_error="")
            return self._generate_plan(
                project,
                previous_failure={
                    "reason": "رفض المالك للخطة",
                    "feedback": feedback,
                },
            )
        service.approve_plan(self._sessions, plan["id"])
        service.materialize_plan(self._sessions, plan)
        service.update_project(self._sessions, project_id,
                               status="READY", last_error="")
        self._emit(project_id, "PLAN_APPROVED",
                   {"plan_id": plan["id"], "version": plan["version"]})
        return service.get_project(self._sessions, project_id)

    def _gate_of_plan(self, project_id: int, plan_id: int) -> dict | None:
        for gate in service.list_gates(self._sessions, project_id):
            if (gate["kind"] == "PLAN_APPROVAL"
                    and gate["status"] == "OPEN"
                    and gate["details"].get("plan_id") == plan_id):
                return gate
        return None

    def verify(self, project_id: int) -> dict:
        """التحقق النهائي (§16) — VERIFIED قرار المالك وحده، بلا استثناء.

        القناة الوحيدة: المشروع COMPLETED وcompletion_state=CANDIDATE.
        لا يوجد أي مسار آخر في النظام كله يكتب VERIFIED.
        """
        project = self._project(project_id)
        if project["status"] != "COMPLETED":
            raise EngineError(
                f"المشروع في حالة {project['status']} — التحقق النهائي "
                "يتطلب اكتمالًا مرشحًا (COMPLETED + CANDIDATE)"
            )
        if project["completion_state"] != "CANDIDATE":
            raise EngineError(
                f"حالة الإكمال {project['completion_state']} — لا تحقق قبل "
                "نجاح التدقيق النهائي"
            )
        gate = self._open_gate(project_id, "FINAL_VERIFICATION")
        if gate is not None:
            service.resolve_gate(self._sessions, gate["id"], approved=True)
            self._emit(project_id, "OWNER_GATE_RESOLVED",
                       {"gate_id": gate["id"], "approved": True})
        service.update_project(self._sessions, project_id,
                               status="VERIFIED", completion_state="VERIFIED")
        self._emit(project_id, "PROJECT_VERIFIED", {})
        return service.get_project(self._sessions, project_id)

    def request_stop(self, project_id: int, reason: str = "") -> dict:
        """طلب إيقاف — علم ذرّي يُكرَّم عند أقرب checkpoint (§9)."""
        self._project(project_id)
        service.update_project(self._sessions, project_id,
                               stop_requested=True)
        controller = _ACTIVE_CONTROLLERS.get(project_id)
        if controller is not None:
            controller.request_stop(
                f"project-{project_id}", by="owner", reason=reason
            )
        return service.get_project(self._sessions, project_id)

    def resume(self, project_id: int) -> dict:
        """استئناف صريح — من checkpoint بعد إيقاف أو قرار مالك (§9)."""
        project = self._project(project_id)
        if project["status"] not in ("PAUSED", "BLOCKED", "READY", "REVISING"):
            raise EngineError(
                f"المشروع في حالة {project['status']} — لا استئناف من هنا"
            )
        if project["status"] == "BLOCKED":
            gates = service.open_gates(self._sessions, project_id)
            if gates:
                raise EngineError(
                    "بوابات مالك مفتوحة تمنع الاستئناف — عالجها أولًا: "
                    + "؛ ".join(g["kind"] for g in gates)
                )
        service.update_project(self._sessions, project_id,
                               stop_requested=False, status="RUNNING")
        self._emit(project_id, "PROJECT_RESUMED",
                   {"from_status": project["status"]})
        return service.get_project(self._sessions, project_id)

    def resolve_gate(self, project_id: int, gate_id: int, *,
                     approved: bool) -> dict:
        """حل بوابة مالك — لكل نوع أثره الصريح (§14)."""
        project = self._project(project_id)
        outcome = service.resolve_gate(
            self._sessions, gate_id, approved=approved
        )
        self._emit(project_id, "OWNER_GATE_RESOLVED",
                   {"gate_id": gate_id, "approved": approved})
        if not approved:
            service.update_project(self._sessions, project_id,
                                   status="STOPPED", last_error="رفض المالك البوابة")
            return outcome
        if outcome["kind"] == "PLAN_REVISION_APPROVAL":
            # موافقة على مراجعة الخطة → توليد v جديدة بسياق الفشل (§4)
            failure = self._last_failure_context(project_id)
            service.update_project(self._sessions, project_id,
                                   status="REVISING", last_error="")
            self._generate_plan(project, previous_failure=failure)
        elif outcome["kind"] == "PROVIDER_ACTION_REQUIRED":
            # المالك عالج المزود → الخطوة الجاهزة للإعادة والاستئناف صريح
            plan = self._active_plan(project)
            for step in self._pending_steps(
                project_id, plan_id=plan["id"] if plan else None
            ):
                if step["status"] == "BLOCKED":
                    service.update_step(self._sessions, step["id"],
                                        status="READY", last_error="")
            service.update_project(self._sessions, project_id, status="PAUSED")
        elif outcome["kind"] == "FINAL_VERIFICATION":
            service.update_project(self._sessions, project_id, status="COMPLETED")
        elif outcome["kind"] == "ESCALATION":
            service.update_project(self._sessions, project_id, status="PAUSED")
        return outcome

    def _last_failure_context(self, project_id: int) -> dict:
        """سياق الفشل الأخير — يُمرر للمخطط كي تراه الخطة v الجديدة."""
        executions = service.list_executions(self._sessions, project_id)
        failed = [e for e in executions if e["status"] == "FAILED"]
        if not failed:
            return {}
        last = failed[0]
        return {
            "reason": "فشل تنفيذ متكرر استنفد المحاولات",
            "last_error": last["error"][:500],
            "step_objective": self._step_objective(last["step_id"]),
        }

    def _step_objective(self, step_id: int) -> str:
        step = service.get_step(self._sessions, step_id)
        return step["objective"] if step else ""

    # ------------------------------------------------------------------ #
    # الحلقة الذاتية (§10)
    # ------------------------------------------------------------------ #

    def tick(self, project_id: int) -> dict:
        """وحدة عمل واحدة ذرّية — كل الحالة من القاعدة وإليها."""
        project = self._project(project_id)
        status = project["status"]

        if status in TERMINAL_STATES:
            return {"action": "none", "reason": f"الحالة {status} نهائية"}
        if status == "PAUSED":
            return {"action": "paused",
                    "reason": "متوقف مؤقتًا — الاستئناف قرار صريح"}
        if status == "BLOCKED":
            gates = service.open_gates(self._sessions, project_id)
            return {"action": "blocked",
                    "reason": "بوابة مالك مفتوحة",
                    "gates": [g["kind"] for g in gates]}
        if status == "AWAITING_OWNER_APPROVAL":
            return {"action": "wait_owner",
                    "reason": "الخطة تنتظر اعتماد المالك"}

        # إيقاف مطلوب — يُكرَّم فورًا عند هذا الحد الآمن (§9)
        if project["stop_requested"]:
            return self._pause(project, "طلب إيقاف المالك")

        # لا خطة معتمدة → توليد (DRAFT/REVISING) — الحلقة تتضمن Planner
        plan = self._active_plan(project)
        if plan is None:
            if status == "PLANNING":
                return {"action": "failed",
                        "reason": "توليد الخطة لم يكتمل — أعد المحاولة"}
            failure = None
            latest = service.latest_plan(self._sessions, project_id)
            if latest is not None and latest["status"] == "REJECTED":
                failure = {"reason": "رفض سابق", "feedback": ""}
            plan = self._generate_plan(project, previous_failure=failure)
            return {"action": "wait_owner",
                    "reason": "خطة جديدة تنتظر الاعتماد",
                    "plan_id": plan["id"]}

        # خطة معتمدة + جاهز/يعمل ← حدد المرحلة الحالية
        phases = service.active_phases(self._sessions, plan["id"])
        if not phases:
            return self._final_audit(project, plan, phases)

        active = next(
            (p for p in phases
             if p["status"] not in ("COMPLETED", "REVISED", "FAILED")),
            None,
        )
        if active is None:
            return self._final_audit(project, plan, phases)

        if active["status"] in ("PLANNED", "READY"):
            service.update_phase(self._sessions, active["id"], status="RUNNING")
            service.update_project(self._sessions, project_id,
                                   current_phase_id=active["id"])
            self._emit(project_id, "PHASE_STARTED",
                       {"phase_id": active["id"], "title": active["title"]})

        steps = service.phase_steps(self._sessions, active["id"])
        step = next(
            (s for s in steps if s["status"] != "COMPLETED"), None
        )
        if step is None:
            return self._stage_review(project, plan, active, steps)

        return self._execute_step(project, plan, active, step)

    def run(self, project_id: int, *, max_ticks: int = 100) -> dict:
        """الحلقة الكاملة — tick حتى حالة نهائية أو انتظار أو فشل."""
        ticks = 0
        last: dict = {}
        while ticks < max_ticks:
            last = self.tick(project_id)
            ticks += 1
            if last.get("action") in (
                "none", "paused", "blocked", "wait_owner", "failed",
            ):
                break
        last["ticks"] = ticks
        return last

    # ------------------------------------------------------------------ #
    # تنفيذ الخطوة (§6+§7+§8) — readiness ← execution ← evidence ← audit
    # ------------------------------------------------------------------ #

    def _execute_step(self, project: dict, plan: dict, phase: dict,
                      step: dict) -> dict:
        from core.stop_controller import StopController
        from tasks import run_task

        project_id = project["id"]

        # 1) جاهزية المزودين (007.1 §17): حل الأدوار ← المزود ← التكوين
        #    ← النموذج ← فحص قبل أي تنفيذ. لا نموذج = EXECUTION_BLOCKED.
        role_selections = self._role_selections()
        router = self._router_factory()
        unready: list[dict] = []
        for role in PROJECT_ROLES:
            selection = role_selections.get(role)
            if selection is None:
                continue
            key = selection.transport_key()
            if not getattr(router, "has_live_provider", lambda _p: False)(key):
                unready.append({
                    "role": role, "provider": selection.provider,
                    "configuration": selection.configuration,
                    "model": selection.model,
                    "reason": f"لا نقل حي قابل للحل للمزود '{key}'",
                })
        if unready:
            return self._block_on_providers(project, plan, phase, step,
                                            unready)

        # 2) سجل التنفيذ الدائم (§7) — كل محاولة سجل مستقل
        attempt = step["attempts"] + 1
        workspace = PROJECTS_DIR / str(project_id) / "steps" / str(step["id"])
        workspace.mkdir(parents=True, exist_ok=True)
        # أمانة ما بعد الانهيار: تنفيذ RUNNING بلا خيط حي (restart)
        # يُوسم فشلًا بسبب صريح — لا يبقى معلقًا كأنه حي (§9)
        self._fail_orphaned_executions(step["id"])
        execution_id = service.create_execution(
            self._sessions, step["id"], attempt=attempt,
            provider=str(role_selections.get("implementer")),
            model=str(getattr(role_selections.get("implementer"), "model", "")),
            workspace=str(workspace), agent_role="implementer",
        )
        service.update_step(
            self._sessions, step["id"], status="RUNNING",
            attempts=attempt, current_execution_id=execution_id,
            last_error="",
        )
        service.update_project(self._sessions, project_id,
                               current_step_id=step["id"], status="RUNNING")
        self._emit(project_id, "STEP_STARTED",
                   {"step_id": step["id"], "objective": step["objective"]})
        self._emit(project_id, "EXECUTION_STARTED",
                   {"execution_id": execution_id, "attempt": attempt,
                    "step_id": step["id"]})

        # 3) التنفيذ — run_task منفذ وحدة الخطوة (§10: لا حذف له)
        stop = StopController()
        _ACTIVE_CONTROLLERS[project_id] = stop
        # الهدف الكامل: معايير القبول جزء من عقد الخطوة — المنفذ يراها
        # حرفيًا فيخطط مهامه عليها (لا اجتهاد فوق ما حددته الخطة)
        goal = step["objective"]
        if step.get("input"):
            goal += f"\n\nالمدخلات: {step['input']}"
        if step.get("expected_output"):
            goal += f"\nالمخرج المتوقع: {step['expected_output']}"
        if step.get("acceptance_criteria"):
            goal += "\nمعايير القبول (تحقق حرفيًا):\n- " + \
                "\n- ".join(step["acceptance_criteria"])

        def cycle_sink(event: dict) -> None:
            self._on_event and self._on_event({
                "project_id": project_id, "kind": "step.progress",
                "payload": {"step_id": step["id"],
                            "execution_id": execution_id, "event": event},
            })

        try:
            result = run_task(
                goal,
                router=router,
                role_config={
                    key: value for key, value in role_selections.items()
                    if key != "chat"
                },
                workspace=workspace,
                on_event=cycle_sink,
                cycle_id=f"project-{project_id}-step-{step['id']}",
                stop_controller=stop,
            )
        except Exception as error:  # noqa: BLE001 — فشل صريح موثق
            service.update_execution(self._sessions, execution_id,
                                     status="FAILED", error=str(error))
            return self._on_step_failure(project, plan, phase, step,
                                         execution_id, str(error))
        finally:
            _ACTIVE_CONTROLLERS.pop(project_id, None)

        if result.verdict == "STOPPED":
            service.update_execution(self._sessions, execution_id,
                                     status="STOPPED")
            service.update_step(self._sessions, step["id"], status="READY")
            return self._pause(
                project, f"أوقفت الخطوة أثناء التنفيذ — استئنافها من جديد"
            )

        if result.verdict != "PASS":
            service.update_execution(
                self._sessions, execution_id, status="FAILED",
                error=result.reason[:2000],
            )
            return self._on_step_failure(project, plan, phase, step,
                                         execution_id, result.reason)

        # 4) نجاح ← دليل دائم (§8) + تدقيق ميكانيكي (§12) + checkpoint
        commit = _git_head()
        service.update_execution(self._sessions, execution_id,
                                 status="COMPLETED", commit_sha=commit)
        self._emit(project_id, "EXECUTION_COMPLETED",
                   {"execution_id": execution_id, "step_id": step["id"],
                    "commit_sha": commit, "verdict": result.verdict})
        evidence_id = service.create_evidence(
            self._sessions,
            execution_id=execution_id, step_id=step["id"],
            project_id=project_id,
            files=_files_with_sha(result.workspace),
            tool_calls=result.tool_calls,
            verification={"final_state": result.final_state,
                          "state_history": result.state_history},
            review_result={"verdict": result.verdict},
            commit=commit,
            evidence_path=result.evidence_path,
            evidence_sha256=result.evidence_sha256,
            verdict=result.verdict,
            commands=[], artifacts=result.files,
        )
        self._emit(project_id, "EVIDENCE_CREATED",
                   {"evidence_id": evidence_id, "step_id": step["id"],
                    "files": result.files})
        self._emit(project_id, "TEST_COMPLETED",
                   {"step_id": step["id"], "final_state": result.final_state})
        self._emit(project_id, "REVIEW_COMPLETED",
                   {"step_id": step["id"], "verdict": result.verdict})

        findings = auditor.audit_step(
            step, {"status": "COMPLETED"}, _evidence_view(result)
        )
        audit_id = service.create_audit(
            self._sessions, project_id=project_id, phase_id=phase["id"],
            step_id=step["id"], execution_id=execution_id,
            plan_version=plan["version"], findings=findings,
            evidence_refs=[evidence_id], commit_sha=commit,
            tests={"final_state": result.final_state},
            verdict=findings["verdict"],
        )
        self._emit(project_id, "AUDIT_COMPLETED",
                   {"audit_id": audit_id, "step_id": step["id"],
                    "verdict": findings["verdict"]})

        # (§11+§12) التدقيق الميكانيكي جزء من الحلقة: معايير مفقودة =
        # لا اكتمال صامت — التنفيذ يُعلن فاشلًا بتشخيص التدقيق وتعاد
        # المحاولة أو تُفتح بوابة المالك. لا ثقة بنص المنفذ أبدًا.
        if findings["verdict"] != "PASS":
            service.update_execution(
                self._sessions, execution_id, status="FAILED",
                error=(
                    f"فشل التدقيق الميكانيكي ({findings['verdict']}): "
                    f"missing={findings['missing']} "
                    f"unverifiable={findings['unverifiable']}"
                )[:2000],
            )
            return self._on_step_failure(
                project, plan, phase, step, execution_id,
                f"التدقيق الميكانيكي فشل — missing="
                f"{findings['missing'][:3]}",
            )

        service.update_step(self._sessions, step["id"], status="COMPLETED",
                            evidence_id=evidence_id)
        self._checkpoint(project_id, plan, phase, step)
        if result.state_history and "ADJUDICATED" in result.state_history:
            self._emit(project_id, "ADJUDICATION_COMPLETED",
                       {"step_id": step["id"]})
        return {"action": "continue", "step_id": step["id"],
                "verdict": findings["verdict"]}

    def _block_on_providers(self, project: dict, plan: dict, phase: dict,
                            step: dict, unready: list[dict]) -> dict:
        """EXECUTION_BLOCKED (007.1 §17-§18) — دليل + بوابة مالك، لا mock."""
        project_id = project["id"]
        execution_id = service.create_execution(
            self._sessions, step["id"], attempt=step["attempts"] + 1,
            provider="؛ ".join(u["provider"] for u in unready)[:110],
            model="؛ ".join(u["model"] for u in unready)[:190],
            workspace=str(PROJECTS_DIR / str(project_id) / "steps" / str(step["id"])),
            agent_role="coordinator",
        )
        service.update_execution(
            self._sessions, execution_id, status="BLOCKED",
            error="مزود غير جاهز: " + "; ".join(
                f"{u['role']}→{u['provider']}" for u in unready
            ),
        )
        evidence_id = service.create_evidence(
            self._sessions, execution_id=execution_id, step_id=step["id"],
            project_id=project_id, files={}, tool_calls=[],
            verification={"final_state": "EXECUTION_BLOCKED"},
            review_result={}, commit="", evidence_path="", evidence_sha256="",
            verdict="EXECUTION_BLOCKED",
            artifacts=[], tests={"unready_roles": unready},
        )
        service.update_step(self._sessions, step["id"], status="BLOCKED",
                            current_execution_id=execution_id,
                            last_error="مزود غير جاهز — قرار مالك مطلوب")
        first = unready[0]
        gate_id = service.open_gate(
            self._sessions, project_id, "PROVIDER_ACTION_REQUIRED",
            f"المزود '{first['provider']}' مهيأ لكنه غير جاهز — "
            f"الدور {first['role']} بلا نموذج قابل للاستدعاء",
            {"unready": unready,
             "required_action": "راجع المزود/التكوين من الإعدادات ثم اختبره"},
        )
        service.update_project(self._sessions, project_id, status="BLOCKED")
        self._emit(project_id, "EXECUTION_BLOCKED",
                   {"step_id": step["id"], "execution_id": execution_id,
                    "evidence_id": evidence_id, "gate_id": gate_id,
                    "unready": unready})
        return {"action": "blocked", "reason": "مزود غير جاهز",
                "gate_id": gate_id}

    def _on_step_failure(self, project: dict, plan: dict, phase: dict,
                         step: dict, execution_id: int, reason: str) -> dict:
        """تصنيف الفشل (§13) — إعادة أو بوابة مالك، لا توقف أعمى."""
        project_id = project["id"]
        failures = self._step_failures(step["id"])
        if failures < self._max_step_failures:
            service.create_retry(
                self._sessions, step_id=step["id"],
                previous_execution_id=execution_id,
                reason=reason[:500], diagnosis="فشل تنفيذ — إعادة محاولة",
                decision="RETRY",
            )
            service.update_step(self._sessions, step["id"], status="READY",
                                last_error=reason[:500])
            self._emit(project_id, "EXECUTION_FAILED",
                       {"step_id": step["id"], "execution_id": execution_id,
                        "reason": reason[:300]})
            self._emit(project_id, "RETRY_REQUESTED",
                       {"step_id": step["id"], "attempt": failures + 1,
                        "decision": "RETRY"})
            return {"action": "continue", "reason": "إعادة محاولة الخطوة"}
        # استنفد المحاولات — فشل خطة: مراجعة تقتضي قرار المالك (§4+§13)
        service.create_retry(
            self._sessions, step_id=step["id"],
            previous_execution_id=execution_id, reason=reason[:500],
            diagnosis="استنفاد المحاولات — يلزم مراجعة الخطة",
            decision="ESCALATE",
        )
        service.update_step(self._sessions, step["id"], status="FAILED",
                            last_error=reason[:500])
        gate_id = service.open_gate(
            self._sessions, project_id, "PLAN_REVISION_APPROVAL",
            f"الخطوة فشلت {failures} مرات — مراجعة الخطة v{plan['version']} "
            "تقتضي خطة جديدة",
            {"step_id": step["id"], "last_error": reason[:500]},
        )
        service.update_project(self._sessions, project_id, status="BLOCKED",
                               last_error=reason[:500])
        self._emit(project_id, "EXECUTION_FAILED",
                   {"step_id": step["id"], "execution_id": execution_id,
                    "reason": reason[:300], "exhausted": True})
        return {"action": "blocked", "reason": "استنفدت المحاولات — بوابة مالك",
                "gate_id": gate_id}

    def _step_failures(self, step_id: int) -> int:
        """عدد التنفيذات الفاشلة للخطوة — ميزانية الإعادات للفشل فقط."""
        with self._sessions() as session:
            from sqlalchemy import select as _select

            from workflow.models import Execution

            rows = session.scalars(
                _select(Execution).where(Execution.step_id == int(step_id))
            ).all()
            return len([r for r in rows if r.status == "FAILED"])

    def _fail_orphaned_executions(self, step_id: int) -> None:
        """وسم تنفيذات RUNNING اليتيمة فشلًا بسبب صريح — لا حياة كاذبة."""
        with self._sessions() as session:
            from sqlalchemy import select as _select

            from workflow.models import Execution

            rows = session.scalars(
                _select(Execution).where(
                    Execution.step_id == int(step_id),
                    Execution.status == "RUNNING",
                )
            ).all()
            for row in rows:
                row.status = "FAILED"
                row.error = "انقطع التنفيذ (توقف العملية أثناءه) — وُسم فشلًا"
                row.finished_at = _utc_now()
            if rows:
                session.commit()

    # ------------------------------------------------------------------ #
    # مراجعة المرحلة (§15) والتدقيق النهائي (§16)
    # ------------------------------------------------------------------ #

    def _stage_review(self, project: dict, plan: dict, phase: dict,
                      steps: list[dict]) -> dict:
        """اكتمال المرحلة ← تدقيق ← COMPLETED/REVISE/BLOCKED/ESCALATE."""
        project_id = project["id"]
        service.update_phase(self._sessions, phase["id"], status="REVIEWING")
        evidences = [
            e for e in service.list_evidence(self._sessions, project_id)
            if e["step_id"] in {s["id"] for s in steps}
        ]
        result = auditor.audit_phase(phase, steps, evidences)
        audit_id = service.create_audit(
            self._sessions, project_id=project_id, phase_id=phase["id"],
            step_id=None, execution_id=None, plan_version=plan["version"],
            findings=result, evidence_refs=[e["id"] for e in evidences],
            commit_sha=_git_head(), tests={}, verdict=result["verdict"],
        )
        self._emit(project_id, "AUDIT_COMPLETED",
                   {"audit_id": audit_id, "phase_id": phase["id"],
                    "verdict": result["verdict"]})
        if result["verdict"] == "COMPLETED":
            service.update_phase(self._sessions, phase["id"],
                                 status="COMPLETED", review_status="PASS")
            self._emit(project_id, "PHASE_COMPLETED",
                       {"phase_id": phase["id"], "title": phase["title"]})
            self._checkpoint(project_id, plan, phase, None)
            return {"action": "continue", "reason": "المرحلة اكتملت"}
        if result["verdict"] == "REVISE":
            gate_id = service.open_gate(
                self._sessions, project_id, "PLAN_REVISION_APPROVAL",
                f"مراجعة المرحلة '{phase['title']}' وجدت نقصًا — خطة جديدة؟",
                {"phase_id": phase["id"], "findings": result},
            )
            service.update_phase(self._sessions, phase["id"],
                                 status="BLOCKED", review_status="REVISE")
            service.update_project(self._sessions, project_id,
                                   status="BLOCKED")
            return {"action": "blocked", "reason": "المرحلة تحتاج مراجعة",
                    "gate_id": gate_id}
        gate_id = service.open_gate(
            self._sessions, project_id, "ESCALATION",
            f"المرحلة '{phase['title']}' محجوبة — تصعيد",
            {"phase_id": phase["id"], "findings": result},
        )
        service.update_phase(self._sessions, phase["id"],
                             status="BLOCKED", review_status="BLOCKED")
        service.update_project(self._sessions, project_id, status="ESCALATED")
        return {"action": "blocked", "reason": "تصعيد", "gate_id": gate_id}

    def _final_audit(self, project: dict, plan: dict,
                     phases: list[dict]) -> dict:
        """التدقيق النهائي (§16) — لا اكتمال بلا نجاحه، والتحقق للمالك."""
        project_id = project["id"]
        steps = self._pending_steps(project_id, plan_id=plan["id"],
                                    include_completed=True)
        evidences = service.list_evidence(self._sessions, project_id)
        audits = service.list_audits(self._sessions, project_id)
        result = auditor.audit_final(project, phases, steps, evidences, audits)
        audit_id = service.create_audit(
            self._sessions, project_id=project_id, phase_id=None,
            step_id=None, execution_id=None, plan_version=plan["version"],
            findings=result, evidence_refs=[e["id"] for e in evidences],
            commit_sha=_git_head(), tests={}, verdict=result["verdict"],
        )
        self._emit(project_id, "AUDIT_COMPLETED",
                   {"audit_id": audit_id, "final": True,
                    "verdict": result["verdict"]})
        if result["verdict"] != "PASS":
            gate_id = service.open_gate(
                self._sessions, project_id, "PLAN_REVISION_APPROVAL",
                "التدقيق النهائي وجد مسائل معلقة — مراجعة الخطة",
                {"findings": result},
            )
            service.update_project(self._sessions, project_id,
                                   status="BLOCKED",
                                   last_error="التدقيق النهائي فشل")
            return {"action": "blocked", "reason": "التدقيق النهائي فشل",
                    "gate_id": gate_id}
        service.update_project(
            self._sessions, project_id, status="COMPLETED",
            completion_state="CANDIDATE", current_step_id=None,
        )
        gate_id = service.open_gate(
            self._sessions, project_id, "FINAL_VERIFICATION",
            "المشروع مرشح للإكمال — التحقق النهائي قرار المالك",
            {"final_audit_id": audit_id},
        )
        self._emit(project_id, "PROJECT_COMPLETION_CANDIDATE",
                   {"final_audit_id": audit_id, "gate_id": gate_id})
        return {"action": "wait_owner",
                "reason": "مرشح — التحقق النهائي للمالك", "gate_id": gate_id}

    def _pause(self, project: dict, reason: str) -> dict:
        project_id = project["id"]
        plan = self._active_plan(project)
        phase = service.get_phase(
            self._sessions, project["current_phase_id"]
        ) if project["current_phase_id"] else None
        step = service.get_step(
            self._sessions, project["current_step_id"]
        ) if project["current_step_id"] else None
        self._checkpoint(project_id, plan, phase, step)
        service.update_project(self._sessions, project_id,
                               status="PAUSED", stop_requested=False)
        self._emit(project_id, "PROJECT_PAUSED", {"reason": reason})
        return {"action": "paused", "reason": reason}

    def _checkpoint(self, project_id: int, plan: dict | None,
                    phase: dict | None, step: dict | None) -> int:
        checkpoint_id = service.create_checkpoint(
            self._sessions, project_id, plan_id=plan["id"] if plan else None,
            phase_id=phase["id"] if phase else None,
            step_id=step["id"] if step else None, tick_count=0,
            state={"last_execution": self._last_execution_id(project_id),
                   "plan_version": plan["version"] if plan else None},
        )
        self._emit(project_id, "CHECKPOINT_CREATED",
                   {"checkpoint_id": checkpoint_id})
        return checkpoint_id

    def _last_execution_id(self, project_id: int) -> int | None:
        executions = service.list_executions(self._sessions, project_id,
                                             limit=1)
        return executions[0]["id"] if executions else None

    # ------------------------------------------------------------------ #
    # استرداد بدء التشغيل (§19) — اكتشاف وتقييم، لا تنفيذ عشوائي
    # ------------------------------------------------------------------ #

    def assess_recovery(self) -> list[dict]:
        """فحص المشاريع غير النهائية عند الإقلاع — تقييم صريح لا تشغيل.

        لكل مشروع: آخر checkpoint، المرحلة/الخطوة الحالية، آخر تنفيذ
        ودليل وتدقيق، وهل يمكن استئنافه تلقائيًا أم يحتاج مالكًا —
        والقرار مسجّل كحدث RECOVERY_ASSESSED. لا يبدأ أي تنفيذ أبدًا.
        """
        assessments = []
        for project in service.list_projects(self._sessions):
            if project["status"] not in WAITING_STATES + ("RUNNING", "READY",
                                                          "PLANNING",
                                                          "REVISING"):
                continue
            project_id = project["id"]
            checkpoint = service.latest_checkpoint(self._sessions, project_id)
            gates = service.open_gates(self._sessions, project_id)
            executions = service.list_executions(self._sessions, project_id,
                                                 limit=1)
            evidence = service.list_evidence(self._sessions, project_id,
                                             limit=1)
            audits = service.list_audits(self._sessions, project_id, limit=1)
            if project["status"] == "RUNNING":
                # كان يعمل عند الإيقاف — لا استئناف تلقائي (§19.6)
                recommendation = "OWNER_DECISION"
                reason = "كان قيد التشغيل عند توقف العملية — الاستئناف صريح"
                service.update_project(self._sessions, project_id,
                                       status="PAUSED")
            elif gates:
                recommendation = "OWNER_DECISION"
                reason = "بوابات مالك مفتوحة: " + "، ".join(
                    g["kind"] for g in gates)
            elif project["status"] == "PAUSED":
                recommendation = "RESUMABLE"
                reason = "متوقف بلقطة — قابل للاستئناف الصريح"
            else:
                recommendation = "OWNER_DECISION"
                reason = f"الحالة {project['status']} تتطلب قرارًا"
            assessment = {
                "project_id": project_id, "name": project["name"],
                "status": project["status"],
                "recommendation": recommendation, "reason": reason,
                "checkpoint": (checkpoint or {}).get("id"),
                "current_phase_id": project["current_phase_id"],
                "current_step_id": project["current_step_id"],
                "last_execution_id": executions[0]["id"] if executions else None,
                "last_evidence_id": evidence[0]["id"] if evidence else None,
                "last_audit_id": audits[0]["id"] if audits else None,
                "open_gates": [g["kind"] for g in gates],
            }
            self._emit(project_id, "RECOVERY_ASSESSED", assessment)
            assessments.append(assessment)
        return assessments

    # ------------------------------------------------------------------ #
    # أدوات داخلية
    # ------------------------------------------------------------------ #

    def _project(self, project_id: int) -> dict:
        project = service.get_project(self._sessions, int(project_id))
        if project is None:
            raise EngineError(f"مشروع غير معروف: {project_id}")
        return project

    def _active_plan(self, project: dict) -> dict | None:
        plan = service.latest_plan(self._sessions, project["id"])
        if plan is not None and plan["status"] == "ACTIVE" \
                and plan["approved_by_owner"]:
            return plan
        return None

    def _open_gate(self, project_id: int, kind: str) -> dict | None:
        for gate in service.open_gates(self._sessions, project_id):
            if gate["kind"] == kind:
                return gate
        return None

    def _pending_steps(self, project_id: int, *, plan_id: int | None = None,
                       include_completed: bool = False) -> list[dict]:
        """خطوات المشروع — محصورة بخطة معنية إن أعطيت (لا الخطط المنسوخة)."""
        steps: list[dict] = []
        for phase in service.list_phases(self._sessions, project_id):
            if plan_id is not None and phase["plan_id"] != plan_id:
                continue
            for step in service.phase_steps(self._sessions, phase["id"]):
                if include_completed or step["status"] != "COMPLETED":
                    steps.append(step)
        return steps

    def _role_selections(self) -> dict[str, RoleSelection]:
        """ربط الأدوار من السجل الدائم — {role: RoleSelection}."""
        if self._role_mappings_provider is not None:
            mappings = self._role_mappings_provider()
        else:
            from providers_registry import registry

            mappings = registry.get_mappings(self._sessions)
        return {
            role: RoleSelection(
                provider=m["provider"], model=m["model"],
                configuration=m.get("configuration", ""),
            )
            for role, m in mappings.items()
        }

    def _build_planner(self):
        if self._planner_factory is not None:
            return self._planner_factory()
        from workflow.planner import LivePlanner

        selections = self._role_selections()
        return LivePlanner(self._router_factory(),
                           selection=selections.get("thinker"))


#: متحكمات الإيقاف النشطة — project_id → StopController (بث لحظي فقط،
#: الحالة الدائمة في القاعدة، والمرجع يُمسح عند نهاية الخطوة).
_ACTIVE_CONTROLLERS: dict[int, Any] = {}
_ACTIVE_LOCK = threading.Lock()


def _git_head() -> str:
    """HEAD لمستودع العمل إن وُجد — أمانة كاملة: فارغ إن لم يوجد."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 — لا مستودع = لا SHA
        return ""


def _files_with_sha(workspace: str) -> dict:
    """ملفات مساحة العمل وsha256 — الأدلة الميكانيكية للتنفيذ."""
    root = Path(workspace)
    if not root.is_dir():
        return {}
    out = {}
    for path in sorted(root.iterdir()):
        if path.is_file() and path.name != "evidence.json":
            out[path.name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
    return out


def _evidence_view(result: Any) -> dict:
    """تمثيل الأدلة للمدقق — من النتيجة الفعلية لا من نص المنفذ."""
    return {
        "files": _files_with_sha(result.workspace),
        "tool_calls": result.tool_calls,
        "verification": {"final_state": result.final_state},
        "verdict": result.verdict,
        "final_state": result.final_state,
        "evidence_sha256": result.evidence_sha256,
    }
