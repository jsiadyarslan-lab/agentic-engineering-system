# SECRET_GUARD_REVIEW — AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (fix 1 + hardening)

**Scope:** review and repair of `scripts/ops/secret_guard.py` as shipped in PR #4 commit `1adfaf1`.
**Method:** code analysis + synthetic-data tests (`tests/security/test_secret_guard.py`) + full-repo scan.
**Baseline for comparison:** guard as of `1adfaf1` (132 lines) — identical to the local copy archived at `scripts/c1113/secret_guard.py` (VERIFIED by byte-identity at review start).

## 1. The defect (confirmed — OBSERVED)

As shipped, `scan_file()` contained:

```python
if "secret_guard" in path:
    return findings  # the scanner itself contains rule definitions
```

`path` was the **absolute filesystem path** of the scanned file. The check is a substring test, therefore it excluded:

- any file whose *name* merely contains `secret_guard` (e.g. `my_secret_guard_config.py`),
- every file under any *directory* named `secret_guard`,
- and — if the repository itself were cloned into a directory containing `secret_guard` — the entire repository.

Effect: a credential committed into such a path bypasses the guard completely. This is a hole in the control that exists to prevent a repeat of the 1113 incident. (Classification: OBSERVED — the code line existed verbatim in `1adfaf1`.)

## 2. The repair (R1 §3) — VERIFIED

1. The substring exclusion is **removed entirely**.
2. Self-exclusion is now an **exact repo-relative POSIX path comparison**:

```python
SELF_EXACT = "scripts/ops/secret_guard.py"
...
if rel == SELF_EXACT:
    continue
```

3. No other file is excluded by name or folder — including files that contain `secret_guard` in their path.
4. The two cases ordered by the command were implemented as tests:
   - repo root directory *containing* `secret_guard` in its name + a credential file inside → **detected** (`test_exclusion_is_exact_path_not_substring`);
   - file named `secret_guard_credentials.py` carrying a fully synthetic credential → **detected** (`test_copy_of_guard_with_credential_at_other_path`, `test_guard_file_is_skipped_only_at_exact_relpath`).
5. A copy of the guard at its exact relpath is still skipped; the same copy placed at any other path is scanned (`test_guard_file_is_skipped_only_at_exact_relpath`).

## 3. Additional hardening performed in the same file (fixes 3, 4 and review findings)

| Change | Why |
|---|---|
| Rule A extended to **JSON-key form** (`"api_key": "…"`) and **shell form** (`TOKEN=…`, optional `export`) with case-insensitive JSON keys | R1 §4 requires detection of "a constant credential in Python and JSON and Shell" |
| Value classification gate: regex-looking values (`\\`, `[]`, `(`, `|`…) and known placeholders are not credentials; prose JSON values (spaces/slashes) are descriptions; fixture-marker values (`test`, `fake`, `dummy`, `sample`, `synth`, `example`, `LOGKEY`, `12345678`, `999999`) treated as synthetic test data | Avoids false positives on `_COMMAND_TOKEN_RE`-style regex constants, repo prose, and test fixtures — while hex/base64-like values still fire |
| Dedupe of the three rule-A forms by (line, sha256[:12]) | Python-style and shell-style patterns could double-report one line |
| Nginx analysis rewritten block-scoped (see NGINX_RULE_VALIDATION.md) | R1 §5 |
| Allowlist is governed JSONL with expiry, fail-closed (see ALLOWLIST_REVIEW.md) | R1 §6 |
| Findings never print the value — only `sha256[:12]` (retained from P0) | Credential hygiene |

## 4. Verification status

| Claim | Class |
|---|---|
| Substring exclusion existed at `1adfaf1` | OBSERVED (code line read from the commit) |
| Exact-path exclusion implemented; substring cases detected | VERIFIED (21/21 local tests, `tests/security/test_secret_guard.py`, 2026-11-13, exit 0) |
| Full-repo scan after hardening: CLEAN, exit 0 (W1 entries suppressed via governed allowlist) | VERIFIED (local run 2026-11-13) |
| w1t03_monitor_deploy.py still produces a rule-C finding pre-suppression (allowlist entry is live, not stale) | VERIFIED (direct analyzer invocation) |
| w1t02_audit_check.py still produces a rule-A finding pre-suppression | VERIFIED (direct scan, 1 finding line 29) |
| secret-guard workflow passes on the branch in CI after the push | OBSERVED (run on the R1 commit — see TRUSTED_SUITE_FAILURE_ANALYSIS.md §6) |
| Synthetic values only in tests (no real or historical credential) | VERIFIED (test file builds values by runtime concatenation of fragments; full values never appear in source) |

## 5. Residual limitations (INFERRED / declared)

- Rule A is lexical, not semantic: a credential assigned to an innocuous name (`DATA = "hex40…"`) is not detected. This is the accepted detection scope since P0; deep entropy scanning is out of scope for R1.
- The fixture-marker convention can, by design, suppress a *real* secret that contains the word `test` etc. Trade-off accepted and documented; expires only by changing the guard.
- Docs (`*.md`, `docs/**`) are excluded from rules C/D (historical records are not actionable config); rules A/B still scan them.
