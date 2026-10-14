---
name: systematic-debugging
description: Use when investigating failures — reproduce, isolate, hypothesize, verify before coding.
---

# Systematic Debugging

1. Reproduce or gather the strongest failure signal (stack, log, failing test).
2. Narrow scope to the smallest suspect module.
3. Form one hypothesis; test it with reads/searches before editing.
4. Only then propose a minimal fix.
5. Prefer evidence over speculation; if blocked, mark `needs_more_context`.
