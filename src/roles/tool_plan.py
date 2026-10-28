"""تحليل خطة أدوات المنفذ الحي (W2-T25) — نحيلة ومعزولة.

الدافع المقيس (الخطوة 138 التنفيذ 46 الجولة 2): النموذج يضيف أحيانًا
أسوار كود تحوط الرد كله، أو يعيد مصفوفة JSON بدل أسطر «أداة | وسيطة» —
فيفشل التحليل مرتين ويُعلن RoleSystemFault «لا أسطر استدعاء صالحة»
رغم أن الاستدعاءات نفسها قانونية تمامًا.

العقد: ثلاثة تنويعات صادقة بالترتيب — أسطر الأنابيب كما هي، ثم بعد
نزع الأسوار الخارجية، ثم مصفوفة JSON لاستدعاءات بالأدوات المعروفة
بوسيطاتها القانونية. كل تنويع يخدم العقد نفسه (أداة معروفة + وسيطة
قانونية) — لا تمرير أوسع ولا اختراق: أي شيء آخر يظل فشلًا صريحًا.
"""

from __future__ import annotations

import json
import re

#: مصفوفة JSON مرشحة — تُحاول بالترتيب حتى تنجح واحدة.
_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*?\]", re.MULTILINE)

#: (W2-T25) إعلان «لا استدعاءات» — النموذج يحسم أحيانًا أن المهمة
#: محلية بحتة (بناء/أوامر) فلا بحث ويب فيها، ويكتبها صراحةً. قَبول
#: الإعلان الصريح خطة فارغة قانونية: مهام البناء تتابع (create_files
#: + build_commands)، ومهام البحث تفشل بصدق لاحقًا عند فحص المادة
#: («لا مادة قابلة للتحليل») — لا تجاوز: التحقق يبقى الحكم.
_NO_CALLS_RE = re.compile(
    r"لا توجد استدعاءات|بلا استدعاءات أدوات|لا حاجة لاستدعاء"
    r"|no (?:external )?tool calls|no tools (?:are )?(?:needed|required)",
    re.IGNORECASE,
)


def strip_outer_fences(text: str) -> str:
    """إزالة أسوار كود تحوط الرد كله — لا الأسوار الداخلية."""
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped.strip()


def _parse_pipe_lines(
    text: str,
    *,
    line_tools: dict[str, str],
    kv_line_tools: dict[str, str],
    kv_allowed_keys: dict[str, set[str]],
    strip_arg_chars: str,
) -> list[dict]:
    calls: list[dict] = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip().lstrip("-*•0123456789. ").strip()
        if not line or "|" not in line:
            continue
        name, _, arg = line.partition("|")
        name = name.strip()
        arg = arg.strip().strip(strip_arg_chars)
        if not arg:
            raise ValueError(f"سطر أداة غير صالح: {raw_line[:80]}")
        if name in line_tools:
            calls.append({"tool": name, "args": {line_tools[name]: arg}})
        elif name in kv_line_tools:
            parts = arg.split()
            primary = parts[0]
            args = {kv_line_tools[name]: primary}
            for token in parts[1:]:
                if "=" not in token:
                    raise ValueError(
                        f"جزء بلا مفتاح=قيمة في سطر {name}: {token[:40]}"
                    )
                key, _, val = token.partition("=")
                if key not in kv_allowed_keys.get(name, set()):
                    raise ValueError(
                        f"مفتاح غير مسموح {key} لأداة {name} "
                        f"(المسموح: {sorted(kv_allowed_keys.get(name, set()))})"
                    )
                args[key] = val
            calls.append({"tool": name, "args": args})
        else:
            raise ValueError(f"سطر أداة غير صالح: {raw_line[:80]}")
    if not calls:
        raise ValueError("لا أسطر استدعاء صالحة في الرد")
    return calls


def _parse_json_calls(
    text: str,
    *,
    line_tools: dict[str, str],
) -> list[dict]:
    """تنويع JSON — أداة معروفة بوسيطتها القانونية حصرًا."""
    for match in _JSON_ARRAY_RE.finditer(text):
        try:
            items = json.loads(match.group(0))
        except (ValueError, TypeError):
            continue
        if not isinstance(items, list):
            continue
        calls: list[dict] = []
        ok = True
        for item in items:
            if not isinstance(item, dict):
                ok = False
                break
            name = str(item.get("tool", "")).strip()
            key = line_tools.get(name)
            if not key:
                ok = False
                break
            args = item.get("args")
            if isinstance(args, dict) and args.get(key):
                canonical = {key: str(args[key])}
            elif item.get(key):
                canonical = {key: str(item[key])}
            else:
                ok = False
                break
            calls.append({"tool": name, "args": canonical})
        if ok and calls:
            return calls
    raise ValueError("لا مصفوفة استدعاءات JSON صالحة في الرد")


def parse_tool_calls(
    text: str,
    *,
    line_tools: dict[str, str],
    kv_line_tools: dict[str, str],
    kv_allowed_keys: dict[str, set[str]],
    strip_arg_chars: str,
) -> list[dict]:
    """التحليل المتسامح الصادق — أربعة مقاربات قبل الفشل الصريح:
    أسطر الأنابيب، ثم بعد نزع الأسوار، ثم مصفوفة JSON، ثم إعلان
    «لا استدعاءات» الصريح (خطة فارغة قانونية)."""
    try:
        return _parse_pipe_lines(
            text, line_tools=line_tools, kv_line_tools=kv_line_tools,
            kv_allowed_keys=kv_allowed_keys,
            strip_arg_chars=strip_arg_chars,
        )
    except ValueError:
        pass
    fenced = strip_outer_fences(text)
    if fenced != text:
        try:
            return _parse_pipe_lines(
                fenced, line_tools=line_tools, kv_line_tools=kv_line_tools,
                kv_allowed_keys=kv_allowed_keys,
                strip_arg_chars=strip_arg_chars,
            )
        except ValueError:
            pass
    try:
        return _parse_json_calls(text, line_tools=line_tools)
    except ValueError:
        pass
    if _NO_CALLS_RE.search(text):
        return []
    raise ValueError("لا أسطر استدعاء صالحة في الرد ولا إعلان «لا استدعاءات»")


__all__ = ["parse_tool_calls", "strip_outer_fences"]
