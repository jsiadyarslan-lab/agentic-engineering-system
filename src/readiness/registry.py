"""سجل القدرات الدائم (الأمر 009 §2-§3+§8-§9) — الجرد الحقيقي.

القدرات مسجلة من الكود الفعلي حصرًا (لا افتراض وجود §3): أدوات
القائمة البيضاء، الركيزة، الويب، الشبكة، git، الملفات، الاختبار،
البناء، LLM من سجل المزودين. الأداة غير المنفذة = UNAVAILABLE
بسبب NOT_IMPLEMENTED — لا READY أبدًا.

الجاهزية تنتهي (§24): READY لها expires_at؛ بعد انقضائها تُعرض
STALE ويُعاد الفحص قبل الاعتماد — القاعدة مصدر الحقيقة.
"""

from __future__ import annotations

import datetime as _dt
import json

from sqlalchemy import select

from readiness import probes
from readiness.models import CapabilityRecord

#: الجرد الحقيقي — من الكود الموجود فعلًا (§3). required: تطلبه
#: preflight المهمة العامة افتراضيًا.
CAPABILITY_INVENTORY: tuple[dict, ...] = (
    {"capability_id": "llm", "name": "نماذج LLM (الأدوار)",
     "description": "مزود/تكوين/نموذج مربوط بكل دور — مسبار جاهزية المزود",
     "category": "LLM", "required": True, "probe": "llm_providers"},
    {"capability_id": "model_inference", "name": "استدلال النموذج الفعلي",
     "description": "توكن واحد حقيقي عبر التكوين الأساسي — /models وحده لا يكفي (§10)",
     "category": "LLM", "required": False, "probe": "model_inference"},
    {"capability_id": "web_search", "name": "بحث الويب",
     "description": "بحث DuckDuckGo حقيقي بنتائج قابلة للتحليل",
     "category": "RESEARCH", "required": True, "probe": "web_search"},
    {"capability_id": "web_fetch", "name": "جلب صفحات الويب",
     "description": "جلب صفحة موثوقة واستخلاص نصها", "category": "WEB",
     "required": False, "probe": "web_fetch"},
    {"capability_id": "network_dns", "name": "تحليل DNS",
     "description": "حل اسم حقيقي", "category": "NETWORK",
     "required": True, "probe": "dns"},
    {"capability_id": "network_https", "name": "اتصال HTTPS",
     "description": "اتصال TLS حقيقي لمصدر موثوق", "category": "NETWORK",
     "required": True, "probe": "https"},
    {"capability_id": "sandbox", "name": "ركيزة التنفيذ المعزولة",
     "description": "إقلاع/كتابة/قراءة/تنفيذ/التقاط مخرجات داخل العزل",
     "category": "SANDBOX", "required": True, "probe": "sandbox"},
    {"capability_id": "filesystem", "name": "نظام الملفات والأدلة",
     "description": "إنشاء/قراءة/تعديل/حذف والتقاط أدلة",
     "category": "FILESYSTEM", "required": True, "probe": "filesystem"},
    {"capability_id": "git", "name": "Git",
     "description": "إصدار/حالة/سجل/فرع فعليًا", "category": "GIT",
     "required": False, "probe": "git"},
    {"capability_id": "repository", "name": "المستودع",
     "description": "وصول المستودع وآخر التزام", "category": "REPOSITORY",
     "required": False, "probe": "repository"},
    {"capability_id": "shell", "name": "القشدة وPython",
     "description": "اكتشاف فعلي لإصدار Python", "category": "SHELL",
     "required": True, "probe": "shell"},
    {"capability_id": "package_management", "name": "إدارة الحزم",
     "description": "pip + قابلية حل السجل (بلا تثبيت عشوائي)",
     "category": "PACKAGE_MANAGEMENT", "required": False,
     "probe": "package_management"},
    {"capability_id": "testing", "name": "إطار الاختبارات",
     "description": "pytest متاح فعليًا", "category": "TESTING",
     "required": False, "probe": "testing"},
    {"capability_id": "build", "name": "أدوات البناء",
     "description": "أدوات البناء المكتشفة", "category": "BUILD",
     "required": False, "probe": "build"},
    {"capability_id": "persistence", "name": "القاعدة الدائمة",
     "description": "كتابة/قراءة/حذف فعلي في SQLite", "category": "PERSISTENCE",
     "required": True, "probe": "persistence"},
    {"capability_id": "artifacts", "name": "التقاط الأدلة",
     "description": "ملفات الأدلة بـsha256 داخل مساحات العمل",
     "category": "ARTIFACTS", "required": False, "probe": "filesystem"},
    {"capability_id": "observability", "name": "المراقبة والمقاييس",
     "description": "عدادات الأدوات والفشل والتعافي", "category": "OBSERVABILITY",
     "required": False, "probe": "observability"},
    # أداة غير منفذة صراحة (§3): تظهر UNAVAILABLE لا READY أبدًا
    {"capability_id": "browser", "name": "متصفح ميكانيكي",
     "description": "أداة تصفح/تحكم متصفح — غير منفذة في هذا النظام",
     "category": "WEB", "required": False, "probe": None},
)


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def ensure_capabilities(sessions) -> None:
    """بذر الجرد عند أول تشغيل — آمن للتكرار، لا يمس قراءات المسبارات."""
    with sessions() as session:
        existing = {
            row.capability_id for row in session.scalars(
                select(CapabilityRecord)
            ).all()
        }
        for spec in CAPABILITY_INVENTORY:
            if spec["capability_id"] in existing:
                continue
            session.add(CapabilityRecord(
                capability_id=spec["capability_id"],
                name=spec["name"],
                description=spec["description"],
                category=spec["category"],
                required=1 if spec["required"] else 0,
                readiness_status=(
                    "UNAVAILABLE" if spec["probe"] is None else "UNKNOWN"
                ),
                failure_reason=(
                    "NOT_IMPLEMENTED" if spec["probe"] is None else ""
                ),
            ))
        session.commit()


def _applied_staleness(row: CapabilityRecord) -> str:
    """الحالة المعروضة: READY منتهية الصلاحية = STALE (§24)."""
    if row.readiness_status == "READY" and row.expires_at is not None:
        if row.expires_at.tzinfo is None:
            expires = row.expires_at.replace(tzinfo=_dt.timezone.utc)
        else:
            expires = row.expires_at
        if expires <= _utc_now():
            return "STALE"
    return row.readiness_status


def get_capabilities(sessions) -> list[dict]:
    """كل القدرات بقراءتها الحالية — STALE مطبقة، بلا أسرار."""
    ensure_capabilities(sessions)
    out: list[dict] = []
    with sessions() as session:
        rows = session.scalars(
            select(CapabilityRecord).order_by(CapabilityRecord.id)
        ).all()
        for row in rows:
            try:
                details = json.loads(row.details or "{}")
            except ValueError:
                details = {}
            out.append({
                "capability_id": row.capability_id,
                "name": row.name,
                "description": row.description,
                "category": row.category,
                "required": bool(row.required),
                "readiness_status": _applied_staleness(row),
                "stored_status": row.readiness_status,
                "provider_id": row.provider_id or "",
                "configuration_id": row.configuration_id or "",
                "last_probe_at": row.last_probe_at.isoformat()
                if row.last_probe_at else None,
                "last_success_at": row.last_success_at.isoformat()
                if row.last_success_at else None,
                "last_failure_at": row.last_failure_at.isoformat()
                if row.last_failure_at else None,
                "failure_class": row.failure_class,
                "failure_stage": row.failure_stage,
                "failure_reason": row.failure_reason,
                "probe_latency_ms": row.probe_latency_ms,
                "ttl_seconds": row.ttl_seconds,
                "expires_at": row.expires_at.isoformat()
                if row.expires_at else None,
                "details": details,
            })
    return out


def get_capability(sessions, capability_id: str) -> dict | None:
    for cap in get_capabilities(sessions):
        if cap["capability_id"] == capability_id:
            return cap
    return None


def record_probe(sessions, capability_id: str, result) -> dict:
    """كتابة نتيجة مسبار — انتقال حالة صادق + أزمنة نجاح/فشل."""
    ensure_capabilities(sessions)
    with sessions() as session:
        row = session.scalars(
            select(CapabilityRecord)
            .where(CapabilityRecord.capability_id == capability_id)
        ).first()
        if row is None:
            raise KeyError(f"قدرة غير معروفة: {capability_id}")
        data = result.to_dict()
        row.readiness_status = data["status"]
        row.last_probe_at = _utc_now()
        if data["status"] == "READY":
            row.last_success_at = _utc_now()
            row.failure_class = ""
            row.failure_stage = ""
            row.failure_reason = ""
        else:
            row.last_failure_at = _utc_now()
            row.failure_class = data.get("failure_class", "")
            row.failure_stage = data.get("failure_stage", "")
            row.failure_reason = data.get("reason", "")
        row.probe_latency_ms = data["latency_ms"]
        row.ttl_seconds = data["ttl_seconds"]
        expires = data.get("expires_at")
        row.expires_at = (
            _dt.datetime.fromisoformat(expires) if expires else None
        )
        details = {**data.get("details", {}),
                   "reason": data.get("reason", "")}
        row.details = json.dumps(details, ensure_ascii=False, default=str)
        row.updated_at = _utc_now()
        session.commit()
    return get_capability(sessions, capability_id)


def run_probe(sessions, capability_id: str, *,
              search_fn=None, fetch_fn=None, https_fn=None,
              llm_providers_fn=None, inference_fn=None) -> dict:
    """مسبار واحد حقيقي (§8) — النتيجة تُكتب وتُعاد.

    الحقن (search_fn/…) للاختبارات حصرًا — المسار نفسه بمصادر مضبوطة.
    """
    ensure_capabilities(sessions)
    cap = get_capability(sessions, capability_id)
    if cap is None:
        raise KeyError(f"قدرة غير معروفة: {capability_id}")
    spec = next(
        (s for s in CAPABILITY_INVENTORY
         if s["capability_id"] == capability_id), {}
    )
    probe_name = spec.get("probe")
    if probe_name is None:
        # أداة غير منفذة — تبقى UNAVAILABLE بلا تزييف (§3)
        result = probes.ProbeResult(
            status="UNAVAILABLE",
            reason="NOT_IMPLEMENTED — هذه الأداة غير منفذة في النظام",
            checked_at=_utc_now().isoformat(),
        )
        return record_probe(sessions, capability_id, result)

    if probe_name == "web_search":
        result = probes.probe_web_search(search_fn=search_fn)
    elif probe_name == "web_fetch":
        result = probes.probe_web_fetch(fetch_fn=fetch_fn)
    elif probe_name == "dns":
        result = probes.probe_dns()
    elif probe_name == "https":
        result = probes.probe_https(fetch=https_fn)
    elif probe_name == "sandbox":
        result = probes.probe_sandbox()
    elif probe_name == "filesystem":
        result = probes.probe_filesystem()
    elif probe_name == "git":
        result = probes.probe_git()
    elif probe_name == "repository":
        result = probes.probe_repository()
    elif probe_name == "shell":
        result = probes.probe_shell()
    elif probe_name == "package_management":
        result = probes.probe_package_management()
    elif probe_name == "testing":
        result = probes.probe_testing()
    elif probe_name == "build":
        result = probes.probe_build()
    elif probe_name == "persistence":
        result = probes.probe_persistence()
    elif probe_name == "observability":
        from readiness.metrics import snapshot
        result = probes.ProbeResult(
            status="READY",
            reason="عدادات المراقبة تعمل",
            checked_at=_utc_now().isoformat(),
            ttl_seconds=probes.TTL_DEFAULTS["OBSERVABILITY"],
            details=snapshot(),
        )
    elif probe_name == "llm_providers":
        result = (llm_providers_fn or _probe_llm_providers)(sessions)
    elif probe_name == "model_inference":
        result = (inference_fn or _probe_model_inference_default)(sessions)
    else:  # pragma: no cover — الجرد مغلق
        result = probes.ProbeResult(status="UNKNOWN",
                                    reason="مسبار غير معروف")
    return record_probe(sessions, capability_id, result)


def _probe_llm_providers(sessions):
    """جاهزية مزودي الأدوار (§9): لكل تكوين مربوط بدور مسباره الصادق."""
    started = _utc_now()
    t0 = probes.time.monotonic()
    from providers_registry import registry

    mappings = registry.get_mappings(sessions)
    specs = registry.resolve_provider_specs(sessions)
    per_role: dict[str, dict] = {}
    ok = 0
    for role, found in mappings.items():
        key = registry.transport_key(found["provider"],
                                     found.get("configuration", ""))
        if key in specs:
            per_role[role] = {
                "provider": found["provider"],
                "model": found["model"],
                "resolvable": True,
            }
            ok += 1
        else:
            per_role[role] = {
                "provider": found["provider"],
                "model": found["model"],
                "resolvable": False,
                "reason": "التكوين غير قابل للحل (مفتاح غائب/معطّل؟)",
            }
    total = len(mappings) or 1
    return probes.ProbeResult(
        status="READY" if ok == total else (
            "NOT_READY" if ok == 0 else "DEGRADED"
        ),
        reason=f"{ok}/{total} دور بمزود قابل للحل",
        latency_ms=int((probes.time.monotonic() - t0) * 1000),
        checked_at=started.isoformat(),
        ttl_seconds=probes.TTL_DEFAULTS["LLM"],
        failure_class="" if ok == total else "AUTH_FAILURE",
        failure_stage="PROVIDER_RESOLUTION",
        details={"roles": per_role},
    )


def _probe_model_inference_default(sessions):
    """استدلال فعلي عبر التكوين الأساسي القابل للحل الأول (§10)."""
    from providers_registry import registry

    specs = registry.resolve_provider_specs(sessions)
    if not specs:
        return probes.ProbeResult(
            status="NOT_READY",
            reason="لا تكوين LLM قابل للحل — احفظ مفتاحًا أولًا",
            checked_at=_utc_now().isoformat(),
            ttl_seconds=probes.TTL_DEFAULTS["LLM"],
            failure_class="AUTH_FAILURE", failure_stage="PROVIDER_RESOLUTION",
        )
    key = next(iter(specs))
    model = specs[key].get("model", "")
    if not model:
        return probes.ProbeResult(
            status="NOT_READY",
            reason=f"التكوين {key} بلا نموذج افتراضي",
            checked_at=_utc_now().isoformat(),
            ttl_seconds=probes.TTL_DEFAULTS["LLM"],
            failure_class="INVALID_CONFIGURATION",
            failure_stage="PROVIDER_RESOLUTION",
        )
    return probes.probe_model_inference(dict(specs[key]), str(model))


def probe_all(sessions) -> list[dict]:
    """فحص البيئة الكامل (§22-§23) — كل قدرة بمسبارها الحقيقي."""
    ensure_capabilities(sessions)
    results = []
    for spec in CAPABILITY_INVENTORY:
        try:
            results.append(run_probe(sessions, spec["capability_id"]))
        except Exception as error:  # noqa: BLE001 — قدرة لا تكسر البقية
            results.append({
                "capability_id": spec["capability_id"],
                "readiness_status": "NOT_READY",
                "failure_reason": f"المسبار فشل: {error}",
            })
    return results
