"""حزمة أدوات البناء (الأمر السادس المنقح §3) — قائمة بيضاء مغلقة.

الأدوات الأربع: write_file / read_file / list_dir (fs) وrun_command
(proc). كل استدعاء عبر run_tool يوثَّق بحدث: الاسم، ملخص الوسائط،
sha256 للمخرج، موقع التنفيذ، المدة — نفس عقد توثيق roles.tools.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from roles.tools import ToolContext, ToolError
from tools import fs, proc

#: القائمة البيضاء (§3.2) — غيرها = فشل خطوة صريح.
TOOLS_WHITELIST: tuple[str, ...] = (
    "write_file",
    "read_file",
    "list_dir",
    "run_command",
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_tool(name: str, args: dict, ctx: ToolContext) -> Any:
    """تنفيذ أداة بناء من القائمة البيضاء مع توثيق sha256 (§3.2+§3.3)."""
    if name not in TOOLS_WHITELIST:
        raise ToolError(
            f"أداة خارج القائمة البيضاء: '{name}' (المسموح: {list(TOOLS_WHITELIST)})"
        )
    started = time.monotonic()
    site = "substrate"
    try:
        if name == "write_file":
            value = fs.write_file(
                ctx, str(args.get("path", "")), str(args.get("content", ""))
            )
            digest = _sha256_text(str(args.get("content", "")))
            summary: Any = {"path": str(value)}
        elif name == "read_file":
            value = fs.read_file(ctx, str(args.get("path", "")))
            digest = _sha256_text(str(value))
            summary = {"chars": len(str(value))}
        elif name == "list_dir":
            value = fs.list_dir(ctx, str(args.get("path", "")))
            digest = _sha256_text("\n".join(value))
            summary = {"entries": len(value)}
        elif name == "run_command":
            argv = list(args.get("argv", []) or [])
            value = proc.run_command(ctx, argv, timeout=float(args.get("timeout", 180)))
            digest = value["output_sha256"]
            site = value["execution_site"]
            summary = {
                "argv0": argv[0] if argv else "",
                "exit_code": value["exit_code"],
            }
        else:  # pragma: no cover — القائمة مغلقة أعلاه
            raise ToolError(f"أداة غير منفذة: {name}")
    except ToolError:
        raise
    except Exception as error:  # noqa: BLE001 — فشل خطوة صريح موثق
        raise ToolError(f"الأداة {name} فشلت: {error}") from error

    duration_ms = int((time.monotonic() - started) * 1000)
    ctx.emit({
        "kind": "tool.call",
        "role": "implementer",
        "tool": name,
        "args_summary": summary,
        "output_sha256": digest,
        "execution_site": site,
        "duration_ms": duration_ms,
    })
    return value


#: وصف الأدوات لنموذج البناء — يُدمج في برومبت المنفذ.
TOOLS_MANIFEST: list[dict] = [
    {"tool": "write_file", "args": {"path": "textstats/cli.py", "content": "…"},
     "desc": "كتابة ملف داخل مساحة العمل الممنوحة (داخل الركيزة)"},
    {"tool": "read_file", "args": {"path": "textstats/cli.py"},
     "desc": "قراءة ملف من مساحة العمل (داخل الركيزة)"},
    {"tool": "list_dir", "args": {"path": "textstats"},
     "desc": "سرد محتويات مجلد (داخل الركيزة)"},
    {"tool": "run_command", "args": {"argv": ["python", "…"]},
     "desc": "تشغيل أمر python/pytest من القائمة البيضاء (داخل الركيزة)"},
]
