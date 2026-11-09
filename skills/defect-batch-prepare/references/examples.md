# Examples

Commands are written `agent1 <subcommand>`. In this packaged skill that is
`scripts\agent1.exe <subcommand>`; in a repo checkout it is
`python skills/defect-batch-prepare/scripts/agent1.py <subcommand>`, or
`bugfix-agent <subcommand>` when the package is installed. Flags are identical.

## CSV export → batch → intent review

```bash
agent1 prepare-batch \
  --product-line hc \
  --source 缺陷拉取/脱敏/export.csv \
  --posture beta \
  --out defect-batch.json

agent1 apply-review \
  --batch defect-batch.json \
  --overrides review.json \
  --out defect-batch.json
```

`review.json` lists only adjustments. Do not include hard-reject / security / excluded / duplicate tickets. Promoting into `strict` needs `expectQuality`.

## Excel export

```bash
agent1 xlsx-to-raw \
  --xlsx path/to/缺陷列表.xlsx \
  --product-line hc \
  --out raw-defects.json
```

Then `agent1 prepare-batch --source raw-defects.json`. Spreadsheets drop rows in ways CSVs do not
(merged cells, blank IDs, a second worksheet), so count again.

## Historical batch

`--posture alpha` keeps closed tickets in the functional funnel — use it to see how a past export
*would* have been sorted, not to decide today's queue.

```bash
agent1 prepare-batch --product-line hc --source old.csv --posture alpha --out historical.json
```

## Python API (repo checkout only)

The executable exposes no Python API. From a checkout with the package installed:

```python
from bugfix_agent import run_defect_batch_prepare

batch = run_defect_batch_prepare(product_line="demo", posture="beta", source="./raw-defects.json")
print(batch.funnel, len(batch.clusters))
```
