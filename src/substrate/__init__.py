# Substrate Package
"""Substrate Package - Execution backends for different platforms.

(013.9 D1) استيراد منفّذ Windows محروس بالمنصة: تحميل هذه الحزمة على
Linux/macOS لا يتطلب pywin32 إطلاقًا — عيب 013.8 F-1 كان الاستيراد
غير المحروس هنا يعطّل كل وحدات الركيزة (limits/sandbox/workspace/
local_substrate) على Linux عبر ``ModuleNotFoundError: win32pipe``.

السلوك المحفوظ حرفيًا: على Windows (``sys.platform == "win32"``)
يبقى الاستيراد الحرفي للمنفّذ عند تحميل الحزمة كما كان دائمًا.
على غير Windows يُوفَّر الاسم عند الطلب عبر ``__getattr__`` الكسول
(PEP 562): الوحدة نفسها أصبحت قابلة للاستيراد على كل المنصات
(استيراداتها العليا محروسة بعلم HAS_PYWIN32)، فالوصول الصريح ينجح،
وإن تعذّر فالخطأ صريح بسبب معلن — لا ابتلاع صامت ولا حالة جاهزة
شكلية.
"""

from __future__ import annotations

import sys

#: الأسماء التي يصدّرها هذا التكوين من وحدة منفّذ Windows.
_WIN32_EXECUTOR_NAMES = ("WindowsExecutor", "ExecutionLimits",
                         "ExecutionResult")

if sys.platform == "win32":
    # السلوك المدعوم كما كان حرفيًا — استيراد فوري على Windows.
    from .windows_executor import (  # noqa: F401
        WindowsExecutor,
        ExecutionLimits,
        ExecutionResult,
    )

__all__ = [
    "WindowsExecutor",
    "ExecutionLimits",
    "ExecutionResult",
]


def __getattr__(name: str):
    """(PEP 562) وصول كسول على غير Windows — صدق لا ابتلاع.

    على Linux/macOS لا يُحمَّل windows_executor مع الحزمة إطلاقًا؛ إن
    طلبه مستهلك صراحةً (``from substrate import WindowsExecutor``)
    يُستورد الآن ويعاد كما هو. أي اسم آخر يرفض برسالة واضحة.
    """
    if name in _WIN32_EXECUTOR_NAMES:
        from . import windows_executor

        return getattr(windows_executor, name)
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )
