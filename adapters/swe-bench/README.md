# SWE-bench adapter（独立上层）

与核心 `src/` **解耦**：只通过 `runPipeline` + `ClusterHandlers` 注入 checkout / patch 交付 / verify 计划。  
核心代码里**没有** `instance_id`、SWE 类型或 predictions 格式。

```text
instances.jsonl  →  adapters/swe-bench  →  runPipeline(handlers)
                                              ↓
                                       predictions.jsonl
                                              ↓
                              (可选) swebench.harness.run_evaluation
```

## 跑子集基线

仓库内已备好实例与脚本，详见 [`eval/swe/README.md`](../../eval/swe/README.md)。

1. 根目录 `.env` 配置 `ANTHROPIC_API_KEY`（可选 `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL`）。
2. 烟雾 10 条：`npm run swe:baseline`  
   或 20 条：`npm run swe:baseline:20`（数据在 `eval/swe/data/`）。
3. 全量/更大子集（需 HuggingFace）：`npm run swe:fetch`
4. 官方 harness 打分：`npm run swe:eval`（需 Docker + `pip install swebench`）

手动等价：

```bash
npx tsx adapters/swe-bench/cli.ts \
  --instances eval/swe/data/lite-smoke-10.jsonl \
  --work-dir eval/swe/runs/baseline-smoke \
  --predictions eval/swe/runs/baseline-smoke/predictions.jsonl \
  --limit 10
```

## 行为说明

| 能力 | 实现位置 |
|------|----------|
| `base_commit` checkout | adapter `ensureRepo` handler |
| 跳过 GitLab，写 `model_patch` | adapter `deliverFix` handler |
| pytest 启发式（`python3`） | adapter `resolveVerifyPlan` / `map-instance` |
| 默认跳过 pip install | `skipInstall`：本地 `runVerify` 记为 deferred，**不以本机 pytest 当真绿**；加 `--install` 才跑真 verify |
| 跳过 reproduce | request `options.skipReproduce: true`（官方已有 FAIL_TO_PASS） |

公司内部缺陷可平行新增 `adapters/internal-bugs/`，复用同一 handlers 模式，互不污染。
