# 三 Agent 优化实现完整复审

日期：2026-11-17（Asia/Shanghai）。范围：基于main `d668185`的当前未提交实现。10类问题已修复且通过最终全量回归，结果见本文末尾；不代表真实业务效果已经验收。

依据：[修订方案](../specs/2026-11-16-three-agent-evidence-quality-design.md)、[实施计划](../plans/2026-11-16-three-agent-evidence-quality-implementation-plan.md)、[首次执行自查](2026-11-16-three-agent-quality-ledger.md)。保留既有工作区改动，未提交或推送；未调用真实模型。

## 本轮发现与修复

本次重新沿真实CLI、HTTP、LangGraph、SDK解析/合并和报告落盘检查。首次420项测试通过仍有入口遗漏；增加绕过此前helper-only盲点的回归。

| 编号 | 级别 | 实际问题 | 修复及对应验收 |
|---|---|---|---|
| R1 | P1 | HTTP将applyFix=false改为None，BUGFIX_APPLY_FIX=1可覆盖只出报告要求 | runner原样传False。真实HTTP→工作流→Agent3测试默认false/显式false，禁止创建编辑runner，检查保存报告applyFix=false |
| R2 | P1 | HTTP/图节点捕获任意TypeError并删除参数重跑，可能重复分析，甚至去掉apply_fix授权边界 | 删除运行后猜签名的兼容重试；内部TypeError一次失败。SDK明确不支持resume时的记录/降级仍保留，这是计划内能力降级 |
| R3 | P1 | SDK先按ID字典覆盖重复票、先丢非法schema的组外票；调度器看不到原始错误 | 在_merge_enrichment进入coercion/by_id前检查原始ID和范围。重复/组外拒绝合并；错误输出保留已知SDK账单；缓存协议升v2 |
| R4 | P2 | Agent2的skillDiscovery.read恒False，即使SDK成功读取技能 | 成功Read工具结果→CartographyResult.skill_reads→分组汇总→正式manifest。只请求Read、错误Read不计成功；applied仍不由读取推断 |
| R5 | P2 | Agent3相对Read路径按进程cwd解析，且异常/无完整JSON时丢成功读取记录 | 按请求workDir解析相对路径；成功/部分失败/salvage均保留实际读取轨迹。SDK适配器覆盖相对/绝对、完整/不完整、成功/失败Read |
| R6 | P1 | 报告写附件read=true，但TaskContext仍按未读判断，误挡编辑资格 | 将实际读到的附件引用交给build_task_context；正式run_analyst回归检查报告与actionability一致。仅证明资料读到，不证明理解/视觉因果 |
| R7 | P1 | 单票异常时_exception_entry使用原始票，丢本轮expected/revisionId | 异常报告使用当前有效revision；异常隔离不改变用户目标/票身份 |
| R8 | P2 | 未知票号可导入孤立反馈，resume执行零票仍成功 | 有批次时先校验票号；未知票不执行分析、不产空round。无批次的独立反馈存储/会话预览保持原有明确用途 |
| R9 | P2 | C1c把单独“排行”/“bottom”标签当具体比较，豁免范围过宽 | 仅明确反向顺序、top/bottom对比或排序方向豁免。补“排行榜显示异常”负例和明确反向顺序正例；needs_info仍可有限调查 |
| R10 | P1 | resume读取旧analysis-report不校验版本，合并后可能静默当0.3.0保存 | 分析前验证已有报告及批次/知识；旧版本明确拒绝，失败不写新会话决策；已验证的全量报告再合并其他票 |

主要回归：`tests/integration/test_quality_review_hardening.py`（真实控制链、SDK适配器，模型query受控），`tests/platform/test_analyze_sdk.py`、`tests/agent1/test_input_quality.py`。已有分组、评分、CLI续跑、隔离补丁等回归一起执行。测试不通过预设“模型已经理解正确”来冒充业务效果。

## 逐项对照方案与计划

| 任务 | 复审后的工程结论 | 正式入口或证据 |
|---|---|---|
| Q0 | 类型/版本/证据索引接通；外部旧产物拒绝补齐到resume | contracts校验、R10、来源manifest及SHA256 |
| Q1 | 原文、业务字段、offset/hash、来源及附件引用可跨阶段传递 | CSV→Agent1及三阶段/反馈入口测试；原文保持不变 |
| Q2 | 质量与调查资格分开；收紧过宽排行规则 | Agent1 prepare/review、R9、needs_info有限调查回归 |
| Q3 | 完整revision继承与报告模式实际续跑接通；未知身份和异常目标不丢失 | feedback/resume CLI、R7/R8/R10、多轮及全量合并回归 |
| Q4 | 分类问题及编辑门槛接通；附件读取状态同步 | run_analyst、validate_edit_decision、R6；blocking/choice继续阻断 |
| Q5 | 主张/证据/条件状态与报告传递接通 | SDK JSON→normalize/bind→报告；片段匹配仍仅证明引用 |
| Q6 | 分组覆盖/预算/失败续跑/缓存接通，原始SDK身份在合并前校验 | run_cartographer→SDK→调度；R3；37票与缓存回归 |
| Q7 | 两个SDK的技能读取与manifest已接通，配置声明不伪装验证 | R4/R5；图像配置错误不误当max_turns；真实能力smoke待验 |
| Q8 | stale评语排除主评分、绑定当前版本，原目录覆盖与完成分析定位口径分开 | score_report及rating测试，独立复核未发现新增重大错误 |
| Q9 | CLI、HTTP和工作流的报告模式边界接通，内部类型错误不再删除授权重试 | R1/R2及正式入口测试；真实模型/业务阶段仍未验 |

## 遗漏和过度设计判断

本轮主要是已有能力未完全穿透SDK/入口，而非需要扩大架构。删除HTTP/图节点的TypeError兼容重跑，减小重复执行和授权丢失风险。继续使用现有顺序分组、文件缓存和SDK会话；未引入新Agent、数据库、后台调度或通用中文矛盾检测器。

保留的复杂度有具体用途：revision解决目标继承；结构化问题避免永久阻断；完成组缓存减少重复成本；逐主张证据防止把路径命中当根因证明。技能applied不自动判真，语义因果仍需模型和业务人员判断。没有新增HTTP反馈接口；当前反馈/报告续跑正式路径是CLI，符合“HTTP如提供续跑接口则复用”的边界。

## 需要真实项目验证

- [ ] **模型能力**：实际服务端约1M窗口、多模态输入、工具调用、图像成功读取；声明和离线SDK受控返回不算真实smoke。
- [ ] **固定8—12票语义效果**：04188/03610的错配、09314二轮目标、03691/11009071调查资格、02007时序、04762样式、06318旧评语、04084设备假设、01340模态错误，按资料选样。
- [ ] **业务技能效果**：成功Read之后是否遵循业务规范、能否按说明启动环境，不能用read=true当applied=true。
- [ ] **效率与预算**：真实大仓8票分组深度、重复读码时间、Token/费用、软预算收尾成本与缓存收益。
- [ ] **外部材料**：跳过的4项历史CSV与1项peitao仓定位测试，提供指定材料后再运行。
- [ ] **补丁效果**：真实补丁应用、业务回归和用户验收另测；本批applyFix=false不统计修复成功率。

对照协议：先原版本换正确模型，再同模型比较优化版本；冻结业务HEAD/dirty、票面/图、技能和预算，人工评语绑定当前reportDigest及claimIds。定位目录命中不作为根因率；无资料填无法判断。

## 验证结果

最终命令：`py -3.12 -m pytest tests -q --tb=short -rs`。结果：**437 passed / 5 skipped，141.78s，退出码0**。包含CodeGraph测试，没有通过全局关闭它隐藏失败。5项跳过仍为4项仓外历史CSV、1项未提供的peitao业务仓；不算通过。

独立只读复核：修补链路未发现新的实质回归，独立执行相关4个文件26 passed。源码差异检查和本地文档链接检查均通过。[结果摘要](2026-11-17-three-agent-review-test-results.txt)。

工程结论：修订方案/计划的当前工程验收通过；没有剩余已确认的本轮入口阻断项。真实模型smoke、业务逐主张正确性、实际成本和补丁验收仍未执行，按上节待验清单单列。未提交或推送。
