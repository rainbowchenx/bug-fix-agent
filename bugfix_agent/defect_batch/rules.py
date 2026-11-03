from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from bugfix_agent.defect_batch.distill import DefectDigest

SCANNER_RE = re.compile(
    r"检出工具|软件成分分析|静态检测|hikshield|漏洞名称|(?<![A-Za-z])SCA(?![A-Za-z])|依赖扫描",
    re.I,
)
CVE_RE = re.compile(r"CVE-\d+|CVE漏洞", re.I)
CANCEL_RE = re.compile(r"^(?:Cancel|Not\s*a\s*bug|不是缺陷|误报)$", re.I)

NOTCODE_BUILTIN = {
    "dirty-env": re.compile(r"脏数据|环境问题|环境异常|环境是否"),
    # Avoid code-review identifiers like NopluginPlayer / NoPlugin
    "plugin": re.compile(
        r"启用控件|(?<![A-Za-z])无插件(?![A-Za-z]).{0,20}(?:无法播放|黑屏|不能播放|点击无效)"
    ),
    "browser": re.compile(r"(?:火狐|safari|chrome).+(?:黑屏|录像失败|无法播放|播放失败)", re.I),
    "product-decided": re.compile(r"产品已有结论|需要后续优化|后续优化"),
    "service-down": re.compile(r"服务端?异常|服务.+宕机|hccvis.+异常|服务不可用", re.I),
    "resource-swap": re.compile(r"还是旧的|改回旧图|要不要替换图片|旧图"),
    "impl-suggestion": re.compile(r"不要写死|写死"),
}

VAGUE_ADJ = re.compile(
    r"展示异常|显示异常|页面偏移|偏移|兼容有点问题|显示不全|间距问题|多了一个|少了一个|有点问题|不太对"
)
CONCRETE_DETAIL = re.compile(
    r"错误码|error\s*code|https?:\/\/|\d{1,3}(?:\.\d{1,3}){3}|[\w.-]+\.(?:png|jpg|json|xml|ts|js|vue)|顶部|底部|左侧|右侧|遮挡|未翻译|乱码|\d+\s*(?:px|个|条|秒)",
    re.I,
)
DESIGN_RE = re.compile(
    r"请保持一致|需要保持一致|建议统一|拍板|找能拍板|(?:是否|需确认|确认是否).+(?:展示|保留|增加|支持|修改|统一|翻译)"
)
CRASH_RE = re.compile(r"崩溃|闪退|白屏|crash", re.I)
PROB_RE = re.compile(r"偶现|概率|有时|偶尔|不稳定|难以复现")
ATTACH_RE = re.compile(
    r"看群里|群里发|没法上传|附件传不|附件上传失败|(?:附件|截图|录屏|视频|文件).+上传失败|上传失败.+(?:附件|截图|录屏)"
)
SLOW_RE = re.compile(r"较慢|太慢|卡顿|超时|延迟|\d+\s*秒后")


@dataclass
class ScreenProfile:
    # None = default on (reject empty templates). Explicit False opts out.
    reject_empty_template: Optional[bool] = None
    device_patterns: list[re.Pattern[str]] = field(default_factory=list)
    notcode_extra: list[re.Pattern[str]] = field(default_factory=list)
    disabled_notcode: list[str] = field(default_factory=list)
    sca_source: Optional[re.Pattern[str]] = None
    sca_vuln: Optional[re.Pattern[str]] = None


@dataclass
class RuleHit:
    id: str
    detail: str


def is_security_title(title: str) -> bool:
    return bool(re.match(r"^\[安全\]|^【安全】", title.strip(), re.I))


def is_excluded_status(status: Optional[str] = None, flow_status: Optional[str] = None) -> bool:
    s = (status or "").strip()
    f = (flow_status or "").strip()
    if CANCEL_RE.match(s) or CANCEL_RE.match(f):
        return True
    if re.search(r"作废|不是缺陷|误报", s) or re.search(r"作废|不是缺陷|误报", f):
        return True
    return False


def is_open_like(status: Optional[str] = None) -> bool:
    s = (status or "").strip()
    return bool(re.match(r"^(?:Open|New|打开|新建)$", s, re.I))


def match_sca_cve(d: DefectDigest, profile: Optional[ScreenProfile] = None) -> Optional[RuleHit]:
    profile = profile or ScreenProfile()
    scanner = profile.sca_source or SCANNER_RE
    vuln = profile.sca_vuln or CVE_RE
    if scanner.search(d.fullText) and vuln.search(d.fullText):
        return RuleHit("C7", "SCA/CVE scanner ticket")
    return None


def match_not_code(d: DefectDigest, profile: Optional[ScreenProfile] = None) -> Optional[RuleHit]:
    profile = profile or ScreenProfile()
    # Code-review style tickets discuss product code; C3 environment heuristics misfire.
    if getattr(d, "titleTag", "") == "_code_review" or d.title.strip().startswith("问题描述"):
        return None
    disabled = set(profile.disabled_notcode)
    for rid, cre in NOTCODE_BUILTIN.items():
        if rid in disabled:
            continue
        if cre.search(d.fullText):
            return RuleHit(f"C3:{rid}", f"non-code: {rid}")
    for cre in profile.notcode_extra:
        if cre.search(d.fullText):
            return RuleHit("C3:extra", "profile.notcodeExtra")
    for cre in profile.device_patterns:
        if cre.search(d.fullText):
            return RuleHit("C3b", "device/protocol side")
    return None


def match_design_undefined(d: DefectDigest) -> Optional[RuleHit]:
    sig = f"{d.title}\n{d.observed}"
    if re.match(r"^【?需求变更】?|^\[需求变更\]", d.title.strip()):
        return RuleHit("C2", "requirement change")
    if DESIGN_RE.search(sig):
        if re.search(r"基线|550", sig):
            return None
        return RuleHit("C2", "expectation undefined / needs design input")
    return None


def match_runtime_attach(d: DefectDigest) -> Optional[RuleHit]:
    text = d.fullText
    has_stack = bool(re.search(r"at\s+\w+|Exception|Stack|堆栈|stack\s*trace", text, re.I))
    if CRASH_RE.search(d.title) and PROB_RE.search(text) and not has_stack:
        return RuleHit("C4", "crash/probabilistic without stack")
    if re.search(r"老设备|\d\.\d\.\d+\s*老", text):
        return RuleHit("C4", "depends on old device")
    if ATTACH_RE.search(text):
        return RuleHit("C5", "depends on missing attachment")
    return None


def match_vague(d: DefectDigest, profile: Optional[ScreenProfile] = None) -> Optional[RuleHit]:
    profile = profile or ScreenProfile()
    # Empty / placeholder templates are garbage for Agent-1 — always needs_info.
    reject_empty = True if profile.reject_empty_template is None else profile.reject_empty_template
    if reject_empty and getattr(d, "emptyTemplate", False):
        return RuleHit("C1a", "empty / placeholder template")
    if reject_empty and "包括复现方法和现象描述等" in d.description:
        return RuleHit("C1a", "empty / placeholder template")
    observed_short = 0 < len(d.observed.strip()) < 4
    if reject_empty and observed_short and not d.expected.strip() and not d.steps.strip():
        # title-only signal still allowed through other rules; short obs alone is weak
        if not re.search(r"应(?:该)?|需要|必须|与.+一致|未翻译|报错|失败", d.title):
            return RuleHit("C1a", "empty / placeholder template")

    if CRASH_RE.search(d.title) and not CRASH_RE.search(d.description) and len(d.description.strip()) < 60:
        return RuleHit("C1b", "crash title without body detail")

    sig = f"{d.title}\n{d.observed}"
    if VAGUE_ADJ.search(sig):
        exempt = (
            CRASH_RE.search(sig)
            or re.search(r"应统一|应一致|保持一致|与.+一致|与.+不一样", sig)
            or re.search(r"未翻译|没有翻译|翻译显示|显示为中文|词条", sig)
            or re.search(r"增加.+提示|缺少提示|没报错|未做校验", sig)
            or CONCRETE_DETAIL.search(d.fullText)
            or (len(d.expected.strip()) > 0 and re.search(r"漏翻译|翻译不合理|乱码", d.expected))
        )
        if not exempt:
            return RuleHit("C1c", "vague adjective without quantification")

    if SLOW_RE.search(sig) and not re.search(r"\d+\s*(?:ms|毫秒|秒|s)\b", sig, re.I) and not re.search(r"\d+%", sig):
        return RuleHit("C1d", "slowness without quantification")

    if re.search(r"报错|报了错|有错误", sig) and not CONCRETE_DETAIL.search(sig) and len(d.observed.strip()) < 20:
        return RuleHit("C1e", "error mentioned without detail")

    return None
