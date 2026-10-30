/**
 * 配套-交通项目 规则一致性检查
 *
 *   npx tsx 规则提取/配套-交通项目/check-consistency.ts
 *   npx tsx 规则提取/配套-交通项目/check-consistency.ts --verbose
 *
 * 口径：`src/defects` + `TRAFFIC_PROFILE` 跑 150 条，与 `baseline-labels.csv` 人工判定对比。
 * 类型比较时把 `安全-SCA` / `安全-漏洞` 归一为 `安全`。
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { classifyDefects, TRAFFIC_PROFILE, type RawDefect } from "../../src/defects/index.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(resolve(here, "fixtures/defects.json"), "utf-8")) as Array<{
  defectId: string;
  status: string;
  severity: string;
  probability: string;
  testModule: string;
  title: string;
  description: string;
}>;

const raw: RawDefect[] = fixtures.map((d) => ({
  defectId: d.defectId,
  title: d.title,
  description: d.description,
  status: d.status,
  severity: d.severity,
}));

const summary = classifyDefects(raw, TRAFFIC_PROFILE);

// ---- 读基线
const csv = readFileSync(resolve(here, "baseline-labels.csv"), "utf-8").replace(/^\uFEFF/, "");
const lines = csv.trim().split(/\r?\n/);
const header = lines[0].split(",");
const col = (name: string) => header.indexOf(name);
const labels = lines.slice(1).map((ln) => ln.split(","));
const rowOf = (id: string) => labels.find((r) => r[col("defectId")] === id);

const normType = (t: string) => (t.startsWith("安全") ? "安全" : t);

let vHit = 0;
let rHit = 0;
let tHit = 0;
const flips: string[] = [];
const typeMiss: string[] = [];
const verbose = process.argv.includes("--verbose");

for (const res of summary.results) {
  const row = rowOf(res.defectId);
  if (!row) continue;
  const expV = row[col("verdict")];
  const expR = row[col("reasonCode")];
  const expT = row[col("summaryType")];
  const expTitle = row[col("title")];

  if (res.verdict === expV) vHit++;
  if (res.reason === expR) rHit++;
  if (normType(res.type) === expT) tHit++;

  if (res.verdict !== expV || res.reason !== expR) {
    flips.push(
      `  ${res.defectId}  期望 ${expV}/${expR} → 实得 ${res.verdict}/${res.reason}  [${res.rule}] ${res.detail ?? ""}\n     ${expTitle}`,
    );
  }
  if (normType(res.type) !== expT) {
    typeMiss.push(`  ${res.defectId}  ${expT} → ${res.type} | ${expTitle}`);
  }
}

const n = summary.results.length;
const pct = (a: number) => `${((a / n) * 100).toFixed(1)}%`;

console.log(`\n=== 一致率（配套-交通项目，n=${n}）===`);
console.log(`verdict   ${vHit}/${n}  ${pct(vHit)}   ← 主指标`);
console.log(`reason    ${rHit}/${n}  ${pct(rHit)}`);
console.log(`类型       ${tHit}/${n}  ${pct(tHit)}`);

console.log(`\n--- 判定分布（规则实现）---`);
console.log("可修", summary.byVerdict.FIXABLE, "/ 不可修", summary.byVerdict.UNFIXABLE);
console.log("原因码:", summary.byReason);
console.log("类型:", summary.byType);
console.log("定位档:", summary.byDLevel);
console.log("附件档:", summary.attachment);
console.log("证据缺口:", summary.evidenceGaps);
console.log("簇数:", summary.byCluster.length);
console.log("Top 簇:", summary.byCluster.slice(0, 8).map((c) => `${c.key}(${c.count})`).join(" "));

const expectGap = labels.filter((r) => r[col("baselineGap")] === "Y").length;
console.log(`基线对照依赖（人工标注）: ${expectGap} 条`);

if (flips.length) {
  console.log(`\n--- 判定翻转（${flips.length} 条）---`);
  console.log(flips.join("\n"));
}
if (verbose) {
  console.log(`\n--- 类型不一致（${typeMiss.length} 条）---`);
  console.log(typeMiss.join("\n"));
}
const fail = vHit / n < 0.9;
console.log(`\n${fail ? "❌" : "✅"} verdict 一致率 ${pct(vHit)}（门槛 90%）`);
if (fail) process.exitCode = 1;
