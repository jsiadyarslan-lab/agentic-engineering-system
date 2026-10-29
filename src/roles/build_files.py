"""طور إنشاء ملفات المشروع (W2-T23) — مستخرج من implementer_live لرقته.

المنفذ الحي كان عاجزًا بنيويًا عن بناء ملفات المشروع: خطته أدوات بحث
حصرًا ومخرجه تقرير+PDF+مصادر — فمعايير الخطوات الملفية (package.json/
tsconfig.json/astro.config.mjs...) تفشل بنمط «تقرير واصف بدل ملف».

هذه الوحدة تضيف طور البناء دون مساس بمسار البحث/التقرير:
- ‎required_build_files(): الملفات المصدرية التي تطلبها المعايير فعليًا
  (اتفاقية المفكر الموسعة بامتدادات الويب) مع استبعاد مخرجات الدور
  التلقائية ونواتج الأوامر (node_modules/dist/الأقفال — لا تُختلق).
- ‎parse_created_files(): تحليل رد النموذج بصيغة ‎### FILE:‎ المسار ثم
  كتلة محتوى (نمط missions_textstats المُثبت) بفحوص أمان صارمة:
  مسارات نسبية بلا ../ بلا مطلق، امتدادات بيضاء، سقوف حجم/عدد/طول.
- ‎create_files_phase(): النداء الحي الكامل — حمولة تحمل الملفات
  المطلوبة وتغذية المحاولات السابقة راجعة وملخص المادة المجلوبة،
  بإعادة تحليل واحدة ثم فشل صريح (RoleSystemFault).

الكتابة نفسها تبقى عبر run_tool("write_file") في implementer_live —
داخل الركيزة بأدلة sha256 لكل ملف؛ المعايير هي العقد.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from roles.live import RoleSystemFault
from router.model_router import ChatMessage

#: ملفات البناء القابلة للطلب من المعايير — أوسع من اتفاقية المراجع
#: الوهمي لأن خطط البناء تذكر .astro/.mjs/.ts/.css/... والحد الخلفي
#: (?!\w) يمنع ابتلاع js لـ json (خطأ ترتيب البدائل الكلاسيكي).
_BUILD_FILENAME = re.compile(
    r"(?:[\w@./-]+\.(?:astro|mjs|cjs|json|mdx|toml|yaml|yml|html|css"
    r"|tsx|jsx|csv|xml|txt|log|md|js|ts|py|env)"
    # (W2-T25) ملف نقطي: لا يسبق النقطة حرف كلمة فلا يبتلع «file.env».
    r"|(?<![\w@./-])\.(?:gitignore|editorconfig|npmrc|nvmrc"
    r"|prettierrc|babelrc|eslintrc|browserslistrc|prettierignore"
    r"|eslintignore))(?!\w)"
)

#: (W2-T25) أسماء تقنية ليست ملفات — «Next.js» كملف مطلوب أفشل
#: التنفيذين 39/40 (الخطوة 130) بمطالبة زائفة لا يكتبها النموذج.
_BUILD_TECH_NAMES = frozenset({
    "next.js", "node.js", "vue.js", "nuxt.js", "react.js",
    "express.js", "svelte.js", "nest.js", "d3.js", "three.js",
    "chart.js", "socket.io", "prisma.io", "github.io", "vue.cjs",
})

#: (W2-T25) ملفات نقطية مسموحة — Path().suffix لها فارغ فيُرفض زورًا.
_CREATE_ALLOWED_DOTFILES = frozenset({
    ".env", ".gitignore", ".editorconfig", ".npmrc", ".nvmrc",
    ".prettierrc", ".eslintrc", ".babelrc", ".browserslistrc",
    ".prettierignore", ".eslintignore", ".gitkeep",})
#: صيغة رد إنشاء الملفات (نمط missions_textstats المُثبت): ‎### FILE: مسار
_CREATE_FILE_HEADER = re.compile(r"^###\s+FILE:\s*(\S+)\s*$", re.MULTILINE)
_CREATE_ALLOWED_EXTS = frozenset({
    ".astro", ".mjs", ".cjs", ".js", ".ts", ".tsx", ".jsx", ".css",
    ".html", ".json", ".md", ".mdx", ".txt", ".toml", ".yaml", ".yml",
    ".xml", ".csv", ".py", ".cfg", ".env", ".d.ts",
})
#: نواتج أوامر لا يُختلق نصها — تُنتج بأوامر حقيقية (بطاقة لاحقة)
_CREATE_GENERATED_PREFIXES = ("node_modules/", "dist/", "build/", ".astro/")
_CREATE_GENERATED_NAMES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
})
_CREATE_MAX_FILES = 16
_CREATE_MAX_CHARS = 120_000
_CREATE_MAX_PATH = 200
#: (W2-T25) معيار دليل بلا ملف — علامة .gitkeep تنشئ الدليل (قياس 256).
_DIR_ONLY = re.compile(
    r"Directory\s+`?([\w@./-]+)/?`?\s+exists", re.IGNORECASE)


def own_artifact_names(task_id: str) -> set[str]:
    """مخرجات الدور التلقائية — لا تُطلب من النموذج «بناؤها»."""
    return {f"{task_id}-report.md", f"{task_id}-report.pdf",
            "report.md", "report.pdf", "sources.json"}


def required_build_files(
    acceptance_criteria: list[str] | None, task_id: str,
) -> list[str]:
    """الملفات المصدرية التي تطلبها المعايير فعليًا (W2-T23): استخراج
    الأسماء مع استبعاد مخرجات الدور ونواتج الأوامر — الفارغة = مهمة
    بحث/تقرير بلا تغيير سلوك."""
    own = own_artifact_names(task_id)
    required: list[str] = []
    for criterion in acceptance_criteria or []:
        for match in _BUILD_FILENAME.findall(str(criterion)):
            clean = match.strip("/")  # (W2-T25) دون أكل نقطة الملف النقطي
            while clean.startswith("./"):
                clean = clean[2:]
            if (
                not clean or clean in own or clean in required
                or clean in _CREATE_GENERATED_NAMES
                or clean.startswith(_CREATE_GENERATED_PREFIXES)
                or clean.startswith("@/")            # (W2-T25) alias مستورد
                or ".." in clean.split("/")          # (W2-T25) استيراد أبوي
                or Path(clean).stem.isdigit()      # «3.mdx» رقم لا ملف
                or clean.lower() in _BUILD_TECH_NAMES  # «Next.js» تقنية
            ):
                continue
            required.append(clean)
    # (W2-T25) دليل بلا ملف: علامة .gitkeep تُطلب فيُخلق الدليل بكتابتها.
    for directory in _DIR_ONLY.findall(
            " ".join(map(str, acceptance_criteria or []))):
        d = directory.strip("/")
        marker = f"{d}/.gitkeep"
        if d and marker not in required \
                and not any(r.startswith(d + "/") for r in required):
            required.append(marker)
    return required[:_CREATE_MAX_FILES]


def _required_satisfied(required: str, seen: set[str]) -> bool:
    """(W2-T25) حاضر؟ الحرفية وحدها كانت تُفشل معايير الأدلة: «Directory
    src/app exists with layout.tsx» يستخرج المجرد والنموذج يكتب المتداخل
    (قياس 189) — فحكم «غائبة» كان زورًا."""
    if required in seen:
        return True
    if "/" in required:  # بمساره: لاحقة المسار نفسه، لا اسم مجرد بدليل آخر
        return any(s.endswith("/" + required) for s in seen)
    return any(Path(s).name == required for s in seen)  # مجردًا: الاسم يكفي


def parse_created_files(
    text: str, required_files: list[str],
) -> list[tuple[str, str]]:
    """تحليل رد الملفات: ‎### FILE: مسار ثم كتلة محتوى — يرفع
    ValueError موصوفة عند أي خلل؛ الغائبة تُسمّى حرفيًا."""
    matches = list(_CREATE_FILE_HEADER.finditer(text))
    if not matches:
        raise ValueError("لا كتل ### FILE: في الرد")
    files: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        # (W2-T25) تنظيف «./» رائد دون أكل نقطة ملف نقطي.
        path = match.group(1).strip()
        while path.startswith("./"):
            path = path[2:]
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        # تقشير أسوار الكود من الحافتين (يتحمل الأسوار المزدوجة/الخارجية)
        body_lines = body.splitlines()
        while body_lines and body_lines[0].strip().startswith("```"):
            body_lines.pop(0)
        while body_lines and body_lines[-1].strip() == "```":
            body_lines.pop()
        body = "\n".join(body_lines).rstrip()
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"مسار غير آمن: {path[:80]}")
        if len(path) > _CREATE_MAX_PATH:
            raise ValueError(f"مسار أطول من {_CREATE_MAX_PATH}: {path[:60]}")
        if path in seen:
            raise ValueError(f"ملف مكرر: {path}")
        if (
            Path(path).suffix.lower() not in _CREATE_ALLOWED_EXTS
            and Path(path).name.lower() not in _CREATE_ALLOWED_DOTFILES
        ):
            raise ValueError(f"امتداد غير مسموح: {path[:80]}")
        if not body.strip() and Path(path).name != ".gitkeep":
            raise ValueError(f"ملف فارغ: {path[:80]}")  # .gitkeep علامة فراغها طبيعتها
        if len(body) > _CREATE_MAX_CHARS:
            raise ValueError(
                f"الملف {path[:60]} يتجاوز {_CREATE_MAX_CHARS} حرفًا"
            )
        seen.add(path)
        files.append((path, body))
    missing = [p for p in required_files if not _required_satisfied(p, seen)]
    if missing:
        raise ValueError("ملفات مطلوبة غائبة عن الرد: " + ", ".join(missing))
    if not files:
        raise ValueError("لا ملفات صالحة")
    return files


def create_files_phase(
    *,
    live_call: Callable[[list[ChatMessage]], dict],
    system_prompt: str,
    task_payload: dict,
    materials: dict,
    required_files: list[str],
    previous_attempts: list[str],
    role: str,
) -> list[tuple[str, str]]:
    """النداء الحي الكامل لطور الإنشاء — إعادة واحدة ثم فشل صريح.

    live_call: مستدعى النموذج الخاص بالدور (يمر باختيار الدور إن وجد).
    يرفع RoleSystemFault(role, ...) بعد فشل التحليل في الإعادة.
    """
    payload = {
        "phase": "create_files",
        "task": task_payload,
        "required_files": required_files,
        "previous_attempts": list(previous_attempts or [])[:4],
        "materials_summary": {
            "search_results": [
                {"title": str(r.get("title", ""))[:120],
                 "url": str(r.get("url", ""))[:300]}
                for r in (materials.get("search_results") or [])[:10]
            ],
            "pages": [
                {"title": str(p.get("title", ""))[:120],
                 "url": str(p.get("url", ""))[:300]}
                for p in (materials.get("pages") or [])[:6]
            ],
        },
    }
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(
            role="user",
            content=json.dumps(payload, ensure_ascii=False)[:24000],
        ),
    ]
    last_error: Exception | None = None
    for _attempt in (1, 2):
        text = live_call(messages)["text"]
        try:
            return parse_created_files(text, required_files)
        except ValueError as error:
            last_error = error
            messages = messages + [
                ChatMessage(role="assistant", content=text[:2000]),
                ChatMessage(
                    role="user",
                    content=(
                        f"صيغة غير صالحة ({error}) — أعد كل الملفات "
                        "بصيغة ### FILE: <المسار> ثم كتلة محتوى "
                        "كاملة داخل أسوار كود"
                    ),
                ),
            ]
    raise RoleSystemFault(
        role,
        f"كتابة ملفات البناء فشلت بعد إعادة واحدة: {last_error}",
    )


def materials_with_created(
    materials: dict, created_files: list[tuple[str, str]],
) -> dict:
    """نسخة المادة لطلب التقرير — تشمل الملفات المنشأة ليوثّقها التقرير."""
    out = dict(materials)
    if created_files:
        out["created_files"] = [path for path, _body in created_files]
    return out


def _sources_section(markdown: str) -> str:
    """قسم «## المصادر» من التقرير — ما بعده حتى عنوان ## آخر أو النهاية."""
    parts = re.split(r"^##\s+", markdown, flags=re.MULTILINE)
    for part in parts[1:]:
        if part.strip().startswith("المصادر"):
            return part
    return ""


def write_sources_file(ctx, root: Path, report_md: str) -> Path | None:
    """ملف المصادر (W2-T23): الفعلية من قسم «## المصادر» بالتقرير، وعند
    نقصها تُستكمل من نتائج البحث — الدليل يطابق التقرير؛ عبر run_tool
    بأدلة sha256، أو None عند انعدام المصادر."""
    from roles.tools import run_tool

    report_urls = re.findall(
        r"https?://[^\s\)\]]+", _sources_section(report_md))
    title_by_url = {
        item.get("url", ""): item.get("title", "")
        for item in ctx.search_results
    }

    def _title_of(url: str) -> str:
        """عنوان المصدر: من نتائج البحث إن طابق، وإلا نص سطره."""
        if url in title_by_url and title_by_url[url]:
            return title_by_url[url]
        for line in _sources_section(report_md).splitlines():
            if url in line:
                head = line.split(url)[0]
                head = head.lstrip("-*• ").strip(" \u2014-:|")
                return head.strip()[:120]
        return ""

    seen: set[str] = set()
    sources: list[dict] = []
    for url in report_urls:
        clean = url.rstrip(".,;")
        if clean not in seen:
            seen.add(clean)
            sources.append({"title": _title_of(clean), "url": clean})
    if len(sources) < 5:
        for item in [*ctx.search_results, *ctx.data_urls]:
            url = item.get("url", "")
            if url and url not in seen:
                seen.add(url)
                sources.append({"title": item.get("title", ""), "url": url})
            if len(sources) >= 8:
                break
    if not sources:
        return None
    run_tool("write_file", {"path": "sources.json",
             "content": json.dumps(sources, ensure_ascii=False, indent=1)}, ctx)
    return root / "sources.json"


__all__ = [
    "create_files_phase",
    "materials_with_created",
    "own_artifact_names",
    "parse_created_files",
    "required_build_files",
    "write_sources_file",
]
