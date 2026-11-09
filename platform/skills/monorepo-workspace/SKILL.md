---
name: monorepo-workspace
description: Use when the repo has workspaces or pnpm-workspace — install and test the package that owns the defect.
---

# Monorepo Workspace

## 适用
pnpm/yarn/npm workspaces，缺陷路径落在某个子包。

## 不适用
单包仓库。

## 步骤
1. 看 lockfile 与 `packageManager` 选 pnpm / yarn / npm。
2. 用缺陷路径或 `package: name` 选定子包。
3. 在该包运行 test，而不是只跑根脚本却测错包。

## 反例
在 pnpm 仓执行 `npm install` 生成第二份 lockfile。

## 案例
缺陷在 `packages/web/src/Login.vue`：验证命令针对 `packages/web` 的 test 脚本。
