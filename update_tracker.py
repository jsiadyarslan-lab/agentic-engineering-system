import re

text = open('EXECUTION-TRACKER-v2.1.md', 'r', encoding='utf-8').read()

# Find and replace the PHASE 0.5 section
old = """**Phase Progress: 57.1%** (8/14 completed)

---


## 📋 PHASE 0.5: RUST PORT (Weeks 3-4) — Target: 100%

| Status | ID | Title | Dependencies | Owner | Acceptance Criteria | Files |
|--------|-----|-------|--------------|-------|---------------------|-------|
| ⏳ | **0.5.1** | Port Linux Substrate to Rust (crates/substrate-linux) | 0.1.1 | Backend | cargo test -p substrate-linux passes | crates/substrate-linux/ |
| ⏳ | **0.5.2** | Port Windows Substrate (Job Objects + Silos) | 0.1.2 | Backend | cargo test -p substrate-windows passes | crates/substrate-windows/, crates/job-objects/, crates/silos/ |
| ⏳ | **0.5.3** | Port macOS Substrate (Seatbelt) | 0.1.3 | Backend | cargo test -p substrate-macos passes | crates/substrate-macos/, crates/seatbelt/ |
| ⏳ | **0.5.4** | FFI Bridge: Python EOE → Rust Substrates | 0.5.1, 0.5.2, 0.5.3 | Backend | eoe_engine calls substrate via FFI | src/substrate/ffi_bridge.py |

**Phase Progress: 0%** (0/4 completed)"""

new = """**Phase Progress: 57.1%** (8/14 completed)

---

## 📋 PHASE 0.5: LLM INTEGRATION LAYER (Weeks 2-3) — Target: 100%

| Status | ID | Title | Dependencies | Owner | Acceptance Criteria | Files |
|--------|-----|-------|--------------|-------|---------------------|-------|
| 🔄 | **0.5.1** | LLM Provider Abstraction Layer | 0.1.4 | Backend | `llm.chat([...])` returns structured output, supports NVIDIA/OpenAI/Anthropic/Local | `src/llm/provider.py`, `src/llm/nvidia_provider.py` |
| ⏳ | **0.5.2** | Structured Output Parsing (Pydantic) | 0.5.1 | Backend | `llm.structured(prompt, Model)` returns validated instance, retries on parse failure | `src/llm/structured.py` |
| ⏳ | **0.5.3** | Token Budget & Cost Tracking | 0.5.1 | Backend | `budget.check(tokens)` enforces limits, `cost.report()` accurate to $0.01 | `src/llm/budget.py` |
| ⏳ | **0.5.4** | Prompt Template Management | 0.5.1 | Backend | `prompt.load("explorer")` loads versioned template, supports variables | `src/llm/prompts/`, `src/llm/prompts/__init__.py` |

**Phase Progress: 25%** (1/4 completed)

---

## 📋 PHASE 1.0: RUST PORT (Weeks 3-4) — Target: 100%

| Status | ID | Title | Dependencies | Owner | Acceptance Criteria | Files |
|--------|-----|-------|--------------|-------|---------------------|-------|
| ⏳ | **1.0.1** | Port Linux Substrate to Rust (crates/substrate-linux) | 0.1.1 | Backend | cargo test -p substrate-linux passes | crates/substrate-linux/ |
| ⏳ | **1.0.2** | Port Windows Substrate (Job Objects + Silos) | 0.1.2 | Backend | cargo test -p substrate-windows passes | crates/substrate-windows/, crates/job-objects/, crates/silos/ |
| ⏳ | **1.0.3** | Port macOS Substrate (Seatbelt) | 0.1.3 | Backend | cargo test -p substrate-macos passes | crates/substrate-macos/, crates/seatbelt/ |
| ⏳ | **1.0.4** | FFI Bridge: Python EOE → Rust Substrates | 1.0.1, 1.0.2, 1.0.3 | Backend | eoe_engine calls substrate via FFI | src/substrate/ffi_bridge.py |

**Phase Progress: 0%** (0/4 completed)"""

if old in text:
    text = text.replace(old, new)
    open('EXECUTION-TRACKER-v2.1.md', 'w', encoding='utf-8').write(text)
    print('Updated successfully')
else:
    print('OLD STRING NOT FOUND')
    # Debug: show what we're looking for
    idx = text.find('## 📋 PHASE 0.5: RUST PORT')
    if idx >= 0:
        print(f'Found at index {idx}')
        print(repr(text[idx:idx+200]))
    else:
        print('Not found at all')

open('EXECUTION-TRACKER-v2.1.md', 'w', encoding='utf-8').write(text)