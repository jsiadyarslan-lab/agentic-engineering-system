# EXECUTION ORDER — PHASE 2.0 INTEGRATION FIXES
## إصلاحات التكامل الفعلي — بناءً على نتائج الاختبار الحقيقي

---

### §0 — عقد التنفيذ

**النتائج الحقيقية من الاختبار:**

| المكون | الحالة | المشكلة |
|----------|--------|---------|
| **Orchestrator** | ❌ | `__init__` يتطلب 6 arguments إلزامية، لا `test_mode` |
| **CLI** | ❌ | ينشئ `AgentFactoryOrchestrator()` بلا arguments |
| **Test** | ❌ | يمرر `test_mode=True` غير موجود |
| **Dependencies** | ❌ | لا توجد factory methods لإنشاء dependencies |
| **NVIDIA_API_KEY** | ❌ | غير موجود في البيئة |
| **HAS_PYWIN32** | ⚠️ | `False` — fallback إلى subprocess |

---

### §1 — إصلاح Orchestrator: Factory Pattern + Optional Dependencies

**الملف:** `src/factory/orchestrator.py`

**المطلوب:**
1. إضافة class method `create()` أو `create_for_test()` ينشئ dependencies افتراضية
2. جعل dependencies اختيارية مع defaults معقولة
3. دعم `test_mode` للاختبارات

```python
# في AgentFactoryOrchestrator class:

@classmethod
def create_for_test(cls, test_mode: bool = True) -> 'AgentFactoryOrchestrator':
    """Factory method for testing with mocked dependencies."""
    from src.llm import NVIDIAProvider, StructuredLLM, TokenBudget
    from src.factory.human import ChatInterface, HumanApprovalGate
    from src.factory.context.memory import SharedContextManager
    from src.substrate.windows_executor import WindowsExecutor
    from src.factory.context.decisions import DecisionLog
    
    # Mock LLM provider if no API key
    if test_mode:
        llm_provider = MockLLMProvider()  # أو create mock
    else:
        llm_provider = NVIDIAProvider()
    
    return cls(
        llm_provider=llm_provider,
        context_manager=SharedContextManager(),
        windows_executor=WindowsExecutor(),
        human_gate=HumanApprovalGate(chat_interface=ChatInterface()),
        chat_interface=ChatInterface(),
        token_budget=TokenBudget(),
    )

def __init__(
    self,
    llm_provider: 'LLMProvider',
    context_manager: 'SharedContextManager',
    windows_executor: 'WindowsExecutor',
    human_gate: 'HumanApprovalGate',
    chat_interface: 'ChatInterface',
    token_budget: 'TokenBudget',
):
    # ... existing init
```

---

### §2 — إصلاح CLI: Dependency Injection صحيح

**الملف:** `src/factory/cli.py`

**المطلوب:**
1. إنشاء orchestrator عبر factory method
2. معالجة غياب NVIDIA_API_KEY

```python
async def main():
    parser = argparse.ArgumentParser(description="Agent Factory CLI")
    # ... existing args
    
    args = parser.parse_args()
    
    # Create orchestrator with proper dependencies
    if args.command == "run":
        # Check for API key
        if not os.getenv("NVIDIA_API_KEY"):
            print("⚠️  NVIDIA_API_KEY not set. Running in test mode with mock LLM.")
            orchestrator = AgentFactoryOrchestrator.create_for_test(test_mode=True)
        else:
            orchestrator = AgentFactoryOrchestrator.create_for_production()
        
        mission = await orchestrator.start_mission(args.task, args.codebase)
        await mission.completed_event.wait()
        print(f"Mission {mission.mission_id}: {mission.state.value}")
```

---

### §3 — إصلاح Test: API صحيح

**الملف:** `tests/factory/test_full_mission.py`

**المطلوب:**
1. استخدام `create_for_test()` بدلاً من `test_mode=True`
2. Mock LLM provider للاختبار السريع

```python
@pytest.mark.asyncio
async def test_full_mission_typo_fix():
    """Test: User requests typo fix -> mission completes with evidence."""
    orchestrator = AgentFactoryOrchestrator.create_for_test(test_mode=True)
    
    mission = await orchestrator.start_mission(
        user_request="Fix typo in README.md",
        codebase_path=".",
    )
    
    await asyncio.wait_for(mission.completed_event.wait(), timeout=300.0)
    
    assert mission.state == MissionState.COMPLETED
    assert mission.implementation_result is not None
    assert mission.verification is not None
    assert mission.verification.passed is True
    assert len(mission.evidence_hashes) >= 8
    
    for h in mission.evidence_hashes:
        assert len(h) == 64
        assert all(c in '0123456789abcdef' for c in h)
```

---

### §4 — Mock LLM Provider للاختبارات

**الملف:** `src/llm/mock_provider.py` (جديد)

```python
#!/usr/bin/env python3
"""Mock LLM Provider for testing without API keys."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional
from src.llm.provider import LLMProvider, LLMMessage, LLMResponse, LLMUsage, LLMProviderType
from src.llm.structured import parse_structured_output


class MockLLMProvider(LLMProvider):
    """Mock provider that returns predefined responses for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(model="mock", api_key="mock")
        self._responses = {}
        self._call_count = 0
    
    @property
    def provider_type(self) -> LLMProviderType:
        return LLMProviderType.LOCAL
    
    def set_response(self, prompt_contains: str, response: Any):
        """Set predefined response for prompts containing string."""
        self._responses[prompt_contains] = response
    
    async def chat(self, messages: list, **kwargs) -> LLMResponse:
        self._call_count += 1
        prompt = " ".join(m.content for m in messages)
        
        # Check for predefined response
        for key, response in self._responses.items():
            if key in prompt:
                return LLMResponse(
                    content=response if isinstance(response, str) else str(response),
                    model="mock",
                    usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
                    finish_reason="stop",
                )
        
        # Default fallback response
        return LLMResponse(
            content='{"status": "mock_response"}',
            model="mock",
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )
    
    async def structured_chat(self, messages: list, output_model: type, **kwargs):
        # Return mock instance of output_model
        import json
        mock_data = self._get_mock_data(output_model)
        return parse_structured_output(json.dumps(mock_data), output_model)
    
    def _get_mock_data(self, model):
        """Generate mock data for Pydantic model."""
        from pydantic import BaseModel
        if not issubclass(model, BaseModel):
            return {}
        
        mock = {}
        for field_name, field_info in model.model_fields.items():
            if field_info.annotation == str:
                mock[field_name] = f"mock_{field_name}"
            elif field_info.annotation == int:
                mock[field_name] = 1
            elif field_info.annotation == float:
                mock[field_name] = 1.0
            elif field_info.annotation == bool:
                mock[field_name] = True
            elif field_info.annotation == list:
                mock[field_name] = []
            elif field_info.annotation == dict:
                mock[field_name] = {}
            else:
                mock[field_name] = "mock"
        return mock
```

---

### §5 — تحديث LLM Layer Exports

**الملف:** `src/llm/__init__.py`

```python
# إضافة في __all__:
from .mock_provider import MockLLMProvider

__all__ = [
    # ... existing
    "MockLLMProvider",
]
```

---

### §6 — Orchestrator.create_for_test() Implementation

**الملف:** `src/factory/orchestrator.py` — إضافة method في class

```python
@classmethod
def create_for_test(cls, test_mode: bool = True) -> 'AgentFactoryOrchestrator':
    """Factory method for testing with mocked dependencies."""
    from src.llm import NVIDIAProvider, StructuredLLM, TokenBudget, MockLLMProvider
    from src.factory.human import ChatInterface, HumanApprovalGate
    from src.factory.context.memory import SharedContextManager
    from src.substrate.windows_executor import WindowsExecutor
    from src.factory.context.decisions import DecisionLog
    from src.factory.context.memory import SharedContextManager
    from src.llm.budget import TokenBudget
    
    # Mock LLM provider for testing
    if test_mode:
        llm_provider = MockLLMProvider()
        # Set up mock responses for each agent type
        llm_provider.set_response("explore", '{"summary": "mock exploration", "codebase_structure": {}, "entry_points": [], "dependencies": {}, "file_inventory": [], "key_patterns": [], "tech_stack": {}}')
        llm_provider.set_response("analyze", '{"root_cause": "mock", "impact_assessment": "mock", "affected_components": [], "risk_factors": [], "recommendations": [], "confidence": 0.9}')
        llm_provider.set_response("plan", '{"summary": "mock plan", "tasks": [], "dependencies": {}, "estimates": {}, "risks": []}')
        llm_provider.set_response("design", '{"summary": "mock design", "architecture": {}, "components": [], "interfaces": [], "data_models": [], "api_contracts": []}')
        llm_provider.set_response("review", '{"approved": true, "summary": "mock review", "issues": [], "suggestions": [], "risk_assessment": "low"}')
        llm_provider.set_response("implement", '{"files_created": [], "files_modified": [], "tests_added": [], "tests_modified": [], "build_command": "echo", "test_command": "echo", "artifacts": []}')
    else:
        llm_provider = NVIDIAProvider()
    
    structured_llm = StructuredLLM(llm_provider)
    
    return cls(
        llm_provider=structured_llm,
        context_manager=SharedContextManager(),
        windows_executor=WindowsExecutor(),
        human_gate=HumanApprovalGate(chat_interface=ChatInterface()),
        chat_interface=ChatInterface(),
        token_budget=TokenBudget(),
    )
```

---

### §7 — أوامر التحقق النهائية

```bash
# 1. Test passes
python -m pytest tests/factory/test_full_mission.py -v

# 2. CLI works
python -m src.factory.cli run "smoke test"

# 3. All imports
python -c "
import src.factory.orchestrator
import src.factory.cli
import src.llm.mock_provider
print('All OK')
"

# 4. Zero late imports (verify fix from previous order)
python -c "
import ast
agent_files = [
    'src/factory/agents/explorer.py',
    'src/factory/agents/thinker.py',
    'src/factory/agents/planner.py',
    'src/factory/agents/designer.py',
    'src/factory/agents/reviewer.py',
    'src/factory/agents/implementer.py',
    'src/factory/agents/verifier.py',
    'src/factory/agents/security.py',
]
total_late = 0
for f in agent_files:
    with open(f) as fp: tree = ast.parse(fp.read())
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name.endswith('Agent')]
    first_class = min(c.lineno for c in classes)
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    late = [i for i in imports if i.lineno > first_class]
    if late:
        print(f'FAIL: {f} has {len(late)} late imports')
    total_late += len(late)
assert total_late == 0
print('Late imports: FIXED')
"
```

---

### §8 — معايير القبول النهائية

| المعيار | الأمر | النتيجة المتوقعة |
|----------|-------|-----------------|
| **Test passes** | `python -m pytest tests/factory/test_full_mission.py -v` | 1 passed |
| **CLI runs** | `python -m src.factory.cli run "smoke test"` | Completes without error |
| **Orchestrator factory** | `python -c "from src.factory.orchestrator import AgentFactoryOrchestrator; o = AgentFactoryOrchestrator.create_for_test(); print('OK')"` | OK |
| **Mock LLM works** | `python -c "from src.llm import MockLLMProvider; m = MockLLMProvider(); print('OK')"` | OK |
| **Late imports fixed** | (من الأمر السابق) | 0 late imports |

---

**END OF ORDER**