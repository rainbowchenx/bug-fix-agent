import type { DefectDigest, ScreenProfile } from "./types.js";

export const SCANNER_RE =
  /检出工具|软件成分分析|静态检测|hikshield|漏洞名称|SCA|依赖扫描/i;
export const CVE_RE = /CVE-\d+|CVE漏洞/i;

export const CANCEL_RE = /^(?:Cancel|Not\s*a\s*bug|不是缺陷|误报)$/i;

const NOTCODE_BUILTIN: Record<string, RegExp> = {
  "dirty-env": /脏数据|环境问题|环境异常|环境是否/,
  plugin: /启用控件|无插件.+(?:无法播放|黑屏|不能播放|点击无效)/,
  browser: /(?:火狐|safari|chrome).+(?:黑屏|录像失败|无法播放|播放失败)/i,
  "product-decided": /产品已有结论|需要后续优化|后续优化/,
  "service-down": /服务.+异常|hccvis.+异常/i,
  "resource-swap": /还是旧的|改回旧图|要不要替换图片|旧图/,
  "impl-suggestion": /不要写死|写死/,
};

const VAGUE_ADJ =
  /展示异常|显示异常|页面偏移|偏移|兼容有点问题|显示不全|间距问题|多了一个|少了一个|有点问题|不太对/;

const CONCRETE_DETAIL =
  /错误码|error\s*code|https?:\/\/|\d{1,3}(?:\.\d{1,3}){3}|[\w.-]+\.(?:png|jpg|json|xml|ts|js|vue)|顶部|底部|左侧|右侧|遮挡|未翻译|乱码|\d+\s*(?:px|个|条|秒)/i;

const DESIGN_RE =
  /请保持一致|需要保持一致|建议统一|拍板|找能拍板|(?:是否|需确认|确认是否).+(?:展示|保留|增加|支持|修改|统一|翻译)/;

const CRASH_RE = /崩溃|闪退|白屏|crash/i;
const PROB_RE = /偶现|概率|有时|偶尔|不稳定|难以复现/;
const ATTACH_RE =
  /看群里|群里发|没法上传|附件传不|附件上传失败|(?:附件|截图|录屏|视频|文件).+上传失败|上传失败.+(?:附件|截图|录屏)/;
const SLOW_RE = /较慢|太慢|卡顿|超时|延迟|\d+\s*秒后/;

export function isSecurityTitle(title: string): boolean {
  return /^\[安全\]|^【安全】/i.test(title.trim());
}

export function isExcludedStatus(status?: string, flowStatus?: string): boolean {
  const s = (status ?? "").trim();
  const f = (flowStatus ?? "").trim();
  if (CANCEL_RE.test(s) || CANCEL_RE.test(f)) return true;
  if (/作废|不是缺陷|误报/.test(s) || /作废|不是缺陷|误报/.test(f)) return true;
  return false;
}

export function isOpenLike(status?: string): boolean {
  const s = (status ?? "").trim();
  return /^(?:Open|New|打开|新建)$/i.test(s);
}

export type RuleHit = { id: string; detail: string };

export function matchScaCve(d: DefectDigest, profile: ScreenProfile = {}): RuleHit | null {
  const text = d.fullText;
  const scanner = profile.scaSource ?? SCANNER_RE;
  const vuln = profile.scaVuln ?? CVE_RE;
  if (scanner.test(text) && vuln.test(text)) {
    return { id: "C7", detail: "SCA/CVE scanner ticket" };
  }
  return null;
}

export function matchNotCode(d: DefectDigest, profile: ScreenProfile = {}): RuleHit | null {
  const disabled = new Set(profile.disabledNotcode ?? []);
  const text = d.fullText;
  for (const [id, re] of Object.entries(NOTCODE_BUILTIN)) {
    if (disabled.has(id)) continue;
    if (re.test(text)) return { id: `C3:${id}`, detail: `non-code: ${id}` };
  }
  for (const re of profile.notcodeExtra ?? []) {
    if (re.test(text)) return { id: "C3:extra", detail: "profile.notcodeExtra" };
  }
  for (const re of profile.devicePatterns ?? []) {
    if (re.test(text)) return { id: "C3b", detail: "device/protocol side" };
  }
  return null;
}

export function matchDesignUndefined(d: DefectDigest): RuleHit | null {
  const sig = `${d.title}\n${d.observed}`;
  if (/^【?需求变更】?|^\[需求变更\]/.test(d.title.trim())) {
    return { id: "C2", detail: "requirement change" };
  }
  if (DESIGN_RE.test(sig)) {
    if (/基线|550/.test(sig)) return null;
    return { id: "C2", detail: "expectation undefined / needs design input" };
  }
  return null;
}

export function matchRuntimeAttach(d: DefectDigest): RuleHit | null {
  const text = d.fullText;
  const hasStack = /at\s+\w+|Exception|Stack|堆栈|stack\s*trace/i.test(text);
  if (CRASH_RE.test(d.title) && PROB_RE.test(text) && !hasStack) {
    return { id: "C4", detail: "crash/probabilistic without stack" };
  }
  if (/老设备|\d\.\d\.\d+\s*老/.test(text)) {
    return { id: "C4", detail: "depends on old device" };
  }
  if (ATTACH_RE.test(text)) {
    return { id: "C5", detail: "depends on missing attachment" };
  }
  return null;
}

export function matchVague(d: DefectDigest, profile: ScreenProfile = {}): RuleHit | null {
  const placeholder = /包括复现方法和现象描述等/;
  const observedShort = d.observed.trim().length > 0 && d.observed.trim().length < 4;
  if (placeholder.test(d.description) || observedShort) {
    if (profile.rejectEmptyTemplate) {
      return { id: "C1a", detail: "empty / placeholder template" };
    }
  }

  if (CRASH_RE.test(d.title) && !CRASH_RE.test(d.description) && d.description.trim().length < 60) {
    return { id: "C1b", detail: "crash title without body detail" };
  }

  const sig = `${d.title}\n${d.observed}`;
  if (VAGUE_ADJ.test(sig)) {
    const exempt =
      CRASH_RE.test(sig) ||
      /应统一|应一致|保持一致|与.+一致|与.+不一样/.test(sig) ||
      /未翻译|没有翻译|翻译显示|显示为中文|词条/.test(sig) ||
      /增加.+提示|缺少提示|没报错|未做校验/.test(sig) ||
      CONCRETE_DETAIL.test(d.fullText) ||
      (d.expected.trim().length > 0 && /漏翻译|翻译不合理|乱码/.test(d.expected));
    if (!exempt) return { id: "C1c", detail: "vague adjective without quantification" };
  }

  if (SLOW_RE.test(sig) && !/\d+\s*(?:ms|毫秒|秒|s)\b/i.test(sig) && !/\d+%/.test(sig)) {
    return { id: "C1d", detail: "slowness without quantification" };
  }

  if (/报错|报了错|有错误/.test(sig) && !CONCRETE_DETAIL.test(sig) && d.observed.trim().length < 20) {
    return { id: "C1e", detail: "error mentioned without detail" };
  }

  return null;
}
