# NGINX_RULE_VALIDATION — AES-P0-CONTAINMENT-PR-REMEDIATION-1113-R1 (fix 3)

**Scope:** replacement of the file-wide keyword-co-presence check (rule C) with a conservative block-scoped analyzer; introduction of rule D (REVIEW_REQUIRED, fail-closed).
**Explicit disclaimer (as ordered):** the analyzer is a tokenizer + block-tree reasoner, **not** a real nginx parser. It does **not** prove an nginx configuration is secure. When it cannot parse, or sees an unresolved `include`, it refuses to declare the content safe (rule D). Only a clear, parseable, single-block pattern of `allow all` + effective `auth_basic off` + `proxy_pass` is reported as rule C.

## 1. The defect in the shipped rule C (OBSERVED at `1adfaf1`)

```python
elif text.count("allow all") and re.search(r"auth_basic\s+off", text) and re.search(r"proxy_pass", text):
```

- The three directives could sit in **different, unrelated blocks** (or in prose/strings) and still be reported — an approximate keyword check, not block analysis.
- No understanding of `location` boundaries, `server` inheritance, or `include`.

## 2. The new analyzer (VERIFIED by tests)

Pipeline per scanned blob:
1. **Tokenizer** — words, `{`/`}` braces, `;` directive terminators, `#` comments, quoted strings; line numbers kept. Python `.format()` escapes (`{{`/`}}`) collapse to single braces; short `{placeholder}` runs stay inside the word stream so embedded templates still parse.
2. **Block tree** — words before `{` form the block header (`location …`, `server`, `http`…); directives end at `;`; unbalanced braces mark the blob **unparsed** → rule D.
3. **Effective directives** — `auth_basic` resolves nearest-wins (location overrides server); `allow`/`deny` resolve location-own-else-inherited; `proxy_pass` must be in the location itself.
4. **Rule C** fires only when one location has all three *effectively*: explicit `allow all`, effective `auth_basic off`, own `proxy_pass`.
5. **Rule D** (REVIEW_REQUIRED) fires on: unresolved `include` inside any non-root block; unparseable (unbalanced) nginx-like content.
6. **Blob selection** — real conf extensions (`.conf`/`.nginx`) or nginx-shaped raw text are analyzed whole; for other files (deploy scripts), each **string literal** that is nginx-shaped is analyzed separately, so Python braces never contaminate the block tree.

Validation matrix (all synthetic; run locally 2026-11-13, exit codes asserted):

| Case | Result | Test |
|---|---|---|
| Single location `allow all` + `auth_basic off` + `proxy_pass` | rule-C fired | `test_nginx_public_unauth_proxy_detected` |
| `allow all` in location A, `auth_basic off` (with own allow-list) in location B, `proxy_pass` in location C, server-level `auth_basic "realm"` | **no finding** — directives never merged across blocks | `test_nginx_separate_blocks_not_flagged` |
| Unresolved `include` in server block | rule-D REVIEW_REQUIRED | `test_nginx_include_unresolved_review_required` |
| Unbalanced braces | rule-D REVIEW_REQUIRED | `test_nginx_unparsable_content_review_required` |
| nginx template embedded in a Python triple-quoted string (w1t03 pattern) | rule-C fired from the literal blob | `test_nginx_embedded_template_in_python_detected` |
| Real repo file `scripts/ops/w1t03_monitor_deploy.py` | rule-C fired pre-suppression (allowlist entry live) | direct invocation, 2026-11-13 |
| nginx-like text under `docs/` | not analyzed (docs are historical records, not actionable config) | `test_docs_markdown_nginx_text_not_flagged` |

## 3. Inheritance semantics actually implemented

- `auth_basic`: nearest declaration wins (location → server → http → root). `auth_basic off` in a location overrides an inherited realm; a realm string in a location overrides an inherited `off`.
- `allow`/`deny`: if the location declares any of its own, they are used; otherwise the nearest ancestor set applies.
- These are the two inheritance rules nginx documents for these directives; nothing deeper is claimed (no `map`, no variables, no regex-location resolution).

## 4. Known limits (declared, fail-closed behavior)

- `if (...) { }` blocks are parsed as blocks; `include` inside them still yields rule D. Complex conditions are not evaluated.
- Real nginx configs with adjacent closing braces without newlines (`}}`) would be read as one escape token — such files (if unbalanced afterwards) fall to rule D, never to a silent pass.
- The analyzer may miss exposures expressed through mechanisms it does not model (variables, upstream indirection). Its job is fail-closed triage, not proof of security — that decision remains with human review.
