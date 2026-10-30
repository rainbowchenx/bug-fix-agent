# SWE 基准测试（本机）

流程分两段，互不耦合：

1. **推理（本仓 adapter）** → `predictions.jsonl`
2. **打分（官方 swebench harness + Docker）** → Resolved%

## 前置

| 项 | 说明 |
|----|------|
| 模型 | 根目录 `.env` 设置 `ANTHROPIC_API_KEY`（可选 `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL`） |
| 实例 | 官方 Lite 已落盘：`official-lite-300.jsonl`（全量 300）、`official-lite-50.jsonl`、`official-lite-20.jsonl`；烟雾集 `lite-smoke-10.jsonl` |
| 重新导出 | `$env:HF_ENDPOINT="https://hf-mirror.com"; npm run swe:export:official:all`（需 HuggingFace / 镜像） |
| 预拉仓库 | GitHub：`npm run swe:prefetch`；更稳：`npm run swe:prefetch:docker`（从官方评测镜像拷 `.git`）→ `eval/swe/cache/mirrors/`；批跑前 `$env:SWE_MIRROR_CACHE=(Resolve-Path eval/swe/cache/mirrors)` |
| 打分 | Docker + `pip install swebench`（Python 3.12 推荐）；每条实例首次会拉对应官方评测镜像 |

## 一键推理（烟雾 10 条）

在仓库根目录：

```powershell
# 1) 写入 .env 后：
npm run swe:baseline
```

等价于：

```powershell
npm run swe:batch -- `
  --instances eval/swe/data/lite-smoke-10.jsonl `
  --work-dir eval/swe/runs/baseline-smoke `
  --predictions eval/swe/runs/baseline-smoke/predictions.jsonl `
  --limit 10
```

产物：

- `eval/swe/runs/baseline-smoke/predictions.jsonl`
- `eval/swe/runs/baseline-smoke/swe-batch-summary.json`
- 每实例工作区在 `.../instances/<instance_id>/`

## 官方打分

```powershell
npm run swe:eval
```

或手动：

```powershell
py -3.12 -m swebench.harness.run_evaluation `
  --dataset_name princeton-nlp/SWE-bench_Lite `
  --predictions_path eval/swe/runs/baseline-smoke/predictions.jsonl `
  --max_workers 2 `
  --run_id bugfix-agent-smoke
```

## 注意

- Adapter 默认跳过 pip install；**最终数字以 Docker harness 为准**。
- 无 `ANTHROPIC_API_KEY` 时推理会在 analyze 阶段失败——先配模型再跑。
- `eval/swe/runs/` 建议 gitignore（体积大）。
