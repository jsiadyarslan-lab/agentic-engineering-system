"""خدمة بيئات التنفيذ (الأمر 010 §17-§20+§27-§28) — ما بعد الكشف.

المسبار والمنفذ من مصدر واحد (§19): resolve_executor() هو الطريق
الوحيد للحصول على خلفية تنفيذ — تستعمله probes.sandbox (المسبار)
وroles/tools._run_in_substrate (المنفذ) — فالتناقض الصامت مستحيل:

- كل تنفيذ يحمل environment_id + آخر verify للبيئة.
- فشل تنفيذ بعد مسبار READY يرفع ENVIRONMENT_MISMATCH مع الهوية
  والزمن — يُشرح ولا يُخفى (§42).

الاختيار (§18): Task → Required → Environment Selection → Preflight
→ Execution — select_environment() تختار الجاهزة الافتراضية أولًا.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from sqlalchemy import select

from execution.backends import (
    ExecutionOutcome,
    LocalLinuxBackend,
    RemoteWorkerBackend,
    VerifyResult,
)
from execution.models import (
    ENVIRONMENT_STATUSES,
    ExecutionEnvironment,
)

_DEFAULT_LOCAL_NAME = "local-linux"


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
    out = {
        "id": row.id,
        "name": row.name,
        "backend": row.backend,
        "status": row.status,
        "profile": _json_loads(row.profile_json, {}),
        "sandboxed": bool(row.sandboxed),
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


def ensure_local_registered(sessions) -> dict:
    """تسجيل البيئة المحلية تلقائيًا عند أول إقلاع — حالة صادقة أولًا.

    لا تفترض جاهزية (§20): تُسجل UNKNOWN ثم verify() يقرر.
    """
    with sessions() as session:
        found = session.scalars(
            select(ExecutionEnvironment)
            .where(ExecutionEnvironment.name == _DEFAULT_LOCAL_NAME)
        ).first()
        if found is not None:
            return _row_to_dict(found)
        row = ExecutionEnvironment(
            name=_DEFAULT_LOCAL_NAME, backend="LOCAL", status="UNKNOWN",
            endpoint="", is_default=1,
        )
        session.add(row)
        session.commit()
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


def build_backend(environment: dict) -> LocalLinuxBackend | RemoteWorkerBackend:
    """بناء الخلفية الحقيقية لبيئة مسجلة — الخياران المدعومان فقط.

    environment بقراءة كاملة (token_ref حاضر) — من _get_environment_full
    أو قائمة داخلية؛ المرجع يقرأ توكنه من مخزن الأسرار لحظتها.
    """
    if environment["backend"] == "LOCAL":
        return LocalLinuxBackend(environment_id=str(environment["id"]))
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
        if row.name == _DEFAULT_LOCAL_NAME:
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


def verify_environment(sessions, environment_id: int) -> dict:
    """التحقق الحقيقي (§28) — READY فقط بعد فحوص إقلاع/كتابة/تنفيذ/التقاط.

    النتيجة تكتب في البيئة (status/profile/last_verified_at) وتعاد —
    هذا نفس المسار الذي سينفذ به run_code لاحقًا (§19 توحيد المصدر).
    """
    environment = _get_environment_full(sessions, environment_id)
    if environment is None:
        raise KeyError(f"بيئة غير معروفة: {environment_id}")
    backend = build_backend(environment)
    result: VerifyResult = backend.verify()
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        row.status = result.status
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
    return out


def select_environment(sessions) -> dict | None:
    """اختيار بيئة التنفيذ (§18) — الافتراضية الجاهزة، وإلا أي جاهزة.

    لا تعيد بيئة غير جاهزة أبدًا؛ عدم وجود جاهزة = None والسبب يعرضه
    preflight (لا بيئة افتراضية غير موجودة §18).
    """
    environments = list_environments(sessions)
    ready = [env for env in environments if env["status"] == "READY"]
    if not ready:
        return None
    for env in ready:
        if env["is_default"]:
            return env
    return ready[0]


def resolve_executor(sessions):
    """المصدر الموحد (§19): (بيئة، خلفية) التي يستعملها المسبار والمنفذ.

    تفضل الجاهزة المختارة؛ إن لم توجد بيئة جاهزة تعيد الافتراضية
    (المحلية عادة) بوضعها الفعلي — المتصل يفحص status بنفسه لأن
    الصدق هنا أهم من الراحة.
    """
    environments_full = list_environments(sessions, include_refs=True)
    by_id = {env["id"]: env for env in environments_full}
    selected = select_environment(sessions)   # قاموس عام بلا مراجع
    if selected is not None:
        full = by_id.get(selected["id"], selected)
        return selected, build_backend(full)
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
    timeout_s: float = 120.0,
) -> ExecutionOutcome:
    """تنفيذ عبر البيئة المختارة — كل نتيجة تحمل هوية البيئة (§19).

    sessions=None (اختبارات/أدوات بلا قاعدة): الخلفية المحلية مباشرة
    — نفس صنف الخلفية الذي يسجلها الجرد، بلا لمس أي قاعدة.
    فشل بدء بعد حالة READY يوسم ENVIRONMENT_MISMATCH بتفصيل الهوية
    والزمن — التفسير إلزامي لا الاختفاء (§42).
    """
    if sessions is None:
        backend = LocalLinuxBackend()
        return backend.run_code(
            code, workspace=workspace, artifacts=artifacts,
            timeout_s=timeout_s,
        )
    environment, backend = resolve_executor(sessions)
    if backend is None:
        return ExecutionOutcome(
            environment_id="none", backend="NONE", exit_code=-1,
            stdout="", stderr="", termination="FAILED_TO_START",
            detail="لا بيئة تنفيذ مسجلة — أضف بيئة من الإعدادات ← "
                   "بيئات التنفيذ ثم تحقق",
        )
    outcome = backend.run_code(
        code, workspace=workspace, artifacts=artifacts, timeout_s=timeout_s,
    )
    if outcome.termination == "FAILED_TO_START" and environment["status"] == "READY":
        outcome.detail = (
            f"ENVIRONMENT_MISMATCH: المسبار قال READY للبيئة "
            f"#{environment['id']} ({environment['name']}/{environment['backend']}) "
            f"عند {environment['last_verified_at']} لكن التنفيذ فشل في البدء — "
            f"{outcome.detail} — أعِد التحقق من البيئة (تُوسم STALE)"
        )
        _mark_stale(sessions, environment["id"])
    return outcome


def _mark_stale(sessions, environment_id: int) -> None:
    """فشل تنفيذ بعد READY = البيئة موضع شك — تُعاد للفحص الإجباري."""
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment_id))
        if row is not None and row.status == "READY":
            row.status = "UNKNOWN"
            row.failure_reason = (
                "ENVIRONMENT_MISMATCH — فشل تنفيذ بعد تحقق ناجح؛ "
                "أعد التحقق قبل الاستخدام"
            )
            row.updated_at = _utc_now()
            session.commit()


def sandbox_probe_result(sessions) -> dict:
    """نتيجة مسبار sandbox الموحد (§19): المسبار = التحقق من البيئة.

    يحمل environment_id/المنصة/الزمن في details — لو اختلف المنفذ
    لاحقًا عُرف أي بيئة قالت READY ومتى.
    """
    environment, backend = resolve_executor(sessions)
    if backend is None:
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
    with sessions() as session:
        row = session.get(ExecutionEnvironment, int(environment["id"]))
        if row is not None:
            row.status = result.status
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


def owner_action_for_missing_environment(sessions) -> str:
    """نص إجراء المالك (§30) عند غياب بيئة تنفيذ جاهزة — تشخيص دقيق."""
    environments = list_environments(sessions)
    ready = [e for e in environments if e["status"] == "READY"]
    if ready:
        return ""
    if not environments:
        return (
            "لا بيئة تنفيذ مسجلة — أضف بيئة من الإعدادات ← بيئات التنفيذ"
        )
    reasons = "؛ ".join(
        f"{e['name']} ({e['backend']}): {e['status']}"
        + (f" — {e['failure_reason'][:120]}" if e["failure_reason"] else "")
        for e in environments
    )
    return (
        "OWNER ACTION REQUIRED — لا بيئة تنفيذ جاهزة. الحالة الحالية: "
        f"{reasons}. الإجراء: شغّل عاملًا على Linux/WSL2 "
        "(python scripts/execution_worker.py) ← الإعدادات ← بيئات التنفيذ "
        "← إضافة بيئة (REMOTE_WORKER برابط العامل) ← تحقق ← أعد المهمة"
    )


__all__ = [
    "add_environment",
    "build_backend",
    "delete_environment",
    "ensure_local_registered",
    "get_environment",
    "list_environments",
    "owner_action_for_missing_environment",
    "resolve_executor",
    "run_code_unified",
    "sandbox_probe_result",
    "select_environment",
    "set_default",
    "verify_environment",
]
