"""مزوّد بيئة التنفيذ (الأمر 013 §16-§17+§44) — دورة حياة معلنة.

المشكلة التي يحلها الموديول: كانت بيئة التنفيذ صف قاعدة يضيفه
المالك يدويًا — «Execution environment does not work» تعني لا مسار
من «غير جاهزة» إلى «جاهزة» داخل النظام. الآن الدورة كاملة:

    DISCOVERING     اكتشاف المضيف والركيزة (runtime_truth)
        ↓
    PROVISIONING    تهيئة المتطلبات (تسجيل محلي + حدود)
        ↓
    BOOTING         إقلاع فحصي (عملية حقيقية عبر المنفذ الموحد)
        ↓
    HEALTH_CHECK    إقلاع/كتابة/تنفيذ/التقاط حقيقية (verify)
        ↓
    READY — مسجلة ومختارة (المنفذ والمسبار من مصدر واحد 011)
    أو DEGRADED (تعمل بنقص) / FAILED (فشل الصحة) / STOPPED

الصدق الأول (§44): إذا كان التجهيز بنيويًا غير ممكن (لا ركيزة ولا
حاوية ولا عامل) — PROVISIONING_UNAVAILABLE بالمتطلب الخارجي
الحرفي، لا فشل ملفق ولا READY كاذبة. كل خطوة تُبث حدثًا حيًّا على
تيار المشاريع (project_id=0 نظامية) وتعاد في الاستجابة بالتزامن.
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Callable

#: حالات دورة حياة التجهيز (§16) — مفردة مقفلة بهذا الترتيب.
PROVISION_STATES: tuple[str, ...] = (
    "DISCOVERING", "PROVISIONING", "BOOTING", "HEALTH_CHECK",
    "READY", "DEGRADED", "FAILED", "STOPPED",
)

#: نبضة البيئة الأخيرة (§16 heartbeat) — بث لحظي فقط؛ الحقيقة في
#: سجل البيئات نفسها (verify يكتبها).
_last_heartbeat: dict = {"at": "", "ok": False, "environment_id": None}


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(moment: _dt.datetime) -> str:
    return moment.isoformat()


def _broadcast(kind: str, payload: dict) -> None:
    """حدث نظامي حي على تيار المشاريع (project_id=0) — لا دائمة
    نظامية: الاستجابة المتزامنة والسجل الدائم هما البرهان."""
    try:
        from core.live_bus import BUS, normalize_event

        BUS.publish(normalize_event({
            "project_id": 0, "kind": kind, "payload": payload,
            "event_id": 0, "stream": "projects", "db": "",
        }))
    except Exception:  # noqa: BLE001 — البث لا يكسر التجهيز
        pass


def _step(steps: list[dict], state: str, ok: bool, detail: str,
          *, duration_ms: int = 0, **extra) -> dict:
    entry = {
        "state": state, "ok": ok, "detail": detail,
        "at": _iso(_utc_now()), "duration_ms": duration_ms, **extra,
    }
    steps.append(entry)
    _broadcast(
        "PROVISIONING_STARTED" if state in ("DISCOVERING", "PROVISIONING",
                                            "BOOTING", "HEALTH_CHECK")
        else ("PROVISIONING_COMPLETED" if ok else "PROVISIONING_FAILED"),
        {"state": state, "ok": ok, "detail": detail, **extra},
    )
    return entry


def heartbeat(sessions, environment_id: int | None = None) -> dict:
    """نبضة البيئة (§16): فحص جاهزية حقيقي يسجل الزمن والنتيجة."""
    from execution import service as execution_service

    started = time.monotonic()
    if environment_id:
        verified_full = execution_service.verify_environment(
            sessions, environment_id
        )
    else:
        verified_full = _verify_any(sessions)
    verified = verified_full.get("verify") or {}
    ok = bool(verified.get("ok"))
    _last_heartbeat.update({
        "at": _iso(_utc_now()), "ok": ok,
        "environment_id": verified_full.get("id"),
        "environment_name": verified_full.get("name", ""),
        "latency_ms": int((time.monotonic() - started) * 1000),
    })
    _broadcast("ENVIRONMENT_HEARTBEAT", {
        "ok": ok, "at": _last_heartbeat["at"],
        "environment": verified_full.get("name", ""),
        "latency_ms": _last_heartbeat["latency_ms"],
    })
    return {**_last_heartbeat, "verified": verified,
            "environment": {
                key: verified_full.get(key)
                for key in ("id", "name", "status", "isolation")
            }}


def _verify_any(sessions) -> dict:
    from execution import service as execution_service

    environments = execution_service.list_environments(sessions)
    for env in environments:
        result = execution_service.verify_environment(sessions, env["id"])
        if (result.get("verify") or {}).get("ok"):
            return result
    return {"id": None, "name": "", "verify": {"ok": False}}


def provision(sessions, *,
              on_event: Callable[[str, dict], None] | None = None
              ) -> dict:
    """تجهيز بيئة تنفيذ محلية كاملة الدورة (§16+§44).

    الخطوات: اكتشاف ← تسجيل/تهيئة ← إقلاع ← فحص صحة ← READY.
    النتيجة: {state, steps[], environment, reason} — كل خطوة
    موقوتة ومعلنة، والفشل في أي منها سببه الحرفي لا عموميات.
    """
    from execution import service as execution_service
    from execution.backends import runtime_truth

    steps: list[dict] = []
    started = time.monotonic()

    # ---- DISCOVERING: اكتشاف المضيف والركيزة ------------------------
    t0 = time.monotonic()
    truth = runtime_truth()
    host = {
        "os": truth.get("os", ""), "arch": truth.get("architecture", ""),
        "python": truth.get("python", ""),
        "container": truth.get("container_runtime", ""),
        "cores": truth.get("cpu_cores", 0), "memory_gb": truth.get("memory", ""),
    }
    substrate_ok = execution_service._substrate_available()
    _step(steps, "DISCOVERING", True,
          f"{host['os']}/{host['arch']} — Python {host['python']}"
          + (f" — {host['container']}" if host["container"] else "")
          + (" — ركيزة العزل متاحة" if substrate_ok
             else " — ركيزة العزل غير متاحة (تنفيذ متوافق محلي)"),
          duration_ms=int((time.monotonic() - t0) * 1000),
          host=host, substrate_available=substrate_ok)

    # ---- PROVISIONING: تسجيل البيئة المحلية (أو تأكيد وجودها) -------
    t0 = time.monotonic()
    try:
        environment = execution_service.ensure_local_registered(sessions)
        _step(steps, "PROVISIONING", True,
              f"البيئة «{environment['name']}» مسجلة "
              f"({environment['backend']}/{environment['isolation']})",
              duration_ms=int((time.monotonic() - t0) * 1000),
              environment_id=environment["id"])
    except Exception as error:  # noqa: BLE001 — السبب الحرفي
        return _unavailable(sessions, steps, started,
                            f"تعذر تسجيل البيئة المحلية: {error}",
                            requirement="ركيزة تنفيذ محلية (packages/"
                                        "namespaces) أو عامل بعيد")

    # ---- BOOTING + HEALTH_CHECK: المنفذ الموحد هو الحكم (011 محفوظ)
    t0 = time.monotonic()
    try:
        verified_full = execution_service.verify_environment(
            sessions, environment["id"]
        )
    except Exception as error:  # noqa: BLE001
        return _failed(sessions, steps, started,
                       f"فحص الصحة فشل: {error}", environment)
    boot_ms = int((time.monotonic() - t0) * 1000)
    verified = verified_full.get("verify") or {}

    if bool(verified.get("ok")):
        _step(steps, "BOOTING", True,
              "إقلاع فحصي عبر المنفذ الموحد نجح",
              duration_ms=boot_ms)
        _step(steps, "HEALTH_CHECK", True,
              "إقلاع/كتابة/تنفيذ/التقاط — كلها حقيقية وناجحة",
              duration_ms=boot_ms,
              checks=[
                  {"name": c.get("name"), "ok": c.get("ok"),
                   "detail": str(c.get("detail", ""))[:120]}
                  for c in verified.get("checks", [])
              ])
        _step(steps, "READY", True,
              f"بيئة التنفيذ «{environment['name']}» جاهزة — المسبار "
              "والمنفذ من مصدر واحد")
        _last_heartbeat.update({
            "at": _iso(_utc_now()), "ok": True,
            "environment_id": environment["id"],
            "environment_name": environment["name"],
        })
        return {
            "state": "READY", "steps": steps,
            "environment": {
                key: verified_full.get(key)
                for key in ("id", "name", "backend", "status",
                            "isolation", "sandboxed")
            },
            "reason": "بيئة التنفيذ جاهزة بتجهيز فعلي مُتحقق",
            "duration_ms": int((time.monotonic() - started) * 1000),
            "heartbeat": dict(_last_heartbeat),
        }

    # فشل الصحة — بسبب حرفي، والمتطلب معلن (لا READY كاذبة)
    reason = str(verified.get("reason")
                 or verified.get("status")
                 or "فشل فحص الصحة")[:300]
    failed_checks = [
        {"name": c.get("name"), "ok": c.get("ok"),
         "detail": str(c.get("detail", ""))[:160]}
        for c in verified.get("checks", []) if not c.get("ok")
    ] or "كل الفحوص"
    _step(steps, "BOOTING", False, reason, duration_ms=boot_ms)
    _step(steps, "HEALTH_CHECK", False, reason, duration_ms=boot_ms,
          checks=failed_checks)
    _step(steps, "FAILED", False, reason)
    return {
        "state": "FAILED", "steps": steps,
        "environment": environment, "reason": reason,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "owner_action": "راجع فحوص الإقلاع/الكتابة/التنفيذ/التقاط في "
                        "الخطوات أعلاه — السبب الحرفي معلن",
    }


def _failed(sessions, steps: list[dict], started: float, reason: str,
            environment: dict) -> dict:
    _step(steps, "FAILED", False, reason)
    return {
        "state": "FAILED", "steps": steps, "environment": environment,
        "reason": reason,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def _unavailable(sessions, steps: list[dict], started: float,
                 reason: str, *, requirement: str) -> dict:
    """(§44) تعذر بنيوي صريح — المتطلب الخارجي معلن، لا فشل ملفق."""
    _broadcast("PROVISIONING_UNAVAILABLE", {
        "reason": reason, "requirement": requirement,
    })
    return {
        "state": "PROVISIONING_UNAVAILABLE", "steps": steps,
        "environment": None, "reason": reason,
        "requirement": requirement,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "owner_action": (
            "التجهيز المحلي بنيويًا غير ممكن في هذه البيئة — المطلوب: "
            + requirement
        ),
    }


def last_heartbeat() -> dict:
    """آخر نبضة مسجلة — قراءة صادقة (فارغة = لم تنبض بعد)."""
    return dict(_last_heartbeat)


__all__ = [
    "PROVISION_STATES",
    "heartbeat",
    "last_heartbeat",
    "provision",
]
