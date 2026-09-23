"""تحقق حي §P/§C: هل يصل مشروع حقيقي إلى خطة مكتملة فعلًا؟

هذا هو الاختبار الذي يخالف العطل الأصلي: مشروع حقيقي بقي PLANNING
‏17992ث. هنا نُنشئ مشروعًا عبر الـAPI الحقيقي، نبدأ التخطيط، ونرصد
حتى حالة نهائية — ثم نتحقق من الخطة الدائمة نفسها (مراحل/خطوات)
ومن عقد الاستدعاء (المزود والنموذج الفعليان) ومن زمن الإنفاق.

لا شيء مزيّف: لا نموذج بديل ولا مهلة ممددة من الخارج.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = "http://127.0.0.1:8010"
ROOT = Path(__file__).resolve().parents[1]
OBJECTIVE = (
    "بناء لوحة متابعة مهام داخلية: واجهة واحدة تعرض المهام المتأخرة "
    "وتُنبّه المالك، بلا تكامل خارجي"
)


def call(method: str, path: str, body: dict | None = None,
         timeout: float = 60.0) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, raw
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw


def main() -> int:
    evidence: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "objective": OBJECTIVE,
    }
    t_zero = time.monotonic()
    status, config = call("GET", "/api/models/config")
    if status != 200:
        print(f"FAIL: تعذر قراءة تهيئة النماذج ({status})")
        return 2
    roles = config.get("roles") or []
    by_key = {
        row.get("key"): (row.get("selection") or {})
        for row in roles if isinstance(row, dict)
    }
    planner_role = by_key.get("thinker") or {}
    evidence["roles"] = {k: v for k, v in by_key.items()}
    evidence["declared_provider"] = planner_role.get("provider")
    evidence["declared_model"] = planner_role.get("model")
    print(f"التهيئة المعلنة (thinker): {evidence['declared_provider']} / "
          f"{evidence['declared_model']}")
    print("كل الأدوار: " + json.dumps(
        {k: f"{v.get('provider')}/{v.get('model')}"
         for k, v in by_key.items()}, ensure_ascii=False))
    if not evidence["declared_model"]:
        print("FAIL: لا نموذج معلن لدور المفكر — لا تحقق بلا عقد")
        return 2

    status, project = call("POST", "/api/projects", {
        "name": "تحقق 013.5 — خطة حقيقية",
        "objective": OBJECTIVE,
        "created_by": "acceptance-0135",
    })
    if status not in (200, 201):
        print(f"FAIL: تعذر إنشاء المشروع ({status}) {project}")
        return 1
    project_id = project.get("id") or project.get("project", {}).get("id")
    evidence["project_id"] = project_id
    print(f"مشروع جديد id={project_id} status="
          f"{project.get('status') or project.get('project', {}).get('status')}")

    status, started = call("POST", f"/api/projects/{project_id}/plan/generate",
                           {}, timeout=60.0)
    print(f"بدء التخطيط: HTTP {status} {json.dumps(started, ensure_ascii=False)[:200]}")
    evidence["plan_start"] = {"status": status, "body": started}
    if status not in (200, 202):
        print("FAIL: لم يبدأ التخطيط")
        return 1

    deadline = time.monotonic() + 900.0
    series: list[dict] = []
    terminal = None
    print("  انتظار الحالة النهائية (كل 5ث، حتى 900ث)...", flush=True)
    while time.monotonic() < deadline:
        status, snap = call("GET", f"/api/projects/{project_id}/runtime")
        if status == 200:
            planning = snap.get("planning") or {}
            row = {
                "t": round(time.monotonic() - t_zero, 1),
                "project_status": snap.get("status"),
                "stage": snap.get("stage"),
                "phase": snap.get("phase"),
                "wait_phase": planning.get("wait_phase"),
                "planning_state": planning.get("state"),
                "planning_silence_s": snap.get("planning_silence_s"),
                "elapsed_seconds": snap.get("elapsed_seconds"),
                "provider": snap.get("provider"),
                "model": snap.get("model"),
                "actual_provider": snap.get("actual_provider"),
                "actual_model": snap.get("actual_model"),
                "waiting_for": snap.get("waiting_for"),
            }
            series.append(row)
            print(f"  t+{row['t']:>6.1f}s status={row['project_status']} "
                  f"wait={row['wait_phase']} silence={row['planning_silence_s']} "
                  f"plan={row['planning_state']}", flush=True)
            if row["project_status"] in ("AWAITING_OWNER_APPROVAL", "READY",
                                         "DRAFT", "BLOCKED", "STOPPED",
                                         "COMPLETED", "FAILED", "ESCALATED"):
                terminal = row
                break
        time.sleep(5)
    evidence["poll_series"] = series
    evidence["terminal_poll"] = terminal
    evidence["total_seconds"] = round(time.monotonic() - t_zero, 1)
    if terminal is None:
        print("FAIL: لم تصل حالة نهائية خلال 900ث — انتظار بلا نهاية")
        return 1

    status, final = call("GET", f"/api/projects/{project_id}")
    evidence["final_project"] = final
    print(f"\nالحالة النهائية: {final.get('status')} | "
          f"last_error={final.get('last_error')!r}")

    status, plans = call("GET", f"/api/projects/{project_id}/plan")
    plan_list = [plans] if isinstance(plans, dict) and plans.get("id") else []
    evidence["plans_count"] = len(plan_list)
    ok = final.get("status") == "AWAITING_OWNER_APPROVAL" and bool(plan_list)
    if plan_list:
        plan = plan_list[0]
        phases = plan.get("phases") or []
        steps = sum(len(p.get("steps") or []) for p in phases)
        evidence["plan"] = {
            "id": plan.get("id"), "version": plan.get("version"),
            "phases": len(phases), "steps": steps,
            "generated_by": plan.get("generated_by"),
            "objective_chars": len(plan.get("objective") or ""),
        }
        print(f"الخطة: id={plan.get('id')} v{plan.get('version')} "
              f"مراحل={len(phases)} خطوات={steps}")
        print(f"مولّدة بواسطة: {json.dumps(plan.get('generated_by'), ensure_ascii=False)[:300]}")

    status, sessions = call("GET", f"/api/projects/{project_id}/runtime")
    evidence["planning_view"] = sessions
    planning = (sessions or {}).get("planning") or {}
    detail = planning.get("detail") or {}
    if isinstance(detail, str):
        detail = {}
    evidence["session"] = {
        "id": detail.get("id") or (sessions or {}).get("planning_session_id"),
        "state": detail.get("state") or planning.get("state"),
        "wait_phase": planning.get("wait_phase"),
        "provider": detail.get("provider") or (sessions or {}).get("provider"),
        "model": detail.get("model") or (sessions or {}).get("model"),
        "actual_provider": detail.get("actual_provider")
        or (sessions or {}).get("actual_provider"),
        "actual_model": detail.get("actual_model")
        or (sessions or {}).get("actual_model"),
        "request_id": detail.get("request_id")
        or (sessions or {}).get("request_id"),
        "attempt": detail.get("attempt") or (sessions or {}).get("attempt"),
        "elapsed_s": detail.get("elapsed_s"),
        "reasoning_chars": detail.get("reasoning_chars"),
        "error_class": detail.get("error_class"),
        "error_detail": detail.get("error_detail"),
        "hard_deadline_at": detail.get("hard_deadline_at"),
        "hard_timeout_s": detail.get("hard_timeout_s"),
    }
    print(f"الجلسة: {json.dumps(evidence['session'], ensure_ascii=False)}")

    # (§B) عقد الاستدعاء الكامل محفوظ — لا حقل فعلي فارغ بعد الآن
    contract_ok = bool(evidence["session"].get("actual_provider")
                       and evidence["session"].get("actual_model"))
    evidence["checks"] = {
        "project_awaiting_approval":
            final.get("status") == "AWAITING_OWNER_APPROVAL",
        "plan_persisted_with_phases": bool(plan_list),
        "session_completed": evidence["session"].get("state") == "COMPLETED",
        "actual_provider_recorded": contract_ok,
        "finished_within_hard_timeout": (
            (evidence.get("total_seconds") or 1e9) < 900.0),
    }
    ok = all(evidence["checks"].values())
    print(f"الفحوص: {json.dumps(evidence['checks'], ensure_ascii=False)}")

    evidence["verdict"] = "PASS" if ok else "FAIL"
    out_dir = ROOT / "runtime" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"order0135-real-plan-{stamp}.json"
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nالحكم: {evidence['verdict']} — دليل: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
