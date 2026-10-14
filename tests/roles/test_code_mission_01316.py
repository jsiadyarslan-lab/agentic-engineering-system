"""اختبارات القدرة البرمجية للمهام (013.16 §2) — run_python + فرع المهمة البرمجية.

أداة run_python تنفَّذ فعليًا داخل الركيزة المعزولة (نفس ركيزة
write_file/read_file — LocalSandboxBackend على Linux هذه الجلسة)،
والمنفذ الحي يُختبر بموجّه مزيف حقنًا (test wiring مسموح في الاختبارات
حصرًا — المسار الحقيقي: برومبت implementer_code ← عقد CodeMissionFiles
← write_file ← run_python ×2 داخل الركيزة الحقيقية).
"""

from __future__ import annotations

import json

import pytest

from roles.implementer import ImplementerRequest, ImplementerStatus
from roles.implementer_live import LiveImplementer
from roles.thinker import PlanTask
from roles.tools import ToolContext, ToolError, run_tool
from router.model_router import ChatMessage


def _ctx(tmp_path, events=None):
    return ToolContext(grant_root=tmp_path, on_event=events)


# ------------------------------------------------------------------ #
# 1) أداة run_python — العقد والمنحة والركيزة الحقيقية
# ------------------------------------------------------------------ #

def test_run_python_success_returns_actual_output(tmp_path):
    """تشغيل ناجح: exit_code/stdout فعليان من الركيزة لا نص نموذج."""
    ctx = _ctx(tmp_path)
    run_tool(
        "write_file",
        {"path": "hello.py", "content": "print('hello from substrate')\n"},
        ctx,
    )
    out = run_tool("run_python", {"path": "hello.py"}, ctx)
    assert out["ok"] is True
    assert out["exit_code"] == 0
    assert "hello from substrate" in out["stdout"]


def test_run_python_nonzero_exit_is_result_not_exception(tmp_path):
    """الخروج غير الصفري نتيجة موثقة (فصل transport عن result) لا استثناء."""
    ctx = _ctx(tmp_path)
    run_tool(
        "write_file",
        {"path": "boom.py", "content": "raise SystemExit(3)\n"},
        ctx,
    )
    out = run_tool("run_python", {"path": "boom.py"}, ctx)
    assert out["ok"] is False
    assert out["exit_code"] == 3


def test_run_python_runtime_error_captured(tmp_path):
    """خطأ تشغيل حقيقي يُلتقط stderr الفعلي — لا يُبتلع ولا يُخفى."""
    ctx = _ctx(tmp_path)
    run_tool(
        "write_file",
        {"path": "crash.py",
         "content": "1 / 0\n"},
        ctx,
    )
    out = run_tool("run_python", {"path": "crash.py"}, ctx)
    assert out["ok"] is False
    assert out["exit_code"] != 0
    assert "ZeroDivisionError" in out["stderr"]


def test_run_python_grant_escape_refused(tmp_path):
    """خارج المجلد الممنوح = رفض صريح قبل أي تنفيذ (مثل read_file)."""
    ctx = _ctx(tmp_path)
    with pytest.raises(ToolError, match="خارج المجلد الممنوح"):
        run_tool("run_python", {"path": "../escape.py"}, ctx)
    with pytest.raises(ToolError, match="خارج المجلد الممنوح"):
        run_tool("run_python", {"path": "/etc/passwd"}, ctx)


def test_run_python_args_and_events_recorded(tmp_path):
    """الوسائط تصل sys.argv، وكل استدعاء يوثّق موقعًا وبصمة (§3.3)."""
    events: list[dict] = []
    ctx = _ctx(tmp_path, events.append)
    run_tool(
        "write_file",
        {"path": "args.py",
         "content": "import sys; print('ARG=', sys.argv[1])\n"},
        ctx,
    )
    out = run_tool("run_python", {"path": "args.py", "args": ["value-1"]},
                   ctx)
    assert "ARG= value-1" in out["stdout"]
    kinds = [e["kind"] for e in events]
    assert "tool.started" in kinds and "tool.call" in kinds
    for event in events:
        if event["kind"] == "tool.call" and event["tool"] == "run_python":
            assert event["execution_site"] == "substrate"
            assert event["output_sha256"]
            assert event["args_summary"]["exit_code"] == 0


# ------------------------------------------------------------------ #
# 2) كشف المهمة البرمجية — حتمي معلن
# ------------------------------------------------------------------ #

def _code_task_request(criteria=None, description=None, sandbox_root=""):
    return ImplementerRequest(
        task=PlanTask(
            id="T1",
            description=description or "ابنِ أداة Python تقرأ transactions.csv",
            acceptance_criteria=criteria or [
                "الملف tool.py موجود ونُفّذ داخل الركيزة",
                "الملف report.md ناتج فعلي من الأداة بإجمالي 85.00",
                "الاختبارات test_tool.py تنجح برمز خروج صفر",
            ],
        ),
        tools_available=["python"],
        sandbox_root=sandbox_root,
    )


def test_is_code_mission_detection():
    """البصمة تلتقط مهمة برمجية وتمرّر مهمة تقرير عادية."""
    assert LiveImplementer._is_code_mission(_code_task_request()) is True
    report_request = ImplementerRequest(
        task=PlanTask(
            id="T1",
            description="اكتب تقريرًا عن الوضع الجيوسياسي",
            acceptance_criteria=["الملف T1-report.md موجود ضمن الأدلة"],
        ),
    )
    assert LiveImplementer._is_code_mission(report_request) is False


# ------------------------------------------------------------------ #
# 3) المنفذ الحي — المهمة البرمجية عبر الركيزة الحقيقية
# ------------------------------------------------------------------ #

class FakeRouter:
    """موجّه مسجَّل (test wiring) — استجابة واحدة تكفي المسار البرمجي."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def chat_live(self, messages, **_kwargs):
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("استدعاءات أكثر من الاستجابات المسجلة")
        return {"text": self.responses.pop(0), "provider": "fake",
                "model": "fake", "tokens": 1, "duration_ms": 1}


_TOOL_PY = (
    "import csv\n"
    "import sys\n"
    "from collections import defaultdict\n"
    "\n"
    "def load_rows(path):\n"
    "    with open(path, newline='', encoding='utf-8') as handle:\n"
    "        rows = list(csv.DictReader(handle))\n"
    "    if not rows:\n"
    "        raise SystemExit('ERROR: empty transactions file (no records)')\n"
    "    for row in rows:\n"
    "        try:\n"
    "            float(row['amount'])\n"
    "        except (TypeError, ValueError):\n"
    "            raise SystemExit(\n"
    "                'ERROR: invalid amount for id '\n"
    "                + str(row.get('id')) + ': ' + repr(row.get('amount'))\n"
    "            )\n"
    "    return rows\n"
    "\n"
    "def summarize(rows):\n"
    "    totals = defaultdict(float)\n"
    "    for row in rows:\n"
    "        totals[row['category']] += float(row['amount'])\n"
    "    return totals\n"
    "\n"
    "def main():\n"
    "    rows = load_rows('transactions.csv')\n"
    "    totals = summarize(rows)\n"
    "    lines = ['# تقرير المعاملات', '']\n"
    "    for category in sorted(totals):\n"
    "        lines.append(f'- {category}: {totals[category]:.2f}')\n"
    "    lines.append(f'- الإجمالي: {sum(totals.values()):.2f}')\n"
    "    with open('report.md', 'w', encoding='utf-8') as handle:\n"
    "        handle.write('\\n'.join(lines) + '\\n')\n"
    "    print('records=', len(rows))\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    main()\n"
)

_TRANSACTIONS_CSV = (
    "id,category,amount\n"
    "1,food,10.00\n"
    "2,food,15.00\n"
    "3,travel,20.00\n"
    "4,travel,20.00\n"
    "5,tools,20.00\n"
    "6,food,0.00\n"
)

_TEST_TOOL_PY = (
    "import os, sys, tempfile\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import tool\n"
    "\n"
    "CASES = []\n"
    "\n"
    "def check(name, condition, detail=''):\n"
    "    CASES.append((name, bool(condition), detail))\n"
    "\n"
    "def run_cases(csv_text):\n"
    "    \"\"\"تشغيل دوال الأداة على بيانات مؤقتة — بلا عمليات فرعية\n"
    "    (عقد اختبار الركيزة: استيراد واستدعاء مباشر حصرًا).\"\"\"\n"
    "    with tempfile.TemporaryDirectory() as tmp:\n"
    "        path = os.path.join(tmp, 'transactions.csv')\n"
    "        open(path, 'w').write(csv_text)\n"
    "        try:\n"
    "            rows = tool.load_rows(path)\n"
    "            return 'ok', tool.summarize(rows)\n"
    "        except SystemExit as exit_signal:\n"
    "            return f'rejected({exit_signal.code})', None\n"
    "\n"
    "status, totals = run_cases(\n"
    "    'id,category,amount\\n1,food,25.00\\n2,travel,40.00\\n3,tools,20.00\\n'\n"
    ")\n"
    "check('valid input', status == 'ok' and abs(\n"
    "    sum(totals.values()) - 85.00) < 0.001)\n"
    "check('empty csv rejected', run_cases('id,category,amount\\n')[0]\n"
    "    .startswith('rejected'))\n"
    "check('invalid amount rejected', run_cases(\n"
    "    'id,category,amount\\n1,food,abc\\n')[0].startswith('rejected'))\n"
    "failed = [c for c in CASES if not c[1]]\n"
    "for name, ok_flag, detail in CASES:\n"
    "    print(('PASS' if ok_flag else 'FAIL'), name, detail)\n"
    "sys.exit(1 if failed else 0)\n"
)


def _code_files_response(files=None, entrypoint="tool.py",
                         tests_entrypoint="test_tool.py"):
    payload = {
        "files": files or [
            {"path": "tool.py", "content": _TOOL_PY},
            {"path": "transactions.csv", "content": _TRANSACTIONS_CSV},
            {"path": "test_tool.py", "content": _TEST_TOOL_PY},
        ],
        "entrypoint": entrypoint,
        "tests_entrypoint": tests_entrypoint,
        "notes": [],
    }
    return json.dumps(payload, ensure_ascii=False)


def test_code_mission_full_path_through_substrate(tmp_path):
    """المسار الكامل: كتابة ← تشغيل ← اختبار — المخرجات فعلية ببصمات."""
    router = FakeRouter([_code_files_response()])
    ctx = _ctx(tmp_path)
    implementer = LiveImplementer(router, tools_ctx=ctx)
    result = implementer.run(
        _code_task_request(sandbox_root=str(tmp_path))
    )
    assert result.status is ImplementerStatus.EXECUTED, result.stderr_truncated
    names = {str(p) for p in result.artifacts}
    assert any(n.endswith("tool.py") for n in names)
    assert any(n.endswith("transactions.csv") for n in names)
    assert any(n.endswith("report.md") for n in names)
    assert any(n.endswith("test_tool.py") for n in names)
    refs = "\n".join(result.evidence_refs)
    assert "run:exit=0:tool.py" in refs
    assert "run:exit=0:test_tool.py" in refs
    assert "sha256:" in refs
    # report.md ناتج الأداة الفعلي — إجماليات البيانات المكتوبة
    # (food 10+15+0=25 + travel 20+20=40 + tools 20 = 85.00)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "الإجمالي: 85.00" in report
    # برومبت المهمة البرمجية هو الذي وصل النموذج (لا برومبت التقرير)
    assert "المهمة البرمجية" in router.calls[0][0].content


def test_code_mission_failing_tests_reported_honestly(tmp_path):
    """اختبارات تفشل = فشل تنفيذي مفصل (CODE_RUN_FAILURE) لا نجاح مدّعى."""
    bad_tests = _TEST_TOOL_PY.replace(
        "check('valid input', status == 'ok'",
        "check('valid input', False and status == 'ok'",
    )
    router = FakeRouter([
        _code_files_response(files=[
            {"path": "tool.py", "content": _TOOL_PY},
            {"path": "transactions.csv", "content": _TRANSACTIONS_CSV},
            {"path": "test_tool.py", "content": bad_tests},
        ]),
    ])
    ctx = _ctx(tmp_path)
    implementer = LiveImplementer(router, tools_ctx=ctx)
    result = implementer.run(
        _code_task_request(sandbox_root=str(tmp_path))
    )
    assert result.status is ImplementerStatus.FAILED
    assert result.failure["class"] == "CODE_RUN_FAILURE"
    assert result.failure["reason"] == "TESTS_NONZERO"
    assert result.failure["tests_exit"] != 0
    # الأدلة رغم الفشل: الملفات المكتوبة ببصماتها + نتائج التشغيل
    assert any("sha256:" in r for r in result.evidence_refs)


def test_code_mission_broken_entrypoint_is_execution_failure(tmp_path):
    """أداة مكسورة = فشل ENTRYPOINT_NONZERO صريح بلا التهام."""
    router = FakeRouter([
        _code_files_response(files=[
            {"path": "tool.py", "content": "import missing_module_xyz\n"},
            {"path": "transactions.csv", "content": _TRANSACTIONS_CSV},
            {"path": "test_tool.py", "content": "print('no tests')\n"},
        ]),
    ])
    ctx = _ctx(tmp_path)
    implementer = LiveImplementer(router, tools_ctx=ctx)
    result = implementer.run(
        _code_task_request(sandbox_root=str(tmp_path))
    )
    assert result.status is ImplementerStatus.FAILED
    assert result.failure["reason"] == "ENTRYPOINT_NONZERO"
    # traceback حقيقي من الركيزة في رأس stderr — لا التهام صامت
    assert "Traceback" in result.failure["stderr_head"]
    assert result.failure["entry_exit"] != 0
