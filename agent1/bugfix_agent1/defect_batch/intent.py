from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from bugfix_contracts.common import Confidence
from bugfix_contracts.defect_batch import Intent, IntentSource
from bugfix_agent1.defect_batch.distill import DefectDigest

FIELD_MAP = {
    "ui": "ui_layout",
    "ui还原": "ui_layout",
    "界面": "ui_layout",
    "文案": "i18n",
    "翻译": "i18n",
    "i18n": "i18n",
    "逻辑": "logic",
    "功能": "logic",
    "性能": "perf",
    "兼容": "compat",
    "配置": "config",
    "崩溃": "crash",
    "安全": "security_scan",
    "数据": "data_wrong",
}


@dataclass
class IntentResult:
    intent: Intent
    intentSource: IntentSource
    intentConfidence: Confidence
    rationale: str


# 「机型」和裸「兼容」曾经在这里，实测全错：平台导出的【前置条件】几乎每张都写
# 「设备机型为…」，产品里还有个叫「兼容模式」的模式名，两者都与兼容性无关。
# 这类语料下宁可落到 unclear（诚实），也别制造 5/5 的假阳性。
COMPAT_RE = re.compile(
    r"火狐|firefox|safari|chrome|安卓|android"
    r"|(?<![a-z])ios(?![a-z])"
    r"|兼容性|不兼容|浏览器版本|插件版本|不同浏览器",
    re.I,
)


IntentClassifier = Callable[[list[DefectDigest]], dict[str, IntentResult]]


def heuristic_classify_intent(d: DefectDigest) -> IntentResult:
    """用关键词 / ``fieldType`` 给单条 digest 打 L3 意图（0 LLM）。

    Args:
        d: 蒸馏产物。

    Returns:
        封闭枚举意图及来源、置信度、理由。
    """
    text = d.fullText
    if re.search(r"CVE-|软件成分分析|漏洞名称|\[安全\]", text):
        return IntentResult("security_scan", "heuristic", "high", "security/CVE signals")
    if re.search(r"崩溃|闪退|白屏|crash", text, re.I) and not re.search(r"没有崩溃|未崩溃", text):
        return IntentResult("crash", "heuristic", "high", "crash keywords")
    if re.search(r"较慢|卡顿|超时|延迟|\d+\s*秒", text):
        return IntentResult("perf", "heuristic", "medium", "performance keywords")
    if COMPAT_RE.search(text):
        return IntentResult("compat", "heuristic", "medium", "compat keywords")
    if re.search(r"未翻译|没有翻译|翻译错误|乱码|文案|词条|i18n", text, re.I):
        return IntentResult("i18n", "heuristic", "high", "i18n keywords")
    if re.search(r"溢出|截断|偏移|间距|边框|遮挡|布局|显示不全|看不到", text):
        return IntentResult("ui_layout", "heuristic", "medium", "ui/layout keywords")
    # data_wrong 必须在 config 之前：「配置下发不一致」「未更新」这类是数据/状态
    # 不对，而「配置」二字在平台模板里遍地都是，先判 config 会把它全吃掉。
    if re.search(r"数据错误|数量不对|列表为空|未更新|不符|不一致", text):
        return IntentResult("data_wrong", "heuristic", "medium", "data keywords")
    if re.search(r"配置|开关|权限|鉴权", text):
        return IntentResult("config", "heuristic", "low", "config keywords")

    if d.fieldType and d.fieldType.strip():
        key = d.fieldType.strip().lower()
        for k, intent in FIELD_MAP.items():
            if k in key:
                return IntentResult(intent, "field_fallback", "low", f"fieldType={d.fieldType}")  # type: ignore[arg-type]

    return IntentResult("unclear", "unclear", "low", "no strong intent signal")


def default_intent_classifier(digests: list[DefectDigest]) -> dict[str, IntentResult]:
    """默认 L3 分类器：对每条 digest 跑 ``heuristic_classify_intent``。

    Args:
        digests: 通常为 ``strict``（或含 ``locatable_only``）池的蒸馏结果。

    Returns:
        ``defectId → IntentResult``。
    """
    return {d.defectId: heuristic_classify_intent(d) for d in digests}
