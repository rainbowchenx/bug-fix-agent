# P1 质量门禁波 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status:** Implemented (2026-10-15)

**Goal:** 在现有全自动双结局流水线上，降低无效 iterate、挡住坏编辑与低质量 MR：验证失败分类路由、静态检查门闩、只读 Reviewer、失败日志结构化回灌。

**Architecture:** 编排仍在 TypeScript（`src/runs/runner.ts`）；新增确定性分类器与静态检查；Reviewer 走 Claude Agent SDK **review（只读）** 模式；不引入 AskUser、不改日批无中断语义。聚合保持规则版。

**Tech Stack:** Node/TS、Vitest、Hono、`@anthropic-ai/claude-agent-sdk`

## Global Constraints

- 无 GREEN / Reviewer 不通过 → 不开 MR
- 环境类 verify 失败 → 直接 `unfixed`，不烧 implement 预算
- Reviewer 禁用 Edit；commit/push/MR 仍仅 Orchestrator
- 本波不做：LLM 聚合、多样本 N 选优、Dify OpenAPI、Storage 鉴权、GitLab CI pr_iteration、Electron E2E

## Tasks

- [x] Task 1: Verify Smart Routing（`verify-classify.ts`）
- [x] Task 2: 失败日志 snip（`log-snip.ts`）
- [x] Task 3: Static check（`static-check.ts`）
- [x] Task 4: 只读 Reviewer（`review.ts` + `skipReviewer`）
- [x] Task 5: 本文档 + README

## 验收

- [x] `npm test` 全绿
- [x] 环境类 verify 失败单次 implement
- [x] Reviewer `request_changes` 耗尽无 `mrUrl`
- [x] 无中间等人 API；聚合仍为规则版

## 延后

多样本选优、LLM 聚合、Dify OpenAPI、Storage 鉴权、GitLab CI pr_iteration、Electron E2E
