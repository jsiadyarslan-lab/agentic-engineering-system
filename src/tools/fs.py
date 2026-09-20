"""أدوات الملفات (الأمر السادس المنقح §3.1) — وحدات حقيقية مختبرة.

write_file / read_file / list_dir — كلها داخل الركيزة المعزولة عبر
نفس بنية التنفيذ التي تستخدمها أدوار المنفذ (SandboxManager +
NetworkMode.NONE)، وكل مسار محصور داخل المجلد الممنوح (خروج عنه =
رفض صريح). البنية التحتية (_bounded_path + _run_in_substrate)
مشتركة مع roles.tools — تنفيذ واحد، أدوات متعددة.
"""

from __future__ import annotations

import json
from pathlib import Path

from roles.tools import ToolContext, ToolError, _bounded_path, _run_in_substrate


def _prepare(ctx: ToolContext) -> tuple[Path, Path]:
    workspace = ctx.grant_root / "_ws"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace, ctx.grant_root


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    """كتابة ملف داخل المجلد الممنوح فقط — داخل الركيزة (§3.2)."""
    target = _bounded_path(ctx.grant_root, path)
    workspace, artifacts = _prepare(ctx)
    code = (
        "import json\n"
        f"payload = json.loads({json.dumps({'path': path, 'content': content}, ensure_ascii=False)!r})\n"
        "import pathlib\n"
        "target = pathlib.Path('/artifacts') / payload['path']\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        "target.write_text(payload['content'], encoding='utf-8')\n"
        "print('wrote', len(payload['content']), 'chars to', payload['path'])\n"
    )
    exit_code, _stdout, stderr = _run_in_substrate(ctx, code, workspace, artifacts)
    if exit_code != 0:
        raise ToolError(f"فشل كتابة {path} داخل الركيزة: {stderr[:200]}")
    return str(target)


def read_file(ctx: ToolContext, path: str) -> str:
    """قراءة ملف من المجلد الممنوح فقط — داخل الركيزة (§3.2)."""
    _bounded_path(ctx.grant_root, path)  # رفض خارج المنحة قبل أي تنفيذ
    workspace, artifacts = _prepare(ctx)
    code = (
        "import json, pathlib\n"
        f"payload = json.loads({json.dumps({'path': path})!r})\n"
        "target = pathlib.Path('/artifacts') / payload['path']\n"
        "data = target.read_text(encoding='utf-8')\n"
        "print(json.dumps({'len': len(data), 'head': data[:2000]}))\n"
    )
    exit_code, stdout, stderr = _run_in_substrate(ctx, code, workspace, artifacts)
    if exit_code != 0:
        raise ToolError(f"فشل قراءة {path} داخل الركيزة: {stderr[:200]}")
    try:
        return json.loads(stdout.strip().splitlines()[-1])["head"]
    except (ValueError, KeyError, IndexError) as error:
        raise ToolError(f"مخرج قراءة غير مفهوم لـ {path}: {error}") from error


def list_dir(ctx: ToolContext, path: str) -> list[str]:
    """سرد محتويات مجلد داخل المنحة — داخل الركيزة (§3.1)."""
    _bounded_path(ctx.grant_root, path)
    workspace, artifacts = _prepare(ctx)
    code = (
        "import json, pathlib\n"
        f"payload = json.loads({json.dumps({'path': path})!r})\n"
        "target = pathlib.Path('/artifacts') / payload['path']\n"
        "entries = sorted([p.name + ('/' if p.is_dir() else '') for p in target.iterdir()])\n"
        "print(json.dumps({'entries': entries}))\n"
    )
    exit_code, stdout, stderr = _run_in_substrate(ctx, code, workspace, artifacts)
    if exit_code != 0:
        raise ToolError(f"فشل سرد {path} داخل الركيزة: {stderr[:200]}")
    try:
        return list(json.loads(stdout.strip().splitlines()[-1])["entries"])
    except (ValueError, KeyError, IndexError) as error:
        raise ToolError(f"مخرج سرد غير مفهوم لـ {path}: {error}") from error
