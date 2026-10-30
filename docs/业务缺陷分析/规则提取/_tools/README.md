# 复现工具（S8 / 定位）

这些脚本产出了报告里引用的中间数据。**缓存（`.pkl`）不入库**，用时现建。

```
规则提取/_tools/
├── hc-s8-index.py      hc：20 个子仓缺陷窗口内提交索引（含中文 diff）
├── hc-s8-match.py      hc：idf + 稀有词 + 排除大杂烩 → s8-crosscheck.csv
├── hcp-s8.py           hcp：子模块级 S8 索引 + 反查（同一条命令完成两步）
├── hcp-zhindex.py      hcp：源码中文 3-gram 倒排索引（定位辅助）
├── led-s8.py           led：双仓 S8 索引 + 稀有 gram 反查（452 提交窗口）
└── audit-s8-noise.py   S8 噪音提交审计（坑 12：骨架屏/合并/埋点类提交）
```

## 用法

```bash
cd /e/working_code_webfront/ai/bug-fix-agent

# hc（需先把仓路径改成你的）
python 规则提取/_tools/hc-s8-index.py     # → _tools/_cache/hc-s8idx.pkl（约 1.4MB）
python 规则提取/_tools/hc-s8-match.py     # → 规则提取/hc/s8-crosscheck.csv

# hcp
python 规则提取/_tools/hcp-s8.py          # → _tools/_cache/hcp-s8index.pkl + 匹配结果
python 规则提取/_tools/hcp-zhindex.py     # → _tools/_cache/hcp-zhindex.pkl

# led（双仓；--all 只比 HEAD 多 2 条）
python 规则提取/_tools/led-s8.py          # → 规则提取/led-客户端/s8-crosscheck-v2.csv

# 噪音提交审计（任何 s8-crosscheck.csv 都能跑）
python 规则提取/_tools/audit-s8-noise.py 规则提取/hc/s8-crosscheck.csv
```

## 三个必须记住的坑

| 坑 | 内容 |
|---|---|
| **坑 15** | 索引必须用 `git log --all`，不能用 `HEAD`。hc 实测：HEAD 390 提交 → `--all` 699 提交，高置信命中 27 → 54 条 |
| **坑 12** | 报数前必须跑 `audit-s8-noise.py`。hcp 30/98 命中是骨架屏/合并类假阳性；hc 有埋点提交一条吃掉 10 条缺陷 |
| **坑 13** | 别指望自动定位。hc 自动定位器在有 ground truth 的 6 条上 top-1 文件 **0/6**；缺陷是「测试语言」，代码是「工程语言」，唯一交集是**修复后写的中文注释** |

## 缓存为什么不入库

`hc-s8idx.pkl` 1.4MB、`hcp-s8index.pkl` 10MB、`hcp-zhindex.pkl` 15MB、`led-s8.pkl` 约 2MB，
且完全可由源码重建。重建时间：hc 约 3~5 分钟，led 约 2 分钟，hcp 约 15~25 分钟。

## 报数纪律（三条，写在这里防止下次忘）

1. **候选 ≠ 命中**。任何 s8 脚本的输出都是候选，必须先人工复核 ≥30 条再报数。
   实测：hcp 假阳性 18.9%、hc 误配 52%、led 误配 **73%**。
2. **只能当下界**。「没找到候选」= 我没找到证据，不等于缺陷没修。
3. **必须 `--all`**。LED 是例外（+2 条），但 hc 不看 `--all` 会漏 44% 的提交。
