"""§10.6-§10.7 — test_push_requires_signature + test_push_replay_blocked.

محرك الدفع على مستودعات حقيقية: دفع بلا موافقة = رفض؛ بموافقة موقعة =
نجاح بشهادة؛ إعادة استخدام nonce = رفض (أحادية الاستخدام).
"""
from __future__ import annotations

import pytest


from eoe.access_gateway import AccessAdmission, AccessLedger, GrantorService
from eoe.order_parser import AccessRequest, GrantKind
from eoe.push_engine import (
    NonceLedger,
    OwnerApprovalService,
    PushEngine,
    PushRejected,
)


def _push_stack(sandbox_manager, tmp_path, repo_factory, *, grant_root=None):
    """مستودع حقيقي + bare remote + محرك دفع مكتمل التجهيز."""
    repo = repo_factory(
        "repo",
        files={"README.md": "content v1\n", "docs/note.txt": "note\n"},
        remote=tmp_path / "remote.git",
    )
    # منحة كتابة على جذر المستودع كله (نطاق التزام الاختبار)
    grant_root = grant_root or str(repo)
    grantor = GrantorService(b"push-key")
    ledger = AccessLedger()
    admission = AccessAdmission(ledger, grantor)
    ledger.register(
        grantor.approve(
            grantor.propose(
                AccessRequest(
                    kind=GrantKind.PATH_GRANT, scope="read_write",
                    target=grant_root,
                )
            )
        )
    )
    approvals = OwnerApprovalService(b"push-approval-key")
    engine = PushEngine(
        sandbox_manager, approvals, NonceLedger(), admission,
        work_base=str(tmp_path / "pushwork"),
    )
    return repo, engine, approvals


def _modify(repo) -> None:
    (repo / "docs" / "note.txt").write_text("note v2 — by EOE\n", encoding="utf-8")


def test_push_without_signature_rejected(sandbox_manager, tmp_path, repo_factory):
    """بلا موافقة موقعة = رفض قبل أي دفع — والremote لا يتغير."""
    repo, engine, _approvals = _push_stack(sandbox_manager, tmp_path, repo_factory)
    _modify(repo)
    with pytest.raises(PushRejected) as excinfo:
        engine.push(
            repo_root=str(repo), branch="main",
            commit_message="v2", scope_paths=(str(repo),),
            approval=None, remote_url=str(tmp_path / "remote.git"),
        )
    assert "بلا موافقة" in str(excinfo.value)
    # الremote بقي على الالتزام الأول
    import subprocess

    remote_head = subprocess.run(
        ["git", "-C", str(tmp_path / "remote.git"), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    local_first = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.split()[0]
    assert remote_head == local_first


def test_push_with_signed_approval_succeeds_with_certificates(
    sandbox_manager, tmp_path, repo_factory
):
    """موافقة موقعة صحيحة = دفع ناجح + سجل sha قبل/بعد + شهادة غياب."""
    repo, engine, approvals = _push_stack(sandbox_manager, tmp_path, repo_factory)
    _modify(repo)
    import subprocess

    before = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    # الالتزام داخل العزل يعطي sha نوقّع عليه
    commit_sha, staged = engine.commit_in_sandbox(
        str(repo), "v2 by EOE", (str(repo),)
    )
    digest, files = engine.verify_before_push(staged, before, (str(repo),), repo_root=str(repo))
    approval = approvals.sign(
        repository=str(repo), branch="main",
        commit_sha=commit_sha, files_digest=digest,
    )
    record = engine.push(
        repo_root=str(repo), branch="main", commit_message="v2 by EOE",
        scope_paths=(str(repo),), approval=approval,
        remote_url=str(tmp_path / "remote.git"),
        staged=staged, commit_sha=commit_sha,
    )
    assert record.pushed is True
    assert record.before_sha == before
    assert record.after_sha == commit_sha
    assert "docs/note.txt" in record.files
    # بلا فشل لا شهادة استرجاع (NONE)
    assert record.rollback_certificate == {}
    # الremote تقدم فعلًا إلى الالتزام الجديد
    remote_head = subprocess.run(
        ["git", "-C", str(tmp_path / "remote.git"), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert remote_head == commit_sha


def test_push_replay_blocked_nonce_single_use(sandbox_manager, tmp_path, repo_factory):
    """إعادة استخدام nonce الموافقة = رفض — أحادية الاستخدام مفروضة."""
    repo, engine, approvals = _push_stack(sandbox_manager, tmp_path, repo_factory)
    # دفعة أولى ناجحة
    _modify(repo)
    import subprocess

    before = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    commit_sha, staged = engine.commit_in_sandbox(
        str(repo), "v2", (str(repo),)
    )
    digest, files = engine.verify_before_push(staged, before, (str(repo),), repo_root=str(repo))
    approval = approvals.sign(
        repository=str(repo), branch="main",
        commit_sha=commit_sha, files_digest=digest,
    )
    record = engine.push(
        repo_root=str(repo), branch="main", commit_message="v2",
        scope_paths=(str(repo),), approval=approval,
        remote_url=str(tmp_path / "remote.git"),
        staged=staged, commit_sha=commit_sha,
    )
    assert record.pushed is True
    # المحاولة الثانية بنفس الموافقة (نفس nonce وsha) = رفض إعادة التشغيل
    with pytest.raises(PushRejected) as excinfo:
        engine.push(
            repo_root=str(repo), branch="main", commit_message="v2",
            scope_paths=(str(repo),), approval=approval,
            remote_url=str(tmp_path / "remote.git"),
            staged=staged, commit_sha=commit_sha,
        )
    assert "إعادة تشغيل" in str(excinfo.value) or "nonce" in str(excinfo.value)


def test_nonce_ledger_single_use_unit():
    """دفتر nonces: الاستهلاك الأول ينجح والثاني يفشل — بنيويًا."""
    ledger = NonceLedger()
    assert ledger.consume("n-1") is True
    assert ledger.consume("n-1") is False
    assert ledger.consume("n-2") is True
    assert ledger.consume("") is False


def test_tampered_approval_signature_rejected(sandbox_manager, tmp_path, repo_factory):
    """موافقة بتوقيع مزور (مفتاح آخر) = رفض."""
    repo, engine, approvals = _push_stack(sandbox_manager, tmp_path, repo_factory)
    _modify(repo)
    import subprocess

    before = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    commit_sha, staged = engine.commit_in_sandbox(
        str(repo), "v2", (str(repo),)
    )
    digest, files = engine.verify_before_push(staged, before, (str(repo),), repo_root=str(repo))
    forger = OwnerApprovalService(b"attacker-key")
    forged = forger.sign(
        repository=str(repo), branch="main",
        commit_sha=commit_sha, files_digest=digest,
    )
    with pytest.raises(PushRejected) as excinfo:
        engine.push(
            repo_root=str(repo), branch="main", commit_message="v2",
            scope_paths=(str(repo),), approval=forged,
            remote_url=str(tmp_path / "remote.git"),
            staged=staged, commit_sha=commit_sha,
        )
    assert "توقيع" in str(excinfo.value)


def test_rollback_certificate_on_push_failure(sandbox_manager, tmp_path, repo_factory):
    """فشل الدفع = استرجاع تلقائي بشهادة قابلة للفحص."""
    repo, engine, approvals = _push_stack(sandbox_manager, tmp_path, repo_factory)
    _modify(repo)
    import subprocess

    before = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    commit_sha, staged = engine.commit_in_sandbox(
        str(repo), "v2", (str(repo),)
    )
    digest, files = engine.verify_before_push(staged, before, (str(repo),), repo_root=str(repo))
    approval = approvals.sign(
        repository=str(repo), branch="main",
        commit_sha=commit_sha, files_digest=digest,
    )
    # remote غير موجود = الدفع يفشل منتصف الطريق
    record = engine.push(
        repo_root=str(repo), branch="main", commit_message="v2",
        scope_paths=(str(repo),), approval=approval,
        remote_url=str(tmp_path / "nonexistent-remote.git"),
        staged=staged, commit_sha=commit_sha,
    )
    assert record.pushed is False
    cert = record.rollback_certificate
    assert cert["kind"] == "rollback.certificate"
    assert cert["before_sha"] == before
    assert cert["verified"] is True
    # المحلي استُرجع فعلًا إلى الأساس
    head_now = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert head_now == before


def test_blast_limits_enforced(sandbox_manager, tmp_path, repo_factory):
    """حدود الانفجار: ملف أكبر من 1MiB = رفض قبل الدفع."""
    repo, engine, approvals = _push_stack(sandbox_manager, tmp_path, repo_factory)
    # ملف 1.5MiB داخل النطاق
    big = repo / "big.bin"
    big.write_bytes(b"x" * (1536 * 1024))
    import subprocess

    before = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    commit_sha, staged = engine.commit_in_sandbox(
        str(repo), "big file", (str(repo),)
    )
    with pytest.raises(PushRejected) as excinfo:
        engine.verify_before_push(staged, before, (str(repo),))
    assert "حدود الانفجار" in str(excinfo.value)
