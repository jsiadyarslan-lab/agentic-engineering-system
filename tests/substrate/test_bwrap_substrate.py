"""اختبارات محوّل bwrap — إثباتات تنفيذ معزول حقيقي (AES-EXP-04 §3).

كل اختبار هنا يشغّل bubblewrap فعليًا (لا محاكاة): إطلاع + كتابة +
قراءة + التقاط مخرجات + انتشار رمز الخروج + حجب الشبكة + قتل المهلة +
خرق السعة + قاعدة التنفيذ الواحد + قائمة منع seccomp (aarch64) +
تفكيك موثق. على مضيف بلا ركيزة: تخطٍ صادق ببيان السبب.
"""

from __future__ import annotations

import hashlib
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from substrate.bwrap_substrate import (  # noqa: E402
    BubblewrapSubstrateAdapter,
    _seccomp_bpf_bytes,
    bwrap_capabilities,
    default_bwrap_images,
)
from substrate.factory import (  # noqa: E402
    KIND_BWRAP,
    KIND_LOCAL,
    select_substrate,
)
from substrate.limits import (  # noqa: E402
    E1_LIMITS_DEFAULTS,
    ExecutionLimits,
)
from substrate.sandbox import (  # noqa: E402
    NetworkMode,
    SandboxRequest,
    SandboxTermination,
)

pytestmark = pytest.mark.skipif(
    select_substrate().get("kind") is not KIND_BWRAP,
    reason="هذه الاختبارات لمحوّل bwrap تحديدًا — الركيزة المختارة ليست bwrap",
)


def _adapter(tmp_path: Path) -> BubblewrapSubstrateAdapter:
    return BubblewrapSubstrateAdapter(base_dir=tmp_path)


def _request(
    tmp_path: Path,
    *,
    sandbox_id: str,
    code: str,
    limits: ExecutionLimits | None = None,
    env_names: frozenset[str] = frozenset({"PATH"}),
) -> tuple[SandboxRequest, Path]:
    artifacts = tmp_path / "art"
    artifacts.mkdir(parents=True, exist_ok=True)
    images = default_bwrap_images()
    image = next(iter(images))
    return SandboxRequest(
        sandbox_id=sandbox_id,
        image=image,
        command=("python", "-c", code),
        limits=limits or E1_LIMITS_DEFAULTS,
        env_names=env_names,
        network=NetworkMode.NONE,
        workspace_root=str(tmp_path / "ws"),
        artifacts_dir=str(artifacts),
    ), artifacts


def test_capabilities_truthful_and_proven():
    """سجل القدرات صادق: bwrap موجود + probe إطلاق حقيقي OK."""
    caps = bwrap_capabilities()
    assert caps["bwrap_present"] is True
    assert caps["supported"] is True
    assert caps["launch_probe"] == "OK"
    assert caps["userns_enabled"] is True
    assert int(caps["max_user_namespaces"]) > 0


def test_seccomp_bpf_program_shape():
    """برنامج BPF: تحميل arch ثم nr ثم جدول المنع ثم القرارين."""
    program = _seccomp_bpf_bytes()
    assert len(program) % 8 == 0
    count = len(program) // 8
    # LD arch + JEQ arch + LD nr + N*JEQ + RET_ALLOW + RET_DENY
    from substrate.bwrap_substrate import DENIED_SYSCALLS_AARCH64

    assert count == 3 + len(DENIED_SYSCALLS_AARCH64) + 2


def test_real_execution_write_read_capture(tmp_path):
    """تنفيذ حقيقي: كتابة ملف داخل /artifacts + قراءته + التقاط stdout."""
    adapter = _adapter(tmp_path)
    code = (
        "import pathlib\n"
        "p = pathlib.Path('/artifacts/result.txt')\n"
        "p.write_text('bw-exec-ok', encoding='utf-8')\n"
        "print('read:', p.read_text(encoding='utf-8'))\n"
    )
    request, artifacts = _request(tmp_path, sandbox_id="bw-real-1", code=code)
    record = adapter.execute(request)
    try:
        assert record.termination is SandboxTermination.COMPLETED
        assert record.executed is True
        assert record.exit_code == 0
        stdout = Path(record.stdout_reference).read_text(
            encoding="utf-8", errors="replace"
        )
        assert "read: bw-exec-ok" in stdout
        # الملف نتج عن التنفيذ الفعلي داخل الركيزة وعلى المضيف
        result_file = artifacts / "result.txt"
        assert result_file.is_file()
        assert result_file.read_text(encoding="utf-8") == "bw-exec-ok"
        # دليل الحجز: sha256 يطابق محتوى الملف الفعلي
        entry = next(a for a in record.artifacts if a.path == "result.txt")
        assert entry.sha256 == hashlib.sha256(b"bw-exec-ok").hexdigest()
    finally:
        adapter.teardown(request.sandbox_id)


def test_exit_code_propagation_is_evidence_only(tmp_path):
    """رمز خروج غير صفري يُسجَّل كما هو — دليل لا حكم (D-08)."""
    adapter = _adapter(tmp_path)
    request, _ = _request(
        tmp_path, sandbox_id="bw-exit-1", code="import sys; sys.exit(42)"
    )
    record = adapter.execute(request)
    try:
        assert record.termination is SandboxTermination.COMPLETED
        assert record.exit_code == 42
    finally:
        adapter.teardown(request.sandbox_id)


def test_network_isolation_blocks_outbound(tmp_path):
    """العزل الشبكي: اتصال صادر لمستمع حي على المضيف يجب أن يفشل."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3.0)
    port = listener.getsockname()[1]
    try:
        adapter = _adapter(tmp_path)
        code = (
            "import socket, sys\n"
            "try:\n"
            f"    socket.create_connection(('127.0.0.1', {port}), timeout=2)\n"
            "    print('ESCAPED')\n"
            "except Exception as error:\n"
            "    print('BLOCKED:', type(error).__name__)\n"
        )
        request, _ = _request(tmp_path, sandbox_id="bw-net-1", code=code)
        record = adapter.execute(request)
        try:
            assert record.termination is SandboxTermination.COMPLETED
            stdout = Path(record.stdout_reference).read_text(
                encoding="utf-8", errors="replace"
            )
            assert "ESCAPED" not in stdout
            assert "BLOCKED:" in stdout
        finally:
            adapter.teardown(request.sandbox_id)
    finally:
        listener.close()


def test_seccomp_denylist_blocks_mount_inside(tmp_path):
    """seccomp (أرقام aarch64): mount داخل الركيزة → EPERM (منع صريح)."""
    adapter = _adapter(tmp_path)
    code = (
        "import ctypes, errno, os\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mount.restype = ctypes.c_int\n"
        "libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, "
        "ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p]\n"
        "ctypes.set_errno(0)\n"
        "rc = libc.mount(b'/tmp', b'/mnt-target', None, 0, None)\n"
        "err = ctypes.get_errno()\n"
        "print('MOUNT_RC', rc, 'ERR', err, os.strerror(err) if err else '')\n"
    )
    request, _ = _request(tmp_path, sandbox_id="bw-seccomp-1", code=code)
    record = adapter.execute(request)
    try:
        assert record.termination is SandboxTermination.COMPLETED
        stdout = Path(record.stdout_reference).read_text(
            encoding="utf-8", errors="replace"
        )
        # rc=-1 وerrno=EPERM — الدليل الحي على أن قائمة المنع تعمل
        assert "MOUNT_RC -1 ERR 1" in stdout
    finally:
        adapter.teardown(request.sandbox_id)


def test_timeout_kills_stuck_process(tmp_path):
    """عملية معلقة تُقتل بالمهلة — termination=TIMEOUT (لا تعليق أبدًا)."""
    adapter = _adapter(tmp_path)
    limits = ExecutionLimits(timeout_seconds=6)
    request, _ = _request(
        tmp_path, sandbox_id="bw-timeout-1",
        code="import time; print('stuck'); time.sleep(120)",
        limits=limits,
    )
    import time as _time

    started = _time.monotonic()
    record = adapter.execute(request)
    elapsed = _time.monotonic() - started
    try:
        assert record.termination is SandboxTermination.TIMEOUT
        assert elapsed < 30, f"المهلة استغرقت {elapsed:.1f}ث — الإيقاف غير فعال"
        assert record.executed is True  # بدأ فعلًا ثم قُتل
    finally:
        adapter.teardown(request.sandbox_id)


def test_output_cap_breach_terminates(tmp_path):
    """خرق سعة المخرجات → LIMIT_BREACH (لا تجاوز للسقف D-13)."""
    adapter = _adapter(tmp_path)
    limits = ExecutionLimits(max_output_bytes=4096)
    request, _ = _request(
        tmp_path, sandbox_id="bw-cap-1",
        code="import sys\nfor i in range(2000):\n    sys.stdout.write('x' * 64)\n",
        limits=limits,
    )
    record = adapter.execute(request)
    try:
        assert record.termination is SandboxTermination.LIMIT_BREACH
    finally:
        adapter.teardown(request.sandbox_id)


def test_single_execute_per_id(tmp_path):
    """قاعدة التنفيذ الواحد: نفس المعرف مرة ثانية → NOT_RUN صادق."""
    adapter = _adapter(tmp_path)
    request, _ = _request(
        tmp_path, sandbox_id="bw-once-1", code="print('once')"
    )
    first = adapter.execute(request)
    try:
        assert first.termination is SandboxTermination.COMPLETED
        second = adapter.execute(request)
        assert second.termination is SandboxTermination.NOT_RUN
        assert second.executed is False
    finally:
        adapter.teardown(request.sandbox_id)


def test_env_allowlist_enforced(tmp_path):
    """بيئة الركيزة: أسماء خارج المسموح → رفض صادق (لا قيم من الطلب)."""
    adapter = _adapter(tmp_path)
    request, _ = _request(
        tmp_path, sandbox_id="bw-env-1", code="print('x')",
        env_names=frozenset({"PATH", "LD_PRELOAD"}),
    )
    record = adapter.execute(request)
    assert record.termination is SandboxTermination.NOT_RUN
    assert record.executed is False
    evidence = adapter.execution_evidence("bw-env-1")
    assert "permitted set" in str(evidence.get("failure_reason", ""))


def test_teardown_attestation_complete(tmp_path):
    """التفكيك دائمًا: العملية زالت + لا بقايا مجموعة + مجلد التشغيل أزيل."""
    adapter = _adapter(tmp_path)
    request, _ = _request(
        tmp_path, sandbox_id="bw-teardown-1", code="print('bye')"
    )
    record = adapter.execute(request)
    assert record.termination is SandboxTermination.COMPLETED
    evidence = adapter.execution_evidence("bw-teardown-1")
    teardown = evidence.get("teardown") or {}
    assert teardown.get("proc_gone") is True
    assert teardown.get("pgid_members_remaining") == 0
    assert teardown.get("rootfs_removed") is True
    # teardown بعد الانتهاء idempotent ولا يرفع استثناء
    result = adapter.teardown("bw-teardown-1")
    assert result.torn_down is True
