# E44 — SYSTEM-SCALE SELF-HOSTING MISSION DEFINITION

## Mission Overview

**Mission ID**: e44-self-hosting-001
**Type**: Self-hosting engineering mission
**Target**: The factory's own evidence/verification system
**Self-Hosting**: TRUE — The factory operates on its own codebase

---

## Objective

**Implement cryptographic evidence chain integrity for all mission artifacts**

The factory currently produces artifacts with SHA256 hashes stored in the evidence store, but there is no cryptographic proof that the evidence chain itself (the sequence of events, artifacts, and verifications) has not been tampered with after creation.

This mission will:
1. **Discover** the current evidence system architecture
2. **Design** a cryptographic evidence chain with signed checkpoints
3. **Implement** the evidence chain integrity mechanism
4. **Integrate** it into the operational runtime
5. **Verify** it detects tampering
6. **Test** recovery from tamper detection
7. **Produce** complete evidence of the implementation

---

## Acceptance Criteria

The mission is complete when ALL of the following are verified:

### Discovery Phase
- [ ] Current evidence store architecture documented
- [ ] Artifact lifecycle traced from creation to verification
- [ ] Gap analysis: where tampering could occur undetected

### Design Phase
- [ ] Cryptographic evidence chain design document produced
- [ ] Threat model for evidence tampering documented
- [ ] Integration points with operational agents identified

### Implementation Phase
- [ ] `EvidenceChain` class implemented with:
  - [ ] Checkpoint signing (Ed25519 or equivalent)
  - [ ] Merkle tree of artifact hashes
  - [ ] Chain verification API
  - [ ] Tamper detection with evidence
- [ ] Integration into `OperationalVerifierAgent` and `EvidenceStore`
- [ ] New acceptance criterion type: `evidence_chain_intact`

### Verification Phase
- [ ] Golden task: create artifact → verify chain intact → PASS
- [ ] Tamper test: modify artifact post-creation → chain verification FAILS
- [ ] Recovery test: detect tamper → alert → reject completion
- [ ] All existing E43-R2 tests still pass (no regression)

### Evidence Phase
- [ ] Complete execution trace from discovery to completion
- [ ] All artifacts with cryptographic chain proofs
- [ ] Independent verification of the implementation
- [ ] Human intervention log

---

## Mission Architecture

```
DISCOVERY
    ↓
ARCHITECTURE/DESIGN
    ↓
IMPLEMENTATION (parallel: EvidenceChain, Integration, Tests)
    ↓
INTEGRATION TESTING
    ↓
TAMPER DETECTION TESTING
    ↓
RECOVERY TESTING
    ↓
REGRESSION TESTING
    ↓
EVIDENCE PACKAGING
    ↓
COMPLETION
```

---

## Controlled Failure Condition

**Injected Failure**: During implementation, introduce a deliberate bug in the Merkle tree construction that causes chain verification to fail on valid chains. The factory must:
1. Detect the failure during integration testing
2. Classify it as implementation bug (not infrastructure)
3. Recover by fixing the bug
4. Re-run verification
5. Continue to completion

---

## Interruption Point

**Planned Interruption**: After Implementation phase completes but before Verification phase. The mission will be paused, state persisted, then resumed to verify resume capability.

---

## Agents Required

- **EXPLORER**: Codebase discovery and analysis
- **ANALYST**: Requirements and threat modeling
- **PLANNER**: Task decomposition and scheduling
- **DESIGNER**: Cryptographic design
- **IMPLEMENTER**: Core implementation (EvidenceChain, integration)
- **SECURITY**: Security audit of cryptographic implementation
- **VERIFIER**: Independent verification of all artifacts
- **REVIEWER**: Final review and completion certification

---

## Expected Metrics (Targets)

| Metric | Target |
|--------|--------|
| mission_completion_rate | 1.0 |
| task_completion_rate | ≥ 0.9 |
| task_throughput | ≥ 1.0 tasks/sec |
| false_success_rate | 0.0 |
| verification_accuracy | 1.0 |
| tamper_detection_rate | 1.0 |
| reconstruction_accuracy | 1.0 |
| human_intervention_rate | ≤ 0.15 |

---

## Anti-Gaming Constraints

- No mock agents — all agents must be operational runtime agents
- No synthetic artifacts — all artifacts must be real code/files
- No weakened criteria — acceptance criteria are fixed at mission start
- No manual orchestration — factory manages task graph autonomously
- Evidence must reconstruct the complete execution
- Regression matrix must pass (E43-R2 protections intact)