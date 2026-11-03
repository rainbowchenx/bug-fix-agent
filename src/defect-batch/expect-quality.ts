import type { DefectDigest, ExpectQuality } from "./types.js";

const GENERIC_PASS =
  /^(?:界面正常加载|显示正确|无异常|符合预期|正常|通过|ok|pass)[.。!！\s]*$/i;

const BENCHMARK =
  /插件下有|与\s*550\s*基线|与(?!预期).+?(?:一致|不一致|不一样)|设计稿|CS端|对照|基线/;

const DIRECTION =
  /应(?:该)?(?:显示|为|置灰|禁用|隐藏|保留|对齐|重置|改成|提示)|需要|要改成|应显示为|不显示|不应|不可以|必须/;

const OBJECT_PHENOMENON = /显示|展示|按钮|页面|列表|弹窗|配置|下发|播放|登录|保存/;

function effectiveExpected(expected: string, title: string): string {
  const t = expected.trim();
  if (!t) return "";
  if (GENERIC_PASS.test(t)) return "";
  // copied title only
  if (t === title.trim() || t.replace(/\s+/g, "") === title.replace(/\s+/g, "")) return "";
  return t;
}

export function classifyExpectQuality(d: DefectDigest): ExpectQuality {
  const expect = effectiveExpected(d.expected, d.title);
  const sig = `${d.title}\n${d.observed}`;
  const all = `${d.title}\n${d.observed}\n${d.expected}`;

  if (expect || BENCHMARK.test(all)) return "explicit";
  if (DIRECTION.test(d.title) || DIRECTION.test(expect)) return "inferred";

  const hasObject = OBJECT_PHENOMENON.test(sig);
  const vagueOnly = /显示异常|展示异常|有\d+处异常|异常展示|有点问题/.test(sig) && !DIRECTION.test(sig);
  if (vagueOnly && !hasObject) return "absent";
  if (
    hasObject &&
    ((/不一致/.test(sig) && !BENCHMARK.test(sig)) || (/没有/.test(sig) && !DIRECTION.test(sig)))
  ) {
    return "ambiguous";
  }
  if (!d.observed.trim() && !expect && !DIRECTION.test(d.title)) return "absent";
  if (hasObject) return "ambiguous";
  return "absent";
}
