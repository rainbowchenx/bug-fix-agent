---
name: reproduction-test
description: Use on the reproduce phase — add a minimal failing test before fixing product code.
---

# Reproduction Test

## 适用
implement 的 reproduce 阶段：只写会失败的测试。

## 不适用
仓库无法跑测试（环境缺依赖）时不要伪造 GREEN。

## 步骤
1. 在 `target_files` 同包新增 `*.test.*` / `*.spec.*`。
2. 断言当前缺陷行为，让测试先 RED。
3. 不要在这一步修改产品代码。

## 反例
一边加测试一边把 bug 修掉，导致无法证明复现。

## 案例
`sum(2, 3)` 期望 5 但实现是减法：先提交失败断言，再在下一步把运算符改为加。
