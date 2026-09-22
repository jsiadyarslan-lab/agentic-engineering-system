"""عقود القدرات والمزودين في الـHarness (012-B) — تعريف موحد فوق
مصدر الحقيقة الواحد (011 §12).

المفاهيم:

- **CapabilitySpec**: قدرة هندسية معلنة (llm/web_search/sandbox/…)
  لها فئة، ونمط حل (SINGLE واحد لا بديل / FAILOVER سلسلة بديلة /
  AGGREGATED مشتقة من مزودين)، وتصنيف انتظار: ``blocked_kind``
  يكون ``WORKER`` للقدرات التي تعني بيئة تنفيذ (عامل/ركيزة)
  و``CAPABILITY`` لما عداها — هذا التصنيف هو ما يميّز انتظار
  الوظيفة: WAITING_WORKER مقابل WAITING_CAPABILITY (012-E).

- **ProviderSpec**: مزود قابل للتبديل خلف القدرة — مسباره من
  المصدر (readiness/execution/research)، لا مسبار موازٍ هنا.

الاشتقاق كله يفوَّض إلى readiness.service (القدرات) و
execution.service (البيئات) وproviders_registry (الربط الحي لكل
دور) — هذه الوحدة تنظّم وترتّب ولا تصدر حالة جاهزية من عندها
أبدًا. سلوك FAILOVER للبحث يعتمد ترتيب الجاهزية الفعالة ثم
زمن النداء (research.service.search يجرب التالي عند فشل الأول).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from harness.seams import HarnessSeams

#: القدرات التي تعني «بيئة تنفيذ/عامل» — انتظارها WAITING_WORKER.
#: sandbox مشتقة من سجل بيئات التنفيذ (execution/service) لا من
#: سجل القدرات وحده (011 §12-§13).
WORKER_CAPABILITIES: frozenset[str] = frozenset({"sandbox"})

#: أنماط الحل — كيف يُختار المزود الفعلي خلف القدرة.
RESOLUTION_MODES = ("SINGLE", "FAILOVER", "AGGREGATED")

#: أدوار المشروع الخمسة — عقدها في harness/roles_runtime.
PROJECT_ROLES = ("thinker", "reviewer", "implementer", "verifier",
                 "arbiter")


@dataclass(frozen=True)
class ProviderSpec:
    """مزود خلف قدرة — وصف معلن لا حالة مكررة.

    ``probe`` يبقى في المصدر؛ هنا الاسم والنوع والنقل فقط، وتُستكمل
    الحالة الفعلية عند الحل من الدرزة (مصدر الحقيقة).
    """

    name: str
    kind: str
    note: str = ""


@dataclass(frozen=True)
class CapabilitySpec:
    """قدرة هندسية معلنة — بطاقة تعريف موحدة لطبقة التحكم."""

    capability_id: str
    category: str
    resolution: str = "SINGLE"
    blocked_kind: str = "CAPABILITY"   # CAPABILITY | WORKER
    providers: tuple[ProviderSpec, ...] = field(default_factory=tuple)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "category": self.category,
            "resolution": self.resolution,
            "blocked_kind": self.blocked_kind,
            "description": self.description,
            "providers": [
                {"name": p.name, "kind": p.kind, "note": p.note}
                for p in self.providers
            ],
        }


#: مواصفات القدرات التي يضيف عليها الـHarness تنظيمًا خاصًّا؛ ما لم
#: يذكر هنا يظهر من جرد readiness كما هو (SINGLE/غير مطلوب تنظيم).
_HARNESS_SPECS: dict[str, CapabilitySpec] = {
    "llm": CapabilitySpec(
        capability_id="llm", category="LLM", resolution="SINGLE",
        description="ربط حي لكل دور من الخمسة — مزود::تكوين::نموذج، "
                    "لا دور يرث مزود دور آخر",
        providers=tuple(
            ProviderSpec(name=role, kind="role_mapping",
                         note=f"ربط الدور {role} من سجل المزودين")
            for role in PROJECT_ROLES
        ),
    ),
    "web_search": CapabilitySpec(
        capability_id="web_search", category="RESEARCH",
        resolution="FAILOVER",
        description="سلسلة مزودي بحث — أول جاهز يُستخدم والفشل زمن "
                    "النداء يعني التالي؛ تعطيل الجميع = SEARCH_BLOCKED",
        providers=(
            ProviderSpec("ddg", "search_ddg", "DuckDuckGo الافتراضي"),
            ProviderSpec("searxng", "search_searx",
                         "SearXNG — يوفَّر من الإعدادات"),
            ProviderSpec("search-api", "search_api",
                         "Search API بمفتاح — يوفَّر من الإعدادات"),
        ),
    ),
    "sandbox": CapabilitySpec(
        capability_id="sandbox", category="SANDBOX", resolution="SINGLE",
        blocked_kind="WORKER",
        description="بيئة التنفيذ المختارة — المسبار والمنفذ من "
                    "resolve_executor واحد؛ توفيرها = عامل Linux "
                    "أو ركيزة معزولة محلية",
        providers=(
            ProviderSpec("local-sandbox", "LOCAL",
                         "الركيزة المعزولة المحلية (Linux فقط)"),
            ProviderSpec("local-process", "LOCAL",
                         "وضع التوافق المعلن بلا عزل"),
            ProviderSpec("remote-worker", "REMOTE_WORKER",
                         "عامل HTTP على Linux/WSL2"),
        ),
    ),
}


def spec_for(capability_id: str, readiness_record: dict | None) -> CapabilitySpec:
    """مواصفة قدرة — من تعريفات الـHarness أو من جرد readiness."""
    if capability_id in _HARNESS_SPECS:
        return _HARNESS_SPECS[capability_id]
    return CapabilitySpec(
        capability_id=capability_id,
        category=(readiness_record or {}).get("category", "UNKNOWN"),
        resolution="SINGLE",
        description=(readiness_record or {}).get("description", ""),
    )


def blocked_kind_of(capability_id: str) -> str:
    """تصنيف حتمي: هل انتظار هذه القدرة عامل أم قدرة؟ (012-E).

    WORKER حكرًا على بيئة التنفيذ؛ كل ما عداها قدرة (مزود بحث،
    نقل LLM، شبكة، …) — بلا استثناءات صامتة.
    """
    spec = _HARNESS_SPECS.get(capability_id)
    if spec is not None:
        return spec.blocked_kind
    return "WORKER" if capability_id in WORKER_CAPABILITIES else "CAPABILITY"


def resolve_capability(seams: HarnessSeams, capability_id: str,
                       *, role: str | None = None) -> dict:
    """حل قدرة واحدة — الحالة من المصدر + المزودون المرتبون.

    يعيد: {capability_id, category, resolution, blocked_kind, status,
           reason, providers: [{name, status, selected}], selected,
           detail} — يكفي المنسقَ والواجهة معًا. للبحث: المزودون
            بترتيب الجاهزية الفعالة (الجاهز أولًا) وهو نفس ترتيب
            المحاولة زمن النداء في research.service.search.
    """
    spec = spec_for(capability_id, None)
    out = {
        "capability_id": capability_id,
        "category": spec.category,
        "resolution": spec.resolution,
        "blocked_kind": blocked_kind_of(capability_id),
        "description": spec.description,
        "status": "UNKNOWN",
        "reason": "",
        "selected": None,
        "providers": [],
        "detail": {},
    }

    if capability_id == "llm":
        return _resolve_llm(seams, out, role=role)
    if capability_id == "web_search":
        return _resolve_web_search(seams, out)
    if capability_id == "sandbox":
        return _resolve_sandbox(seams, out)

    # بقية الجرد — من مصدر الحقيقة كما هي
    view = seams.capability_view(capability_id)
    if view is None:
        out["status"] = "UNKNOWN"
        out["reason"] = "قدرة غير معروفة في الجرد"
        return out
    out["status"] = view.get("readiness_status") or view.get("status") \
        or "UNKNOWN"
    out["reason"] = (view.get("reason") or view.get("failure_reason")
                     or "")[:300]
    out["detail"] = {"source": "readiness.service.capability_view"}
    return out


def _resolve_llm(seams: HarnessSeams, out: dict, *,
                 role: str | None) -> dict:
    """حل ربط LLM — لكل دور اختياره المستقل (لا توريث بين الأدوار)."""
    mappings = seams.role_selections()
    roles = [role] if role else list(PROJECT_ROLES)
    providers = []
    ready_all = True
    for key in roles:
        mapping = mappings.get(key) or {}
        provider = mapping.get("provider", "")
        model = mapping.get("model", "")
        configuration = mapping.get("configuration", "")
        transport = f"{provider}::{configuration}" if configuration \
            else provider
        has = bool(provider) and seams.has_transport(transport)
        if not has:
            ready_all = False
        providers.append({
            "name": key, "kind": "role_mapping",
            "provider": provider, "model": model,
            "configuration": configuration,
            "transport_key": transport, "ready": has,
            "status": "READY" if has else "NOT_READY",
        })
    out["status"] = "READY" if ready_all else "NOT_READY"
    out["reason"] = "" if ready_all else (
        "أدوار بلا نقل حي قابل للحل: "
        + "؛ ".join(p["name"] for p in providers if not p["ready"])
    )
    out["providers"] = providers
    out["selected"] = next((p for p in providers if p["ready"]), None)
    out["detail"] = {"role": role or "all", "source":
                     "providers_registry + router transport check"}
    return out


def _resolve_web_search(seams: HarnessSeams, out: dict) -> dict:
    """حل البحث — سلسلة FAILOVER بترتيب الجاهزية الفعالة."""
    view = seams.capability_view("web_search") or {}
    providers_view = seams.research_providers_view()
    # الترتيب: الجاهز الفعّال أولًا ثم المعطل ثم بلا حالة — نفس
    # الروح التي يحاول بها research.service.search عند النداء.
    order = {"READY": 0, "STALE": 1, "UNKNOWN": 2, "NOT_READY": 3,
             "NOT_CONFIGURED": 4, "DISABLED": 5, "UNAVAILABLE": 6}
    ranked = sorted(
        providers_view, key=lambda p: order.get(
            p.get("effective_status", "UNKNOWN"), 9
        )
    )
    providers = [
        {
            "name": p.get("name", ""),
            "kind": p.get("kind", ""),
            "status": p.get("effective_status", "UNKNOWN"),
            "configured": bool(p.get("configured")),
            "reason": (p.get("state_reason") or "")[:200],
        }
        for p in ranked
    ]
    out["status"] = view.get("readiness_status") or view.get("status") \
        or "UNKNOWN"
    out["reason"] = (view.get("reason") or "")[:300]
    out["providers"] = providers
    out["selected"] = next(
        (p for p in providers if p["status"] == "READY"), None
    )
    out["detail"] = {
        "failover": "أول جاهز عند المسبار؛ الفشل زمن النداء ينتقل "
                    "للتالي (research.service.search)",
        "per_provider": view.get("per_provider") or providers,
    }
    return out


def _resolve_sandbox(seams: HarnessSeams, out: dict) -> dict:
    """حل بيئة التنفيذ — من resolve_executor (المسبار=المنفذ)."""
    view = seams.capability_view("sandbox") or {}
    environments = seams.list_environments()
    providers = [
        {
            "name": e.get("name", ""),
            "kind": e.get("backend", ""),
            "status": e.get("status", "UNKNOWN"),
            "isolation": e.get("isolation", ""),
            "sandboxed": bool(e.get("sandboxed")),
            "failure_reason": (e.get("failure_reason") or "")[:200],
        }
        for e in environments
    ]
    out["status"] = view.get("readiness_status") or view.get("status") \
        or "UNKNOWN"
    out["reason"] = (view.get("reason") or "")[:300]
    out["providers"] = providers
    out["selected"] = next(
        (p for p in providers if p["status"] == "READY"), None
    )
    out["detail"] = {
        "readiness_ladder": "connectivity → authentication → heartbeat → "
                            "environment → workspace → execute → artifact "
                            "(011 §10)",
        "owner_action": (view.get("owner_action") or "")[:400],
    }
    return out


def capability_catalog(seams: HarnessSeams) -> list[dict]:
    """الكتالوج الكامل — جرد readiness + مواصفات الـHarness معًا.

    كل قدرة تظهر مرة واحدة: الحالة من مصدر الحقيقة، والتنظيم
    (نمط الحل/المزودون/تصنيف الانتظار) من الـHarness.
    """
    records = seams.capabilities_view()
    catalog = []
    seen: set[str] = set()
    for record in records:
        capability_id = record.get("capability_id", "")
        if capability_id in seen:
            continue
        seen.add(capability_id)
        resolved = resolve_capability(seams, capability_id)
        resolved["name"] = record.get("name", capability_id)
        resolved["required"] = bool(record.get("required", False))
        catalog.append(resolved)
    # مواصفات الـHarness لقدرات قد لا تكون في الجرد بعد (llm دائمًا
    # موجودة؛ sandbox كذلك) — أمانة العرض لا أكثر
    for capability_id, spec in _HARNESS_SPECS.items():
        if capability_id not in seen:
            catalog.append({
                **spec.to_dict(), "name": capability_id,
                "status": "UNKNOWN", "reason": "غير موجودة في جرد "
                "الجاهزية بعد", "selected": None, "providers": [],
                "detail": {}, "required": None,
            })
    return catalog


__all__ = [
    "PROJECT_ROLES",
    "RESOLUTION_MODES",
    "WORKER_CAPABILITIES",
    "CapabilitySpec",
    "ProviderSpec",
    "blocked_kind_of",
    "capability_catalog",
    "resolve_capability",
    "spec_for",
]
