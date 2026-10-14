---
name: patch-review
description: Use after edits — self-review for regressions, scope creep, and missing tests.
---

# Patch Review

- Diff against intent: does each hunk serve the root cause?
- Check error paths and empty states.
- Confirm no secrets or env-specific hardcodes were introduced.
- Note residual risks in the MR description.
