"""متصفح التطور اللحظي (AES-UI-REDESIGN-016-E) — لقطة موحدة وحصرًا.

مبدأان لا تنازل عنهما:
1) مصدر حقيقة واحد: كل رقم يُقرأ من اللقطة القانونية runtime_snapshot
   (workflow/snapshot.py) — لا نسبة تُحسب هنا ولا في طبقة العرض.
2) لا نجاح مزيف: الملفات من الأدلة الدائمة حصرًا، مجمعة بالاسم، آخر
   حالة تفوز، وعدد النسخ يُعرض كما هو — ما لم يُثبت لا يُعرض.
"""
from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


def _sessions():
    from api import routes  # كسول — يمنع الدوران

    return routes._sessions


def _pick_project(sessions, project_id: Optional[int]):
    from workflow import service

    projects = service.list_projects(sessions)
    if not projects:
        raise HTTPException(status_code=404, detail="لا مشاريع بعد")
    if project_id is not None:
        for p in projects:
            if p["id"] == project_id:
                return p, projects
        raise HTTPException(status_code=404, detail="مشروع غير موجود")
    live = [p for p in projects
            if str(p.get("status") or "") not in
            ("VERIFIED", "COMPLETED", "STOPPED")]
    pool = live or projects
    return max(pool, key=lambda p: str(p.get("updated_at") or "")), projects


@router.get("/snapshot")
def evolution_snapshot(project_id: Optional[int] = None) -> dict:
    """لقطة تطور موحدة: مشروع + تقدم قانوني + خطة + ملفات + آخر الأحداث.

    هذه هي النقطة الوحيدة التي يقرأ منها العرض أرقامه — متصفح التطور
    لا يحسب نسبةً بنفسه أبدًا؛ التحديث اللحظي يأتي من بث الأحداث،
    والأرقام تتحدث فقط من لقطات متجددة من هنا.
    """
    from workflow import service
    from workflow.snapshot import runtime_snapshot

    sessions = _sessions()
    proj, projects = _pick_project(sessions, project_id)
    pid = proj["id"]
    snap = runtime_snapshot(sessions, pid)

    steps = []
    try:
        for phase in service.list_phases(sessions, pid):
            for st in service.phase_steps(sessions, phase["id"]):
                steps.append({
                    "id": st.get("id"),
                    "ordinal": st.get("ordinal"),
                    "phase": phase.get("title"),
                    "objective": st.get("objective"),
                    "status": st.get("status"),
                    "attempts": st.get("attempts"),
                    "last_error": st.get("last_error") or "",
                    "current_execution_id": st.get("current_execution_id"),
                })
    except Exception:  # noqa: BLE001 — خطة فاسدة لا تكسر اللقطة
        steps = []

    files: dict = {}
    try:
        for ev in service.list_evidence(sessions, pid, limit=400):
            created = str(ev.get("created_at") or "")
            for name, meta in (ev.get("files") or {}).items():
                cur = files.get(name)
                versions = (cur or {}).get("versions", 0) + 1
                cand = {
                    "name": name,
                    "bytes": (meta or {}).get("bytes", 0),
                    "sha256": (meta or {}).get("sha256", ""),
                    "step_id": ev.get("step_id"),
                    "created_at": created,
                    "verdict": ev.get("verdict", ""),
                    "versions": versions,
                }
                if cur is None or created >= cur["created_at"]:
                    files[name] = cand
                else:
                    cur["versions"] = versions
    except Exception:  # noqa: BLE001 — أدلة غائبة لا تكسر اللقطة
        pass

    file_list = sorted(files.values(),
                       key=lambda f: f["created_at"], reverse=True)

    events = []
    try:
        events = service.list_events(sessions, pid, limit=30) or []
    except Exception:  # noqa: BLE001
        pass

    current_command = None
    try:
        for ex in service.list_executions(sessions, pid, limit=10):
            cmd_text = str(ex.get("command") or "")
            if not cmd_text:
                # أمر فارغ في السجل — نبنيه من نص الخطوة نفسها بلا تخمين
                try:
                    st = service.get_step(sessions, ex.get("step_id"))
                    if st:
                        import json as _cj
                        crit = st.get("acceptance_criteria")
                        try:
                            crit = _cj.loads(crit) if isinstance(crit, str)                                 else (crit or [])
                        except Exception:  # noqa: BLE001
                            crit = []
                        parts = [str(st.get("objective") or "")]
                        if st.get("expected_output"):
                            parts.append("\nالمخرج المتوقع: "
                                         + str(st.get("expected_output")))
                        if crit:
                            parts.append("\nمعايير القبول (تحقق حرفيًا):\n- "
                                         + "\n- ".join(str(x) for x in crit))
                        cmd_text = "\n".join(parts)
                except Exception:  # noqa: BLE001
                    cmd_text = ""
            current_command = {
                "execution_id": ex.get("id"),
                "step_id": ex.get("step_id"),
                "role": ex.get("agent_role"),
                "status": ex.get("status"),
                "command": cmd_text[:4000],
                "started_at": str(ex.get("started_at") or ""),
                "model": str(ex.get("model") or ""),
            }
            if str(ex.get("status") or "").upper() == "RUNNING":
                break
    except Exception:  # noqa: BLE001
        current_command = None

    thinker = None
    try:
        import json as _json
        plan = service.latest_plan(sessions, pid)
        if plan:
            def _lst(x):
                try:
                    return _json.loads(x) if isinstance(x, str) else (x or [])
                except Exception:  # noqa: BLE001
                    return []
            thinker = {
                "version": plan.get("version"),
                "objective": plan.get("objective"),
                "assumptions": _lst(plan.get("assumptions"))[:6],
                "risks": _lst(plan.get("risks"))[:6],
                "owner_decisions": _lst(
                    plan.get("required_owner_decisions"))[:6],
                "revision_reason": plan.get("revision_reason") or "",
                "status": plan.get("status"),
            }
    except Exception:  # noqa: BLE001
        thinker = None

    tools_summary = {}
    try:
        for ev in service.list_events(sessions, pid, limit=400):
            if ev.get("kind") != "TOOL_EXECUTION":
                continue
            pl = ev.get("payload") or {}
            t = tools_summary.setdefault(str(pl.get("tool") or "?"),
                                         {"n": 0, "ok": 0, "fail": 0})
            t["n"] += 1
            if str(pl.get("phase")) == "succeeded":
                t["ok"] += 1
            elif str(pl.get("phase")) == "failed":
                t["fail"] += 1
    except Exception:  # noqa: BLE001
        tools_summary = {}

    run = {k: snap.get(k) for k in
           ("status", "stage", "waiting_for", "heartbeat_at", "elapsed_s",
            "progress", "role", "tool", "provider", "last_event")
           if k in snap}
    return {
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "projects": [{"id": p["id"], "name": p.get("name"),
                      "status": p.get("status")} for p in projects],
        "project": {"id": proj["id"], "name": proj.get("name"),
                    "objective": proj.get("objective"),
                    "status": proj.get("status")},
        "run": run,
        "current_command": current_command,
        "thinker": thinker,
        "tools_summary": tools_summary,
        "steps": steps,
        "files": file_list[:200],
        "files_total": len(files),
        "recent_events": [{"id": e.get("id"), "kind": e.get("kind"),
                           "payload": e.get("payload") or {},
                           "created_at": e.get("created_at")}
                          for e in events],
    }


@router.get("/page")
def evolution_page(request: Request) -> Response:
    """صفحة متصفح التطور — ملف مستقل معزول؛ no-cache دائمًا."""
    ui = Path(__file__).resolve().parents[1] / "ui"
    html = (ui / "evolution.html").read_bytes()
    etag = '"' + hashlib.sha256(html).hexdigest()[:20] + '"'
    inm = request.headers.get("if-none-match", "")
    tokens = [t.strip() for t in inm.split(",") if t.strip()]
    if etag in tokens or f"W/{etag}" in tokens or "*" in tokens:
        return Response(status_code=304,
                        headers={"ETag": etag,
                                 "Cache-Control": "no-cache"})
    return Response(content=html, media_type="text/html; charset=utf-8",
                    headers={"ETag": etag, "Cache-Control": "no-cache"})
