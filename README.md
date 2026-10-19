# bugfix-agent

本地双结局 BugFix Agent（npm 包）：Dify / `curl` 一次提交缺陷整表 + `workDir`，全自动跑完后产出汇总报告——**可修开 GitLab MR**，**不可修写全原因**；无中间等人断点。

## 安装

```bash
npm i -g bugfix-agent
# 或
npx bugfix-agent serve --port 8787
```

**重要：** 依赖 `@anthropic-ai/claude-agent-sdk` 的 **optional 平台二进制**，安装时**不要**使用 `npm i --omit=optional`。

Node.js ≥ 20。

## 环境变量

见 `.env.example`：

| 变量 | 说明 |
|------|------|
| `PORT` | HTTP 端口，默认 `8787` |
| `ANTHROPIC_API_KEY` | Claude Agent SDK |
| `ANTHROPIC_BASE_URL` | 可选代理/网关 |
| `ANTHROPIC_MODEL` | 可选模型覆盖 |
| `GITLAB_TOKEN` | 推送与创建 MR |
| `GITLAB_HOST` | 默认 `https://gitlab.com` |

## CLI

```bash
bugfix-agent serve --port 8787
bugfix-agent run --work-dir D:/batch/today --defects defects.json [--engine pipeline|langgraph]
bugfix-agent version
bugfix-agent --help
```

`run` 同步等待整批结束并打印报告：全部 fixed 退出码 `0`，否则 `1`。

服务仅绑定 `127.0.0.1`，供本机 Dify Custom Tool / HTTP 节点调用。

## HTTP API

### `POST /v1/runs` → `202 { runId }`

```json
{
  "workDir": "D:/batch/today",
  "userPrompt": "verify: `npm test`",
  "defects": [
    {
      "id": "1",
      "title": "Null crash on login",
      "repoUrl": "https://gitlab.com/org/app.git",
      "fingerprint": "login-null",
      "stackTrace": "..."
    }
  ],
  "options": {
    "maxIterate": 3,
    "verifyOverrides": { "test": ["npm test"] },
    "skipReviewer": false
  }
}
```

### `GET /v1/runs/:runId?workDir=`

返回 `status`、`progress`；完成后含 `report`。

### 报告结构（双结局）

```json
{
  "runId": "...",
  "summary": { "totalClusters": 2, "fixed": 1, "unfixed": 1 },
  "fixed": [{ "clusterId": "...", "defectIds": [], "mrUrl": "...", "rootCauseSummary": "..." }],
  "unfixed": [{ "clusterId": "...", "reasonCode": "not_actionable", "reasonDetail": "..." }]
}
```

硬门禁：**没有 GREEN，就没有 MR**。

### 质量门禁（P1）

簇在 GREEN→MR 前经过：

1. **Implement** → **Static check**（探测到的 `typecheck`/`lint`/`tsc --noEmit`；无则跳过）
2. **Verify**（仓库测试）
3. **Smart Routing**：verify 失败时启发式分类  
   - `environment` / `flaky` / `bad_assertion` → 立即 `unfixed`（`env_verify_failed` 等），不空烧 iterate  
   - `product_code` / `unknown` → 允许回灌 snip 后的日志再 implement  
4. **只读 Reviewer**（默认开；`options.skipReviewer: true` 可关）→ `request_changes` 计入同一 `maxIterate`；耗尽 → `review_failed`，**不开 MR**

相关 `reasonCode`：`env_verify_failed`、`static_check_failed`、`review_failed`、`verify_failed`。

## 日批用法（Dify）

1. Dify 校验并解析 Excel → `defects[]`，选定本机 `workDir`。
2. 本机先起 `bugfix-agent serve`（或前序 shell 节点拉起）。
3. HTTP 节点 `POST /v1/runs`，轮询 `GET` 直到 `completed`。
4. 把 `report.fixed` / `report.unfixed` 展示或转发通知。

Agent **自身不做业务库**；状态默认落在 `{workDir}/.bugfix-runs/{runId}/`。可选 `StorageAdapter`（noop / HTTP stub）把进度/报告同步到远程（`best_effort` 失败不挡本地 MR）。

## 与 Sentry Seer 的差异

| Seer | 本产品 |
|------|--------|
| `stopping_point` 人机协作断点 | **全自动**，无「根因后等人」 |
| 可修路径可停在方案/改码 | 可修默认冲到 **开 MR** |
| 不可修 | 同样产出 **完整 unfixed 说明** |

## 编排引擎（pipeline / LangGraph）

`options.engine` 可选 `"pipeline"`（默认，原命令式循环）或 `"langgraph"`（`@langchain/langgraph` StateGraph）。两者底层都使用 Claude Agent SDK，产出与报告结构一致。仓库自带 `langgraph.json`，可直接 `npx @langchain/langgraph-cli dev` 在 LangGraph Server / Studio 中运行图 `bugfix`。详见 [docs/langgraph.md](docs/langgraph.md)。

## 当前限制（Phase B 完成后）

Phase A 可信闭环与 Phase B 修复真值已落地。计划：[Phase A](docs/superpowers/plans/2026-10-17-phase-a-trusted-loop.md)、[Phase B](docs/superpowers/plans/2026-10-18-phase-b-fix-truth.md)。

簇报告可带 `baseSha`、`profileId`、`iterations`、`verifyLevel`（`reproduced` | `regression_only`）、`baselineRed`、`skillsInvoked`。基线里已经存在的失败签名不会单独阻断；写不出 RED 复现时 MR 默认为 Draft。

仍建议知晓：

| 限制 | 说明 |
|------|------|
| 默认串行 | `options.concurrency` 还未做跨仓并行 |
| 包管理器 | 复杂 monorepo 只做最小 workspace 选择 |
| `scripts.test` | 无 test 命令 → `no_test_command`，不开 MR |
| GET 轮询 | HTTP `GET /v1/runs/:id` 仍需带 `workDir` |
| 聚合 | 同文件合并与簇大小上限是规则；没有 LLM 同根因判定 |
| Phase C+ | Storage、取消/恢复、`.bugfix.yml`、Dify OpenAPI、引擎收敛尚未做 |

差距分析与后续 Phase C–D：[implementation-gap-analysis-and-roadmap](docs/superpowers/specs/2026-10-17-implementation-gap-analysis-and-roadmap.md)。

## SWE-bench 适配（独立上层）

公开榜评测不塞进核心：`adapters/swe-bench/` 只通过 `handlers` 注入 checkout / patch 交付，导出 `predictions.jsonl` 后再用官方 harness 打分。

```bash
# .env 配好 ANTHROPIC_API_KEY 后
npm run swe:baseline      # 烟雾 10 条 → predictions
npm run swe:baseline:20   # 20 条
npm run swe:eval          # Docker 官方 harness 打分（需 swebench）
```

详见 [eval/swe/README.md](eval/swe/README.md)、[adapters/swe-bench/README.md](adapters/swe-bench/README.md)。

## 库 API

```ts
import { createApp, startRun, loadConfig, startServer } from "bugfix-agent";
import { createBugfixGraph, invokeBugfixGraph } from "bugfix-agent/graph";
import { graph } from "bugfix-agent/langgraph"; // 已编译图，供 LangGraph Server 引用
```

## 开发

```bash
npm test
npm run build
npm pack --dry-run   # 应含 dist/ + skills/
```

## License

MIT
