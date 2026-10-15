---
name: systematic-debugging
description: Use when investigating failures — reproduce, isolate, hypothesize, verify before coding. Enforces IRON LAW (no fix without evidenced root cause).
---

# Systematic Debugging

**IRON LAW:** No code changes without a proven hypothesis. Every change must trace to evidenced root cause. If blocked, mark `needs_more_context` / `not_actionable` — do not ship symptom patches.

## Process

1. Reproduce or gather the strongest failure signal (stack, log, failing test).
2. Narrow scope to the smallest suspect module (repo → package → file → symbol).
3. Map to a failure mode: `race_condition` | `nil_propagation` | `state_corruption` | `integration_failure` | `configuration_drift` | `stale_cache` | `logic_error` | `api_contract_mismatch` | `other`.
4. Form **one** explicit hypothesis; gather evidence with reads/searches before editing.
5. **3-strike:** if the same hypothesis fails three checks, stop and re-investigate (do not pile symptom patches).
6. Only then propose a minimal fix with `target_files` allowlist.
7. Prefer evidence over speculation.

## BugFix light path

This is defect repair, not greenfield delivery: skip PRD/architecture theater; localize → root cause → minimal solution → verify.
