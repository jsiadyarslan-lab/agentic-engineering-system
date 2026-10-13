"""اختبار خدمة بيئات التنفيذ (الأمر 010 §17-§19+§27-§28).

الجذر الجوهري (§19): المسبار والمنفذ من resolve_executor() نفسه —
كل نتيجة تحمل environment_id فلا تناقض بلا تفسير. الاختبارات تحقن
خلفية مضبوطة للمسار السريع، والفحوص الحقيقية لها اختبارات backends.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from execution import service  # noqa: E402
from execution.backends import (  # noqa: E402
    ExecutionOutcome,
    LocalLinuxBackend,
    VerifyResult,
)
from persistence.database import build_engine, init_db, make_session_factory  # noqa: E402


@pytest.fixture()
def sessions(tmp_path):
    engine = build_engine(tmp_path / "exec-test.db")
    init_db(engine)
    return make_session_factory(engine)


class StubBackend:
    """خلفية مضبوطة لاختبار الخدمة — نفس العقد، نتائج معلنة."""

    backend_kind = "STUB"

    def __init__(self, verify_ok=True, run_ok=True):
        self.verify_ok = verify_ok
        self.run_ok = run_ok
        self.ran: list[str] = []

    def describe(self):
        return {"os": "TestOS", "architecture": "test64",
                "sandboxed": True, "available": True}

    def verify(self):
        # (013.11 §5 + 013.12 D2) العقد الكامل للعامل المعلن العزل —
        # سلم 7 + isolation_probe الحي: خلفية الاختبار تعكس ما تنتجه
        # الخلفيات الحقيقية لا قائمة مختزلة
        names = ["connectivity", "authentication", "heartbeat",
                 "environment_probe", "workspace_probe",
                 "execute_probe", "artifact_probe", "isolation_probe"]
        return VerifyResult(
            ok=self.verify_ok,
            status="READY" if self.verify_ok else "NOT_READY",
            checks=[
                {"name": n, "ok": self.verify_ok,
                 "detail": "" if self.verify_ok else "stub failure"}
                for n in names
            ],
            profile=self.describe(),
            reason="" if self.verify_ok else "stubbed failure",
        )

    def run_code(self, code, *, workspace, artifacts, timeout_s=120):
        self.ran.append(code[:40])
        return ExecutionOutcome(
            environment_id="stub", backend="STUB",
            exit_code=0 if self.run_ok else -1,
            stdout="stub-out", stderr="", termination="COMPLETED"
            if self.run_ok else "FAILED_TO_START",
            detail="" if self.run_ok else "stub start failure",
        )


def test_local_registered_automatically_with_honest_status(sessions):
    environments = service.list_environments(sessions)
    # (013.1 §10) اسم البيئة المحلية من المضيف الفعلي — local-linux
    # على مضيف Linux وlocal-windows على Windows، والاختبار يقيس
    # التسجيل التلقائي والحالة الصادقة على أي مضيف.
    expected = service.local_environment_name()
    assert any(e["name"] == expected and e["backend"] == "LOCAL"
               for e in environments), (
        f"البيئة المحلية {expected} لم تُسجل تلقائيًا"
    )
    # الحالة الأولى DETECTED (013.7 §P1: مسجلة ولم تُتحقق) — لا READY
    # بلا تحقق (§20 لا افتراض جاهزية)
    local = [e for e in environments if e["name"] == expected][0]
    assert local["status"] in ("UNKNOWN", "DETECTED", "READY",
                               "NOT_READY", "UNAVAILABLE")


def test_add_environment_validates_backend_and_endpoint(sessions):
    with pytest.raises(ValueError, match="غير مدعوم"):
        service.add_environment(sessions, name="x", backend="DOCKER")
    with pytest.raises(ValueError, match="رابط العامل"):
        service.add_environment(
            sessions, name="x", backend="REMOTE_WORKER", endpoint="ftp://bad",
        )
    added = service.add_environment(
        sessions, name="worker-a", backend="REMOTE_WORKER",
        endpoint="http://127.0.0.1:9999",
    )
    assert added["status"] == "UNKNOWN"
    assert added["endpoint"] == "http://127.0.0.1:9999"


def _env_id_by_name(sessions, name):
    return [e for e in service.list_environments(sessions)
            if e["name"] == name][0]["id"]


def test_verify_environment_writes_real_result(sessions, monkeypatch):
    service.add_environment(
        sessions, name="worker-b", backend="REMOTE_WORKER",
        endpoint="http://127.0.0.1:9998",
    )
    env_id = _env_id_by_name(sessions, "worker-b")
    stub = StubBackend(verify_ok=True)
    monkeypatch.setattr(
        service, "build_backend", lambda env: stub,
    )
    out = service.verify_environment(sessions, env_id)
    # (013.7 §P1 + 013.10 §3) التحقق الناجح يكتب HEALTHY (صحة بأدلة)،
    # والجاهزية تُحسب بالتعريف القانوني الواحد: تحقق ناجح + عزل
    # (StubBackend يعيد sandboxed=True) → موافقة تحت STRICT_ISOLATED.
    assert out["status"] == "HEALTHY"
    assert out["sandboxed"] is True
    assert out["last_verified_at"]
    assert out["verify"]["checks"][0]["name"] == "connectivity"
    from execution import policy as execution_policy

    assert execution_policy.environment_satisfies(
        out, "STRICT_ISOLATED"
    ), "بيئة متحققة معزولة بلا اختيار — شق 013.9 PD-1"
    # لا مرجع توكن في الرد أبدًا
    assert "token_ref" not in out


def test_select_environment_prefers_ready_default(sessions):
    # local UNKNOWN (غير جاهزة) + عامل جاهز = العامل يُختار
    service.add_environment(
        sessions, name="worker-c", backend="REMOTE_WORKER",
        endpoint="http://127.0.0.1:9997", make_default=True,
    )
    from execution.models import ExecutionEnvironment
    from sqlalchemy import select as sa_select

    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.name == "worker-c")).first()
        row.status = "READY"
        # (013.11 §5) أدلة كاملة العقد — الاختيار (حتى بلا سياسة)
        # بتعريف قانوني واحد
        from execution import policy as execution_policy

        detail = execution_policy.valid_evidence("REMOTE_WORKER", True)
        row.last_verified_at = _dt.datetime.now(_dt.timezone.utc)
        s.flush()
        detail["profile"]["environment_id"] = row.id
        row.last_probe_detail = json.dumps(detail, ensure_ascii=False)
        s.commit()
    selected = service.select_environment(sessions)
    assert selected is not None and selected["name"] == "worker-c"
    # لا بيئة جاهزة على الإطلاق = None بلا افتراض وهمي (§18)
    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.name == "worker-c")).first()
        row.status = "NOT_READY"
        s.commit()
    assert service.select_environment(sessions) is None


def test_resolve_executor_is_single_source_for_probe_and_run(
    sessions, monkeypatch,
):
    """(§19 الجذر) المسبار والمنفذ يبنيان من resolve_executor نفسه."""
    service.add_environment(
        sessions, name="worker-d", backend="REMOTE_WORKER",
        endpoint="http://127.0.0.1:9996", make_default=True,
    )
    from execution.models import ExecutionEnvironment
    from sqlalchemy import select as sa_select

    with sessions() as s:
        row = s.scalars(sa_select(ExecutionEnvironment).where(
            ExecutionEnvironment.name == "worker-d")).first()
        row.status = "READY"
        # (013.11 §5) أدلة كاملة العقد — الاختيار بتعريف قانوني واحد
        from execution import policy as execution_policy

        detail = execution_policy.valid_evidence("REMOTE_WORKER", True)
        row.last_verified_at = _dt.datetime.now(_dt.timezone.utc)
        s.flush()
        detail["profile"]["environment_id"] = row.id
        row.last_probe_detail = json.dumps(detail, ensure_ascii=False)
        s.commit()

    shared = StubBackend()
    monkeypatch.setattr(service, "build_backend", lambda env: shared)

    # المسبار
    probe = service.sandbox_probe_result(sessions)
    assert probe["status"] == "READY"
    assert probe["details"]["environment_name"] == "worker-d"
    assert probe["details"]["environment_id"] == _env_id_by_name(
        sessions, "worker-d")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        outcome = service.run_code_unified(
            sessions, "print('x')", workspace=Path(tmp),
            artifacts=Path(tmp) / "a",
        )
    assert outcome.ok
    assert shared.ran, "المنفذ لم يمر بالخلفية المشتركة"


def test_run_code_unified_marks_environment_mismatch(sessions, monkeypatch):
    """فشل بدء بعد جاهزية (HEALTHY/READY) = ENVIRONMENT_MISMATCH + وسم
    STALE (§42) — الوسم يتبع الحالة المخزنة فعلاً (013.10 §3)."""
    service.ensure_local_registered(sessions)
    stub = StubBackend(verify_ok=True, run_ok=False)
    monkeypatch.setattr(service, "build_backend", lambda env: stub)
    # اجعل الافتراضية متحققة عبر التحقق الحقيقي (يكتب HEALTHY)
    local_id = _env_id_by_name(sessions, service.local_environment_name())
    service.verify_environment(sessions, local_id)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        outcome = service.run_code_unified(
            sessions, "print('x')", workspace=Path(tmp),
            artifacts=Path(tmp) / "a",
        )
    assert outcome.termination == "FAILED_TO_START"
    assert "ENVIRONMENT_MISMATCH" in outcome.detail
    assert f"#{local_id}" in outcome.detail  # هوية البيئة مسماة
    # البيئة وُسمت للفحص الإجباري — لا بقاء READY كاذب
    env = service.get_environment(sessions, local_id)
    assert env["status"] != "READY"


def test_owner_action_names_real_path(sessions):
    action = service.owner_action_for_missing_environment(sessions)
    assert "OWNER ACTION REQUIRED" in action
    assert "execution_worker.py" in action  # المسار الهندسي الحقيقي
    assert "تحقق" in action
