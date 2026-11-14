#!/usr/bin/env python3
"""AES-FACTORY-RELEASE-READINESS-002 §2 — runner-side substrate diagnostic.

خطوة تشخيص صادقة على عدّاء CI — مرصد لا اختبار:

1. يطبع قدرات الركيزة الحقيقية (بوابة userns الحقيقية).
2. يعيد تسلسل namespaces الخاص بالمُطلِق خطوة-بخطوة داخل عملية هذا
   السكربت نفسه (عملية إدامة يُرمى بعد الخروج) ويطبع نتيجة كل نداء
   مع errno — أي خطوة تُفشل تظهر باسمها ورمز خطئها فورًا.
3. ينفّذ طلب رمل حقيقي واحد عبر المحوّل الإنتاجي (نفس المسار الذي
   تمر به الاختبارات) ويطبع السجل والأدلة والمخارج المحفوظة كاملة —
   فيظهر «SANDBOX-INIT-ERROR at <step>» الحقيقي إن وُجد.

الخطوة لا تُخفي اختبارًا ولا تُغيّر نتيجة المجموعة؛ في الـ workflow
تعمل بـ continue-on-error فتبقى مرصدًا خالصًا (لا بوابة).
"""
from __future__ import annotations

import ctypes
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

# ---------------------------------------------------------------- #
# القسم 1: قدرات الركيزة (البوابة الحقيقية)
# ---------------------------------------------------------------- #
from substrate.factory import substrate_capabilities_report

print("[diag] === substrate capabilities report ===", flush=True)
print(json.dumps(
    substrate_capabilities_report(), ensure_ascii=False, indent=2,
    default=str,
), flush=True)

# ---------------------------------------------------------------- #
# القسم 2: تسلسل المُطلِق خطوة-بخطوة (errno صريح لكل نداء)
# ---------------------------------------------------------------- #
MS_BIND = 4096
MS_REC = 16384
MS_SLAVE = 1 << 19
CLONE_NEWNS = 0x00020000
CLONE_NEWUTS = 0x04000000
CLONE_NEWUSER = 0x10000000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000

libc = ctypes.CDLL(None, use_errno=True)
libc.unshare.restype = ctypes.c_int
libc.unshare.argtypes = [ctypes.c_int]


def _step(label: str, ok: bool, errno: int | None = None) -> bool:
    suffix = "" if ok else f"  errno={errno} ({os.strerror(errno) if errno else '?'})"
    print(f"[diag] launcher-step {label}: {'OK' if ok else 'FAIL'}{suffix}", flush=True)
    return ok


print("[diag] === launcher sequence, step by step ===", flush=True)
# التسلسل يُنفَّذ في ابنٍ مُشوَّق — العملية الأم تبقى نظيفة تمامًا
# للقسم 3 (تنفيذ المحوّل الحقيقي لا يجري داخل userns متشابك).
_sequence_pid = os.fork()
if _sequence_pid == 0:  # ابن التشخيص — يُخرج 0 نجاحًا و1 فشلًا
    _sequence_failed = False
    try:
        # uid/gid يجب التقاطهما قبل unshare — بعد unshare(CLONE_NEWUSER)
        # يعيد getuid() رقم overflow (65534) لأن uid المضيف غير مُعرَّف
        # في الـ userns الجديد، وخريطة "0 65534 1" تُرفض EPERM حتمًا.
        # المُطلِق الإنتاجي يلتقط _REAL_UID عند import الوحدة (قبل
        # unshare) — هنا نفس العقد.
        _uid, _gid = os.getuid(), os.getgid()
        rc = libc.unshare(CLONE_NEWUSER)
        if not _step("unshare(CLONE_NEWUSER)", rc == 0, ctypes.get_errno()):
            _sequence_failed = True

        if not _sequence_failed:
            try:
                with open("/proc/self/setgroups", "w") as h:
                    h.write("deny")
                _step("setgroups deny", True)
            except OSError as e:
                _step("setgroups deny", False, e.errno)
                _sequence_failed = True
        if not _sequence_failed:
            try:
                with open("/proc/self/uid_map", "w") as h:
                    h.write(f"0 {_uid} 1\n")
                with open("/proc/self/gid_map", "w") as h:
                    h.write(f"0 {_gid} 1\n")
                _step("uid_map/gid_map", True)
            except OSError as e:
                _step("uid_map/gid_map", False, e.errno)
                _sequence_failed = True

        if not _sequence_failed:
            for label, flag in (
                ("unshare(CLONE_NEWUTS)", CLONE_NEWUTS),
                ("unshare(CLONE_NEWNET)", CLONE_NEWNET),
                ("unshare(CLONE_NEWNS)", CLONE_NEWNS),
                ("unshare(CLONE_NEWPID)", CLONE_NEWPID),
            ):
                rc = libc.unshare(flag)
                if not _step(label, rc == 0, ctypes.get_errno()):
                    _sequence_failed = True
                    break

        if not _sequence_failed:
            libc.sethostname.restype = ctypes.c_int
            libc.sethostname.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
            hostname = b"aes-diag"
            if not _step(
                "sethostname",
                libc.sethostname(hostname, len(hostname)) == 0,
                ctypes.get_errno(),
            ):
                _sequence_failed = True
    finally:
        os._exit(1 if _sequence_failed else 0)

_, _sequence_status = os.waitpid(_sequence_pid, 0)
_sequence_ok = os.WIFEXITED(_sequence_status) and os.WEXITSTATUS(_sequence_status) == 0
if _sequence_ok:
    print("[diag] launcher-side sequence complete OK", flush=True)
else:
    print("[diag] sequence stopped at the failing step above", flush=True)

# ---------------------------------------------------------------- #
# القسم 3: تنفيذ رمل حقيقي واحد عبر المحوّل الإنتاجي (نفس مسار الأدوات)
# ---------------------------------------------------------------- #
print("[diag] === one REAL adapter execution ===", flush=True)
try:
    from substrate.limits import E1_LIMITS_DEFAULTS
    from substrate.local_substrate import (
        LocalSubstrateAdapter,
        default_local_images,
    )
    from substrate.sandbox import NetworkMode, SandboxRequest

    image_name = next(iter(default_local_images()))
    image = default_local_images()[image_name]
    print(f"[diag] image: {image_name}", flush=True)
    print(f"[diag] interpreter: {image.interpreter}", flush=True)
    print(f"[diag] read_only_roots: {image.read_only_roots}", flush=True)

    adapter = LocalSubstrateAdapter()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="aes-diag-"))
    (tmp / "ws").mkdir(parents=True, exist_ok=True)
    (tmp / "art").mkdir(parents=True, exist_ok=True)
    request = SandboxRequest(
        sandbox_id="ci-diag-1",
        image=image_name,
        command=("python", "-c", "print('SANDBOX-DIAG-OK')"),
        limits=E1_LIMITS_DEFAULTS,
        env_names=frozenset({"PATH"}),
        network=NetworkMode.NONE,
        workspace_root=str(tmp / "ws"),
        artifacts_dir=str(tmp / "art"),
    )
    record = adapter.execute(request)
    print(
        f"[diag] termination={record.termination} "
        f"exit_code={record.exit_code} executed={record.executed}",
        flush=True,
    )
    evidence = adapter.execution_evidence("ci-diag-1")
    print(
        "[diag] evidence: " + json.dumps(
            evidence, ensure_ascii=False, indent=2, default=str
        ),
        flush=True,
    )
    for label, ref in (
        ("stdout", record.stdout_reference),
        ("stderr", record.stderr_reference),
    ):
        print(f"[diag] {label}_reference: {ref!r}", flush=True)
        path = pathlib.Path(str(ref)) if ref else None
        if path is not None and path.is_file():
            print(
                f"[diag] {label} content:\n"
                + path.read_text(errors="replace")[:2000],
                flush=True,
            )
        else:
            print(f"[diag] {label} content: (no persisted file)", flush=True)
except Exception as error:  # noqa: BLE001 — التشخيص يطبع ولا يرفع
    print(
        f"[diag] adapter execution could not run: "
        f"{type(error).__name__}: {error}",
        flush=True,
    )

print("[diag] === diagnostic end (observability only) ===", flush=True)
