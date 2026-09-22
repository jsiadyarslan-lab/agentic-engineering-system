"""مساعد اختبارات التخطيط الخلفي (013.4 §1) — انتظار صادق لا سقف مفتوح.

POST /plan/generate صار أمرًا خلفيًا محدودًا: يعيد فورًا وصف الجلسة،
والخطة تظهر عند اكتمال الجلسة. هذه الأداة تنتظر النتيجة النهائية
(خطة تنتظر اعتمادًا / فشلًا مصنّفًا) بمهلة صريحة.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def generate_plan_and_wait(client, pid: int, *, timeout: float = 20.0):
    """أمر التوليد ثم انتظار نتيجته — يعيد (استجابة الأمر، التفصيل).

    الفشل المصنّف يرفع AssertionError مع نص error_class — لا انتظار
    أبديًا ولا نجاحًا وهميًا.
    """
    out = client.post(f"/api/projects/{pid}/plan/generate")
    assert out.status_code == 200, out.text
    return out, wait_for_plan(client, pid, timeout=timeout)


def wait_for_plan(client, pid: int, *, timeout: float = 20.0) -> dict:
    """انتظار خطة تنتظر الاعتماد (أو فشل صريح) — يعيد تفصيل المشروع."""
    deadline = time.monotonic() + float(timeout)
    last = {}
    while time.monotonic() < deadline:
        detail = client.get(f"/api/projects/{pid}")
        assert detail.status_code == 200, detail.text
        last = detail.json()
        plan = last.get("plan")
        if plan is not None and plan.get("status") in (
            "AWAITING_OWNER_APPROVAL", "ACTIVE", "SUPERSEDED"
        ):
            return last
        error = last.get("last_error") or ""
        if last.get("status") in ("DRAFT", "BLOCKED") and error:
            raise AssertionError(
                f"فشل توليد الخطة: {error[:300]}"
            )
        time.sleep(0.05)
    raise AssertionError(
        f"التخطيط لم يكتمل خلال {timeout}ث — الحالة الأخيرة: "
        f"{last.get('status')} / {last.get('last_error', '')[:200]}"
    )
