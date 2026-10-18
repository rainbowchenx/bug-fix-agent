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

1. 准备实例文件（官方 Lite/Verified 导出或自截 20 条），需字段：`instance_id`、`repo`、`base_commit`、`problem_statement`；建议含 `FAIL_TO_PASS`。
2. 配置模型：`ANTHROPIC_API_KEY`（及可选 `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL`）。
3. 批跑：

```bash
npx tsx adapters/swe-bench/cli.ts \
  --instances D:/data/swe-lite-20.jsonl \
  --work-dir D:/eval/swe-run1 \
  --predictions D:/eval/swe-run1/predictions.jsonl \
  --limit 20
```

4. 用官方 harness 打分（本 adapter **不**内嵌 Docker 评测）：

```bash
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --predictions_path D:/eval/swe-run1/predictions.jsonl \
  --max_workers 4 \
  --run_id bugfix-agent-smoke
```

## 行为说明

| 能力 | 实现位置 |
|------|----------|
| `base_commit` checkout | adapter `ensureRepo` handler |
| 跳过 GitLab，写 `model_patch` | adapter `deliverFix` handler |
| pytest 启发式 | adapter `resolveVerifyPlan`（可用 request 的 `verifyOverrides`） |
| 默认跳过 pip install | `skipInstall`（加 `--install` 才走 prepare；完整依赖仍建议官方镜像评测） |

公司内部缺陷可平行新增 `adapters/internal-bugs/`，复用同一 handlers 模式，互不污染。
