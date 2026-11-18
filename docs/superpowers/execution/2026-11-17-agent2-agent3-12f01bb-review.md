# Agent2 / Agent3 修复复审：12f01bb

日期：2026-11-17。基线：提交`12f01bb`，审核开始时工作区干净。只审核及记录文档，不修改产品代码、不调用真实模型。依据：[修订方案](../specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md)、[实施计划](../plans/2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md)、[上一轮16项审核](2026-11-17-agent2-agent3-handoff-convergence-code-review.md)。

## 结论与测试

**改动方向正向，但仍未达到工程验收目标。** 不再将已解决的旧反例列为现存问题：JSON死循环、坏共享module全量回退、answered直接放行、Markdown正式导入的锁和幂等、默认父工作流的共享产物根均有实质修复。但仍存在合法调查整票丢失，以及用户补充后无法收敛/续跑遗漏新阻断的确定反例。

完整回归：`py -3.12 -m pytest tests -q --tb=short -rs`，本机用Windows Python 3.12执行：**518 passed / 5 skipped，155.00秒，退出码0**。4项依赖未提交的脱敏CSV，1项依赖peitao仓库。另以临时目录、受控SDK消息、正式run_analyst/CLI及纯函数验证以下反例；没有外部模型费用。全量日志位于`/tmp/bugfixagent-review-12f01bb-tests.log`。

## 剩余问题

### R01 [P1] 坏candidate.source仍会丢掉同票合法facts

位置：`platform/bugfix_platform/sdk/match_payload.py:423`—`:424`；组隔离`:174`—`:185`。

candidate.source为非空dict/list时，set membership仍抛unhashable TypeError，且在候选级try之外。现在组级catch能保住邻票B，是改善；但A票先前已规范化的合法facts、好候选仍随整票被隔离。复现A/B都有合法facts，A附带source={"bad":1}的坏候选，accepted只剩B。

修复要求：先验证source类型，异常收敛到单候选，保留A其它内容；测试要断言同票保留，不只断言邻票保留。对应F01/T2。

### R02 [P1] 仓外或版本不符的引用会升级为已核验事实

位置：`platform/bugfix_platform/sdk/match_payload.py:447`—`:466`。

verify_fact_references直接拼repoId/path读取，未检查resolve后的仓库边界、合法repoId、revision或contentDigest。正式SDK适配链复现：path=../outside.txt、revision=wrong，仓外文件含snippet，即得到reference_verified及complete；仓内错误revision/contentDigest同样被验证。

这不是要求机器证明根因，而是源码来源/版本自身不符合声明。应按实际仓映射检查边界和内容版本，来源不符不得升级或缓存为complete。对应F03/T2/T3。

### R03 [P1] 发出Read请求就算已观察，失败读取也能complete

位置：`platform/bugfix_platform/sdk/cartography.py:475`—`:482`；`sdk/match_payload.py:469`—`:477`。

observed_paths在ToolUse到达时添加，没有等待匹配ToolResult的成功结果。受控正式适配复现：Read a.ts随后返回permission denied/is_error=true，模型只返回该候选，仍得到observedScopes=[a.ts]、complete。范围匹配另用子串/后缀，不能区分多仓同名文件。

要求：按tool_use_id关联成功结果，程序生成规范化repo/path范围；失败/仅发起/部分读取分别记录。对应F03/T1/T3。

### R04 [P1] 正常SDK引用与问题消费不一致，技术问题仍可能一直卡住

位置：`platform/bugfix_platform/agents/analyst/continuation.py:175`—`:176`、`:209`；`analyst/claims.py:43`；`sdk/analyze.py:606`—`:608`。

正式run_analyst中，受控返回先经过SDK _normalize_payload：技术问题给status=resolved、具体决策理由及newEvidenceRefs=[candidate:1]，候选原文已核验；程序却只认read-D1-1等内部证据ID。claims有别名转换，questions没有。初分析+closing两次后仍allowed=false、analysis incomplete。

SDK提示词问题输出形状还未完整列category/status/newEvidenceRefs；模型按提示返回可能默认open。不能要求真实模型猜内部ID来满足门槛。

要求：统一claims/questions的引用解析及输出协议，解析后再校验当前有效证据；新增正常别名→决策收敛→正式修复入口的正向测试。对应F08/T7/T8/T9。

### R05 [P1] 重复resume永久优先旧反馈父轮，漏掉最新分析的阻断

位置：`platform/bugfix_platform/cli.py:83`—`:98`。

正式feedback→resume --execute复现：a1表回答q1，首个resume生成a2并新增未解产品q2，allowed=false；不导入新反馈再次resume，parent_id仍取旧feedback.attemptId=a1。模型只处理q1即可allowed=true、questions为空，a2的q2未进入上下文。

显式父绑定解决了旧表猜latest的部分问题，但已消费反馈不能让后续重试永远倒回旧父轮。指定revision时同样不能无条件加载最新Feedback作为父上下文。

要求：校验反馈是否已被attempt消费；续修承接正确串行链，重试/指定revision身份明确；会话和分析父版本必须一致。对应F09/T7/T9。

### R06 [P1] 快照只存未解题，已解决问题无法执行重开约束

位置：`platform/bugfix_platform/agents/analyst/run.py:303`—`:310`；`analyst/continuation.py:146`—`:173`、`:229`—`:234`。

resolved问题从rootCause.questions移除，只剩resolution，下一轮parent_questions无法恢复完整题目。纯函数复现：父快照openQuestions=[]、已有q1 resolved及有效答案；本轮重新提q1 open但无新证据，violations=[]，程序把它作为新问题继续阻断，不执行“已解决问题无依据不得重开”的检查。

正式三轮另复现：目标修改后旧resolution被过滤，但旧题/失效处理记录并未恢复。目标修改不一定需要再问用户；问题在于无法明确记录受影响决定的继承、替代或重开，不能把删记录当完整账本。

要求：持久化全部问题及生命周期，未解题只是派生视图；用全部历史身份校验重开，新目标逐项写处理结论。对应F08/T5/T7/T8。

### R07 [P1] closing改了分析或遇到源码变化后，仍使用旧证据门槛

位置：`platform/bugfix_platform/agents/analyst/run.py:338`—`:355`、`:383`—`:386`；首次漂移检查`:263`—`:266`。

本版closing会重新消费问题，已阻止原“漏题就清空”的反例；但替换localization/summary/proposedFix后不重新构建ctx、核验片段和绑定claims，drifted也只在closing之前算一次。

正式run复现：closing期间临时源文件由减法变乘法，返回已resolved及有效旧程序证据ID，最终allowed=true。此注入模拟外部编辑器/进程修改源码，不声称只读SDK有写权限。收尾定位到新文件也不应借旧文件的valid证据授权。

要求：对最终分析重新完成证据/片段/主张绑定和源码漂移检查，再计算最终编辑决定。对应F06/T8/T9。

### R08 [P1] 有旧latest时，中断重试仍不会提交新latest

位置：`platform/bugfix_platform/agents/analyst/analysis_store.py:104`—`:106`、`:78`。

已有完整a0；保存a1在analysis.json成功后、save_attempt写入时失败；同digest重试后，attempt/form虽被补齐，latest仍a0。已独立复现“新attempt文件存在=True，latest=a0”。新测试只覆盖首次根目录没有latest的情况。

要求：区分已提交历史attempt的幂等重读与未提交attempt的恢复；恢复后正确提交且不得让重读旧历史倒退latest。对应F11/T5。

### R09 [P1] 子集恢复覆盖其它组的journal，下一次全量重付费调查

位置：`platform/bugfix_platform/agents/cartographer/investigation.py:141`—`:161`。

9票全完成→仅恢复ticket_ids=[8]：返回9票仍完整，是本次改善，但progress.json只写本轮records，历史0—7组被删除。再次全量恢复0—7会重调runner。非选中票恢复还直接拷贝journal_matches，未逐票核对其输入是否已变化。

要求：按输入身份合并历史组进度与本轮更新，不能用子集覆盖全量恢复依据；非选中票也要保留stale边界。对应F13/T3。

### R10 [P1] 成本预算耗尽仍追加SDK收尾；收尾保全仍不完整

位置：`platform/bugfix_platform/sdk/cartography.py:587`—`:601`、`:603`—`:646`。

本版turns耗尽后不再强加两轮、失败费用不再回滚，均已改善；但只判断剩余turns。受控SDK首轮error_max_budget_usd、num_turns=1/max_turns=4后，仍发起2turn收尾，调用配置[4,2]、费用继续增加。明确成本停止时不得因尚有轮数再调用。

收尾仍只记录非空text，唯一ToolUse/ToolResult标记未进入产物；save_response又覆盖初始response.json而非独立响应。初始文本部分仍在transcript，不能说所有初始内容丢失。

要求：同时约束cost/time/turn预算；主/收尾使用同一事件序列化及不可覆盖响应记录。对应F14/T1/T3。

### R11 [P2] 评测仍按票布尔值计算答案消费，把合理重开算成重复提问

位置：`platform/bugfix_platform/agents/analyst/baseline.py:83`—`:96`。

report-only和单条stale修复率反例已修。但requiredQuestions=[q1,q2,q3]、answersConsumed=1时answerConsumption=1.0，应为1/3；questionReopened=true即repeatQuestionRate=1.0，不区分有新证据的合理重开，也不是方案要求的“重复必答题数/全部必答题数”。尚无独立可修票子集的完整指标。

要求：保持按题/按票分母区分，有效答案、合理重开、无依据重复分别记录；正式评分器与模板共用数据口径。对应F16/T10。

## 上一轮16项逐项状态

| 旧项 | 本轮判断 | 依据 |
|---|---|---|
| F01 字段隔离 | 部分修复 | 原反例修好，R01仍丢同票合法内容 |
| F02 JSON死循环 | 原缺陷已修复 | 字符串/转义识别及错误推进已增加 |
| F03 引用/complete | 部分修复 | 已保留并校验引用，但R02/R03会假验证/假完成 |
| F04 坏共享块全量回退 | 原缺陷已修复 | role坏类型隔离，最终异常尝试保留typed结果 |
| F05 Bash只读 | 预授权风险已收紧，S未验收 | 移出allowed_tools；见下方SDK语义边界 |
| F06 closing绕过 | 部分修复 | 漏父题已有回归，R07仍用旧证据 |
| F07 answered/伪resolved放行 | 原列明反例已修复 | answered阻断、resolution和incomplete参与门槛 |
| F08 答案消费/事权 | 部分修复 | 字数规则已删除，R04/R06仍破坏收敛 |
| F09 父轮与上下文 | 部分修复 | 已传显式父轮，但R05续跑倒退；patchState调用未传worktree，仍多为unknown |
| F10 锁/幂等 | 正式Markdown入口原反例已修复 | parse/归档/import同锁；累计父revision锁内选择，幂等内容比较已调整 |
| F11 中断恢复 | 部分修复 | 已补文件，R08已有latest时未提交 |
| F12 表单交付 | 主要修复 | 不覆盖已填表、原文归档、重复ANSWER拒绝、补充区和报告链接已加入；显式删除附件入口尚缺 |
| F13 journal与账单 | 部分修复 | 输入key/partial载入/费用字段/最终flush已增加，R09仍抹恢复历史 |
| F14 收尾保全/预算 | 部分修复 | turns限制及费用保留改善，R10未闭合 |
| F15 默认共同产物根 | 正式父工作流原缺陷已修复 | 默认runId根贯穿A2/A3，CLI返回artifactDir |
| F16 计分 | 部分修复 | stale/report-only绑定已修；R11定义仍不符 |

SDK语义补充：本地已安装SDK源码和[官方Python SDK README](https://github.com/anthropics/claude-agent-sdk-python/blob/main/README.md)均区分tools与allowed_tools。移出allowed_tools只取消自动批准，不移除工具；[官方权限流程](https://code.claude.com/docs/en/agent-sdk/permissions)说明dontAsk会拒绝需要提示的调用，但无需批准的只读操作仍可执行。当前未显式disallowed Bash，不能把列表变化称为工具彻底禁用；同样不能仅因helper返回allow就断言dontAsk下实际发生写入。S需实际CLI路由证据，若采取完全关闭Bash的兜底，应使用明确工具限制/deny配置。

## 验收结论与建议

- **E1未通过**：R01/R02/R03/R09/R10均为可离线确认的调查可靠性缺口。
- **E2未通过**：R04/R05/R06/R07/R08仍影响用户补充后修复和上下文完整性。
- **E3未完全通过**：评分的关键错误已有修复，但R11仍不符合约定口径。
- **S/B未执行**：真实SDK、固定三项目业务样本及真实修复率不能由518个测试替代，仍不宣布整体交付成功。

T9新增测试覆盖了closing漏题的负向路径，这是实际改善；但授权修复集成测试仍仅断言fixer调用/票号，未补“填写表单→实际resume --apply-fix→完整补丁可应用→缺陷断言先失败后通过”的正向验收。这一缺口应随R04/R05修复补齐，而非只扩充纯函数断言。

下一版优先：同票字段隔离及引用来源→技术引用协议/完整问题账本/正确续跑父链→最终closing证据门槛→恢复与预算→指标。无需增加新Agent、数据库或重写修复循环。
