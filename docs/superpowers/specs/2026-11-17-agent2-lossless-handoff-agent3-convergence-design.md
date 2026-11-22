# Agent2调查保全与Agent3反馈收敛方案

本方案制定于 2026-11-17，当时的代码基线为 `405b544`。以下各节记录目标与验收要求，实际交付范围见[当前实现与验收状态](../../architecture.md#验收状态)。

关联：[实施计划](../plans/2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md)、[三项目实测复评](../../field-eval/agent3/reviews/2026-11-17-three-project-real-run-assessment.md)、[统计](../../field-eval/agent3/reviews/2026-11-17-three-project-artifact-statistics.json)、[18票对照](../../field-eval/agent3/reviews/2026-11-17-three-project-ticket-comparison.csv)、[上一版方案](2026-11-16-three-agent-evidence-quality-design.md)、[上一版计划](../plans/2026-11-16-three-agent-evidence-quality-implementation-plan.md)。本次真实项目范围仅peitao、transport、hcp。

## 1. 目标、事实与非目标

目标：Agent2的有效调查不因局部字段异常消失；Agent3接收并处理用户答案，证据充分时推进修复，而非反复上交技术选择。工程完整性与真实修复效果独立验收。

已核实的输入：三线93票、13组调用，85次invalid_match拒绝、逐票facts/scopes全空；具体无效字段没有原始响应/ValidationError可追。字符串facts能复现整票校验失败，但尚不能证明它是所有拒绝的唯一原因。18票A3中16有结构化分析、2解析失败、14有预算截断标记、18全不允许编辑。本批applyFix=false，未改码符合要求，不能用无补丁扣分。

当前缺口：

| 位置 | 当前行为 | 要改的行为 |
|---|---|---|
| sdk/cartography.py `_coerce_sdk_match` | 仅gap规范化；其它校验异常返回None，整票SDK内容不交接 | 原始记录先保全；分字段/分候选解析；结果、来源、拒绝原因一起交接 |
| `_merge_enrichment` / coverage | 保留baseline；返回ID即可能partial；facts非空即可complete | 身份强约束；区别SDK接受、规则线索和证据完整度；无引用字符串不触发complete |
| cartographer/investigation.py | complete缓存；无完整进度账本及明确stopReason；部分错误金额缺失 | 每组增量持久化、可恢复阶段、账单和停止原因，不能靠长detail反推 |
| SDK工具权限 | 日志提示whole-tool allow遮蔽can_use_tool | 在实际SDK执行路由验证Bash限制，阻止只读阶段写操作 |
| analyst/report.py / cli.py | 用户需另写Feedback JSON；报告没有答复区 | 每票生成可填写文档，自动携带身份，程序导入内部Feedback |
| AnalyzeRequest / `_build_prompt` | 当前票+上游知识+反馈文字；没有previousAttempt | 恢复/新会话均注入首轮分析、答案、旧补丁状态及当前目标 |
| AttemptRecord / save_attempt | 保存decision/evidence等，不完整保存候选、rootCause、ruledOut和方案 | 每attempt保存不可覆盖分析快照，并与索引绑定 |
| Question / edit gate | 未解决blocking/choice一律挡；没有答案状态 | 对已回答问题做有界处理；技术选择由Agent决定；重开须有原因与证据 |

不新增数据库、调度服务、投票Agent、通用语义判真系统或完整前端。继续用现有SDK会话、文件产物、隔离工作区、PatchSet和验证器。不取消Agent2逐票调查。不做历史生产契约兼容；新模型响应的容错不是旧产物兼容。

## 2. 必须保持的不变量

1. 在进入解析前记录收到的SDK响应；失败不可静默变成“SDK完成”。落盘失败明确标artifact_error，不虚称已保全。
2. 身份与仓库范围错误在最小可确认边界拒绝交接；错误条目不串票，也不连带丢弃同响应内其它身份明确的合法票。一个无效可选字段或单候选不得连带丢弃其它合法内容。
3. 拒绝/规范化必须有计数、字段路径、原因和原始引用；规则baseline与SDK调查不可混淆。
4. 类型转换不创造证据、不提高可信度；有claim文本不等于源码事实成立。
5. 已确认目标与已解决答案持久继承。新一轮不能无依据还原为开放问题；目标变更或新事实使旧决定不适用时，显式标记受影响的决定失效及原因，不沿用旧授权。
6. 事实充分且已授权编辑的票必须进入修复尝试，或给出可审查的具体工程失败/新阻断；不可只输出一组等价技术选项。
7. 不为修复率绕过源码、范围、补丁可应用性与验证门槛。applyFix=false始终零编辑。
8. 无法保证外部SDK永不出错；工程保证是局部故障隔离、可恢复、可诊断与不静默丢失，不是网络/磁盘永不失败。

## 3. 契约与模块

生产产物统一升级0.4.0（defect-batch/code-knowledge/analysis-report/attempt），同步常量、Literal、导出、prompt、解析、CLI/HTTP、fixtures和样本。原始CSV/RawDefects输入格式保持原职责；旧归档只供离线取证，不喂进新生产链。

现有contracts/repair.py增加最小嵌套类型：QuestionAnswer、QuestionResolution、PreviousAttemptContext、AnalysisSnapshotRef。Question复用现字段，增加category（product/fact/implementation/follow_up）、status（open/answered/resolved/reopened）、predecessorId和newEvidenceRefs。kind继续表达当前阻断语义，不以category直接授权。

contracts/code_knowledge.py增加InvestigationFact（claim、reference可空、validity=unverified默认、source=model_reported默认）、ParseIssue（fieldPath、reason、action、rawRef）及SDK交接状态。Fact引用只说明来源，source不得由模型自报tool_observed；验证后才能升级validity。

新增模块限定为：

- sdk/match_payload.py：仅负责不可信模型响应到交接结构的规范化/分层校验。
- agents/cartographer/investigation_store.py：组原始响应、解析诊断、进度、缓存/恢复记录。
- agents/analyst/analysis_store.py：不可覆盖逐票分析快照及索引。
- agents/analyst/feedback_document.py：用户可填写文档的生成/导入。
- agents/analyst/continuation.py：组装previousAttempt、合并答案、校验问题收敛。复用现revisions/feedback/sessions，不建立第二套会话系统。

关键字段进一步约定：InvestigationFact.reference为可空CodeReference（repoId、path、revision/contentDigest、snippet，行号可选），validity仅为unverified/reference_verified/rejected；reference_verified只证明引用吻合，不证明claim因果成立。规范化字符串默认reference=null、unverified。MatchCandidate.source扩展model_reported用于无工具来源的模型线索，不把未知来源伪造为grep。

AnalysisSnapshot包含ticketReport、effectiveRevision、workspaceSnapshot、questionResolutions、parentAttemptId和digest；AnalysisSnapshotRef为path/digest/attemptId。InputRevision保存questionAnswers和questionResolutions；每个QuestionResolution记录resolutionSource（user_answer/agent_decision/existing_rule）、适用targetDigest及产生决定的revisionId；user_answer须关联非空answerRevisionId，其它来源可空但必须有决策/规范依据，不能伪造用户答复。不能只存在SDK聊天里。PreviousAttemptContext与ConvergenceResult字段以第6/7节为准，T0必须先固定JSON形状。

类型在原契约模块集中定义；不要每个字段建模块。各文件职责是边界处理，不重写run_analyst和修复循环。

## 4. Agent2：先保全，再分层接受，再评调查质量

### 4.1 原始产物与诊断

目录建议：`agent2/groups/<groupId>/attempts/<callId>/{response.json, transcript.jsonl, parse-result.json, manifest.json}`。callId唯一；manifest关联输入摘要、仓HEAD/内容摘要、模型/技能/协议摘要、预算、启动/结束、终止原因、turns、估算cost、SDK/CLI版本。transcript保存SDK实际公开的消息/工具结果，不捏造隐藏推理；设置文件大小上限并记录truncated与原始文件引用，不能悄悄截掉最后JSON。

SDK流式消息到达时增量保存可见文本、structured_output、工具结果和终止/异常事件；不能等正常ResultMessage才开始写，异常退出也能回查已收到的内容。尚未从外部SDK收到的数据不在保全保证内。response保留structured_output、最终文本以及解析器可能采用的全部候选文本；有界格式修复的结果作为新响应保存，不覆盖初始响应。诊断文件不默认回显凭据/环境账号；目录按现有产物权限管理，外发包另走脱敏，脱敏后重算digest。只在manifest落盘成功后更新latest指针，使用原子replace和现有文件锁语义。磁盘不可写时保留能返回的合法结果及artifact_error，但不缓存成可审计完成；正式SDK运行不能无持久化目录：工作流有out-dir则复用；未指定时派生workDir/.bugfix-runs/<runId>/artifacts，并在结果/CLI输出中给出路径。该目录排除源码指纹；不可写时允许指定外部out-dir或明确失败，不静默跳过。直接调用SDK适配器由调用方提供同等存储上下文。

### 4.2 解析隔离边界

顺序固定：候选信封识别→请求范围/重复ID→逐票标量→逐字段→逐候选/事实→文件/符号核验→合并。先检查业务信封结构，不能仅因structured_output或末尾一段是可解析JSON就停止搜索：例如工具结果JSON、空对象不能遮住更早的有效调查。无法解析任何合法信封时保存全部原文/错误，才进入一次有界格式收尾；不从残缺JSON里猜票号和事实。

身份隔离以条目/歧义票为边界：缺ID、组外ID及非对象条目只隔离自身；重复ID的所有版本保全并隔离该票，不用first/last wins，也不让其它唯一合法ID一起失败。格式收尾可只要求补齐歧义票。候选越界路径只隔离该候选。模型不得覆盖程序持有的product、仓库映射、输入票身份、运行配置和权限。

多份有效输出不盲目全量替换：只处理选定的主调查输出及其一次格式收尾，不把聊天中的每份草稿汇成通用冲突库。同一次调用内先保留已接受且无冲突的字段，格式收尾只补缺/修坏；对已有值的实质更改必须有显式更正关系，冲突值保留诊断、相关字段降为待核实，不能把前一份合法调查清空。跨调用仍按显式父调用/恢复清单合并，保留每个字段的rawRef。

可选字段规则：

| 输入 | 处理 |
|---|---|
| facts中的非空字符串 | 转为claim文本，source=model_reported、validity=unverified，记facts_coerced |
| 合法facts对象 | 保留信息并按Fact契约校验，不能让模型声明已验证 |
| 数字/布尔/空串/嵌套数组或坏facts对象 | 单元素隔离到diagnostics；不str()伪装观察 |
| 单个坏candidate、非法source/不存在路径 | 隔离该候选；其它候选、facts、ruledOut不丢；缺source可用明确model_reported来源，不伪称grep |
| 可选字段null/缺省 | 按契约空值并记缺口；不补造调查内容 |
| 字段类型完全错误 | 隔离该字段并保留rawRef；不可覆盖同票其它合法内容 |
| 未知字段 | 原始响应保留，诊断记录；不升级为授权事实 |
| confidence非法 | 降为low并记录，不能因此丢整票 |

同样的隔离覆盖共享架构/techStack/modules等增强字段和最终CodeKnowledge组装：基线先独立验证，SDK各增强块校验后增量合入；坏module或未知共享字段不能抹掉逐票调查。最终严格校验若发现可归属的输入问题，隔离对应块后重验一次；若是内部契约/程序错误则标internal_error并保存已接受的typed逐票交接及诊断，禁止外层except把它们静默换成纯启发式成功。修复契约错误后可离线重放已保存响应，不必重新付费调查；这不是旧生产契约兼容。

生产产物保持严格类型。模型响应适配器只执行明确允许的转换；不解析任意自然语言为确定根因。无合法调查内容的票标failed/partial及具体原因，规则候选可单独作为search_draft传递，但不能挂“SDK有效调查”来源。

如果整组无可用结果或影响关键调查的字段缺失，最多一次、2轮的同会话格式收尾（也受整批预算约束）。不给模型重新全仓探索；要求按完整JSON schema返回已获得结果。仍失败时交付可保留内容、失败原因和下一步，不循环重跑。SDK支持结构化输出时用同一schema；不支持时走明确记录的文本解析，不为适配调用重跑整个业务会话。

### 4.3 complete、缓存与续跑

保留既有investigationStatus含义：complete是“约定前置调查已交接，有可追溯代码观察或有实际检索范围的搜索记录”，不是根因已证实；partial为有用内容尚有关键缺口；failed为调用/协议不可交接；not_investigated仅表示未启动。禁止仅因raw ID出现或facts非空设置complete。

判定complete至少满足：请求内身份明确、必需交接字段有合法值、当前代码/搜索引用可追且没有影响交接的未解决协议冲突。reference_verified由程序核对repo/path边界、当前revision或contentDigest及非空原文snippet；只有path/符号/文件存在不能证明代码观察成立。它仍不证明claim因果。候选根因未知不妨碍一次真实前置搜索complete；关键响应缺失或预算截断未收尾时仍partial。

searchedScopes区分模型自述与观察到的Read/Grep/CodeGraph工具调用。工具调用只证明查过范围，不证明每票机制；模型应把票与范围/引用关联，不能把全组工具列表自动分给每张票。空候选且确实搜索过可完成，不强填路径。

完整组缓存与阶段进度分开：partial的合法成果保存到journal，恢复时仍标partial，不能作为complete缓存命中。恢复清单包含待处理票/组；同输入、代码、模型、技能、schema/归一化协议才能复用，变化后保留历史并标stale。完成组跳过、失败组可单独重跑，partial可仅做收尾/指定票补查；不能每次从第一组重新耗尽预算。显式传入resume目录/票范围，不扫描“最近目录”猜身份。

模型调查覆盖状态与SDK接受/存储状态分开记录：partial可同时带artifact_error；不能用complete掩盖审计缺失。planned集合按唯一票计，阶段分区为未启动pending、已启动未终结running/interrupted、已终结complete/partial/failed；launched/accepted是可重叠过程计数而非互斥分类。模型未返回某张已请求票时记该票交接缺失，不继承为not_investigated。子集恢复继续合并全量历史，不以本次子集覆盖其它票。

主manifest记录planned/launched/accepted/complete/partial/failed/pending票数、stopReason（completed/time_budget/group_budget/cost_budget/sdk_error/output_invalid/artifact_error/internal_error），每组及整批账单/缺失项分别记录。成本是SDK估算，缺值保持unknown；不得用截断detail充当唯一状态。

## 5. 用户反馈：在产物里直接填写

每轮默认生成 `defects/<id>/attempts/<attemptId>/feedback-form.md`，并在完整报告给出逐票链接/填写区；票级最新链接只是便捷入口，不能覆盖历史表或用户已经填写的文件。初始表保留绑定与题目模板，导入时另存用户填写原文。文档分为只读摘要、逐问题答复、预期修正、其他补充、附件引用、补丁应用/验收状态。技术性等价选择不生成用户必答题。

系统携带product、defectId、attemptId、baseRevisionId（表所基于分析的revision）、analysisDigest、questionId；用户不新建JSON、不手工维护ID。`feedback --file`接受生成的Markdown及内部JSON；Markdown输入只读取标记的答复区，不把编辑报告正文当反馈事实。统一生成内部Feedback：questionAnswers、text、expected/observed/steps、kind等；kind仅辅助，明确字段与原文都保存。

schema形状示例（用户只填空白）：

```text
问题 Q-xxx：开启ONVIF应跳转到哪一页？
你的答复：

当前期望：<系统展示>
如需修正，请填写：
其他补充：
附件路径或链接：
补丁应用/验收反馈：
```

导入必须用存储中的不可覆盖快照校验票/attempt/revision/digest和questionId。Markdown“只读/隐藏”只是展示约定，不是可信保护：题号、题目和绑定从快照恢复，不信任用户文件自行声明；analysisDigest指向规范化快照内容摘要（不含digest字段自身），reportDigest仅用于派生报告评测绑定，两者不混用。旧表在新轮已存在时默认报stale并给出新表及差异；本次只支持单票串行续修，不新增分支创建/合并产品。已有旧revision只供读取历史，不静默套到latest。相同导入内容按formId/规范化答复区内容摘要幂等（只统一CRLF/LF，不抹去代码片段内有意义的空白；展示区不计入），新内容生成新feedbackId。表中baseRevisionId始终绑定原分析；内部Feedback.parentRevisionId由导入器在锁内取同父attempt的最新有效反馈revision，首份才取baseRevisionId，避免第二次导入又从首轮重建。新答复按questionId显式覆盖其有效值并保留旧版本/来源；空白不撤回旧答案，需要显式清空。原始表和内部Feedback均保存。空白不清空原字段，明确“清空”才走clearFields；附件删除继续显式表达。异常文档/缺身份/重复答复冲突要返回可填写的错误，不触发分析，更不授权编辑。

CLI先完成，HTTP不额外开发新反馈产品页面；若以后提供接口，复用同一导入与续跑服务。`resume --execute`继续只报告，`--apply-fix`才授权修复；用户填写“同意方案”也不自动覆盖执行模式。

## 6. 不可覆盖快照与previousAttempt

每轮保存 `defects/<id>/attempts/<attemptId>/analysis.json`：完整TicketReport、当轮有效InputRevision、目标、claims/questions、候选顺序/片段、ruledOut、方案、验证范围、模型/技能摘要、仓库快照及引用。AttemptRecord增加analysisRef/digest，已有patch/checks引用继续复用。首轮也保存，不能只保存resume之后的rounds文件。

沿用现有产物根锁，不另建分布式事务：在同一锁内写入analysis.json、attempt.json及初始反馈表，全部就绪后原子replace latest提交指针；同attempt同digest重试幂等，不同digest禁止覆盖。提交前中断产生的孤立目录可诊断/清理，不视为完成；提交后汇总/Markdown写失败只标派生视图待重建，不撤销已提交分析。反馈导入的父版本检查、保存revision、更新feedback-latest同锁完成；resume先检查本次revision对应的父attempt，运行与提交沿用现锁，另一导入/续跑返回busy，禁止两次latest互相覆盖。导入多个不同内容后再运行时，revision显式累计先前补充，父attempt仍绑定产生该表的轮次；不能把“反馈revision更新”误判成“分析attempt已更新”。进程异常遗留锁只允许校验持有进程/运行状态后显式恢复，不按任意超时抢锁。

JSON/Markdown完整报告是这些逐票真源的派生视图，重建不改变历史。sourceRoot路径不作为唯一长期证据；保存必要引用/摘要，不复制整个业务仓或全部秘密配置。

`AnalyzeRequest.previous_attempt`与feedback上下文显式进入 `_build_prompt`；`FixRequest.analysis`接收同一信息。包内容至少包含：

- attempt/revision/digest、当时仓HEAD/contentDigest及当前对比结果；
- 首轮outcome、topCandidates、rootCause摘要、关键claims/状态、ruledOut；
- 原方案、未决问题与答案处理结果、用户已确认目标；
- 最新反馈kind/原文、否定的假设、当前补丁应用状态和引用。

提示词优先级：当前用户明确目标/答案→适用规范和业务skill→已有代码事实→历史假设/方案。历史结论不能代替本轮证据；HEAD相同仍核对内容摘要/dirty，源码变化时旧代码证据标historical，重新读取相关处。用户否定假设后不可原样继续该假设的修复。

SDK会话是性能优化，不是唯一上下文存储。resume/fork/new均载入上述包；恢复失败记录降级并新开，不能丢掉首轮分析。选择父attempt来自显式表单绑定并校验当前串行链，不能以latest猜测或覆盖它。包摘要保留关键来源，完整分析可按analysisRef读取，避免无限重放所有历史消息。内联包中的当前目标、全部未消费答案、否定假设及剩余阻断不允许摘要截掉；完整快照须由实际SDK Read能力可达，不能只放一个相对宿主机、会话不可读的路径。预算不足以载入必要上下文时标context_budget/analysis incomplete，不能遗忘答案后重新提问。模型返回缺evidenceRefs/未知引用/坏问题结构时保留原始输出与诊断、复用一次格式修复，只能引用实际本轮证据；仍失败记工程分析失败，不代用户生成choice，也不造证据放行。

## 7. 决策事权与二轮收敛

### 7.1 默认策略

| 类别 | 默认责任/行为 |
|---|---|
| 等价技术实现、改哪个函数、复用何种已有组件 | Agent按代码/业务skill/最小改动决定，并记录依据；不作为choice上交 |
| 明确验收行为之间有实质分歧 | 用户决定，choice；说明各答案如何改变验收，不能只问“走哪条路” |
| 现场事实/接口结果/控件位置不足 | 先查已有原文、代码、历史反馈；仍必要才blocking补证 |
| 当前因果与方案不变，仅需实机回归 | verification，不一律阻断进入修复，但不得声称验证已通过 |
| 其它端、语言或附带健壮性优化 | follow_up；除非用户明确纳入，默认不扩本票范围 |

applyFix=false并不强制actionability=false；报告可以是可实施方案，但编辑runner仍不得调用。choice只能由验收目标/产品行为的实质不确定性支撑。用户答“按现有规范最小改动”是明确授权Agent做技术决定，不得换一组等价技术选项再问。

### 7.2 问题账本和答案消费

Question ID由程序生成并稳定保留；每轮模型要关联前题（predecessorId），不能自己重置Q1身份。账本状态：open→answered（原答已收到）→resolved（明确消费并写处理结果）；发现实际矛盾可reopened。answered不等于自动完成：如答复“随便”未提供必要事实，可说明具体缺口继续澄清，不能谎称已补齐。

每轮对新答案及状态变更写QuestionResolution（不重复生成未变历史记录）：questionId、resolutionSource、revisionId、answerRevisionId（用户答案时必填）、targetDigest、disposition（resolved/insufficient/conflicting）、resolutionSummary、evidenceRefs。用户产品选择与待核实事实分开，用户陈述不自动标源码valid。每条答案记录原文/来源/对应revision，QuestionResolution还记录适用目标摘要及依据；只继承仍适用于当前目标的决定。修改expected不一概重开全部旧题，仅对受影响的决定显式重开；没有用户答案时，产品choice不能由模型仅写resolved通过，除非既有明确业务规范已唯一确定行为并给出依据。实现类问题自主解决也须写具体采用方式与理由，不能只改category/status消除门槛。

在现有分析收尾增加一次有界决策校验（复用同会话、最多2轮，不加Agent）：

1. 消费所有新答案；明确当前目标、否定假设、已解决/剩余问题。程序必须从父快照携带完整问题账本；模型遗漏旧题不能令它消失。每条旧blocking/choice须显式保留或有对应resolution，每条新题须给阻断验收/机制的依据；不能只检查模型本轮主动列出的题。
2. 按默认事权处理implementation/follow_up；有依据可自行决定则形成具体方案。
3. resolved问题不得再开放；若重开必须关联旧题、说明矛盾/新证据。新依据可包括首次发现的既有源码冲突，但重复读同一文件或新时间戳本身不算。仅换ID/措辞不能当新问题；真正新问题允许没有predecessorId，必须解释本轮首次发现的阻断依据。
4. 对关键缺口仍存在的票，输出可审查原因、已做调查、最小补充请求；没有格式/消费结果则记analysis incomplete，不输出“用户还得选择”的伪业务阻断。
5. 目标明确、当前代码证据有效、真正阻断已解且授权编辑时进入现有fix loop；未授权时只交可实施报告。

编辑门槛只对未resolved的blocking/choice生效（open/answered/reopened）；模型写resolved但没有对应有效QuestionResolution仍不能放行。程序可强校验ID、答案引用、重开理由、证据是否属于本轮及旧题是否被消费；不能完美识别任意语义改写或裁判因果。相近问题复述、无意义新choice属于真实模型评审项；不得把一次fake回“resolved”当已证明业务收敛。

### 7.3 输出与限制

复用analysisStatus/actionability/blockers，在报告中清楚显示“可实施”“待业务决定”“待事实证据”“分析失败需重试”，并列每轮解决/新增/重开问题和已采取决定。unknown schema/SDK解析错误是工程阻断，不伪装成业务choice。verification不等于可忽略所有假设：会改变根因/目标文件/修法的分歧应blocking或choice，而不是贴verification绕过门槛。

格式修复每个主调用最多一次、最多2-turn；决策收尾每票每轮最多一次、最多2-turn，二者复用已有会话并共享本轮剩余turn/cost/time上限。原有budget salvage计入格式修复，不能叠加；没有剩余额度就保存partial/incomplete与停止原因，不新会话重置预算。收尾成功后仍调用原fix loop，不再发起第二次分析循环。

不设“二轮必须改码”的轮次数规则。有效约束是：信息充分且授权时必须尝试，不能无依据重新抛题；不充分/不在仓/环境无法验证时如实阻断。最多一次收尾修复后仍矛盾则明示失败，禁止自动无限对话/编辑。

## 8. 工程验收与真实效果分开

### A. 工程硬门槛（可离线验证）

- 合法信息在混合坏字段/坏候选/坏事实/坏共享架构、错ID邻票及后续收尾响应中不被连带丢弃；最终组装失败亦可离线恢复已接受调查；流式异常前已收到的内容及诊断可读。
- 身份错/范围错/重复ID不错误合并；无来源字符串facts不会因转换直接complete；scope记录来源准确。
- SDK真实适配链中的禁止写Bash被执行前拦截；不能只直接调用callback函数证明限制生效。
- 首轮快照、生成反馈表、导入、父版本绑定、previousAttempt和答案状态贯穿CLI及SDK prompt；恢复失败仍带完整包。
- 用户明确回答后不因旧题遗漏、摘要截断或换会话重问；目标变化只失效相关决定；旧答案被新证据推翻有完整记录；错误/不足答复不自动授权。并发/中断、篡改绑定、首轮/多次导入均有覆盖。
- 隔离小仓有真实缺陷、有效源码证据、明确产品目标：报告模式零编辑；修复模式确实修改隔离副本、生成可应用PatchSet、运行真实断言验证修复。fake仅承担模型边界，不证明业务判断。
- 最终候选验证/语义复核/旧补丁应用状态/源码漂移等原有门槛不退化；整票失败不抹其它票，汇总报告可从逐票快照恢复。

### B. 模型与真实业务验收（不得由A代替）

本批18票没有实际用户补充后的运行，不能据此断言二轮已能收敛。先冻结三项目8—12张报告/反馈试点票，再扩展至少20张经业务独立标注的可修票；样本小或材料不齐则只报初步结果，不宣布通过。包含：确有产品choice、只是技术选择、截图/接口事实缺失、非当前仓、用户否定首轮假设、关键资料补齐后二轮进入修复。首轮/二轮同票比较，记录模型/实际能力、预算、技能、HEAD/dirty/内容摘要与成本；不混改模型与代码后宣称单变量因果。

指标固定：

- 全部入选缺陷验收成功率 = 实际验收成功的缺陷 / 全部入选唯一缺陷；同时列排除原因和待验，不能由Agent把难票移出分母。
- 可修票验收成功率 = 独立业务评审预先判定“当前仓、目标和证据充分、具备约定验证条件”的票中实际成功数 / 该固定子集总数。若二轮补齐后才满足条件，按预先规则入该子集，保留前后分母/时间戳，由业务评审确认。
- 二轮推进：分别计已足量反馈票的修复尝试数、可应用候选数、实际验收成功数；不把进入fix/allowed=true算修复成功。
- 问题收敛：有效答案消费率=本轮被明确处理且处理合理的有效答案数/本轮有效答案数；无新依据重复提问率=人工判定无新依据重复的本轮必答题数/本轮全部必答题数，另列受影响票数。零分母为null；按题与按票不混算。新增/重开理由、用户审阅时间另列，不只比较问题数量，合理补证不判坏。
- 成本：首次/二轮、Agent2/3分别记录已知SDK估算与缺失账单、耗时、人工介入；记录停止原因。

**70%只作为可修票业务验收成功率的试运行提议，非已经确认的SLA，也不承诺现有模型达到。** 实施后先试跑建立基线，再由业务评审确认目标、样本和验证条件；未确认或样本不足不作业务通过结论。不得验收后改分母/路径真值来达标。

未应用/未验收标pending，不算成功，也不伪称已证失败；同时展示成功/失败/pending及成功数/固定总数的保守值、成功数/已验收数的观察值，避免只验容易票制造成功率。每条评价绑定product/defect/attempt/reportDigest/claimIds（适用时），stale不沿用。报告模式样本不统计修复率。

## 9. 优先级和交付分界

P0：Agent2原始保全/分层解析/状态及SDK只读路由；Agent3逐轮快照/填写反馈/首轮上下文/答案消费与事权；正式入口闭环与回归。P1：真实规模下的成本调优、评测工具/模板、受控真实试点。阶段恢复和失败账单记录属于P0可靠性交付。真实模型/业务验收是独立交付门槛，不因“P1”可跳过。

第一里程碑为工程链路可靠；第二为真实模型能正常交接并处理答案；第三为固定业务样本的修复验收。只有第一项通过时仅报告工程完成，不能宣布稳定修复产品交付。详细依赖和任务验收见实施计划。

## 10. 本次完整复审记录（2026-11-17）

复审结论：原方向保留，但不能把“转换facts”和“增加previousAttempt字段”当彻底解决。补齐以下缺口，实施验收据本修订版执行：

| 发现 | 本次修订 | 验收任务 |
|---|---|---|
| 身份严格校验仍整组拒绝，合法邻票可能被丢 | 只隔离错误条目/重复歧义票，唯一合法票继续交接 | T2/T9 |
| 坏共享架构、首个无关JSON、最终总契约异常仍可全量退baseline | 信封识别、增强块隔离、accepted中间产物与离线重放；禁止伪成功回退 | T1/T2/T3 |
| 只在正常结束落盘，预算收尾可覆盖首份有效内容 | 流式增量保全；收尾补缺、冲突可追；失败也保留账单 | T1/T2/T3 |
| 表单覆盖、绑定可信度、latest原子性与并发规则不足 | 逐attempt表单、真源校验、统一锁与提交顺序；本期不做反馈分支 | T5/T6/T9 |
| 旧题遗漏/目标改变/答案摘要丢失仍可导致重问或错误放行 | 完整账本覆盖、决定适用性、关键答案必载、真实Read可达 | T7/T8/T9 |
| A3协议失败可能仍伪装业务阻断，收尾预算可能叠加 | 显式工程失败、一次格式修复复用现salvage、共享预算、直接进入原fix loop | T7/T8/T9 |
| 只靠fake与题数下降不能证明业务收敛 | 控制链硬验收与真实模型语义/修复验收分离，指标口径固定 | T9/T10 |

不为“彻底”作网络/磁盘、任意模型响应及语义判断永不失败的承诺。可验收承诺是：合法已收到内容可追、局部坏输入不连坐、故障不伪成功、必要答案不静默遗忘、证据充分且授权时正式入口确实尝试修复。真实修复比例仍须固定业务样本验证。
