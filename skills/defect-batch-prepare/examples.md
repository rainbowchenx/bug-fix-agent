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

## Full three-agent run

```bash
pip install -e ".[dev]"
bugfix-agent run \
  --work-dir /path/to/repos \
  --product-line hc \
  --source raw-defects.json \
  --posture alpha \
  --out-dir /tmp/artifacts
```

## Platform CSV（缺陷拉取）

```bash
bugfix-agent prepare-batch \
  --product-line sample \
  --source 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.csv \
  --posture beta \
  --out /tmp/defect-batch.json
```

## Excel export

```bash
python3 bugfix_agent/scripts/xlsx_to_raw_defects.py \
  --xlsx /tmp/biz-defect/缺陷列表demo/hc1.xlsx \
  --product-line hc \
  --out /tmp/hc-raw.json
```
