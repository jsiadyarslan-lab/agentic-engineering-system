"""بوابة الوصول — §2 من الأمر الرابع المعدل.

ثلاثة أنواع منح، كلها موقعة HMAC بوقت انتهاء وإبطال حي:

- REPO_GRANT: مستودع + فرع + نطاق (read | read_write) + طريقة
  (clone | worktree).
- PATH_GRANT: مسار مطلق على الكمبيوتر + نطاق + عمق أقصى.
- NET_GRANT: مضيف:منفذ محدد — لا شبكة عامة أبدًا.

النموذج مطابق لعقد E1 (grants/grant.py): جهة الإصدار توقّع وجهة
التحقق تفحص — المفتاح يدخل من المستدعي وقت التشغيل ولا يُخزَّن في
الحزمة. البوابة (admission) fail-closed: كل محاولة وصول تمر عبر
``admit_access`` وبلا منح ساري = رفض بأسباب مقروءة آليًا.

**لا منح عام**: أي مسار فيه ``*`` أو ``**`` أو جذر ``/`` مجردًا =
رفض بنيوي عند الإصدار نفسه. النطاق دائمًا محدد.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Callable

from eoe.order_parser import AccessRequest, GrantKind


class GrantScope(str, Enum):
    READ = "read"
    READ_WRITE = "read_write"


class EoeGrantState(str, Enum):
    PENDING = "PENDING"      # مقترح من الأمر — بانتظار موافقة المالك
    APPROVED = "APPROVED"    # المالك وافق — موقع ومصدر
    REVOKED = "REVOKED"      # أُبطل حيًّا
    EXPIRED = "EXPIRED"      # انتهت صلاحيته


#: رفض بنيوي — كل سبب مقروء آليًا (fail-closed).
class AccessRejection(str, Enum):
    WILDCARD_FORBIDDEN = "منح عام ممنوع: لا * ولا / ولا **"
    NOT_ABSOLUTE = "مسار المنحة يجب أن يكون مطلقًا"
    BAD_HOST_PORT = "منحة الشبكة يجب أن تكون مضيف:منفذ محددًا"
    UNKNOWN_GRANT = "المنحة غير موجودة في الدفتر"
    NOT_APPROVED = "المنحة بانتظار موافقة المالك — لا وصول"
    REVOKED = "المنحة أُبطلت"
    EXPIRED = "المنحة انتهت صلاحيته"
    WRONG_KIND = "نوع المنحة لا يطابق الطلب"
    INSUFFICIENT_SCOPE = "نطاق المنحة قراءة والطلب كتابة"
    PATH_NOT_COVERED = "المسار المطلوب خارج نطاق المنحة"
    BRANCH_NOT_COVERED = "الفرع المطلوب خارج نطاق المنحة"
    HOST_NOT_COVERED = "المضيف:المنفذ خارج نطاق منحة الشبكة"
    DEPTH_EXCEEDED = "المسار أعمق من العمق الأقصى للمنحة"
    BAD_SIGNATURE = "توقيع المنحة غير صالح"
    MALFORMED = "طلب وصول مشوه"


@dataclass(frozen=True)
class EoeGrant:
    """منحة وصول واحدة — موقعة من جهة المالك بعد موافقته."""

    grant_id: str
    kind: GrantKind
    scope: GrantScope
    target: str            # owner/repo | مسار مطلق | host:port
    branch: str = ""       # REPO_GRANT
    method: str = ""       # REPO_GRANT: clone | worktree
    max_depth: int = 8     # PATH_GRANT: عمق أقصى تحت الهدف
    issued_at: float = 0.0
    expires_at: float = 0.0
    state: EoeGrantState = EoeGrantState.PENDING
    signature: str = ""

    def canonical_payload(self) -> bytes:
        """البايتات الموقعة — حتمية: JSON مفاتيح مرتبة بلا التوقيع."""
        payload = asdict(self)
        payload.pop("signature")
        payload["kind"] = self.kind.value
        payload["scope"] = self.scope.value
        payload["state"] = self.state.value
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")


def _sign(grant: EoeGrant, key: bytes) -> str:
    return hmac.new(key, grant.canonical_payload(), hashlib.sha256).hexdigest()


class AccessDenied(Exception):
    """رفض وصول — يحمل السبب المقروء (لا يُتجاهل أبدًا)."""

    def __init__(self, reason: AccessRejection, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


def _validate_grant_shape(request: AccessRequest) -> None:
    """فحص بنيوي عند الإصدار — يمنع المنح العامة من البداية."""
    if request.kind is GrantKind.PATH_GRANT:
        if not request.target.startswith("/"):
            raise AccessDenied(AccessRejection.NOT_ABSOLUTE, request.target)
        if request.target == "/":
            raise AccessDenied(AccessRejection.WILDCARD_FORBIDDEN, "الجذر / ممنوع")
        if "*" in request.target:
            raise AccessDenied(AccessRejection.WILDCARD_FORBIDDEN, request.target)
    if request.kind is GrantKind.REPO_GRANT:
        if "*" in request.target or request.target.strip() == "":
            raise AccessDenied(AccessRejection.WILDCARD_FORBIDDEN, request.target)
    if request.kind is GrantKind.NET_GRANT:
        parts = request.target.rsplit(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1].isdigit():
            raise AccessDenied(AccessRejection.BAD_HOST_PORT, request.target)
        if parts[0] in ("*", "0.0.0.0", "**"):
            raise AccessDenied(AccessRejection.WILDCARD_FORBIDDEN, request.target)


class GrantorService:
    """جهة المالك: تقترح منح الأمر (PENDING) وتوقّعها بعد الموافقة.

    الفصل صارم: ``propose`` ينشئ منحة غير موقعة بانتظار المالك؛
    ``approve`` يوقّع ويصدر — ولا يوقّع شيئًا لم توافق عليه الواجهة.
    المفتاح يدخل من المستدعي وقت التشغيل.
    """

    def __init__(self, key: bytes, ttl_seconds: float = 3600.0) -> None:
        if not isinstance(key, bytes) or not key:
            raise ValueError("مفتاح التوقيع يجب أن يكون بايتات غير فارغة")
        self._key = key
        self._ttl = ttl_seconds

    def propose(self, request: AccessRequest) -> EoeGrant:
        _validate_grant_shape(request)
        scope = GrantScope.READ_WRITE if request.scope == "read_write" else GrantScope.READ
        return EoeGrant(
            grant_id=f"grant-{uuid.uuid4().hex[:12]}",
            kind=request.kind,
            scope=scope,
            target=request.target,
            branch=request.branch,
            method=request.method or ("clone" if request.kind is GrantKind.REPO_GRANT else ""),
            issued_at=0.0,
            expires_at=0.0,
            state=EoeGrantState.PENDING,
        )

    def approve(
        self, grant: EoeGrant, *, now: float | None = None
    ) -> EoeGrant:
        """توقيع منحة وافق عليها المالك — تصبح سارية بتوقيت الإصدار."""
        if grant.state is not EoeGrantState.PENDING:
            raise ValueError("لا تُوقَّع إلا منحة بانتظار الموافقة")
        issued = time.time() if now is None else now
        signed = EoeGrant(
            grant_id=grant.grant_id,
            kind=grant.kind,
            scope=grant.scope,
            target=grant.target,
            branch=grant.branch,
            method=grant.method,
            max_depth=grant.max_depth,
            issued_at=issued,
            expires_at=issued + self._ttl,
            state=EoeGrantState.APPROVED,
        )
        return EoeGrant(
            **{**asdict(signed), "signature": _sign(signed, self._key)}
        )

    def verify(self, grant: EoeGrant) -> bool:
        """إعادة حساب التوقيع — تحقق جهة المالك قبل الاعتماد."""
        return hmac.compare_digest(_sign(grant, self._key), grant.signature)


class AccessLedger:
    """دفتر المنح الصادر + قناة الإبطال الحي + سجل الأحداث."""

    def __init__(self) -> None:
        self._grants: dict[str, EoeGrant] = {}
        self._revoked: set[str] = set()
        self.events: list[dict] = []

    def register(self, grant: EoeGrant) -> None:
        if grant.grant_id in self._grants:
            raise ValueError(f"معرف منحة مكرر: {grant.grant_id}")
        self._grants[grant.grant_id] = grant
        self._emit("grant.issued", grant)

    def revoke(self, grant_id: str) -> None:
        self._revoked.add(grant_id)
        grant = self._grants.get(grant_id)
        if grant is not None:
            self._grants[grant_id] = EoeGrant(
                **{**asdict(grant), "state": EoeGrantState.REVOKED}
            )
        self._emit("grant.revoked", self._grants.get(grant_id))

    def lookup(self, grant_id: str) -> EoeGrant | None:
        return self._grants.get(grant_id)

    def all(self) -> tuple[EoeGrant, ...]:
        return tuple(self._grants.values())

    def _emit(self, kind: str, grant: EoeGrant | None) -> None:
        if grant is not None:
            self.events.append(
                {"kind": kind, "grant_id": grant.grant_id, "kind_type": grant.kind.value}
            )

    def sweep_expired(self, now: float) -> list[str]:
        """تعليم المنح المنتهية — يُستدعى دوريًا من المحرك."""
        expired: list[str] = []
        for grant in self._grants.values():
            if (
                grant.state is EoeGrantState.APPROVED
                and grant.expires_at
                and now >= grant.expires_at
            ):
                self._grants[grant.grant_id] = EoeGrant(
                    **{**asdict(grant), "state": EoeGrantState.EXPIRED}
                )
                expired.append(grant.grant_id)
                self.events.append(
                    {"kind": "grant.expired", "grant_id": grant.grant_id,
                     "kind_type": grant.kind.value}
                )
        return expired


class AccessAdmission:
    """بوابة القبول — fail-closed على النموذج E1: كل وصول يُفحص.

    ``admit_access`` يرفض دائمًا بسبب مقروء ولا يرفع استثناءً إلى
    المستدعي إلا ``AccessDenied`` نفسها (السبب + التفصيل).
    """

    def __init__(
        self,
        ledger: AccessLedger,
        grantor: GrantorService,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._ledger = ledger
        self._grantor = grantor
        self._now = now
        self.usage_log: list[dict] = []

    def admit_grant_id(
        self,
        grant_id: str,
        *,
        write: bool,
        path: str = "",
        depth: "int | None" = None,
    ) -> EoeGrant:
        """E10-RP2 §2: قبول وصول مربوط بمنحة بعينها (لا أي منحة تغطي).

        نفس دلالات ``admit_access`` تمامًا (توقيع، سارية، حالة، نطاق،
        تغطية المسار، العمق) لكن للمنحة التي قدّمها طرف التنفيذ
        بهويتها — وليس أول منحة سارية تطابق. تُستخدم من جسر المحرك
        الموحّد (``eoe.engine_bridge``) الذي يربط سياسة منح EOE
        بـ``grant_validator`` في مسار التنفيذ المحكوم: المحرك يقدّم
        ``grant_id`` محددًا، فلا يجوز أن تغطيه منحة أخرى.

        E10-RP2.1 §2 — عقد العمق الصريح: ``depth=None`` (الافتراضي
        الجديد) يعني "احسب العمق الحقيقي للمسار المطلوب تحت هدف المنحة".
        اصطلاح العمق: depth(path, T) = عدد مكوّنات المسار تحت الهدف T
        (الهدف نفسه = 0؛ ملف مباشر تحت الهدف = 1؛ ملف داخل مجلد واحد
        تحت الهدف = 2). بالتالي منحة ``max_depth=0`` لا تجيز أي كتابة
        ملف تحت الهدف (أي ملف على عمق >= 1) — الحد مطبق على المسار
        الفعلي المطلوب، لا قيمة ثابتة يمررها المستدعي.
        """
        if not grant_id:
            raise AccessDenied(AccessRejection.NOT_APPROVED, "معرّف منحة فارغ")
        now = self._now()
        self._ledger.sweep_expired(now)
        grant = self._ledger.lookup(grant_id)
        if grant is None:
            raise AccessDenied(
                AccessRejection.NOT_APPROVED,
                f"منحة غير معروفة: {grant_id} — رفض fail-closed",
            )
        if grant.state is not EoeGrantState.APPROVED:
            raise AccessDenied(
                AccessRejection.NOT_APPROVED,
                f"المنحة {grant_id} حالتها {grant.state.value} — لا وصول",
            )
        # E10-RP2.1 §2.3: honest depth — computed from the ACTUAL requested
        # path relative to the grant target, never a caller-fixed constant.
        effective_depth = depth
        if effective_depth is None:
            effective_depth = self._actual_depth(grant, path)
        problem = self._check(
            grant, write=write, path=path, repo="", branch="",
            host_port="", depth=effective_depth, now=now,
        )
        if problem is not None:
            rejection = next(
                (r for r in AccessRejection if r.value == problem),
                AccessRejection.PATH_NOT_COVERED,
            )
            raise AccessDenied(rejection, problem)
        self.usage_log.append(
            {"grant_id": grant.grant_id, "kind": grant.kind.value,
             "at": now, "write": write, "target": path}
        )
        self._ledger.events.append(
            {"kind": "grant.used", "grant_id": grant.grant_id,
             "kind_type": grant.kind.value}
        )
        return grant

    def admit_grant_kind(self, grant_id: str, *, write: bool) -> EoeGrant:
        """E10-RP2.1 §2 — البوابة الخشنة: صلاحية المنحة ونطاقها مقابل
        نوع العملية (قراءة/كتابة) بلا مسار.

        شرط لازم فقط — لا يكفي أبدًا لتجويز عملية ملموسة: القرار الكامل
        يتطلب المسار الفعلي والعمق (``admit_grant_id`` بصيغته الموسعة).
        تفحص: الوجود، الحالة (APPROVED)، التوقيع، السارية، النطاق.
        """
        if not grant_id:
            raise AccessDenied(AccessRejection.NOT_APPROVED, "معرّف منحة فارغ")
        now = self._now()
        self._ledger.sweep_expired(now)
        grant = self._ledger.lookup(grant_id)
        if grant is None:
            raise AccessDenied(
                AccessRejection.NOT_APPROVED,
                f"منحة غير معروفة: {grant_id} — رفض fail-closed",
            )
        if grant.state is not EoeGrantState.APPROVED:
            raise AccessDenied(
                AccessRejection.NOT_APPROVED,
                f"المنحة {grant_id} حالتها {grant.state.value} — لا وصول",
            )
        problem = self._check(
            grant, write=write, path="", repo="", branch="",
            host_port="", depth=0, now=now, kind_only=True,
        )
        if problem is not None:
            rejection = next(
                (r for r in AccessRejection if r.value == problem),
                AccessRejection.NOT_APPROVED,
            )
            raise AccessDenied(rejection, problem)
        return grant

    @staticmethod
    def _actual_depth(grant: EoeGrant, path: str) -> int:
        """E10-RP2.1 §2.3 — العمق الحقيقي للمسار المطلوب تحت هدف المنحة.

        اصطلاح العمق (صريح ومختبر): عدد مكوّنات المسار تحت الهدف.
        الهدف نفسه = 0، ملف مباشر تحته = 1، وهكذا. إذا كان المسار
        خارج الهدف أصلًا فالعمق لا يهم (فحص التغطية سيرفض) — نعيد
        عددًا كبيرًا كي لا يمر أي فحص عمق بالخطأ.
        """
        if grant.kind is not GrantKind.PATH_GRANT or not path:
            return 0
        target = grant.target.rstrip("/")
        if path == target:
            return 0
        if not path.startswith(target + "/"):
            # خارج نطاق المنحة — فحص التغطية يرفض؛ عمق كبير كي لا
            # يوحي فحص العمق بأي سماح.
            return 1 << 30
        rel = path[len(target) + 1:]
        return len([p for p in rel.split("/") if p not in ("", ".")])

    def admit_access(
        self,
        *,
        kind: GrantKind,
        write: bool,
        path: str = "",
        repo: str = "",
        branch: str = "",
        host_port: str = "",
        depth: int = 0,
    ) -> EoeGrant:
        """فحص محاولة وصول واحدة — تعيد المنحة السارية أو ترفض."""
        now = self._now()
        self._ledger.sweep_expired(now)
        candidates = [
            grant
            for grant in self._ledger.all()
            if grant.kind is kind and grant.state is EoeGrantState.APPROVED
        ]
        if not candidates:
            raise AccessDenied(
                AccessRejection.NOT_APPROVED,
                f"لا منحة سارية من نوع {kind.value} — رفض fail-closed",
            )
        failures: list[str] = []
        for grant in candidates:
            problem = self._check(grant, write=write, path=path, repo=repo,
                                  branch=branch, host_port=host_port, depth=depth, now=now)
            if problem is None:
                self.usage_log.append(
                    {"grant_id": grant.grant_id, "kind": grant.kind.value,
                     "at": now, "write": write, "target": path or repo or host_port}
                )
                self._ledger.events.append(
                    {"kind": "grant.used", "grant_id": grant.grant_id,
                     "kind_type": grant.kind.value}
                )
                return grant
            failures.append(f"{grant.grant_id}: {problem}")
        reason = failures[0].split(": ", 1)[1] if failures else ""
        for candidate in (AccessRejection.PATH_NOT_COVERED,
                          AccessRejection.BRANCH_NOT_COVERED,
                          AccessRejection.HOST_NOT_COVERED,
                          AccessRejection.INSUFFICIENT_SCOPE):
            if candidate.value == reason:
                raise AccessDenied(candidate, reason)
        raise AccessDenied(AccessRejection.PATH_NOT_COVERED, "؛ ".join(failures))

    def _check(
        self,
        grant: EoeGrant,
        *,
        write: bool,
        path: str,
        repo: str,
        branch: str,
        host_port: str,
        depth: int,
        now: float,
        kind_only: bool = False,
    ) -> str | None:
        """سبب الرفض أو None إن كانت المنحة تغطي الطلب.

        ``kind_only=True`` (بوابة خشنة): تفحص التوقيع/السارية/الإبطال/
        النطاق فقط — لا تغطية مسار ولا عمق ولا فرع ولا مضيف (لا مسار
        ملموسًا في هذا الوضع أصلًا).
        """
        if not self._grantor.verify(grant):
            return AccessRejection.BAD_SIGNATURE.value
        if now >= grant.expires_at:
            return AccessRejection.EXPIRED.value
        if grant.state is EoeGrantState.REVOKED:
            return AccessRejection.REVOKED.value
        if write and grant.scope is not GrantScope.READ_WRITE:
            return AccessRejection.INSUFFICIENT_SCOPE.value
        if kind_only:
            return None
        if grant.kind is GrantKind.PATH_GRANT:
            if not path.startswith(grant.target.rstrip("/") + "/") and path != grant.target:
                return AccessRejection.PATH_NOT_COVERED.value
            if depth > grant.max_depth:
                return AccessRejection.DEPTH_EXCEEDED.value
        if grant.kind is GrantKind.REPO_GRANT:
            if repo != grant.target:
                return AccessRejection.PATH_NOT_COVERED.value
            if grant.branch and branch and branch != grant.branch:
                return AccessRejection.BRANCH_NOT_COVERED.value
        if grant.kind is GrantKind.NET_GRANT and host_port != grant.target:
            return AccessRejection.HOST_NOT_COVERED.value
        return None
