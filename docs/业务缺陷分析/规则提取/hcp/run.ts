/**
 * hcp 骨架跑批（安全单剔除后）
 * 用法：npx tsx 规则提取/hcp/run.ts
 */
import { readFileSync } from "node:fs";
import { classifyDefects, HC_PROFILE, type RawDefect } from "../../src/defects/index.js";

const raw = (JSON.parse(readFileSync("规则提取/hcp/fixtures/defects.json", "utf-8")) as RawDefect[])
  .filter((d) => !d.title.startsWith("[安全]")); // 87 条安全扫描单整体剔除（85 SCA + 2 iOS）
const s = classifyDefects(raw, HC_PROFILE);
const p = (n: number) => `${n} (${((n / s.total) * 100).toFixed(1)}%)`;

console.log(`n = ${s.total}（安全单已剔除）| profile = ${s.profile}`);
console.log("①-a 可定位      ", p(s.byVerdict.FIXABLE), "| 不可定位", s.byVerdict.UNFIXABLE, s.byReason);
console.log("①-b 严格可修    ", p(s.strictFixable), "| expectQuality", s.byExpectQuality);
console.log("类型           ", s.byType);
console.log("定位档         ", s.byDLevel);
console.log("分簇           ", s.byCluster.map((c) => `${c.key}:${c.count}`).join(" · "));
