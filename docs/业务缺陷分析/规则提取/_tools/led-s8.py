# -*- coding: utf-8 -*-
"""led 双仓 S8：窗口提交索引（--all）+ 稀有 gram 反查真实修复提交。

用法（在仓库根执行）：
    python 规则提取/_tools/led-s8.py              # 建索引 + 出候选
    python 规则提取/_tools/led-s8.py --rebuild    # 强制重建索引

依赖：E:/working_code_webfront/bug-fix-demo-project/led/{calibrationtool,calibration-subsystem}
输出：规则提取/led-客户端/s8-crosscheck-v2.csv

与 hc 的差异（实测打出来的）：
  · df ≤ 8 才算稀有词（hc 用 shared≤3）；452 提交语料更小，阈值要放宽
  · 大杂烩过滤用「改动 >20 文件 或 中文 diff 行 >120」（LED 只剔掉 1 个）
  · 坑 15 在 LED 不成立：--all 只比 HEAD 多 2 条（hc 是 +309）

★ 报数纪律：候选不等于命中。LED 人工复核 30 条 → 真命中 6（20%）、弱 2、误配 22（73%）。
  所以本脚本的输出只能当候选，**必须人工复核后才能报 20% 这个数**。
"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_CACHE = _os.path.join(_HERE, "_cache")
_os.makedirs(_CACHE, exist_ok=True)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_HERE)))

import subprocess, os, re, json, pickle, sys, math, csv, io
from collections import defaultdict, Counter

BASE = "E:/working_code_webfront/bug-fix-demo-project/led"
REPOS = ["calibrationtool", "calibration-subsystem"]
SINCE, UNTIL = "2026-05-11", "2026-06-17"
CACHE = _os.path.join(_CACHE, "led-s8.pkl")
RUN = re.compile(r"[\u4e00-\u9fa5]{2,}")
HDR = re.compile(r"^@@@([0-9a-f]+)\|(\d{4}-\d{2}-\d{2})\|(.*)$")


def build():
    commits = []
    for repo in REPOS:
        r = subprocess.run(["git", "log", "--all", f"--since={SINCE}", f"--until={UNTIL}",
                            "--date=short", "--format=@@@%H|%ad|%s", "-p", "--unified=0", "--no-color"],
                           cwd=os.path.join(BASE, repo), capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=3600)
        cur = None
        for line in r.stdout.split("\n"):
            m = HDR.match(line)
            if m:
                if cur: commits.append(cur)
                cur = {"repo": repo, "sha": m.group(1)[:10], "date": m.group(2),
                       "subj": m.group(3)[:120], "files": set(), "text": []}
                continue
            if cur is None: continue
            if line.startswith("+++ b/"): cur["files"].add(line[6:].strip())
            elif line[:1] in "+-" and RUN.search(line): cur["text"].append(line[1:].strip()[:160])
        if cur: commits.append(cur)
        print(f"  {repo}: {sum(1 for c in commits if c['repo'] == repo)} 提交", flush=True)
    idx = defaultdict(set)
    for i, c in enumerate(commits):
        c["files"] = sorted(c["files"])
        gs = set()
        for t in c["text"]:
            for run in RUN.findall(t):
                for k in range(len(run) - 2): gs.add(run[k:k + 3])
        for g in gs: idx[g].add(i)
    return {"commits": commits, "idx": {g: sorted(s) for g, s in idx.items()}}


def grams(t):
    out = []
    for run in RUN.findall(t or ""):
        for i in range(len(run) - 2): out.append(run[i:i + 3])
    return out


if os.path.exists(CACHE) and "--rebuild" not in sys.argv:
    I = pickle.load(open(CACHE, "rb"))
else:
    I = build()
    pickle.dump(I, open(CACHE, "wb"))
print(f"索引 {len(I['commits'])} 提交 · {len(I['idx'])} 个 3-gram", flush=True)

N = len(I["commits"])
BIG = {i for i, c in enumerate(I["commits"]) if len(c["files"]) > 20 or len(c["text"]) > 120}


def find_rare(text, df_cap=8, topk=3, min_grams=2):
    """只认稀有 gram（df<=df_cap）且命中 ≥min_grams 个，排除大杂烩提交。"""
    sc, hg = Counter(), defaultdict(set)
    for g in set(grams(text)):
        hs = I["idx"].get(g)
        if not hs or len(hs) > df_cap: continue
        w = math.log(N / len(hs))
        for i in hs:
            if i in BIG: continue
            sc[i] += w; hg[i].add(g)
    res = [(i, s, hg[i]) for i, s in sc.items() if len(hg[i]) >= min_grams]
    res.sort(key=lambda x: (-len(x[2]), -x[1]))
    return [(I["commits"][i], round(s, 2), sorted(g)) for i, s, g in res[:topk]]


if __name__ == "__main__":
    src = os.path.join(os.path.dirname(_HERE), "led-客户端", "fixtures", "defects.json")
    raw = json.load(io.open(src, encoding="utf-8"))
    defects = raw if isinstance(raw, list) else raw["defects"]
    out = os.path.join(os.path.dirname(_HERE), "led-客户端", "s8-crosscheck-v2.csv")
    print(f"提交 {N} · 大杂烩提交 {len(BIG)} 个", flush=True)
    n_hit = 0
    with io.open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["defectId", "title", "createdAt", "top1Repo", "top1Sha", "top1Date",
                    "top1Subject", "sharedRareGrams", "nFiles"])
        for d in defects:
            hits = find_rare(str(d.get("title", "")))
            t = hits[0] if hits else None
            if t: n_hit += 1
            w.writerow([d.get("defectId"), d.get("title"), d.get("createdAt"),
                        t[0]["repo"] if t else "", t[0]["sha"] if t else "",
                        t[0]["date"] if t else "", t[0]["subj"] if t else "",
                        " ".join(t[2][:6]) if t else "", len(t[0]["files"]) if t else ""])
    print(f"有候选 {n_hit}/{len(defects)} = {n_hit/len(defects)*100:.1f}%  → {out}")
