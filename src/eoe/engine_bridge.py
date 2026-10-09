"""E10-RP2 §2 — جسر سياسة منح EOE إلى ``grant_validator`` في المحرك الموحّد.

المشكلة المكتشفة (مثبتة عند خط الأساس 6d83cec): البوابة المحكومة
للكتابة (``ToolExecutor._check_permissions``) تتحقق من
``context.grant_validator(grant_id, permission)`` لكن لا يوجد أي مكون
إنتاجي يوصل سياسة منح EOE الحقيقية (``eoe.access_gateway``) بهذه
البوابة — الأدلة حتى E10-RP1 كانت تمرّر نمط اختباري يسمح بكل المنح
(mفصوح عنه، لكنه نمط اختباري).

هذه الوحدة هي الجسر الإنتاجي: تُبنى فوق عقد القبول الحقيقي
(``AccessAdmission``) وتحوّله إلى الدالة التي يستهلكها المحرك.
لا تُصدر منحًا ولا توقّع شيئًا — التوقيع والإصدار من جهة المالك
(``GrantorService``) والموافقة قبل ذلك؛ الجسر يتحقق فقط.

دلالات الربط:
- إذن المحرك "write" يحتاج منحة PATH_GRANT سارية بنطاق READ_WRITE
  تغطي جذر الأدلة المربوط (``artifacts_root``).
- إذن "read" تقبله أي منحة سارية تغطي الجذر (قراءة أو قراءة/كتابة).
- أي إذن آخر (مثل "execute") لا يمكن تأسيسه في سياسة منح EOE
  الحالية → رفض صريح (fail-closed) مع تسجيل السبب — لا توسيع
  صامت للسياسة.

الجذر المربوط هو نطاق المنحة على مستوى المهمة؛ عزل المسارات
داخل الجذر يبقى مسؤولية الـsandbox (طبقة دفاعية ثانية مستقلة).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from eoe.access_gateway import AccessAdmission, AccessDenied

#: إذن الكتابة كما تظهر في عقود أدوات المحرك الموحّد (مثل artifact_write).
ENGINE_PERMISSION_WRITE = "write"
#: إذن القراءة.
ENGINE_PERMISSION_READ = "read"

Validator = Callable[[str, str], bool]


def build_engine_grant_validator(
    admission: AccessAdmission,
    artifacts_root: str,
) -> Validator:
    """بناء ``grant_validator`` إنتاجي من عقد قبول EOE الحقيقي.

    الدالة المعادة تحقق منحةً بعينها (بهويتها — لا أي منحة أخرى)
    لكل استدعاء أداة محكوم. أي فشل (توقيع، سارية، إبطال، نطاق،
    تغطية مسار) أو أي إذن غير قابل للتأسيس → False (رفض).
    """
    root = str(Path(artifacts_root).resolve())

    def validator(grant_id: str, permission: str) -> bool:
        if permission == ENGINE_PERMISSION_WRITE:
            write = True
        elif permission == ENGINE_PERMISSION_READ:
            write = False
        else:
            # fail-closed: إذن لا تغطيه سياسة منح EOE يُرفض صراحة.
            return False
        try:
            admission.admit_grant_id(grant_id, write=write, path=root, depth=0)
        except AccessDenied:
            return False
        except Exception:
            # أي خطأ غير متوقع أثناء التحقق = رفض، لا سماح.
            return False
        return True

    return validator


__all__ = [
    "ENGINE_PERMISSION_WRITE",
    "ENGINE_PERMISSION_READ",
    "build_engine_grant_validator",
]
