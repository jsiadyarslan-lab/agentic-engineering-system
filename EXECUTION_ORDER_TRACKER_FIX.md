# EXECUTION ORDER — TRACKER ALIGNMENT & REPAIR
## مواءمة الترَكَر مع واقع الكود + إصلاح العيوب الحرجة

---

### §0 — عقد التنفيذ الصلب

1. **المستودع**: jsiadyarslan-lab/agentic-engineering-system — **الفرع**: main — **الوضع**: WRITE_LOCAL.
2. **الهدف الوحيد**: إصلاح `EXECUTION-TRACKER-v2.1.md` و `tracker.py` ليطابقا واقع المستودع (Python EOE System) ويزيلا التكرار والاخطاء الحسابية.
3. **المنح المطلوبة**:
   - PATH_GRANT قراءة وكتابة على `EXECUTION-TRACKER-v2.1.md`
   - PATH_GRANT قراءة وكتابة على `tracker.py`
4. أي تعديل خارج هذين الملفين = **HARD STOP** فوري.
5. انحراف الأساس عن `origin/main` قبل البدء = **HARD STOP**.
6. لا استنتاج: كل تغيير موثق أدناه حرفياً — ما ليس مكتوباً لا يُنفَّذ.
7. **الأوامر المسموحة**: `python`، `sed`، `awk`، `grep`، `cat`، `cp`، `mv` — كل أمر خارجها = **HARD STOP** قبل التنفيذ.
8. **الدفع**: لا دفع — أمر محلي فقط.

---

### §1 — إزالة تكرار Phase 4 (حرج)

**المتطلبات:**
1. حذف الكتلة المكررة كاملة: من سطر `## 📋 PHASE 4: PRODUCTION HARDENING (Weeks 14-16) — Target: 100%` الثاني (السطر 249 تقريباً) إلى نهاية جدوله وقبل `## 📋 PHASE 5`.
2. التحقق: بعد الحذف، يبقى **واحد فقط** Phase 4 في الملف.

**القيود:** عملية حذف جراحية — لا تعديل على Phase 4 الأول (السطر 211).

**الأوامر:**
- python -c "
import re
text = open('EXECUTION-TRACKER-v2.1.md', 'r', encoding='utf-8').read()
# Find second occurrence of '## 📋 PHASE 4: PRODUCTION HARDENING'
matches = list(re.finditer(r'## 📋 PHASE 4: PRODUCTION HARDENING \(Weeks 14-16\) — Target: 100%', text))
if len(matches) >= 2:
    start = matches[1].start()
    # Find next '## 📋 PHASE 5' after that
    next_phase = text.find('## 📋 PHASE 5:', start)
    if next_phase > 0:
        new_text = text[:start] + text[next_phase:]
        open('EXECUTION-TRACKER-v2.1.md', 'w', encoding='utf-8').write(new_text)
        print('DELETED duplicate Phase 4 block')
    else:
        print('ERROR: PHASE 5 not found after duplicate')
else:
    print('ERROR: Less than 2 Phase 4 headers found')
"

---

### §2 — تصحيح 0.1.1 / 0.1.2 / 0.1.3 لتطابق Python Codebase (حرج)

**المتطلبات:**
1. تحديث صف 0.1.1: تغيير `Files` من `crates/substrate-linux/src/lib.rs` إلى `src/substrate/local_substrate.py`
2. تحديث صف 0.1.2: تغيير `Files` إلى `src/substrate/windows_substrate.py` (غير موجود — يُكتب لاحقاً)، إضافة `BLOCKED: No Windows substrate implementation exists; requires design first`
3. تحديث صف 0.1.3: تغيير `Files` إلى `src/substrate/macos_substrate.py` (غير موجود — يُكتب لاحقاً)، إضافة `BLOCKED: No macOS substrate implementation exists; requires design first`
4. تحديث عمود `Owner` لـ 0.1.2 و 0.1.3 إلى `Backend (Design Required)`

**القيود:** تعديل خلايا الجدول فقط — لا تغيير للعناوين أو البنية.

**الأوامر:**
- python -c "
import re
text = open('EXECUTION-TRACKER-v2.1.md', 'r', encoding='utf-8').read()

# 0.1.1 fix
text = re.sub(
    r'(\| 🔄 \| \*\*0\.1\.1\*\* \| Implement Linux Substrate \(namespaces/seccomp/cgroups/landlock\) \| — \| Backend \| `pytest tests/execution/test_linux_substrate\.py` passes \| )`crates/substrate-linux/src/lib\.rs`',
    r'\1`src/substrate/local_substrate.py`',
    text
)

# 0.1.2 fix - Windows
text = re.sub(
    r'(\| 🔄 \| \*\*0\.1\.2\*\* \| Implement Windows Substrate \(Job Objects \+ Silos/AppContainers\) \| 0\.1\.1 \| Backend \| `pytest tests/execution/test_windows_substrate\.py` passes \| )`crates/substrate-windows/src/lib\.rs`, `crates/job-objects/`, `crates/silos/` \| BLOCKED: Windows API compatibility issues with windows 0\.58 crate',
    r'\1`src/substrate/windows_substrate.py` (NOT EXISTS) \| BLOCKED: No Windows substrate implementation exists; requires design first',
    text
)

# 0.1.3 fix - macOS
text = re.sub(
    r'(\| ⏳ \| \*\*0\.1\.3\*\* \| Implement macOS Substrate \(Seatbelt/XPC/App Sandbox\) \| 0\.1\.1 \| Backend \| `pytest tests/execution/test_macos_substrate\.py` passes \| )`crates/substrate-macos/src/lib\.rs`, `crates/seatbelt/`',
    r'\1`src/substrate/macos_substrate.py` (NOT EXISTS) \| BLOCKED: No macOS substrate implementation exists; requires design first',
    text
)

open('EXECUTION-TRACKER-v2.1.md', 'w', encoding='utf-8').write(text)
print('UPDATED 0.1.1, 0.1.2, 0.1.3 rows')
"

---

### §3 — إضافة Phase 0.5: RUST PORT (مرحلة جديدة بعد Phase 0)

**المتطلبات:**
1. إدراج مرحلة جديدة **بعد Phase 0 مباشرة** وقبل `## 📋 A. CONTEXT MANAGEMENT`.
2. المرحلة بعنوان: `## 📋 PHASE 0.5: RUST PORT (Weeks 3-4) — Target: 100%`
3. 4 خطوات بالجدول القياسي.

**القيود:** الإدراج جراحي — لا تعديل على المراحل المجاورة.

**الأوامر:**
- python -c "
text = open('EXECUTION-TRACKER-v2.1.md', 'r', encoding='utf-8').read()

phase_05 = '''
## 📋 PHASE 0.5: RUST PORT (Weeks 3-4) — Target: 100%

| Status | ID | Title | Dependencies | Owner | Acceptance Criteria | Files |
|--------|-----|-------|--------------|-------|---------------------|-------|
| ⏳ | **0.5.1** | Port Linux Substrate to Rust (crates/substrate-linux) | 0.1.1 | Backend | `cargo test -p substrate-linux` passes | `crates/substrate-linux/` |
| ⏳ | **0.5.2** | Port Windows Substrate (Job Objects + Silos) | 0.1.2 | Backend | `cargo test -p substrate-windows` passes | `crates/substrate-windows/`, `crates/job-objects/`, `crates/silos/` |
| ⏳ | **0.5.3** | Port macOS Substrate (Seatbelt) | 0.1.3 | Backend | `cargo test -p substrate-macos` passes | `crates/substrate-macos/`, `crates/seatbelt/` |
| ⏳ | **0.5.4** | FFI Bridge: Python EOE → Rust Substrates | 0.5.1, 0.5.2, 0.5.3 | Backend | `eoe_engine` calls substrate via FFI | `src/substrate/ffi_bridge.py` |

**Phase Progress: 0%** (0/4 completed)

---

'''

# Insert after Phase 0 block (before A. CONTEXT MANAGEMENT)
marker = '## 📋 A. CONTEXT MANAGEMENT'
idx = text.find(marker)
if idx > 0:
    new_text = text[:idx] + phase_05 + text[idx:]
    open('EXECUTION-TRACKER-v2.1.md', 'w', encoding='utf-8').write(new_text)
    print('INSERTED Phase 0.5 after Phase 0')
else:
    print('ERROR: A. CONTEXT MANAGEMENT marker not found')
"

---

### §4 — إصلاح Metrics Summary (إعادة حساب الأرقام)

**المتطلبات:**
1. تشغيل `python tracker.py status` لقراءة الحالة الحالية بعد التعديلات أعلاه.
2. تحديث جدول `## 📈 METRICS SUMMARY` بالأرقام الصحيحة (إجمالي خطوات = 133 بعد حذف التكرار + 4 Phase 0.5 = 137).
3. تحديث نسبة `Overall Progress` في الأعلى.

**القيود:** لا تعديل يدوي — يتم عبر تشغيل الأداة.

**الأوامر:**
- python tracker.py status
- python tracker.py report -o /tmp/tracker_report.md
- python -c "
import subprocess
result = subprocess.run(['python', 'tracker.py', 'report'], capture_output=True, text=True)
print(result.stdout)
"

---

### §5 — إصلاح tracker.py: دعم عمود blocked_reason + صلابة parsing

**المتطلبات:**
1. في `parse_tracker()`: إضافة استخراج `blocked_reason` من عمود `Files` (إذا احتوى `BLOCKED:`).
2. في `show_status()`: طباعة `blocked_reason` للخطوات المحجوبة (كما في الكود الحالي السطر 296).
3. في `update_step_status()`: دعم تحديث `blocked_reason` عند الأمر `block`.
4. صلابة: عدم الكسر عند وجود صفوف مكررة أو جداول غير متوقعة.

**الأوامر:**
- python -c "
# Backup first
import shutil
shutil.copy2('tracker.py', 'tracker.py.backup')
print('Backed up tracker.py')
"

- python -c "
# Apply patches to tracker.py
text = open('tracker.py', 'r', encoding='utf-8').read()

# Patch 1: In parse_tracker, extract blocked_reason from Files column
# Find the line: 'files = cells[6] if len(cells) > 6 else ''''
# Replace with extraction logic
old = '''                files = cells[6] if len(cells) > 6 else ''
                
                # Map icon to status
                status_map = {'✅': 'completed', '🔄': 'in_progress', '⏳': 'pending', '🚫': 'blocked'}
                status = status_map.get(status_icon, 'pending')
                
                step = {'''

new = '''                files = cells[6] if len(cells) > 6 else ''
                # Extract blocked_reason from files column if present
                blocked_reason = None
                if files and 'BLOCKED:' in files:
                    blocked_reason = files.split('BLOCKED:', 1)[1].strip()
                
                # Map icon to status
                status_map = {'✅': 'completed', '🔄': 'in_progress', '⏳': 'pending', '🚫': 'blocked'}
                status = status_map.get(status_icon, 'pending')
                
                step = {'''

text = text.replace(old, new)

# Patch 2: Add blocked_reason to step dict
old2 = '''                step = {
                    'id': step_id,
                    'title': title,
                    'status': status,
                    'dependencies': [d.strip() for d in deps.split(',') if d.strip()] if deps else [],
                    'owner': owner,
                    'acceptance': acceptance,
                    'files': files
                }'''

new2 = '''                step = {
                    'id': step_id,
                    'title': title,
                    'status': status,
                    'dependencies': [d.strip() for d in deps.split(',') if d.strip()] if deps else [],
                    'owner': owner,
                    'acceptance': acceptance,
                    'files': files,
                    'blocked_reason': blocked_reason
                }'''

text = text.replace(old2, new2)

# Patch 3: In update_step_status, support blocked reason
old3 = '''def update_step_status(step_id: str, status: str, note: Optional[str] = None):'''

new3 = '''def update_step_status(step_id: str, status: str, note: Optional[str] = None, blocked_reason: Optional[str] = None):'''

text = text.replace(old3, new3)

# Patch 4: In update_step_status, update blocked_reason in file if provided
old4 = '''    new_content = '\\n'.join(lines)
    
    # Update metrics summary
    new_content = update_metrics(new_content)'''

new4 = '''    # If blocking with reason, update the files column to include BLOCKED: reason
    if status == 'blocked' and blocked_reason:
        lines = new_content.split('\\n')
        for i, line in enumerate(lines):
            if f'| {step_id} |' in line and '|' in line:
                parts = line.split('|')
                if len(parts) >= 8:
                    # files column is index 7 (0-based after split)
                    current_files = parts[7].strip()
                    if 'BLOCKED:' not in current_files:
                        parts[7] = f' {current_files} | BLOCKED: {blocked_reason} '
                        lines[i] = '|'.join(parts)
        new_content = '\\n'.join(lines)
    
    # Update metrics summary
    new_content = update_metrics(new_content)'''

text = text.replace(old4, new4)

open('tracker.py', 'w', encoding='utf-8').write(text)
print('PATCHED tracker.py with blocked_reason support')
"

---

### §6 — التحقق النهائي (إثبات الصفر-كتابة + التقرير)

**المتطلبات:**
1. تشغيل `python tracker.py status` — يعرض التقدم الصحيح بلا أخطاء.
2. تشغيل `python tracker.py report` — يولد تقرير Markdown سليم.
3. تحقق بصمة git: `git diff --stat` يظهر تعديل الملفين فقط.
4. تحقق `python -m pytest tests/ -x -q` — لا كسر للاختبارات الموجودة.

**الأوامر:**
- python tracker.py status
- python tracker.py report
- git diff --stat
- python -m pytest tests/ -x -q --tb=short 2>&1 | head -50

---

### §7 — القالب الإلزامي للتقرير

التقرير يُبنى من هذه الحقول بهذا الترتيب حرفياً:

```
VERDICT: PASS / HARD STOP
PHASE 4 DUPLICATE REMOVED: YES / NO
0.1.1/0.1.2/0.1.3 CORRECTED: YES / NO
PHASE 0.5 INSERTED: YES / NO
METRICS RECALCULATED: YES / NO
TRACKER.PY PATCHED: YES / NO
TESTS PASS: YES / NO
HARD STOPS FIRED: عدد أو NONE
ZERO-WRITE PROOF: قبل/بعد بصمة الملفين
```

---

### §8 — قرارات مالك (مرجع للبوابة)

**D1:** هل نضيف Phase 0.5 أم ندمج خطوات Rust Port في Phase 0؟ — الأدلة: Phase 0 مكتمل 57%، Rust Port عمل منفصل يستحق مرحلة.
**D2:** هل ننشئ `windows_substrate.py` و `macos_substrate.py` كهيكل وهمي (skeleton) أم نتركها BLOCKED؟ — الأدلة: tracker يظهرها BLOCKED بتصميم مطلوب.
**D3:** هل نحذف Immediate Actions `imm-2` إلى `imm-6` (Rust workspace) لأنها لا تطابق الواقع؟ — الأدلة: الأوامر `cargo new` لا تنطبق على Python repo.

---

### §9 — حدود الصدق

1. الملف الوحيد المعدل: `EXECUTION-TRACKER-v2.1.md` و `tracker.py`.
2. أي تغيير في `src/` أو `tests/` = **HARD STOP**.
3. الأوامر أعلاه تقرأ وتكتب الملفين المستهدفين فقط — لا شبكة، لا subprocess غير مصرح.

---

### §10 — إثبات الكتابة-صفر قبل وبعد

**الأوامر:**
- python -c "
import hashlib, os
for f in ['EXECUTION-TRACKER-v2.1.md', 'tracker.py']:
    h = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16]
    print(f'{f}: {h}')
"

**END OF ORDER**