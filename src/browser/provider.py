"""درزة تنفيذ المتصفح (الأمر 013 §14) — Playwright+Chromium حقيقي.

``BrowserProvider`` بروتوكول درزة: أي تنفيذ يفي به يصلح (عامل متصفح
بعيد لاحقًا بنفس العقد). التنفيذ المحلي:

- ``available()``: فحص صادق — playwright مستورد؟ Chromium مثبت؟
  (لا READY لمجرد وجود إعداد — §14).
- ``launch(policy)``: تشغيل Chromium headless بوسائط الأمان، سياق
  نظيف بلا كوكيز دائمة، مهل من السياسة، رمل تنزيلات داخل الجلسة.

الجلسة (``BrowserSession``) تنفذ العمليات المطلوبة (§13): navigate/
click/type/scroll/wait/screenshot/extract_text/extract_links/download/
upload/back/forward/new_page/close_page/close — كل عملية:
1. تفحص السياسة (URL/المسارات/السقوف)؛
2. تنفذ فعليًا عبر Playwright؛
3. تبث حدثًا مهيكلًا عبر on_event؛
4. تعيد نتيجة قابلة للدليل (sha256 للقطات والتنزيلات).
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Protocol

from browser.policy import BrowserPolicy, PolicyViolation

#: مجلد جلسات المتصفح — رمل التنزيلات والأدلة.
BROWSER_RUNTIME_DIR = Path("runtime") / "browser"

#: (AES-LIVE-FACTORY-E2E-001 المرحلة 6ط) خيط المتصفح الوحيد: Playwright
#: Sync API يرفض العمل داخل حلقة asyncio ("use the Async API"), وخطوات
#: سير العمل قد تُنفَّذ في سياق async (مثبت حياً: مشروع 16 — المرحلة
#: الأولى نجحت من خيط متزامن والثانية فشلت كل أدواتها فوراً). كل
#: لمسة sync_playwright تمر عبر هذا الخيط الوحيد فيثبت انتماء
#: الجلسة لخيط واحد أياً كان سياق المستدعي.
import concurrent.futures as _cf
import contextvars as _cv

_BROWSER_ACTOR = _cf.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="aes-browser-actor")


def _on_browser_thread(fn, *args, **kwargs):
    """تنفيذ دالة متصفح على خيط الممثل الوحيد — بلا مهلة إضافية
    (المهل تحكمها سياسة الجلسة نفسها).

    (RLR-001 §4d-7) السياق يُعزل عن المستدعي: ThreadPoolExecutor
    ينسخ contextvars المستدعي — ومن داخل مهمة asyncio ينسخ معها
    أثر sniffio/asyncio فيرفض Playwright Sync العمل ("inside the
    asyncio loop") رغم أن الخيط الممثل بلا حلقة. سياق نظيف التُقط
    عند الاستيراد (بلا أي حلقة) يُستنسخ لكل تنفيذ فيقطع التسرب.
    """
    return _CLEAN_CONTEXT.run(fn, *args, **kwargs)


#: سياق نظيف بلا أثر async — يُلتقط لحظة الاستيراد (بداية العملية:
#: لا حلقة، لا sniffio) ويُستخدم كجذر لعزل كل استدعاءات الممثل.
_CLEAN_CONTEXT = _cv.copy_context()


def browser_threaded(fn):
    """زخرفة: طريقة جلسة المتصفح تُنفَّذ كاملة على خيط الممثل."""
    def wrapper(*args, **kwargs):
        return _on_browser_thread(fn, *args, **kwargs)
    wrapper.__name__ = getattr(fn, "__name__", "browser_op")
    wrapper.__doc__ = fn.__doc__
    return wrapper

#: وسيط تشغيل Chromium في الحاويات (بلا user namespaces للـSandbox
#: الداخلي) — معلن لا مخفي: العزل هنا حدود عملية+مهل+سياق، وعامل
#: متصفح بعيد هو مسار العزل الأقوى (§15 عقد العامل البعيد).
_CONTAINER_ARGS = ["--no-sandbox", "--disable-setuid-sandbox"]


def _utc_now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProviderNotReady(RuntimeError):
    """المزود غير جاهز — مع السبب الحقيقي حرفيًا (لا READY مزيفًا)."""


class BrowserSession:
    """جلسة متصفح حية — عمليات موثقة كل واحدة بحدث ونتيجة."""

    def __init__(self, session_id: str, playwright, browser, context,
                 policy: BrowserPolicy,
                 on_event: Callable[[str, dict], None] | None = None):
        self.session_id = session_id
        self._playwright = playwright
        self._browser = browser
        self._context = context
        self._pages: list = []
        self.policy = policy
        self._on_event = on_event
        self._closed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # الأحداث — كل عملية تُبث لحظة حدوثها (§13 قابلة للتسجيل)
    # ------------------------------------------------------------------ #

    def _emit(self, kind: str, payload: dict) -> None:
        event = {"kind": f"browser.{kind}",
                 "session_id": self.session_id,
                 "at": _utc_now_iso(), **payload}
        if self._on_event is not None:
            try:
                self._on_event(f"browser.{kind}", event)
            except Exception:  # noqa: BLE001 — المستقبِل لا يكسر العملية
                pass

    # ------------------------------------------------------------------ #
    # إدارة الصفحات
    # ------------------------------------------------------------------ #

    @property
    def page(self):
        with self._lock:
            if not self._pages:
                raise ProviderNotReady(
                    "لا صفحة مفتوحة — استخدم new_page أولًا"
                )
            return self._pages[-1]

    @browser_threaded
    def new_page(self) -> dict:
        """فتح صفحة جديدة — تحت سقف السياسة."""
        with self._lock:
            if self._closed:
                raise ProviderNotReady("الجلسة مغلقة")
            if len(self._pages) >= self.policy.max_pages:
                raise PolicyViolation(
                    f"سقف الصفحات المفتوحة ({self.policy.max_pages}) — "
                    "أغلق صفحة أولًا"
                )
            page = self._context.new_page()
            page.set_default_timeout(
                self.policy.action_timeout_s * 1000
            )
            page.set_default_navigation_timeout(
                self.policy.nav_timeout_s * 1000
            )
            self._pages.append(page)
        self._emit("session.page_opened", {"pages": len(self._pages)})
        return {"session_id": self.session_id, "pages": len(self._pages)}

    @browser_threaded
    def close_page(self) -> dict:
        with self._lock:
            if not self._pages:
                return {"session_id": self.session_id, "pages": 0}
            page = self._pages.pop()
        try:
            page.close()
        except Exception:  # noqa: BLE001 — إغلاق ميت لا يكسر
            pass
        return {"session_id": self.session_id, "pages": len(self._pages)}

    # ------------------------------------------------------------------ #
    # العمليات (§13)
    # ------------------------------------------------------------------ #

    @browser_threaded
    def navigate(self, url: str) -> dict:
        host = self.policy.check_url(url)
        self._emit("navigate", {"url": url, "host": host})
        started = time.monotonic()
        response = self.page.goto(url, wait_until="domcontentloaded",
                                  timeout=self.policy.nav_timeout_s * 1000)
        status = response.status if response else 0
        title = self.page.title()
        result = {
            "url": url, "host": host, "http_status": status,
            "title": title,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        self._emit("page.loaded", result)
        return result

    @browser_threaded
    def click(self, selector: str) -> dict:
        self._emit("click", {"selector": selector})
        self.page.click(selector,
                        timeout=self.policy.action_timeout_s * 1000)
        return {"selector": selector, "clicked": True}

    @browser_threaded
    def type(self, selector: str, text: str) -> dict:
        self._emit("type", {"selector": selector,
                            "text_len": len(text)})
        self.page.fill(selector, str(text),
                       timeout=self.policy.action_timeout_s * 1000)
        return {"selector": selector, "typed_chars": len(str(text))}

    @browser_threaded
    def scroll(self, pixels: int = 600) -> dict:
        self.page.mouse.wheel(0, int(pixels))
        self._emit("session.scrolled", {"pixels": int(pixels)})
        return {"scrolled_px": int(pixels)}

    @browser_threaded
    def wait(self, seconds: float = 1.0) -> dict:
        seconds = max(0.0, min(float(seconds), self.policy.load_timeout_s))
        self.page.wait_for_timeout(int(seconds * 1000))
        return {"waited_s": seconds}

    @browser_threaded
    def screenshot(self, name: str = "") -> dict:
        artifacts = self._artifacts_dir()
        filename = (name or f"shot-{uuid.uuid4().hex[:8]}") + ".png"
        path = artifacts / filename
        self.page.screenshot(path=str(path),
                             timeout=self.policy.action_timeout_s * 1000)
        size = path.stat().st_size
        result = {
            "file": str(path), "bytes": size,
            "sha256": _sha256_file(path),
        }
        self._emit("screenshot", result)
        return result

    @browser_threaded
    def extract_text(self) -> dict:
        text = self.page.inner_text("body", timeout=(
            self.policy.action_timeout_s * 1000
        ))
        result = {
            "url": self.page.url,
            "chars": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "excerpt": text[:400],
        }
        self._emit("extract", {**result, "kind_detail": "text"})
        return result

    @browser_threaded
    def extract_links(self, limit: int = 50) -> dict:
        links = self.page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.href, text: (e.textContent || "
            "'').trim().slice(0, 120)}))",
        )
        links = [
            link for link in links if link.get("href")
        ][:max(1, min(int(limit), 200))]
        result = {"url": self.page.url, "count": len(links),
                  "links": links}
        self._emit("extract", {**result, "kind_detail": "links"})
        return result

    @browser_threaded
    def download(self, url: str) -> dict:
        self.policy.check_url(url)
        self._emit("download.started", {"url": url})
        if not self.policy.download_dir:
            raise PolicyViolation("رمل التنزيلات غير مهيأ")
        response = self.page.request.get(
            url, timeout=self.policy.load_timeout_s * 1000
        )
        if not response.ok:
            raise ProviderNotReady(
                f"فشل التنزيل: HTTP {response.status}"
            )
        body = response.body()
        self.policy.check_download_size(len(body))
        filename = Path(url.split("?")[0].rstrip("/").split("/")[-1]
                        or f"download-{uuid.uuid4().hex[:6]}")
        path = Path(self.policy.download_dir) / filename
        path.write_bytes(body)
        result = {
            "url": url, "file": str(path), "bytes": len(body),
            "sha256": _sha256_file(path),
        }
        self._emit("download", result)
        return result

    @browser_threaded
    def upload(self, selector: str, path: str) -> dict:
        self.policy.check_upload_path(path)
        self.page.set_input_files(
            selector, str(path),
            timeout=self.policy.action_timeout_s * 1000,
        )
        self._emit("session.uploaded", {"selector": selector,
                                        "file": str(path)})
        return {"selector": selector, "uploaded": str(path)}

    @browser_threaded
    def back(self) -> dict:
        self.page.go_back(timeout=self.policy.nav_timeout_s * 1000)
        return {"url": self.page.url, "navigated": "back"}

    @browser_threaded
    def forward(self) -> dict:
        self.page.go_forward(timeout=self.policy.nav_timeout_s * 1000)
        return {"url": self.page.url, "navigated": "forward"}

    # ------------------------------------------------------------------ #
    # الحياة والموت
    # ------------------------------------------------------------------ #

    def _artifacts_dir(self) -> Path:
        root = BROWSER_RUNTIME_DIR / self.session_id / "artifacts"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @browser_threaded
    def close(self) -> dict:
        with self._lock:
            if self._closed:
                return {"session_id": self.session_id,
                        "closed": True, "already": True}
            self._closed = True
        started = time.monotonic()
        try:
            self._context.close()
            self._browser.close()
        except Exception:  # noqa: BLE001 — إغلاق ميت لا يكسر
            pass
        finally:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
        result = {
            "session_id": self.session_id, "closed": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        self._emit("session.closed", result)
        return result


class BrowserProvider(Protocol):
    """درزة تنفيذ المتصفح — أي خلفية تفي بالعقد تصلح (§14)."""

    def name(self) -> str: ...

    def available(self) -> tuple[bool, str]: ...

    def launch(self, policy: BrowserPolicy,
               on_event: Callable[[str, dict], None] | None = None
               ) -> BrowserSession: ...


class PlaywrightBrowserProvider:
    """التنفيذ المحلي — Playwright + Chromium headless (§14)."""

    def name(self) -> str:
        return "playwright-chromium"

    def _chromium_direct_path(self):
        """مسار Chromium من قرص القراءة حصرًا — بلا تشغيل تعريف
        (AES-RLR-001 §4d): الفحص القديم كان يشغّل عملية تعريف كاملة
        (node) في كل إطلاق جلسة — على خادم محمّل تفشل العملية
        («تعذر فحص Chromium») فيموت الإطلاق اللاحق فورًا (فشل 4ms
        الموثق بعد الاستئناف). وجود الملف التنفيذي ثابت عبر عمر
        العملية — قرصٌ كافٍ وصادق، وإن غاب المسار نُجري الفحص
        الكامل القديم كاحتياط."""
        import os as _os

        roots = []
        env_root = str(_os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
                       ).strip()
        if env_root:
            roots.append(Path(env_root).expanduser())
        roots.append(Path.home() / ".cache" / "ms-playwright")
        for root in roots:
            if not root.is_dir():
                continue
            try:
                candidates = sorted(
                    (p for p in root.glob("chromium-*")
                     if p.is_dir()
                     and "headless" not in p.name.lower()),
                    key=lambda p: p.name, reverse=True,
                )
            except OSError:
                continue
            for cand in candidates:
                # تخطيطا التثبيت: x64 = chrome-linux/ ، arm64 = chrome-linux-arm64/
                for exe in (cand / "chrome-linux" / "chrome",
                            cand / "chrome-linux-arm64" / "chrome",
                            cand / "chrome-linux" / "headless_shell",
                            cand / "chrome-linux-arm64" / "headless_shell"):
                    if exe.is_file():
                        return exe
        return None

    def available(self) -> tuple[bool, str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            return False, (
                f"مكتبة Playwright غير مثبتة ({error}) — ثبّت الحزمة "
                "الاختيارية: pip install '.[browser]'"
            )
        direct = self._chromium_direct_path()
        if direct is not None:
            return True, f"Playwright + Chromium جاهز ({direct})"
        try:
            with sync_playwright() as playwright:
                path = playwright.chromium.executable_path
                if not Path(str(path)).exists():
                    return False, (
                        f"Chromium غير مثبت ({path}) — شغّل: "
                        "python -m playwright install chromium"
                    )
                return True, f"Playwright + Chromium جاهز ({path})"
        except Exception as error:  # noqa: BLE001 — السبب الحرفي
            return False, f"تعذر فحص Chromium: {error}"

    def launch(self, policy: BrowserPolicy,
               on_event: Callable[[str, dict], None] | None = None
               ) -> BrowserSession:
        from playwright.sync_api import sync_playwright

        session_id = policy.session_id or f"brs-{uuid.uuid4().hex[:10]}"
        policy.session_id = session_id
        session_root = BROWSER_RUNTIME_DIR / session_id
        downloads = session_root / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        policy.download_dir = str(downloads)
        policy.upload_dir = str(session_root)

        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(
                headless=True,
                args=[*policy.launch_args(), *_CONTAINER_ARGS],
                env={},
            )
        except Exception as error:  # noqa: BLE001
            try:
                playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            raise ProviderNotReady(
                f"تعذر تشغيل Chromium: {error}"
            ) from error
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
                "AgenticEngineeringSystem/3.5.0 (+browser-capability)"
            ),
        )
        context.set_default_timeout(policy.action_timeout_s * 1000)
        context.set_default_navigation_timeout(
            policy.nav_timeout_s * 1000
        )
        session = BrowserSession(
            session_id, playwright, browser, context, policy,
            on_event=on_event,
        )
        session._emit("session.created", {
            "provider": self.name(),
            "policy": policy.describe(),
            "download_sandbox": policy.download_dir,
        })
        return session


#: المزود الافتراضي العملية-wide — قابل للاستبدال (درزة معلنة).
DEFAULT_PROVIDER = PlaywrightBrowserProvider()


__all__ = [
    "BROWSER_RUNTIME_DIR",
    "BrowserProvider",
    "BrowserSession",
    "PlaywrightBrowserProvider",
    "ProviderNotReady",
    "DEFAULT_PROVIDER",
]
