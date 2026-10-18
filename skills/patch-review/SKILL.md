---
name: patch-review
description: Use after edits / as readonly reviewer — approve or request_changes before MR. Never edit files in review mode.
---

# Patch Review

Readonly gate for automated bugfix (no Edit tools).

## Decision contract

Output exactly one JSON object:

```json
{ "decision": "approve" | "request_changes", "reasons": ["..."] }
```

- `approve` — diff matches root cause, within `target_files`, tests not weakened without cause.
- `request_changes` — list concrete blockers (scope creep, missing guard, bad test change, etc.).

## Checklist

- Diff against intent: does each hunk serve the root cause?
- Scope lock respected?
- Error paths and empty states covered?
- No secrets / env hardcodes?
- Residual risks named in `reasons` even on approve.

## 适用
review 模式。

## 不适用
analyze / implement（不要在评审里改文件）。

## 步骤
对照 DIFF hunk 与 target_files。

## 反例
没有 diff 却 approve。

## 案例
hunk 只把 `a - b` 改成 `a + b` 且测试变绿：approve。顺手改了无关文件：request_changes。
