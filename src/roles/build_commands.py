"""طور أوامر البناء الحقيقية (W2-T24) — npm يُنفَّذ فعليًا بأدلة صادقة.

بطاقة W2-T23 حررت الخطوات الملفية وقالت في build_files.py حرفيًا:
«نواتج أوامر لا يُختلق نصها — تُنتج بأوامر حقيقية (بطاقة لاحقة)» —
هذه هي البطاقة. الخطوات التي تطلب معاييرها أوامرِ بناء (npm install /
npm run build / npm run preview — نصًّا أو بعلامات نواتجها:
node_modules/ وpackage-lock.json وdist/) تنفذ الأوامر فعلًا:

- ‎required_build_commands(): الأوامر التي تطلبها المعايير بترتيب
  التبعية (install قبل build قبل preview) — بلا أوامر = مهمة على
  مسارها الأصلي بلا أي تغيير في السلوك.
- ‎gather_build_prerequisites(): مساحة كل خطوة مستقلة (projects/«pid»/
  steps/«id») — ملفات الخطوات السابقة تُجلب إلى مساحة الخطوة الحالية:
  نسخ للملفات المصدرية (package.json/tsconfig/src/public...) وsymlink
  لنواتج الأوامر الثقيلة (node_modules/dist) بلا نسخها.
- ‎run_build_commands_phase(): فحص الأدوات → التجميع → تنفيذ كل أمر
  عبر run_tool("run_build_command") بأدلة exit_code/stdout/stderr
  حقيقية → جمع نواتج المعايير الموجودة على القرص كأدلة (package-lock
  .json، dist/index.html...).

فقد node/npm ليس فشل خطوة بل عائق توفير: النتيجة تحمل توقيع
BUILD_TOOLING_MISSING (مع استدعاء أداة مسجل) فيفتح المحرك حاجز
PREFLIGHT_BLOCKED قابلًا للحل بإعادة الفحص بعد التثبيت — لا حرق
موافقات مراجعة الخطة (امتداد آلية W1-T06).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

#: الأوامر الصريحة التي تذكرها المعايير نصًّا → الأمر الموحد.
_COMMAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"npm\s+install", re.IGNORECASE), "npm install"),
    (re.compile(r"npm\s+ci\b", re.IGNORECASE), "npm ci"),
    (re.compile(r"npm\s+run\s+lint\b", re.IGNORECASE), "npm run lint"),
    (re.compile(r"npm\s+run\s+build", re.IGNORECASE), "npm run build"),
    (re.compile(r"npm\s+run\s+preview", re.IGNORECASE), "npm run preview"),
    (re.compile(r"node\s+--version", re.IGNORECASE), "node --version"),
    (re.compile(r"npm\s+--version", re.IGNORECASE), "npm --version"),
)
#: علامات النواتج التي تستلزم أمرًا لم يُذكر نصًّا.
_OUTPUT_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"node_modules/", re.IGNORECASE), "npm install"),
    (re.compile(r"package-lock\.json", re.IGNORECASE), "npm install"),
    (re.compile(r"\bdist/", re.IGNORECASE), "npm run build"),
)
#: ترتيب التبعية — install يسبق lint/build يسبق preview.
_COMMAND_ORDER = {
    "node --version": 0, "npm --version": 0, "npm ci": 1,
    "npm install": 1, "npm run lint": 2, "npm run build": 3,
    "npm run preview": 4,
}
_COMMAND_TIMEOUTS = {
    "node --version": 30, "npm --version": 30, "npm ci": 600,
    "npm install": 600, "npm run lint": 300, "npm run build": 600,
    "npm run preview": 90,
}

#: ملفات تُنسخ من الخطوات السابقة (المصدرية — صغيرة بالطبع).
_GATHER_FILES = (
    "package.json", "package-lock.json", "tsconfig.json",
    "astro.config.mjs", ".npmrc", "env.d.ts", "astro.config.ts",
)
_GATHER_DIRS = ("src", "public", "styles")
#: نواتج ثقيلة تُوصل symlink لا نسخًا (نفس المضيف ونفس نظام الملفات).
_GATHER_LINK_DIRS = ("node_modules", "dist", ".astro")


def required_build_commands(
    acceptance_criteria: list[str] | None,
) -> list[str]:
    """الأوامر التي تطلبها المعايير (نصًّا أو بعلامات نواتجها).

    قائمة فارغة = مهمة بحث/ملفات على مسارها الأصلي — الطور لا يعمل.
    """
    found: set[str] = set()
    for criterion in acceptance_criteria or []:
        text = str(criterion)
        for pattern, command in _COMMAND_PATTERNS:
            if pattern.search(text):
                found.add(command)
        for pattern, command in _OUTPUT_MARKERS:
            if pattern.search(text):
                found.add(command)
    return sorted(found, key=lambda c: _COMMAND_ORDER[c])[:4]


def missing_build_tooling() -> list[str]:
    """الأدوات الغائبة فعليًا (node/npm) — من PATH والمسارات الشائعة."""
    from roles.tools import resolve_build_tool

    return [
        name for name in ("node", "npm")
        if resolve_build_tool(name) is None
    ]


def gather_build_prerequisites(root: Path) -> dict[str, list[str]]:
    """جلب متطلبات البناء من الخطوات السابقة إلى مساحة الخطوة الحالية.

    مساحات الخطوات مستقلة بتصميم (أدلة معزولة لكل تنفيذ) — لكن أوامر
    البناء تحتاج تراكم المشروع: المصدرية تُنسخ (إن غابت) وnode_modules/
    dist تُوصل symlink (ثقيلة ونفس المضيف). لا يُستبدل ملف موجود: ما
    أنشأته الخطوة الحالية (create_files) له الأولوية.

    (W2-T25) مسارات مطلقة حصرًا: الرابط النسبي معلق (قياس 161) والجولة
    التالية تصطدم Errno 17 لأن exists() لا يرى المعلق.
    """
    copied: list[str] = []
    linked: list[str] = []
    root = root.resolve()
    try:
        step_id = int(root.name)
        steps_dir = root.parent
        project_dir = steps_dir.parent
    except (ValueError, IndexError):
        return {"copied": copied, "linked": linked, "note": "مسار خطوة غير نمطي"}
    siblings = []
    for entry in steps_dir.iterdir():
        try:
            if int(entry.name) < step_id and entry.is_dir():
                siblings.append(int(entry.name))
        except ValueError:
            continue
    # (W2-T25) الأحدث أولًا — أحدث نسخة تفوز (قياس 172: astro القديم طغى زورًا).
    for sibling in sorted(siblings, reverse=True):
        source_dir = project_dir / "steps" / str(sibling)
        for name in _GATHER_FILES:
            source = source_dir / name
            target = root / name
            if source.is_file() and not target.exists():
                target.write_bytes(source.read_bytes())
                copied.append(name)
        for name in _GATHER_DIRS:
            source = source_dir / name
            target = root / name
            if source.is_dir() and not target.exists():
                shutil.copytree(source, target)
                copied.append(f"{name}/")
        for name in _GATHER_LINK_DIRS:
            source = source_dir / name
            target = root / name
            if source.is_dir() and not target.exists():
                # رابط معلق من جولة سابقة (مسار نسبي قديم) يُستبدل
                if target.is_symlink():
                    target.unlink()
                target.symlink_to(source, target_is_directory=True)
                linked.append(name)
    return {"copied": copied, "linked": linked}


def _criterion_output_names(
    acceptance_criteria: list[str] | None,
) -> list[str]:
    """أسماء ملفات النواتج التي تذكرها المعايير (اتفاقية build_files)."""
    from roles.build_files import _BUILD_FILENAME

    names: list[str] = []
    for criterion in acceptance_criteria or []:
        for match in _BUILD_FILENAME.findall(str(criterion)):
            clean = match.strip("./")
            if clean and clean not in names:
                names.append(clean)
    return names[:16]


def collect_criterion_outputs(
    root: Path, acceptance_criteria: list[str] | None,
) -> list[Path]:
    """النواتج الموجودة على القرص فعلًا والمطابقة لأسماء المعايير.

    البحث محصور (الجذر + dist/ + public/ + src/) — لا يعبر node_modules
    (آلاف الملفات) ولا يختلق غائبًا: ما لم ينتجه الأمر يبقى غائبًا
    فيقوله المراجع بصدق.
    """
    artifacts: list[Path] = []
    for name in _criterion_output_names(acceptance_criteria):
        candidates = [
            root / name,
            root / "dist" / name,
            root / "public" / name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                artifacts.append(candidate)
                break
        else:
            src_dir = root / "src"
            if src_dir.is_dir():
                for hit in src_dir.rglob(name):
                    if hit.is_file():
                        artifacts.append(hit)
                        break
    return artifacts[:24]


@dataclass
class BuildPhaseOutcome:
    """نتيجة طور أوامر البناء — المنفذ الحي يستهلكها نحيلًا."""

    commands: list[str] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    artifacts: list[Path] = field(default_factory=list)
    gathered: dict = field(default_factory=dict)
    failed_result: object | None = None  # ImplementerResult عند الفشل
    summary: str = ""


def _tooling_missing_result(missing: list[str],
                            commands: list[str]) -> object:
    from roles.implementer import ImplementerResult, ImplementerStatus

    message = (
        "BUILD_TOOLING_MISSING — node/npm غير متوفرين لبيئة التنفيذ "
        f"({', '.join(missing)}) — أوامر البناء المطلوبة "
        f"({'؛ '.join(commands)}) تتطلبهما. ثبّت Node.js LTS على مضيف "
        "التنفيذ ثم أعد الفحص — الحاجز حاجز توفير لا مراجعة خطة"
    )
    return ImplementerResult(
        status=ImplementerStatus.FAILED,
        stderr_truncated=message[:400],
        failure={
            "class": "DEPENDENCY_FAILURE", "stage": "TOOL_START",
            "tool": "run_build_command",
            "reason": "BUILD_TOOLING_MISSING", "retryable": False,
            "missing": missing, "commands": commands,
        },
    )


def _command_failed_result(command: str, failure) -> object:
    from roles.implementer import ImplementerResult, ImplementerStatus

    details = getattr(failure, "details", None) or {}
    exit_code = details.get("exit_code")
    stderr_tail = str(details.get("stderr_tail") or str(failure))[:300]
    message = (
        f"أمر البناء فشل فعليًا: {command}"
        + (f" (exit_code={exit_code})" if exit_code is not None else "")
        + f" — {stderr_tail}"
    )
    return ImplementerResult(
        status=ImplementerStatus.FAILED,
        stderr_truncated=message[:400],
        failure={
            "class": "TOOL_FAILURE", "stage": "TOOL_EXECUTION",
            "tool": "run_build_command",
            "reason": "BUILD_COMMAND_FAILED", "retryable": True,
            "command": command, "exit_code": exit_code,
            "stderr_tail": stderr_tail,
        },
    )


def run_build_commands_phase(
    ctx, root: Path, commands: list[str],
    acceptance_criteria: list[str] | None,
) -> BuildPhaseOutcome:
    """الطور الكامل: فحص الأدوات → تجميع المتطلبات → تنفيذ → أدلة.

    كل أمر عبر run_tool المسجل في tool_invocations؛ الأدلة
    exit_code/stdout/stderr تكتب داخل مساحة الخطوة. فشل أي أمر =
    فشل صادق برسالة الأمر الحقيقية — لا تزييف.
    """
    from roles.tools import run_tool
    from roles.tool_failures import ToolFailure

    outcome = BuildPhaseOutcome(commands=list(commands))
    if not commands:
        return outcome

    gathered = gather_build_prerequisites(root)
    outcome.gathered = gathered

    # ضمان الاعتماديات: build/preview بلا node_modules ⇒ install أولًا
    effective = list(commands)
    needs_deps = any(
        command in ("npm run build", "npm run preview")
        for command in effective
    )
    if (needs_deps and "npm install" not in effective
            and "npm ci" not in effective
            and (root / "package.json").is_file()
            and not (root / "node_modules").exists()):
        effective.insert(0, "npm install")

    for command in effective:
        timeout = _COMMAND_TIMEOUTS.get(command, 300)
        try:
            value = run_tool(
                "run_build_command",
                {"command": command, "timeout_s": timeout},
                ctx,
            )
        except ToolFailure as failure:
            if str(getattr(failure, "reason", "")) == "BUILD_TOOLING_MISSING":
                details = getattr(failure, "details", None) or {}
                missing = list(details.get("missing") or ["node", "npm"])
                outcome.failed_result = _tooling_missing_result(
                    missing, effective)
            else:
                outcome.failed_result = _command_failed_result(
                    command, failure)
            return outcome
        outcome.results.append({
            "command": command,
            "exit_code": value.get("exit_code"),
            "duration_s": value.get("duration_s"),
            "preview_url_seen": value.get("preview_url_seen"),
        })

    outcome.artifacts = collect_criterion_outputs(root, acceptance_criteria)
    # (W2-T25) سجل الأوامر (install log) دليل يراه المراجع: معيار
    # «No error output captured in install log» يحتاج الملف نفسه.
    ev_dir = root / "evidence"
    if ev_dir.is_dir():
        outcome.artifacts += sorted(
            p for p in ev_dir.iterdir() if p.is_file()
        )[:12]
    ran = len(outcome.results)
    gathered_count = len(gathered.get("copied", [])) \
        + len(gathered.get("linked", []))
    extra = f" وجلبت {gathered_count} متطلبًا من خطوات سابقة" if gathered_count else ""
    outcome.summary = f"نفّذت {ran} أمر بناء فعلي{extra}"
    return outcome


__all__ = [
    "BuildPhaseOutcome",
    "collect_criterion_outputs",
    "gather_build_prerequisites",
    "missing_build_tooling",
    "required_build_commands",
    "run_build_commands_phase",
]
