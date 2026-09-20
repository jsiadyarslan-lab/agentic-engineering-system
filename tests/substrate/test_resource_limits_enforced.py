"""إثبات سالب 3: حدود الموارد مفروضة ميكانيكيًا (RLIMIT_NPROC).

سقف العمليات يُفرض من النواة داخل العزل. البرنامج يحاول تفريع عددًا
من العمليات المتزامنة يتجاوز السقف الممنوح — يجب أن يفشل fork
بخطأ مورد (OSError) بدل تجاوز الحد.
"""

from __future__ import annotations

from substrate.limits import ExecutionLimits

from tests.substrate.conftest import read_stdout, run_in_sandbox  # noqa: F401


def test_resource_limits_enforced(adapter, tmp_path):
    # سقف عمليات منخفض (8 ≤ الافتراضي 32 — الطلبات تخفض فقط لا ترفع)
    limits = ExecutionLimits(max_processes=8)

    code = '''
import os, sys, time
children = []
try:
    for i in range(40):  # يتجاوز بكثير سقف 8
        pid = os.fork()
        if pid == 0:
            time.sleep(1.5)
            os._exit(0)
        children.append(pid)
    # وصلنا هنا = تجاوزنا السقف كاملًا — خرق
    print("BREACH:forked", len(children))
    for p in children:
        try:
            os.waitpid(p, 0)
        except ChildProcessError:
            pass
    sys.exit(0)
except OSError as e:
    print("LIMIT_ENFORCED:errno", e.errno, "after", len(children), "children")
    for p in children:
        try:
            os.waitpid(p, 0)
        except ChildProcessError:
            pass
    sys.exit(3)   # السقف عمل — جيد
'''
    record, artifacts = run_in_sandbox(
        adapter, tmp_path, code, sandbox_id="neg-limits-001", limits=limits
    )
    stdout = read_stdout(record)

    # 1) التفريع فشل عند السقف (وليس بعد استنفاد 40)
    assert record.exit_code == 3, f"داخل العزل: {stdout!r}"
    assert "LIMIT_ENFORCED" in stdout
    assert "BREACH" not in stdout

    # 2) عدد الأبناء المُفرَّعين قبل الفشل ظل تحت السقف الفعلي
    line = [l for l in stdout.splitlines() if "after" in l]
    assert line, f"سطر العدد مفقود: {stdout!r}"
    forked = int(line[0].split("after")[1].split("children")[0].strip())
    assert forked < 40, "لا معنى للفشل بعد 40 — السقف لم يُفرض"
