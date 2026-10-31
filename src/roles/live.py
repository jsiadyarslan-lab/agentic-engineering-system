"""الأدوار الحية (الأمر السادس §2) — كل دور يستدعي نموذجًا حقيقيًا.

لا mock في أي دور: كل دور يبني رسائله من برومبت prompts/<role>.md
ثم يستدعي ModelRouter.chat_live() (نقل urllib حقيقي)، يتحقق من
استجابته ضد عقد pydantic الصارم (CONTRACTS.md)، يعيد المحاولة مرة
واحدة عند فشل التحقق، ثم يفشل الدور صراحةً (RoleSystemFault) —
الفشل الصريح أفضل من رد وهمي.

الأدوار mock السابقة (roles/*.py) تبقى كما هي: اختبارات الأمر
الثاني تعتمدها، والدورة الافتراضية للخادم تبقى mock حتى يجهز
المستخدم مفتاحه — مهمة الأمر السادس وحدها تبني الأدوار الحية.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from roles.arbiter import ArbiterRequest, ArbiterResult
from roles.reviewer import ReviewerRequest, ReviewerResult
from roles.thinker import Plan, ThinkerRequest, ThinkerResult
from roles.verifier import VerifierRequest, VerifierResult
from router.model_router import ChatMessage, ModelRouter
from router.role_config import RoleSelection

#: جذر البرومبتات — نسبيًا لمستودع src/ (prompts/ في جذر المستودع).
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class RoleSystemFault(RuntimeError):
    """فشل دور حي بعد إعادة المحاولة الواحدة — يُسجَّل system_fault."""

    def __init__(self, role: str, reason: str):
        self.role = role
        self.reason = reason
        super().__init__(f"system_fault [{role}]: {reason}")


def load_prompt(name: str) -> str:
    """قراءة برومبت الدور — برومبت مفقود = فشل صريح لا صمت."""
    path = PROMPTS_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise RoleSystemFault(name, f"البرومبت مفقود: {path} ({error})") from error


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

#: (W2-T25) رمز بنيوي ASCII في نص المعايير — tag.class أو file.ext?query.
#: الحروف العربية (لام الجر مثلًا «لarticle.html») تُقلم تلقائيًا.
_ASCII_TOKEN = re.compile(
    r"[A-Za-z][\w-]*\.[A-Za-z][\w-]*(?:\?[A-Za-z]\w*=?)?"
)
#: امتدادات ملفات معروفة — tag.ext بامتداد ملف يُعدّ حرفيًا لا كمحدد CSS.
_FILE_EXT_TOKEN = frozenset({
    "html", "css", "js", "ts", "json", "md", "mjs", "cjs", "tsx", "jsx",
    "svg", "jpg", "png", "webp", "gif", "ico", "txt", "csv", "xml",
    "yaml", "yml", "toml", "py", "astro", "env", "log", "pdf",
})


def _count_token(text: str, token: str) -> int:
    """عدّ الرمز في النص: محدد CSS (tag.class) يُعد بصيغة السمة
    الحقيقية <tag class="class"> إضافة للصيغة النصية؛ والبقية حرفيًا."""
    parts = token.split(".")
    if (len(parts) == 2 and "?" not in token
            and parts[1].lower() not in _FILE_EXT_TOKEN):
        tag, cls = parts
        attr = re.compile(
            r"<%s\b[^>]*\bclass\s*=\s*[\"'][^\"']*\b%s\b[\"']" % (
                re.escape(tag), re.escape(cls)))
        return len(attr.findall(text)) + text.count(token)
    return text.count(token)


def extract_json(text: str) -> dict:
    """استخراج أول كائن JSON من رد النموذج — يتحمل أي لفّ نصي حوله."""
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError("لا كائن JSON في الرد")
    return json.loads(match.group(0))


class LiveRoleBase:
    """القاعدة المشتركة: برومبت ← chat_live ← تحقق ← إعادة واحدة ← فشل.

    selection (الأمر 006 §3+§4): اختيار الدور المستقل — المزود
    والنموذج المخصصان له حصرًا؛ غيابه = افتراضات الموجّه المعلنة.
    """

    #: اسم البرومبت (prompts/<name>.md) — يضبطه كل دور.
    PROMPT_NAME = ""
    #: اسم الدور في الأحداث والتشخيص.
    ROLE = ""

    def __init__(self, router: ModelRouter, selection: RoleSelection | None = None):
        self._router = router
        self._selection = selection
        self._system_prompt = load_prompt(self.PROMPT_NAME)

    def _live_call(self, messages: list[ChatMessage]) -> dict:
        """استدعاء حي واحد باختيار الدور — لا افتراض صامت لمزود آخر.

        transport_key (007.1 §10): اختيار الدور قد يحدد تكوينًا بعينه
        داخل المزود — «مزود::تكوين» — فيصل الاستدعاء إلى Base URL
        المختار حصرًا، لا إلى التكوين الأساسي.
        """
        if self._selection is None:
            return self._router.chat_live(messages)
        return self._router.chat_live(
            messages,
            provider_id=self._selection.transport_key(),
            model=self._selection.model,
        )

    # ------------------------------------------------------------------ #
    # الاستدعاء + التحقق + إعادة المحاولة الواحدة (§2.3)
    # ------------------------------------------------------------------ #

    def _validated_completion(self, payload: dict, result_model: type[BaseModel]) -> BaseModel:
        """استدعاء حي واحد مع تحقق العقد — إعادة واحدة ثم فشل الدور."""
        messages = [
            ChatMessage(role="system", content=self._system_prompt),
            ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]
        last_error: Exception | None = None
        for attempt in (1, 2):
            outcome = self._live_call(messages)
            text = outcome["text"]
            try:
                data = extract_json(text)
                return result_model.model_validate(data)
            except (ValueError, ValidationError) as error:
                last_error = error
                # إعادة المحاولة بتغذية راجعة: الخطأ نفسه يرى النموذج
                messages = messages + [
                    ChatMessage(role="assistant", content=text[:2000]),
                    ChatMessage(
                        role="user",
                        content=(
                            f"ردك غير صالح ضد العقد ({error}). أعد الإخراج "
                            "JSON صالحًا بالصيغة الحرفية المطلوبة فقط — لا نص إضافي."
                        ),
                    ),
                ]
        raise RoleSystemFault(
            self.ROLE,
            f"فشل تحقق JSON بعد إعادة واحدة — آخر خطأ: {last_error}",
        )


class ThinkerLive(LiveRoleBase):
    """المفكر الحي — الهدف ← خطة بعقد ThinkerResult نفسه.

    البرومبت يطلب حقول الخطة مباشرة (tasks/risks/…) — الدور يتحقق
    منها كعقد Plan ثم يغلّفها في ThinkerResult (تكييف العقد، لا
    تمييعه: نفس حقول pydantic الصارمة).
    """

    PROMPT_NAME = "thinker"
    ROLE = "thinker"

    def run(self, request: ThinkerRequest) -> ThinkerResult:
        payload = {
            "goal": request.goal,
            "context": request.context,
            "previous_reviews": request.previous_reviews,
        }
        plan = self._validated_completion(payload, Plan)
        return ThinkerResult(plan=plan)


class ReviewerLive(LiveRoleBase):
    """المدقق الحي — الخطة ← approved/revise بعقد ReviewerResult."""

    PROMPT_NAME = "reviewer"
    ROLE = "reviewer"

    def run(self, request: ReviewerRequest) -> ReviewerResult:
        payload = {
            "plan": request.plan.model_dump(),
            "previous_gaps": request.previous_gaps,
        }
        return self._validated_completion(payload, ReviewerResult)


class VerifierLive(LiveRoleBase):
    """المراجع الحي — يبني الحقائق الميكانيكية بنفسه ثم يحكم عليها.

    الحقائق (وجود الملفات، صفحات PDF، عدد المصادر، sha256) تُجمع
    ميكانيكيًا هنا وتُمرَّر للنموذج — حكمه يُبنى على أرقام مثبتة
    لا على نص يدّعي (الصدق قبل الراحة).

    (W2-T25 2026-10-28) مقتطف المحتوى: معايير المفكر كثيرًا ما تفحص
    **مضمون** الملف («package.json content showing name: news-site»)
    بينما الحقائق كانت وجودًا وبصمة فقط — فالملف الصحيح موجود على
    القرص والمراجع لا يراه: يعيد not_evidenced بصدق والمحكَّم ينهي
    الدورة «ركودًا» بخطوة نُفِّذت صحيحة. الحق الأصدق: مقتطف حقيقي
    محدود من محتوى الملفات النصية الصغيرة (content_head) — المضمون
    المثبت نفسه، لا حكم مُعد سلفًا.
    """

    PROMPT_NAME = "verifier"
    ROLE = "verifier"

    #: (W2-T25) معايير الأدلة: «Directory src/pages/ exists» و
    #: «contains @astrojs/ directory» — وجود الأدلة حقيقة ميكانيكية.
    _DIR_CRITERION = re.compile(
        r"Directory\s+([\w@.-]+(?:/[\w@.-]+)*)/?(?=\s+(?:exists|and)\b)",
        re.IGNORECASE,
    )
    #: (W2-T25 قياس 555) صيغ الدليل المعكوسة والعربية — «.next directory
    #: exists» و«دليل .next موجود» لم تُطابق فغابت facts.directories.
    _DIR_REVERSED = re.compile(
        r"([\w@./-]+)/?\s+directory\s+exists", re.IGNORECASE)
    _DIR_ARABIC = re.compile(
        r"دليل\s+`?([\w@./-]+)`?\s+موجود", re.IGNORECASE)
    _DIR_CONTAINS = re.compile(
        r"contains\s+([\w@.-]+(?:/[\w@.-]+)*)/?\s+directory",
        re.IGNORECASE,
    )
    #: (W2-T25) رموز بنيوية في المعايير (section.hero، article.card،
    #: article.html?id=) — عدّها في الملفات دليل ميكانيكي مباشر.
    _CRIT_TOKEN = re.compile(
        r"`([^`\n]{2,60})`|(\b[\w-]+\.[\w-]+(?:\?\w+=)?\b)"
    )
    #: (W2-T25) خصائص CSS المخصصة «--color-primary» — تُعد ميكانيكيًا
    #: (قياس 445: معايير التوكنز تطلب عشرات المتغيرات بالاسم).
    _CSS_VAR = re.compile(r"--[a-zA-Z][\w-]*")
    #: (W2-T25 728) حرفيات grep بالمعايير — «grep -o '{' | wc -l».
    _GREP_LITERAL = re.compile(r"grep\s+(?:-[A-Za-z]+\s+)?'([^']+)'")

    #: فحوص ميكانيكية إضافية تُدمج في facts إن توفرت الدالة الخارجية.
    facts_builder: Any = None

    #: امتدادات نصية يُقتطف محتواها — البقية (ثنائي/PDF/صور) بوجودها فقط.
    _TEXT_EXTS: frozenset[str] = frozenset({
        ".json", ".md", ".txt", ".log", ".csv", ".xml", ".yaml", ".yml",
        ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".html",
        ".astro", ".toml", ".py", ".mdx", ".sh", ".env", ".cfg",
    })
    #: سقف المقتطف وحد حجم الملف المقروء — أمان إحداثي معلن.
    _CONTENT_HEAD_LIMIT = 1800
    #: (W2-T25) ذيل الملف — استعلامات الوسائط ونواتج البنية تعيش في
    #: النهاية والمقتطف الأولي يعميها (قياس 271: @media غائبة عن head).
    _CONTENT_TAIL_LIMIT = 600
    _CONTENT_FILE_LIMIT = 262_144

    def _content_tail(self, path: Path) -> str | None:
        """(W2-T25) آخر الملف النصي — تكملة الرأس للمعايير الختامية."""
        try:
            dotfile_text = path.name.startswith(".") and not path.suffix
            if (path.suffix.lower() not in self._TEXT_EXTS
                    and not dotfile_text):
                return None
            if path.stat().st_size > self._CONTENT_FILE_LIMIT:
                return None
            raw = path.read_bytes()[-self._CONTENT_TAIL_LIMIT:]
            text = raw.decode("utf-8", "replace").strip()
            return text if text or path.stat().st_size == 0 else None
        except OSError:
            return None

    def _json_summary(self, path: Path) -> dict | None:
        """(W2-T25) ملخص بنيوي ميكانيكي لملف JSON — الطول والمفاتيح
        وعدادات القيم النصية منخفضة التفرّد. المقتطف وحده لا يكفي
        لمعايير مثل «Array length is 7» أو «Categories World (3)»
        على ملف أكبر من نافذة الاقتطاع (قياس 257)."""
        if path.suffix.lower() != ".json" \
                or path.stat().st_size > self._CONTENT_FILE_LIMIT:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(data, list):
            out: dict[str, Any] = {"type": "array", "length": len(data)}
            dicts = [x for x in data if isinstance(x, dict)]
            if dicts:
                out["item_keys"] = sorted(
                    set().union(*(x.keys() for x in dicts)))
                if len(dicts) <= 50:
                    counts: dict[str, dict[str, int]] = {}
                    for key in out["item_keys"]:
                        strs = [x.get(key) for x in dicts
                                if isinstance(x.get(key), str)]
                        if strs and len(set(strs)) <= 10:
                            counts[key] = {v: strs.count(v) for v in set(strs)}
                    if counts:
                        out["string_value_counts"] = counts
            return out
        if isinstance(data, dict):
            return {"type": "object", "keys": sorted(data.keys())}
        return {"type": type(data).__name__}

    def _css_summary(self, path: Path) -> dict | None:
        """(W2-T25) ملخص قواعد CSS ميكانيكي من الملف كاملًا: المحددات
        كما هي وعددها واستعلامات الوسائط والخصائص المخصصة المعرَّفة.
        معايير «Link (a) base typography» و«Utility classes .container
        and .sr-only» تسكن وسط ملف أكبر من نافذة الرأس+الذيل (قياس
        445: styles.css ‏3254 حرفًا و30 قاعدة والنافذة 2400 فتصعيد
        زور رغم اكتمال الملف)."""
        if path.suffix.lower() != ".css" \
                or path.stat().st_size > self._CONTENT_FILE_LIMIT:
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        selectors: list[str] = []
        for chunk in text.split("{")[:-1]:
            for part in re.split(r"[};]", chunk)[-1].split(","):
                sel = " ".join(part.split())
                if sel and sel not in selectors:
                    selectors.append(sel[:80])
        props: list[str] = []
        for name in re.findall(r"(--[a-zA-Z][\w-]*)\s*:", text):
            if name not in props:
                props.append(name)
        # (W2-T25) خريطة الإعلانات: معايير القيم تسكن وسط الملف
        # («gap using spacing tokens»، «aspect-ratio 16:9» — قياس 465:
        # ملف 6574 حرفًا والنافذة 2400 والخاصيات موجودة فعلًا).
        decls: dict[str, int] = {}
        for block in re.findall(r"\{([^{}]*)\}", text):
            for dm in re.finditer(r"([a-zA-Z-]+)\s*:\s*[^;{}]+", block):
                name = dm.group(1).lower()
                decls[name] = decls.get(name, 0) + 1
        return {
            "rule_count": len(selectors),
            "selectors": selectors[:64],
            "media_queries": [s for s in selectors
                              if s.startswith("@media")][:12],
            "custom_property_count": len(props),
            "custom_properties": props[:40],
            "declaration_count": sum(decls.values()),
            "declarations": {
                k: decls[k] for k in sorted(decls)[:96]},
            "var_function_count": len(re.findall(r"var\(--", text)),
        }

    def _html_summary(self, path: Path) -> dict | None:
        """(W2-T25) ملخص عناصر HTML ميكانيكي من الملف كاملًا: عدّات
        الوسوم الدلالية وعدّات الأصناف — معايير «يعرض هيدرًا وهيرو و6
        بطاقات وفوترًا» تفحص ملفًا أكبر من نافذة الرأس فتُحسم بأعداد
        مثبتة (قياس 520: article-card ×6 في index.html والمراجع أعمى)."""
        if path.suffix.lower() not in (".html", ".htm") \
                or path.stat().st_size > self._CONTENT_FILE_LIMIT:
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        counts: dict[str, int] = {}
        for tag in ("header", "main", "footer", "nav", "section", "article",
                    "aside", "h1", "h2", "h3", "a", "img", "button", "form",
                    "ul", "li", "div", "span", "p", "script", "link"):
            hits = len(re.findall(rf"<{tag}[\s>]", text, re.IGNORECASE))
            if hits:
                counts[tag] = hits
        classes: dict[str, int] = {}
        for matched in re.finditer(r'class="([^"]+)"', text):
            for one in matched.group(1).split():
                classes[one] = classes.get(one, 0) + 1
        return {
            "element_count": sum(counts.values()),
            "elements": counts,
            "class_counts": {k: classes[k] for k in sorted(classes)[:48]},
        }

    def _content_head(self, path: Path) -> str | None:
        """مقتطف حقيقي محدود من ملف نصي صغير — أو None.

        (W2-T25) الملف النصي الفارغ يقتطف «» — فراغ المضمون دليل
        بذاته (سجل أمر بلا أخطاء) لا غياب فحص.
        """
        try:
            # (W2-T25) ملف نقطي بلا امتداد (.prettierrc/.gitignore) نصٌّ
            # بطبيعته — Path().suffix له فارغ فكان يُحجب مضمونه زورًا
            # والمعايير تفحصه («.prettierrc content showing semi: true»).
            dotfile_text = path.name.startswith(".") and not path.suffix
            if (path.suffix.lower() not in self._TEXT_EXTS
                    and not dotfile_text):
                return None
            if path.stat().st_size > self._CONTENT_FILE_LIMIT:
                return None
            raw = path.read_bytes()[: self._CONTENT_HEAD_LIMIT]
            text = raw.decode("utf-8", "replace").strip()
            return text if text or path.stat().st_size == 0 else None
        except OSError:
            return None

    def run(self, request: VerifierRequest) -> VerifierResult:
        facts: dict[str, Any] = {"files": {}}
        # (W2-T25) relpath: أصل مشترك للأدلة — معايير المسارات
        # («node_modules/.package-lock.json exists») تتحقق من المسار
        # النسبي لا من الاسم المجرد وحده (قياس 221: الملف موجود والاسم
        # المجرد .package-lock.json لم يُطابق عند المراجع).
        parents = [str(Path(r).parent) for r in request.artifacts]
        common = None
        if parents:
            try:
                common = __import__("os").path.commonpath(parents)
            except ValueError:
                common = None
        for reference in request.artifacts:
            path = Path(reference)
            entry: dict[str, Any] = {
                "exists": path.is_file(),
                # (W2-T25) قابلية الكتابة حقيقة ميكانيكية مقيسة — معيار
                # «Each file exists and is writable» كان يحكم النقص لأن
                # الحقائق بلا أي بيانات صلاحيات (قياس 726: الملفات
                # الخمسة موجودة على القرص والمراجع أعمى للكتابة فرفض
                # الدورة كاملة التنفيذ بصمت «no file permission data»).
                "writable": __import__("os").access(
                    path, __import__("os").W_OK),
                "sha256_head": (
                    __import__("hashlib")
                    .sha256(path.read_bytes())
                    .hexdigest()[:16]
                    if path.is_file() and path.stat().st_size < 20_000_000
                    else None
                ),
            }
            if common:
                try:
                    entry["relpath"] = str(path.relative_to(common))
                except ValueError:
                    entry["relpath"] = str(path)
            facts["files"][path.name] = entry
            head = self._content_head(path)
            if head is not None:
                facts["files"][path.name]["content_head"] = head
            tail = self._content_tail(path)
            if tail is not None and tail != head:
                facts["files"][path.name]["content_tail"] = tail
            if path.is_file():
                summary = self._json_summary(path)
                if summary is not None:
                    facts["files"][path.name]["json_summary"] = summary
                css = self._css_summary(path)
                if css is not None:
                    facts["files"][path.name]["css_summary"] = css
                html = self._html_summary(path)
                if html is not None:
                    facts["files"][path.name]["html_summary"] = html
        if self.facts_builder is not None:
            try:
                facts.update(self.facts_builder(request))
            except Exception:  # noqa: BLE001 — الحقائق الإضافية اختيارية
                pass
        # (W2-T25) حقائق الأدلة الميكانيكية: «Directory src/pages/
        # exists» و«contains @astrojs/ directory» — الوجود يُقاس من
        # الأصل المشترك للأدلة (قياس 230: node_modules/@astrojs وsrc/pages
        # موجودان فعلًا والمراجع أعمى عن الأدلة فحكم بالغياب).
        if common:
            base_root = Path(common)
            dirs: dict[str, bool] = {}
            for criterion in request.task_acceptance_criteria:
                text = str(criterion)
                for pattern in (self._DIR_CRITERION, self._DIR_REVERSED,
                                self._DIR_ARABIC):
                    for match in pattern.finditer(text):
                        name = match.group(1)
                        dirs[name] = (base_root / name).is_dir()
                    for sub in self._DIR_CONTAINS.finditer(text):
                        child = sub.group(1)
                        dirs[f"{name}/{child}"] = (
                            base_root / name / child).is_dir()
            if dirs:
                facts["directories"] = dirs
        # (W2-T25) عدّ الرموز البنيوية المذكورة في المعايير داخل الملفات
        # النصية: «article.card لكل مقال» تُحسم بأعداد ميكانيكية (قياس
        # 300: index.html كامل والمراجع لا يعد البطاقات) — محدد CSS
        # (tag.class) يُعد بصيغة <tag class="class"> الحقيقية + النصية.
        tokens: list[str] = []
        for criterion in request.task_acceptance_criteria:
            for backtick, _dotted in self._CRIT_TOKEN.findall(str(criterion)):
                for hit in _ASCII_TOKEN.finditer(backtick):
                    token = hit.group(0)
                    if token not in tokens:
                        tokens.append(token)
            for hit in _ASCII_TOKEN.finditer(str(criterion)):
                token = hit.group(0)
                if token not in tokens:
                    tokens.append(token)
            for var in self._CSS_VAR.findall(str(criterion)):
                if var not in tokens:  # (W2-T25) توكنز CSS بالاسم
                    tokens.append(var)
            for lit in self._GREP_LITERAL.findall(str(criterion)):
                if lit and lit not in tokens:  # (W2-T25 728) حرفيات grep
                    tokens.append(lit)
        if tokens:
            counts: dict[str, dict[str, int]] = {}
            for reference in request.artifacts:
                path = Path(reference)
                if not path.is_file() or path.stat().st_size > \
                        self._CONTENT_FILE_LIMIT:
                    continue
                if (path.suffix.lower() not in self._TEXT_EXTS
                        and not (path.name.startswith(".") and not path.suffix)):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                file_counts = {
                    t: _count_token(text, t) for t in tokens}
                if any(file_counts.values()):
                    counts[path.name] = file_counts
            if counts:
                facts["token_counts"] = counts
        payload = {
            "criteria": request.task_acceptance_criteria,
            "evidence_refs": request.evidence_refs[:40],
            "facts": facts,
        }
        return self._validated_completion(payload, VerifierResult)


class ArbiterLive(LiveRoleBase):
    """المُحكَّم الحي — حسم الخلافات بعقد ArbiterResult."""

    PROMPT_NAME = "arbiter"
    ROLE = "arbiter"

    def __init__(
        self,
        router: ModelRouter,
        max_retries: int = 2,
        selection: RoleSelection | None = None,
    ):
        super().__init__(router, selection=selection)
        self._max_retries = max_retries

    def run(self, request: ArbiterRequest) -> ArbiterResult:
        payload = {
            "conflict_type": request.conflict_type,
            "parties": request.parties,
            "evidences": request.evidences[:20],
            "history": request.history[:20],
            "max_retries_budget": self._max_retries,
            # سياق الفشل المنظم (إضافة 008 §14) — قرار حقيقي على السبب
            "failure_context": request.failure_context or None,
        }
        result = self._validated_completion(payload, ArbiterResult)
        # الميزانية المركزية ملك المحكَّم — لا يتجاوزها النموذج فوق السقف
        if result.max_retries_remaining > self._max_retries:
            result = result.model_copy(
                update={"max_retries_remaining": self._max_retries}
            )
        return result


#: إعادة تصدير العقود المطلوبة في التركيب — استيراد واحد للوحدة.
__all__ = [
    "ArbiterLive",
    "LiveRoleBase",
    "Plan",
    "ReviewerLive",
    "RoleSystemFault",
    "ThinkerLive",
    "VerifierLive",
    "load_prompt",
]
