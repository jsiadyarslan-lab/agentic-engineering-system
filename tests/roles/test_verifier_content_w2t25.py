"""اختبارات W2-T25 — مقتطف المحتوى في حقائق المراجع الحي (content_head).

الدافع المقيس (الخطوة 122 للمشروع #3، التنفيذان 36/37): معايير المفكر
تفحص **مضمون** الملف («package.json content showing name: news-site»)
بينما حقائق المراجع كانت وجودًا وبصمة فقط — الملف الصحيح على القرص
والمراجع لا يراه → not_evidenced بصدق → المحكَّم ينهي «ركودًا» بخطوة
نُفِّذت صحيحة (بصمة الفشل نفسها مرتين: INSUFFICIENT_EVIDENCE).

العقد الجديد: الملفات النصية الصغيرة تُقتطف (content_head ≤1800 حرفًا،
ملفات ≤256KB) — المضمون المثبت نفسه يصل للمراجع.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from roles.live import VerifierLive  # noqa: E402
from roles.verifier import VerifierRequest  # noqa: E402


class _StubRouter:
    """موجّه صامت — يمسك الحمولة ويعيد حكمًا محددًا مسبقًا."""

    def __init__(self, verdict_json: dict):
        self._verdict = verdict_json
        self.payloads: list[str] = []

    def chat_live(self, messages, **_kwargs):
        import json
        self.payloads.append(messages[-1].content)
        return {"text": json.dumps(self._verdict, ensure_ascii=False)}


def _write(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_content_head_in_facts_for_text_files(tmp_path):
    """الملف النصي الصغير يصل بمقتطفه — المراجع يرى name/version/type."""
    pkg = _write(tmp_path, "package.json", (
        '{\n  "name": "news-site",\n  "version": "1.0.0",\n'
        '  "type": "module",\n  "scripts": {"dev": "vite",'
        ' "build": "vite build", "preview": "vite preview"},\n'
        '  "devDependencies": {"vite": "^5.0.0"}\n}\n'))
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=[
            'package.json content showing name: "news-site"',
            'package.json content showing version: "1.0.0"',
        ],
        artifacts=[pkg],
    ))
    import json
    payload = json.loads(router.payloads[0])
    files = payload["facts"]["files"]["package.json"]
    assert files["exists"] is True
    assert "content_head" in files
    assert '"news-site"' in files["content_head"]
    assert '"1.0.0"' in files["content_head"]
    assert '"vite": "^5.0.0"' in files["content_head"]


def test_content_head_absent_for_binary_and_missing(tmp_path):
    """PDF/ملف غائب: وجود فقط بلا مقتطف — العقد كما كان للثنائيات."""
    pdf = tmp_path / "T1-report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake-binary\x00\x01\x02")
    missing = str(tmp_path / "absent.json")
    router = _StubRouter({"verdict": "not_evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 0.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=["x"], artifacts=[str(pdf), missing]))
    import json
    payload = json.loads(router.payloads[0])
    assert "content_head" not in payload["facts"]["files"]["T1-report.pdf"]
    assert payload["facts"]["files"]["T1-report.pdf"]["exists"] is True
    assert payload["facts"]["files"]["absent.json"]["exists"] is False


def test_content_head_bounded(tmp_path):
    """ملف نصي كبير: المقتطف محدود بالسقف المعلن لا يتجاوزه."""
    big = _write(tmp_path, "big.md", "x" * 5000)
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(task_acceptance_criteria=["x"],
                             artifacts=[big]))
    import json
    payload = json.loads(router.payloads[0])
    head = payload["facts"]["files"]["big.md"]["content_head"]
    assert len(head) <= role._CONTENT_HEAD_LIMIT


def test_content_head_skips_oversized_files(tmp_path):
    """ملف نصي فوق حد 256KB: بلا مقتطف (سقف القراءة المعلن)."""
    big = tmp_path / "huge.json"
    big.write_text('{"pad": "' + "y" * 300_000 + '"}', encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(task_acceptance_criteria=["x"],
                             artifacts=[str(big)]))
    import json
    payload = json.loads(router.payloads[0])
    assert "content_head" not in payload["facts"]["files"]["huge.json"]
    assert payload["facts"]["files"]["huge.json"]["exists"] is True


def test_verifier_prompt_mentions_content_head():
    """البرومبت يعلن الحقيقة الجديدة للمراجع (لا يفاجأ بها)."""
    prompt = (REPO / "prompts" / "verifier.md").read_text(encoding="utf-8")
    assert "content_head" in prompt
