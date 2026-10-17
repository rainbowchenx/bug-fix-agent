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
bugfix-agent version
bugfix-agent --help
```

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

## 现状与路线

当前实现相对设计规格的差距、理论效果评估、阻断级问题清单与 Phase A–D 后续安排见 [docs/superpowers/specs/2026-10-17-implementation-gap-analysis-and-roadmap.md](docs/superpowers/specs/2026-10-17-implementation-gap-analysis-and-roadmap.md)。在 Phase A 完成前，请勿将其用于真实日批。

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
