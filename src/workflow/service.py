"""خدمة كيانات المشروع (الأمر 007 §18) — قراءة/كتابة نحيفة بلا منطق.

كل عمليات القاعدة لكيانات workflow هنا: الإنشاء والاستعلام وتجميع
التفاصيل والأحداث والبوابات. لا orchestration في هذه الوحدة —
الحلقة الذاتية في engine.py، والنقل في api/projects.py.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from sqlalchemy import select

from persistence.models import _utc_now
from workflow.models import (
    AuditRecord,
    CheckpointRecord,
    EvidenceRecord,
    Execution,
    OwnerGate,
    Phase,
    Plan,
    Project,
    ProjectEvent,
    RetryRecord,
    Step,
)

PROJECT_ROLES = ("thinker", "reviewer", "implementer", "verifier", "arbiter")


def _jload(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except (ValueError, TypeError):
        return default


# ------------------------------------------------------------------ #
# المشروع
# ------------------------------------------------------------------ #

def create_project(sessions, *, name: str, objective: str,
                   execution_policy: str = "STRICT_ISOLATED") -> dict:
    """إنشاء مشروع DRAFT — الحالة الصادقة من اللحظة الأولى (§3).

    execution_policy (011 §26): STRICT_ISOLATED (الافتراضية) أو
    COMPATIBLE_LOCAL — تُخزن منذ الإنشاء فلا قرار لاحق خفي.
    """
    from execution import policy as execution_policy_mod

    if not execution_policy_mod.is_valid_policy(execution_policy):
        raise ValueError(
            f"سياسة تنفيذ غير معروفة: {execution_policy} — المدعوم: "
            + "، ".join(execution_policy_mod.POLICIES)
        )
    with sessions() as session:
        project = Project(
            name=name or "مشروع جديد", objective=objective or "",
            execution_policy=execution_policy,
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        pid = project.id
    add_event(sessions, pid, "PROJECT_CREATED",
              {"name": name, "objective": objective})
    return get_project(sessions, pid)


# ------------------------------------------------------------------ #
# دورة حياة المشروع (013.4 §11-§17) — تكرار/أرشفة/استرجاع/تسمية
# ------------------------------------------------------------------ #

def duplicate_project(sessions, source: dict, *, name: str = "") -> dict:
    """نسخة مشروع جديدة (013.4 §15) — الأصل لا يُمس أبدًا.

    تُنسخ: الهدف والاسم والسياسة وبنية الخطة النشطة إن وُجدت
    (مراحلها وخطواتها بمعرفات جديدة، مصدرها source_id معلن).
    لا تُنسخ: الأحداث/الأدلة/الوظائف/البوابات — ملك جولة الأصل.
    النسخة تولد DRAFT (لا اعتماد موروث — قرار مالك جديد دائمًا).
    """
    from execution import policy as execution_policy_mod

    new_name = (name or f"نسخة — {source['name']}").strip()[:200]
    with sessions() as session:
        duplicate = Project(
            name=new_name, objective=source.get("objective", ""),
            execution_policy=execution_policy_mod.is_valid_policy(
                source.get("execution_policy")
            ) and source.get("execution_policy") or "STRICT_ISOLATED",
            original_id=int(source["id"]),
        )
        session.add(duplicate)
        session.commit()
        session.refresh(duplicate)
        new_id = duplicate.id

        # بنية الخطة النشطة (لا سجلها) — إن كان للأصل خطة معتمدة
        source_plan = None
        plan_row = session.scalars(
            select(Plan).where(
                Plan.project_id == int(source["id"]),
                Plan.status == "ACTIVE",
            ).order_by(Plan.id.desc()).limit(1)
        ).first()
        if plan_row is not None:
            source_plan = _plan_dict(plan_row)
    if source_plan is not None:
        plan_data = {
            "objective": source_plan.get("objective", ""),
            "assumptions": source_plan.get("assumptions", []),
            "acceptance_criteria": source_plan.get(
                "acceptance_criteria", []),
            "phases": [
                {
                    "title": p.get("title", ""),
                    "objective": p.get("objective", ""),
                    "acceptance_criteria": p.get(
                        "acceptance_criteria", []),
                    "steps": [
                        {
                            "objective": s.get("objective", ""),
                            "input": s.get("input", ""),
                            "expected_output": s.get(
                                "expected_output", ""),
                            "acceptance_criteria": s.get(
                                "acceptance_criteria", []),
                            "dependencies": s.get("dependencies", []),
                        }
                        for s in p.get("steps", [])
                    ],
                }
                for p in source_plan.get("phases", [])
            ],
            "risks": source_plan.get("risks", []),
            "dependencies": source_plan.get("dependencies", []),
            "required_owner_decisions": source_plan.get(
                "required_owner_decisions", []),
            "duplicated_from": {
                "project_id": int(source["id"]),
                "plan_id": source_plan.get("id"),
            },
        }
        create_plan(sessions, new_id, plan_data,
                    supersedes_plan_id=None,
                    revision_reason="نسخة بنية من مشروع أصلي",
                    revision_evidence={"source_id": int(source["id"])})
    add_event(sessions, new_id, "PROJECT_DUPLICATED", {
        "original_id": int(source["id"]),
        "source_id": int(source["id"]),
        "copied_at": _utc_now().isoformat(),
    })
    return get_project(sessions, new_id)


def archive_project(sessions, project_id: int) -> dict:
    """أرشفة (013.4 §17) — علم دورة حياة، لا حذف بيانات أبدًا."""
    with sessions() as session:
        project = session.get(Project, int(project_id))
        if project is None:
            raise KeyError(f"مشروع غير معروف: {project_id}")
        if project.status == "RUNNING":
            raise ValueError("المشروع يعمل — لا أرشفة أثناء التشغيل")
        project.archived_at = _utc_now()
        project.updated_at = _utc_now()
        session.commit()
    return get_project(sessions, project_id)


def restore_project(sessions, project_id: int) -> dict:
    """استرجاع من الأرشيف (013.4 §45) — عودة كاملة للحياة النشطة."""
    with sessions() as session:
        project = session.get(Project, int(project_id))
        if project is None:
            raise KeyError(f"مشروع غير معروف: {project_id}")
        project.archived_at = None
        project.updated_at = _utc_now()
        session.commit()
    return get_project(sessions, project_id)


def rename_project(sessions, project_id: int, name: str) -> dict:
    """إعادة تسمية مشروع — أمر دائم بسيط صادق."""
    with sessions() as session:
        project = session.get(Project, int(project_id))
        if project is None:
            raise KeyError(f"مشروع غير معروف: {project_id}")
        project.name = name[:200]
        project.updated_at = _utc_now()
        session.commit()
    return get_project(sessions, project_id)


def get_project(sessions, project_id: int) -> dict | None:
    with sessions() as session:
        project = session.get(Project, int(project_id))
        if project is None:
            return None
        return _project_dict(project)


def _project_dict(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "objective": project.objective,
        "status": project.status,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "current_plan_id": project.current_plan_id,
        "current_phase_id": project.current_phase_id,
        "current_step_id": project.current_step_id,
        "stop_requested": project.stop_requested,
        "completion_state": project.completion_state,
        "last_error": project.last_error,
        "execution_policy": project.execution_policy or "STRICT_ISOLATED",
        # (013.4 §15+§17) دورة الحياة: النسخة والأرشفة معلنتان
        "archived_at": project.archived_at.isoformat()
        if getattr(project, "archived_at", None) else None,
        "original_id": getattr(project, "original_id", None),
    }


def list_projects(sessions, limit: int = 200, *,
                  include_archived: bool = False) -> list[dict]:
    """قائمة المشاريع (013.4 §17) — النشطة افتراضيًا.

    المؤرشف لا يظهر في القائمة النشطة لكنه يبقى قابلًا للاستعلام
    (get_project) والاسترجاع (restore_project) — الأرشفة ليست حذفًا.
    """
    with sessions() as session:
        query = select(Project).order_by(
            Project.updated_at.desc(), Project.id.desc()
        )
        if not include_archived:
            query = query.where(Project.archived_at.is_(None))
        rows = session.scalars(query.limit(limit)).all()
        return [_project_dict(row) for row in rows]


def archived_projects(sessions, limit: int = 200) -> list[dict]:
    """المشاريع المؤرشفة حصرًا — قائمة الاسترجاع (013.4 §45)."""
    with sessions() as session:
        rows = session.scalars(
            select(Project)
            .where(Project.archived_at.is_not(None))
            .order_by(Project.archived_at.desc())
            .limit(limit)
        ).all()
        return [_project_dict(row) for row in rows]


def update_project(sessions, project_id: int, **fields) -> None:
    """تحديث حقول المشروع — الاستخدام الداخلي للمحرك حصرًا."""
    with sessions() as session:
        project = session.get(Project, int(project_id))
        if project is None:
            raise KeyError(f"مشروع غير معروف: {project_id}")
        for key, value in fields.items():
            setattr(project, key, value)
        project.updated_at = _utc_now()
        session.commit()


#: الحالات غير النهائية — مشاريع الاسترداد عند الإقلاع (§19).
UNFINISHED_STATES = ("RUNNING", "REVISING", "BLOCKED", "PAUSED", "PLANNING",
                     "AWAITING_OWNER_APPROVAL", "READY")


# ------------------------------------------------------------------ #
# الخطة
# ------------------------------------------------------------------ #

def create_plan(sessions, project_id: int, plan_data: dict, *,
                supersedes_plan_id: int | None = None,
                revision_reason: str = "", revision_evidence: dict | None = None,
                status: str = "AWAITING_OWNER_APPROVAL") -> dict:
    """حفظ خطة (v جديدة) — لا تمسح السابقة أبدًا (§4)."""
    with sessions() as session:
        version = 1 + len(session.scalars(
            select(Plan).where(Plan.project_id == int(project_id))
        ).all())
        plan = Plan(
            project_id=int(project_id),
            version=version,
            objective=str(plan_data.get("objective", "")),
            assumptions=json.dumps(plan_data.get("assumptions", []),
                                   ensure_ascii=False),
            acceptance_criteria=json.dumps(
                plan_data.get("acceptance_criteria", []), ensure_ascii=False),
            phases=json.dumps(plan_data.get("phases", []), ensure_ascii=False),
            risks=json.dumps(plan_data.get("risks", []), ensure_ascii=False),
            dependencies=json.dumps(plan_data.get("dependencies", []),
                                    ensure_ascii=False),
            required_owner_decisions=json.dumps(
                plan_data.get("required_owner_decisions", []), ensure_ascii=False),
            status=status,
            supersedes_plan_id=supersedes_plan_id,
            revision_reason=revision_reason,
            revision_evidence=json.dumps(revision_evidence or {},
                                         ensure_ascii=False),
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        pid = plan.id
    update_project(sessions, project_id, current_plan_id=pid)
    add_event(sessions, project_id,
              "PLAN_REVISED" if supersedes_plan_id else "PLAN_CREATED",
              {"plan_id": pid, "version": version,
               "supersedes": supersedes_plan_id,
               "reason": revision_reason})
    return get_plan(sessions, pid)


def get_plan(sessions, plan_id: int) -> dict | None:
    with sessions() as session:
        plan = session.get(Plan, int(plan_id))
        if plan is None:
            return None
        return _plan_dict(plan)


def latest_plan(sessions, project_id: int) -> dict | None:
    with sessions() as session:
        plan = session.scalars(
            select(Plan).where(Plan.project_id == int(project_id))
            .order_by(Plan.version.desc())
        ).first()
        return _plan_dict(plan) if plan else None


def _plan_dict(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "version": plan.version,
        "objective": plan.objective,
        "assumptions": _jload(plan.assumptions, []),
        "acceptance_criteria": _jload(plan.acceptance_criteria, []),
        "phases": _jload(plan.phases, []),
        "risks": _jload(plan.risks, []),
        "dependencies": _jload(plan.dependencies, []),
        "required_owner_decisions": _jload(plan.required_owner_decisions, []),
        "status": plan.status,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "supersedes_plan_id": plan.supersedes_plan_id,
        "revision_reason": plan.revision_reason,
        "revision_evidence": _jload(plan.revision_evidence, {}),
        "approved_by_owner": plan.approved_by_owner,
        "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
    }


def approve_plan(sessions, plan_id: int) -> dict:
    """اعتماد المالك — القناة الوحيدة إلى ACTIVE (§4+§14)."""
    with sessions() as session:
        plan = session.get(Plan, int(plan_id))
        if plan is None:
            raise KeyError(f"خطة غير معروفة: {plan_id}")
        plan.approved_by_owner = True
        plan.approved_at = _utc_now()
        plan.status = "ACTIVE"
        session.commit()
    return get_plan(sessions, plan_id)


def supersede_plan(sessions, plan_id: int) -> None:
    with sessions() as session:
        plan = session.get(Plan, int(plan_id))
        if plan is not None:
            plan.status = "SUPERSEDED"
            session.commit()


# ------------------------------------------------------------------ #
# المراحل والخطوات
# ------------------------------------------------------------------ #

def materialize_plan(sessions, plan: dict) -> None:
    """تفعيل خطة معتمدة: إنشاء صفوف Phase/Step من هيكلها (§4→§5→§6)."""
    project_id = plan["project_id"]
    with sessions() as session:
        # المراحل القديمة من خطط سابقة تبقى للتاريخ — الجديدة تُنشأ
        for index, phase_data in enumerate(plan["phases"], start=1):
            phase = Phase(
                project_id=project_id,
                plan_id=plan["id"],
                ordinal=index,
                title=str(phase_data.get("title", f"المرحلة {index}")),
                objective=str(phase_data.get("objective", "")),
                acceptance_criteria=json.dumps(
                    phase_data.get("acceptance_criteria", []),
                    ensure_ascii=False),
                status="PLANNED",
            )
            session.add(phase)
            session.flush()
            for step_index, step_data in enumerate(
                phase_data.get("steps", []), start=1
            ):
                session.add(Step(
                    phase_id=phase.id,
                    ordinal=step_index,
                    objective=str(step_data.get("objective", "")),
                    input=str(step_data.get("input", "")),
                    expected_output=str(step_data.get("expected_output", "")),
                    acceptance_criteria=json.dumps(
                        step_data.get("acceptance_criteria", []),
                        ensure_ascii=False),
                    dependencies=json.dumps(
                        step_data.get("dependencies", []), ensure_ascii=False),
                    status="PENDING",
                ))
        session.commit()


def list_phases(sessions, project_id: int) -> list[dict]:
    with sessions() as session:
        rows = session.scalars(
            select(Phase).where(Phase.project_id == int(project_id))
            .order_by(Phase.plan_id.desc(), Phase.ordinal)
        ).all()
        out = []
        for row in rows:
            out.append({
                "id": row.id,
                "project_id": row.project_id,
                "plan_id": row.plan_id,
                "ordinal": row.ordinal,
                "title": row.title,
                "objective": row.objective,
                "acceptance_criteria": _jload(row.acceptance_criteria, []),
                "status": row.status,
                "current_step_id": row.current_step_id,
                "review_status": row.review_status,
                "completed_at": row.completed_at.isoformat()
                if row.completed_at else None,
            })
        return out


def active_phases(sessions, plan_id: int) -> list[dict]:
    """مراحل الخطة المعنية بترتيبها — مراحل الخطط الأقدم تُستبعد."""
    with sessions() as session:
        rows = session.scalars(
            select(Phase).where(Phase.plan_id == int(plan_id))
            .order_by(Phase.ordinal)
        ).all()
        return [{
            "id": r.id, "ordinal": r.ordinal, "title": r.title,
            "objective": r.objective,
            "acceptance_criteria": _jload(r.acceptance_criteria, []),
            "status": r.status, "current_step_id": r.current_step_id,
        } for r in rows]


def get_phase(sessions, phase_id: int) -> dict | None:
    with sessions() as session:
        row = session.get(Phase, int(phase_id))
        if row is None:
            return None
        return {
            "id": row.id, "project_id": row.project_id, "plan_id": row.plan_id,
            "ordinal": row.ordinal, "title": row.title,
            "status": row.status,
            "acceptance_criteria": _jload(row.acceptance_criteria, []),
        }


def update_phase(sessions, phase_id: int, **fields) -> None:
    with sessions() as session:
        row = session.get(Phase, int(phase_id))
        if row is None:
            raise KeyError(f"مرحلة غير معروفة: {phase_id}")
        for key, value in fields.items():
            setattr(row, key, value)
        if fields.get("status") == "COMPLETED":
            row.completed_at = _utc_now()
        session.commit()


def phase_steps(sessions, phase_id: int) -> list[dict]:
    with sessions() as session:
        rows = session.scalars(
            select(Step).where(Step.phase_id == int(phase_id))
            .order_by(Step.ordinal)
        ).all()
        return [_step_dict(row) for row in rows]


def get_step(sessions, step_id: int) -> dict | None:
    with sessions() as session:
        row = session.get(Step, int(step_id))
        return _step_dict(row) if row else None


def _step_dict(row: Step) -> dict:
    return {
        "id": row.id,
        "phase_id": row.phase_id,
        "ordinal": row.ordinal,
        "objective": row.objective,
        "input": row.input,
        "expected_output": row.expected_output,
        "acceptance_criteria": _jload(row.acceptance_criteria, []),
        "dependencies": _jload(row.dependencies, []),
        "status": row.status,
        "attempts": row.attempts,
        "current_execution_id": row.current_execution_id,
        "evidence_id": row.evidence_id,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def update_step(sessions, step_id: int, **fields) -> None:
    with sessions() as session:
        row = session.get(Step, int(step_id))
        if row is None:
            raise KeyError(f"خطوة غير معروفة: {step_id}")
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = _utc_now()
        if fields.get("status") == "COMPLETED":
            row.completed_at = _utc_now()
        session.commit()


# ------------------------------------------------------------------ #
# التنفيذ والأدلة والتدقيق والإعادات
# ------------------------------------------------------------------ #

def create_execution(sessions, step_id: int, *, attempt: int,
                     provider: str, model: str, workspace: str,
                     agent_role: str = "implementer") -> int:
    with sessions() as session:
        execution = Execution(
            step_id=int(step_id), attempt=attempt, status="RUNNING",
            agent_role=agent_role, provider=provider, model=model,
            workspace=workspace,
        )
        session.add(execution)
        session.commit()
        session.refresh(execution)
        return execution.id


def update_execution(sessions, execution_id: int, **fields) -> None:
    with sessions() as session:
        row = session.get(Execution, int(execution_id))
        if row is None:
            raise KeyError(f"تنفيذ غير معروف: {execution_id}")
        for key, value in fields.items():
            setattr(row, key, value)
        if fields.get("status") in ("COMPLETED", "FAILED", "STOPPED", "BLOCKED"):
            row.finished_at = _utc_now()
        session.commit()


def list_executions(sessions, project_id: int, limit: int = 200) -> list[dict]:
    with sessions() as session:
        step_ids = [
            s.id for s in session.scalars(
                select(Step).where(
                    Step.phase_id.in_(
                        select(Phase.id).where(
                            Phase.project_id == int(project_id)
                        )
                    )
                )
            ).all()
        ]
        if not step_ids:
            return []
        rows = session.scalars(
            select(Execution).where(Execution.step_id.in_(step_ids))
            .order_by(Execution.id.desc()).limit(limit)
        ).all()
        return [{
            "id": r.id, "step_id": r.step_id, "attempt": r.attempt,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status, "agent_role": r.agent_role,
            "provider": r.provider, "model": r.model, "workspace": r.workspace,
            "commit_sha": r.commit_sha, "error": r.error,
        } for r in rows]


def create_evidence(sessions, *, execution_id: int, step_id: int,
                    project_id: int, files: dict, tool_calls: list,
                    verification: dict, review_result: dict, commit: str,
                    evidence_path: str, evidence_sha256: str,
                    verdict: str, commands: list | None = None,
                    tests: dict | None = None, artifacts: list | None = None,
                    logs: list | None = None) -> int:
    with sessions() as session:
        record = EvidenceRecord(
            execution_id=execution_id, step_id=step_id, project_id=project_id,
            files=json.dumps(files, ensure_ascii=False),
            tests=json.dumps(tests or {}, ensure_ascii=False),
            commands=json.dumps(commands or [], ensure_ascii=False),
            artifacts=json.dumps(artifacts or [], ensure_ascii=False),
            logs=json.dumps(logs or [], ensure_ascii=False),
            tool_calls=json.dumps(tool_calls, ensure_ascii=False),
            verification=json.dumps(verification, ensure_ascii=False),
            review_result=json.dumps(review_result, ensure_ascii=False),
            commit=commit or "", evidence_path=evidence_path,
            evidence_sha256=evidence_sha256, verdict=verdict,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def get_evidence(sessions, evidence_id: int) -> dict | None:
    with sessions() as session:
        row = session.get(EvidenceRecord, int(evidence_id))
        if row is None:
            return None
        return _evidence_dict(row)


def _evidence_dict(row: EvidenceRecord) -> dict:
    return {
        "id": row.id, "execution_id": row.execution_id, "step_id": row.step_id,
        "project_id": row.project_id,
        "files": _jload(row.files, {}), "tests": _jload(row.tests, {}),
        "commands": _jload(row.commands, []),
        "artifacts": _jload(row.artifacts, []),
        "logs": _jload(row.logs, []),
        "tool_calls": _jload(row.tool_calls, []),
        "verification": _jload(row.verification, {}),
        "review_result": _jload(row.review_result, {}),
        "audit_result": _jload(row.audit_result, {}),
        "commit": row.commit, "evidence_path": row.evidence_path,
        "evidence_sha256": row.evidence_sha256, "verdict": row.verdict,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_evidence(sessions, project_id: int, limit: int = 200) -> list[dict]:
    with sessions() as session:
        rows = session.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.project_id == int(project_id))
            .order_by(EvidenceRecord.id.desc()).limit(limit)
        ).all()
        return [_evidence_dict(row) for row in rows]


def create_audit(sessions, *, project_id: int, phase_id: int | None,
                 step_id: int | None, execution_id: int | None,
                 plan_version: int, findings: dict, evidence_refs: list,
                 commit_sha: str, tests: dict, verdict: str) -> int:
    with sessions() as session:
        record = AuditRecord(
            project_id=project_id, phase_id=phase_id, step_id=step_id,
            execution_id=execution_id, plan_version=plan_version,
            findings=json.dumps(findings, ensure_ascii=False),
            evidence_refs=json.dumps(evidence_refs, ensure_ascii=False),
            commit_sha=commit_sha, tests=json.dumps(tests, ensure_ascii=False),
            verdict=verdict,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def list_audits(sessions, project_id: int, limit: int = 200) -> list[dict]:
    with sessions() as session:
        rows = session.scalars(
            select(AuditRecord)
            .where(AuditRecord.project_id == int(project_id))
            .order_by(AuditRecord.id.desc()).limit(limit)
        ).all()
        return [{
            "id": r.id, "project_id": r.project_id, "phase_id": r.phase_id,
            "step_id": r.step_id, "execution_id": r.execution_id,
            "plan_version": r.plan_version, "findings": _jload(r.findings, {}),
            "evidence_refs": _jload(r.evidence_refs, []),
            "commit_sha": r.commit_sha, "tests": _jload(r.tests, {}),
            "verdict": r.verdict,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]


def create_retry(sessions, *, step_id: int, previous_execution_id: int | None,
                 reason: str, diagnosis: str, decision: str) -> int:
    with sessions() as session:
        record = RetryRecord(
            step_id=step_id, previous_execution_id=previous_execution_id,
            reason=reason, diagnosis=diagnosis, decision=decision,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


# ------------------------------------------------------------------ #
# نقاط الاستئناف
# ------------------------------------------------------------------ #

def create_checkpoint(sessions, project_id: int, *, plan_id: int | None,
                      phase_id: int | None, step_id: int | None,
                      tick_count: int, state: dict) -> int:
    with sessions() as session:
        record = CheckpointRecord(
            project_id=project_id, plan_id=plan_id, phase_id=phase_id,
            step_id=step_id, tick_count=tick_count,
            state_json=json.dumps(state, ensure_ascii=False),
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record.id


def latest_checkpoint(sessions, project_id: int) -> dict | None:
    with sessions() as session:
        row = session.scalars(
            select(CheckpointRecord)
            .where(CheckpointRecord.project_id == int(project_id))
            .order_by(CheckpointRecord.id.desc())
        ).first()
        if row is None:
            return None
        return {
            "id": row.id, "project_id": row.project_id, "plan_id": row.plan_id,
            "phase_id": row.phase_id, "step_id": row.step_id,
            "tick_count": row.tick_count, "state": _jload(row.state_json, {}),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


# ------------------------------------------------------------------ #
# بوابات المالك
# ------------------------------------------------------------------ #

def open_gate(sessions, project_id: int, kind: str, reason: str,
              details: dict | None = None, *, status: str = "PENDING") -> int:
    """فتح بوابة — PENDING للقرار (الافتراضي) أو BLOCKED للتوفير (011 §2)."""
    from workflow.gates import GATE_STATUSES

    if status not in GATE_STATUSES:
        raise ValueError(f"حالة بوابة غير معروفة: {status}")
    with sessions() as session:
        gate = OwnerGate(
            project_id=int(project_id), kind=kind, reason=reason,
            details=json.dumps(details or {}, ensure_ascii=False),
            status=status,
        )
        session.add(gate)
        session.commit()
        session.refresh(gate)
        return gate.id


def auto_resolve_gate(sessions, gate_id: int, *, note: str = "") -> dict:
    """حل آلي لبوابة توفير BLOCKED (011 §19) — بعد إعادة فحص ناجحة.

    بوابات التوفير لا تنتظر قرار المالك بل توفيره — حين ينجح الفحص
    تُحل آليًا (APPROVED + أثر) دون مساس أي قرار جوهري: الخطة
    المعتمدة تبقى معتمدة، ولا إعادة اعتماد أبدًا ما لم تتغير الخطة.
    """
    from workflow.gates import state_label

    with sessions() as session:
        gate = session.get(OwnerGate, int(gate_id))
        if gate is None:
            raise KeyError(f"بوابة غير معروفة: {gate_id}")
        if gate.status != "BLOCKED":
            return {
                "id": gate.id, "project_id": gate.project_id,
                "kind": gate.kind, "status": gate.status,
                "already_resolved": True,
                "note": f"حالتها {state_label(gate.status)} — لا أثر",
            }
        details = _jload(gate.details, {})
        details["auto_resolved"] = True
        if note:
            details["auto_resolution_note"] = note
        gate.status = "APPROVED"
        gate.details = json.dumps(details, ensure_ascii=False)
        gate.resolved_at = _utc_now()
        session.commit()
        return {
            "id": gate.id, "project_id": gate.project_id,
            "kind": gate.kind, "status": gate.status,
            "auto_resolved": True,
        }


def resolve_gate(sessions, gate_id: int, *, approved: bool) -> dict:
    """حل بوابة مالك — idempotent للقرار نفسه (011 §1 إصلاح الجذر).

    كان الحل المتكرر يرفع «البوابة ليست مفتوحة (حالتها: APPROVED)»
    فتظهر للواجهة كأن النظام متناقض. الآن: إعادة نفس القرار = نجاح
    بلا أثر (idempotent)؛ عكس القرار يحتاج بوابة جديدة (القرار
    الجوهري لا يُنقض بالنقر مرتين)؛ وبوابات التوفير BLOCKED تُحل
    بإعادة الفحص (engine.recheck_preflight) لا من هنا.
    """
    from workflow.gates import can_transition, state_label

    with sessions() as session:
        gate = session.get(OwnerGate, int(gate_id))
        if gate is None:
            raise KeyError(f"بوابة غير معروفة: {gate_id}")
        target = "APPROVED" if approved else "REJECTED"
        if gate.status == target:
            return {
                "id": gate.id, "project_id": gate.project_id,
                "kind": gate.kind, "status": gate.status,
                "already_resolved": True,
                "note": f"القرار نفسه ({state_label(gate.status)}) — لا أثر",
            }
        if gate.status == "BLOCKED":
            raise ValueError(
                "هذه بوابة توفير محجوبة — تُحل بإعادة الفحص بعد توفير "
                "البيئة/المزود (زر إعادة الفحص)، لا بقرار موافقة"
            )
        if not can_transition(gate.status, target):
            raise ValueError(
                f"لا يمكن حل بوابة حالتها {state_label(gate.status)} "
                f"إلى {target} — القرار السابق قائم"
            )
        gate.status = target
        gate.resolved_at = _utc_now()
        session.commit()
        return {
            "id": gate.id, "project_id": gate.project_id, "kind": gate.kind,
            "status": gate.status,
        }


def list_gates(sessions, project_id: int) -> list[dict]:
    with sessions() as session:
        rows = session.scalars(
            select(OwnerGate).where(OwnerGate.project_id == int(project_id))
            .order_by(OwnerGate.id.desc())
        ).all()
        return [{
            "id": r.id, "project_id": r.project_id, "kind": r.kind,
            "reason": r.reason, "details": _jload(r.details, {}),
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        } for r in rows]


def open_gates(sessions, project_id: int) -> list[dict]:
    """البوابات التي تنتظر المالك — PENDING (011 §2) + BLOCKED للعرض.

    BLOCKED تُعاد أيضًا كي تراها الواجهة مع زر إعادة الفحص، لكنها
    لا تمنع الاستئناف بعد إعادة فحص ناجحة (engine يفصل).
    """
    return [
        g for g in list_gates(sessions, project_id)
        if g["status"] in ("PENDING", "BLOCKED")
    ]


# ------------------------------------------------------------------ #
# الأحداث الدائمة (§17)
# ------------------------------------------------------------------ #

def add_event(sessions, project_id: int, kind: str,
             payload: dict) -> int:
    """حدث مشروع دائم — يعيد معرفه (013 §5) ليصل البث الحي مع
    معرف الدائمة نفسه: إسقاط المكرر وLast-Event-ID مصالحة صادقة.

    فشل التسجيل يُعلن لا يُبتلع (يعيد 0 — الحدث الحي يمر بلا معرف).
    """
    try:
        with sessions() as session:
            row = ProjectEvent(
                project_id=int(project_id), kind=kind,
                payload=json.dumps(payload, ensure_ascii=False,
                                   default=str),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return int(row.id)
    except Exception:  # noqa: BLE001 — السجل لا يكسر العملية
        return 0


def list_events(sessions, project_id: int, limit: int = 100) -> list[dict]:
    with sessions() as session:
        rows = session.scalars(
            select(ProjectEvent)
            .where(ProjectEvent.project_id == int(project_id))
            .order_by(ProjectEvent.id.desc()).limit(limit)
        ).all()
        return [{
            "id": r.id, "project_id": r.project_id, "kind": r.kind,
            "payload": _jload(r.payload, {}),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in reversed(rows)]


def events_page(sessions, project_id: int, *, before_id: int = 0,
                limit: int = 100) -> dict:
    """صفحة أحداث بمؤشر رجوع (013.4 §43) — التاريخ الطويل بلا غرق.

    يعيد {events (تصاعديًا), next_before, has_more}: الأحدث أولًا
    داخل الاستعلام ثم يُعاد ترتيبها تصاعديًا للعرض. المؤشر قبل
    الاستخدام لا بعده — استدعاء آخر قبل الاستخدام السابق.
    """
    limit = max(1, min(int(limit), 200))
    with sessions() as session:
        query = select(ProjectEvent).where(
            ProjectEvent.project_id == int(project_id)
        )
        if int(before_id) > 0:
            query = query.where(ProjectEvent.id < int(before_id))
        rows = session.scalars(
            query.order_by(ProjectEvent.id.desc()).limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        events = [{
            "id": r.id, "project_id": r.project_id, "kind": r.kind,
            "payload": _jload(r.payload, {}),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]
        return {
            "events": list(reversed(events)),
            "next_before": events[-1]["id"] if events else 0,
            "has_more": has_more,
        }


def list_recent_events(sessions, after_id: int = 0,
                       limit: int = 100) -> list[dict]:
    """أحدث الأحداث عبر كل المشاريع بعد معرف (011 §21) — لتيار التزامن.

    مصدر واحد للشريط الجانبي وصفحة المشروع وخط الزمن: كل انتقال
    مهم يصل الجميع بلا refresh يدوي.
    """
    with sessions() as session:
        rows = session.scalars(
            select(ProjectEvent)
            .where(ProjectEvent.id > int(after_id))
            .order_by(ProjectEvent.id).limit(limit)
        ).all()
        return [{
            "id": r.id, "project_id": r.project_id, "kind": r.kind,
            "payload": _jload(r.payload, {}),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]
