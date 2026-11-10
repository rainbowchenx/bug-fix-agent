---
name: defect-batch-prepare
description: Turns an exported defect list (平台 CSV / Excel / JSON) into a validated defect-batch.json by running the rule funnel in code, then rereading the original ticket text to correct intent and match-pool placement. Use this skill whenever the user asks to 筛选, 分簇, 分类, 复核, or 整理缺陷单; convert a 缺陷列表 or 平台导出; run prepare-batch; build or validate defect-batch; or check whether tickets landed in the right pool or intent — even if they never name this skill, never say "defect-batch", and just paste a CSV path and ask 帮我看下这批缺陷.
compatibility: Needs only the bundled `agent1` CLI — the packaged `scripts/agent1.exe` runs on Windows with no Python, no pip and no network. Python source is not shipped; the executable is the interface. In a repo checkout the same subcommands are served by `bugfix-agent`.
metadata:
  profiles: defect-batch
---

# Defect Batch Prepare

Turn an exported defect list into a validated `defect-batch.json`.

Screening and the L1/L2 grouping keys run in code, so the same export always yields the same funnel. Ticket prose is too irregular for those rules, so after the script finishes you reread the original text and correct intent and match-pool mistakes.

```text
export → preflight → prepare-batch → defect-batch.json
       → reread originals → review.json → apply-review → defect-batch.json
```

## Invoking `agent1`

Every command below is written `agent1 <subcommand>`. Pick the form that exists on your machine —
they take identical flags and produce identical bytes:

| Where | Invoke as |
|---|---|
| This packaged skill | `scripts\agent1.exe <subcommand>` |
| Repo checkout / installed package | `bugfix-agent <subcommand>` |

Subcommands: `preflight` · `prepare-batch` · `apply-review` · `validate` · `xlsx-to-raw` · `self-check`.

`agent1 --help` lists them; `agent1 self-check` prints the committed source revision the
executable was built from, which is what you quote when a result is questioned.

## Why the split exists

The funnel has to be reproducible. If two people run the same export they must get the same pools, otherwise nobody can argue about a ticket's fate. That is why R0–R3 and L1/L2 live in `agent1/bugfix_agent1/defect_batch/*` and you must not re-derive them in chat — a one-off rewrite drifts from the contract, and the next run will disagree with yours.

Intent (L3) is the opposite problem: it needs to understand what a human meant by 「按钮偏了」, which keyword matching cannot do. So L3 starts as a heuristic and you are the correction layer.

## Step 0 — Preflight before trusting anything

Run this first, every time:

```bash
agent1 preflight --source path/to/export.csv
```

The **first line is the build identity** — `build : <commit> · vendor N files · frozen|dev`. Quote it in the hand-off when a result is questioned; without it nobody can tell two runs apart from the log, and "which version produced this" has cost real re-runs.

It then prints the source row count, which column fed each contract field, which columns it could not place, how many descriptions are unfilled templates, whether the module column mapped, and what share of those modules carry no product semantics.

Read the output before running the funnel:

- **rows mappable < rows in file** → an ID or title column spelling is unknown. Fix the mapping first; see [references/column-aliases.md](references/column-aliases.md).
- **testModule MISS** → every cluster collapses into `_unmoduled` and the L1 dimension is dead. Say so, and say that clustering quality is limited by the export rather than by the analysis.
- **testModule semantic-free ≥ 30%** → the column is present, so the funnel will look healthy, but those are case-set / 【公共】/ checklist names, not code areas. Expect mostly singleton clusters; say the cluster view is of limited value instead of presenting it as a grouping.
- **description is an unfilled template** → for those tickets there is nothing to name. They belong in `needs_info`; do not fabricate intent for them.

The failure this prevents is silent: an unrecognised ID column used to make `prepare-batch` return `{"ok": true, "tickets": 0}`. `ok: true` means the rules ran, not that the data was read. It now raises instead, but preflight tells you *which column* before you get there.

## Step 1 — Rule funnel

```bash
agent1 prepare-batch \
  --source path/to/export.csv \
  --out defect-batch.json
```

**Nothing here needs asking.** Both optional flags resolve deterministically; pass them only to override.

`--product-line` is a **batch namespace**, not a column in the export and not a repo type — repo type
is Agent-2's `cartographyProfile`, unrelated. It becomes the `clusterId` prefix, so the only
requirement is that it stays stable across batches of the same project. Omitted, it resolves in
this order: `--product-line` → `BUGFIX_PRODUCT_LINE` → `productLine` inside raw-defects → the
project code in the source file name (`PJ01PM20260711040-….csv`) → else `unspecified` with a
stderr warning. The resolved value and its provenance print as
`productLine: <value> (via filename)` — quote that line when a cluster id looks odd.

`--posture` defaults to `beta` and should stay there: resolved / closed tickets are not ours to
work on, so `beta` gates them into `excluded`. Pass `alpha` only when the ask is explicitly
"replay history and show where closed tickets would have landed" — never to build a fix queue,
because closed tickets carry the resolver and root cause. On an all-`Open`/`New` export (the
usual daily export) `alpha` and `beta` produce identical tickets and only the `posture` field
differs, so there is nothing to decide.

Cluster size has a **ceiling**: a group holding more than 25% of the `strict` tickets (and more than 4 tickets) is re-split by title token. So on a small batch the shape is forced — with 4 strict tickets a cluster of 3 is 75%, above the line, and the earlier behaviour split it into 4 singletons. Do not read a wall of singleton clusters as "the grouping failed": say the batch is small, quote the ceilings, and move on. Conversely, do not expect tickets you just gave the same intent to merge — they only merge if the group stays under the threshold.

**Check the count before you read the pools.** `tickets` must equal the source row count from preflight. If it does not, say how many rows were dropped and why — never report a funnel built on a partial read, because the percentage breakdown looks perfectly healthy either way.

Pool meanings, posture behaviour and platform quirks: [references/reference.md](references/reference.md).

For `.xlsx`, convert first — the executable carries `openpyxl` itself, nothing to install:

```bash
agent1 xlsx-to-raw \
  --xlsx path/to/export.xlsx --out raw-defects.json
```

Then run `prepare-batch --source raw-defects.json` and count again — spreadsheets drop rows in ways CSVs do not (merged cells, blank IDs, a second worksheet).

mcp/crawler ingest is still stubbed; use a preloaded file.

## Step 2 — Intent review

Save the rule output before you touch anything, as `defect-batch.rules-snapshot.json` — the name is fixed so the downstream step can find it without asking (three runs named it three different things, and a glob found nothing).

The batch drops the long `description` on purpose: keeping it makes the artifact unreadable at a glance. But that means the JSON carries only `observed` / `expected` / `steps`, and when the template did not parse those are empty for reasons that have nothing to do with the reporter.

So reread the original export next to the distilled fields. Treat `unclear`, low confidence, `locatable_only` and `needs_info` as *suspicions*, not conclusions: they often mean "the template did not parse", not "the reporter said nothing".

For every ticket you change, be able to state: what the reporter actually meant → which closed intent that is → whether it still belongs in the current pool.

Closed intent set: `ui_layout` · `i18n` · `logic` · `data_wrong` · `perf` · `compat` · `config` · `security_scan` · `crash` · `unclear`

Safe to change: `intent` (which sets `intentSource` to `ai`) and `pool` among `strict` / `locatable_only` / `needs_info`. Promoting into `strict` requires `expectQuality` of `explicit` or `inferred` — a ticket with no checkable expected result cannot be clustered for code localization however clear its intent is.

**Give the intent too when you promote.** `apply-review` accepts a pool change with no intent, but the ticket then lands in an `::unclear` cluster and the grouping you just fixed is wasted.

Leave `hard_reject` / `security` / `excluded` / `duplicate` alone in both directions. Those are safety and status gates, not language judgements — a CVE ticket you "rescue" into `strict` because its prose reads like a normal bug is exactly the failure that boundary exists to prevent.

Leave `testModule` / `titleTag` alone *in the batch* — do not hand-edit them, and never derive a module from `所属模块`-style fields by rewriting a ticket. Fixing the source column mapping upstream is a different thing and is encouraged; that is what preflight is for. Do not hand-edit `clusterId` / `clusters[]` / `funnel` either; `apply-review` rebuilds them so the file still validates.

Write only the tickets you are changing:

```json
{
  "adjustments": [
    {
      "defectId": "PJ-123",
      "intent": "ui_layout",
      "intentConfidence": "high",
      "intentRationale": "标题与实际结果都是按钮偏移/遮挡，不是逻辑错误",
      "pool": "strict",
      "expectQuality": "inferred"
    }
  ]
}
```

```bash
agent1 apply-review \
  --batch defect-batch.json \
  --overrides review.json \
  --out defect-batch.json
```

If nothing should change, skip `apply-review` and hand off the rule output, saying why nothing needed changing. An empty `adjustments` list is a legitimate result; inventing edits to look busy corrupts a file the rules already got right.

## Step 3 — Hand off honestly

Report: total tickets, the funnel, how many tickets you changed and in which direction, and the final file path. If the batch is materially degraded — most modules unknown, most descriptions empty, a large share still `unclear` — say that in the same breath. The next step (code localization) inherits whatever you paper over, and it cannot tell a real `unclear` from one you created.

**Quote numbers, do not count them.** `prepare-batch` and `apply-review` both print a `clusters` object (`total` / `singleton` / `largest`) next to the funnel. Copy those figures; hand-counting cluster or singleton totals is where wrong numbers in hand-off reports come from. The same goes for naming a rule: if you say why a heuristic label was wrong, describe the symptom you saw, do not guess at the keyword rule behind it.

`apply-review` also prints a `review` block that sorts your own edits by where they came from:

```text
"review": {"changedIntent": 36, "fromUnclear": 18, "fromHeuristic": 18,
           "fromNone": 0, "keptHeuristic": 8, "changedPool": 0}
```

`fromUnclear` is filling a gap, `fromHeuristic` is correcting a guess — report them as two numbers, never one. A run where these were merged claimed "36 tickets rescued from unclear, 3 heuristic misjudgments" when the truth was 18 + 18. `changedPool` counts pool moves separately because "I changed 40 tickets" hides whether any of them changed bucket.

Before handing off, run `agent1 validate --batch <file>`. It re-checks the JSON against the contract and prints the same summary; exit code 2 with an `error` field means the artifact is broken and must not be passed on.

Command variants: [references/examples.md](references/examples.md). Output artifact shape:
`references/defect-batch-guide.md` (repo: `docs/contracts/v0.1/defect-batch-guide.md`).
