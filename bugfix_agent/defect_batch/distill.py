from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bugfix_agent.contracts.defect_batch import RawDefect

END_SIDE_RE = re.compile(
    r"[（(]\s*(?:HPP\s*Portal|APP|App|iOS|H5|flutter(?:\s*[（(]App[）)])?|Web|PC)\s*[）)]",
    re.I,
)
MODULE_SEMANTIC_FREE = {
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
}
SEMANTIC_FREE_PREFIX = re.compile(r"^(?:【专项测试】|【海外】|【公共】)")


@dataclass
class DefectDigest:
    defectId: str
    title: str
    description: str
    status: Optional[str]
    testModuleRaw: Optional[str]
    fieldType: Optional[str]
    severity: Optional[str]
    createdAt: Optional[str]
    duplicateOf: Optional[str]
    duplicate: bool
    titleTag: str
    testModule: str
    semanticFree: bool
    observed: str
    expected: str
    steps: str
    fullText: str


def strip_end_side(s: str) -> str:
    return re.sub(r"\s+", " ", END_SIDE_RE.sub("", s)).strip()


def extract_title_tag(title: str) -> str:
    m = re.search(r"【([^】]+)】|\[([^\]]+)\]", title)
    raw = ((m.group(1) if m and m.group(1) else None) or (m.group(2) if m else "") or "").strip()
    if not raw:
        return "_untagged"
    return strip_end_side(raw) or "_untagged"


def normalize_test_module(raw: Optional[str]) -> tuple[str, bool]:
    if not raw or not raw.strip():
        return "_unmoduled", False
    s = strip_end_side(raw.strip())
    s = re.sub(r"优化v?\d+(?:\.\d+)*", "", s, flags=re.I)
    s = re.sub(r"回归\s*v?\d+(?:\.\d+)*", "", s, flags=re.I)
    s = re.sub(r"-?海外版", "", s, flags=re.I)
    s = re.sub(r"V\d+(?:\.\d+)?回归功能", "", s, flags=re.I)
    s = re.sub(r"（回归）|\(回归\)", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "_unmoduled", False
    lower = s.lower()
    semantic_free = (
        lower in MODULE_SEMANTIC_FREE or s in MODULE_SEMANTIC_FREE or bool(SEMANTIC_FREE_PREFIX.match(s))
    )
    if semantic_free:
        return f"misc/{s}", True
    return s, False


def _section_after(desc: str, labels: list[str]) -> str:
    for label in labels:
        re_pat = re.compile(
            rf"(?:^|[\n\r])\s*{re.escape(label)}\s*[:：]\s*([\s\S]*?)"
            rf"(?=(?:^|[\n\r])\s*(?:实际结果|预期结果|期望结果|复现步骤|操作步骤|问题|建议)\s*[:：]|$)",
            re.I | re.M,
        )
        m = re_pat.search(desc)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def split_description(description: str) -> tuple[str, str, str]:
    desc = description or ""
    observed = _section_after(desc, ["实际结果", "实际现象", "现象"])
    expected = _section_after(desc, ["预期结果", "期望结果"])
    steps = _section_after(desc, ["复现步骤", "操作步骤"])
    return observed, expected, steps


def distill_defect(raw: RawDefect) -> DefectDigest:
    description = raw.description or ""
    observed, expected, steps = split_description(description)
    title_tag = extract_title_tag(raw.title)
    test_module, semantic_free = normalize_test_module(raw.testModule)
    full_text = "\n".join(x for x in [raw.title, description] if x)
    return DefectDigest(
        defectId=raw.defectId,
        title=raw.title.strip(),
        description=description,
        status=raw.status,
        testModuleRaw=raw.testModule,
        fieldType=raw.fieldType,
        severity=raw.severity,
        createdAt=raw.createdAt,
        duplicateOf=raw.duplicateOf,
        duplicate=bool((raw.duplicateOf or "").strip()),
        titleTag=title_tag,
        testModule=test_module,
        semanticFree=semantic_free,
        observed=observed,
        expected=expected,
        steps=steps,
        fullText=full_text,
    )


def distill_all(raws: list[RawDefect]) -> list[DefectDigest]:
    return [distill_defect(r) for r in raws]
