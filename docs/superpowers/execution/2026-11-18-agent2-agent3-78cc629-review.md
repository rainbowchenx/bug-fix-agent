# Agent2 与 Agent3 复审（78cc629）

审核日期为 2026-11-18（Asia/Shanghai）。依据为[上一轮复审](2026-11-18-agent2-agent3-0f21994-review.md)、[设计方案](../specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md)和[实施计划](../plans/2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md)。R10 延续暂缓决定。

正式 CLI 修复链已通过。截断的汇总 JSON 可以重建，已应用的补丁可以在续跑中识别。本次仍确认并发父轮、汇总提交恢复、Agent2 部分成果恢复和计分口径存在缺口，完整工程验收仍待完成。

| 上轮事项 | 本轮结果 |
|---|---|
| 损坏汇总及并发续跑 | 截断 JSON 重建通过。两个不同缺陷错开执行时，汇总保留两票最新结果。同票并发仍会选用过期父轮，语法有效但内容落后的汇总也不会修复。 |
| 补丁应用状态 | 已修。正式修复产出补丁，应用到临时业务仓后，正式 CLI 的下次分析获得 `previousAttempt.patchState=applied`。HEAD 改变时继续采用分类器的保守判断。 |
| 零预算恢复 | 原误报已修。零预算时保留 partial=True 且不会调用 runner。对外产物及后续补查丢失已保存 facts，补查完成后总状态也可能一直停在 partial。 |
| 评测口径 | 显式有效答案数已接通，独立可修票字段已进入正式评分。报告模式和固定子集分母仍有反例。 |

## 剩余发现

### [P1] 同票并发可跳过已经提交的父轮（T7、T9）

CLI 在 run_analyst 获取产物根锁之前读取 revision、session 和 parent。用两个线程驱动实际 resume CLI，在第一个执行完父轮选择、调用 run_analyst 前暂停，第二个先正常完成，再恢复第一个。两次均返回成功，最终 latest 的父轮仍是两次开始前的旧 attempt，跳过了已提交的中间 attempt。中间轮新增的阻断或答复因此可能不进入后一个分析。合并 JSON 的锁不覆盖这段状态选择。位置为 `platform/bugfix_platform/cli.py:88` 和 `:97`。

同票续跑应在同一锁内选择并验证最新父轮，或者提交前显式拒绝过期父轮。不同票错开提交时，已验证锁内重新读取汇总能够保留两票结果。

### [P1] 汇总合法但落后时无法从已提交快照恢复（T5、T9）

模拟分析快照和 latest 已提交、汇总尚未写入的中断点。D2 的最新快照已经更新，旧 analysis-report.json 仍然是合法 JSON。接着通过实际 CLI 续跑 D1，最终汇总中的 D2 继续指向旧 attempt，与 latest 不一致。只要汇总能通过 schema 校验，load_or_rebuild_analysis_report 就直接返回旧汇总。位置为 `platform/bugfix_platform/agents/analyst/report_store.py:93` 至 `:95`。

应以已提交的逐票快照为准核对汇总内容，恢复其他票已成功提交的结果。语法损坏的恢复继续保留现有通过用例。

### [P1] 部分调查恢复丢事实，完成补查后批次仍可能未完成（T3）

以正式 investigate_groups 和受控 runner 保存一个组级 partial、票级 complete 且有事实的结果。零预算恢复输出 partial=True，调用次数保持不变，但对外 CodeKnowledge 的事实计数从 1 变为 0。随后允许重跑，runner 的输入仍无保存在 journal 的事实。另一次独立试验中，首轮为 partial，第二轮 runner 返回 complete。该组记录为 complete，最终批次却仍是 partial=True，因为读取旧记录时已将 incomplete 设为 True。位置为 `platform/bugfix_platform/agents/cartographer/investigation.py:206` 至 `:229`。

匹配输入的合法事实应保留在恢复产物和补查输入中，组级完成度由后续结果决定。只有补查尚未完成时才沿用组级 partial。

### [P2] 正式评分可抬高可修票成功率（T10）

调用实际 score_report。给定两张人工标为可修的票，一张有当前绑定并验收成功，另一张评分绑定过期、等待重新验收。当前输出的 eligibleDefects 为 1，eligibleRepairRate 为 100%。按方案冻结的独立可修票子集应保留两张，保守率为 50%，过期评分单列。将同一试验换成 applyFix=false 后，convergence.repairRate 正确为 null，但 eligibleRepairRate 和旧 summary.repair.successRate 仍为 100%。位置为 `platform/bugfix_platform/agents/analyst/baseline.py:139` 及 `packaging/eval_agent3.py:270`。

显式传入 effectiveAnswers=2 与 answersConsumed=1 已能得到 50%。缺有效答案分母时仍用已消费数推断收到数量，可能报告 100%，当前评测模板也缺相应分母字段。应独立记录有效答案数和是否完成标注。

## 正式入口与验收依据

Windows Python 3.12 运行 `pytest tests -q --tb=short -rs`，**541 通过、5 跳过**，退出码 0，耗时 155.31 秒。跳过项依赖本地脱敏 CSV 和 peitao 仓。

在临时算术仓，通过实际 feedback 和 resume --apply-fix 命令走完补充、分析、隔离编辑、检查和补丁交付。受控模型回复经过 SDK 分析规范化，同一份用户答复进入 fixer prompt。修复产物父链和问题账本一致，补丁可应用，应用后断言通过。第三轮将汇总截断再调用 resume --execute，验证 CLI 重建汇总并在分析上下文看到 applied。并发试验调用实际 CLI 和真实 run_analyst，仅控制进入分析的先后顺序。没有使用外部模型调用。

T0—T2 的现有回归覆盖契约和调查交接。T3 的部分成果恢复仍有确定反例。T5—T9 的补丁状态和正向修复通过，汇总恢复和串行父链尚未达到要求。T10 的固定分母和报告模式仍有确定反例。T4 对应的真实 SDK 工具路由与三项目业务验证尚未执行。R10 暂缓不影响上述判定。
