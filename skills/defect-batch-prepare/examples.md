# Examples

## Preloaded JSON

```json
{
  "productLine": "demo",
  "defects": [
    {
      "defectId": "1",
      "title": "【预览】进度条应显示在底部",
      "description": "预期结果：进度条应显示在预览画面底部\n实际结果：显示到顶部遮挡",
      "status": "Open",
      "testModule": "预览"
    }
  ]
}
```

```ts
const batch = await runDefectBatchPrepare({
  mode: "preloaded",
  productLine: "demo",
  posture: "beta",
  source: "./raw-defects.json",
});
console.log(batch.funnel, batch.clusters.length);
```

## Excel export (from zip demos)

```bash
# unzip docs/业务缺陷分析.zip then:
python3 skills/defect-batch-prepare/scripts/xlsx_to_raw_defects.py \
  --xlsx /tmp/biz-defect/缺陷列表demo/hc-bug-1029/hc1.xlsx \
  --sheet 缺陷列表 \
  --product-line hc \
  --out /tmp/hc-raw.json

npx tsx -e '
import { runDefectBatchPrepare } from "./src/defect-batch/index.ts";
(async () => {
  const batch = await runDefectBatchPrepare({
    mode: "preloaded",
    productLine: "hc",
    posture: "alpha",
    source: "/tmp/hc-raw.json",
  });
  console.log(JSON.stringify(batch.funnel, null, 2));
})();
'
```

