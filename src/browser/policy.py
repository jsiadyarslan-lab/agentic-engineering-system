"""عقد أمان المتصفح (الأمر 013 §15) — عزل معلن لا وصول حر.

قواعد السياسة (كلها قابلة للضبط من المستوى الأعلى):
- **الشبكة**: بروتوكولا https/http حصرًا؛ النطاقات مسموحة كلها
  افتراضيًا أو قائمة صريحة (allowlist)؛ الشبكات الخاصة والحلقية
  محجوبة افتراضيًا (localhost/127.0.0.0-8/10.x/172.16-31.x/192.168.x/
  169.254.x/::1) — لا وصول من المتصفح إلى خدمات المضيف الداخلية.
- **المهل**: تنقل 20ث، فعل 10ث، تحميل 30ث — لا انتظار لانهائي.
- **الصفحات**: سقف صفحات مفتوحة لكل جلسة (4) — لا انفجار تبويبات.
- **التنزيلات**: صندوق رمل داخل مجلد الجلسة حصرًا، بسقف حجم معلن.
- **الرفع**: من مجلد الجلسة حصرًا (لا نظام ملفات المضيف الحر).
- **الأسرار**: لا متغيرات بيئة تمر للمتصفح (بيئة نظيفة)، ولا كوكيز
  دائمة — سياق جديد نظيف لكل جلسة (fresh context).
- **التنظيف**: إغلاق صريح عند نهاية الجلسة + عند إطفاء العملية؛
  عملية المتصفح تنتهي مع العملية الأم (handle cleanup).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

#: المهلة الافتراضية للتنقل (ثواني).
DEFAULT_NAV_TIMEOUT_S = 20.0
#: المهلة الافتراضية لأفعال DOM (ثواني).
DEFAULT_ACTION_TIMEOUT_S = 10.0
#: سقف الصفحات المفتوحة لكل جلسة.
DEFAULT_MAX_PAGES = 4
#: سقف حجم التنزيل الواحد (ميغابايت).
DEFAULT_MAX_DOWNLOAD_MB = 50

#: المضيفون المحجوبون دائمًا ما لم يُعلن العكس صراحة (internal).
_PRIVATE_HOST_HINTS = ("localhost", "0.0.0.0", "metadata.google.internal")


#: (AES-LIVE-FACTORY-E2E-001 المرحلة 4ب) استثناء معلن ومحدود حصرًا
#: لتطبيق المصنع نفسه على الحلقة الراجعة: عندما يُفعّل المالك
#: AES_BROWSER_ALLOW_LOCAL_APP=<port> يُسمح للمتصفح بفتح
#: localhost/127.0.0.1 على ذلك المنفذ وحده (المنفذ الذي يعمل عليه
#: تطبيق المصنع صاحب الجلسة) — للتحقق الحي من المعاينة التي يبنيها.
#: كل ما عدا ذلك من شبكات خاصة/حلقية يبقى محجوبًا كما هو، والقيمة
#: الفارغة/الغائبة = لا استثناء إطلاقًا (السلوك الأصلي كاملًا).
def _local_app_exception() -> str:
    raw = os.environ.get("AES_BROWSER_ALLOW_LOCAL_APP", "")
    raw = str(raw).strip().strip(":/")
    return raw if raw.isdigit() else ""


def _url_in_local_app_exception(url: str) -> bool:
    port = _local_app_exception()
    if not port:
        return False
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if host not in ("127.0.0.1", "localhost"):
        return False
    try:
        url_port = parsed.port
    except ValueError:
        return False
    return url_port is not None and str(url_port) == port


def _ip_is_private(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local \
        or addr.is_reserved


class PolicyViolation(RuntimeError):
    """خرق سياسة المتصفح — مرفوض صريحًا لا صمتًا."""


@dataclass
class BrowserPolicy:
    """عقد أمان جلسة المتصفح — كل حد معلن وقابل للفحص."""

    #: None = كل النطاقات العامة مسموحة؛ وإلا قائمة صريحة حصرًا.
    allowed_domains: list[str] | None = None
    #: حجب الشبكات الخاصة/الحلقية (افتراضي: محجوبة — أمان أولًا).
    block_private_networks: bool = True
    nav_timeout_s: float = DEFAULT_NAV_TIMEOUT_S
    action_timeout_s: float = DEFAULT_ACTION_TIMEOUT_S
    load_timeout_s: float = 30.0
    max_pages: int = DEFAULT_MAX_PAGES
    max_download_mb: int = DEFAULT_MAX_DOWNLOAD_MB
    #: مجلد رمل التنزيلات (يضبطه البروفايدر داخل مجلد الجلسة).
    download_dir: str = ""
    #: مجلد الرفعات المسموح (مجلد الجلسة).
    upload_dir: str = ""
    #: تعطيل الكوكيز الدائمة — سياق نظيف لكل جلسة.
    persistent_session: bool = False
    #: معرّف الجلسة للأدلة والأحداث.
    session_id: str = ""
    extra_launch_args: list[str] = field(default_factory=list)

    def check_url(self, url: str) -> str:
        """فحص الرابط قبل أي تنقل — يعيد المضيف أو يرفض صراحة (§15)."""
        parsed = urlparse(str(url or ""))
        if parsed.scheme not in ("https", "http"):
            raise PolicyViolation(
                f"بروتوكول غير مسموح للمتصفح: {parsed.scheme or '؟'} — "
                "https/http حصرًا"
            )
        host = (parsed.hostname or "").strip().lower()
        if not host:
            raise PolicyViolation("رابط بلا مضيف")
        if self.allowed_domains is not None:
            allowed = tuple(
                d.strip().lower() for d in self.allowed_domains if d.strip()
            )
            if allowed and not any(
                    host == d or host.endswith("." + d) for d in allowed):
                raise PolicyViolation(
                    f"نطاق خارج القائمة المسموحة: {host}"
                )
        if self.block_private_networks:
            # (AES-LIVE-FACTORY-E2E-001 المرحلة 4ب) الاستثناء المعلن
            # وحده يسبق الحجب: تطبيق المصنع نفسه على منفذه المفعّل.
            if _url_in_local_app_exception(str(url or "")):
                return host
            if host in _PRIVATE_HOST_HINTS or _ip_is_private(host):
                raise PolicyViolation(
                    f"الوصول إلى شبكة خاصة/حلقية محجوب: {host}"
                )
            resolved = _resolve_host(host)
            if resolved and _ip_is_private(resolved):
                raise PolicyViolation(
                    f"المضيف {host} يحل إلى عنوان خاص ({resolved}) — محجوب"
                )
        return host

    def check_download_size(self, size_bytes: int) -> None:
        if size_bytes > self.max_download_mb * 1024 * 1024:
            raise PolicyViolation(
                f"تنزيل يتجاوز السقف ({size_bytes} > "
                f"{self.max_download_mb}MB)"
            )

    def check_upload_path(self, path: str) -> None:
        """الرفع من مجلد الجلسة حصرًا — لا نظام ملفات المضيف الحر."""
        if not self.upload_dir:
            raise PolicyViolation("مجلد الرفعات غير مهيأ لهذه الجلسة")
        import os

        real = os.path.realpath(str(path))
        root = os.path.realpath(self.upload_dir)
        if not real.startswith(root + os.sep):
            raise PolicyViolation(
                "الرفع مسموح من مجلد الجلسة حصرًا (سياسة §15)"
            )

    def launch_args(self) -> list[str]:
        """وسائط إطلاق Chromium — أمان وحدود معلنة."""
        return [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-features=Translate,MediaRouter",
            "--font-render-hinting=none",
            *self.extra_launch_args,
        ]

    def describe(self) -> dict:
        return {
            "allowed_domains": self.allowed_domains or "كل النطاقات العامة",
            "block_private_networks": self.block_private_networks,
            "nav_timeout_s": self.nav_timeout_s,
            "action_timeout_s": self.action_timeout_s,
            "max_pages": self.max_pages,
            "max_download_mb": self.max_download_mb,
            "persistent_session": self.persistent_session,
        }


def _resolve_host(host: str) -> str:
    """حل المضيف مرة واحدة للفحص — الفشل لا يمنع (المتصفح يحسم)."""
    try:
        return socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
    except (socket.gaierror, IndexError, OSError):
        return ""


__all__ = [
    "BrowserPolicy",
    "PolicyViolation",
]
