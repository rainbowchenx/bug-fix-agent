---
name: minimal-diff
description: Use when implementing fixes — keep patches tiny, local, and reviewable.
---

# Minimal Diff

- Change only what is required for the root cause.
- Avoid drive-by refactors, renames, and formatting churn.
- Prefer fixing call sites / guards over rewriting modules.
- Do not add dependencies unless essential.
