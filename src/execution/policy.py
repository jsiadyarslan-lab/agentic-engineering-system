"""سياسة تنفيذ المهمة (الأمر 011 §26) — عزل صارم أو توافق معلن.

    STRICT_ISOLATED     تطلب بيئة معزولة (sandboxed=True) — Linux/x86_64
                        worker (ركيزة محلية على Linux أو عامل بعيد)؛
                        لا تعمل محليًا بلا عزل مهما كانت الظروف.

    COMPATIBLE_LOCAL    تقبل أي بيئة جاهزة معلنة (حتى غير المعزولة)
                        — تُوسم النتائج «وضع متوافق بلا عزل» صراحة،
                        ولا يُدّعى عزل أبدًا (011 §28: لا خفض للسقف).

السياسة قرار المالك (عمود projects.execution_policy) — لا تخمين:
STRICT_ISOLATED هي الافتراضية لأن النظام هندسي والادعاء أرخص من
الإثبات، والمالك يخفضها صراحة حين يريد التنفيذ المتوافق.

(013.11 §2+§3) تحصين بوابة الأدلة — حكم التحكيم على 013.10:
  READY = صحة ناجحة ∧ أدلة تحقق **مكتملة وصالحة البنية وحديثة** ∧ أهلية.
  - مجموعة الفحوص المطلوبة مستخرجة من VerifyResult الفعلي لكل خلفية
    (لا تخمين — انظر REQUIRED_CHECKS أدناه بمراجع الكود).
  - أي عنصر فحص مجهول البنية أو بلا اسم أو مكرر أو نجاحه غير منطقي
    صريح = أدلة فاسدة كلها (رفض مغلق، لا تجاهل العيب واحتساب البقية).
  - الدليل له عمر أقصى (VERIFICATION_MAX_AGE_S) — القديم لا يمنح
    READY مع بقاء حالة الصحة التاريخية كما هي (لا حذف ولا حالة جديدة
    في المفردات؛ الحجب بسبب حرفي VERIFICATION_STALE).
"""

from __future__ import annotations

import datetime as _dt

POLICIES: tuple[str, ...] = ("STRICT_ISOLATED", "COMPATIBLE_LOCAL")

POLICY_LABELS: dict[str, str] = {
    "STRICT_ISOLATED": "عزل صارم — بيئة معزولة إلزامية",
    "COMPATIBLE_LOCAL": "توافق محلي — بلا عزل، معلن",
}

# ------------------------------------------------------------------ #
# (013.11 §3) عمر الدليل الأقصى — قيمة مركزية واحدة.
# المصدر: اتساق مع مهلة مسبار بيئة التنفيذ الحالية ttl_seconds=300
# (src/execution/service.py sandbox_probe_result — ثلاثة مواضع) و مع
# الافتراضية في src/readiness/probes.py (ttl_seconds=300) ونبضة الوظائف
# (src/harness/jobs.py STALE_HEARTBEAT_S=300). لا وثيقة معمارية قائمة
# تحدد قيمة أخرى لعمر أدلة التحقق (فُحص docs/ — أقرب تعريف منظم هو
# _is_expired في readiness/service.py لمسبارات المزودين، نطاق مختلف).
# ------------------------------------------------------------------ #

VERIFICATION_MAX_AGE_S: float = 300.0

#: تسامح الوقت المستقبلي (انحراف ساعة طفيف بين الكاتب والقارئ) —
#: ما تجاوزه يُعد وقتًا مستقبليًا غير معقول = دليل غير صالح.
_FUTURE_TOLERANCE_S: float = 120.0

# ------------------------------------------------------------------ #
# (013.11 §2) عقد الفحوص المطلوبة لكل خلفية — مستخرج من الكود المنتج
# حرفيًا لا بالتخمين:
#
# LOCAL + sandboxed (ركيزة Linux معزولة) — LocalSandboxBackend.verify
#   (src/execution/backends.py، وسم «013.2 §6 فحوص مسماة حرفية»):
#   تسعة فحوص، و«isolation» فيها هو إثبات العزل الحي: ok تعني شبكة
#   محجوبة داخل namespaces (نجاح DNS يعني أن العزل مكسور — backends.py
#   سطر «نجاح DNS يعني أن العزل مكسور»).
#
# LOCAL بلا عزل (وضع متوافق — منفذ عمليات المضيف) —
#   LocalProcessBackend.verify (backends.py، وسم «013.3 §8»): عشرة
#   فحوص (تضاف preflight)، و«isolation» فيها معكوسة الدلالة عمدًا:
#   ok تعني أن الشبكة تعمل (صدق الإعلان: بلا عزل) — ليست إثبات عزل.
#
# REMOTE_WORKER — RemoteWorkerBackend.verify (backends.py، وسم
#   «سلم جاهزية العامل 011 §10»): سبعة فحوص connectivity→artifact_probe.
#   **فرق عقد موثق**: سلم العامل بلا فحص عزل إطلاقًا؛ حالة العزل تأتي
#   معلنة من العامل نفسه (profile.sandboxed من /capabilities —
#   backends.py: «network_policy: worker-declared»). لذلك إثبات العزل
#   تحت STRICT للعامل البعيد = profile.sandboxed=True **داخل الأدلة**
#   (المسجَّل لحظة التحقق الحقيقي) + اكتمال السلم — وحدّ البروتوكول
#   هذا معلن في التقرير (013.11 §6-2).
# ------------------------------------------------------------------ #

_SUBSTRATE_CHECKS: tuple[str, ...] = (
    "boot", "execute", "write_file", "read_file", "delete_file",
    "working_directory", "architecture", "isolation", "capture",
)
_COMPAT_CHECKS: tuple[str, ...] = (
    "preflight", "boot", "execute", "write_file", "read_file",
    "delete_file", "working_directory", "architecture", "isolation",
    "capture",
)
_WORKER_CHECKS: tuple[str, ...] = (
    "connectivity", "authentication", "heartbeat", "environment_probe",
    "workspace_probe", "execute_probe", "artifact_probe",
)

_REQUIRED_CHECKS: dict[tuple[str, bool], tuple[str, ...]] = {
    ("LOCAL", True): _SUBSTRATE_CHECKS,
    ("LOCAL", False): _COMPAT_CHECKS,
    # العامل البعيد: السلم نفسه معزولًا أو لا (الإعلان في الملف الشخصي)
    ("REMOTE_WORKER", True): _WORKER_CHECKS,
    ("REMOTE_WORKER", False): _WORKER_CHECKS,
}

#: أكواد الحجب الحرفية — قابلة للفحص من الواجهة والاختبارات.
EVIDENCE_BLOCKERS: dict[str, str] = {
    "VERIFICATION_MALFORMED": "أدلة التحقق فاسدة البنية",
    "VERIFICATION_REQUIRED_MISSING": "فحوص مطلوبة غائبة من الأدلة",
    "VERIFICATION_TIME_INVALID": "زمن التحقق غائب أو غير قابل للتحليل أو مستقبلي غير معقول",
    "VERIFICATION_STALE": "أدلة التحقق تجاوزت عمرها الأقصى",
    "VERIFICATION_ISOLATION_PROOF_MISSING": "لا إثبات عزل صريح داخل الأدلة",
    "VERIFICATION_IDENTITY_MISMATCH": "أدلة التحقق تعود لبيئة أخرى",
}


def is_valid_policy(policy: str) -> bool:
    return policy in POLICIES


# ------------------------------------------------------------------ #
# (013.10 §3) التعريف القانوني الواحد للجاهزية — مصدر واحد يقرأه
# بوابة السياسة وحالة العرض والتجهيز والمسبار:
#
#   HEALTHY   نجاح فحص الصحة (إقلاع/كتابة/تنفيذ/التقاط) بأدلة دائمة.
#   ELIGIBLE  صحة ناجحة + مطابقة متطلب السياسة (العزل تحت الصارم).
#   READY     السماح الفعلي ببدء التنفيذ = صحة + أدلة تحقق + أهلية.
#
# ثلاثة مفاهيم منفصلة لا تُدمج أبدًا: «سليمة» ليست «مؤهلة»،
# و«مؤهلة» بلا أدلة تحقق دائمة ليست «جاهزة». (يغلق شق 013.9:
# verify يكتب HEALTHY بينما البوابة تشترط READY فتبقى المهمة
# محجوبة بعد نجاح التحقق نفسه.)
# ------------------------------------------------------------------ #

#: حالات الصحة الصادقة: HEALTHY (نموذج 013.7 §P1) أو READY المخزنة
#: تاريخيًا من النظام القديم — الثانية تعامل كصحة ناجحة عندما تحمل
#: أدلتها (لا تُبطل تلقائيًا، ولا تكفي بلا أدلة لمجرد اسمها).
HEALTH_STATUSES: tuple[str, ...] = ("HEALTHY", "READY")


def health_ok(environment: dict) -> bool:
    """هل فحص الصحة ناجح؟ — HEALTHY أو READY التاريخية، لا غير."""
    return environment.get("status") in HEALTH_STATUSES


def required_check_names(backend: str, sandboxed: bool) -> tuple[str, ...]:
    """مجموعة الفحوص المطلوبة لعقد الخلفية — من REQUIRED_CHECKS حرفيًا.

    خلفية غير معروفة = مجموعة فارغة لا تُحقق أبدًا (فشل مغلق:
    verification_evidence تعلن REQUIRED_UNKNOWN لا أنها تمر).
    """
    return _REQUIRED_CHECKS.get(
        (str(backend), bool(sandboxed)), ()
    )


def _parse_verified_at(value) -> tuple[_dt.datetime | None, str]:
    """تحليل زمن التحقق — (الزمن، سبب-الرفض-الحرفي).

    يقبل datetime (naive تُعامل UTC — حفظ SQLite يجرّد المنطقة) أو
    نص isoformat. يرفع سببًا حرفيًا للغائب/غير القابل للتحليل/
    المستقبلي غير المعقول (013.11 §3-3).
    """
    if value is None or value == "":
        return None, "VERIFICATION_TIME_INVALID:زمن التحقق غائب"
    if isinstance(value, _dt.datetime):
        moment = value
    else:
        try:
            moment = _dt.datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None, "VERIFICATION_TIME_INVALID:زمن غير قابل للتحليل"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    moment = moment.astimezone(_dt.timezone.utc)
    now = _dt.datetime.now(_dt.timezone.utc)
    if (moment - now).total_seconds() > _FUTURE_TOLERANCE_S:
        return None, "VERIFICATION_TIME_INVALID:زمن مستقبلي غير معقول"
    return moment, ""


def valid_evidence(
    backend: str, sandboxed: bool, *, environment_id: int | None = None,
    verified_at=None, os_name: str = "Linux", arch: str = "x86_64",
) -> dict:
    """بناء أدلة تحقق صحيحة **كاملة العقد** — للبذر والاختبار والتوثيق.

    تعكس الشكل الحرفي الذي يكتبه verify_environment
    (result.to_dict(): ok/status/checks/profile/reason) بكل فحوص
    المجموعة المطلوبة للخلفية ناجحة — لا قائمة مختزلة (013.11 §5:
    البيانات الاصطناعية يجب أن تعكس العقد الكامل).
    """
    profile = {
        "environment_id": environment_id,
        "backend": backend,
        "os": os_name,
        "architecture": arch,
        "sandboxed": bool(sandboxed),
        "isolation": ("REMOTE" if backend == "REMOTE_WORKER"
                      else ("NAMESPACES" if sandboxed else "NONE")),
        "network_policy": ("worker-declared" if backend == "REMOTE_WORKER"
                           else ("namespaces-no-egress" if sandboxed
                                 else "host")),
    }
    return {
        "ok": True,
        "status": "READY",
        "checks": [
            {"name": name, "ok": True, "detail": "عقد كامل (013.11)"}
            for name in required_check_names(backend, sandboxed)
        ],
        "profile": profile,
        "reason": "",
        "last_verified_at": (
            verified_at if verified_at is not None
            else _dt.datetime.now(_dt.timezone.utc).isoformat()
        ),
    }


def verification_evidence(environment: dict) -> dict:
    """أدلة التحقق الدائمة — الحكم المحكم (013.11 §2+§3).

    العقد:
      1. last_probe_detail يحمل {checks:[...]} (أو {verify:{checks}}).
      2. كل عنصر فحص: قاموس، اسم نصي غير فارغ **فريد**، ونجاح منطقي
         صريح يساوي True (ok is True — يرفض "true"/1/None/الغائب).
      3. أي عنصر معيب = أدلة فاسدة كلها (رفض مغلق، لا احتساب البقية).
      4. مجموعة الفحوص المطلوبة لعقد الخلفية (backend, sandboxed)
         موجودة كاملة بأسمائها — خلفية غير معروفة لا تُحقق أبدًا.
      5. الزمن: موجود، قابل للتحليل، ليس مستقبليًا غير معقول، وعمره
         ≤ VERIFICATION_MAX_AGE_S — وإلا الدليل غير صالح/قديم.
      6. هوية البيئة: profile.environment_id (إن وُجد في الأدلة)
         يطابق البيئة الحاملة — وإلا أدلة لبيئة أخرى (فاسدة).

    ملاحظة توافق: records قديمة بلا profile.environment_id تُقبل
    بلا حكم هوية (الربط البنيوي: الأدلة مخزنة على صف البيئة نفسها
    كتبها verify_environment) — الموثق في التقرير 013.11 §6-2.
    """
    detail = environment.get("last_probe_detail") or {}
    verify = detail.get("verify") or detail
    checks = verify.get("checks") or []
    backend = str(environment.get("backend") or "")
    sandboxed = bool(environment.get("sandboxed"))
    required = required_check_names(backend, sandboxed)

    malformed: list[str] = []
    seen: set[str] = set()
    ok_names: set[str] = set()
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            malformed.append(f"[{index}] عنصر غير قاموسي")
            continue
        name = check.get("name")
        if not isinstance(name, str) or not name.strip():
            malformed.append(f"[{index}] اسم فحص غائب أو فارغ")
            continue
        if name in seen:
            malformed.append(f"[{index}] اسم مكرر: {name}")
            continue
        seen.add(name)
        ok_value = check.get("ok")
        if ok_value is not True:
            malformed.append(
                f"[{index}] نجاح غير منطقي صريح ({name}: {ok_value!r})"
            )
            continue
        ok_names.add(name)

    if not required:
        malformed.append(
            f"خلفية غير معروفة ({backend!r}) — لا عقد فحوص يُحقق"
        )
    required_missing = [name for name in required if name not in ok_names]

    # الزمن والصلاحية (013.11 §3)
    verified_at = environment.get("last_verified_at")
    moment, time_reject = _parse_verified_at(verified_at)
    age_s: float | None = None
    fresh = False
    stale_reason = time_reject
    if moment is not None:
        age_s = (
            _dt.datetime.now(_dt.timezone.utc) - moment
        ).total_seconds()
        if age_s > VERIFICATION_MAX_AGE_S:
            stale_reason = (
                f"VERIFICATION_STALE:عمر الدليل {int(age_s)}ث يتجاوز "
                f"الحد {int(VERIFICATION_MAX_AGE_S)}ث"
            )
        else:
            fresh = True

    # هوية البيئة داخل الأدلة (013.11 §2)
    identity_reject = ""
    profile = verify.get("profile") or {}
    evidence_env_id = profile.get("environment_id") if isinstance(
        profile, dict) else None
    env_id = environment.get("id")
    if evidence_env_id is not None and env_id is not None:
        try:
            if int(evidence_env_id) != int(env_id):
                identity_reject = (
                    "VERIFICATION_IDENTITY_MISMATCH:"
                    f"الأدلة للبيئة {evidence_env_id} لا {env_id}"
                )
        except (TypeError, ValueError):
            identity_reject = (
                "VERIFICATION_IDENTITY_MISMATCH:معرف غير قابل للمقارنة"
            )

    # إثبات العزل الصريح تحت العقد (للمسار الصارم يُستهلك في readiness)
    # - LOCAL معزولة: فحص isolation داخل العقد هو الإثبات الحي.
    # - REMOTE_WORKER: لا فحص عزل في سلمها (فرق عقد موثق) — الإثبات
    #   الممكن هو profile.sandboxed=True داخل الأدلة نفسها.
    isolation_proof = False
    if (backend, sandboxed) == ("LOCAL", True):
        isolation_proof = "isolation" in ok_names
    elif backend == "REMOTE_WORKER":
        isolation_proof = bool(
            isinstance(profile, dict) and profile.get("sandboxed")
        )
    elif (backend, sandboxed) == ("LOCAL", False):
        # الوضع المتوافق: فحص isolation معكوس الدلالة (شبكة تعمل) —
        # ليس إثبات عزل ولا يُطالب به.
        isolation_proof = False

    shape_ok = not malformed and not required_missing
    complete = bool(shape_ok and fresh and not identity_reject)
    return {
        "last_verified_at": verified_at,
        "age_s": age_s,
        "fresh": fresh,
        "stale_reason": stale_reason,
        "checks_count": len(checks),
        "checks_ok": not malformed and bool(checks),
        "required": list(required),
        "required_missing": required_missing,
        "malformed": malformed,
        "identity_reject": identity_reject,
        "isolation_proof": isolation_proof,
        "complete": complete,
    }


def policy_eligibility(environment: dict, policy: str) -> tuple[bool, str]:
    """أهلية البيئة لسياسة معينة — الصحة شرط مسبق للأهلية (013.10 §3-1).

    STRICT_ISOLATED   عزل فعلي (sandboxed) إلزامي — بلا استثناء.
    COMPATIBLE_LOCAL  تقبل غير المعزولة، لكن لا تُهلّك بيئة لم تجتز
                      الصحة بعد (DETECTED ليست مؤهلة).
    تعيد (مؤهلة؟، سبب عدم الأهلية الحرفي).
    """
    if not health_ok(environment):
        status = environment.get("status")
        return False, (
            f"لم تجتز فحص الصحة بعد (status={status!r}) — "
            "الأهلية بعد الصحة في السلم القانوني"
        )
    if policy == "STRICT_ISOLATED":
        if bool(environment.get("sandboxed")):
            return True, ""
        return False, "سليمة لكن غير معزولة — السياسة تطلب عزلًا صارمًا"
    if policy == "COMPATIBLE_LOCAL":
        return True, ""
    return False, f"سياسة غير معروفة: {policy}"


def readiness(environment: dict, policy: str) -> dict:
    """حكم الجاهزية الكامل — التعريف القانوني الواحد (013.10 §3 + 013.11 §2+§3).

    ready = صحة ناجحة ∧ أدلة تحقق مكتملة **وصالحة البنية وحديثة** ∧ أهلية
    السياسة (∧ إثبات عزل صريح تحت STRICT حيث يتطلبه العقد).
    blockers أسباب حرفية بأكواد قابلة للفحص (EVIDENCE_BLOCKERS).
    """
    h = health_ok(environment)
    evidence = verification_evidence(environment)
    eligible, ineligibility = policy_eligibility(environment, policy)
    blockers: list[str] = []
    if not h:
        blockers.append(
            "حالة البيئة "
            f"{environment.get('status')!r} ليست صحة ناجحة "
            f"({'/'.join(HEALTH_STATUSES)})"
        )
    if evidence["malformed"]:
        blockers.append(
            f"VERIFICATION_MALFORMED: أدلة فاسدة البنية — "
            f"{'; '.join(evidence['malformed'][:5])}"
        )
    if evidence["required_missing"]:
        blockers.append(
            f"VERIFICATION_REQUIRED_MISSING: فحوص مطلوبة غائبة — "
            f"{', '.join(evidence['required_missing'])}"
        )
    if evidence["stale_reason"]:
        blockers.append(evidence["stale_reason"])
    if evidence["identity_reject"]:
        blockers.append(evidence["identity_reject"])
    if h and eligible and policy == "STRICT_ISOLATED" and not evidence[
        "isolation_proof"
    ]:
        blockers.append(
            "VERIFICATION_ISOLATION_PROOF_MISSING: لا إثبات عزل صريح "
            "داخل أدلة التحقق (فحص العزل للركيزة، أو إعلان العامل "
            "المسجل لحظة التحقق) — sandboxed وحده لا يكفي (013.11 §2)"
        )
    if not eligible and h:
        # سبب الأهلية يُذكر صراحة عندما تكون الصحة قائمة (غيره مكرر)
        blockers.append(ineligibility)
    ready = bool(
        h and evidence["complete"] and eligible
        and (policy != "STRICT_ISOLATED" or evidence["isolation_proof"])
    )
    return {
        "health_ok": h,
        "evidence": evidence,
        "eligible": eligible,
        "ready": ready,
        "blockers": blockers,
    }


def environment_satisfies(environment: dict, policy: str) -> bool:
    """هل البيئة جاهزة فعلًا وتفي بسياسة التنفيذ؟ (011 §27 + 013.10 §3)

    التعريف القانوني الموحد — لا يكفي status=="READY" الخام:
    HEALTHY بعد تحقق ناجح بأدلة كاملة تُختار تحت STRICT_ISOLATED،
    وسجل قديم بلا أدلة لا يحصل على الجاهزية لمجرد اسمه.
    """
    return readiness(environment, policy)["ready"]


def select_environment_for_policy(
    environments: list[dict], policy: str,
) -> dict | None:
    """اختيار بيئة وفق السياسة — الافتراضية الجاهزة الموافقة أولًا.

    لا تعيد بيئة لا تفي بالسياسة أبدًا؛ غياب الموافق = None والسبب
    يعرضه preflight (011 §18+§27).
    """
    satisfying = [
        env for env in environments if environment_satisfies(env, policy)
    ]
    if not satisfying:
        return None
    for env in satisfying:
        if env.get("is_default"):
            return env
    # للتوافق المحلي: فضّل المعزولة إن وُجدت (أمان أعلى بلا كلفة إضافية)
    if policy == "COMPATIBLE_LOCAL":
        for env in satisfying:
            if env.get("sandboxed"):
                return env
    return satisfying[0]


def requirement_text(policy: str) -> str:
    """نص «المطلوب» الصريح (011 §3+§27 + 013.2 §2).

    (013.2 §2) هذا نص *متطلب* لا نص *حالة*: ممنوع أن يحمل كلمة
    «جاهزة» أو أي صياغة توحي بحالة تشغيل — فالذي عرض سابقًا تحت
    «غير جاهزة» كان يقول «بيئة معزولة جاهزة» فنشأ التناقض الذي
    رفضه المالك. الصياغة الآن: مطلوب + كيف يوفره المالك.
    """
    if policy == "STRICT_ISOLATED":
        return (
            "المطلوب: بيئة تنفيذ Linux/x86_64 معزولة فعليًا — "
            "الركيزة المحلية على مضيف Linux، أو عامل بعيد على أي "
            "Linux/WSL2 (python scripts/execution_worker.py). "
            "لم تُوفَّر بعد على هذا المضيف"
        )
    return "المطلوب: أي بيئة تنفيذ تعمل فعليًا (حتى المتوافقة غير المعزولة) — لم تُتحقق بعد"


def policy_note(policy: str) -> str:
    """سطر معلن يرافق التنفيذ والنتائج حسب السياسة (011 §26)."""
    if policy == "STRICT_ISOLATED":
        return "السياسة: عزل صارم — التنفيذ داخل بيئة معزولة حصرًا"
    return (
        "السياسة: توافق محلي — التنفيذ قد يكون بلا عزل وهذا معلن؛ "
        "لا يُدّعى عزل في هذا المسار"
    )


__all__ = [
    "EVIDENCE_BLOCKERS",
    "HEALTH_STATUSES",
    "POLICIES",
    "POLICY_LABELS",
    "REQUIRED_CHECKS_DOC",
    "VERIFICATION_MAX_AGE_S",
    "environment_satisfies",
    "health_ok",
    "is_valid_policy",
    "policy_eligibility",
    "policy_note",
    "readiness",
    "required_check_names",
    "requirement_text",
    "select_environment_for_policy",
    "valid_evidence",
    "verification_evidence",
]

#: توثيق الفروق بين عقود الخلفيات (013.11 §6-2) — يقرأه التقرير
#: والاختبارات بدل إعادة اكتشافه من الكود كل مرة.
REQUIRED_CHECKS_DOC: dict[str, dict] = {
    "LOCAL_sandboxed": {
        "source": "src/execution/backends.py LocalSandboxBackend.verify (وسم 013.2 §6)",
        "checks": list(_SUBSTRATE_CHECKS),
        "isolation_proof": "فحص isolation: شبكة محجوبة داخل namespaces (إثبات حي)",
    },
    "LOCAL_compatible": {
        "source": "src/execution/backends.py LocalProcessBackend.verify (وسم 013.3 §8)",
        "checks": list(_COMPAT_CHECKS),
        "isolation_proof": "لا شيء — فحص isolation هنا معكوس الدلالة (شبكة تعمل = صدق إعلان)",
    },
    "REMOTE_WORKER": {
        "source": "src/execution/backends.py RemoteWorkerBackend.verify (وسم 011 §10)",
        "checks": list(_WORKER_CHECKS),
        "isolation_proof": (
            "لا فحص عزل في السلم (فرق عقد موثق) — الإثبات الممكن: "
            "profile.sandboxed داخل الأدلة (إعلان العامل لحظة التحقق)"
        ),
    },
}
