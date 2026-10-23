"""مسبارات الجاهزية الحقيقية (الأمر 009 §6-§15) — لا جاهزية بلا دليل.

كل مسبار استدعاء فعلي: DNS حقيقي، HTTPS حقيقي، بحث حقيقي يفحص
قابلية النتائج للتحليل (نجاح النقل ≠ نتيجة صالحة §4)، ركيزة تُقلع
فعلًا وتكتب وتقرأ وتنفذ، git حقيقي، ملفات حقيقية، واستدلال LLM
بتوكن واحد. ممنوع (§27): «التكوين موجود = READY» و«HTTP 200 = أداة».

كل مسبار قابل للحقن في الاختبارات (fetch/runner) — الاختبار يمر
بالمسار الحقيقي نفسه بمصادر مضبوطة.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

#: عناوين الفحص — مصادر موثوقة مستقرة، لا خدمة خاصة.
DNS_PROBE_HOST = "example.com"
HTTPS_PROBE_URL = "https://example.com"
HTTP_PROBE_URL = "http://example.com"
WEB_SEARCH_PROBE_QUERY = "open source python"

#: مهل المسبارات (ثوان) — قصيرة: الفحص خفيف أو مفشَّل سريعًا.
PROBE_TIMEOUT = 8.0

#: مهلة حل أسماء DNS (ثوان) — ``socket.gethostbyname`` لا يقبل مهلة
#: أصلًا، فالتقييد بخيط حاجب بحد زمني صارم عبر ``run_bounded``.
#: هذا هو الجذر المثبّت لتعليق ``GET /api/environment/inventory``
#: الموثق في AES-EXP-01: مُحلِّل بطيء كان يجمّد مسار الطلب عشرات
#: الثواني بلا سقف. النداء لا يُحتجز أبعد من هذا الحد.
DNS_RESOLVE_TIMEOUT = 5.0


def run_bounded(fn: Callable[[], Any],
                timeout: float) -> tuple[bool, Any]:
    """تشغيل دالة حاجبة بحد زمني صارم — خيط daemon + صندوق نتيجة.

    الخيط لا يُقتل (بايثون لا تسمح) لكنه daemon فلا يمنع الإطفاء،
    والنداء يستعيد السيطرة فور انتهاء المهلة — وهذا عقد المسبارات:
    الفحص خفيف أو مفشَّل سريعًا (رأس الملف §0). يعيد زوجًا:
    ``(True, نتيجة)`` عند الإتمام، و``(False, None)`` عند تجاوز
    المهلة، ويُعاد رفع استثناء الدالة كما هو إن حدث بعد الإتمام.
    """
    box: dict = {}

    def _target() -> None:
        try:
            box["result"] = fn()
        except BaseException as error:  # noqa: BLE001 — يُعاد للنداء
            box["error"] = error

    worker = threading.Thread(target=_target, daemon=True,
                              name="aes-bounded-probe")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return False, None
    if "error" in box:
        raise box["error"]
    return True, box.get("result")

#: TTL افتراضي لكل عائلة (§24) — الجاهزية تنتهي لا تدوم.
TTL_DEFAULTS = {
    "LLM": 600, "WEB": 120, "NETWORK": 120, "SANDBOX": 300,
    "FILESYSTEM": 600, "GIT": 600, "SHELL": 3600, "TESTING": 3600,
    "BUILD": 3600, "REPOSITORY": 600, "PERSISTENCE": 600,
    "ARTIFACTS": 600, "OBSERVABILITY": 300,
}


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


@dataclass
class ProbeResult:
    """نتيجة مسبار واحد — status من READINESS_STATUSES حصرًا."""

    status: str                     # READY | DEGRADED | NOT_READY | UNAVAILABLE
    reason: str = ""
    latency_ms: int = 0
    checked_at: str = ""
    expires_at: str = ""
    ttl_seconds: int = 300
    failure_class: str = ""
    failure_stage: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status, "reason": self.reason,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at, "expires_at": self.expires_at,
            "ttl_seconds": self.ttl_seconds,
            "failure_class": self.failure_class,
            "failure_stage": self.failure_stage,
            "details": self.details,
        }


def _finish(status: str, reason: str, started: float, ttl: int,
            failure_class: str = "", failure_stage: str = "",
            details: dict | None = None) -> ProbeResult:
    now = _utc_now()
    return ProbeResult(
        status=status, reason=reason,
        latency_ms=int((time.monotonic() - started) * 1000),
        checked_at=now.isoformat(),
        expires_at=(now + _dt.timedelta(seconds=ttl)).isoformat()
        if status == "READY" else "",
        ttl_seconds=ttl,
        failure_class=failure_class, failure_stage=failure_stage,
        details=details or {},
    )


# ------------------------------------------------------------------ #
# الشبكة: DNS / HTTPS / بحث حقيقي (§6)
# ------------------------------------------------------------------ #

def probe_dns(host: str = DNS_PROBE_HOST,
              timeout: float | None = None) -> ProbeResult:
    """فحص resolve حقيقي — لا افتراض توفر، وبحد زمني صارم (§6).

    (AES-EXP-03 P1) كان الحل عبر ``gethostbyname`` بلا مهلة — دالة
    حاجبة لا تقبل سقفًا؛ الآن الحل داخل خيط محدود ``DNS_RESOLVE_TIMEOUT``
    فالمسبار يفشل بوضوح بدل أن يجمّد مسار الطلب. المهلة تُقرأ وقت
    الاستدعاء (لا وقت الاستيراد) فالضبط والاختبار يغيرانها بفعالية.
    """
    if timeout is None:
        timeout = DNS_RESOLVE_TIMEOUT
    started = time.monotonic()
    try:
        bounded, addr = run_bounded(
            lambda: socket.gethostbyname(host), timeout)
    except OSError as error:
        return _finish("NOT_READY", f"تعذر حل {host}: {error}", started,
                       TTL_DEFAULTS["NETWORK"],
                       failure_class="NETWORK_FAILURE",
                       failure_stage="TOOL_EXECUTION", details={"host": host})
    if not bounded:
        return _finish(
            "NOT_READY",
            f"تجاوز حل {host} مهلة {timeout:.0f}ث — المُحلِّل لا يستجيب",
            started, TTL_DEFAULTS["NETWORK"], failure_class="TIMEOUT",
            failure_stage="TOOL_EXECUTION",
            details={"host": host, "timeout_s": timeout})
    return _finish("READY", f"حلّ {host} ← {addr}", started,
                   TTL_DEFAULTS["NETWORK"], details={"host": host,
                                                      "address": addr})


def probe_https(url: str = HTTPS_PROBE_URL,
                fetch: Callable[..., Any] | None = None) -> ProbeResult:
    """اتصال HTTPS حقيقي — حالة/نوع محتوى/حجم."""
    started = time.monotonic()
    getter = fetch or urllib.request.urlopen
    try:
        with getter(url, timeout=PROBE_TIMEOUT) as response:  # type: ignore[call-arg]
            body = response.read(2048)
            return _finish(
                "READY",
                f"HTTP {response.status} · {len(body)} بايت مقروءة",
                started, TTL_DEFAULTS["NETWORK"],
                details={"url": url, "http_status": response.status,
                         "content_type": response.headers.get(
                             "Content-Type", "")},
            )
    except Exception as error:  # noqa: BLE001 — فشل مصنَّف صريح
        return _finish("NOT_READY", f"تعذر الوصول إلى {url}: {error}",
                       started, TTL_DEFAULTS["NETWORK"],
                       failure_class="NETWORK_FAILURE",
                       failure_stage="TOOL_EXECUTION", details={"url": url})


def probe_http_get(url: str = HTTP_PROBE_URL,
                   fetch: Callable[..., Any] | None = None) -> ProbeResult:
    """HTTP GET مباشر (منفذ 80) — منفصل عن HTTPS (010 §23).

    البنية قد تسمح بأحدهما دون الآخر (جدار يقطع 80 لا 443) —
    فالقدرتان مستقلتان لا «شبكة» واحدة.
    """
    started = time.monotonic()
    getter = fetch or urllib.request.urlopen
    try:
        with getter(url, timeout=PROBE_TIMEOUT) as response:  # type: ignore[call-arg]
            body = response.read(1024)
            return _finish(
                "READY", f"HTTP {response.status} · {len(body)} بايت",
                started, TTL_DEFAULTS["NETWORK"],
                details={"url": url, "http_status": response.status},
            )
    except Exception as error:  # noqa: BLE001
        return _finish(
            "NOT_READY", f"تعذر HTTP المباشر إلى {url}: {error}",
            started, TTL_DEFAULTS["NETWORK"],
            failure_class="NETWORK_FAILURE", failure_stage="TOOL_EXECUTION",
            details={"url": url},
        )


def probe_web_search(search_fn: Callable[[str], list] | None = None) -> ProbeResult:
    """بحث حقيقي (§6): طلب فعلًا ثم فحص النتائج — الوجود والتحليل.

    نجاح النقل لا يكفي: النتائج يجب أن تحمل حقولًا قابلة للتحليل
    (title/url/snippet) — وإلا DEGRADED/NOT_READY لا READY.
    """
    from roles.tool_failures import ToolFailure
    from roles import web_tools

    started = time.monotonic()
    search = search_fn or web_tools.web_search
    try:
        results = search(WEB_SEARCH_PROBE_QUERY)
        usable = [
            r for r in results
            if r.get("url", "").startswith("http") and r.get("title")
        ]
        if not usable:
            return _finish(
                "NOT_READY",
                f"نُقل البحث لكن بلا نتائج قابلة للتحليل "
                f"({len(results)} خامًا)",
                started, TTL_DEFAULTS["WEB"], failure_class="TOOL_FAILURE",
                failure_stage="TOOL_RESULT",
                details={"query": WEB_SEARCH_PROBE_QUERY,
                         "raw_count": len(results)},
            )
        return _finish(
            "READY" if len(usable) >= 3 else "DEGRADED",
            f"{len(usable)} نتيجة قابلة للتحليل",
            started, TTL_DEFAULTS["WEB"],
            details={"query": WEB_SEARCH_PROBE_QUERY,
                     "usable_count": len(usable),
                     "sample": usable[0].get("title", "")[:80]},
        )
    except ToolFailure as failure:
        return _finish(
            "NOT_READY", failure.human_summary(), started,
            TTL_DEFAULTS["WEB"], failure_class=failure.failure_class,
            failure_stage=failure.stage,
            details={"query": WEB_SEARCH_PROBE_QUERY,
                     "reason": failure.reason, **failure.details},
        )
    except Exception as error:  # noqa: BLE001
        return _finish("NOT_READY", f"فشل مسبار البحث: {error}", started,
                       TTL_DEFAULTS["WEB"], failure_class="UNKNOWN_FAILURE",
                       failure_stage="TOOL_EXECUTION")


def probe_web_fetch(fetch_fn: Callable[[str], str] | None = None) -> ProbeResult:
    """جلب صفحة موثوقة (§6): حالة/طول/نوع/تحليل — fetch حقيقي."""
    from roles.tool_failures import ToolFailure
    from roles import web_tools

    started = time.monotonic()
    fetch = fetch_fn or web_tools.fetch_page
    try:
        text = fetch(HTTPS_PROBE_URL)
        return _finish(
            "READY", f"جُلبت الصفحة واستُخلص منها {len(text)} حرفًا",
            started, TTL_DEFAULTS["WEB"],
            details={"url": HTTPS_PROBE_URL, "chars": len(text)},
        )
    except ToolFailure as failure:
        return _finish("NOT_READY", failure.human_summary(), started,
                       TTL_DEFAULTS["WEB"], failure_class=failure.failure_class,
                       failure_stage=failure.stage,
                       details={"url": HTTPS_PROBE_URL, "reason": failure.reason})
    except Exception as error:  # noqa: BLE001
        return _finish("NOT_READY", f"فشل مسبار الجلب: {error}", started,
                       TTL_DEFAULTS["WEB"], failure_class="UNKNOWN_FAILURE")


# ------------------------------------------------------------------ #
# ركيزة التنفيذ المعزولة (§11): إقلاع + كتابة + قراءة + أمر + مخرجات
# ------------------------------------------------------------------ #

def probe_sandbox() -> ProbeResult:
    """ركيزة حقيقية: صورة متاحة؟ تُقلع؟ تكتب وتقرأ وتنفذ وتلتقط؟"""
    started = time.monotonic()
    try:
        from substrate.local_substrate import (
            SubstrateUnavailable, default_local_images, local_sandbox_manager,
        )
        from substrate.limits import E1_LIMITS_DEFAULTS
        from substrate.sandbox import NetworkMode, SandboxRequest, SandboxTermination
    except Exception as error:  # noqa: BLE001 — الركيزة نفسها غير قابلة للاستيراد
        return _finish("UNAVAILABLE", f"الركيزة غير قابلة للاستيراد: {error}",
                       started, TTL_DEFAULTS["SANDBOX"],
                       failure_class="DEPENDENCY_FAILURE", failure_stage="STARTUP")

    try:
        images = default_local_images()
    except SubstrateUnavailable as error:
        return _finish(
            "UNAVAILABLE", f"لا صورة تنفيذ متاحة: {error}", started,
            TTL_DEFAULTS["SANDBOX"], failure_class="SANDBOX_FAILURE",
            failure_stage="STARTUP",
            details={"platform": f"{platform.system()}/{platform.machine()}"},
        )
    image = next(iter(images), None)
    if image is None:
        return _finish(
            "UNAVAILABLE",
            "لا صورة تنفيذ متاحة — الركيزة المعزولة تتطلب Linux/x86_64",
            started, TTL_DEFAULTS["SANDBOX"],
            failure_class="SANDBOX_FAILURE", failure_stage="STARTUP",
            details={"platform": f"{platform.system()}/{platform.machine()}"},
        )

    with tempfile.TemporaryDirectory(prefix="env-probe-") as tmp:
        workspace = Path(tmp) / "ws"
        artifacts = Path(tmp) / "art"
        workspace.mkdir()
        artifacts.mkdir()
        code = (
            "import pathlib\n"
            "p = pathlib.Path('/artifacts/probe.txt')\n"
            "p.write_text('sandbox-ready', encoding='utf-8')\n"
            "print('wrote:', p.read_text(encoding='utf-8'))\n"
        )
        try:
            manager = local_sandbox_manager(images={**images})
            request = SandboxRequest(
                sandbox_id=f"probe-{int(time.time())}",
                image=image,
                command=("python", "-c", code),
                limits=E1_LIMITS_DEFAULTS,
                env_names=frozenset({"PATH"}),
                network=NetworkMode.NONE,
                workspace_root=str(workspace),
                artifacts_dir=str(artifacts),
            )
            outcome = manager.execute(request)
        except Exception as error:  # noqa: BLE001
            return _finish("NOT_READY", f"تعذر إقلاع الركيزة: {error}",
                           started, TTL_DEFAULTS["SANDBOX"],
                           failure_class="SANDBOX_FAILURE", failure_stage="STARTUP")

        record = outcome.record
        if record is None or record.termination is not SandboxTermination.COMPLETED:
            return _finish(
                "NOT_READY",
                "الركيزة أقلعت لكن التنفيذ لم يكتمل: " +
                str(outcome.detail or "بلا تفصيل"),
                started, TTL_DEFAULTS["SANDBOX"],
                failure_class="SANDBOX_FAILURE", failure_stage="TOOL_EXECUTION",
            )
        stdout = ""
        try:
            stdout = Path(record.stdout_reference).read_text(
                encoding="utf-8", errors="replace"
            ) if record.stdout_reference else ""
        except OSError:
            pass
        artifact = artifacts / "probe.txt"
        return _finish(
            "READY" if artifact.is_file() and "sandbox-ready" in stdout
            else "DEGRADED",
            "ركيزة تعمل: إقلاع + كتابة + تنفيذ + التقاط مخرجات"
            if artifact.is_file() else
            "الركيزة نفّذت لكن الأداة لم تُكتب — وضع متدهور معلن",
            started, TTL_DEFAULTS["SANDBOX"],
            details={
                "image": str(image), "exit_code": record.exit_code,
                "stdout_head": stdout[:80],
                "artifact_persisted": artifact.is_file(),
            },
        )


# ------------------------------------------------------------------ #
# نظام الملفات والـgit والقشدة (§12-§14)
# ------------------------------------------------------------------ #

def probe_filesystem() -> ProbeResult:
    """إنشاء/قراءة/تعديل/حذف/التقاط أدلة — فعليًا داخل runtime/."""
    started = time.monotonic()
    root = Path("runtime") / "readiness-probes"
    try:
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"probe-{int(time.time())}.txt"
        target.write_text("first", encoding="utf-8")
        first = target.read_text(encoding="utf-8")
        target.write_text("modified", encoding="utf-8")
        modified = target.read_text(encoding="utf-8")
        target.unlink()
        ok = first == "first" and modified == "modified" and not target.exists()
        return _finish(
            "READY" if ok else "DEGRADED",
            "إنشاء/قراءة/تعديل/حذف تعمل فعليًا"
            if ok else "عمليات الملفات جزئية — متدهور معلن",
            started, TTL_DEFAULTS["FILESYSTEM"],
            details={"root": str(root)},
        )
    except OSError as error:
        return _finish("NOT_READY", f"تعذر الوصول لنظام الملفات: {error}",
                       started, TTL_DEFAULTS["FILESYSTEM"],
                       failure_class="DEPENDENCY_FAILURE", failure_stage="TOOL_EXECUTION")


def _run_cmd(args: list[str], cwd: str | None = None,
             timeout: float = PROBE_TIMEOUT) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        return proc.returncode, (proc.stdout or proc.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, str(error)


def probe_git() -> ProbeResult:
    """git حقيقي: إصدار + حالة + سجل + فرع (§12)."""
    started = time.monotonic()
    code, version = _run_cmd(["git", "--version"])
    if code != 0:
        return _finish("NOT_READY", f"git غير متاح: {version}", started,
                       TTL_DEFAULTS["GIT"], failure_class="DEPENDENCY_FAILURE",
                       failure_stage="TOOL_START")
    _, status = _run_cmd(["git", "status", "--short"])
    _, branch = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    _, head = _run_cmd(["git", "log", "-1", "--format=%h %s"])
    return _finish(
        "READY", f"{version} · فرع {branch or '—'}",
        started, TTL_DEFAULTS["GIT"],
        details={"version": version, "branch": branch,
                 "head": head[:80], "dirty": bool(status)},
    )


def probe_repository() -> ProbeResult:
    """وصول المستودع: موجود؟ قابل للقراءة؟ آخر التزام؟"""
    started = time.monotonic()
    repo = Path(__file__).resolve().parents[2]
    if not (repo / ".git").exists():
        return _finish("UNAVAILABLE", "لا مستودع git في جذر المشروع",
                       started, TTL_DEFAULTS["REPOSITORY"],
                       failure_class="DEPENDENCY_FAILURE")
    code, head = _run_cmd(["git", "log", "-1", "--format=%H"], cwd=str(repo))
    if code != 0:
        return _finish("NOT_READY", f"تعذر قراءة سجل المستودع: {head}",
                       started, TTL_DEFAULTS["REPOSITORY"],
                       failure_class="DEPENDENCY_FAILURE")
    return _finish("READY", f"المستودع متاح · آخر التزام {head[:10]}",
                   started, TTL_DEFAULTS["REPOSITORY"],
                   details={"path": str(repo), "head": head[:16]})


def probe_shell(command: str = "python") -> ProbeResult:
    """اكتشاف قشدة حقيقي — إصدار فعلي لا افتراض (§5)."""
    started = time.monotonic()
    code, out = _run_cmd([command, "--version"])
    if code != 0:
        return _finish("UNAVAILABLE", f"{command} غير موجود: {out[:80]}",
                       started, TTL_DEFAULTS["SHELL"],
                       failure_class="DEPENDENCY_FAILURE", failure_stage="STARTUP")
    return _finish("READY", out[:90], started, TTL_DEFAULTS["SHELL"],
                   details={"version": out[:120]})


def probe_package_management() -> ProbeResult:
    """مدير الحزم: pip متاح؟ السجل قابل للوصول (DNS فقط — لا تثبيت §14)."""
    started = time.monotonic()
    code, version = _run_cmd(["pip", "--version"])
    if code != 0:
        return _finish("UNAVAILABLE", "pip غير متاح", started,
                       TTL_DEFAULTS["PACKAGE_MANAGEMENT"]
                       if "PACKAGE_MANAGEMENT" in TTL_DEFAULTS
                       else TTL_DEFAULTS["SHELL"],
                       failure_class="DEPENDENCY_FAILURE")
    registry = probe_dns("pypi.org")
    if registry.status != "READY":
        return _finish(
            "DEGRADED", f"{version.splitlines()[0][:60]} · سجل الحزم "
            "غير قابل للحل الآن",
            started, TTL_DEFAULTS["NETWORK"],
            details={"pip": version[:80],
                     "registry": registry.to_dict()},
        )
    return _finish("READY", version.splitlines()[0][:80], started,
                   TTL_DEFAULTS["SHELL"],
                   details={"pip": version[:80], "registry": "pypi.org قابل للحل"})


def probe_testing() -> ProbeResult:
    """إطار الاختبارات متاح فعليًا — إصدار pytest (§14: بلا تشغيل عشوائي)."""
    started = time.monotonic()
    code, out = _run_cmd([str(Path("runtime") / ".venv-python"
                             if False else "python"), "-m", "pytest", "--version"])
    if code != 0:
        return _finish("UNAVAILABLE", f"pytest غير متاح: {out[:80]}", started,
                       TTL_DEFAULTS["TESTING"], failure_class="DEPENDENCY_FAILURE")
    return _finish("READY", out.splitlines()[0][:80], started,
                   TTL_DEFAULTS["TESTING"], details={"version": out[:120]})


def probe_build() -> ProbeResult:
    """أدوات البناء المكتشفة فعليًا — لا افتراض."""
    started = time.monotonic()
    found = {}
    for tool in ("python", "pip"):
        code, out = _run_cmd([tool, "--version"])
        found[tool] = out[:60] if code == 0 else None
    if not any(found.values()):
        return _finish("UNAVAILABLE", "لا أداة بناء مكتشفة", started,
                       TTL_DEFAULTS["BUILD"], failure_class="DEPENDENCY_FAILURE")
    return _finish("READY", "أدوات البناء: " + ", ".join(
        k for k, v in found.items() if v), started, TTL_DEFAULTS["BUILD"],
        details=found)


def probe_persistence() -> ProbeResult:
    """القاعدة تقبل الكتابة والقراءة فعليًا — صف مسبار يُكتب ويُحذف."""
    started = time.monotonic()
    try:
        from api import routes  # noqa: PLC0415 — جلسة العملية الوحيدة

        sessions = routes._sessions
        from persistence.models import Event  # noqa: PLC0415
        marker = f"readiness-probe-{int(time.time())}"
        with sessions() as session:
            session.add(Event(cycle_id=marker, seq=1, role="probe",
                              kind="readiness.probe",
                              payload=json.dumps({"ping": True})))
            session.commit()
        with sessions() as session:
            from sqlalchemy import select
            rows = session.scalars(
                select(Event).where(Event.cycle_id == marker)
            ).all()
            count = len(rows)
            for row in rows:
                session.delete(row)
            session.commit()
        return _finish("READY" if count == 1 else "DEGRADED",
                       "القاعدة تكتب وتقرأ وتحذف فعليًا"
                       if count == 1 else f"قراءة غير متسقة ({count})",
                       started, TTL_DEFAULTS["PERSISTENCE"])
    except Exception as error:  # noqa: BLE001
        return _finish("NOT_READY", f"تعذر التحقق من القاعدة: {error}",
                       started, TTL_DEFAULTS["PERSISTENCE"],
                       failure_class="DEPENDENCY_FAILURE")


def probe_model_inference(provider_cfg: dict, model: str) -> ProbeResult:
    """استدلال LLM حقيقي (§10): توكن واحد فعلي — لا /models وحده دليلًا."""
    started = time.monotonic()
    try:
        from router.model_router import ChatMessage
        from router.streaming import stream_completion

        text = stream_completion(
            dict(provider_cfg, max_tokens=8), model,
            [ChatMessage(role="user", content="قل: جاهز")],
            on_delta=lambda _d: None,
        )
        return _finish(
            "READY", f"استدلال فعلي ناجح ({len(text)} حرفًا)", started,
            TTL_DEFAULTS["LLM"], details={"model": model,
                                          "chars": len(text)},
        )
    except Exception as error:  # noqa: BLE001 — فشل مصنَّف
        return _finish("NOT_READY", f"فشل الاستدلال الفعلي: {str(error)[:160]}",
                       started, TTL_DEFAULTS["LLM"],
                       failure_class="PROVIDER_FAILURE",
                       failure_stage="TOOL_EXECUTION",
                       details={"model": model})
