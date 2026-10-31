"""اختبارات W2-T25 — قابلية الكتابة في حقائق المراجع الحي (writable).

الدافع المقيس (الخطوة 726 للمشروع #3، التنفيذ 441، إعادة إنتاج حية
بالمعايير والملفات نفسها): معيار «Each file exists and is writable»
حُكم نقصًا حرفيًا — «Writable permission not mechanically verified for
any of the five files (no file permission data in facts)» — بينما
الملفات الخمسة موجودة على القرص وكتبها المنفذ للتو. عمى الحقائق
نفسه فئة content_head/ddac7d7: المعيار يطلب حقيقة لا تصل المراجع.

العقد الجديد: كل ملف في facts يحمل `writable` مقيسة فعليًا
(os.access W_OK) — الموجود القابل كتابةً true، والغائب false،
والمقصي للقراءة فقط false. والبرومبت يعلن القاعدة.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from roles.live import VerifierLive  # noqa: E402
from roles.verifier import VerifierRequest  # noqa: E402

_PROMPT = (REPO / "prompts" / "verifier.md").read_text(encoding="utf-8")


class _StubRouter:
    """موجّه صامت — يمسك الحمولة ويعيد حكمًا محددًا مسبقًا."""

    def __init__(self, verdict_json: dict):
        self._verdict = verdict_json
        self.payloads: list[str] = []

    def chat_live(self, messages, **_kwargs):
        self.payloads.append(messages[-1].content)
        return {"text": json.dumps(self._verdict, ensure_ascii=False)}


def _run_over(paths: list[str]) -> dict:
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    VerifierLive(router).run(VerifierRequest(
        task_acceptance_criteria=["Each file exists and is writable."],
        artifacts=paths,
    ))
    return json.loads(router.payloads[0])["facts"]["files"]


def test_writable_true_for_written_file(tmp_path):
    """ملف كتبه المنفذ للتو — writable=true مقيسة فعلًا."""
    f = tmp_path / "index.html"
    f.write_text("<html></html>", encoding="utf-8")
    files = _run_over([str(f)])
    assert files["index.html"]["exists"] is True
    assert files["index.html"]["writable"] is True


def test_writable_false_for_missing_file(tmp_path):
    """الملف الغائب — writable=false (الوجود نفسه false)."""
    files = _run_over([str(tmp_path / "absent.css")])
    assert files["absent.css"]["exists"] is False
    assert files["absent.css"]["writable"] is False


def test_writable_false_for_readonly_file(tmp_path):
    """ملف مقصي للقراءة فقط — writable=false من صلاحيات القرص."""
    f = tmp_path / "styles.css"
    f.write_text("body{}", encoding="utf-8")
    os.chmod(f, 0o444)
    if os.access(f, os.W_OK):  # root يتجاوز الصلاحيات — لا اختبار هنا
        pytest.skip("فعّال بصفة root — بتات الصلاحية غير مُعتبَرة")
    files = _run_over([str(f)])
    assert files["styles.css"]["exists"] is True
    assert files["styles.css"]["writable"] is False
    os.chmod(f, 0o644)


def test_prompt_announces_writable_fact():
    """البرومبت يعلن حقيقة writable — المراجع يعرف مصدر الحكم."""
    assert "writable" in _PROMPT
    assert "is writable" in _PROMPT
