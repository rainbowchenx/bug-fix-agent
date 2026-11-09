---
name: hierarchical-localization
description: Use to locate bug sites — repo → package → file → symbol → line.
---

# Hierarchical Localization

1. Start from stack frames / error messages / page routes.
2. Map to package or feature folder.
3. Grep for unique symbols; open 2–5 candidate files.
4. Identify the earliest incorrect assumption, not only the crash line.
5. Record file paths in the root-cause writeup and in `LOCALIZATION.editTargets`.

## 适用
analyze，产出 localization。

## 不适用
已经给出精确文件和符号时不要再全仓扫描。

## 步骤
仓库 → 包 → 文件 → 符号 → 行。

## 反例
把整个 `src/` 放进 editTargets。

## 案例
栈顶 `formatUser` 在 `src/login.ts`：suspectFiles 与 editTargets 都只含该文件。
