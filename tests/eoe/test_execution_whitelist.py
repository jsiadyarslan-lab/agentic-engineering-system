"""§10.5 — test_execution_whitelist: أمر خارج القائمة = HARD STOP قبل التنفيذ."""
from __future__ import annotations

import pytest

from eoe.execution_engine import (
    ExecutionEngine,
    ExecutionHardStop,
    IsolationLevel,
    SectionExecutionPlan,
)


def _engine(sandbox_manager, tmp_path, whitelist=("python",)):
    from eoe.access_gateway import AccessAdmission, AccessLedger, GrantorService

    grantor = GrantorService(b"wl-key")
    ledger = AccessLedger()
    admission = AccessAdmission(ledger, grantor)
    return ExecutionEngine(
        sandbox_manager, admission,
        command_whitelist=tuple(whitelist), work_base=str(tmp_path / "wl"),
    )


def test_command_outside_whitelist_stops_before_execution(
    sandbox_manager, tmp_path
):
    """bash خارج قائمة python = HARD STOP قبل أي ركيزة."""
    engine = _engine(sandbox_manager, tmp_path)
    plan = SectionExecutionPlan(
        section_number=1,
        commands=(("bash", "-c", "echo pwned"),),
        isolation=IsolationLevel.FULL_ISOLATION,
    )
    with pytest.raises(ExecutionHardStop) as excinfo:
        engine.run_section(plan)
    assert "خارج القائمة البيضاء" in str(excinfo.value)
    # ولم يُنفَّذ شيء أصلًا — لا سجلات تنفيذ
    assert engine.executions == []


def test_empty_command_rejected(sandbox_manager, tmp_path):
    """أمر فارغ = رفض قبل التنفيذ."""
    engine = _engine(sandbox_manager, tmp_path)
    with pytest.raises(ExecutionHardStop):
        engine.run_section(
            SectionExecutionPlan(
                section_number=1, commands=((),),
                isolation=IsolationLevel.FULL_ISOLATION,
            )
        )


def test_whitelisted_command_executes_in_sandbox(sandbox_manager, tmp_path):
    """python داخل القائمة = ينفَّذ داخل الركيزة بمخرج حقيقي."""
    engine = _engine(sandbox_manager, tmp_path)
    plan = SectionExecutionPlan(
        section_number=2,
        commands=(("python", "-c", "print('wl-ok')"),),
        isolation=IsolationLevel.FULL_ISOLATION,
    )
    outcomes = engine.run_section(plan)
    assert len(outcomes) == 1
    assert outcomes[0].executed is True
    assert outcomes[0].exit_code == 0
    assert "wl-ok" in outcomes[0].stdout
    assert outcomes[0].duration_ms >= 0


def test_engine_never_runs_host_subprocess_for_order_commands(
    sandbox_manager, tmp_path, monkeypatch
):
    """أوامر الأقسام لا تمر عبر subprocess المضيف إطلاقًا — كل شيء
    عبر الركيزة (الفرق الجوهري عن v1، مفروض بنيويًا)."""
    import subprocess as real_subprocess

    engine = _engine(sandbox_manager, tmp_path)
    calls: list[tuple] = []
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: calls.append(a) or real_subprocess.run(*a, **k)
    )
    plan = SectionExecutionPlan(
        section_number=3,
        commands=(("python", "-c", "print('isolation-proof')"),),
        isolation=IsolationLevel.FULL_ISOLATION,
    )
    engine.run_section(plan)
    # لا استدعاء subprocess واحد من محرك التنفيذ (البصمات في proofs
    # تستدعي git خارج هذا النطاق — هنا نفحص مسار التنفيذ وحده)
    assert calls == [] or all(
        "python" not in str(a[0][:2]) or "isolation-proof" not in str(a)
        for a in calls
    )
