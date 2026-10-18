---
name: minimal-diff
description: Use when implementing fixes — keep patches tiny, local, and within scope lock (solution target_files only).
---

# Minimal Diff + Scope Lock

- Change only what is required for the evidenced root cause.
- **Scope lock:** edit only files listed in the solution `target_files` (or named in solution steps). Do not touch unrelated modules.
- Avoid drive-by refactors, renames, and formatting churn.
- Prefer fixing call sites / guards over rewriting modules.
- Prefer fixing product code over weakening tests (unless the assertion is clearly wrong).
- Do not add dependencies unless essential.

## 适用
任何 implement 阶段。

## 不适用
需要迁移 API 的大版本升级。

## 步骤
1. 只改 `target_files`。
2. 复现测试可以加在同目录 `*.test.*`。
3. 不顺手格式化无关代码。

## 反例
修空指针时重排整个模块的 import。

## 案例
`src/sum.js` 把 `-` 改成 `+`，测试放在 `test/sum.test.js`，不动 `package.json`。
