"""جرد البيئة الفعلي (الأمر 009 §5) — لا افتراض لأي عنصر.

كل عنصر يُكتشف فعليًا: نظام/معمارية/CPU/RAM/قرص/Python/Node/npm/
pip/Git/قشدة/Docker/متصفح/شبكة — مع إصدار ونتيجة فحص وسبب فشل
وطابع زمني. عنصر غائب = UNAVAILABLE بسبب صريح، لا صمت.
"""

from __future__ import annotations

import datetime as _dt
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _item(status: str, version: str = "", reason: str = "",
          extra: dict | None = None) -> dict:
    return {
        "status": status,        # READY | NOT_READY | UNAVAILABLE
        "version": version,
        "reason": reason,
        "checked_at": _utc_now_iso(),
        "details": extra or {},
    }


def _cmd_version(args: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=8
        )
        out = (proc.stdout or proc.stderr or "").strip().splitlines()
        return proc.returncode == 0, (out[0] if out else "")
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def environment_inventory() -> dict:
    """الجرد الكامل لحظة الطلب — كل قيمة مقروءة فعليًا."""
    items: dict[str, dict] = {}

    items["os"] = _item(
        "READY", f"{platform.system()} {platform.release()} "
        f"({platform.machine()})",
    )
    items["python"] = _item("READY", sys.version.split()[0], extra={
        "executable": sys.executable,
    })

    # CPU/RAM/قرص — قراءة فعلية لا تخمين
    try:
        cpu = os.cpu_count() or 1
        items["cpu"] = _item("READY", f"{cpu} نواة")
    except Exception as error:  # noqa: BLE001
        items["cpu"] = _item("NOT_READY", reason=str(error))

    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    items["ram"] = _item(
                        "READY", f"{kb // (1024 * 1024)} GB تقريبًا")
                    break
            else:
                items["ram"] = _item("NOT_READY", reason="تعذر قراءة /proc")
    except OSError:
        items["ram"] = _item("UNAVAILABLE", reason="لا /proc في هذه المنصة")

    try:
        usage = shutil.disk_usage(os.getcwd())
        items["disk"] = _item(
            "READY",
            f"حر {usage.free // (1024 ** 3)} GB من "
            f"{usage.total // (1024 ** 3)} GB",
        )
    except OSError as error:
        items["disk"] = _item("NOT_READY", reason=str(error))

    # الأدوات — اكتشاف فعلي (013.1 §11: podman أيضًا — لا افتراض)
    for name, args in (
        ("git", ["git", "--version"]),
        ("pip", ["pip", "--version"]),
        ("node", ["node", "--version"]),
        ("npm", ["npm", "--version"]),
        ("docker", ["docker", "--version"]),
        ("podman", ["podman", "--version"]),
    ):
        ok, version = _cmd_version(args)
        items[name] = (
            _item("READY", version) if ok
            else _item("UNAVAILABLE", reason="غير مثبت في PATH")
        )

    # قشدة التنفيذ — shell حقيقي
    ok, version = _cmd_version([os.environ.get("SHELL", "/bin/sh"), "-c",
                                "echo ok"])
    items["shell"] = (
        _item("READY", os.environ.get("SHELL", "/bin/sh"))
        if ok else _item("NOT_READY", reason="تعذر تنفيذ قشدة")
    )

    # متصفح ميكانيكي (013 added Playwright+Chromium) — (013.1 §11)
    # جرد صادق: الكذب ممنوع في الاتجاهين — لا UNAVAILABLE كاذبة بعد
    # إضافة المتصفح الحقيقي، ولا READY بلا اكتشاف فعلي للمحرك.
    try:
        from browser.provider import DEFAULT_PROVIDER

        available, why = DEFAULT_PROVIDER.available()
        items["browser_runtime"] = _item(
            "READY" if available else "NOT_READY",
            version="playwright-chromium" if available else "",
            reason="" if available else (why or "Chromium غير متاح"),
            extra={"provider": "playwright", "engine": "chromium"},
        )
    except Exception as error:  # noqa: BLE001 — بلا متصفح لا نكذب جاهزية
        items["browser_runtime"] = _item(
            "UNAVAILABLE",
            reason=f"تعذر فحص مزود المتصفح: {error}",
        )

    # قدرة الافتراضية (VM) — فحص فعلي لا تخمين (013.1 §11)
    vm_ready = os.access("/dev/kvm", os.R_OK)
    vm_reason = "/dev/kvm متاح" if vm_ready else (
        "لا برامج افتراضية (kvm/qemu/virtualbox) قابلة للاستخدام"
    )
    if not vm_ready:
        for vm_bin in ("qemu-system-x86_64", "VBoxManage"):
            if shutil.which(vm_bin):
                vm_ready = True
                vm_reason = f"{vm_bin} مثبت"
                break
    items["vm"] = _item(
        "READY" if vm_ready else "UNAVAILABLE",
        version=vm_reason if vm_ready else "",
        reason="" if vm_ready else vm_reason,
    )

    # الشبكة — فحص فعلي (لا قراءة إعدادات فقط)
    from readiness import probes

    dns = probes.probe_dns()
    items["network_dns"] = _item(
        dns.status, reason=dns.reason, extra=dns.details)
    https = probes.probe_https()
    items["network_https"] = _item(
        https.status, reason=https.reason, extra=https.details)
    items["network"] = _item(
        "READY" if dns.status == "READY" and https.status == "READY"
        else "NOT_READY",
        reason="خارجي يعمل" if dns.status == "READY"
        and https.status == "READY"
        else "الاتصال الخارجي متعذر الآن",
    )

    # المستودع — وصول فعلي
    repo = probes.probe_repository()
    items["repository_access"] = _item(
        repo.status, reason=repo.reason, extra=repo.details)

    # سجل الحزم — حل فعلي (بلا تثبيت)
    pypi = probes.probe_dns("pypi.org")
    items["package_registries"] = _item(
        pypi.status,
        version="pypi.org",
        reason=pypi.reason,
        extra=pypi.details,
    )

    # البروكسي إن ضُبط
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    items["proxy"] = _item(
        "READY" if not proxy else "READY",
        version=proxy or "غير مضبوط",
    )

    # تنفيذ العمليات والملفات (013.1 §11) — فحص فعلي صغير لا افتراض
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            probe_file = Path(tmp) / "rw.txt"
            probe_file.write_text("ok", encoding="utf-8")
            fs_ok = probe_file.read_text(encoding="utf-8") == "ok"
        items["filesystem"] = _item(
            "READY" if fs_ok else "NOT_READY",
            version="قراءة/كتابة",
            reason="" if fs_ok else "تعذرت الكتابة والقراءة",
        )
    except OSError as error:
        items["filesystem"] = _item("NOT_READY", reason=str(error))

    proc = subprocess.run(
        [sys.executable, "-c", "print('ok')"],
        capture_output=True, text=True, timeout=10,
    )
    items["process_execution"] = _item(
        "READY" if proc.returncode == 0
        and proc.stdout.strip() == "ok" else "NOT_READY",
        version=f"Python {sys.version.split()[0]}",
        reason="" if proc.returncode == 0 else proc.stderr[:200],
    )

    return {
        "checked_at": _utc_now_iso(),
        "items": items,
        "summary": {
            "ready": sum(1 for v in items.values() if v["status"] == "READY"),
            "not_ready": sum(
                1 for v in items.values() if v["status"] == "NOT_READY"),
            "unavailable": sum(
                1 for v in items.values() if v["status"] == "UNAVAILABLE"),
        },
    }
