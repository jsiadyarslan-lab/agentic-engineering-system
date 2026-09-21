"""استراتيجية التعافي من فشل الأدوات (إضافة 008 §8-§11 + 009 §18-§19).

لا إعادة عمياء (§9): كل قرار تعافٍ مبني على تصنيف الفشل —
- RETRYABLE (مهلة/شبكة/حد معدل) ← إعادة مباشرة بلا تغيير؛
- NEEDS_STRATEGY_CHANGE (لا نتائج/لا مادة) ← مراجعة الاستعلام أو
  أداة بديلة مسجَّلة فعلًا — إعادة نفس الاستعلام حرفيًا ممنوعة؛
- NOT_RETRYABLE (مصادقة/سياسة/صورة غائبة) ← تخطي أو فشل صريح.

الأدوات البديلة حقيقية من TOOL_WHITELIST حصرًا (§11: لا اختراع
أدوات غير موجودة ولا mock أبدًا).
"""

from __future__ import annotations

from dataclasses import dataclass

from roles.tool_failures import ToolFailure, revise_query

#: بدائل حقيقية مسجلة (§11): لكل أداة فاشلة بدائل من القائمة البيضاء.
TOOL_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "web_search": ("fetch_page", "http_get_text"),
    "fetch_page": ("http_get_text", "page_to_text"),
}

#: أنواع التعافي — قرار واحد لكل فشل.
RECOVERY_ACTIONS: tuple[str, ...] = (
    "RETRY_SAME",          # فشل عابر — إعادة كما هي
    "REVISE_QUERY",        # مراجعة الاستعلام ثم إعادة
    "ALTERNATIVE_TOOL",    # أداة بديلة مسجلة
    "SKIP_TOOL",           # تخطٍ — المادة تُجمع من غيرها
    "FAIL_MATERIAL",       # لا مسار متبقٍ — فشل المادة (لا فشل كاذب)
)


@dataclass
class RecoveryDecision:
    """قرار تعافٍ واحد — صادق ومعلل، يصل الواجهة حدثًا حيًا."""

    action: str                      # RECOVERY_ACTIONS
    reason: str                      # شرح عربي موجز
    tool: str = ""
    revised_query: str = ""          # لـ REVISE_QUERY
    alternative_tool: str = ""       # لـ ALTERNATIVE_TOOL
    alternative_args: dict | None = None


def plan_recovery(
    failure: ToolFailure,
    *,
    attempted_queries: list[str],
    available_urls: list[str],
) -> RecoveryDecision:
    """قرار التعافي لفشل واحد (§8) — بلا إعادة عمياء ولا اختراع أدوات."""
    if failure.retryable:
        return RecoveryDecision(
            action="RETRY_SAME",
            reason=(
                f"فشل عابر ({failure.reason}) — إعادة مباشرة دون تغيير"
            ),
            tool=failure.tool,
        )
    if failure.needs_strategy_change:
        # (1) مراجعة الاستعلام أولًا — إن أنتجت استعلامًا مختلفًا فعلًا
        query = str(failure.details.get("query") or "")
        revised = revise_query(query, attempted_queries) if query else None
        if revised:
            return RecoveryDecision(
                action="REVISE_QUERY",
                reason=(
                    "الاستعلام لم يُنتج مادة — إعادة باستراتيجية مختلفة "
                    f"(استعلام مراجَع: {revised[:80]})"
                ),
                tool=failure.tool,
                revised_query=revised,
            )
        # (2) أداة بديلة مسجلة — على مادة موجودة فعلًا (روابط نتائج سابقة)
        for alt in TOOL_ALTERNATIVES.get(failure.tool, ()):
            if alt == "fetch_page" and available_urls:
                return RecoveryDecision(
                    action="ALTERNATIVE_TOOL",
                    reason=(
                        "البحث لا ينتج مادة — جلب مباش لأحد الروابط "
                        "المعروفة عبر أداة بديلة مسجلة"
                    ),
                    tool=failure.tool,
                    alternative_tool=alt,
                    alternative_args={"url": available_urls[0]},
                )
            if alt in ("http_get_text", "page_to_text") and available_urls:
                return RecoveryDecision(
                    action="ALTERNATIVE_TOOL",
                    reason="جلب المادة الخام عبر أداة بديلة مسجلة",
                    tool=failure.tool,
                    alternative_tool=alt,
                    alternative_args={"url": available_urls[0]},
                )
        # (3) لا مسار متبقٍ — تخطٍ موثق أو فشل مادة
        return RecoveryDecision(
            action="SKIP_TOOL",
            reason=(
                "لا مراجعة ممكنة ولا بديل متاح — تخطٍّ موثق، المادة "
                "تُجمع مما نجح، وانعدامها فشل صريح"
            ),
            tool=failure.tool,
        )
    # NOT_RETRYABLE: مصادقة/سياسة/صورة غائبة — لا إعادة تغني
    return RecoveryDecision(
        action="FAIL_MATERIAL",
        reason=(
            f"فشل غير قابل للإعادة ({failure.reason}) — {failure.human_summary()}"
        ),
        tool=failure.tool,
    )


def absorb_material(name: str, value, materials: dict,
                    *, max_results: int = 8) -> None:
    """تجميع المادة من نتيجة أداة ناجحة — عقد مواد المنفذ الحي."""
    if name == "web_search":
        materials["search_results"].extend(list(value)[:max_results])
    elif name == "fetch_page":
        materials["pages"].append({"chars": len(value), "text": value[:6000]})
    elif name in ("http_get_text", "http_get_json", "page_to_text",
                  "fred_csv", "worldbank_indicator"):
        materials["data"].append({
            key: value.get(key)
            for key in ("tool", "series_id", "indicator", "url", "rows",
                        "count", "chars", "words", "structure",
                        "sample_rows", "first_300_words")
            if key in value
        })


def run_with_recovery(
    ctx,
    name: str,
    args: dict,
    *,
    attempt: int,
    attempted_queries: list[str],
    available_urls: list[str],
    materials: dict,
    failed_calls: list[dict],
    max_results: int = 8,
) -> bool:
    """استدعاء أداة واحد + تعافٍ مصنَّف واحد — يعيد هل وصلت مادة.

    كل قرار تعافٍ يُبث حدث tool.recovery حيًا (§12) ويُسجَّل —
    الواجهة ترى الاستعلام والتصنيف والإجراء لحظة حدوثها.
    """
    from roles.tools import run_tool  # noqa: PLC0415 — كسول يمنع الدوران

    query = str(args.get("query") or args.get("url") or "")
    if query:
        attempted_queries.append(query)

    def once(tool_name: str, tool_args: dict):
        return run_tool(tool_name, tool_args, ctx, attempt=attempt)

    try:
        value = once(name, args)
    except ToolFailure as failure:
        failed_calls.append(failure.to_record()["failure"])
        decision = plan_recovery(
            failure,
            attempted_queries=attempted_queries,
            available_urls=available_urls,
        )
        ctx.emit({
            "kind": "tool.recovery",
            "role": "implementer",
            "tool": name,
            "action": decision.action,
            "reason": decision.reason,
            "failure_class": failure.failure_class,
            "failure_reason": failure.reason,
            "query": query[:200],
            "attempt": attempt,
        })
        if decision.action == "RETRY_SAME":
            try:
                value = once(name, args)
            except ToolFailure as again:
                failed_calls.append(again.to_record()["failure"])
                return False
        elif decision.action == "REVISE_QUERY":
            try:
                value = once("web_search", {"query": decision.revised_query})
                attempted_queries.append(decision.revised_query)
            except ToolFailure as again:
                failed_calls.append(again.to_record()["failure"])
                return False
        elif decision.action == "ALTERNATIVE_TOOL":
            try:
                value = once(decision.alternative_tool,
                             decision.alternative_args or {})
                attempted_queries.append(str(
                    (decision.alternative_args or {}).get("url") or ""
                ))
                name = decision.alternative_tool
            except ToolFailure as again:
                failed_calls.append(again.to_record()["failure"])
                return False
        else:  # SKIP_TOOL / FAIL_MATERIAL — موثق لا مُقنَّع
            return False
        absorb_material(name, value, materials, max_results=max_results)
        return True
    absorb_material(name, value, materials, max_results=max_results)
    if name == "web_search":
        available_urls.extend(
            item["url"] for item in value if item.get("url")
        )
    return True
