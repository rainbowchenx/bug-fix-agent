# Examples

## Preloaded JSON

```python
from bugfix_agent import run_defect_batch_prepare

batch = run_defect_batch_prepare(
    product_line="demo",
    posture="beta",
    source="./raw-defects.json",
)
print(batch.funnel, len(batch.clusters))
```

## CSV export → batch → intent review

```bash
bugfix-agent prepare-batch \
  --product-line hc \
  --source 缺陷拉取/脱敏/export.csv \
  --posture beta \
  --out defect-batch.json

bugfix-agent apply-review \
  --batch defect-batch.json \
  --overrides review.json \
  --out defect-batch.json
```

`review.json` lists only adjustments. Do not include hard-reject / security / excluded / duplicate tickets. Promoting into `strict` needs `expectQuality`.

## Excel export

Run from this skill directory (or pass the skill-relative path):

```bash
python scripts/xlsx_to_raw_defects.py \
  --xlsx path/to/缺陷列表.xlsx \
  --product-line hc \
  --out raw-defects.json
```
