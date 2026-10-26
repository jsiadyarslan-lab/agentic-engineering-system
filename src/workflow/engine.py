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
import time
from pathlib import Path
from typing import Any, Callable

from router.role_config import RoleSelection
from workflow import auditor, planning_runtime, service
from workflow.models import GATE_KINDS, _utc_now
from workflow.service import PROJECT_ROLES

#: (AES-EXP-04 §6) خنق إعادة الفحص الآلية داخل فرع الحجب — كل نبضة كانت
#: تجري فحصًا قسريًا كاملًا (بإقلاع رمل حقيقي) كل 0.5ث فتزاحم الطلبات
#: اليدوية وقاعدة SQLite. إعادة الفحص الآلية كل 5ث تكفي للتوفير الآلي.
_AUTO_RECHECK_INTERVAL_S = 5.0

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
        probe_injections: dict | None = None,
    ):
        self._sessions = sessions
        self._router_factory = router_factory
        self._planner_factory = planner_factory
        self._on_event = on_event
        self._role_mappings_provider = role_mappings_provider
        self._max_step_failures = max(1, int(max_step_failures))
        # (AES-EXP-04 §6) حقن مسبارات القدرات للاختبارات — نفس عقد
        # registry.run_probe المعلن (search_fn/fetch_fn/https_fn/…
        # «للاختبارات حصرًا»). None في الإنتاج = المسار الحقيقي كاملًا.
        self._probe_injections = probe_injections or None

    # ------------------------------------------------------------------ #
    # الأحداث — دائمة + بث لحظي
    # ------------------------------------------------------------------ #

    def _emit(self, project_id: int, kind: str, payload: dict) -> None:
        event_id = service.add_event(self._sessions, project_id, kind,
                                     payload)
        if self._on_event is not None:
            try:
                self._on_event({
                    "project_id": project_id, "kind": kind,
                    "payload": payload, "event_id": event_id,
                })
            except Exception:  # noqa: BLE001 — المستقبِل لا يكسر الحلقة
                pass

    # ------------------------------------------------------------------ #
    # العمليات العليا — يستدعيها الـAPI
    # ------------------------------------------------------------------ #

    def create_project(self, name: str, objective: str,
                        execution_policy: str = "STRICT_ISOLATED") -> dict:
        if not objective or not objective.strip():
            raise EngineError("الهدف مطلوب — المشروع بلا هدف لا معنى له")
        try:
            return service.create_project(
                self._sessions, name=name.strip(), objective=objective.strip(),
                execution_policy=execution_policy,
            )
        except ValueError as error:
            raise EngineError(str(error)) from error

    def generate_plan(self, project_id: int) -> dict:
        """توليد الخطة (§4) — حي حصرًا: فشل النموذج = فشل صريح لا خطة ملفقة.

        (013.4 §1) هذا المسار **المتزامن** يبقى للنداء الداخلي المباشر
        والاختبارات؛ الواجهة والـAPI يمرّان حصرًا عبر
        ``start_plan_generation`` — أمر خلفي محدود (جلسة/نبضة/إيجار/
        تصنيف فشل) لا استدعاءً حاجزًا داخل الطلب.
        """
        project = self._project(project_id)
        if project["status"] in TERMINAL_STATES:
            raise EngineError(
                f"المشروع في حالة نهائية ({project['status']}) — لا توليد خطة"
            )
        previous = service.latest_plan(self._sessions, project_id)
        return self._generate_plan(project, previous_failure=None)

    def start_plan_generation(self, project_id: int, *,
                              previous_failure: dict | None = None,
                              reason: str = "توليد الخطة") -> dict:
        """أمر توليد خطة خلفي (013.4 §1-§3) — فوري الوصف بطيء التنفيذ.

        لا استدعاء LLM داخل الطلب أبدًا: جلسة تخطيط دائمة (GENERATING
        بنبضة وإيجار) + خيط منفّذ مُتتبَّع (request_id/provider/model)
        + أحداث PLANNING_STARTED/PLAN_GENERATING/MODEL_CALL_*/
        PLAN_CREATED|PLANNING_FAILED. الفشل مصنّف لا صامت، وموت
        العملية يوسمه كلب الإيجار INTERRUPTED — لا PLANNING أبديًا.
        """
        from workflow import planning_runtime

        return planning_runtime.start_planning(
            int(project_id),
            sessions=self._sessions,
            engine_factory=lambda: self,
            on_live_event=self._on_event,
            previous_failure=previous_failure,
            reason=reason,
        )

    # (013.4 §1) واجهات يحتاجها زمن تشغيل التخطيط — عمومية صريحة
    def role_selections(self) -> dict:
        """ربط الأدوار — للعموم لا للخاصية الخاصة."""
        return self._role_selections()

    def build_planner(self):
        """بناء المخطط الحي — نفس مصنع المحرك، علني لجلسة التخطيط."""
        return self._build_planner()

    def record_generated_plan(self, project_id: int, plan_data: dict, *,
                              generated_by: dict | None = None,
                              previous_failure: dict | None = None) -> dict:
        """تدوين خطة مولّدة (013.4 §2) — الجزء الدائم المشترك.

        خطة v جديدة ← حلّ محل السابقة ← AWAITING_OWNER_APPROVAL ←
        بوابة اعتماد ← حدث PLAN_APPROVAL_REQUIRED. يُستدعى من المسار
        المتزامن (_generate_plan) ومن جلسة التخطيط الخلفية معًا —
        مصدر واحد للتدوين لا مسارين يفترقان.
        """
        previous = service.latest_plan(self._sessions, int(project_id))
        supersedes = previous["id"] if previous else None
        plan = service.create_plan(
            self._sessions, int(project_id), plan_data,
            supersedes_plan_id=supersedes,
            revision_reason=(
                (previous_failure or {}).get("reason", "") if supersedes
                else ""
            ),
            revision_evidence=previous_failure or {},
        )
        if supersedes:
            service.supersede_plan(self._sessions, supersedes)
        service.update_project(
            self._sessions, int(project_id),
            status="AWAITING_OWNER_APPROVAL", last_error="",
        )
        gate_id = service.open_gate(
            self._sessions, int(project_id), "PLAN_APPROVAL",
            f"اعتماد الخطة v{plan['version']} — "
            f"{len(plan['phases'])} مرحلة",
            {"plan_id": plan["id"], "version": plan["version"]},
        )
        self._emit(int(project_id), "PLAN_APPROVAL_REQUIRED",
                   {"plan_id": plan["id"], "gate_id": gate_id,
                    "generated_by": generated_by or {}})
        return plan

    def _generate_plan(self, project: dict, *,
                       previous_failure: dict | None = None) -> dict:
        """توليد خطة جديدة (v1 أو مراجعة) — PLANNING → نتيجة صادقة.

        (013.4 §1) المسار المتزامن الداخلي؛ كل استدعاء خارجي يمر عبر
        start_plan_generation (خلفي محدود). الفشل يُصنّف عبر زمن
        التشغيل؛ هذا المسار يوثّق السبب الحرفي في last_error.
        """
        project_id = project["id"]
        service.update_project(self._sessions, project_id, status="PLANNING")
        try:
            planner = self._build_planner()
            plan_data = planner.generate(
                project["objective"], previous_failure=previous_failure
            )
        except Exception as error:  # noqa: BLE001 — فشل صريح موثق
            from router.call_tracker import (
                classify_failure,
                is_transient_provider_failure,
            )

            error_class, _detail = classify_failure(error)
            if is_transient_provider_failure(error_class):
                # (RLR-001 §1) فشل اتصال عابر لا يسقط المشروع إلى DRAFT:
                # الحالة تُحفظ قابلة للاستئناف والسبب مصنّف للمالك مع
                # الإجراء التالي — لا صمت ولا نجاح وهمي.
                service.update_project(
                    self._sessions, project_id, status="PAUSED",
                    last_error=f"انتظار المزود [{error_class}]: {error}",
                )
                self._emit(project_id, "PROVIDER_TRANSIENT_FAILURE", {
                    "phase": "PLANNING", "error_class": error_class,
                    "error_detail": str(error)[:400],
                    "next_action": "يُستأنف التوليد عند عودة الاتصال "
                                   "أو بإعادة الاستئناف يدويًا",
                    "retry_available": True,
                })
                raise EngineError(
                    f"انتظار المزود [{error_class}]: {error}"
                ) from error
            service.update_project(
                self._sessions, project_id, status="DRAFT",
                last_error=f"فشل توليد الخطة [{error_class}]: {error}",
            )
            self._emit(project_id, "PLANNING_FAILED", {
                "error_class": error_class,
                "error_detail": str(error)[:400],
                "sync": True, "retry_available": True,
            })
            raise EngineError(f"فشل توليد الخطة [{error_class}]: {error}") \
                from error

        return self.record_generated_plan(
            project_id, plan_data,
            previous_failure=previous_failure,
        )

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
        if gate is not None and gate["status"] == "PENDING":
            service.resolve_gate(self._sessions, gate["id"], approved=approved)
            self._emit(project_id, "OWNER_GATE_RESOLVED",
                       {"gate_id": gate["id"], "approved": approved})
        if not approved:
            # (013.4 §1) رفض = إعادة توليد **خلفية** بتغذية المالك
            # الراجعة — لا استدعاء LLM حاجزًا داخل الطلب؛ الجلسة
            # تحمل النبضة/الإيجار/التصنيف والأحداث تصل عبر التيار.
            service.update_project(self._sessions, project_id,
                                   status="REVISING", last_error="")
            planning = self.start_plan_generation(
                project_id,
                previous_failure={
                    "reason": "رفض المالك للخطة",
                    "feedback": feedback,
                },
                reason="إعادة توليد بعد رفض المالك",
            )
            project_row = service.get_project(self._sessions, project_id)
            return {**project_row, "planning": planning,
                    "revision_pending": True}
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
                    and gate["status"] == "PENDING"
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

    def request_stop(self, project_id: int, reason: str = "",
                     *, final: bool = False) -> dict:
        """طلب إيقاف — علم ذرّي يُكرَّم عند أقرب checkpoint (§9).

        (013.4 §12+§13) نيتان معلنتان:
        - ``final=False`` ← إيقاف مؤقت: PAUSED بلقطة قابلة للاستئناف
          من نفس الوظيفة الدائمة.
        - ``final=True`` ← إيقاف نهائي: STOPPED دائمة مع حفظ كل شيء
          (الأحداث/الأدلة/اللقطات/التاريخ لا تُمس أبدًا).

        (013.5 §K) **إلغاء حقيقي أثناء التخطيط**: إن كان توليد جارٍ
        فالاستدعاء يُقطع فعلًا من خيطه (``cancel_planning``) — لا علم
        تجميلي على صف المشروع بينما الخيط يواصل العمل.
        """
        from workflow import planning_runtime

        self._project(project_id)
        _STOP_INTENTS[int(project_id)] = "stop" if final else "pause"
        service.update_project(self._sessions, project_id,
                               stop_requested=True)
        cancel_result = planning_runtime.cancel_planning(
            self._sessions, project_id,
            reason=reason or ("إيقاف نهائي من المالك" if final
                              else "إيقاف مؤقت من المالك"),
            final=final,
            on_live_event=self._on_event,
        )
        controller = _ACTIVE_CONTROLLERS.get(project_id)
        if controller is not None:
            controller.request_stop(
                f"project-{project_id}", by="owner", reason=reason
            )
        if final:
            self._emit(project_id, "OWNER_STOP_REQUESTED", {
                "reason": reason, "final": True,
                "planning_cancelled": bool(cancel_result.get("cancelled")),
            })
        project = service.get_project(self._sessions, project_id)
        return {**project, "planning_cancel": cancel_result}

    # ------------------------------------------------------------------ #
    # أزرار التحكم الحقيقية (013.4 §11-§17) — كل زر أمر دائم
    # ------------------------------------------------------------------ #

    def pause(self, project_id: int, reason: str = "") -> dict:
        """إيقاف مؤقت (013.4 §13) — RUNNING → PAUSING → PAUSED.

        نفس آلية الإيقاف الصادقة (علم ذرّي يُكرَّم عند أقرب checkpoint)
        لكن بنيّة معلنة: الحلقة تكتب لقطة، الخطوة الجارية تعود READY،
        والوظيفة تنتظر — الاستئناف من نفس الوظيفة الدائمة بلا نسخ.
        """
        project = self._project(project_id)
        if project["status"] not in ("RUNNING", "READY", "REVISING",
                                     "PLANNING"):
            raise EngineError(
                f"المشروع في حالة {project['status']} — لا إيقافًا مؤقتًا "
                "من هنا"
            )
        self._emit(project_id, "PROJECT_PAUSING", {"reason": reason})
        result = self.request_stop(
            project_id, reason or "إيقاف مؤقت من المالك"
        )
        # (013.5 §K) الإيقاف المؤقت أثناء التخطيط **يلغي التوليد فعلًا**:
        # المشروع يصير PAUSED وجلسته CANCELLED — لا انتظار حتى ينتهي
        # استدعاء طويل ثم تُقلب الحالة. الاستئناف قرار مالك صريح يعيد
        # التوليد بجلسة جديدة (retry_of) فلا نجاح مُدّعى من فراغ.
        paused = self._pause(project, reason or "إيقاف مؤقت من المالك")
        # إرجاع المشروع المحدث بعد الإيقاف المؤقت
        updated_project = service.get_project(self._sessions, project_id)
        return {**updated_project, "pausing": True, "pause_result": paused}

    def retry(self, project_id: int) -> dict:
        """إعادة المحاولة (013.4 §11) — آخر فشل يحدد الإجراء الصادق.

        - تخطيط فاشل/منقطع → إعادة توليد خطة (جلسة جديدة retry_of).
        - خطوة فاشلة/محجوبة → READY + إطلاق الحلقة من checkpoint.
        - وظيفة فاشلة (خارج كل التزامن) → إطلاق صريح.
        لا مسار «تجاهل الفشل»: كل فرع يعلن ما يعيده ولماذا.
        """
        from workflow import planning_runtime

        project = self._project(project_id)
        project_id = project["id"]
        session = planning_runtime.latest_session(self._sessions,
                                                  project_id)
        if project["status"] == "PLANNING" or (
            session is not None and session["state"] == "GENERATING"
        ):
            raise EngineError(
                "التوليد جارٍ الآن — انتظر نتيجته أو أوقفه أولًا"
            )
        if session is not None and session["state"] in (
            "FAILED", "INTERRUPTED"
        ):
            planning = self.start_plan_generation(
                project_id,
                previous_failure={
                    "reason": f"إعادة صريحة بعد {session['error_class']}",
                    "last_error": session.get("error_detail", ""),
                },
                reason="إعادة المحاولة من المالك",
            )
            self._emit(project_id, "RETRY_REQUESTED", {
                "target": "planning",
                "from_session": session["id"],
                "error_class": session["error_class"],
            })
            return {"retried": "planning", "planning": planning}

        plan = self._active_plan(project)
        failed_steps = [
            s for s in self._pending_steps(
                project_id, plan_id=plan["id"] if plan else None
            )
            if s["status"] in ("FAILED", "BLOCKED")
        ]
        if failed_steps and plan is not None:
            for step in failed_steps:
                service.update_step(self._sessions, step["id"],
                                    status="READY", last_error="")
            service.update_project(self._sessions, project_id,
                                   status="READY", last_error="",
                                   stop_requested=False)
            self._emit(project_id, "RETRY_REQUESTED", {
                "target": "steps",
                "step_ids": [s["id"] for s in failed_steps],
            })
            return {"retried": "steps",
                    "step_ids": [s["id"] for s in failed_steps]}
        # لا فشل محدد — إطلاق صريح للحلقة إن كان المشروع قابلًا للتشغيل
        if project["status"] in ("PAUSED", "BLOCKED", "READY", "DRAFT"):
            if project["status"] == "BLOCKED":
                gates = [g for g in service.open_gates(
                    self._sessions, project_id
                ) if g["status"] == "PENDING"]
                if gates:
                    raise EngineError(
                        "بوابات قرار تنتظرك — عالجها أولًا: "
                        + "؛ ".join(g["kind"] for g in gates)
                    )
            service.update_project(self._sessions, project_id,
                                   stop_requested=False)
            self._emit(project_id, "RETRY_REQUESTED",
                       {"target": "run"})
            return {"retried": "run"}
        raise EngineError(
            f"لا شيء يعاد محاكمته — الحالة {project['status']} "
            "بلا فشل تخطيط أو خطوة"
        )

    def duplicate_project(self, project_id: int, *,
                          name: str = "") -> dict:
        """تكرار مشروع (013.4 §15) — نسخة جديدة لا تمس الأصل أبدًا.

        النسخة: الهدف + الاسم + السياسة + الخطة المعتمدة إن وجدت
        (بنيتها لا سجلها) بحالة DRAFT جديدة وoriginal_id يشير للأصل.
        الأدلة/الأحداث/الوظائف لا تُنسخ — ملك جولة الأصل وحدها.
        """
        source = self._project(project_id)
        duplicate = service.duplicate_project(
            self._sessions, source, name=name
        )
        self._emit(duplicate["id"], "PROJECT_DUPLICATED", {
            "original_id": source["id"],
            "source_id": source["id"],
            "copied_at": duplicate["created_at"],
            "note": "نسخة من مشروع قائم — الأصل لم يُمس",
        })
        return duplicate

    def archive_project(self, project_id: int) -> dict:
        """أرشفة (013.4 §17) — دورة حياة لا حذفًا.

        المشروع المؤرشف: يبقى قابلًا للاستعلام والاسترجاع، لا
        يُنفَّذ، ولا يظهر في القائمة النشطة افتراضيًا. كل الأحداث
        والأدلة والخطة تبقى كما هي حرفيًا.
        """
        project = self._project(project_id)
        if project["status"] == "RUNNING":
            raise EngineError(
                "المشروع يعمل — أوقفه أو أوقفه مؤقتًا قبل الأرشفة"
            )
        if project.get("archived_at"):
            return project   # أرشفة مرتين = نفس الحالة (idempotent)
        result = service.archive_project(self._sessions, project_id)
        self._emit(project_id, "PROJECT_ARCHIVED", {
            "archived_at": result["archived_at"],
            "note": "الأرشفة لا تحذف بيانات — الاسترجاع متاح دائمًا",
        })
        return result

    def restore_project(self, project_id: int) -> dict:
        """استرجاع من الأرشيف (013.4 §45) — عودة للحياة النشطة."""
        project = self._project(project_id)
        if not project.get("archived_at"):
            return project
        result = service.restore_project(self._sessions, project_id)
        self._emit(project_id, "PROJECT_RESTORED", {
            "from_archived_at": project["archived_at"],
        })
        return result

    def rename_project(self, project_id: int, name: str) -> dict:
        """إعادة تسمية — أمر دائم بحدث معلن (013.4 §11)."""
        project = self._project(project_id)
        name = (name or "").strip()
        if not name:
            raise EngineError("الاسم الجديد مطلوب — لا فراغًا")
        result = service.rename_project(self._sessions, project_id, name)
        self._emit(project_id, "PROJECT_RENAMED", {
            "from": project["name"], "to": name,
        })
        return result

    @staticmethod
    def _planning_wait_text(view: dict) -> str:
        """نص «ما الذي ينتظره التخطيط» (013.4 §3) — حرفي لا عام."""
        detail = view.get("detail") or {}
        waiting = view.get("waiting_for") or {}
        if not view.get("active"):
            return "لا جلسة تخطيط نشطة"
        parts = []
        if waiting.get("provider"):
            parts.append(f"المزود {waiting.get('provider')}")
        if waiting.get("model"):
            parts.append(f"النموذج {waiting.get('model')}")
        if waiting.get("request_id"):
            parts.append(f"الطلب {waiting.get('request_id')}")
        if detail.get("elapsed_s") is not None:
            parts.append(f"مضى {detail.get('elapsed_s')}ث")
        return "ينتظر استدعاء النموذج (" + " · ".join(parts) + ")" \
            if parts else "ينتظر استدعاء النموذج"

    def resume(self, project_id: int) -> dict:
        """استئناف صريح — من checkpoint بعد إيقاف أو قرار مالك (§9)."""
        project = self._project(project_id)
        if project["status"] not in ("PAUSED", "BLOCKED", "READY", "REVISING"):
            raise EngineError(
                f"المشروع في حالة {project['status']} — لا استئناف من هنا"
            )
        if project["status"] == "BLOCKED":
            gates = service.open_gates(self._sessions, project_id)
            pending = [g for g in gates if g["status"] == "PENDING"]
            if pending:
                raise EngineError(
                    "بوابات قرار تنتظرك — عالجها أولًا: "
                    + "؛ ".join(g["kind"] for g in pending)
                )
            # (011 §19) بوابات توفير فقط: الاستئناف يعيد الفحص —
            # نجح = استمر بلا إعادة اعتماد؛ فشل = السبب الحقيقي.
            if gates:
                recheck = self.recheck_preflight(project_id)
                if recheck["verdict"] != "PASS":
                    raise EngineError(
                        "الاستئناف ممكن بعد توفير المتطلبات — "
                        + recheck["summary"]
                    )
        # (013.5 §K) استئناف صادق: مشروع أُوقف **أثناء التخطيط** لا خطة
        # له — تشغيل الحلقة عليه نجاح مُدّعى من فراغ. الاستئناف الصادق
        # يعيده DRAFT ويعلن أن الخطوة التالية توليدُ خطة (قرار المالك).
        from workflow import planning_runtime

        session = planning_runtime.latest_session(self._sessions, project_id)
        needs_planning = (
            project["status"] == "PAUSED"
            and service.latest_plan(self._sessions, project_id) is None
            and session is not None
            and session["state"] == "CANCELLED"
        )
        if needs_planning:
            service.update_project(self._sessions, project_id,
                                   stop_requested=False, status="DRAFT",
                                   last_error="")
            self._emit(project_id, "PROJECT_RESUMED", {
                "from_status": project["status"],
                "to_status": "DRAFT",
                "needs_planning": True,
                "reason": "أُوقف أثناء التوليد فلا خطة بعد — الاستئناف "
                          "يعيد DRAFT ويطلب توليدًا صريحًا",
            })
            return service.get_project(self._sessions, project_id)
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
            # (013.4 §1) موافقة على مراجعة الخطة ← توليد v جديدة
            # بسياق الفشل — خلفيًا محدودًا (جلسة/نبضة/إيجار) لا
            # استدعاءً حاجزًا داخل طلب حل البوابة.
            failure = self._last_failure_context(project_id)
            service.update_project(self._sessions, project_id,
                                   status="REVISING", last_error="")
            self.start_plan_generation(
                project_id, previous_failure=failure,
                reason="مراجعة خطة بعد بوابة مالك",
            )
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
        """سياق الفشل الأخير — يُمرر للمخطط كي تراه الخطة v الجديدة.

        (RLR-001 §4d-6) سياق المخطط يضم قائمة نقص المُتحقّق الأخيرة —
        كان يرى «الدورة لم تكتمل أدلةً» العامة فيعيد نفس المعايير
        غير القابلة للحكم (تنفيذ أوامر/مجلدات نظام) فتدور الحلقة
        عمياء. الآن يرى النقص الحرفي فيكتب معايير قابلة للحكم من
        ملفات مكتوبة ومحتواها.
        """
        executions = service.list_executions(self._sessions, project_id)
        failed = [e for e in executions if e["status"] == "FAILED"]
        if not failed:
            return {}
        last = failed[0]
        context = {
            "reason": "فشل تنفيذ متكرر استنفد المحاولات",
            "last_error": last["error"][:500],
            "step_objective": self._step_objective(last["step_id"]),
        }
        verifier_missing = self._latest_verifier_missing(project_id)
        if verifier_missing:
            context["verifier_missing"] = verifier_missing
            context["criteria_contract"] = (
                "اكتب معايير قبول قابلة للحكم من ملفات مكتوبة ومحتواها "
                "حصرًا (وجود ملف بمساره النسبي، محتوى نصي محدد) — "
                "لا تطلب تنفيذ أوامر (npm install/playwright run) ولا "
                "مجلدات نظام تولَّد بأدوات خارجية (node_modules) ولا "
                "لقطات متصفح ضمن معايير البناء"
            )
        return context

    def _latest_verifier_missing(self, project_id: int) -> list:
        """قائمة نقص آخر TASK_VERIFICATION — من الأحداث الدائمة."""
        try:
            rows = service.list_events(
                self._sessions, project_id, limit=60
            ) if hasattr(service, "list_events") else []
        except Exception:  # noqa: BLE001 — السياق الإضافي اختياري
            rows = []
        for row in reversed(rows if isinstance(rows, list) else []):
            kind = str(row.get("kind", "")) if isinstance(row, dict) else ""
            if kind != "TASK_VERIFICATION":
                continue
            payload = row.get("payload") if isinstance(row, dict) else None
            if isinstance(payload, str):
                try:
                    import json as _json
                    payload = _json.loads(payload)
                except Exception:  # noqa: BLE001
                    payload = None
            if isinstance(payload, dict):
                missing = payload.get("missing") or []
                if missing:
                    return [str(m)[:160] for m in missing][:4]
        return []

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
            pending = [g for g in gates if g["status"] == "PENDING"]
            provisioning = [g for g in gates if g["status"] == "BLOCKED"]
            if provisioning and not pending:
                # (011 §19) BLOCKED ← RECHECK ← READY ← OPEN: التوفير
                # اكتمل؟ أعد الفحص تلقائيًا — بلا إعادة اعتماد الخطة.
                # (AES-EXP-04 §6) بخنق زمني: لا فحص قسري كل نبضة.
                now_mono = time.monotonic()
                last_recheck = getattr(self, "_last_auto_recheck_at", 0.0)
                if now_mono - last_recheck >= _AUTO_RECHECK_INTERVAL_S:
                    self._last_auto_recheck_at = now_mono
                    recheck = self.recheck_preflight(project_id)
                    self._last_recheck_result = recheck
                else:
                    # نبضة خنق: نعيد استخدام آخر نتيجة فحص حقيقية (≤5ث)
                    # كاملة الأ shape — التصنيف يقرأ blocked منها كما هي
                    recheck = getattr(self, "_last_recheck_result", None)
                    if not recheck:
                        recheck = {
                            "verdict": "BLOCKED",
                            "summary": (
                                "الفحص الأخير محجوب — إعادة الفحص الآلية "
                                "مبرمجة كل "
                                f"{_AUTO_RECHECK_INTERVAL_S:.0f}ث"
                            ),
                            "blocked": [],
                            "matrix": [],
                        }
                if recheck["verdict"] == "PASS":
                    return self.tick(project_id)
                return {
                    "action": "blocked", "blocked_kind": "preflight",
                    "reason": recheck["summary"],
                    "gates": [g["kind"] for g in gates],
                    "preflight": {
                        "verdict": recheck["verdict"],
                        "summary": recheck["summary"],
                        "matrix": recheck.get("matrix", []),
                        # (AES-EXP-04 تصحيح): قائمة المحجوبات لازمة
                        # للتصنيف الصادق (sandbox وحده = WAITING_WORKER)
                        # — كان غيابها يصنف كل حجب بعد التحقق CAPABILITY
                        "blocked": recheck.get("blocked", []),
                    },
                }
            return {"action": "blocked",
                    "reason": "بوابة قرار تنتظر المالك",
                    "gates": [g["kind"] for g in gates]}
        if status == "AWAITING_OWNER_APPROVAL":
            return {"action": "wait_owner",
                    "reason": "الخطة تنتظر اعتماد المالك"}

        # إيقاف مطلوب — يُكرَّم فورًا عند هذا الحد الآمن (§9)؛ النية
        # (مؤقت/نهائي 013.4 §12) مسجلة مع الطلب نفسه
        if project["stop_requested"]:
            intent = _STOP_INTENTS.get(project_id, "pause")
            return self._pause(
                project, "طلب إيقاف المالك", final=(intent == "stop"),
            )

        # لا خطة معتمدة → توليد (DRAFT/REVISING) — الحلقة تتضمن Planner
        # (013.4 §1+§3) التوليد **أمر خلفي محدود** — لا استدعاء LLM
        # داخل الحلقة أبدًا: الجلسة تحمل المزود/النموذج/request_id/
        # النبضة/الإيجار، والحلقة تنتظر wait_planning بتفسير حرفي.
        plan = self._active_plan(project)
        if plan is None:
            from workflow import planning_runtime

            session = planning_runtime.latest_session(
                self._sessions, project_id
            )
            if status == "PLANNING" or (
                session is not None and session["state"] == "GENERATING"
            ):
                view = planning_runtime.session_view(
                    self._sessions, project_id
                )
                return {
                    "action": "wait_planning",
                    "reason": "توليد الخطة جارٍ — "
                              + self._planning_wait_text(view),
                    "planning": view,
                }
            if session is not None and session["state"] in (
                "FAILED", "INTERRUPTED"
            ):
                return {
                    "action": "failed",
                    "reason": (
                        f"توليد الخطة فشل "
                        f"[{session.get('error_class', '?')}] — "
                        "أعد المحاولة أو راجع المزود"
                    ),
                    "planning": session,
                }
            failure = None
            latest = service.latest_plan(self._sessions, project_id)
            if latest is not None and latest["status"] == "REJECTED":
                failure = {"reason": "رفض سابق", "feedback": ""}
            self.start_plan_generation(
                project_id, previous_failure=failure,
                reason="الحلقة بلا خطة معتمدة — توليد خطة",
            )
            return {"action": "wait_planning",
                    "reason": "بدأ توليد الخطة خلفيًا — الجلسة تحمل "
                              "المزود والنموذج والنبضة",
                    "planning": planning_runtime.session_view(
                        self._sessions, project_id
                    )}

        # (011 §2+§27) عند الجاهزية: حاجز الفحص قبل أول خطوة —
        # APPROVED + PASS = OPEN؛ APPROVED + BLOCKED = بوابة توفير
        if status == "READY":
            blocked = self._preflight_gate(project, plan)
            if blocked is not None:
                return blocked

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
                "none", "paused", "stopped", "blocked", "wait_owner",
                "failed", "wait_planning",
            ):
                break
        last["ticks"] = ticks
        return last

    # ------------------------------------------------------------------ #
    # فحص ما قبل التنفيذ (011 §2+§17-§19+§27) — policy-aware
    # ------------------------------------------------------------------ #

    def _unready_roles(self, role_selections=None, router=None) -> list[dict]:
        """الأدوار بلا مزود قابل للحل — نفس فحص 007.1 §17 مستخرجًا."""
        role_selections = role_selections or self._role_selections()
        router = router or self._router_factory()
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
        return unready

    def _preflight_goal(self, project: dict, plan: dict) -> str:
        """هدف الفحص — الهدف الكامل بمعايير قبول الخطة (011 §17)."""
        goal = project["objective"]
        criteria = plan.get("acceptance_criteria") or []
        if criteria:
            goal += "\nمعايير القبول:\n- " + "\n- ".join(criteria[:6])
        return goal

    def _run_preflight(self, project: dict, plan: dict, *,
                       force: bool = False) -> dict:
        """تنفيذ الفحص المسبق الفعلي — policy من المشروع (011 §26).

        (AES-EXP-04 §6): حقن المسبارات (إن وُجد) يمر عبر العقد المعلن
        نفسه — run_probe_fn — فلا مسار مزدوج ولا تجاوز للحقيقة.
        """
        from readiness import preflight as preflight_mod
        from readiness import registry as readiness_registry

        unready = self._unready_roles()
        injected_probe = None
        if self._probe_injections:
            injections = dict(self._probe_injections)

            def injected_probe(sessions, capability_id: str) -> dict:
                return readiness_registry.run_probe(
                    sessions, capability_id, **injections
                )

        return preflight_mod.task_preflight(
            self._sessions, self._preflight_goal(project, plan),
            policy=project.get("execution_policy") or "STRICT_ISOLATED",
            force=force,
            run_probe_fn=injected_probe,
            llm_ready=not unready,
            llm_detail={"unready_roles": unready} if unready else None,
        )

    def _emit_preflight(self, project_id: int, result: dict) -> None:
        """أحداث الفحص — المصفوفة كاملة تصل الواجهة (011 §17)."""
        kind = "PREFLIGHT_PASS" if result["verdict"] == "PASS" \
            else "PREFLIGHT_BLOCKED"
        self._emit(project_id, kind, {
            "verdict": result["verdict"],
            "summary": result["summary"],
            "policy": result.get("policy"),
            "matrix": result.get("matrix", []),
            "blocked": [
                {
                    "capability_id": b["capability_id"],
                    "status": b["status"],
                    "reason": (b.get("reason") or "")[:300],
                    "required_environment": b.get("required_environment", ""),
                    "owner_action": b.get("owner_action"),
                    "recovery": b.get("recovery", ""),
                }
                for b in result["blocked"]
            ],
            "environment": (
                {"id": result["environment"]["id"],
                 "name": result["environment"]["name"],
                 "isolation": result["environment"].get("isolation", "")}
                if result.get("environment") else None
            ),
        })

    def _preflight_gate(self, project: dict, plan: dict) -> dict | None:
        """حاجز الجاهزية عند READY (011 §2+§27) — PASS=None، BLOCKED=بوابة.

        (013 §4) السلسلة معلنة حدثًا حدثًا — كل خطوة قابلة للرؤية:
        PREFLIGHT_STARTED ← CAPABILITIES_EVALUATED ←
        ENVIRONMENT_CHECK_STARTED ← ENVIRONMENT_READY | PREFLIGHT_BLOCKED
        ← EXECUTION_OPENED. لا فحص صامت أبدًا.

        APPROVED + preflight BLOCKED = APPROVED_BUT_BLOCKED: بوابة توفير
        (status=BLOCKED) تُحل بإعادة الفحص بعد التوفير — لا إعادة
        اعتماد الخطة أبدًا ما لم تتغير (§19).
        """
        project_id = project["id"]
        self._emit(project_id, "PREFLIGHT_STARTED", {
            "plan_id": plan["id"], "version": plan["version"],
            "policy": project.get("execution_policy") or "STRICT_ISOLATED",
        })
        result = self._run_preflight(project, plan)
        self._emit(project_id, "CAPABILITIES_EVALUATED", {
            "verdict": result["verdict"],
            "required": result.get("required", []),
            "capabilities": [
                {"capability_id": c["capability_id"], "status": c["status"],
                 "ok": bool(c.get("ok"))}
                for c in result.get("capabilities", [])
            ],
            "matrix": result.get("matrix", []),
        })
        self._emit(project_id, "ENVIRONMENT_CHECK_STARTED", {
            "environment": (
                {"id": result["environment"]["id"],
                 "name": result["environment"]["name"],
                 "isolation": result["environment"].get("isolation", "")}
                if result.get("environment") else None
            ),
            "policy": result.get("policy"),
        })
        self._emit_preflight(project_id, result)
        if result["verdict"] == "PASS":
            self._emit(project_id, "ENVIRONMENT_READY", {
                "environment": (
                    {"id": result["environment"]["id"],
                     "name": result["environment"]["name"],
                     "isolation": result["environment"].get("isolation", "")}
                    if result.get("environment") else None
                ),
            })
            self._emit(project_id, "EXECUTION_OPENED", {
                "plan_id": plan["id"], "version": plan["version"],
                "summary": "الخطة معتمدة والقدرات جاهزة — التنفيذ مفتوح",
            })
            return None
        blocked = result["blocked"]
        # (007.1 §17 يبقى سليمًا) المزود غير الجاهز وحده يعالجه حاجز
        # الخطوة بدليل EXECUTION_BLOCKED وبوابة PROVIDER_ACTION_REQUIRED —
        # لا نبني مسارًا موازيًا يكسر عقد الدليل. الفحص المسبق يكتفي
        # ببث المصفوفة (حدث PREFLIGHT_BLOCKED أعلاه).
        if blocked and all(b["capability_id"] == "llm" for b in blocked):
            return None
        reason = "؛ ".join(
            f"{b['capability_id']} ({b['status']})" for b in blocked
        )
        owner_action = next(
            (b.get("owner_action") for b in blocked if b.get("owner_action")),
            "",
        )
        required_env = next(
            (b.get("required_environment")
             for b in blocked if b.get("required_environment")),
            "",
        )
        gate_id = service.open_gate(
            self._sessions, project["id"], "PREFLIGHT_BLOCKED", reason,
            {
                "matrix": result.get("matrix", []),
                "blocked": [
                    {"capability_id": b["capability_id"],
                     "status": b["status"],
                     "owner_action": b.get("owner_action")}
                    for b in blocked
                ],
                "policy": result.get("policy"),
                "required_environment": required_env,
                "owner_action": owner_action,
                "recheck_hint": "أعد الفحص بعد التوفير — لا إعادة اعتماد",
            },
            status="BLOCKED",
        )
        service.update_project(
            self._sessions, project["id"], status="BLOCKED",
            last_error=result["summary"][:800],
        )
        return {
            "action": "blocked", "blocked_kind": "preflight",
            "reason": result["summary"], "gate_id": gate_id,
            "preflight": {
                "verdict": result["verdict"], "summary": result["summary"],
                "matrix": result.get("matrix", []),
                "blocked": [
                    {"capability_id": b["capability_id"],
                     "status": b["status"],
                     "required_environment": b.get("required_environment", ""),
                     "owner_action": b.get("owner_action")}
                    for b in blocked
                ],
            },
        }

    def recheck_preflight(self, project_id: int) -> dict:
        """إعادة الفحص بعد توفير (011 §19) — RECHECK ← READY ← OPEN.

        النجاح يحل بوابات التوفير آليًا (GATE_AUTO_RESOLVED) ويعيد
        المشروع READY — دون مساس قرار الاعتماد: الخطة لم تتغير.
        الفشل يبقي الحجب ويحدّث سببه بالنتيجة الحالية.
        """
        project = self._project(project_id)
        plan = self._active_plan(project)
        if plan is None:
            raise EngineError("لا خطة معتمدة تُعاد فحص جاهزيتها")
        # (AES-EXP-04 §6): إعادة الفحص الآلية تحترم مهل التخزين (TTL) —
        # القدرات حديثة الفحص تبقى مخزنة وما عادا جاهزًا يُعاد فحصه
        # فعلًا؛ force=True كان يعيد فحص web_search قسريًا (ميزانية كاملة)
        # في كل خنقة فبطئ الوظائف المنتظرة تحت الحمل.
        result = self._run_preflight(project, plan, force=False)
        # نفس شكل تفاصيل _emit_preflight — السبب الحقيقي يصل الواجهة
        # حرفيًا (011 §3: سبب دقيق لا placeholder)
        self._emit(project_id, "PREFLIGHT_RECHECKED", {
            "verdict": result["verdict"], "summary": result["summary"],
            "policy": result.get("policy"),
            "matrix": result.get("matrix", []),
            "blocked": [
                {
                    "capability_id": b["capability_id"],
                    "status": b["status"],
                    "reason": (b.get("reason") or "")[:300],
                    "required_environment": b.get("required_environment", ""),
                    "owner_action": b.get("owner_action"),
                    "recovery": b.get("recovery", ""),
                }
                for b in result["blocked"]
            ],
            "environment": (
                {"id": result["environment"]["id"],
                 "name": result["environment"]["name"],
                 "isolation": result["environment"].get("isolation", "")}
                if result.get("environment") else None
            ),
        })
        if result["verdict"] == "PASS":
            self._emit(project_id, "ENVIRONMENT_READY", {
                "environment": (
                    {"id": result["environment"]["id"],
                     "name": result["environment"]["name"]}
                    if result.get("environment") else None
                ),
                "recheck": True,
            })
            self._emit(project_id, "EXECUTION_OPENED", {
                "plan_id": plan["id"], "version": plan["version"],
                "summary": "إعادة فحص ناجحة بعد التوفير — التنفيذ مفتوح "
                           "بلا إعادة اعتماد",
            })
            for gate in service.open_gates(self._sessions, project_id):
                if gate["status"] == "BLOCKED":
                    service.auto_resolve_gate(
                        self._sessions, gate["id"],
                        note="إعادة فحص ناجحة بعد التوفير — التنفيذ مفتوح",
                    )
                    self._emit(project_id, "GATE_AUTO_RESOLVED", {
                        "gate_id": gate["id"], "kind": gate["kind"],
                        "note": "إعادة فحص ناجحة — لا إعادة اعتماد مطلوبة",
                    })
            if project["status"] == "BLOCKED":
                service.update_project(
                    self._sessions, project_id, status="READY",
                    last_error="",
                )
            self._emit(project_id, "PREFLIGHT_PASS", {
                "summary": result["summary"],
                "matrix": result.get("matrix", []),
            })
        return result

    def set_execution_policy(self, project_id: int, policy: str) -> dict:
        """سياسة تنفيذ المشروع (011 §26) — قرار مالك صريح مسجل."""
        from execution import policy as policy_mod

        if not policy_mod.is_valid_policy(policy):
            raise EngineError(
                f"سياسة تنفيذ غير مدعومة: {policy} — المدعوم: "
                + "، ".join(policy_mod.POLICIES)
            )
        project = self._project(project_id)
        if project["status"] == "RUNNING":
            raise EngineError(
                "لا تغيير سياسة أثناء تشغيل الحلقة — أوقف المشروع أولًا"
            )
        service.update_project(
            self._sessions, project_id, execution_policy=policy
        )
        self._emit(project_id, "EXECUTION_POLICY_CHANGED", {
            "from": project.get("execution_policy"), "to": policy,
            "note": policy_mod.policy_note(policy),
        })
        return service.get_project(self._sessions, project_id)

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
        unready = self._unready_roles(role_selections, router)
        if unready:
            return self._block_on_providers(project, plan, phase, step,
                                            unready)

        # 2) سجل التنفيذ الدائم (§7) — كل محاولة سجل مستقل
        attempt = step["attempts"] + 1
        workspace = PROJECTS_DIR / str(project_id) / "steps" / str(step["id"])
        workspace.mkdir(parents=True, exist_ok=True)
        # (013.7 §P14) أمر التنفيذ ومسار العمل
        command_text = step["objective"]
        if step.get("input"):
            command_text += f"\n\nالمدخلات: {step['input']}"
        if step.get("expected_output"):
            command_text += f"\nالمخرج المتوقع: {step['expected_output']}"
        if step.get("acceptance_criteria"):
            command_text += "\nمعايير القبول (تحقق حرفيًا):\n- " + \
                "\n- ".join(step["acceptance_criteria"])
        # أمانة ما بعد الانهيار: تنفيذ RUNNING بلا خيط حي (restart)
        # يُوسم فشلًا بسبب صريح — لا يبقى معلقًا كأنه حي (§9)
        self._fail_orphaned_executions(step["id"])
        execution_id = service.create_execution(
            self._sessions, step["id"], attempt=attempt,
            provider=str(role_selections.get("implementer")),
            model=str(getattr(role_selections.get("implementer"), "model", "")),
            workspace=str(workspace), agent_role="implementer",
            command=command_text, cwd=str(workspace),
            command_type="step_execution",
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
        self._emit(project_id, "ROLE_EXECUTING", {
            "step_id": step["id"], "execution_id": execution_id,
            "role": "implementer", "phase": "execution",
            "objective": step["objective"][:200],
        })

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

        # (013 §4+§28) أدوار الدورة وأدواتها تصل أحداثًا دائمة حيّة —
        # دور يبدأ = ROLE_EXECUTING (مرة لكل دور داخل التنفيذ)؛
        # أداة تستدعى = TOOL_EXECUTION (بدء/نجاح/فشل بمواقعها)؛
        # عملية متصفح = BROWSER_* (كل عملية قابلة للتسجيل §13).
        cycle_roles_seen: set[str] = {"implementer"}

        _CYCLE_ROLE_KINDS = {
            "plan": "thinker", "task_execution": "implementer",
            "verification_rollup": "verifier",
            "review_verdict": "reviewer", "arbiter_decision": "arbiter",
        }
        _TOOL_KINDS = {"tool.started", "tool.call", "tool.failed"}
        _BROWSER_DURABLE = {
            "browser.session.created": "BROWSER_SESSION_CREATED",
            "browser.navigate": "BROWSER_NAVIGATE",
            "browser.page.loaded": "BROWSER_PAGE_LOADED",
            "browser.click": "BROWSER_CLICK",
            "browser.type": "BROWSER_TYPE",
            "browser.screenshot": "BROWSER_SCREENSHOT",
            "browser.extract": "BROWSER_EXTRACT",
            "browser.download": "BROWSER_DOWNLOAD",
            "browser.session.closed": "BROWSER_SESSION_CLOSED",
            "browser.session.interrupted": "BROWSER_SESSION_INTERRUPTED",
        }

        def cycle_sink(event: dict) -> None:
            kind = str(event.get("kind", ""))
            if kind in _TOOL_KINDS:
                self._emit(project_id, "TOOL_EXECUTION", {
                    "step_id": step["id"],
                    "execution_id": execution_id,
                    "tool": event.get("tool", ""),
                    "phase": ({"tool.started": "started",
                               "tool.call": "succeeded",
                               "tool.failed": "failed"}).get(kind, ""),
                    "role": event.get("role", "implementer"),
                    "duration_ms": event.get("duration_ms", 0),
                    "execution_site": event.get("execution_site", ""),
                    "summary": str(event.get("args_summary")
                                    or event.get("query")
                                    or event.get("human")
                                    or "")[:200],
                    "error": str(event.get("error") or "")[:200],
                })
                # (AES-LIVE-FACTORY-E2E-001 المرحلة 4د) ملف يُكتب فعليًا
                # = حدث دائم باسم الملف والوكيل والبصمة — يسنده تبويب
                # الملفات إلى دور حقيقي لا اجتهاد. المسار نسبي للمشروع.
                if kind == "tool.call" and str(
                        event.get("tool", "")) in ("write_file",
                                                   "generate_pdf_arabic"):
                    summary = event.get("args_summary")
                    written = ""
                    if isinstance(summary, dict):
                        written = str(summary.get("path") or "")
                    if written:
                        marker = str(Path(workspace).resolve()) \
                            if workspace else ""
                        if marker and marker in written:
                            written = written.split(marker, 1)[1].lstrip("/")
                        self._emit(project_id, "FILE_WRITTEN", {
                            "step_id": step["id"],
                            "execution_id": execution_id,
                            "path": written[:300],
                            "role": event.get("role", "implementer"),
                            "sha256": str(
                                event.get("output_sha256") or "")[:64],
                        })
            elif kind in _BROWSER_DURABLE:
                payload = {
                    "step_id": step["id"],
                    "execution_id": execution_id,
                    "session_id": event.get("session_id", ""),
                    "url": event.get("url", ""),
                    "summary": str(event.get("title")
                                    or event.get("detail")
                                    or event.get("sha256", ""))[:160],
                    "bytes": event.get("bytes", 0),
                    "detail": {k: v for k, v in event.items()
                               if k not in ("kind", "role")},
                }
                self._emit(project_id, _BROWSER_DURABLE[kind], payload)
            elif kind.startswith("browser."):
                # عمليات متصفح أخرى (scroll/wait/upload/…) — أداة عامة
                self._emit(project_id, "TOOL_EXECUTION", {
                    "step_id": step["id"],
                    "execution_id": execution_id,
                    "tool": "browser", "phase": kind,
                    "role": event.get("role", "implementer"),
                    "summary": str(event.get("pixels")
                                    or event.get("waited_s")
                                    or event.get("file")
                                    or "")[:200],
                })
            elif kind in ("task_execution", "task_verification"):
                # (RLR-001 §1) نتيجة الدور الدورية تُخلَّد دائمًا — كانت
                # تذهب للبث الحي وحده فيبتلع سبب الفشل الحقيقي (stderr/
                # missing_evidence) وتبقى الرسالة العامة وحدها في السجل.
                details = event.get("details") or {}
                self._emit(
                    project_id,
                    "TASK_EXECUTION" if kind == "task_execution"
                    else "TASK_VERIFICATION",
                    {
                        "step_id": step["id"],
                        "execution_id": execution_id,
                        "role": event.get("role", "implementer"),
                        "status": str(details.get("status")
                                      or details.get("verdict") or "")[:40],
                        "summary": str(event.get("text") or "")[:220],
                        "stderr": str(details.get("stderr") or "")[:400],
                        "missing": list(
                            details.get("missing_evidence") or [])[:4],
                        "duration_ms": event.get("duration_ms", 0),
                    },
                )
            else:
                cycle_role = _CYCLE_ROLE_KINDS.get(kind)
                if cycle_role and cycle_role not in cycle_roles_seen:
                    cycle_roles_seen.add(cycle_role)
                    self._emit(project_id, "ROLE_EXECUTING", {
                        "step_id": step["id"],
                        "execution_id": execution_id,
                        "role": cycle_role, "phase": "cycle",
                        "objective": str(event.get("text") or "")[:200],
                    })
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
                sessions=self._sessions,
                # (013.1 §13) سياسة المشروع تصل أدوات الخطوة حصرًا —
                # STRICT_ISOLATED بلا بيئة معزولة = POLICY_BLOCK معلن
                # لا تنفيذ غير معزول بدلًا عنها
                execution_policy=project.get("execution_policy")
                or "STRICT_ISOLATED",
                # (013.1 §19) مفتاح إيقاف على مستوى المشروع — يطابق
                # request_stop فَيُكرّم الإيقاف داخل الخطوة نفسها
                stop_cycle_id=f"project-{project_id}",
            )
        except Exception as error:  # noqa: BLE001 — فشل صريح موثق
            from router.call_tracker import classify_failure

            error_class, _detail = classify_failure(error)
            service.update_execution(self._sessions, execution_id,
                                     status="FAILED", error=str(error))
            return self._on_step_failure(project, plan, phase, step,
                                         execution_id, str(error),
                                         error_class=error_class)
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
        self._emit(project_id, "STEP_COMPLETED", {
            "step_id": step["id"], "execution_id": execution_id,
            "evidence_id": evidence_id, "attempts": attempt,
        })
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
                         step: dict, execution_id: int, reason: str,
                         error_class: str = "") -> dict:
        """تصنيف الفشل (§13) — إعادة أو بوابة مالك، لا توقف أعمى.

        (RLR-001 §1) فشل المزود العابر لا يحرق ميزانية إعادة الخطوة
        ولا يفتح بوابة مراجعة خطة زائفة — الدورة تُحفظ عبر بوابة
        PROVIDER_ACTION_REQUIRED بالتصنيف الصريح والإجراء التالي.
        """
        project_id = project["id"]
        if error_class:
            from router.call_tracker import TRANSIENT_PROVIDER_CLASSES

            if error_class in TRANSIENT_PROVIDER_CLASSES:
                return self._block_provider_transient(
                    project, step, execution_id, error_class, reason)
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

    def _block_provider_transient(self, project: dict, step: dict,
                                  execution_id: int, error_class: str,
                                  reason: str) -> dict:
        """حجب صادق بانتظار المزود (RLR-001 §1) — لا مراجعة خطة زائفة.

        الخطوة تبقى READY (تعود للعمل عند الاستئناف مباشرة)، والمشروع
        BLOCKED ببوابة PROVIDER_ACTION_REQUIRED تحمل التصنيف والإجراء
        التالي — عكس مسار استنفاد المحاولات الذي يفتح PLAN_REVISION.
        """
        project_id = project["id"]
        service.update_step(self._sessions, step["id"], status="READY",
                            last_error=f"[{error_class}] {reason[:400]}")
        gate_id = service.open_gate(
            self._sessions, project_id, "PROVIDER_ACTION_REQUIRED",
            f"عطل مزود عابر [{error_class}] — الدورة محفوظة قابلة للاستئناف",
            {"error_class": error_class, "execution_id": execution_id,
             "step_id": step["id"],
             "required_action": "تحقق من مسار الشبكة/الوكيل ثم استأنف — "
                                "والفحص التلقائي يحترم TTL"},
        )
        service.update_project(self._sessions, project_id, status="BLOCKED",
                               last_error=f"[{error_class}] {reason[:500]}")
        self._emit(project_id, "PROVIDER_TRANSIENT_FAILURE", {
            "step_id": step["id"], "execution_id": execution_id,
            "error_class": error_class, "gate_id": gate_id,
            "error_detail": reason[:400],
            "next_action": "الاستئناف عند عودة الاتصال — لا مراجعة خطة",
        })
        return {"action": "blocked",
                "reason": f"انتظار المزود [{error_class}]",
                "gate_id": gate_id, "blocked_kind": "provider_transient"}

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
        self._emit(project_id, "STAGE_REVIEW", {
            "phase_id": phase["id"], "phase_title": phase["title"],
            "steps": len(steps), "stage": "review",
        })
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

    def _pause(self, project: dict, reason: str,
               *, final: bool = False) -> dict:
        """توقف عند checkpoint (§9) — مؤقت قابل للاستئناف أو نهائي.

        (013.4 §12) الإيقاف النهائي يكتب STOPPED دائمة: لا حذف — كل
        الأحداث والأدلة واللقطات والتاريخ تبقى حرفيًا كما هي.
        """
        project_id = project["id"]
        plan = self._active_plan(project)
        phase = service.get_phase(
            self._sessions, project["current_phase_id"]
        ) if project["current_phase_id"] else None
        step = service.get_step(
            self._sessions, project["current_step_id"]
        ) if project["current_step_id"] else None
        self._checkpoint(project_id, plan, phase, step)
        _STOP_INTENTS.pop(int(project_id), None)
        if final:
            service.update_project(
                self._sessions, project_id,
                status="STOPPED", stop_requested=False,
            )
            self._emit(project_id, "PROJECT_STOPPED", {
                "reason": reason, "final": True,
                "preserved": ["events", "evidence", "checkpoints",
                              "history"],
            })
            return {"action": "stopped", "reason": reason}
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
            elif project["status"] in ("PLANNING", "REVISING"):
                # (013.5 §C.4) التخطيط ليس «قرار مالك»: إن كان المولِّد
                # ميتًا فهذا عطل يُحسم بوسم صادق (PLANNING_INTERRUPTED /
                # MODEL_TIMEOUT) لا سؤال يُترك معلقًا — الجذر الحرفي
                # للعطل الذي بقي PLANNING ‏17992ث. الحسم يقع في
                # planning_runtime.recover_at_startup قبل هذا التقييم.
                live = planning_runtime.latest_session(
                    self._sessions, project_id)
                recommendation = "OWNER_RETRY"
                reason = (
                    "التخطيط لم يكتمل وحُسم بحالة صادقة "
                    f"({live['state']}/{live['error_class']}) — أعد التوليد"
                    if live and live.get("error_class") else
                    "التخطيط لم يكتمل — لا جلسة توليد حيّة؛ أعد التوليد"
                )
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

#: (013.4 §12) نية الإيقاف لكل مشروع — "pause" مؤقت قابل للاستئناف
#: أو "stop" نهائي دائم؛ تُقرأ عند أقرب checkpoint وتُمسح بعده.
_STOP_INTENTS: dict[int, str] = {}


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
    """ملفات مساحة العمل وsha256 — الأدلة الميكانيكية للتنفيذ.

    (RLR-001 §4d-4) مسح تكراري بمفاتيح مسارات نسبية — كان المسح
    العلوّي وحده يُخفي كل تسليم مساري (css/main.css، src/styles/base.css)
    ف يحكم المدقق الميكانيكي بالفقد زوراً رغم وجود الملف وبصمته.
    """
    root = Path(workspace)
    if not root.is_dir():
        return {}
    out = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == "evidence.json" or rel.startswith("_versions/"):
            continue
        out[rel] = {
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
