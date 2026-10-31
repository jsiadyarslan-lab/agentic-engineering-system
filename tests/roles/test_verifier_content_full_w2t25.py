"""اختبارات W2-T25 2026-11-01 — الملف الصغير كله في حقائق المراجع.

الدافع المقيس (الخطوة 1009، تنفيذ 638): index.html (~3KB) فيه الأقسام
(#latest/#categories/#newsletter) في وسطه، ونافذة الرأس+الذيل
(1800+600 حرفًا) عمت الوسط فحكم المراجع «Sections with ids 'latest',
'categories', 'newsletter' not observed in provided snippets
(content_head, content_tail)» مرتين على ملف كُتب صحيحًا.

العقد: الملف النصي ≤8KB يصل كله (content_full) بلا head/tail ازدواجًا؛
الأكبر منه يبقى على الرأس+الذيل؛ ملخص JSON يبقى وارًا للملفات الصغيرة
والكبيرة معًا (لا يلغيه content_full).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from roles.live import VerifierLive  # noqa: E402
from roles.verifier import VerifierRequest  # noqa: E402


class _StubRouter:
    def __init__(self, verdict_json: dict):
        self._verdict = verdict_json
        self.payloads: list[str] = []

    def chat_live(self, messages, **_kwargs):
        self.payloads.append(messages[-1].content)
        return {"text": json.dumps(self._verdict, ensure_ascii=False)}


def _facts(tmp_path: Path, name: str, body: str) -> dict:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced", "checks_performed": [],
                          "missing_evidence": [], "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=["File exists"], artifacts=[str(p)]))
    payload = json.loads(router.payloads[0])
    return payload["facts"]


_MIDDLE_HTML = (
    "<!DOCTYPE html>\n<html lang=\"en\">\n<head><title>News Portal"
    " - Placeholder</title></head>\n<body>\n<header>hero header</header>\n"
    + ("<p>filler line to push sections beyond the head window.</p>\n" * 60)
    + "<main>\n<section id=\"latest\">latest news here</section>\n"
    "<section id=\"categories\">categories here</section>\n"
    "<section id=\"newsletter\">newsletter here</section>\n</main>\n"
    "<footer>site footer</footer>\n</body>\n</html>\n")


def test_small_html_file_arrives_whole(tmp_path):
    """قياس 1009 حرفيًا: أقسام الوسط تصل كاملة — لا «not observed»."""
    facts = _facts(tmp_path, "index.html", _MIDDLE_HTML)
    entry = facts["files"]["index.html"]
    assert entry["content_full"] is not None
    for section in ("latest", "categories", "newsletter"):
        assert f'id="{section}"' in entry["content_full"], section
    # لا ازدواج: content_full يحل محل head/tail لا يراكبهما.
    assert "content_head" not in entry
    assert "content_tail" not in entry


def test_large_file_keeps_head_tail(tmp_path):
    """الملف الأكبر من السقف يبقى على النافذة — لا انفجار حجم الحقائق."""
    big = "<html>" + ("<p>long body line for a large page.</p>\n" * 700) \
        + "<section id=\"latest\"></section></html>"
    assert len(big) > 8_192
    facts = _facts(tmp_path, "index.html", big)
    entry = facts["files"]["index.html"]
    assert "content_full" not in entry
    assert "content_head" in entry and "content_tail" in entry


def test_json_summary_survives_content_full(tmp_path):
    """ملخص JSON يبقى وارًا مع content_full — ملخص البنية لا يُلغى."""
    data = [{"id": i, "title": f"t{i}"} for i in range(7)]
    facts = _facts(tmp_path, "articles.json", json.dumps(data))
    entry = facts["files"]["articles.json"]
    assert entry["content_full"] is not None
    assert entry["json_summary"]["type"] == "array"
    assert entry["json_summary"]["length"] == 7


def test_verifier_prompt_declares_content_full():
    """البرومبت يعلن content_full للمراجع — لا مفاجأة حقائق."""
    prompt = (REPO / "prompts" / "verifier.md").read_text(encoding="utf-8")
    assert "content_full" in prompt
