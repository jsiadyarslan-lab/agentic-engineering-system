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
    r"[\w@./-]+\.(?:astro|mjs|cjs|json|mdx|toml|yaml|yml|html|css"
    r"|tsx|jsx|csv|xml|txt|log|md|js|ts|py)(?!\w)"
)
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


def own_artifact_names(task_id: str) -> set[str]:
    """مخرجات الدور التلقائية — لا تُطلب من النموذج «بناؤها»."""
    return {
        f"{task_id}-report.md", f"{task_id}-report.pdf",
        "report.md", "report.pdf", "sources.json",
    }


def required_build_files(
    acceptance_criteria: list[str] | None, task_id: str,
) -> list[str]:
    """الملفات المصدرية التي تطلبها المعايير فعليًا (W2-T23).

    استخراج أسماء الملفات من نص المعايير، مع استبعاد مخرجات الدور
    التلقائية ونواتج الأوامر — قائمة فارغة = مهمة بحث/تقرير على
    مسارها الأصلي بلا أي تغيير في السلوك.
    """
    own = own_artifact_names(task_id)
    required: list[str] = []
    for criterion in acceptance_criteria or []:
        for match in _BUILD_FILENAME.findall(str(criterion)):
            clean = match.strip("./")
            if (
                not clean or clean in own or clean in required
                or clean in _CREATE_GENERATED_NAMES
                or clean.startswith(_CREATE_GENERATED_PREFIXES)
                or Path(clean).stem.isdigit()      # «3.mdx» رقم لا ملف
            ):
                continue
            required.append(clean)
    return required[:_CREATE_MAX_FILES]


def parse_created_files(
    text: str, required_files: list[str],
) -> list[tuple[str, str]]:
    """تحليل رد الملفات: ‎### FILE: مسار ثم كتلة محتوى — لكل ملف.

    يرفع ValueError موصوفة عند أي خلل (صيغة/أمان/اكتمال) — المتصل
    يقرر الإعادة؛ الغائبة من required_files تُسمّى في الرسالة حرفيًا.
    """
    matches = list(_CREATE_FILE_HEADER.finditer(text))
    if not matches:
        raise ValueError("لا كتل ### FILE: في الرد")
    files: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        path = match.group(1).strip().lstrip("./")
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
        if Path(path).suffix.lower() not in _CREATE_ALLOWED_EXTS:
            raise ValueError(f"امتداد غير مسموح: {path[:80]}")
        if not body.strip():
            raise ValueError(f"ملف فارغ: {path[:80]}")
        if len(body) > _CREATE_MAX_CHARS:
            raise ValueError(
                f"الملف {path[:60]} يتجاوز {_CREATE_MAX_CHARS} حرفًا"
            )
        seen.add(path)
        files.append((path, body))
    missing = [p for p in required_files if p not in seen]
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
    """ملف المصادر (W2-T23: مستخرج من implementer_live لرقته).

    المصادر الفعلية المذكورة في قسم «## المصادر» بالتقرير (اختيار
    النموذج الموثق)؛ وعند نقصها تُستكمل من نتائج البحث الفريدة —
    الدليل يطابق التقرير. يكتب عبر run_tool("write_file") بأدلة
    sha256 ويعيد مسار الملف أو None عند انعدام المصادر.
    """
    from roles.tools import run_tool

    report_urls = re.findall(
        r"https?://[^\s\)\]]+", _sources_section(report_md)
    )
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
    run_tool(
        "write_file",
        {
            "path": "sources.json",
            "content": json.dumps(sources, ensure_ascii=False, indent=1),
        },
        ctx,
    )
    return root / "sources.json"


__all__ = [
    "create_files_phase",
    "materials_with_created",
    "own_artifact_names",
    "parse_created_files",
    "required_build_files",
    "write_sources_file",
]
