"""إسقاطات الـHarness (012-D) — خط زمن مرحلي وسلسلة قبول من الأحداث.

الإسقاط (projection) اشتقاق قراءة فقط من السجل الدائم — لا يكتب
حالة أبدًا: الأحداث في project_events هي الحقيقة، وهنا تُبنى
القراءات التي تستهلكها الواجهة:

- **project_timeline(events)**: كل حدث ← بند خط زمني {stage,
  canonical, at, actor, title, detail, status} — عنوان عربي صادق
  لكل نوع + تفصيل مختصر من الحمولة.

- **acceptance_chain(events)**: سلسلة القبول الكاملة (Owner →
  Objective → … → VERIFIED): لكل مرحلة حالتها الحتمية (PENDING/
  ACTIVE/DONE/WAITING/FAILED) وأول/آخر علامة رُصدت لها — البطاقة
  التي تُظهر «أين يقف المسار الآن ولماذا توقف» بلا غموض.

الاشتقاق حتمي خالص من الأنواع القانونية (harness/events.py) —
نفس الأحداث تنتج دائمًا نفس الإسقاط، وهو ما تختبره الاختبارات.
"""

from __future__ import annotations

from harness.events import (
    CHAIN_STAGES,
    canonical,
    event_stage,
    stage_status,
)

#: عناوين عربية صادقة لكل نوع قانوني — مصدر عرض الواجهة.
TITLES: dict[str, str] = {
    "project/created": "إنشاء المشروع",
    "plan/created": "توليد الخطة",
    "plan/revised": "مراجعة الخطة",
    "owner/gate.requested": "بوابة مالك: قرار مطلوب",
    "plan/approved": "اعتماد الخطة",
    "phase/started": "بدء مرحلة",
    "phase/completed": "اكتمال مرحلة",
    "step/started": "بدء خطوة",
    "execution/started": "بدء تنفيذ",
    "execution/completed": "اكتمال تنفيذ",
    "execution/failed": "فشل تنفيذ",
    "execution/blocked": "تنفيذ محجوب",
    "retry/requested": "إعادة محاولة",
    "policy/changed": "تغيير سياسة التنفيذ",
    "preflight/pass": "الفحص المسبق ناجح",
    "preflight/blocked": "الفحص المسبق محجوب",
    "preflight/rechecked": "إعادة الفحص",
    "evidence/created": "تسجيل دليل",
    "verifier/completed": "اكتمال تحقق المراجع",
    "review/completed": "اكتمال مراجعة",
    "audit/created": "تدقيق",
    "arbiter/decision": "قرار المحكَّم",
    "checkpoint/created": "نقطة حفظ",
    "owner/gate.resolved": "حل بوابة المالك",
    "owner/gate.auto_resolved": "فتح تلقائي بعد التوفير",
    "project/paused": "إيقاف مؤقت",
    "project/stopped": "إيقاف نهائي",
    "resume/started": "استئناف",
    "project/completion_candidate": "مرشح للإكمال",
    "project/verified": "تحقق المالك — VERIFIED",
    "recovery/assessed": "تقييم الاسترداد",
    "job/queued": "وظيفة في الطابور",
    "job/created": "إنشاء الوظيفة الدائمة",
    "job/started": "بدء الوظيفة",
    "job/waiting": "الوظيفة تنتظر بأمان",
    "job/retrying": "الوظيفة تعيد المحاولة",
    "job/revising": "الوظيفة تراجع الخطة",
    "job/paused": "إيقاف الوظيفة عند checkpoint",
    "job/resumed": "استئناف الوظيفة",
    "job/completed": "اكتمال الوظيفة",
    "job/failed": "فشل الوظيفة",
    "job/stopped": "إيقاف الوظيفة",
    "job/escalated": "تصعيد الوظيفة",
    "job/interrupted": "انقطاع الوظيفة (وفاة العملية)",
    "job/recovery_assessed": "تقييم استرداد الوظيفة",
    # (013 §4) سلسلة الفحص المعلنة
    "preflight/started": "بدء فحص ما قبل التنفيذ",
    "preflight/capabilities": "تقييم قدرات التنفيذ",
    "environment/check.started": "فحص بيئة التنفيذ",
    "environment/ready": "بيئة التنفيذ جاهزة",
    "environment/heartbeat": "نبضة بيئة التنفيذ",
    "execution/opened": "التنفيذ مفتوح",
    "step/completed": "اكتمال خطوة",
    "stage/review": "مراجعة المرحلة",
    "role/executing": "دور يعمل الآن",
    "tool/execution": "استدعاء أداة",
    # (013 §13) المتصفح
    "browser/session.created": "فتح جلسة متصفح",
    "browser/navigate": "الانتقال إلى صفحة",
    "browser/page.loaded": "تحميل الصفحة",
    "browser/click": "نقر عنصر",
    "browser/type": "إدخال نص",
    "browser/screenshot": "التقاط لقطة شاشة",
    "browser/extract": "استخلاص محتوى",
    "browser/download": "تنزيل ملف",
    "browser/session.closed": "إغلاق جلسة المتصفح",
    "browser/session.interrupted": "انقطاع جلسة المتصفح",
    # (013 §16) التجهيز
    "provisioning/started": "بدء تجهيز البيئة",
    "provisioning/completed": "اكتمال تجهيز البيئة",
    "provisioning/failed": "فشل تجهيز البيئة",
    "provisioning/unavailable": "التجهيز غير متاح — متطلب خارجي",
    "owner/resource.waiting": "بانتظار مورد من المالك",
}

#: أي حقل حمولة يظهر كتفصيل أولًا — الأهم للعرض الصادق.
_DETAIL_KEYS = ("summary", "reason", "note", "verdict", "owner_action",
                "required", "detail")


def _title_for(canonical_kind: str, payload: dict) -> str:
    """عنوان البند — نص النوع + هوية المحل (مرحلة/خطوة/بوابة)."""
    base = TITLES.get(canonical_kind, canonical_kind)
    for key in ("phase_title", "title"):
        if payload.get(key):
            return f"{base}: {str(payload[key])[:80]}"
    if payload.get("step_id") and canonical_kind.startswith(
            ("step/", "execution/", "evidence/")):
        return f"{base} (خطوة #{payload['step_id']})"
    return base


def _detail_for(payload: dict) -> str:
    """تفصيل مختصر صادق — أول حقل معلن مهم، لا تفريغ كامل."""
    for key in _DETAIL_KEYS:
        value = payload.get(key)
        if value:
            return str(value)[:220]
    if payload.get("error"):
        return str(payload["error"])[:220]
    return ""


def project_timeline(events: list[dict]) -> dict:
    """خط زمن مرحلي من أحداث المشروع — قراءة فقط.

    كل حدث {id, kind, payload, created_at} ← بند واحد، مرتبًا كما
    ورد (تصاعديًا). الأنواع الداخلية (Stream/تشغيل) تُمرَّر كما هي
    بلا عنوان مخصص — لا حذف ولا تزيين.
    """
    items = []
    for event in events:
        kind = event.get("kind", "")
        payload = event.get("payload") or {}
        canonical_kind = canonical(kind)
        items.append({
            "id": event.get("id"),
            "stage": event_stage(kind),
            "kind": kind,
            "canonical": canonical_kind,
            "at": event.get("created_at", ""),
            "actor": _actor_for(canonical_kind),
            "title": _title_for(canonical_kind, payload),
            "detail": _detail_for(payload),
            "waiting_kind": payload.get("waiting_kind", ""),
        })
    return {"stages": list(CHAIN_STAGES), "items": items}


def _actor_for(canonical_kind: str) -> str:
    """من فعل الفعل — المالك/المنسق/الدور/المحرك."""
    if canonical_kind.startswith("owner/") \
            or canonical_kind in ("project/created", "plan/approved",
                                  "project/verified", "project/stopped",
                                  "project/paused"):
        return "owner"
    if canonical_kind.startswith(("plan/", "phase/", "step/")):
        return "thinker"
    if canonical_kind.startswith("execution/"):
        return "implementer"
    if canonical_kind in ("verifier/completed", "evidence/created"):
        return "verifier"
    if canonical_kind == "arbiter/decision":
        return "arbiter"
    if canonical_kind.startswith(("job/", "preflight/", "checkpoint/")):
        return "coordinator"
    return "system"


def acceptance_chain(events: list[dict]) -> dict:
    """سلسلة القبول — أين يقف المسار الآن ولماذا (حتمية خالصة).

    لكل مرحلة في CHAIN_STAGES: حالتها + عدد أحداثها + آخر علامة
    رُصدت (نوع قانوني + وقت) + وصف الانتظار إن كانت WAITING (سبب
    الحجب الحرفي من الحمولة — لا إعادة صياغة تخفيه).
    """
    canonical_kinds: set[str] = set()
    by_stage: dict[str, list[dict]] = {stage: [] for stage in CHAIN_STAGES}
    for event in events:
        kind = event.get("kind", "")
        payload = event.get("payload") or {}
        canonical_kind = canonical(kind)
        canonical_kinds.add(canonical_kind)
        stage = event_stage(kind)
        by_stage.setdefault(stage, []).append({
            "canonical": canonical_kind,
            "at": event.get("created_at", ""),
            "payload": payload,
        })

    stages_view = []
    for stage in CHAIN_STAGES:
        stage_events = by_stage.get(stage, [])
        status = stage_status(stage, canonical_kinds)
        last = stage_events[-1] if stage_events else None
        waiting_reason = ""
        if status == "WAITING" and last is not None:
            waiting_reason = _detail_for(last["payload"]) \
                or last["canonical"]
        stages_view.append({
            "stage": stage,
            "status": status,
            "events": len(stage_events),
            "last_at": (last or {}).get("at", ""),
            "last_mark": (last or {}).get("canonical", ""),
            "waiting_reason": waiting_reason[:300],
        })
    return {
        "stages": stages_view,
        "complete": all(
            s["status"] == "DONE" for s in stages_view
            if s["stage"] in ("OBJECTIVE", "APPROVAL", "VERIFICATION")
        ),
    }


__all__ = ["TITLES", "acceptance_chain", "project_timeline"]
