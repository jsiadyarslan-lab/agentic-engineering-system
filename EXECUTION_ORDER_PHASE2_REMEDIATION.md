# EXECUTION ORDER — PHASE 2.0 REMEDIATION
## إصلاح Phase 2.0: تنظيف الكود الكاذب + بناء الوكلاء الحقيقيين + إكمال النواة

---

### ⚠️ **الحقيقة المثبتة بالكود:**

| ما ادعى التقرير الكاذب | الواقع |
|---------------------|--------|
| 8 Agents مكتملة | **0/8** — لا يوجد أي ملف agent implementation |
| Workflow Engine مكتمل | **0/4** — مجلدات فارغة |
| Context/Memory مكتمل | **0/4** — مجلدات فارغة |
| CLI + Tests مكتملة | **0/2** — غير موجودة |
| Prompt Templates 6/6 | **1/6** — `explorer.yaml` فقط |

**النتيجة:** Phase 2.0 **غير مكتمل** — ما يوجد: LLM Layer ✅ + Skeletons + كود يحتاج تنظيف.

---

### §0 — عقد التنظيف والإصلاح (Hard Stops إلزامية)

1. **لا كود وهمي** — كل import يجب أن يشير لملف موجود.
2. **لا تكرار** — كل class/function معرف مرة واحدة.
3. **Imports في الأعلى** — حسب PEP 8، لا imports في منتصف/أسفل الملف.
4. **Fail-closed** — أي import مفقود = خطأ فوري، لا fallback صامت.
5. **الأدلة حقيقية** — كل agent ينتج `evidence_hash` صحيح من output حقيقي.

---

### §1 — التنظيف الفوري (يوم 1)

#### 1.1 إصلاح `src/factory/orchestrator.py`
```bash
# إزالة الاستيرادات الكاذبة (الأسطر 23-30, 46-50):
# from factory.agents.explorer import ExplorerAgent
# from factory.agents.thinker import ThinkerAgent
# ... (كلها غير موجودة)

# استبدال بـ:
# agents تُسجل ديناميكياً عبر AgentRegistry
```

#### 1.2 تنظيف `src/factory/contracts/agent_protocol.py`
```bash
# إزالة التكرارات الثلاثة:
# Handoff (مرات 3) → مرة واحدة
# AgentTask (مرات 3) → مرة واحدة  
# AgentResult (مرات 3) → مرة واحدة
```

#### 1.3 إصلاح `src/substrate/windows_executor.py`
```bash
# إزالة الدوال المكررة:
# _collect_artifacts (مرتين)
# _compute_evidence_hash (مرتين)
# _get_termination_status (مرتين)

# نقل imports للأعلى (الأسطر 642-686 → الأعلى)
# إزالة imports المكررة
```

#### 1.4 إصلاح `src/factory/orchestrator.py` imports
```bash
# إزالة imports المكررة في الأسفل (الأسطر 665-674)
# توحيد imports في الأعلى
```

**أوامر التحقق:**
```bash
python -c "import src.factory.orchestrator; print('orchestrator OK')"
python -c "import src.factory.contracts.agent_protocol; print('contracts OK')"
python -c "import src.substrate.windows_executor; print('windows_executor OK')"
```

---

### §2 — بناء الوكلاء الحقيقيين (الأولوية القصوى، أيام 2-8)

**قاعدة:** كل agent = ملف implementation + prompt template + test.

| الترتيب | الوكيل | الملفات المطلوبة | يعتمد على |
|---------|--------|----------------|----------|
| **1** | **Explorer** | `explorer.py` + `thinker.yaml` | `explorer.yaml` ✅ موجود |
| **2** | **Thinker** | `thinker.py` + `thinker.yaml` | Explorer output |
| **3** | **Planner** | `planner.py` + `planner.yaml` | Thinker output |
| **4** | **Designer** | `designer.py` + `designer.yaml` | Planner output |
| **5** | **Reviewer** | `reviewer.py` + `reviewer.yaml` | Plan + Design |
| **6** | **Implementer** | `implementer.py` + `implementer.yaml` | Reviewer approved |
| **7** | **Verifier** | `verifier.py` (لا prompt — ميكانيكي) | Implementer output |
| **8** | **Security** | `security.py` (لا prompt — ميكانيكي) | Verification passed |

---

### §2.1 — Explorer Agent (اليوم 2)

**ملفات:**
- `src/factory/agents/explorer.py`
- `src/llm/prompts/thinker.yaml` ← إنشاء

**العقدة الداخلة:** `AgentTask(task_type="explore", spec={"user_request": "..."})`
**العقدة الخارجة:** `ExplorationReport` (من `agent_protocol.py`)

**الأدوات:** `read_code`, `search_web`, `git_log`, `tree_sitter` (Python فقط)

**كود هيكل:**
```python
class ExplorerAgent(BaseAgent):
    agent_type = "explorer"
    agent_role = "Codebase Explorer"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. استخراج codebase path من context
        # 2. تشغيل tree-sitter analysis
        # 3. استدعاء LLM مع explorer.yaml prompt
        # 4. إرجاع ExplorationReport مع evidence_hash
```

---

### §2.2 — Thinker Agent (اليوم 3)

**ملفات:**
- `src/factory/agents/thinker.py`
- `src/llm/prompts/thinker.yaml`

**العقدة الداخلة:** `ExplorationReport` + `user_request`
**العقدة الخارجة:** `Analysis`

---

### §2.3 — Planner Agent (اليوم 4)

**ملفات:**
- `src/factory/agents/planner.py`
- `src/llm/prompts/planner.yaml`

**العقدة الداخلة:** `Analysis` + `ExplorationReport`
**العقدة الخارجة:** `Plan` مع `tasks[]` + `dependencies` + `estimates`

---

### §2.4 — Designer Agent (اليوم 5)

**ملفات:**
- `src/factory/agents/designer.py`
- `src/llm/prompts/designer.yaml`

**العقدة الداخلة:** `Plan`
**العقدة الخارجة:** `DesignSpec` مع `architecture`, `components`, `interfaces`, `data_models`, `api_contracts`

---

### §2.5 — Reviewer Agent (اليوم 6)

**ملفات:**
- `src/factory/agents/reviewer.py`
- `src/llm/prompts/reviewer.yaml`

**العقدة الداخلة:** `Plan` + `DesignSpec`
**العقدة الخارجة:** `Review` مع `approved: bool`, `issues[]`, `suggestions[]`

---

### §2.6 — Implementer Agent (اليوم 7)

**ملفات:**
- `src/factory/agents/implementer.py`
- `src/llm/prompts/implementer.yaml`

**العقدة الداخلة:** `Plan` + `DesignSpec` + `workspace` + `grants`
**العقدة الخارجة:** `ImplementationResult` مع `files_created`, `tests_added`, `build_command`, `test_command`

**التنفيذ الحقيقي:** يستخدم `WindowsExecutor` عبر `grants`

---

### §2.7 — Verifier Agent (اليوم 8) — **ميكانيكي، لا LLM**

**ملفات:**
- `src/factory/agents/verifier.py` (لا prompt)

**العقدة الداخلة:** `ImplementationResult` + `Plan` + `DesignSpec`
**العقدة الخارجة:** `Verification` مع `passed: bool`, `tests_passed`, `coverage`, `issues[]`

**التحقق الميكانيكي:**
- تشغيل `test_command` والتحقق من exit code
- مطابقة `files_created` مع `Plan.tasks`
- فحص `coverage` ضد threshold

---

### §2.8 — Security Agent (اليوم 8) — **ميكانيكي، لا LLM**

**ملفات:**
- `src/factory/agents/security.py` (لا prompt)

**العقدة الداخلة:** `ImplementationResult` + `Verification`
**العقدة الخارجة:** `SecurityReport` مع `vulnerabilities_found`, `secrets_found`, `dependencies_checked`

**الأدوات الحقيقية:**
- `bandit` / `semgrep` للـ SAST
- `pip-audit` / `safety` للـ dependencies
- `detect-secrets` / `truffleHog` للـ secrets

---

### §3 — Prompt Templates المفقودة (بالتوازي مع §2)

```bash
# إنشاء في src/llm/prompts/:
touch thinker.yaml planner.yaml designer.yaml reviewer.yaml implementer.yaml
```

**كل template يتبع نمط `explorer.yaml`:**
- `metadata`: agent, version, model_preference, temperature, max_tokens
- `system_prompt`: تعليمات صارمة (JSON فقط، لا markdown)
- `user_prompt_template`: مع variables置换
- `output_schema`: JSON Schema مطابق للعقدة الخارجة (`Analysis`, `Plan`, etc.)

---

### §4 — Workflow Engine + Context (أيام 9-11)

| الملف | الوصف |
|-------|-------|
| `src/factory/workflow/dag.py` | TaskDAG مع dependencies، parallel execution |
| `src/factory/workflow/engine.py` | WorkflowEngine مع retry، checkpoint، handoff verification |
| `src/factory/workflow/retry.py` | RetryPolicy مع exponential backoff |
| `src/factory/workflow/checkpoint.py` | CheckpointManager للـ resume |
| `src/factory/context/memory.py` | SharedContextManager مع SQLite |
| `src/factory/context/knowledge.py` | KnowledgeGraph (nodes/edges) |
| `src/factory/context/artifacts.py` | ArtifactRegistry مع hash-chaining |
| `src/factory/context/decisions.py` | DecisionLog (ADR-style) |

---

### §5 — CLI + Integration Test (أيام 12-13)

| الملف | الوصف |
|-------|-------|
| `src/factory/cli.py` | `factory chat`، `factory run`، `factory resume`، `factory status` |
| `tests/factory/test_full_mission.py` | End-to-end test: user request → COMPLETED مع أدلة |

**اختبار التكامل:**
```python
async def test_full_mission():
    # User: "أصلح regex في src/api/users.py"
    mission = await orchestrator.start_mission("أصلح regex...")
    # esperar COMPLETED
    assert mission.state == MissionState.COMPLETED
    assert len(mission.evidence_hashes) >= 8  # لكل وكيل
    # التحقق من evidence hashes
```

---

### §6 — معايير القبول النهائية (Definition of Done)

```bash
# 1. Orchestrator يعمل بلا ImportError
python -c "from factory.orchestrator import AgentFactoryOrchestrator; print('OK')"

# 2. كل الوكلاء الـ 8 يستوردون وينفذون
python -c "
from factory.agents.explorer import ExplorerAgent
from factory.agents.thinker import ThinkerAgent
# ... all 8
print('All agents OK')
"

# 3. Prompt templates كلها موجودة
ls src/llm/prompts/*.yaml | wc -l  # يجب أن يكون 6

# 4. تنظيف الكود يمر
python -c "
import src.factory.orchestrator
import src.factory.contracts.agent_protocol
import src.substrate.windows_executor
print('Clean imports OK')
"

# 5. Integration test يمر
python -m pytest tests/factory/test_full_mission.py -v -s  # PASS

# 6. مهمة حقيقية تنجح
factory run "أصلح typo في README.md"  # يكمل بـ COMPLETED مع أدلة
```

---

### §7 — قالب التقرير الإلزامي

```
VERDICT: PASS / HARD STOP
CLEANUP COMPLETE: YES / NO
ALL 8 AGENTS IMPLEMENTED: عدد/8
PROMPT TEMPLATES COMPLETE: عدد/6
WORKFLOW ENGINE WORKS: YES / NO
CONTEXT MEMORY WORKS: YES / NO
CLI WORKS: YES / NO
INTEGRATION TEST PASS: YES / NO
REAL MISSION SUCCESS: YES / NO
EVIDENCE HASHES VALID: YES / NO
HARD STOPS FIRED: عدد أو NONE
ZERO-WRITE PROOF: قبل/بعد بصمة الملفات المحدثة
```

---

### §8 — حدود الصدق

1. **لا agent وهمي** — إذا `import` يفشل، التقرير يفشل.
2. **لا نجاح زائف** — `test_full_mission.py` يجب أن يمر فعلاً.
3. **الأدلة حقيقية** — كل `evidence_hash` يحسب من output حقيقي.
4. **Verifier/Security ميكانيكيان** — لا LLM فيهما.

---

### §9 — إثبات الكتابة-صفر قبل وبعد

```bash
python -c "
import hashlib, os
files = [
    'src/factory/orchestrator.py',
    'src/factory/contracts/agent_protocol.py',
    'src/substrate/windows_executor.py',
    'src/factory/agents/explorer.py',
    'src/factory/agents/thinker.py',
    'src/factory/agents/planner.py',
    'src/factory/agents/designer.py',
    'src/factory/agents/reviewer.py',
    'src/factory/agents/implementer.py',
    'src/factory/agents/verifier.py',
    'src/factory/agents/security.py',
    'src/factory/workflow/dag.py',
    'src/factory/workflow/engine.py',
    'src/factory/context/memory.py',
    'src/factory/cli.py',
    'tests/factory/test_full_mission.py',
]
for f in files:
    h = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16] if os.path.exists(f) else 'MISSING'
    print(f'{f}: {h}')
"
```

---

**END OF ORDER**