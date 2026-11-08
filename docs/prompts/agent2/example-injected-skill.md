---
name: acme-player-layout
description: >
  指导通读本产品线播放器仓：测试模块对照、不要扫的目录、单测位置。
  Agent-2 通读与 Agent-3 分析都要遵循。
profiles: bugfix
---

# 本仓通读规则（示例，复制后改成真实路径）

把这份文件放到下面任一位置，目录名即 skill 名：

- `{workDir}/.bugfix/skills/acme-player-layout/SKILL.md`
- 某仓根 `.claude/skills/acme-player-layout/SKILL.md`
- `--skills-dir` 指向的目录下 `acme-player-layout/SKILL.md`

`profiles: bugfix` 表示 Agent-2 和 Agent-3 都加载（最高优先级 overlay）。只要给一边：`cartography` 或 `analyze`。放在 `.bugfix/skills` / `--skills-dir` 且不写 profiles 时，默认两边都加载。仓内 `.claude/skills` 必须写 profiles。

## 怎么读这个仓

1. 先看 `packages/player` 与 `apps/desktop`，不要把 `packages/legacy` 当定位目标。
2. 测试模块「回放」→ `packages/playback`；「预览」→ `packages/player/src/preview`。
3. 单元测试在 `tests/unit`，e2e 在 `tests/e2e`：e2e 只用来理解复现步骤，不要当作缺陷代码位点。
4. 开发启动：`pnpm --filter @acme/player dev`（runtimeVerify 默认关闭时不要真的起服务）。

## 匹配偏置

- 崩溃 / 托盘 / IPC → Electron main / preload
- 文案 / 布局 / 控件偏移 → renderer 或对应微前端子应用
- 标题括注 `[回放]` 优先在 `packages/playback` 下 Grep

## 不要做

- 不要发明 workDir 里不存在的路径
- 不要超过每票 3 个候选
- 不要改 matching 池或 code-knowledge 字段名
