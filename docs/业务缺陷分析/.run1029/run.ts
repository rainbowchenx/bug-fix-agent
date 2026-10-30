import { readFileSync, writeFileSync } from "node:fs";
import { classifyDefects, HC_PROFILE, TRAFFIC_PROFILE, LED_PROFILE, HITOOLS_PROFILE } from "../src/defects/index.js";
const LINES: Array<[string,string,any,string]> = [
  ["hcp", ".run1029/hcp.json", HC_PROFILE, "有仓（主仓+55 子模块）"],
  ["hc", ".run1029/hc.json", HC_PROFILE, "有仓（主仓+20 子模块）"],
  ["配套", ".run1029/pe.json", TRAFFIC_PROFILE, "有仓（单仓）"],
  ["led", ".run1029/led.json", LED_PROFILE, "有仓（双仓）"],
  ["hitools", ".run1029/hitools.json", HITOOLS_PROFILE, "**无仓 → ① 止步**"],
];
const pad=(s:string,n:number)=>s.length>=n?s:s+" ".repeat(n-s.length);
for (const [n,f,p,note] of LINES) {
  const arr = JSON.parse(readFileSync(f,"utf-8")).defects;
  const s = classifyDefects(arr,p);
  const r:Record<string,number>={}; for(const x of s.results) r[x.rule]=(r[x.rule]??0)+1;
  const dl:Record<string,number>={}; for(const x of s.results) dl[x.dlevel]=(dl[x.dlevel]??0)+1;
  const ty:Record<string,number>={}; for(const x of s.results) ty[x.type]=(ty[x.type]??0)+1;
  const eq:Record<string,number>={}; for(const x of s.results) eq[x.expectQuality]=(eq[x.expectQuality]??0)+1;
  const real = s.byCluster.filter(c=>!c.semanticFree);
  console.log(`\n===== ${n} · ${note} =====`);
  console.log(`n=${s.total}  ①-a ${s.byVerdict.FIXABLE} (${(s.byVerdict.FIXABLE/s.total*100).toFixed(1)}%)  ①-b ${s.strictFixable} (${(s.strictFixable/s.total*100).toFixed(1)}%)  落差 ${((s.byVerdict.FIXABLE-s.strictFixable)/s.total*100).toFixed(1)}pt`);
  console.log(`expectQ ${JSON.stringify(eq)}`);
  console.log(`类型    ${JSON.stringify(ty)}`);
  console.log(`定位档  ${JSON.stringify(dl)}`);
  console.log(`拦截    ${JSON.stringify(r)}`);
  console.log(`分簇    真模块 ${real.length} 个${s.clusterConcentrated?`（集中 ${(s.clusterMaxShare*100).toFixed(1)}%）`:""}: ${real.slice(0,6).map(c=>c.key+"="+c.count).join(" · ")}`);
  writeFileSync(`.run1029/${n}-detail.csv`,
    "defectId,status,verdict,rule,reason,expectQuality,strictFixable,type,dlevel,clusterKey,clusterRaw,semanticFree,title\n" +
    s.results.map(x=>{
      const d = arr.find((y:any)=>y.defectId===x.defectId);
      const q=(v:any)=>`"${String(v??"").replace(/"/g,'""')}"`;
      return [x.defectId, d?.status, x.verdict, x.rule, x.reason, x.expectQuality, x.strictFixable, x.type, x.dlevel, q(x.clusterKey), q(x.clusterRaw), x.semanticFreeTag, q(d?.title)].join(",");
    }).join("\n"), "utf-8");
}
