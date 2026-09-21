"""اختبارات الأمر السادس المنقح — المفاتيح + الربط + الأدوات + مهمة البناء.

الحزم: secrets_store (منقول v1) + نظافة المفتاح (env/سجلات/DOM) +
نقاط المزودات + حل مفاتيح nvidia من المخزن + أدوات src/tools +
مهمة textstats كاملة (نموذج مبرمج في الاختبار — المسار الحي وحده
يستخدم LLM حقيقيًا، لا mock فيه).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from secrets_store import store as store_mod  # noqa: E402


@pytest.fixture()
def store_dir(tmp_path, monkeypatch):
    """عزل المخزن في مجلد اختبار + تصفير الكاش."""
    monkeypatch.setattr(store_mod, "RUNTIME_DIR", tmp_path)
    store_mod._invalidate_known_cache()
    yield tmp_path
    store_mod._invalidate_known_cache()


# ------------------------------------------------------------------ #
# §1 — حزمة الأسرار المنقولة من v1
# ------------------------------------------------------------------ #

def test_store_roundtrip_and_mask(store_dir):
    key = "nvapi-abcdef1234567890WXYZ"
    store_mod.set_key("nvidia", key)
    assert store_mod.get_key("nvidia") == key
    assert store_mod.has_key("nvidia")
    assert store_mod.stored_providers() == ["nvidia"]
    assert store_mod.mask(key) == "****WXYZ"
    assert store_mod.mask("abc") == "****"
    assert store_mod.mask(None) is None


def test_store_delete(store_dir):
    store_mod.set_key("nvidia", "nvapi-1234567890abcd")
    assert store_mod.delete_key("nvidia") is True
    assert store_mod.get_key("nvidia") is None
    assert store_mod.delete_key("nvidia") is False


def test_store_corrupted_file_treated_empty(store_dir):
    target = store_mod.secrets_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("NOT-JSON-AT-ALL", encoding="utf-8")
    assert store_mod.get_key("nvidia") is None
    assert store_mod.stored_providers() == []


def test_store_permissions_600(store_dir):
    if sys.platform == "win32":
        pytest.skip("صلاحيات POSIX خارج Windows")
    store_mod.set_key("nvidia", "nvapi-1234567890abcd")
    mode = oct(store_mod.secrets_file().stat().st_mode & 0o777)
    assert mode == "0o600"


def test_redact_and_log_filter(store_dir):
    key = "nvapi-SUPERSECRET-9999"
    store_mod.set_key("nvidia", key)
    assert store_mod.redact(f"فشل الطلب بمفتاح {key}") == (
        f"فشل الطلب بمفتاح {store_mod.REDACTED}"
    )
    logger = logging.getLogger("test.redact")
    logger.setLevel(logging.INFO)
    captured: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(self.format(record))

    handler = Capture()
    handler.addFilter(store_mod.SecretRedactingFilter())
    logger.addHandler(handler)
    logger.info("اطلب بالمفتاح %s", key)
    assert captured and key not in captured[0]
    assert store_mod.REDACTED in captured[0]


def test_store_status_no_secrets(store_dir):
    store_mod.set_key("nvidia", "nvapi-1234567890abcd")
    status = store_mod.store_status()
    assert status["stored_providers"] == ["nvidia"]
    assert "nvidia" not in json.dumps(status) or "nvapi-" not in json.dumps(status)
    assert status["file_exists"] is True
    assert status["encryption_available"] == (sys.platform == "win32")


# ------------------------------------------------------------------ #
# §1.3 — نظافة المفتاح: لا env، لا سجلات، لا DOM/واجهة
# ------------------------------------------------------------------ #

def test_key_never_in_environment(store_dir):
    store_mod.set_key("nvidia", "nvapi-SECRETKEY-1234")
    for name, value in os.environ.items():
        assert "nvapi-SECRETKEY" not in value, f"المفتاح تسرب إلى {name}"


def test_key_never_in_api_response(store_dir, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from api import routes

    # عزل القاعدة (الأمر 007.1): بطاقات المزودين من سجل دائم لا كود
    from persistence.database import build_engine, init_db, make_session_factory

    engine = build_engine(tmp_path / "order6-key.db")
    init_db(engine)
    sessions = make_session_factory(engine)
    monkeypatch.setattr(routes, "_sessions", sessions)

    secret = "nvapi-VERYSECRET-7777"
    store_mod.set_key("nvidia", secret)
    client = TestClient(routes.app)
    response = client.get("/api/providers")
    assert response.status_code == 200
    body = response.text
    assert secret not in body
    assert "****7777" in body
    # حفظ مفتاح قصير يُرفض (تحقق المخطط 422 — الأمر 007.1)؛ والحفظ
    # السليم يعيد التقنيع فقط
    assert client.put(
        "/api/providers/nvidia/key", json={"key": "short"}
    ).status_code == 422
    saved = client.put(
        "/api/providers/nvidia/key", json={"key": "nvapi-NEWSECRET-8888"}
    ).json()
    assert saved["key_masked"] == "****8888"
    assert "nvapi-NEWSECRET-8888" not in json.dumps(saved)


def test_key_deleted_via_api(store_dir):
    from fastapi.testclient import TestClient

    from api import routes

    store_mod.set_key("nvidia", "nvapi-1234567890abcd")
    client = TestClient(routes.app)
    assert client.delete("/api/providers/nvidia/key").json()["existed"] is True
    assert store_mod.get_key("nvidia") is None


# ------------------------------------------------------------------ #
# §2 — الربط الحي: nvidia من المخزن، لا من البيئة أبدًا
# ------------------------------------------------------------------ #

def test_nvidia_resolved_from_store_not_env(store_dir, monkeypatch):
    from router import model_router as mr

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env-should-be-ignored")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-env-ignored-too")
    # بلا مفاتيح في المخزن: لا nvidia ولا openai_compatible يُحلّان
    resolved = mr.resolve_live_providers()
    assert "nvidia" not in resolved
    assert "openai_compatible" not in resolved
    # مفتاح nvidia في المخزن → يُحل من المخزن وحده
    store_mod.set_key("nvidia", "nvapi-FROM-STORE-0001")
    resolved = mr.resolve_live_providers()
    assert resolved["nvidia"]["api_key"] == "nvapi-FROM-STORE-0001"
    assert resolved["nvidia"]["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert "openai_compatible" not in resolved  # مفتاح البيئة تُجوهل


def test_default_provider_is_nvidia():
    from core.config import LiveModelConfig

    cfg = LiveModelConfig(_env_file=None)  # بلا ‎.env — الافتراضي الخام
    assert cfg.default_provider == "nvidia"
    assert cfg.default_model == "nvidia/nemotron-3-ultra-550b-a55b"


def test_nano_forbidden_for_arbitration(store_dir, tmp_path):
    """قرار §2.3 الموثق: نموذج nano يوقف المهمة قبل أن تبدأ."""
    from missions_textstats import run_textstats_mission

    class NanoRouter:
        _live_default_model = "nemotron-nano-test"

        def chat_live(self, messages):  # pragma: no cover — لا يُستدعى
            raise AssertionError("لا استدعاءات قبل فحص nano")

    result = run_textstats_mission(
        router=NanoRouter(), repo_root=tmp_path, mission_dir=tmp_path / "m",
        approvals=lambda kind, payload: True,
    )
    assert result.verdict == "HARD STOP"
    assert "nano" in result.reason


# ------------------------------------------------------------------ #
# §3 — أدوات البناء: fs + proc (وحدات حقيقية داخل الركيزة)
# ------------------------------------------------------------------ #

def _ctx(tmp_path):
    from roles.tools import ToolContext

    tmp_path.mkdir(parents=True, exist_ok=True)
    return ToolContext(grant_root=tmp_path)


def test_fs_write_read_roundtrip(tmp_path):
    from tools import fs

    ctx = _ctx(tmp_path)
    fs.write_file(ctx, "textstats/x.txt", "hello\nworld")
    assert fs.read_file(ctx, "textstats/x.txt").startswith("hello")
    assert (tmp_path / "textstats" / "x.txt").read_text(encoding="utf-8") == "hello\nworld"


def test_fs_write_path_escape_rejected(tmp_path):
    from roles.tools import ToolError
    from tools import fs

    ctx = _ctx(tmp_path)
    with pytest.raises(ToolError):
        fs.write_file(ctx, "../escape.txt", "no")
    with pytest.raises(ToolError):
        fs.write_file(ctx, "/etc/passwd", "no")


def test_fs_read_missing_fails(tmp_path):
    from roles.tools import ToolError
    from tools import fs

    ctx = _ctx(tmp_path)
    with pytest.raises(ToolError):
        fs.read_file(ctx, "textstats/missing.txt")


def test_fs_list_dir(tmp_path):
    from tools import fs

    ctx = _ctx(tmp_path)
    fs.write_file(ctx, "textstats/a.py", "x = 1")
    fs.write_file(ctx, "textstats/b.py", "y = 2")
    entries = fs.list_dir(ctx, "textstats")
    assert sorted(entries) == ["a.py", "b.py"]


def test_proc_whitelist_rejects_unknown_command(tmp_path):
    from roles.tools import ToolError
    from tools import proc

    ctx = _ctx(tmp_path)
    with pytest.raises(ToolError):
        proc.run_command(ctx, ["rm", "-rf", "/"])
    with pytest.raises(ToolError):
        proc.run_command(ctx, ["/bin/sh", "-c", "echo hi"])
    with pytest.raises(ToolError):
        proc.run_command(ctx, [])


def test_proc_runs_python_and_captures_output(tmp_path):
    from tools import proc

    ctx = _ctx(tmp_path)
    result = proc.run_command(
        ctx, [sys.executable, "-c", "print('tool-ok-123')"]
    )
    assert result["exit_code"] == 0
    assert "tool-ok-123" in result["stdout"]
    assert result["output_sha256"]


def test_proc_exit_code_propagates(tmp_path):
    from tools import proc

    ctx = _ctx(tmp_path)
    result = proc.run_command(
        ctx, [sys.executable, "-c", "import sys; sys.exit(3)"]
    )
    assert result["exit_code"] == 3


def test_proc_runs_real_pytest_on_package(tmp_path):
    from tools import fs, proc

    ctx = _ctx(tmp_path)
    fs.write_file(ctx, "pkg/cal.py", "def add(a, b):\n    return a + b\n")
    fs.write_file(
        ctx,
        "pkg/tests/test_cal.py",
        "from pkg.cal import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
        "def test_add_zero():\n    assert add(0, 0) == 0\n",
    )
    fs.write_file(
        ctx,
        "pkg/conftest.py",
        "import os\nimport sys\n\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n",
    )
    result = proc.run_command(
        ctx,
        [sys.executable, "-m", "pytest", "/artifacts/pkg", "-q", "-p", "no:cacheprovider"],
        timeout=120,
    )
    assert result["exit_code"] == 0, result["stderr"][-300:]
    assert "2 passed" in result["stdout"]


# ------------------------------------------------------------------ #
# §4 — مهمة textstats: دورة كاملة + دفع بفرع ملتزم
# ------------------------------------------------------------------ #

CLI_PY = (
    "import sys\n"
    "\n"
    "\n"
    "def count_stats(content):\n"
    "    return {\n"
    '        "lines": content.count("\\n") + 1,\n'
    '        "words": len(content.split()),\n'
    '        "chars": len(content),\n'
    "    }\n"
    "\n"
    "\n"
    "def main(argv=None):\n"
    "    argv = list(sys.argv[1:] if argv is None else argv)\n"
    "    if not argv:\n"
    '        print("usage: cli.py FILE", file=sys.stderr)\n'
    "        return 2\n"
    "    with open(argv[0], encoding=\"utf-8\") as handle:\n"
    "        content = handle.read()\n"
    "    if not content.strip():\n"
    "        return 1\n"
    "    stats = count_stats(content)\n"
    '    print("lines: {}".format(stats["lines"]))\n'
    '    print("words: {}".format(stats["words"]))\n'
    '    print("chars: {}".format(stats["chars"]))\n'
    "    return 0\n"
    "\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    raise SystemExit(main())\n"
)

TESTS_PY = (
    "from textstats.cli import count_stats, main\n"
    "\n"
    "\n"
    "def test_basic():\n"
    '    assert count_stats("hello world\\nsecond line") == {\n'
    '        "lines": 2, "words": 4, "chars": 23}\n'
    "\n"
    "\n"
    "def test_single_line():\n"
    '    assert count_stats("one two three") == {\n'
    '        "lines": 1, "words": 3, "chars": 13}\n'
    "\n"
    "\n"
    "def test_unicode():\n"
    '    assert count_stats("\\u0645\\u0631\\u062d\\u0628\\u0627") == {\n'
    '        "lines": 1, "words": 1, "chars": 5}\n'
    "\n"
    "\n"
    "def test_three_lines():\n"
    '    assert count_stats("a\\nb\\nc") == {"lines": 3, "words": 3, "chars": 5}\n'
    "\n"
    "\n"
    "def test_main_output_format(tmp_path, capsys):\n"
    '    sample = tmp_path / "s.txt"\n'
    '    sample.write_text("hello world\\nsecond line", encoding="utf-8")\n'
    "    assert main([str(sample)]) == 0\n"
    "    out = capsys.readouterr().out\n"
    '    assert out == "lines: 2\\nwords: 4\\nchars: 23\\n"\n'
)

FILES_TEXT = (
    "### FILE: textstats/__init__.py\n"
    "```python\n"
    '__version__ = "1.0.0"\n'
    "```\n"
    "\n"
    "### FILE: textstats/cli.py\n"
    "```python\n"
    + CLI_PY +
    "```\n"
    "\n"
    "### FILE: textstats/tests/test_cli.py\n"
    "```python\n"
    + TESTS_PY +
    "```\n"
    "\n"
    "### FILE: textstats/README.md\n"
    "```markdown\n"
    "# textstats\n"
    "\n"
    "عدّ أسطر/كلمات/أحرف ملف نصي.\n"
    "\n"
    "    python textstats/cli.py textstats/sample.txt\n"
    "```\n"
)

THINKER_JSON = json.dumps({
    "tasks": [{
        "id": "T1",
        "description": "بناء حزمة textstats كاملة: CLI + suite + README",
        "acceptance_criteria": [
            "textstats/cli.py يطبع lines: N / words: N / chars: N",
            "pytest على textstats/tests ناجح كله (5+ اختبارات)",
            "textstats/README.md يوثق الاستخدام",
        ],
    }],
    "risks": [], "assumptions": [], "evidence_required": [],
}, ensure_ascii=False)

REVIEWER_JSON = json.dumps({
    "verdict": "approved", "score": 9.0, "evolution_score": 8.0,
    "issues": [], "required_changes": [], "gaps": [], "rationale": "خطة واضحة",
}, ensure_ascii=False)

VERIFIER_JSON = json.dumps({
    "verdict": "evidenced", "checks_performed": ["pytest", "cli"],
    "missing_evidence": [], "confidence": 0.95, "rationale": "الأدلة مطابقة",
}, ensure_ascii=False)


class ScriptedRouter:
    """نموذج مبرمج للاختبار — يوزع الردود حسب برومبت الدور."""

    _live_default_model = "fake-build-model"

    def __init__(self, files_text: str = FILES_TEXT) -> None:
        self._files_text = files_text
        self.calls = 0

    def chat_live(self, messages):
        self.calls += 1
        system = messages[0].content
        if "Thinker" in system:
            return {"text": THINKER_JSON}
        if "Reviewer" in system:
            return {"text": REVIEWER_JSON}
        if "Verifier" in system:
            return {"text": VERIFIER_JSON}
        if "BUILD" in system:
            return {"text": self._files_text}
        raise AssertionError("برومبت دور غير معروف: " + system[:60])


def _git(path: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True, text=True, timeout=60, check=False,
    )


@pytest.fixture()
def repo_with_remote(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@local")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)],
                   capture_output=True, check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")
    return repo, bare


def test_textstats_mission_full_pass(repo_with_remote, tmp_path):
    """الدورة الكاملة: بناء + اختبارات + دفع بفرع ملتزم (§4)."""
    from missions_textstats import run_textstats_mission

    repo, bare = repo_with_remote
    result = run_textstats_mission(
        router=ScriptedRouter(),
        repo_root=repo,
        mission_dir=tmp_path / "mission",
        approvals=lambda kind, payload: True,
    )
    assert result.verdict == "PASS", result.reason
    assert result.pushed and result.commit_sha
    assert result.pytest_passed >= 5
    # الفرع على الـremote الفعلي = الالتزام المدفوع
    head = _git(bare, "rev-parse", "refs/heads/mission/textstats")
    assert head.stdout.strip() == result.commit_sha
    evidence = json.loads(
        (tmp_path / "mission" / "evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["verdict"] == "PASS"
    assert evidence["pushed"] is True
    assert "textstats/cli.py" in evidence["files"]


def test_textstats_mission_push_denied_no_push(repo_with_remote, tmp_path):
    """رفض بوابة الدفع = لا دفع أبدًا (fail-closed §4.3)."""
    from missions_textstats import run_textstats_mission

    repo, bare = repo_with_remote
    result = run_textstats_mission(
        router=ScriptedRouter(),
        repo_root=repo,
        mission_dir=tmp_path / "mission",
        approvals=lambda kind, payload: kind == "path_grant",
    )
    assert result.verdict == "HARD STOP"
    assert "رُفض الدفع" in result.reason
    probe = _git(bare, "rev-parse", "--verify", "refs/heads/mission/textstats")
    assert probe.returncode != 0  # لا فرع على الremote


def test_textstats_mission_path_grant_denied_no_writes(repo_with_remote, tmp_path):
    """رفض منحة المسار = لا كتابة أبدًا (fail-closed §5)."""
    from missions_textstats import run_textstats_mission

    repo, bare = repo_with_remote
    result = run_textstats_mission(
        router=ScriptedRouter(),
        repo_root=repo,
        mission_dir=tmp_path / "mission",
        approvals=lambda kind, payload: False,
    )
    assert result.verdict == "HARD STOP"
    assert "رُفضت منحة المسار" in result.reason
    workspace = tmp_path / "mission" / "repo"
    assert not (workspace / "textstats").exists()


def test_default_repo_root_is_this_repo_not_parent():
    """انحدار الجذر الافتراضي: parents[2] الخاطئة كانت تدفع مساحة عمل
    المهمة إلى مستودع المجلد الأب فيهبط الدفع في المستودع الخطأ —
    الجذر الصحيح هو المستودع الحاوي لهذا المصدر نفسه (درس المهمة الأولى)."""
    from missions_textstats import _default_repo_root

    root = _default_repo_root().resolve()
    # جذر هذا المستودع حصرًا: بنيته المميزة موجودة فيه
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "missions_textstats.py").is_file()
    assert (root / ".git").exists()
    # وليس المجلد الأب (الذي لا يحوي هذه البنية)
    assert root != root.parent
    assert not (root.parent / "src" / "missions_textstats.py").is_file()
