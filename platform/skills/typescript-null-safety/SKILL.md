---
name: typescript-null-safety
description: Use for TypeScript null/undefined crashes and unsafe optional chaining gaps.
---

# TypeScript Null Safety

- Prefer narrowing (`if (!x) return`) over non-null assertions (`!`).
- Fix types at the source when data can legitimately be missing.
- Avoid `as any` unless bridging an external untyped boundary.

## 适用
TS 空值崩溃、`TS2322`/`TS2532`。

## 不适用
运行时竞态，类型本身正确。

## 步骤
1. 在数据源头收窄。
2. 避免 `!` 和 `as any`。

## 反例
`as any` 让编译通过但线上仍崩。

## 案例
`user.name` 报 possibly undefined：`if (!user) return` 后再访问。
