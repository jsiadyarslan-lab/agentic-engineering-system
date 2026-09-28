# EXECUTION ORDER — PHASE 2.0 FINAL FIX
## إصلاح Late Imports الأخيرة — 10 imports في 8 Agents

---

### §0 — عقد التنفيذ

1. **الهدف الوحيد**: نقل 10 late imports للأعلى في 8 agent files — لا كود جديد.
2. **Hard Gate**: `assert 0 late imports` بعد الإصلاح.
3. **الأوامر المسموحة**: `sed`، `python`، `grep`، `cat`.
3. **لا كود جديد** — نقل فقط.

---

### §1 — الملفات والـ imports المطلوب نقلها

| الملف | السطر | الاستيراد | الهدف |
|-------|------|-------------|-------|
| `explorer.py` | 193 | `import tomli` | أعلى الملف |
| `explorer.py` | 307 | `from factory.contracts.agent_protocol import ExplorationReport` | أعلى الملف |
| `thinker.py` | 116 | `from factory.contracts.agent_protocol import Analysis` | أعلى الملف |
| `planner.py` | 120 | `from factory.contracts.agent_protocol import Plan` | أعلى الملف |
| `designer.py` | 122 | `from factory.contracts.agent_protocol import DesignSpec` | أعلى الملف |
| `reviewer.py` | 122 | `from factory.contracts.agent_protocol import Review` | أعلى الملف |
| `implementer.py` | 128 | `from factory.contracts.agent_protocol import ImplementationResult` | أعلى الملف |
| `verifier.py` | 123 | `from factory.contracts.agent_protocol import Verification` | أعلى الملف |
| `security.py` | 125 | `from factory.contracts.agent_protocol import SecurityReport` | أعلى الملف |

---

### §2 — الإصلاح الآلي

```bash
# إنشاء backup
cp src/factory/agents/explorer.py src/factory/agents/explorer.py.bak
cp src/factory/agents/thinker.py src/factory/agents/thinker.py.bak
cp src/factory/agents/planner.py src/factory/agents/planner.py.bak
cp src/factory/agents/designer.py src/factory/agents/designer.py.bak
cp src/factory/agents/reviewer.py src/factory/agents/reviewer.py.bak
cp src/factory/agents/implementer.py src/factory/agents/implementer.py.bak
cp src/factory/agents/verifier.py src/factory/agents/verifier.py.bak
cp src/factory/agents/security.py src/factory/agents/security.py.bak
```

---

### §2.1 — إصلاح `explorer.py` (2 imports)

```bash
# 1. إضافة في قسم imports الأعلى (بعد السطر 22 تقريباً):
sed -i '22a import tomli\nfrom factory.contracts.agent_protocol import ExplorationReport' src/factory/agents/explorer.py

# 2. حذف السطر 193 (import tomli داخل _analyze_dependencies)
sed -i '193d' src/factory/agents/explorer.py

# 3. حذف السطر 307 (import ExplorationReport داخل _build_exploration_report)
# ملاحظة: بعد الحذف الأول، السطر يتحرك — البحث والحذف:
sed -i '/from factory.contracts.agent_protocol import ExplorationReport/d' src/factory/agents/explorer.py
```

---

### §2.2 — إصلاح الـ 7 agents الآخرين (كل منها import واحد)

```bash
for agent in thinker planner designer reviewer implementer verifier security; do
    file="src/factory/agents/${agent}.py"
    # إضافة import في الأعلى (بعد imports الموجودة)
    # تحديد الـ import المطلوب من الجدول
    case $agent in
        thinker) import_line="from factory.contracts.agent_protocol import Analysis" ;;
        planner) import_line="from factory.contracts.agent_protocol import Plan" ;;
        designer) import_line="from factory.contracts.agent_protocol import DesignSpec" ;;
        reviewer) import_line="from factory.contracts.agent_protocol import Review" ;;
        implementer) import_line="from factory.contracts.agent_protocol import ImplementationResult" ;;
        verifier) import_line="from factory.contracts.agent_protocol import Verification" ;;
        security) import_line="from factory.contracts.agent_protocol import SecurityReport" ;;
    esac
    
    # إضافة بعد آخر import في أعلى الملف (بعد السطر الذي يحتوي on 'from factory.contracts')
    sed -i "/^from factory\.contracts/a ${import_line}" "$file"
    
    # حذف السطر المتأخر داخل الـ method
    sed -i "/${import_line}/d" "$file"
done
```

---

### §3 — التحقق الإلزامي (Hard Gate)

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
total_late = 0
for f in agent_files:
    with open(f) as fp:
        tree = ast.parse(fp.read())
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name.endswith('Agent')]
    first_class_line = min(c.lineno for c in classes)
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    late_imports = [i for i in imports if i.lineno > first_class_line]
    if late_imports:
        print(f'FAIL: {f} has {len(late_imports)} late imports')
        for imp in late_imports:
            print(f'  Line {imp.lineno}')
        total_late += len(late_imports)
    else:
        print(f'OK: {f}')
assert total_late == 0, f'Total late imports: {total_late}'
print('ALL LATE IMPORTS FIXED ✅')
"
```

---

### §4 — التحقق الشامل النهائي (Full Hard Gate)

```bash
python -c "
import ast, os

# 1. agent_protocol clean
with open('src/factory/contracts/agent_protocol.py') as f:
    tree = ast.parse(f.read())
assert len([c for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == 'Handoff']) == 1
print('1. agent_protocol: OK')

# 2. windows_executor clean
with open('src/substrate/windows_executor.py') as f:
    tree = ast.parse(f.read())
funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
from collections import Counter
dups = {k: v for k, v in Counter(f.name for f in funcs).items() if v > 1}
assert not dups
first_func = min(f.lineno for f in funcs)
imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
late = [i for i in imports if i.lineno > first_func]
assert not late
print('2. windows_executor: OK')

# 3. All 8 agents inherit BaseAgent
for f in ['src/factory/agents/explorer.py','src/factory/agents/thinker.py','src/factory/agents/planner.py','src/factory/agents/designer.py','src/factory/agents/reviewer.py','src/factory/agents/implementer.py','src/factory/agents/verifier.py','src/factory/agents/security.py']:
    with open(f) as fp: tree = ast.parse(fp.read())
    for c in ast.walk(tree):
        if isinstance(c, ast.ClassDef) and c.name.endswith('Agent'):
            bases = [b.id if isinstance(b, ast.Name) else '' for b in c.bases]
            assert 'BaseAgent' in bases, f'{f}: {c.name} bases={bases}'
print('3. All 8 agents inherit BaseAgent: OK')

# 4. ALL imports at top (including late imports fix)
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
        for imp in late:
            print(f'  Line {imp.lineno}')
        total_late += len(late)
assert total_late == 0, f'Total late imports: {total_late}'
print('4. All imports at top: OK')

# 5. Explorer bug fixed
with open('src/factory/agents/explorer.py') as f:
    content = f.read()
assert 'json.dumps(data, sort_keys=True, default=str)' in content
assert 'json.dumps(output, sort_keys=True, default=str)' not in content
print('5. Explorer bug fixed: OK')

# 5. Test file exists
import os
assert os.path.exists('tests/factory/test_full_mission.py')
print('5. Test file exists: OK')

# 6. CLI exists
assert os.path.exists('src/factory/cli.py')
print('6. CLI exists: OK')

print('ALL CRITICAL FIXES VERIFIED ✅')
"
```

---

### §5 — قالب التقرير الإلزامي

```
VERDICT: PASS / HARD STOP
LATE IMPORTS FIXED: YES / NO (count before/after)
ALL HARD GATES PASS: YES / NO
ZERO-WRITE PROOF: قبل/بعد بصمة الـ 8 agent files
```

---

**END OF ORDER**