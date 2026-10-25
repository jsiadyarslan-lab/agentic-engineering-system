"""(AES-LIVE-FACTORY-E2E-001 المرحلة 6) نمط البناء في المنفذ الحي.

المغطى:
- مهمة تصرّح بملفات (html/css/js) ← بناء فعلي: write_file لكل ملف
  عبر الأداة (ركيزة + أحداث) وأدلة بصمة لكل ملف — لا تقرير.
- مهمة تقرير (report.md وحده) ← تبقى على مسار التقرير الأصلي حرفياً.
- عقد JSON الصارم للبناء: فشل التحليل يُعاد مرة ثم فشل صريح.
- أدوات verify: الناجحة ترفق لقطاتها كأدلة، والفاشلة تُعلن لا تُخفى.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import roles.implementer_live as il  # noqa: E402
from roles.implementer import (  # noqa: E402
    ImplementerRequest,
    ImplementerStatus,
)
from roles.implementer_live import (  # noqa: E402
    LiveImplementer,
    _deliverable_names,
    _parse_build_payload,
)
from roles.thinker import PlanTask  # noqa: E402
from router.model_router import ChatMessage  # noqa: E402


class FakeRouter:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat_live(self, _messages, **_kwargs):
        if not self.responses:
            raise AssertionError("استدعاءات أكثر من الاستجابات")
        return {"text": self.responses.pop(0), "provider": "fake",
                "model": "fake", "tokens": 1, "duration_ms": 1}

    def chat_live_stream(self, messages, on_delta=None, **kwargs):
        # (المرحلة 6هـ) مسار البث: يغذي on_delta ثم يعيد مثل chat_live
        outcome = self.chat_live(messages, **kwargs)
        if on_delta and outcome.get("text"):
            on_delta(outcome["text"])
        return outcome


def _build_task(**overrides):
    task = PlanTask(
        id="T1",
        description="كتابة index.html بصفحة رئيسية RTL كاملة",
        acceptance_criteria=["الملف index.html موجود ضمن الأدلة"],
    )
    for key, value in overrides.items():
        setattr(task, key, value)
    return task


def test_deliverable_names_extraction():
    site = _deliverable_names({
        "description": "اكتب index.html وstyle.css وscript.js",
        "acceptance_criteria": ["index.html يعمل من المعاينة"],
    })
    assert site == ["index.html", "style.css", "script.js"]
    report = _deliverable_names({
        "description": "اكتب report.md يلخص الهدف",
        "acceptance_criteria": ["report.md موجود ضمن الأدلة"],
    })
    assert report == []
    mixed = _deliverable_names({
        "description": "اكتب report.md ثم chart.svg",
        "acceptance_criteria": [],
    })
    assert mixed == ["chart.svg"]


def test_parse_build_contract_strict():
    good = ('{"files": [{"path": "index.html", "content": "<h1>x</h1>"}],'
            ' "verify": []}')
    assert _parse_build_payload(good)["files"][0]["path"] == "index.html"
    for bad in ("نص", "{}", '{"files": []}', '{"files": "x"}',
                '{"files": [{"path": "a.html"}]}'):
        with pytest.raises(ValueError):
            _parse_build_payload(bad)


def test_build_mode_writes_real_files(tmp_path, monkeypatch):
    """مهمة ملفات ← write_file فعلي عبر الأداة + أدلة بصمة لكل ملف."""
    calls = []

    def fake_run_tool(name, args, ctx, **_kw):
        calls.append((name, args["path"]))
        (ctx.grant_root / args["path"]).write_text(
            args["content"], encoding="utf-8")
        return str(ctx.grant_root / args["path"])

    monkeypatch.setattr(il, "run_tool", fake_run_tool)
    router = FakeRouter([
        "<!doctype html><html dir=\"rtl\"><body><h1>سلام</h1></body></html>",
        '{"verify": []}',
    ])
    implementer = LiveImplementer(router)
    result = implementer.run(ImplementerRequest(
        task=_build_task(), sandbox_root=str(tmp_path)))
    assert result.status == ImplementerStatus.EXECUTED, result.stderr_truncated
    assert ("write_file", "index.html") in calls
    assert (tmp_path / "index.html").read_text(
        encoding="utf-8") == "<!doctype html><html dir=\"rtl\"><body><h1>سلام</h1></body></html>"
    assert any(ref.startswith("sha256:") for ref in result.evidence_refs)


def test_build_mode_verify_failure_is_declared_not_hidden(
        tmp_path, monkeypatch):
    """أداة verify فاشلة: تُعلن رسالتها في stdout والأدلة تبقى للملفات."""
    def fake_run_tool(name, args, ctx, **_kw):
        if name == "browser_navigate":
            raise il.ToolFailure(
                name, "رفض السياسة", failure_class="POLICY_BLOCK",
                reason="PRIVATE_HOST", stage="TOOL_START", retryable=False)
        (ctx.grant_root / args["path"]).write_text(
            args["content"], encoding="utf-8")
        return "ok"

    monkeypatch.setattr(il, "run_tool", fake_run_tool)
    router = FakeRouter([
        "<html><body>محتوى صفحة كامل يكفي طولاً لاجتياز الحد الأدنى"
        " المطلوب للملف المكتوب فعلياً في مساحة العمل</body></html>",
        '{"verify": [{"tool": "browser_navigate", "args":'
        ' {"url": "http://x/y"}}]}',
    ])
    implementer = LiveImplementer(router)
    result = implementer.run(ImplementerRequest(
        task=_build_task(), sandbox_root=str(tmp_path)))
    assert result.status == ImplementerStatus.EXECUTED
    assert "فشل browser_navigate" in (result.stdout_truncated or "")


def test_report_task_stays_on_report_path(tmp_path, monkeypatch):
    """مهمة تقرير (report.md وحده) لا تدخل نمط البناء إطلاقاً."""
    reached_build = {"yes": False}
    original = il.LiveImplementer._run_build_mode

    def spy(self, *args, **kwargs):
        reached_build["yes"] = True
        return original(self, *args, **kwargs)

    monkeypatch.setattr(il.LiveImplementer, "_run_build_mode", spy)

    def fake_run_tool(name, args, ctx, **_kw):
        (ctx.grant_root / args["path"]).write_text(
            args["content"], encoding="utf-8")
        return "ok"

    monkeypatch.setattr(il, "run_tool", fake_run_tool)

    def fake_recovery(ctx, tool, args, **kwargs):
        kwargs["materials"]["search_results"].append(
            {"url": "https://example.com/x", "title": "مثال"})

    monkeypatch.setattr(il, "run_with_recovery", fake_recovery)
    # دورة تقرير كاملة: خطة أدوات (استدعاء واحد) ← تقرير ← كتابة
    router = FakeRouter([
        "web_search | موضوع الاختبار",
        "# تقرير القبول " + "نص عربي كافٍ " * 20,
    ])
    implementer = LiveImplementer(router)
    result = implementer.run(ImplementerRequest(
        task=PlanTask(
            id="T1",
            description="اكتب report.md يلخص هدف الاختبار في ثلاث نقاط",
            acceptance_criteria=["الملف report.md موجود ضمن الأدلة"],
        ),
        sandbox_root=str(tmp_path)))
    assert reached_build["yes"] is False
    assert (tmp_path / "T1-report.md").exists()


def test_verify_only_step_runs_browser_tools(tmp_path, monkeypatch):
    """(المرحلة 6د) خطوة تحقق بلا ملفات: كشفها عبر browser_* وتنفيذ
    أدواتها — واللقطات الناجحة تصير أدلة."""
    shots = []

    def fake_run_tool(name, args, ctx, **_kw):
        if name == "browser_screenshot":
            shot = Path(ctx.grant_root) / f"{args.get('name', 'shot')}.png"
            shot.write_bytes(b"\x89PNG-fake")
            shots.append(shot)
            return {"ok": True, "file": str(shot),
                    "sha256": "f" * 64, "bytes": 9}
        return {"ok": True}

    monkeypatch.setattr(il, "run_tool", fake_run_tool)
    router = FakeRouter([
        '{"verify": [{"tool": "browser_navigate", "args":'
        ' {"url": "http://127.0.0.1:8011/api/projects/1/preview/index.html"}},'
        ' {"tool": "browser_screenshot", "args": {"name": "home"}}]}',
    ])
    implementer = LiveImplementer(router)
    result = implementer.run(ImplementerRequest(
        task=PlanTask(
            id="T1",
            description="تحقق بالمتصفح: browser_navigate ثم browser_screenshot",
            acceptance_criteria=["اللقطات مثبتة"],
        ),
        sandbox_root=str(tmp_path)))
    assert result.status == ImplementerStatus.EXECUTED
    assert shots, "لم تُنفذ أداة اللقطة"
    assert any(ref.startswith("shot:") for ref in result.evidence_refs)


def test_context_goal_drives_detection_when_task_lacks_filenames(tmp_path, monkeypatch):
    """(المرحلة 6ز) مهمة المفكر بلا أسماء ملفات لكن هدف الخطوة يذكرها —
    نمط البناء يُفعَّل من الهدف الكامل لا من صياغة المفكر."""
    calls = []

    def fake_run_tool(name, args, ctx, **_kw):
        calls.append((name, args["path"]))
        (ctx.grant_root / args["path"]).write_text(
            args["content"], encoding="utf-8")
        return str(ctx.grant_root / args["path"])

    monkeypatch.setattr(il, "run_tool", fake_run_tool)
    router = FakeRouter([
        "<!doctype html><html dir=\"rtl\"><body>محتوى كامل يكفي طولاً"
        " لاجتياز حد الملف الفعلي المكتوب في مساحة العمل</body></html>",
        '{"verify": []}',
    ] * 5)
    implementer = LiveImplementer(router)
    result = implementer.run(ImplementerRequest(
        task=PlanTask(
            id="T1",
            description="اكتب الملفات المطلوبة للموقع",
            acceptance_criteria=["الملفات موجودة وكاملة"],
        ),
        sandbox_root=str(tmp_path),
        context_goal="كتابة الملفات الخمسة (index.html، category.html، "
                     "article.html، style.css، script.js) في خطوة واحدة "
                     "ثم التحقق بأدوات المتصفح browser_navigate و"
                     "browser_screenshot من المعاينة",
    ))
    assert result.status == ImplementerStatus.EXECUTED, result.stderr_truncated
    written = sorted(p.name for p in tmp_path.iterdir() if p.is_file())
    assert written == [
        "article.html", "category.html", "index.html", "script.js",
        "style.css",
    ]
