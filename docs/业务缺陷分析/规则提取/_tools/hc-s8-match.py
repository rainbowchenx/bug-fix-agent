# -*- coding: utf-8 -*-
"""hc S8 v3：idf + 稀有词 + 排除大杂烩提交 + 一条提交至多归 3 条缺陷"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_CACHE = _os.path.join(_HERE, "_cache")
_os.makedirs(_CACHE, exist_ok=True)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_HERE)))
import json, re, pickle, io, csv, math
from collections import Counter, defaultdict
CJK=re.compile(r"[\u4e00-\u9fff]")
GENERIC=set("""页面 窗口 显示 界面 功能 数据 信息 正常 正确 提示 问题 异常 操作 设置 配置 支持 需要 无法
没有 应该 实际 预期 结果 出现 导致 进行 点击 选择 打开 关闭 使用 查看 查询 时候 列表 详情 内容 情况 效果
之后 之前 是否 一下 已经 还是 这样 那样 什么 怎么 现在 目前 一个 多个 其他 我们 他们 这个 那个 并且 而且
所以 但是 因为 如果 就是 不是 不能 不会 也要 都要 一起 分别 单独 测试 验证 复现 步骤 附件 截图 录屏 版本
环境 客户 项目 需求 建议 优化 修改 增加 删除 添加 更新 调整 不一致 缺少 不显示 显示不全 时无 后无 对应""".split())
FUNC=set("的了时候后前在上中下和与或是无不能都也会就还很太个些这那什么怎样为所以但而且如果因将把被让使对从到向给跟同及其之者等又再多每次各本该项此该想需可按让")
NONFIX=re.compile(r"refactor|style|注释|日志|格式化|eslint|规范|重命名|Merge|合并|骨架屏|upload lan|Revert|回退|版本号|打包|构建",re.I)
def grams(text,lens=(3,4)):
    out=set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}",text):
        for n in lens:
            for i in range(len(run)-n+1):
                g=run[i:i+n]
                if g in GENERIC: continue
                if sum(1 for c in g if c in FUNC)>=2: continue
                out.add(g)
    return out
def main():
    cs=pickle.load(io.open(_os.path.join(_CACHE,"hc-s8idx.pkl"),"rb"))
    for c in cs:
        c["g"]=grams(c["cjk"]); c["sz"]=c["add"]+c["del"]; c["nf"]=len(c["files"])
        c["nonfix"]=bool(NONFIX.search(c["subject"]))
    N=len(cs); df=Counter()
    for c in cs:
        for g in c["g"]: df[g]+=1
    idf=lambda g: math.log(1+N/(1+df.get(g,0)))
    js=json.load(io.open("规则提取/hc/fixtures/hc-defects.json",encoding="utf-8"))
    cand_all=[]
    for k,d in enumerate(js["defects"]):
        m=re.search(r"BGCM(\d{4})(\d{2})(\d{2})",d["defectId"])
        cd=f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "2026-09-01"
        t=re.sub(r"^\s*[\[【][^\]】]*[\]】]\s*","",d["title"]); g=grams(t)
        lst=[]
        for c in cs:
            if c["date"]<cd: continue
            if c["nonfix"] or c["nf"]>6 or c["sz"]>250: continue   # 排除大杂烩/非修复
            hit=g & c["g"]
            if len(hit)<2: continue
            rare=[x for x in hit if df[x]<=5]
            if len(rare)<1: continue
            lst.append((sum(idf(x) for x in hit), len(rare), len(hit), c))
        lst.sort(key=lambda x:x[0],reverse=True)
        cand_all.append((k,d,cd,lst))
    # 一条提交被多少条缺陷选中（用于降权）
    share=defaultdict(int)
    for k,d,cd,lst in cand_all:
        if lst: share[lst[0][3]["sha"]]+=1
    out=[]
    for k,d,cd,lst in cand_all:
        if lst:
            sc,nr,nh,c=lst[0]
            solo = share[c["sha"]]<=3
            rec=dict(score=round(sc,1),nrare=nr,nhit=nh,module=c["module"],sha=c["sha"],date=c["date"],
                     subject=c["subject"][:80],size=f'{c["nf"]}f/{c["sz"]}L',shared=share[c["sha"]],
                     snippet=(c["cjk"] or "").replace("\n"," | ")[:180])
        else:
            rec=dict(score=0,nrare=0,nhit=0,module="",sha="",date="",subject="",size="",shared=0,snippet="")
        out.append({"defectId":d["defectId"],"cdate":cd,"title":d["title"],**rec})
    cols=["defectId","cdate","score","nrare","nhit","module","sha","date","subject","size","shared","snippet","title"]
    with io.open(_os.path.join(_os.path.dirname(_HERE),"hc","s8-crosscheck.csv"),"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore"); w.writeheader(); w.writerows(out)
    n=len(out); hit=[r for r in out if r["sha"]]
    print(f"n={n}  有候选 {len(hit)} ({len(hit)/n*100:.1f}%)")
    for lo in (6,8,10,12):
        s=[r for r in hit if r["score"]>=lo and r["shared"]<=3]
        print(f"  score≥{lo} 且 独占提交: {len(s)} ({len(s)/n*100:.1f}%)")
    print(f"\n被多条缺陷共享的提交 top: {Counter({k:v for k,v in share.items() if v>2}).most_common(5)}")
main()
