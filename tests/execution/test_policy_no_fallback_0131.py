"""اختبارات العزل الصارم بلا تراجع صامت (013.1 §13+§10).

العقد الحرفي من الأمر:
- STRICT_ISOLATED بلا بيئة معزولة جاهزة = POLICY_BLOCK معلن —
  لا تنفيذ محلي غير معزول بدلًا عنها مهما كانت الظروف.
- resolve_executor(policy) لا يسقط إلى البيئة الافتراضية أبدًا.
- المضيف ≠ بيئة التنفيذ: local-windows لا تُعرض معزولة أبدًا،
  والعزل يتبع توفر الركيزة الفعلي لا اسم البيئة.
- COMPATIBLE_LOCAL يقبل غير المعزولة بلا ادعاء عزل (معلن).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


@pytest.fixture()
def env_db(tmp_path, monkeypatch):
    """قاعدة معزولة + بذر مزودين — نمط اختبارات التنفيذ.

    seam العزل (نمط 011 المعتمد): على مضيف Linux فيه ركيزة فعلية
    يصحح ensure_local_registered عزل البيئة المحلية ليتبع الحقيقة
    (sandboxed=1) — وهذا صدق لا نخونه. اختبار «بيئة جاهزة بلا عزل»
    يحتاج مضيفًا بلا ركيزة، فنحقن ذلك عبر الخطاف الحتمي المعتمد.
    """
    from persistence.database import (
        build_engine, init_db, make_session_factory,
    )
    from providers_registry import registry
    from execution import service as execution_service

    monkeypatch.chdir(tmp_path)
    engine = build_engine(tmp_path / "policy-0131.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    registry.ensure_seeded(sessions)
    monkeypatch.setattr(execution_service, "_substrate_available",
                        lambda: False)
    return sessions


def _set_local_env(sessions, *, status, sandboxed):
    """ضبط صف البيئة المحلية — الحتمية عبر المنصات."""
    import sqlalchemy as sa

    from execution import service as execution_service
    from execution.models import ExecutionEnvironment

    execution_service.ensure_local_registered(sessions)
    with sessions() as s:
        row = s.scalars(sa.select(ExecutionEnvironment).where(
            ExecutionEnvironment.name.in_(("local-linux",
                                           "local-windows")))).first()
        row.status = status
        row.sandboxed = sandboxed
        s.commit()
        return row.id


# ------------------------------------------------------------------ #
# §13 — لا تراجع صامت تحت سياسة أبدًا
# ------------------------------------------------------------------ #

def test_resolve_executor_strict_never_falls_back(env_db):
    """STRICT + بيئة جاهزة غير معزولة = (None, None) — لا سقوط
    إلى الافتراضية: الحجب معلن لا تنفيذ بأدنى سقف."""
    from execution import service as execution_service

    _set_local_env(env_db, status="READY", sandboxed=0)
    environment, backend = execution_service.resolve_executor(
        env_db, policy="STRICT_ISOLATED"
    )
    assert environment is None and backend is None, (
        "resolve_executor سقط إلى بيئة غير معزولة تحت STRICT — "
        "تراجع صامت ممنوع (013.1 §13)"
    )


def test_resolve_executor_strict_uses_sandboxed(env_db, monkeypatch):
    """STRICT + بيئة معزولة جاهزة = تُختار هي حصرًا.

    الركيزة هنا حقيقية (seam معكوس): هذا المضيف Linux فيه ركيزة
    فعلية فتُسجل البيئة معزولة صدقًا وتُختار تحت السياسة الصارمة."""
    from execution import service as execution_service

    monkeypatch.setattr(execution_service, "_substrate_available",
                        lambda: True)
    _set_local_env(env_db, status="READY", sandboxed=1)
    environment, backend = execution_service.resolve_executor(
        env_db, policy="STRICT_ISOLATED"
    )
    assert environment is not None and backend is not None
    assert environment["sandboxed"] is True or environment["sandboxed"] == 1


def test_resolve_executor_without_policy_keeps_history(env_db):
    """بلا سياسة (المسار العام التاريخي): الافتراضية بوضعها الفعلي —
    سلوك الأدوات العامة لا يتغير؛ الحجب حكر على السياسة الصريحة."""
    from execution import service as execution_service

    _set_local_env(env_db, status="READY", sandboxed=0)
    environment, backend = execution_service.resolve_executor(env_db)
    assert environment is not None, "المسار العام فقد البيئة الافتراضية"


def test_run_code_unified_strict_blocks_with_requirement(
        env_db, tmp_path):
    """STRICT بلا بيئة موافقة = POLICY_BLOCK بالمتطلب الحرفي —
    التنفيذ يحجب نفسه بدل التنفيذ غير المعزول."""
    from execution import service as execution_service

    _set_local_env(env_db, status="READY", sandboxed=0)
    outcome = execution_service.run_code_unified(
        env_db, "print('x')", workspace=tmp_path / "ws",
        artifacts=tmp_path, policy="STRICT_ISOLATED",
    )
    assert outcome.termination == "POLICY_BLOCK"
    assert "STRICT_ISOLATED" in outcome.detail
    assert "المطلوب" in outcome.detail or "بيئة" in outcome.detail
    assert outcome.exit_code != 0


def test_run_code_unified_compatible_accepts_unisolated(
        env_db, tmp_path):
    """COMPATIBLE_LOCAL + بيئة غير معزولة جاهزة = تنفيذ معلن
    بلا عزل — لا حجب ولا ادعاء عزل."""
    from execution import service as execution_service

    _set_local_env(env_db, status="READY", sandboxed=0)
    environment, backend = execution_service.resolve_executor(
        env_db, policy="COMPATIBLE_LOCAL"
    )
    assert environment is not None, (
        "COMPATIBLE_LOCAL رفض بيئة جاهزة غير معزولة — السياسة تقبلها"
    )


def test_tool_substrate_honors_policy_context(env_db, tmp_path):
    """أدوات الخطوات تمر بسياسة المشروع (ToolContext.execution_policy):
    STRICT بلا بيئة = ToolFailure POLICY_BLOCK غير قابل لإعادة
    المحاولة داخل الخطوة."""
    from roles.tools import ToolContext, ToolFailure, write_file

    _set_local_env(env_db, status="READY", sandboxed=0)
    ctx = ToolContext(grant_root=tmp_path / "grant",
                      sessions=env_db,
                      execution_policy="STRICT_ISOLATED")
    with pytest.raises(ToolFailure) as excinfo:
        write_file(ctx, "x.md", "# محتوى")
    failure = excinfo.value
    assert failure.failure_class == "POLICY_BLOCK"
    assert failure.reason == "NO_POLICY_ENVIRONMENT"
    assert failure.retryable is False


def test_sandbox_probe_strict_honest_when_missing(env_db):
    """مسبار sandbox تحت STRICT بلا بيئة موافقة = UNAVAILABLE بسبب
    السياسة والمتطلب — لا مسبار على بيئة أدنى سقفًا."""
    from execution import service as execution_service

    _set_local_env(env_db, status="READY", sandboxed=0)
    result = execution_service.sandbox_probe_result(
        env_db, policy="STRICT_ISOLATED"
    )
    assert result["status"] == "UNAVAILABLE"
    assert "STRICT_ISOLATED" in result["reason"]


# ------------------------------------------------------------------ #
# §10 — المضيف ≠ بيئة التنفيذ
# ------------------------------------------------------------------ #

def test_local_environment_identity_follows_host(env_db, monkeypatch):
    """مضيف Windows يسجل local-windows بعزل NONE — لا local-linux
    كاذبة أبدًا؛ الهوية من المضيف الفعلي (011 §4 محفوظ + 013.1 §10).

    ملاحظة seam: backends.runtime_truth هنا يُحقن على service
    لا على backends — ensure_local_registered يقرأه من هناك."""
    from execution import backends, service as execution_service

    monkeypatch.setattr(execution_service, "runtime_truth",
                        lambda: {"os": "Windows", "architecture": "AMD64",
                                 "container_runtime": "", "cpu_cores": 8})
    monkeypatch.setattr(execution_service, "host_platform_label",
                        lambda *a, **k: "Windows AMD64")
    monkeypatch.setattr(execution_service, "local_environment_name",
                        lambda: "local-windows")
    monkeypatch.setattr(execution_service, "_substrate_available",
                        lambda: False)
    execution_service.ensure_local_registered(env_db)
    from execution.models import ExecutionEnvironment
    import sqlalchemy as sa

    with env_db() as s:
        row = s.scalars(sa.select(ExecutionEnvironment).where(
            ExecutionEnvironment.name == "local-windows")).first()
        assert row is not None, "مضيف Windows لم يسجل local-windows"
        assert row.sandboxed == 0, "local-windows معزولة؟! كذب §10"
