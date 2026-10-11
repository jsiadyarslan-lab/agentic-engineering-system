"""اختبارات سلامة الإبلاغ عن الفشل (الأمر 013.9 D2).

العقد الحرفي من الأمر (§4) — ثلاث حالات إلزامية:
- فشل يحوي ``code`` صالحًا ← الرمز يظهر في التفصيل كما هو.
- فشل لا يحوي ``code`` ← رمز بديل معلن (FAILURE_UNCODED)، بلا
  استثناء ثانوي (KeyError) يحجب السبب الأصلي ويحوّل الاستجابة
  إلى HTTP 500.
- فشل يحوي ``code`` غير صالح (None/رقم) ← نفس المعاملة الآمنة.

ويُحفظ دائمًا: exit_code و termination و stdout و stderr وتفاصيل
البيئة والأدلة، ولا يتحول الفشل إلى نجاح لمجرد غياب حقل.

إضافة (D2-b من نفس عائلة العيب): مسار ``SubstrateUnavailable`` في
LocalSandboxBackend.verify كان يذكر اسمًا غير معرّف
(``substrate_local_substrate``) فيتعامل مع الاستثناء الأصلي بـ
NameError ثانوي — عولج مع D2 لكونه حرفيًا «استثناء ثانوي يحجب
سبب الفشل الأصلي» على مسار صياغة النتيجة.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from execution.backends import (  # noqa: E402
    FAILURE_CODE_FALLBACK,
    LocalProcessBackend,
    LocalSandboxBackend,
    _failure_code,
)


# ------------------------------------------------------------------ #
# §4 — العقد المساعد _failure_code (لا يرفع أبدًا)
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("failure,expected", [
    ({"code": "RUNTIME_WORKSPACE_INVALID"}, "RUNTIME_WORKSPACE_INVALID"),
    ({"code": "RUNTIME_WORKSPACE_INVALID", "reason": "X"}, "RUNTIME_WORKSPACE_INVALID"),
    ({}, FAILURE_CODE_FALLBACK),
    ({"reason": "SOMETHING"}, FAILURE_CODE_FALLBACK),
    ({"code": None}, FAILURE_CODE_FALLBACK),
    ({"code": ""}, FAILURE_CODE_FALLBACK),
    ({"code": "   "}, FAILURE_CODE_FALLBACK),
    ({"code": 123}, FAILURE_CODE_FALLBACK),
    ({"code": ["list"]}, FAILURE_CODE_FALLBACK),
    (None, FAILURE_CODE_FALLBACK),
])
def test_failure_code_helper_never_raises(failure, expected):
    assert _failure_code(failure) == expected


# ------------------------------------------------------------------ #
# §4 — الحالات الثلاث عبر مسار execute() الحقيقي
# ------------------------------------------------------------------ #

def _backend_with_run_failure(monkeypatch, failure_dict):
    """خلفية متوافقة يُجبر مسار إطلاقها على فشل مساحة عمل مهيكل.

    seam معتمد (نمط 0131): حقن نتيجة _run مباشرة يعزل اختبار صياغة
    النتيجة عن سلوك المضيف — ما يُختبر هو تنفيذ execute() الحرفي
    على مدخلات عدائية، لا سلوك النظام الفرعي للعمليات.
    """
    backend = LocalProcessBackend(environment_id="d2-test")

    def fake_run(code, args, *, workspace, timeout_s):
        return (
            -1, "", "FAILED_TO_START: boom", "startup", dict(failure_dict),
        )

    monkeypatch.setattr(backend, "_run", fake_run)
    return backend


def _execute_on(backend, tmp_path):
    return backend.run_code(
        "print('x')", workspace=tmp_path / "ws", artifacts=tmp_path / "art",
        timeout_s=10.0,
    )


def test_failure_with_valid_code_shown_verbatim(tmp_path, monkeypatch):
    """الحالة 1: code صالح — يظهر حرفيًا في التفصيل."""
    backend = _backend_with_run_failure(monkeypatch, {
        "code": "RUNTIME_WORKSPACE_INVALID",
        "reason": "WORKSPACE_MISSING_AT_LAUNCH",
        "cwd": "/tmp/gone",
    })
    outcome = _execute_on(backend, tmp_path)
    assert "RUNTIME_WORKSPACE_INVALID/WORKSPACE_MISSING_AT_LAUNCH" in (
        outcome.detail
    )
    assert outcome.termination == "FAILED_TO_START"
    assert outcome.exit_code == -1
    assert outcome.failure["code"] == "RUNTIME_WORKSPACE_INVALID"


def test_failure_without_code_no_secondary_exception(tmp_path, monkeypatch):
    """الحالة 2: بلا code — لا KeyError، رمز بديل معلن، التفاصيل محفوظة.

    قبل 013.9 كان هذا المسار يرفع KeyError أثناء صياغة التفصيل نفسه
    (backends.py:936 في الأصل) فيتحول التشخيص إلى HTTP 500 ثانوي
    يحجب السبب الأصلي.
    """
    backend = _backend_with_run_failure(monkeypatch, {
        "reason": "WORKSPACE_MISSING_AT_LAUNCH",
        "cwd": "/tmp/gone",
    })
    outcome = _execute_on(backend, tmp_path)  # لا استثناء — هذا جوهر D2
    assert f"[{FAILURE_CODE_FALLBACK}/WORKSPACE_MISSING_AT_LAUNCH" in (
        outcome.detail
    )
    assert outcome.termination == "FAILED_TO_START"
    assert outcome.exit_code != 0
    assert outcome.ok is False, "لا يتحول الفشل إلى نجاح لغياب حقل"
    # التفاصيل الأصلية باقية كما هي في التقرير — لم تُستبدل
    assert outcome.failure["reason"] == "WORKSPACE_MISSING_AT_LAUNCH"
    assert outcome.failure["cwd"] == "/tmp/gone"
    assert "code" not in outcome.failure, "لم يُخترع code مزيف في التقرير"


@pytest.mark.parametrize("bad_code", [None, 123, "", "   "])
def test_failure_with_invalid_code_safe(tmp_path, monkeypatch, bad_code):
    """الحالة 3: code غير صالح — نفس المعاملة الآمنة والرمز البديل."""
    backend = _backend_with_run_failure(monkeypatch, {
        "code": bad_code, "reason": "R", "cwd": "/c",
    })
    outcome = _execute_on(backend, tmp_path)
    assert f"[{FAILURE_CODE_FALLBACK}/R" in outcome.detail
    assert outcome.termination == "FAILED_TO_START"
    assert outcome.exit_code == -1


def test_run_oserror_path_formats_safely_without_code(monkeypatch, tmp_path):
    """مسار _run الحقيقي: OSError ← classify بلا code ← لا استثناء ثانوي.

    يغطي موقع backends.py:759 الأصلي: تصنيف OSError يعيد تقريرًا
    ناقص المفاتيح (code/reason/host/execution_mode) فتكسر الصياغة
    نفسها الاستجابة. بعد D2 تُقرأ كلها بأمان والسبب الخام يبقى ظاهرًا.
    """
    import execution.backends as backends_mod
    import execution.workspace as workspace_mod

    def hostile_classify(error, *, cwd, **_kwargs):
        return {"cwd": cwd}  # بلا code ولا reason ولا host

    def hostile_popen(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "/gone/ws")

    monkeypatch.setattr(
        workspace_mod, "classify_process_oserror", hostile_classify,
    )
    monkeypatch.setattr(backends_mod.subprocess, "Popen", hostile_popen)

    backend = LocalProcessBackend(environment_id="d2-run-path")
    exit_code, stdout, stderr, detail, failure = backend._run(
        "print('x')", [], workspace=tmp_path / "ws", timeout_s=5.0,
    )
    # عقد _run الحرفي: الموضع الثالث يحمل النص التشخيصي والرابع
    # مؤشر الفئة ("startup") — كلاهما يُحفظ بلا استثناء ثانوي.
    assert exit_code == -1
    assert detail == "startup"
    assert "FAILED_TO_START" in stderr
    assert "No such file or directory" in stderr, "السبب الخام يبقى ظاهرًا"
    assert FAILURE_CODE_FALLBACK in stderr, "رمز بديل معلن بدل KeyError"
    assert failure == {"cwd": str(tmp_path / "ws")}, "التقرير الأصلي سليم"


def test_execute_preserves_success_fields_on_failure(tmp_path, monkeypatch):
    """حفظ حقول النتيجة كاملة عند الفشل: stdout/stderr/الأدلة/المدة."""
    backend = _backend_with_run_failure(monkeypatch, {
        "reason": "WORKSPACE_MISSING_AT_LAUNCH", "cwd": "/tmp/gone",
    })
    outcome = _execute_on(backend, tmp_path)
    # عقد ExecutionOutcome كامل الحقول حتى في الفشل — لا حجب ولا تفريغ
    assert outcome.environment_id == "d2-test"
    assert outcome.backend == "LOCAL"
    assert outcome.duration_ms >= 0
    assert isinstance(outcome.stdout, str) and isinstance(outcome.stderr, str)
    # مسار الإصلاح الواحد موثق في التقرير (§10): repaired_attempted
    # يُضاف للتقرير الأصلي — لا استبدال للتفاصيل الأولى.
    assert outcome.failure["repaired_attempted"] is True
    assert outcome.failure["reason"] == "WORKSPACE_MISSING_AT_LAUNCH"


# ------------------------------------------------------------------ #
# D2-b — SubstrateUnavailable لا يتحول إلى NameError ثانوي
# ------------------------------------------------------------------ #

@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="يتطلب ركيزة Linux متاحة (available() تتحقق أولًا)",
)
def test_sandbox_verify_substrate_unavailable_honest(monkeypatch):
    """verify() عند غياب الركيزة = UNAVAILABLE بسبب معلن — لا NameError.

    قبل 013.9 كان معالج الاستثناء يذكر ``substrate_local_substrate``
    (اسم غير معرّف — الربط الفعلي ``local_substrate``) فيرفع NameError
    ثانويًا يحجب سبب الاستغناء الأصلي أثناء صياغة نتيجة التحقق.
    """
    from substrate.local_substrate import SubstrateUnavailable

    backend = LocalSandboxBackend(environment_id="d2-sandbox")

    def unavailable_manager():
        raise SubstrateUnavailable(
            "محاكاة 013.9: تعذر إنشاء العزل الحقيقي لهذا الاختبار"
        )

    monkeypatch.setattr(backend, "_manager", unavailable_manager)
    result = backend.verify()  # قبل الإصلاح: NameError هنا
    assert result.status == "UNAVAILABLE"
    assert result.ok is False
    assert "محاكاة 013.9" in result.reason, "السبب الأصلي ظاهر بلا حجب"
