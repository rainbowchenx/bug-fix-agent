import { readFileSync } from "node:fs";
import { classifyDefects, HC_PROFILE, TRAFFIC_PROFILE, LED_PROFILE, HITOOLS_PROFILE } from "../src/defects/index.js";
const LINES: Array<[string,string,any]> = [
  ["hitools", ".run1029/hitools.json", HITOOLS_PROFILE],
  ["hc", ".run1029/hc.json", HC_PROFILE],
  ["hcp", ".run1029/hcp.json", HC_PROFILE],
  ["led", ".run1029/led.json", LED_PROFILE],
  ["配套", ".run1029/pe.json", TRAFFIC_PROFILE],
];
const P=(a:number,b:number)=>`${a}（${(a/b*100).toFixed(1)}%）`;
for (const [n,f,p] of LINES) {
  const arr = JSON.parse(readFileSync(f,"utf-8")).defects;
  const s = classifyDefects(arr,p); const N=s.total;
  const r:Record<string,number>={}; for(const x of s.results) r[x.rule]=(r[x.rule]??0)+1;
  const t=s.byAnchorTier;
  console.log(`\n【${n}】n=${N}`);
  console.log(`  verdict  ${JSON.stringify(s.byVerdict)}   rule ${JSON.stringify(r)}`);
  console.log(`  anchor   L1 ${t.L1??0} · L2 ${t.L2??0} · L3 ${t.L3??0} · none ${t.none??0}`);
  console.log(`  ①-a(L1) ${P(s.locatableL1,N)}   ①-a(宽松) ${P(s.locatableLoose,N)}`);
  console.log(`  ①-b(L1) ${P(s.strictFixableL1,N)}   ①-b(宽松) ${P(s.strictFixableLoose,N)}`);
  const no=s.results.filter(x=>x.anchorTier==="none");
  console.log(`  NOANCHOR ${no.length}: ` + no.slice(0,4).map(x=>`${x.defectId}`).join(","));
}
