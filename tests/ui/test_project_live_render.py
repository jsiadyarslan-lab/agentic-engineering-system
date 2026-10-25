"""(AES-ORACLE-UI-RUNTIME-002 §2+§3+§6) اختبارات تراجع رسم بطاقة التنفيذ.

البنود المغطاة من الأمر:
- renderExecutionCard لا يرمي استثناءً بلا سجل تنفيذ أو ببيانات ناقصة
  (بند 3 — المرجع لعطل ReferenceError: execution is not defined).
- الحقول الاختيارية (command/cwd/pid/parent_pid/command_type) بأمان —
  غياب أي منها لا يوقف الرسم، ولا PID/أمر وهميًا أبدًا.
- بطاقة النشاط الحي تُبنى من أحداث حقيقية بترتيبها (بند 5).
- حدود الرسم: فشل بطاقة لا يقتل المشهد — appendSafe يعرض خطأ قابلًا
  للتشخيص (بند 11: لا ReferenceError توقف المشهد كله).

طبقتان:
1) ثابتة على المصدر (تعمل دائمًا حتى بلا node).
2) وظيفية عبر node مع DOM مصغّر (تتخطى بصدق إن غاب node).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UI = REPO / "src" / "ui"
PROJECT_LIVE = UI / "project-live.js"


# ---------------- 1) ثوابت المصدر — تعمل دائمًا ----------------

def test_execution_is_defined_from_snapshot_before_use():
    """المرجع الصادق: السجل يُعرَّف من اللقطة قبل أي استعمال."""
    src = PROJECT_LIVE.read_text(encoding="utf-8")
    define_at = src.find("var execution = state.execution || null;")
    assert define_at != -1, "تعريف execution من اللقطة غائب"
    first_use = src.find("execution.command", define_at)
    assert first_use != -1
    # لا استعمال لـ execution قبل التعريف داخل الدالة
    func_start = src.find("function renderExecutionCard")
    assert func_start != -1 and func_start < define_at
    assert src.find("execution.", func_start, define_at) == -1


def test_scene_uses_safe_render_boundaries():
    """حدود الرسم: البطاقات تُركب عبر appendSafe لا append مباشر."""
    src = PROJECT_LIVE.read_text(encoding="utf-8")
    for name in ("بطاقة التنفيذ", "بطاقة النشاط الحي", "بطاقة التوقف",
                 "بطاقة التحقق", "بطاقة الاعتماد"):
        assert f'appendSafe(container, "{name}"' in src, name
    assert "renderExecutionCard: renderExecutionCard" in src


def test_live_refresh_includes_role_tool_model_events():
    """(§3) نشاط الأدوار/الأدوات/النموذج يحدّث المشهد حيًا."""
    src = PROJECT_LIVE.read_text(encoding="utf-8")
    for kind in ("ROLE_EXECUTING", "TOOL_EXECUTION",
                 "MODEL_CALL_STARTED", "MODEL_CALL_COMPLETED",
                 "MODEL_CALL_FAILED", "STEP_STARTED", "STEP_COMPLETED",
                 "EVIDENCE_CREATED"):
        assert f'"{kind}"' in src, kind


# ---------------- 2) وظيفية عبر node — DOM مصغّر ----------------

NODE = shutil.which("node")


def _run_node(script: str) -> str:
    proc = subprocess.run(
        [NODE, "-e", script, str(PROJECT_LIVE)],
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError(
            "فشل اختبار node:\nSTDOUT:\n" + proc.stdout
            + "\nSTDERR:\n" + proc.stderr)
    return proc.stdout


DOM_STUB = r"""
const fs = require("fs");
function makeNode(tag) {
  return {
    tag, className: "", textContent: "", dir: "", hidden: false,
    style: {}, children: [], title: "", value: "",
    appendChild(c) { this.children.push(c); return c; },
    remove() {}, setAttribute() {}, removeAttribute() {},
    addEventListener() {}, removeEventListener() {},
    querySelector() { return null; },
    classList: { add() {}, remove() {}, toggle() {} },
    contains() { return false; },
  };
}
global.document = {
  createElement: (t) => makeNode(t),
  getElementById: () => null,
  addEventListener() {},
  body: makeNode("body"),
  visibilityState: "visible",
};
global.window = {
  Hub: { $: () => makeNode("div"), esc: (s) => String(s) },
  addEventListener() {},
  ErrorBoundary: { report() {} },
};
global.navigator = {};
global.location = { reload() {} };

function texts(n, acc) {
  acc = acc || [];
  if (!n) return acc;
  if (n.textContent) acc.push(String(n.textContent));
  (n.children || []).forEach((c) => texts(c, acc));
  return acc;
}
function allText(n) { return texts(n).join(" | "); }

const src = fs.readFileSync(process.argv[2] || process.argv[1], "utf8");
eval(src);
const PL = global.window.ProjectLive;
if (!PL || !PL.renderExecutionCard) {
  console.error("FAIL: ProjectLive.renderExecutionCard غير مُصدَّرة");
  process.exit(2);
}
const assert = require("assert");

// (بند 2) لا سجل تنفيذ: حالة فارغة صريحة — لا استثناء
let out = PL.renderExecutionCard(
  { id: 4, status: "RUNNING", objective: "هدف", phases: [], events: [],
    execution: null, job: { id: 1, status: "RUNNING" } }, {});
let t = allText(out.row);
assert(t.indexOf("لم تتوفر بعد") !== -1, "الحالة الفارغة الصريحة غائبة");
assert(t.indexOf("undefined") === -1, "نص undefined تسرّب للعرض");

// (بند 3) حقول ناقصة: الأمر فقط بلا PID — لا استثناء ولا حقول وهمية
out = PL.renderExecutionCard(
  { id: 4, status: "RUNNING", objective: "هدف", phases: [], events: [],
    execution: { command: "python generate.py" },
    job: { id: 1, status: "RUNNING" } }, {});
t = allText(out.row);
assert(t.indexOf("python generate.py") !== -1, "الأمر غير معروض");
assert(t.indexOf("(PID)") === -1, "PID وهمي ظهر رغم غيابه من السجل");
assert(t.indexOf("لم تتوفر بعد") === -1, "الحالة الفارغة ظهرت رغم وجود سجل");

// سجل كامل: كل الحقول تُعرض
out = PL.renderExecutionCard(
  { id: 4, status: "RUNNING", objective: "هدف", phases: [], events: [],
    execution: { command: "pytest -q", cwd: "/ws", pid: 123,
                 parent_pid: 9, command_type: "step_execution" },
    job: { id: 1, status: "RUNNING" } }, {});
t = allText(out.row);
for (const want of ["pytest -q", "(PID)", "(PPID)", "step_execution"]) {
  assert(t.indexOf(want) !== -1, "حقل مفقود: " + want);
}

// (بند 5) بطاقة النشاط من أحداث حقيقية بترتيبها + النشاط الحالي
const container = makeNode("div");
PL.renderProjectScene(container, {
  id: 4, status: "RUNNING", objective: "بناء منصة",
  plan: { phases: [] }, phases: [],
  events: [
    { id: 1, kind: "ROLE_EXECUTING", payload: { role: "thinker" } },
    { id: 2, kind: "TOOL_EXECUTION",
      payload: { tool: "file_write", phase: "succeeded" } },
    { id: 3, kind: "MODEL_CALL_COMPLETED", payload: { duration_ms: 1500 } },
  ],
  job: { id: 1, status: "RUNNING" },
  activity: { role: "thinker", tool: "file_write", provider: "nvidia" },
  execution: { command: "x" },
}, {});
t = allText(container);
assert(t.indexOf("التنفيذ جارٍ") !== -1, "بطاقة التنفيذ غائبة عن المشهد");
assert(t.indexOf("المفكر يعمل الآن") !== -1, "نشاط المفكر غائب");
assert(t.indexOf("أداة file_write") !== -1, "نشاط الأداة غائب");
assert(t.indexOf("نشاط حالي") !== -1, "النشاط الحالي من اللقطة غائب");
assert(t.indexOf("nvidia") !== -1, "المزود الحالي غائب");

// (بند 11) حدود الرسم: بطاقة ترمي ← المشهد يبقى ويعرض خطأ قابلًا للتشخيص
const container2 = makeNode("div");
PL.appendSafe(container2, "بطاقة اختبار", function () {
  throw new Error("boom-اختبار");
});
t = allText(container2);
assert(t.indexOf("تعذر رسم قسم") !== -1, "رسالة الخطأ القابلة للتشخيص غائبة");
assert(t.indexOf("boom-اختبار") !== -1, "سبب الخطأ غائب");

console.log("ALL_OK");
"""


@pytest.mark.skipif(
    NODE is None,
    reason="node غير متاح في هذه البيئة — الاختبار الوظيفي يتطلبه")
def test_render_execution_card_never_throws_node():
    """الوظيفة الحرفية: البطاقة ترسم بلا استثناء عبر الحالات الثلاث."""
    out = _run_node(DOM_STUB)
    assert "ALL_OK" in out
