# AES-UI-PREMIUM-REDESIGN-004 — CI trigger marker

This file exists only on the temporary `aes-integration-004-ci-run` branch to trigger the repository's `AES trusted suite` workflow through a pull request whose base already contains `.github/workflows/trusted-suite.yml`.

- Audited integration baseline: `d55f4bba6b2f0133b446a1b6ba3d51105305eb64`
- Intended tests: `tests/readiness`, `tests/core`, `tests/api`
- This marker is not application code and must not be merged into `main` or the production integration branch.
- No deployment is authorized by this marker.
