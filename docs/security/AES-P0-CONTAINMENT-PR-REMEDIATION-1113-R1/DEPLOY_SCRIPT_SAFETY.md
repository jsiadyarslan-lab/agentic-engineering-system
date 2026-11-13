# DEPLOY_SCRIPT_SAFETY — AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (fix 5)

**Scope:** `w2t25-monitor-v2/apply_owner_console_v3.py` (the owner-console deploy script) and `w2t25-monitor-v2/apply_monitor_v2.py`.
**Constraint honored:** no deploy script was executed at any point of R1; the POST opt-in was never used; tests are import/unit/mechanism-level only (per R1 §7: "اختبر تحليل الكود ووحداته فقط").

## 1. The risk (OBSERVED at `1adfaf1`)

`apply_owner_console_v3.py` `main()` ran a single `checks` list on every deployment:

- `relay-harmless-gate` — POST `/api/projects/3/gates/999999` (targets the **gates** control surface),
- `relay-forbidden-path` — POST `/api/projects/3/plan/delete`,
- `owner-mode-on` / `owner-mode-off` — POST `/api/owner-mode` (flips the **owner-mode** state),
- and the token was still placed in `curl`'s argument list via `-H "X-Access-Key: $W2T25_MONITOR_TOKEN"`.

So a routine "verification" step could change project state (gate/owner-mode) by default, and pass the credential through process arguments visible in `/proc/*/cmdline`.

## 2. The repair (VERIFIED by unit tests — `tests/security/test_deploy_script_safety.py`)

`apply_owner_console_v3.py`:

1. **Default verification is GET-only and state-free**: `GET_CHECKS` = `healthz`, `owner-mode-get`, `page-has-owner`, `driver-alive`, `driver-log`. No POST, no PUT/PATCH/DELETE, no project state change.
2. **State-changing POSTs live in `POST_CHECKS`** and run only under a **dual explicit opt-in**:

   ```
   python3 apply_owner_console_v3.py --with-post-checks --confirm-post-changes
   ```

3. Incomplete opt-in (`--with-post-checks` without `--confirm-post-changes`) is **refused** (`verification_checks` returns `None`, `main` exits 2 with `REFUSED:` message).
4. When both flags are given, the script prints a **WARNING listing exactly which state-changing checks will run**, then a 10-second abort window before proceeding.
5. `verification_checks(with_post, confirm)` is a pure function — unit-tested without executing anything.

`apply_monitor_v2.py`: its checks were already GET-only; the credential transport was moved to STDIN headers (below), and the token read became lazy.

## 3. Credential transport (fix 6 applied here as well)

- The token is read **lazily** (`load_token()` — env var or the root-only secret file) — importing either script touches no secret and connects to nothing (test: `test_owner_console_import_is_side_effect_free`).
- Every authenticated curl now pipes the header through **stdin**:

  ```
  printf "X-Access-Key: %s" "$W2T25_MONITOR_TOKEN" | curl -s -m 8 -H @- "http://127.0.0.1:8765/…"
  ```

  The value lives in the shell's memory (printf is a builtin) and in curl's stdin — never in a URL, never in a process argument list, never printed. POST checks pipe `X-Access-Key` and `Content-Type` headers the same way.

## 4. What was NOT changed

- The patch/deploy machinery (`patch_monitor`, `patch_driver`, restarts, backups) is untouched — R1 is a PR repair, not a redeployment; those functions are the script's documented purpose and are only run by an explicit deployment decision of the owner.
- No production file was touched (R1 forbids Oracle access entirely).

## 5. Verification status

| Claim | Class |
|---|---|
| POST checks existed in the default path at `1adfaf1` | OBSERVED (code read) |
| Default path is GET-only now; incomplete opt-in refused; dual opt-in unlocks POST with warning | VERIFIED (9/9 unit tests, local run 2026-11-13) |
| Token absent from URLs/argv in all checks | VERIFIED (source assertions `test_owner_console_token_never_in_url_or_argv`, `test_monitor_v2_no_query_string_auth`) + mechanism test with a FAKE value (`tests/security/test_audit_token_path.py` — argv sampling via /proc) |
| Neither script was executed during R1 | VERIFIED (no process was spawned from them; only import/AST/unit access) |
| CI green for these tests on the R1 commit | OBSERVED after push (trusted-suite run) |
