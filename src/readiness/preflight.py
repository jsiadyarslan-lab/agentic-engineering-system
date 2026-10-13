"""فحص المهمة المسبق (الأمر 009 §16-§17 + 010 §18+§26-§30 + 011 §17-§19).

    Task → Plan → Capability Analysis → Required Capabilities
         → Environment Selection (policy-aware 011 §26)
         → Environment Preflight
         → PASS (EXECUTION OPEN) / BLOCKED (لا بدء + مصفوفة + إجراء مالك)

القدرة المطلوبة غير الجاهزة = BLOCKED بسبب معروف وخطة استرداد
ومسار مالك إن لزم (§25+§30) — لا بدء مهمة تموت بعد دقائق بسبب كان
قابلًا للكشف مسبقًا. الجاهزية المنتهية (STALE) تُعاد فحصها قبل
الاعتماد (§24)؛ والقدرة الاختيارية الغائبة لا تحجب (§28 preflight).

مصفوفة القدرات (010 §26 + 011 §17): Required/Available/Decision لكل
قدرة + صف السياسة + صف البيئة المختارة — القرار ✓ أو BLOCK،
وإجراء المالك الصريح. الحالة تُقرأ من readiness.service حصرًا
(011 §14: مصدر واحد — لا يعيد preflight الحساب بطريقته).
"""

from __future__ import annotations

from typing import Any

from readiness import registry
from readiness import service as readiness_service

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
                   "(عامل Linux/WSL2) ← تحقق ← أعد الفحص",
        "network_dns": "افحص إعدادات الشبكة/DNS في البيئة المضيفة",
        "network_https": "افحص الوصول الخارجي (جدار/بروكسي)",
        "network_http": "افحص الوصول لمنفذ 80 (جدار/بروكسي)",
        "filesystem": "تحقق من صلاحيات الكتابة في مجلد المشروع",
        "shell": "تحقق من تثبيت Python في PATH",
        "persistence": "تحقق من صلاحية ملف قاعدة البيانات (قراءة/كتابة)",
    }
    return hints.get(capability_id, "افحص هذه القدرة من لوحة البيئة")


def _owner_action(sessions, capability_id: str, failure_class: str,
                  *, policy: str | None = None) -> str | None:
    """متى يستلزم تدخل المالك (§25+§30+011 §27) — مفاتيح/بيئات/مزودون."""
    if capability_id == "llm" and failure_class in (
        "AUTH_FAILURE", "INVALID_CONFIGURATION",
    ):
        return (
            "قرار مطلوب منك: احفظ مفتاح المزود من ⚙ الإعدادات ← "
            "المزودون، أو اربط الأدوار بمزود متاح"
        )
    if capability_id == "sandbox":
        from execution import service as execution_service

        return execution_service.owner_action_for_missing_environment(
            sessions, policy=policy
        ) or None
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
    policy: str = "STRICT_ISOLATED",
    force: bool = False,
    run_probe_fn: Any = None,
    llm_ready: bool | None = None,
    llm_detail: dict | None = None,
) -> dict:
    """فحص مسبق كامل — PASS يسمح بالبدء، BLOCKED يمنعه بصدق.

    policy (011 §26): STRICT_ISOLATED تطلب بيئة معزولة؛
    COMPATIBLE_LOCAL تقبل المعلنة غير المعزولة — القرار معروض
    في المصفوفة فلا حجب مفاجئ ولا عزل مُدّعى.
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
        # (011 §14) الحالة من مصدر واحد — readiness.service
        current = readiness_service.capability_view(sessions, capability_id)
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
            probe(sessions, capability_id)
            current = readiness_service.capability_view(
                sessions, capability_id
            ) or current
            status = current["readiness_status"]
        ok = status == "READY"
        if capability_id == "sandbox":
            # (011 §18+§26) الحكم بالسياسة: البيئة المختارة يجب أن
            # تفي بها — لا يكفي أن توجد بيئة جاهزة ما إذا كانت
            # السياسة تطلب العزل.
            from execution import policy as execution_policy
            from execution import service as execution_service

            satisfying = execution_service.select_environment(
                sessions, policy=policy
            )
            ok = satisfying is not None
            status = "READY" if ok else "BLOCKED"
            
            # (011 §26+§28) COMPATIBLE_LOCAL: إذا كان المسبار يعيد UNAVAILABLE
            # (لا ركيزة معزولة على Windows) لكن توجد بيئة غير معزولة جاهزة
            # (local-windows)، فالسياسة تسمح بالتجاوز — لا حجب مسبق.
            if not ok and policy == "COMPATIBLE_LOCAL":
                # البحث عن بيئة غير معزولة جاهزة وفق التعريف القانوني
                # الموحد (013.10 §3) — نفس بوابة السياسة لا شرط خام.
                environments = execution_service.list_environments(sessions)
                compatible_env = next(
                    (env for env in environments
                     if execution_policy.environment_satisfies(env, policy)
                     and not env.get("sandboxed")),
                    None
                )
                if compatible_env:
                    ok = True
                    status = "READY"
                    # تسجيل أن هذا وضع متوافق لا معزول
                    pass
        #: «المطلوب» نص حرفي لكل قدرة محجوبة (011 §3) — لا افتراض
        #: عامل لينكس والحاجز بحث مثلًا
        required_text = ""
        if not ok:
            if capability_id == "sandbox":
                required_text = execution_policy.requirement_text(policy)
            elif capability_id == "llm":
                required_text = "مزود LLM جاهز بمفتاح محفوظ مربوط بالأدوار"
            elif capability_id == "web_search":
                required_text = (
                    "مزود بحث جاهز — SearXNG (رابط مثيل) أو Search API "
                    "(نقطة + مفتاح)"
                )
            elif capability_id.startswith("network_"):
                required_text = "وصول شبكة خارجي سليم من المضيف"
        entry = {
            "capability_id": capability_id,
            "name": current.get("name", capability_id),
            "status": status,
            "ok": ok,
            "reason": current.get("failure_reason", "")
            or current.get("reason", "")
            or ("جاهز بمسبار حقيقي" if ok else status),
            "last_probe": current.get("last_probe_at"),
            "latency_ms": current.get("probe_latency_ms", 0),
            "recovery": "" if ok else _recovery_hint(capability_id),
            "owner_action": (None if ok else _owner_action(
                sessions, capability_id, current.get("failure_class", ""),
                policy=policy)),
            "required_environment": required_text,
        }
        if capability_id == "sandbox":
            entry["policy"] = policy
        capabilities.append(entry)
        if not ok:
            blocked.append(entry)

    # (010 §18 + 011 §18+§26) اختيار بيئة التنفيذ قبل القرار — وفق
    # السياسة؛ البيئة المختارة تُسمّى في النتيجة، وغيابها سبب معلن.
    environment: dict | None = None
    try:
        from execution import service as execution_service

        environment = execution_service.select_environment(
            sessions, policy=policy
        )
    except Exception:  # noqa: BLE001 — بلا قاعدة تنفيذ في هذا السياق
        environment = None

    from execution import policy as execution_policy

    verdict = "PASS" if not blocked else "BLOCKED"
    result = {
        "verdict": verdict,
        "goal": goal[:200],
        "policy": policy,
        "policy_note": execution_policy.policy_note(policy),
        "required": required,
        "capabilities": capabilities,
        "blocked": blocked,
        "environment": environment,
        "matrix": _matrix(capabilities, policy, environment),
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
            "كل القدرات المطلوبة جاهزة بمسبارات حقيقية — التنفيذ مفتوح"
            + (
                f" عبر بيئة: {environment['name']}"
                + ("/معزولة" if environment.get("sandboxed")
                   else " (متوافقة بلا عزل — معلن)")
                if environment else ""
            )
        )
    return result


def _matrix(capabilities: list[dict], policy: str,
            environment: dict | None) -> list[dict]:
    """مصفوفة القدرات (§26+011 §17): Required/Available/Decision.

    تتصدرها سياسة التنفيذ والبيئة المختارة — المالك يرى القرار
    كاملًا: القدرات × السياسة × البيئة.
    """
    from execution import policy as execution_policy

    rows: list[dict] = [
        {
            "capability": "سياسة التنفيذ",
            "capability_id": "execution_policy",
            "required": "معتمدة",
            "available": execution_policy.POLICY_LABELS.get(policy, policy),
            "decision": "PROCEED",
        },
        {
            "capability": "بيئة التنفيذ",
            "capability_id": "environment",
            "required": execution_policy.requirement_text(policy),
            "available": (
                f"{environment['name']} ({environment['isolation']})"
                if environment else "لا بيئة موافقة"
            ),
            "decision": "PROCEED" if environment else "BLOCK",
        },
    ]
    rows.extend(
        {
            "capability": entry.get("name") or entry["capability_id"],
            "capability_id": entry["capability_id"],
            "required": "مطلوبة",
            "available": entry["status"],
            "decision": "PROCEED" if entry.get("ok") else "BLOCK",
        }
        for entry in capabilities
    )
    return rows


def preflight_events(result: dict) -> list[dict]:
    """أحداث حية للفحص المسبق — تُبث في تيار المهمة (§16+§29)."""
    events = [{
        "kind": "preflight.started",
        "role": "coordinator",
        "text": "فحص البيئة قبل البدء…",
        "details": {
            "required": result["required"],
            "policy": result.get("policy", ""),
        },
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
                "policy": result.get("policy"),
                "environment": (
                    {"id": environment["id"], "name": environment["name"],
                     "backend": environment["backend"],
                     "isolation": environment.get("isolation", ""),
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
                "policy": result.get("policy"),
                "recovery": [
                    {"capability_id": b["capability_id"],
                     "recovery": b["recovery"],
                     "owner_action": b["owner_action"],
                     "required_environment": b.get("required_environment", "")}
                    for b in result["blocked"]
                ],
            },
        })
    return events
