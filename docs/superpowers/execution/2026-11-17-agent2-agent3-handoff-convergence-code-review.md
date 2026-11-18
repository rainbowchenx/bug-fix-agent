# Agent2调查保全与Agent3反馈收敛：实现审核

日期：2026-11-17。审核基线：HEAD `405b544` 上当前未提交的实现，包括新建模块和测试。审核期间不修改产品代码，不调用真实模型，不执行归档脚本；以下复现使用临时目录、受控SDK消息或纯函数。

依据：[修订方案](../specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md)、[修订实施计划](../plans/2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md)、[本批运行证据](../../field-eval/agent3/reviews/2026-11-17-three-project-real-run-assessment.md)。

## 结论

**尚未达到方案和计划的工程验收要求。** 新类型、规范化模块、逐轮快照、填写表单、previousAttempt及部分入口参数已经存在，是实际进展；但Agent2仍有整组丢合法调查的路径，Agent3则同时存在“答案未真正消费”和“未解阻断被错误放行”。不能把后者导致的allowed上升当作收敛改善。

完整回归命令：`py -3.12 -m pytest tests -q --tb=short -rs`。本机经`/mnt/c/Windows/py.exe`执行，结果 **503 passed / 5 skipped，159.75秒，退出码0**。4项skip依赖本地脱敏CSV，1项依赖peitao业务仓。测试通过不覆盖下列反例；真实SDK与业务验收未执行。

## 确认的问题

### F01 [P1] 字段隔离仍可抛异常，合法邻票再次整组丢失

位置：`platform/bugfix_platform/sdk/match_payload.py:229`、`:257`、`:265`、`:338`；组循环`:147`；`sdk/cartography.py:631`。

已分别复现：A票`confidence={}`触发unhashable TypeError，`hypotheses=True`触发not iterable，`title={}`触发整票ValidationError，candidate `symbol=42`触发候选ValidationError。外层normalize_group_matches不隔离这些异常，B票的合法调查也无法返回，正式适配器整组回退。字符串facts的常规测试通过，不能证明可选字段的所有形状都被隔离。

要求：标量、列表及每个候选在各自边界验证，坏字段保留诊断，其余合法字段/邻票继续；最终内部异常保留accepted中间结果。补正式query→normalize→merge混合组回归。对应T2。

### F02 [P1] 新JSON提取器可能永久死循环

位置：`platform/bugfix_platform/sdk/match_payload.py:80`—`:104`。

围栏包裹的合法JSON中，facts含字符串`handler checks value == "}"`，扫描器将字符串里的花括号算作对象边界。json.loads失败后break，却没有推进start，外层反复处理同一位置。独立子进程3秒仍不返回，已强制终止；同步解析阶段不受组间时间检查保护。

要求：使用识别JSON字符串转义的标准解码方式，所有错误路径必须推进或退出；增加含花括号/引号/转义的源码片段和坏JSON的有界回归。对应T2。

### F03 [P1] 合法引用被清空，SDK调查无法正常到达complete

位置：`platform/bugfix_platform/sdk/match_payload.py:248`—`:264`、`:290`—`:296`。

合法Fact对象的reference无条件变为None，payload不保留observedScopes，也没有程序从真实工具消息关联逐票scope、核验引用并升级reference_verified的链路。受控SDK响应带合法引用和范围，经正式适配器后仍变为reference=None、observedScopes=[]、partial。模型自报valid不应被信任，但合法引用本身应保留供验证。

后果：调查证据再度损失；complete缓存/恢复在真实适配链不能正常使用。现测试直接构造已验证Fact或complete结果，绕过了缺口。

要求：保留并核验引用；逐票关联可观察工具范围；仅程序升级validity。对应T2/T3。

### F04 [P1] 共享架构异常仍触发全量启发式回退

位置：`platform/bugfix_platform/sdk/match_payload.py:175`—`:189`；`sdk/cartography.py:620`—`:637`。

两票合法facts加`architecture.modules=[{"id":"m","role":{}}]`时，module因有id被接受，最终CodeKnowledge校验失败。正式适配器返回sdk_fallback，两票facts均空。未隔离坏增强块重验，也未交付typed accepted产物及internal_error。

要求：对共享块执行完整类型校验；已接受逐票调查不能随总组装失败丢弃；支持零SDK调用离线重放。对应T1/T2。

### F05 [P1] Bash hook接通但策略仍允许常规写代码命令

位置：`platform/bugfix_platform/sdk/cartography.py:118`—`:130`、`:225`—`:240`。

`touch /tmp/sentinel`、`cp src/a.ts src/b.ts`、`sed -i s/a/b/ src/a.ts`和`node -e "require('fs').writeFileSync(...)"`均得到允许。PreToolUse调用同一策略后返回允许。新hook解决了旧callback被遮蔽的接线问题，但没有实现只读能力。

现测试仅直接调用hook并模拟执行分支，不是SDK CLI真实路由证明。此审核没有在业务仓执行写命令，也不声称本批发生了改码。

要求：可靠收窄能力；未完成实际路由验证前关闭Bash，不能仅扩大正则黑名单。对应T4/S。

### F06 [P1] 决策收尾覆盖父账本后不重新校验，可清掉未回答产品问题

位置：`platform/bugfix_platform/agents/analyst/run.py:301`—`:347`。

正式run_analyst复现：首轮有未答产品choice q1；续跑初分析遗漏q1，consume找回并触发收尾；收尾再次返回questions=[]，325行直接覆盖rootCause。之后不再消费账本、检查violations或重建ctx/证据，最终actionability.allowed=True。满足其余条件且授权编辑时可进入fixer。

收尾请求也未传resume_session_id、当前conv违规/待处理问题，形式上是另一轮相似分析而不是明确的同会话决策校验。

要求：收尾结果重新执行账本覆盖、引用/源码漂移及编辑门槛校验；剩余协议错误必须阻断，收尾明确承载违规及会话身份。对应T8/T9。

### F07 [P1] answered和无resolution的resolved可绕过编辑门槛

位置：`platform/bugfix_platform/agents/analyst/evidence.py:30`—`:34`；`analyst/continuation.py:153`。

已复现：用户答`?`被记insufficient，问题为answered，但validate_edit_decision返回空错误列表。收尾预算不足仅设置analysisStatus=incomplete，仍可计算allowed=True。模型直接标resolved也不要求匹配有效QuestionResolution。新测试`test_resolved_blocking_does_not_fail_edit_gate`反而断言没有resolution也能放行。

要求：open/answered/reopened的blocking/choice继续阻断；resolved必须校验对应有效处理记录；工程incomplete不能只作为展示。对应T8。

### F08 [P1] 用答案长度代替答案消费，制造虚假收敛

位置：`platform/bugfix_platform/agents/analyst/continuation.py:135`—`:180`、`:197`—`:207`。

产品choice答“不知道”会自动resolved、问题消失；英文unknown却insufficient。程序没有消费模型对充分性/矛盾的判断，实际不存在conflicting分支；实现问题仅靠status或reason+requestedEvidence也可能自行关闭。expected变更是否失效旧决定仅搜索resolutionSummary中的英文target/expected，targetDigest写的却是旧analysis digest。

要求：由现有分析会话给具体处理结论/适用目标/依据，程序验证引用及状态；不能把字数、分类标签或关键词当业务判断。补中英文不足答案、反驳证据、目标更改的正式链回归。对应T7/T8。

### F09 [P1] 旧表不报stale，父attempt及反馈语义没有可靠传到续跑

位置：`platform/bugfix_platform/agents/analyst/feedback_document.py:103`—`:149`；`cli.py:80`；`analyst/run.py:180`—`:201`；`analyst/continuation.py:56`—`:79`。

已保存a2后再解析a1原表仍被接受，因为只比较旧快照自己的digest，没有检查当前链，也忽略baseRevisionId。CLI resume不传反馈绑定的parent_attempt_ids，run_analyst按latest猜父轮。父快照缺失/损坏又被静默变成previous_payload=None。

正式调用build_previous_attempt未传feedback，只覆盖questionAnswers，因此latestFeedbackKind/Text、rejectedHypotheses通常为空、patchState恒为None。原反馈文字可能仍拼入observed，但不等于计划要求的结构化续跑上下文。

要求：导入及执行绑定同一父attempt/revision，stale明确拒绝；损坏父快照报工程错误；携完整反馈语义及旧补丁状态。对应T6/T7/T9。

### F10 [P1] 锁外选择反馈父revision会丢补充；相同表重复导入还会报冲突

位置：`platform/bugfix_platform/agents/analyst/feedback_document.py:140`—`:160`；`analyst/feedback.py:38`—`:62`；`cli.py:35`。

并发顺序复现：已有q1=old answer，先parse A（q1=new answer）和B（仅改expected），再依次import A/B；B仍用旧父revision，最终q1回退old answer。import持锁不能保护此前parse选定的父版本。

同一填好文件parse/import第二次，feedbackId相同但parentRevisionId变成首次导入后的revision，触发feedbackId conflicts，幂等失败。parse还把所有答案来源写成固定D1:form，不能精确追到实际反馈revision。

要求：不可变答复内容决定幂等身份；在同一锁中先查幂等、校验父attempt、选择最新有效反馈revision、合并并提交。对应T6/T9。

### F11 [P1] 快照中断后同digest重试不会补齐提交

位置：`platform/bugfix_platform/agents/analyst/analysis_store.py:50`—`:55`。

注入save_attempt写失败后，analysis.json已存在；再次保存同snapshot会直接返回ref。已复现返回成功但attempt.json、latest.json、feedback-form.md全部不存在，孤立目录永久冒充幂等成功。

要求：区分已完整提交与仅有snapshot；同digest重试补齐未提交文件/指针，冲突仍拒绝。对应T5。

### F12 [P2] 表单仍会覆盖用户填写内容，必要补充入口不足

位置：`platform/bugfix_platform/agents/analyst/analysis_store.py:76`—`:77`；`analyst/feedback_document.py:29`—`:77`。

新轮无条件重写票级feedback-form.md；当前集成测试正让用户编辑该路径。导入未另存Markdown原文。模板只有expected、reject_hypothesis和逐题回答，没有其他补充、observed/steps、附件、补丁应用/验收及显式清空/删除区；未知答复块被拒绝，重复ANSWER标记则字典后值覆盖。

要求：报告链接不可覆盖的逐attempt表或保留填写文件；原表归档；补齐必要反馈种类及重复冲突检查。对应T6。另`analyst/report.py`本轮未修改，完整报告未增加表单链接。

### F13 [P1] journal复用漏输入指纹，partial恢复与最终进度/账单不完整

位置：`platform/bugfix_platform/agents/cartographer/investigation.py:41`、`:120`—`:150`、`:199`—`:227`。

已复现同仓同ID改title/目标后仍resumed complete group，runner不调用：journal只比identity与IDs，忽略包含ticket内容的cacheKey。partial journal完全不恢复；指定票子集只从新baseline初始化，未载入其它旧调查。turns/cost硬编码None；异常或预算break后不补写最终journal，停止原因可能仍completed。

要求：journal与cache统一校验完整输入/代码/配置身份；恢复合法partial及全量其它票；每个终止路径提交进度，携实际已知账单并区分未知口径。对应T3。

### F14 [P1] SDK收尾未保全唯一有效输出，且重置预算/漏费用

位置：`platform/bugfix_platform/sdk/cartography.py:546`—`:601`。

原始response在收尾前保存；_salvage不调用append_event/save_response/save_format_repair。受控SDK主调用耗尽2turn后仍追加2turn，配置为[2,2]，成功收尾才出现的fact在磁盘所有产物中不存在；收尾仍无可解析结果时回滚首轮turns/cost，漏记额外花费。主调用transcript也没保存ToolUse/ToolResult的name/input/id/content，源码读取证据丢成空text。

要求：主/收尾每次输出独立保存，结果先保全再解析；共享实际剩余预算，失败费用不回滚；工具公开消息如实序列化。对应T1/T3。A3缺evidenceRefs/坏协议的有界格式修复在本轮也未完整实现，不能靠普通closing替代。

### F15 [P1] 默认入口没有统一产物根，Agent3默认无快照可续跑

位置：`platform/bugfix_platform/workflow/run.py:153`—`:154`；`agents/cartographer/run.py:181`附近；`agents/analyst/run.py:140`、`:1090`附近。

CLI/库未给out-dir时workflow不派生artifact_dir。A2独自使用固定workDir/.bugfix-runs/agent2，A3仍out_dir=None，_persist_ticket_entry直接返回、不保存快照/表单；batch/knowledge/report也没有共同续跑根。不能完成默认运行→填表→resume。

要求：workflow生成一次带runId的共享根，贯穿A2/A3及批次/知识/报告，结果和CLI返回该路径；单独入口同样明确持久化规则。对应T3/T9。

### F16 [P2] 新收敛计分绕过过期绑定，报告模式也能显示100%修复率

位置：`packaging/eval_agent3.py:273`；`platform/bugfix_platform/agents/analyst/baseline.py:37`—`:67`。

正式score_report复现：report.applyFix=false，case带错误reportDigest但accepted/resolved=true，row正确判stale、旧repair指标无验收数据，新增convergence却success=1、repairRate=1.0。因为传入原始cases而非已校验绑定结果，并从每个case的可缺省applyFix推断模式。独立函数对首条stale也照计成功；按defectId去重还会混不同product。

模板的requiredQuestions/answersConsumed与函数requiredQuestion/answerConsumed字段不一致，指标也没有实现独立eligibility子集和重复提问率；按票布尔值不能替代按有效答案数的分母。

要求：统一评测绑定/执行模式/项目身份和字段口径；stale保留分母但不继承成功，pending独立；补正式评分器回归。对应T10。

## 逐项验收

| 任务 | 当前判定 | 主要差距 |
|---|---|---|
| T0 契约与夹具 | 类型基本存在，集成待完善 | 字段存在不证明语义/来源及prompt真正接通 |
| T1 响应保全 | 部分完成，未通过 | F04/F14；主文本保留不等于收尾及工具轨迹完整 |
| T2 分层规范化 | 未通过 | F01/F02/F03/F04 |
| T3 状态/恢复/预算 | 未通过 | F03/F13/F14/F15 |
| T4 实际只读能力 | 未通过 | F05；真实SDK路由也未证明 |
| T5 分析快照 | 部分完成，未通过 | F11/F12 |
| T6 用户反馈 | 部分完成，未通过 | F09/F10/F12 |
| T7 previousAttempt | 部分完成，未通过 | F09；有字段/能看到部分答案，不代表完整续接 |
| T8 决策收敛 | 未通过 | F06/F07/F08 |
| T9 正式入口及修复闭环 | 未通过 | F06/F09/F10/F15，集成验收缺失 |
| T10 工程评测支持 | 部分完成，未通过 | F16 |

E1/E2/E3均不应标完成。S（真实SDK）和B（真实业务）未执行；它们不应被用于掩盖以上可离线发现的工程缺口。70%仍只是待业务确认的试运行提议，本次无依据宣称任何真实修复率。

## 测试覆盖为何没有阻止问题

- T2只覆盖部分常见坏形状，缺dict confidence、布尔列表、坏标量/候选类型以及共享块内部字段；没有有界坏JSON用例。
- complete测试通过注入已验证fact/observedScopes，未实际走“模型响应→引用保全→程序验证”。
- `tests/integration/test_handoff_feedback_convergence.py`的Agent2直接返回合法CodeKnowledge，绕过真实规范化；二轮调用run_analyst而非实际resume CLI。
- 同文件的授权修复测试只断言fixer调用一次及defectId，没有二轮反馈后修复、补丁git apply、缺陷前失败后成功断言或实际检查结果。写过候选文件不足以满足T9。
- gate测试无有效resolution却允许resolved，恰好固化了与方案相反的行为。
- 表单测试未覆盖跨attempt stale、相同文件重复CLI导入、锁外解析交错和用户填写文件保全；snapshot幂等仅覆盖成功后的重试。
- T10仅测孤立函数，没覆盖score_report的真实绑定/模式路径。

## 建议修复顺序

1. 先处理解析死循环、Agent2合法数据隔离与只读边界（F01—F05），同时完成主/收尾保全与预算（F14）。
2. 修正Agent3最终门槛和真正答案消费（F06—F08），不得先以放松门槛提高allowed比例。
3. 完成反馈父版本/锁/幂等、快照恢复及表单保全（F09—F12），再连统一默认产物根（F15）。
4. 完成A2恢复/计费（F13）、修正计分（F16），补上述正式入口反例后跑全套回归。
5. 工程门槛通过后做S，再执行固定三项目反馈/修复试点B；分别记录完成状态。

未发现需要新增Agent、数据库、队列或重写修复器的理由。主要问题是已有设计的边界校验和接线尚未兑现，修复应集中于上述路径。
