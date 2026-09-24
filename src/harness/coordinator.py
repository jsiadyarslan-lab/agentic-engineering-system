"""المنسق الحتمي (012-F) — القرار رقم 2 محفوظًا بنيويًا: لا LLM هنا.

كل ما في هذا الملف دوال نقية خالصة: نفس المدخلات ← نفس القرار،
دائمًا، بلا نموذج ولا عشوائية ولا وقت. المنسق في الـHarness هو
**مستوى تحكم** (control plane) لا وكيل:

- ``JOB_TRANSITIONS``: جدول انتقالات الوظيفة المقفل.
- ``classify_tick()``: نتيجة tick المحرك + الحالة الدائمة ←
  حالة الوظيفة + نوع الانتظار + تفصيله — التصنيف الوحيد الذي
  يفرّق WAITING_WORKER عن WAITING_CAPABILITY عن WAITING_GATE.
- ``current_role_of()``: الدور الذي يعمل الآن — من الحالة الدائمة
  لا من تخمين.
- ``can_transition()``: بوابة الانتقال التي يمر منها JobManager.

النموذج يفكر داخل الأدوار (harness/roles_runtime)؛ المحرك يملك
آلة حالة المشروع (workflow/engine)؛ هذا الملف يقرر كيف تُقرأ
حركتهما كوظيفة قابلة للنبض والانقطاع والاستئناف — حتميًا.
"""

from __future__ import annotations

from harness.capabilities import blocked_kind_of

#: جدول انتقالات الوظيفة — مقفل؛ كل انتقال خارج القائمة مرفوض.
JOB_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "QUEUED": ("RUNNING", "PAUSED", "FAILED", "STOPPED"),
    "RUNNING": (
        "RUNNING", "RETRYING", "REVISING", "WAITING_CAPABILITY",
        "WAITING_WORKER", "WAITING_GATE", "WAITING_PLANNING",
        "PAUSED", "COMPLETED", "FAILED", "STOPPED", "ESCALATED",
        "INTERRUPTED",
    ),
    "RETRYING": (
        "RUNNING", "RETRYING", "REVISING", "WAITING_CAPABILITY",
        "WAITING_WORKER", "WAITING_GATE", "WAITING_PLANNING",
        "PAUSED", "FAILED", "STOPPED", "ESCALATED",
    ),
    "REVISING": (
        "RUNNING", "WAITING_GATE", "WAITING_PLANNING", "PAUSED",
        "FAILED", "STOPPED",
    ),
    "WAITING_CAPABILITY": (
        "QUEUED", "RUNNING", "WAITING_CAPABILITY", "WAITING_WORKER",
        "WAITING_PLANNING", "PAUSED", "FAILED", "STOPPED",
    ),
    "WAITING_WORKER": (
        "QUEUED", "RUNNING", "WAITING_WORKER", "WAITING_CAPABILITY",
        "WAITING_PLANNING", "PAUSED", "FAILED", "STOPPED",
    ),
    "WAITING_GATE": (
        "QUEUED", "RUNNING", "WAITING_GATE", "REVISING", "PAUSED",
        "COMPLETED", "FAILED", "STOPPED", "ESCALATED",
    ),
    # (013.4 §2) التخطيط الخلفي جارٍ — الجلسة تحمل النبضة والإيجار
    "WAITING_PLANNING": (
        "QUEUED", "RUNNING", "WAITING_GATE", "WAITING_PLANNING",
        "PAUSED", "FAILED", "STOPPED",
    ),
    "PAUSED": ("QUEUED", "RUNNING", "PAUSED", "STOPPED", "FAILED"),
    "INTERRUPTED": ("QUEUED", "RUNNING", "STOPPED", "FAILED"),
    "COMPLETED": (), "FAILED": (), "STOPPED": (), "ESCALATED": (),
}

#: أفعال tick التي توقف الحلقة (نفس روح engine.run).
_TICK_STOP_ACTIONS = ("none", "paused", "stopped", "blocked",
                      "wait_owner", "failed", "wait_planning")

#: بوابات تعني «مزود/قدرة غير جاهزة» — انتظار قدرة لا قرارًا.
_CAPABILITY_GATE_KINDS = ("PROVIDER_ACTION_REQUIRED",)


def can_transition(current: str, target: str) -> bool:
    """هل الانتقال مسموح؟ — جدول مقفل، الخارج مرفوض."""
    if current == target:
        return True
    return target in JOB_TRANSITIONS.get(current, ())


#: أنواع الانتظار الصادقة (مطابقة harness/models) — التخطيط
#: الخلفي (013.4 §2) انتظار من عائلة القدرة لكنه معلن باسمه.
WAITING_KINDS = ("CAPABILITY", "WORKER", "GATE", "PLANNING")


def classify_tick(tick_result: dict, *, project: dict,
                  open_gates: list[dict],
                  retry_requested: bool = False) -> dict:
    """تصنيف حتمي واحد لنتيجة tick — قرار الوظيفة كله هنا.

    المدخلات كلها من الحقيقة الدائمة (نتيجة tick + حالة المشروع +
                  البوابات المفتوحة)، والخرج:
    {status, waiting_kind, waiting_detail, terminal, stop}

    القواعد (معلنة ومختبرة):
    - none ← نهائية المشروع: VERIFIED → COMPLETED (القناة الوحيدة
      إضافة إلى mark_verified)، COMPLETED/مرشح → WAITING_GATE
      (التحقق النهائي للمالك — لا اكتمال وظيفة بلا تحقق)،
      STOPPED → STOPPED، ESCALATED → ESCALATED.
    - wait_owner أو blocked ببوابة قرار → WAITING_GATE.
    - blocked بمزود غير جاهز (PROVIDER_ACTION_REQUIRED) →
      WAITING_CAPABILITY.
    - blocked بفحص مسبق → تصنيف كل قدرة محجوبة: worker حكرًا
      (sandbox) → WAITING_WORKER؛ غيرها → WAITING_CAPABILITY؛
      الاثنان معًا → WAITING_CAPABILITY مع تفصيل يشمل العامل.
    - continue + REVISING → REVISING؛ + RETRY_REQUESTED →
      RETRYING؛ وإلا RUNNING.
    """
    action = tick_result.get("action", "")
    waiting_detail: dict = {}
    waiting_kind = ""

    if action == "none":
        project_status = project.get("status", "")
        if project_status == "VERIFIED":
            status = "COMPLETED"
        elif project_status == "COMPLETED":
            # مرشح بانتظار تحقق المالك — عمل الحلقة انتهى والقرار
            # معلق؛ الوظيفة تنتظر البوابة لا تكتمل (الصدق 012-E)
            status, waiting_kind = "WAITING_GATE", "GATE"
            waiting_detail = {
                "summary": "المشروع مرشح للإكمال — التحقق النهائي "
                           "قرار المالك وحده",
                "gate_kinds": [g.get("kind", "") for g in open_gates]
                or ["FINAL_VERIFICATION"],
            }
        elif project_status == "STOPPED":
            status = "STOPPED"
        elif project_status == "ESCALATED":
            status = "ESCALATED"
        else:
            status = "FAILED"
            waiting_detail = {"summary": f"الحالة النهائية للمشروع "
                                         f"{project_status} بلا اكتمال"}
        return {
            "status": status, "waiting_kind": waiting_kind,
            "waiting_detail": waiting_detail,
            "terminal": status in ("COMPLETED", "STOPPED",
                                   "ESCALATED", "FAILED"),
            "stop": True,
        }

    if action == "paused":
        return {"status": "PAUSED", "waiting_kind": "",
                "waiting_detail": {"summary": tick_result.get("reason",
                                                              "")},
                "terminal": False, "stop": True}

    if action == "stopped":
        # (013.4 §12) إيقاف نهائي دائم — الوظيفة تغلق صادقة والبيانات
        # كلها محفوظة (لا حذف أبدًا)
        return {"status": "STOPPED", "waiting_kind": "",
                "waiting_detail": {
                    "summary": tick_result.get("reason", "إيقاف نهائي"),
                    "preserved": ["events", "evidence", "checkpoints",
                                  "history"],
                },
                "terminal": True, "stop": True}

    if action == "failed":
        return {"status": "FAILED", "waiting_kind": "",
                "waiting_detail": {"summary": tick_result.get("reason",
                                                              "")[:300]},
                "terminal": True, "stop": True}

    if action == "wait_owner":
        gate_kinds = [g.get("kind", "") for g in open_gates]
        return {
            "status": "WAITING_GATE", "waiting_kind": "GATE",
            "waiting_detail": {
                "summary": tick_result.get("reason", "قرار مالك معلق"),
                "gate_kinds": gate_kinds,
            },
            "terminal": False, "stop": True,
        }

    if action == "wait_planning":
        # (013.4 §2+§3) التخطيط الخلفي جارٍ — انتظار تخطيط معلن
        # بجلسته: المزود/النموذج/الطلب/النبضة كلها في waiting_detail.
        planning = tick_result.get("planning") or {}
        return {
            "status": "WAITING_PLANNING", "waiting_kind": "PLANNING",
            "waiting_detail": {
                "summary": tick_result.get("reason",
                                           "توليد الخطة جارٍ"),
                "planning": planning,
            },
            "terminal": False, "stop": True,
        }

    if action == "blocked":
        gate_kinds = [g.get("kind", "") for g in open_gates]
        # مزود غير جاهز — بوابة PROVIDER_ACTION_REQUIRED (007.1 §17)
        if any(k in _CAPABILITY_GATE_KINDS for k in gate_kinds):
            unready = next(
                (g.get("details", {}).get("unready")
                 for g in open_gates
                 if g.get("kind") in _CAPABILITY_GATE_KINDS),
                [],
            )
            return {
                "status": "WAITING_CAPABILITY",
                "waiting_kind": "CAPABILITY",
                "waiting_detail": {
                    "summary": tick_result.get("reason",
                                               "مزود غير جاهز"),
                    "gate_kinds": gate_kinds,
                    "unready_roles": [
                        u.get("role", "") for u in (unready or [])
                    ],
                    "owner_action": next(
                        (str(g.get("details", {}).get("required_action",
                                                     ""))
                         for g in open_gates
                         if g.get("kind") in _CAPABILITY_GATE_KINDS),
                        "راجع المزود/التكوين من الإعدادات ثم اختبره",
                    ),
                },
                "terminal": False, "stop": True,
            }
        # فحص مسبق محجوب — تصنيف القدرات المحجوبة واحدًا واحدًا
        if tick_result.get("blocked_kind") == "preflight":
            preflight = tick_result.get("preflight") or {}
            blocked = preflight.get("blocked") or []
            return _classify_preflight_block(
                blocked, gate_kinds, summary=tick_result.get("reason",
                                                             "")
            )
        # بوابة قرار (مراجعة خطة/تصعيد) — قرار مالك
        return {
            "status": "WAITING_GATE", "waiting_kind": "GATE",
            "waiting_detail": {
                "summary": tick_result.get("reason", "بوابة قرار مالك"),
                "gate_kinds": gate_kinds,
            },
            "terminal": False, "stop": True,
        }

    # action == "continue" — الحلقة مستمرة
    if project.get("status") == "REVISING":
        return {"status": "REVISING", "waiting_kind": "",
                "waiting_detail": {}, "terminal": False, "stop": False}
    if retry_requested:
        return {"status": "RETRYING", "waiting_kind": "",
                "waiting_detail": {"summary": tick_result.get("reason",
                                                              "")},
                "terminal": False, "stop": False}
    return {"status": "RUNNING", "waiting_kind": "",
            "waiting_detail": {}, "terminal": False, "stop": False}


def _classify_preflight_block(blocked: list[dict], gate_kinds: list[str],
                              *, summary: str) -> dict:
    """تصنيف حجب الفحص المسبق — worker حكرًا على بيئة التنفيذ.

    القدرة sandbox مشتقة من سجل البيئات (011 §12) وانتظارها
    WAITING_WORKER (سلم العامل: connectivity → … → artifact)؛
    كل قدرة أخرى (web_search/llm/…) انتظار قدرة WAITING_CAPABILITY.
    اختلاطهما = قدرة (التفصيل يُظهر العامل أيضًا — لا إخفاء).
    """
    capability_ids = [
        str(b.get("capability_id", "")) for b in blocked
    ]
    kinds = {blocked_kind_of(cid) for cid in capability_ids if cid}
    owner_action = next(
        (str(b.get("owner_action")) for b in blocked
         if b.get("owner_action")), "",
    )
    required_env = next(
        (str(b.get("required_environment")) for b in blocked
         if b.get("required_environment")), "",
    )
    if kinds == {"WORKER"}:
        status, waiting_kind = "WAITING_WORKER", "WORKER"
    else:
        status, waiting_kind = "WAITING_CAPABILITY", "CAPABILITY"
    return {
        "status": status,
        "waiting_kind": waiting_kind,
        "waiting_detail": {
            "summary": (summary or "الفحص المسبق محجوب")[:300],
            "gate_kinds": gate_kinds,
            "blocked": [
                {
                    "capability_id": b.get("capability_id", ""),
                    "status": b.get("status", ""),
                    "required_environment":
                        b.get("required_environment", ""),
                    "owner_action": (b.get("owner_action") or "")[:300],
                }
                for b in blocked
            ],
            "required_environment": required_env,
            "owner_action": owner_action[:400],
            "recovery": "وفّر المتطلب ← تحقق ← أعد الفحص ← استئناف "
                        "(بلا إعادة اعتماد)",
        },
        "terminal": False, "stop": False,
    }


def current_role_of(project: dict, execution: dict | None) -> str:
    """الدور الذي يعمل الآن — من الحالة الدائمة لا من تخمين.

    تنفيذ جارٍ ← دور التنفيذ المسجل؛ توليد/مراجعة خطة ← المفكر؛
    خلاف ذلك المنسق (الفحص/الجدولة/البوابات).
    """
    if execution is not None and execution.get("status") == "RUNNING":
        return execution.get("agent_role", "") or "implementer"
    status = project.get("status", "")
    if status in ("PLANNING", "REVISING"):
        return "thinker"
    if status in ("AWAITING_OWNER_APPROVAL", "READY"):
        return "coordinator"
    return "coordinator"


def waiting_unblock_path(waiting_kind: str) -> str:
    """مسار رفع كل انتظار — نص واحد صادق لكل نوع (للواجهة)."""
    return {
        "CAPABILITY": "جهّز المزود/القدرة من الإعدادات ← اختبره ← "
                      "أعد الفحص/الاستئناف",
        "WORKER": "أضف بيئة تنفيذ (عامل Linux/WSL2 أو ركيزة محلية) "
                  "← تحقق منها ← أعد الفحص ← استئناف",
        "GATE": "عالج البوابة المعلقة من صفحة المشروع — القرار لك",
        "PLANNING": "انتظر اكتمال التوليد أو أعده من زر الإعادة — "
                    "الجلسة تعرض ما تنتظره حرفيًا",
    }.get(waiting_kind, "")


__all__ = [
    "JOB_TRANSITIONS",
    "WAITING_KINDS",
    "can_transition",
    "classify_tick",
    "current_role_of",
    "waiting_unblock_path",
]
