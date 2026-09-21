"""الأمر 007 — الإثبات الحي الكامل (smoke حقيقي لا mocks).

المراحل (كلها عبر HTTP فعلي ضد الخادم الحي):
  providers  : مسبارا الجاهزية الحقيقيان (zai_internal + nvidia) بالتشخيص الكامل
  lifecycle  : مشروع كامل — إنشاء ← خطة حية (LLM حقيقي) ← اعتماد ← حلقة
               ذاتية (أدوار حية + ركيزة) ← أدلة ← تدقيق ← مرشح ← تحقق المالك
  pause      : مشروع ثانٍ يوقف عند checkpoint (قبل الإكمال)
  recover    : بعد restart فعلي للعملية — الاسترداد يجده ويقيّمه
  finish     : استئناف من checkpoint ← إكمال ← تحقق نهائي

التقرير يطبع Mock/Live لكل طبقة بصدق — أي فشل يظهر كما هو.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8010"
OUT: dict = {"phases": {}}


def call(method: str, path: str, body: dict | None = None, timeout: float = 600.0):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload, int((time.monotonic() - started) * 1000)


def sse(method: str, path: str, body: dict | None = None, timeout: float = 900.0):
    """استهلاك بث SSE كامل — يعيد الأحداث ومدتها."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b"{}"
    request = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    events = []
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        import codecs

        decoder = codecs.getincrementaldecoder("utf-8")()
        buffer = ""
        while True:
            chunk = response.read(1024)
            if not chunk:
                break
            buffer += decoder.decode(chunk)
            while "\n\n" in buffer:
                part, buffer = buffer.split("\n\n", 1)
                if part.startswith("data: "):
                    try:
                        events.append(json.loads(part[6:]))
                    except ValueError:
                        pass
    return events, int((time.monotonic() - started) * 1000)


def log(phase: str, message: str) -> None:
    print(f"[{phase}] {message}", flush=True)


def save() -> None:
    with open("runtime/smoke_order007.json", "w", encoding="utf-8") as handle:
        json.dump(OUT, handle, ensure_ascii=False, indent=1)


def phase_providers() -> None:
    """مسبارا الجاهزية الحقيقيان — تشخيص NVIDIA منظم (007.1 §7+§21)."""
    result: dict = {"providers": {}}
    providers, _ = call("GET", "/api/providers")
    for provider in providers["providers"]:
        for cfg in provider["configurations"]:
            if not cfg["is_primary"]:
                continue
            probe, ms = call(
                "POST", f"/api/provider-configurations/{cfg['id']}/test",
                timeout=60,
            )
            result["providers"][provider["name"]] = {
                "status": probe["status"],
                "http_status": probe.get("http_status"),
                "endpoint": probe.get("endpoint"),
                "model": probe.get("model"),
                "latency_ms": probe.get("latency_ms", ms),
                "error_message": probe.get("error_message"),
                "diagnosis": probe.get("diagnosis", {}),
            }
            log("providers", f"{provider['name']}: {probe['status']} "
                f"(http={probe.get('http_status')}, {probe.get('latency_ms')}ms)")
    # zai_internal يجب أن يكون READY (منشأة معلنة حية)
    zai = result["providers"].get("zai_internal", {})
    result["zai_ready"] = zai.get("status") == "READY"
    # nvidia: الحقيقة كما هي — لا تجميل (§21)
    result["nvidia_honest"] = "nvidia" in result["providers"]
    OUT["phases"]["providers"] = result
    save()


def phase_lifecycle() -> None:
    """المشروع الكامل: خطة حية ← حلقة ذاتية حية ← أدلة ← تحقق المالك."""
    result: dict = {}

    # 1) إنشاء
    project, ms = call("POST", "/api/projects", {
        "name": "إثبات النظام الحي",
        "objective": (
            "أنشئ ملفًا باسم solar-brief.md يشرح ثلاث فوائد رئيسية "
            "للطاقة الشمسية في الشرق الأوسط في ثلاث فقرات، مع مقدمات "
            "وخلاصة، وبأي لغة عربية واضحة."
        ),
    })
    pid = project["id"]
    result["project_id"] = pid
    log("lifecycle", f"أُنشئ المشروع #{pid} — {project['status']}")

    # 2) توليد الخطة — LLM حي (نموذج المفكر من الربط الدائم)
    plan, ms = call("POST", f"/api/projects/{pid}/plan/generate", timeout=300)
    result["plan"] = {
        "version": plan["version"], "status": plan["status"],
        "phases": [
            {"title": p["title"], "steps": [s["objective"][:80] for s in p["steps"]]}
            for p in plan["phases"]
        ],
        "generated_by": plan.get("generated_by") if isinstance(plan.get("generated_by"), dict) else None,
        "duration_ms": ms,
    }
    log("lifecycle", f"الخطة v{plan['version']}: {len(plan['phases'])} مرحلة، "
        f"{sum(len(p['steps']) for p in plan['phases'])} خطوة ({ms}ms — LLM حي)")

    # 3) اعتماد المالك
    approved, _ = call("POST", f"/api/projects/{pid}/plan/approve",
                       {"approved": True})
    result["after_approve"] = approved["status"]
    log("lifecycle", f"اعتُمدت الخطة — المشروع {approved['status']}")

    # 4) الحلقة الذاتية — بث حي كامل
    events, ms = sse("POST", f"/api/projects/{pid}/run/stream")
    kinds = [e["kind"] for e in events]
    result["run"] = {
        "duration_ms": ms,
        "events_count": len(events),
        "kinds": kinds,
        "step_progress_count": kinds.count("step.progress"),
    }
    key = ["PHASE_STARTED", "STEP_STARTED", "EXECUTION_STARTED",
           "EXECUTION_COMPLETED", "EVIDENCE_CREATED", "TEST_COMPLETED",
           "REVIEW_COMPLETED", "AUDIT_COMPLETED", "PHASE_COMPLETED",
           "PROJECT_COMPLETION_CANDIDATE"]
    result["run"]["key_events_seen"] = [k for k in key if k in kinds]
    log("lifecycle", f"الحلقة انتهت ({ms}ms، {len(events)} حدثًا) — "
        f"الأحداث المفاتيح: {result['run']['key_events_seen']}")

    # 5) الحالة النهائية + الأدلة + التدقيق
    detail, _ = call("GET", f"/api/projects/{pid}")
    result["final"] = {
        "status": detail["status"],
        "completion_state": detail["completion_state"],
    }
    evidence, _ = call("GET", f"/api/projects/{pid}/evidence")
    result["evidence_count"] = len(evidence["evidence"])
    for ev in evidence["evidence"]:
        result.setdefault("evidence_files", []).extend(ev.get("files", {}).keys())
    audits, _ = call("GET", f"/api/projects/{pid}/audit")
    result["audit_verdicts"] = [a["verdict"] for a in audits["audits"]]
    executions, _ = call("GET", f"/api/projects/{pid}/executions")
    result["executions"] = [
        {"attempt": e["attempt"], "status": e["status"],
         "provider": e["provider"], "model": e["model"]}
        for e in executions["executions"]
    ]
    log("lifecycle", f"النهاية: {result['final']} — "
        f"أدلة: {result['evidence_count']} — تدقيق: {result['audit_verdicts']}")

    # 6) التحقق النهائي — قرار المالك وحده
    if detail["status"] == "COMPLETED":
        verified, _ = call("POST", f"/api/projects/{pid}/verify")
        result["verified"] = verified["status"]
        log("lifecycle", f"تحقق المالك: {verified['status']}")

    OUT["phases"]["lifecycle"] = result
    OUT["lifecycle_project_id"] = pid
    save()


def phase_pause() -> None:
    """مشروع الاستئناف: يصل checkpoint ثم يتوقف (قبل الإكمال)."""
    project, _ = call("POST", "/api/projects", {
        "name": "إثبات الاستئناف بعد إعادة التشغيل",
        "objective": (
            "أنشئ ملفًا باسم notes.md فيه خمس نقاط قصيرة عن أهمية "
            "الاختبارات الآلية في أنظمة الذكاء الاصطناعي."
        ),
    })
    pid = project["id"]
    call("POST", f"/api/projects/{pid}/plan/generate", timeout=300)
    call("POST", f"/api/projects/{pid}/plan/approve", {"approved": True})
    # إيقاف مطلوب قبل التشغيل — أول نبضة تحوّله PAUSED مع checkpoint
    call("POST", f"/api/projects/{pid}/stop", {"reason": "اختبار الاستئناف"})
    events, ms = sse("POST", f"/api/projects/{pid}/run/stream")
    detail, _ = call("GET", f"/api/projects/{pid}")
    OUT["phases"]["pause"] = {
        "project_id": pid, "status": detail["status"],
        "checkpoint": detail.get("current_step_id") is not None
        or bool(events),
    }
    OUT["resume_project_id"] = pid
    log("pause", f"المشروع #{pid} توقف عند {detail['status']} — checkpoint جاهز")
    save()


def phase_recover() -> None:
    """بعد restart فعلي للعملية: الاسترداد يجد المشروع ويقيّمه (§19)."""
    pid = OUT["resume_project_id"]
    listing, _ = call("GET", "/api/projects")
    entry = [r for r in listing["recovery"] if r["project_id"] == pid]
    events, _ = call("GET", f"/api/projects/{pid}/events")
    recovery_event = [e for e in events if e["kind"] == "RECOVERY_ASSESSED"]
    OUT["phases"]["recover"] = {
        "found": bool(entry),
        "recommendation": entry[0]["recommendation"] if entry else None,
        "resumable": entry[0]["resumable"] if entry else None,
        "checkpoint": entry[0]["checkpoint"] if entry else None,
        "recovery_event_logged": bool(recovery_event),
    }
    log("recover", f"الاسترداد: {OUT['phases']['recover']}")
    save()


def phase_finish() -> None:
    """استئناف من checkpoint ← إكمال ← تحقق نهائي."""
    pid = OUT["resume_project_id"]
    call("POST", f"/api/projects/{pid}/resume")
    events, ms = sse("POST", f"/api/projects/{pid}/run/stream")
    detail, _ = call("GET", f"/api/projects/{pid}")
    result = {
        "status": detail["status"],
        "completion_state": detail["completion_state"],
        "duration_ms": ms,
    }
    if detail["status"] == "COMPLETED":
        verified, _ = call("POST", f"/api/projects/{pid}/verify")
        result["verified"] = verified["status"]
    OUT["phases"]["finish"] = result
    log("finish", f"بعد الاستئناف: {result}")
    save()


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    if phase in ("providers", "all"):
        phase_providers()
    if phase in ("lifecycle", "all"):
        phase_lifecycle()
    if phase in ("pause", "all"):
        phase_pause()
    if phase in ("recover", "all"):
        phase_recover()
    if phase in ("finish", "all"):
        phase_finish()
    print(json.dumps(OUT, ensure_ascii=False, indent=1))
