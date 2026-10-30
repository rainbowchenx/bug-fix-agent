/**
 * 一致率校验：规则实现 vs 人工基线
 *
 * 用法：npx tsx 规则提取/hc/check-consistency.ts [--verbose]
 *
 * 输入：
 *   fixtures/hc-defects.json   —— 由 xlsx 导出的 200 条原始记录
 *   baseline-labels.csv        —— 人工逐条判定基线（verdict + reasonCode）
 * 输出：
 *   一致率（verdict 为主，reasonCode 为次）+ 不一致条目明细
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { classifyDefects, type RawDefect } from "../../src/defects/index.js";

const here = dirname(fileURLToPath(import.meta.url));
const verbose = process.argv.includes("--verbose");

interface FixtureDefect {
  idx: number;
  source: string;
  defectId: string;
  status: string;
  severity: string;
  quality: string;
  title: string;
  description: string;
}

interface Fixture {
  productLine: string;
  count: number;
  defects: FixtureDefect[];
}

interface BaselineRow {
  idx: number;
  defectId: string;
  verdict: string;
  reasonCode: string;
  summaryType: string;
}

/** 极简 CSV 解析（支持引号包裹与转义） */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = false;
      } else cell += ch;
      continue;
    }
    if (ch === '"') quoted = true;
    else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (ch !== "\r") cell += ch;
  }
  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c.trim().length));
}

const fixture = JSON.parse(readFileSync(resolve(here, "fixtures/hc-defects.json"), "utf-8")) as Fixture;
const csv = parseCsv(readFileSync(resolve(here, "baseline-labels.csv"), "utf-8").replace(/^\uFEFF/, ""));
const header = csv[0];
const col = (name: string) => header.indexOf(name);
const baseline = new Map<number, BaselineRow>();
for (const r of csv.slice(1)) {
  const idx = Number(r[col("idx")]);
  baseline.set(idx, {
    idx,
    defectId: r[col("defectId")],
    verdict: r[col("verdict")],
    reasonCode: r[col("reasonCode")],
    summaryType: r[col("summaryType")],
  });
}

const raw: RawDefect[] = fixture.defects.map((d) => ({
  defectId: d.defectId,
  title: d.title,
  description: d.description,
  status: d.status,
  severity: d.severity,
  quality: d.quality,
}));

const summary = classifyDefects(raw);

let verdictHit = 0;
let reasonHit = 0;
let typeHit = 0;
const mismatches: Array<{ idx: number; source: string; expV: string; gotV: string; expR: string; gotR: string; rule: string; detail?: string; expT: string; gotT: string; title: string }> = [];
const verdictMismatch: typeof mismatches = [];
const reasonOnlyMismatch: typeof mismatches = [];

for (let i = 0; i < fixture.defects.length; i++) {
  const fx = fixture.defects[i];
  const got = summary.results[i];
  const exp = baseline.get(fx.idx);
  if (!exp) continue;
  const vOk = exp.verdict === got.verdict;
  const rOk = exp.reasonCode === got.reason;
  const tOk = exp.summaryType === got.type;
  if (vOk) verdictHit++;
  if (rOk) reasonHit++;
  if (tOk) typeHit++;
  if (!vOk || !rOk || !tOk) {
    const row = {
      idx: fx.idx,
      source: fx.source,
      expV: exp.verdict,
      gotV: got.verdict,
      expR: exp.reasonCode,
      gotR: got.reason,
      rule: got.rule,
      detail: got.detail,
      expT: exp.summaryType,
      gotT: got.type,
      title: fx.title.replace(/^\s*[\[【][^\]】]+[\]】]\s*/, "").slice(0, 44),
    };
    if (!vOk) verdictMismatch.push(row);
    else if (!rOk) reasonOnlyMismatch.push(row);
    if (!vOk || !rOk) mismatches.push(row);
  }
}

const n = fixture.defects.length;
const pct = (x: number) => `${((x / n) * 100).toFixed(1)}%`;

console.log(`\n=== 一致率（${fixture.productLine}，n=${n}）===`);
console.log(`verdict   ${verdictHit}/${n}  ${pct(verdictHit)}   ← 主指标，目标 ≥90%`);
console.log(`reason    ${reasonHit}/${n}  ${pct(reasonHit)}`);
console.log(`类型       ${typeHit}/${n}  ${pct(typeHit)}`);

console.log(`\n--- 判定分布（规则实现）---`);
console.log(`可修 ${summary.byVerdict.FIXABLE} / 不可修 ${summary.byVerdict.UNFIXABLE}`);
console.log("原因码:", summary.byReason);
console.log("定位档:", summary.byDLevel);
console.log("附件档:", summary.attachment);
console.log("簇数:", summary.byCluster.length, " 其中无语义前缀:", summary.byCluster.filter((c) => c.semanticFree).length);

if (verdictMismatch.length) {
  console.log(`\n--- 判定翻转（${verdictMismatch.length} 条，必须逐条处理）---`);
  for (const m of verdictMismatch) {
    console.log(
      `#${String(m.idx).padStart(3)} ${m.source.padEnd(8)} 期望 ${m.expV}/${m.expR} → 实得 ${m.gotV}/${m.gotR}  [${m.rule}] ${m.detail ?? ""}\n     ${m.title}`,
    );
  }
}
if (reasonOnlyMismatch.length) {
  console.log(`\n--- 仅原因码不一致（${reasonOnlyMismatch.length} 条，判定正确）---`);
  for (const m of reasonOnlyMismatch) {
    console.log(`#${String(m.idx).padStart(3)} ${m.source.padEnd(8)} ${m.expR} → ${m.gotR}  [${m.rule}] ${m.detail ?? ""} | ${m.title}`);
  }
}

// 类型混淆矩阵（只打印不一致）
const typeMis = fixture.defects
  .map((fx, i) => ({ fx, got: summary.results[i], exp: baseline.get(fx.idx) }))
  .filter((x) => x.exp && x.exp.summaryType !== x.got.type);
console.log(`\n--- 类型不一致（${typeMis.length} 条）---`);
const pair = new Map<string, number>();
for (const m of typeMis) {
  const k = `${m.exp!.summaryType} → ${m.got.type}`;
  pair.set(k, (pair.get(k) ?? 0) + 1);
}
for (const [k, v] of [...pair.entries()].sort((a, b) => b[1] - a[1])) console.log(`  ${k}: ${v}`);
if (verbose) {
  for (const m of typeMis) {
    console.log(`  #${String(m.fx.idx).padStart(3)} ${m.exp!.summaryType} → ${m.got.type} | ${m.fx.title.slice(0, 50)}`);
  }
}

console.log("");
process.exitCode = verdictHit / n >= 0.9 ? 0 : 1;
