# EXECUTION ORDER — PHASE 2.0 REMEDIATION: PART 2/3
## بناء 5 وكلاء أساسيين: Thinker, Planner, Designer, Reviewer, Implementer

---

### §0 — عقد التنفيذ

1. **المتطلب المسبق**: Part 1 مكتمل 100% (التنظيف + LLM + Explorer يعمل).
2. **الهدف**: بناء 5 وكلاء حقيقيين مع Prompt Templates.
3. **الترتيب الإلزامي**: Thinker → Planner → Designer → Reviewer → Implementer (كل وكيل يعتمد على سابقه).
4. **لا وكيل يعمل بلا Prompt Template** — الـ YAML يُنشأ قبل الـ .py.

---

### §1 — Thinker Agent

#### 1.1 Prompt Template
```bash
touch src/llm/prompts/thinker.yaml
# يتبع نمط explorer.yaml: metadata, system_prompt, user_prompt_template, output_schema
# output_schema يطابق Analysis من agent_protocol.py
```

#### 1.2 Implementation
```bash
touch src/factory/agents/thinker.py
```

**المواصفات:**
```python
class ThinkerAgent(BaseAgent):
    agent_type = "thinker"
    agent_role = "Root Cause Analyst"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. استلام ExplorationReport من task.spec
        # 2. استدعاء LLM مع thinker.yaml prompt
        # 3. إرجاع Analysis مع evidence_hash
```

**العقدة الداخلة:** `ExplorationReport` + `user_request`
**العقدة الخارجة:** `Analysis` من `agent_protocol.py`

---

### §2 — Planner Agent

#### 2.1 Prompt Template
```bash
touch src/llm/prompts/planner.yaml
```

#### 2.2 Implementation
```bash
touch src/factory/agents/planner.py
```

**المواصفات:**
```python
class PlannerAgent(BaseAgent):
    agent_type = "planner"
    agent_role = "Execution Planner"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. استلام Analysis + ExplorationReport
        # 2. استدعاء LLM مع planner.yaml
        # 3. إرجاع Plan مع tasks[], dependencies, estimates, risks
```

**العقدة الداخلة:** `Analysis` + `ExplorationReport`
**العقدة الخارجة:** `Plan` من `agent_protocol.py`

---

### §3 — Designer Agent

#### 3.1 Prompt Template
```bash
touch src/llm/prompts/designer.yaml
```

#### 3.2 Implementation
```bash
touch src/factory/agents/designer.py
```

**المواصفات:**
```python
class DesignerAgent(BaseAgent):
    agent_type = "designer"
    agent_role = "System Designer"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. استلام Plan
        # 2. استدعاء LLM مع designer.yaml
        # 3. إرجاع DesignSpec مع architecture, components, interfaces, data_models, api_contracts
```

**العقدة الداخلة:** `Plan`
**العقدة الخارجة:** `DesignSpec` من `agent_protocol.py`

---

### §4 — Reviewer Agent

#### 4.1 Prompt Template
```bash
touch src/llm/prompts/reviewer.yaml
```

#### 4.2 Implementation
```bash
touch src/factory/agents/reviewer.py
```

**المواصفات:**
```python
class ReviewerAgent(BaseAgent):
    agent_type = "reviewer"
    agent_role = "Plan & Design Reviewer"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. استلام Plan + DesignSpec
        # 2. استدعاء LLM مع reviewer.yaml
        # 3. إرجاع Review مع approved: bool, issues[], suggestions[]
```

**العقدة الداخلة:** `Plan` + `DesignSpec`
**العقدة الخارجة:** `Review` من `agent_protocol.py`

---

### §5 — Implementer Agent

#### 5.1 Prompt Template
```bash
touch src/llm/prompts/implementer.yaml
```

#### 5.2 Implementation
```bash
touch src/factory/agents/implementer.py
```

**المواصفات:**
```python
class ImplementerAgent(BaseAgent):
    agent_type = "implementer"
    agent_role = "Code Implementer"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. استلام Plan + DesignSpec + workspace + grants
        # 2. استخدام WindowsExecutor عبر grants للكتابة
        # 3. إنشاء/تعديل ملفات، تشغيل اختبارات
        # 4. إرجاع ImplementationResult مع files_created, tests_added, build_command, test_command
```

**العقدة الداخلة:** `Plan` + `DesignSpec` + `workspace` + `grants`
**العقدة الخارجة:** `ImplementationResult` من `agent_protocol.py`

---

### §6 — معايير القبول النهائية (Part 2)

```bash
# 1. كل الـ 5 وكلاء يستوردون
python -c "
from factory.agents.thinker import ThinkerAgent
from factory.agents.planner import PlannerAgent
from factory.agents.designer import DesignerAgent
from factory.agents.reviewer import ReviewerAgent
from factory.agents.implementer import ImplementerAgent
print('✅ All 5 agents OK')
"

# 2. Prompt templates: 6/6 مكتملة
ls src/llm/prompts/*.yaml | wc -l  # 6

# 3. كل وكيل ينفذ execute() ويعيد AgentResult صحيح
python -c "
import asyncio
from factory.agents.thinker import ThinkerAgent
# ... اختبار سريع لكل وكيل مع mock task
print('✅ Agents execute OK')
"

# 2. Zero-write proof
python -c "
import hashlib, os
files = [
    'src/factory/agents/thinker.py',
    'src/factory/agents/planner.py',
    'src/factory/agents/designer.py',
    'src/factory/agents/reviewer.py',
    'src/factory/agents/implementer.py',
    'src/llm/prompts/thinker.yaml',
    'src/llm/prompts/planner.yaml',
    'src/llm/prompts/designer.yaml',
    'src/llm/prompts/reviewer.yaml',
    'src/llm/prompts/implementer.yaml',
]
for f in files:
    h = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16] if os.path.exists(f) else 'MISSING'
    print(f'{f}: {h}')
"
```

---

### §7 — قالب التقرير الإلزامي (Part 2)

```
VERDICT: PASS / HARD STOP
THINKER AGENT: YES / NO
PLANNER AGENT: YES / NO
DESIGNER AGENT: YES / NO
REVIEWER AGENT: YES / NO
IMPLEMENTER AGENT: YES / NO
ALL 5 PROMPTS CREATED: YES / NO (count/5)
ALL AGENTS IMPORT: YES / NO
HARD STOPS FIRED: عدد أو NONE
ZERO-WRITE PROOF: قبل/بعد بصمة الـ 10 ملفات
```

---

**END OF PART 2 ORDER**