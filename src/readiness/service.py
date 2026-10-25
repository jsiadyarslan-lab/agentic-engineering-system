"""خدمة الجاهزية (الأمر 011 §12-§14) — مصدر واحد للحقيقة.

المشكلة التي يحلها هذا الموديول (011 §12): «بحث الويب EXPIRED»
بينما «DuckDuckGo جاهز» — حالتان متناقضتان لأن كل شاشة أعادت
الحساب بطريقتها. هنا **اشتقاق واحد** تستهلكه كل الواجهات:

    UI (لوحة البيئة) ─┐
    Preflight ─────────┼─→ readiness.service.capability_view()
    Planner ───────────┤      (قاموس واحد مشتق من المصدر نفسه)
    Task Engine ───────┘

قواعد الاشتقاق (§12-§13):
- حالة المزود تُشتق بمصدرها هي: NOT_CONFIGURED (لم يُعد) |
  DISABLED | UNKNOWN | READY (مسبار حديث ناجح) | STALE (مسبار
  ناجح انتهت صلاحيته) | NOT_READY (فشل معلن).
- حالة القدرة المجمعة (web_search) تُشتق من مزوديها حصرًا: أي جاهز
  حديث → READY؛ جاهز منتهي الصلاحية → STALE يسمي المزود (فلا
  تناقض «مزود جاهز/قدرة منتهية» أبدًا)؛ الكل غير معد → NOT_CONFIGURED.
- EXPIRED ليست READY أبدًا حتى إعادة فحص ناجحة (§13) — والضغط
  «فحص حقيقي» ينقل STALE → PROBING → READY ويحدّث كل النظم
  المعتمدة لأنها تقرأ من هنا.
"""

from __future__ import annotations

import datetime as _dt
import json

from sqlalchemy import select

from readiness import registry
from readiness.probes import TTL_DEFAULTS

#: صلاحية مسبار مزود البحث (ثواني) — تنتهي فيُعرض STALE لا READY
RESEARCH_PROVIDER_TTL_S = 600


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse_ts(raw: str | None) -> _dt.datetime | None:
    if not raw:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def _is_expired(last_probe_at: str | None, ttl_s: int) -> bool:
    probed = _parse_ts(last_probe_at)
    if probed is None:
        return False
    return (_utc_now() - probed).total_seconds() > ttl_s


# ------------------------------------------------------------------ #
# مزودو البحث — حالة مشتقة واحدة (011 §12)
# ------------------------------------------------------------------ #

def _provider_configured(record: dict) -> bool:
    """هل المزود معد بالفعل؟ (011 §16: غير المعد NOT_CONFIGURED لا READY)"""
    config = record.get("config") or {}
    kind = record.get("kind", "")
    if kind == "search_ddg":
        return True                       # نقطة النهاية الافتراضية كافية
    if kind == "search_bing":
        # (013.2) Bing بلا مفاتيح — النقطة الافتراضية كافية كما DDG؛
        # كان يُرجع False فتُهدر جاهزيته رغم مسبار READY ناجح
        return True
    if kind == "search_wikipedia":
        # (013.5 §L) ويكيبيديا بلا مفاتيح وبلا رابط مثيل: واجهة
        # MediaWiki العامة هي النقطة الافتراضية. دون هذا الفرع كان
        # `return False` الأخير يوسمها NOT_CONFIGURED — فيُستبعد المزود
        # الوحيد الذي يعمل فعلًا من هذا المضيف، ويبقى §L بلا مصادر.
        return True
    if kind == "search_searx":
        return bool(config.get("base_url"))
    if kind == "search_api":
        if not config.get("endpoint"):
            return False
        from secrets_store import store

        return bool(store.get_key(f"research::{record.get('name', '')}"))
    return False


def provider_effective_state(record: dict) -> dict:
    """حالة المزود المشتقة — بمصدر واحد لكل الشاشات (011 §12-§13).

    stored_status يبقى كما كتبه المسبار؛ ``status`` المعروض يطبق
    الصلاحية: مسبار READY انتهت صلاحيته = STALE (منتهية) بلا
    استثناء — فلا يمكن أن يقول المزود «جاهز» والقدرة «منتهية».
    """
    stored = record.get("last_probe_status", "UNKNOWN")
    if not record.get("enabled", True):
        return {
            "status": "DISABLED",
            "configured": _provider_configured(record),
            "reason": "معطل بقرار المالك",
            "stale": False,
        }
    if not _provider_configured(record):
        return {
            "status": "NOT_CONFIGURED",
            "configured": False,
            "reason": "غير معد — عيّن رابطه/مفتاحه من إعدادات البحث ثم افحص",
            "stale": False,
        }
    if stored == "UNKNOWN":
        return {
            "status": "UNKNOWN", "configured": True,
            "reason": "معد ولم يُفحص بعد — اضغط فحص", "stale": False,
        }
    expired = _is_expired(record.get("last_probe_at"),
                          RESEARCH_PROVIDER_TTL_S)
    if stored == "READY" and expired:
        return {
            "status": "STALE", "configured": True, "stale": True,
            "reason": "مسبار ناجح انتهت صلاحيته — أعد الفحص لتحديثها",
        }
    return {
        "status": stored, "configured": True, "stale": False,
        "reason": record.get("failure_reason", ""),
    }


def research_providers_view(sessions) -> list[dict]:
    """كل مزودي البحث بحالتهم المشتقة — للواجهة والجرد حصرًا."""
    from research import service as research_service

    out: list[dict] = []
    for record in research_service.list_providers(sessions):
        state = provider_effective_state(record)
        out.append({
            **record,
            "effective_status": state["status"],
            "configured": state["configured"],
            "stale": state["stale"],
            "state_reason": state["reason"],
        })
    return out


def _web_search_capability(sessions, stored: dict) -> dict:
    """اشتقاق قدرة web_search من مزوديها (011 §12) — مصدر واحد."""
    providers = research_providers_view(sessions)
    ready_fresh = [
        p for p in providers if p["effective_status"] == "READY"
    ]
    stale_ready = [
        p for p in providers if p["effective_status"] == "STALE"
    ]
    out = dict(stored)
    out["derived_from"] = "research_providers"
    if ready_fresh:
        out["readiness_status"] = "READY"
        out["failure_reason"] = ""
        out["reason"] = (
            "مزود بحث جاهز بمسبار حقيقي حديث: "
            + "، ".join(p["name"] for p in ready_fresh)
        )
        out["details"] = {
            **(out.get("details") or {}),
            "ready_providers": [p["name"] for p in ready_fresh],
            "per_provider": [
                {"provider": p["name"], "status": p["effective_status"]}
                for p in providers
            ],
        }
    elif stale_ready:
        # (011 §12-§13) القدرة والمزود يتفقان: كلاهما منتهٍ حتى فحص جديد
        out["readiness_status"] = "STALE"
        out["reason"] = (
            "مسبار المزود(ات) "
            + "، ".join(p["name"] for p in stale_ready)
            + " انتهت صلاحيته — أعد الفحص لتحديث الجاهزية"
        )
        out["failure_reason"] = out["reason"]
        out["details"] = {
            **(out.get("details") or {}),
            "stale_providers": [p["name"] for p in stale_ready],
            "per_provider": [
                {"provider": p["name"], "status": p["effective_status"]}
                for p in providers
            ],
        }
    else:
        not_configured = [
            p for p in providers
            if p["effective_status"] == "NOT_CONFIGURED"
        ]
        out["readiness_status"] = (
            "NOT_CONFIGURED" if len(not_configured) == len(providers)
            else "NOT_READY"
        )
        out["reason"] = (
            "كل مزودي البحث غير معدّين — جهّز SearXNG (رابط) أو "
            "Search API (نقطة+مفتاح) من إعدادات البحث"
            if out["readiness_status"] == "NOT_CONFIGURED" else
            "لا مزود بحث جاهز — "
            + "؛ ".join(
                f"{p['name']}: {p['effective_status']}"
                + (f" ({p['state_reason'][:80]})" if p["state_reason"] else "")
                for p in providers if p["effective_status"] != "DISABLED"
            )
        )
        out["failure_reason"] = out["reason"]
        out["details"] = {
            **(out.get("details") or {}),
            "per_provider": [
                {"provider": p["name"], "status": p["effective_status"]}
                for p in providers
            ],
        }
    return out


# ------------------------------------------------------------------ #
# القدرات — عرض مشتق واحد (011 §14)
# ------------------------------------------------------------------ #

#: القدرات المجمعة — تُشتق حيًا من مصادرها لا من سجلها المخزن وحده
_AGGREGATED: dict[str, str] = {
    "web_search": "research_providers",
    "sandbox": "execution_environment",
    # (AES-EXP-03 P2) الجاهزية الحقيقية للاستخدام: دليل استدعاء حي
    # حديث (نجاح/فشل مسجل) لا سؤال «هل فُحص المزود؟» — هذا هو جذر
    # التناقض الموثق: محادثة ناجحة فعليًا بينما readiness_status=UNKNOWN.
    "llm": "live_call_evidence",
}


# ------------------------------------------------------------------ #
# قدرة LLM — اشتقاق من أدلة الاستدعاء الحي + المسبار المخزن (AES-EXP-03 P2)
# ------------------------------------------------------------------ #

def _llm_live_evidence(sessions) -> dict:
    """آخر دليل اتصال حي (نجاح/فشل) من جدول events — بلا أي أسرار.

    المصدر الحقيقي لـ«آخر نجاح فعلي»: أحداث المحادثة المسجلة
    (message_completed / chat.error) بحمولتها الكاملة. لا مسبار
    جديد مكلف ولا قراءة أسرار — قراءة أدلة مسجلة أصلًا.
    """
    from persistence.models import Event

    out: dict = {"success": None, "failure": None}
    with sessions() as session:
        rows = session.scalars(
            select(Event)
            .where(Event.kind.in_(("message_completed", "chat.error")))
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(25)
        ).all()
        for row in rows:
            try:
                payload = json.loads(row.payload or "{}")
            except ValueError:
                continue
            details = payload.get("details") or {}
            entry = {
                "at": row.created_at.isoformat() if row.created_at else "",
                "provider": str(details.get("provider", "") or ""),
                "model": str(details.get("model", "") or ""),
            }
            if row.kind == "message_completed" and out["success"] is None:
                out["success"] = entry
            elif row.kind == "chat.error" and out["failure"] is None:
                entry["error_class"] = str(
                    details.get("error_class", "")
                    or payload.get("code", "") or "")
                out["failure"] = entry
            if out["success"] and out["failure"]:
                break
    return out


def _providers_overview(sessions) -> list[dict]:
    """بُعد «هل المزود معد؟» — has_key منطقي فقط، لا قيم ولا أسرار."""
    try:
        from providers_registry import registry as providers_registry

        states = providers_registry.list_providers(sessions)
    except Exception:  # noqa: BLE001 — البُعد تحسين لا شرط
        return []
    return [
        {
            "name": p.get("name", ""),
            "enabled": bool(p.get("enabled", True)),
            "has_key": p.get("has_key"),
        }
        for p in states
    ]


def _llm_capability(sessions, stored: dict) -> dict:
    """جاهزية LLM من أدلتها الفعلية — الأبعاد منفصلة والعرض متسق.

    (AES-EXP-03 P2) الأبعاد المنفصلة الصادقة: (1) إعداد المزود
    (has_key)، (2) آخر نجاح اتصال حي مسجل، (3) آخر فشل مصنف،
    (4) المسبار المخزن. الحالة المعروضة مشتقة من **أحدث دليل**:

    - فشل حي أحدث من آخر نجاح ← NOT_READY بصنفه ومزوده وزمنه.
    - نجاح حي داخل نافذة الصلاحية ← READY بدليل live_call (لا
      يُشترط مسبار جديد كل فتح صفحة — الدليل المسجل يكفي).
    - نجاح حي منتهي النافذة ← STALE بعمر الدليل المعلن.
    - لا دليل حي إطلاقًا ← حالة المسبار المخزن كما هي؛ وإن كانت
      UNKNOWN فتبقى UNKNOWN **بسبب معلن** — لا جاهزية بلا دليل،
      ولا ادعاء عكسه.
    """
    out = dict(stored)
    out["derived_from"] = "live_call_evidence"
    evidence = _llm_live_evidence(sessions)
    success = evidence["success"]
    failure = evidence["failure"]
    ttl = TTL_DEFAULTS["LLM"]
    details = {
        **(out.get("details") or {}),
        "evidence_ttl_s": ttl,
        "last_live_success": success,
        "last_live_failure": failure,
        "providers": _providers_overview(sessions),
    }
    out["details"] = details
    success_at = _parse_ts(success["at"]) if success else None
    failure_at = _parse_ts(failure["at"]) if failure else None

    if failure_at is not None and (
        success_at is None or failure_at > success_at
    ):
        error_class = failure.get("error_class") or "LIVE_CALL_FAILED"
        out["readiness_status"] = "NOT_READY"
        out["failure_reason"] = error_class
        out["reason"] = (
            f"آخر استدعاء حي فشل [{error_class}] على مزود "
            f"'{failure['provider']}' — راجع إعدادات المزود أو أعد الفحص"
        )
        return out

    if success_at is not None:
        age = (_utc_now() - success_at).total_seconds()
        if age <= ttl:
            out["readiness_status"] = "READY"
            out["failure_reason"] = ""
            out["reason"] = (
                f"اتصال حي ناجح مسجل على مزود '{success['provider']}' "
                f"قبل {int(age)}ث — دليل استخدام فعلي لا مسبار"
            )
            out["details"] = {
                **details, "evidence_kind": "live_call",
                "evidence_age_s": int(age),
            }
            return out
        out["readiness_status"] = "STALE"
        out["reason"] = (
            f"نجاح حي مسجل قبل {int(age)}ث — خارج نافذة الصلاحية "
            f"({ttl}ث)؛ لا جاهزية بلا دليل حديث"
        )
        out["failure_reason"] = out["reason"]
        out["details"] = {
            **details, "evidence_kind": "live_call",
            "evidence_age_s": int(age),
        }
        return out

    # لا دليل حي إطلاقًا — المسبار المخزن هو الحكم كما هو.
    if out.get("readiness_status") in ("UNKNOWN", None, ""):
        out["reason"] = (
            "لا مسبار حديث ولا استدعاء حي مسجل — الحالة غير معروفة: "
            "افحص المزود من الإعدادات أو أرسل رسالة محادثة لتسجيل دليل حي"
        )
        if not out.get("failure_reason"):
            out["failure_reason"] = out["reason"]
    return out


def capability_view(sessions, capability_id: str) -> dict | None:
    """حالة القدرة الواحدة كما تُعرض/تُقرر — الاشتقاق من المصدر.

    كل مستهلك (preflight/UI/planner) يمر من هنا؛ لا يعيد أي مكوّن
    حساب الجاهزية بطريقته (011 §14 single source of truth).
    """
    stored = registry.get_capability(sessions, capability_id)
    if stored is None:
        return None
    if capability_id == "web_search":
        return _web_search_capability(sessions, stored)
    if capability_id == "llm":
        # (AES-EXP-03 P2) اشتقاق من أدلة الاتصال الحي — لا تناقض
        # «محادثة ناجحة / جاهزية UNKNOWN» بعد الآن.
        return _llm_capability(sessions, stored)
    if capability_id == "sandbox":
        # الحقيقة من سجل البيئات نفسها (المسبار والمنفذ من مصدر واحد)
        from execution import service as execution_service

        environments = execution_service.list_environments(sessions)
        selected = execution_service.select_environment(sessions)
        ready = [e for e in environments if e["status"] == "READY"]
        out = dict(stored)
        out["derived_from"] = "execution_environments"
        if selected is not None:
            out["readiness_status"] = "READY"
            out["failure_reason"] = ""
            out["reason"] = (
                f"بيئة جاهزة: {selected['name']} "
                f"({selected['backend']}"
                + ("/معزولة" if selected["sandboxed"] else "/بلا عزل")
                + f") — المسبار والمنفذ من مصدر واحد"
            )
            out["details"] = {
                **(out.get("details") or {}),
                "environment_id": selected["id"],
                "environment_name": selected["name"],
                "isolation": selected["isolation"],
            }
        elif ready:
            out["readiness_status"] = "READY"
            out["reason"] = "بيئة جاهزة متاحة"
        else:
            out["readiness_status"] = stored.get(
                "readiness_status", "UNKNOWN"
            ) if stored.get("readiness_status") in (
                "NOT_READY", "UNAVAILABLE"
            ) else "NOT_READY"
            out["reason"] = execution_service.owner_action_for_missing_environment(
                sessions
            )[:400]
            out["failure_reason"] = out["reason"]
            out["details"] = {
                **(out.get("details") or {}),
                "environments": [
                    {"name": e["name"], "status": e["status"],
                     "isolation": e["isolation"]}
                    for e in environments
                ],
            }
        return out
    return stored


def capabilities_view(sessions) -> list[dict]:
    """كل القدرات بالعرض المشتق — لوحة البيئة والجرد حصرًا (§14)."""
    registry.ensure_capabilities(sessions)
    out: list[dict] = []
    for stored in registry.get_capabilities(sessions):
        capability_id = stored["capability_id"]
        if capability_id in _AGGREGATED:
            derived = capability_view(sessions, capability_id)
            out.append(derived if derived is not None else stored)
        else:
            out.append(stored)
    return out


def summary(sessions) -> dict[str, int]:
    """ملخص الأعداد من العرض المشتق نفسه (لا إعادة عد بخلافه)."""
    counts = {"READY": 0, "DEGRADED": 0, "STALE": 0, "NOT_READY": 0,
              "NOT_CONFIGURED": 0, "UNAVAILABLE": 0, "UNKNOWN": 0}
    for cap in capabilities_view(sessions):
        status = cap.get("readiness_status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return counts


__all__ = [
    "RESEARCH_PROVIDER_TTL_S",
    "capability_view",
    "capabilities_view",
    "provider_effective_state",
    "research_providers_view",
    "summary",
]
