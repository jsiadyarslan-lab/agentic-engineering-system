"""مُنسّق محرك الأوامر التنفيذية — الأمر الرابع المعدل.

المسار الكامل: تحليل → أساس → منح → أقسام (إثبات قبل/بعد) →
دفع (إن كان الوضع كاتبًا) → تقرير بالقالب حرفيًا.

قواعد مفروضة آليًا (§9 الموسعة) — كل واحدة توقف صلب + تقرير جزئي
+ حدث ``hard_stop.fired`` بالسبب:

- انحراف الأساس (إن اشترط الأمر فحص الأساس)؛
- قسم غير موجود في الـ spec يُطلب تنفيذه، أو قسم موجود يُتجاهل —
  كل قسم يُحاسب: نفّذ أو أُوقف، لا تخطٍّ صامت؛
- فشل قسم = توقف ما بعده (§2.4)؛
- أمر خارج القائمة البيضاء / وصول بلا منح / ملف خارج النطاق —
  تفرضها وحدات المحرك (execution_engine/access_gateway)؛
- قرار مالك من النظام — تفرضه owner_gate؛
- تقرير ناقص أو زائد — يفرضه report_builder.

الحقول التي يحسبها المحرك بنفسه (المصدر 0): VERDICT و
HARD STOPS FIRED وحقول وضع الكتابة الثلاثة و DECISIONS و
ZERO-WRITE PROOF (بطارية المحرك + مخرج قسمه). بقية الحقول تُملأ
من أقسامها المربوطة صراحة في القالب ``(§N)`` — بلا ربط موضعي.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from eoe.access_gateway import (
    AccessAdmission,
    AccessDenied,
    AccessLedger,
    EoeGrant,
    GrantorService,
)
from eoe.execution_engine import (
    ExecutionEngine,
    ExecutionHardStop,
    IsolationLevel,
    SectionExecutionPlan,
)
from eoe.order_parser import (
    ExecutionMode,
    GrantKind,
    OrderSpec,
    parse_order,
)
from eoe.owner_gate import OwnerDecisionViolation, OwnerGate
from eoe.proofs import ProofBattery
from eoe.push_engine import NonceLedger, OwnerApprovalService, PushEngine, PushRejected
from eoe.report_builder import Report, ReportRejected, build_report

#: حقول يحسبها المحرك حصرًا — لا يقربها أي قسم.
ENGINE_FIELDS = {
    "VERDICT", "HARD STOPS FIRED", "DECISIONS",
    "GRANTS_USED", "FILES_CHANGED", "PUSHES",
}

#: مسبار الكتابة الداخلي — أمر ثابت من المحرك لا من الأمر.
_WRITE_PROBE = (
    "python", "-c",
    "import sys\n"
    "try:\n"
    "    open('/work/.eoe-write-probe', 'w').write('x')\n"
    "    print('PROBE-WROTE')\n"
    "except OSError as error:\n"
    "    print('PROBE-BLOCKED', type(error).__name__, error.errno)\n"
    "    sys.exit(0)\n"
    "sys.exit(3)\n",
)


@dataclass
class EoeResult:
    """نتيجة تنفيذ أمر كامل — التقرير النهائي أو الجزئي + الأحداث."""

    verdict: str
    report: Report | None
    hard_stops: list[str] = field(default_factory=list)
    section_states: dict[int, str] = field(default_factory=dict)
    grants_used: list[dict] = field(default_factory=list)
    pushes: list[dict] = field(default_factory=list)
    executed_sections: list[int] = field(default_factory=list)


class EoeHardStop(Exception):
    """توقف صلب من المُنسّق — يحمل السبب المقروء."""


class EoeEngine:
    """محرك الأوامر — يُنسّق الوحدات ويحاسب كل قسم ولا يتخطى صامتًا."""

    def __init__(
        self,
        manager,
        *,
        grantor_key: bytes,
        approval_key: bytes,
        on_event: Callable[[str, dict], None] | None = None,
        work_base: str = "",
        working_repo: str = "",
        now: Callable[[], float] = time.time,
    ) -> None:
        self._manager = manager
        self._on_event = on_event or (lambda kind, payload: None)
        self._now = now
        self._working_repo = working_repo
        self._grantor = GrantorService(grantor_key)
        self._ledger = AccessLedger()
        self._admission = AccessAdmission(self._ledger, self._grantor, now=now)
        self._approvals = OwnerApprovalService(approval_key)
        self._execution = ExecutionEngine(
            manager, self._admission, work_base=work_base
        )
        self._push = PushEngine(
            manager, self._approvals, NonceLedger(),
            self._admission, work_base=work_base,
        )
        self.owner_gate = OwnerGate()

    # -- نقطة الدخول -------------------------------------------------------

    def approve_grant(self, proposal: EoeGrant) -> EoeGrant:
        """قناة المالك لتوقيع منحة مقترحة (تستدعيها الواجهة بعد موافقته)."""
        return self._grantor.approve(proposal)

    def sign_push_approval(
        self, *, repository: str, branch: str, commit_sha: str, files_digest: str
    ):
        """قناة المالك لتوقيع موافقة دفع واحدة (بعد موافقته عبر الواجهة)."""
        return self._approvals.sign(
            repository=repository, branch=branch,
            commit_sha=commit_sha, files_digest=files_digest,
        )

    def run_order(
        self,
        order_text: str,
        *,
        approve_grants: Callable[[list[EoeGrant]], list[EoeGrant]] | None = None,
        approve_push: Callable[[dict], object | None] | None = None,
    ) -> EoeResult:
        """تنفيذ أمر كامل — الموافقات عبر callbacks المالك (الواجهة)."""
        result = EoeResult(verdict="HARD STOP", report=None)
        try:
            parsed = parse_order(order_text)
            if not parsed.ok or parsed.spec is None:
                raise EoeHardStop("فشل تحليل الأمر", parsed.reason)
            spec = parsed.spec
            self._execution.set_whitelist(tuple(spec.command_whitelist))
            self._emit("order.parsed", {
                "sections": len(spec.sections),
                "mode": spec.execution_mode.value,
                "stops": len(spec.hard_stop_conditions),
                "decisions": len(spec.owner_decisions),
                "template_fields": len(spec.report_template),
                "repository": spec.repository,
                "branch": spec.branch,
                "access_requests": [r.describe() for r in spec.access_requests],
            })
            self._check_baseline(spec)
            grants = self._issue_grants(spec, approve_grants)
            self._run_sections(spec, result)
            if (
                spec.execution_mode is ExecutionMode.WRITE_AND_PUSH
                and any(s.commands for s in spec.sections)
                and not result.hard_stops
            ):
                self._maybe_push(spec, result, approve_push)
            report = self._build_report(spec, result)
            result.report = report
            result.verdict = report.verdict
            self._emit("report.ready", {
                "verdict": report.verdict,
                "artifact_hash": report.artifact_hash,
                "lines": len(report.lines),
            })
            return result
        except (EoeHardStop, ExecutionHardStop, PushRejected,
                OwnerDecisionViolation, ReportRejected) as stop:
            reason = getattr(stop, "reason", None) or type(stop).__name__
            detail = str(stop)
            result.hard_stops.append(f"{reason}: {detail}")
            self._emit("hard_stop.fired", {"reason": str(reason), "detail": detail})
            try:
                parsed = parse_order(order_text)
                if parsed.ok and parsed.spec is not None:
                    report = self._build_report(parsed.spec, result, stopped=True)
                    result.report = report
                    result.verdict = "HARD STOP"
            except Exception:  # التقرير الجزئي أفضل جهد — التوقف هو الحقيقة
                pass
            return result

    # -- الأساس -------------------------------------------------------------

    def _check_baseline(self, spec: OrderSpec) -> None:
        """إن اشترط الأمر فحص الأساس: HEAD == origin/main للمستودع العامل."""
        demands_baseline = any(
            "الأساس" in stop or "baseline" in stop.lower()
            for stop in spec.hard_stop_conditions
        )
        if not demands_baseline or not self._working_repo:
            return
        import subprocess

        def _rev(ref: str) -> str:
            return subprocess.run(
                ["git", "-C", self._working_repo, "rev-parse", ref],
                capture_output=True, text=True, timeout=15, check=False,
            ).stdout.strip()

        head, origin = _rev("HEAD"), _rev("origin/main")
        if not head or not origin or head != origin:
            raise EoeHardStop(
                "انحراف الأساس",
                f"HEAD {head[:10]} != origin/main {origin[:10]} — لا عمل بأساس منحرف",
            )

    # -- المنح ---------------------------------------------------------------

    def _issue_grants(
        self,
        spec: OrderSpec,
        approve_grants: Callable[[list[EoeGrant]], list[EoeGrant]] | None,
    ) -> list[EoeGrant]:
        """اقتراح منح الأمر → موافقة المالك → تفعيل في الدفتر."""
        proposals = [self._grantor.propose(r) for r in spec.access_requests]
        self._emit("grant.requested", {
            "proposals": [
                {"grant_id": g.grant_id, "kind": g.kind.value,
                 "scope": g.scope.value, "target": g.target}
                for g in proposals
            ],
        })
        if not proposals:
            return []
        if approve_grants is None:
            raise EoeHardStop(
                "وصول بلا منح سارية",
                "الأمر يطلب منحًا ولا قناة موافقة — بلا موافقة لا وصول",
            )
        approved = approve_grants(list(proposals))
        if not approved:
            raise EoeHardStop(
                "وصول بلا منح سارية", "المالك لم يوافق على أي منحة — لا وصول"
            )
        for grant in approved:
            if grant.state.value != "APPROVED":
                raise EoeHardStop(
                    "وصول بلا منح سارية",
                    f"المنحة {grant.grant_id} غير موقعة بعد الموافقة",
                )
            self._ledger.register(grant)
        self._emit("grant.approved", {
            "grants": [g.grant_id for g in approved],
        })
        return approved

    # -- الأقسام ---------------------------------------------------------------

    def _run_sections(self, spec: OrderSpec, result: EoeResult) -> None:
        write_mode = spec.execution_mode is not ExecutionMode.READ_ONLY
        write_roots = tuple(
            g.target for g in self._ledger.all()
            if g.kind is GrantKind.PATH_GRANT
            and g.scope.value == "read_write"
            and g.state.value == "APPROVED"
        )
        read_root = next(
            (
                g.target for g in self._ledger.all()
                if g.kind is GrantKind.PATH_GRANT and g.state.value == "APPROVED"
                and Path(g.target).is_dir()
            ),
            "",
        )
        battery = ProofBattery(
            git_root=self._working_repo,
            db_targets=(
                (str(Path(read_root) / "agent_hub.db"),)
                if read_root and (Path(read_root) / "agent_hub.db").is_file()
                else ()
            ),
            file_roots=(read_root,) if read_root else (),
        )
        for section in spec.sections:
            if section.is_report_template or not (
                section.commands or section.decision_ids or section.requirements
            ):
                result.section_states[section.number] = "مُعلن (بلا تنفيذ)"
                self._emit("section.done", {
                    "section": section.number, "title": section.title,
                    "state": "declared",
                })
                continue
            self._emit("section.started", {
                "section": section.number, "title": section.title,
                "commands": [list(c) for c in section.commands],
                "declared": {
                    "reads": list(read_root and [read_root] or []),
                    "writes": list(write_roots),
                },
            })
            before = battery.capture(f"§{section.number}-before")
            try:
                if section.commands:
                    plan = SectionExecutionPlan(
                        section_number=section.number,
                        commands=section.commands,
                        isolation=(
                            IsolationLevel.BUILD_ISOLATION
                            if write_mode
                            else IsolationLevel.FULL_ISOLATION
                        ),
                        reads=(read_root,) if read_root else (),
                        writes=(
                            section.landing_paths if write_mode else ()
                        ),
                    )
                    self._execution.run_section(plan)
                if section.decision_ids:
                    self._run_decision_section(section)
                if (
                    spec.execution_mode is ExecutionMode.READ_ONLY
                    and read_root
                ):
                    self._write_probe(section.number)
            except (ExecutionHardStop, OwnerDecisionViolation) as stop:
                result.section_states[section.number] = "HARD STOP"
                raise
            after = battery.capture(f"§{section.number}-after")
            diffs = before.differs_from(after)
            if write_mode:
                outside = [
                    d for d in diffs
                    if d.startswith("files:")
                    and not any(root in d for root in write_roots)
                ]
                if outside:
                    raise EoeHardStop(
                        "تعديل خارج نطاق المنحة",
                        f"§{section.number}: {outside[0][:200]}",
                    )
            elif diffs:
                raise EoeHardStop(
                    "كتابة في READ_ONLY",
                    f"§{section.number}: البصمة تغيرت — {diffs[0][:200]}",
                )
            result.section_states[section.number] = "منفذ"
            result.executed_sections.append(section.number)
            self._emit("section.proof", {
                "section": section.number,
                "before": before.git_status or before.tables[:3] and str(before.tables[:3]) or "",
                "identical": not diffs,
                "diffs": diffs[:3],
            })
            self._emit("section.done", {
                "section": section.number, "state": "executed",
            })

    def _run_decision_section(self, section) -> None:
        """قسم قرارات: تسجيل القرارات + تسليم مخرجات أوامره أدلةً للبوابة.

        الأدلة تُسلم عبر ``submit_evidence`` فيفحصها الفاحص الآلي — أي
        تسلل قرار من أي دور يوقف المحرك (§7.2).
        """
        decisions = _decisions_of(section)
        for decision_id, question in decisions:
            self.owner_gate.register_decision(decision_id, question)
        if not section.commands:
            return
        evidence = {
            f"مخرج-أمر-{index + 1}": outcome.stdout.strip()[:600]
            for index, outcome in enumerate(
                [
                    o for o in self._execution.executions
                    if o.sandbox_id.startswith(f"s{section.number}-")
                ]
            )
        }
        for decision_id, _ in decisions:
            if evidence:
                self.owner_gate.submit_evidence(
                    decision_id, dict(evidence), role="implementer"
                )

    def _write_probe(self, section_number: int) -> None:
        """مسبار الكتابة الداخلي: الكتابة على التحميل للقراءة يجب أن تفشل."""
        plan = SectionExecutionPlan(
            section_number=section_number,
            commands=(_WRITE_PROBE,),
            isolation=IsolationLevel.FULL_ISOLATION,
        )
        # المسبار أمر محرك لا أمر أمرٍ — يمر بلا قائمة بيضاء
        probe = self._execution._execute_one(plan, _WRITE_PROBE)
        if "PROBE-WROTE" in probe.stdout:
            raise EoeHardStop(
                "كتابة في READ_ONLY",
                f"§{section_number}: المسبار كتب داخل التحميل للقراءة — العزل مخرق",
            )
        self._emit("section.proof", {
            "section": section_number, "inside_probe": probe.stdout.strip()[:80],
        })

    # -- الدفع -------------------------------------------------------------------

    def _maybe_push(self, spec: OrderSpec, result: EoeResult, approve_push) -> None:
        """في WRITE_AND_PUSH: التزام + دفع بموافقة موقعة عبر callback."""
        if not self._working_repo:
            return
        commit_message = f"EOE: {spec.repository} — {spec.objective[:60]}".strip()
        scope = tuple(
            g.target for g in self._ledger.all()
            if g.kind is GrantKind.PATH_GRANT
            and g.scope.value == "read_write"
            and g.state.value == "APPROVED"
        )
        commit_sha, staged = self._push.commit_in_sandbox(
            self._working_repo, commit_message, scope
        )
        files_digest, files = self._push.verify_before_push(
            staged, _head_of(self._working_repo), scope
        )
        self._emit("push.approval_needed", {
            "commit_sha": commit_sha[:12], "files": list(files)[:10],
            "files_count": len(files),
        })
        if approve_push is None:
            raise EoeHardStop(
                "دفع بلا موافقة موقعة",
                "الوضع WRITE_AND_PUSH بلا قناة موافقة المالك — لا دفع",
            )
        approval = approve_push({
            "commit_sha": commit_sha, "files_digest": files_digest,
            "repository": spec.repository, "branch": spec.branch or "main",
        })
        record = self._push.push(
            repo_root=self._working_repo,
            branch=spec.branch or "main",
            commit_message=commit_message,
            scope_paths=scope,
            approval=approval,
            remote_url="origin",
            staged=staged,
            commit_sha=commit_sha,
        )
        result.pushes.append({
            "before": record.before_sha[:12], "after": record.after_sha[:12],
            "pushed": record.pushed, "files": list(record.files),
            "rollback_certificate": record.rollback_certificate or "NONE",
        })
        self._emit("push.done", {"pushed": record.pushed})

    # -- التقرير -------------------------------------------------------------------

    def _build_report(
        self, spec: OrderSpec, result: EoeResult, *, stopped: bool = False
    ) -> Report:
        write_mode = spec.execution_mode is not ExecutionMode.READ_ONLY
        # استخدام المنح يُلتقط لحظة البناء — لا قبل التنفيذ
        result.grants_used = list(self._admission.usage_log)
        values: dict[str, str] = {}
        for name, source in spec.report_template:
            if name == "VERDICT":
                values[name] = "HARD STOP" if stopped or result.hard_stops else "PASS"
            elif name == "HARD STOPS FIRED":
                values[name] = (
                    str(len(result.hard_stops)) if result.hard_stops else "NONE"
                )
            elif name == "DECISIONS":
                values[name] = self._decisions_summary(spec)
            elif name == "GRANTS_USED":
                values[name] = (
                    "; ".join(
                        f"{u['kind']}→{u['target']} ({'كتابة' if u['write'] else 'قراءة'})"
                        for u in result.grants_used
                    ) or "NONE"
                )
            elif name == "FILES_CHANGED":
                values[name] = self._files_changed(result)
            elif name == "PUSHES":
                values[name] = (
                    "; ".join(
                        f"{p['before']}→{p['after']} pushed={p['pushed']} "
                        f"rollback_cert={'نعم' if p['rollback_certificate'] != 'NONE' else 'لا'}"
                        for p in result.pushes
                    ) or "NONE"
                )
            elif name == "ZERO-WRITE PROOF":
                values[name] = self._zero_write_value(source, result)
            else:
                if source == 0:
                    raise ReportRejected(
                        f"حقل {name!r} بلا ربط قسم (§N) وليس من حقول المحرك"
                    )
                values[name] = self._section_output(source)
        return build_report(
            template=[name for name, _ in spec.report_template],
            values=values,
            verdict="HARD STOP" if stopped or result.hard_stops else "PASS",
            write_mode=write_mode,
        )

    def _section_output(self, number: int) -> str:
        """مخرج القسم — آخر stdout لأوامره، أول 400 حرف، كما هو."""
        for outcome in reversed(self._execution.executions):
            if outcome.command and f"s{number}-" in outcome.sandbox_id:
                return outcome.stdout.strip()[:400] or f"(بلا مخرج §{number})"
        return f"(لم يُنفَّذ §{number})"

    def _decisions_summary(self, spec: OrderSpec) -> str:
        if not spec.owner_decisions:
            return "NONE"
        return "; ".join(
            f"{decision_id} بانتظار المالك"
            for decision_id, _ in spec.owner_decisions
        )

    def _files_changed(self, result: EoeResult) -> str:
        files = sorted(
            {
                target
                for outcome in self._execution.executions
                for target, _ in outcome.custody_files
            }
        )
        return "; ".join(files) if files else "NONE"

    def _zero_write_value(self, source: int, result: EoeResult) -> str:
        engine_proof = (
            "بطارية المحرك: البصمات متطابقة قبل/بعد لكل قسم منفذ"
            if not result.hard_stops
            else "بطارية المحرك: توقفت عند أول خرق"
        )
        if source:
            return f"{engine_proof}؛ من داخل الركيزة: {self._section_output(source)}"
        return engine_proof

    def _emit(self, kind: str, payload: dict) -> None:
        self._on_event(kind, payload)


def _decisions_of(section):
    """استخراج (معرف، سؤال) من أسطر DN: في جسم القسم."""
    import re

    pattern = re.compile(r"^(D\d+)\s*[:：]\s*(.+)$", re.MULTILINE)
    return pattern.findall(section.body)


def _head_of(repo: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=15, check=False,
    ).stdout.strip()
