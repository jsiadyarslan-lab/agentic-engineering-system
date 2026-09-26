# EXECUTION ORDER — ORCHESTRATOR CORE + WINDOWS EXECUTION BACKEND (Phase 2.0)
## بناء الأوركستر + وكلاء حقيقيون + backend تنفيذي على Windows (subprocess + Job Objects)

---

### §0 — عقد التنفيذ الصلب

1. **المستودع**: jsiadyarslan-lab/agentic-engineering-system — **الفرع**: main — **الوضع**: WRITE_LOCAL.
2. **الهدف الوحيد**: بناء أوركستر كامل ينسق 7 وكلاء حقيقيين (Explorer, Thinker, Planner, Designer, Reviewer, Implementer, Verifier, Security) مع backend تنفيذي يعمل على Windows اليوم — ينتج كود حقيقي، أدلة حقيقية، موافقة بشرية حقيقية.
3. **المنح المطلوبة**:
   - PATH_GRANT قراءة وكتابة على `src/factory/` — للأوركستر والوكلاء
   - PATH_GRANT قراءة وكتابة على `src/llm/` — للـ LLM Layer (موجود)
   - PATH_GRANT قراءة وكتابة على `src/substrate/windows_executor.py` — للـ backend الجديد
   - PATH_GRANT قراءة على `src/contracts/` — للعقود الموجودة
4. أي كتابة خارج المسارات الممنوحة = **HARD STOP** فوري.
5. انحراف الأساس عن `origin/main` قبل البدء = **HARD STOP**.
6. لا استنتاج: كل وكييل يتبع عقدته، الاتصال عبر Handoff موقّع، الأدلة تُجمع ميكانيكياً.
7. **الأوامر المسموحة**: `python`، `pip`، `pytest`، `grep`، `cat` — كل أمر خارجها = **HARD STOP**.
8. **الدفع**: لا دفع — أمر محلي فقط.

---

### §1 — Orchestrator Core (src/factory/orchestrator.py)

**المتطلبات:**
1. `AgentFactoryOrchestrator` class — المحاور والموزع
2. State Machine للمهمة (Mission States):
   ```
   IDLE → LISTENING → EXPLORING → ANALYZING → PLANNING
        → DESIGNING → REVIEWING → AWAITING_APPROVAL
        → EXECUTING → VERIFYING → SECURITY_CHECK
        → COMPLETED | REVISING | BLOCKED | ABORTED | ESCALATED
   ```
3. `HumanApprovalGate` — واجهة محادثة CLI للموافقة البشرية
4. `SharedContextManager` — سياق مشترك بين الوكلاء (in-memory + persistence)
5. `AgentRegistry` — تسجيل واكتشاف الوكلاء السبعة
6. `Mission` dataclass — تتبع المهمة الكاملة مع التاريخ

**القيود:**
- لا substrate — يستخدم `WindowsExecutor` (§3) للتنفيذ
- كل انتقال حالة مسجل في `DecisionLog` مع timestamp + actor
- Human approval إلزامي قبل EXECUTING
- Checkpoint كل انتقال حالة (يمكن الاستئناف)

**الأوامر:**
- mkdir -p src/factory/{orchestrator,state,human,context,agents,workflow}
- cat > src/factory/orchestrator.py << 'PYEOF'
  # ... (التنفيذ الكامل)
PYEOF

---

### §2 — Human Gate + Chat Interface (src/factory/human/)

**المتطلبات:**
1. `HumanApprovalGate` — يعرض الخطة/التصميم، ينتظر رد المستخدم
2. `ChatInterface` — CLI تفاعلي مع history
3. خيارات الرد: `✅ موافقة` / `🔄 تعديل` / `❌ رفض` / `💬 مناقشة`
4. كل رد مخزن كـ `HumanDecision` في `DecisionLog`
5. Timeout قابل للتكوين (افتراضي 24 ساعة)

**الأوامر:**
- cat > src/factory/human/gate.py << 'PYEOF'
- cat > src/factory/human/chat.py << 'PYEOF'
- cat > src/factory/human/format.py << 'PYEOF'

---

### §3 — Windows Execution Backend (src/substrate/windows_executor.py)

**المتطلبات:**
1. `WindowsExecutor` class — يحل محل substrate على Windows
2. `execute(cmd, limits, env, working_dir) -> ExecutionResult`
3. **Job Objects** للعزل الجزئي:
   - Memory limit: `JOB_OBJECT_LIMIT_PROCESS_MEMORY` + `JOB_OBJECT_LIMIT_JOB_MEMORY`
   - CPU limit: `JOB_OBJECT_LIMIT_PROCESS_TIME` + `JOBOBJECT_CPU_RATE_CONTROL`
   - Process count: `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`
   - Working directory enforcement
4. **لا عزل filesystem/network** — موثق بصراحة في `ExecutionResult.isolation_level = "PARTIAL_JOB_OBJECT"`
5. Evidence collection حقيقي:
   - `stdout`, `stderr`, `exit_code`, `duration_ms`
   - `evidence_hash` = SHA256(cmd + stdout + stderr + limits_json)
   - File hashes لأي ملفات مكتوبة في working_dir
6. Timeout enforcement مع `wait_for_single_object`

**القيود:**
- يستخدم `pywin32` للـ Job Objects API
- Falls back إلى `subprocess` بسيط إذا Job Objects غير متاح
- **لا يدعي عزل حقيقي** — `isolation_level` يعكس الواقع بصراحة
- Structured logging لكل تنفيذ

**الأوامر:**
- pip install pywin32
- mkdir -p src/substrate
- cat > src/substrate/windows_executor.py << 'PYEOF'
  # ... (التنفيذ الكامل مع Job Objects)
PYEOF

---

### §4 — Agent Base Class + Contracts (src/factory/agents/base.py)

**المتطلبات:**
1. `BaseAgent` abstract class — جميع الوكلاء يرثون منه
2. `__init__(llm: StructuredLLM, context: SharedContext, grants: GrantManager)`
3. `async execute(task: AgentTask) -> AgentResult` — نقطة الدخول الوحيدة
4. Lifecycle hooks: `on_start`, `on_complete`, `on_failed`, `on_handoff_received`
5. Context management: `compact_context(budget)`, `prioritize_context(task)`
6. Structured output عبر `StructuredLLM.structured_chat()`

**العقود (src/factory/contracts/):**
- `AgentTask` — مهمة واحدة مع type, spec, acceptance_criteria, dependencies
- `AgentResult` — outcome مع artifacts, evidence, next_actions
- `Handoff` — تسليم بين وكلاء مع HMAC signature
- `ExplorationReport`, `Analysis`, `Plan`, `DesignSpec`, `Review`, `ImplementationResult`, `Verification`, `SecurityReport`

**الأوامر:**
- mkdir -p src/factory/contracts
- cat > src/factory/agents/base.py << 'PYEOF'
- cat > src/factory/contracts/__init__.py << 'PYEOF'
- cat > src/factory/contracts/agent_protocol.py << 'PYEOF'
- cat > src/factory/contracts/explorer.py << 'PYEOF'
- ... (باقي العقود)

---

### §5 — الوكلاء السبعة (src/factory/agents/)

**كل وكيل = class يرث BaseAgent + prompt template في src/llm/prompts/**

| الوكيل | الملف | العقدة الدخيلة | العقدة الخارجة | الأدوات |
|--------|-------|---------------|---------------|---------|
| **Explorer** | `explorer.py` | `Task(explore)` | `ExplorationReport` | `read_code`, `search_web`, `git_log`, `tree_sitter` |
| **Thinker** | `thinker.py` | `ExplorationReport` | `Analysis` | LLM فقط |
| **Planner** | `planner.py` | `Analysis + ExplorationReport` | `Plan` | LLM فقط |
| **Designer** | `designer.py` | `Plan` | `DesignSpec` | LLM فقط |
| **Reviewer** | `reviewer.py` | `Plan + DesignSpec` | `Review` | LLM فقط |
| **Implementer** | `implementer.py` | `Task(impl) + DesignSpec + Grant` | `ImplementationResult` | `WindowsExecutor`, `write_file`, `run_test` |
| **Verifier** | `verifier.py` | `Task + ImplementationResult` | `Verification` | `read_evidence`, `run_test` (ميكانيكي) |
| **Security** | `security.py` | `ImplementationResult` | `SecurityReport` | `run_sast`, `scan_deps`, `scan_secrets` (ميكانيكي) |

**Prompt Templates المطلوبة:**
- `src/llm/prompts/explorer.yaml` ✅ (موجود)
- `src/llm/prompts/thinker.yaml` 🔄
- `src/llm/prompts/planner.yaml` 🔄
- `src/llm/prompts/designer.yaml` 🔄
- `src/llm/prompts/reviewer.yaml` 🔄
- `src/llm/prompts/implementer.yaml` 🔄

**الأوامر:**
- mkdir -p src/factory/agents
- cat > src/factory/agents/explorer.py << 'PYEOF'
- ... (باقي الوكلاء)
- cat > src/llm/prompts/thinker.yaml << 'YMLEOF'
- ... (باقي الـ prompts)

---

### §6 — Workflow Engine (src/factory/workflow/)

**المتطلبات:**
1. `TaskDAG` — Directed Acyclic Graph للمهام مع dependencies
2. `WorkflowEngine` — ينفذ DAG مع:
   - Parallel execution للمهام المستقلة
   - Retry policy مع exponential backoff
   - Checkpoint كل مهمة مكتملة
   - Handoff بين الوكلاء مع signature verification
   - Escalation بعد 3 فشل → Orchestrator → Human
3. `RetryPolicy` configurable per task type

**الأوامر:**
- mkdir -p src/factory/workflow
- cat > src/factory/workflow/dag.py << 'PYEOF'
- cat > src/factory/workflow/engine.py << 'PYEOF'
- cat > src/factory/workflow/retry.py << 'PYEOF'
- cat > src/factory/workflow/checkpoint.py << 'PYEOF'

---

### §7 — Shared Context + Memory (src/factory/context/)

**المتطلبات:**
1. `SharedContext` — سياق المهمة المشترك:
   - `knowledge_graph` — SQLite مع nodes/edges (files, functions, decisions)
   - `artifact_registry` — hash-chained artifacts
   - `decision_log` — ADR-style decisions مع rationale
   - `episodic_memory` — ما حدث في المهمة
2. `ContextView` — view محدود لكل وكيل حسب صلاحياته
3. Persistence: SQLite database per mission

**الأوامر:**
- mkdir -p src/factory/context
- cat > src/factory/context/memory.py << 'PYEOF'
- cat > src/factory/context/knowledge.py << 'PYEOF'
- cat > src/factory/context/artifacts.py << 'PYEOF'
- cat > src/factory/context/decisions.py << 'PYEOF'

---

### §8 — Integration: Full Mission Test

**المتطلبات:**
1. `tests/factory/test_full_mission.py` — اختبار مهمة كاملة:
   ```
   User: "أصلح regex في src/api/users.py"
   → Explorer يستكشف الكود
   → Thinker يحلل المشكلة
   → Planner يخطط (3 مهام)
   → Designer يصمم (لا تغيير معماري)
   → Reviewer يوافق
   → Human يوافق
   → Implementer ينفذ عبر WindowsExecutor
   → Verifier يتحقق (ملفات + اختبارات)
   → Security يفحص
   → COMPLETED مع أدلة
   ```
2. Evidence verification: كل خطوة لها `evidence_hash` صحيح
3. Resume test: إيقاف في منتصف المهمة → استئناف من checkpoint

**الأوامر:**
- cat > tests/factory/test_full_mission.py << 'PYEOF'
- python -m pytest tests/factory/test_full_mission.py -v -s

---

### §9 — CLI Entry Point (src/factory/cli.py)

**المتطلبات:**
1. `factory` command — نقطة دخول موحدة
2. `factory chat` — محادثة تفاعلية مع الأوركستر
3. `factory run "task description"` — تشغيل مهمة مباشرة
4. `factory resume <mission_id>` — استئناف من checkpoint
5. `factory status <mission_id>` — حالة المهمة

**الأوامر:**
- cat > src/factory/cli.py << 'PYEOF'
- pip install -e .  # يجعل `factory` متاحاً

---

### §10 — قرارات مالك (للبوابة)

**D1:** هل `WindowsExecutor` يستخدم Job Objects إلزامي أم fallback؟ — الأدلة: Job Objects أفضل، لكن fallback لـ subprocess مطلوب للتوافق.
**D2:** هل الوكلاء يستخدمون نفس LLM model أم models مختلفة؟ — الأدلة: نفس model (Nemotron) للتبسيط، temperature مختلف لكل دور.
**D3:** هل `SharedContext` يستمر بين المهام (cross-mission learning)؟ — الأدلة: نعم، `knowledge_graph` و `decision_log` مشروع-واسع.

---

### §11 — حدود الصدق

1. **لا عزل filesystem/network على Windows** — `isolation_level = "PARTIAL_JOB_OBJECT"` موثق بصراحة في كل `ExecutionResult`.
2. **لا نجاح زائف** — `exit_code != 0` = فشل، الأدلة توثق الفشل.
3. **Human approval إلزامي** — لا تنفيذ بلا موافقة صريحة.
4. **Verifier/Security ميكانيكيان** — لا LLM في التحقق/الأمن.

---

### §12 — قالب التقرير الإلزامي

```
VERDICT: PASS / HARD STOP
ORCHESTRATOR BUILT: YES / NO
HUMAN GATE WORKS: YES / NO
WINDOWS EXECUTOR WORKS: YES / NO
JOB OBJECTS ACTIVE: YES / NO (fallback reason if NO)
ALL 8 AGENTS WORK: عدد/8
PROMPT TEMPLATES COMPLETE: عدد/6
WORKFLOW ENGINE WORKS: YES / NO
CONTEXT MEMORY WORKS: YES / NO
FULL MISSION TEST: PASS / FAIL
RESUME TEST: PASS / FAIL
EVIDENCE HASHES VALID: YES / NO
ISOLATION LEVEL HONEST: PARTIAL_JOB_OBJECT documented
HARD STOPS FIRED: عدد أو NONE
ZERO-WRITE PROOF: قبل/بعد بصمة الملفات
```

---

### §13 — إثبات الكتابة-صفر قبل وبعد

```bash
python -c "
import hashlib, os
files = [
    'src/factory/orchestrator.py',
    'src/factory/human/gate.py',
    'src/factory/human/chat.py',
    'src/substrate/windows_executor.py',
    'src/factory/agents/base.py',
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
]
for f in files:
    h = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16] if os.path.exists(f) else 'MISSING'
    print(f'{f}: {h}')
"
```

---

**END OF ORDER**