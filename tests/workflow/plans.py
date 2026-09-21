"""خطط منظمة لاختبارات المحرك — ملف فريد يتجنب تضارب أسماء conftest."""

from __future__ import annotations

#: خطة منظمة: مرحلة واحدة بخطوتين — معايير ميكانيكية بملفات مسماة.
SCRIPTED_PLAN = {
    "objective": "تجميع تقرير موجز عن الموضوع",
    "assumptions": ["الأدوات متاحة"],
    "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
    "phases": [
        {
            "title": "المرحلة الأولى: التجميع",
            "objective": "تجميع المادة وكتابة المخرج",
            "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
            "steps": [
                {
                    "objective": "كتابة المخرج الأول",
                    "input": "مواد المصادر",
                    "expected_output": "ملف deliverable.md",
                    "acceptance_criteria": [
                        "الملف deliverable.md موجود ضمن الأدلة"
                    ],
                    "dependencies": [],
                },
                {
                    "objective": "كتابة المخرج الثاني",
                    "input": "مخرج الخطوة الأولى",
                    "expected_output": "ملف deliverable.md",
                    "acceptance_criteria": [
                        "الملف deliverable.md موجود ضمن الأدلة"
                    ],
                    "dependencies": [],
                },
            ],
        }
    ],
    "risks": ["مصادر ناقصة"],
    "dependencies": [],
    "required_owner_decisions": [],
}

#: خطة مرحلتين — لاختبار انتقال المراحل (§22.13).
TWO_PHASE_PLAN = {
    **SCRIPTED_PLAN,
    "phases": [
        {
            "title": "المرحلة الأولى",
            "objective": "أول وحدة عمل",
            "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
            "steps": [SCRIPTED_PLAN["phases"][0]["steps"][0]],
        },
        {
            "title": "المرحلة الثانية",
            "objective": "ثاني وحدة عمل",
            "acceptance_criteria": ["الملف deliverable.md موجود ضمن الأدلة"],
            "steps": [SCRIPTED_PLAN["phases"][0]["steps"][1]],
        },
    ],
}


