"""تصنيف فشل الأدوات وتشخيصها (إضافة الأمر 008 §1-§5+§16-§18).

الفشل لم يعد سلسلة نصية غامضة («كل استدعاءات الأدوات فشلت») بل بنية
ميكانيكية صادقة تصل إلى: الأدلة ← المحكَّم ← الأحداث ← الواجهة.

الطبقات الثلاث المفصولة (§1+§16):
- failure_class: عائلة الفشل (TOOL_FAILURE / SANDBOX_FAILURE / …)
- failure_stage: أين وقع في المسار (PROVIDER_RESOLUTION … ARBITRATION)
- failure_reason: السبب الدقيق للأداة (NO_RESULTS /
  RESULTS_NOT_ANALYZABLE / …) — التمييز الإلزامي بين «لا نتائج»
  و«نتائج غير قابلة للتحليل» و«خطأ مزود» (§3).

عقد الاستخدام (§5): نجاح النقل (transport=SUCCESS) لا يعني نتيجة
صالحة (result=USABLE) — القيمتان مستقلتان في كل سجل استدعاء.
"""

from __future__ import annotations

import datetime as _dt
import re
import urllib.error
from dataclasses import dataclass, field
from typing import Any

#: عائلات الفشل (إضافة 008 §1) — مفردات مقفلة.
FAILURE_CLASSES: tuple[str, ...] = (
    "TOOL_FAILURE",           # الأداة نفسها لم تنتج مادة قابلة للاستخدام
    "EXECUTOR_FAILURE",       # المنفذ فشل في منطقه هو
    "PROVIDER_FAILURE",       # مزود الخدمة رفض/أخطأ
    "SANDBOX_FAILURE",        # بيئة التنفيذ المعزولة لم تبدأ/تعطلت
    "NETWORK_FAILURE",        # شبكة/DNS/اتصال
    "AUTH_FAILURE",           # مصادقة/مفاتيح
    "INPUT_FAILURE",          # مدخلات غير صالحة من المنفذ
    "VALIDATION_FAILURE",     # خرج الأداة لم يصمد أمام التحقق
    "DEPENDENCY_FAILURE",     # تبعية ناقصة (خط/مكتبة/مسار)
    "TIMEOUT",                # مهلة صريحة
    "POLICY_BLOCK",           # رفض سياسة (قائمة بيضاء/منح)
    "INSUFFICIENT_EVIDENCE",  # لا أدلة كافية للحكم
    "UNKNOWN_FAILURE",
)

#: مراحل الفشل (§17) — أين في المسار.
FAILURE_STAGES: tuple[str, ...] = (
    "PROVIDER_RESOLUTION", "TOOL_START", "TOOL_EXECUTION", "TOOL_RESULT",
    "ANALYSIS", "IMPLEMENTATION", "VERIFICATION", "AUDIT", "ARBITRATION",
    "STARTUP",
)

#: أسباب فشل الأدوات الحية (§3) — التمييز الإلزامي لكل حالة بحث.
TOOL_FAILURE_REASONS: tuple[str, ...] = (
    "NO_RESULTS",              # البحث نجح نقليًا وصفر نتائج نظيفة
    "RESULTS_NOT_ANALYZABLE",  # صفحة وصلت لكن الاستخلاص لم يجد مادة
    "RESULTS_UNAVAILABLE",
    "PROVIDER_ERROR",
    "NETWORK_ERROR",
    "RATE_LIMITED",
    "AUTH_FAILED",
    "INVALID_QUERY",
    "REQUEST_FAILED",
    "RESPONSE_EMPTY",
    "INVALID_RESPONSE",
    "PARSER_FAILURE",
    "TIMEOUT",
    "PAGE_EMPTY",
    "NO_ANALYZABLE_MATERIAL",
    "TOOL_NOT_WHITELISTED",
    "PATH_OUTSIDE_GRANT",
    "NO_EXECUTION_IMAGE",
    "SUBSTRATE_REJECTED_IMPORT",
    "OUTPUT_UNPARSEABLE",
)

#: الفشل القابل للإعادة مباشرة (سياسة الإعادة §9) — دون تغيير المدخلات.
RETRYABLE_REASONS: frozenset[str] = frozenset({
    "TIMEOUT", "NETWORK_ERROR", "RATE_LIMITED", "PROVIDER_ERROR",
    "REQUEST_FAILED",
})

#: فشل لا يُعاد إلا بتغيير الاستراتيجية — إعادة نفس الاستعلام حرفيًا
#: مضيعة ممنوعة (§9: NO_ANALYZABLE_RESULTS لا يعاد بلا تغيير).
NEEDS_STRATEGY_CHANGE: frozenset[str] = frozenset({
    "NO_RESULTS", "RESULTS_NOT_ANALYZABLE", "RESULTS_UNAVAILABLE",
    "NO_ANALYZABLE_MATERIAL", "PAGE_EMPTY", "INVALID_QUERY",
    "RESPONSE_EMPTY",
})

#: لا إعادة أبدًا — إصلاح يدوي أو تخطي (§9).
NOT_RETRYABLE_REASONS: frozenset[str] = frozenset({
    "AUTH_FAILED", "TOOL_NOT_WHITELISTED", "PATH_OUTSIDE_GRANT",
    "NO_EXECUTION_IMAGE",
})

#: توقيع فشل بدء الركيزة (رسالة الصدق من _run_in_substrate §11 الأمر 006).
SANDBOX_STARTUP_PREFIX = "FAILED_TO_START:"


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class ToolError(RuntimeError):
    """فشل خطوة أداة — الصنف الأساس (عقد الأمر السادس محفوظ).

    عُرّف هنا (لا في roles.tools) ليظل مسارًا واحدًا: roles/tools يعيد
    تصديره للتوافق مع كل الاستيرادات القائمة (tools/fs, tools/proc,
    tools/data_tools, الاختبارات).
    """


class ToolFailure(ToolError):
    """فشل أداة مصنَّف — بنية صادقة لا سلسلة غامضة (§1).

    Attributes:
        tool: اسم الأداة.
        failure_class: عائلة الفشل (FAILURE_CLASSES).
        reason: السبب الدقيق (TOOL_FAILURE_REASONS).
        stage: مرحلة الفشل (FAILURE_STAGES).
        retryable: هل الإعادة المجدية ممكنة دون تغيير؟
        needs_strategy_change: هل تتطلب الإعادة تغيير الاستعلام/الأداة؟
        details: تشخيص آمن (بلا أسرار) — الاستعلام، عدادات الاستخلاص…
    """

    def __init__(
        self,
        tool: str,
        message: str,
        *,
        failure_class: str = "TOOL_FAILURE",
        reason: str = "UNKNOWN",
        stage: str = "TOOL_RESULT",
        retryable: bool | None = None,
        details: dict | None = None,
    ):
        self.tool = tool
        self.failure_class = failure_class
        self.reason = reason
        self.stage = stage
        self.details = details or {}
        if retryable is None:
            retryable = reason in RETRYABLE_REASONS
        self.retryable = retryable
        self.needs_strategy_change = reason in NEEDS_STRATEGY_CHANGE
        super().__init__(message)

    def to_record(self) -> dict:
        """الملخص المنظم (§18) — المصدر الذي تستخدمه الواجهة والمحكَّم."""
        return {
            "failure": {
                "class": self.failure_class,
                "stage": self.stage,
                "tool": self.tool,
                "reason": self.reason,
                "retryable": self.retryable,
                "needs_strategy_change": self.needs_strategy_change,
                "message": str(self),
                "details": self.details,
            }
        }

    def human_summary(self) -> str:
        """ملخص عربي مفهوم (§13) — لا JSON خام للمستخدم العادي."""
        labels = {
            "NO_RESULTS": "لم يعثر على نتائج",
            "RESULTS_NOT_ANALYZABLE": "لم تُرجع الأداة مادة قابلة للتحليل",
            "NETWORK_ERROR": "تعذر الوصول إلى الشبكة",
            "RATE_LIMITED": "حد المعدل لدى المزود",
            "AUTH_FAILED": "المصادقة مرفوضة",
            "TIMEOUT": "انتهت المهلة",
            "NO_EXECUTION_IMAGE": "لا صورة تنفيذ متاحة للركيزة المعزولة",
            "PAGE_EMPTY": "الصفحة شبه فارغة بعد الاستخلاص",
        }
        why = labels.get(self.reason, self.reason)
        where = {
            "TOOL_START": "بدء الأداة", "TOOL_EXECUTION": "تنفيذ الأداة",
            "TOOL_RESULT": "نتيجة الأداة", "STARTUP": "بدء بيئة التنفيذ",
        }.get(self.stage, self.stage)
        return f"{self.tool}: {why} (المرحلة: {where})"


def classify_transport_error(
    tool: str, error: Exception, *, query: str = "",
) -> ToolFailure:
    """تصنيف خطأ نقل واحد (§3) — شبكة/مهلة/مزود/مصادقة."""

    def fail(reason: str, cls: str, stage: str, retryable: bool | None = None,
             **extra) -> ToolFailure:
        return ToolFailure(
            tool, f"فشل {tool} ({reason}): {error}", failure_class=cls,
            reason=reason, stage=stage, retryable=retryable,
            details={"query": query[:200], **extra},
        )

    if isinstance(error, urllib.error.HTTPError):
        code = int(error.code)
        if code in (401, 403):
            return fail("AUTH_FAILED", "AUTH_FAILURE", "TOOL_EXECUTION",
                        retryable=False)
        if code == 429:
            return fail("RATE_LIMITED", "PROVIDER_FAILURE", "TOOL_EXECUTION")
        if code >= 500:
            return fail("PROVIDER_ERROR", "PROVIDER_FAILURE", "TOOL_EXECUTION")
        return fail("INVALID_RESPONSE", "PROVIDER_FAILURE", "TOOL_EXECUTION",
                    http_status=code)
    if isinstance(error, TimeoutError):
        return fail("TIMEOUT", "TIMEOUT", "TOOL_EXECUTION")
    text = str(error).lower()
    if "timed out" in text or "timeout" in text:
        return fail("TIMEOUT", "TIMEOUT", "TOOL_EXECUTION")
    if "gaierror" in text or "name or service" in text or "dns" in text:
        return fail("NETWORK_ERROR", "NETWORK_FAILURE", "TOOL_EXECUTION")
    return fail("NETWORK_ERROR", "NETWORK_FAILURE", "TOOL_EXECUTION")


def classify_sandbox_failure(
    tool: str, stderr: str,
) -> ToolFailure | None:
    """تصنيف فشل الركيزة (§16+§23) — FAILED_TO_START ليس فشل منفذ.

    الحالة التاريخية الموثقة: «FAILED_TO_START: لا صورة تنفيذ متاحة —
    الركيزة المعزولة تتطلب Linux/x86_64» — هذه SANDBOX_FAILURE في
    مرحلة STARTUP، لا فشل كود المنفذ نفسه.
    """
    head = (stderr or "").strip()[:400]
    if not head:
        return None
    if head.startswith(SANDBOX_STARTUP_PREFIX):
        return ToolFailure(
            tool,
            f"بيئة التنفيذ المعزولة لم تبدأ: {head}",
            failure_class="SANDBOX_FAILURE",
            reason="NO_EXECUTION_IMAGE",
            stage="STARTUP",
            retryable=False,
            details={"stderr_head": head[:200]},
        )
    if "import" in head.lower() and "error" in head.lower():
        return ToolFailure(
            tool,
            f"الركيزة رفضت الاستيراد: {head[:160]}",
            failure_class="SANDBOX_FAILURE",
            reason="SUBSTRATE_REJECTED_IMPORT",
            stage="TOOL_EXECUTION",
            retryable=True,
            details={"stderr_head": head[:200]},
        )
    return None


@dataclass
class ToolCallRecord:
    """سجل استدعاء أداة دائم (§2) — المصدر الخام لأي Evidence لاحق.

    transport_status وresult_status منفصلان (§5): نجاح النقل لا يعني
    نتيجة قابلة للاستخدام. لا أسرار في أي حقل أبدًا.
    """

    tool_call_id: str
    tool: str
    started_at: str
    completed_at: str = ""
    status: str = "RUNNING"             # RUNNING | SUCCEEDED | FAILED
    transport_status: str = "PENDING"   # SUCCESS | FAILED | PENDING
    result_status: str = "PENDING"      # USABLE | NOT_USABLE | PENDING
    failure_class: str = ""
    failure_stage: str = ""
    failure_reason: str = ""
    query: str = ""                     # نص الاستعلام/الرابط (بلا أسرار)
    request_summary: dict = field(default_factory=dict)
    result_count: int = 0
    analyzable: bool = False
    error: str = ""
    retryable: bool = False
    duration_ms: int = 0
    execution_site: str = ""
    output_sha256: str = ""
    result_summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tool_call_id": self.tool_call_id, "tool": self.tool,
            "started_at": self.started_at, "completed_at": self.completed_at,
            "status": self.status,
            "transport_status": self.transport_status,
            "result_status": self.result_status,
            "failure_class": self.failure_class,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "query": self.query[:300],
            "request_summary": self.request_summary,
            "result_count": self.result_count,
            "analyzable": self.analyzable, "error": self.error[:300],
            "retryable": self.retryable, "duration_ms": self.duration_ms,
            "execution_site": self.execution_site,
            "output_sha256": self.output_sha256,
            "result_summary": self.result_summary,
        }

    def failure_block(self) -> dict:
        """كتلة الفشل الموحدة (§18) — تصل المحكَّم والواجهة كما هي."""
        if self.status != "FAILED":
            return {}
        return {
            "class": self.failure_class or "TOOL_FAILURE",
            "stage": self.failure_stage or "TOOL_RESULT",
            "tool": self.tool,
            "reason": self.failure_reason or "UNKNOWN",
            "retryable": self.retryable,
            "attempt": self.request_summary.get("attempt"),
            "query": self.query[:200],
            "result_count": self.result_count,
            "error": self.error[:200],
        }


#: نموذج الاستعلام الحي الذي لا ينتج مادة — كلمات مفتاحية إنجليزية
#: أقصر أنجح تجريبيًا من العربية الطويلة (خطة مراجعة الاستعلام §10).
_QUERY_NOISE = re.compile(r"[^\w\s\u0600-\u06FF]", re.UNICODE)


def revise_query(query: str, previous_queries: list[str]) -> str | None:
    """مراجعة استراتيجية الاستعلام (§10) — تغيير حقيقي لا تكرار حرفي.

    الاستراتيجية معلنة وصادقة (لا وهم ذكاء): تقليم الكلمات الوقفية
    العربية الشائعة + الاقتصار على الكلمات الدالة الأهم + تقديم
    المصطلحات اللاتينية إن وجدت. الناتج يجب أن يختلف عن كل الاستعلامات
    السابقة وإلا لا مراجعة (None) — الإعادة الحرفية ممنوعة (§9).
    """
    stop_ar = {
        "في", "من", "على", "عن", "الى", "إلى", "مع", "هذا", "هذه", "التي",
        "الذي", "او", "أو", "و", "ثم", "كل", "بعض", "جدا", "جدًا", "الى",
        "افضل", "أفضل", "مثل", "معمارية", "بناء", "اريد", "أريد",
    }
    cleaned = _QUERY_NOISE.sub(" ", query)
    words = [w for w in cleaned.split() if w and w not in stop_ar]
    latin = [w for w in words if re.match(r"^[A-Za-z0-9._-]+$", w)]
    if latin:
        revised = " ".join(latin[:6])
    else:
        # عربي خالص: أقصر الكلمات الدالة (الكلمات الأطول أعمق دلالة غالبًا)
        core = sorted(set(words), key=len, reverse=True)[:5]
        revised = " ".join(core)
    if not revised or len(revised) < 3:
        return None
    if revised == query.strip():
        return None
    if revised in {q.strip() for q in previous_queries}:
        return None
    return revised
