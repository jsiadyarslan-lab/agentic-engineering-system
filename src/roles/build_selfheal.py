"""الإصلاح الذاتي لأوامر البناء (W2-T25) — مفصول عن build_tool للرقة.

موت خطط مشروع #3 (v87/v88) بنمط واحد: المنفذ يكتب قالب إطار
(astro.config.mjs أو next.config.js) بينما package.json بلا سكربت
build، فيفشل `npm run build` بـ«Missing script» مرتين وتموت الخطة
وتُعاد التهيئة من فراغ. العقد هنا: عند هذا الفشل تحديدًا — ووُجد
package.json صالح، وكُشف إطار معروف من ملف إعداده — يُضاف سكربت
build المناسب للإطار ويُعاد الأمر مرة واحدة؛ العملية تُسجَّل كاملة
في المُخرج (self_heal) ليحكم المراجع على الناتج بوعي به. كل ما
عداه فشل صادق كما كان: لا تخمين لسكربتات غير build، ولا دخول بلا
إطار معروف، ولا مساس بـpackage.json المعطوب.

القياس 849 (v91): tsconfig.json كُتب قبل next.config فلم يُعرف
الإطار من ملف إعداد — الكشف يُكمل من اعتماديات package.json:
next/astro في dependencies أو devDependencies تكفي للتعرف.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

#: مطابق لـ _BUILD_EVIDENCE_MAX_CHARS في build_tool (تفادي الاستيراد الدائري).
_MAX_CHARS = 200_000
#: الإطارات المعروفة: ملفات إعدادها → أمر البناء الصحيح لها.
_FRAMEWORKS = (
    (("astro.config.mjs", "astro.config.ts"), "astro build"),
    (("next.config.js", "next.config.ts", "next.config.mjs"), "next build"),
)
#: كشف احتياطي من اعتماديات package.json (قياس 849 أعلاه).
_DEPS = (("astro", "astro build"), ("next", "next build"))


def _detect_framework(root: Path, pkg: dict):
    """أمر بناء الإطار: من ملف الإعداد أولًا ثم من الاعتماديات."""
    for cfgs, build_cmd in _FRAMEWORKS:
        if any((root / c).exists() for c in cfgs):
            return build_cmd
    deps = {**(pkg.get("dependencies") or {}),
            **(pkg.get("devDependencies") or {})}
    for name, build_cmd in _DEPS:
        if name in deps:
            return build_cmd
    return None


def heal_and_rerun(workdir, command: str, stderr: bytes, argv: list,
                   env: dict, timeout: float):
    """كشف «Missing script: build» → أضف سكربت الإطار → أعِد الأمر مرة.

    المُخرج None إن لم يكن هذا الفشل هو نمط السكربت المفقود (فشل صادق
    يبقى كما هو)، وإلا الخماسية
    (exit_code, stdout, stderr, duration_s, self_heal).
    """
    parts = command.split()
    if ("Missing script" not in stderr.decode("utf-8", "replace")
            or len(parts) < 3 or parts[2] != "build"):
        return None
    pkg_path = Path(workdir) / "package.json"
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        scripts = pkg.get("scripts")
        if scripts is None:
            scripts = {}
            pkg["scripts"] = scripts
        if not isinstance(scripts, dict) or "build" in scripts:
            return None  # موجود فعلًا أو بنية شاذة — الفشل لسبب آخر
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    build_cmd = _detect_framework(Path(workdir), pkg)
    if build_cmd is None:
        return None  # لا إطار معروف — لا تخمين أعمى
    scripts["build"] = build_cmd
    try:
        pkg_path.write_text(
            json.dumps(pkg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    except OSError:
        return None
    started = time.monotonic()
    try:
        done = subprocess.run(argv, cwd=str(workdir), env=env,
                              capture_output=True, timeout=timeout)
        code = done.returncode
        out = (done.stdout or b"")[:_MAX_CHARS]
        err = (done.stderr or b"")[_MAX_CHARS * -1:]
    except subprocess.TimeoutExpired as error:
        code = 124
        out = (error.stdout or b"")[:_MAX_CHARS] \
            if isinstance(error.stdout, (bytes, bytearray)) else b""
        err = f"انتهت مهلة الأمر ({timeout:.0f}ث)".encode("utf-8")
    heal = {"healed": True, "added_script": "build",
            "script_command": build_cmd,
            "package_json": str(pkg_path)}
    return code, out, err, round(time.monotonic() - started, 2), heal


__all__ = ["heal_and_rerun"]
