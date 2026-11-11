# Agent-3：全程 SDK 分析 + 开关控制改码

> 日期：2026-11-11  
> 状态：**实现中**  
> 基线：[三 Agent 正式架构](2026-11-03-three-agent-architecture.md) · [Agent-3 D 组](2026-10-30-agent3-defect-analyst-discussion.md)

## 1. 目标

Agent-3 默认**全程用 Claude Agent SDK**，吃 Agent-1 票切片 + Agent-2 仓图/软起点，按条产出**完整分析报告**（定位、根因、修复方案或分类阻断）。

改码（worktree + 第二次 SDK）**一起实现**，但用开关打开；默认只出报告。`openMr` 仍只管是否开 MR，且没有改码开关时禁止开启。

## 2. 流水线

```text
匹配池每票
  ├─ pool=needs_info → 完整阻断报告（不烧 SDK）
  └─ 其余（含 Agent-2 空候选）→ 只读 SDK analyze
        ├─ --apply-fix 关（默认）→ 停；可修也是 plan_only
        └─ --apply-fix 开且可修 → worktree 内 fix SDK
              └─ --open-mr 仍默认关（本轮不真推远端）
```

无根因不出码。空候选不再在路由器里终局 `unlocalized`（路由仍给出 hint），交给 SDK 自搜；搜完仍空才 `unlocalized`。

## 3. 开关

| 开关 | 默认 | 作用 |
|---|---|---|
| `--apply-fix` / `BUGFIX_APPLY_FIX` / 报告 `applyFix` | 关 | 是否跑第二段改码 |
| `--open-mr` | 关 | 是否集成并开 MR；**无 `--apply-fix` 时预检失败** |
| `--analyze-mode heuristic` | 仅测试/无 key 显式指定 | 不假装 SDK 分析过 |

产品路径：有凭据则 SDK。显式 `analyze-mode=sdk` 但无凭据 / SDK 挂掉 → 该票 `other_blocked`（写清原因），**不再**用启发式抄路由结果冒充分析。

## 4. Analyze（默认必须达标）

- 每票独立只读会话：Read / Glob / Grep；禁 Edit / Write / Bash。
- Prompt 带齐票正文（含 `intentRationale` / observed / expected / steps）和 Agent-2 `architecture`、playbook、`defectCodeMatches`、`gap`。
- `applyFix=false` 时禁止声称 `patch_ready`。
- 模型给出的路径：必须在 `workDir` 存在；`shell` / `host` / `route_table` 不当修位点。
- 触顶 salvage 半成品 JSON；`max_turns` 默认 24。
- `BUGFIX_ANALYZE_LIMIT` 仍为成本帽，默认不限。

## 5. Fix（代码落地，默认不跑）

- 仅当分析可修（真实 `rootCause.summary` + `proposedFix.summary`）。
- 每票 `workDir/.bugfix/worktrees/{defectId}`；非 git 仓则跳过改码并记 note。
- 第二次会话可 Edit/Write；结束后 `git diff` 写入 `{artifactDir|workDir/.bugfix/patches}/{defectId}.patch`。
- 有 diff → `patch_ready`；空 diff / 失败 → 仍 `plan_only` 并写明。
- `--open-mr` 本轮仍只改报告标志，不推 GitLab。

## 6. 测试

可注入 `analyze_fn` / `fix_fn`。覆盖：空候选仍进 analyze；`needs_info` 不进；无凭证 sdk → `other_blocked`；默认不调 fix；`--apply-fix` 才调；`--open-mr` 无 apply-fix 失败。
