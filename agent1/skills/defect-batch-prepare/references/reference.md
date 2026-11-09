# defect-batch-prepare — reference

Read this when you need pool meanings, posture, or CSV quirks. Do not re-run these rules in chat; `prepare-batch` already applied them.

## Authority

| Topic | Source |
|---|---|
| Screen rules / expectQuality / field bans | `docs/defect-input-analysis/_stage1-rules.md` |
| R0–R6 pool semantics / L1→L2→L3 keys | `docs/superpowers/specs/2026-10-30-defect-screen-cluster-design.md` |
| Implementation | `agent1/bugfix_agent1/defect_batch/*`, `agent1/bugfix_agent1/ingest/*` |

## Pool mapping

| Pool | Meaning |
|---|---|
| `strict` | Fixable and expectQuality is explicit or inferred — primary cluster queue |
| `locatable_only` | Fixable but expected result is not unique |
| `needs_info` | Information gap (thin template, design unset, missing attachment) |
| `hard_reject` | Hard non-code or SCA+CVE |
| `security` | `[安全]` title or scanner corpus |
| `excluded` | Cancel / not a bug / beta non-Open |
| `duplicate` | Duplicate ticket |

Match pool (default work set after this skill): `strict` ∪ `locatable_only` ∪ `needs_info`.

## Cluster id

```text
{productLine}::{testModule}::{titleTag}::{intent}[::{tokenBucket}]
```

L3 first pass is a keyword heuristic. Intent review after `prepare-batch` sets `intentSource=ai` and `apply-review` rebuilds cluster ids.

## Posture

- `alpha` — keep all statuses in the functional funnel (rule-shape analysis)
- `beta` — only `Open` / `New` (daily-batch simulation)

## Platform CSV notes

- Descriptions are often a **single glued template line**; distill splits on 预期结果 / 实际结果 / 操作步骤 even without newlines.
- Empty template or「包括复现方法和现象描述等」→ `needs_info`.
- Title starting with `问题描述:` → `titleTag=_code_review`; fat clusters split on a title token.
- Field map SSOT: `agent1/bugfix_agent1/ingest/field_map.py` (includes platform typo `describle`).
