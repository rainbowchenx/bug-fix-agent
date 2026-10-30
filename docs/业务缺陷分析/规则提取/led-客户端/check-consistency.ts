/**
 * led-客户端 规则一致率检查（回归 + 人工子集）
 *
 * 用法：npx tsx 规则提取/led-客户端/check-consistency.ts [--verbose]
 *
 * 两个指标含义不同，必须分开看：
 *  - **回归一致率**（全 319 行）：基线是**规则输出快照**，只用于防止后续改规则时无意漂移，
 *    **不是准确率**。100% 只代表「没变」。
 *  - **人工子集一致率**（provenance=manual，45 行）：这批是逐条人工核对过的，
 *    它的一致率才反映规则准不准。
 */
import { readFileSync } from "node:fs";
import { classifyDefects, LED_PROFILE, type RawDefect } from "../../src/defects/index.js";

interface Label {
  defectId: string;
  verdict: string;
  reason: string;
  type: string;
  dlevel: string;
  clusterKey: string;
  provenance: string;
}

const dir = "规则提取/led-客户端";
const raw = JSON.parse(readFileSync(`${dir}/fixtures/defects.json`, "utf-8")) as RawDefect[];
const csv = readFileSync(`${dir}/baseline-labels.csv`, "utf-8").trim().split(/\r?\n/);

/** CSV 解析：末列 title 可能含逗号，用引号包裹（见生成脚本），此处只取前 7 列 */
function parse(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') {
      if (q && line[i + 1] === '"') { cur += '"'; i++; }
      else q = !q;
    } else if (c === "," && !q) { out.push(cur); cur = ""; }
    else cur += c;
  }
  out.push(cur);
  return out;
}

const labels: Label[] = csv.slice(1).map((l) => {
  const f = parse(l);
  return { defectId: f[0], verdict: f[1], reason: f[2], type: f[3], dlevel: f[4], clusterKey: f[5], provenance: f[6] };
});

const s = classifyDefects(raw, LED_PROFILE);
const got = new Map(s.results.map((r) => [r.defectId, r]));
const verbose = process.argv.includes("--verbose");

let n = 0, okV = 0, okR = 0, okT = 0, okD = 0, nManual = 0, mV = 0, mT = 0;
const diffs: string[] = [];

for (const l of labels) {
  const g = got.get(l.defectId);
  if (!g) continue;
  n++;
  const isM = l.provenance === "manual";
  if (isM) nManual++;
  const v = g.verdict === l.verdict, r = g.reason === l.reason, t = g.type === l.type, d = g.dlevel === l.dlevel;
  if (v) okV++;
  if (r) okR++;
  if (t) okT++;
  if (d) okD++;
  if (isM) { if (v) mV++; if (t) mT++; }
  if (!v || !r || !t) diffs.push(`${l.defectId}  ${l.verdict}/${l.reason}/${l.type} → ${g.verdict}/${g.reason}/${g.type}`);
}

const pct = (a: number, b: number) => `${((a / b) * 100).toFixed(1)}%`;
console.log(`\n=== 回归一致率（全量快照，n=${n}）===`);
console.log(`verdict   ${okV}/${n}  ${pct(okV, n)}   ← 只代表「没变」，不代表准`);
console.log(`reason    ${okR}/${n}  ${pct(okR, n)}`);
console.log(`类型      ${okT}/${n}  ${pct(okT, n)}`);
console.log(`定位档    ${okD}/${n}  ${pct(okD, n)}`);

console.log(`\n=== 人工核对子集（n=${nManual}）===`);
console.log(`verdict   ${mV}/${nManual}  ${pct(mV, nManual)}   ← 准确率读数`);
console.log(`类型      ${mT}/${nManual}  ${pct(mT, nManual)}`);

if (verbose && diffs.length) {
  console.log(`\n--- 差异（${diffs.length}）---`);
  for (const d of diffs) console.log("  " + d);
}

const exit = okV / n < 0.98 ? 1 : 0;
if (exit) console.log("\n❌ 回归一致率 < 98%，检查是否无意改了规则");
process.exit(exit);
