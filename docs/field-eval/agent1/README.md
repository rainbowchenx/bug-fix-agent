# Agent-1 实场验证（skill + 规则管线）

明天带几组真实导出时，只需要回答三件事：

1. **skill 有没有按规范跑**（先脚本、再读原文、再回写）
2. **规则层产物对不对**（漏斗、全量票、契约）
3. **实际分类质量够不够交给后续步骤**（池、意图、蒸馏切片）

契约阅读说明：`docs/contracts/v0.1/defect-batch-guide.md`。  
skill 正文：`agent1/skills/defect-batch-prepare/SKILL.md`。

---

## 0. 出发前

每组数据单独一个目录，不要混：

```text
field-runs/2026-11-09-hc-组1/
  00-source.csv              # 或 json / xlsx
  01-before-review.json      # prepare-batch 刚出来、还没意图复核
  02-review.json             # skill 写出的调整；没有调整就留空文件并注明
  03-after-review.json       # apply-review 之后（若无调整，复制 01）
  notes.md                   # 下面「过程检查」打勾 + 你的观感
  score.tsv                  # 抽查表
```

记下四件事：`productLine`、`posture`（建议真实日批用 `beta`）、原始文件格式、这组大概多少条。

本机先确认：

```bash
python --version          # ≥ 3.11
bugfix-agent version
```

xlsx 需要 `openpyxl`。skill 要让 Claude Code 能读到 `agent1/skills/defect-batch-prepare/`（仓内路径即可；若装到用户技能目录，把整个文件夹拷过去，不要只拷 `SKILL.md`）。

今晚若有空，用仓库夹具热身（不必打分）：

```bash
bugfix-agent prepare-batch --product-line hc --source test/fixtures/defect-batch/hc1-raw.json --posture alpha --out /tmp/hc1-batch.json
```

`hc1` alpha 应为 50 张票。能跑通再带真实数据。

---

## 1. 怎么验证 skill

验证的是 **过程**，不是漏斗数字漂不漂亮。

在 Claude Code 里用接近真实的说法（不要点名 skill 文件）：

- 「把这份导出的缺陷列表筛选分类，做成 defect-batch。」
- 「规则已经跑完了，请按原文复核意图，分错了就改。」
- 「这是 xlsx，先转再筛选，然后再看分类对不对。」

### 过程检查（每组必做）

看对话和落盘，不是看模型口头保证：

| 检查 | 通过 | 失败迹象 |
|---|---|---|
| 规则层走 CLI / `run_defect_batch_prepare` | 有 `prepare-batch` 命令和 `01-before-review.json` | 在对话里写正则、手填 `pool` |
| 意图复核对照**原始导出** | 打开了 `00-source` 的描述，不只看 `observed` | 只扫蒸馏切片就改 intent |
| 回写走 `apply-review` | 有 `02-review.json` + `03-after-review.json` | 手改 `clusterId` / `funnel` / `clusters[]` |
| 硬淘汰不动 | `hard_reject` / `security` / `excluded` / `duplicate` 不出现在 adjustments | 把 CVE / `[安全]` 单「救」进 strict |
| 无调整时不空跑 | notes 写明「无需复核」并复制 01→03 | 为了走流程编造无意义 adjustments |

xlsx 组额外看：是否用了 `agent1 xlsx-to-raw`，而不是现场另写转换脚本。

过程五项里有一项失败，这组 **skill 记为未按规范执行**。漏斗再好看也不算 skill 验证通过。

---

## 2. 怎么验证 Agent-1 效果（产物）

这部分可以 **不经过 Claude**，直接对 `01` / `03` 跑命令。效果分两层：规则层可复算，复核层看增量。

### 2.1 契约与计数

在仓库根目录：

```bash
python -c "
from pathlib import Path
from collections import Counter
from bugfix_contracts import validate_defect_batch
import json
p = Path('field-runs/2026-11-09-hc-组1/03-after-review.json')
b = validate_defect_batch(json.loads(p.read_text(encoding='utf-8')))
print('ok', b.productLine, b.posture, 'tickets', len(b.tickets), 'clusters', len(b.clusters))
print('funnel', dict(b.funnel))
print('intent', Counter(t.intent for t in b.tickets if t.intent))
print('source', Counter(t.intentSource for t in b.tickets if t.intentSource))
"
```

硬条件（不通过就不要打质量分）：

- `validate_defect_batch` 不报错
- `len(tickets) == funnel.total == 原始导出条数`（xlsx/CSV 转换丢行要先修转换，不要接着评）
- `clusters` 里的 `defectIds` 都能在 `tickets` 找到，且那些票 `pool=strict`
- 非 strict 的 `clusterId` 为 `null`
- 同一 `00-source` 再跑一次 `prepare-batch`，`01` 的 `funnel` 应一致（规则层确定性）

### 2.2 规则层 vs 复核层

| 看 | 文件 | 说明 |
|---|---|---|
| 规则漏斗 | `01-before-review.json` | 筛池、L1/L2、启发式 L3 |
| 模型改了什么 | `02-review.json` | 只应改匹配池和 intent |
| 交给后续步骤的终态 | `03-after-review.json` | 簇已重建，`intentSource=ai` 表示复核过 |

建议看三个增量数：

- 复核改了多少张（`adjustments` 条数 / 匹配池票数）
- 其中多少是改 `intent`、多少是改 `pool`（尤其是 `needs_info` → `strict`）
- 复核后 `unclear` 少了多少

改动率为 0 不一定失败：描述规范时启发式就够。改动率很高（例如匹配池过半）要抽查是真读懂了，还是在乱贴标签。

`beta` 下非 Open/New 进 `excluded` 是设计如此，不要当成漏筛。日批请用 `beta`；要看历史已关单怎么分，用 `alpha`。

---

## 3. 怎么评估实际执行质量

不要全量打分。每组抽查即可，优先抽「贵」的错误。

### 3.1 抽查配额（一组约 30～40 分钟）

从 `03-after-review.json` + 原始描述：

| 样本 | 数量 | 为什么 |
|---|---|---|
| `02-review.json` 里每一条 | 全看（太多则随机 20） | 这是 skill 真正动手的地方 |
| `strict` | 10 | 会进后续匹配 |
| `locatable_only` + `needs_info` | 各 5 | 常被蒸馏误伤，也是复核该救的地方 |
| `hard_reject` + `security` | 各 5（不足则全看） | 误杀最贵：可修单被扔掉 |
| `excluded` / `duplicate` | 各 3 | 只确认不是乱打 |

抽到的票对照 **原始标题 + 完整描述**，不要只看蒸馏切片。

### 3.2 逐票怎么判

每张抽查票写一行（可直接粘进 `score.tsv`，Tab 分隔）：

```text
defectId	pool_规则	pool_终态	pool_对不对	intent_终态	intent_对不对	切片能不能用	备注
```

- **pool 对不对**：这张单该不该进后续匹配。可修且预期清楚 → `strict`；可修但预期不唯一 → `locatable_only`；缺关键信息 → `needs_info`；非代码 / CVE / 安全扫描 → 旁路池。判 `是` / `否` / `吃不准`。
- **intent 对不对**：终态是否落在封闭枚举里最贴原文的那一类。启发式对了、复核没改，也算对。枚举：`ui_layout` `i18n` `logic` `data_wrong` `perf` `compat` `config` `security_scan` `crash` `unclear`。
- **切片能不能用**：`observed` / `expected` / `steps` 是否短、是否像人话。空切片但原文其实有预期 → 记一笔（这是复核该改 pool 的信号）。

意图没有唯一标准答案时标 `吃不准`，不要硬判错。质量分只统计你标了 `是`/`否` 的票。

### 3.3 一组怎么汇总

抽查结束后算四个数（分母都是「你打了是/否的票」，不含吃不准）：

| 指标 | 怎么算 | 明天可先用的线 |
|---|---|---|
| 匹配池准确率 | 匹配池样本里 pool 判「是」的比例 | ≥ 80% 可把这组交给后续；低于 70% 先别往下传 |
| 旁路误杀 | `hard_reject`/`security` 样本里「其实可修」的张数 | **有 1 张就要记缺陷**；这比 intent 贴不贴更重要 |
| 意图一致率 | intent 判「是」的比例 | ≥ 70% 可接受；大量 `unclear` 且原文能读懂 → 复核没干活 |
| 复核有效率 | `02` 里你判「改对了」的条数 / `02` 总条数 | 低且 `02` 很长 → 模型在乱改；高 → skill 在补规则短板 |

另外用文字记三条（比分数有用）：

1. 哪类单规则总判错（空模板、代码评审、安全误伤、模块名乱……）
2. 复核有没有回读原文，还是只改了标题像的票
3. 这组能不能交给代码定位：匹配池是否太肥、簇是否全是 `_untagged`/`unclear`

### 3.4 什么叫这组「实际可用」

同时满足：

- skill 过程检查通过
- 契约与计数硬条件通过
- 旁路误杀 = 0（抽查范围内）
- 匹配池准确率 ≥ 80%
- 意图一致率 ≥ 70%，或一致率略低但 `unclear` 都是原文确实读不出

否则在 `notes.md` 写清是 **skill 没按规范**、**规则漏斗错** 还是 **复核质量不够**，方便回来改，而不是只记「效果不好」。

---

## 4. 明天建议怎么跑

3 组就够看趋势，5 组更好。尽量满足：

- 至少两条产品线，或同一线两个不同导出日
- 至少一组 CSV、一组若有则 xlsx
- 日批用 `beta`；若导出里大量已关闭单，另跑一组 `alpha` 对比漏斗，不要混在同一目录

每组顺序：

1. 放下 `00-source`，开 Claude Code，用第 1 节的自然语言任务（让它自己找 skill）
2. 要它把规则产物另存为 `01-before-review.json`（复核前快照；若它只给了终态，你自己先跑一遍 `prepare-batch` 补 01）
3. 做过程检查
4. 跑第 2 节的校验脚本
5. 按第 3 节抽查，填 `score.tsv` 和 `notes.md`

一组不要超过一小时。时间不够就砍 `strict` 抽查到 5 张，**不要砍旁路误杀抽查**。

---

## 5. 回来时带什么

每组目录齐全即可，外加一张总表：

| 组 | 线别 | 条数 | skill过程 | 契约 | 匹配池准确率 | 旁路误杀 | 意图一致率 | 复核条数 | 能否交给后续 |
|---|---|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |  |  |

有这张表就能判断：是安装/触发问题、规则要调，还是意图复核要改 skill 口径。
