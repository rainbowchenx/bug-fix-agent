# Phase B — 修复真值与报告质量

> 依据：`docs/superpowers/specs/2026-10-17-implementation-gap-analysis-and-roadmap.md` §7 Phase B  
> **Status:** Implemented (2026-10-18)

**Goal:** `fixed[]` 能区分基线红与新增失败，并带上复现级别与可审计字段。

## Tasks

- [x] **B1** prepare 后记录 `baseline.json`；门禁只阻断新增失败签名；基线红标记 `baselineRed`
- [x] **B2** implement 增加 `Write`；先写复现测试再修复；`verifyLevel` 为 `reproduced` | `regression_only`（后者默认 Draft MR）
- [x] **B3** `localization.json` + 轻量 repo map 注入 analyze；空 `target_files` 时用 `editTargets`
- [x] **B4** 报告增加 `baseSha`、`branch`、`profileId`、`iterations`、`verify.exitCode`、`durationMs`、`skillsInvoked`、`mcpToolsInvoked`、`verifyLevel`、`baselineRed`，以及 run 级 `startedAt` / `finishedAt` / `engine`
- [x] **B5** MCP `{ enabled, servers, allowedTools, deniedTools, mode }`；stdio 命令白名单；`required` 不通过则本簇 `prepare_failed`；analyze 拒绝写类工具
- [x] **B6** 指纹含顶层应用栈帧；同仓同文件再合并；簇大小上限 5。LLM 同根因判定仍为可选项，本波用规则
- [x] **B7** Skills 补齐适用/不适用/步骤/反例/案例；新增 `reproduction-test`、`monorepo-workspace`、`electron-process-boundary`、`gitlab-mr-hygiene`；按 profile 暴露

## 验收

- [x] `npm test` 全绿（含双引擎 parity）
- [x] 原有相同 lint 签名不再误杀；新增失败仍阻断
