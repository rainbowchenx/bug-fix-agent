> 当前生产契约：0.3.0（2026-11-16）。目录保留原文档路径；旧 Agent 产物版本明确拒绝，请重新生成。

# analysis-report v0.1

**Producer:** Agent-3 (analyst) · **Consumer:** 人 / 下游

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | string | `"0.3.0"` |
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

## 0.3.0 主张、问题及反馈

rootCause.claims：claimId、statement、role、status、evidenceRefs、assumptions。supported 引用须能解析至本轮有效 Evidence；片段匹配仅证明引用，运行因果仍需真实观测。rootCause.questions：id、kind、reason、relatedClaimIds、requestedEvidence；blocking/choice 阻断整票编辑，verification/follow_up 保留但不一律阻断。openQuestions 从 questions 派生。

SDK 缺少 claims/questions 时一次有界格式修复；仍失败标 incomplete，保留可解析事实。报告含 attemptId、analysisStatus、actionability、附件读取状态，以及 TicketSlice 的当前 revisionId/sourceDocument/inputQuality。applyFix=false 仍可展示行动资格，但不会执行编辑器。

`feedback` 导入显式字段并继承父版本；`resume --execute` 实际运行报告模式续分析；`--apply-fix` 才允许编辑。expected/steps 未提供则继承，clearFields 显式清空，removeAttachmentIds 撤销附件；父版本未知或损坏拒绝静默回退。feedbackText 累积原文，单次反馈文件保留主要 kind 与来源。
