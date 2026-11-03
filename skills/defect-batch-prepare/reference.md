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

## Platform CSV notes（脱敏样本实测）

- 描述常为**单行粘连**模板；distill 按标签切 `预期结果`/`实际结果`/`操作步骤`（不必有换行）。
- 空模板 /「包括复现方法和现象描述等」→ **`needs_info` / C1a**（默认开启）。
- 标题以 `问题描述:` 开头 → `titleTag=_code_review`；肥簇按符号 token 再切；并跳过 C3/security 误杀。

