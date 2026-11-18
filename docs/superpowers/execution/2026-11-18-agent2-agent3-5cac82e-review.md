# Agent2 / Agent3 完整复审：5cac82e

日期：2026-11-18（Asia/Shanghai）。基线：`5cac82e`，审核开始时工作区干净。关联：[上一轮7项](2026-11-17-agent2-agent3-8e13ead-review.md)、[修订方案](../specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md)、[实施计划](../plans/2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md)。

用户明确R10继续暂缓；本次不把R10作为必须修复项或不通过原因。只审核和记录，没有修改产品代码，没有调用真实模型/API。

## 结论

**修复主链已实际接通，上一轮大多数指定反例已闭合；仍不能宣布完整工程验收通过。** 本轮实际执行了填表、feedback CLI、resume --apply-fix、隔离修改、命令检查、补丁应用和缺陷断言，确认能产出真正有效的小仓补丁。与此同时，这条正式入口暴露了fixer上下文和修复产物父链未接通；另有完整问题账本及partial恢复状态的问题。

完整回归：`py -3.12 -m pytest tests -q --tb=short -rs`，Windows Python 3.12：**536 passed / 5 skipped，149.55秒，退出码0**。4项skip依赖未提交的脱敏CSV，1项依赖peitao业务仓。日志：`/tmp/bugfixagent-review-5cac82e-tests.log`。离线正式CLI试验日志：`/tmp/bugfixagent-review-5cac82e-e2e.log`。

## 仍需修复的4项

### C01 [P1] 当轮新提出并解决的问题没有写进完整账本

位置：`platform/bugfix_platform/agents/analyst/run.py:332`、`:486`；`analyst/analysis_store.py:149`—`:153`；`analyst/continuation.py:277`—`:289`。

首轮技术题现在能正确消费并进入编辑门槛，这是S06的实质修复。但consume生成resolution后从openQuestions中移除题目，run又用openQuestions替换report.questions；保存快照时只合父ledger及剩余report.questions，没有保存本轮已解决题的完整对象。

正式run经SDK _normalize_payload复现：全新根，q2为implementation/resolved，理由和candidate:1引用有效，allowed=True；快照却为questionLedger=[]、questionResolutions=[q2 resolved]。下一轮无新证据再次提q2，程序把它作为新题，不能执行已解决题的重开校验，产生重复阻断。续跑中新出现并当轮解决的问题也有同一路径。

要求：完整ledger由父账本加本轮全部问题及处理结果生成；openQuestions只作为视图。不要依赖仍留在报告未解列表里的题目才能持久化。

验收：首轮与后续新技术题当轮解决后，保存快照仍有完整题目及resolved状态；下一轮同ID无依据重开必须被识别，真实新依据重开及目标失效处理继续正常。对应T5/T7/T8。

### C02 [P1] previousAttempt只接到analyze，没有接到fixer

位置：`platform/bugfix_platform/agents/analyst/run.py:753`—`:766`；`sdk/fix.py:241`。

run向AnalyzeRequest传previous_payload，但没有把它存入entry或传给_run_fix_loop。fix分支analysis=dict(entry)，随后仅加currentTarget/inputRevision/upstreamInvestigation；SDK fix提示词虽读analysis.previousAttempt，实际始终为空。

本轮实际feedback→resume --apply-fix的同一成功试验中，analyze拿到previousAttempt=True，fixer拿到False。当前票的分析和输入revision仍在，因此简单补丁可以修好；但旧假设、排除项、答案处理记录、旧补丁状态和会话降级信息没有按T7要求贯穿到编辑会话，不能把“prompt里有字段”当作交接成功。

要求：将正确父attempt的续跑包显式贯穿到FixRequest.analysis；不要由fixer自行猜latest。验收要检查实际fix SDK prompt中的包及其父版本、关键答案/否定假设，而非只检查AnalyzeRequest。

对应T7/T9。

### C03 [P1] 授权修复分支缺父attempt，提交恢复仍不完整

位置：`platform/bugfix_platform/agents/analyst/run.py:867`—`:874`；`analyst/analysis_store.py:85`—`:88`。

本次新增incomplete_child判断已修复有父身份的report-only提交恢复。但_run_fix_loop返回的AttemptRecord未赋parentAttemptId，只有不进入fix的_attempt_from_entry分支赋值。

实际CLI续修成功产物已确认：预期父attempt为首轮ID，实际parentAttemptId=None。另以正式run_analyst(apply_fix=True)、真实临时worktree写入及_write_latest异常复现：analysis/attempt/form都已保存，同snapshot重试成功返回，latest仍为旧轮。恢复条件依赖parentAttemptId==latest，因此新的修复没有覆盖到授权编辑分支；快照父链也随之断开。

要求：传递显式父身份到fix产物及snapshot，恢复依据完整提交状态校验。验收同时覆盖report-only和apply-fix，包含latest写失败后恢复及读取旧轮不倒退指针。

对应S05、T5/T7/T9。

### C04 [P1] SDK明确partial的组可在恢复时升级为完整完成

位置：`platform/bugfix_platform/agents/cartographer/investigation.py:256`—`:258`；恢复路径`:213`—`:217`。

计算group_status时强制knowledge.partial=False。正式investigate_groups→run_claude_cartography受控query复现：正常结束的SDK响应partial=true，一票包含可核验源码引用；首轮knowledge.partial=True，但组记录status=complete。相同输入resume后未再调用SDK，返回resumed complete group、knowledge.partial=False，query总次数仍为1。

这与R10的成本/收尾问题独立：明确未完成的组被journal当完整命中，后续调查没有推进。票有已验证片段不代表组级协议缺口/未完成调查已解决。

要求：保留组级partial与未完成理由；若能证明某部分不影响约定调查交接，应显式记录判定依据，不能一律清零partial。阶段恢复可复用合法片段，但不得静默晋升complete缓存。

验收：显式partial、有合法事实的组首次及恢复后均不虚报完整；后续补查真正完成后才允许complete。对应T3。

## 上一轮5项P1、2项P2核对

| 上轮项 | 本轮复核 |
|---|---|
| S01 / R02 多仓HEAD | 原反例已修；child错误root HEAD保持unverified/partial，正确child HEAD能核验 |
| S02 / R03 仓外观察路径 | 原反例已修；成功Read ../a.ts不再成为仓内a.ts的observedScope |
| S03 / R09 跨输入key恢复 | 原反例已修；取值来自匹配输入key的组，恢复facts正确 |
| S04 / R06 目标变化遗漏题目 | 原反例已修；遗漏失效题阻断，明确重述并有合法依据后正常放行 |
| S05 / R08 提交恢复 | 有父身份的report-only原用例已修；正式fix产物缺父身份，C03仍未闭合 |
| S06 首轮技术题不消费 | 首轮可正常消费/放行；同轮已解决新题的持久化回归见C01 |
| S07 / R11 重复题率分母 | 原用例已修；1/10及零分母null通过，答案消费率仍按题计数 |

R10：继续暂缓，不作为本轮上述判断的原因。此前已修的坏source、JSON死循环、closing漂移和CLI重复resume父轮问题没有被重复列为现存缺陷。

## 正式CLI正向试验

临时仓包含src/add.py，初始实现return a - b，目标为加法。分析结果经过SDK的_normalize_payload，模型边界用受控AnalyzeResult与FixResult；实际调用CLI feedback和resume --apply-fix，实际隔离副本、PatchSet收集器、命令执行器及git apply均未替换。

过程：首轮报告保存快照/表单→在q1答复区填写加法目标→feedback导入→resume --apply-fix读取revision与previousAttempt→fixer修改隔离副本→运行两条正负数加法断言→生成bundle.diff→原临时仓git apply --check→应用补丁→重跑同一缺陷断言。

关键结果：

```text
BASELINE_ASSERTION_EXIT 1
RESUME_EXIT 0 OUTCOME patch_ready VERIFY passed
ANALYZE_PREVIOUS_ATTEMPT True FIX_PREVIOUS_ATTEMPT False
ACTUAL_FIX_PARENT None
CHECKS [('passed', 0)]
PATCH_APPLY_CHECK_EXIT 0
PATCH_APPLY_EXIT 0
AFTER_PATCH_ASSERTION_EXIT 0
```

这证明正式CLI可以在有效反馈后真实推进修复并交付可应用补丁，也同时证明C02/C03存在。模型stub不能证明真实模型的语义判断、真实SDK CLI权限路由或业务修复率。Agent2的三项来源/恢复修复另经其正式SDK适配器及组调度的受控query复核；本次没有将合成CodeKnowledge冒称完整实仓Agent1→Agent2效果验证。

## 方案与计划验收状态

| 计划项 | 本轮判断 |
|---|---|
| T0 契约/来源夹具 | 类型及契约回归通过；字段实际交接仍受C01—C03限制 |
| T1 响应保全 | 原有主链回归通过；R10相关收尾原文/工具轨迹限制按用户要求保留；不据此新增阻断 |
| T2 分层规范化 | 已列明坏字段、共享块、引用身份原反例通过正式链复核；未发现新的同范围确定失败 |
| T3 覆盖/恢复 | 指定多输入恢复已修；C04的partial晋升使完整验收仍不通过 |
| T4 工具只读路由 | 保留此前配置收紧；本轮未执行真实SDK工具路由S，不声明S通过 |
| T5 快照 | 普通父轮恢复已修；C01账本、C03 fix父链仍未闭合 |
| T6 填写反馈 | 正式Markdown feedback导入通过，原有锁/幂等回归无失败 |
| T7 上下文 | analyze续接已接通；C01完整问题、C02 fixer包及C03父链仍有遗漏 |
| T8 决策收敛 | 首轮技术题及目标失效正反用例通过；C01会让已解决的新题被重复提问 |
| T9 正式入口/补丁 | 本次CLI有效反馈→真实补丁/验证试验通过；上下文及恢复分支有C02/C03，尚不能整体通过 |
| T10 评测支持 | 本轮S07的指标定义修复通过；完整业务eligibility、固定样本评审和效果验收仍需独立执行 |

排除R10后，E1仍受C04影响，E2仍受C01—C03影响；不能宣布完整工程验收达成。已实际验证的CLI修复能力应承认，不应继续描述成“只能产分析报告”。真实SDK门槛S、三项目真实业务验收B仍未执行，不用536个测试或这张合成缺陷计算业务成功率。

建议后续聚焦这四条接线/状态问题，无需扩展新架构。将本次临时CLI正向试验固化为回归，并在同一测试中断言fixer收到previousAttempt、产物父身份正确、完整ledger保留，再补partial恢复反例。
