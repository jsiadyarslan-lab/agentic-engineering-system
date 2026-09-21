# العقود الصارمة بين الأدوار الخمسة — CONTRACTS.md

كل تواصل بين الأدوار يمر عبر هذه العقود حصرًا. أي حقل جديد يُضاف هنا
أولًا (مع رقم إصدار عقد) ثم يُستخدم في الكود. العقود تُعرَّف برمجيًا
بنماذج pydantic في `src/roles/*.py` وتُختبر في `tests/contracts/`.

قواعد عامة:
- كل الأدوار تُعيد نتائج صادقة — لا SUCCESS إطلاقًا.
- `evidence_refs[]` دائمًا **مراجع** (مسارات/معرّفات/هاشات) لا محتوى.
- الفشل يوصف بمحلّه لا بتبرير عام.

---

## 1) THINKER — المفكر

**Request**
```json
{
  "goal": "string (إلزامي)",
  "context": "string",
  "constraints": ["string"],
  "previous_reviews": ["string"]
}
```

**Result**
```json
{
  "plan": {
    "tasks": [
      {"id": "string", "description": "string", "acceptance_criteria": ["string"]}
    ],
    "risks": ["string"],
    "assumptions": ["string"],
    "evidence_required": ["string"]
  }
}
```

الحالة الصادقة: **DRAFT**

---

## 2) REVIEWER — المدقق

**Request**
```json
{
  "plan": {"<عقد خطة المفكر كما أعلاه>"},
  "reviewer_checklist": ["string"],
  "previous_gaps": ["string"]
}
```

**Result**
```json
{
  "verdict": "approved | revise",
  "issues": ["string"],
  "required_changes": ["string"],
  "score": 0.0,
  "evolution_score": 0.0
}
```

- `score`: جودة الخطة 0.0–10.0. `evolution_score`: تحسّنها عن المراجعات
  السابقة 0.0–10.0.

الحالة الصادقة: **UNDER_REVIEW**

---

## 3) IMPLEMENTER — المنفذ

**Request**
```json
{
  "task": {"id": "string", "description": "string", "acceptance_criteria": ["string"]},
  "tools_available": ["string"],
  "sandbox_root": "string",
  "previous_attempts": ["string"]
}
```

**Result**
```json
{
  "status": "executed | failed",
  "artifacts": ["string"],
  "stdout_truncated": "string",
  "stderr_truncated": "string",
  "evidence_refs": ["string"]
}
```

الحالة الصادقة: **EXECUTED** — ليست SUCCESS أبدًا؛ كونها «نُفِّذت» لا
يعني «نجحت». القرار للمراجع ثم للمستخدم.

---

## 4) VERIFIER — المراجع

**Request**
```json
{
  "task_acceptance_criteria": ["string"],
  "artifacts": ["string"],
  "evidence_refs": ["string"]
}
```

**Result**
```json
{
  "verdict": "evidenced | not_evidenced",
  "checks_performed": ["string"],
  "missing_evidence": ["string"],
  "confidence": 0.0
}
```

- `confidence`: 0.0–1.0.
- `not_evidenced` **ليس فشلًا** — نقص أدلة يوثَّق ويُغذّي المُحكَّم.

الحالة الصادقة: **EVIDENCED** (وحكم not_evidenced فرعي يقود للمُحكَّم)

---

## 5) ARBITER — المُحكَّم (توقيع v2)

**Request**
```json
{
  "conflict_type": "string",
  "parties": ["string"],
  "evidences": ["string"],
  "history": ["string"]
}
```

**Result**
```json
{
  "decision": "string",
  "rationale": "string",
  "escalation_to_human": false,
  "max_retries_remaining": 0
}
```

الصلاحيات: يحسم الخلافات، يقرر إعادة التنفيذ (ضمن ميزانية إعادة مركزية
عنده وحده)، يصعّد للبشر، يمنع الدوران اللانهائي (تشخيص STAGNANT).

الحالة الصادقة: **ADJUDICATED** (أو ESCALATED_TO_HUMAN عند التصعيد)

---

## آلة الحالات الكاملة (13 حالة صادقة)

```text
DRAFT → UNDER_REVIEW → APPROVED → EXECUTING → EXECUTED → VERIFYING
      → EVIDENCED → ADJUDICATED → VERIFIED (من المستخدم وحده)

زوج الإيقاف الآمن (الأمر 004): STOPPING → STOPPED (نهائية — الاستئناف دورة جديدة)
الحالات السلبية: FAILED، ESCALATED_TO_HUMAN
حكمان فرعيان (ليسا حالتَي خطة): NOT_EVIDENCED (حكم المراجع)، STAGNANT (تشخيص المحكَّم)
```

**القاعدة الذهبية**: لا دور يمنح نفسه VERIFIED — الانتقال إليها يشترط
`actor == "user"` ويُفرض برمجيًا في `src/core/state.py`.

سلسلة المعنى الصادقة:

```text
EXECUTED (نُفِّذ)  ≠  EVIDENCED (أُثبت)  ≠  ADJUDICATED (حُسم)  ≠  VERIFIED (وافق المستخدم)
```
