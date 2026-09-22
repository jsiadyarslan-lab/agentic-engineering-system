"""زمن تشغيل الأدوار في الـHarness (012-C) — الدور كيان أول لا دالة.

كل دور من الخمسة يوصف ببطاقة ``RoleDefinition`` معلنة (القرار
المحفوظ رقم 1: الأدوار تتواصل عبر العقود حصرًا):

- **الهوية**: اسم الدور وعرضه وموضعه في الحلقة (CYCLE).
- **العقود**: طلب pydantic ونتيجة pydantic — كل تواصل مع المنسق
  عبرهما؛ لا نص حر بين الأدوار أبدًا.
- **العقد النظامي**: البرومبت (prompts/<name>.md) — العقل الإجرائي
  للدور منفصل عن الكود.
- **الأدوات المسموحة**: قائمة بيضاء لكل دور — المنفذ وحده يحمل
  أدوات؛ بقية الأدوار تحليلية بلا أدوات.
- **سياسة الأدلة**: ما يخلفه الدور من برهان (خطة/مراجعة/مصنوعات
  بـsha256/حكم/قرار تحكيم).
- **الميزانية**: سقف استدعاءات LLM الحية للدور في المهمة الواحدة
  (المنفذ 2 — خطة الأدوات ثم كتابة التقرير؛ غيره 1).

``RoleRuntime`` غلاف تنفيذ واحد للأدوار جميعًا: حدث role/started
قبل الاستدعاء، تحقق النتيجة ضد عقد الدور، حدث role/completed أو
role/failed بعده — بنفس شكل الأحداث الذي يستهلكه الإسقاط. لا
يقرر شيئًا؛ التنقل بين الأدوار يبقى للمنسق الحتمي.

التنفيذ الفعلي للأدوار باقٍ في أدوار 011 (roles/live.py و
roles/implementer_live.py) — هذه الطبقة تعلّمها ولا تستبدلها.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

#: أدوات المنفذ المسموحة — من القائمة البيضاء في roles/tool_manifest
#: (أدوات سطر الأوامر التي يفهمها بروتوكول المنفذ الحي) + كتابة
#: الملف/القراءة/PDF التي يستدعيها كود التنفيذ نفسه.
IMPLEMENTER_TOOLS: tuple[str, ...] = (
    "web_search", "fetch_page", "http_get_text", "http_get_json",
    "page_to_text", "fred_csv", "worldbank_indicator",
    "write_file", "read_file",
    "generate_pdf_arabic", "verify_pdf_pages",
)

#: الأدوار التحليلية — بلا أدوات إطلاقًا (عقدها نصي خالص).
ANALYTICAL_TOOLS: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoleDefinition:
    """بطاقة تعريف دور — معلنة من الكود الفعلي لا من الوصف."""

    role: str
    display: str
    request_contract: type
    result_contract: type
    prompt: str                      # prompts/<prompt>.md
    allowed_tools: tuple[str, ...]
    evidence_policy: str
    max_live_calls: int
    enters_state: str                # حالة الحلقة عند دخول الدور
    exit_by: str                     # حقل النتيجة الذي يحدد الوجهة
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "display": self.display,
            "request_contract": self.request_contract.__name__,
            "result_contract": self.result_contract.__name__,
            "prompt": f"prompts/{self.prompt}.md",
            "allowed_tools": list(self.allowed_tools),
            "evidence_policy": self.evidence_policy,
            "max_live_calls": self.max_live_calls,
            "enters_state": self.enters_state,
            "exit_by": self.exit_by,
            "description": self.description,
        }


def _build_definitions() -> dict[str, RoleDefinition]:
    """بناء التعريفات من العقود الفعلية — الاستيراد كسول يمنع الدوران."""
    from roles.arbiter import ArbiterRequest, ArbiterResult
    from roles.implementer import ImplementerRequest, ImplementerResult
    from roles.reviewer import ReviewerRequest, ReviewerResult
    from roles.thinker import ThinkerRequest, ThinkerResult
    from roles.verifier import VerifierRequest, VerifierResult

    defs = (
        RoleDefinition(
            role="thinker", display="المفكر",
            request_contract=ThinkerRequest,
            result_contract=ThinkerResult,
            prompt="thinker", allowed_tools=ANALYTICAL_TOOLS,
            evidence_policy="PLAN_CONTRACT",
            max_live_calls=1, enters_state="DRAFT", exit_by="plan",
            description="يولّد الخطة بعقد صارم — المراجع يقيّمها؛ "
                        "لا يلمس أدوات ولا كودًا",
        ),
        RoleDefinition(
            role="reviewer", display="المدقق",
            request_contract=ReviewerRequest,
            result_contract=ReviewerResult,
            prompt="reviewer", allowed_tools=ANALYTICAL_TOOLS,
            evidence_policy="VERDICT_CONTRACT",
            max_live_calls=1, enters_state="UNDER_REVIEW",
            exit_by="verdict",
            description="يراجع الخطة ضد الهدف ويعيد حكمًا مهيكلًا — "
                        "جولات محدودة ثم التحكيم",
        ),
        RoleDefinition(
            role="implementer", display="المنفذ",
            request_contract=ImplementerRequest,
            result_contract=ImplementerResult,
            prompt="implementer", allowed_tools=IMPLEMENTER_TOOLS,
            evidence_policy="ARTIFACTS_SHA256",
            max_live_calls=2, enters_state="EXECUTING",
            exit_by="status",
            description="ينفذ المهمة بأدوات القائمة البيضاء داخل "
                        "الركيزة — استدعاءان حيّان حصرًا: خطة "
                        "الأدوات ثم كتابة التقرير",
        ),
        RoleDefinition(
            role="verifier", display="المراجع",
            request_contract=VerifierRequest,
            result_contract=VerifierResult,
            prompt="verifier", allowed_tools=ANALYTICAL_TOOLS,
            evidence_policy="EVIDENCE_VERDICT",
            max_live_calls=1, enters_state="VERIFYING",
            exit_by="verdict",
            description="يتحقق من المعايير ضد الأدلة الميكانيكية "
                        "(ملفات بـsha256) لا ضد نص المنفذ",
        ),
        RoleDefinition(
            role="arbiter", display="المحكَّم",
            request_contract=ArbiterRequest,
            result_contract=ArbiterResult,
            prompt="arbiter", allowed_tools=ANALYTICAL_TOOLS,
            evidence_policy="DECISION_CONTRACT",
            max_live_calls=1, enters_state="ADJUDICATED",
            exit_by="decision",
            description="يفصل تعارض التنفيذ/التحقق بإعادة أو تصعيد — "
                        "ضمن ميزانية مركزية لا يملكها",
        ),
    )
    return {d.role: d for d in defs}


ROLE_DEFINITIONS: dict[str, RoleDefinition] = _build_definitions()


def describe_roles() -> list[dict]:
    """التعريفات الخمسة مرتبة بترتيب الحلقة — للواجهة والفحص."""
    return [
        ROLE_DEFINITIONS[role].to_dict()
        for role in ("thinker", "reviewer", "implementer", "verifier",
                     "arbiter")
    ]


class RoleRuntime:
    """غلاف تنفيذ دور — أحداث role/* + إلزام عقد النتيجة.

    الاستعمال: ``RoleRuntime(definition, implementation, on_event=..)
    .run(request)``. لا يضيف منطقًا للقرار — فقط الملاحظة الصادقة:
    قبل الاستدعاء حدث ``role/started`` (بالمزود/النموذج إن وُجدا)،
    وبعده إلزام أن تكون النتيجة من نوع عقد الدور ثم حدث
    ``role/completed`` أو ``role/failed`` بفشل مهيكل.

    المنسق الحتمي (harness/jobs.py) يستهلك هذه الأحداث عبر
    الإسقاط؛ الأدوار نفسها تبقى تنفيذ 011 كما هي.
    """

    def __init__(self, definition: RoleDefinition, implementation: Any,
                 *, on_event: Callable[[dict], None] | None = None):
        self.definition = definition
        self.implementation = implementation
        self._on_event = on_event

    def _emit(self, kind: str, payload: dict) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event({
                "role": self.definition.role,
                "kind": f"role/{kind}",
                "payload": payload,
            })
        except Exception:  # noqa: BLE001 — المستقبِل لا يكسر الدور
            pass

    def run(self, request: Any) -> Any:
        """تنفيذ واحد موثق — عقد الدور هو القانون قبل وبعد."""
        selection = getattr(self.implementation, "selection", None)
        provider = getattr(selection, "provider", "") or ""
        model = getattr(selection, "model", "") or ""
        started = time.monotonic()
        self._emit("started", {
            "role": self.definition.role,
            "request_contract": self.definition.request_contract.__name__,
            "result_contract": self.definition.result_contract.__name__,
            "provider": provider, "model": model,
            "allowed_tools": list(self.definition.allowed_tools),
            "max_live_calls": self.definition.max_live_calls,
        })
        try:
            if not isinstance(request, self.definition.request_contract):
                raise TypeError(
                    f"طلب {type(request).__name__} لا يطابق عقد الدور "
                    f"{self.definition.request_contract.__name__}"
                )
            result = self.implementation.run(request)
            if not isinstance(result, self.definition.result_contract):
                raise TypeError(
                    f"نتيجة {type(result).__name__} تخرق عقد الدور "
                    f"{self.definition.result_contract.__name__} — "
                    "لا تمر بلا إلزام"
                )
        except Exception as error:  # noqa: BLE001 — فشل مهيكل معلن
            self._emit("failed", {
                "role": self.definition.role,
                "error": f"{type(error).__name__}: {error}"[:400],
                "duration_ms": int((time.monotonic() - started) * 1000),
            })
            raise
        self._emit("completed", {
            "role": self.definition.role,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "result_contract": type(result).__name__,
            "provider": provider, "model": model,
        })
        return result


def role_runtime_view(seams) -> list[dict]:
    """الأدوار الخمسة كما تعمل الآن — تعريف + ربط حي + جاهزية.

    لكل دور: بطاقته المعلنة + المزود/النموذج المرتبط فعليًا من سجل
    المزودين + هل النقل الحي قابل للحل — عرض واحد صادق يستهلكه
    ``/api/harness/roles`` والفحص المسبق.
    """
    mappings = seams.role_selections()
    view = []
    for described in describe_roles():
        role = described["role"]
        mapping = mappings.get(role) or {}
        transport = (
            f"{mapping.get('provider', '')}::{mapping.get('configuration', '')}"
            if mapping.get("configuration")
            else mapping.get("provider", "")
        )
        has_transport = bool(mapping.get("provider")) \
            and seams.has_transport(transport)
        view.append({
            **described,
            "live_selection": {
                "provider": mapping.get("provider", ""),
                "configuration": mapping.get("configuration", ""),
                "model": mapping.get("model", ""),
                "transport_key": transport,
                "ready": has_transport,
            },
            "prompt_exists": _prompt_exists(described["prompt"]),
        })
    return view


def _prompt_exists(prompt_path: str) -> bool:
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / prompt_path
    return path.is_file()


__all__ = [
    "ANALYTICAL_TOOLS",
    "IMPLEMENTER_TOOLS",
    "ROLE_DEFINITIONS",
    "RoleDefinition",
    "RoleRuntime",
    "describe_roles",
    "role_runtime_view",
]
