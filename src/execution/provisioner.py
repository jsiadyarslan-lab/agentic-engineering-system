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
    VERIFYING_ISOLATION  هل توافق البيئة سياسة هذا المشروع؟ (013.6 §3)
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
#: INTERRUPTED (013.1 §12): تجهيز بدأ ثم انقطع (وفاة عملية/فقدان
#: عامل) قبل اكتمال فحص الصحة — لا READY ولا FAILED، بل قابل
#: للإعادة من DISCOVERING بقرار صريح.
PROVISION_STATES: tuple[str, ...] = (
    "DISCOVERING", "PROVISIONING", "BOOTING", "HEALTH_CHECK",
    # (013.6 §3) خطوة مطابقة العزل — منفصلة عن فحص الصحة عمدًا
    "VERIFYING_ISOLATION",
    "READY", "DEGRADED", "FAILED", "INTERRUPTED", "STOPPED",
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
                                            "BOOTING", "HEALTH_CHECK",
                                            "VERIFYING_ISOLATION")
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


def provision(sessions, *, policy: str = "STRICT_ISOLATED",
              on_event: Callable[[str, dict], None] | None = None
              ) -> dict:
    """تجهيز بيئة تنفيذ محلية كاملة الدورة (§16+§44 + 013.2 §5).

    الخطوات: اكتشاف ← تسجيل/تهيئة ← إقلاع ← فحص صحة ← READY — وكل
    خطوة تُسجل في الحالة القانونية الدائمة (runtime_state) فيصير
    «جاري التجهيز X%» حقيقة مقروءة لا وعودًا.

    (013.2 §4-§5) واعٍ بالسياسة حرفيًا: إن كان المضيف لا يستطيع
    توفير عزل فعلي (Windows بلا WSL2/Docker وبلا عامل بعيد) تحت
    STRICT_ISOLATED — فالنتيجة ENVIRONMENT_UNAVAILABLE بفجوات
    حرفية وأفعال واضحة، لا READY للبيئة المحلية المتوافقة وهي لا
    توافق السياسة (هذا بالضبط كان انفصام الحقيقة الذي رفضه المالك).
    """
    from execution import policy as execution_policy
    from execution import runtime_state
    from execution import service as execution_service
    from execution.backends import runtime_truth

    if not execution_policy.is_valid_policy(policy):
        policy = "STRICT_ISOLATED"
    steps: list[dict] = []
    started = time.monotonic()

    # ---- DISCOVERING: اكتشاف المضيف والركيزة (013.1 §11 حرفيًا) ----
    runtime_state.record_state(
        sessions, policy, "DISCOVERING",
        reason="جرد المضيف والركائز المتاحة…", progress=10,
    )
    t0 = time.monotonic()
    truth = runtime_truth()
    host = {
        "os": truth.get("os", ""), "arch": truth.get("architecture", ""),
        "python": truth.get("python", ""),
        "container": truth.get("container_runtime", ""),
        "cores": truth.get("cpu_cores", 0), "memory_gb": truth.get("memory", ""),
    }
    # (013.1 §11) جرد فعلي موسع — لا افتراض لأي عنصر: القرص/الحاوية
    # (docker/podman)/الافتراضية/المتصفح/الشبكة/العملية/العامل
    try:
        from readiness import environment as env_inventory

        inventory = env_inventory.environment_inventory()
        host["disk"] = next(
            (i.get("version") for k, i in inventory.items()
             if k == "disk"), "")
        host["container_runtimes"] = sorted(
            k for k, i in inventory.items()
            if k in ("docker", "podman") and i.get("status") == "READY"
        )
        host["vm_capability"] = next(
            (i.get("status") for k, i in inventory.items()
             if k == "vm"), "")
        host["chromium"] = next(
            (i.get("status") for k, i in inventory.items()
             if k == "browser_runtime"), "")
        host["network"] = next(
            ("READY" if i.get("status") == "READY" else i.get("status"))
            for k, i in inventory.items() if k == "network_dns"
        )
    except Exception:  # noqa: BLE001 — الجرد الموسع لا يكسر التجهيز
        inventory = {}
    substrate_ok = execution_service._substrate_available()
    host_is_linux = str(host.get("os", "")).lower() == "linux"
    has_remote_worker = any(
        env.get("backend") == "REMOTE_WORKER"
        for env in execution_service.list_environments(sessions)
    )
    _step(steps, "DISCOVERING", True,
          f"{host['os']}/{host['arch']} — Python {host['python']}"
          + (f" — {host['container']}" if host["container"] else "")
          + (f" — حاويات: {'، '.join(host['container_runtimes'])}"
             if host.get("container_runtimes") else " — لا حاويات")
          + (" — ركيزة العزل متاحة" if substrate_ok
             else " — ركيزة العزل غير متاحة (تنفيذ متوافق محلي)"),
          duration_ms=int((time.monotonic() - t0) * 1000),
          host=host, substrate_available=substrate_ok)

    # ---- (013.2 §4) الفجوة البنيوية أولًا: عزل صارم بلا مسار توفير ----
    # مضيف غير Linux بلا ركيزة بلا حاويات بلا عامل بعيد = التجهيز
    # المحلي المعزول مستحيل بنيويًا — يُعلن بالفجوة والفعل، لا فشل
    # ملفق ولا READY لبيئة لا توافق السياسة أصلًا.
    strict = policy == "STRICT_ISOLATED"
    can_isolate_locally = substrate_ok and host_is_linux
    has_containers = bool(host.get("container_runtimes"))
    if strict and not (can_isolate_locally or has_remote_worker
                       or has_containers):
        host_is_windows = str(host.get("os", "")).lower() == "windows"
        wsl_detection: dict = {}
        if host_is_windows:
            # (013.3 §3+§5) حد WSL2 الصريح قبل إعلان الاستحالة:
            # Windows ← wsl.exe ← Linux ← عامل داخل WSL — لا إطلاق
            # عامل Linux كعملية Windows بمسار Linux أبدًا (جذر WinError 267)
            wsl_result = _provision_wsl_worker(
                sessions, policy=policy, steps=steps, started=started,
            )
            if wsl_result is not None:
                return wsl_result
            wsl_detection = _LAST_WSL_DETECTION
        actual = runtime_state.canonical_state(sessions, policy)
        missing = list(actual.get("missing") or [])
        # (013.3 §5) فجوة WSL2 بالتفصيل الفعلي — لا «لا شيء متاح» عام
        if host_is_windows and wsl_detection:
            missing.append({
                "need": "WSL2 يعمل عليه python3 (حد تنفيذ Linux صريح)",
                "detected": (
                    "wsl.exe: "
                    + str(wsl_detection.get("steps", {}).get("wsl_exe"))
                    + "؛ uname: "
                    + str(wsl_detection.get("steps", {}).get("uname", ""))
                    + "؛ python3: "
                    + str(wsl_detection.get("steps", {}).get("python3", ""))
                ),
                "action": "فعّل WSL2 (wsl --install) مع توزيعة فيها "
                          "python3، أو سجّل عامل Linux بعيد",
            })
        reason = (
            f"المضيف {host['os']}/{host['arch']} لا يستطيع توفير عزل "
            "فعلي: لا ركيزة Linux محلية، لا حاويات Docker/Podman، "
            "لا عامل بعيد مسجل"
            + (
                "، وWSL2 غير متاح فعليًا"
                if host_is_windows else ""
            )
            + " — والسياسة ترفض التنفيذ بلا عزل"
        )
        runtime_state.record_state(
            sessions, policy, "UNAVAILABLE", reason=reason,
            missing=missing, evidence={"host": host,
                                       "wsl_detection": wsl_detection},
            progress=0,
        )
        _step(steps, "DISCOVERING", False, reason,
              host=host, substrate_available=substrate_ok)
        # (013.17-R1 §8) محاولة PROVISIONING تُسجَّل حتى في مسار الفجوة
        # البنيوية: آلة الحالة تُظهر أن التجهيز جُرِّب ورُفض لغياب أي
        # مسار عزل — لا قفزة صامتة من DISCOVERING إلى UNAVAILABLE،
        # والنتيجة تبقى صادقة (PROVISIONING_UNAVAILABLE بسبب حرفي).
        _step(steps, "PROVISIONING", False,
              "لا مسار تجهيز مطابق للسياسة — الفجوة البنيوية أعلاه "
              "سببها الحرفي، ولا تنفيذ بلا عزل",
              host=host, substrate_available=substrate_ok)
        result = _unavailable(sessions, steps, started, reason,
                              requirement=execution_policy
                              .requirement_text(policy))
        # (013.3 §5) العقد الحرفي: ENVIRONMENT_UNAVAILABLE بحقول
        # host/required/available/missing/action — لا يُحاول بعدها
        # تشغيل العامل كعملية Windows أبدًا
        result.update({
            "code": "ENVIRONMENT_UNAVAILABLE",
            "host": {
                "os": host.get("os", ""), "arch": host.get("arch", ""),
            },
            "required": "Linux x86_64 + STRICT_ISOLATED",
            "available": "LOCAL_WINDOWS (وضع متوافق بلا عزل — لا يوافق "
                         "السياسة)",
            "missing": missing,
            "action": (
                "جهّز WSL2 (wsl --install) أو سجّل عامل Linux بعيد "
                "(python scripts/execution_worker.py) — أو خفّض السياسة "
                "صراحة إلى COMPATIBLE_LOCAL من إعدادات المشروع"
            ),
        })
        result["policy"] = policy
        return result

    # ---- PROVISIONING: تسجيل البيئة المحلية (أو تأكيد وجودها) -------
    runtime_state.record_state(
        sessions, policy, "PROVISIONING",
        reason="تسجيل/تهيئة بيئة التنفيذ المحلية…", progress=30,
    )
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
    runtime_state.record_state(
        sessions, policy, "BOOTING",
        reason="إقلاع فحصي عبر المنفذ الموحد…", progress=55,
        environment_id=environment["id"],
    )
    t0 = time.monotonic()
    try:
        verified_full = execution_service.verify_environment(
            sessions, environment["id"]
        )
    except Exception as error:  # noqa: BLE001
        runtime_state.record_state(
            sessions, policy, "FAILED",
            reason=f"فشل فحص الصحة: {error}",
            environment_id=environment["id"], progress=0,
        )
        return _failed(sessions, steps, started,
                       f"فحص الصحة فشل: {error}", environment)
    runtime_state.record_state(
        sessions, policy, "HEALTH_CHECK",
        reason="فحوص الإقلاع/الكتابة/التنفيذ/التقاط تعمل…", progress=75,
        environment_id=environment["id"],
    )
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
        # (013.6 §3) خطوة صريحة: العزل يُتحقق منه منفصلًا عن الصحة.
        # الصحة تجيب «هل تعمل؟» والعزل يجيب «هل توافق سياسة هذا
        # المشروع؟» — ودمجهما كان يُخفي الفرق عن المالك تمامًا.
        runtime_state.record_state(
            sessions, policy, "VERIFYING_ISOLATION",
            reason="التحقق من مطابقة عزل البيئة لسياسة المشروع…",
            progress=90, environment_id=environment["id"],
        )
        # (013.2 §4) READY تُعلن فقط إذا وافقت البيئةُ السياسةَ حرفيًا:
        # تحقق ناجح لبيئة غير معزولة تحت عزل صارم ليس READY للسياسة —
        # هذا بالضبط كان انفصام «التقرير READY والواجهة غير جاهزة»
        satisfies = execution_policy.environment_satisfies(
            verified_full, policy
        )
        _step(
            steps, "VERIFYING_ISOLATION", bool(satisfies),
            (
                f"العزل مطابق: {verified_full.get('isolation') or 'معزولة'}"
                if satisfies else
                "العزل غير مطابق لسياسة المشروع — "
                f"الفعلي {verified_full.get('isolation') or 'NONE'}"
            ),
        )
        if not satisfies:
            reason = (
                f"البيئة «{environment['name']}» اجتازت الفحوص لكنها لا "
                "توافق سياسة العزل الصارم (تنفيذ متوافق بلا عزل). "
                "السياسة لا تقبلها — لا READY كاذبة"
            )
            missing = [{
                "need": "بيئة معزولة فعليًا توافق STRICT_ISOLATED",
                "detected": f"المضيف {host['os']}/{host['arch']} — "
                            "البيئة المحلية متوافقة بلا عزل",
                "action": "شغّل عاملًا بعيدًا على Linux/WSL2 "
                          "(python scripts/execution_worker.py) وسجّله، "
                          "أو فعّل WSL2/Docker، أو خفّض السياسة إلى "
                          "توافق محلي معلن",
            }]
            runtime_state.record_state(
                sessions, policy, "UNAVAILABLE", reason=reason,
                missing=missing, environment_id=environment["id"],
                evidence={"checks": verified.get("checks", [])[:10]},
                progress=0,
            )
            _step(steps, "READY", False, reason)
            return {
                "state": "PROVISIONING_UNAVAILABLE", "steps": steps,
                "policy": policy,
                "environment": environment, "reason": reason,
                "requirement": execution_policy.requirement_text(policy),
                "missing": missing,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "owner_action": (
                    "التنفيذ تحت سياسة العزل الصارم يتطلب بيئة معزولة "
                    "فعليًا — عامل بعيد على Linux/WSL2 أو تفعيل "
                    "WSL2/Docker، أو خفض السياسة صراحة من إعدادات المشروع"
                ),
            }
        _step(steps, "READY", True,
              f"بيئة التنفيذ «{environment['name']}» جاهزة — المسبار "
              "والمنفذ من مصدر واحد")
        runtime_state.record_state(
            sessions, policy, "READY",
            reason=f"البيئة «{environment['name']}» اجتازت فحوص الصحة "
                   "الحقيقية وتوافق السياسة",
            environment_id=environment["id"],
            evidence={"checks": verified.get("checks", [])[:10],
                      "verified_at": verified_full.get("last_verified_at")},
            progress=100,
        )
        _last_heartbeat.update({
            "at": _iso(_utc_now()), "ok": True,
            "environment_id": environment["id"],
            "environment_name": environment["name"],
        })
        return {
            "state": "READY", "steps": steps, "policy": policy,
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
    runtime_state.record_state(
        sessions, policy, "FAILED", reason=reason,
        environment_id=environment["id"],
        evidence={"failed_checks": failed_checks}, progress=0,
    )
    return {
        "state": "FAILED", "steps": steps, "policy": policy,
        "environment": environment, "reason": reason,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "owner_action": "راجع فحوص الإقلاع/الكتابة/التنفيذ/التقاط في "
                        "الخطوات أعلاه — السبب الحرفي معلن",
    }


#: آخر كشف WSL2 (013.3 §5) — للفجوة الدقيقة في رسالة الاستحالة.
_LAST_WSL_DETECTION: dict = {}


def _provision_wsl_worker(sessions, *, policy: str, steps: list[dict],
                          started: float) -> dict | None:
    """تجهيز عامل داخل WSL2 (013.3 §3+§5+§6) — حد تنفيذ صريح.

    Windows ← wsl.exe ← Linux ← python execution_worker.py ← HTTP.
    يعيد None إن لم يكن WSL2 متاحًا فعليًا (فيكمل المسار إعلان
    الاستحالة بفجوة WSL2 الدقيقة)، أو نتيجة التجهيز الكاملة عند
    توفره: فشل كل درجة مسمّى وصادق — لا READY كاذبة أبدًا.
    """
    import secrets as _secrets
    from pathlib import Path

    from execution import runtime_state
    from execution import service as execution_service
    from execution import wsl as wsl_mod

    global _LAST_WSL_DETECTION  # noqa: PLW0603 — الفجوة تُقرأ لاحقًا

    # ---- DISCOVERING: كشف WSL2 الفعلي — لا افتراض أبدًا (§5) ----
    runtime_state.record_state(
        sessions, policy, "DISCOVERING",
        reason="كشف WSL2 الفعلي (wsl.exe ← uname ← python3)…", progress=15,
    )
    detection = wsl_mod.wsl_available()
    _LAST_WSL_DETECTION = detection
    if not detection["available"]:
        return None  # الاستحالة البنيوية — مع الفجوة المسماة أعلاه

    # ---- PROVISIONING: بيئة العامل (إعادة استخدام أو تسجيل) ----
    runtime_state.record_state(
        sessions, policy, "PROVISIONING",
        reason=f"WSL2 متاح ({detection['detail']}) — تجهيز عامل Linux "
                "داخله عبر الحد الصريح…",
        progress=35,
    )
    existing = next(
        (env for env in execution_service.list_environments(sessions)
         if env["name"] == wsl_mod.WSL_ENVIRONMENT_NAME), None,
    )
    if existing is not None:
        environment = existing
        port = int(environment["endpoint"].rsplit(":", 1)[-1]
                   or wsl_mod.WSL_WORKER_DEFAULT_PORT)
        token = ""
        if environment.get("token_ref"):
            from secrets_store import store as secrets_store

            token = secrets_store.get_key(environment["token_ref"]) or ""
    else:
        port = wsl_mod.WSL_WORKER_DEFAULT_PORT
        token = _secrets.token_urlsafe(24)
        environment = execution_service.add_environment(
            sessions, name=wsl_mod.WSL_ENVIRONMENT_NAME,
            backend="REMOTE_WORKER",
            endpoint=f"http://127.0.0.1:{port}", token=token,
        )
    _step(steps, "PROVISIONING", True,
          f"بيئة العامل «{wsl_mod.WSL_ENVIRONMENT_NAME}» مسجلة "
          f"({environment['endpoint']}) — حد التنفيذ: Windows ← wsl.exe "
          "← Linux ← عامل",
          environment_id=environment["id"])

    # ---- BOOTING: العامل حي أصلًا؟ وإلا يُطلق داخل WSL (§6) ----
    runtime_state.record_state(
        sessions, policy, "BOOTING",
        reason="إطلاع العامل داخل WSL2 (بعد حل المسار داخل WSL نفسه)…",
        progress=45, environment_id=environment["id"],
    )
    from execution.backends import RemoteWorkerBackend

    worker_alive = False
    try:
        RemoteWorkerBackend(environment["endpoint"], token=token).health()
        worker_alive = True
    except Exception:  # noqa: BLE001 — أي عائق = يحتاج إطلاقًا
        worker_alive = False

    launch_evidence: dict = {"already_running": worker_alive}
    if not worker_alive:
        repo_root = Path(__file__).resolve().parents[2]
        launch = wsl_mod.launch_wsl_worker(
            repo_windows_root=repo_root, port=port, token=token,
        )
        launch_evidence = launch
        if not launch.get("ok"):
            reason = (
                f"فشل إطلاق العامل داخل WSL2 ({launch.get('stage')}/"
                f"{launch.get('reason')}): {launch.get('detail')}"
            )
            runtime_state.record_state(
                sessions, policy, "FAILED", reason=reason,
                environment_id=environment["id"],
                evidence={"wsl_launch": launch}, progress=0,
            )
            _step(steps, "BOOTING", False, reason,
                  environment_id=environment["id"])
            return {
                "state": "FAILED", "steps": steps, "policy": policy,
                "environment": environment, "reason": reason,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "owner_action": launch.get("detail", ""),
                "wsl_evidence": launch,
            }
        # مهلة إقلاع قصيرة صادقة — العامل يستمع داخل WSL
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                RemoteWorkerBackend(
                    environment["endpoint"], token=token,
                ).health()
                worker_alive = True
                break
            except Exception:  # noqa: BLE001 — لم يقلع بعد
                time.sleep(0.5)
        if not worker_alive:
            reason = (
                "أُطلق العامل داخل WSL2 لكنه لم يستجب على "
                f"{environment['endpoint']} خلال 20ث — تحقق من python3 "
                "والمنفذ داخل WSL"
            )
            runtime_state.record_state(
                sessions, policy, "FAILED", reason=reason,
                environment_id=environment["id"],
                evidence={"wsl_launch": launch}, progress=0,
            )
            _step(steps, "BOOTING", False, reason,
                  environment_id=environment["id"])
            return {
                "state": "FAILED", "steps": steps, "policy": policy,
                "environment": environment, "reason": reason,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "owner_action": reason,
                "wsl_evidence": launch,
            }
    _step(steps, "BOOTING", True,
          "العامل يعمل داخل WSL2 (نبضة HTTP حقيقية)"
          if worker_alive else "…",
          environment_id=environment["id"])

    # ---- HEALTH_CHECK: سلم الجاهزية الحقيقي عبر HTTP (§6+§8) ----
    runtime_state.record_state(
        sessions, policy, "HEALTH_CHECK",
        reason="سلم جاهزية العامل: connectivity←auth←heartbeat←env←"
                "workspace←execute←artifact…",
        progress=70, environment_id=environment["id"],
    )
    verified_full = execution_service.verify_environment(
        sessions, environment["id"]
    )
    verified = verified_full.get("verify") or {}
    # (013.6 §3) خطوة العزل الصريحة — قبل الحكم على المطابقة
    runtime_state.record_state(
        sessions, policy, "VERIFYING_ISOLATION",
        reason="التحقق من أن العامل يعلن ركيزة عزل Linux فعلية…",
        progress=90, environment_id=environment["id"],
        worker_id=launch_evidence.get("worker_id", ""),
    )
    satisfies = _satisfies(verified_full, policy)
    _step(
        steps, "VERIFYING_ISOLATION", bool(satisfies),
        (
            "العامل يعلن ركيزة Linux معزولة داخل WSL2"
            if satisfies else
            "الركيزة المُعلنة من العامل لا توافق سياسة المشروع"
        ),
    )

    if bool(verified.get("ok")) and satisfies:
        _step(steps, "HEALTH_CHECK", True,
              "فحوص العامل الحقيقية اجتازت داخل WSL2",
              environment_id=environment["id"],
              checks=[
                  {"name": c.get("name"), "ok": c.get("ok"),
                   "detail": str(c.get("detail", ""))[:120]}
                  for c in verified.get("checks", [])
              ])
        _step(steps, "READY", True,
              "بيئة Linux معزولة جاهزة عبر WSL2 — العامل يعلن ركيزة "
              "العزل من داخل Linux نفسه")
        runtime_state.record_state(
            sessions, policy, "READY",
            reason="عامل WSL2 اجتاز سلم الجاهزية ويعلن الركيزة المعزولة",
            environment_id=environment["id"],
            evidence={
                "checks": verified.get("checks", [])[:10],
                "wsl": launch_evidence,
                "verified_at": verified_full.get("last_verified_at"),
            },
            progress=100,
        )
        return {
            "state": "READY", "steps": steps, "policy": policy,
            "environment": {
                key: verified_full.get(key)
                for key in ("id", "name", "backend", "status",
                            "isolation", "sandboxed")
            },
            "reason": "بيئة Linux معزولة عبر WSL2 — عامل حقيقي بفحوص "
                      "حقيقية",
            "duration_ms": int((time.monotonic() - started) * 1000),
            "execution_boundary": "Windows ← wsl.exe ← Linux ← worker",
            "wsl_evidence": launch_evidence,
        }

    # فشل الصحة أو عدم موافقة السياسة — السبب الحرفي المسماة
    if bool(verified.get("ok")) and not satisfies:
        reason = (
            "عامل WSL2 يعمل واجتاز الفحوص لكنه يعلن تنفيذًا بلا ركيزة "
            "عزل (subprocess mode داخل WSL) — السياسة "
            f"{policy} لا تقبله. فعّل user namespaces داخل توزيعة WSL "
            "أو استخدم عامل Linux كامل"
        )
    else:
        reason = str(verified.get("reason")
                     or verified.get("status")
                     or "فشل سلم جاهزية عامل WSL2")[:300]
    runtime_state.record_state(
        sessions, policy, "UNAVAILABLE", reason=reason,
        environment_id=environment["id"],
        evidence={"checks": verified.get("checks", [])[:10],
                  "wsl": launch_evidence},
        progress=0,
    )
    _step(steps, "HEALTH_CHECK", False, reason,
          environment_id=environment["id"])
    return {
        "state": "PROVISIONING_UNAVAILABLE", "steps": steps,
        "policy": policy, "environment": environment, "reason": reason,
        "requirement": execution_policy.requirement_text(policy),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "owner_action": reason,
        "wsl_evidence": launch_evidence,
    }


def _satisfies(environment: dict, policy: str) -> bool:
    """environment_satisfies عبر الاستيراد المتأخر (تقاطع استيراد)."""
    from execution.policy import environment_satisfies

    return environment_satisfies(environment, policy)


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
