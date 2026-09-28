# EXECUTION ORDER — PHASE 2.0 REMEDIATION: PART 3/3
## الوكلاء الميكانيكيان (Verifier, Security) + Workflow Engine + Context + CLI + Integration Test

---

### §0 — عقد التنفيذ

1. **المتطلب المسبق**: Part 1 + Part 2 مكتملان 100%.
2. **الهدف**: إكمال النواة الصلبة — وكلاء ميكانيكيان + محرك سير العمل + سياق/ذاكرة + CLI + اختبار تكامل كامل.
3. **Verifier & Security ميكانيكيان فقط** — لا LLM، أدوات حقيقية فقط.

---

### §1 — Verifier Agent (ميكانيكي، لا LLM)

```bash
touch src/factory/agents/verifier.py
# لا prompt template
```

**المواصفات:**
```python
class VerifierAgent(BaseAgent):
    agent_type = "verifier"
    agent_role = "Mechanical Verifier"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. استلام ImplementationResult + Plan + DesignSpec
        # 2. تشغيل test_command من ImplementationResult
        # 3. فحص exit_code == 0
        # 4. مطابقة files_created مع Plan.tasks
        # 5. حساب coverage (إذا متاح)
        # 6. إرجاع Verification مع passed: bool, tests_passed, coverage, issues[]
```

**العقدة الداخلة:** `ImplementationResult` + `Plan` + `DesignSpec`
**العقدة الخارجة:** `Verification` من `agent_protocol.py`

---

### §2 — Security Agent (ميكانيكي، لا LLM)

```bash
touch src/factory/agents/security.py
# لا prompt template
```

**المواصفات:**
```python
class SecurityAgent(BaseAgent):
    agent_type = "security"
    agent_role = "Security Auditor"
    
    async def execute(self, task: AgentTask) -> AgentResult:
        # 1. استلام ImplementationResult + Verification
        # 2. تشغيل SAST: bandit / semgrep على الملفات المنتجة
        # 3. فحص secrets: detect-secrets / truffleHog
        # 4. فحص dependencies: pip-audit / safety
        # 5. إرجاع SecurityReport مع vulnerabilities_found, secrets_found, dependencies_checked, issues[]
```

**الأدوات الحقيقية (يجب توفرها):**
- `bandit` أو `semgrep` للـ SAST
- `detect-secrets` للـ secrets
- `pip-audit` أو `safety` للـ dependencies

**العقدة الداخلة:** `ImplementationResult` + `Verification`
**العقدة الخارجة:** `SecurityReport` من `agent_protocol.py`

---

### §3 — Workflow Engine (4 ملفات)

```bash
mkdir -p src/factory/workflow
touch src/factory/workflow/{dag.py,engine.py,retry.py,checkpoint.py}
```

| الملف | المسؤولية |
|-------|-----------|
| `dag.py` | TaskDAG: إضافة مهام، dependencies، topological sort، parallel execution groups |
| `engine.py` | WorkflowEngine: تنفيذ DAG، handoff verification، checkpoint كل مهمة |
| `retry.py` | RetryPolicy: exponential backoff، max retries، jitter |
| `checkpoint.py` | CheckpointManager: save/load mission state، resume من أي مهمة |

**التكامل:** `Orchestrator` يستخدم `WorkflowEngine` بدلاً من state machine المباشر.

---

### §4 — Context + Memory (4 ملفات)

```bash
mkdir -p src/factory/context
touch src/factory/context/{memory.py,knowledge.py,artifacts.py,decisions.py}
```

| الملف | المسؤولية |
|-------|-----------|
| `memory.py` | SharedContextManager: initialize_mission, get_workspace, summarize, prioritize |
| `knowledge.py` | KnowledgeGraph: SQLite، nodes (files, functions, decisions)، edges (calls, depends) |
| `artifacts.py` | ArtifactRegistry: hash-chained artifacts، register/get/verify |
| `decisions.py` | DecisionLog: ADR-style decisions مع rationale، search، link |

**التكامل:** كل agent يستلم `SharedContextManager` في `__init__`.

---

### §5 — CLI Entry Point

```bash
touch src/factory/cli.py
```

**الأوامر:**
```bash
factory chat                 # محادثة تفاعلية
factory run "task"           # تشغيل مهمة مباشرة
factory resume <mission_id>  # استئناف من checkpoint
factory status <mission_id>  # حالة المهمة
factory evidence <mission_id> # تصفح الأدلة
```

---

### §6 — Integration Test (Full Mission)

```bash
mkdir -p tests/factory
touch tests/factory/test_full_mission.py
```

**اختبار التكامل:**
```python
async def test_full_mission():
    orchestrator = AgentFactoryOrchestrator(...)
    mission = await orchestrator.start_mission("أصلح typo في README.md")
    
    # انتظار الإنجاز
    await asyncio.wait_for(mission.completed_event, timeout=300)
    
    # التحقق
    assert mission.state == MissionState.COMPLETED
    assert len(mission.evidence_hashes) >= 8  # لكل وكيل
    assert mission.implementation_result is not None
    assert mission.verification.passed == True
    assert mission.security_report.vulnerabilities_found == 0
    
    # التحقق من evidence hashes حقيقية
    for h in mission.evidence_hashes:
        assert len(h) == 64  # SHA256
```

---

### §7 — معايير القبول النهائية (Part 3 + Phase 2.0 Complete)

```bash
# 1. الوكلاء الميكانيكيان
python -c "
from factory.agents.verifier import VerifierAgent
from factory.agents.security import SecurityAgent
print('✅ Mechanical agents OK')
"

# 2. Workflow Engine
python -c "
from factory.workflow.dag import TaskDAG
from factory.workflow.engine import WorkflowEngine
from factory.workflow.retry import RetryPolicy
from factory.workflow.checkpoint import CheckpointManager
print('✅ Workflow Engine OK')
"

# 3. Context/Memory
python -c "
from factory.context.memory import SharedContextManager
from factory.context.knowledge import KnowledgeGraph
from factory.context.artifacts import ArtifactRegistry
from factory.context.decisions import DecisionLog
print('✅ Context/Memory OK')
"

# 4. CLI يعمل
factory --help  # يظهر الأوامر
factory run "echo test"  # يعمل (mock)

# 5. Integration Test يمر
python -m pytest tests/factory/test_full_mission.py -v -s  # PASS

# 6. مهمة حقيقية تنجح
factory run "أصلح typo في README.md"  # → COMPLETED مع أدلة

# 7. Zero-write proof لجميع ملفات Part 3
python -c "
import hashlib, os
files = [
    'src/factory/agents/verifier.py',
    'src/factory/agents/security.py',
    'src/factory/workflow/dag.py',
    'src/factory/workflow/engine.py',
    'src/factory/workflow/retry.py',
    'src/factory/workflow/checkpoint.py',
    'src/factory/context/memory.py',
    'src/factory/context/knowledge.py',
    'src/factory/context/artifacts.py',
    'src/factory/context/decisions.py',
    'src/factory/cli.py',
    'tests/factory/test_full_mission.py',
]
for f in files:
    h = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16] if os.path.exists(f) else 'MISSING'
    print(f'{f}: {h}')
"
```

---

### §8 — قالب التقرير الإلزامي (Part 3 + Final)

```
VERDICT: PASS / HARD STOP
VERIFIER AGENT (mechanical): YES / NO
SECURITY AGENT (mechanical): YES / NO
WORKFLOW ENGINE (4/4): YES / NO
CONTEXT/MEMORY (4/4): YES / NO
CLI ENTRY POINT: YES / NO
INTEGRATION TEST: PASS / FAIL
REAL MISSION SUCCESS: YES / NO
ALL 8 AGENTS WORK: 8/8
ALL 6 PROMPTS: 6/6
PHASE 2.0 COMPLETE: YES / NO
HARD STOPS FIRED: عدد أو NONE
ZERO-WRITE PROOF: قبل/بعد بصمة جميع الملفات الجديدة
```

---

**END OF PART 3 ORDER — PHASE 2.0 COMPLETE**