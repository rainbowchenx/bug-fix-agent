# Agent2 与 Agent3 复审（0f21994）

审核日期为 2026-11-18（Asia/Shanghai）。依据是[上一轮复审](2026-11-18-agent2-agent3-5cac82e-review.md)、[设计方案](../specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md)及[实施计划](../plans/2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md)。

正式 CLI 修复路径已验证。上一轮四项的原始反例均已关闭，Agent2 的批次未完成状态和 Agent3 的正式续跑恢复仍有缺口。本轮验收结论独立于继续暂缓的 R10。

| 上轮发现 | 复核结果 |
|---|---|
| C01 新解决的问题丢失 | 首轮已解决的技术题进入快照账本，无新依据重开的回归通过。另以 CLI 验证二轮解决的产品题保留在账本内。 |
| C02 fixer 缺 previousAttempt | 实际调用反馈导入和续跑，验证 fixer 请求包含正确父轮，SDK fixer prompt 包含用户答复。上一补丁的应用状态仍有下述缺口。 |
| C03 修复产物缺父轮 | CLI 修复生成的 attempt 和分析快照均指向首轮。额外在真实修复产物写入 latest 时注入错误，确认旧指针保留，存储层重试同一 attempt 后指针推进。 |
| C04 partial 写成 complete journal | 初次记录保持 partial，同输入恢复有预算时会再次调用 runner。零预算时输出总状态仍错误，详见下文。 |

CLI 正向试验使用临时仓、受控模型回复和实际 SDK 输出规范化及 fixer prompt 构建。首轮出表到 feedback、resume --apply-fix 均经正式入口。隔离副本实际运行检查、产出 bundle.diff，补丁通过 git apply --check，实际应用后缺陷断言由失败转为通过。一次快速复跑碰到临时仓 Python 字节码缓存，清理该缓存后重跑通过。测试没有调用外部模型。单轮快照账本、补丁及父身份均有直接断言。

全量回归使用 Windows Python 3.12 执行 pytest tests -q --tb=short -rs，结果为 **538 passed、5 skipped**，耗时 151.78 秒。跳过项为四个本地脱敏 CSV 测试和一个需要 peitao 工作仓的测试。

## 剩余发现

### [P1] 汇总报告损坏会阻断正式续跑（T5、T9）

在成功修复后保留完整 latest 和逐票快照，把 analysis-report.json 模拟为写入中断的半截 JSON。再次执行实际 resume 会在进入分析前抛 JSONDecodeError。CLI 启动时直接读汇总，尚未按方案从提交的逐票快照重建。应以逐票提交记录重建汇总，保留其他票，并让当前票继续执行。位置为 `platform/bugfix_platform/cli.py:73`。

同一入口的并发边界也有代码缺口。CLI 在取得 run_analyst 的产物根锁前读取旧汇总、revision 和父轮，锁释放后才写合并汇总。两次续跑的分析可以串行拿锁，但后提交者仍可能用早先读取的汇总覆盖另一票的新结果。此点为代码审查结论，本轮未运行并发压力用例。位置为 `cli.py:73`、`:89`、`:124` 及 `agents/analyst/run.py:150`。

### [P1] 续跑包没有实际核对上一补丁是否已经应用（T7、T9）

CLI 产生可应用补丁后，实际将其应用到临时业务仓，并用当前快照验证。同一 PatchSet 和工作区直接交给 classify_patch_state 返回 applied，build_previous_attempt 却输出 unknown。它调用分类器时漏传工作树。fixer 现在确实收到整包，也会收到这个恒为 unknown 的状态。修复交付时的补丁分类另有调用，本发现针对分析和编辑开始前收到的上下文。位置为 `platform/bugfix_platform/agents/analyst/continuation.py:70`。

### [P1] 零预算恢复时丢失组级 partial（T3）

用正式 investigate_groups 调度和受控 runner 执行一票，runner 返回组 partial、票 complete。首轮正确输出 partial=True。用原 journal、同输入及 max_groups=0 恢复时，runner 没有再次执行，结果却是 partial=False、stopReason=budget_exhausted。journal 本身仍是 partial，误报发生在对外批次汇总。读取过程恢复了逐票 complete，提前退出后汇总只基于逐票状态及已执行组结果。位置为 `platform/bugfix_platform/agents/cartographer/investigation.py:234`、`:292`。此问题与暂缓的 SDK 格式收尾预算属于不同路径。

### [P2] 评测仍缺独立可修票子集与有效答案分母（T10）

本轮重复提问率的既有修复仍有效。正式汇总的 convergence 指标没有根据人工 eligibility 产出独立可修票验收指标。answerConsumption 还复用 requiredQuestions 分母。因此三道必答题仅收到一份有效答案、且该答案已合理处理时，配置现有字段会计为 1/3。设计中这时的有效答案消费率为 1/1。位置为 `packaging/eval_agent3.py:273` 及 `platform/bugfix_platform/agents/analyst/baseline.py:119`。

## 验收状态

| 验收范围 | 判断 |
|---|---|
| T0—T2 契约、原始响应与交接 | 现有契约和交接回归通过。R10 涉及的收尾保全继续暂缓。 |
| T3—T4 覆盖、恢复和工具路由 | 有额度时的 partial 恢复已接通，零额度的汇总有确定反例。真实 SDK 工具路由尚待验收。 |
| T5—T6 快照和反馈 | 同 attempt 存储重试、Markdown 反馈导入通过。正式入口的损坏汇总恢复未达标。 |
| T7—T9 上下文、账本及正式修复 | CLI 正向验收通过。上一补丁状态、续跑恢复和汇总提交范围仍有缺口。 |
| T10 评测 | 现有回归保留。人工可修票子集和有效答案口径有工程缺口。 |
| 真实业务 | 有效反馈能推动合成缺陷完成修复。真实 SDK smoke 与三项目验收没有执行，本次没有实测业务修复率。 |
