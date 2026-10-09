"""E10-RP2 §2 + E10-RP2.1 §2 — جسر سياسة منح EOE إلى ``grant_validator``
في المحرك الموحّد.

المشكلة المكتشفة عند خط أساس RP2 (6d83cec): بوابة الكتابة المحكومة
(``ToolExecutor._check_permissions``) تتحقق من
``context.grant_validator(grant_id, permission)`` لكن لا يوجد أي مكون
إنتاجي يوصل سياسة منح EOE الحقيقية (``eoe.access_gateway``) بهذه
البوابة.

المشكلتان المكتشفتان عند خط أساس RP2.1 (631f6fb) والمصلحتان هنا
(انظر E10/E10_RP21_DISCOVERY.md D1-D4):
1. الجسر كان يمرر ``depth=0`` ثابتًا — حد العمق في المنحة
   (``max_depth``) لم يُطبق قط.
2. الجسر كان يسأل عن تغطية الجذر فقط؛ مسار الكتابة الفعلي
   (``<root>/sandbox-<task>/<path>``) لم يُعرض على طبقة الترخيص قط،
   والعزل المزعوم داخل الـsandbox لم يكن موجودًا (أصلح في
   ``sandbox.py`` / ``windows_adapter.py``).

هذه الوحدة هي الجسر الإنتاجي: تُبنى فوق عقد القبول الحقيقي
(``AccessAdmission``) وتحوّله إلى الدالة التي يستهلكها المحرك.
لا تُصدر منحًا ولا توقّع شيئًا — التوقيع والإصدار من جهة المالك
(``GrantorService``) والموافقة قبل ذلك؛ الجسر يتحقق فقط.

**عقد الصلاحيات الصريح (RP2.1 §2.2 — لا دلالة ضمنية):**
المنحة لا تخوّل "جذر المهمة بالكامل"؛ بل تخوّل **مسارات وعمقًا محددين
داخل الجذر**: عملية كتابة/قراءة ملموسة تجاز فقط إذا كان المسار الفعلي
المحلول داخل هدف المنحة وعمقه تحت الهدف ≤ ``max_depth``.

صيغتا الاستدعاء:
- ``validator(grant_id, permission)`` — بوابة خشنة: صلاحية المنحة
  (توقيع/حالة/نطاق) مقابل **نوع** الإذن. شرط لازم، غير كافٍ أبدًا
  لعملية كتابة ملموسة.
- ``validator(grant_id, permission, path, depth=None)`` — القرار الكامل
  للعملية الملموسة: المسار الفعلي المحلول + العمق الحقيقي تحت هدف
  المنحة (``depth=None`` = حساب أمين داخل ``AccessAdmission``).
  المسار التشغيلي (``ToolExecutor._check_permissions``) يستدعي هذه
  الصيغة لكل كتابة/قراءة محكومة.

السمة ``__path_aware__`` على الدالة المعادة تخبر المحرك أن المتحقق
يقبل الصيغة الموسعة — لا يوجد أي متحقق يسمح بكل المنح في المسار
التشغيلي، ولا توسيع صامت للسياسة: إذن لا يمكن تأسيسه في سياسة منح
EOE (مثل "execute") يُرفض صراحة (fail-closed).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from eoe.access_gateway import AccessAdmission, AccessDenied

#: إذن الكتابة كما تظهر في عقود أدوات المحرك الموحّد (مثل artifact_write).
ENGINE_PERMISSION_WRITE = "write"
#: إذن القراءة.
ENGINE_PERMISSION_READ = "read"

Validator = Callable[..., bool]


def build_engine_grant_validator(
    admission: AccessAdmission,
    artifacts_root: str,
) -> Validator:
    """بناء ``grant_validator`` إنتاجي من عقد قبول EOE الحقيقي.

    الدالة المعادة تحقق منحةً بعينها (بهويتها — لا أي منحة أخرى) لكل
    استدعاء أداة محكوم. أي فشل (توقيع، سارية، إبطال، نطاق، تغطية مسار،
    عمق) أو أي إذن غير قابل للتأسيس → False (رفض).
    """
    root = str(Path(artifacts_root).resolve())

    def validator(
        grant_id: str,
        permission: str,
        path: Optional[str] = None,
        depth: Optional[int] = None,
    ) -> bool:
        if permission == ENGINE_PERMISSION_WRITE:
            write = True
        elif permission == ENGINE_PERMISSION_READ:
            write = False
        else:
            # fail-closed: إذن لا تغطيه سياسة منح EOE يُرفض صراحة.
            return False
        if path is None:
            # البوابة الخشنة (نوع الإذن فقط): صلاحية المنحة مقابل
            # النطاق. القرار الكامل لأي عملية ملموسة يتطلب المسار
            # الفعلي (الصيغة الموسعة أدناه).
            try:
                admission.admit_grant_kind(grant_id, write=write)
            except AccessDenied:
                return False
            except Exception:
                return False
            return True
        # القرار الكامل: المسار الفعلي المطلوب + العمق الحقيقي تحت
        # هدف المنحة (depth=None → حساب أمين داخل AccessAdmission؛
        # لا قيمة ثابتة يمكنها تجاوز حد العمق المقصود).
        # المستوى الأول: المسار داخل كون الكتابة المرتبط بالمحرك
        # (artifacts_root) — حتى لو قبلت المنحة مسارًا أوسع.
        try:
            resolved = str(Path(path).resolve())
        except Exception:
            return False
        if resolved != root and not resolved.startswith(root + "/"):
            return False
        try:
            admission.admit_grant_id(grant_id, write=write, path=resolved, depth=depth)
        except AccessDenied:
            return False
        except Exception:
            # أي خطأ غير متوقع أثناء التحقق = رفض، لا سماح.
            return False
        return True

    # علامة صريحة للمحرك: هذا المتحقق يقبل المسار الفعلي والعمق.
    validator.__path_aware__ = True  # type: ignore[attr-defined]
    return validator


__all__ = [
    "ENGINE_PERMISSION_WRITE",
    "ENGINE_PERMISSION_READ",
    "build_engine_grant_validator",
]
