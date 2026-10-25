"""جرد البيئة الفعلي (الأمر 009 §5) — لا افتراض لأي عنصر.

كل عنصر يُكتشف فعليًا: نظام/معمارية/CPU/RAM/قرص/Python/Node/npm/
pip/Git/قشدة/Docker/متصفح/شبكة — مع إصدار ونتيجة فحص وسبب فشل
وطابع زمني. عنصر غائب = UNAVAILABLE بسبب صريح، لا صمت.

(AES-EXP-03 P1) عقد المهلة: كل عنصر له حد زمني معلن، والمسبارات
الشبكية تعمل عبر ``probes.run_bounded`` — المسار يعيد نتيجة محددة
ضمن ميزانية معلومة (``budget_seconds`` في الرد) أو يعلن التعذر
بسبب صريح، بدل التعليق غير المحدود. لا معلومة تُحذف: تجاوز المهلة
هو نفسه معلومة تُعرض مع سببها.
"""

from __future__ import annotations

import datetime as _dt
import os
import platform
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from readiness import probes
from readiness.probes import run_bounded

#: مهلة كشف كل أداة PATH (ثوان) — الفحوص الستة تعمل متوازية
#: فأسوأ حالة مجموعها ≈ هذه المهلة لا مجموعها المتسلسل.
TOOL_PROBE_TIMEOUT = 8.0
#: مهلة فحص مزود المتصفح (تشغيل درايفر Playwright)
BROWSER_PROBE_TIMEOUT = 10.0
#: مهلة مسبار HTTPS (اتصال + قراءة)
HTTPS_PROBE_TIMEOUT = 12.0
#: مهلة مسبار وصول المستودع
REPO_PROBE_TIMEOUT = 8.0
#: مهلة تنفيذ عملية بايثون صغيرة
PROCESS_PROBE_TIMEOUT = 10.0
#: أسوأ ميزانية كلية معلنة للرد (مجموع الحدود بمسار متوازٍ معقول)
BUDGET_SECONDS = (
    TOOL_PROBE_TIMEOUT + BROWSER_PROBE_TIMEOUT + HTTPS_PROBE_TIMEOUT
    + probes.DNS_RESOLVE_TIMEOUT + REPO_PROBE_TIMEOUT
    + PROCESS_PROBE_TIMEOUT + 8.0  # القشدة
)


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


def _bounded_probe_item(label: str, fn, timeout: float) -> dict:
    """مسبار محدود الزمن — نتيجة صريحة عند النجاح/الفشل/تجاوز المهلة.

    (AES-EXP-03 P1) تجاوز المهلة ليس صمتًا ولا تعليقًا: عنصر
    NOT_READY بسبب معلن «تجاوز مهلة الفحص» — والمعلومة كاملة محفوظة.
    """
    try:
        bounded, result = run_bounded(fn, timeout)
    except Exception as error:  # noqa: BLE001 — الفشل نتيجة لا انهيار
        return _item("NOT_READY", reason=f"فشل فحص {label}: {error}")
    if not bounded:
        return _item(
            "NOT_READY",
            reason=f"تجاوز فحص {label} مهلة {timeout:.0f}ث — العنصر "
                   "لا يستجيب الآن",
            extra={"timeout_s": timeout},
        )
    return result


def _tool_versions() -> dict[str, dict]:
    """كشف الأدوات الست متوازيًا — كل أداة بمهلتها الصارمة الخاصة."""
    tools = {
        "git": ["git", "--version"],
        "pip": ["pip", "--version"],
        "node": ["node", "--version"],
        "npm": ["npm", "--version"],
        "docker": ["docker", "--version"],
        "podman": ["podman", "--version"],
    }

    def one(name: str, args: list[str]) -> tuple[str, dict]:
        ok, version = _cmd_version(args)
        return name, (
            _item("READY", version) if ok
            else _item("UNAVAILABLE", reason="غير مثبت في PATH")
        )

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(tools),
                            thread_name_prefix="inv-tool") as pool:
        futures = [pool.submit(one, name, args)
                   for name, args in tools.items()]
        for future in futures:
            name, item = future.result(timeout=TOOL_PROBE_TIMEOUT + 2)
            out[name] = item
    return out


def environment_inventory() -> dict:
    """الجرد الكامل لحظة الطلب — كل قيمة مقروءة فعليًا وبحد زمني معلن."""
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

    # الأدوات — اكتشاف فعلي متوازٍ (013.1 §11: podman أيضًا — لا افتراض)
    items.update(_tool_versions())

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
    def _browser_check() -> dict:
        from browser.provider import DEFAULT_PROVIDER

        available, why = DEFAULT_PROVIDER.available()
        return _item(
            "READY" if available else "NOT_READY",
            version="playwright-chromium" if available else "",
            reason="" if available else (why or "Chromium غير متاح"),
            extra={"provider": "playwright", "engine": "chromium"},
        )

    items["browser_runtime"] = _bounded_probe_item(
        "مزود المتصفح", _browser_check, BROWSER_PROBE_TIMEOUT)

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

    # الشبكة — فحص فعلي محدود (لا قراءة إعدادات فقط، ولا تعليق)
    dns = probes.probe_dns()
    items["network_dns"] = _item(
        dns.status, reason=dns.reason, extra=dns.details)

    def _https_check():
        result = probes.probe_https()
        return _item(result.status, reason=result.reason,
                     extra=result.details)

    https = _bounded_probe_item(
        "HTTPS", _https_check, HTTPS_PROBE_TIMEOUT)
    items["network_https"] = https
    dns_ready = dns.status == "READY"
    https_ready = https["status"] == "READY"
    items["network"] = _item(
        "READY" if dns_ready and https_ready else "NOT_READY",
        reason="خارجي يعمل" if dns_ready and https_ready
        else "الاتصال الخارجي متعذر الآن",
    )

    # المستودع — وصول فعلي محدود
    def _repo_check():
        result = probes.probe_repository()
        return _item(result.status, reason=result.reason,
                     extra=result.details)

    items["repository_access"] = _bounded_probe_item(
        "وصول المستودع", _repo_check, REPO_PROBE_TIMEOUT)

    # سجل الحزم — حل فعلي (بلا تثبيت) — probe_dns محدود داخليًا الآن
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

    # (AES-EXP-03 P1) كان الاستدعاء مكشوفًا بلا معالجة — مهلة أو خطأ
    # نظامي كان يرفع 500 بدل نتيجة صادقة. الآن: فشل = NOT_READY بسبب.
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "print('ok')"],
            capture_output=True, text=True, timeout=PROCESS_PROBE_TIMEOUT,
        )
        proc_ok = proc.returncode == 0 and proc.stdout.strip() == "ok"
        items["process_execution"] = _item(
            "READY" if proc_ok else "NOT_READY",
            version=f"Python {sys.version.split()[0]}",
            reason="" if proc_ok else (proc.stderr or "")[:200],
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        items["process_execution"] = _item(
            "NOT_READY",
            version=f"Python {sys.version.split()[0]}",
            reason=f"تعذر تنفيذ عملية بايثون: {error}",
        )

    return {
        "checked_at": _utc_now_iso(),
        "budget_seconds": BUDGET_SECONDS,
        "items": items,
        "summary": {
            "ready": sum(1 for v in items.values() if v["status"] == "READY"),
            "not_ready": sum(
                1 for v in items.values() if v["status"] == "NOT_READY"),
            "unavailable": sum(
                1 for v in items.values() if v["status"] == "UNAVAILABLE"),
        },
    }
