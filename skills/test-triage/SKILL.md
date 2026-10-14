---
name: test-triage
description: Use when choosing or interpreting verify commands and failing test output.
---

# Test Triage

- Prefer existing project scripts (`npm test`, vitest, jest).
- Read failure tail carefully; distinguish product bug vs flaky env.
- When iterating, feed the exact failing assertion back into the next edit.
- Never claim GREEN without a real command succeeding.
