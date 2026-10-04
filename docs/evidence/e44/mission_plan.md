# E44 — SYSTEM-SCALE SELF-HOSTING EXECUTION PLAN

## Phase 1: DISCOVERY (Tasks 1-3)

### Task 1: Explore Evidence System Architecture
- **Agent**: EXPLORER
- **Operation**: run_command
- **Command**: find src -name "*.py" | xargs grep -l "evidence\|EvidenceStore\|artifact" | head -20
- **Acceptance**: file_contains:discovery_evidence.md:EvidenceStore

### Task 2: Trace Artifact Lifecycle
- **Agent**: EXPLORER
- **Operation**: run_command
- **Command**: grep -rn "store_artifact\|get_artifact\|write_artifact" src/unified/ src/evidence/ --include="*.py" | head -50
- **Acceptance**: file_contains:discovery_lifecycle.md:store_artifact

### Task 3: Analyze Current Verification Flow
- **Agent**: ANALYST
- **Operation**: write_file
- **Path**: discovery_verification.md
- **Content**: Analysis of how OperationalVerifierAgent checks artifacts, what gaps exist for chain integrity

---

## Phase 2: ARCHITECTURE/DESIGN (Tasks 4-6)

### Task 4: Threat Model for Evidence Tampering
- **Agent**: ANALYST
- **Operation**: write_file
- **Path**: design_threat_model.md
- **Content**: STRIDE analysis of evidence store, artifact creation, verification, storage

### Task 5: Cryptographic Evidence Chain Design
- **Agent**: DESIGNER
- **Operation**: write_file
- **Path**: design_evidence_chain.md
- **Content**: 
  - Ed25519 key generation and management
  - Checkpoint structure: {prev_hash, artifacts_merkle_root, timestamp, signature}
  - Merkle tree of artifact SHA256 hashes
  - Verification API: verify_chain(chain) -> {valid, tamper_evidence}

### Task 6: Integration Points Design
- **Agent**: DESIGNER
- **Operation**: write_file
- **Path**: design_integration.md
- **Content**: Where to hook into EvidenceStore, OperationalVerifierAgent, mission lifecycle

---

## Phase 3: IMPLEMENTATION (Tasks 7-12) — PARALLEL

### Task 7: Implement EvidenceChain Core
- **Agent**: IMPLEMENTER
- **Operation**: write_file
- **Path**: src/unified/evidence_chain.py
- **Content**: Full EvidenceChain class with signing, verification, Merkle tree

### Task 8: Integrate with EvidenceStore
- **Agent**: IMPLEMENTER
- **Operation**: write_file
- **Path**: src/unified/evidence_store_integration.py
- **Content**: Monkey-patch or extend EvidenceStore to maintain chain

### Task 9: Integrate with OperationalVerifierAgent
- **Agent**: IMPLEMENTER
- **Operation**: write_file
- **Path**: src/unified/verifier_chain_integration.py
- **Content**: Add evidence_chain_intact criterion support

### Task 10: Add Acceptance Criterion Type
- **Agent**: IMPLEMENTER
- **Operation**: write_file
- **Path**: src/unified/verification_standard_ext.py
- **Content**: New criterion type for evidence chain verification

### Task 11: Write Tamper Detection Tests
- **Agent**: IMPLEMENTER
- **Operation**: write_file
- **Path**: tests/e44/test_evidence_chain.py
- **Content**: Tests for valid chain, tampered chain, recovery

### Task 12: Write Golden Task Test
- **Agent**: IMPLEMENTER
- **Operation**: write_file
- **Path**: tests/e44/test_golden_chain.py
- **Content**: End-to-end test: create → verify → tamper → detect

---

## Phase 4: INTEGRATION TESTING (Tasks 13-14)

### Task 13: Run Integration Tests
- **Agent**: VERIFIER
- **Operation**: run_command
- **Command**: python -m pytest tests/e44/test_evidence_chain.py -v
- **Acceptance**: command_succeeds:pytest tests/e44/test_evidence_chain.py

### Task 14: Run Golden Chain Test
- **Agent**: VERIFIER
- **Operation**: run_command
- **Command**: python -m pytest tests/e44/test_golden_chain.py -v
- **Acceptance**: command_succeeds:pytest tests/e44/test_golden_chain.py

---

## Phase 5: TAMPER DETECTION TESTING (Tasks 15-16)

### Task 15: Tamper Test - Modify Artifact Post-Creation
- **Agent**: SECURITY
- **Operation**: security_audit
- **Target**: test artifacts
- **Scan Types**: ["tamper_detection"]
- **Acceptance**: file_contains:tamper_test_result.md:TAMPER_DETECTED

### Task 16: Recovery Test - Detect Tamper → Alert → Reject
- **Agent**: VERIFIER
- **Operation**: run_command
- **Command**: python -c "from unified.evidence_chain import *; test_recovery()"
- **Acceptance**: file_contains:recovery_test_result.md:RECOVERY_SUCCESS

---

## Phase 6: REGRESSION TESTING (Tasks 17-18)

### Task 17: Run E43-R2 Regression Matrix
- **Agent**: VERIFIER
- **Operation**: run_command
- **Command**: python -m pytest tests/e43/test_adversarial.py -v
- **Acceptance**: command_succeeds:pytest tests/e43/test_adversarial.py

### Task 18: Run E43-R2 Scale Tests
- **Agent**: VERIFIER
- **Operation**: run_command
- **Command**: python -m pytest tests/e43/test_scale.py -v
- **Acceptance**: command_succeeds:pytest tests/e43/test_scale.py

---

## Phase 7: EVIDENCE PACKAGING (Tasks 19-20)

### Task 19: Package Complete Evidence
- **Agent**: REVIEWER
- **Operation**: write_file
- **Path**: e44_complete_evidence.md
- **Content**: Complete execution trace, all artifacts, chain proofs, verification results

### Task 20: Final Certification
- **Agent**: REVIEWER
- **Operation**: write_file
- **Path**: e44_final_verdict.md
- **Content**: Final verdict with all metrics, human intervention log, regression status

---

## Dependency Graph

```
1 → 2 → 3
    ↓
4 → 5 → 6
    ↓
7 → 8 → 9 → 10
    ↓
11 → 12
    ↓
13 → 14
    ↓
15 → 16
    ↓
17 → 18
    ↓
19 → 20
```

Parallel groups: {7,8,9,10,11,12} can run in parallel after 6 completes

---

## Controlled Failure Injection

**Task 7 (EvidenceChain Core)**: Deliberate bug in Merkle tree root calculation
- Expected: Task 13 fails
- Recovery: Factory detects, classifies, fixes, re-runs

---

## Interruption Point

**After Task 12 completes** — Mission paused, state saved, then resumed for Phase 4+