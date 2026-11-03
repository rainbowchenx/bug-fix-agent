import type { DefectDigest, RawDefect } from "./types.js";

const END_SIDE_RE =
  /[（(]\s*(?:HPP\s*Portal|APP|App|iOS|H5|flutter(?:\s*[（(]App[）)])?|Web|PC)\s*[）)]/gi;

const MODULE_SEMANTIC_FREE = new Set([
  "系统",
  "安全",
  "其他",
  "其它",
  "checklist",
  "测试要点",
  "ui专项测试",
  "接口测试",
  "控件用例合集",
  "功能稳定性",
  "b2变更",
  "需求变更",
]);

const SEMANTIC_FREE_PREFIX = /^(?:【专项测试】|【海外】|【公共】)/;

export function stripEndSide(s: string): string {
  return s.replace(END_SIDE_RE, "").replace(/\s+/g, " ").trim();
}

export function extractTitleTag(title: string): string {
  const m = /【([^】]+)】|\[([^\]]+)\]/.exec(title);
  const raw = (m?.[1] ?? m?.[2] ?? "").trim();
  if (!raw) return "_untagged";
  const normalized = stripEndSide(raw);
  return normalized || "_untagged";
}

export function normalizeTestModule(raw: string | undefined): {
  testModule: string;
  semanticFree: boolean;
} {
  if (!raw?.trim()) return { testModule: "_unmoduled", semanticFree: false };
  let s = stripEndSide(raw.trim());
  s = s
    .replace(/优化v?\d+(?:\.\d+)*/gi, "")
    .replace(/回归\s*v?\d+(?:\.\d+)*/gi, "")
    .replace(/-?海外版/gi, "")
    .replace(/V\d+(?:\.\d+)?回归功能/gi, "")
    .replace(/（回归）|\(回归\)/gi, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!s) return { testModule: "_unmoduled", semanticFree: false };
  const lower = s.toLowerCase();
  const semanticFree =
    MODULE_SEMANTIC_FREE.has(lower) ||
    MODULE_SEMANTIC_FREE.has(s) ||
    SEMANTIC_FREE_PREFIX.test(s);
  if (semanticFree) {
    return { testModule: `misc/${s}`, semanticFree: true };
  }
  return { testModule: s, semanticFree: false };
}

function sectionAfter(desc: string, labels: string[]): string {
  for (const label of labels) {
    // Require a field delimiter after the label so bare「预期」inside「与预期不一致」does not match.
    const re = new RegExp(
      `(?:^|[\\n\\r])\\s*${label}\\s*[:：]\\s*([\\s\\S]*?)(?=(?:^|[\\n\\r])\\s*(?:实际结果|预期结果|期望结果|复现步骤|操作步骤|问题|建议)\\s*[:：]|$)`,
      "im",
    );
    const m = re.exec(desc);
    if (m?.[1]) {
      const t = m[1].trim();
      if (t) return t;
    }
  }
  return "";
}

export function splitDescription(description: string): {
  observed: string;
  expected: string;
  steps: string;
} {
  const desc = description ?? "";
  const observed = sectionAfter(desc, ["实际结果", "实际现象", "现象"]);
  const expected = sectionAfter(desc, ["预期结果", "期望结果"]);
  const steps = sectionAfter(desc, ["复现步骤", "操作步骤"]);
  return { observed, expected, steps };
}

export function distillDefect(raw: RawDefect): DefectDigest {
  const description = raw.description ?? "";
  const { observed, expected, steps } = splitDescription(description);
  const titleTag = extractTitleTag(raw.title);
  const { testModule, semanticFree } = normalizeTestModule(raw.testModule);
  const fullText = [raw.title, description].filter(Boolean).join("\n");
  return {
    defectId: raw.defectId,
    title: raw.title.trim(),
    description,
    status: raw.status,
    testModuleRaw: raw.testModule,
    fieldType: raw.fieldType,
    severity: raw.severity,
    createdAt: raw.createdAt,
    duplicateOf: raw.duplicateOf,
    duplicate: Boolean(raw.duplicateOf?.trim()),
    titleTag,
    testModule,
    semanticFree,
    observed,
    expected,
    steps,
    fullText,
  };
}

export function distillAll(raws: RawDefect[]): DefectDigest[] {
  return raws.map(distillDefect);
}
