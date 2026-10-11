"""اختبارات انحدار سلسلة استيراد الركيزة على Linux (الأمر 013.9 D1).

العقد الحرفي من الأمر (§3):
- ``import substrate.local_substrate`` عبر سلسلة الاستيراد الطبيعية
  ينجح على Linux — من دون أي وحدات وهمية في ``sys.modules``.
- الاستيراد لا يعتمد على توفر ``win32pipe`` أو أي وحدة Windows أخرى:
  الاختبار (2) يثبت أن التحميل لا يلمسها إطلاقًا في عملية جديدة نظيفة.
- المسارات المستخدمة فعلًا في التطبيق (limits/sandbox/workspace/
  local_substrate/windows_executor بنمطي الاستيراد) كلها تعمل.
- سلوك Windows محفوظ: فرع الاستيراد الفوري ``sys.platform == "win32"``
  موجود حرفيًا في ``__init__`` (التحقق التشغيلي الكامل على Windows
  نفسه مصنّف NOT RUN على مضيف Linux — لا ادعاء).

سياق العيب (013.8 F-1 = 013.9 D1): كان ``substrate/__init__.py``
يستورد ``windows_executor`` بلا حراسة، والملف يحتوي كتلة ملحقة
ميتة تستورد ``win32pipe`` على مستوى الوحدة بلا حراسة — فتعطّلت
حزمة الركيزة كلها على Linux (ModuleNotFoundError: win32pipe) وأسقطت
معها كل مسارات التنفيذ المعزول إلى «وضع متوافق بلا عزل».
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"

_IS_LINUX = sys.platform.startswith("linux")

#: الوحدات التي يستهلكها التطبيق فعلًا من حزمة الركيزة (grep موثق
#: في تقرير 013.9 §3) — كل مسار استيراد حرفي من كود المستودع.
_APP_IMPORT_STATEMENTS = [
    "import substrate.local_substrate",
    "import substrate.limits",
    "import substrate.sandbox",
    "import substrate.workspace",
    "from substrate.local_substrate import (local_sandbox_manager,"
    " default_local_images, LocalSubstrateAdapter, SubstrateUnavailable,"
    " _SUPPORTED_ARCH)",
    "from substrate.limits import E1_LIMITS_DEFAULTS, ExecutionLimits,"
    " validate_against_defaults, DEFAULT_MAX_OUTPUT_BYTES",
    "from substrate.sandbox import NetworkMode, SandboxRequest,"
    " SandboxTermination",
    "from substrate.workspace import Workspace, ArtifactCustodyEntry",
    "from substrate.windows_executor import WindowsExecutor,"
    " ExecutionLimits, ExecutionResult",
    "from substrate import WindowsExecutor, ExecutionLimits,"
    " ExecutionResult",
]

#: وحدات Windows التي لا يجوز أن تُحمَّل — ولا يُشترط توفرها — لأجل
#: استيراد الركيزة على Linux (جوهر D1).
_WIN32_MODULES = (
    "win32pipe", "win32api", "win32file", "win32event", "win32con",
    "win32job", "win32process", "win32security", "pywintypes",
)


def _fresh_python(code: str) -> subprocess.CompletedProcess:
    """عملية بايثون جديدة نظيفة — لا ميراث ولا وحدات وهمية إطلاقًا.

    هذا هو حرفيًا «سلسلة الاستيراد الطبيعية» المطلوبة في §3: نفس
    المفسّر، بلا أي حقن في sys.modules، وبمتغير بيئة PYTHONPATH يشير
    إلى src فقط.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120, env=env, cwd=str(REPO),
    )


@pytest.mark.skipif(not _IS_LINUX, reason="عيب D1 خاص بـ Linux — يُختبر عليها حصرًا")
def test_normal_import_chain_succeeds_on_linux():
    """§3-1: الاستيراد الطبيعي عبر سلسلة المنتج ينجح — بلا أي وهمية."""
    result = _fresh_python("import substrate.local_substrate")
    assert result.returncode == 0, (
        f"فشل الاستيراد الطبيعي على Linux:\n{result.stderr}"
    )


@pytest.mark.skipif(not _IS_LINUX, reason="دليل «لا اعتماد على win32» خاص بـ Linux")
def test_import_does_not_load_or_require_win32_modules():
    """§3-4: اختبار الانحدار — الاستيراد لا يعتمد على win32pipe.

    عملية جديدة نظيفة تستورد كل وحدات الركيزة المستخدمة، ثم تتحقق
    أن أياً من وحدات Windows لم يُحمَّل أصلاً في sys.modules — أي أن
    الاستيراد لم يحاول حتى لمسها، فضلاً عن الاعتماد عليها.
    """
    code = (
        "import sys\n"
        "import substrate, substrate.local_substrate, substrate.limits,"
        " substrate.sandbox, substrate.workspace, substrate.windows_executor\n"
        "loaded = [m for m in "
        + repr(list(_WIN32_MODULES)) +
        " if m in sys.modules]\n"
        "assert not loaded, f'وحدات Windows حُمّلت مع الركيزة: {loaded}'\n"
        "print('CLEAN-IMPORT: no win32 modules loaded')\n"
    )
    result = _fresh_python(code)
    assert result.returncode == 0, (
        f"الاستيراد حمّل أو تطلب وحدات Windows:\n{result.stdout}"
        f"\n{result.stderr}"
    )
    assert "CLEAN-IMPORT" in result.stdout


def test_app_consumed_import_paths():
    """§3-2: كل مسارات الاستيراد التي يستخدمها التطبيق فعلًا تعمل."""
    for statement in _APP_IMPORT_STATEMENTS:
        exec(compile(statement, "<013.9-app-import>", "exec"), {})
    # نمط المصنع/المنسق الحرفي (factory/orchestrator.py:52) — يتطلب جذر
    # المستودع على المسار (كما يوفره تشغيل uvicorn من الجذر).
    sys.path.insert(0, str(REPO))
    try:
        from src.substrate.windows_executor import (  # noqa: F401
            WindowsExecutor as _OrchestratorExecutor,
        )
    finally:
        sys.path.remove(str(REPO))


@pytest.mark.skipif(not _IS_LINUX, reason="العلم الصادق يُقرأ على Linux حيث pywin32 غائب")
def test_windows_executor_honest_flag_on_linux():
    """استيراد الوحدة ينجح على Linux والعلم صادق: HAS_PYWIN32 = False."""
    import substrate.windows_executor as we

    assert we.HAS_PYWIN32 is False, (
        "علم HAS_PYWIN32 صادق على Linux حيث pywin32 غير مثبتة"
    )
    # المنفّذ قابل للوصول عبر الوصول الكسول للحزمة دون تحميل مسبق
    from substrate import WindowsExecutor

    assert WindowsExecutor is we.WindowsExecutor


def test_package_init_windows_branch_preserved():
    """§3-3: فرع Windows محفوظ حرفيًا — الاستيراد الفوري عند win32.

    فحص بنيوي (ast) لا نصي: يثبت أن التحميل الفوري لوحدة المنفّذ
    موجود داخل شرط ``sys.platform == "win32"`` كما كان دائمًا، وأن
    ``__getattr__`` الكسول يغطي الأسماء الثلاثة المصدَّرة. التحقق
    التشغيلي الكامل على Windows نفسه = NOT RUN على مضيف Linux.
    """
    import ast

    source = (SRC / "substrate" / "__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    def _imports_windows_executor(node) -> bool:
        for n in ast.walk(node):
            if isinstance(n, ast.ImportFrom):
                if (n.module or "").endswith("windows_executor"):
                    return True
                # النمط الكسول: from . import windows_executor
                if not n.module and any(
                    alias.name == "windows_executor" for alias in n.names
                ):
                    return True
        return False

    # 1) الاستيراد الفوري محروس حرفيًا بشرط sys.platform == "win32"
    guarded_import = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Attribute)
        and node.test.left.attr == "platform"
        and any(
            isinstance(c, ast.Constant) and c.value == "win32"
            for c in node.test.comparators
        )
        and _imports_windows_executor(node)
        for node in ast.walk(tree)
    )

    # 2) الأسماء الثلاثة معلنة في مجموعة أسماء المنفّذ على مستوى الوحدة
    exported_names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_WIN32_EXECUTOR_NAMES"
            and isinstance(node.value, (ast.Tuple, ast.List))
        ):
            exported_names = {
                e.value for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }

    # 3) __getattr__ الكسول يستخدم مجموعة الأسماء ويستورد الوحدة عند الطلب
    lazy_getattr = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__getattr__":
            uses_names = any(
                isinstance(n, ast.Name) and n.id == "_WIN32_EXECUTOR_NAMES"
                for n in ast.walk(node)
            )
            lazy_import = _imports_windows_executor(node)
            raises = any(
                isinstance(n, ast.Raise) for n in ast.walk(node)
            )
            lazy_getattr = uses_names and lazy_import and raises

    assert guarded_import, (
        "فرع الاستيراد الفوري لـ windows_executor داخل شرط "
        "sys.platform == 'win32' غير موجود — سلوك Windows مهدَّد"
    )
    assert {"WindowsExecutor", "ExecutionLimits",
            "ExecutionResult"} <= exported_names, (
        "مجموعة أسماء المنفّذ لا تغطي الأسماء المصدَّرة الثلاثة"
    )
    assert lazy_getattr, (
        "__getattr__ الكسول (PEP 562) لا يغطي مسار غير Windows بصدق"
    )
