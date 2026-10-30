"""طور أوامر البناء الحقيقية (W2-T24) — npm يُنفَّذ فعليًا بأدلة صادقة.

بطاقة W2-T23 قالت في build_files.py حرفيًا: «نواتج أوامر لا يُختلق
نصها — تُنتج بأوامر حقيقية (بطاقة لاحقة)» — هذه هي البطاقة. الخطوات
التي تطلب معاييرها أوامر (نصًّا أو بعلامات نواتجها) تنفذها فعلًا:

- required_build_commands(): أوامر المعايير بترتيب التبعية — بلا
  أوامر = مهمة على مسارها الأصلي بلا تغيير سلوك.
- gather_build_prerequisites(): ملفات الخطوات السابقة تُجلب لمساحة
  الحالية (نسخ للمصدرية، symlink للثقيلة) بلا نسخها.
- run_build_commands_phase(): فحص الأدوات → التجميع → التنفيذ عبر
  run_tool بأدلة exit_code/stdout/stderr حقيقية → جمع النواتج.

فقد node/npm عائق توفير لا فشل خطوة: توقيع BUILD_TOOLING_MISSING
يفتح حاجز PREFLIGHT_BLOCKED قابلًا للحل بإعادة الفحص (W1-T06).
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
    # (W2-T25) أدوات التحقق وسكربته — معايير خطوات التحقق تشترطها نصًا.
    (re.compile(r"npx\s+htmlhint", re.IGNORECASE), "npx --yes htmlhint *.html"),
    (re.compile(r"node\s+verify\.js\b", re.IGNORECASE), "node verify.js"),
    (re.compile(r"node\s+verify\.mjs\b", re.IGNORECASE), "node verify.mjs"),
)
#: علامات نواتج تستلزم أمرًا لم يُذكر نصًّا.
_OUTPUT_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"node_modules/", re.IGNORECASE), "npm install"),
    (re.compile(r"package-lock\.json", re.IGNORECASE), "npm install"),
    (re.compile(r"\bdist/", re.IGNORECASE), "npm run build"),
)
#: ترتيب التبعية — install يسبق lint/build يسبق preview.
_COMMAND_ORDER = {
    "node --version": 0, "npm --version": 0, "npm ci": 1,
    "npm install": 1, "npm run lint": 2, "npm run build": 3,
    "npm run preview": 4, "npx --yes htmlhint *.html": 5,
    "node verify.js": 6, "node verify.mjs": 6,
}
_COMMAND_TIMEOUTS = {
    "node --version": 30, "npm --version": 30, "npm ci": 600,
    "npm install": 600, "npm run lint": 300, "npm run build": 600,
    "npm run preview": 90, "npx --yes htmlhint *.html": 300,
    "node verify.js": 120, "node verify.mjs": 120,
}

#: ملفات تُنسخ من الخطوات السابقة (المصدرية — صغيرة بالطبع).
_GATHER_FILES = (
    "package.json", "package-lock.json", "tsconfig.json",
    "astro.config.mjs", ".npmrc", "env.d.ts", "astro.config.ts",
)
_GATHER_DIRS = ("src", "public", "styles")
#: نواتج ثقيلة تُوصل symlink لا نسخًا.
_GATHER_LINK_DIRS = ("node_modules", "dist", ".astro")


def required_build_commands(
    acceptance_criteria: list[str] | None,
) -> list[str]:
    """أوامر المعايير (نصًّا أو بعلامات نواتجها) + «npx tsc --version»
    الديناميكي — الفارغة = مهمة بحث/ملفات والطور لا يعمل.
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
        for hit in re.finditer(
                r"npx\s+([\w@/.-]+)\s+--version", text, re.IGNORECASE):
            found.add(f"npx --yes {hit.group(1)} --version")
    return sorted(found, key=lambda c: _COMMAND_ORDER.get(c, 5))[:6]


def missing_build_tooling() -> list[str]:
    """الأدوات الغائبة فعليًا (node/npm) — من PATH والمسارات الشائعة."""
    from roles.tools import resolve_build_tool

    return [
        name for name in ("node", "npm")
        if resolve_build_tool(name) is None
    ]


def gather_build_prerequisites(root: Path) -> dict[str, list[str]]:
    """جلب متطلبات البناء من الخطوات السابقة إلى مساحة الحالية:
    المصدرية تُنسخ والثقيلة تُوصل symlink بلا استبدال. (W2-T25)
    مسارات مطلقة: النسبي معلق (قياس 161) يصطدم Errno 17 لاحقًا.
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
    """الطور الكامل: فحص الأدوات → التجميع → التنفيذ → الأدلة. كل أمر
    عبر run_tool المسجل؛ فشل أي أمر = فشل صادق برسالة حقيقية.
    """
    from roles.tools import run_tool
    from roles.tool_failures import ToolFailure

    # (W2-T25) سكربت التحقق المكتوب يُشغَّل حين تطلب المعايير فحص DOM —
    # الاسم اختيار النموذج (قياس 309: verify.js موجود ولم يُشغَّل أبدًا).
    if re.search(r"querySelector|فحص DOM|DOM check",
                 " ".join(map(str, acceptance_criteria or [])),
                 re.IGNORECASE):
        for name in ("verify.js", "verify.mjs"):
            if (root / name).is_file() and f"node {name}" not in commands:
                commands.append(f"node {name}")

    outcome = BuildPhaseOutcome(commands=list(commands))
    if not commands:
        return outcome

    gathered = gather_build_prerequisites(root)
    outcome.gathered = gathered

    # ضمان الاعتماديات: install قبل build/preview ما دام package.json —
    # node_modules القديم لا يكفي: الاعتماديات تتغير (قياس 325: marked).
    effective = list(commands)
    needs_deps = any(
        command in ("npm run build", "npm run preview")
        for command in effective
    )
    if (needs_deps and "npm install" not in effective
            and "npm ci" not in effective
            and (root / "package.json").is_file()):
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
