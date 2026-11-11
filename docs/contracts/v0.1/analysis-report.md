# analysis-report v0.1

**Producer:** Agent-3 (analyst) · **Consumer:** 人 / 下游

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | string | `"0.1.0"` |
| `productLine` / `workDir` | string | |
| `generatedAt` | ISO string | |
| `openMr` | boolean | 默认 false；没有 `applyFix` 时禁止开启 |
| `applyFix` | boolean | 默认 false；true 才跑第二段 worktree 改码 |
| `mrUrl` | string \| null | |
| `integrateMode` | `none` \| `single_mr` | openMr 时为 single_mr |
| `summary` | `{ total, byOutcome }` | 浏览用；真源是 tickets[] |
| `boundSkills[]` | string | 本次实际绑定的 analyze skill 名（overlay 在前，包内置在后） |
| `tickets[]` | **每票完整报告** | D2 |

`tickets[].localization.notes` 里带 `analyze=<sdk\|heuristic\|sdk_fallback>` 及降级原因——
判断 Agent-3 到底调用没调用 LLM 看这一处，不要靠猜。

默认只出报告。`--apply-fix` / `BUGFIX_APPLY_FIX` 打开后，可修票才进 worktree fix 会话；空 diff 仍是 `plan_only`。`--open-mr` 本轮仍不真推远端。

### tickets[] 互斥规则

| `outcome` | 必填 | 禁止糊写 |
|---|---|---|
| `patch_ready` / `plan_only` | `proposedFix.summary` | 不可只写 blockers |
| 其它阻断类 | `blockers` | 不可只写「不可修」 |

### outcome 枚举

`patch_ready` · `plan_only` · `needs_test_env` · `needs_ticket_info` · `needs_design_input` · `not_code` · `config_or_dependency` · `unlocalized` · `other_blocked`

### tickets[] 字段

| Field | Notes |
|---|---|
| `ticket` | 单信息切片（title/module/tag/intent/obs/exp/steps…） |
| `localization` | candidates + notes；可 `degradedSearch` |
| `rootCause` | summary / ruledOut / openQuestions |
| `proposedFix?` | summary / steps / targetFiles |
| `patch?` | path / summary |
| `blockers?` | kind / detail / missingInfo? / envNeeds? |
| `suggestedVerify` | steps + executed（默认 false） |
| `confidence` | high/medium/low |
| `verifyStatus` | passed/failed/**skipped**（默认 skipped；非 GREEN 门禁） |
