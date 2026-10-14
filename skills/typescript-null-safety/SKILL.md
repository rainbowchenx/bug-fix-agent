---
name: typescript-null-safety
description: Use for TypeScript null/undefined crashes and unsafe optional chaining gaps.
---

# TypeScript Null Safety

- Prefer narrowing (`if (!x) return`) over non-null assertions (`!`).
- Fix types at the source when data can legitimately be missing.
- Avoid `as any` unless bridging an external untyped boundary.
