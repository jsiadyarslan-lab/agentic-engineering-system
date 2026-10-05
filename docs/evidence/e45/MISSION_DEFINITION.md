# E45 MISSION DEFINITION

## Mission ID
e45-autonomous-mission

## User Request
Build a real engineering feature for the Agentic Engineering System: **File Size Verification Criterion**

A new acceptance criterion type `file_size` that allows verification of file size constraints (min/max bytes). This extends the verification standard and provides a practical tool for engineering missions that need to enforce artifact size limits.

## Mission Scope

The mission must deliver:
1. **Core Implementation**: `FileSizeCriterion` class in `src/unified/verification_standard.py`
2. **Integration**: Register criterion in `OperationalVerifierAgent` 
3. **Tests**: Unit tests for the new criterion
4. **Documentation**: Update verification standard documentation
5. **Demo**: Example mission using the new criterion

## Task Graph (Initial Plan v1)

```
TASK-A: Discovery & Analysis
  ├─> TASK-B: Design FileSizeCriterion
  ├─> TASK-C: Implement FileSizeCriterion
  │    ├─> TASK-D: Unit Tests (parallel branch 1)
  │    └─> TASK-E: Integration Tests (parallel branch 2)
  ├─> TASK-F: VerifierAgent Integration
  ├─> TASK-G: Update Documentation
  ├─> TASK-H: Create Example Mission
  └─> TASK-I: Verification Gate (all tests pass)
       └─> TASK-J: Final Review & Complete
```

## Dependencies
- B depends on A
- C depends on B
- D depends on C
- E depends on C
- F depends on C
- G depends on C
- H depends on C
- I depends on D, E, F
- J depends on I, G, H

## Acceptance Criteria
- All code follows existing patterns (E33/E43/E44 style)
- No mock agents, no fake artifacts, no verification weakening
- All tests pass with independent verification
- Evidence chain maintained throughout

## Failure Opportunity
TASK-C (Implementation) has a deterministic first-attempt failure injection to demonstrate failure detection, recovery, and replanning.

## Replanning Opportunity
If TASK-C fails and cannot be recovered by retry, the mission will replan to add a remediation task and potentially adjust the implementation approach.

## Human Gate
At TASK-I (Verification Gate), if tests fail unexpectedly, a human decision is required to proceed.