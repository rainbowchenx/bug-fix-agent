---
name: minimal-diff
description: Use when implementing fixes — keep patches tiny, local, and within scope lock (solution target_files only).
---

# Minimal Diff + Scope Lock

- Change only what is required for the evidenced root cause.
- **Scope lock:** edit only files listed in the solution `target_files` (or named in solution steps). Do not touch unrelated modules.
- Avoid drive-by refactors, renames, and formatting churn.
- Prefer fixing call sites / guards over rewriting modules.
- Prefer fixing product code over weakening tests (unless the assertion is clearly wrong).
- Do not add dependencies unless essential.
