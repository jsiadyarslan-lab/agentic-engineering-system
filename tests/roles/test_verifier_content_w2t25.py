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


def test_content_head_covers_dotfiles(tmp_path):
    """.prettierrc/.gitignore نصوص رغم امتدادها الفارغ — معايير
    «.prettierrc content showing semi: true» تفحص مضمونها حرفيًا
    (قياس حي التنفيذ 42: الملف الكامل الصحيح على القرص والمراجع
    أعمى عنه فرفض الدورة كلها)."""
    dot = _write(tmp_path, ".prettierrc",
                 '{\n  "semi": true,\n  "singleQuote": true,\n'
                 '  "tabWidth": 2\n}\n')
    gi = _write(tmp_path, ".gitignore", "node_modules\n.next\n.turbo\n")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=[
            ".prettierrc content showing semi: true, singleQuote: true",
            ".gitignore content showing node_modules",
        ],
        artifacts=[dot, gi],
    ))
    import json
    payload = json.loads(router.payloads[0])
    prettier = payload["facts"]["files"][".prettierrc"]
    gitignore = payload["facts"]["files"][".gitignore"]
    assert '"semi": true' in prettier["content_head"]
    assert "node_modules" in gitignore["content_head"]


# ------------------------------------------------------------------ #
# (W2-T25) relpath في حقائق المراجع — معايير المسارات
# ------------------------------------------------------------------ #

def test_relpath_in_facts_for_path_criteria(tmp_path):
    """معيار «node_modules/.package-lock.json exists» يتحقق من relpath —
    قياس حي الخطوة 221: الملف موجود والاسم المجرد (.package-lock.json)
    لم يطابق المسار المذكور عند المراجع فحكم بالغياب زورًا."""
    root = tmp_path / "step221"
    (root / "node_modules").mkdir(parents=True)
    lock = root / "node_modules" / ".package-lock.json"
    lock.write_text('{"lockfileVersion": 3}', encoding="utf-8")
    root_pkg = root / "package-lock.json"
    root_pkg.write_text('{"lockfileVersion": 3}', encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=[
            "package-lock.json exists at root",
            "node_modules/.package-lock.json exists (indicates install completed)",
        ],
        artifacts=[str(root_pkg), str(lock)],
        evidence_refs=[],
    ))
    import json
    payload = json.loads(router.payloads[0])
    facts = payload["facts"]["files"]
    assert facts[".package-lock.json"]["relpath"] == \
        "node_modules/.package-lock.json"
    assert facts["package-lock.json"]["relpath"] == "package-lock.json"
    assert facts[".package-lock.json"]["exists"] is True


def test_install_log_evidence_reaches_verifier(tmp_path):
    """سجل أمر البناء (install log) يصل الأدلة فيراه المراجع —
    ملفات evidence/build-* مع مضمونها (stderr فارغ = لا أخطاء)."""
    ev = tmp_path / "evidence"
    ev.mkdir()
    stdout_log = ev / "build-npm-install-stdout.txt"
    stdout_log.write_text("added 2 packages in 5s", encoding="utf-8")
    stderr_log = ev / "build-npm-install-stderr.txt"
    stderr_log.write_text("", encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=["No error output captured in install log"],
        artifacts=[str(stdout_log), str(stderr_log)],
        evidence_refs=[],
    ))
    import json
    payload = json.loads(router.payloads[0])
    facts = payload["facts"]["files"]
    assert facts["build-npm-install-stderr.txt"]["content_head"] == ""
    assert "added 2 packages" in facts[
        "build-npm-install-stdout.txt"]["content_head"]


# ------------------------------------------------------------------ #
# (W2-T25) حقائق الأدلة — معايير Directory
# ------------------------------------------------------------------ #

def test_directory_facts_reach_verifier(tmp_path):
    """«Directory node_modules/ exists and contains @astrojs/ directory»
    و«Directory src/pages/ exists» تتحقق من حقائق ميكانيكية — قياس حي
    الخطوة 230: الأدلة موجودة فعلًا (node_modules/@astrojs + src/pages)
    والمراجع أعمى عن الأدلة فحكم بالغياب مرتين وركود."""
    root = tmp_path / "step230"
    (root / "node_modules" / "@astrojs" / "compiler").mkdir(parents=True)
    (root / "src" / "pages").mkdir(parents=True)
    pkg = root / "package.json"
    pkg.write_text('{"dependencies": {"astro": "^4.16.0"}}',
                   encoding="utf-8")
    cfg = root / "astro.config.mjs"
    cfg.write_text("export default {}", encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=[
            'File package.json exists and contains "astro" in dependencies',
            "Directory node_modules/ exists and contains @astrojs/ directory",
            "Directory src/pages/ exists",
        ],
        artifacts=[str(pkg), str(cfg)],
        evidence_refs=[],
    ))
    import json
    payload = json.loads(router.payloads[0])
    dirs = payload["facts"]["directories"]
    assert dirs["node_modules"] is True
    assert dirs["node_modules/@astrojs"] is True
    assert dirs["src/pages"] is True


def test_directory_facts_false_when_missing(tmp_path):
    """الدليل الغائب يظهر false — لا اختلاق وجود."""
    root = tmp_path / "empty_step"
    root.mkdir()
    pkg = root / "package.json"
    pkg.write_text("{}", encoding="utf-8")
    router = _StubRouter({"verdict": "not_evidenced",
                          "checks_performed": [], "missing_evidence": ["x"],
                          "confidence": 0.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=["Directory src/pages/ exists"],
        artifacts=[str(pkg)],
        evidence_refs=[],
    ))
    import json
    payload = json.loads(router.payloads[0])
    assert payload["facts"]["directories"]["src/pages"] is False


# ------------------------------------------------------------------ #
# (W2-T25) ملخص JSON البنيوي — معايير الطول والعدادات
# ------------------------------------------------------------------ #

def test_json_summary_reaches_verifier(tmp_path):
    """«Array length is 7» و«Categories World (3), Tech (2), Local (2)»
    تتحقق من ملخص بنيوي ميكانيكي — قياس حي الخطوة 257: الملف مثالي
    تمامًا والمقتطف وحده (1800 حرف من ~10KB) أعجز المراجع عن العد
    فحكم بالنقص (ESCALATED_TO_HUMAN بعد دورة 10/10 أدوات ناجحة)."""
    import json as _json
    arts = []
    cats = ["World"] * 3 + ["Tech"] * 2 + ["Local"] * 2
    for i, cat in enumerate(cats):
        arts.append({"slug": f"article-{i}-mock", "title": f"A{i}",
                     "category": cat, "excerpt": "x" * 900,
                     "body": "<p>" + "y" * 900 + "</p>",
                     "date": "2024-11-20T09:15:00Z",
                     "image": "/img/a.png"})
    root = tmp_path / "step257"
    root.mkdir()
    pkg = root / "data"
    pkg.mkdir()
    arts_file = pkg / "articles.json"
    arts_file.write_text(_json.dumps(arts, ensure_ascii=False),
                         encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=[
            "File `data/articles.json` exists and is valid JSON.",
            "Array length is 7.",
            "Categories used: World (3), Tech (2), Local (2).",
        ],
        artifacts=[str(arts_file)],
        evidence_refs=[],
    ))
    payload = _json.loads(router.payloads[0])
    summary = payload["facts"]["files"]["articles.json"]["json_summary"]
    assert summary["type"] == "array"
    assert summary["length"] == 7
    assert summary["string_value_counts"]["category"] == \
        {"World": 3, "Tech": 2, "Local": 2}
    assert "slug" in summary["item_keys"]


def test_json_summary_invalid_json_absent(tmp_path):
    """JSON تالف — لا ملخص مختلق؛ الوجود والاسم يبقيان."""
    root = tmp_path / "bad"
    root.mkdir()
    bad = root / "broken.json"
    bad.write_text("{not valid json", encoding="utf-8")
    router = _StubRouter({"verdict": "not_evidenced",
                          "checks_performed": [], "missing_evidence": ["x"],
                          "confidence": 0.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=["File broken.json is valid JSON"],
        artifacts=[str(bad)],
        evidence_refs=[],
    ))
    import json as _json
    payload = _json.loads(router.payloads[0])
    entry = payload["facts"]["files"]["broken.json"]
    assert "json_summary" not in entry
    assert entry["exists"] is True


def test_content_tail_reaches_verifier(tmp_path):
    """«Media query @media (max-width: 600px)» في نهاية ملف كبير —
    الرأس المبتور لا يراها والذيل يصل (قياس حي الخطوة 271)."""
    css_body = "/* reset */\n* { box-sizing: border-box; margin: 0; }\n"
    css_body += ".filler { color: #333; }\n" * 90  # >1800 chars
    css_body += "@media (max-width: 600px) {\n  nav { flex-direction: column; }\n}\n"
    root = tmp_path / "step271"
    (root / "public" / "css").mkdir(parents=True)
    css = root / "public" / "css" / "style.css"
    css.write_text(css_body, encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=[
            "File `public/css/style.css` exists.",
            "Media query @media (max-width: 600px) present.",
        ],
        artifacts=[str(css)],
        evidence_refs=[],
    ))
    import json
    payload = json.loads(router.payloads[0])
    facts = payload["facts"]["files"]["style.css"]
    assert "@media (max-width: 600px)" in facts["content_tail"]
    assert "@media" not in facts["content_head"]


def test_token_counts_reach_verifier(tmp_path):
    """«شبكة مقالات (article.card) لكل مقال» و«رابط لarticle.html?id=» —
    عدّ ميكانيكي للرموز البنيوية في الملف (قياس حي الخطوة 300:
    index.html كامل أكبر من النوافذ والمراجع لا يعد البطاقات)."""
    root = tmp_path / "step300"
    (root / "project").mkdir(parents=True)
    html = root / "project" / "index.html"
    html.write_text(
        '<section class="hero"><article class="featured">A</article></section>'
        '<section class="latest">'
        + '<article class="card"><a href="article.html?id=2">x</a></article>' * 4
        + "</section>",
        encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=[
            "يوجد section.hero به article.featured واحد",
            "يوجد section.latest به شبكة مقالات (article.card) لكل مقال غير بارز",
            "كل card يحتوي رابط لarticle.html?id=...",
        ],
        artifacts=[str(html)],
        evidence_refs=[],
    ))
    import json
    payload = json.loads(router.payloads[0])
    counts = payload["facts"]["token_counts"]["index.html"]
    assert counts["section.hero"] == 1
    assert counts["article.featured"] == 1
    assert counts["article.card"] == 4
    assert counts["article.html?id="] == 4


def test_token_counts_absent_when_no_tokens(tmp_path):
    """معايير بلا رموز بنيوية — لا حقل token_counts مختلق."""
    root = tmp_path / "plain"
    root.mkdir()
    f = root / "notes.txt"
    f.write_text("hello world", encoding="utf-8")
    router = _StubRouter({"verdict": "evidenced",
                          "checks_performed": [], "missing_evidence": [],
                          "confidence": 1.0})
    role = VerifierLive(router)
    role.run(VerifierRequest(
        task_acceptance_criteria=["File notes.txt exists"],
        artifacts=[str(f)],
        evidence_refs=[],
    ))
    import json
    payload = json.loads(router.payloads[0])
    assert "token_counts" not in payload["facts"]
