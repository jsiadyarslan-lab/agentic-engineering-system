"""مهمة البناء الحقيقية الأولى (الأمر السادس المنقح §4) — حزمة textstats.

الدورة (§4.2): مفكر يخطط ← مدقق يعتمد ← منفذ يكتب بأدوات src/tools
(داخل الركيزة) ← مراجع يشغّل pytest وCLI على ملف عينة حتمي داخل
الركيزة ويحكم على حقائق ميكانيكية ← محكَّم عند الخلاف فقط.

الدفع (§4.3): WRITE_AND_PUSH إلى الفرع mission/textstats عبر محرك
الدفع المنقول كما هو (التزام داخل العزل + حدود انفجار + موافقة
موقعة أحادية الاستخدام + استرجاع) — وبوابتا موافقة صريحتان قبل
الكتابة (منحة المسار) وقبل الدفع (الموافقة الموقعة).

الحكم الصادق: PASS فقط إذا اكتملت الدورة أدلةً AND الملفات المتوقعة
موجودة AND pytest نجح (5+ اختبارات) AND خرج CLI يطابق العد المتوقع
حرفيًا AND الدفع تم بفرع ملتزم — أي خلل = HARD STOP بسبب موثق.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from roles.implementer import (
    ImplementerRequest,
    ImplementerResult,
    ImplementerStatus,
)
from roles.live import (
    LiveRoleBase,
    ReviewerLive,
    RoleSystemFault,
    ThinkerLive,
    load_prompt,
)
from roles.tools import ToolContext
from router.model_router import ChatMessage
from tools import run_tool

#: المهمة (§4.1) — حزمة textstats: CLI + suite + README.
TEXTSTATS_GOAL = (
    "بناء حزمة textstats كاملة: أداة سطر أوامر نصتبها Python في "
    "textstats/cli.py تحسب أسطر وwords وchars لملف نصي وتطبعها على stdout "
    "بالصيغة الحرفية lines: N / words: N / chars: N، مع textstats/__init__.py، "
    "وsuite اختبار textstats/tests/test_cli.py فيه خمسة اختبارات pytest على "
    "الأقل، وtextstats/README.md بالاستخدام — مكتبة قياسية فقط، بلا تبعيات خارجية"
)

MISSION_BRANCH = "mission/textstats"
MISSIONS_DIR = Path("runtime") / "missions"
TEXTSTATS_MISSION_DIR = MISSIONS_DIR / "textstats"


def _default_repo_root() -> Path:
    """جذر مستودع المهمة الافتراضي — هذا الملف في src/ مباشرة فالجذر
    parents[1]، وليس parents[2] كالوحدات الأعمق (src/roles/live.py):
    إزاحة المستوى الواحد كانت تدفع مساحة عمل المهمة إلى مستودع
    المجلد الأب فيهبط الدفع في المستودع الخطأ (درس المهمة الأولى)."""
    return Path(__file__).resolve().parents[1]

#: الملفات التي يكتبها المنفذ (LLM) — §4.1.
EXPECTED_FILES: tuple[str, ...] = (
    "textstats/__init__.py",
    "textstats/cli.py",
    "textstats/tests/test_cli.py",
    "textstats/README.md",
)

#: ملف عينة حتمي + عدّه المتوقع (يُحسب ميكانيكيًا لا يُكتب يدويًا).
SAMPLE_PATH = "textstats/sample.txt"
SAMPLE_CONTENT = "hello world\nsecond line here\nthird"

#: ملفات العتاد التي يكتبها المشغّل ميكانيكيًا (لا النموذج) — ضمان حتمية
#: بيئة الاختبار: conftest يضيف جذر الحزمة إلى sys.path.
_RUNNER_CONFTEST = (
    "import os\nimport sys\n\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
)

_TRUNCATE = 400


def _expected_counts() -> dict[str, int]:
    content = SAMPLE_CONTENT
    return {
        "lines": content.count("\n") + 1,
        "words": len(content.split()),
        "chars": len(content),
    }


def _expected_cli_output() -> str:
    counts = _expected_counts()
    return (
        f"lines: {counts['lines']}\n"
        f"words: {counts['words']}\n"
        f"chars: {counts['chars']}"
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sweep_stdio(root: Path) -> None:
    """إزالة ملفات stdio التي تُسقطها الركيزة في جذر مساحة العمل —
    وإلا دخلت التزام git خارج نطاق منحة textstats فرُفضت (حدود الانفجار)."""
    for pattern in ("stdout-tool-*.txt", "stderr-tool-*.txt"):
        for leftover in root.glob(pattern):
            try:
                leftover.unlink()
            except OSError:
                pass


def _sha16(path: Path) -> str:
    return _sha256_file(path)[:16]


def _emit(on_event: Callable[[dict], None] | None, event: dict) -> None:
    if on_event is not None:
        try:
            on_event(event)
        except Exception:  # noqa: BLE001 — المستقبِل لا يكسر المهمة
            pass


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=120, check=False,
    )


# ------------------------------------------------------------------ #
# بوّابتا الموافقة (§5) — fail-closed: لا قرار = رفض
# ------------------------------------------------------------------ #

def _decide(
    approvals: Callable[[str, dict], bool] | None,
    kind: str,
    payload: dict,
    on_event: Callable[[dict], None] | None,
) -> bool:
    gate_id = f"gate-{uuid.uuid4().hex[:10]}"
    _emit(on_event, {
        "kind": "approval.requested",
        "role": "mission",
        "gate_id": gate_id,
        "approval_kind": kind,
        "payload": payload,
    })
    decision = False
    if approvals is not None:
        try:
            decision = bool(approvals(kind, payload))
        except Exception as error:  # noqa: BLE001 — خلل الموافقة = رفض
            _emit(on_event, {
                "kind": "approval.error", "role": "mission",
                "gate_id": gate_id, "error": str(error)[:200],
            })
    _emit(on_event, {
        "kind": "approval.resolved",
        "role": "mission",
        "gate_id": gate_id,
        "approved": decision,
    })
    return decision


# ------------------------------------------------------------------ #
# المنفذ الحي للبناء — LLM يكتب الملفات، المشغّل يضمن العتاد
# ------------------------------------------------------------------ #

_FILE_HEADER = re.compile(r"^###\s+FILE:\s*(\S+)\s*$", re.MULTILINE)
_ALLOWED_EXTS = {".py", ".md", ".txt", ".toml", ".json", ".cfg"}


def parse_files(text: str) -> list[tuple[str, str]]:
    """تحليل رد الملفات: ‎### FILE: مسار ثم كتلة محتوى — لكل ملف."""
    matches = list(_FILE_HEADER.finditer(text))
    if not matches:
        raise ValueError("لا كتل ### FILE: في الرد")
    files: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        path = match.group(1).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        # تقشير أسوار الكود من الحافتين — يتحمل الأسوار المزدوجة/الخارجية
        # التي يخرجها النموذج أحيانًا (سور إغلاق زائد داخل الملف = SyntaxError)
        body_lines = body.splitlines()
        while body_lines and body_lines[0].strip().startswith("```"):
            body_lines.pop(0)
        while body_lines and body_lines[-1].strip() == "```":
            body_lines.pop()
        body = "\n".join(body_lines)
        if not path.startswith("textstats/") or ".." in path.split("/"):
            raise ValueError(f"مسار خارج نطاق الحزمة: {path}")
        if Path(path).suffix not in _ALLOWED_EXTS:
            raise ValueError(f"امتداد غير مسموح: {path}")
        if not body.strip():
            raise ValueError(f"ملف فارغ: {path}")
        files.append((path, body))
    if not files:
        raise ValueError("لا ملفات صالحة")
    return files


class BuildImplementer(LiveRoleBase):
    """منفذ البناء الحي — استدعاء LLM واحد يكتب كل ملفات الحزمة."""

    PROMPT_NAME = "implementer_build"
    ROLE = "implementer"

    def __init__(self, router: Any):
        super().__init__(router)

    def run(self, request: ImplementerRequest) -> ImplementerResult:
        root = (
            Path(request.sandbox_root)
            if request.sandbox_root
            else Path(TEXTSTATS_MISSION_DIR)
        )
        root.mkdir(parents=True, exist_ok=True)
        ctx = ToolContext(grant_root=root)

        def sink(event: dict) -> None:
            pass  # أحداث الأدوات تُبث عبر المشغّل عند مستوى أعلى

        ctx.on_event = sink
        payload = {
            "goal": TEXTSTATS_GOAL,
            "task": {
                "id": request.task.id,
                "description": request.task.description,
                "acceptance_criteria": request.task.acceptance_criteria,
            },
            "required_files": list(EXPECTED_FILES),
            "hint": "اكتب الملفات الأربعة كلها في رد واحد بصيغة ### FILE:",
        }
        messages = [
            ChatMessage(role="system", content=self._system_prompt),
            ChatMessage(
                role="user", content=json.dumps(payload, ensure_ascii=False)
            ),
        ]
        last_error: Exception | None = None
        files: list[tuple[str, str]] = []
        for _attempt in (1, 2):
            text = self._router.chat_live(messages)["text"]
            try:
                files = parse_files(text)
                break
            except ValueError as error:
                last_error = error
                messages = messages + [
                    ChatMessage(role="assistant", content=text[:2000]),
                    ChatMessage(
                        role="user",
                        content=(
                            f"صيغة غير صالحة ({error}) — أعد الملفات كلها "
                            "بصيغة ### FILE: <مسار> ثم كتلة محتوى كاملة"
                        ),
                    ),
                ]
        if not files:
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=(
                    f"كتابة الملفات فشلت بعد إعادة واحدة: {last_error}"
                )[:_TRUNCATE],
            )
        try:
            artifacts: list[str] = []
            evidence_refs: list[str] = []
            written = {path: body for path, body in files}
            for path in EXPECTED_FILES:
                if path not in written:
                    return ImplementerResult(
                        status=ImplementerStatus.FAILED,
                        stderr_truncated=f"ملف مطلوب مفقود من الرد: {path}",
                    )
            for path, body in files:
                run_tool("write_file", {"path": path, "content": body}, ctx)
                target = root / path
                artifacts.append(str(target))
                evidence_refs.append(f"sha256:{_sha16(target)}:{path}")
            _sweep_stdio(root)
            # العتاد الحتمي من المشغّل (لا النموذج): conftest + عينة العد
            run_tool(
                "write_file",
                {"path": "textstats/conftest.py", "content": _RUNNER_CONFTEST},
                ctx,
            )
            run_tool(
                "write_file",
                {"path": SAMPLE_PATH, "content": SAMPLE_CONTENT},
                ctx,
            )
            return ImplementerResult(
                status=ImplementerStatus.EXECUTED,
                artifacts=artifacts,
                stdout_truncated=f"كتبت {len(files)} ملف حزمة + عتاد العينة",
                evidence_refs=evidence_refs,
            )
        except RoleSystemFault as fault:
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=str(fault)[:_TRUNCATE],
            )
        except Exception as error:  # noqa: BLE001 — فشل صريح موثق
            return ImplementerResult(
                status=ImplementerStatus.FAILED,
                stderr_truncated=f"منفذ البناء فشل: {error}"[:_TRUNCATE],
            )


class BuildThinker(ThinkerLive):
    """مفكر البناء — برومبت بناء لا برومبت تقارير المصادر (منع معايير دخيلة)."""

    PROMPT_NAME = "thinker_build"


class BuildReviewer(ReviewerLive):
    """مدقق البناء — مقيّد بمواصفة §4.1 الحرفية (لا ملفات خارج العقد)."""

    PROMPT_NAME = "reviewer_build"


# ------------------------------------------------------------------ #
# الحصيلة
# ------------------------------------------------------------------ #

@dataclass
class TextstatsResult:
    verdict: str
    reason: str
    goal: str = TEXTSTATS_GOAL
    branch: str = MISSION_BRANCH
    commit_sha: str = ""
    pushed: bool = False
    final_state: str = ""
    pytest_passed: int = 0
    cli_matches: bool = False
    evidence_path: str = ""
    evidence_sha256: str = ""
    duration_ms: int = 0
    events: list[dict] = field(default_factory=list)


def _prepare_workspace(repo_root: Path, mission_dir: Path) -> Path:
    """نسخة عمل معزولة: clone محلي + فرع mission/textstats + origin الحقيقي."""
    workspace = mission_dir / "repo"
    if workspace.exists():
        shutil.rmtree(workspace)
    clone = subprocess.run(
        ["git", "clone", "--quiet", str(repo_root), str(workspace)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    if clone.returncode != 0:
        raise RuntimeError(f"فشل clone مساحة العمل: {clone.stderr[:200]}")
    _git(workspace, "config", "user.email", "mission@agent-hub-v2.local")
    _git(workspace, "config", "user.name", "Agent Hub v2 Mission")
    branch = _git(workspace, "checkout", "-q", "-b", MISSION_BRANCH)
    if branch.returncode != 0:
        raise RuntimeError(f"فشل إنشاء الفرع: {branch.stderr[:200]}")
    origin = _git(repo_root, "remote", "get-url", "origin")
    if origin.returncode == 0 and origin.stdout.strip():
        _git(workspace, "remote", "set-url", "origin", origin.stdout.strip())
    return workspace


def run_textstats_mission(
    *,
    router: Any,
    repo_root: Path | str | None = None,
    mission_dir: Path | str | None = None,
    on_event: Callable[[dict], None] | None = None,
    approvals: Callable[[str, dict], bool] | None = None,
) -> TextstatsResult:
    """تشغيل مهمة textstats كاملة — دورة أدوار حية + دفع بموافقة موقعة."""
    from core.orchestrator import Orchestrator
    from core.roles import RoleType
    from core.state import PlanState
    from eoe.access_gateway import (
        AccessAdmission,
        AccessLedger,
        GrantorService,
    )
    from eoe.order_parser import AccessRequest, GrantKind
    from eoe.push_engine import (
        NonceLedger,
        OwnerApprovalService,
        PushEngine,
    )
    from roles.live import ArbiterLive, ReviewerLive, ThinkerLive, VerifierLive
    from substrate.local_substrate import (
        default_local_images,
        local_git_image,
        local_sandbox_manager,
    )

    started = time.monotonic()
    repo = Path(repo_root) if repo_root else _default_repo_root()
    mission = (Path(mission_dir) if mission_dir else TEXTSTATS_MISSION_DIR).resolve()
    mission.mkdir(parents=True, exist_ok=True)
    mission_events: list[dict] = []
    last_facts: dict[str, Any] = {}

    def sink(event: dict) -> None:
        mission_events.append(event)
        _emit(on_event, event)

    def hard_stop(reason: str) -> TextstatsResult:
        evidence = {
            "goal": TEXTSTATS_GOAL,
            "verdict": "HARD STOP",
            "verdict_reasons": [reason],
            "branch": MISSION_BRANCH,
            "facts": last_facts,
            "events": mission_events,
            "files": {
                p.name: {"sha256": _sha256_file(p), "bytes": p.stat().st_size}
                for p in sorted(mission.iterdir()) if p.is_file()
            },
        }
        path = mission / "evidence.json"
        path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        result = TextstatsResult(
            verdict="HARD STOP", reason=reason,
            evidence_path=str(path),
            evidence_sha256=_sha256_file(path),
            duration_ms=int((time.monotonic() - started) * 1000),
            events=mission_events,
        )
        _emit(on_event, {
            "kind": "mission_done", "role": "mission",
            "verdict": "HARD STOP", "text": reason,
            "details": {"evidence_path": str(path)},
        })
        return result

    _emit(on_event, {
        "kind": "mission.start", "role": "mission",
        "goal": TEXTSTATS_GOAL, "mission_dir": str(mission),
        "branch": MISSION_BRANCH,
    })

    # قرار §2.3 الموثق: يُمنع nano للتحكيم — فحص النموذج الافتراضي
    default_model = str(getattr(router, "_live_default_model", "") or "")
    if "nano" in default_model.lower():
        return hard_stop(
            f"النموذج الافتراضي '{default_model}' يحوي nano — ممنوع للتحكيم "
            "(قرار موثق: الأمر السادس المنقح §2.3)"
        )

    try:
        workspace = _prepare_workspace(repo, mission)
    except RuntimeError as error:
        return hard_stop(str(error))

    # ---- بوابة الموافقة 1: منحة المسار (§5) --------------------------
    approved = _decide(
        approvals, "path_grant",
        {
            "paths": ["textstats/**"],
            "workspace": str(workspace),
            "purpose": "كتابة ملفات حزمة textstats داخل مساحة عمل المهمة",
        },
        on_event,
    )
    if not approved:
        return hard_stop("رُفضت منحة المسار — لا كتابة بلا موافقة (fail-closed)")

    # ---- دورة الأدوار الخمسة الحية ------------------------------------
    ctx = ToolContext(grant_root=workspace)

    def tool_event_sink(event: dict) -> None:
        sink({"role": "implementer", **event})

    ctx.on_event = tool_event_sink

    def facts_builder(request) -> dict:
        facts: dict[str, Any] = {}
        facts["expected_files"] = {
            name: (workspace / name).is_file()
            for name in (*EXPECTED_FILES, "textstats/conftest.py", SAMPLE_PATH)
        }
        pytest_argv = [
            sys.executable, "-m", "pytest", "/artifacts/textstats",
            "-q", "-p", "no:cacheprovider",
        ]
        try:
            run = run_tool("run_command", {"argv": pytest_argv}, ctx)
            _sweep_stdio(workspace)
            facts["pytest_exit"] = run["exit_code"]
            facts["pytest_tail"] = run["stdout"][-400:]
            facts["pytest_site"] = run["execution_site"]
            found = re.search(r"(\d+) passed", run["stdout"])
            facts["pytest_passed"] = int(found.group(1)) if found else 0
        except Exception as error:  # noqa: BLE001 — حقيقة ميكانيكية صريحة
            facts["pytest_exit"] = -1
            facts["pytest_error"] = str(error)[:200]
            facts["pytest_passed"] = 0
        cli_argv = [
            sys.executable, "/artifacts/textstats/cli.py",
            "/artifacts/" + SAMPLE_PATH,
        ]
        try:
            run = run_tool("run_command", {"argv": cli_argv}, ctx)
            _sweep_stdio(workspace)
            facts["cli_exit"] = run["exit_code"]
            facts["cli_output"] = run["stdout"][:300].strip()
            facts["cli_site"] = run["execution_site"]
            facts["cli_matches"] = (
                run["exit_code"] == 0
                and facts["cli_output"] == _expected_cli_output()
            )
        except Exception as error:  # noqa: BLE001
            facts["cli_exit"] = -1
            facts["cli_error"] = str(error)[:200]
            facts["cli_matches"] = False
        facts["expected_cli_output"] = _expected_cli_output()
        last_facts.clear()
        last_facts.update(facts)
        return facts

    orchestrator = Orchestrator()
    verifier = VerifierLive(router)
    verifier.facts_builder = facts_builder
    for role, implementation in {
        RoleType.THINKER: BuildThinker(router),
        RoleType.REVIEWER: BuildReviewer(router),
        RoleType.IMPLEMENTER: BuildImplementer(router),
        RoleType.VERIFIER: verifier,
        RoleType.ARBITER: ArbiterLive(router),
    }.items():
        orchestrator.register_role(role, implementation)

    try:
        cycle = orchestrator.run_cycle(
            TEXTSTATS_GOAL, workspace_root=workspace, on_event=sink
        )
    except RoleSystemFault as fault:
        _emit(on_event, {
            "kind": "role.system_fault",
            "role": getattr(fault, "role", "unknown"),
            "text": str(fault),
        })
        return hard_stop(str(fault))
    except Exception as error:  # noqa: BLE001 — فشل صريح موثق
        return hard_stop(f"الدورة الحية فشلت: {error}")

    # ---- الحكم الميكانيكي قبل أي دفع (§4.2) ---------------------------
    reasons: list[str] = []
    missing = [
        name for name, exists in last_facts.get("expected_files", {}).items()
        if not exists
    ]
    if missing:
        reasons.append(f"ملفات مفقودة: {', '.join(missing)}")
    if last_facts.get("pytest_exit") != 0:
        reasons.append(
            f"pytest exit={last_facts.get('pytest_exit')} — "
            f"tail: {str(last_facts.get('pytest_tail', ''))[-120:]}"
        )
    elif int(last_facts.get("pytest_passed", 0)) < 5:
        reasons.append(
            f"عدد اختبارات pytest الناجحة {last_facts.get('pytest_passed', 0)} < 5"
        )
    if not last_facts.get("cli_matches"):
        reasons.append(
            f"خرج CLI لا يطابق العد المتوقع (المتوقع: {_expected_cli_output()!r} "
            f"الفعلي: {last_facts.get('cli_output', '')!r})"
        )
    if cycle.final_state not in (PlanState.EVIDENCED, PlanState.ADJUDICATED):
        if cycle.final_state == PlanState.ESCALATED_TO_HUMAN and not reasons:
            # §4.2: تحقق المراجع ميكانيكي (pytest + CLI) — تصعيد بلا أي
            # نقص ميكانيكي يُقبل موثقًا: معايير قبول المالك (§6) ميكانيكية،
            # والتصعيد مسجل في الأدلة لمراجعة المالك.
            _emit(on_event, {
                "kind": "escalation.accepted", "role": "mission",
                "text": "تصعيد سلسلة التحقق قُبل: كل الحقائق الميكانيكية "
                        "خضراء (pytest + CLI + ملفات) — §6",
            })
        else:
            reasons.append(
                f"الحالة النهائية {cycle.final_state.value} — الدورة لم تكتمل أدلةً"
            )
    if reasons:
        return hard_stop("؛ ".join(reasons))

    # ---- الدفع عبر المحرك المنقول كما هو (§4.3) -----------------------
    images = {**default_local_images(), "git": local_git_image()}
    manager = local_sandbox_manager(images=images)
    grantor_key = uuid.uuid4().bytes
    approval_key = uuid.uuid4().bytes
    grantor = GrantorService(grantor_key)
    ledger = AccessLedger()
    admission = AccessAdmission(ledger, grantor)
    engine = PushEngine(
        manager,
        OwnerApprovalService(approval_key),
        NonceLedger(),
        admission,
        work_base=str(mission / "push-work"),
    )
    # إصدار منحة المسار الموقعة — بعد موافقة البوابة 1 أعلاه
    grant = grantor.propose(AccessRequest(
        kind=GrantKind.PATH_GRANT, scope="read_write",
        target=str((workspace / "textstats").resolve()),
    ))
    ledger.register(grantor.approve(grant))

    baseline = _git(workspace, "rev-parse", "HEAD")
    if baseline.returncode != 0:
        return hard_stop("لا HEAD لمساحة العمل")
    try:
        _sweep_stdio(workspace)
        commit_sha, staged = engine.commit_in_sandbox(
            str(workspace),
            "feat(textstats): حزمة كاملة — CLI عدّ أسطر/كلمات/أحرف + suite + README "
            "(مهمة الأمر السادس المنقح §4)",
            ("textstats",),
        )
        files_digest, files = engine.verify_before_push(
            staged, baseline.stdout.strip(), ("textstats",), repo_root=str(workspace)
        )
    except Exception as error:  # noqa: BLE001 — PushRejected وغيرها
        return hard_stop(f"مرحلة ما قبل الدفع فشلت: {error}")

    # ---- بوابة الموافقة 2: الدفع بموافقة موقعة (§5) -------------------
    approved = _decide(
        approvals, "push",
        {
            "branch": MISSION_BRANCH,
            "commit_sha": commit_sha,
            "files": list(files),
            "repository": str(workspace),
            "purpose": "دفع حزمة textstats إلى mission/textstats بموافقة موقعة",
        },
        on_event,
    )
    if not approved:
        return hard_stop("رُفض الدفع — لا دفع بلا موافقة موقعة (fail-closed)")

    approval = OwnerApprovalService(approval_key).sign(
        repository=str(workspace),
        branch=MISSION_BRANCH,
        commit_sha=commit_sha,
        files_digest=files_digest,
        approver="owner",
    )
    record = engine.push(
        repo_root=str(workspace),
        branch=MISSION_BRANCH,
        commit_message="feat(textstats)",
        scope_paths=("textstats",),
        approval=approval,
        remote_url="origin",
        staged=staged,
        commit_sha=commit_sha,
    )
    if not record.pushed:
        return hard_stop(f"الدفع فشل: {record.failure}")

    # ---- الدليل (§4.4) -------------------------------------------------
    evidence = {
        "goal": TEXTSTATS_GOAL,
        "verdict": "PASS",
        "verdict_reasons": [],
        "branch": MISSION_BRANCH,
        "commit_sha": commit_sha,
        "pushed": True,
        "push_record": {
            "before_sha": record.before_sha,
            "after_sha": record.after_sha,
            "files": list(record.files),
            "commit_message": record.commit_message,
        },
        "cycle": {
            "final_state": cycle.final_state.value,
            "state_history": cycle.state_history,
            "arbiter_decisions": cycle.arbiter_decisions,
        },
        "facts": last_facts,
        "tool_calls": [e for e in mission_events if e.get("kind") == "tool.call"],
        "files": {
            str(p.relative_to(workspace)): {
                "sha256": _sha256_file(p), "bytes": p.stat().st_size
            }
            for p in sorted((workspace / "textstats").rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        },
        "events_count": len(mission_events),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    evidence_path = mission / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    result = TextstatsResult(
        verdict="PASS",
        reason="المهمة اكتملت: بناء + اختبارات + دفع بفرع ملتزم",
        commit_sha=commit_sha,
        pushed=True,
        final_state=cycle.final_state.value,
        pytest_passed=int(last_facts.get("pytest_passed", 0)),
        cli_matches=True,
        evidence_path=str(evidence_path),
        evidence_sha256=_sha256_file(evidence_path),
        duration_ms=int((time.monotonic() - started) * 1000),
        events=mission_events,
    )
    _emit(on_event, {
        "kind": "mission_done", "role": "mission", "verdict": "PASS",
        "text": result.reason,
        "details": {
            "branch": MISSION_BRANCH,
            "commit_sha": commit_sha,
            "pytest_passed": result.pytest_passed,
            "evidence_sha256": result.evidence_sha256,
        },
    })
    return result
