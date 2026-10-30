"""hcp 子模块级 S8：建窗口提交索引（含 diff 中文 3-gram），再按缺陷标题反查。"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_CACHE = _os.path.join(_HERE, "_cache")
_os.makedirs(_CACHE, exist_ok=True)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_HERE)))
import subprocess, os, re, json, pickle
from collections import defaultdict, Counter

SUPER = "E:/working_code_webfront/bug-fix-demo-project/hcp/hcp"
SINCE = "2026-09-04"
CACHE = _os.path.join(_CACHE, "hcp-s8.pkl")
RUN = re.compile(r"[\u4e00-\u9fa5]{2,}")
HDR = re.compile(r"^@@@([0-9a-f]+)\|(\d{4}-\d{2}-\d{2})\|(.*)$")

def modules():
    out = []
    gm = open(os.path.join(SUPER, ".gitmodules"), encoding="utf-8", errors="ignore").read()
    for m in re.finditer(r"path = (.+)", gm):
        p = m.group(1).strip()
        if os.path.isdir(os.path.join(SUPER, p, ".git")) or os.path.isfile(os.path.join(SUPER, p, ".git")):
            out.append(p)
    return out

def build():
    commits = []
    for mod in modules():
        try:
            r = subprocess.run(["git", "-C", mod, "log", f"--since={SINCE}", "--date=short",
                                "--format=@@@%H|%ad|%s", "-p", "--unified=0", "--no-color", "--", "."],
                               cwd=SUPER, capture_output=True, text=True, encoding="utf-8",
                               errors="ignore", timeout=1800)
        except Exception as e:
            print("skip", mod, e, flush=True); continue
        cur = None
        for line in r.stdout.split("\n"):
            m = HDR.match(line)
            if m:
                if cur: commits.append(cur)
                cur = {"mod": os.path.basename(mod), "sha": m.group(1)[:10],
                       "date": m.group(2), "subj": m.group(3)[:110], "files": set(), "text": []}
                continue
            if cur is None: continue
            if line.startswith("+++ b/"):
                cur["files"].add(line[6:].strip())
            elif line.startswith("+") or line.startswith("-"):
                if RUN.search(line): cur["text"].append(line[1:].strip()[:160])
        if cur: commits.append(cur)
        print(f"  {os.path.basename(mod)}: ok", flush=True)
    # 建索引
    idx = defaultdict(set)
    for i, c in enumerate(commits):
        c["files"] = sorted(c["files"])
        gs = set()
        for t in c["text"]:
            for run in RUN.findall(t):
                for k in range(len(run) - 2): gs.add(run[k:k + 3])
        for g in gs: idx[g].add(i)
    return {"commits": commits, "idx": {g: sorted(s) for g, s in idx.items()}}

if os.path.exists(CACHE) and "--rebuild" not in __import__("sys").argv:
    I = pickle.load(open(CACHE, "rb"))
else:
    I = build(); pickle.dump(I, open(CACHE, "wb"))
    print(f"索引: {len(I['commits'])} 提交 · {len(I['idx'])} 个 3-gram", flush=True)

def grams(t):
    out = []
    for run in RUN.findall(t or ""):
        for i in range(len(run) - 2): out.append(run[i:i + 3])
    return out

def find(title, files=None, topk=5, df_cap=300):
    sc = Counter(); why = defaultdict(list)
    gs = grams(title)
    for g in gs:
        hs = I["idx"].get(g)
        if not hs or len(hs) > df_cap: continue
        w = 1.0 / (1 + len(hs) ** 0.5)
        for i in hs:
            sc[i] += w
            if len(why[i]) < 3: why[i].append(g)
    if files:
        base = [os.path.basename(f) for f in files]
        for i, c in enumerate(I["commits"]):
            if any(os.path.basename(x) in base for x in c["files"]): sc[i] += 1.2
    return [(I["commits"][i], s, why[i]) for i, s in sc.most_common(topk)]
