"""اختبارات الأدوار الحية (الأمر السادس §2.3) — إعادة واحدة ثم فشل.

موجّه مزيف حقنًا (اختبار بنية تحتية — الاستجابات مسجَّلة، لكن المسار
الحقيقي: برومبت ← chat_live ← استخراج JSON ← تحقق العقد ← إعادة/فشل).
"""

from __future__ import annotations

import json

import pytest

from roles.live import RoleSystemFault, ThinkerLive, VerifierLive
from roles.thinker import ThinkerRequest
from roles.verifier import VerifierRequest
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


def test_role_json_retry_then_success():
    """JSON تالف ثم صالح — الإعادة الواحدة تنجح والاستدعاءان موثقان."""
    bad = "لا أستطيع الالتزام بصيغة JSON"          # لا كائن JSON إطلاقًا
    good = (
        '{"tasks": [{"id": "T1", "description": "اكتب التقرير",'
        ' "acceptance_criteria": ["الملف report.md موجود ضمن الأدلة"]}],'
        ' "risks": ["مصادر ناقصة"], "assumptions": ["الشبكة متاحة"],'
        ' "evidence_required": ["مسار الملفات"]}'
    )
    router = FakeRouter([bad, good])
    thinker = ThinkerLive(router)
    result = thinker.run(ThinkerRequest(goal="تقرير عن الشرق الأوسط"))
    assert len(result.plan.tasks) == 1
    assert result.plan.tasks[0].id == "T1"
    assert len(router.calls) == 2  # المحاولة الأولى فشلت ثم الإعادة
    # رسالة الإعادة تحمل التغذية الراجحة (خطأ التحقق)
    assert "JSON" in router.calls[1][-1].content


def test_role_system_fault_after_retry():
    """JSON تالف مرتين = فشل الدور الصريح RoleSystemFault (system_fault)."""
    router = FakeRouter(["نص بلا JSON", "{'مفاتيح': 'غير مكتملة'}"])
    thinker = ThinkerLive(router)
    with pytest.raises(RoleSystemFault) as fault:
        thinker.run(ThinkerRequest(goal="هدف"))
    assert fault.value.role == "thinker"
    assert len(router.calls) == 2  # إعادة واحدة فقط — لا دوران


def test_verifier_live_gets_mechanical_facts(tmp_path):
    """المراجع الحي يبني حقائقه الميكانيكية بنفسه (وجود الملفات)."""
    real_file = tmp_path / "report.pdf"
    real_file.write_bytes(b"%PDF-1.4 fake")
    payload_holder: dict = {}

    class CapturingRouter(FakeRouter):
        def chat_live(self, messages, **kwargs):
            payload_holder["last_user"] = messages[-1].content
            return super().chat_live(messages, **kwargs)

    router = CapturingRouter(
        ['{"verdict": "evidenced", "checks_performed": ["الملف موجود"],'
         ' "missing_evidence": [], "confidence": 1.0}']
    )
    verifier = VerifierLive(router)
    result = verifier.run(
        VerifierRequest(
            task_acceptance_criteria=["الملف report.pdf موجود ضمن الأدلة"],
            artifacts=[str(real_file)],
        )
    )
    assert result.verdict.value == "evidenced"
    # الحقائق الميكانيكية وصلت النموذج في نفس الطلب
    assert "report.pdf" in payload_holder["last_user"]
    assert '"exists": true' in payload_holder["last_user"]


def test_verifier_live_content_preview_mechanical(tmp_path):
    """(AES-LIVE-FACTORY-E2E-001 المرحلة 6) محتوى نصي صغير ← معاينة
    كاملة تصل المحقق؛ ملف ضخم أو غير نصي ← بلا معاينة (حد معلن)."""
    from roles.verifier import VerifierRequest

    small = tmp_path / "index.html"
    small.write_text(
        "<!doctype html><html dir='rtl'><header></header>"
        "<nav></nav><ul></ul></html>", encoding="utf-8")
    big = tmp_path / "big.js"
    big.write_text("x" * 250_000, encoding="utf-8")
    binary = tmp_path / "shot.png"
    binary.write_bytes(b"\x89PNG" + b"0" * 100)

    captured = {}

    class CaptureRouter(FakeRouter):
        def chat_live(self, messages, **_kwargs):
            captured["payload"] = json.loads(messages[-1].content)
            raise AssertionError("stop-here")

    verifier = VerifierLive(CaptureRouter([]))
    request = VerifierRequest(
        task_acceptance_criteria=["index.html يحتوي header وnav"],
        artifacts=[str(small), str(big), str(binary)],
        evidence_refs=["sha256:abc:index.html"],
    )
    try:
        verifier.run(request)
    except AssertionError:
        pass
    files = captured["payload"]["facts"]["files"]
    assert "content_full" in files["index.html"]
    assert "<header>" in files["index.html"]["content_full"]
    assert "content_full" not in files["big.js"]
    assert "content_full" not in files["shot.png"]
