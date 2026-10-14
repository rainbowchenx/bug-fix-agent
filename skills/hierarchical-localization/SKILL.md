---
name: hierarchical-localization
description: Use to locate bug sites — repo → package → file → symbol → line.
---

# Hierarchical Localization

1. Start from stack frames / error messages / page routes.
2. Map to package or feature folder.
3. Grep for unique symbols; open 2–5 candidate files.
4. Identify the earliest incorrect assumption, not only the crash line.
5. Record file paths in the root-cause writeup.
