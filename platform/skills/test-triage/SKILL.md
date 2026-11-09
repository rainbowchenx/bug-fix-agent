---
name: test-triage
description: Use when choosing or interpreting verify commands and failing test output.
---

# Test Triage

- Prefer existing project scripts (`npm test`, vitest, jest).
- Read failure tail carefully; distinguish product bug vs flaky env.
- When iterating, feed the exact failing assertion back into the next edit.
- Never claim GREEN without a real command succeeding.

## 适用
verify 失败后的下一轮 implement。

## 不适用
基线里已经存在、且签名没变的 lint/测试失败（由 Orchestrator 基线差分处理）。

## 步骤
1. 看失败是环境、flaky、断言还是产品代码。
2. 环境类停止空烧迭代。
3. 把断言原文写回下一轮 prompt。

## 反例
把 `Cannot find module` 当成产品 bug 反复改业务代码。

## 案例
`AssertionError: expected 1 to be 2` 只修对应断言所在函数，不重装依赖。
