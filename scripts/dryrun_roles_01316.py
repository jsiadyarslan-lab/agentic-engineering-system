# -*- coding: utf-8 -*-
"""تجفيف عقود الأدوار الحية على zai_internal/glm-4.6 (013.16 قبل الجلسة).

ليس إنشاء مهمة — لا حالة مهمة ولا واجهة ولا مجلدات: استدعاء مباشر
للأدوار الحية بالهدف نفسه لهدف E11 للتحقق من التزام النموذج بعقود
JSON الصارمة قبل تشغيل الجلسة الحية الكاملة.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from roles.live import ReviewerLive, ThinkerLive  # noqa: E402
from roles.thinker import ThinkerRequest  # noqa: E402
from roles.reviewer import ReviewerRequest  # noqa: E402
from router.model_router import ModelRouter  # noqa: E402

GOAL = (
    "مهمة برمجية: اكتب أداة Python باسم tool.py تستخدم المكتبات القياسية "
    "فقط (stdlib)، تقرأ ملف transactions.csv وتنتج report.md بالإجماليات. "
    "بيانات الإدخال ستة سجلات بإجمالي كلي 85.00: food بإجمالي 25.00 "
    "وtravel بإجمالي 40.00 وtools بإجمالي 20.00. اكتب أيضًا ملف اختبارات "
    "test_tool.py يغطي ثلاث حالات: الإدخال الصحيح، وملف CSV فارغ (ترفضه "
    "الأداة برمز خروج غير صفري)، ومبلغ غير صالح (ترفضه الأداة برمز خروج "
    "غير صفري). نفّذ الأداة والاختبارات فعليًا داخل الركيزة المعزولة "
    "وتحقق أن report.md ناتج فعلي من تنفيذ الأداة."
)


def main() -> int:
    router = ModelRouter.build_live(require_default=False)
    print("providers:", router.live_providers())

    t0 = time.monotonic()
    thinker = ThinkerLive(router)
    plan_result = thinker.run(ThinkerRequest(goal=GOAL))
    t_plan = time.monotonic() - t0
    plan = plan_result.plan
    print(f"thinker OK in {t_plan:.1f}s — tasks={len(plan.tasks)} "
          f"risks={len(plan.risks)}")
    for task in plan.tasks:
        print(f"  task {task.id}: {task.description[:90]}")
        for criterion in task.acceptance_criteria:
            print(f"    criterion: {criterion[:100]}")

    t1 = time.monotonic()
    reviewer = ReviewerLive(router)
    review = reviewer.run(ReviewerRequest(plan=plan, previous_gaps=[]))
    t_rev = time.monotonic() - t1
    print(f"reviewer OK in {t_rev:.1f}s — verdict={review.verdict.value} "
          f"score={review.score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
