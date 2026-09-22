"""دروز الـHarness (012-A) — الواجهات الرسمية فوق خدمات 011.

الدرزة (seam) ليست إعادة كتابة؛ هي حدّ معماري معلن: كل ما فوقها
(الوظائف/المنسق/الإسقاطات) يستهلك خدمات 011 عبر هذه الدروز حصرًا،
فيمكن استبدال أي خدمة خلفها دون لمس طبقة التحكم — والعكس صحيح:
خدمات 011 لا تعرف شيئًا عن الـharness.

```
HARNESS (jobs / coordinator / projections / roles-runtime)
   │  يستهلك حصرًا عبر ↓
DRIZES (seams.py)          ← هذا الملف
   │  يفوّض إلى ↓
011 TRUTH + BACKENDS (readiness.service / execution.service /
                      research.service / providers_registry /
                      workflow.service / router)
```

لا منطق أعمال هنا — تفويض صريح موثق فقط، والسلوك الحتمي نفسه
للخدمات المصدر (لا نسخ حالة، لا جاهزية موازية، لا كاش جانبي).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


class LLMBroker(Protocol):
    """درزة النماذج — اختيار الدور + قابلية النقل الحي (لا استدعاء).

    المصدر: providers_registry.registry (الربط الدائم) + موجّه
    الإنتاج (has_live_provider). الاستدلال الفعلي يبقى داخل الأدوار
    عبر router.chat_live — هذه الدرزة للفحص والعرض فقط.
    """

    def role_selections(self) -> dict[str, Any]: ...

    def has_transport(self, transport_key: str) -> bool: ...


class CapabilityBroker(Protocol):
    """درزة الحقيقة — جاهزية القدرات من المصدر الوحيد (011 §12).

    المصدر: readiness.service (capability_view/capabilities_view/
    research_providers_view). لا اشتقاق موازٍ هنا أبدًا.
    """

    def capability_view(self, capability_id: str) -> dict | None: ...

    def capabilities_view(self) -> list[dict]: ...

    def research_providers_view(self) -> list[dict]: ...


class ExecutionBroker(Protocol):
    """درزة التنفيذ — المسبار والمنفذ من مسار resolve_executor واحد.

    المصدر: execution.service (010 §19 + 011 §19). الوظيفة المنتظرة
    لعامل تقرأ تفاصيل سلم الجاهزية من هنا حرفيًا.
    """

    def resolve_executor(self, policy: str | None = None) -> tuple: ...

    def list_environments(self) -> list[dict]: ...

    def owner_action_missing(self, policy: str | None = None) -> str: ...

    def host_truth(self) -> dict: ...


class ResearchBroker(Protocol):
    """درزة البحث — سلسلة مزودين بترتيب جاهزية وفشل مفصل عند النداء.

    المصدر: research.service.search (فشل الأول يعني محاولة التالي —
    FAILOVER زمن النداء) + research_providers_view للترتيب.
    """

    def search(self, query: str) -> dict: ...

    def providers_view(self) -> list[dict]: ...


class WorkflowStore(Protocol):
    """درزة الحالة الدائمة — مشاريع/خطط/بوابات/أحداث (القاعدة §9).

    المصدر: workflow.service. المنسق يقرأ ويكتب الحالة عبرها فقط.
    """

    def get_project(self, project_id: int) -> dict | None: ...

    def latest_plan(self, project_id: int) -> dict | None: ...

    def open_gates(self, project_id: int) -> list[dict]: ...

    def add_event(self, project_id: int, kind: str, payload: dict) -> None: ...

    def list_events(self, project_id: int, limit: int = 100) -> list[dict]: ...


@dataclass
class HarnessSeams:
    """حزمة الدروز الملموسة — تُبنى من خدمات 011 ولا تحمل حالة own.

    البناء رخيص (كائنات تفويض بلا حالة) فيمكن إنشاؤه لكل طلب أو
    لكل وظيفة دون تسريب. ``router_factory`` كسول — لا يبنى موجّهًا
    إلا عند الحاجة الفعلية للفحص.
    """

    sessions: Any
    router_factory: Callable[[], Any] | None = None

    # --- LLMBroker ------------------------------------------------- #

    def role_selections(self) -> dict[str, Any]:
        from providers_registry import registry

        return registry.get_mappings(self.sessions)

    def has_transport(self, transport_key: str) -> bool:
        if self.router_factory is None:
            return False
        router = self.router_factory()
        return bool(
            getattr(router, "has_live_provider", lambda _k: False)(
                transport_key
            )
        )

    # --- CapabilityBroker ------------------------------------------ #

    def capability_view(self, capability_id: str) -> dict | None:
        from readiness.service import capability_view

        return capability_view(self.sessions, capability_id)

    def capabilities_view(self) -> list[dict]:
        from readiness.service import capabilities_view

        return capabilities_view(self.sessions)

    def research_providers_view(self) -> list[dict]:
        from readiness.service import research_providers_view

        return research_providers_view(self.sessions)

    # --- ExecutionBroker ------------------------------------------- #

    def resolve_executor(self, policy: str | None = None) -> tuple:
        from execution import service as execution_service

        return execution_service.resolve_executor(
            self.sessions, policy=policy
        )

    def list_environments(self) -> list[dict]:
        from execution import service as execution_service

        return execution_service.list_environments(self.sessions)

    def owner_action_missing(self, policy: str | None = None) -> str:
        from execution import service as execution_service

        return execution_service.owner_action_for_missing_environment(
            self.sessions, policy=policy
        )

    def host_truth(self) -> dict:
        from execution.backends import runtime_truth

        return runtime_truth()

    # --- ResearchBroker -------------------------------------------- #

    def search(self, query: str) -> dict:
        from research import service as research_service

        return research_service.search(self.sessions, query)

    def providers_view(self) -> list[dict]:
        return self.research_providers_view()

    # --- WorkflowStore --------------------------------------------- #

    def get_project(self, project_id: int) -> dict | None:
        from workflow import service

        return service.get_project(self.sessions, project_id)

    def latest_plan(self, project_id: int) -> dict | None:
        from workflow import service

        return service.latest_plan(self.sessions, project_id)

    def open_gates(self, project_id: int) -> list[dict]:
        from workflow import service

        return service.open_gates(self.sessions, project_id)

    def add_event(self, project_id: int, kind: str, payload: dict) -> None:
        from workflow import service

        service.add_event(self.sessions, project_id, kind, payload)

    def list_events(self, project_id: int, limit: int = 100) -> list[dict]:
        from workflow import service

        return service.list_events(self.sessions, project_id, limit=limit)


__all__ = [
    "CapabilityBroker",
    "ExecutionBroker",
    "HarnessSeams",
    "LLMBroker",
    "ResearchBroker",
    "WorkflowStore",
]
