"""اختبارات W2-T25 — فحص صياغة node --check وحرفيات grep (قياس 728).

الدافع المقيس (الخطوة 728، التنفيذ 445): معايير حرفية بأوامر
— «node --check js/data.js exits 0» و«grep -o '{' js/data.js | wc -l
≥ 3» — والقائمة البيضاء لا تعرف node --check أصلاً فلم يُنفّذ أي
أمر والمراجع بلا مادة حكم → not_evidenced → استنفاد وتصعيد زور.

العقد الجديد: (1) node --check <ملف> يُستخرج من المعايير ويُنفَّذ
فعليًا بأدلة exit_code على القرص — الملف النسبي الآمن حصرًا (بلا
عبور .. وبامتداد نصي)؛ (2) حرفيات grep المذكورة بالمعايير تُعد
ميكانيكيًا ضمن token_counts فيحقق المراجع معايير العد حرفيًا.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from roles import build_commands  # noqa: E402
from roles.live import VerifierLive  # noqa: E402
from roles.verifier import VerifierRequest  # noqa: E402
from roles.tool_failures import ToolFailure  # noqa: E402
from roles.tools import ToolContext, run_tool  # noqa: E402


def _make_stub_tools(tmp_path: Path) -> Path:
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir(exist_ok=True)
    node = stub_dir / "node"
    node.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in --check)\n"
        "  if grep -q SYNTAX_BAD \"$2\"; then\n"
        "    echo 'SyntaxError: unexpected token' >&2; exit 1\n"
        "  fi; exit 0 ;;\n"
        "*) echo v22.0.0-stub ;; esac\n")
    node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    npm = stub_dir / "npm"
    npm.write_text("#!/bin/sh\necho stub-npm\n")
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    npx = stub_dir / "npx"
    npx.write_text("#!/bin/sh\necho stub-npx\n")
    npx.chmod(npx.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return stub_dir


def _patch(monkeypatch, stub_dir):
    def fake_which(name):
        if stub_dir is None:
            return None
        candidate = stub_dir / name
        return str(candidate) if candidate.exists() else None

    monkeypatch.setattr("shutil.which", fake_which)


def test_node_check_extracted_from_criteria():
    """معيار node --check حرفي → الأمر بالمستخرَج وبترتيب الطور."""
    cmds = build_commands.required_build_commands([
        "Valid JS syntax (node --check js/data.js exits 0).",
        "grep -c 'window.NEWS_ARTICLES' js/data.js = 1.",
    ])
    assert "node --check js/data.js" in cmds


def test_node_check_runs_real_check_with_evidence(tmp_path, monkeypatch):
    """ملف سليم الصياغة → exit 0 وأدلة stdout/exit على القرص."""
    _patch(monkeypatch, _make_stub_tools(tmp_path))
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "data.js").write_text(
        "window.NEWS_ARTICLES = [{id:1},{id:2},{id:3}];\n")
    value = run_tool("run_build_command",
                     {"command": "node --check js/data.js", "timeout_s": 30},
                     ToolContext(grant_root=tmp_path))
    assert value["exit_code"] == 0
    ev = tmp_path / "evidence"
    names = " ".join(p.name for p in ev.iterdir())
    assert "node---check" in names and "exit" in names


def test_node_check_bad_syntax_fails_honestly(tmp_path, monkeypatch):
    """صياغة تالفة → فشل صادق مصنّف BUILD_COMMAND_FAILED."""
    _patch(monkeypatch, _make_stub_tools(tmp_path))
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "data.js").write_text("SYNTAX_BAD window.NEWS = [\n")
    with pytest.raises(ToolFailure) as err:
        run_tool("run_build_command",
                 {"command": "node --check js/data.js", "timeout_s": 30},
                 ToolContext(grant_root=tmp_path))
    assert err.value.reason == "BUILD_COMMAND_FAILED"


def test_node_check_rejects_traversal_and_bad_extension(
        tmp_path, monkeypatch):
    """عبور .. أو امتداد غير نصي → POLICY_BLOCK — لا تنفيذ إطلاقًا."""
    _patch(monkeypatch, _make_stub_tools(tmp_path))
    ctx = ToolContext(grant_root=tmp_path)
    for bad in ("node --check ../etc/passwd.js",
                "node --check payload.sh"):
        with pytest.raises(ToolFailure) as err:
            run_tool("run_build_command", {"command": bad}, ctx)
        assert err.value.reason == "COMMAND_NOT_WHITELISTED"


def test_grep_literals_counted_in_token_facts(tmp_path):
    """حرفية '{' بمعيار grep تُعد ميكانيكيًا في token_counts للملف."""
    import json

    class _StubRouter:
        def __init__(self):
            self.payloads = []

        def chat_live(self, messages, **_kw):
            self.payloads.append(messages[-1].content)
            return {"text": json.dumps({
                "verdict": "evidenced", "checks_performed": [],
                "missing_evidence": [], "confidence": 1.0})}

    router = _StubRouter()
    data = tmp_path / "data.js"
    data.write_text(
        "window.NEWS_ARTICLES = [{a:1},{a:2},{a:3},{a:4}];\n")
    VerifierLive(router).run(VerifierRequest(
        task_acceptance_criteria=[
            "grep -o '{' js/data.js | wc -l ≥ 3.",
            "grep -c 'window.NEWS_ARTICLES' js/data.js = 1.",
        ],
        artifacts=[str(data)],
    ))
    payload = json.loads(router.payloads[0])
    counts = payload["facts"]["token_counts"]["data.js"]
    assert counts["{"] == 4
    assert counts["window.NEWS_ARTICLES"] == 1


def test_thinness_ratchets_hold():
    """عقود الرقة بعد الإضافة — build_commands<340 وbuild_tool<260."""
    for path, ceiling in (("src/roles/build_commands.py", 340),
                          ("src/roles/build_tool.py", 260)):
        n = len((REPO / path).read_text(encoding="utf-8").splitlines())
        assert n < ceiling, f"{path}={n} >= {ceiling}"
