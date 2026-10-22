# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

`bugfix-agent`：本地双结局 BugFix Agent（npm 包）。Dify 一次提交缺陷整表 + `workDir`，全自动跑完产出汇总报告——可修开 GitLab MR，不可修写全原因；无中间等人断点。核心硬门禁：**没有 GREEN，就没有 MR**（验证不通过记入 `unfixed`，绝不交付红灯代码）。

设计文档（改架构前必读）：
- `docs/superpowers/specs/2026-10-14-local-bugfix-agent-design.md` — 已固化的设计
- `docs/superpowers/plans/2026-10-14-local-bugfix-agent-mvp.md` — MVP 实现计划
- `docs/research/` — Sentry Seer 深潜与 SOTA 调研（很多设计决策对标 Seer 的 `stopping_point`，本产品明确**不做**人机协作断点）

## 常用命令

```bash
npm test                    # vitest run（全部测试）
npx vitest run test/unit/aggregate.test.ts        # 单个测试文件
npx vitest run -t "partial name"                  # 按名称过滤
npm run build               # tsup → dist/（ESM, node20, dts）
npm run dev:serve           # tsx src/cli.ts serve（本地起 HTTP 服务）
npm pack --dry-run          # 验证发布内容应含 dist/ + skills/
```

- TypeScript 5.8，ESM only，Node ≥ 20。无 ESLint/Prettier 配置——风格靠 `tsconfig.json` 与现有代码约定。
- 测试用 Vitest（node 环境），集成测试在 `test/integration/`，其余单测在 `test/unit/`。Pipeline 各阶段函数均接受可注入的 `execFn` / handlers，测试以此 mock。

## 架构

一次 Run 的主流水线（`src/runs/runner.ts` 编排）：

```
POST /v1/runs → createRun（落盘 {workDir}/.bugfix-runs/{runId}/）→ enqueueRun（setImmediate 异步）
  normalize（normalize.ts）→ aggregate（rule-based 缺陷聚合成簇）→ 每簇：
    analyze（analyze.ts，不可修 → unfixed 记录，跳过后续）
    → prepare（装依赖）→ implement（调 Claude Agent SDK 改码）→ verify（GREEN 门禁）
    → iterate（shouldContinueIterate 控制预算，默认 maxIterate=3）→ deliver（push + 开 GitLab MR）
  → buildReport（双结局：fixed[] + unfixed[]，含 reasonCode）
```

关键模块：

- **`src/http/app.ts`** — Hono 应用，仅绑定 `127.0.0.1`，`POST /v1/runs`（202）+ `GET /v1/runs/:runId` 轮询。
- **`src/runs/`** — `create-run.ts`（ID/落盘）、`runner.ts`（编排，`ClusterHandlers` 可注入用于测试）、`store.ts`（文件系统 run 状态，JSON 读写 + `updateRunMeta`）。
- **`src/pipeline/`** — 纯逻辑阶段，互相之间通过 `src/types.ts` 的 artifact 类型传递（`RootCauseArtifact`、`SolutionArtifact`、`VerifyPlan` 等）。`verify.ts` 自动探测验证命令，可被请求的 `verifyOverrides` 覆盖。
- **`src/agent/sdk-runner.ts`** — 包装 `@anthropic-ai/claude-agent-sdk`，启动时只注入 `skills/` 目录元数据，模型按需选择性调用；`src/agent/artifacts.ts` 用 zod 校验 SDK 产出的结构化 artifact。
- **`src/profiles/`** — Stack Profile（node-web / node-lib / electron），`detect.ts` 自动识别目标仓库类型，决定 install/verify 命令。可扩展新 profile。
- **`src/skills/manifest.ts`** — 内置 skills（仓库根 `skills/`，随包发布）的清单加载。
- **`src/mcp/load-config.ts`** — Run 级与本机 MCP 配置合并。
- **`src/gitlab/client.ts`** — push + 创建 MR（不自动 merge）。Token 走环境变量 `GITLAB_TOKEN`，绝不让模型自由 Bash 执行 git push。
- **`src/storage/`** — 可选 `StorageAdapter`（noop / HTTP stub），`best_effort` 同步远程，失败不挡本地 MR。Agent 自身不做业务库。
- **`src/workspace/git.ts`** — clone/工作副本管理；`paths.ts` — run 目录布局。

## 设计约束（改动时必须保持）

- **全自动无断点**：不在 analyze/plan 后等人；可修冲到开 MR，不可修产出完整 unfixed 说明（`reasonCode` + `reasonDetail`）。
- **一簇缺陷 → 一个 MR**；聚合是 rule-based（`aggregate.ts` + `normalize.ts`），不调模型。
- **状态默认落本地文件系统**（`{workDir}/.bugfix-runs/`）；远程存储是可选旁路。
- **凭据只走环境变量**（`.env.example`），不进缺陷正文、不进 Excel。
- 修复类工作遵循 `skills/minimal-diff`、`skills/systematic-debugging` 等内置 skill 的精神：最小 diff、验证驱动。
