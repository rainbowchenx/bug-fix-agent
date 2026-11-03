import type { DefectDigest, Intent, IntentSource } from "./types.js";

export const INTENT_ENUM: Intent[] = [
  "ui_layout",
  "i18n",
  "logic",
  "data_wrong",
  "perf",
  "compat",
  "config",
  "security_scan",
  "crash",
  "unclear",
];

export interface IntentResult {
  intent: Intent;
  intentSource: IntentSource;
  intentConfidence: "high" | "medium" | "low";
  rationale: string;
}

export type IntentClassifier = (
  digests: DefectDigest[],
) => Promise<Map<string, IntentResult>> | Map<string, IntentResult>;

const FIELD_MAP: Record<string, Intent> = {
  ui: "ui_layout",
  "ui还原": "ui_layout",
  界面: "ui_layout",
  文案: "i18n",
  翻译: "i18n",
  i18n: "i18n",
  逻辑: "logic",
  功能: "logic",
  性能: "perf",
  兼容: "compat",
  配置: "config",
  崩溃: "crash",
  安全: "security_scan",
  数据: "data_wrong",
};

/** Deterministic heuristic classifier (default; swap for LLM batch later). */
export function heuristicClassifyIntent(d: DefectDigest): IntentResult {
  const text = d.fullText;
  if (/CVE-|软件成分分析|漏洞名称|\[安全\]/.test(text)) {
    return done("security_scan", "heuristic", "high", "security/CVE signals");
  }
  if (/崩溃|闪退|白屏|crash/i.test(text) && !/没有崩溃|未崩溃/.test(text)) {
    return done("crash", "heuristic", "high", "crash keywords");
  }
  if (/较慢|卡顿|超时|延迟|\d+\s*秒/.test(text)) {
    return done("perf", "heuristic", "medium", "performance keywords");
  }
  if (/火狐|safari|chrome|机型|安卓|ios|兼容/i.test(text)) {
    return done("compat", "heuristic", "medium", "compat keywords");
  }
  if (/未翻译|没有翻译|翻译错误|乱码|文案|词条|i18n/i.test(text)) {
    return done("i18n", "heuristic", "high", "i18n keywords");
  }
  if (/溢出|截断|偏移|间距|边框|遮挡|布局|显示不全|看不到/.test(text)) {
    return done("ui_layout", "heuristic", "medium", "ui/layout keywords");
  }
  if (/配置|开关|权限|鉴权/.test(text)) {
    return done("config", "heuristic", "low", "config keywords");
  }
  if (/数据错误|数量不对|列表为空|未更新|不符/.test(text)) {
    return done("data_wrong", "heuristic", "medium", "data keywords");
  }

  if (d.fieldType?.trim()) {
    const key = d.fieldType.trim().toLowerCase();
    for (const [k, intent] of Object.entries(FIELD_MAP)) {
      if (key.includes(k)) {
        return done(intent, "field_fallback", "low", `fieldType=${d.fieldType}`);
      }
    }
  }

  return done("unclear", "unclear", "low", "no strong intent signal");
}

export const defaultIntentClassifier: IntentClassifier = (digests) => {
  const map = new Map<string, IntentResult>();
  for (const d of digests) map.set(d.defectId, heuristicClassifyIntent(d));
  return map;
};

function done(
  intent: Intent,
  intentSource: IntentSource,
  intentConfidence: IntentResult["intentConfidence"],
  rationale: string,
): IntentResult {
  return { intent, intentSource, intentConfidence, rationale };
}
