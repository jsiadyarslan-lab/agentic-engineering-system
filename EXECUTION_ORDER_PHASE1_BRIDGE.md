# EXECUTION ORDER — PYTHON-RUST BRIDGE (Phase 1.0)
## ربط Python بـ substrate-linux العامل عبر gRPC/Unix Socket — **مشروط ببيئة Linux عاملة**

---

### ⚠️ **PRECONDITION إلزامي — يُفحص قبل أي قسم**

```bash
# يجب أن ينجح هذا قبل البدء:
cargo test -p substrate-linux --test real_execution 2>&1 | grep "test_execute_echo_hello ... ok"

# إذا فشل → HARD STOP فوري
# السبب: Cloud Shell / Containers لا تدعم unshare(CLONE_NEWPID)
# المطلوب: Linux VM حقيقي (Multipass, VMware, bare metal)
```

**إذا لم يتوفر الشرط أعلاه، الأمر مؤجل بالكامل.**

---

### §0 — عقد التنفيذ الصلب

1. **المستودع**: jsiadyarslan-lab/agentic-engineering-system — **الفرع**: main — **الوضع**: WRITE_LOCAL.
2. **الهدف الوحيد**: بناء جسر gRPC بين Python و Rust يسمح للأوركستر بتنفيذ أوامر حقيقية في substrate-linux مع إعادة Evidence موقع — **على Linux VM فقط**.
3. **المنح المطلوبة** (Linux VM فقط):
   - PATH_GRANT قراءة وكتابة على `src/substrate/` — للجسر والبروتوكول
   - PATH_GRANT قراءة وكتابة على `crates/substrate-rpc/` — لخادم Rust
   - PATH_GRANT قراءة على `crates/substrate-linux/src/` — للوصول للـ execution logic
4. أي كتابة خارج المسارات الممنوحة = **HARD STOP** فوري.
5. انحراف الأساس عن `origin/main` قبل البدء = **HARD STOP**.
6. لا استنتاج: البروتوكول يُعرف في `.proto`، الكود يُولد منه، الاختبار يفرض العقدة.
7. **الأوامر المسموحة**: `cargo`، `python`، `protoc`، `tonic-build`، `grep`، `cat` — كل أمر خارجها = **HARD STOP**.
8. **الدفع**: لا دفع — أمر محلي فقط.

---

### §0.5 — فحص البيئة (أول خطوة، إلزامي)

**المتطلبات:**
1. التحقق من نظام التشغيل: `Linux` فقط
2. التحقق من قدرات substrate: `cargo test -p substrate-linux --test real_execution`
3. إذا فشل → كتابة `ENVIRONMENT_NOT_QUALIFIED` في التقرير وإنهاء الأمر

**الأوامر:**
- python -c "
  import platform, subprocess, sys
  if platform.system() != 'Linux':
      print('ENVIRONMENT_NOT_QUALIFIED: Not Linux')
      sys.exit(1)
  result = subprocess.run(['cargo', 'test', '-p', 'substrate-linux', '--test', 'real_execution'], capture_output=True, text=True)
  if 'test_execute_echo_hello ... ok' not in result.stdout:
      print('ENVIRONMENT_NOT_QUALIFIED: substrate-linux cannot execute')
      print(result.stdout[-2000:])
      sys.exit(1)
  print('ENVIRONMENT_QUALIFIED: Linux + substrate execution works')
  "

---

### §1 — تعريف البروتوكول (Protobuf)

**المتطلبات:**
1. تعريف `ExecuteRequest`، `ExecuteResponse`، `Evidence`، `LogEntry`، `HealthStatus` في `src/substrate/proto/substrate.proto`
2. حقول إلزامية: `command` (repeated string)، `limits` (map<string, uint64>)، `env` (map<string, string>)، `working_dir` (string)
3. Response: `exit_code` (int32)، `stdout` (string)، `stderr` (string)، `evidence_hash` (string)، `duration_ms` (uint64)، `termination` (enum)
4. Streaming: `LogEntry` للـ real-time logs، `HealthStatus` للـ health check

**القيود:** 
- Protobuf v3 فقط
- لا optional fields — استخدم defaults صريحة
- كل حقل موثق بـ comment

**الأوامر:**
- protoc --version  # التحقق من وجود protoc
- mkdir -p src/substrate/proto
- cat > src/substrate/proto/substrate.proto << 'EOF'
  syntax = "proto3";
  package substrate;
  
  // ... (التعريف الكامل في التنفيذ)
EOF

---

### §2 — خادم Rust gRPC (crates/substrate-rpc)

**المتطلبات:**
1. إنشاء `crates/substrate-rpc/` كمكتبة `tonic` server
2. تنفيذ `SubstrateService` trait من الكود المولد
3. استدعاء `substrate_linux::execute()` الحقيقي داخل handler
5. تحويل `ExecutionLimits` من proto إلى struct حقيقي
6. إرجاع `Evidence` مع hash موقع
7. Health check endpoint يعيد حالة substrate (مُتاح/مشغول/خطأ)

**القيود:**
- Unix socket فقط (`/tmp/substrate.sock`) — لا TCP
- Timeout افتراضي 60 ثانية، قابل للتجاوز عبر request
- خطأ واحد في handler = response مع error code، لا panic
- Structured logging مع `tracing` crate

**الأوامر:**
- cargo new --lib substrate-rpc --edition 2021
- cd crates/substrate-rpc && cargo add tonic prost prost-types serde serde_json tracing anyhow
- mkdir -p crates/substrate-rpc/src
- cat > crates/substrate-rpc/Cargo.toml << 'EOF'
  [dependencies]
  tonic = { version = "0.12", features = ["tls", "transport"] }
  prost = "0.13"
  prost-types = "0.13"
  substrate-linux = { path = "../substrate-linux" }
  # ...
EOF

---

### §3 — عميل Python gRPC (src/substrate/bridge.py)

**المتطلبات:**
1. `SubstrateBridge` class مع async interface
2. `execute(cmd, limits, env, working_dir) -> ExecutionResult`
3. `stream_logs(request_id) -> AsyncIterator[LogEntry]`
4. `health_check() -> HealthStatus`
5. Connection pooling للـ Unix socket
6. Retry مع exponential backoff على transient errors
7. تحويل `ExecutionResult` إلى dataclass Python مع `evidence_hash`

**القيود:**
- `grpcio` للـ client — متوافق مع `tonic`
- Generated stubs من `protoc` + `grpcio-tools`
- لا blocking calls في async methods
- Context manager للـ connection lifecycle

**الأوامر:**
- python -m pip install grpcio grpcio-tools protobuf
- mkdir -p src/substrate
- cat > src/substrate/bridge.py << 'PYEOF'
  # ... (التنفيذ الكامل)
PYEOF

---

### §4 — تكامل مع LLM Layer (اختبار حلقة كاملة — **مشروط بنجاح §0.5**)

**المتطلبات:**
1. `LLMProvider` ينتج أمر → `SubstrateBridge` ينفذ → `Evidence` يعود → `LLM` يفسر
2. اختبار: `echo hello` → stdout + evidence_hash صحيح
3. اختبار: أمر يفشل (exit_code != 0) → خطأ منظم
4. اختبار: تجاوز memory limit → termination = LIMIT_BREACH
5. اختبار: streaming logs يعمل

**القيود:**
- لا mock — substrate حقيقي، LLM حقيقي (أو mock provider للاختبار)
- Evidence hash يُحفظ في `budget.consume()` للـ tracking

**الأوامر:**
- python -c "
  from llm import NVIDIAProvider, StructuredLLM
  from substrate.bridge import SubstrateBridge
  # اختبار حلقة كاملة
  "

---

### §5 — اختبارات التكامل (Integration Tests — **مشروط بنجاح §0.5**)

**المتطلبات:**
1. `tests/substrate/test_bridge.py` — pytest tests
2. Test: `execute_basic_command` — echo hello
3. Test: `execute_with_limits` — memory/CPU limits enforced
4. Test: `execute_streaming_logs` — logs arrive in order
5. Test: `health_check` — returns HEALTHY
6. Test: `concurrent_executions` — multiple requests handled
7. Test: `evidence_hash_reproducible` — same command = same hash

**الأوامر:**
- cat > tests/substrate/test_bridge.py << 'PYEOF'
  import pytest
  from substrate.bridge import SubstrateBridge
  # ...
PYEOF
- python -m pytest tests/substrate/test_bridge.py -v

---

### §6 — تحديث Evidence + Budget Integration

**المتطلبات:**
1. `ExecutionResult.evidence_hash` يُمرر إلى `TokenBudget.consume()` كـ metadata
2. `Evidence` struct يحتوي: `command_hash`، `output_hash`، `limits_hash`، `timestamp`
3. `ArtifactRegistry` يسجل كل execution كـ artifact قابل للتدقيق

**القيود:**
- لا تعديل على `src/llm/budget.py` — إضافة metadata فقط
- `evidence_hash` = SHA256(command + stdout + stderr + limits_json)

---

### §7 — قرارات مالك (للبوابة)

**D1:** هل نستخدم `grpcio` أم `tonic` للـ Python client؟ — الأدلة: `grpcio` ناضج، `tonic` في Rust فقط.
**D2:** هل Unix socket path ثابت أم configurable؟ — الأدلة: `/tmp/substrate.sock` افتراضي، env var للتجاوز.
**D3:** هل نضيف TLS للـ local socket؟ — الأدلة: لا — Unix socket permissions كافية للعزل المحلي.

---

### §8 — حدود الصدق

1. إذا `substrate-linux` لم ينفذ أمراً حقيقياً، لا نخفي الخطأ — نعيده كما هو.
2. لا نجاح زائف: `exit_code != 0` = فشل، لا "نجح مع تحذيرات".
3. Evidence hash يُحسب من output حقيقي، لا mock hash.
4. **إذا البيئة غير مؤهلة (§0.5 فشل)، الأمر يعلن ذلك صراحةً ولا يكمل.**

---

### §9 — قالب التقرير الإلزامي

التقرير يُبنى من هذه الحقول بهذا الترتيب:

```
VERDICT: PASS / HARD STOP / ENVIRONMENT_NOT_QUALIFIED
ENVIRONMENT CHECK: QUALIFIED / NOT_QUALIFIED (reason)
PROTO DEFINED: YES / NO
RUST SERVER BUILT: YES / NO
PYTHON BRIDGE WORKS: YES / NO
FULL ROUNDTRIP TEST: PASS / FAIL / SKIPPED
EVIDENCE HASH VALID: YES / NO
STREAMING LOGS WORK: YES / NO
HEALTH CHECK WORKS: YES / NO
INTEGRATION TESTS PASS: عدد/إجمالي
HARD STOPS FIRED: عدد أو NONE
ZERO-WRITE PROOF: قبل/بعد بصمة الملفين
```

---

### §10 — إثبات الكتابة-صفر قبل وبعد

**الأوامر:**
- python -c "
  import hashlib, os
  files = [
    'src/substrate/proto/substrate.proto',
    'crates/substrate-rpc/src/lib.rs', 
    'src/substrate/bridge.py'
  ]
  for f in files:
      h = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16] if os.path.exists(f) else 'MISSING'
      print(f'{f}: {h}')
  "

---

## 🪟 **ملحق: مسار Windows (منفصل، لا علاقة له بهذا الأمر)**

**هذا الأمر (Phase 1.0) ليس لبيئة Windows الحالية.**

على Windows، المسار مختلف تماماً:

| المكون | Linux (هذا الأمر) | Windows (أمر منفصل) |
|---------|------------------|---------------------|
| **Substrate** | `substrate-linux` (namespaces/seccomp/cgroups) | `subprocess` مع `Job Objects` (مبسط، لاحقاً) |
| **Bridge** | gRPC/Unix socket | **لا يوجد** — استدعاء مباشر |
| **Execution** | sandboxed حقيقي | **غير معزول** — phase 0 فقط |
| **Priority** | Phase 1.0 بعد LLM | **بعد Orchestrator + LLM** |

**الأمر الخاص بـ Windows سيصدر لاحقاً باسم:** `EXECUTION_ORDER_WINDOWS_EXECUTION.md`

---

**END OF ORDER**