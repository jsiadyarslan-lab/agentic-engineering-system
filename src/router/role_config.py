"""اختيار النموذج لكل دور (الأمر 006 §3+§4) — مصدر الحقيقة الوحيد.

كل دور يملك (provider, model) مستقلين؛ المحادثة العادية تملك اختيارها
أيضًا. الحفظ ملف JSON واحد atomic تحت runtime/ — إعداد تشغيلي لا
بيانات علائقية (جداول SQLAlchemy للكيانات لا للتفضيلات).

فصل الطبقات الصارم: هذه الوحدة بيانات صرفة (تحميل/حفظ/افتراضات) لا
تعرف بطاقات المزودات؛ التحقق الدلالي (مزود معروف؟ نموذج معلَن أو
حي؟) مسؤولية طبقة api (models_config) التي ترى الطبقتين معًا.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

#: مفاتيح الأدوار الخمسة + المحادثة — كل ما يقبل اختيار نموذج.
ROLE_KEYS: tuple[str, ...] = (
    "thinker",
    "reviewer",
    "implementer",
    "verifier",
    "arbiter",
    "chat",
)

#: الافتراض المعلن (الأمر 006 §4): كل الأدوار والمحادثة على المزود
#: الافتراضي للبطاقات — إعلان صريح لا استنتاج خافت.
DEFAULT_PROVIDER = "nvidia"
DEFAULT_MODEL = "nemotron-3-ultra-550b-a55b"

CONFIG_PATH = Path("runtime") / "role_model_config.json"


class RoleConfigError(ValueError):
    """اختيار غير صالح لدور — الرسالة تسمي الدور والسبب."""


@dataclass(frozen=True)
class RoleSelection:
    """اختيار واحد: مزود + نموذج."""

    provider: str
    model: str

    def as_dict(self) -> dict:
        return {"provider": self.provider, "model": self.model}


def _defaults() -> dict[str, RoleSelection]:
    return {
        key: RoleSelection(DEFAULT_PROVIDER, DEFAULT_MODEL)
        for key in ROLE_KEYS
    }


def _coerce_one(key: str, raw: object) -> RoleSelection:
    """تحويل قيمة خام إلى RoleSelection — شكل خاطئ = خطأ يسمي الدور."""
    if not isinstance(raw, dict):
        raise RoleConfigError(
            f"اختيار الدور '{key}' يجب أن يكون كائنًا {{provider, model}}"
        )
    provider = str(raw.get("provider", "")).strip()
    model = str(raw.get("model", "")).strip()
    if not provider or not model:
        raise RoleConfigError(
            f"الدور '{key}' يحتاج provider وmodel غير فارغين"
        )
    return RoleSelection(provider, model)


def load_role_config(path: Path | str | None = None) -> dict[str, RoleSelection]:
    """تحميل الاختيارات المحفوظة — الفاسد يُهمل بصراحة (افتراضات + سبب).

    ملف تالف لا يكسر التشغيل أبدًا: تُعاد الافتراضات مع بيان السبب في
    ``load_warning`` (صدق قبل الراحة) — الحفظ التالي يصلح الملف.
    """
    target = Path(path) if path else CONFIG_PATH
    selections = _defaults()
    if not target.is_file():
        return selections
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return selections
    if not isinstance(raw, dict):
        return selections
    clean: dict[str, RoleSelection] = {}
    for key in ROLE_KEYS:
        if key in raw:
            clean[key] = _coerce_one(key, raw[key])
    selections.update(clean)
    return selections


def load_warning(path: Path | str | None = None) -> str | None:
    """سبب إهمال الملف إن كان تالفًا — يُعرض للمستخدم لا يُبتلع."""
    target = Path(path) if path else CONFIG_PATH
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return f"ملف اختيارات النماذج تالف فتجاهلناه ({error}) — الافتراضات سارية"
    if not isinstance(raw, dict):
        return "ملف اختيارات النماذج بصيغة غير مفهومة — الافتراضات سارية"
    return None


def save_role_config(
    selections: dict[str, RoleSelection], path: Path | str | None = None
) -> Path:
    """حفظ atomic — كتابة مؤقتة ثم rename (لا ملف نصف مكتوب أبدًا)."""
    target = Path(path) if path else CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: selections.get(
            key, RoleSelection(DEFAULT_PROVIDER, DEFAULT_MODEL)
        ).as_dict()
        for key in ROLE_KEYS
    }
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".role_config.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def selections_as_dict(selections: dict[str, RoleSelection]) -> dict:
    """تمثيل JSON للاختيارات — للردود (بلا أي مفاتيح أسرار أصلًا)."""
    return {key: selections[key].as_dict() for key in ROLE_KEYS}


__all__ = [
    "CONFIG_PATH",
    "DEFAULT_MODEL",
    "DEFAULT_PROVIDER",
    "ROLE_KEYS",
    "RoleConfigError",
    "RoleSelection",
    "load_role_config",
    "load_warning",
    "save_role_config",
    "selections_as_dict",
]
