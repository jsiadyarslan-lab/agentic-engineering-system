"""اختبارات بوابة الجاهزية الموحدة (013.10 §3) — إغلاق PD-1.

العقد الحرفي من الأمر: تعريف قانوني واحد يفصل ثلاثة مفاهيم لا تُدمج:
  HEALTHY   نجاح فحص الصحة بأدلة دائمة.
  ELIGIBLE  صحة + مطابقة سياسة المشروع (العزل تحت الصارم).
  READY     السماح الفعلي ببدء التنفيذ = صحة ∧ أدلة ∧ أهلية.

يغلق شق 013.9: verify يكتب HEALTHY بينما كانت البوابة تشترط
status=="READY" الخام — فبيئة متحققة معزولة بقيت محجوبة
(DISCOVERING/selected=null) بعد نجاح التحقق نفسه.

الحالات الإلزامية الثماني من الأمر §3 + اتساق الحالة المعروضة
(compute_environment_state) + مسارات الخدمة والحالة القانونية.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


@pytest.fixture()
def env_db(tmp_path, monkeypatch):
    """قاعدة معزولة + مضيف بلا ركيزة (نمط 0131 المعتمد)."""
    from persistence.database import build_engine, init_db, make_session_factory
    from providers_registry import registry
    from execution import service as execution_service

    monkeypatch.chdir(tmp_path)
    engine = build_engine(tmp_path / "gate-01310.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)
    monkeypatch.setattr(execution_service, "_substrate_available",
                        lambda: False)
    return sessions


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _seed(sessions, *, status, sandboxed, verified="now",
          checks=None, name=None, make_default=False):
    """بذر بيئة بتحكم كامل في العقد: الحالة/العزل/الأدلة.

    verified: "now" = تحقق حاضر، None = بلا تحقق، datetime = قيمة.
    checks: None = أدلة كاملة العقد (013.11 §5)، [] = بلا فحوص،
    قائمة = كما هي (تشويه مقصود).
    """
    import json as _json

    import sqlalchemy as sa

    from execution import policy as execution_policy
    from execution import service as execution_service
    from execution.models import ExecutionEnvironment

    execution_service.ensure_local_registered(sessions)
    label = name or f"seed-{status}-{sandboxed}-{len(str(checks))}"
    if checks is None:
        # (013.11) العقد الكامل لعامل بعيد معلن العزل — لا قائمة مختزلة
        detail = execution_policy.valid_evidence(
            "REMOTE_WORKER", sandboxed)
        stored_at = (
            _now() if verified == "now"
            else (verified if isinstance(verified, _dt.datetime) else None)
        )
        detail["last_verified_at"] = (
            stored_at.isoformat() if stored_at else None
        )
    else:
        detail = ({"verify": {"ok": True, "status": "READY",
                              "checks": checks}}
                  if checks else {})
        stored_at = (
            _now() if verified == "now"
            else (verified if isinstance(verified, _dt.datetime) else None)
        )
    with sessions() as s:
        row = ExecutionEnvironment(
            name=label, backend="REMOTE_WORKER",
            endpoint="http://127.0.0.1:9777",
            status=status, sandboxed=1 if sandboxed else 0,
            is_default=1 if make_default else 0,
            last_verified_at=stored_at,
            last_probe_detail=_json.dumps(detail, ensure_ascii=False),
        )
        s.add(row)
        s.flush()
        if isinstance(detail.get("profile"), dict):
            detail["profile"]["environment_id"] = row.id
            row.last_probe_detail = _json.dumps(detail, ensure_ascii=False)
        s.commit()
        return row.id


# ------------------------------------------------------------------ #
# الحالة 1: HEALTHY + تحقق ناجح + أدلة كاملة + sandboxed=True
#           ← تُختار تحت STRICT_ISOLATED
# ------------------------------------------------------------------ #

def test_healthy_verified_isolated_selected_under_strict(env_db):
    from execution import policy as execution_policy
    from execution import service as execution_service

    env_id = _seed(env_db, status="HEALTHY", sandboxed=True,
                   make_default=True)
    selected = execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED"
    )
    assert selected is not None, (
        "بيئة HEALTHY متحققة معزولة رُفض تحت STRICT — شق PD-1 لم يُغلق"
    )
    assert selected["id"] == env_id
    assert execution_policy.environment_satisfies(
        selected, "STRICT_ISOLATED"
    )
    # بوابة الاختيار عبر policy.select_environment_for_policy نفسها
    via_policy = execution_policy.select_environment_for_policy(
        execution_service.list_environments(env_db), "STRICT_ISOLATED"
    )
    assert via_policy is not None and via_policy["id"] == env_id


# ------------------------------------------------------------------ #
# الحالة 2: HEALTHY + sandboxed=False ← تُرفض تحت STRICT_ISOLATED
# ------------------------------------------------------------------ #

def test_healthy_not_sandboxed_rejected_under_strict(env_db):
    from execution import service as execution_service

    _seed(env_db, status="HEALTHY", sandboxed=False, make_default=True)
    selected = execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED"
    )
    assert selected is None, (
        "بيئة سليمة غير معزولة قُبلت تحت عزل صارم — كذب سياسة"
    )
    # لا سقوط صامت: resolve_executor يعيد (None, None)
    environment, backend = execution_service.resolve_executor(
        env_db, policy="STRICT_ISOLATED"
    )
    assert environment is None and backend is None


# ------------------------------------------------------------------ #
# الحالة 3: تحقق لم يُجر / غياب last_verified_at / أدلة ناقصة
#           ← لا اختيار ولا جاهزية
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("seed_kwargs", [
    pytest.param({"status": "HEALTHY", "sandboxed": True,
                  "verified": None}, id="no-last_verified_at"),
    pytest.param({"status": "HEALTHY", "sandboxed": True,
                  "verified": "now", "checks": []}, id="no-checks"),
    pytest.param({"status": "HEALTHY", "sandboxed": True,
                  "verified": "now",
                  "checks": [{"name": "boot", "ok": True, "detail": ""},
                             {"name": "capture", "ok": False,
                              "detail": "فشل الالتقاط"}]},
                 id="failing-check"),
    pytest.param({"status": "READY", "sandboxed": True,
                  "verified": None, "checks": []},
                 id="legacy-ready-by-name-only"),
])
def test_missing_evidence_never_ready_or_selected(env_db, seed_kwargs):
    from execution import policy as execution_policy
    from execution import service as execution_service

    _seed(env_db, make_default=True, **seed_kwargs)
    assert execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED"
    ) is None, (
        "سجل بلا تحقق/بلا أدلة حصل على الجاهزية لمجرد اسمه — مخالفة §3-4"
    )
    assert not execution_policy.environment_satisfies(
        execution_service.list_environments(env_db)[0],
        "STRICT_ISOLATED",
    )


# ------------------------------------------------------------------ #
# الحالة 4: فحص فاشل / NOT_READY / UNAVAILABLE ← لا اختيار
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("status", ["NOT_READY", "UNAVAILABLE", "DETECTED"])
def test_failed_or_negative_status_never_selected(env_db, status):
    from execution import service as execution_service

    _seed(env_db, status=status, sandboxed=True, make_default=True)
    assert execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED"
    ) is None, f"حالة {status} قُبلت كبينئة تنفيذ"


# ------------------------------------------------------------------ #
# الحالة 5: سجل تاريخي READY بأدلة صالحة ← التوافق وفق العقد المعلن
# ------------------------------------------------------------------ #

def test_legacy_ready_with_valid_evidence_stays_compatible(env_db):
    from execution import service as execution_service

    env_id = _seed(env_db, status="READY", sandboxed=True,
                   make_default=True)
    selected = execution_service.select_environment(
        env_db, policy="STRICT_ISOLATED"
    )
    assert selected is not None and selected["id"] == env_id, (
        "READY تاريخي بأدلة صالحة بُطل ظلمًا — التوافق التاريخي مطلوب §3-4"
    )


# ------------------------------------------------------------------ #
# الحالة 6: COMPATIBLE_LOCAL مع بيئة غير معزولة ← مسموح وفق السياسة
#           دون أي وصف مضلل للعزل
# ------------------------------------------------------------------ #

def test_compatible_local_accepts_unisolated_without_isolation_claims(env_db):
    from execution import policy as execution_policy
    from execution import service as execution_service

    _seed(env_db, status="HEALTHY", sandboxed=False, make_default=True)
    selected = execution_service.select_environment(
        env_db, policy="COMPATIBLE_LOCAL"
    )
    assert selected is not None, (
        "COMPATIBLE_LOCAL رفض بيئة متحققة غير معزولة — السياسة تقبلها"
    )
    # لا ادعاء عزل: غير معزولة صراحة ولا وسم SANDBOXED عليها
    assert selected["isolation"] != "SANDBOXED"
    assert selected["sandboxed"] is False
    assert "بلا عزل" in execution_policy.policy_note("COMPATIBLE_LOCAL")
    assert not execution_policy.environment_satisfies(
        selected, "STRICT_ISOLATED"
    ), "البيئة نفسها قُبلت تحت السياستين المتضادتين"


# ------------------------------------------------------------------ #
# الحالة 7: بعد تحقق حقيقي ← runtime-state READY مع selected و
#           environment_id متطابقين (مسار الخدمة والحالة القانونية)
# ------------------------------------------------------------------ #

class VerifiedBackend:
    """خلفية تحقق مضبوطة — نفس عقد VerifyResult الحقيقي."""

    backend_kind = "STUB_VERIFIED"

    def __init__(self, sandboxed=True, ok=True):
        self.sandboxed = sandboxed
        self.ok = ok

    def describe(self):
        return {"os": "Linux", "architecture": "x86_64",
                "sandboxed": self.sandboxed, "available": self.ok}

    def verify(self):
        from execution.backends import VerifyResult

        # (013.11 §5) العقد الكامل لسلم العامل البعيد (7 فحوص) —
        # قائمة مختصرة لا يُتوقع منها READY خطأً
        checks = [
            {"name": n, "ok": self.ok,
             "detail": "" if self.ok else "فشل مضبوط"}
            for n in ("connectivity", "authentication", "heartbeat",
                      "environment_probe", "workspace_probe",
                      "execute_probe", "artifact_probe")
        ]
        return VerifyResult(
            ok=self.ok and self.sandboxed,
            status="READY" if (self.ok and self.sandboxed) else "NOT_READY",
            checks=checks,
            profile=self.describe(),
            reason="" if self.ok else "فشل مضبوط للاختبار",
        )

    def run_code(self, code, *, workspace, artifacts, timeout_s=120):
        from execution.backends import ExecutionOutcome

        return ExecutionOutcome(
            environment_id="stub", backend="STUB_VERIFIED",
            exit_code=0 if self.ok else -1,
            stdout="", stderr="",
            termination="COMPLETED" if self.ok else "FAILED_TO_START",
            detail="",
        )


def test_runtime_state_ready_after_real_verify(env_db, monkeypatch):
    from execution import runtime_state as runtime_state_mod
    from execution import service as execution_service

    env_id = execution_service.add_environment(
        env_db, name="worker-verified", backend="REMOTE_WORKER",
        endpoint="http://127.0.0.1:9666",
    )["id"]
    monkeypatch.setattr(
        execution_service, "build_backend",
        lambda env: VerifiedBackend(sandboxed=True),
    )
    verified = execution_service.verify_environment(env_db, env_id)
    assert verified["status"] == "HEALTHY"
    assert verified["last_verified_at"]

    canonical = runtime_state_mod.canonical_state(
        env_db, "STRICT_ISOLATED"
    )
    assert canonical["state"] == "READY", (
        "بعد تحقق ناجح بقي runtime-state محجوبًا — شق 013.9 PD-1"
    )
    assert canonical["selected"] is not None
    assert canonical["environment_id"] == env_id
    assert canonical["selected"]["id"] == env_id
    assert canonical["evidence"]["checks_ok"] is True


def test_runtime_state_blocked_without_eligible_env_no_fallback(
        env_db, monkeypatch):
    from execution import runtime_state as runtime_state_mod
    from execution import service as execution_service

    env_id = execution_service.add_environment(
        env_db, name="worker-unisolated", backend="REMOTE_WORKER",
        endpoint="http://127.0.0.1:9555",
    )["id"]
    monkeypatch.setattr(
        execution_service, "build_backend",
        lambda env: VerifiedBackend(sandboxed=False),
    )
    execution_service.verify_environment(env_db, env_id)

    canonical = runtime_state_mod.canonical_state(
        env_db, "STRICT_ISOLATED"
    )
    assert canonical["state"] != "READY"
    assert canonical["selected"] is None
    assert canonical["environment_id"] is None
    # سبب حجب قابل للفحص — لا صمت
    assert canonical["coherent"]["detail"] or canonical["missing"]
    # لا سقوط إلى غير المعزولة تحت الصارمة
    environment, backend = execution_service.resolve_executor(
        env_db, policy="STRICT_ISOLATED"
    )
    assert environment is None and backend is None


# ------------------------------------------------------------------ #
# اتساق الحالة المعروضة (§3-5): اسم الحالة يطابق الأهلية دائمًا —
# لا ELIGIBLE وeligible=false (التناقض الذي وضعه المالك)
# ------------------------------------------------------------------ #

def test_compute_state_name_agrees_with_eligible(env_db):
    from execution import policy as execution_policy
    from execution import service as execution_service

    cases = [
        # (status, sandboxed, verified, policy, expected_state)
        ("HEALTHY", True, "now", "STRICT_ISOLATED", "READY"),
        ("READY", True, "now", "STRICT_ISOLATED", "READY"),  # توافق تاريخي
        ("HEALTHY", False, "now", "STRICT_ISOLATED", "HEALTHY"),
        ("HEALTHY", True, None, "STRICT_ISOLATED", "HEALTHY"),
        ("DETECTED", True, "now", "STRICT_ISOLATED", "DETECTED"),
        ("ONLINE", True, None, "STRICT_ISOLATED", "ONLINE"),
        ("NOT_READY", True, "now", "STRICT_ISOLATED", "NOT_READY"),
        ("UNAVAILABLE", True, None, "STRICT_ISOLATED", "UNAVAILABLE"),
        ("HEALTHY", False, "now", "COMPATIBLE_LOCAL", "READY"),
        ("DETECTED", False, None, "COMPATIBLE_LOCAL", "DETECTED"),
    ]
    for status, sandboxed, verified, policy, expected in cases:
        # (013.11) أدلة كاملة العقد عندما يُبذر تحقق — لا فحص واحد
        full_detail = execution_policy.valid_evidence(
            "REMOTE_WORKER", sandboxed, environment_id=1)
        full_detail["last_verified_at"] = (
            _now().isoformat() if verified == "now" else None
        )
        env = {
            "id": 1, "name": "x", "backend": "REMOTE_WORKER",
            "status": status, "sandboxed": sandboxed,
            "isolation": "SANDBOXED" if sandboxed else "NONE",
            "last_verified_at": (
                _now().isoformat() if verified == "now" else None
            ),
            "last_probe_detail": full_detail if verified else {},
            "failure_reason": "",
        }
        state = execution_service.compute_environment_state(env, policy)
        assert state["state"] == expected, (
            f"({status}, sandboxed={sandboxed}, verified={verified}, "
            f"{policy}) ← {state['state']} لا {expected}"
        )
        # العقد الصارم: state=="READY" ⇔ eligible ∧ جاهزية حقيقية
        assert (state["state"] == "READY") == state["ready"]
        assert state["state"] != "ELIGIBLE", (
            "اسم ELIGIBLE مع أي حالة — التوحي بالأهلية ممنوع §3-5"
        )
        if state["state"] == "READY":
            assert state["eligible"] is True
        if not state["eligible"] and status in ("HEALTHY", "READY"):
            assert state["ineligible_reason"], (
                "عدم أهلية بلا سبب حرفي قابل للفحص"
            )


# ------------------------------------------------------------------ #
# مسار التجهيز (provisioner): environment_satisfies على نتيجة التحقق
# الحقيقية — الخطوة التي كانت تُعلن UNAVAILABLE لبيئة متحققة معزولة
# ------------------------------------------------------------------ #

def test_provisioner_gate_passes_for_verified_isolated_env(
        env_db, monkeypatch):
    from execution import service as execution_service

    env_id = execution_service.add_environment(
        env_db, name="worker-prov", backend="REMOTE_WORKER",
        endpoint="http://127.0.0.1:9444",
    )["id"]
    monkeypatch.setattr(
        execution_service, "build_backend",
        lambda env: VerifiedBackend(sandboxed=True),
    )
    verified_full = execution_service.verify_environment(env_db, env_id)
    # نفس النداء الحرفي في provisioner (VERIFYING_ISOLATION)
    from execution import policy as execution_policy

    assert execution_policy.environment_satisfies(
        verified_full, "STRICT_ISOLATED"
    ), "خطوة VERIFYING_ISOLATION تحجب بيئة متحققة معزولة — شق PD-1"


# ------------------------------------------------------------------ #
# الحالة 8 المكمّلة: POLICY_BLOCK بالمتطلب الحرفي عند غياب المؤهلة
# ------------------------------------------------------------------ #

def test_run_code_unified_policy_block_literal_requirement(env_db, tmp_path):
    from execution import service as execution_service

    _seed(env_db, status="HEALTHY", sandboxed=False, make_default=True)
    outcome = execution_service.run_code_unified(
        env_db, "print('x')", workspace=tmp_path / "ws",
        artifacts=tmp_path, policy="STRICT_ISOLATED",
    )
    assert outcome.termination == "POLICY_BLOCK"
    assert "STRICT_ISOLATED" in outcome.detail
    assert outcome.environment_id == "none"
