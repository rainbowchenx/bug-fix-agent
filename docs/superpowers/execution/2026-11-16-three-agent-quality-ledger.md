# 三 Agent 优化实施与逐项验收

方案日期：2026-11-16；收尾日期：2026-11-17。状态：工程实现及离线验收已完成；真实模型与业务效果验收待执行。最终测试结果见本文末尾。

关联：[修订方案](../specs/2026-11-16-three-agent-evidence-quality-design.md)、[实施计划](../plans/2026-11-16-three-agent-evidence-quality-implementation-plan.md)、[本批复评及运行边界](../../field-eval/agent3/reviews/2026-11-16-three-agent-real-project-assessment.md)、[24票表](../../field-eval/agent3/reviews/2026-11-16-ticket-reassessment.csv)。工程完成不代表这些业务票已经重新分析或修复。

## 基线、范围与执行约束

- 基于 main / `d6681858f838dcd25fc30f0b7b783456556fe58f`。开始时工作区已有大量行尾变动；保留既有修改，原位实施，未重置、提交或推送。
- 交付包 SHA256 已现场复算：`f0e2398b1a5e23a2e906761724ce36e65f7ed4b9a8a13176535e8a9857fb44c1`。只读分析包，不运行包内脚本或 pickle。
- 四线24票属于报告评测，原运行约256K文本模型、applyFix=false。历史账本主路径17/24、含Alt 18/24保留；不是根因或修复成功率。
- 契约统一升级 `0.3.0`（含 attempt）；生产拒绝旧 Agent 产物。raw-defects 是输入适配载荷，不承担历史 Agent 输出兼容。活动 fixtures、导出脚本、样本和文档已同步。
- 新增共享 workspace_fingerprint 工具供调查缓存与修复快照复用，避免 Agent2 依赖 Agent3 内部模块。未引入新 Agent、数据库或并发调度系统。
- 测试使用 Windows Python 3.12：pydantic 2.14.3、pytest 9.1.1、claude-agent-sdk 0.2.182、langgraph 1.2.20。Linux 系统 Python 不具备完整测试依赖。

## 按任务及验收标准自查

| 任务 | 工程结果 | 实现与验收证据 | 仍需现场确认 |
|---|---|---|---|
| Q0 证据/共享契约 | 完成 | `tests/fixtures/repair_quality/manifest.json` 记录来源及使用边界；`test_quality_evidence.py` 验证 JSON 往返与旧版本拒绝 | 历史人工评语不当新真值；尚未取得原始完整工具轨迹 |
| Q1 原文保全 | 完成 | sourceDocument 保存原始 Unicode/空白、SHA256、业务列与 section offsets；ingest→A1→SDK prompt→报告可追溯。`test_source_document.py`、`test_quality_report_flow.py` | 真实CSV/Excel各种导出格式、受权限限制的回放/截图可用性 |
| Q2 质量及筛选 | 完成 | expectedOrigin 与 relevance 分离，默认 uncertain；已有 intent review 可显式写 conflicting。C1c 排序反向、C1e 缺少错误提示不误挡，needs_info 仍保留。`test_input_quality.py` | 04188/03610 等语义错配是否实际被模型识别；程序不假装通用中文矛盾检测 |
| Q3 反馈及目标 | 完成 | merge_revision 继承完整字段/累计补充，显式清空与附件撤销，父链与同ID冲突校验，latest指针原子更新。`test_revision_targets.py`、正式CLI报告续跑集成 | 09314 真实模型是否持续遵守移除目标、附带风险是否抢占主任务 |
| Q4 问题门槛 | 完成 | blocking/choice 阻断，verification/follow_up 不一律阻断；openQuestions 派生。SDK漏字段一次有界修复，失败 incomplete；needs_info 首轮最多8轮且不超过显式预算。`test_question_gate.py`、`test_analyze_sdk.py`、入口集成 | 模型分类是否合理，是否把真正阻断问题误标 follow_up |
| Q5 因果与报告 | 完成 | Claim 状态/假设/引用保留；未知引用、非本轮 valid Evidence、源码漂移降级；不完整输出保留已解析事实。报告显示当前目标、analysisStatus、actionability、附件是否读到。`test_claim_report.py` | LED04084/02007/04762 的设备、时序、样式因果；引用匹配不证明因果 |
| Q6 分组调查 | 完成 | 默认8、上限16，37票正式入口5组；仓图后续复用；组外/重复ID拒绝；失败组不抹其它组；预算只计新组；完整组按代码/票面/地图/技能/模型/预算配置缓存。`test_investigation_batches.py`、SDK账单回归 | 实项目重复读码时间/成本、8票分组是否合适、实际资料下事实质量 |
| Q7 技能/模型观察 | 完成 | 显式目录/allowlist 支持无profile技能；发现/拒绝原因、正文注入、成功Read结果与applied区分；约1M声明不自动 verified，smokeStatus=not_executed。图像不支持不误记 max_turns、不反复恢复重试。`test_runtime_profile.py`、SDK适配器测试 | 真实模型成功读取图片和业务skill；SDK/服务端实际支持的窗口、工具、模态 |
| Q8 可信评分 | 完成 | reportDigest/产品/票/attempt/claim绑定；stale保留诊断但排除主评分；无绑定不计人工验收成功。主路径与Alt分列；SDK失败与诚实性分开，失败继承候选不计完成分析定位。主locAt3保留历史端到端目录覆盖口径，completedAnalysisLocAt3另列；后者也不冒充Agent3独立新增定位率。`test_claim_ratings.py`、`test_eval_agent3.py` | 重做陈旧评语，人工逐主张裁判；字段齐全不算根因正确 |
| Q9 正式入口 | 离线工程完成，真实运行待验 | `test_quality_report_flow.py` 贯穿原始输入→A1→A2→A3→feedback→resume --execute→全量报告；原文、目标、问题与代码不变/零编辑器调用均断言；原有补丁隔离/回修回归继续执行 | 固定8—12票、正确模型配置、完整工具证据与业务人员复评 |

### 重点边界检查

- [x] 原始前置条件、测试数据、回放URL、中文特殊符号/offset/hash保留；独立业务字段保留，人员字段不默认进入模型。
- [x] 非空expected不自动视为可靠验收；复杂冲突默认uncertain并允许已有语义审阅更正。
- [x] 连续反馈不丢父版本目标/步骤/事实；清空与未提供分开；撤销附件不删除历史。
- [x] 显式未知revision、损坏latest父链、相同feedbackId不同内容均拒绝静默回退；report与attempt引用同一revision。
- [x] `resume --execute`实际再分析并写round及全量报告，不调用fix runner；同秒轮次文件增加微秒避免覆盖。
- [x] 补充前needs_info可有限调查；不会为了调查数量把所有票自动升strict。
- [x] 仅有验证或跟进待项不永久挡编辑；blocking缺少relatedClaimIds也照常阻断。
- [x] 缺claims不被默认[]绕过SDK检查；未知/无效引用不能维持supported；源码匹配不自动支持设备运行假设。
- [x] 37票完整覆盖；预算耗尽如实保留未调查；失败组单独重试，完整缓存组不消耗续跑新组额度。
- [x] 输入、代码、技能、模型/endpoint、实际预算配置和导航地图进入复用键；不完整结果不能缓存成完成。
- [x] SDK返回组外/重复票拒绝合并；零候选但有搜索范围可完整交接；SDK自述调查固定model_reported。
- [x] skill选择、工具Read成功、实际应用分开；未读附件、未验证多模态能力不会声称已验证。
- [x] 旧评语stale不进入主评分；主路径/Alt与人工验收分别计数，空样本拒绝，重复case ID拒绝。
- [x] 快照复制与摘要共用.env/credentials.json排除规则，含.env的正式报告/续跑入口通过。
- [x] 完整tests目录运行，含contract、Agent1、platform、integration、打包/skill文档与CodeGraph测试。
- [ ] 真实约1M多模态SDK smoke：未运行，不冒充离线SDK返回测试。
- [ ] 固定8—12票业务对照与逐主张人工复评：未运行。
- [ ] 真实项目补丁应用/业务回归：不属于本批只出报告范围，另行验收。

## 独立审核及落实

进行了多轮只读实现复审。发现并修复：缺claims被补空绕过门槛、逐主张引用未绑定本轮有效证据、needs_info首次调查被入口跳过、调整生效预算仍命中旧缓存、stale仍参与主评分，以及显式未知revision/损坏父链回退、报告revisionId不一致。收尾又复现并修复快照复制/摘要对.env与credentials.json排除不一致：先观察新增快照测试失败，再统一共享排除规则，并用含.env的正式入口夹具复跑。每项对应新增行为回归或既有入口测试。静态复审不等于模型业务理解通过。

## 真实项目待验协议

使用[逐票表](../../field-eval/agent3/templates/ticket-review.md)、[批次模板](../../field-eval/agent3/templates/batch-evaluation-report.md)，优先选择04188、03610、09314、03691/11009071、02007、04762、06318、04084、01340等8—12票。

1. 固定业务HEAD/dirty、原始票/图、技能、预算及服务端实际配置，先验证模型工具和图像能力。
2. 原代码换正确模型与优化代码同模型分开对照；历史256K文本结果单列，不能将两个变量一起归因为代码收益。
3. 全程applyFix=false。评分原文遗漏、严重事实错误、因果过度断言、目标遵守、合理阻断/可行动性、重复调查时间/成本；本批不计算补丁成功率。
4. 每个评语绑定当前reportDigest及claimIds；图像读取成功和字段完整均不直接计根因正确。
5. 没有资料/环境时记录无法判断及具体补充请求，不填通过。真实补丁质量以后单独验收。

## 首次实施验证（复审前）

输出摘要：[测试结果](2026-11-16-three-agent-test-results.txt)。

命令：`py -3.12 -m pytest tests -q --tb=short -rs`（从WSL调用同一Windows解释器）。最终结果：**420 passed / 5 skipped，140.45s，退出码0**。包括CodeGraph的15项测试；没有通过全局禁用CodeGraph来隐藏失败。

5项跳过：4项引用仓外本地脱敏CSV、1项要求未提供的peitao业务仓。这些不算通过；包内脱敏资料并不等同于测试中指定路径的历史CSV。新增最小夹具与正式入口测试已执行，真实业务仓定位测试仍待现场。

代码差异检查使用`git -c core.whitespace=cr-at-eol diff --check`核对本轮源码，兼顾既有CRLF；没有将工作区全部行尾改动当本轮功能修改。首轮失败中的旧schema断言、旧needs_info禁止调查断言、集成夹具缺Git标记/Windows默认编码问题均已修正并在最终测试复跑。

真实SDK/模型smoke：**未执行**。SDK适配器使用受控返回及工具消息测试，不调用真实模型，不证明业务语义收益。无业务补丁应用或验收成功率结论。

## 2026-11-17 完整复审

本轮重新检查正式入口并直接修复遗漏，详见[完整复审与修复记录](2026-11-17-three-agent-implementation-review.md)。首次420通过不是本轮最终结果；以复审记录中最新全量输出为准。真实模型和业务待验边界保持不变。

本轮复审后最终验证：**437 passed / 5 skipped，141.78s，退出码0**。详见[复审结果摘要](2026-11-17-three-agent-review-test-results.txt)。
