# -*- coding: utf-8 -*-
"""S8 噪音提交审计：把 s8-crosscheck.csv 里命中的 commit 按 subject 分成三类。

用法：
    python 规则提取/_tools/audit-s8-noise.py 规则提取/hc/s8-crosscheck.csv
    python 规则提取/_tools/audit-s8-noise.py 规则提取/hcp/s8-crosscheck.csv --sha-col sha

背景（`_pipeline.md` 坑 12）：不加语义过滤的 3-gram 匹配会把
「骨架屏 / 合并模块 / upload lan files / 需求开发 / 埋点 / 回滚」类大范围提交算成命中。
hcp 实测 98 条命中里 30 条（18.9%）是假阳性，真实下界 61.6% → 42.8%。
hc 实测 84 条候选中 44 条误配（52%），其中埋点提交 `3086b24d` 一条吃掉 10 条缺陷。
"""
import csv, io, re, sys
from collections import Counter

NOISE = re.compile(
    r"骨架屏|Merge|合并|upload lan|lan files|eslint|格式化|规范|重命名|Revert|回退|版本号|打包|构建"
    r"|埋点|buryPoint|chore|refactor|style|注释|日志|删除无用|删除冗余", re.I)
FIX = re.compile(r"fix|修复|bug|缺陷|解决|hotfix", re.I)

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    path = sys.argv[1]
    col = "subject"
    if "--sha-col" in sys.argv:
        pass
    rows = list(csv.DictReader(io.open(path, encoding="utf-8-sig")))
    hit = [r for r in rows if (r.get("sha") or "").strip()]
    tally = Counter()
    per_commit = Counter()
    for r in hit:
        s = r.get("subject", "")
        per_commit[(r.get("module", ""), r.get("sha", "")[:10], s[:44])] += 1
        if NOISE.search(s): tally["噪音提交"] += 1
        elif FIX.search(s): tally["缺陷修复提交"] += 1
        else: tally["其他（subject 笼统）"] += 1
    n = len(rows)
    print(f"总行 {n} | 有命中 {len(hit)}（{len(hit)/n*100:.1f}%）")
    for k, v in tally.most_common():
        print(f"  {k:20s} {v:4d}  {v/n*100:5.1f}%")
    real = tally["缺陷修复提交"] + tally["其他（subject 笼统）"]
    print(f"\n剔除噪音后的下界：{real}/{n} = {real/n*100:.1f}%")
    print("\n被多条缺陷共享的提交 top10（一条吃多条的典型）：")
    for (m, sha, s), c in per_commit.most_common(10):
        if c >= 2: print(f"  {c:3d}×  {m}/{sha}  {s}")

if __name__ == "__main__":
    main()
