# EXECUTION ORDER — PHASE 2.0 CRITICAL FIXES
## إصلاحات حرجة إلزامية قبل أي تقدم — Hard Gates

---

### §0 — عقد التنفيذ

1. **الهدف**: إصلاح كل الأخطاء الحرجة المكتشفة في التدقيق — لا كود جديد قبل عبور هذه البوابة.
2. **Hard Gates**: كل قسم يجب أن يمر 100% قبل الانتقال للقسم التالي.
3. **لا كود جديد** — تنظيف وإصلاح فقط.
4. **الأوامر المسموحة**: `python`، `sed`، `grep`، `cat`، `mv`، `cp`، `rm`.

---

### §1 — تنظيف `src/factory/contracts/agent_protocol.py`

**المشكلة**: `Handoff` class معرّف مرتين (سطر 68، سطر 172).

**الإصلاح**:
```bash
# إزالة التعريف الثاني (أسطر 172-180) — الاحتفاظ بالأول (أسطر 68-76)
```

**أمر تحقق**:
```bash
python -c "
import ast
with open('src/factory/contracts/agent_protocol.py') as f:
    tree = ast.parse(f.read())
classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
handoff_count = sum(1 for c in classes if c.name == 'Handoff')
assert handoff_count == 1, f'Handoff defined {handoff_count} times'
print('Handoff: OK')
"
```

---

### §2 — تنظيف `src/substrate/windows_executor.py` (حرج)

**المشاكل**:
1. 3 دوال مكررة ×3 لكل منها:
   - `_collect_artifacts` (أسطر 450، 595، 740)
   - `_compute_evidence_hash` (أسطر 471، 616، 761)
   - `_get_termination_status` (أسطر 493، 638، 783)
   - `_execute_subprocess_fallback` (أسطر 502، 647) — مكررة مرتين
2. imports مكررة في الأسفل (أسطر 41-52، 797-814)
3. `HAS_PYWIN32` و `logger` معرّفين مرتين

**الإصلاح**:
```bash
# 1. الاحتفاظ بالتعريف الأول لكل دالة، حذف المكررات
# 2. نقل كل imports للأعلى (أسطر 7-23)، حذف المكررات في الأسفل
# 3. تعريف HAS_PYWIN32 و logger مرة واحدة في الأعلى
```

**أمر تحقق**:
```bash
python -c "
import ast
with open('src/substrate/windows_executor.py') as f:
    tree = ast.parse(f.read())
funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
names = [f.name for f in funcs]
from collections import Counter
dups = {k: v for k, v in Counter(names).items() if v > 1}
assert not dups, f'Duplicate functions: {dups}'

imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
# التحقق من عدم وجود imports بعد أول تعريف دالة
first_func_line = min(f.lineno for f in funcs)
late_imports = [imp for imp in imports if imp.lineno > first_func_line]
assert not late_imports, f'Late imports at lines: {[i.lineno for i in late_imports]}'
print('windows_executor: OK')
"
```

---

### §3 — إضافة `BaseAgent` ك base class لجميع 8 agents (حرج)

**المشكلة**: لا وكيل يرث من `BaseAgent` — كلها `class XAgent:` مع `bases: []`.

**الملفات الـ 8**:
- `src/factory/agents/explorer.py`
- `src/factory/agents/thinker.py`
- `src/factory/agents/planner.py`
- `src/factory/agents/designer.py`
- `src/factory/agents/reviewer.py`
- `src/factory/agents/implementer.py`
- `src/factory/agents/verifier.py`
- `src/factory/agents/security.py`

**الإصلاح لكل ملف**:
```python
# تغيير:
class ExplorerAgent:
# إلى:
class ExplorerAgent(BaseAgent):
```

**أمر تحقق**:
```bash
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
for f in agent_files:
    with open(f) as fp:
        tree = ast.parse(fp.read())
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for c in classes:
        if c.name.endswith('Agent'):
            bases = [b.id if isinstance(b, ast.Name) else 'unknown' for b in c.bases]
            assert 'BaseAgent' in bases, f'{f}: {c.name} does not inherit BaseAgent (bases: {bases})'
print('All 8 agents inherit BaseAgent: OK')
"
```

---

### §4 — نقل imports للأعلى في جميع agent files

**المشكلة**: imports في أسفل الملف (بعد تعريف الكلاس) — مخالفة PEP 8.

**الإصلاح**: نقل كل imports للأعلى، قبل تعريف الكلاس.

**أمر تحقق**:
```bash
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
for f in agent_files:
    with open(f) as fp:
        tree = ast.parse(fp.read())
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    if classes:
        first_class_line = min(c.lineno for c in classes)
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        late_imports = [imp for imp in imports if imp.lineno > first_class_line]
        assert not late_imports, f'{f}: {len(late_imports)} imports after class definition'
print('All agents: imports at top OK')
"
```

---

### §5 — إصلاح Bug في `src/factory/agents/explorer.py`

**المشكلة**: سطر 331 — `_create_evidence_hash` يستخدم متغير `output` غير معرف (يجب `data`).

```python
# السطر 331 الحالي:
content = json.dumps(output, sort_keys=True, default=str)
# يجب أن يكون:
content = json.dumps(data, sort_keys=True, default=str)
```

**أمر تحقق**:
```bash
python -c "
with open('src/factory/agents/explorer.py') as f:
    content = f.read()
assert 'json.dumps(output, sort_keys=True, default=str)' not in content, 'Bug still present'
assert 'json.dumps(data, sort_keys=True, default=str)' in content, 'Fix not applied'
print('Explorer bug fix: OK')
"
```

---

### §6 — إنشاء `tests/factory/test_full_mission.py`

**الحد الأدنى المطلوب**:
```bash
mkdir -p tests/factory
touch tests/factory/test_full_mission.py
```

**الحد الأدنى للمحتوى**:
```python
#!/usr/bin/env python3
"""Integration test: Full mission from user request to COMPLETED."""

import asyncio
import pytest

from src.factory.orchestrator import AgentFactoryOrchestrator, MissionState


@pytest.mark.asyncio
async def test_full_mission_typo_fix():
    """Test: User requests typo fix -> mission completes with evidence."""
    orchestrator = AgentFactoryOrchestrator(
        # config for test mode
        test_mode=True,
    )
    
    mission = await orchestrator.start_mission(
        user_request="Fix typo in README.md",
        codebase_path=".",
    )
    
    # Wait for completion with timeout
    await asyncio.wait_for(mission.completed_event.wait(), timeout=300.0)
    
    # Assertions
    assert mission.state == MissionState.COMPLETED, f"Mission state: {mission.state}"
    assert mission.implementation_result is not None, "No implementation result"
    assert mission.verification is not None, "No verification"
    assert mission.verification.passed is True, "Verification failed"
    assert len(mission.evidence_hashes) >= 8, f"Only {len(mission.evidence_hashes)} evidence hashes"
    
    # Verify evidence hashes are valid SHA256
    for h in mission.evidence_hashes:
        assert len(h) == 64, f"Invalid hash length: {h}"
        assert all(c in '0123456789abcdef' for c in h), f"Invalid hex: {h}"
```

---

### §7 — إنشاء `src/factory/cli.py`

**الحد الأدنى للأوامر**:
```bash
touch src/factory/cli.py
```

**المحتوى الأدنى**:
```python
#!/usr/bin/env python3
"""Factory CLI Entry Point."""

import asyncio
import argparse
import sys

from src.factory.orchestrator import AgentFactoryOrchestrator


async def main():
    parser = argparse.ArgumentParser(description="Agent Factory CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # factory run "task"
    run_parser = subparsers.add_parser("run", help="Run a mission")
    run_parser.add_argument("task", help="Task description")
    run_parser.add_argument("--codebase", default=".", help="Codebase path")
    
    # factory status <mission_id>
    status_parser = subparsers.add_parser("status", help="Get mission status")
    status_parser.add_argument("mission_id", help="Mission ID")
    
    # factory chat
    subparsers.add_parser("chat", help="Interactive chat mode")
    
    args = parser.parse_args()
    
    orchestrator = AgentFactoryOrchestrator()
    
    if args.command == "run":
        mission = await orchestrator.start_mission(args.task, args.codebase)
        await mission.completed_event.wait()
        print(f"Mission {mission.mission_id}: {mission.state.value}")
    elif args.command == "status":
        status = orchestrator.get_mission_status(args.mission_id)
        print(status)
    elif args.command == "chat":
        print("Chat mode not yet implemented")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

---

### §8 — بوابة القبول النهائية (Hard Gate)

**يجب أن يمر كل هذا قبل إعلان Phase 2.0 لأي تقدم**:

```bash
# 1. Contracts نظيفة
python -c "
import ast
with open('src/factory/contracts/agent_protocol.py') as f:
    tree = ast.parse(f.read())
handoffs = [c for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == 'Handoff']
assert len(handoffs) == 1
print('1. agent_protocol: OK')
"

# 2. windows_executor نظيف
python -c "
import ast
with open('src/substrate/windows_executor.py') as f:
    tree = ast.parse(f.read())
funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
from collections import Counter
dups = {k: v for k, v in Counter(f.name for f in funcs).items() if v > 1}
assert not dups
first_func = min(f.lineno for f in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)])
imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
late = [i for i in imports if i.lineno > first_func]
assert not late
print('2. windows_executor: OK')
"

# 3. 8 Agents ترث BaseAgent
python -c "
import ast
for f in ['src/factory/agents/explorer.py','src/factory/agents/thinker.py','src/factory/agents/planner.py','src/factory/agents/designer.py','src/factory/agents/reviewer.py','src/factory/agents/implementer.py','src/factory/agents/verifier.py','src/factory/agents/security.py']:
    with open(f) as fp: tree = ast.parse(fp.read())
    for c in ast.walk(tree):
        if isinstance(c, ast.ClassDef) and c.name.endswith('Agent'):
            bases = [b.id if isinstance(b, ast.Name) else '' for b in c.bases]
            assert 'BaseAgent' in bases, f'{f}: {c.name} bases={bases}'
print('3. All 8 agents inherit BaseAgent: OK')
"

# 4. Imports في الأعلى
python -c "
import ast
for f in ['src/factory/agents/explorer.py','src/factory/agents/thinker.py','src/factory/agents/planner.py','src/factory/agents/designer.py','src/factory/agents/reviewer.py','src/factory/agents/implementer.py','src/factory/agents/verifier.py','src/factory/agents/security.py']:
    with open(f) as fp: tree = ast.parse(fp.read())
    classes = [n for n in ast.walk(tree) if isinstance(c, ast.ClassDef) for c in [n] if c.name.endswith('Agent')]
    first_class = min(c.lineno for c in classes)
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    late = [i for i in imports if i.lineno > first_class]
    assert not late, f'{f}: late imports'
print('4. All imports at top: OK')
"

# 5. Explorer bug fixed
python -c "
with open('src/factory/agents/explorer.py') as f: c = f.read()
assert 'json.dumps(data, sort_keys=True, default=str)' in c
assert 'json.dumps(output, sort_keys=True, default=str)' not in c
print('5. Explorer bug fixed: OK')
"

# 6. Test file exists
import os
assert os.path.exists('tests/factory/test_full_mission.py'), 'tests/factory/test_full_mission.py missing'
print('6. Test file exists: OK')

# 7. CLI exists
assert os.path.exists('src/factory/cli.py'), 'src/factory/cli.py missing'
print('7. CLI exists: OK')

print('ALL CRITICAL FIXES VERIFIED ✅')
"
```

---

### §9 — قالب التقرير الإلزامي

```
VERDICT: PASS / HARD STOP
1. AGENT_PROTOCOL CLEAN: YES / NO
2. WINDOWS_EXECUTOR CLEAN: YES / NO
3. ALL 8 AGENTS INHERIT BASEAGENT: عدد/8
4. ALL IMPORTS AT TOP: YES / NO
5. EXPLORER BUG FIXED: YES / NO
6. TEST FILE CREATED: YES / NO
7. CLI CREATED: YES / NO
HARD STOPS FIRED: عدد أو NONE
ZERO-WRITE PROOF: قبل/بعد بصمة الملفات المصلحة
```

---

**END OF CRITICAL FIXES ORDER**