"""أداة أوامر البناء الحقيقية (W2-T24) — مستخرجة لرقة tools.py.

أمر 008 وزّع أنحاف tools.py (التصنيف في tool_failures، الويب في
web_tools، الـPDF في pdf_tools) — وأوامر البناء هنا مثلها: التنفيذ
والأدلة والقائمة البيضاء في هذه الوحدة، وtools.py يستوردها نحيلًا.

العقد (W2-T24): قائمة أوامر مغلقة تنفذ فعليًا في العملية معلنة
(npm يحتاج شبكة+HOME كأدوات الويب — execution_site=in_process_declared)
بأدلة exit_code/stdout/stderr مكتوبة bounded داخل مساحة الخطوة،
وبيئة منظفة بلا أسرار الخدمة (سكربتات npm لا ترى المفاتيح). فقد
node/npm فشل صنفي BUILD_TOOLING_MISSING غير قابل لإعادة المحاولة —
يقرؤه مصنف المحرك فيفتح حاجز توفير (امتداد W1-T06) لا مراجعة خطة.
"""

from __future__ import annotations

import json
from pathlib import Path

from roles.tool_failures import ToolFailure

#: أوامر مسموحة حصرًا — قائمة مغلقة (لا تفسير ولا وسائط حرة).
#: (W2-T25) npm run lint وnpx htmlhint وnode verify — تشترطها معايير
#: خطط المصنع نصًّا فلم تكن تُنفّذ والتزم المنفذ بالصدق («لا دليل»).
BUILD_COMMAND_WHITELIST: frozenset[str] = frozenset({
    "node --version", "npm --version",
    "npm install", "npm ci",
    "npm run build", "npm run preview", "npm run lint",
    # (W2-T25) أدوات التحقق وسكربته — معايير خطوات التحقق تشترطها
    # نصًا («npx htmlhint تعيد 0»، «فحص DOM عبر script») فلم تكن تُنفّذ.
    "npx --yes htmlhint *.html", "node verify.js", "node verify.mjs",
})
#: مسارات شائعة إلى جانب PATH (تثبيت tarball القياسي إلى /usr/local).
_BUILD_TOOL_FALLBACK_DIRS = ("/usr/local/bin", "/opt/node/bin")
#: سقوف الأدلة المكتوبة (حد أقصى للنص المحفوظ من مخرجات الأمر).
_BUILD_EVIDENCE_MAX_CHARS = 200_000
_BUILD_PREVIEW_URL_HINTS = (b"Local", b"Network")


def resolve_build_tool(name: str) -> str | None:
    """مسار أداة البناء إن وُجدت فعليًا — PATH ثم المسارات الشائعة."""
    import os as _os
    import shutil as _shutil

    found = _shutil.which(name)
    if found:
        return found
    for directory in _BUILD_TOOL_FALLBACK_DIRS:
        candidate = Path(directory) / name
        if candidate.is_file() and _os.access(candidate, _os.X_OK):
            return str(candidate)
    return None


def _build_command_env(npm_path: str) -> dict:
    """بيئة منظفة للأمر — بلا أسرار الخدمة إطلاقًا.

    npm يحتاج شبكة وHOME (ذاكرة التخزين) كأدوات الويب — التنفيذ في
    العملية معلن (execution_site=in_process_declared)؛ ويمرر لأمر
    npm متغيرات عامة حصرًا: لا مفاتيح مزودين ولا أسرار search-api.
    """
    import os as _os

    keep = {}
    for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TZ"):
        value = _os.environ.get(key)
        if value:
            keep[key] = value
    node_dir = str(Path(npm_path).resolve().parent)
    keep["PATH"] = node_dir + ":" + keep.get("PATH", "/usr/bin:/bin")
    return keep


def _build_evidence_paths(ctx, command: str) -> tuple[Path, Path, Path]:
    """مسارات أدلة الأمر داخل مساحة الخطوة (evidence/build-«slug»-*)."""
    slug = command.replace(" ", "-").replace("/", "-")
    evidence_dir = ctx.grant_root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return (
        evidence_dir / f"build-{slug}-stdout.txt",
        evidence_dir / f"build-{slug}-stderr.txt",
        evidence_dir / f"build-{slug}-exit.json",
    )


def _run_preview_command(ctx, npm_path: str, timeout_s: float) -> dict:
    """npm run preview: مراقبة مخرج Local/Network ثم قتل المجموعة.

    نجاح المعيار هو «عملية تبدأ وتصرح بعنوانها» — لا خادم يبقى حيًا:
    عند رؤية العنوان يُقتل أمرًا ويوثق preview_url_seen=true.
    """
    import os as _os
    import select as _select
    import signal as _signal
    import subprocess as _subprocess
    import time as _time

    started = _time.monotonic()
    process = _subprocess.Popen(  # noqa: S603 — argv ثابت من القائمة البيضاء
        [npm_path, "run", "preview"],
        cwd=str(ctx.grant_root), env=_build_command_env(npm_path),
        stdout=_subprocess.PIPE, stderr=_subprocess.PIPE,
        start_new_session=True,
    )
    output = b""
    url_seen = False
    deadline = started + max(10.0, timeout_s)
    fds = [process.stdout.fileno(), process.stderr.fileno()]
    try:
        while len(fds) > 0:
            if _time.monotonic() > deadline:
                break
            readable, _, _ = _select.select(fds, [], [], 0.5)
            for fd in readable:
                try:
                    chunk = _os.read(fd, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    fds.remove(fd)
                    continue
                output += chunk[-_BUILD_EVIDENCE_MAX_CHARS:]
                if any(hint in output for hint in _BUILD_PREVIEW_URL_HINTS):
                    url_seen = True
                    break
            if url_seen:
                break
    finally:
        try:
            _os.killpg(process.pid, _signal.SIGKILL)
        except OSError:
            process.kill()
        try:
            process.wait(timeout=10)
        except _subprocess.TimeoutExpired:  # pragma: no cover — قتل بالفعل
            pass
    return {
        "command": "npm run preview",
        "exit_code": 0 if url_seen else 124,
        "duration_s": round(_time.monotonic() - started, 2),
        "preview_url_seen": url_seen,
        "output_tail": output[-4000:].decode("utf-8", "replace"),
    }


def run_build_command(ctx, command: str, timeout_s: float = 0) -> dict:
    """تنفيذ أمر بناء حقيقي (W2-T24) — أدلة exit_code/stdout/stderr.

    قائمة بيضاء مغلقة (لا تفسير ولا وسائط حرة)؛ وفقد node/npm فشل
    مصنّف BUILD_TOOLING_MISSING غير قابل لإعادة المحاولة (توفير
    بيئي)؛ والأدلة تكتب bounded داخل مساحة الخطوة (evidence/). نجاح
    الأمر لا يعني نجاح الخطوة — المراجع يحكم على الملفات الناتجة.
    """
    import subprocess as _subprocess
    import time as _time

    command = str(command or "").strip()
    if command not in BUILD_COMMAND_WHITELIST:
        raise ToolFailure(
            "run_build_command",
            f"أمر بناء خارج القائمة البيضاء: '{command}' "
            f"(المسموح: {sorted(BUILD_COMMAND_WHITELIST)})",
            failure_class="POLICY_BLOCK", reason="COMMAND_NOT_WHITELISTED",
            stage="TOOL_START", retryable=False,
            details={"command": command[:120]},
        )
    missing = [n for n in ("node", "npm") if resolve_build_tool(n) is None]
    if command.startswith("npx") and resolve_build_tool("npx") is None:
        missing.append("npx")
    if missing:
        raise ToolFailure(
            "run_build_command",
            "BUILD_TOOLING_MISSING — node/npm غير متوفرين لبيئة التنفيذ "
            f"({', '.join(missing)}) — أوامر البناء تتطلبهما",
            failure_class="DEPENDENCY_FAILURE",
            reason="BUILD_TOOLING_MISSING",
            stage="TOOL_START", retryable=False,
            details={"missing": missing, "command": command[:120]},
        )
    npm_path = resolve_build_tool("npm")
    timeout = float(timeout_s) if timeout_s and timeout_s > 0 else 600.0

    if command == "npm run preview":
        result = _run_preview_command(ctx, npm_path, timeout)
        if not result["preview_url_seen"]:
            raise ToolFailure(
                "run_build_command",
                "npm run preview لم يصرح بعنوان Local/Network خلال "
                f"{timeout:.0f}ث — "
                + result["output_tail"][-200:],
                failure_class="TOOL_FAILURE",
                reason="BUILD_COMMAND_FAILED",
                stage="TOOL_EXECUTION", retryable=True,
                details={"command": command,
                         "exit_code": result["exit_code"],
                         "preview_url_seen": False,
                         "stderr_tail": result["output_tail"][-300:]},
            )
        stdout_path, stderr_path, exit_path = _build_evidence_paths(
            ctx, command)
        stdout_path.write_text(result["output_tail"], encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        exit_path.write_text(json.dumps(result, ensure_ascii=False),
                             encoding="utf-8")
        return result

    # (W2-T25) npx كأداة ثالثة بجانب npm/node — أدوات التحقق تعبرها.
    if command.startswith("npm"):
        runner = npm_path
    elif command.startswith("npx"):
        runner = resolve_build_tool("npx")
    else:
        runner = resolve_build_tool("node")
    argv = [runner, *command.split()[1:]]
    started = _time.monotonic()
    try:
        completed = _subprocess.run(  # noqa: S603 — argv من القائمة البيضاء
            argv, cwd=str(ctx.grant_root),
            env=_build_command_env(npm_path),
            capture_output=True, timeout=timeout,
        )
        exit_code = completed.returncode
        stdout = (completed.stdout or b"")[:_BUILD_EVIDENCE_MAX_CHARS]
        stderr = (completed.stderr or b"")[_BUILD_EVIDENCE_MAX_CHARS * -1:]
    except _subprocess.TimeoutExpired as error:
        exit_code = 124
        stdout = (error.stdout or b"")[:_BUILD_EVIDENCE_MAX_CHARS] \
            if isinstance(error.stdout, (bytes, bytearray)) else b""
        stderr = f"انتهت مهلة الأمر ({timeout:.0f}ث)".encode("utf-8")
    duration_s = round(_time.monotonic() - started, 2)

    stdout_path, stderr_path, exit_path = _build_evidence_paths(ctx, command)
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    record = {
        "command": command, "exit_code": exit_code,
        "duration_s": duration_s,
        "stdout_chars": len(stdout), "stderr_chars": len(stderr),
    }
    exit_path.write_text(json.dumps(record, ensure_ascii=False),
                         encoding="utf-8")
    if exit_code != 0:
        raise ToolFailure(
            "run_build_command",
            f"أمر البناء فشل فعليًا: {command} (exit_code={exit_code}) — "
            + stderr.decode("utf-8", "replace")[-300:],
            failure_class="TOOL_FAILURE", reason="BUILD_COMMAND_FAILED",
            stage="TOOL_EXECUTION", retryable=True,
            details={"command": command, "exit_code": exit_code,
                     "stderr_tail": stderr.decode("utf-8", "replace")[-300:]},
        )
    return record


__all__ = [
    "BUILD_COMMAND_WHITELIST",
    "resolve_build_tool",
    "run_build_command",
]
