# ALLOWLIST_REVIEW — AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (fix 4)

**Scope:** governance of `.secretguard-allow` as ordered by R1 §6: every exception must carry an owner, a reason, a creation date, a clear expiry, and the task that will resolve it; an expired entry must fail the scan.

## 1. Format change (OBSERVED: before → after)

| | Before (`1adfaf1`) | After (R1) |
|---|---|---|
| Format | free text: `<relpath>` or `<relpath>:<RULE>` | JSONL, one object per line |
| Fields | path + optional rule | `path`, `rule` (A\|B\|C\|D\|*), `owner`, `reason`, `created`, `expires` (YYYY-MM-DD), `task` |
| Expiry | none | required; expired entry → **scan fails (fail-closed)**, error names the path and date |
| Validation | none | missing/invalid fields, invalid JSON, invalid rule value, future `created` → config error, exit 1 |

Expiry reference: current UTC date. All errors print `ALLOWLIST CONFIG ERROR — fail-closed` with the line number.

## 2. Entries after migration (VERIFIED — file is the one in this PR diff)

| # | path | rule | owner | reason (summary) | created | expires | task |
|---|---|---|---|---|---|---|---|
| 1 | `scripts/ops/w1t03_monitor_deploy.py` | C | repo-owner | W1-T03 public `/healthz` liveness endpoint template (allow all + auth_basic off + proxy_pass to `8010/health`, GET-only, no app data) — separate owner decision | 2026-11-13 | 2027-01-31 | AES-P0 follow-up: W1-T03 healthz re-evaluation |
| 2 | `scripts/ops/w1t03_audit_check.py` | C | repo-owner | audit checker references the same directives as *expectations* for verifying the server conf; retained as defense-in-depth (the block-scoped analyzer no longer flags this file — see note) | 2026-11-13 | 2027-01-31 | AES-P0 follow-up: W1-T03 healthz re-evaluation |
| 3 | `scripts/ops/w1t02_audit_check.py` | A | repo-owner | `HTPASSWD_SHA` constant — see classification below | 2026-11-13 | 2027-01-31 | AES-P0 follow-up: W1-T02 fingerprint classification + Basic-Auth rotation decision |
| 4 | `docs/ops/aes-remediation/P3-STALE-DIAG/diag_readonly.json` | A | repo-owner | historical read-only diagnostic records an internal SSE resume cursor — see classification below | 2026-11-13 | 2027-01-31 | AES-P0 follow-up: sanitize historical ops dumps |

Note on entry 2: the R1 analyzer evaluates rule C **within one location block only**; the w1t03 *audit checker* holds the directives as comparison strings, not as a block — so it no longer produces a finding. The entry is kept deliberately (documented here) as defense-in-depth for the rule-C surface on that file; it is not required for a CLEAN scan and can be dropped by the owner together with the W1-T03 remediation.

## 3. Value classification — as ordered, no assumptions

### `HTPASSWD_SHA` (W1-T02, `scripts/ops/w1t02_audit_check.py:29`)

- OBSERVED context: the 64-hex constant is compared against `sha256sum /etc/nginx/.htpasswd_vis` output (script lines 152, 346–350): it is the **SHA-256 fingerprint of the htpasswd file** used to detect drift.
- It is a **hash, not plaintext**, and it is not, by itself, login-capable material. Login capability is NOT established by this review.
- Therefore it is **classified as needs-review**, recorded in the allowlist entry as such, and the Basic-Auth **password rotation decision is deferred to the owner with this evidence** — the R1 command explicitly forbids describing it as a password before its nature is proven. Rotation of the Basic-Auth password remains a reasonable owner-side precaution because the hash is public; that decision (and its execution on the receiving server) is out of R1 scope.
- VERIFIED: the guard still reports a rule-A finding for this file pre-suppression (1 finding, line 29) — the entry is live.

### `resume_token` (P3-STALE-DIAG, `docs/ops/aes-remediation/P3-STALE-DIAG/diag_readonly.json:66`)

- OBSERVED context: `"resume_token": "rsm-…"` sits next to `"last_event_id": "1664"` in a read-only diagnostic dump from 2026-10-28 — an internal **SSE resume cursor** captured from execution state, not an access credential.
- Classified as internal stream cursor; recorded in the allowlist with expiry 2027-01-31 and a task to sanitize historical ops dumps. If the owner classifies it differently, the entry should be removed and the material rotated — the guard then fails closed on it.

## 4. Lifecycle rules (implemented — VERIFIED by tests SG-11…SG-15)

- Any line that is not JSON or misses a field → scan fails.
- An entry whose `expires` is in the past → scan fails with `EXPIRED entry … renew or remove it`.
- Renewal or removal is an owner action; the guard never silently extends.

## 5. Evidence classes

- Format/validation behavior: VERIFIED (local tests, `tests/security/test_secret_guard.py`).
- Entries content: OBSERVED (read from the migrated `.secretguard-allow` in this branch).
- W1-T02 / resume-token classifications: INFERRED from script context (documented above with the exact lines), explicitly marked as unproven until the owner decides.
