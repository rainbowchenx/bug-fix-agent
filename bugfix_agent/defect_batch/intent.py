from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from bugfix_agent.contracts.common import Confidence
from bugfix_agent.contracts.defect_batch import Intent, IntentSource
from bugfix_agent.defect_batch.distill import DefectDigest

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


IntentClassifier = Callable[[list[DefectDigest]], dict[str, IntentResult]]


def heuristic_classify_intent(d: DefectDigest) -> IntentResult:
    text = d.fullText
    if re.search(r"CVE-|软件成分分析|漏洞名称|\[安全\]", text):
        return IntentResult("security_scan", "heuristic", "high", "security/CVE signals")
    if re.search(r"崩溃|闪退|白屏|crash", text, re.I) and not re.search(r"没有崩溃|未崩溃", text):
        return IntentResult("crash", "heuristic", "high", "crash keywords")
    if re.search(r"较慢|卡顿|超时|延迟|\d+\s*秒", text):
        return IntentResult("perf", "heuristic", "medium", "performance keywords")
    if re.search(r"火狐|safari|chrome|机型|安卓|ios|兼容", text, re.I):
        return IntentResult("compat", "heuristic", "medium", "compat keywords")
    if re.search(r"未翻译|没有翻译|翻译错误|乱码|文案|词条|i18n", text, re.I):
        return IntentResult("i18n", "heuristic", "high", "i18n keywords")
    if re.search(r"溢出|截断|偏移|间距|边框|遮挡|布局|显示不全|看不到", text):
        return IntentResult("ui_layout", "heuristic", "medium", "ui/layout keywords")
    if re.search(r"配置|开关|权限|鉴权", text):
        return IntentResult("config", "heuristic", "low", "config keywords")
    if re.search(r"数据错误|数量不对|列表为空|未更新|不符", text):
        return IntentResult("data_wrong", "heuristic", "medium", "data keywords")

    if d.fieldType and d.fieldType.strip():
        key = d.fieldType.strip().lower()
        for k, intent in FIELD_MAP.items():
            if k in key:
                return IntentResult(intent, "field_fallback", "low", f"fieldType={d.fieldType}")  # type: ignore[arg-type]

    return IntentResult("unclear", "unclear", "low", "no strong intent signal")


def default_intent_classifier(digests: list[DefectDigest]) -> dict[str, IntentResult]:
    return {d.defectId: heuristic_classify_intent(d) for d in digests}
