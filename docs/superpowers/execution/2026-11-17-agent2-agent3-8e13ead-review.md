# Agent2 / Agent3 再复审：8e13ead

日期：2026-11-17。基线：`8e13ead`（父提交`12f01bb`），审核开始工作区干净。本轮只审核、记录文档，不修改产品实现、不调用真实模型。

依据：[上一轮R01—R11](2026-11-17-agent2-agent3-12f01bb-review.md)、[修订方案](../specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md)、[实施计划](../plans/2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md)。**用户明确R10暂缓，本轮不要求修复R10，也不以它阻断本轮验收。**

## 结论

改动继续正向，R01坏source、R04续跑引用别名、R05重复resume父轮、R07 closing漂移的原反例均已有实质修复。但排除R10后，仍确认5项P1和2项P2，暂不满足本轮剩余工程目标。应分别记录“原用例通过”和“同一要求是否完整兑现”，不能把新增边界重复算成原用例没有修复。

完整回归：`py -3.12 -m pytest tests -q --tb=short -rs`，本机Windows Python 3.12运行，**529 passed / 5 skipped，150.05秒，退出码0**。4项skip依赖本地脱敏CSV，1项依赖peitao业务仓。日志：`/tmp/bugfixagent-review-8e13ead-tests.log`。下列反例均用临时目录、受控SDK消息/正式run_analyst或CLI/存储调用复核，没有真实服务费用。

## 仍需修复的发现

### S01 [P1] R02：嵌套仓引用仍能借外层仓HEAD通过核验

位置：`platform/bugfix_platform/sdk/match_payload.py:549`—`:554`。

版本核验用`heads["."]`或文件实际仓HEAD的集合，不按ref.repoId选择唯一仓。正式SDK适配链复现：外层HEAD为a×40，child仓HEAD为b×40，repoRoots也明确child=b；引用child/a.ts却声明revision=a，仍得到reference_verified和complete。

普通越界路径与单仓错误版本已被本次修复。剩余问题是多仓来源绑定错误，应从引用所属仓解析HEAD及内容摘要；不能用外层HEAD作另一种合法答案。对应R02、T2/T3。

验收补充：两仓同名文件、不同HEAD；child引用root HEAD必须拒绝升级，正确child HEAD才可核验。应走正式SDK适配器，不仅测_git_head helper。

### S02 [P1] R03：仓外Read可被规范化成仓内同名文件的成功观察

位置：`platform/bugfix_platform/sdk/match_payload.py:520`—`:529`及末尾_norm_obs。

repo_relative_path检测到越界后返回_norm_obs(raw)，后者用lstrip("./")将../a.ts变成a.ts。正式适配链复现：Read ../a.ts成功返回仓外内容，模型只报告仓内a.ts候选；最终observedScopes=[a.ts]并complete，仓内外文件内容不同。

失败ToolResult不再计成功、普通多仓路径不再子串匹配，原改进有效。越界观察应隔离或保留明确外部身份，不能折叠为仓内相对路径。对应R03、T1/T3。

验收补充：仓内外同名文件、相对越界和绝对越界路径，均不能给仓内候选生成成功观察范围。

### S03 [P1] R09：历史按输入key保存了，取match时却跨版本last-wins

位置：`platform/bugfix_platform/agents/cartographer/investigation.py:123`—`:148`。

journal_matches先将所有历史组按defectId汇总，后值覆盖。后续虽然对某组cacheKey做了正确校验，却从全局journal_matches取票，而非从该已验证组取matches。

正式investigate_groups复现：9票初次title=failure→仅重查0号且title改为changed target→将0号title恢复failure，本次仅resume 8号。最终0号仍携带changed target调查且complete，未重新调用runner。原“子集写盘删掉其它组”的问题已修；保留多版本后发生了数据串版本。

要求：恢复身份与实际取值使用同一个已验证记录，保留不同输入的历史，不跨key拼接。对应R09、T3。

验收补充：至少两个输入版本和一个子集恢复，断言facts内容属于正确输入，不能只断言complete数量和组数。

### S04 [P1] R06：目标变化后，失效问题仍会被跳过并放行

位置：`platform/bugfix_platform/agents/analyst/continuation.py:168`—`:199`；`analyst/analysis_store.py`的_ledger_from_entry。

新增questionLedger确实保存了历史题目，也已拦截无依据重开原反例。但expected变化后先生成`insufficient / expected changed; restatement required`，若模型遗漏该题，invalidated_ids分支直接continue，不进入未解列表。

正式三轮复现：q1产品选择→用户回答后resolved→第三轮expected改变且模型遗漏q1，最终allowed=True，questionLedger仍为q1 resolved，对应resolution却为insufficient。状态和门槛矛盾。

目标变化不意味着必须再次问用户；模型可以基于新目标明确替代或保留旧决定。但当前未给任何本轮处理结论就跳过，不能算完成答案/目标消费。对应R06、T7/T8。

验收补充：同时断言本轮resolution、ledger、未解列表及allowed一致；需要替代/重开而尚未完成处理的决定不能被静默放行，已明确处理的目标变更不能机械重问。

### S05 [P1] R08：提交后段中断仍无法恢复latest

位置：`platform/bugfix_platform/agents/analyst/analysis_store.py:63`、`:79`—`:87`。

本次修复了attempt.json缺失时的恢复，但recovering只检查attempt文件是否存在。已有a0，写a1时analysis/attempt/form均成功、_write_latest抛OSError；恢复后同digest重试成功返回，latest仍指向a0。此反例已独立注入存储异常确认。

要求：依据完整提交状态区分“未完成的新轮恢复”和“已完成历史轮幂等读取”，而非用单个文件存在判断；既要补齐未提交指针，又不能回读旧轮时倒退latest。对应R08、T5。

验收补充：analysis写后、attempt写后、form写后、latest更新前各中断点，以及成功提交后读取旧轮的组合。

### S06 [P2] R04扩展：首轮已决定的技术问题仍没有消费路径

位置：`platform/bugfix_platform/agents/analyst/run.py:305`—`:307`。

续跑candidate:1别名已修、SDK问题协议也已补齐。但resolutions初始化为空，只有previous_payload存在才调用consume。全新产物根正式run返回implementation choice、status=resolved、具体决策理由、newEvidenceRefs=[candidate:1]及有效片段，仍allowed=False，原因resolved question lacks matching resolution，也不会进入closing。

这不等于应放松resolved门槛，而是首轮及本轮新技术问题同样需要程序生成/校验相应决策记录。否则合法模型输出必须额外续跑才能进入修复，降低首轮有效率。对应T8/T9；R04上一轮的二轮别名用例可判通过。

验收补充：全新根/首轮就完成技术决策时，无需用户补一个无意义反馈即可进入既有编辑门槛；没有实质业务决定的产品choice仍阻断。

### S07 [P2] R11：重复提问率仍用错分母

位置：`platform/bugfix_platform/agents/analyst/baseline.py:110`—`:121`。

答案消费1/3原反例已修，合理/不合理重开也有计数。但repeatQuestionRate计算为无依据重开数/全部重开数，而方案要求无新依据重复必答题数/本轮全部必答题数。

已复现requiredQuestions=10题、unjustifiedReopens=1、justifiedReopens=0，结果1.0，约定口径应为0.1；没有任何必答题时返回0.0而非null。新测试恰好required数和reopen总数都是2，没区分两个分母。

要求：明确重复题计数和本轮必答题分母；若需要“重开合理性占比”另设指标，不覆盖原名称。对应R11、T10。

## R01—R11核对表

| 项目 | 本轮状态 |
|---|---|
| R01 同票字段隔离 | 原反例已修，同票合法facts/好候选保留 |
| R02 引用仓库/版本 | 普通越界和错误版本已修，多仓HEAD绑定仍见S01 |
| R03 成功工具观察 | 失败结果/子串匹配已修，越界路径身份仍见S02 |
| R04 技术引用协议 | 原二轮别名反例已修；首轮技术决策消费缺口S06另列 |
| R05 resume父链 | 原正式CLI反例已修，第二次resume承接a2并保留q2阻断 |
| R06 完整账本 | 已增加持久化，重开原反例已修；目标失效处理仍见S04 |
| R07 closing证据重建 | 原漂移/旧证据反例已修，收尾重新绑定当前证据与漂移 |
| R08 快照提交恢复 | attempt缺失场景已修；提交后段失败仍见S05 |
| R09 journal保全 | 子集不再抹历史；跨输入版本取值仍见S03 |
| R10 预算/收尾原文 | **按用户指示暂缓，不列本轮必修/不作为本轮不通过原因** |
| R11 收敛指标 | 答案按题计数已修；重复题分母仍见S07 |

## 交付边界

排除R10后，Agent2的来源/恢复仍有S01—S03，Agent3的状态/恢复仍有S04—S05，因此本轮工程验收仍未通过。S06影响首轮推进，S07影响效果评价准确性，应一并补齐。

R10暂缓影响仍保留：成本耗尽后追加收尾的风险，以及主/收尾原始响应、工具轨迹保全不完整。接受暂缓不等于它已修复，也不影响本轮其它项的独立判断。

真实SDK路由S和三项目业务修复效果B本轮未执行。529个通过测试不能证明真实修复率。现有授权修复集成测试仍主要断言fixer调用，完整“填表→实际resume --apply-fix→补丁可应用→真实缺陷断言恢复”的验收证据仍需补齐。

本次没有新增架构要求；剩余修改应集中在正确的身份绑定、提交状态和决策消费边界。
