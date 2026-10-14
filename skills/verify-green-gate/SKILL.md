---
name: verify-green-gate
description: Use before delivery — no MR without a passing verify command.
---

# Verify Green Gate

Hard rule for this product: **no GREEN, no MR**.

- If no test command exists → stop with `no_test_command`.
- If verify fails after iterate budget → `verify_failed` with log tail.
- Do not open MRs based on model self-assessment alone.
