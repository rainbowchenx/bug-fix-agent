# Agent-3 评估标准与判断标准

默认只评 **报告路径**（`--apply-fix` 关）。改码 / MR 另列，不和「分析得对不对」混成一个分数。

不要和 SWE-bench、Seer 直接比通过率：那些多半是「有失败测试的 GitHub issue」；这里是中文工单 + 设备 Web / Electron，经常没堆栈。

契约：`docs/contracts/v0.1/analysis-report.md`。  
对已有 `analysis-report.json` 打分：

```bash
python packaging/eval_agent3.py \
  --report /path/to/analysis-report.json \
  --cases field-eval/agent3/<run>/cases.json \
  --out field-eval/agent3/<run>/score.json
```

---

## 0. 评什么、不评什么

| 评 | 不评（本轮） |
|---|---|
| 过程是否诚实（有没有真的跑 SDK、有没有假装修过） | 本机测绿 / `verifyStatus=passed` |
| 定位是否落到真值目录（可复核的路径前缀） | patch 能否合并、MR 质量 |
| 结局桶是否分对（可修 vs 缺信息 vs 未定位） | 文案是否漂亮 |
| 根因是否说到代码机制（人审 0/1/2） | 和 SWE-bench 分数对比 |

一组评测先固定：同一 `defect-batch`、同一 `code-knowledge`（或同一次 `bugfix-platform run`）、`applyFix=false`。换仓图或换模型必须另开目录，不要覆盖上次 `score.json`。

---

## 1. 真值怎么标（`cases.json`）

和 Agent-2 一样：**能从仓里复核**，禁止凭印象。

每条至少：

| 字段 | 含义 |
|---|---|
| `defectId` | 对应报告里的票 |
| `expectPathPrefix` | 定位真值目录或文件前缀（用票面独特词 grep 仓，取命中目录） |
| `expectOutcomes` | 允许的 `outcome` 列表。报告路径下可修票应含 `plan_only`，不要写 `patch_ready` |
| `pool` | 来自 defect-batch；`needs_info` 单独判「不烧 SDK」 |
| `rootCauseMustInclude` | 可选。根因摘要应出现的词（代码符号 / 模块名），不是复述标题 |
| `why` | 人话：这条真值怎么从仓里得到的 |

可修票不要把 `unlocalized` 放进 `expectOutcomes`，除非你故意标「当前仓确实找不到」。  
缺信息票：`expectOutcomes: ["needs_ticket_info"]`，且不应要求路径命中。

模板：`field-eval/agent3/cases.example.json`。transport 三张票的路径真值可直接复用 Agent-2 的 `field-eval/agent2/2026-11-10-transport/cases.json`。

---

## 2. 四道门（判断标准）

先过 G0，再看 G1/G2；G3 必须人看。G0 任一票失败 → **整次 run 过程不合格**，后面的命中率不作数。

### G0 过程（必须 100%）

看落盘，不看口头保证。

| 检查 | 通过 | 失败 |
|---|---|---|
| 契约 | `validate_analysis_report` 通过 | schema 坏了还接着评 |
| 真跑 SDK | 应分析的票 `localization.notes` 含 `analyze=sdk` | `heuristic` / `sdk_fallback` 冒充分析；或 notes 里没有 `analyze=` |
| 缺凭据诚实 | 显式 sdk 但没 key → `other_blocked`，blockers 写清 | 抄路由器 hint 当根因 |
| `needs_info` | `outcome=needs_ticket_info`，notes **没有** `analyze=sdk` | 仍去烧 SDK |
| 默认不出补丁 | `applyFix=false` 时没有 `patch_ready`；`suggestedVerify.executed=false` | 报告路径声称已修 |
| 路径存在 | `localization.candidates[].path` / `proposedFix.targetFiles` 在 workDir 里（相对路径） | 编路径；或候选全是 `Router/pc.js`、`main-*.js` 这类入口/路由表 |

脚本对「入口噪声」的启发式：路径以 `src/Router/`、`src/main-pc`、`src/main-mobile` 结尾且没有任何 `expectPathPrefix` 命中 → 记 `entryNoise=true`（G0 警告；若该票 `confidence` 还是 high/medium 则 G0 失败）。

### G1 定位（可自动）

与 Agent-2 相同的前缀规则：候选路径等于或落在 `expectPathPrefix` 下。

| 指标 | 怎么算 | 判断 |
|---|---|---|
| loc@1 | top1 命中前缀 | 单条：命中 / 未命中 |
| loc@3 | 前 3 个候选任一命中 | 主指标 |
| 空候选 | `candidates=[]` | 若 `expectOutcomes` 含 `unlocalized` 则定位项记「符合阻断」；否则 loc 失败 |

**一批可定位票（标了 `expectPathPrefix` 且不是 `needs_info`）**：

| 档 | loc@3 | 含义 |
|---|---|---|
| 不可用 | &lt; 40% | 分析在错模块里讲故事 |
| 可用 | ≥ 50% | 能当人工审的起点 |
| 好 | ≥ 70% 且 loc@1 ≥ 40% | 和 Agent-2 软起点相比，Agent-3 自己搜有增值 |

三张 transport 票若全未命中 postHVT / PreviewStream / snap，即使根因写得很长也判 **定位失败**。

### G2 结局桶（可自动）

`outcome ∈ expectOutcomes`。

| 票的标注 | 允许（报告路径） | 不允许 |
|---|---|---|
| 可修、能定位 | `plan_only` | `patch_ready`（未开 apply-fix）；`needs_ticket_info`（单已经够用） |
| 缺复现/期望 | `needs_ticket_info` | `plan_only` 编一套修复 |
| 搜完仍无代码点 | `unlocalized` | `plan_only` 但候选空或全是入口文件 |
| 要实机/环境 | `needs_test_env` | 假装已定位根因 |
| SDK 挂了 | `other_blocked` | 静默降级成启发式成功 |

一批：命中率 ≥ 80% 为可用；&lt; 60% 为不可用（乱分桶）。

### G3 根因（人审，0 / 1 / 2）

脚本只做弱检查（摘要非空、不是标题复制、可选关键词）。**档次必须人打**，填 `score.tsv`。

| 分 | 标准 |
|---|---|
| 0 | 复述标题 / 空 / 与打开的文件无关 / 把入口文件当根因 |
| 1 | 指到了正确模块或函数，但机制含糊（「可能没销毁」） |
| 2 | 说出可核对的机制（符号、分支、错误的状态/时序），`ruledOut` 或 `openQuestions` 不装懂 |

一批可修票：平均 ≥ 1.0 为可用；≥ 1.5 且没有大量 0 分为好。  
**定位 G1 失败的票，根因最高记 0**（不许在错误文件上编 2 分故事）。

---

## 3. 一次 run 怎么判（汇总）

按顺序停：

1. **G0 未满** → 过程失败。不要比较 G1/G2，去修凭据、提示词或 salvage。
2. **G0 满，G1 不可用** → 分析在错地方搜。先查仓图是否进 prompt、弱票是否空起点、24 轮是否触顶。
3. **G1 可用，G2 不可用** → 会找文件但分桶狂。查 `applyFix=false` 是否仍输出 `patch_ready`，或把缺信息票当成可修。
4. **G1+G2 可用，G3 均分 &lt; 1** → 定位对、故事不对。这是「效果」问题，不是门禁问题。
5. 四道都过 → 这次报告路径 **可用**。再谈 `--apply-fix`。

成本（不进通过/失败，但必须记）：每票 `turns` / 耗时；触顶 `reason=max_turns` 占比。24 轮打满且 G1 仍差，加回合不是下一实验，先看是不是在扫整仓。

---

## 4. 和 Agent-2 评测的关系

| | Agent-2 | Agent-3 |
|---|---|---|
| 主指标 | `defectCodeMatches` hit@k | 报告 `localization` hit@k **加上**结局 + 根因 |
| 启发式空候选 | 对中文票可以是 **正确**（不要假 medium） | 必须自己 Grep；空着出 `plan_only` 算 G1/G2 失败 |
| 成功 | 路径前缀对 | 路径对 **且** 桶对 **且** 根因不是复述标题 |

同一组 transport 票：先看 Agent-2 是否不再把 Router 当候选，再看 Agent-3 能否补上 postHVT / PreviewStream。

---

## 5. `--apply-fix`（默认不评）

只有 G1+G2+G3 已「可用」才打开。额外只看：

- 无根因摘要 → 不进 fix
- 有 diff → `patch_ready` 且 `patch.path` 存在
- 空 diff / 非 git 仓 → 仍是 `plan_only`，写明原因
- 不评能否合进主干

---

## 6. 建议最小集

10 张以内即可，三类都要有：

1. 可修且路径真值明确（可复用 Agent-2 三张 transport）
2. `needs_info`（确认不烧 SDK）
3. 故意不可定位或非代码（确认 `unlocalized` / `not_code`，不要编修复）

目录建议：`field-eval/agent3/<日期>-<仓>/`，放入 `cases.json`、`analysis-report.json`、`score.json`、`score.tsv`（G3 人分）。
