# defect-batch-prepare — reference

## Authority

| Topic | Source |
|---|---|
| C* screen rules / expectQuality / field bans | `docs/defect-input-analysis/_stage1-rules.md` |
| R0–R6 pool semantics / L1→L2→L3 keys | `docs/superpowers/specs/2026-10-30-defect-screen-cluster-design.md` |
| Implementation | `bugfix_agent/defect_batch/*`, `bugfix_agent/ingest/*`（Python） |

## Pool mapping (screen)

| Pool | Meaning |
|---|---|
| `strict` | FIXABLE ∧ expectQuality ∈ {explicit, inferred} — primary cluster queue |
| `locatable_only` | FIXABLE ∧ expect not unique |
| `needs_info` | C1/C2/C4/C5-style info gaps |
| `hard_reject` | C3/C3b/C7 hard non-code or SCA+CVE |
| `security` | `[安全]` title or scanner corpus (bypass) |
| `excluded` | Cancel / Not a bug / beta non-Open |

## Cluster id

```text
{productLine}::{testModule}::{titleTag}::{intent}[::{tokenBucket}]
```

L3 default = heuristic `IntentClassifier`; inject LLM later via `cluster.intentClassifier`.

## Posture

- `alpha` — keep all statuses in functional funnel (rule-shape analysis)
- `beta` — only `Open`/`New` (daily-batch simulation)
