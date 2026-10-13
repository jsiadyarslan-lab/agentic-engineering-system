# -*- coding: utf-8 -*-
"""الأمر 013.11 §4 — تحصين بوابة أدلة الجاهزية (12 حالة إلزامية + تكامل).

المصدر: أمر 013.11 (حكم التحكيم على 013.10) — READY تشترط أدلة تحقق
مكتملة **وصالحة البنية وحديثة** وفق عقد الخلفية الفعلي، والفشل مغلق
عند أي عيب: عنصر مجهول البنية، اسم غائب/مكرر، نجاح غير منطقي صريح،
فحص مطلوب غائب، زمن غائب/غير قابل للتحليل/مستقبلي، أو تجاوز العمر
الأقصى (VERIFICATION_MAX_AGE_S=300 — اتساقًا مع مهلة مسبار البيئة).

البيانات الاصطناعية هنا تعكس **العقد الكامل** المستخرج من الكود
المنتج (src/execution/backends.py) عبر execution_policy.valid_evidence —
لا قائمة مختزلة يُتوقع منها READY خطأً (§5 حرفيًا).
"""

import datetime as _dt
import json as _json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from execution import policy as execution_policy  # noqa: E402


# ------------------------------------------------------------------ #
# أدوات البذر — قاعدة حقيقية + أدلة كاملة العقد قابلة للتشويه
# ------------------------------------------------------------------ #

def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


@pytest.fixture()
def env_db(tmp_path, monkeypatch):
    """قاعدة معزولة + مضيف بلا ركيزة (نمط 0131 المعتمد)."""
    from persistence.database import build_engine, init_db, make_session_factory
    from providers_registry import registry
    from execution import service as execution_service

    monkeypatch.chdir(tmp_path)
    engine = build_engine(tmp_path / "evidence-01311.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)
    monkeypatch.setattr(execution_service, "_substrate_available",
                        lambda: False)
    return sessions


def _evidence(*, backend="REMOTE_WORKER", sandboxed=True, env_id=1,
              age_s=0.0, mutate=None, drop_time=False):
    """أدلة كاملة صالحة (العقد الحرفي للخلفية) + تشويه اختياري.

    mutate(checks) تستقبل القائمة كاملة وتعيدها معدلة — كل التشويهات
    الإلزامية في الأمر تُبنى من دليل سليم واحد لتعزل المتغير الواحد.
    """
    verified_at = (
        (_now() - _dt.timedelta(seconds=age_s)).isoformat()
        if not drop_time else None
    )
    ev = execution_policy.valid_evidence(
        backend, sandboxed, environment_id=env_id,
        verified_at=verified_at,
    )
    if drop_time:
        ev.pop("last_verified_at")
    if mutate is not None:
        checks = mutate(ev["checks"])
        ev["checks"] = checks
    return ev


def _seed(sessions, *, status="HEALTHY", sandboxed=True, backend="REMOTE_WORKER",
          evidence=None, name=None, make_default=True):
    """بذر بيئة بتحكم كامل: الحالة/العزل/الأدلة (قاموس to_dict كامل)."""
    import sqlalchemy as sa

    from execution.models import ExecutionEnvironment

    label = name or f"seed-{status}-{backend}-{sandboxed}"
    detail = dict(evidence) if evidence else execution_policy.valid_evidence(
        backend, sandboxed, environment_id=1)
    stored_at = detail.get("last_verified_at")
    if isinstance(stored_at, str) and stored_at:
        stored_at = _dt.datetime.fromisoformat(stored_at)
    with sessions() as s:
        row = ExecutionEnvironment(
            name=label, backend=backend,
            endpoint=("http://127.0.0.1:9791" if backend == "REMOTE_WORKER"
                      else None),
            status=status, sandboxed=1 if sandboxed else 0,
            is_default=1 if make_default else 0,
            last_verified_at=stored_at,
            last_probe_detail=_json.dumps(detail, ensure_ascii=False),
        )
        s.add(row)
        s.flush()
        # ربط الهوية: الأدلة تعود لهذه البيئة حرفيًا (013.11 §2)
        if isinstance(detail.get("profile"), dict):
            detail["profile"]["environment_id"] = row.id
            row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()
        return row.id


def _env_dict(sessions, env_id):
    from execution import service as execution_service

    return [e for e in execution_service.list_environments(sessions)
            if e["id"] == env_id][0]


# ------------------------------------------------------------------ #
# الحد المركزي (§3-2): قيمة واحدة 300 ثانية — اتساقًا مع مسبار البيئة
# ------------------------------------------------------------------ #

def test_verification_max_age_is_central_300s():
    from execution import service as execution_service

    assert execution_policy.VERIFICATION_MAX_AGE_S == 300.0
    # الاتساق المعلن: مهلة مسبار البيئة ttl_seconds=300 في المصدر نفسه
    assert execution_service.PROBE_TTL_S == 300


# ------------------------------------------------------------------ #
# الحالة 1: أدلة كاملة حديثة صحيحة → READY فقط عند الأهلية
# ------------------------------------------------------------------ #

def test_complete_fresh_evidence_ready_when_eligible(env_db):
    from execution import service as execution_service

    env_id = _seed(env_db)  # عامل بعيد معلن العزل + سلم كامل حديث
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is True, verdict["blockers"]
    assert verdict["evidence"]["complete"] is True
    assert verdict["evidence"]["fresh"] is True
    # الاختيار عبر خدمة البيئات يفتح بهذه الأدلة حصرًا
    selected = execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED")
    assert selected is not None and selected["id"] == env_id


# ------------------------------------------------------------------ #
# الحالة 2: فحص واحد من المجموعة المطلوبة → لا READY (جذر 013.11)
# ------------------------------------------------------------------ #

def test_single_check_of_required_set_not_ready(env_db):
    env_id = _seed(env_db, evidence=_evidence(
        mutate=lambda checks: [checks[0]]))   # connectivity وحده
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False
    assert verdict["evidence"]["required_missing"], (
        "فحص واحد لا يكفي العقد الكامل للخلفية"
    )
    assert any(b.startswith("VERIFICATION_REQUIRED_MISSING")
               for b in verdict["blockers"])


# ------------------------------------------------------------------ #
# الحالة 3: مطلوب غائب / اسم مكرر / اسم غائب → لا READY
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("mutation", [
    pytest.param(
        lambda checks: [c for c in checks if c["name"] != "artifact_probe"],
        id="missing-required"),
    pytest.param(
        lambda checks: checks + [dict(checks[0])],
        id="duplicate-name"),
    pytest.param(
        lambda checks: checks + [{"ok": True, "detail": "بلا اسم"}],
        id="unnamed-element"),
    pytest.param(
        lambda checks: [dict(c, name="   ") if i == 2 else c
                        for i, c in enumerate(checks)],
        id="blank-name"),
])
def test_missing_duplicate_unnamed_required_check_not_ready(env_db, mutation):
    env_id = _seed(env_db, evidence=_evidence(mutate=mutation))
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False, verdict["blockers"]
    assert any(
        b.startswith(("VERIFICATION_REQUIRED_MISSING",
                      "VERIFICATION_MALFORMED"))
        for b in verdict["blockers"]
    )


# ------------------------------------------------------------------ #
# الحالة 4: عنصر غير قاموسي → لا READY (رفض مغلق لا تجاهل)
# ------------------------------------------------------------------ #

def test_non_dict_element_not_ready(env_db):
    def poison(checks):
        return checks + ["boot ok"]

    env_id = _seed(env_db, evidence=_evidence(mutate=poison))
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False
    assert any(b.startswith("VERIFICATION_MALFORMED")
               for b in verdict["blockers"])
    assert any("عنصر غير قاموسي" in m
               for m in verdict["evidence"]["malformed"])


# ------------------------------------------------------------------ #
# الحالة 5: ok غائب/None/نص "true" → لا READY (نجاح منطقي صريح حصرًا)
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("ok_value,ok_present", [
    pytest.param(None, False, id="ok-absent"),
    pytest.param(None, True, id="ok-none"),
    pytest.param("true", True, id="ok-string"),
    pytest.param(1, True, id="ok-int"),
])
def test_ok_missing_none_or_string_not_ready(env_db, ok_value, ok_present):
    def poison(checks):
        row = dict(checks[1])
        if ok_present:
            row["ok"] = ok_value
        else:
            row.pop("ok", None)
        return [row if i == 1 else c for i, c in enumerate(checks)]

    env_id = _seed(env_db, evidence=_evidence(mutate=poison))
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False, verdict["blockers"]
    assert any(b.startswith("VERIFICATION_MALFORMED")
               for b in verdict["blockers"])


# ------------------------------------------------------------------ #
# الحالة 6: أي فحص ok=False → لا READY حتى مع اكتمال المجموعة
# ------------------------------------------------------------------ #

def test_any_false_check_not_ready(env_db):
    def poison(checks):
        return [dict(c, ok=False) if c["name"] == "workspace_probe" else c
                for c in checks]

    env_id = _seed(env_db, evidence=_evidence(mutate=poison))
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False, verdict["blockers"]
    assert any("ok=False" in m or "نجاح غير منطقي" in m
               for m in verdict["evidence"]["malformed"])


# ------------------------------------------------------------------ #
# الحالة 7: last_verified_at غائب أو غير قابل للتحليل → لا READY
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("broken_time", [
    pytest.param(None, id="missing"),
    pytest.param("", id="empty"),
    pytest.param("ليس زمنًا", id="unparseable"),
    pytest.param((_now() + _dt.timedelta(minutes=10)).isoformat(),
                 id="unreasonably-future"),
])
def test_missing_or_unparseable_verified_at_not_ready(env_db, broken_time):
    # مستوى الوحدة مباشرة: حكم readiness على قاموس بيئة حامل زمنًا
    # مكسورًا — (التخزين الحقيقي لا يكتب إلا datetime؛ النص المكسور
    # يظهر من سجلات قديمة أو تدخل خارجي والبوابة تفشل مغلقًا)
    evidence = _evidence()
    env = {
        "id": 7, "name": "broken-time", "backend": "REMOTE_WORKER",
        "status": "HEALTHY", "sandboxed": True, "is_default": True,
        "last_verified_at": broken_time,
        "last_probe_detail": evidence,
    }
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False, verdict["blockers"]
    assert verdict["evidence"]["fresh"] is False
    assert any(b.startswith("VERIFICATION_TIME_INVALID")
               for b in verdict["blockers"])


# ------------------------------------------------------------------ #
# الحالة 8: تجاوز العمر الأقصى → لا READY بسبب حرفي VERIFICATION_STALE
#           (عند الحد نفسه يبقى طازجًا — الحد شامل)
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("age_s,expect_ready", [
    pytest.param(250, True, id="inside-ttl"),
    pytest.param(301, False, id="beyond-ttl"),
    pytest.param(3600, False, id="one-hour-old"),
])
def test_stale_beyond_ttl_not_ready_with_expiry_reason(env_db, age_s,
                                                       expect_ready):
    env_id = _seed(env_db, evidence=_evidence(age_s=age_s))
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is expect_ready, verdict["blockers"]
    if not expect_ready:
        assert verdict["evidence"]["stale_reason"].startswith(
            "VERIFICATION_STALE")
        assert any(b.startswith("VERIFICATION_STALE")
                   for b in verdict["blockers"])


# ------------------------------------------------------------------ #
# الحالة 9: أدلة كاملة حديثة لكن بلا عزل تحت STRICT → محجوبة
# ------------------------------------------------------------------ #

def test_fresh_valid_non_isolated_strict_blocked(env_db):
    # وضع متوافق: عقد عشرة فحوص (isolation فيها معكوس الدلالة عمدًا)
    env_id = _seed(env_db, backend="LOCAL", sandboxed=False,
                   evidence=_evidence(backend="LOCAL", sandboxed=False))
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is False
    assert verdict["evidence"]["complete"] is True, (
        "الأدلة صالحة — الحجب بسبب العزل لا بسبب العقد"
    )
    assert verdict["evidence"]["isolation_proof"] is False
    assert not execution_policy.environment_satisfies(env, "STRICT_ISOLATED")
    # العامل البعيد المعلن بلا عزل (السلم كامل لكن الإعلان False)
    env_id2 = _seed(env_db, name="worker-no-iso", backend="REMOTE_WORKER",
                    sandboxed=False,
                    evidence=_evidence(backend="REMOTE_WORKER",
                                       sandboxed=False))
    env2 = _env_dict(env_db, env_id2)
    assert not execution_policy.environment_satisfies(
        env2, "STRICT_ISOLATED")


# ------------------------------------------------------------------ #
# الحالة 10: أدلة كاملة حديثة + إثبات عزل صريح → الاختيار مسموح
# ------------------------------------------------------------------ #

def test_fresh_valid_proven_isolated_strict_selected(env_db):
    from execution import service as execution_service

    # (أ) الركيزة: فحص isolation الحي (شبكة محجوبة) هو الإثبات
    env_id = _seed(env_db, backend="LOCAL", sandboxed=True,
                   name="substrate-isolated",
                   evidence=_evidence(backend="LOCAL", sandboxed=True,
                                      env_id=None))
    env = _env_dict(env_db, env_id)
    verdict = execution_policy.readiness(env, "STRICT_ISOLATED")
    assert verdict["ready"] is True, verdict["blockers"]
    assert verdict["evidence"]["isolation_proof"] is True
    assert execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED")["id"] == env_id

    # (ب) العامل البعيد: لا فحص عزل في سلمه (فرق عقد موثق) — الإثبات
    #     إعلان العامل داخل الأدلة (profile.sandboxed) لحظة التحقق
    env_id2 = _seed(env_db, name="worker-isolated")
    env2 = _env_dict(env_db, env_id2)
    verdict2 = execution_policy.readiness(env2, "STRICT_ISOLATED")
    assert verdict2["ready"] is True, verdict2["blockers"]
    assert verdict2["evidence"]["isolation_proof"] is True

    # (ج) العامل الذي أعلن العزل لكن الأدلة بلا الإعلان (profile
    #     مبتور) → محجوب: sandboxed وحده في الصف لا يكفي (§2 حرفيًا)
    evidence3 = _evidence()
    evidence3["profile"].pop("sandboxed")
    env_id3 = _seed(env_db, name="worker-undeclared",
                    evidence=evidence3)
    env3 = _env_dict(env_db, env_id3)
    verdict3 = execution_policy.readiness(env3, "STRICT_ISOLATED")
    assert verdict3["ready"] is False, verdict3["blockers"]
    assert any(b.startswith("VERIFICATION_ISOLATION_PROOF_MISSING")
               for b in verdict3["blockers"])


# ------------------------------------------------------------------ #
# الحالة 11: READY تاريخية بأدلة كاملة حديثة → توافق رجعي
# ------------------------------------------------------------------ #

def test_legacy_ready_with_valid_complete_fresh_evidence(env_db):
    from execution import service as execution_service

    env_id = _seed(env_db, status="READY", name="legacy-ready")
    env = _env_dict(env_db, env_id)
    assert execution_policy.health_ok(env) is True
    assert execution_policy.environment_satisfies(env, "STRICT_ISOLATED")
    assert execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED")["id"] == env_id


# ------------------------------------------------------------------ #
# الحالة 12: أدلة جزئية/قديمة لا تفتح بوابة المهمة ولا تُطلق المنفذ
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("evidence,label", [
    pytest.param(_evidence(mutate=lambda cs: [cs[0]]),
                 "partial-single-check", id="partial"),
    pytest.param(_evidence(age_s=900), "stale-15min", id="stale"),
    pytest.param(_evidence(drop_time=True), "timeless", id="no-time"),
])
def test_partial_or_stale_evidence_never_opens_mission_gate(
        env_db, evidence, label):
    from execution import service as execution_service
    from readiness import preflight

    _seed(env_db, evidence=evidence, name=f"gate-{label}")

    # 1) المنفذ لا يُطلق: resolve_executor يعيد (None, None) تحت STRICT
    environment, backend = execution_service.resolve_executor(
        env_db, policy="STRICT_ISOLATED")
    assert environment is None and backend is None, (
        f"[{label}] منفذ أُطلق بأدلة غير مكتملة/قديمة — مخالفة §2+§3"
    )

    # 2) بوابة المهمة (preflight) تحجب: قدرة sandbox مشتقة من سجل
    #    البيئات بتعريف قانوني واحد — لا PASS بأدلة معيبة
    result = preflight.task_preflight(
        env_db, "مهمة تتطلب بيئة معزولة",
        run_probe_fn=_registry_probe,
    )
    assert result["verdict"] == "BLOCKED", result


def _registry_probe(sessions, capability_id, **_kwargs):
    """مسبار سجلي محايد: القدرات غير المعزولة تعاد جاهزة كي ينعزل
    قياس هذا الملف على قدرة sandbox المشتقة من الأدلة حصرًا."""
    from readiness import registry as readiness_registry
    from readiness.probes import ProbeResult

    if capability_id == "sandbox":
        return readiness_registry.record_probe(
            sessions, capability_id,
            ProbeResult(status="NOT_READY", reason="تُشتق من البيئات",
                        checked_at=_now().isoformat(),
                        details={"derived": True}),
        )
    return readiness_registry.record_probe(
        sessions, capability_id,
        ProbeResult(status="READY", reason="محايد لهذا الاختبار",
                    checked_at=_now().isoformat()),
    )


# ------------------------------------------------------------------ #
# الحالة 13 (التكامل الإلزامي): مسار كامل عبر خدمة اختيار البيئة +
#           runtime-state + preflight — فتح صادق ثم تقادم صادق
# ------------------------------------------------------------------ #

def test_integration_selection_runtime_state_preflight_fresh_then_stale(
        env_db):
    """دورة حياة الدليل: طازج → ثلاثة أسطح تفتح معًا؛ يتقادم → الثلاثة
    نفسها تحجب بـ VERIFICATION_STALE (لا سطح يبقى على القديم)."""
    from execution import runtime_state
    from execution import service as execution_service
    from readiness import preflight

    env_id = _seed(env_db, name="integration-worker")

    # (1) دليل طازج كامل: الاختيار يفتح وruntime-state READY وpreflight PASS
    selected = execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED")
    assert selected is not None and selected["id"] == env_id
    canonical = runtime_state.canonical_state(env_db, "STRICT_ISOLATED")
    assert canonical["state"] == "READY", canonical
    assert canonical["selected"]["id"] == env_id
    pre = preflight.task_preflight(env_db, "مهمة تكامل",
                                   run_probe_fn=_registry_probe)
    assert pre["verdict"] == "PASS", pre

    # (2) تقادم الدليل (بلا مس بأي شيء آخر): العمر يتجاوز 300ث
    with env_db() as s:
        from execution.models import ExecutionEnvironment

        row = s.get(ExecutionEnvironment, env_id)
        stale_moment = _now() - _dt.timedelta(seconds=600)
        row.last_verified_at = stale_moment
        detail = _json.loads(row.last_probe_detail)
        detail["last_verified_at"] = stale_moment.isoformat()
        row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()

    # (3) الاختيار نفسه لا يعيد بيئة قديمة — الصدق على كل السطوح
    assert execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED") is None
    canonical2 = runtime_state.canonical_state(env_db, "STRICT_ISOLATED")
    assert canonical2["state"] != "READY", canonical2
    # حالة الصحة التاريخية باقية (لا حذف ولا مفردة جديدة) والحجب بسبب حرفي
    env_after = _env_dict(env_db, env_id)
    assert execution_policy.health_ok(env_after) is True, (
        "حالة الصحة التاريخية تبقى كما هي — التقادم يمنع الجاهزية لا الصحة"
    )
    assert "VERIFICATION_STALE" in str(canonical2["coherent"].get("detail",
                                  canonical2.get("reason", ""))) or \
        canonical2["state"] == "DEGRADED"
    pre2 = preflight.task_preflight(env_db, "مهمة تكامل بعد التقادم",
                                    run_probe_fn=_registry_probe)
    assert pre2["verdict"] == "BLOCKED", pre2


# ------------------------------------------------------------------ #
# حصر فروق العقود بين الخلفيات (§2-6) — الحقيقة المستخرجة من الكود
# ------------------------------------------------------------------ #

def test_backend_contracts_match_documented_differences():
    substrate = execution_policy.required_check_names("LOCAL", True)
    compatible = execution_policy.required_check_names("LOCAL", False)
    worker = execution_policy.required_check_names("REMOTE_WORKER", True)
    # الركيزة: 9 فحوص — isolation فيها إثبات حي
    assert len(substrate) == 9 and "isolation" in substrate \
        and "preflight" not in substrate
    # المتوافق: 10 فحوص (تضاف preflight) — isolation معكوسة الدلالة
    assert len(compatible) == 10 and "preflight" in compatible
    # العامل: 7 فحوص سلم — لا فحص عزل إطلاقًا (فرق موثق)
    assert len(worker) == 7 and "isolation" not in worker
    # خلفية غير معروفة: لا عقد → لا تحقيق أبدًا (فشل مغلق)
    assert execution_policy.required_check_names("DOCKER", True) == ()
    doc = execution_policy.REQUIRED_CHECKS_DOC
    assert doc["REMOTE_WORKER"]["isolation_proof"].startswith("لا فحص عزل")
