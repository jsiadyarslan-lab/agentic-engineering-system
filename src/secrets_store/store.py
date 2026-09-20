"""مخزن الأسرار — منقول حرفيًا من v1 (الأمر السادس المنقح §1).

نسخ لا اختراع: نفس المنطق والسلوك من backend/services/secrets_store.py
في v1، بتكييف الاستيرادات فقط (v1: backend.config.settings → v2: مجلد
runtime/ المركزي في core.config).

المتطلبات المحققة (كما في v1):
- التخزين في: runtime/secrets/secrets.json (مستثنى من Git عبر .gitignore).
- على Windows: تشفير المحتوى عبر DPAPI (CryptProtectData /
  CryptUnprotectData) باستخدام ctypes القياسية فقط — صفر مكتبات
  خارجية. التشفير مرتبط بحساب مستخدم Windows الحالي.
- على غير Windows: التخزين بصلاحيات 600 مع تحذير واضح — base64 هنا
  ترميز لإخفاء العرض العادي وليس تشفيرًا، والحماية الفعلية صلاحيات
  الملف.
- التقنيع: mask() تعيد ‎**** + آخر 4 أحرف فقط — ولا تُعاد القيمة
  الكاملة من أي نقطة نهاية إطلاقًا.
- مرشح السجلات: redact() تستبدل أي قيمة مفتاح معروفة بـ [REDACTED]،
  وSecretRedactingFilter تُركَّب على معالجات مسجل الجذر.

فرق وحيد عن v1 (الأمر السادس المنقح §0.3): لا مفاتيح من متغيرات
البيئة أبدًا — known_keys() من المخزن وحده (v1 كانت تدمج مفاتيح ‎.env).

صيغة الملف:
    {"version": 1, "encrypted": true|false, "payload": "<base64>"}
حيث payload بعد فك base64 يكون:
    - encrypted=true  (Windows): كتلة DPAPI ثنائية.
    - encrypted=false (غيره): نص JSON {"providers": {"<name>": "<key>"}}.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import threading
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

REDACTED = "[REDACTED]"

#: جذر بيانات التشغيل — نفس اتفاقية missions/ وeoe-runs/ في v2.
RUNTIME_DIR = Path("runtime")

_lock = threading.RLock()

# ذاكرة تخزين مؤقت للمفاتيح المعروفة (لتسريع redact دون قراءة الملف كل سطر)
_known_keys_cache: list[str] | None = None


def secrets_dir() -> Path:
    """مجلد مخزن الأسرار: runtime/secrets/"""
    return RUNTIME_DIR / "secrets"


def secrets_file() -> Path:
    """ملف مخزن الأسرار: runtime/secrets/secrets.json"""
    return secrets_dir() / "secrets.json"


def encryption_available() -> bool:
    """هل التشفير الحقيقي (DPAPI) متوفر على هذا النظام؟"""
    return IS_WINDOWS


def platform_warning() -> str | None:
    """تحذير يظهر في الواجهة والتوثيق عند غياب التشفير (غير Windows)."""
    if IS_WINDOWS:
        return None
    return (
        "التشفير غير متوفر على هذا النظام — تُخزَّن المفاتيح محليًا بصلاحيات 600 "
        "داخل runtime/secrets/secrets.json (ترميز base64 وليس تشفيرًا). "
        "على Windows تُشفَّر تلقائيًا عبر DPAPI المرتبط بحساب المستخدم."
    )


# ================================================================== #
# DPAPI على Windows — ctypes قياسية فقط (crypt32 + kernel32)
# ================================================================== #

if IS_WINDOWS:  # pragma: no cover — يُنفَّذ على أجهزة Windows فقط
    import ctypes
    import ctypes.wintypes as wintypes

    class _DATA_BLOB(ctypes.Structure):
        """بنية DATA_BLOB المطلوبة لدوال DPAPI."""

        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    # توثيق التواقيع لتفادي أخطاء التحويل بين 32/64 بت
    _crypt32 = ctypes.WinDLL("crypt32")  # type: ignore[attr-defined]
    _kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),  # pDataIn
        wintypes.LPCWSTR,            # szDataDescr
        ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
        ctypes.c_void_p,             # pvReserved
        ctypes.c_void_p,             # pPromptStruct
        wintypes.DWORD,              # dwFlags
        ctypes.POINTER(_DATA_BLOB),  # pDataOut
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL

    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),   # pDataIn
        ctypes.POINTER(wintypes.LPWSTR),  # ppszDataDescr
        ctypes.POINTER(_DATA_BLOB),   # pOptionalEntropy
        ctypes.c_void_p,              # pvReserved
        ctypes.c_void_p,              # pPromptStruct
        wintypes.DWORD,               # dwFlags
        ctypes.POINTER(_DATA_BLOB),   # pDataOut
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL

    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _kernel32.LocalFree.restype = wintypes.HLOCAL

    def _dpapi_protect(data: bytes) -> bytes:
        """تشفير البايتات عبر CryptProtectData (مرتبط بحساب المستخدم الحالي)."""
        in_buffer = ctypes.create_string_buffer(data, max(len(data), 1))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(blob_in), "agent-hub-v2-secrets", None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            raise OSError("فشل CryptProtectData (DPAPI) — تعذر تشفير المفاتيح")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(blob_out.pbData, wintypes.HLOCAL))

    def _dpapi_unprotect(blob: bytes) -> bytes:
        """فك تشفير كتلة DPAPI عبر CryptUnprotectData."""
        in_buffer = ctypes.create_string_buffer(blob, max(len(blob), 1))
        blob_in = _DATA_BLOB(len(blob), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        desc = wintypes.LPWSTR()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), ctypes.byref(desc), None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            raise OSError(
                "فشل CryptUnprotectData (DPAPI) — لا يمكن فك تشفير الملف "
                "(ربما أُنشئ بحساب Windows آخر أو على جهاز مختلف)"
            )
        try:
            if desc:
                _kernel32.LocalFree(ctypes.cast(desc, wintypes.HLOCAL))
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(blob_out.pbData, wintypes.HLOCAL))


# ================================================================== #
# القراءة والكتابة
# ================================================================== #

def _write_file(raw: bytes) -> None:
    """كتابة الملف بصلاحيات 600 (حيثما تدعمها المنصة)."""
    path = secrets_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    # إنشاء الملف بصلاحيات مقيدة منذ البداية حيثما أمكن (تفادي نافذة صلاحيات واسعة)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    try:
        path.chmod(0o600)  # no-op عمليًا على Windows
    except OSError:
        pass


def _read_file() -> bytes:
    path = secrets_file()
    return path.read_bytes()


def _load_inner() -> dict:
    """قراءة المخزن وإرجاع القاموس الداخلي {"providers": {...}}.

    - لا يوجد ملف → قاموس فارغ.
    - encrypted=true → فك DPAPI (يُنفَّذ على Windows فقط).
    - أي تلف/فشل فك → قاموس فارغ مع تحذير (بدون انهيار الخادم).
    """
    path = secrets_file()
    if not path.exists():
        return {"providers": {}}
    try:
        envelope = json.loads(_read_file().decode("utf-8"))
        payload_b64 = envelope.get("payload") or ""
        payload = base64.b64decode(payload_b64) if payload_b64 else b""
        if envelope.get("encrypted"):
            payload = _dpapi_unprotect(payload)
        inner = json.loads(payload.decode("utf-8"))
        if not isinstance(inner, dict):
            return {"providers": {}}
        providers = inner.get("providers")
        if not isinstance(providers, dict):
            inner["providers"] = {}
        return inner
    except Exception:  # noqa: BLE001 — ملف تالف لا يُسقط الخادم
        logging.getLogger("agent_hub_v2.secrets").warning(
            "تعذر قراءة مخزن الأسرار (%s) — يُعامل كأنه فارغ", path
        )
        return {"providers": {}}


def _save_inner(inner: dict) -> None:
    """تشفير/ترميز القاموس الداخلي وكتابته إلى الملف."""
    payload = json.dumps(inner, ensure_ascii=False).encode("utf-8")
    if IS_WINDOWS:
        blob = _dpapi_protect(payload)
        envelope = {"version": 1, "encrypted": True, "payload": base64.b64encode(blob).decode("ascii")}
    else:
        envelope = {"version": 1, "encrypted": False, "payload": base64.b64encode(payload).decode("ascii")}
    raw = (json.dumps(envelope, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_file(raw)
    _invalidate_known_cache()


# ================================================================== #
# الواجهة العامة
# ================================================================== #

def get_key(provider: str) -> str | None:
    """المفتاح المحفوظ للمزود من المخزن المحلي (لا بيئة — §0.3)."""
    with _lock:
        providers = _load_inner().get("providers", {})
    value = providers.get(provider)
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_key(provider: str, key: str) -> None:
    """حفظ/تحديث مفتاح مزود في المخزن المحلي."""
    with _lock:
        inner = _load_inner()
        inner.setdefault("providers", {})[provider] = key.strip()
        _save_inner(inner)


def delete_key(provider: str) -> bool:
    """حذف مفتاح مزود. يعيد True إذا كان موجودًا وحُذف."""
    with _lock:
        inner = _load_inner()
        providers = inner.get("providers", {})
        existed = provider in providers
        if existed:
            del providers[provider]
            _save_inner(inner)
        else:
            _invalidate_known_cache()
    return existed


def has_key(provider: str) -> bool:
    return get_key(provider) is not None


def stored_providers() -> list[str]:
    """أسماء المزودات التي لها مفاتيح محفوظة في المخزن."""
    with _lock:
        providers = _load_inner().get("providers", {})
    return sorted(k for k, v in providers.items() if isinstance(v, str) and v.strip())


def mask(key: str | None) -> str | None:
    """تقنيع مفتاح: ‎**** + آخر 4 أحرف فقط.

    المفاتيح القصيرة جدًا تُقنَّع بالكامل حتى لا يكشف الجزء الظاهر شيئًا.
    """
    if not key:
        return None
    key = key.strip()
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]


# ================================================================== #
# مرشح السجلات — استبدال أي قيمة مفتاح معروفة بـ [REDACTED]
# ================================================================== #

def _invalidate_known_cache() -> None:
    global _known_keys_cache
    _known_keys_cache = None


def known_keys() -> list[str]:
    """قيم المفاتيح المعروفة (المخزن وحده — لا بيئة أبدًا §0.3)."""
    global _known_keys_cache
    if _known_keys_cache is None:
        with _lock:
            providers = _load_inner().get("providers", {})
        _known_keys_cache = [
            v.strip()
            for v in providers.values()
            if isinstance(v, str) and len(v.strip()) >= 4
        ]
    return _known_keys_cache


def redact(text: str) -> str:
    """استبدال أي قيمة مفتاح معروفة داخل نص بـ [REDACTED]."""
    if not text:
        return text
    for key in known_keys():
        if key and key in text:
            text = text.replace(key, REDACTED)
    return text


class SecretRedactingFilter(logging.Filter):
    """مرشح سجلات: يستبدل قيم المفاتيح المعروفة بـ [REDACTED] قبل الكتابة.

    يُطبَّق على record.msg وrecord.args قبل التنسيق، فلا يظهر مفتاح
    كامل في الكونسول ولا في أي سجل إطلاقًا.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            args = record.args
            if args:
                if isinstance(args, tuple):
                    record.args = tuple(
                        redact(a) if isinstance(a, str) else a for a in args
                    )
                elif isinstance(args, str):
                    record.args = redact(args)
        except Exception:  # noqa: BLE001 — مرشح السجلات لا يُسقط الخادم أبدًا
            pass
        return True


def install_log_redaction(root_logger: logging.Logger | None = None) -> int:
    """تركيب مرشح التقنيع على كل معالجات مسجل الجذر — يعيد عدد المعالجات."""
    import logging as _logging

    root = root_logger or _logging.getLogger()
    installed = 0
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactingFilter) for f in handler.filters):
            handler.addFilter(SecretRedactingFilter())
            installed += 1
    return installed


def store_status() -> dict:
    """حالة المخزن لعرضها في الواجهة (بدون أي قيمة سرية)."""
    path = secrets_file()
    encrypted_flag = None
    if path.exists():
        try:
            envelope = json.loads(_read_file().decode("utf-8"))
            encrypted_flag = bool(envelope.get("encrypted"))
        except Exception:  # noqa: BLE001
            encrypted_flag = None
    perms = None
    try:
        perms = oct(path.stat().st_mode & 0o777) if path.exists() else None
    except OSError:
        pass
    return {
        "file": "runtime/secrets/secrets.json",
        "file_exists": path.exists(),
        "encrypted": encrypted_flag,
        "encryption_available": encryption_available(),
        "warning": platform_warning(),
        "stored_providers": stored_providers(),
        "file_permissions": perms,
    }
