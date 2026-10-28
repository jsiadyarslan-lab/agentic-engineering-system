# -*- coding: utf-8 -*-
"""اختبارات طور create_files للمنفذ الحي (W2-T23).

تغطي: استخراج الملفات المطلوبة من المعايير (مع استبعاد نواتج الأوامر
ومخرجات الدور)، تحليل رد ### FILE: (صلاحية/أمان/اكتمال)، تكامل run()
بموجه مزيف (بناء حقيقي على القرص + أدلة sha256)، وعدم مساس مسار
مهام البحث/التقرير الأصلي (استدعاءان حصرًا).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import roles.implementer_live as impl_mod
from roles import build_files
from roles.implementer import ImplementerRequest, ImplementerStatus
from roles.implementer_live import LiveImplementer
from roles.thinker import PlanTask
from router.model_router import ChatMessage


class FakeRouter:
    """موجّه مسجَّل — يعيد النصوص بالترتيب ويعدّ الاستدعاءات."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def chat_live(self, messages, **_kwargs):
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("استدعاءات أكثر من الاستجابات المسجلة")
        return {"text": self.responses.pop(0), "provider": "fake",
                "model": "fake", "tokens": 1, "duration_ms": 1}


# ------------------------------------------------------------------ #
# 1) استخراج الملفات المطلوبة من المعايير
# ------------------------------------------------------------------ #

STEP102_CRITERIA = [
    "package.json exists with name, version, type:module, scripts (dev, build, preview), dependencies (astro, typescript, @astrojs/tailwind), devDependencies",
    "tsconfig.json exists with extends: ['astro/tsconfigs/strict']",
    "astro.config.mjs exists with import tailwind from '@astrojs/tailwind', export default defineConfig({ integrations: [tailwind()], site: 'http://localhost:4321' })",
]


def test_required_build_files_step102():
    """معايير الخطوة 102 الحقيقية → الملفات الثلاثة المطلوبة."""
    required = build_files.required_build_files(STEP102_CRITERIA, "T1")
    assert required == ["package.json", "tsconfig.json", "astro.config.mjs"]


def test_required_build_files_research_task_empty():
    """مهمة بحث (تقرير/مصادر فقط) → لا ملفات بناء — مسارها الأصلي."""
    criteria = [
        "report.md يحتوي ملخصًا بالمصادر",
        "sources.json يوثق 5-8 مصادر",
        "التقرير 180-240 كلمة",
    ]
    assert build_files.required_build_files(criteria, "T1") == []
    assert build_files.required_build_files([], "T1") == []
    assert build_files.required_build_files(None, "T1") == []


def test_required_build_files_filters_command_outputs():
    """نواتج الأوامر (node_modules/dist/الأقفال) لا تُطلب من النموذج."""
    criteria = [
        "npm install executes with exit code 0",
        "node_modules/astro exists",
        "package-lock.json exists",
        "dist/index.html exists with real content",
        "src/pages/index.astro exists with basic structure",
    ]
    required = build_files.required_build_files(criteria, "T1")
    assert required == ["src/pages/index.astro"]


def test_required_build_files_astro_layouts():
    """معايير الخطوات الملفية 104-108 تُستخرج بمساراتها الكاملة."""
    criteria = [
        "src/styles/global.css exists with @tailwind base; @tailwind components; @tailwind utilities;",
        "src/env.d.ts exists with /// <reference types=\"astro/client\" />",
        "src/layouts/BaseLayout.astro exists with DOCTYPE, html, head (meta charset, viewport, title, description), body with Header, slot, Footer, imports ../styles/global.css",
        "src/content/config.ts exists with defineCollection for 'articles' and 'categories' using z schemas",
    ]
    required = build_files.required_build_files(criteria, "T1")
    assert "src/styles/global.css" in required
    assert "src/env.d.ts" in required
    assert "src/layouts/BaseLayout.astro" in required
    assert "src/content/config.ts" in required


# ------------------------------------------------------------------ #
# 2) تحليل رد ### FILE:
# ------------------------------------------------------------------ #

def _parse(text, required):
    return build_files.parse_created_files(text, required)


def test_parse_created_files_valid():
    router = FakeRouter([])
    text = (
        "### FILE: package.json\n"
        "```json\n"
        "{\"name\": \"news-site\", \"version\": \"0.1.0\"}\n"
        "```\n"
        "### FILE: astro.config.mjs\n"
        "```js\n"
        "import { defineConfig } from 'astro/config';\n"
        "export default defineConfig({ site: 'http://localhost:4321' });\n"
        "```\n"
    )
    files = _parse(text, ["package.json", "astro.config.mjs"])
    assert [p for p, _ in files] == ["package.json", "astro.config.mjs"]
    assert json.loads(files[0][1])["name"] == "news-site"
    assert "defineConfig" in files[1][1]


def test_parse_created_files_missing_required():
    router = FakeRouter([])
    text = (
        "### FILE: package.json\n"
        "```json\n"
        "{\"name\": \"x\"}\n"
        "```\n"
    )
    with pytest.raises(ValueError) as err:
        _parse(text, ["package.json", "tsconfig.json"])
    assert "tsconfig.json" in str(err.value)


@pytest.mark.parametrize("bad_path", [
    "/etc/passwd", "../escape.json", "a/../../b.json",
])
def test_parse_created_files_unsafe_path(bad_path):
    router = FakeRouter([])
    text = "### FILE: %s\n```\ncontent\n```\n" % bad_path
    with pytest.raises(ValueError):
        _parse(text, [bad_path])


def test_parse_created_files_bad_extension_and_empty():
    with pytest.raises(ValueError):
        _parse("### FILE: run.sh\n```\necho hi\n```\n", ["run.sh"])
    with pytest.raises(ValueError):
        _parse("### FILE: empty.json\n```\n\n```\n", ["empty.json"])
    with pytest.raises(ValueError):
        _parse("لا كتل إطلاقًا", ["x.json"])


# ------------------------------------------------------------------ #
# 3) تكامل run() — مهمة بناء كاملة بموجه مزيف وأدوات مزيفة
# ------------------------------------------------------------------ #

CREATE_RESPONSE = (
    "### FILE: package.json\n"
    "```json\n"
    "{\"name\": \"news-website\", \"version\": \"0.1.0\", "
    "\"type\": \"module\", \"scripts\": {\"dev\": \"astro dev\"}}\n"
    "```\n"
    "### FILE: tsconfig.json\n"
    "```json\n"
    "{\"extends\": [\"astro/tsconfigs/strict\"]}\n"
    "```\n"
    "### FILE: astro.config.mjs\n"
    "```js\n"
    "import { defineConfig } from 'astro/config';\n"
    "export default defineConfig({ site: 'http://localhost:4321' });\n"
    "```\n"
)

REPORT_MD = (
    "# تقرير إنشاء هيكل مشروع Astro\n\n"
    "## الملفات المنشأة\n"
    "أنشأت ملفات هيكل المشروع الثلاثة المطلوبة بالمعايير: package.json "
    "بحقول الاسم والإصدار والنوع والنصوص، وtsconfig.json بامتداد إعدادات "
    "Astro الصارمة، وastro.config.mjs بتكامل Tailwind والموقع المحلي.\n\n"
    "## ملاحظات البناء\n"
    "المحتوى كامل قابل للتشغيل ولا يحوي مواضع placeholders، والمسارات "
    "نسبية تحت مساحة العمل الممنوحة. أوصي بالتحقق الميكانيكي من الحقول "
    "النصية داخل كل ملف قبل الانتقال لخطوة تثبيت الاعتماديات.\n\n"
    "## المصادر\n"
    "- Astro Docs — https://docs.astro.build/\n"
    "- TypeScript — https://www.typescriptlang.org/\n"
)


def _build_request(tmp_path, criteria, previous=None):
    task = PlanTask(
        id="T1", description="Create Astro project structure",
        acceptance_criteria=criteria,
    )
    return ImplementerRequest(
        task=task, tools_available=["python"],
        sandbox_root=str(tmp_path / "ws"),
        previous_attempts=list(previous or []),
    )


def _fake_tools(monkeypatch, tmp_path):
    """أدوات مزيفة: بحث يملأ المادة، وكتابة تلمس القرص فعلًا."""
    import roles.tools as roles_tools_mod

    written: list[dict] = []

    def fake_recovery(ctx, tool, args, *, attempt, attempted_queries,
                      available_urls, materials, failed_calls, max_results):
        materials["search_results"].append({
            "title": "Astro Docs",
            "url": "https://docs.astro.build/",
        })
        return None

    def fake_run_tool(name, args, ctx, *, attempt=1):
        if name == "write_file":
            target = Path(ctx.grant_root) / args["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
            written.append({"path": args["path"],
                            "chars": len(args["content"])})
            return str(target)
        if name == "verify_pdf_pages":
            return 1
        return str(Path(ctx.grant_root) / args.get("path", ""))

    monkeypatch.setattr(impl_mod, "run_with_recovery", fake_recovery)
    # رقعتان للاسم نفسه: ربط implementer_live (استيراد أعلى الملف)
    # وربط roles.tools (الاستيراد المحلي داخل build_files.write_sources_file)
    monkeypatch.setattr(impl_mod, "run_tool", fake_run_tool)
    monkeypatch.setattr(roles_tools_mod, "run_tool", fake_run_tool)
    return written


def test_run_build_task_creates_files(tmp_path, monkeypatch):
    """مهمة بناء: نداء create_files يحدث، الملفات تُكتب فعلًا، والأدلة sha256."""
    written = _fake_tools(monkeypatch, tmp_path)
    router = FakeRouter([
        "web_search | Astro project structure\nfetch_page | https://docs.astro.build/\n",
        CREATE_RESPONSE,
        REPORT_MD,
    ])
    implementer = LiveImplementer(router)
    result = implementer.run(_build_request(tmp_path, STEP102_CRITERIA))

    assert result.status is ImplementerStatus.EXECUTED, result.stderr_truncated
    # ثلاثة نداءات: خطة أدوات → إنشاء ملفات → تقرير
    assert len(router.calls) == 3
    # حمولة الإنشاء تحمل الملفات المطلوبة وتغذية المحاولات السابقة
    create_payload = json.loads(router.calls[1][-1].content)
    assert create_payload["phase"] == "create_files"
    assert create_payload["required_files"] == [
        "package.json", "tsconfig.json", "astro.config.mjs"]
    # الملفات الثلاثة كُتبت إلى القرص فعليًا
    written_paths = {w["path"] for w in written}
    assert {"package.json", "tsconfig.json", "astro.config.mjs"} <= written_paths
    for name in ("package.json", "tsconfig.json", "astro.config.mjs"):
        on_disk = Path(result.artifacts[0]).parent / name
        assert on_disk.is_file(), name
    # الأدلة تحمل sha256 لكل ملف بناء
    build_refs = [r for r in result.evidence_refs
                  if r.endswith(("package.json", "tsconfig.json",
                                 "astro.config.mjs"))]
    assert len(build_refs) == 3
    assert all(r.startswith("sha256:") for r in build_refs)
    # رسالة المخرج تذكر ملفات البناء
    assert "3 ملف بناء" in result.stdout_truncated


def test_run_build_task_includes_previous_feedback(tmp_path, monkeypatch):
    """تغذية المراجع السابقة تصل حمولة الإنشاء — محاولة الإصلاح واعية."""
    _fake_tools(monkeypatch, tmp_path)
    router = FakeRouter([
        "web_search | Astro tsconfig\n",
        CREATE_RESPONSE,
        REPORT_MD,
    ])
    implementer = LiveImplementer(router)
    previous = [
        "محاولة 1: not_evidenced — الملف package.json غائب عن الأدلة",
    ]
    implementer.run(_build_request(tmp_path, STEP102_CRITERIA, previous))
    create_payload = json.loads(router.calls[1][-1].content)
    assert create_payload["previous_attempts"] == previous


def test_run_research_task_unchanged(tmp_path, monkeypatch):
    """مهمة بحث/تقرير: نداءان حصرًا (خطة + تقرير) — لا انحطاط بالسلوك القديم."""
    _fake_tools(monkeypatch, tmp_path)
    router = FakeRouter([
        "web_search | موضوع عام\n",
        REPORT_MD,
    ])
    implementer = LiveImplementer(router)
    criteria = ["report.md يحتوي ملخصًا", "sources.json يوثق المصادر"]
    result = implementer.run(_build_request(tmp_path, criteria))
    assert result.status is ImplementerStatus.EXECUTED
    assert len(router.calls) == 2  # خطة الأدوات ثم التقرير — بلا إنشاء
    phases = [
        json.loads(c[-1].content).get("phase") for c in router.calls
    ]
    assert phases == ["plan_tools", "write_report"]


def test_run_build_task_with_retry_on_bad_format(tmp_path, monkeypatch):
    """رد غير صالح أولًا ثم صالح — إعادة التحليل الواحدة تنجح."""
    _fake_tools(monkeypatch, tmp_path)
    router = FakeRouter([
        "web_search | Astro config\n",
        "سأكتب التقرير فقط بلا ملفات",  # غير صالح: لا كتل FILE
        CREATE_RESPONSE,
        REPORT_MD,
    ])
    implementer = LiveImplementer(router)
    result = implementer.run(_build_request(tmp_path, STEP102_CRITERIA))
    assert result.status is ImplementerStatus.EXECUTED
    assert len(router.calls) == 4  # خطة + إنشاء (فاشل) + إنشاء (صالح) + تقرير


# ------------------------------------------------------------------ #
# (W2-T25) أسماء تقنية ليست ملفات + ملفات نقطية
# ------------------------------------------------------------------ #

def test_required_build_files_filters_tech_names():
    """«Next.js»/«Node.js» أسماء تقنية — لا تُطلب كملفات (الخطوة 130
    أفشلت تنفيذين كاملين بمطالبة كاذبة بملف اسمه Next.js)."""
    criteria = [
        "tsconfig.json with strict TypeScript for Next.js 14",
        "next.config.js with output export",
        "Node.js 20 LTS runtime configuration",
        "Vue.js components compile with Vite",
    ]
    req = build_files.required_build_files(criteria, "T1")
    assert "Next.js" not in req
    assert "Node.js" not in req
    assert "Vue.js" not in req
    assert "tsconfig.json" in req
    assert "next.config.js" in req


def test_required_build_files_extracts_dotfiles():
    """.prettierrc/.gitignore تُطلب فعلًا حين تذكرها المعايير."""
    criteria = [
        ".prettierrc with singleQuote and trailingComma es5",
        ".gitignore with node_modules and dist entries",
    ]
    req = build_files.required_build_files(criteria, "T1")
    assert ".prettierrc" in req
    assert ".gitignore" in req


def test_parse_created_files_accepts_dotfiles():
    text = (
        "### FILE: .prettierrc\n```\n{\n  \"singleQuote\": true,\n"
        "  \"trailingComma\": \"es5\",\n  \"printWidth\": 80\n}\n"
        "```\n### FILE: .gitignore\n```\nnode_modules/\ndist/\n"
        ".next/\n```\n"
    )
    files = build_files.parse_created_files(
        text, [".prettierrc", ".gitignore"])
    paths = [p for p, _ in files]
    assert ".prettierrc" in paths and ".gitignore" in paths


def test_parse_created_files_still_rejects_disallowed():
    """امتداد غير مسموح يبقى مرفوضًا — الملفات النقطية استثناء معلن
    بالاسم الكامل لا فتحة عشوائية."""
    text = "### FILE: evil.exe\n```\nbinary\n```\n"
    with pytest.raises(ValueError, match="امتداد غير مسموح"):
        build_files.parse_created_files(text, [])


def test_parse_created_files_rejects_unknown_dotfile():
    """dotfile خارج القائمة المعلنة يُرفض — لا تمرير أوسع."""
    text = "### FILE: .secret\n```\nx\n```\n"
    with pytest.raises(ValueError, match="امتداد غير مسموح"):
        build_files.parse_created_files(text, [])
