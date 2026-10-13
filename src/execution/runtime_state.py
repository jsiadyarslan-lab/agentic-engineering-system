"""حالة التشغيل القانونية الواحدة (013.2 §1-§4) — مصدر واحد للحقيقة.

المشكلة التي يحلها الموديول (013.2 §1): كانت البطاقات والسكربتات
والمسارات تُشتق «جاهز/غير جاهز» كلٌّ من مصدره — فقال التقرير READY
وقالت الواجهة غير جاهزة في نفس اللحظة. الآن:

    DURABLE STATE  →  RUNTIME TRUTH  →  USER INTERFACE
        (قاعدة)          (هذا الموديول)      (قراءة فقط)

- كل من يحتاج حالة البيئة (بطاقة المشروع، SSE، سكربت القبول،
  المسبار) يقرأ ``canonical_state()`` حصرًا — لا اشتقاق محلي.
- READY قانونية فقط إذا: بيئة موجودة (id دائم) + فحص صحة ناجح
  حقيقي (عملية+ملفات+التقاط) + العزل موافق للسياسة + هوية مسجلة
  (environment_id/worker_id/last_verified_at). أي نقص = ليست READY.
- المطلوب (REQUIRED) والفعلي (ACTUAL) مفصولان حرفيًا (§2): المطلوب
  من السياسة نصًّا صريحًا لا يوحي بحالة، والفعلي من جرد المضيف
  والبيئات المسجلة — لا يخلطهما عرض أبدًا.
- آلة الحالة القانونية (§3): DISCOVERING → PROVISIONING → BOOTING
  → HEALTH_CHECK → READY → RUNNING، مع DEGRADED/INTERRUPTED/FAILED/
  UNAVAILABLE. لا نص «جاهزة» عامًّا خارج هذه المفردات.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from sqlalchemy import select

from execution.models import RuntimeStateRecord

#: آلة الحالة القانونية (013.2 §3) — مفردة مقفلة، لا نص حر.
RUNTIME_STATES: tuple[str, ...] = (
    "DISCOVERING",   # جرد المضيف والركائز المتاحة
    "PROVISIONING",  # تهيئة بيئة فعلية (تسجيل/حاويات/عامل)
    "BOOTING",       # إقلاع فحصي
    "HEALTH_CHECK",  # فحوص الصحة الحقيقية تعمل الآن
    # (013.6 §3) خطوة صريحة منفصلة: إثبات أن العزل المطلوب بالسياسة
    # قائم فعلًا. كانت مدموجة في HEALTH_CHECK فيظهر «صحة» ثم «جاهز»
    # بلا لحظة تُثبت فيها المطابقة مع سياسة المشروع — فيبقى الفرق بين
    # «البيئة سليمة» و«البيئة صالحة لهذه المهمة» غير مرئي (وهو بالضبط
    # الانفصام الذي رفضه المالك في §1).
    "VERIFYING_ISOLATION",
    "READY",         # كل الفحوص نجحت + هوية دائمة
    "RUNNING",       # وظيفة نشطة على بيئة READY
    "DEGRADED",      # تعمل بنقص معلن (مثلاً عامل بلا عزل تحت سياسة متوافقة)
    "INTERRUPTED",   # انقطعت (فقدان نبضة/إعادة تشغيل) — قابلة للاستعادة
    "FAILED",        # فشل فحص الصحة بسبب حرفي
    "UNAVAILABLE",   # بنيويًا لا مسار توفير على هذا المضيف (§4)
)

#: الحالات التي يجوز للواجهة عرض «جاهزة/تعمل» عليها (013.2 §7)
COHERENT_READY_STATES = ("READY", "RUNNING")
COHERENT_PREPARING_STATES = ("DISCOVERING", "PROVISIONING", "BOOTING",
                             "HEALTH_CHECK", "VERIFYING_ISOLATION")

#: عرض المستخدم المتماسك (§7) — ثلاث حالات لا رابعة
COHERENT_LABELS: dict[str, str] = {
    "PREPARING": "⏳ تجهيز بيئة التنفيذ",
    "READY": "✓ بيئة التنفيذ جاهزة",
    "UNAVAILABLE": "⚠️ بيئة التنفيذ غير متاحة",
    "RUNNING": "● التنفيذ جارٍ",
}

#: (013.6 §3) نص الخطوة الجارية أثناء التجهيز — يُعرض للمالك
#: بدل «جاري التجهيز…» المبهم، فيعرف أن النظام يتحقق من العزل لا
#: من الصحة فقط.
PREPARING_STEP_LABELS: dict[str, str] = {
    "DISCOVERING": "جرد المضيف والركائز المتاحة",
    "PROVISIONING": "تهيئة ركيزة التنفيذ",
    "BOOTING": "إقلاع فحصي",
    "HEALTH_CHECK": "فحوص الصحة الحقيقية",
    "VERIFYING_ISOLATION": "التحقق من مطابقة العزل لسياسة المشروع",
}


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _json_loads(raw: str | None, default: Any):
    try:
        return json.loads(raw or "null") or default
    except ValueError:
        return default


# ------------------------------------------------------------------ #
# الكتابة — من provisioner/verify فقط؛ لا أحد يخترع حالة
# ------------------------------------------------------------------ #

def record_state(
    sessions, policy: str, state: str, *, reason: str = "",
    missing: list | None = None, evidence: dict | None = None,
    environment_id: int | None = None, worker_id: str = "",
    progress: int = 0,
) -> dict:
    """كتابة الحالة القانونية (صف واحد لكل سياسة — آخر حق wins).

    المتصلون الشرعيون: provisioner (كل خطوة)، verify (النتيجة)،
    JobManager (RUNNING/INTERRUPTED). أي أحد آخر يقرأ فقط.
    """
    if state not in RUNTIME_STATES:
        raise ValueError(f"حالة غير قانونية: {state} — المسموح: {RUNTIME_STATES}")
    with sessions() as session:
        row = session.scalars(
            select(RuntimeStateRecord)
            .where(RuntimeStateRecord.policy == policy)
            .order_by(RuntimeStateRecord.id.desc())
        ).first()
        if row is None:
            row = RuntimeStateRecord(policy=policy, state=state)
            session.add(row)
        row.state = state
        row.reason = str(reason)[:2000]
        row.missing_json = json.dumps(missing or [], ensure_ascii=False)
        row.evidence_json = json.dumps(evidence or {}, ensure_ascii=False,
                                       default=str)
        row.environment_id = environment_id
        row.worker_id = str(worker_id or "")[:120]
        row.progress = max(0, min(100, int(progress)))
        row.updated_at = _utc_now()
        session.commit()
        return _row_to_dict(row)


def _row_to_dict(row: RuntimeStateRecord) -> dict:
    return {
        "policy": row.policy,
        "state": row.state,
        "reason": row.reason,
        "missing": _json_loads(row.missing_json, []),
        "evidence": _json_loads(row.evidence_json, {}),
        "environment_id": row.environment_id,
        "worker_id": row.worker_id,
        "progress": row.progress,
        "updated_at": row.updated_at.isoformat()
        if row.updated_at else None,
    }


def read_record(sessions, policy: str) -> dict | None:
    """آخر سجل دائم لسياسة — قراءة صادقة (None = لم يُجهَّز بعد)."""
    with sessions() as session:
        row = session.scalars(
            select(RuntimeStateRecord)
            .where(RuntimeStateRecord.policy == policy)
            .order_by(RuntimeStateRecord.id.desc())
        ).first()
        return _row_to_dict(row) if row is not None else None


# ------------------------------------------------------------------ #
# الاشتقاق — الحقيقة اللحظية من الدائم (§1: لا تخمين أمامي)
# ------------------------------------------------------------------ #

def _required_profile(policy: str) -> dict:
    """البيئة المطلوبة (§2) — من السياسة حصرًا، نص صريح لا يوحي بحالة."""
    from execution import policy as execution_policy

    if policy == "STRICT_ISOLATED":
        return {
            "os": "Linux",
            "architecture": "x86_64 (أو عامل بعيد مكافئ)",
            "isolation": "عزل صارم فعلي (namespaces+seccomp أو عامل بعيد)",
            "worker": "عامل تنفيذ متصل بنبضة صالحة",
            "process": "تنفيذ عمليات حقيقي",
            "filesystem": "كتابة/قراءة/حذف ملفات فعلية",
            "network": "غير مطلوبة داخل العزل (معلومة لا وعد)",
            "requirement_text": execution_policy.requirement_text(policy),
        }
    return {
        "os": "أي نظام يدعم Python",
        "architecture": "أي معمارية",
        "isolation": "بلا عزل — وضع متوافق معلن صراحة",
        "worker": "أي منفذ جاهز (محلي أو بعيد)",
        "process": "تنفيذ عمليات حقيقي",
        "filesystem": "كتابة/قراءة/حذف ملفات فعلية",
        "network": "غير مطلوبة داخل التنفيذ",
        "requirement_text": execution_policy.requirement_text(policy),
    }


def _actual_profile(sessions) -> dict:
    """البيئة الفعلية (§2) — من جرد المضيف والبيئات المسجلة لحظتها."""
    from execution import service as execution_service
    from execution.backends import runtime_truth

    truth = runtime_truth()
    environments = execution_service.list_environments(sessions)
    remote = [e for e in environments if e["backend"] == "REMOTE_WORKER"]
    return {
        "host": {
            "platform": f"{truth.get('os', '')}/{truth.get('architecture', '')}",
            "os": truth.get("os", ""),
            "architecture": truth.get("architecture", ""),
            "container_runtime": truth.get("container_runtime", ""),
            "docker": truth.get("docker", ""),
            "wsl": bool(truth.get("wsl")),
            "cores": truth.get("cpu_cores", 0),
            "memory": truth.get("memory", ""),
        },
        "substrate_available": execution_service._substrate_available(),
        "environments_registered": len(environments),
        "remote_workers_registered": len(remote),
        "environments": [
            {k: e.get(k) for k in ("id", "name", "backend", "status",
                                   "isolation", "sandboxed", "is_default",
                                   "last_verified_at")}
            for e in environments
        ],
    }


def _ready_evidence(environment: dict) -> dict:
    """برهان READY (§3) — هوية دائمة + فحوص حرفية، لا نص عام."""
    detail = environment.get("last_probe_detail") or {}
    verify = detail.get("verify") or detail
    return {
        "environment_id": environment.get("id"),
        "environment_name": environment.get("name"),
        "backend": environment.get("backend"),
        "isolation": environment.get("isolation"),
        "sandboxed": bool(environment.get("sandboxed")),
        "last_verified_at": environment.get("last_verified_at"),
        "checks": (verify.get("checks") or [])[:12],
        "checks_ok": all(
            c.get("ok") for c in (verify.get("checks") or []) if c
        ) if verify.get("checks") else False,
    }


def _structural_missing(policy: str, actual: dict) -> list[dict]:
    """ما ينقص بنيويًا (§4) — الأسباب الحرفية لكل فجوة، لا عموميات."""
    from execution import policy as execution_policy

    missing: list[dict] = []
    if policy != "STRICT_ISOLATED":
        return missing
    host = actual.get("host") or {}
    has_remote = actual.get("remote_workers_registered", 0) > 0
    has_substrate = actual.get("substrate_available", False)
    on_linux = str(host.get("os", "")).lower() == "linux"
    docker = bool(host.get("docker")) or bool(host.get("container_runtime"))
    if not (has_substrate and on_linux) and not has_remote and not docker:
        missing.append({
            "need": "بيئة تنفيذ معزولة فعليًا",
            "detected": (
                f"المضيف {host.get('platform') or 'غير معروف'} — "
                + ("ركيزة العزل غير متاحة، " if not on_linux
                   else "الركيزة المعزولة غير مفعلة، ")
                + ("لا حاويات Docker، " if not docker else "")
                + "لا عامل بعيد مسجل"
            ),
            "action": (
                "أحد ثلاثة: (1) فعّل WSL2/Docker على هذا المضيف وأعد "
                "التجهيز، أو (2) شغّل عاملًا بعيدًا على أي Linux/WSL2: "
                "python scripts/execution_worker.py ثم سجّله من "
                "الإعدادات ← بيئات التنفيذ، أو (3) خفّض السياسة إلى "
                "توافق محلي معلن من إعدادات المشروع"
            ),
        })
    return missing


def canonical_state(sessions, policy: str = "STRICT_ISOLATED",
                    *, job: dict | None = None) -> dict:
    """الحالة القانونية الواحدة (§1) — يقرأها الجميع، لا يشتق أحد.

    ترتيب القرار (الأسبق يفوز):
    1. وظيفة نشطة على بيئة موافقة → RUNNING
    2. وظيفة منقطعة → INTERRUPTED (استعادة، لا READY كاذبة)
    3. بيئة موافقة للسياسة بفحص ناجح → READY (ببرهان هوية+فحوص)
    4. سجل تجهيز جارٍ (DISCOVERING..HEALTH_CHECK) → كما هو
    5. آخر سجل FAILED/UNAVAILABLE → كما هو مع الأسباب
    6. لا شيء يوفر السياسة بنيويًا → UNAVAILABLE بفجوات §4 الحرفية
    """
    from execution import policy as execution_policy
    from execution import service as execution_service

    policy = policy if execution_policy.is_valid_policy(policy) \
        else "STRICT_ISOLATED"
    actual = _actual_profile(sessions)
    required = _required_profile(policy)

    selected = execution_service.select_environment(
        sessions, policy=policy
    )
    environments = actual["environments"]

    state: str
    reason: str = ""
    evidence: dict = {}
    environment_id = None
    worker_id = ""
    progress = 0
    missing: list[dict] = []

    # 1-2) الوظيفة أولاً — هي الحقيقة الأحدث لحظة القراءة
    if job is not None:
        job_status = str(job.get("status") or "")
        worker_id = str(job.get("worker_id") or "")
        env_ok = selected is not None
        if job_status in ("RUNNING", "RETRYING") and env_ok:
            state = "RUNNING"
            evidence = _ready_evidence(selected)
            environment_id = selected["id"]
            reason = f"وظيفة {job.get('id')} نشطة على {selected['name']}"
        elif job_status == "INTERRUPTED":
            state = "INTERRUPTED"
            reason = (
                "انقطع العامل/الخادم أثناء التنفيذ — الوظيفة محفوظة "
                "وتستأنف من آخر checkpoint بنفس الصف"
            )
            evidence = {"job_id": job.get("id"),
                        "last_error": (job.get("last_error") or "")[:200]}
        elif job_status in ("PAUSED", "STOPPED") and env_ok:
            state = "READY"
            evidence = _ready_evidence(selected)
            environment_id = selected["id"]
            reason = "البيئة جاهزة والوظيفة موقوفة بأمان (استئناف متاح)"
        elif job_status in ("PAUSED", "STOPPED"):
            state = "INTERRUPTED"
            reason = "الوظيفة موقوفة والبيئة غير جاهزة — جهّز البيئة ثم استأنف"
            evidence = {"job_id": job.get("id")}
        else:
            state, reason, evidence = _state_from_environments(
                selected, environments, sessions, policy, actual,
            )
    else:
        state, reason, evidence = _state_from_environments(
            selected, environments, sessions, policy, actual,
        )

    if state == "UNAVAILABLE":
        missing = _structural_missing(policy, actual)
    if selected is not None and state in ("READY", "RUNNING"):
        environment_id = selected["id"]

    record = read_record(sessions, policy) or {}
    return {
        "policy": policy,
        "policy_label": execution_policy.POLICY_LABELS.get(policy, policy),
        "state": state,
        "coherent": coherent_view(state, reason, missing, progress),
        "required": required,
        "actual": actual,
        "selected": (
            {k: selected.get(k) for k in (
                "id", "name", "backend", "status", "isolation",
                "sandboxed", "is_default", "last_verified_at")}
            if selected is not None else None
        ),
        "missing": missing,
        "evidence": evidence,
        "environment_id": environment_id,
        "worker_id": worker_id,
        "progress": progress,
        "provisioning_record": {
            k: record.get(k) for k in (
                "state", "reason", "progress", "updated_at")
        } if record else None,
        "note": "مصدر واحد للحقيقة — الواجهة والقبول يقرآن هذه القراءة "
                "حصرًا؛ READY بلا برهان هوية وفحوص = مستحيلة",
    }


def _state_from_environments(
    selected: dict | None, environments: list[dict], sessions,
    policy: str, actual: dict,
) -> tuple[str, str, dict]:
    """قراءة الحالة من البيئات المسجلة عند غياب وظيفة نشطة."""
    from execution import policy as execution_policy

    if selected is not None:
        # (013.10 §3) جاهزية الحالة القانونية من التعريف القانوني
        # الواحد — HEALTHY بأدلة كاملة وأهلية سياسة = READY (يغلق
        # شق 013.9: بيئة متحققة تبقى DISCOVERING/DEGRADED لأن البوابة
        # كانت تشترط status=="READY" الخام).
        # (013.11 §3-4) الحجب يعرض أسبابه الحرفية (VERIFICATION_STALE
        # / VERIFICATION_MALFORMED / …) — حالة الصحة التاريخية تبقى
        # كما هي، لكنها لا تمنح READY وحدها.
        verdict = execution_policy.readiness(selected, policy)
        if verdict["ready"]:
            return (
                "READY",
                f"البيئة «{selected['name']}» اجتازت فحوص الصحة الحقيقية "
                "وتوافق السياسة بأدلة كاملة حديثة",
                _ready_evidence(selected),
            )
        blockers = "؛ ".join(verdict["blockers"][:3]) if verdict[
            "blockers"
        ] else "أعد التحقق"
        return (
            "DEGRADED",
            f"البيئة «{selected['name']}» مسجلة لكن جاهزيتها محجوبة — "
            + str(selected.get("failure_reason") or blockers),
            _ready_evidence(selected),
        )
    # لا بيئة موافقة — آخر سجل تجهيز يقرر، وإلا الفجوة البنيوية
    record = read_record(sessions, policy)
    if record and record.get("state") in COHERENT_PREPARING_STATES:
        return record["state"], record.get("reason", ""), {}
    if record and record.get("state") in ("FAILED",):
        return "FAILED", record.get("reason", ""), {}
    missing = _structural_missing(policy, actual)
    if missing:
        return (
            "UNAVAILABLE",
            "لا مسار توفير يوافق السياسة على هذا المضيف — الفجوات معلنة",
            {},
        )
    # بيئة موجودة لكنها UNKNOWN/فاشلة — تجهيز مطلوب لا استحالة بنيوية
    if environments:
        # (013.11 §3-4) مرشح سليم الصحة محجوب بأدله (قديمة/فاسدة/مبتورة)
        # يعرض سببه الحرفي — لا «تحقق» عام يخفي التقادم؛ حالة الصحة
        # التاريخية باقية والحجب بسبب VERIFICATION_* معلن
        # (013.12 D1) الحكم بأدلة كاملة: قواميس actual مختزلة بلا
        # last_probe_detail — الحجب عليها يتحول زورًا إلى
        # REQUIRED_MISSING؛ الأدلة تُقرأ من قواميس الخدمة الكاملة.
        from execution import service as execution_service

        full_envs = {
            e.get("id"): e
            for e in execution_service.list_environments(sessions)
        }
        for e in environments:
            full = full_envs.get(e.get("id"), e)
            verdict = execution_policy.readiness(full, policy)
            evidence_blockers = [
                b for b in verdict["blockers"]
                if b.startswith("VERIFICATION_")
            ]
            if execution_policy.health_ok(full) and evidence_blockers:
                return (
                    "DEGRADED",
                    f"البيئة «{full['name']}» محجوبة — "
                    + evidence_blockers[0],
                    _ready_evidence(full),
                )
        names = "، ".join(
            f"{e['name']} ({e['status']})" for e in environments[:4]
        )
        return (
            "DISCOVERING",
            f"بيئات مسجلة تحتاج تجهيزًا/تحققًا: {names}",
            {},
        )
    return (
        "DISCOVERING",
        "لا بيئة تنفيذ مسجلة بعد — ابدأ التجهيز",
        {},
    )


def coherent_view(state: str, reason: str = "",
                  missing: list | None = None, progress: int = 0) -> dict:
    """العرض المتماسك للمستخدم (§7) — ثلاث حالات لا رابعة أبدًا.

    UI يقتبس هذه الحقول حرفيًا؛ ممنوع تركيب نص حالة محلي أمامه.
    """
    if state in COHERENT_READY_STATES:
        return {"kind": "READY", "label": COHERENT_LABELS["READY"],
                "detail": reason}
    if state in COHERENT_PREPARING_STATES:
        return {
            "kind": "PREPARING", "label": COHERENT_LABELS["PREPARING"],
            "detail": reason or "جاري إنشاء بيئة التنفيذ…",
            "progress": max(0, min(100, int(progress))),
            # (013.6 §3) الخطوة الجارية بالاسم — لا «تجهيز…» مبهم
            "step": state,
            "step_label": PREPARING_STEP_LABELS.get(state, ""),
        }
    if state == "INTERRUPTED":
        return {
            "kind": "PREPARING",
            "label": "⏸ التنفيذ متوقف — البيئة قابلة للاستعادة",
            "detail": reason,
        }
    if state in ("FAILED", "DEGRADED"):
        return {
            "kind": "UNAVAILABLE",
            "label": COHERENT_LABELS["UNAVAILABLE"],
            "detail": reason or "فحص البيئة فشل — السبب معلن أدناه",
        }
    return {
        "kind": "UNAVAILABLE",
        "label": COHERENT_LABELS["UNAVAILABLE"],
        "detail": reason or "لم يُعثر على بيئة توافق السياسة على هذا المضيف",
        "missing": missing or [],
    }


__all__ = [
    "COHERENT_LABELS",
    "COHERENT_PREPARING_STATES",
    "COHERENT_READY_STATES",
    "PREPARING_STEP_LABELS",
    "RUNTIME_STATES",
    "canonical_state",
    "coherent_view",
    "read_record",
    "record_state",
]
