"""تحقق حي §K: هل يوقف STOP/PAUSE توليدًا جاريًا فعلًا؟

العطل المُغلق: الإيقاف كان يضبط علمًا على صف المشروع بينما خيط
التوليد يواصل الاستدعاء، ثم تصل الخطة وتقلب الحالة إلى
AWAITING_OWNER_APPROVAL **بعد** الإيقاف.

هنا: مشروع حقيقي، توليد حقيقي ضد المزود المُهيَّأ، ثم إيقاف في منتصف
الاستدعاء — ونقيس: هل أُلغيت الجلسة؟ هل توقف المشروع؟ هل بقيت الخطة
غير موجودة (لا نجاح بعد إيقاف)؟ وكم استغرق القطع فعلًا؟
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


def call(method: str, path: str, body: dict | None = None,
         timeout: float = 60.0) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, headers=headers,
                                     method=method)
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


def run_case(label: str, *, final: bool, wait_before: float) -> dict:
    """حالة واحدة: ابدأ توليدًا حقيقيًا ← انتظر ← أوقف ← قِس النتيجة."""
    print(f"\n=== {label} (final={final}) ===", flush=True)
    out: dict[str, Any] = {"label": label, "final": final}
    status, project = call("POST", "/api/projects", {
        "name": f"تحقق §K — {label}",
        "objective": "بناء خدمة تقارير أسبوعية داخلية بلا تكامل خارجي",
        "created_by": "acceptance-0135-k",
    })
    pid = project.get("id")
    out["project_id"] = pid
    print(f"مشروع {pid} أُنشئ", flush=True)

    status, started = call("POST", f"/api/projects/{pid}/plan/generate", {})
    session = (started or {}).get("session") or {}
    out["session_before"] = {
        "id": session.get("id"), "state": session.get("state"),
        "provider": session.get("provider"), "model": session.get("model"),
    }
    print(f"توليد بدأ: session={session.get('id')} "
          f"state={session.get('state')}", flush=True)

    # ننتظر حتى يصبح التوليد جاريًا فعلًا ثم نوقف في منتصف الاستدعاء
    time.sleep(wait_before)
    status, snap = call("GET", f"/api/projects/{pid}/runtime")
    planning = snap.get("planning") or {}
    out["before_stop_snapshot"] = {
        "project_status": snap.get("status"),
        "stage": snap.get("stage"),
        "wait_phase": planning.get("wait_phase"),
        "planning_state": planning.get("state"),
        "planning_silence_s": snap.get("planning_silence_s"),
        "reasoning_chars": (planning.get("detail") or {}).get("reasoning_chars"),
    }
    print(f"قبل الإيقاف: {json.dumps(out['before_stop_snapshot'], ensure_ascii=False)}",
          flush=True)
    out["generating_when_stopped"] = (
        out["before_stop_snapshot"].get("planning_state") == "GENERATING")

    t_stop = time.monotonic()
    if final:
        status, stopped = call("POST", f"/api/projects/{pid}/stop",
                               {"reason": "تحقق §K — إيقاف نهائي",
                                "final": True})
    else:
        status, stopped = call("POST", f"/api/projects/{pid}/pause",
                               {"reason": "تحقق §K — إيقاف مؤقت"})
    out["stop_http"] = status
    out["stop_response"] = stopped
    print(f"الإيقاف: HTTP {status} | "
          f"planning_cancel={json.dumps((stopped or {}).get('planning_cancel'), ensure_ascii=False)}",
          flush=True)

    # نقيس زمن ملاحظة الإلغاء (حدث قطع الاستدعاء) وزمن الحالة النهائية
    observed_at = None
    final_row = None
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        status, snap = call("GET", f"/api/projects/{pid}/runtime")
        if status == 200:
            planning = snap.get("planning") or {}
            row = {
                "t_since_stop": round(time.monotonic() - t_stop, 1),
                "project_status": snap.get("status"),
                "wait_phase": planning.get("wait_phase"),
                "planning_state": planning.get("state"),
            }
            if observed_at is None and row.get("planning_state") in (
                    "CANCELLED", "NONE"):
                observed_at = row["t_since_stop"]
            final_row = row
            if row["project_status"] in ("STOPPED", "PAUSED", "DRAFT",
                                         "AWAITING_OWNER_APPROVAL"):
                break
        time.sleep(2)
    out["final_snapshot"] = final_row
    out["seconds_to_cancel_seen"] = observed_at
    out["seconds_to_settle"] = round(time.monotonic() - t_stop, 1)

    status, after = call("GET", f"/api/projects/{pid}")
    out["project_after"] = {
        "status": after.get("status"),
        "current_plan_id": after.get("current_plan_id"),
        "last_error": after.get("last_error"),
    }
    status, plan = call("GET", f"/api/projects/{pid}/plan")
    plan_present = isinstance(plan, dict) and bool(plan.get("id"))
    out["plan_after_stop"] = plan.get("id") if plan_present else None

    status, events = call("GET", f"/api/projects/{pid}/events?limit=60")
    payload = events if isinstance(events, dict) else {}
    rows = payload.get("events") or payload.get("items") or []
    kinds = [e.get("kind") for e in rows]
    out["events"] = kinds

    print(f"بعد الإيقاف: {json.dumps(out['project_after'], ensure_ascii=False)} "
          f"| خطة={out['plan_after_stop']} "
          f"| استقرّ في {out['seconds_to_settle']}ث", flush=True)
    print(f"أحداث: {kinds}", flush=True)

    expected = "STOPPED" if final else "PAUSED"
    out["checks"] = {
        "was_generating_before_stop": out["generating_when_stopped"],
        "project_reached_expected": out["project_after"]["status"] == expected,
        "no_plan_after_stop": plan_present is False,
        "cancelled_event_seen": "PLANNING_CANCELLED" in kinds,
        "no_success_after_stop": "PLAN_CREATED" not in kinds,
    }
    out["verdict"] = "PASS" if all(out["checks"].values()) else "FAIL"
    print(f"فحوص: {json.dumps(out['checks'], ensure_ascii=False)} -> "
          f"{out['verdict']}", flush=True)
    return out


def main() -> int:
    evidence: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cases": [],
    }
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("stop", "both"):
        evidence["cases"].append(
            run_case("إيقاف نهائي أثناء التوليد", final=True,
                     wait_before=45.0))
    if which in ("pause", "both"):
        evidence["cases"].append(
            run_case("إيقاف مؤقت أثناء التوليد", final=False,
                     wait_before=45.0))
        # الاستئناف بعد الإيقاف المؤقت: لا RUNNING بلا خطة
        pid = evidence["cases"][-1]["project_id"]
        status, resumed = call("POST", f"/api/projects/{pid}/resume")
        evidence["resume_after_pause"] = {
            "http": status, "status": (resumed or {}).get("status"),
            "plan_id": (resumed or {}).get("current_plan_id"),
        }
        print(f"\nالاستئناف بعد الإيقاف المؤقت: HTTP {status} "
              f"status={(resumed or {}).get('status')}", flush=True)

    verdicts = [c["verdict"] for c in evidence["cases"]]
    if "resume_after_pause" in evidence:
        rp = evidence["resume_after_pause"]
        # لا RUNNING بلا خطة (إمّا DRAFT أو AWAITING_OWNER_APPROVAL)
        verdicts.append(
            "PASS" if rp["status"] in ("DRAFT", "AWAITING_OWNER_APPROVAL")
            else "FAIL")
    evidence["verdict"] = "PASS" if all(v == "PASS" for v in verdicts) else "FAIL"
    out_dir = ROOT / "runtime" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"order0135-k-stop-pause-{stamp}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"\nالحكم النهائي §K: {evidence['verdict']} — دليل: {path}",
          flush=True)
    return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
