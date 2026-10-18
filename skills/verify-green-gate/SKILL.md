---
name: verify-green-gate
description: Use before delivery — no MR without a passing verify command.
---

# Verify Green Gate

Hard rule for this product: **no GREEN, no MR**.

- If no test command exists → stop with `no_test_command`.
- If verify fails after iterate budget → `verify_failed` with log tail.
- Do not open MRs based on model self-assessment alone.
- 基线已红且没有新增失败时，报告 `baselineRed`，不要把旧错误当成这次回归。

## 适用
deliver 之前。

## 不适用
没有 test 命令时（应 `no_test_command`）。

## 步骤
先看基线，再看修复后的 verify。

## 反例
模型自称已修好就开 MR。

## 案例
基线 `TS2322` 仍在、没有新错误：不因此 `static_check_failed`。新增 `TS2339` 则阻断。
