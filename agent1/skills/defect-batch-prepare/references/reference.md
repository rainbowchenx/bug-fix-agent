# defect-batch-prepare — reference

Read this when you need pool meanings, posture, or CSV quirks. Do not re-run these rules in chat; `prepare-batch` already applied them.

## Authority

`SKILL.md` and `references/` in this folder are self-contained: everything you need to run
Step 1–3 is here. The two design specs below live only in the source repo — do not go looking
for them in the installed skill.

| Topic | Source |
|---|---|
| 产物契约（字段 / 池 / funnel） | `references/defect-batch-guide.md` — shipped with this skill |
| Screen rules / expectQuality / field bans | repo only: `docs/defect-input-analysis/_stage1-rules.md` |
| R0–R6 pool semantics / L1→L2→L3 keys | repo only: `docs/superpowers/specs/2026-10-30-defect-screen-cluster-design.md` |
| Implementation | repo only: `agent1/bugfix_agent1/defect_batch/*`, `agent1/bugfix_agent1/ingest/*` |

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

**`testModule` and `titleTag` are usually the same string.** The title prefix `[模块名]` is the
module column, so on the exports measured (`5/5`, `21/26`, `19/19`, `36/37`, `54/56`) the key is
really `module::module::intent`. All the resolution comes from `intent`; do not present L1 and L2 as
two corroborating signals in a hand-off. They differ only when the bracket names something else than
the module column — e.g. `[WEB]` on an export whose module column says `WEB基础组(正式批)`, which is
the one case where L2 carries information of its own.

## Posture

A single switch: does the status gate close?

- `beta` (default, and the normal answer) — non-`Open`/`New` goes to `excluded`
  (`reasonDetail: beta posture skips non-Open/New`). Closed tickets are not work.
- `alpha` — gate off, every status reaches the functional funnel. Rule-shape
  research and regression only: closed tickets carry closed-loop fields
  (resolver, root cause), so using them to judge pools leaks the answer.

`is_open_like` accepts exactly `Open` / `New` / `打开` / `新建` (full string, case-insensitive).
`处理中`, `已解决`, `待验证`, `Resolved` all count as closed. On an all-`Open` export the two
postures give identical tickets — only the `posture` field differs.

`excluded` mixes two things: void / not-a-bug (`reasonDetail: Cancel / Not a bug / void`) and the
posture gate. Read `reasonDetail`, not the pool name.

## Product line

Not a column in the export; there is no alias for it in `field_map.py`. It is a namespace written
to the artifact and used as the `clusterId` prefix. Derived when omitted (`--product-line` →
`BUGFIX_PRODUCT_LINE` → raw-defects `productLine` → project code in the file name). `hc` in the
examples is an **example value, not a default** — changing it mid-stream makes cluster ids
incomparable across batches, silently.

## Platform CSV notes

- Descriptions are often a **single glued template line**; distill splits on 预期结果 / 实际结果 / 操作步骤 even without newlines.
- Empty template or「包括复现方法和现象描述等」→ `needs_info`.
- Title starting with `问题描述:` → `titleTag=_code_review`; fat clusters split on a title token.
- Field map SSOT: `agent1/bugfix_agent1/ingest/field_map.py` (includes platform typo `describle`).
