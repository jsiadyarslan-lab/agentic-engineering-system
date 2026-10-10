"""محرك الدفع — §5 من الأمر الرابع المعدل (تفعيل E4 أخيرًا).

المسار الكامل، مرحلة مرحلة، كل واحدة محروسة:

1. **التزام داخل العزل**: نسخة مرحّلة من المستودع الممنوح تُلتزم داخل
   الركيزة بصورة git الحقيقية — ثلاثة أوامر git حرفيًا (add/commit/
   status) بحدود انفجار: ≤64 ملفًا، ≤1MiB للملف، ≤60 ثانية.
2. **تحقق مستقل قبل الدفع**: إعادة بناء قاعدة الكائنات على المضيف
   (fsck + rev-parse + diff --name-only) — لا كائنات تالفة، ولا ملف
   خارج نطاق المنحة، ولا تجاوز للحدود.
3. **موافقة مالك موقعة أحادية الاستخدام**: HMAC على حمولة الدفع
   (المستودع+الفرع+sha+بصمة الملفات) + nonce يُستهلك مرة واحدة من
   دفتر nonces — لا إعادة تشغيل ممكنة، ولا موافقة تصلح لدفع آخر.
4. **snapshot قبل التطبيق**: sha الأساس + refs — للاسترجاع.
5. **النقل داخل المستودع الحقيقي**: fetch + merge --ff-only حصرًا —
   لا دمج قسري ولا rewrite للتاريخ.
6. **الدفع نفسه**: عملية git المضيفية الوحيدة بكل المحرك — argv
   ثابت بلا shell، لأن الركيزة شبكتها NONE (D-04=A) والدفع يقتضي
   شبكة. هذا القرار موثق في ARCHITECTURE §13.
7. **الاسترجاع التلقائي**: فشل الدفع = reset --hard للأساس + شهادة
   استرجاع قابلة للفحص (sha قبل/بعد + refs + تحقق).

كل دفع يُسجَّل PushRecord كاملاً: sha قبل/بعد، قائمة الملفات، رسالة
الالتزام، الشهادة. لا دفع أبدًا بلا موافقة — حتى في WRITE_AND_PUSH.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from eoe.access_gateway import AccessAdmission, AccessDenied
from eoe.order_parser import GrantKind
from substrate.limits import E1_LIMITS_DEFAULTS
from substrate.sandbox import NetworkMode, SandboxRequest


#: حدود الانفجار — حرفيًا من الأمر الرابع §5.1.
BLAST_MAX_FILES = 64
BLAST_MAX_FILE_BYTES = 1024 * 1024   # 1 MiB للملف الواحد
BLAST_TIMEOUT_SECONDS = 60           # الثلاثة أوامر مجتمعة
GIT_COMMAND_ALLOWANCE = ("add", "commit", "status")  # حصرًا


class PushRejected(Exception):
    """رفض دفع — سبب مقروء (بلا موافقة/توقيع/nonce/نطاق/حدود)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class NonceLedger:
    """دفتر nonces — أحادية الاستخدام المفروضة بنيويًا."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def consume(self, nonce: str) -> bool:
        """استهلاك nonce — False إن سبق استهلاكه (إعادة تشغيل ممنوعة)."""
        if not nonce or nonce in self._used:
            return False
        self._used.add(nonce)
        return True


@dataclass(frozen=True)
class PushApproval:
    """موافقة مالك موقعة على دفع واحد بعينه.

    E10-RP2.2-R2 §3.4/§3.5 — الحقلان الجديدان ``remote`` و``force`` يُدخلان
    في نطاق الموافقة وفي الحمولة الموقعة: الموافقة مقيدة الآن بالمستودع
    والـremote والفرع والالتزام وعملية الدفع نفسها (أحادية الاستخدام عبر
    الـnonce). ``remote=""`` عند التوقيع = لا remote معتمدًا — التحقق
    يرفض أي remote مطلوب (fail-closed).
    """

    push_id: str
    repository: str
    branch: str
    commit_sha: str
    files_digest: str
    nonce: str
    issued_at: float
    expires_at: float
    approver: str
    remote: str = ""
    force: bool = False
    signature: str = ""

    def canonical_payload(self) -> bytes:
        payload = {
            "push_id": self.push_id,
            "repository": self.repository,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "files_digest": self.files_digest,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "approver": self.approver,
            "remote": self.remote,
            "force": self.force,
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")


class OwnerApprovalService:
    """جهة توقيع موافقات المالك — المفتاح من المستدعي وقت التشغيل."""

    def __init__(self, key: bytes, ttl_seconds: float = 600.0) -> None:
        if not isinstance(key, bytes) or not key:
            raise ValueError("مفتاح الموافقة يجب أن يكون بايتات غير فارغة")
        self._key = key
        self._ttl = ttl_seconds

    def sign(
        self,
        *,
        repository: str,
        branch: str,
        commit_sha: str,
        files_digest: str,
        approver: str = "owner",
        remote: str = "",
        force: bool = False,
        now: float | None = None,
    ) -> PushApproval:
        issued = time.time() if now is None else now
        approval = PushApproval(
            push_id=f"push-{uuid.uuid4().hex[:12]}",
            repository=repository,
            branch=branch,
            commit_sha=commit_sha,
            files_digest=files_digest,
            nonce=uuid.uuid4().hex,
            issued_at=issued,
            expires_at=issued + self._ttl,
            approver=approver,
            remote=remote,
            force=force,
        )
        signature = hmac.new(
            self._key, approval.canonical_payload(), hashlib.sha256
        ).hexdigest()
        return PushApproval(
            **{**approval.__dict__, "signature": signature}
        )

    def verify(self, approval: PushApproval, *, now: float | None = None) -> bool:
        expected = hmac.new(
            self._key, approval.canonical_payload(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, approval.signature):
            return False
        moment = time.time() if now is None else now
        return approval.issued_at <= moment < approval.expires_at


class PushApprovalRegistry:
    """E10-RP2.2-R2 §3.4/§3.5 — سجل موافقات الدفع الصادرة عن المالك.

    الجسر بين أداة ``git_push`` في المحرك الموحد وآلية موافقة المالك
    الحقيقية: المالك يوقّع موافقة (``OwnerApprovalService.sign``) ويسجلها
    هنا؛ الأداة تقدّم ``owner_approval_nonce`` فقط، والسجل يتحقق من أن
    الـnonce مرتبط بسجل موافقة حقيقي:

    - موجود وموقّع بتوقيع صالح وغير منتهي (``OwnerApprovalService.verify``)؛
    - مقيد بالمستودع والفرع والالتزام والـremote وعلم force المطلوبين
         بعينهم — أي اختلاف = رفض؛
    - غير مستخدم من قبل (``NonceLedger`` أحادي الاستخدام؛ المحاولة
           نفسها تستهلك الموافقة — إعادة التشغيل ممنوعة).

    البصمة الإضافية ``files_digest`` يتحقق منها مسار ``PushEngine`` الخاص
    بالـEOE (نسخته المرحّلة)؛ أداة ``git_push`` الموحدة تربط الالتزام
    نفسه (``commit_sha``) — الحقل يبقى في السجل لكنه خارج نطاق تحقق
    الأداة (حد معلن في تقرير R2).
    """

    def __init__(self, approval_service: OwnerApprovalService, nonce_ledger: NonceLedger) -> None:
        self._approvals = approval_service
        self._nonces = nonce_ledger
        self._by_nonce: dict[str, PushApproval] = {}

    def register(self, approval: PushApproval) -> PushApproval:
        """تسجيل موافقة صادرة (قناة المالك) — بالـnonce مفتاحًا."""
        if not approval.nonce:
            raise ValueError("لا تسجيل موافقة بلا nonce")
        if approval.nonce in self._by_nonce:
            raise ValueError("nonce مكرر في سجل الموافقات")
        self._by_nonce[approval.nonce] = approval
        return approval

    def verify_and_consume(
        self,
        nonce: str,
        *,
        repository: str,
        branch: str,
        commit_sha: str,
        remote: str,
        force: bool = False,
        now: float | None = None,
    ) -> tuple[bool, str]:
        """التحقق من nonce مقابل سجل موافقة حقيقي ثم استهلاكه.

        تعيد ``(True, "approved")`` أو ``(False, السبب)`` — أي فشل رفض
        صريح، والاستهلاك يحدث فقط بعد نجاح كل الفحوص (المحاولة الناجحة
        تحرق الموافقة؛ المحاولة الفاشلة قبل الاستهلاك لا تحرقها إلا إذا
        كان الـnonce مستهلكًا أصلًا).
        """
        if not nonce:
            return False, "لا يوجد nonce"
        record = self._by_nonce.get(nonce)
        if record is None:
            return False, f"nonce {nonce[:8]}… غير مسجل — لا سجل موافقة مالك حقيقي يرتبط به"
        if not self._approvals.verify(record, now=now):
            return False, "توقيع الموافقة غير صالح أو منتهية الصلاحية"
        if record.repository != repository:
            return False, f"الموافقة مقيدة بمستودع آخر ({record.repository!r} != {repository!r})"
        if record.branch != branch:
            return False, f"الموافقة مقيدة بفرع آخر ({record.branch!r} != {branch!r})"
        if record.commit_sha != commit_sha:
            return False, "الموافقة مقيدة بالتزام آخر — تغير HEAD بعد الموافقة"
        if not record.remote or record.remote != remote:
            return False, f"الـremote المطلوب ({remote!r}) غير معتمد في الموافقة"
        if bool(record.force) != bool(force):
            return False, f"علم force المطلوب ({force}) لا يطابق نطاق الموافقة ({record.force})"
        if not self._nonces.consume(nonce):
            return False, f"nonce {nonce[:8]}… استُهلك — الموافقة أحادية الاستخدام"
        # الدفع المرخص بهذا الـnonce تمت مزاولته: السجل يُحرق أيضًا
        # (دفاع بالعمق — أي محاولة لاحقة بنفس الـnonce = nonce غير مسجل).
        self._by_nonce.pop(nonce, None)
        return True, "approved"


@dataclass
class PushRecord:
    """سجل دفع واحد — الدليل الكامل القابل للتدقيق."""

    repository: str
    branch: str
    before_sha: str = ""
    after_sha: str = ""
    commit_message: str = ""
    files: tuple[str, ...] = ()
    pushed: bool = False
    rollback_certificate: dict = field(default_factory=dict)
    failure: str = ""


def _git(repo: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """أمر git مضيفي ثابت الوسائط — بلا shell، بلا مدخلات مستدعٍ."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


class PushEngine:
    """الالتزام داخل العزل + الدفع بموافقة موقعة أحادية الاستخدام."""

    def __init__(
        self,
        manager,
        approval_service: OwnerApprovalService,
        nonce_ledger: NonceLedger,
        admission: AccessAdmission,
        *,
        work_base: str = "",
    ) -> None:
        self._manager = manager
        self._approvals = approval_service
        self._nonces = nonce_ledger
        self._admission = admission
        self._work_base = Path(work_base) if work_base else Path(
            __import__("tempfile").mkdtemp(prefix="eoe-push-")
        )
        self.records: list[PushRecord] = []

    # -- المرحلة 1: التزام داخل العزل -----------------------------------

    def commit_in_sandbox(
        self, repo_root: str, message: str, scope_paths: tuple[str, ...]
    ) -> tuple[str, Path]:
        """نسخة مرحّلة تُلتزم داخل الركيزة — تعيد (sha، مسار النسخة)."""
        import shutil

        repo = Path(repo_root)
        staged = self._work_base / f"staged-{uuid.uuid4().hex[:8]}"
        staged.mkdir(parents=True, exist_ok=True)
        shutil.copytree(repo, staged, dirs_exist_ok=True, symlinks=True)

        started = time.time()
        for subcommand in (
            ("add", "-A"),
            ("commit", "-m", message),
            ("status", "--porcelain"),
        ):
            if time.time() - started > BLAST_TIMEOUT_SECONDS:
                raise PushRejected(
                    "تجاوز حدود الانفجار", "الثلاثة أوامر تجاوزت 60 ثانية"
                )
            self._sandbox_git(staged, subcommand)
        sha_result = _git(staged, "rev-parse", "HEAD")
        if sha_result.returncode != 0:
            raise PushRejected(
                "فشل قراءة sha بعد الالتزام", sha_result.stderr.strip()[:200]
            )
        return sha_result.stdout.strip(), staged

    def _sandbox_git(self, staged: Path, args: tuple[str, ...]) -> None:
        """أمر git واحد داخل الركيزة — /artifacts هو النسخة المرحّلة."""
        if args[0] not in GIT_COMMAND_ALLOWANCE:
            raise PushRejected(
                "أمر git خارج الثلاثة المسموحة", f"git {args[0]}"
            )
        request = SandboxRequest(
            sandbox_id=f"push-{uuid.uuid4().hex[:10]}",
            image="git",
            command=("git", "-C", "/artifacts", *args),
            limits=E1_LIMITS_DEFAULTS,
            env_names=frozenset({"PATH"}),
            network=NetworkMode.NONE,
            workspace_root=str(staged.parent),
            artifacts_dir=str(staged),
        )
        outcome = self._manager.execute(request)
        record = outcome.record
        if record is None or not record.executed or record.exit_code != 0:
            detail = outcome.detail or (
                f"exit={record.exit_code if record else '؟'}"
            )
            raise PushRejected(
                f"فشل git {args[0]} داخل العزل", detail[:200]
            )

    # -- المرحلة 2: تحقق مستقل قبل الدفع ----------------------------------

    def verify_before_push(
        self,
        staged: Path,
        baseline_sha: str,
        scope_paths: tuple[str, ...],
        repo_root: str = "",
    ) -> tuple[str, tuple[str, ...]]:
        """fsck + قائمة الملفات + النطاق + الحدود — تعيد بصمة الملفات.

        فحص النطاق يجري على مسار الملف داخل المستودع الأصلي لا داخل
        النسخة المرحّلة — المنحة تغطي المستودع، والنسخة أداته.
        """
        origin = Path(repo_root) if repo_root else staged
        fsck = _git(staged, "fsck", "--no-progress")
        if fsck.returncode != 0:
            raise PushRejected(
                "قاعدة كائنات تالفة قبل الدفع", fsck.stderr.strip()[:200]
            )
        diff = _git(
            staged, "diff", "--name-only", f"{baseline_sha}..HEAD"
        )
        if diff.returncode != 0:
            raise PushRejected(
                "تعذر حصر الملفات المتغيرة", diff.stderr.strip()[:200]
            )
        files = tuple(
            line.strip() for line in diff.stdout.splitlines() if line.strip()
        )
        if not files:
            raise PushRejected("التزام فارغ — لا ملفات متغيرة")
        if len(files) > BLAST_MAX_FILES:
            raise PushRejected(
                "تجاوز حدود الانفجار",
                f"{len(files)} ملفًا > سقف {BLAST_MAX_FILES}",
            )
        for name in files:
            size = (staged / name).stat().st_size if (staged / name).is_file() else 0
            if size > BLAST_MAX_FILE_BYTES:
                raise PushRejected(
                    "تجاوز حدود الانفجار",
                    f"{name} يتجاوز 1MiB للملف الواحد",
                )
        for name in files:
            absolute = str((origin / name).resolve())
            try:
                self._admission.admit_access(
                    kind=GrantKind.PATH_GRANT, write=True, path=absolute
                )
            except AccessDenied as denied:
                raise PushRejected(
                    "ملف خارج نطاق المنحة",
                    f"{name}: {denied.reason.value}",
                ) from denied
        digest = hashlib.sha256("\n".join(files).encode()).hexdigest()
        return digest, files

    # -- المرحلة 3-7: الموافقة والنقل والدفع والاسترجاع --------------------

    def push(
        self,
        *,
        repo_root: str,
        branch: str,
        commit_message: str,
        scope_paths: tuple[str, ...],
        approval: PushApproval | None,
        remote_url: str = "origin",
        now: float | None = None,
        staged: Path | None = None,
        commit_sha: str | None = None,
    ) -> PushRecord:
        """المسار الكامل: التزام → تحقق → موافقة → نقل → دفع → سجل.

        ``staged``/``commit_sha``: التزام معدّ سلفًا (من تدفق الموافقة
        عبر الواجهة) — يُستخدم كما هو ولا يُعاد إنشاؤه، لأن الموافقة
        موقعة على sha بعينه وإعادة الإنشاء تغيّره.
        """
        repo = Path(repo_root)
        before = _git(repo, "rev-parse", "HEAD")
        if before.returncode != 0:
            raise PushRejected("لا HEAD للمستودع", before.stderr.strip()[:120])
        before_sha = before.stdout.strip()

        # -- بوابة الموافقة الموقعة أولًا: توقيع ثم nonce — قبل أي التزام
        # أو تحقق أو نقل. الموافقة تُستهلك عند المحاولة نفسها (أحادية
        # الاستخدام): المحاولة الفاشلة تحرق الموافقة وتتطلب جديدة.
        moment = time.time() if now is None else now
        if approval is None:
            raise PushRejected(
                "دفع بلا موافقة موقعة",
                "الدفع لا يحدث أبدًا بدون موافقة مالك صريحة",
            )
        if not self._approvals.verify(approval, now=moment):
            raise PushRejected("توقيع الموافقة غير صالح أو منتهية")
        if not self._nonces.consume(approval.nonce):
            raise PushRejected(
                "إعادة تشغيل ممنوعة",
                f"nonce {approval.nonce[:8]}… استُهلك — الموافقة أحادية الاستخدام",
            )

        if staged is not None and commit_sha:
            staged_path = Path(staged)
        else:
            commit_sha, staged_path = self.commit_in_sandbox(
                repo_root, commit_message, scope_paths
            )
        files_digest, files = self.verify_before_push(
            staged_path, before_sha, scope_paths, repo_root=repo_root
        )

        # ربط الموافقة بهذا الدفع بعينه: sha وبصمة الملفات
        if (
            approval.commit_sha != commit_sha
            or approval.files_digest != files_digest
        ):
            raise PushRejected(
                "الموافقة لا تنطبق على هذا الدفع",
                "sha أو بصمة الملفات تغيرت بعد الموافقة",
            )

        record = PushRecord(
            repository=str(repo), branch=branch, before_sha=before_sha,
            after_sha=commit_sha, commit_message=commit_message, files=files,
        )

        # -- snapshot الأساس ثم النقل داخل المستودع الحقيقي --
        refs_snapshot = _git(repo, "show-ref").stdout
        fetch = _git(repo, "fetch", str(staged_path), commit_sha, timeout=60)
        if fetch.returncode != 0:
            raise PushRejected(
                "فشل جلب الالتزام داخل المستودع", fetch.stderr.strip()[:200]
            )
        # تقدم سريع حصرًا: الالتزام الجديد يجب أن ينحدر من الأساس —
        # فحص السلفية صريح ثم تحريك المؤشر بلا مساس لملفات العمل
        # (update-ref + reset --mixed: المؤشر والفهرس فقط؛ العمل يتطابق
        # أصلاً لأن الالتزام صُنع من نسخته).
        ancestry = _git(repo, "merge-base", "--is-ancestor", "HEAD", commit_sha)
        if ancestry.returncode != 0:
            self._rollback(repo, before_sha, record, refs_snapshot)
            raise PushRejected(
                "النقل ليس تقدمًا سريعًا — تاريخ منحرف",
                ancestry.stderr.strip()[:200],
            )
        update_ref = _git(repo, "update-ref", f"refs/heads/{branch}", commit_sha)
        soft_reset = _git(repo, "reset", "--mixed", commit_sha)
        if update_ref.returncode != 0 or soft_reset.returncode != 0:
            self._rollback(repo, before_sha, record, refs_snapshot)
            raise PushRejected(
                "فشل تحديث الفرع إلى الالتزام الجديد",
                (update_ref.stderr or soft_reset.stderr).strip()[:200],
            )

        # -- الدفع نفسه: argv ثابت بلا shell --
        push = _git(repo, "push", remote_url, f"HEAD:refs/heads/{branch}", timeout=120)
        if push.returncode != 0:
            self._rollback(repo, before_sha, record, refs_snapshot)
            record.failure = push.stderr.strip()[:300]
            self.records.append(record)
            return record

        record.pushed = True
        after = _git(repo, "rev-parse", "HEAD").stdout.strip()
        record.after_sha = after or commit_sha
        self.records.append(record)
        return record

    def _rollback(
        self, repo: Path, baseline_sha: str, record: PushRecord, refs: str
    ) -> None:
        """استرجاع تلقائي + شهادة قابلة للفحص (§5.4)."""
        reset = _git(repo, "reset", "--hard", baseline_sha, timeout=60)
        head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
        verified = head_after == baseline_sha and reset.returncode == 0
        record.rollback_certificate = {
            "kind": "rollback.certificate",
            "before_sha": baseline_sha,
            "attempted_sha": record.after_sha,
            "refs_before": refs.strip()[:400],
            "head_after_rollback": head_after,
            "verified": verified,
            "at": time.time(),
        }
        record.after_sha = ""
        record.pushed = False
