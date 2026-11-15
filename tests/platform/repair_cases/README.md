# Agent-3 修复闭环夹具

T00 基线：四类机制夹具，用来对照当前输出与限制。不含业务真值，不据此计算修复成功率。

| kind | 含义 | 当前限制 |
|---|---|---|
| `wrong_argument` | 参数传反，静态证据通常足够出候选 | 现报告路径默认 `applyFix=false`，只出 `plan_only` |
| `missing_failure_state` | 失败状态遗漏（有成功分支、无失败清理） | 无实机也可分析；不能把建议步骤写成已通过 |
| `needs_attachment` | 需要补图/日志才能区分修法 | 缺图不得杜撰；现 `needs_info` 会跳过 analyze SDK |
| `out_of_repo` | 行为不在本仓（外部组件/另一端） | 搜索无结果只能 `unknown`，不能凭关键词判仓外 |

评测：没有用户验收数据时 `repair_success_metrics` 的 `successRate` 必须为 `null`。
