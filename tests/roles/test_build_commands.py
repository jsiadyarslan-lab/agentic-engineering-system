# -*- coding: utf-8 -*-
"""اختبارات طور أوامر البناء الحقيقية (W2-T24).

تغطي: استخراج الأوامر من معايير الخطوات 103/110 الحقيقية، تجميع
متطلبات الخطوات السابقة (نسخ المصدرية وsymlink لnode_modules)، أداة
run_build_command (قائمة بيضاء، فشل الأدوات مصنّف BUILD_TOOLING_MISSING،
نجاح حقيقي بـnpm مزيف يكتب package-lock.json فعليًا، preview يراقب
Local/Network)، والطور الكامل مع تكامل run() بخطوة 103 كاملة.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

import roles.implementer_live as impl_mod
from roles import build_commands, build_files
from roles.implementer import ImplementerRequest, ImplementerStatus
from roles.implementer_live import LiveImplementer
from roles.thinker import PlanTask
from roles.tools import ToolContext, run_tool
from roles.tool_failures import ToolFailure
from router.model_router import ChatMessage


STEP103_CRITERIA = [
    "npm install executes with exit code 0",
    "node_modules/astro exists",
    "node_modules/typescript exists",
    "node_modules/@astrojs/tailwind exists",
    "package-lock.json exists",
]

STEP110_CRITERIA = [
    "npm run build executes with exit code 0",
    "dist/ directory exists with index.html, article/*, category/*, rss.xml, assets/",
    "npm run preview starts and binds to port (verified by process output containing 'Local' or 'Network' URL)",
    "No TypeScript errors in build output",
]

#: (W2-T25) معايير الخطوة 492 الحرفية (خطة v50) — تحقق خادم Express.
STEP492_CRITERIA = [
    "Command `node server.js` starts and binds to port 3000 "
    "(verified by stdout containing 'Server running on port 3000')",
    "HTTP GET to http://localhost:3000/api/articles returns 200 "
    "and JSON array matching seed data",
    "Process terminates cleanly on SIGINT",
]


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
# 1) استخراج الأوامر من المعايير
# ------------------------------------------------------------------ #

def test_required_build_commands_step103():
    """معايير الخطوة 103 الحقيقية → أمر واحد: npm install."""
    assert build_commands.required_build_commands(
        STEP103_CRITERIA) == ["npm install"]


def test_required_build_commands_step110_order():
    """معايير 110: build قبل preview (ترتيب التبعية)."""
    commands = build_commands.required_build_commands(STEP110_CRITERIA)
    assert commands == ["npm run build", "npm run preview"]


def test_required_build_commands_step492_server():
    """معايير 492 الحرفية: خادم Express يُستخرج أمر تشغيله الفعلي —
    قياس حي (التنفيذ 288): الطور لم يستخرج شيئًا فلم يُشغّل الخادم
    أصلًا والتدقيق حكم بالمفقود والدورة أعادت الخطة كاملة."""
    commands = build_commands.required_build_commands(STEP492_CRITERIA)
    assert commands == ["node server.js"]


#: (W2-T25) معايير الخطوة 497 الحرفية (خطة v51) — مهيّء خلفي متداخل.
STEP497_CRITERIA = [
    "File backend/package.json contains dependencies: express, cors, "
    "dotenv, jest, supertest",
    "File backend/src/server.js imports and uses health router",
    "File backend/src/routes/health.js exports router with GET /health",
    "File backend/tests/health.test.js exists and passes when running "
    "`npm test`",
]


def test_required_build_commands_step497_npm_test():
    """معايير 497 الحرفية: npm test يُستخرج — قياس حي (التنفيذان 290/291):
    الملفات الأربعة كُتبت صحيحة والمراجع صدّق «الأدلة الكلية ناقصة:
    Test execution logs for npm test run in backend» فتصعيد
    ESCALATED_TO_HUMAN مرتين — الأمر لم يكن قابلًا للتنفيذ أصلًا."""
    commands = build_commands.required_build_commands(STEP497_CRITERIA)
    assert commands == ["npm test"]


def test_required_build_commands_research_empty():
    """مهمة بحث/ملفات بلا أوامر → قائمة فارغة (الطور لا يعمل)."""
    assert build_commands.required_build_commands(
        STEP103_CRITERIA[:0]) == []
    assert build_commands.required_build_commands(None) == []
    assert build_commands.required_build_commands([
        "src/pages/index.astro exists with basic structure",
    ]) == []


# ------------------------------------------------------------------ #
# 2) تجميع متطلبات الخطوات السابقة
# ------------------------------------------------------------------ #

def _project_tree(tmp_path: Path, with_node_modules: bool = True) -> Path:
    steps = tmp_path / "projects" / "3" / "steps"
    (steps / "102").mkdir(parents=True)
    (steps / "102" / "package.json").write_text('{"name": "news"}')
    (steps / "102" / "astro.config.mjs").write_text("export default {}")
    src_pages = steps / "102" / "src" / "pages"
    src_pages.mkdir(parents=True)
    (src_pages / "index.astro").write_text("---\n---\n<h1>News</h1>")
    if with_node_modules:
        (steps / "102" / "node_modules" / "astro").mkdir(parents=True)
        (steps / "102" / "node_modules" / "astro" / "package.json").write_text("{}")
    (steps / "103").mkdir()
    return steps / "103"


def test_gather_prerequisites_copies_and_links(tmp_path):
    """package.json/src تُنسخ وnode_modules يُوصل symlink — لا نسخ ثقيل."""
    root = _project_tree(tmp_path)
    gathered = build_commands.gather_build_prerequisites(root)

    assert (root / "package.json").is_file()
    assert (root / "astro.config.mjs").is_file()
    assert (root / "src" / "pages" / "index.astro").is_file()
    node_modules = root / "node_modules"
    assert node_modules.is_symlink(), "node_modules يجب أن يكون symlink"
    assert (node_modules / "astro" / "package.json").is_file()
    assert "package.json" in gathered["copied"]
    assert "node_modules" in gathered["linked"]


def test_gather_prerequisites_never_overwrites_current(tmp_path):
    """ما أنشأته الخطوة الحالية له الأولوية — لا استبدال."""
    root = _project_tree(tmp_path)
    (root / "package.json").write_text('{"name": "current"}')
    build_commands.gather_build_prerequisites(root)
    assert json.loads(
        (root / "package.json").read_text())["name"] == "current"


def test_gather_prerequisites_copies_server_js(tmp_path):
    """server.js من خطوة سابقة يُجلب لخطوة التحقق (قياس 492: المدقق
    طلب الملف حاضرًا في أدلة الخطوة 492 وهو في مساحة الخطوة 491)."""
    steps = tmp_path / "projects" / "3" / "steps"
    (steps / "491").mkdir(parents=True)
    (steps / "491" / "server.js").write_text(
        "console.log('Server running on port 3000');\n")
    (steps / "492").mkdir()
    gathered = build_commands.gather_build_prerequisites(steps / "492")
    assert (steps / "492" / "server.js").is_file()
    assert "server.js" in gathered["copied"]


# ------------------------------------------------------------------ #
# 3) أداة run_build_command
# ------------------------------------------------------------------ #

def _make_stub_tools(tmp_path: Path) -> Path:
    """npm/node مزيفان: install يكتب package-lock.json فعليًا."""
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    npm = stub_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "case \"$1 $2\" in\n"
        "  \"install \") echo '{\"lockfileVersion\": 3}' > package-lock.json;"
        " echo stub-install-ok ;;\n"
        "  \"run build\") mkdir -p dist; echo '<html></html>' > dist/index.html;"
        " echo stub-build-ok ;;\n"
        "  \"run preview\") echo '  Local: http://localhost:4321/';"
        " sleep 30 ;;\n"
        "  *) echo stub-$1 ;;\n"
        "esac\n"
    )
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    node = stub_dir / "node"
    node.write_text("#!/bin/sh\necho v22.0.0-stub\n")
    node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    npx = stub_dir / "npx"  # (W2-T25) أدوات التحقق تعبر npx
    npx.write_text("#!/bin/sh\necho htmlhint: 0 errors\n")
    npx.chmod(npx.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    pnpm = stub_dir / "pnpm"  # (W2-T25) pnpm dev كمعاينة
    pnpm.write_text("#!/bin/sh\ncase \"$1\" in dev) echo '  Local: http://localhost:3000/'; sleep 20 ;; *) echo pnpm-$1 ;; esac\n")
    pnpm.chmod(pnpm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return stub_dir


def _patch_tool_paths(monkeypatch, stub_dir: Path | None):
    """توجيه حل الأدوات إلى الـstubs — أو لا شيء (أدوات غائبة)."""
    def fake_which(name: str):
        if stub_dir is None:
            return None
        candidate = stub_dir / name
        return str(candidate) if candidate.exists() else None

    monkeypatch.setattr("shutil.which", fake_which)


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(grant_root=tmp_path)


def test_run_build_command_rejects_non_whitelisted(tmp_path, monkeypatch):
    """أمر خارج القائمة البيضاء → POLICY_BLOCK صريح."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    with pytest.raises(ToolFailure) as err:
        run_tool("run_build_command",
                 {"command": "rm -rf /"}, _ctx(tmp_path))
    assert err.value.reason == "COMMAND_NOT_WHITELISTED"
    assert err.value.failure_class == "POLICY_BLOCK"


def test_run_build_command_missing_tooling_classified(tmp_path, monkeypatch):
    """node/npm غائبان → BUILD_TOOLING_MISSING مصنّفًا غير قابل للإعادة."""
    _patch_tool_paths(monkeypatch, None)
    with pytest.raises(ToolFailure) as err:
        run_tool("run_build_command",
                 {"command": "npm install"}, _ctx(tmp_path))
    assert err.value.reason == "BUILD_TOOLING_MISSING"
    assert err.value.failure_class == "DEPENDENCY_FAILURE"
    assert err.value.retryable is False
    assert err.value.details["missing"] == ["node", "npm"]


def test_run_build_command_real_success_writes_evidence(
        tmp_path, monkeypatch):
    """npm مزيف يكتب package-lock.json فعليًا — أدلة exit_code على القرص."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    ctx = _ctx(tmp_path)
    value = run_tool("run_build_command",
                     {"command": "npm install", "timeout_s": 60}, ctx)
    assert value["exit_code"] == 0
    assert (tmp_path / "package-lock.json").is_file(), "الأمر نفّذ فعليًا"
    exit_json = tmp_path / "evidence" / "build-npm-install-exit.json"
    assert exit_json.is_file()
    record = json.loads(exit_json.read_text())
    assert record["command"] == "npm install"
    assert record["exit_code"] == 0
    assert (tmp_path / "evidence" / "build-npm-install-stdout.txt").is_file()


def test_run_build_command_nonzero_exit_fails_honestly(
        tmp_path, monkeypatch):
    """خروج غير صفري → BUILD_COMMAND_FAILED بذيل stderr الحقيقي."""
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    npm = stub_dir / "npm"
    npm.write_text("#!/bin/sh\necho real-error-detail >&2\nexit 7\n")
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    node = stub_dir / "node"
    node.write_text("#!/bin/sh\necho v22.0.0-stub\n")
    node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    _patch_tool_paths(monkeypatch, stub_dir)

    with pytest.raises(ToolFailure) as err:
        run_tool("run_build_command",
                 {"command": "npm install"}, _ctx(tmp_path))
    assert err.value.reason == "BUILD_COMMAND_FAILED"
    assert err.value.details["exit_code"] == 7
    assert "real-error-detail" in err.value.details["stderr_tail"]


def test_run_build_command_preview_watches_url(tmp_path, monkeypatch):
    """preview: رؤية Local تُثبت النجاح ويُقتل الخادم — لا انتظار 30ث."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    import time as _time

    started = _time.monotonic()
    value = run_tool("run_build_command",
                     {"command": "npm run preview", "timeout_s": 30},
                     _ctx(tmp_path))
    elapsed = _time.monotonic() - started
    assert value["preview_url_seen"] is True
    assert value["exit_code"] == 0
    assert elapsed < 20, "الخادم يُقتل فور رؤية العنوان لا بعد المهل"
    exit_json = tmp_path / "evidence" / "build-npm-run-preview-exit.json"
    assert "Local" in exit_json.read_text()


def test_run_build_command_node_server_watches_binding(
        tmp_path, monkeypatch):
    """node server.js: رؤية سطر البدء تُثبت الربط ويُقتل الخادم — stdout
    حقيقي في الأدلة (قياس 492: التحقق بالتنفيذ الفعلي لا بالوصف)."""
    import time as _time
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    node = stub_dir / "node"
    node.write_text(
        "#!/bin/sh\n"
        "echo 'Server running on port 3000'\n"
        "sleep 30\n"
    )
    node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    npm = stub_dir / "npm"
    npm.write_text("#!/bin/sh\necho stub-npm\n")
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    _patch_tool_paths(monkeypatch, stub_dir)

    started = _time.monotonic()
    value = run_tool("run_build_command",
                     {"command": "node server.js", "timeout_s": 30},
                     _ctx(tmp_path))
    elapsed = _time.monotonic() - started
    assert value["preview_url_seen"] is True
    assert value["exit_code"] == 0
    assert elapsed < 20, "الخادم يُقتل فور سطر البدء لا بعد المهل"
    stdout_txt = tmp_path / "evidence" / "build-node-server.js-stdout.txt"
    assert "Server running on port 3000" in stdout_txt.read_text()


def test_run_build_command_npm_test_in_nested_cwd(
        tmp_path, monkeypatch):
    """npm test بدليل متداخل (backend/): الأمر يعمل حيث المشروع والأدلة
    في جذر الخطوة — قياس 497: «Test execution logs for npm test run in
    backend» يُثبتها سجل حقيقي لا وصف."""
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    npm = stub_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in test) echo 'PASS health.test.js'; echo '"
        "1 passing'; echo '{\"lockfileVersion\": 3}' > package-lock.json "
        ";; *) echo stub-$1 ;; esac\n"
    )
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    node = stub_dir / "node"
    node.write_text("#!/bin/sh\necho v22.0.0-stub\n")
    node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    _patch_tool_paths(monkeypatch, stub_dir)

    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "package.json").write_text(
        '{"name": "news-backend", "scripts": {"test": "jest"}}')
    value = run_tool(
        "run_build_command",
        {"command": "npm test", "timeout_s": 60, "cwd": "backend"},
        _ctx(tmp_path))
    assert value["exit_code"] == 0
    # التنفيذ في backend/ — الأدلة في جذر الخطوة (يراها المراجع)
    assert (backend / "package-lock.json").is_file(), "npm شغّل في backend/"
    stdout_txt = tmp_path / "evidence" / "build-npm-test-stdout.txt"
    assert "1 passing" in stdout_txt.read_text()


def test_run_build_command_sanitized_env_no_secrets(tmp_path, monkeypatch):
    """بيئة الأمر منظفة — مفاتيح الخدمة لا تصل سكربتات npm."""
    from roles import tools as tools_mod

    monkeypatch.setenv("SEARCH_API_KEY", "secret-48hex-value")
    stub_dir = _make_stub_tools(tmp_path)
    probe = tmp_path / "env-probe"
    probe.mkdir()
    (probe / "pkg.json").write_text("{}")
    npm = stub_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"install\" ]; then env | grep -c SEARCH_API_KEY "
        "> search-api-leak.txt 2>/dev/null || echo 0 > search-api-leak.txt; "
        "echo '{}' > package-lock.json; fi\n"
        "echo ok\n"
    )
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    _patch_tool_paths(monkeypatch, stub_dir)

    ctx = ToolContext(grant_root=probe)
    run_tool("run_build_command", {"command": "npm install"}, ctx)
    leak_file = probe / "search-api-leak.txt"
    assert leak_file.read_text().strip() == "0", (
        "سر الخدمة يجب ألا يصل بيئة أمر البناء"
    )


# ------------------------------------------------------------------ #
# 4) الطور الكامل + تكامل run() بخطوة 103
# ------------------------------------------------------------------ #

def test_phase_tooling_missing_returns_failed_result(tmp_path, monkeypatch):
    """فقد الأدوات → ImplementerResult فاشل بتوقيع BUILD_TOOLING_MISSING."""
    _patch_tool_paths(monkeypatch, None)
    outcome = build_commands.run_build_commands_phase(
        _ctx(tmp_path), tmp_path, ["npm install"], STEP103_CRITERIA)
    assert outcome.failed_result is not None
    assert "BUILD_TOOLING_MISSING" in outcome.failed_result.stderr_truncated
    assert outcome.failed_result.failure["reason"] == "BUILD_TOOLING_MISSING"


def test_phase_success_collects_criterion_artifacts(tmp_path, monkeypatch):
    """npm حقيقي (مزيف) → package-lock.json على القرص ضمن الأدلة."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    root = _project_tree(tmp_path)
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, ["npm install"], STEP103_CRITERIA)
    assert outcome.failed_result is None
    assert outcome.results[0]["exit_code"] == 0
    artifact_names = {a.name for a in outcome.artifacts}
    assert "package-lock.json" in artifact_names
    assert (root / "package-lock.json").is_file()


def test_phase_ensures_install_before_build(tmp_path, monkeypatch):
    """build بلا node_modules (خطوة سابقة بلا ناتج) ⇒ install يُقحم أولًا."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    root = _project_tree(tmp_path, with_node_modules=False)
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, ["npm run build"], STEP110_CRITERIA)
    assert outcome.failed_result is None
    executed = [r["command"] for r in outcome.results]
    assert executed == ["npm install", "npm run build"]
    assert (root / "package-lock.json").is_file()
    assert (root / "dist" / "index.html").is_file()
    artifact_names = {a.name for a in outcome.artifacts}
    assert "index.html" in artifact_names


def test_phase_node_server_gathers_and_evidences(tmp_path, monkeypatch):
    """طور كامل لخطوة تحقق خادم (492): الجلب + التشغيل الحقيقي + أدلة
    stdout الفعلية — الخادم الذي لا يصرح بسطر بدء يفشل بصدق."""
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    node = stub_dir / "node"
    node.write_text(
        "#!/bin/sh\n"
        "echo 'Server running on port 3000'\n"
        "sleep 30\n"
    )
    node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    npm = stub_dir / "npm"
    npm.write_text("#!/bin/sh\necho stub-npm\n")
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    _patch_tool_paths(monkeypatch, stub_dir)

    steps = tmp_path / "projects" / "3" / "steps"
    (steps / "491").mkdir(parents=True)
    (steps / "491" / "server.js").write_text(
        "console.log('Server running on port 3000');\n")
    root = steps / "492"
    root.mkdir()
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, ["node server.js"], STEP492_CRITERIA)
    assert outcome.failed_result is None
    assert outcome.results[0]["preview_url_seen"] is True
    assert (root / "server.js").is_file(), "الجلب نسخ خادم الخطوة السابقة"
    stdout_txt = root / "evidence" / "build-node-server.js-stdout.txt"
    assert "Server running on port 3000" in stdout_txt.read_text()


def test_phase_npm_test_nested_backend_runs_and_evidences(
        tmp_path, monkeypatch):
    """طور كامل لخطوة 497 (خلفي متداخل): install يُقحم وnpm test يعمل في
    backend/ والأدلة (stdout/exit) في جذر الخطوة يراها المراجع."""
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    npm = stub_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in install) echo '{\"lockfileVersion\": 3}' "
        "> package-lock.json; echo installed ;; "
        "test) echo 'PASS health.test.js'; echo '1 passing' ;; "
        "*) echo stub-$1 ;; esac\n"
    )
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    node = stub_dir / "node"
    node.write_text("#!/bin/sh\necho v22.0.0-stub\n")
    node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    _patch_tool_paths(monkeypatch, stub_dir)

    steps = tmp_path / "projects" / "3" / "steps"
    (steps / "496").mkdir(parents=True)
    (steps / "496" / "package.json").write_text('{"name": "dead-astro"}')
    root = steps / "497"
    root.mkdir()
    backend = root / "backend"
    backend.mkdir()
    (backend / "package.json").write_text(
        '{"name": "news-backend", "scripts": {"test": "jest"}}')
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, ["npm test"], STEP497_CRITERIA)
    assert outcome.failed_result is None
    executed = [r["command"] for r in outcome.results]
    assert executed == ["npm install", "npm test"]
    # المتداخل: لا خلط أطر ميتة — جذر الخطوة بلا package.json زائد
    assert not (root / "package.json").is_file(), "لا تلوث إطار ميت"
    assert (backend / "package-lock.json").is_file(), "install في backend/"
    stdout_txt = root / "evidence" / "build-npm-test-stdout.txt"
    assert "1 passing" in stdout_txt.read_text()
    artifact_names = {p.name for p in outcome.artifacts}
    assert "build-npm-test-stdout.txt" in artifact_names


REPORT_MD_103 = (
    "# تقرير تثبيت الاعتماديات\n\n"
    "## ما نُفّذ\n"
    "نفّذ النظام أمر npm install فعليًا داخل مساحة الخطوة بعد جلب "
    "متطلبات الخطوة السابقة (package.json وastro.config.mjs)، وانتهى "
    "بخروج صفري موثق بأدلة exit_code على القرص.\n\n"
    "## المصادر\n"
    "- npm Docs — https://docs.npmjs.com/\n"
)


def _fake_tools_research_only(monkeypatch):
    """تعافٍ مزيف يملأ المادة البحثية فقط — أوامر البناء تمر بالأداة
    الحقيقية (أدلة exit_code فعلية مع npm المزيف على PATH)."""
    import roles.tools as roles_tools_mod
    from roles.tools import run_build_command as real_build_command

    def fake_recovery(ctx, tool, args, *, attempt, attempted_queries,
                      available_urls, materials, failed_calls, max_results):
        materials["search_results"].append({
            "title": "npm install docs",
            "url": "https://docs.npmjs.com/",
        })
        return None

    def fake_run_tool(name, args, ctx, *, attempt=1):
        if name == "run_build_command":
            return real_build_command(
                ctx, str(args.get("command", "")),
                timeout_s=float(args.get("timeout_s", 0) or 0),
            )
        if name == "verify_pdf_pages":
            return 1
        if name == "write_file":
            target = Path(ctx.grant_root) / args["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
            return str(target)
        return None

    monkeypatch.setattr(impl_mod, "run_with_recovery", fake_recovery)
    monkeypatch.setattr(impl_mod, "run_tool", fake_run_tool)
    monkeypatch.setattr(roles_tools_mod, "run_tool", fake_run_tool)


def test_run_step103_end_to_end_with_real_command(
        tmp_path, monkeypatch):
    """تكامل كامل: خطة بحث → طور أوامر حقيقي → تقرير — أدلة npm فعلية."""
    stub_dir = _make_stub_tools(tmp_path)
    _patch_tool_paths(monkeypatch, stub_dir)
    _fake_tools_research_only(monkeypatch)

    root = _project_tree(tmp_path)
    router = FakeRouter([
        "web_search | npm install astro dependencies\n",
        REPORT_MD_103,
    ])
    implementer = LiveImplementer(router)
    task = PlanTask(
        id="T1", description="Install all npm dependencies",
        acceptance_criteria=STEP103_CRITERIA,
    )
    request = ImplementerRequest(
        task=task, tools_available=["python"],
        sandbox_root=str(root), previous_attempts=[],
    )
    result = implementer.run(request)

    assert result.status is ImplementerStatus.EXECUTED, result.stderr_truncated
    # نداءان حصريًا للنموذج: خطة الأدوات ثم التقرير (لا create_files)
    assert len(router.calls) == 2
    # الأمر نفّذ فعليًا: package-lock.json على القرص ضمن أدلة الخطوة
    assert (root / "package-lock.json").is_file()
    # الأدلة تحمل sha256 للناتج الفعلي
    build_refs = [r for r in result.evidence_refs
                  if r.endswith("package-lock.json")]
    assert build_refs and build_refs[0].startswith("sha256:")
    # رسالة المخرج تذكر أمر البناء الفعلي
    assert "أمر بناء فعلي" in result.stdout_truncated
    # التقرير استلم نتائج الأوامر الحقيقية
    report_payload = json.loads(router.calls[1][-1].content)
    assert report_payload["materials"]["build_commands"][0][
        "command"] == "npm install"


def test_run_step103_tooling_missing_fails_with_signature(
        tmp_path, monkeypatch):
    """فقد node/npm عبر run() كاملة → فشل بتوقيع المصنّف الحرفي."""
    _patch_tool_paths(monkeypatch, None)
    _fake_tools_research_only(monkeypatch)

    root = _project_tree(tmp_path)
    router = FakeRouter([
        "web_search | npm install verification\n",
    ])
    implementer = LiveImplementer(router)
    task = PlanTask(
        id="T1", description="Install all npm dependencies",
        acceptance_criteria=STEP103_CRITERIA,
    )
    result = implementer.run(ImplementerRequest(
        task=task, tools_available=["python"],
        sandbox_root=str(root), previous_attempts=[],
    ))

    assert result.status is ImplementerStatus.FAILED
    assert "BUILD_TOOLING_MISSING" in result.stderr_truncated
    assert result.failure["reason"] == "BUILD_TOOLING_MISSING"


def test_run_research_task_untouched_by_build_phase(
        tmp_path, monkeypatch):
    """مهمة بحث صرفة: الطور لا يعمل — نداءان حصريًا كما قبل W2-T24."""
    _patch_tool_paths(monkeypatch, None)
    _fake_tools_research_only(monkeypatch)
    root = tmp_path / "ws"
    root.mkdir()
    long_report = (
        "# تقرير بحث عام\n\n"
        "## الخلاصة\n"
        "جُمعت المادة من مصادر موثوقة حول الموضوع العام المطلوب، وتغطي "
        "النقاط الجوهرية التي حددتها معايير القبول للمهمة، مع الحرص على "
        "دقة الأسماء والتواريخ والأرقام كما وردت في المصادر الأصلية دون "
        "أي اختلاق أو تزيين، والتزمت حد الكلمات المفروض على الصفحة.\n\n"
        "## المصادر\n"
        "- ويكيبيديا — https://wikipedia.org\n"
        "- موسوعة — https://example.org\n"
    )
    router = FakeRouter([
        "web_search | موضوع عام\n",
        long_report,
    ])
    implementer = LiveImplementer(router)
    criteria = ["report.md يحتوي ملخصًا", "sources.json يوثق المصادر"]
    result = implementer.run(ImplementerRequest(
        task=PlanTask(id="T1", description="بحث عام",
                      acceptance_criteria=criteria),
        tools_available=["python"], sandbox_root=str(root),
        previous_attempts=[],
    ))
    assert result.status is ImplementerStatus.EXECUTED
    assert len(router.calls) == 2
    assert not (root / "evidence").exists(), (
        "مهمة بحث لا تُنشئ أدلة أوامر — الطور لم يعمل"
    )


# ------------------------------------------------------------------ #
# 5) عقود الرقة
# ------------------------------------------------------------------ #

def test_build_commands_under_340_lines():
    """عقد رقة W2-T24: وحدة الطور تحت 340 سطرًا (منطق مستخرج كاملًا)."""
    path = Path(build_commands.__file__)
    assert len(path.read_text(encoding="utf-8").splitlines()) < 340


# ------------------------------------------------------------------ #
# (W2-T25) npm run lint — خطط المصنع تشترطه حرفيًا في المعايير
# ------------------------------------------------------------------ #

STEP144_CRITERIA = [
    "`npm install` completes without errors (exit code 0)",
    "`npm run lint` runs ESLint and reports 0 errors, 0 warnings",
    "No peer dependency warnings that block installation",
]


def test_required_build_commands_step144_lint():
    """معايير 144 الحقيقية → install ثم lint (كان lint لا يُستخرج
    فلا يُنفَّذ ويصدق المنفذ: «لم يُنفّذ — لا دليل» ويرفض التحقق)."""
    commands = build_commands.required_build_commands(STEP144_CRITERIA)
    assert commands == ["npm install", "npm run lint"]


def test_lint_command_whitelisted():
    """الأمر في قائمة الإغلاق — يمر التنفيذ الموحد لا يرفضه."""
    from roles.build_tool import BUILD_COMMAND_WHITELIST
    assert "npm run lint" in BUILD_COMMAND_WHITELIST


# ------------------------------------------------------------------ #
# (W2-T25) روابط المتطلبات المطلقة + استبدال المعلق
# ------------------------------------------------------------------ #

def test_gather_symlink_absolute_and_survives_retry(tmp_path, monkeypatch):
    """الجلب بمسار نسبي (كما يحدث من cwd الخدمة) ينشئ رابطًا مطلقًا
    يعمل، وإعادة الجلب بعد جولة سابقة (رابط موجود — حتى معلق قديم)
    لا تصطدم Errno 17 بل تستبدل المعلق."""
    import os
    # بنية المشروع: steps/142 (فيه node_modules حقيقي) وsteps/161
    steps = tmp_path / "runtime" / "projects" / "3" / "steps"
    (steps / "142" / "node_modules").mkdir(parents=True)
    (steps / "142" / "node_modules" / "react").mkdir()
    (steps / "161").mkdir(parents=True)
    (steps / "161" / "package.json").write_text("{}", encoding="utf-8")
    # cwd وهمي يحاكي الخدمة — الجلب بجذر نسبي كما يحدث فعلًا
    monkeypatch.chdir(tmp_path)
    from pathlib import Path as _P
    result = build_commands.gather_build_prerequisites(
        _P("runtime/projects/3/steps/161"))
    assert "node_modules" in result["linked"]
    link = steps / "161" / "node_modules"
    assert link.is_symlink()
    assert link.exists(), "الرابط يجب أن يعمل (مطلق لا معلق)"
    assert (link / "react").is_dir()
    # الجولة الثانية (إعادة المحاولة): لا Errno 17 — الرابط موجود فيتخطى
    result2 = build_commands.gather_build_prerequisites(
        _P("runtime/projects/3/steps/161"))
    assert "node_modules" not in result2["linked"]


def test_gather_replaces_dangling_symlink(tmp_path, monkeypatch):
    """رابط معلق من جولة قديمة (مسار نسبي قديم) يُستبدل بمطلق صحيح."""
    steps = tmp_path / "runtime" / "projects" / "3" / "steps"
    (steps / "142" / "node_modules").mkdir(parents=True)
    (steps / "161").mkdir(parents=True)
    dangling = steps / "161" / "node_modules"
    dangling.symlink_to("runtime/projects/3/steps/142/node_modules")
    assert not dangling.exists() and dangling.is_symlink()  # معلق فعلًا
    monkeypatch.chdir(tmp_path)
    from pathlib import Path as _P
    result = build_commands.gather_build_prerequisites(
        _P("runtime/projects/3/steps/161"))
    assert "node_modules" in result["linked"]
    assert dangling.exists() and (dangling / ".").is_dir()


def test_gather_latest_sibling_wins(tmp_path):
    """(W2-T25) التراكم الصحيح: أحدث نسخة من المصدر تفوز — قياس حي
    الخطوة 172: package.json من الخطوة الأقدم (بلا سكربت lint) كان
    يطغى على نسخة أحدث فأخفق npm run lint بخطأ موروث."""
    steps = tmp_path / "steps"
    (steps / "102").mkdir(parents=True)
    (steps / "102" / "package.json").write_text(
        '{"name": "old-astro"}', encoding="utf-8")
    (steps / "171").mkdir(parents=True)
    (steps / "171" / "package.json").write_text(
        '{"name": "new-next", "scripts": {"lint": "next lint"}}',
        encoding="utf-8")
    (steps / "172").mkdir(parents=True)
    build_commands.gather_build_prerequisites(steps / "172")
    gathered_pkg = (steps / "172" / "package.json").read_text(
        encoding="utf-8")
    assert "new-next" in gathered_pkg
    assert "lint" in gathered_pkg


# ------------------------------------------------------------------ #
# (W2-T25) سجل أوامر البناء ضمن الأدلة — المراجع يرى install log
# ------------------------------------------------------------------ #

def test_phase_includes_command_evidence_in_artifacts(tmp_path, monkeypatch):
    """ملفات evidence/build-* (install log) تُضم للأدلة — قياس حي
    الخطوة 221: معيار «No error output captured in install log» بلا
    ملف السجل عند المراجع أفشل تحققًا كاملًا لعمل ناجح (stderr فارغ)."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    root = _project_tree(tmp_path)
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, ["npm install"], STEP103_CRITERIA)
    assert outcome.failed_result is None
    artifact_names = {a.name for a in outcome.artifacts}
    assert "build-npm-install-stdout.txt" in artifact_names
    assert "build-npm-install-stderr.txt" in artifact_names
    assert "build-npm-install-exit.json" in artifact_names
    stderr_file = root / "evidence" / "build-npm-install-stderr.txt"
    assert stderr_file.is_file()
    assert stderr_file.read_text(encoding="utf-8").strip() == ""


# ------------------------------------------------------------------ #
# (W2-T25) أدوات التحقق — npx htmlhint وسكربت verify
# ------------------------------------------------------------------ #

def test_required_build_commands_htmlhint_validator():
    """«npx htmlhint تعيد كود خروج 0» → أمر التحقق يُستخرج ويُنفّذ."""
    commands = build_commands.required_build_commands([
        "أداة سطر أوامر (مثل html-validate أو npx htmlhint) تعيد كود خروج 0",
    ])
    assert "npx --yes htmlhint *.html" in commands


def test_required_build_commands_node_verify_script():
    """«node verify.js» المذكور نصًا يُستخرج."""
    commands = build_commands.required_build_commands([
        "فحص DOM عبر script: node verify.js يتحقق querySelectorAll",
    ])
    assert "node verify.js" in commands


def test_phase_runs_verify_script_when_criteria_demand_dom(tmp_path, monkeypatch):
    """معايير DOM (querySelectorAll) + verify.js مكتوب → يُشغَّل فعليًا
    بأدلة exit_code (قياس حي الخطوة 309: السكربت كُتب ولم يُشغَّل أبدًا
    فحكم المراجع «Run log not provided»)."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    root = _project_tree(tmp_path)
    (root / "verify.js").write_text(
        "console.log('cards:', 3)", encoding="utf-8")
    (root / "index.html").write_text(
        '<article class="card">a</article>', encoding="utf-8")
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, [], [
            "فحص DOM عبر script بسيط يؤكد "
            "document.querySelectorAll('#latest .article-card').length === 6",
        ])
    assert outcome.failed_result is None
    executed = [r["command"] for r in outcome.results]
    assert "node verify.js" in executed
    exit_json = root / "evidence" / "build-node-verify.js-exit.json"
    assert exit_json.is_file()
    record = json.loads(exit_json.read_text(encoding="utf-8"))
    assert record["command"] == "node verify.js"
    assert record["exit_code"] == 0


def test_phase_no_verify_script_no_run(tmp_path, monkeypatch):
    """لا سكربت ولا معايير DOM — لا تشغيل اختلاقي."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    root = _project_tree(tmp_path)
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, [], ["File package.json exists"])
    assert outcome.results == []
    assert not (root / "evidence").exists() or \
        not (root / "evidence" / "build-node-verify.js-exit.json").exists()


def test_run_build_command_npx_whitelisted(tmp_path, monkeypatch):
    """npx htmlhint عبر القائمة البيضاء — أدلة باسم الأمر على القرص."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    ctx = _ctx(tmp_path)
    value = run_tool("run_build_command",
                     {"command": "npx --yes htmlhint *.html",
                      "timeout_s": 60}, ctx)
    assert value["exit_code"] == 0
    exit_json = tmp_path / "evidence" / "build-npx---yes-htmlhint-*.html-exit.json"
    assert exit_json.is_file()


def test_phase_install_before_build_even_with_old_node_modules(
        tmp_path, monkeypatch):
    """node_modules قديم (من خطوة سابقة) لا يلغي install: الاعتماديات
    تتغير بين الخطوات (قياس حي الخطوة 325: symlink بلا marked ففشل
    build بMODULE_NOT_FOUND رغم وجود node_modules)."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    root = _project_tree(tmp_path, with_node_modules=True)  # قديم ناقص
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, ["npm run build"], STEP110_CRITERIA)
    assert outcome.failed_result is None
    executed = [r["command"] for r in outcome.results]
    assert executed == ["npm install", "npm run build"]


def test_required_build_commands_dynamic_npx_versions():
    """«npx tsc --version outputs version string» → فحص إصدار ديناميكي
    (قياس حي الخطوة 336: tsc/tailwindcss/prisma)."""
    commands = build_commands.required_build_commands([
        "npm ci completes with exit code 0",
        "npx tsc --version outputs version string",
        "npx tailwindcss --version outputs version string",
        "npx prisma --version outputs version string",
    ])
    assert "npm ci" in commands
    assert "npx --yes tsc --version" in commands
    assert "npx --yes tailwindcss --version" in commands
    assert "npx --yes prisma --version" in commands


def test_run_build_command_npx_version_dynamic_whitelist(tmp_path, monkeypatch):
    """فحص إصدار npx لحزمة غير مدرجة — قاعدة الأمان تقبله (قراءة فقط)."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    value = run_tool("run_build_command",
                     {"command": "npx --yes tsc --version",
                      "timeout_s": 60}, _ctx(tmp_path))
    assert value["exit_code"] == 0


def test_run_build_command_npx_arbitrary_still_blocked(tmp_path, monkeypatch):
    """npx بأي شيء آخر غير الإصدار — يبقى محجوبًا (لا وسائط حرة)."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    with pytest.raises(ToolFailure) as err:
        run_tool("run_build_command",
                 {"command": "npx --yes some-pkg run-script"},
                 _ctx(tmp_path))
    assert err.value.reason == "COMMAND_NOT_WHITELISTED"


def test_phase_ci_without_lockfile_becomes_install(tmp_path, monkeypatch):
    """npm ci بلا package-lock.json (مشروع وليد) → install — المكافئ
    الميكانيكي (قياس حي الخطوة 388: ci فشل بusage error على مشروع
    بلا lockfile رغم كتابة 39 ملفًا صحيحة)."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    root = _project_tree(tmp_path, with_node_modules=False)
    (root / "package-lock.json").unlink(missing_ok=True)
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, ["npm ci"], STEP103_CRITERIA)
    assert outcome.failed_result is None
    executed = [r["command"] for r in outcome.results]
    assert executed == ["npm install"]
    assert (root / "package-lock.json").is_file()


def test_required_build_commands_pnpm():
    """«`pnpm dev` shows styled page» → pnpm install + pnpm dev."""
    commands = build_commands.required_build_commands([
        "tailwind.config.ts defines colors, typography, spacing, breakpoints",
        "postcss.config.js exists with tailwindcss and autoprefixer",
        "app/globals.css imports @tailwind base/components/utilities",
        "`pnpm dev` shows styled page without errors",
    ])
    assert "pnpm dev" in commands


def test_phase_pnpm_dev_gets_pnpm_install(tmp_path, monkeypatch):
    """pnpm dev بلا اعتماديات مثبتة ⇒ pnpm install يُقحم قبله."""
    _patch_tool_paths(monkeypatch, _make_stub_tools(tmp_path))
    root = _project_tree(tmp_path, with_node_modules=False)
    (root / "node_modules").unlink(missing_ok=True) \
        if (root / "node_modules").exists() else None
    import shutil as _sh
    _sh.rmtree(root / "node_modules", ignore_errors=True)
    (root / "package.json").write_text('{"name": "x"}', encoding="utf-8")
    outcome = build_commands.run_build_commands_phase(
        _ctx(root), root, ["pnpm dev"], ["`pnpm dev` shows styled page"])
    executed = [r["command"] for r in outcome.results]
    assert executed == ["pnpm install", "pnpm dev"]
