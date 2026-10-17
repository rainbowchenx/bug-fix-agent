# Phase A — 可信闭环 Implementation Plan

> 依据：[docs/superpowers/specs/2026-10-17-implementation-gap-analysis-and-roadmap.md](../specs/2026-10-17-implementation-gap-analysis-and-roadmap.md) §7 Phase A  
> **Status:** Implemented (2026-10-17)

**Goal:** 真实仓库上 clone → analyze → implement → static → verify → review → deliver 能稳定跑通；同仓多簇互不污染；零改动不开 MR；解析失败只拖垮本簇。

## 默认决策

- 工作区隔离：`git worktree`（共享 mirror + 每簇独立工作树）
- Skills：`skills/.claude-plugin/plugin.json` + 运行时挂载到 worktree `.claude/skills`，接通 SDK `skills` / `settingSources`
- Token：`http.extraHeader` / 不写进 clone URL 持久化

## Tasks（完成勾选）

- [x] **A8** 解析健壮性 — `json-extract.ts` 平衡括号；review 重试；簇级 `review_failed`
- [x] **A1** worktree 隔离 + `baseSha` — `workspace/git.ts`、`paths.ts`
- [x] **A2** 真实 `changedFiles` + `no_changes` 门禁 — implement / deliver
- [x] **A3** exec/SDK 超时 + `CI=1` — `util/exec.ts`、`config.ts`
- [x] **A4** pnpm/yarn/npm 探测 — `profiles/detect.ts`
- [x] **A5** Skills 挂载 + enabled/disabled — `skills/manifest.ts`、`sdk-runner.ts`
- [x] **A6** Reviewer 喂 diff — Orchestrator `getDiffText` → review prompt
- [x] **A7** Deliver 加固 — git identity、MR body、Draft、ssh path、token header
- [x] **A9** 最小 e2e — `test/e2e/bare-remote.test.ts`
- [x] **A10** CLI `run` — 同步批跑，全 fixed 退出 0 否则 1

## 验收

- [x] `npm test` 含 A8/A4/A9 与双引擎 parity
- [x] 阻断级 GAP-A1…A8 有单测或 e2e 覆盖
- [x] CLI `run --work-dir --defects` 可用

## 本波不做（Phase B+）

基线差分、复现测试优先、Localization/Repo Map、报告扩展、MCP 白名单对齐、LLM 聚合、Storage、Dify OpenAPI、引擎收敛、多样本选优
