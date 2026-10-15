---
name: patch-review
description: Use after edits / as readonly reviewer — approve or request_changes before MR. Never edit files in review mode.
---

# Patch Review

Readonly gate for automated bugfix (no Edit tools).

## Decision contract

Output exactly one JSON object:

```json
{ "decision": "approve" | "request_changes", "reasons": ["..."] }
```

- `approve` — diff matches root cause, within `target_files`, tests not weakened without cause.
- `request_changes` — list concrete blockers (scope creep, missing guard, bad test change, etc.).

## Checklist

- Diff against intent: does each hunk serve the root cause?
- Scope lock respected?
- Error paths and empty states covered?
- No secrets / env hardcodes?
- Residual risks named in `reasons` even on approve.
