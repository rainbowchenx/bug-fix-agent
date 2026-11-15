# Agent-3 方案完整复审

日期：2026-11-15。对象：[Agent-3 方案](../superpowers/specs/2026-11-15-agent3-repair-feedback-design.md)。范围：修复效果、过度设计、当前工作区代码差距。仅修改文档，未实施产品功能或运行业务修复评测。

## 1. 结论与已修改问题

方向成立，但初稿基础设施前置过多，对机制核实、编辑后复核及现有检索错误描述不足。已将优先级调整为：先形成可评估的单票修复链路，再完成批次和反馈，最后扩展规模化能力。记录完整不自动等于修复有效。

| 原问题 | 影响 | 修订 |
|---|---|---|
| SQLite、对象库、并发队列首期同时建设 | 延迟修复效果验证 | 文件阶段落盘、单写入；规模化能力延后 |
| 每个逻辑对象容易变成独立系统 | 状态维护成本过大 | 先作为 attempt JSON 内嵌结构 |
| 缺少编辑后的机制复核 | 编译通过但可能掩盖问题 | 最终 diff 对照预期、失败/正常/重试路径，必要时返回调查 |
| 测试通过未区分是否覆盖缺陷 | 原基线也通过的测试造成假信心 | 尽可能验证基线失败/候选通过，普通覆盖单独声明 |
| 所有修改目标必须已读 | 误挡新增文件 | 核实父目录、调用方、接口及新增必要性 |
| 两个无进展回合缺乏依据 | 复杂调用链过早终止 | 阶段进展解释、合理下一步和总预算兜底 |
| 强隔离作为唯一执行前提 | 宿主设备/Electron 环境难用 | 现成隔离优先；明确配置的宿主受控命令可用，不声称 OS 隔离 |
| 全部 Git 特殊类型与语义冲突检测首期必备 | 边角成本过高 | 普通源文件完整性先行；特殊类型明确限制，机械重叠检测 |
| 所有票先复制整仓 | 补单票也承担高成本 | 基线复用、按需工作副本、只读版本核对 |
| 文本摘要用于反馈去重 | 相同“未解决”可能是新测试结果 | 请求 ID 幂等，内容仅提示重复 |
| Agent-3 自动回调 Agent-2 | 循环调查与编排成本 | 自取证或接受新产物，自动调度延期 |
| 附件仅登记引用 | 可能凭文件名猜测图片 | 实际访问/阅读证据，不可读明确说明 |
| 效果评测排在全部底座之后 | 不能及时识别无收益复杂度 | 第一条纵向链路即对照，实仓材料随到随评 |

## 2. 当前代码复核依据

代码引用以文件及符号定位，均在本轮直接读取。不是只复述历史研究。

| 文件/符号 | 核实行为与改进方向 |
|---|---|
| [analyst/run.py](../../platform/bugfix_platform/agents/analyst/run.py) `run_analyst`、`_actionable_for_fix` | 非匹配池不进入报告；needs_info 不调查；摘要门槛不足。改为全量去向、有限补证与真实来源校验 |
| [sdk/fix.py](../../platform/bugfix_platform/sdk/fix.py) 工具、prompt、worktree、diff | 禁止测试；非空 diff 即 patch_ready；从 workDir HEAD 建树、旧目录直接复用、新增文件不含于 diff。需执行反馈、正确基线与补丁完整性 |
| [sdk/analyze.py](../../platform/bugfix_platform/sdk/analyze.py) `_sanitize_candidates`、prompt | catalog 路径无条件剔除；图片段视作已读。需入口例外与当前源码复核 |
| 同上 `AnalyzeRequest.max_turns`、resolver | 默认24作为 explicit 传入，遮蔽环境配置。需统一优先级及生效记录 |
| [sdk/codegraph.py](../../platform/bugfix_platform/sdk/codegraph.py) `ensure_codegraph` | ready 不证明索引与工作树一致。关键片段必须核对，无需首期新建索引管理平台 |
| [sdk/cartography.py](../../platform/bugfix_platform/sdk/cartography.py) `MAX_PROMPT_TICKETS`、`select_prompt_tickets` | 最多16票进入本次 prompt。需小批覆盖或明确未调查，不能全批完成掩盖逐票差异 |
| [sdk/skill_inject.py](../../platform/bugfix_platform/sdk/skill_inject.py) discover、excerpt | 同名全局覆盖、正文截断2400字符。复用发现机制，补作用域和完整读取 |
| [cluster.py](../../agent1/bugfix_agent1/defect_batch/cluster.py)、[expect_quality.py](../../agent1/bugfix_agent1/defect_batch/expect_quality.py) | 未传原始描述；非空有效预期即 explicit。原文保真和预期一致性需改进 |
| [http/store.py](../../platform/bugfix_platform/http/store.py) `write_meta` | 已有临时文件替换，可复用，不必先引入数据库 |
| [workflow/persist.py](../../platform/bugfix_platform/workflow/persist.py) | OSError 被吞；关键落盘必须失败可见 |
| [eval_agent3.py](../../packaging/eval_agent3.py) `score_ticket`、`summarize` | needs_info 调 SDK 判错；旧只读模式限制；notes 判执行来源；空集合可“可用”。评测必须同步修改 |
| [test_agent3_sdk_report.py](../../tests/platform/test_agent3_sdk_report.py) 改码成功测试 | fake_fix 验接线，不证明真实 worktree 生命周期。需临时真实仓测试 |

可复用：Python/LangGraph/SDK 分层、JSON 解析与契约验证、runner 注入、仓根/规范发现、CLI/HTTP 入口。差距在有效上下文交接、验证和反馈闭环，不需要重写全部系统。现有规范发现应在具体项目验证，不能把历史产物缺口一概当成当前没有能力。

## 3. 首期范围

必须：原文与关键证据、机制核实、正确代码基线、普通源文件补丁完整性、可执行验证与语义复核、全量报告、文件反馈续修、阶段恢复和保存失败可见。

延后：数据库、多写入调度、后台队列、全仓依赖图、通用语义冲突引擎、全面 plugin 迁移、默认独立 reviewer、自研沙箱、全部特殊 Git 类型、联合多仓编辑。

多仓定位以及在多仓容器中修复单一目标仓不延后。联合编辑未支持时明确说明执行能力限制，不误判仓库归属。延后项不影响报告和二次反馈主流程。

## 4. 审查与验证边界

修订稿经过一次独立只读设计审阅，未发现仍会阻碍实施的重大问题；这只表明设计逻辑可推进，不证明实际修复收益。最后检查本地文档引用、Markdown 结构和修订一致性。未运行产品测试、模型跑批或真实设备验证，最终业务解决率仍需后续三类项目材料与验收结果。
