# EXECUTION ORDER — PHASE 2.0 REMEDIATION: PART 1/3
## التنظيف الإلزامي + LLM Layer + Explorer Agent

---

### §0 — عقد التنفيذ

1. **المستودع**: jsiadyarslan-lab/agentic-engineering-system — **الفرع**: main — **الوضع**: WRITE_LOCAL.
2. **الهدف**: تنظيف الكود الكاذب/المكرر + إكمال LLM Layer + بناء أول وكيل حقيقي (Explorer).
3. **المنح**: PATH_GRANT قراءة وكتابة على `src/factory/`، `src/llm/`، `src/substrate/`، `src/factory/contracts/`.
4. أي كود وهمي/مكرر = **HARD STOP**.
3. **الأوامر المسموحة**: `python`، `pip`، `pytest`، `grep`، `sed`، `cat`، `mkdir`، `touch`.
4. **الدفع**: لا دفع.

---

### §1 — التنظيف الإلزامي (يجب أن يمر قبل أي كود جديد)

#### 1.1 إصلاح `src/factory/orchestrator.py`
```bash
# إزالة الاستيرادات الكاذبة (الأسطر 23-30, 46-50):
# from factory.agents.explorer import ExplorerAgent
# from factory.agents.thinker import ThinkerAgent
# ... (كلها غير موجودة)

# إزالة imports المكررة في الأسفل (الأسطر 665-674)
# نقل كل imports للأعلى، توحيدها
```

#### 1.2 تنظيف `src/factory/contracts/agent_protocol.py`
```bash
# إزالة التكرارات الثلاثة:
# Handoff (مرات 3) → تعريف واحد
# AgentTask (مرات 3) → تعريف واحد  
# AgentResult (مرات 3) → تعريف واحد
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

#### 1.4 التحقق الإلزامي (HARD STOP إذا فشل)
```bash
python -c "import src.factory.orchestrator; print('orchestrator OK')"
python -c "import src.factory.contracts.agent_protocol; print('contracts OK')"
python -c "import src.substrate.windows_executor; print('windows_executor OK')"
python -c "import src.factory.agents.base; print('base_agent OK')"
```

---

### §2 — إكمال LLM Layer (إذا غير مكتمل)

```bash
# التحقق مما يوجد
ls src/llm/
# يجب أن يوجد: provider.py, structured.py, budget.py, nvidia_provider.py, __init__.py, prompts/explorer.yaml

# إذا ناقص أي ملف → إنشاؤه وفق مواصفات Phase 0.5
```

**معايير القبول:**
```bash
python -c "
from llm import NVIDIAProvider, StructuredLLM, TokenBudget
from llm.provider import LLMProvider, LLMMessage, LLMResponse
from llm.structured import StructuredLLM, parse_structured_output
from llm.budget import TokenBudget, BudgetExceeded, estimate_tokens
print('LLM Layer OK')
"
```

---

### §3 — Explorer Agent (أول وكيل حقيقي)

#### 3.1 إنشاء Prompt Template
```bash
touch src/llm/prompts/thinker.yaml
# يتبع نمط explorer.yaml الموجود
```

#### 3.2 بناء Explorer Agent
```bash
touch src/factory/agents/explorer.py
```

**المواصفات:**
```python
class ExplorerAgent(BaseAgent):
    agent_type = "explorer"
    agent_role = "Codebase Explorer"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. قراءة codebase path من context
        # 2. Tree-sitter analysis (Python files)
        # 3. استدعاء LLM مع explorer.yaml prompt
        # 4. إرجاع ExplorationReport مع evidence_hash صحيح
```

**العقدة الداخلة:** `AgentTask(task_type="explore", spec={"user_request": "..."})`
**العقدة الخارجة:** `ExplorationReport` من `agent_protocol.py`

---

### §4 — معايير القبول النهائية (Part 1)

```bash
# 1. التنظيف يمر
python -c "import src.factory.orchestrator; import src.factory.contracts.agent_protocol; import src.substrate.windows_executor; print('✅ Cleanup OK')"

# 2. LLM Layer يعمل
python -c "from llm import NVIDIAProvider, StructuredLLM, TokenBudget; print('✅ LLM OK')"

# 3. Explorer Agent موجود ويستورد
python -c "from factory.agents.explorer import ExplorerAgent; print('✅ Explorer OK')"

# 4. Prompt templates: 2/6 على الأقل
ls src/llm/prompts/*.yaml | wc -l  # ≥ 2

# 5. لا تكرار في الكود النظيف
python -c "
import ast, sys
for f in ['src/factory/orchestrator.py', 'src/factory/contracts/agent_protocol.py', 'src/substrate/windows_executor.py']:
    with open(f) as fp:
        tree = ast.parse(fp.read())
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    print(f'{f}: {len(imports)} imports')
"

# 6. Zero-write proof
python -c "
import hashlib, os
for f in ['src/factory/orchestrator.py', 'src/factory/contracts/agent_protocol.py', 'src/substrate/windows_executor.py', 'src/factory/agents/explorer.py', 'src/llm/prompts/thinker.yaml']:
    h = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16] if os.path.exists(f) else 'MISSING'
    print(f'{f}: {h}')
"
```

---

### §5 — قالب التقرير الإلزامي (Part 1)

```
VERDICT: PASS / HARD STOP
CLEANUP COMPLETE: YES / NO (which files)
LLM LAYER COMPLETE: YES / NO
EXPLORER AGENT WORKS: YES / NO
THINKER.YAML CREATED: YES / NO
IMPORTS CLEAN: YES / NO (list any remaining duplicates)
HARD STOPS FIRED: عدد أو NONE
ZERO-WRITE PROOF: قبل/بعد بصمة الملفات
```

---

**END OF PART 1 ORDER**