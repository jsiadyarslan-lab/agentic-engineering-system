"""طور أوامر البناء الحقيقية (W2-T24) — npm يُنفَّذ فعليًا بأدلة صادقة.

بطاقة W2-T23: نواتج الأوامر تُنتج بأوامر حقيقية — لا تُختلق نصًّا.

- required_build_commands(): أوامر المعايير بترتيب التبعية.
- gather_build_prerequisites(): جلب ملفات الخطوات السابقة (نسخ/symlink).
- run_build_commands_phase(): فحص الأدوات ← التجميع ← التنفيذ ← النواتج.

فقد الأدوات عائق توفير (BUILD_TOOLING_MISSING → PREFLIGHT قابلة
للحل بإعادة الفحص — W1-T06) لا فشل خطوة.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

_COMMAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"npm\s+install", re.IGNORECASE), "npm install"),
    (re.compile(r"npm\s+ci\b", re.IGNORECASE), "npm ci"),
    (re.compile(r"npm\s+run\s+lint\b", re.IGNORECASE), "npm run lint"),
    (re.compile(r"npm\s+run\s+build", re.IGNORECASE), "npm run build"),
    (re.compile(r"npm\s+run\s+preview", re.IGNORECASE), "npm run preview"),
    (re.compile(r"npm\s+run\s+dev\b", re.IGNORECASE), "npm run dev"),  # 545
    (re.compile(r"node\s+--version", re.IGNORECASE), "node --version"),
    (re.compile(r"npm\s+--version", re.IGNORECASE), "npm --version"),
    # (W2-T25) أدوات التحقق + عبارة التحقق العامة (قياس 512: w3.org).
    (re.compile(r"npx\s+htmlhint|validator\.w3\.org|أداة تحقق HTML|فحص HTML",
                re.IGNORECASE), "npx --yes htmlhint *.html"),
    (re.compile(r"node\s+verify\.js\b", re.IGNORECASE), "node verify.js"),
    (re.compile(r"node\s+verify\.mjs\b", re.IGNORECASE), "node verify.mjs"),
    (re.compile(r"node\s+server\.js\b", re.IGNORECASE), "node server.js"),  # (W2-T25 492)
    (re.compile(r"pnpm\s+(?:ci|install)", re.IGNORECASE), "pnpm install"),
    (re.compile(r"pnpm\s+dev\b", re.IGNORECASE), "pnpm dev"),
    # (W2-T25) اختبارات المشروع (npm test في backend/ — قياس 497).
    (re.compile(r"npm\s+(?:run\s+)?test\b", re.IGNORECASE), "npm test"),
)
#: علامات نواتج تستلزم أمرًا لم يُذكر نصًّا.
_OUTPUT_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"node_modules/", re.IGNORECASE), "npm install"),
    (re.compile(r"package-lock\.json", re.IGNORECASE), "npm install"),
    (re.compile(r"\bdist/", re.IGNORECASE), "npm run build"),
)
_COMMAND_ORDER = {
    "node --version": 0, "npm --version": 0, "npm ci": 1,
    "npm install": 1, "npm run lint": 2, "npm run build": 3,
    "npm run preview": 4, "npm run dev": 4, "npx --yes htmlhint *.html": 5,
    "node verify.js": 6, "node verify.mjs": 6, "node server.js": 7,
    "npm test": 8,
    "pnpm install": 1, "pnpm dev": 4,
}
_COMMAND_TIMEOUTS = {
    "node --version": 30, "npm --version": 30, "npm ci": 600,
    "npm install": 600, "npm run lint": 300, "npm run build": 600,
    "npm run preview": 90, "npm run dev": 90, "npx --yes htmlhint *.html": 300,
    "node verify.js": 120, "node verify.mjs": 120, "node server.js": 60,
    "npm test": 300,
    "pnpm install": 600, "pnpm dev": 90,
}

_GATHER_FILES = (
    "package.json", "package-lock.json", "tsconfig.json",
    "astro.config.mjs", ".npmrc", "env.d.ts", "astro.config.ts", "server.js",
)
_GATHER_DIRS = ("src", "public", "styles")
_GATHER_LINK_DIRS = ("node_modules", ".astro")  # ثقيلة symlink


def required_build_commands(acceptance_criteria: list[str] | None) -> list[str]:
    """أوامر المعايير + «npx --version» الديناميكي — الفارغة = بلا طور."""
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
    """الأدوات الغائبة فعليًا (node/npm) — من PATH والمسارات."""
    from roles.tools import resolve_build_tool

    return [
        name for name in ("node", "npm")
        if resolve_build_tool(name) is None
    ]


def gather_build_prerequisites(root: Path, *, include_files: bool = True,
                               extra_files: tuple = ()) -> dict[str, list[str]]:
    """جلب متطلبات سابقة: نسخ المصدرية وsymlink الثقيلة بلا استبدال —
    مسارات مطلقة (النسبي المعلق يصطدم Errno 17 — قياس 161)."""
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
    for sibling in sorted(siblings, reverse=True):  # (172) الأحدث أولًا
        source_dir = project_dir / "steps" / str(sibling)
        for name in (*(_GATHER_FILES if include_files else ()),
                     *extra_files):
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
    """النواتج الموجودة فعلًا المطابقة للمعايير — بحث محصور (الجذر
    + dist/ + public/ + src/) لا يعبر node_modules ولا يختلق غائبًا."""
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
    """نتيجة طور الأوامر — المنفذ الحي يستهلكها نحيلًا."""

    commands: list[str] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    artifacts: list[Path] = field(default_factory=list)
    gathered: dict = field(default_factory=dict)
    failed_result: object | None = None  # ImplementerResult عند الفشل
    summary: str = ""


def _tooling_missing_result(missing: list[str], commands: list[str]) -> object:
    from roles.implementer import ImplementerResult, ImplementerStatus

    message = (
        "BUILD_TOOLING_MISSING — node/npm غير متوفرين لبيئة التنفيذ "
        f"({', '.join(missing)}) — أوامر البناء ({'؛ '.join(commands)}) "
        "تتطلبهما؛ ثبّت Node.js LTS ثم أعد الفحص — حاجز توفير لا مراجعة"
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
    message = (f"أمر البناء فشل فعليًا: {command}"
               + (f" (exit_code={exit_code})" if exit_code is not None else "")
               + f" — {stderr_tail}")
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
    """الطور الكامل: فحص الأدوات → التجميع → التنفيذ → الأدلة — فشل أي
    أمر = فشل صادق برسالة حقيقية عبر run_tool المسجل."""
    from roles.tools import run_tool
    from roles.tool_failures import ToolFailure

    # (W2-T25) سكربت التحقق المكتوب يُشغَّل حين تطلب المعايير فحص DOM (309).
    if re.search(r"querySelector|فحص DOM|DOM check",
                 " ".join(map(str, acceptance_criteria or [])),
                 re.IGNORECASE):
        commands += [f"node {n}" for n in ("verify.js", "verify.mjs")
                     if (root / n).is_file() and f"node {n}" not in commands]

    outcome = BuildPhaseOutcome(commands=list(commands))
    if not commands:
        return outcome

    # (W2-T25) دليل npm: المتداخل (backend/) أولًا (npm test — قياس 497).
    _m = re.search(r"([\w@./-]+)/package\.json",
                   " ".join(map(str, acceptance_criteria or [])))
    _sub = root / _m.group(1).strip("/") if _m and ".." not in _m.group(1) \
        and (root / _m.group(1).strip("/")).is_dir() else None
    workdir = _sub or next(
        (d for d in sorted(root.iterdir())
         if d.is_dir() and (d / "package.json").is_file()), root)
    if (workdir / "dist").is_symlink():  # (W2-T25 506) قديم يُنزع
        (workdir / "dist").unlink()

    # (W2-T25) ci بلا lockfile = install (388)؛ install قبل build (325).
    effective = list(commands)
    if "npm ci" in effective and not (workdir / "package-lock.json").is_file():
        effective = [c.replace("npm ci", "npm install") for c in effective]
    # (W2-T25) dev معاينة؛ الخادم والاختبار كذلك — install قبلهما.
    needs_deps = any(command in ("npm run build", "npm run preview",
                                 "npm run dev", "pnpm dev", "node server.js",
                                 "npm test") for command in effective)
    # (W2-T25) ملفات الإطار لحاجة npm/خادم (526) + ملفات المعايير (520/545).
    if workdir == root and (needs_deps or any(
            c.startswith(("npm", "pnpm", "npx")) for c in effective)):
        outcome.gathered = gather_build_prerequisites(
            root, extra_files=tuple(_criterion_output_names(
                acceptance_criteria) or ()))
    if (needs_deps and "npm install" not in effective
            and "npm ci" not in effective and "pnpm install" not in effective
            and (workdir / "package.json").is_file()):
        effective.insert(0, "pnpm install" if "pnpm dev" in effective
                         else "npm install")

    _rel = str(workdir.relative_to(root)) if workdir != root else ""
    for command in effective:
        timeout = _COMMAND_TIMEOUTS.get(command, 300)
        try:
            value = run_tool(
                "run_build_command",
                {"command": command, "timeout_s": timeout, "cwd": _rel},
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
    # (W2-T25) سجل الأوامر (install log) دليل يراه المراجع.
    ev_dir = root / "evidence"
    if ev_dir.is_dir():
        outcome.artifacts += sorted(
            p for p in ev_dir.iterdir() if p.is_file()
        )[:12]
    ran = len(outcome.results)
    gathered_count = len(outcome.gathered.get("copied", [])) \
        + len(outcome.gathered.get("linked", []))
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
