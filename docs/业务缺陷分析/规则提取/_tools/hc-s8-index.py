# -*- coding: utf-8 -*-
"""hc S8 提交索引：20 子仓缺陷窗口内提交 → {sha,date,subject,files,cjk}"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_CACHE = _os.path.join(_HERE, "_cache")
_os.makedirs(_CACHE, exist_ok=True)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_HERE)))
import os, re, subprocess, pickle, io, sys
BASE = r"E:/working_code_webfront/bug-fix-demo-project/hct/hct/src"
SEP = "\x01"
MARK = "@@@COMMIT"
CJK = re.compile(r"[\u4e00-\u9fff]")

def index_module(p, name):
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "log", "--since=2026-08-31",
         f"--format={MARK}%H{SEP}%ad{SEP}%s", "--date=short", "-p", "--unified=0",
         "--no-color", "--no-merges", "--all"],
        cwd=p, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=1800).stdout
    commits, cur = [], None
    for line in out.split("\n"):
        if line.startswith(MARK):
            sha, date, subj = (line[len(MARK):].split(SEP) + ["", "", ""])[:3]
            cur = {"sha": sha, "date": date, "subject": subj, "module": name,
                   "files": [], "cjk": [], "add": 0, "del": 0}
            commits.append(cur); continue
        if cur is None: continue
        if line.startswith("+++ b/"):
            cur["files"].append(line[6:].strip()); continue
        if line.startswith("+") and not line.startswith("+++"):
            cur["add"] += 1
            if CJK.search(line): cur["cjk"].append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            cur["del"] += 1
            if CJK.search(line): cur["cjk"].append(line[1:].strip())
    for c in commits: c["cjk"] = "\n".join(c["cjk"])[:20000]
    return [c for c in commits if c["date"] >= "2026-09-01"]

def main():
    mods = [d for d in sorted(os.listdir(BASE)) if os.path.isdir(os.path.join(BASE, d, ".git"))]
    allc = []
    for i, m in enumerate(mods, 1):
        cs = index_module(os.path.join(BASE, m), m)
        allc += cs
        sys.stderr.write(f"  {i}/{len(mods)} {m}: {len(cs)}\n"); sys.stderr.flush()
    pickle.dump(allc, io.open(_os.path.join(_CACHE,"hc-s8idx.pkl"), "wb"))
    print(f"索引：{len(allc)} 提交 / {sum(len(c['files']) for c in allc)} 文件变更 / 含中文diff {sum(1 for c in allc if c['cjk'])}")

main()
