"""محلل الأوامر التنفيذية — §1 من الأمر الرابع المعدل.

القاعدة الحاكمة: **المحلل لا يستنتج**. ما ليس مكتوبًا في الأمر لا يدخل
الـ spec إطلاقًا. كل استخراج مربوط بعلامة صريحة في النص:

- الأقسام: أسطر ``### §N — عنوان`` (أو ``## §N``) حتى القسم التالي.
- عقد التنفيذ (§0): ``المستودع:`` / ``الفرع:`` / ``الوضع:``.
- الوضع: READ_ONLY | WRITE_LOCAL | WRITE_AND_PUSH — صراحة فقط؛
  إن لم يُذكر = READ_ONLY (قرار الأمر الرابع §1، لا افتراض خفي).
- المنح المطلوبة: بند يبدأ بـ ``المنح المطلوبة:`` وتتبعه بنود
  ``- TYPE نطاق على هدف`` حيث TYPE ∈ {REPO_GRANT, PATH_GRANT, NET_GRANT}.
- شروط التوقف: كل بند مرقم يحتوي ``HARD STOP``.
- قرارات المالك: بنود ``DN:`` (D1..D9) — تُجمع من كل الأمر بالترتيب.
- القالب: القسم الذي يحمل ``القالب`` في عنوانه — حقوله من كتلة
  الشيفرة (سطر يبدأ باسم حقل ثم ``:``).
- سياسة الدفع: ``الدفع: لكل commit`` أو ``الدفع: دفعة واحدة``.
- القائمة البيضاء للأوامر: بند ``الأوامر المسموحة:`` وبنوده.
- أوامر القسم: بنود تتبع سطر ``الأوامر:`` داخل القسم (shlex).

الإخفاق في أي استخراج جوهري (لا أقسام / لا عقد) = رفض صريح
بسبب مقروء — المحلل لا يخمّن أبدًا.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum


class ExecutionMode(str, Enum):
    """أوضاع التنفيذ الثلاثة — تُستخرج صراحة من الأمر."""

    READ_ONLY = "READ_ONLY"
    WRITE_LOCAL = "WRITE_LOCAL"
    WRITE_AND_PUSH = "WRITE_AND_PUSH"


class GrantKind(str, Enum):
    """أنواع المنح الثلاثة (§2 من الأمر)."""

    REPO_GRANT = "REPO_GRANT"
    PATH_GRANT = "PATH_GRANT"
    NET_GRANT = "NET_GRANT"


#: نطاق المنحة كما يُكتب في الأمر (عربية أو إنجليزية).
_SCOPES = {
    "قراءة": "read",
    "كتابة": "read_write",
    "قراءة وكتابة": "read_write",
    "read": "read",
    "read_write": "read_write",
    "write": "read_write",
}

_SECTION_RE = re.compile(r"^#{2,3}\s*§\s*(\d+)\s*[—–-]\s*(.+?)\s*$")
_REPO_RE = re.compile(r"([\w.-]+/[\w.-]+)")
#: حقل قالب بربط قسم صريح: ``FIELD (§N): ...`` — الربط من الأمر لا من التخمين.
#: اسم الحقل: أحرف كبيرة وأرقام وشرطة سفلية ومسافة وشرطة (ZERO-WRITE PROOF).
_FIELD_RE = re.compile(
    r"^([A-Z][A-Z0-9_ \-]+?)\s*(?:\(\s*§\s*(\d+)\s*\))?\s*:\s*(.*)$"
)
#: رمز أمر يصلح للقائمة البيضاء: ASCII فقط (python، git، pytest...).
_COMMAND_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_.\-/]+$")
#: أول حرف عربي — ما بعده شرح لا أوامر.
_FIRST_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_NUMBERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_GRANT_ITEM_RE = re.compile(
    r"-\s*(REPO_GRANT|PATH_GRANT|NET_GRANT)\s+(قراءة وكتابة|read_write|قراءة|كتابة|read|write)?\s*(?:على|on)?\s*(\S+)(.*)$"
)
_NET_TARGET_RE = re.compile(r"^([\w.-]+):(\d+)$")
_DECISION_RE = re.compile(r"^(D\d+)\s*[:：]\s*(.+)$")
_BRANCH_RE = re.compile(r"الفرع\s*[:：]\s*([^\s—]+)")
_MODE_RE = re.compile(
    r"الوضع\s*[:：]\s*(READ_ONLY|WRITE_LOCAL|WRITE_AND_PUSH)", re.IGNORECASE
)


@dataclass(frozen=True)
class AccessRequest:
    """طلب منح كما ورد حرفيًا في الأمر — قبل التوقيع والاعتماد."""

    kind: GrantKind
    scope: str  # read | read_write (NET_GRANT: دائمًا read)
    target: str  # owner/repo | مسار مطلق | host:port
    branch: str = ""  # REPO_GRANT فقط
    method: str = ""  # REPO_GRANT: clone | worktree

    def describe(self) -> str:
        return f"{self.kind.value} {self.scope} على {self.target}"


@dataclass(frozen=True)
class SectionSpec:
    """قسم واحد من الأمر — بنيته كما كُتبت، لا كما فُهمت."""

    number: int
    title: str
    body: str
    requirements: tuple[str, ...] = ()
    hard_stops: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    is_report_template: bool = False
    decision_ids: tuple[str, ...] = ()
    landing_paths: tuple[str, ...] = ()  # مسارات هبوط الملفات الكاتبة — مصرّح بها
    landing_paths: tuple[str, ...] = ()  # مسارات هبوط الملفات الكاتبة — مصرّح بها

    @property
    def declared_access(self) -> tuple[str, ...]:
        """ما أعلنه القسم أنه سيصل إليه (بند «الوصول:»)."""
        declared: list[str] = []
        for line in self.body.splitlines():
            if line.strip().startswith("الوصول:") or line.strip().startswith("- "):
                token = line.strip().lstrip("- ").strip()
                if token.startswith("/"):
                    declared.append(token)
        return tuple(declared)


@dataclass
class OrderSpec:
    """المواصفة الكاملة المستخرجة من نص الأمر — حرفيًا."""

    raw: str
    repository: str = ""
    branch: str = ""
    execution_mode: ExecutionMode = ExecutionMode.READ_ONLY
    objective: str = ""
    access_requests: list[AccessRequest] = field(default_factory=list)
    sections: list[SectionSpec] = field(default_factory=list)
    hard_stop_conditions: list[str] = field(default_factory=list)
    owner_decisions: list[tuple[str, str]] = field(default_factory=list)
    #: حقول القالب بالترتيب الحرفي: (اسم الحقل، رقم القسم المصدر أو 0 للمحرك).
    report_template: list[tuple[str, int]] = field(default_factory=list)
    command_whitelist: list[str] = field(default_factory=list)
    push_policy: str = ""  # per_commit | batch | ""

    def section(self, number: int) -> SectionSpec | None:
        for section in self.sections:
            if section.number == number:
                return section
        return None

    def decision_section(self) -> SectionSpec | None:
        for section in self.sections:
            if section.decision_ids:
                return section
        return None


@dataclass(frozen=True)
class ParseResult:
    """نتيجة التحليل — فاشلة دائمًا بسبب مقروء، لا استثناء."""

    ok: bool
    spec: OrderSpec | None = None
    reason: str = ""


def _parse_grant_item(text: str) -> AccessRequest | None:
    match = _GRANT_ITEM_RE.match(text.strip())
    if not match:
        return None
    kind = GrantKind(match.group(1))
    scope = _SCOPES.get(match.group(2) or "", "read")
    target = match.group(3)
    extra = (match.group(4) or "").strip()
    branch = ""
    method = ""
    if kind is GrantKind.REPO_GRANT:
        repo = _REPO_RE.search(target)
        if repo:
            target = repo.group(1)
        branch_match = re.search(r"فرع\s*[:=]?\s*([^\s،]+)", extra)
        if branch_match:
            branch = branch_match.group(1)
        method_match = re.search(r"(clone|worktree)", extra)
        if method_match:
            method = method_match.group(1)
    if kind is GrantKind.NET_GRANT and not _NET_TARGET_RE.match(target):
        return None
    if kind is GrantKind.PATH_GRANT and not target.startswith("/"):
        return None
    return AccessRequest(
        kind=kind, scope=scope, target=target, branch=branch, method=method
    )


def _split_sections(text: str) -> list[tuple[int, str, list[str]]]:
    """تقسيم النص إلى أقسام (رقم، عنوان، أسطر الجسم)."""
    sections: list[tuple[int, str, list[str]]] = []
    current: tuple[int, str, list[str]] | None = None
    for line in text.splitlines():
        match = _SECTION_RE.match(line)
        if match:
            if current is not None:
                sections.append(current)
            current = (int(match.group(1)), match.group(2).strip(), [])
        elif current is not None:
            current[2].append(line)
    if current is not None:
        sections.append(current)
    return sections


def _extract_commands(body_lines: list[str]) -> tuple[tuple[str, ...], ...]:
    """بنود الأوامر: تتبع سطر «الأوامر:» حتى بند غير بند أو سطر فارغ مضاعف."""
    commands: list[tuple[str, ...]] = []
    in_commands = False
    for line in body_lines:
        stripped = line.strip()
        if stripped.startswith("الأوامر:") or stripped.startswith("الأوامر المعلنة:"):
            in_commands = True
            continue
        if in_commands:
            if stripped.startswith("- "):
                try:
                    commands.append(tuple(shlex.split(stripped[2:])))
                except ValueError:
                    continue  # أمر مشوه التشكيل — يُتجاهل ولا يُخمَّن
            elif stripped == "":
                continue
            else:
                in_commands = False
    return tuple(commands)


def _extract_landing_paths(body_lines: list[str]) -> tuple[str, ...]:
    """مسارات الهبوط المصرّح بها: بنود تتبع سطر «الهبوط:» — مطلقة فقط."""
    paths: list[str] = []
    active = False
    for line in body_lines:
        stripped = line.strip()
        if stripped.startswith("الهبوط:"):
            active = True
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("/"):
                paths.append(inline)
            continue
        if active:
            if stripped.startswith("- ") and stripped[2:].strip().startswith("/"):
                paths.append(stripped[2:].strip())
            elif stripped == "":
                continue
            else:
                active = False
    return tuple(paths)


def _parse_report_fields(body_lines: list[str]) -> list[tuple[str, int]]:
    """حقول القالب بالترتيب: (اسم الحقل، قسم المصدر أو 0 للمحرك).

    الربط صريح من الأمر: ``MAP (§1): ...`` — لا ربط موضعي ولا تخمين.
    """
    fields: list[tuple[str, int]] = []
    in_block = False
    for line in body_lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            continue
        match = _FIELD_RE.match(stripped)
        if match:
            source = int(match.group(2)) if match.group(2) else 0
            fields.append((match.group(1).strip(), source))
    return fields


def parse_order(text: str) -> ParseResult:
    """تحليل أمر تنفيذي إلى OrderSpec — بلا استنتاج، فاشل صراحة."""
    if not isinstance(text, str) or not text.strip():
        return ParseResult(ok=False, reason="نص الأمر فارغ")
    raw_sections = _split_sections(text)
    if not raw_sections:
        return ParseResult(ok=False, reason="لا أقسام § مرقمة في الأمر")

    spec = OrderSpec(raw=text)
    for number, title, body_lines in raw_sections:
        body = "\n".join(body_lines)
        hard_stops: list[str] = []
        requirements: list[str] = []
        decision_ids: list[str] = []
        for line in body_lines:
            stripped = line.strip()
            num_match = _NUMBERED_RE.match(stripped)
            item = num_match.group(2) if num_match else stripped.lstrip("- ")
            if "HARD STOP" in item:
                hard_stops.append(item)
            elif num_match:
                requirements.append(item)
            decision = _DECISION_RE.match(stripped.lstrip("- "))
            if decision:
                decision_ids.append(decision.group(1))
                spec.owner_decisions.append(
                    (decision.group(1), decision.group(2).strip())
                )
        is_template = "القالب" in title
        commands = () if is_template else _extract_commands(body_lines)
        if is_template:
            spec.report_template = _parse_report_fields(body_lines)
        spec.sections.append(
            SectionSpec(
                number=number,
                title=title,
                body=body,
                requirements=tuple(requirements),
                hard_stops=tuple(hard_stops),
                commands=commands,
                is_report_template=is_template,
                decision_ids=tuple(decision_ids),
                landing_paths=_extract_landing_paths(body_lines),
            )
        )
        spec.hard_stop_conditions.extend(hard_stops)

    contract = spec.sections[0] if spec.sections else None
    if contract is None or contract.number != 0:
        return ParseResult(ok=False, reason="القسم §0 (عقد التنفيذ) مفقود")

    for line in contract.body.splitlines():
        stripped = line.strip()
        if "المستودع" in stripped and ":" in stripped:
            repo = _REPO_RE.search(stripped)
            if repo:
                spec.repository = repo.group(1)
        branch = _BRANCH_RE.search(stripped)
        if branch:
            spec.branch = branch.group(1)
        mode = _MODE_RE.search(stripped)
        if mode:
            spec.execution_mode = ExecutionMode(mode.group(1).upper())
        if stripped.startswith("الهدف") and ":" in stripped:
            spec.objective = stripped.split(":", 1)[1].strip()
        if stripped.startswith("المنح المطلوبة"):
            continue
        if stripped.startswith("الدفع:"):
            spec.push_policy = (
                "per_commit" if "لكل" in stripped else "batch"
            )

    grants_active = False
    whitelist_active = False
    for line in text.splitlines():
        stripped = line.strip()
        # البند المرقم «3. المنح المطلوبة:» — البادئة الرقمية لا تمنع الالتقاط
        if "المنح المطلوبة" in stripped and not stripped.startswith("-"):
            grants_active = True
            continue
        if grants_active:
            if stripped.startswith("-"):
                request = _parse_grant_item(stripped)
                if request is not None:
                    spec.access_requests.append(request)
            else:
                grants_active = False
        if "الأوامر المسموحة" in stripped and not stripped.startswith("-"):
            whitelist_active = True
            inline = stripped.split(":", 1)[1] if ":" in stripped else ""
            # القائمة قبل أول كلمة عربية — الشرح العربي بعدها ليس أوامر
            cut = _FIRST_ARABIC_RE.search(inline)
            head = inline[: cut.start()] if cut else inline
            if head:
                spec.command_whitelist.extend(
                    token.strip("`،, ") for token in head.split()
                    if token.strip("`،, ") and _COMMAND_TOKEN_RE.match(token.strip("`،, "))
                )
            continue
        if whitelist_active:
            if stripped.startswith("- ") or stripped.startswith("•"):
                candidate = stripped.lstrip("-• ").strip()
                if candidate and _COMMAND_TOKEN_RE.match(candidate):
                    spec.command_whitelist.append(candidate)
            elif stripped == "":
                continue
            else:
                whitelist_active = False

    if not spec.repository:
        return ParseResult(ok=False, reason="المستودع غير مذكور في §0")
    if not spec.report_template:
        return ParseResult(ok=False, reason="قالب التقرير (§ بقسم «القالب») مفقود")
    return ParseResult(ok=True, spec=spec)
