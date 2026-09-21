"""اختبارات تصنيف فشل الأدوات (إضافة الأمر 008 §22-§26).

الواقعة الحقيقية: T1 محاولة 2 — web_search ثلاث مرات بلا مادة قابلة
للتحليل ثم «كل استدعاءات الأدوات فشلت». المطلوب الآن: ToolFailure
مصنَّف (class/stage/reason)، سجل دائم لكل استدعاء، مراجعة استعلام
فعلية (لا تكرار حرفي)، تعافٍ بأداة بديلة حقيقية، فشل الركيزة
SANDBOX_FAILURE لا فشل منفذ، والمحكَّم يرى البنية كاملة.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from roles import web_tools
from research import providers as research_providers
from roles.recovery import plan_recovery, revise_query, run_with_recovery
from roles.tool_failures import (
    NEEDS_STRATEGY_CHANGE,
    RETRYABLE_REASONS,
    ToolCallRecord,
    ToolFailure,
    classify_sandbox_failure,
)
from roles.tools import ToolContext, run_tool


# ------------------------------------------------------------------ #
# §1+§3: التمييز الإلزامي بين حالات web_search
# ------------------------------------------------------------------ #

def test_web_search_no_analyzable_results_is_classified(tmp_path):
    """الواقعة الحقيقية: صفحة وصلت (HTTP 200) بلا مادة → TOOL_FAILURE/
    RESULTS_NOT_ANALYZABLE مع عدادات الاستخلاص — لا «فشل البحث» غامضًا."""
    import urllib.request

    class EmptyResponse:
        def read(self, _n=-1):
            return b"<html><body>no results here</body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    original = research_providers.urllib.request.urlopen
    research_providers.urllib.request.urlopen = lambda *a, **k: EmptyResponse()
    try:
        with pytest.raises(ToolFailure) as caught:
            web_tools.web_search("أفضل ممارسات بناء منصة OSINT متقدمة")
    finally:
        research_providers.urllib.request.urlopen = original

    failure = caught.value
    assert failure.failure_class == "TOOL_FAILURE"
    assert failure.reason == "RESULTS_NOT_ANALYZABLE"
    assert failure.stage == "TOOL_RESULT"
    assert failure.retryable is False
    assert failure.needs_strategy_change is True
    # التشخلاص يحمل الاستعلام وعدادات الاستخلاص (§4: الاستعلام يظهر)
    assert "OSINT" in failure.details["query"]
    assert failure.details["transport"] == "SUCCESS"
    assert failure.details["page_chars"] > 0


def test_web_search_transport_error_is_not_analyzable_error():
    """خطأ شبكة ≠ لا نتائج — التصنيف يفصل (§3)."""
    import urllib.error

    error = urllib.error.URLError("name or service not known")
    failure = web_tools.classify_transport_error("web_search", error,
                                                 query="q")
    assert failure.failure_class == "NETWORK_FAILURE"
    assert failure.reason == "NETWORK_ERROR"
    assert failure.retryable is True
    assert failure.needs_strategy_change is False


def test_run_tool_failure_creates_durable_record(tmp_path):
    """كل استدعاء فاشل يخلف سجلًا مصنَّفًا (§2+§18) — لا سلسلة فقط."""
    class EmptyResponse:
        def read(self, _n=-1):
            return b"<html>empty</html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    original = research_providers.urllib.request.urlopen
    research_providers.urllib.request.urlopen = lambda *a, **k: EmptyResponse()
    ctx = ToolContext(grant_root=tmp_path)
    try:
        with pytest.raises(ToolFailure) as caught:
            run_tool("web_search",
                     {"query": "zzqqxx obscureterm-notfound-123"}, ctx)
    finally:
        research_providers.urllib.request.urlopen = original
    failure = caught.value
    assert failure.reason == "RESULTS_NOT_ANALYZABLE"
    records = ctx.tool_records
    assert len(records) == 1
    record = records[0]
    assert record.status == "FAILED"
    assert record.transport_status == "SUCCESS"   # HTTP وصل (§5)
    assert record.result_status == "NOT_USABLE"
    assert record.failure_class == "TOOL_FAILURE"
    assert record.failure_reason == "RESULTS_NOT_ANALYZABLE"
    block = record.failure_block()
    assert block["class"] == "TOOL_FAILURE"
    assert block["reason"] == "RESULTS_NOT_ANALYZABLE"
    assert block["tool"] == "web_search"


def test_http_200_is_not_tool_success_without_usable_result():
    """(§5) نجاح النقل ليس نجاح أداة — القيمتان منفصلتان في السجل."""
    import urllib.request

    class OkButEmpty:
        def read(self, _n=-1):
            return b"<html></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    original = research_providers.urllib.request.urlopen
    research_providers.urllib.request.urlopen = lambda *a, **k: OkButEmpty()
    grant = Path("/tmp/tf-http200")
    grant.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(grant_root=grant)
    try:
        with pytest.raises(ToolFailure):
            run_tool("web_search", {"query": "anything"}, ctx)
    finally:
        research_providers.urllib.request.urlopen = original
    record = ctx.tool_records[0]
    assert record.transport_status == "SUCCESS"
    assert record.result_status == "NOT_USABLE"
    assert record.analyzable is False


# ------------------------------------------------------------------ #
# §9+§10: سياسة الإعادة ومراجعة الاستعلام — لا تكرار حرفي
# ------------------------------------------------------------------ #

def test_retryable_transient_failure_plans_retry_same():
    failure = ToolFailure("web_search", "مهلة", failure_class="TIMEOUT",
                          reason="TIMEOUT", stage="TOOL_EXECUTION",
                          retryable=True)
    decision = plan_recovery(failure, attempted_queries=["q"],
                             available_urls=[])
    assert decision.action == "RETRY_SAME"


def test_no_analyzable_results_plans_query_revision_not_repeat():
    """السبب نفسه لا يُعاد بلا تغيير (§9) — مراجعة استراتيجية إلزامية."""
    failure = ToolFailure(
        "web_search", "لا مادة", failure_class="TOOL_FAILURE",
        reason="RESULTS_NOT_ANALYZABLE", stage="TOOL_RESULT",
        details={"query": "أفضل ممارسات بناء منصة OSINT متقدمة معمارية microservices"},
    )
    decision = plan_recovery(
        failure, attempted_queries=["أفضل ممارسات بناء منصة OSINT متقدمة معمارية microservices"],
        available_urls=[],
    )
    assert decision.action == "REVISE_QUERY"
    assert decision.revised_query != "أفضل ممارسات بناء منصة OSINT متقدمة معمارية microservices"
    assert "OSINT" in decision.revised_query or "microservices" in decision.revised_query


def test_revise_query_never_repeats_previous():
    previous = ["OSINT platform architecture"]
    assert revise_query("OSINT platform architecture", previous) is None
    revised = revise_query("بناء منصة OSINT متقدمة جدًا", previous)
    assert revised is not None and revised not in previous


def test_alternative_tool_only_from_registered_whitelist():
    """البديل من الأدوات المسجلة حصرًا (§11) — لا اختراع أدوات."""
    failure = ToolFailure(
        "web_search", "لا مادة", failure_class="TOOL_FAILURE",
        reason="RESULTS_NOT_ANALYZABLE", stage="TOOL_RESULT",
        details={"query": "arabic only query with no latin"},
    )
    decision = plan_recovery(failure, attempted_queries=["arabic only query"],
                             available_urls=["https://example.com/x"])
    assert decision.action == "ALTERNATIVE_TOOL"
    assert decision.alternative_tool in ("fetch_page", "http_get_text",
                                         "page_to_text")
    assert decision.alternative_args["url"].startswith("http")


def test_auth_failure_is_fail_material_not_retry():
    failure = ToolFailure("web_search", "مرفوض", failure_class="AUTH_FAILURE",
                          reason="AUTH_FAILED", stage="TOOL_EXECUTION",
                          retryable=False)
    decision = plan_recovery(failure, attempted_queries=[], available_urls=[])
    assert decision.action == "FAIL_MATERIAL"


# ------------------------------------------------------------------ #
# §24: التعافي الفعلي — فشل ثم استعلام مراجَع ينجح فتكتمل المهمة
# ------------------------------------------------------------------ #

def test_recovery_failing_then_revised_query_succeeds(tmp_path):
    """(§24 اختبار التعافي): فشل ← مراجعة ← استعلام ثانٍ ينجح — مع
    بقاء تاريخ الفشل الأول في السجلات (لا حذف أدلة المحاولة الفاشلة)."""
    ctx = ToolContext(grant_root=tmp_path)
    calls = {"n": 0}

    def flaky_search(query, **_kwargs):
        calls["n"] += 1
        if "منصة" in query:  # الاستعلام العربي الطويل الأول
            raise ToolFailure(
                "web_search", "لا مادة", failure_class="TOOL_FAILURE",
                reason="RESULTS_NOT_ANALYZABLE", stage="TOOL_RESULT",
                retryable=False, details={"query": query},
            )
        return [{"title": "OSINT guide", "url": "https://example.com/osint",
                 "snippet": "دليل"}]

    original = web_tools.web_search
    import roles.tools as tools_module
    tools_module.web_search = flaky_search
    try:
        materials = {"search_results": [], "pages": [], "data": []}
        ok = run_with_recovery(
            ctx, "web_search", {"query": "بناء منصة OSINT متقدمة"},
            attempt=1, attempted_queries=[], available_urls=[],
            materials=materials, failed_calls=[],
        )
    finally:
        tools_module.web_search = original

    assert ok is True
    assert calls["n"] >= 2                      # فشل ثم استعلام مراجَع
    assert materials["search_results"]           # المادة وصلت
    queries = [r.query for r in ctx.tool_records]
    assert len(queries) >= 2 and queries[0] != queries[1]
    # تاريخ الفشل الأول محفوظ (لا حذف §24)
    assert any(r.status == "FAILED" for r in ctx.tool_records)
    assert any(r.status == "SUCCEEDED" for r in ctx.tool_records)


def test_all_paths_failing_ends_in_documented_skip(tmp_path):
    ctx = ToolContext(grant_root=tmp_path)

    def always_fails(query, **_kwargs):
        raise ToolFailure(
            "web_search", "لا مادة", failure_class="TOOL_FAILURE",
            reason="RESULTS_NOT_ANALYZABLE", stage="TOOL_RESULT",
            retryable=False, details={"query": query},
        )

    import roles.tools as tools_module
    original = tools_module.web_search
    tools_module.web_search = always_fails
    try:
        materials = {"search_results": [], "pages": [], "data": []}
        failed_calls: list[dict] = []
        ok = run_with_recovery(
            ctx, "web_search", {"query": "استعلام عربي طويل جدًا بلا لاتيني"},
            attempt=1, attempted_queries=[], available_urls=[],
            materials=materials, failed_calls=failed_calls,
        )
    finally:
        tools_module.web_search = original

    assert ok is False                          # لا نجاح وهمي
    assert failed_calls                         # الفشل موثق مصنَّفًا
    assert failed_calls[0]["reason"] in NEEDS_STRATEGY_CHANGE


# ------------------------------------------------------------------ #
# §16+§23: فشل الركيزة ليس فشل منفذ
# ------------------------------------------------------------------ #

def test_sandbox_failed_to_start_classified_as_sandbox_failure():
    """الرسالة التاريخية: «FAILED_TO_START: لا صورة تنفيذ متاحة» —
    SANDBOX_FAILURE في STARTUP لا IMPLEMENTER_FAILURE."""
    stderr = ("FAILED_TO_START: لا صورة تنفيذ متاحة — الركيزة المعزولة "
              "تتطلب Linux/x86_64 (WSL2 على Windows)")
    failure = classify_sandbox_failure("write_file", stderr)
    assert failure is not None
    assert failure.failure_class == "SANDBOX_FAILURE"
    assert failure.reason == "NO_EXECUTION_IMAGE"
    assert failure.stage == "STARTUP"
    assert failure.retryable is False


def test_plain_code_error_is_not_sandbox_failure():
    assert classify_sandbox_failure("write_file", "SyntaxError: bad") is None


def test_failure_summary_block_shape():
    record = ToolCallRecord(tool_call_id="tc-1", tool="web_search",
                            started_at="t", status="FAILED",
                            failure_class="TOOL_FAILURE",
                            failure_stage="TOOL_RESULT",
                            failure_reason="RESULTS_NOT_ANALYZABLE",
                            query="q", error="لا مادة", retryable=False)
    block = record.failure_block()
    assert set(block) == {
        "class", "stage", "tool", "reason", "retryable", "attempt",
        "query", "result_count", "error",
    }
    assert block["class"] == "TOOL_FAILURE"
    assert block["reason"] == "RESULTS_NOT_ANALYZABLE"


def test_retryable_reasons_policy():
    """(§9) المهلة/الشبكة/الحد تعاد؛ المصادقة/الاستعلام لا تعاد كما هي."""
    assert "TIMEOUT" in RETRYABLE_REASONS
    assert "RATE_LIMITED" in RETRYABLE_REASONS
    assert "AUTH_FAILED" not in RETRYABLE_REASONS
    assert "RESULTS_NOT_ANALYZABLE" not in RETRYABLE_REASONS
    assert "RESULTS_NOT_ANALYZABLE" in NEEDS_STRATEGY_CHANGE
