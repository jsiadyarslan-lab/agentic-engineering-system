"""أداة الأوامر (الأمر السادس المنقح §3.1) — run_command داخل الركيزة.

قائمة بيضاء للأوامر: python / python3 / pytest (بالاسم الأساسي)
أو المسار المطلق لمفسّر العملية الحالية (sys.executable — مفسّر
الخادم صاحب الحزم المثبتة). أي أمر خارجها = رفض صريح ToolError.

التنفيذ داخل الركيزة المعزولة (NetworkMode.NONE) بوسائط ثابتة بلا
shell. إن رفضت الركيزة تنفيذ الأمر نفسه (record غير منفَّذ): تنفيذ
معلَن في العملية مع ترجمة مسارات /artifacts — الحدث والدليل يوثقان
الموقع (نفس مبدأ «معزول أو معلن» في أدوات PDF).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from roles.tools import ToolContext, ToolError

#: القائمة البيضاء — بالاسم الأساسي فقط (§3.3: أمر خارج القائمة = فشل).
COMMAND_BASENAME_WHITELIST = frozenset({"python", "python3", "pytest"})


def _whitelisted(argv0: str) -> bool:
    base = Path(argv0).name
    if base in COMMAND_BASENAME_WHITELIST:
        return True
    return bool(sys.executable) and argv0 == sys.executable


def _translate_for_process(argv: list[str], grant_root: Path) -> list[str]:
    """ترجمة /artifacts/... إلى المسار المضيف داخل المنحة (للتنفيذ المعلن)."""
    translated: list[str] = []
    prefix = "/artifacts/"
    for index, item in enumerate(argv):
        if index > 0 and item.startswith(prefix):
            translated.append(str(grant_root / item[len(prefix):]))
        else:
            translated.append(item)
    return translated


def run_command(
    ctx: ToolContext, argv: list[str], *, timeout: float = 180.0
) -> dict:
    """تنفيذ أمر من القائمة البيضاء داخل الركيزة — فشل التنفيذ =
    ToolError؛ أما exit_code غير الصفري فهو نتيجة حقيقية تُعاد كما هي.
    """
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ToolError(f"وسائط أمر غير صالحة: {argv!r}"[:200])
    if not _whitelisted(argv[0]):
        raise ToolError(
            f"أمر خارج القائمة البيضاء: '{argv[0]}' "
            f"(المسموح: {sorted(COMMAND_BASENAME_WHITELIST)} أو مفسّر العملية)"
        )
    import uuid as uuid_mod

    from substrate.factory import make_sandbox_manager
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.sandbox import NetworkMode, SandboxRequest

    # AES-EXP-04 §3.3: الركيزة من المصنع الواحد — بلا ركيزة أو بلا
    # صورة يكون المسار المعلن (in_process_declared) كما في العقد الحالي
    manager = make_sandbox_manager()
    image = next(iter(manager.image_allowlist), None) if manager else None
    outcome = None
    if manager is not None and image is not None:
        workspace = ctx.grant_root / "_ws"
        workspace.mkdir(parents=True, exist_ok=True)
        request = SandboxRequest(
            sandbox_id=f"proc-{uuid_mod.uuid4().hex[:8]}",
            image=image,
            command=tuple(argv),
            limits=E1_LIMITS_DEFAULTS,
            env_names=frozenset({"PATH"}),
            network=NetworkMode.NONE,
            workspace_root=str(workspace),
            artifacts_dir=str(ctx.grant_root),
        )
        outcome = manager.execute(request)
    record = outcome.record if outcome is not None else None
    site = "substrate"
    if record is not None and record.executed:
        exit_code = record.exit_code if record.exit_code is not None else -1
        stdout = ""
        stderr = ""
        try:
            stdout = Path(record.stdout_reference).read_text(
                encoding="utf-8", errors="replace"
            ) if record.stdout_reference else ""
        except OSError:
            pass
        try:
            stderr = Path(record.stderr_reference).read_text(
                encoding="utf-8", errors="replace"
            ) if record.stderr_reference else ""
        except OSError:
            pass
    else:
        # إعلان صريح: الركيزة لم تنفّذ الأمر نفسه — تنفيذ في العملية
        # بترجمة مسارات /artifacts (نمط أدوات PDF: معزول أو معلن).
        site = "in_process_declared"
        ctx.emit({
            "kind": "tool.site_declared",
            "role": "reviewer",
            "tool": "run_command",
            "execution_site": site,
            "reason": f"الركيزة لم تنفّذ {argv[0]} — تنفيذ معلن في العملية",
        })
        try:
            proc = subprocess.run(
                _translate_for_process(argv, ctx.grant_root),
                capture_output=True, text=True, timeout=timeout,
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as error:
            raise ToolError(f"الأمر تجاوز المهلة {timeout}ث: {argv[:3]}") from error

    import hashlib

    digest = hashlib.sha256(
        (stdout + "\x00" + stderr).encode("utf-8", "replace")
    ).hexdigest()
    return {
        "exit_code": exit_code,
        "stdout": stdout[-8000:],
        "stderr": stderr[-2000:],
        "execution_site": site,
        "output_sha256": digest,
    }
