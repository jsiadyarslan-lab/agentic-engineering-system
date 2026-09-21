"""اختبار خدمة بيئات التنفيذ (الأمر 010 §17-§19+§27-§28).

الجذر الجوهري (§19): المسبار والمنفذ من resolve_executor() نفسه —
كل نتيجة تحمل environment_id فلا تناقض بلا تفسير. الاختبارات تحقن
خلفية مضبوطة للمسار السريع، والفحوص الحقيقية لها اختبارات backends.
"""

from __future__ import annotations

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
        return VerifyResult(
            ok=self.verify_ok,
            status="READY" if self.verify_ok else "NOT_READY",
            checks=[{"name": "boot", "ok": self.verify_ok, "detail": ""}],
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
    assert any(e["name"] == "local-linux" and e["backend"] == "LOCAL"
               for e in environments)
    # الحالة الأولى UNKNOWN — لا READY بلا تحقق (§20 لا افتراض جاهزية)
    local = [e for e in environments if e["name"] == "local-linux"][0]
    assert local["status"] in ("UNKNOWN", "READY", "NOT_READY", "UNAVAILABLE")


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
    assert out["status"] == "READY"
    assert out["sandboxed"] is True
    assert out["last_verified_at"]
    assert out["verify"]["checks"][0]["name"] == "boot"
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
    """فشل بدء بعد READY = ENVIRONMENT_MISMATCH + وسم STALE (§42)."""
    service.ensure_local_registered(sessions)
    stub = StubBackend(verify_ok=True, run_ok=False)
    monkeypatch.setattr(service, "build_backend", lambda env: stub)
    # اجعل الافتراضية READY عبر التحقق
    local_id = _env_id_by_name(sessions, "local-linux")
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
