---
name: gitlab-mr-hygiene
description: Use when preparing the fix commit message and MR summary. The agent must not push; Orchestrator delivers.
---

# GitLab MR Hygiene

## 适用
修复已经 GREEN，准备交给 Orchestrator 开 MR。

## 不适用
自己执行 commit / push / 创建 MR（那是 Orchestrator 的事）。

## 步骤
1. 提交说明只描述根因和修复。
2. 正文保留缺陷 ID、复现、验证命令。
3. 没有复现测试时接受 Draft MR。

## 反例
把 token 写进 remote URL 或 MR 描述。

## 案例
标题 `fix: null crash on login`，正文列出缺陷 id、根因一句话、`npm test` 通过摘要。
