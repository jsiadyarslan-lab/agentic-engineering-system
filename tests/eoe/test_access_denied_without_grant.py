"""§10.3 — test_access_denied_without_grant: fail-closed بأسباب مقروءة."""
from __future__ import annotations

import pytest

from eoe.access_gateway import (
    AccessAdmission,
    AccessDenied,
    AccessLedger,
    AccessRejection,
    GrantorService,
)
from eoe.order_parser import AccessRequest, GrantKind


def _gateway():
    grantor = GrantorService(b"unit-key")
    ledger = AccessLedger()
    admission = AccessAdmission(ledger, grantor)
    return grantor, ledger, admission


def test_read_without_any_grant_is_denied_with_reason():
    """بلا منحة سارية = رفض fail-closed بسبب مقروء."""
    _, _, admission = _gateway()
    with pytest.raises(AccessDenied) as excinfo:
        admission.admit_access(
            kind=GrantKind.PATH_GRANT, write=False, path="/home/z/data/x"
        )
    assert excinfo.value.reason is AccessRejection.NOT_APPROVED
    assert "fail-closed" in excinfo.value.detail


def test_pending_grant_is_not_access():
    """منحة مقترحة بلا موافقة المالك = لا وصول (PENDING يُرفض)."""
    grantor, ledger, admission = _gateway()
    proposal = grantor.propose(
        AccessRequest(kind=GrantKind.PATH_GRANT, scope="read", target="/home/z/data")
    )
    ledger.register(proposal)  # مسجلة PENDING — لم يوافق المالك
    with pytest.raises(AccessDenied) as excinfo:
        admission.admit_access(
            kind=GrantKind.PATH_GRANT, write=False, path="/home/z/data/f.txt"
        )
    assert excinfo.value.reason is AccessRejection.NOT_APPROVED


def test_wrong_path_and_write_scope_denied(tmp_path):
    """منحة على مسار لا تغطي مسارًا آخر، ولا تكفي للكتابة."""
    grantor, ledger, admission = _gateway()
    approved = grantor.approve(
        grantor.propose(
            AccessRequest(kind=GrantKind.PATH_GRANT, scope="read",
                          target=str(tmp_path))
        )
    )
    ledger.register(approved)
    # خارج النطاق
    with pytest.raises(AccessDenied):
        admission.admit_access(
            kind=GrantKind.PATH_GRANT, write=False, path="/etc/passwd"
        )
    # كتابة بمنحة قراءة
    with pytest.raises(AccessDenied) as excinfo:
        admission.admit_access(
            kind=GrantKind.PATH_GRANT, write=True, path=str(tmp_path / "x.txt")
        )
    assert excinfo.value.reason is AccessRejection.INSUFFICIENT_SCOPE


def test_expired_and_revoked_grants_denied(tmp_path):
    """انتهاء الصلاحية والإبطال الحي — كلاهما رفض قراءة السبب."""
    grantor = GrantorService(b"unit-key")
    ledger = AccessLedger()
    # ساعة مجمدة عند 200: منحة صدرت عند 100 بانتهاء 100.001 صارت منتهية
    frozen_admission = AccessAdmission(ledger, grantor, now=lambda: 200.0)
    expired = GrantorService(b"unit-key", ttl_seconds=0.001).approve(
        grantor.propose(
            AccessRequest(kind=GrantKind.PATH_GRANT, scope="read",
                          target=str(tmp_path))
        ),
        now=100.0,
    )
    ledger.register(expired)
    with pytest.raises(AccessDenied):
        frozen_admission.admit_access(
            kind=GrantKind.PATH_GRANT, write=False, path=str(tmp_path / "f")
        )
    # إبطال حي — عبر البوابة الحية
    live = AccessAdmission(ledger, grantor)
    grant_id = expired.grant_id
    ledger.revoke(grant_id)
    with pytest.raises(AccessDenied):
        live.admit_access(
            kind=GrantKind.PATH_GRANT, write=False, path=str(tmp_path / "f")
        )


def test_no_wildcard_grants_ever():
    """لا * ولا / مجردة ولا ** — رفض بنيوي عند الإصدار نفسه."""
    grantor, _, _ = _gateway()
    with pytest.raises(AccessDenied):
        grantor.propose(
            AccessRequest(kind=GrantKind.PATH_GRANT, scope="read", target="/")
        )
    with pytest.raises(AccessDenied):
        grantor.propose(
            AccessRequest(kind=GrantKind.PATH_GRANT, scope="read", target="/data/*")
        )
    with pytest.raises(AccessDenied):
        grantor.propose(
            AccessRequest(kind=GrantKind.REPO_GRANT, scope="read", target="*")
        )
    with pytest.raises(AccessDenied):
        grantor.propose(
            AccessRequest(kind=GrantKind.NET_GRANT, scope="read", target="*:80")
        )
    with pytest.raises(AccessDenied):
        grantor.propose(
            AccessRequest(kind=GrantKind.NET_GRANT, scope="read", target="not-a-port")
        )


def test_valid_grant_allows_access_and_logs_usage(tmp_path):
    """منحة موقعة سارية تسمح بالقراءة وتسجل الاستخدام والأحداث."""
    grantor, ledger, admission = _gateway()
    approved = grantor.approve(
        grantor.propose(
            AccessRequest(kind=GrantKind.PATH_GRANT, scope="read_write",
                          target=str(tmp_path))
        )
    )
    ledger.register(approved)
    grant = admission.admit_access(
        kind=GrantKind.PATH_GRANT, write=True, path=str(tmp_path / "new.txt")
    )
    assert grant.grant_id == approved.grant_id
    assert len(admission.usage_log) == 1
    kinds = [event["kind"] for event in ledger.events]
    assert "grant.issued" in kinds and "grant.used" in kinds
