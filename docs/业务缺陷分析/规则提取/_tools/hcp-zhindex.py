"""hcp 中文 3-gram 倒排索引"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_CACHE = _os.path.join(_HERE, "_cache")
_os.makedirs(_CACHE, exist_ok=True)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_HERE)))
import os, re, glob, pickle, sys, math
from collections import defaultdict, Counter
ROOT = "E:/working_code_webfront/bug-fix-demo-project/hcp/hcp/src"
CACHE = _os.path.join(_CACHE, "hcp-zhindex.pkl")
RUN = re.compile(r"[\u4e00-\u9fa5]{2,}")
def build():
    files=[]
    for ext in ("vue","ts","js","json"):
        files += glob.glob(f"{ROOT}/**/*.{ext}", recursive=True)
    def ok(f):
        r=f.replace("\\","/")
        return "node_modules" not in r and "/i18n/" not in r and "/.claude/" not in r and "/.trellis/" not in r and "/.codegraph/" not in r and "/dist/" not in r
    files=[f for f in files if ok(f)]
    idx=defaultdict(set); n=0
    for f in files:
        try: txt=open(f,encoding="utf-8",errors="ignore").read()
        except Exception: continue
        rel=os.path.relpath(f,ROOT).replace("\\","/")
        gs=set()
        for run in RUN.findall(txt):
            for i in range(len(run)-2): gs.add(run[i:i+3])
        for g in gs: idx[g].add(rel)
        n+=1
    idf={g: math.log(n/(1+len(s))) for g,s in idx.items()}
    return {"idx":{g:sorted(s) for g,s in idx.items()},"idf":idf,"N":n}
if os.path.exists(CACHE) and "--rebuild" not in sys.argv:
    I=pickle.load(open(CACHE,"rb"))
else:
    I=build(); pickle.dump(I,open(CACHE,"wb")); print(f"索引 {I['N']} 文件 · {len(I['idx'])} 3-gram",file=sys.stderr)
def grams(t):
    out=[]
    for run in RUN.findall(t):
        for i in range(len(run)-2): out.append(run[i:i+3])
    return out
def locate(title, topk=8, df_cap=400):
    sc=Counter()
    for g in grams(title):
        fs=I["idx"].get(g)
        if not fs or len(fs)>df_cap: continue
        w=I["idf"].get(g,0)
        for f in fs: sc[f]+=w
    return sc.most_common(topk)
