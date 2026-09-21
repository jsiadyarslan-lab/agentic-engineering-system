"""فحص المهمة المسبق (الأمر 009 §16-§17 + الأمر 010 §18+§26-§30).

    Task → Plan → Capability Analysis → Required Capabilities
         → Environment Selection → Environment Preflight
         → PASS (ابدأ) / BLOCKED (لا تبدأ + مصفوفة + إجراء مالك)

القدرة المطلوبة غير الجاهزة = BLOCKED بسبب معروف وخطة استرداد
ومسار مالك إن لزم (§25+§30) — لا بدء مهمة تموت بعد دقائق بسبب كان
قابلًا للكشف مسبقًا. الجاهزية المنتهية (STALE) تُعاد فحصها قبل
الاعتماد (§24)؛ والقدرة الاختيارية الغائبة لا تحجب (§28 preflight).

مصفوفة القدرات (010 §26): Required/Available/Decision لكل قدرة —
القرار ✓ أو BLOCK، مع البيئة المختارة وإجراء المالك الصريح.
"""

from __future__ import annotations

from typing import Any

from readiness import registry

#: كلمات تدل على اعتماد المهمة جوهريًا على البحث الخارجي (§16
#: Capability Analysis): حين يطلب المالك بحثًا/مصادر/OSINT صراحة
#: فالبحث قدرة مطلوبة تحجب غيابه البدء؛ وما عداه اختياري — المنفذ
#: قد يجرب البحث فيفشل في التعافي الموثق لا في حجب مسبق.
_RESEARCH_HINTS = (
    "بحث", "ابحث", "ابحثي", "مصادر", "sources", "web search", "osint",
    "استخبارات مفتوحة", "أخبار", "رصد",
)


def required_capabilities(goal: str) -> list[str]:
    """القدرات المطلوبة لهذه المهمة — من الجرد المعلن حصرًا.

    الأساس الدائم للمسار الحي: LLM (الأدوار) + بيئة تنفيذ (ملفات
    الأدلة وتنفيذ الكود) + ملفات + شبكة + قشدة + قاعدة. البحث
    الخارجي مطلوب فقط حين يعتمد عليه الهدف جوهريًا (كلمات صريحة).
    """
    base = ["llm", "sandbox", "filesystem",
            "network_dns", "network_https", "shell", "persistence"]
    lowered = (goal or "").lower()
    if any(hint in lowered for hint in _RESEARCH_HINTS):
        base.append("web_search")
    return base


def _recovery_hint(capability_id: str) -> str:
    hints = {
        "llm": "اربط الأدوار بمزود جاهز من ⚙ الإعدادات ← المزودون واحفظ مفتاحه",
        "web_search": "جهّز مزود بحث من ⚙ الإعدادات ← البحث: مثيل SearXNG "
                      "أو Search API بمفتاح — أو شغّل النظام حيث DDG متاح",
        "sandbox": "أضف بيئة تنفيذ من ⚙ الإعدادات ← بيئات التنفيذ "
                   "(عامل Linux/WSL2) ← تحقق ← أعد المهمة",
        "network_dns": "افحص إعدادات الشبكة/DNS في البيئة المضيفة",
        "network_https": "افحص الوصول الخارجي (جدار/بروكسي)",
        "network_http": "افحص الوصول لمنفذ 80 (جدار/بروكسي)",
        "filesystem": "تحقق من صلاحيات الكتابة في مجلد المشروع",
        "shell": "تحقق من تثبيت Python في PATH",
        "persistence": "تحقق من صلاحية ملف قاعدة البيانات (قراءة/كتابة)",
    }
    return hints.get(capability_id, "افحص هذه القدرة من لوحة البيئة")


def _owner_action(sessions, capability_id: str, failure_class: str) -> str | None:
    """متى يستلزم تدخل المالك (§25+§30) — مفاتيح/بيئات/مزودون غائبون."""
    if capability_id == "llm" and failure_class in (
        "AUTH_FAILURE", "INVALID_CONFIGURATION",
    ):
        return (
            "قرار مطلوب منك: احفظ مفتاح المزود من ⚙ الإعدادات ← "
            "المزودون، أو اربط الأدوار بمزود متاح"
        )
    if capability_id == "sandbox":
        from execution import service as execution_service

        return execution_service.owner_action_for_missing_environment(sessions)
    if capability_id == "web_search":
        return (
            "OWNER ACTION REQUIRED — البحث غير جاهز: افحص حالة كل مزود "
            "من ⚙ الإعدادات ← البحث. جهّز مثيل SearXNG (رابط) أو Search "
            "API (نقطة+مفتاح) ثم افحصهما — الجلب (web_fetch) قد يكون "
            "جاهزًا بالتوازي فالمهمات التي لا تحتاج البحث تستمر"
        )
    return None


def task_preflight(
    sessions,
    goal: str,
    *,
    force: bool = False,
    run_probe_fn: Any = None,
    llm_ready: bool | None = None,
    llm_detail: dict | None = None,
) -> dict:
    """فحص مسبق كامل — PASS يسمح بالبدء، BLOCKED يمنعه بصدق.

    force: أعد فحص كل مطلوب حتى الصالح (تجاهل TTL).
    run_probe_fn: حقن الاختبارات — المسار نفسه بمسبار مضبوط.
    llm_ready: نتيجة فحص الموجّه الفعلي الذي سيشغّل المهمة (أصدق من
    فحص مستقل — نفس المزودات التي ستستدعى فعلًا).
    """
    probe = run_probe_fn or registry.run_probe
    required = required_capabilities(goal)
    capabilities: list[dict] = []
    blocked: list[dict] = []

    for capability_id in required:
        if capability_id == "llm" and llm_ready is not None:
            ok = bool(llm_ready)
            entry = {
                "capability_id": "llm",
                "name": "نماذج LLM (الأدوار)",
                "status": "READY" if ok else "NOT_READY",
                "ok": ok,
                "reason": "كل الأدوار بمزود قابل للحل على الموجّه الفعلي"
                if ok else "أدوار بلا مزود قابل للحل على الموجّه الفعلي",
                "last_probe": None,
                "latency_ms": 0,
                "recovery": "" if ok else _recovery_hint("llm"),
                "owner_action": (None if ok else _owner_action(
                    sessions, "llm", "AUTH_FAILURE")),
            }
            if llm_detail:
                entry["detail"] = llm_detail
            capabilities.append(entry)
            if not ok:
                blocked.append(entry)
            continue
        current = registry.get_capability(sessions, capability_id)
        if current is None:
            capabilities.append({
                "capability_id": capability_id, "status": "UNAVAILABLE",
                "ok": False, "reason": "قدرة غير معروفة في الجرد",
                "recovery": "", "owner_action": None,
            })
            continue
        status = current["readiness_status"]
        # STALE أو UNKNOWN = أعد الفحص قبل الاعتماد (§24)
        needs_probe = (
            force or status in ("UNKNOWN", "STALE", "NOT_READY",
                                "UNAVAILABLE")
        )
        if needs_probe:
            probed = probe(sessions, capability_id)
            status = probed["readiness_status"]
            current = probed
        ok = status == "READY"
        entry = {
            "capability_id": capability_id,
            "name": current.get("name", capability_id),
            "status": status,
            "ok": ok,
            "reason": current.get("failure_reason", "")
            or ("جاهز بمسبار حقيقي" if ok else status),
            "last_probe": current.get("last_probe_at"),
            "latency_ms": current.get("probe_latency_ms", 0),
            "recovery": "" if ok else _recovery_hint(capability_id),
            "owner_action": (None if ok else _owner_action(
                sessions, capability_id, current.get("failure_class", ""))),
        }
        capabilities.append(entry)
        if not ok:
            blocked.append(entry)

    # (010 §18) اختيار بيئة التنفيذ قبل القرار — لا بيئة افتراضية
    # غير موجودة: البيئة المختارة تُسمّى في النتيجة، وغيابها سبب معلن.
    environment: dict | None = None
    try:
        from execution import service as execution_service

        environment = execution_service.select_environment(sessions)
    except Exception:  # noqa: BLE001 — بلا قاعدة تنفيذ في هذا السياق
        environment = None

    verdict = "PASS" if not blocked else "BLOCKED"
    result = {
        "verdict": verdict,
        "goal": goal[:200],
        "required": required,
        "capabilities": capabilities,
        "blocked": blocked,
        "environment": environment,
        "matrix": _matrix(capabilities),
    }
    if blocked:
        from readiness import metrics

        metrics.count_preflight_block()
        result["summary"] = (
            "الحواجز: " + "، ".join(
                f"{b['capability_id']} ({b['status']})" for b in blocked
            ) + " — الإجراء قبل البدء، لا بعده"
        )
    else:
        result["summary"] = (
            "كل القدرات المطلوبة جاهزة بمسبارات حقيقية — يمكن البدء"
            + (
                f" عبر بيئة: {environment['name']}"
                if environment else ""
            )
        )
    return result


def _matrix(capabilities: list[dict]) -> list[dict]:
    """مصفوفة القدرات (§26): Required/Available/Decision لكل قدرة."""
    return [
        {
            "capability": entry.get("name") or entry["capability_id"],
            "capability_id": entry["capability_id"],
            "required": "مطلوبة",
            "available": entry["status"],
            "decision": "PROCEED" if entry.get("ok") else "BLOCK",
        }
        for entry in capabilities
    ]


def preflight_events(result: dict) -> list[dict]:
    """أحداث حية للفحص المسبق — تُبث في تيار المهمة (§16+§29)."""
    events = [{
        "kind": "preflight.started",
        "role": "coordinator",
        "text": "فحص البيئة قبل البدء…",
        "details": {"required": result["required"]},
    }]
    if result["verdict"] == "PASS":
        environment = result.get("environment")
        events.append({
            "kind": "preflight.passed",
            "role": "coordinator",
            "text": result["summary"],
            "details": {
                "capabilities": [
                    {"capability_id": c["capability_id"],
                     "status": c["status"]}
                    for c in result["capabilities"]
                ],
                "environment": (
                    {"id": environment["id"], "name": environment["name"],
                     "backend": environment["backend"],
                     "sandboxed": environment["sandboxed"]}
                    if environment else None
                ),
                "matrix": result.get("matrix", []),
            },
        })
    else:
        events.append({
            "kind": "preflight.blocked",
            "role": "coordinator",
            "text": result["summary"],
            "details": {
                "blocked": result["blocked"],
                "matrix": result.get("matrix", []),
                "environment": result.get("environment"),
                "recovery": [
                    {"capability_id": b["capability_id"],
                     "recovery": b["recovery"],
                     "owner_action": b["owner_action"]}
                    for b in result["blocked"]
                ],
            },
        })
    return events
