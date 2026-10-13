"""خدمة بيئات التنفيذ (الأمر 010 §17-§20+§27-§28 + الأمر 011 §4+§18).

المسبار والمنفذ من مصدر واحد (§19): resolve_executor() هو الطريق
الوحيد للحصول على خلفية تنفيذ — تستعمله probes.sandbox (المسبار)
وroles/tools._run_in_substrate (المنفذ) — فالتناقض الصامت مستحيل:

- كل تنفيذ يحمل environment_id + آخر verify للبيئة.
- فشل تنفيذ بعد مسبار READY يرفع ENVIRONMENT_MISMATCH مع الهوية
  والزمن — يُشرح ولا يُخفى (§42).

الحقيقة التشغيلية (011 §4-§5): اسم البيئة المحلية وعزلها من
runtime الفعلي (runtime_truth) — لا ``local-linux`` على مضيف
Windows، ولا ادعاء عزل حيث لا ركيزة. الاختيار (§18+§26) صار
policy-aware: STRICT_ISOLATED تطلب معزولة، COMPATIBLE_LOCAL تقبل
المعلنة غير المعزولة.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from sqlalchemy import select

from execution.backends import (
    ExecutionOutcome,
    LocalProcessBackend,
    LocalSandboxBackend,
    RemoteWorkerBackend,
    VerifyResult,
    host_platform_label,
    local_environment_name,
    runtime_truth,
)
from execution.models import (
    ENVIRONMENT_STATUSES,
    ExecutionEnvironment,
)
from execution import policy as execution_policy

_LEGACY_LOCAL_NAME = "local-linux"


_DEFAULT_SESSIONS = None


def set_default_sessions(sessions) -> None:
    """تسجيل جلسة الإنتاج (routes) — للاستعمال من سياقات بلا جلسة."""
    global _DEFAULT_SESSIONS  # noqa: PLW0603
    _DEFAULT_SESSIONS = sessions


def _sessions_or_default(sessions):
    if sessions is not None:
        return sessions
    return _DEFAULT_SESSIONS


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _row_to_dict(row: ExecutionEnvironment, *, include_refs: bool = False) -> dict:
    """سجل بيئة كقاموس — token_ref (اسم المرجع لا السر) داخلي حصرًا."""
    profile = _json_loads(row.profile_json, {})
    sandboxed = bool(row.sandboxed)
    out = {
        "id": row.id,
        "name": row.name,
        "backend": row.backend,
        "status": row.status,
        "profile": profile,
        "sandboxed": sandboxed,
        #: 011 §4: العزل مفهوم مستقل معلن — SANDBOXED | NONE | WORKER_DECLARED
        "isolation": (
            "WORKER_DECLARED" if row.backend == "REMOTE_WORKER"
            else ("SANDBOXED" if sandboxed else "NONE")
        ),
        #: 011 §4: منصة المضيف الحقيقية (من runtime لا من الاسم)
        "host_platform": profile.get("host_platform") or (
            "remote" if row.backend == "REMOTE_WORKER" else host_platform_label()
        ),
        "compatibility_mode": (
            row.backend == "LOCAL" and not sandboxed
        ),
        "is_default": bool(row.is_default),
        "endpoint": row.endpoint,
        "failure_reason": row.failure_reason,
        "last_verified_at": row.last_verified_at.isoformat()
        if row.last_verified_at else None,
        "last_probe_detail": _json_loads(row.last_probe_detail, {}),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
    if include_refs:
        out["token_ref"] = row.token_ref
    return out


def _json_loads(raw: str, default):
    try:
        return json.loads(raw or "null") or default
    except ValueError:
        return default


def _substrate_available() -> bool:
    """هل الركيزة المعزولة متاحة على هذا المضيف فعلًا؟ (011 §4)"""
    try:
        from substrate.local_substrate import default_local_images

        return bool(default_local_images())
    except Exception:  # noqa: BLE001 — أي عائق = غير متاحة بلا ادعاء
        return False


def ensure_local_registered(sessions) -> dict:
    """تسجيل البيئة المحلية عند أول إقلاع — هويتها من runtime الفعلي.

    (011 §4-§5) الاسم والعزل من المضيف الحقيقي: ``local-linux`` حكر
    على مضيف Linux فعلي؛ مضيف Windows يسجل ``local-windows`` بعزل
    NONE (وضع متوافق معلن — لا ادعاء عزل). قاعدة قديمة سمّت بيئة
    محلية «local-linux» على مضيف غير Linux تُصحَّح بالاسم والحقيقة
    (نفس المعرف يحفظ الهوية التاريخية للتنفيذات).
    لا تفترض جاهزية (§20): تُسجل UNKNOWN ثم verify() يقرر.

    (013.6 §F) محصّن ضد تكرار الاستدعاء المتزامن/المتتالي: يحاول
    القراءة أولاً، فإن تعذر الإدراج لانتهاك UNIQUE يعيد القراءة فورًا.
    """
    correct_name = local_environment_name()
    sandboxed = 1 if _substrate_available() else 0
    with sessions() as session:
        # محاولة قراءة البيئة الموجودة أولاً
        found = session.scalars(
            select(ExecutionEnvironment)
            .where(ExecutionEnvironment.name.in_(
                (correct_name, _LEGACY_LOCAL_NAME)
            ))
        ).first()
        if found is not None:
            # تصحيح الكذبة التاريخية: بيئة محلية باسم لينكس على مضيف
            # غير لينكس — الاسم والعزل من الحقيقة لا من السجل القديم
            if (found.name == _LEGACY_LOCAL_NAME
                    and correct_name != _LEGACY_LOCAL_NAME):
                found.name = correct_name
                found.sandboxed = sandboxed
                found.failure_reason = (
                    "صُحح اسم البيئة من local-linux — المضيف الفعلي "
                    + host_platform_label()
                )
                found.updated_at = _utc_now()
                session.commit()
                session.refresh(found)
            # عزل البيئة المحلية يتبع توفر الركيزة الآن (WSL2 مثلا)
            if bool(found.sandboxed) != bool(sandboxed):
                found.sandboxed = sandboxed
                found.updated_at = _utc_now()
                session.commit()
                session.refresh(found)
            if not _json_loads(found.profile_json, {}).get("host_platform"):
                truth = runtime_truth()
                profile = _json_loads(found.profile_json, {})
                profile.update({
                    "host_platform": host_platform_label(truth),
                    "os": truth["os"],
                    "architecture": truth["architecture"],
                    "kernel": truth["kernel"],
                    "runtime": f"python {truth['python']}",
                    "sandboxed": bool(sandboxed),
                })
                found.profile_json = json.dumps(
                    profile, ensure_ascii=False, default=str
                )
                found.updated_at = _utc_now()
                session.commit()
                session.refresh(found)
            return _row_to_dict(found)
        # لا بيئة موجودة — نحاول الإدراج
        row = ExecutionEnvironment(
            name=correct_name, backend="LOCAL", status="DETECTED",
            endpoint="", is_default=1, sandboxed=sandboxed,
            profile_json=json.dumps({
                "host_platform": host_platform_label(),
                "os": runtime_truth()["os"],
                "architecture": runtime_truth()["architecture"],
                "sandboxed": bool(sandboxed),
                "compatibility_mode": not sandboxed,
            }, ensure_ascii=False, default=str),
        )
        session.add(row)
        try:
            session.commit()
        except Exception as e:  # noqa: BLE001 — نزاع UNIQUE متوقع عند التزامن
            session.rollback()
            # محاولة قراءة ما أُدرج من استدعاء متزامن
            found = session.scalars(
                select(ExecutionEnvironment)
                .where(ExecutionEnvironment.name == correct_name)
            ).first()
            if found is not None:
                return _row_to_dict(found)
            raise
        session.refresh(row)
        return _row_to_dict(row)


def list_environments(sessions, *, include_refs: bool = False) -> list[dict]:
    """كل البيئات المسجلة — بلا أسرار أبدًا (المراجع داخلية حصرًا)."""
    ensure_local_registered(sessions)
    with sessions() as session:
        rows = session.scalars(
            select(ExecutionEnvironment)
            .order_by(ExecutionEnvironment.is_default.desc(),
                      ExecutionEnvironment.id)
        ).all()
        return [_row_to_dict(row, include_refs=include_refs) for row in rows]


def get_environment(sessions, environment_id: int) -> dict | None:
    """قراءة عامة (بلا مراجع أسرار) — لواجهة الـAPI."""
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        return _row_to_dict(row) if row is not None else None


def _get_environment_full(sessions, environment_id: int) -> dict | None:
    """قراءة داخلية بمرجع التوكن — لبناء الخلفية حصرًا لا للعرض."""
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        return _row_to_dict(row, include_refs=True) if row is not None else None


def build_backend(environment: dict):
    """بناء الخلفية الحقيقية لبيئة مسجلة — العزل يحدد الصنف (011 §4).

    LOCAL + sandboxed → LocalSandboxBackend (الركيزة المعزولة)؛
    LOCAL + بلا عزل → LocalProcessBackend (وضع متوافق معلن)؛
    REMOTE_WORKER → RemoteWorkerBackend (بروتوكول HTTP).
    environment بقراءة كاملة (token_ref حاضر) — من _get_environment_full
    أو قائمة داخلية؛ المرجع يقرأ توكنه من مخزن الأسرار لحظتها.
    """
    if environment["backend"] == "LOCAL":
        if environment.get("sandboxed"):
            return LocalSandboxBackend(environment_id=str(environment["id"]))
        return LocalProcessBackend(environment_id=str(environment["id"]))
    if environment["backend"] == "REMOTE_WORKER":
        token = ""
        if environment.get("token_ref"):
            from secrets_store import store

            token = store.get_key(environment["token_ref"]) or ""
        return RemoteWorkerBackend(
            environment["endpoint"], token=token,
            environment_id=str(environment["id"]),
        )
    raise ValueError(
        f"خلفية غير مدعومة: {environment['backend']} — المدعوم: LOCAL، "
        "REMOTE_WORKER فقط (لا implementation وهمية)"
    )


def add_environment(
    sessions, *, name: str, backend: str, endpoint: str = "",
    token: str = "", make_default: bool = False,
) -> dict:
    """إضافة بيئة (§28) — خيارات مدعومة من الكود فعلًا حصرًا."""
    if backend not in ("LOCAL", "REMOTE_WORKER"):
        raise ValueError(
            f"backend غير مدعوم: {backend} — المدعوم: LOCAL (يكشف تلقائيًا) "
            "وREMOTE_WORKER (رابط عامل حقيقي)"
        )
    if backend == "REMOTE_WORKER" and not endpoint.startswith(("http://", "https://")):
        raise ValueError(
            "بيئة REMOTE_WORKER تتطلب رابط العامل (http://host:8900)"
        )
    name = name.strip()
    if not name:
        raise ValueError("اسم البيئة مطلوب")
    token_ref = ""
    if token:
        from secrets_store import store

        token_ref = f"execution::{name}"
        store.set_key(token_ref, token)
    with sessions() as session:
        clash = session.scalars(
            select(ExecutionEnvironment)
            .where(ExecutionEnvironment.name == name)
        ).first()
        if clash is not None:
            raise ValueError(f"اسم بيئة مستخدم مسبقًا: {name}")
        row = ExecutionEnvironment(
            name=name, backend=backend, status="UNKNOWN",
            endpoint=endpoint if backend == "REMOTE_WORKER" else "",
            token_ref=token_ref,
            is_default=1 if make_default else 0,
        )
        if make_default:
            for other in session.scalars(
                select(ExecutionEnvironment)
                .where(ExecutionEnvironment.is_default == 1)
            ):
                other.is_default = 0
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def delete_environment(sessions, environment_id: int) -> bool:
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        if row is None:
            return False
        # (013.10) حقيقة المضيف لا تُحذف: البيئة المحلية الحالية
        # (local_environment_name) واسمها القديم local-linux كلاهما
        # محميان — القائمة تعيد تسجيل المحلية تلقائيًا فورًا، فالحذف
        # على Windows كان يمر بحكم الاسم الثابت وحده.
        if row.name in (_LEGACY_LOCAL_NAME, local_environment_name()):
            raise ValueError("البيئة المحلية الافتراضية لا تُحذف")
        if row.token_ref:
            from secrets_store import store

            store.delete_key(row.token_ref)
        session.delete(row)
        session.commit()
        return True


def set_default(sessions, environment_id: int) -> dict:
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        if row is None:
            raise KeyError(f"بيئة غير معروفة: {environment_id}")
        for other in session.scalars(
            select(ExecutionEnvironment)
            .where(ExecutionEnvironment.is_default == 1)
        ):
            other.is_default = 0
        row.is_default = 1
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def compute_environment_state(environment: dict, policy: str = "STRICT_ISOLATED") -> dict:
    """(013.7 §P1 + 013.10 §3) حساب الحالة الصريحة للبيئة — بلا بوليان «جاهز/متاح».

    الحالات المتسلسلة:
      NOT_CONFIGURED → DETECTED/REGISTERED → ONLINE → HEALTHY → ELIGIBLE → READY
      أو يتوقف عند: NOT_READY / UNAVAILABLE / NOT_CONFIGURED

    (013.10 §3-5) الحالة المعروضة تتفق مع الأهلية وسبب الحجب دائمًا:
    HEALTHY غير مؤهلة تبقى HEALTHY بسبب حرفي — لا اسم ELIGIBLE
    وeligible=false (التناقض الذي وضعه المالك)، وREADY تُعرض فقط
    عندما يصدق حكم التعريف القانوني الواحد (policy.readiness).
    """
    status = environment.get("status", "NOT_CONFIGURED")

    # إذا كانت الحالة نهائية سلبية — لا نرتقي
    if status in ("NOT_READY", "UNAVAILABLE", "NOT_CONFIGURED"):
        return {
            "state": status,
            "health_state": status,
            "eligible": False,
            "ineligible_reason": environment.get("failure_reason", ""),
            "ready": False,
            "evidence": execution_policy.verification_evidence(environment),
        }

    # الحكم من التعريف القانوني الواحد (صحة + أدلة + أهلية سياسة)
    verdict = execution_policy.readiness(environment, policy)
    health_state = (
        "HEALTHY" if status in execution_policy.HEALTH_STATUSES else status
    )

    # (013.10 §3-5) اسم الحالة يطابق قيمة الأهلية:
    #   جاهزة ⇔ الصحة ∧ الأدلة ∧ الأهلية — وإلا تبقى على درجتها
    #   الحقيقية (HEALTHY سليمة غير مؤهلة، DETECTED لم تُتحقق…)
    final_state = "READY" if verdict["ready"] else health_state

    return {
        "state": final_state,
        "health_state": health_state,
        "eligible": verdict["eligible"],
        "ineligible_reason": "؛ ".join(verdict["blockers"]),
        "ready": verdict["ready"],
        "evidence": verdict["evidence"],
    }


def _set_environment_status(sessions, environment_id: int, status: str, **kwargs) -> None:
    """تحديث حالة البيئة بأمان."""
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        if row is not None:
            row.status = status
            for k, v in kwargs.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = _utc_now()
            session.commit()


def verify_environment(sessions, environment_id: int) -> dict:
    """التحقق الحقيقي (§28) — HEALTHY فقط بعد فحوص إقلاع/كتابة/تنفيذ/التقاط.

    النتيجة تكتب في البيئة (status/profile/last_verified_at) وتعاد —
    هذا نفس المسار الذي سينفذ به run_code لاحقًا (§19 توحيد المصدر).
    READY تُحدَّد لاحقاً بالسياسة والأهلية (§P1).
    """
    environment = _get_environment_full(sessions, environment_id)
    if environment is None:
        raise KeyError(f"بيئة غير معروفة: {environment_id}")
    backend = build_backend(environment)
    result: VerifyResult = backend.verify()
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        # (013.7 §P1) التحقق الناجح = HEALTHY؛ READY تُحدَّد لاحقاً
        # بالسياسة والأهلية — لا READY فوري
        row.status = "HEALTHY" if result.ok else result.status
        row.profile_json = json.dumps(
            result.profile, ensure_ascii=False, default=str
        )
        row.sandboxed = 1 if result.profile.get("sandboxed") else 0
        row.failure_reason = "" if result.ok else result.reason[:2000]
        row.last_verified_at = _utc_now()
        row.last_probe_detail = json.dumps(
            result.to_dict(), ensure_ascii=False, default=str
        )
        row.updated_at = _utc_now()
        session.commit()
    out = get_environment(sessions, environment_id)
    out["verify"] = result.to_dict()
    # لا نبلغ READY هنا — الحالة الصريحة تُحسب بالسياسة
    return out


#: خطاف «بيئة أصبحت جاهزة» (011 §21) — تسجله routes لنشر حدث
#: WORKER_READY على تيار المشاريع كي تتزامن الشريط الجانبي والصفحات.
_READY_LISTENERS: list = []


def on_environment_ready(callback) -> None:
    """تسجيل مستمع جاهزية البيئة — تستدعيه verify عند READY."""
    _READY_LISTENERS.append(callback)


def _notify_environment_ready(environment: dict) -> None:
    for callback in list(_READY_LISTENERS):
        try:
            callback(environment)
        except Exception:  # noqa: BLE001 — مستمع لا يكسر التحقق
            pass


def select_environment(sessions, *, policy: str | None = None) -> dict | None:
    """اختيار بيئة التنفيذ (§18+011 §26) — وفق سياسة المهمة.

    سياسة معطاة → environment تفي بها حصرًا (STRICT_ISOLATED تطلب
    المعزولة). بلا سياسة (السلوك التاريخي للمسار العام): الافتراضية
    الجاهزة وإلا أي جاهزة. لا تعيد بيئة غير جاهزة أبدًا؛ غياب
    الموافق = None والسبب يعرضه preflight.
    """
    environments = list_environments(sessions)
    if policy is not None:
        return execution_policy.select_environment_for_policy(
            environments, policy
        )
    ready = [env for env in environments if env["status"] == "READY"]
    if not ready:
        return None
    for env in ready:
        if env["is_default"]:
            return env
    return ready[0]


def resolve_executor(sessions, *, policy: str | None = None):
    """المصدر الموحد (§19): (بيئة، خلفية) التي يستعملها المسبار والمنفذ.

    policy معطاة (013.1 §13 — لا تراجع صامت): البيئة الجاهزة الموافقة
    لها حصرًا؛ غيابها = ``(None, None)`` — لا سقوط إلى الافتراضية
    مهما كانت، فالمسبار يعرض المتطلب والمنفذ يحجب نفسه (POLICY_BLOCK)
    بدل التنفيذ غير المعزول تحت سياسة عزل صارم.

    بلا سياسة (السلوك التاريخي للمسار العام): تُفضّل الجاهزة
    المختارة، وإلا الافتراضية بوضعها الفعلي — المتصل يفحص status
    بنفسه لأن الصدق هنا أهم من الراحة.
    """
    environments_full = list_environments(sessions, include_refs=True)
    by_id = {env["id"]: env for env in environments_full}
    selected = select_environment(sessions, policy=policy)
    if selected is not None:
        full = by_id.get(selected["id"], selected)
        return selected, build_backend(full)
    if policy is not None:
        # (013.1 §13) سياسة معطاة بلا بيئة موافقة = حجب معلن،
        # لا تنفيذ على بيئة أدنى سقفًا منها أبدًا
        return None, None
    for env in environments_full:
        if env["is_default"]:
            public = {k: v for k, v in env.items() if k != "token_ref"}
            return public, build_backend(env)
    if environments_full:
        first = environments_full[0]
        public = {k: v for k, v in first.items() if k != "token_ref"}
        return public, build_backend(first)
    return None, None


def run_code_unified(
    sessions, code: str, *, workspace: Path, artifacts: Path,
    timeout_s: float = 120.0, policy: str | None = None,
) -> ExecutionOutcome:
    """تنفيذ عبر البيئة المختارة — كل نتيجة تحمل هوية البيئة (§19).

    sessions=None (اختبارات/أدوات بلا قاعدة): الخلفية المحلية مباشرة
    — نفس صنف الخلفية الذي يسجلها الجرد، بلا لمس أي قاعدة.
    فشل بدء بعد حالة READY يوسم ENVIRONMENT_MISMATCH بتفصيل الهوية
    والزمن — التفسير إلزامي لا الاختفاء (§42).

    policy (013.1 §13): البيئة الموافقة للسياسة حصرًا — غيابها =
    POLICY_BLOCK بالمتطلب الحرفي، لا تنفيذ غير معزول بدلًا عنها.
    """
    if sessions is None:
        # أداة «داخل الركيزة» تعد بعزل — لا تراجع متوافق هنا: منصة
        # بلا ركيزة = FAILED_TO_START بسببها الصادق (011 §28).
        backend = LocalSandboxBackend()
        return backend.run_code(
            code, workspace=workspace, artifacts=artifacts,
            timeout_s=timeout_s,
        )
    environment, backend = resolve_executor(sessions, policy=policy)
    if backend is None:
        if policy is not None:
            required = execution_policy.requirement_text(policy)
            return ExecutionOutcome(
                environment_id="none", backend="NONE", exit_code=-1,
                stdout="", stderr="", termination="POLICY_BLOCK",
                detail=(
                    f"POLICY_BLOCK — السياسة {policy} بلا بيئة تنفيذ "
                    f"جاهزة موافقة. المطلوب: {required}. لا تنفيذ "
                    "غير معزول بدلًا عنها (لا تراجع صامت)"
                ),
            )
        return ExecutionOutcome(
            environment_id="none", backend="NONE", exit_code=-1,
            stdout="", stderr="", termination="FAILED_TO_START",
            detail="لا بيئة تنفيذ مسجلة — أضف بيئة من الإعدادات ← "
                   "بيئات التنفيذ ثم تحقق",
        )
    outcome = backend.run_code(
        code, workspace=workspace, artifacts=artifacts, timeout_s=timeout_s,
    )
    if outcome.termination == "FAILED_TO_START" and environment["status"] in (
            "READY", "HEALTHY"):
        outcome.detail = (
            f"ENVIRONMENT_MISMATCH: المسبار قال جاهزة "
            f"({environment['status']}) للبيئة "
            f"#{environment['id']} ({environment['name']}/{environment['backend']}) "
            f"عند {environment['last_verified_at']} لكن التنفيذ فشل في البدء — "
            f"{outcome.detail} — أعِد التحقق من البيئة (تُوسم STALE)"
        )
        _mark_stale(sessions, environment["id"])
    return outcome


def _mark_stale(sessions, environment_id: int) -> None:
    """فشل تنفيذ بعد جاهزية (HEALTHY/READY) = بيئة موضع شك — تُعاد للفحص الإجباري."""
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        if row is not None and row.status in ("READY", "HEALTHY"):
            row.status = "UNKNOWN"
            row.failure_reason = (
                "ENVIRONMENT_MISMATCH — فشل تنفيذ بعد تحقق ناجح؛ "
                "أعد التحقق قبل الاستخدام"
            )
            row.updated_at = _utc_now()
            session.commit()


def sandbox_probe_result(sessions, *, policy: str | None = None) -> dict:
    """نتيجة مسبار sandbox الموحد (§19): المسبار = التحقق من البيئة.

    يحمل environment_id/المنصة/الزمن في details — لو اختلف المنفذ
    لاحقًا عُرف أي بيئة قالت READY ومتى. policy (011 §26) يجعل
    المسبار يفحص البيئة التي ستُختار فعلًا لهذه السياسة.
    """
    environment, backend = resolve_executor(sessions, policy=policy)
    if backend is None:
        if policy is not None:
            return {
                "status": "UNAVAILABLE",
                "reason": (
                    "لا بيئة تنفيذ جاهزة توافق السياسة "
                    + policy + " — "
                    + execution_policy.requirement_text(policy)
                ),
                "latency_ms": 0,
                "ttl_seconds": 300,
                "failure_class": "SANDBOX_FAILURE",
                "failure_stage": "STARTUP",
                "details": {"environment_id": None, "policy": policy},
            }
        return {
            "status": "UNAVAILABLE",
            "reason": "لا بيئة تنفيذ مسجلة",
            "latency_ms": 0,
            "ttl_seconds": 300,
            "details": {"environment_id": None},
        }
    import time

    started = time.monotonic()
    result = backend.verify()
    # انعكاس النتيجة على سجل البيئة نفسها (مصدر واحد للحقيقة)
    # (013.10 §3) توحيد الكاتبَين: نجاح المسبار يكتب HEALTHY (صحة
    # ناجحة بأدلة) — مثل verify_environment حرفيًا؛ الجاهزية تُحسب
    # بالتعريف القانوني الواحد لا بالحالة المخزنة.
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment["id"]))
        if row is not None:
            row.status = "HEALTHY" if result.ok else result.status
            row.profile_json = json.dumps(
                result.profile, ensure_ascii=False, default=str
            )
            row.sandboxed = 1 if result.profile.get("sandboxed") else 0
            row.failure_reason = "" if result.ok else result.reason[:2000]
            row.last_verified_at = _utc_now()
            row.last_probe_detail = json.dumps(
                result.to_dict(), ensure_ascii=False, default=str
            )
            row.updated_at = _utc_now()
            session.commit()
    return {
        "status": result.status,
        "reason": result.reason or (
            f"بيئة {environment['name']} ({result.profile.get('os')}/"
            f"{result.profile.get('architecture')}) تجتاز الإقلاع "
            "والكتابة والتنفيذ والتقاط"
        ),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "ttl_seconds": 300,
        "failure_class": "" if result.ok else "SANDBOX_FAILURE",
        "failure_stage": "" if result.ok else "STARTUP",
        "details": {
            "environment_id": environment["id"],
            "environment_name": environment["name"],
            "backend": environment["backend"],
            "sandboxed": bool(result.profile.get("sandboxed")),
            "os": result.profile.get("os"),
            "architecture": result.profile.get("architecture"),
            "checks": result.checks,
            "platform_note": (
                "المسبار والمنفذ يستعملان resolve_executor() نفسه — "
                "نفس البيئة التي فُحصت هي التي تنفّذ"
            ),
        },
    }


def owner_action_for_missing_environment(
    sessions, policy: str | None = None,
) -> str:
    """نص إجراء المالك (§30+011 §3+§27) عند غياب بيئة موافقة — دقيق.

    يسمي السياسة والمطلوب الحقيقي (Linux/x86_64 worker للعزل الصارم)
    والإجراء المرتب: إضافة بيئة ← تحقق ← إعادة الفحص ← استئناف.
    """
    environments = list_environments(sessions)
    if policy is not None and execution_policy.is_valid_policy(policy):
        satisfying = [
            e for e in environments
            if execution_policy.environment_satisfies(e, policy)
        ]
        if satisfying:
            return ""
    else:
        ready = [e for e in environments if e["status"] == "READY"]
        if ready:
            return ""
    required = (
        execution_policy.requirement_text(policy)
        if policy is not None else "بيئة تنفيذ جاهزة"
    )
    reasons = "؛ ".join(
        f"{e['name']} ({e['backend']}"
        + ("/معزولة" if e["sandboxed"] else "/بلا عزل")
        + f"): {e['status']}"
        + (f" — {e['failure_reason'][:120]}" if e["failure_reason"] else "")
        for e in environments
    ) or "لا بيئة تنفيذ مسجلة"
    return (
        "OWNER ACTION REQUIRED — لا بيئة تنفيذ جاهزة توافق السياسة. "
        f"المطلوب: {required}. الحالة الحالية: {reasons}. "
        "الإجراء: بيئات التنفيذ ← إضافة بيئة (REMOTE_WORKER برابط عامل "
        "على Linux/WSL2: python scripts/execution_worker.py) ← تحقق "
        "حقيقي ← إعادة الفحص ← استئناف المهمة بلا إعادة اعتماد"
    )


__all__ = [
    "add_environment",
    "build_backend",
    "delete_environment",
    "ensure_local_registered",
    "get_environment",
    "list_environments",
    "on_environment_ready",
    "owner_action_for_missing_environment",
    "resolve_executor",
    "run_code_unified",
    "sandbox_probe_result",
    "select_environment",
    "set_default",
    "verify_environment",
]
