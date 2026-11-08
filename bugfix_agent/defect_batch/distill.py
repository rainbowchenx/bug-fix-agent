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

# Platform CSVs often glue sections on one line without newlines.
SECTION_LABELS = (
    "用例名称",
    "测试描述",
    "前置条件",
    "操作步骤",
    "复现步骤",
    "测试数据",
    "预期结果",
    "期望结果",
    "实际结果",
    "实际现象",
    "现象",
    "问题描述",
    "问题",
    "建议",
)
SECTION_NEXT = "|".join(SECTION_LABELS)

BOILERPLATE_RE = re.compile(
    r"^(?:如其他项目或产品中存(?:在)?同样缺陷，请说明[:：]?|无|暂无|见标题|同上)[.。\s]*$",
)


@dataclass
class DefectDigest:
    defectId: str
    title: str
    description: str
    status: Optional[str]
    flowStatus: Optional[str]
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
    emptyTemplate: bool = False


def strip_end_side(s: str) -> str:
    return re.sub(r"\s+", " ", END_SIDE_RE.sub("", s)).strip()


def extract_title_tag(title: str) -> str:
    m = re.search(r"【([^】]+)】|\[([^\]]+)\]", title)
    raw = ((m.group(1) if m and m.group(1) else None) or (m.group(2) if m else "") or "").strip()
    if raw:
        # Ignore accidental bracket captures like [Number, String] from code titles
        if re.fullmatch(r"[\d\s,.'\"A-Za-z_+/-]{1,24}", raw) and not re.search(r"[\u4e00-\u9fff]", raw):
            if len(raw) <= 3 or "," in raw or raw in {"0", "''", '""', "当前"}:
                raw = ""
        if raw:
            return strip_end_side(raw) or "_untagged"

    t = title.strip()
    if t.startswith("问题描述:") or t.startswith("问题描述："):
        return "_code_review"
    return "_untagged"


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
    """Extract section body; works for both multiline and glued single-line templates."""
    for label in labels:
        re_pat = re.compile(
            rf"{re.escape(label)}\s*[:：]\s*(.*?)(?=(?:{SECTION_NEXT})\s*[:：]|$)",
            re.I | re.S,
        )
        m = re_pat.search(desc)
        if not m:
            continue
        t = m.group(1).strip()
        t = re.sub(r"\s+", " ", t)
        if t and not BOILERPLATE_RE.match(t):
            return t
    return ""


def split_description(description: str) -> tuple[str, str, str]:
    desc = description or ""
    observed = _section_after(desc, ["实际结果", "实际现象", "现象", "问题描述", "问题"])
    expected = _section_after(desc, ["预期结果", "期望结果"])
    steps = _section_after(desc, ["复现步骤", "操作步骤"])
    return observed, expected, steps


def is_empty_template(description: str, observed: str, expected: str, steps: str) -> bool:
    desc = (description or "").strip()
    if not desc:
        return True
    if "包括复现方法和现象描述等" in desc:
        return True
    # Classic empty glued template
    compact = re.sub(r"\s+", "", desc)
    if re.search(r"用例名称：.*前置条件：.*操作步骤：.*预期结果：.*实际结果：", compact):
        if not observed and not expected and not steps:
            return True
        # only boilerplate after 问题：
        if not expected and not steps and (not observed or BOILERPLATE_RE.match(observed)):
            return True
    if re.search(r"测试描述.*前置条件：.*操作步骤：.*预期结果：", compact) and not expected and not steps:
        if not observed or BOILERPLATE_RE.match(observed):
            return True
    return False


def _observed_from_code_review_title(title: str) -> str:
    m = re.match(r"^问题描述\s*[:：]\s*(.+)$", title.strip(), re.S)
    return m.group(1).strip() if m else ""


def distill_defect(raw: RawDefect) -> DefectDigest:
    """把一条 ``RawDefect`` 蒸馏成结构化 ``DefectDigest``（0 LLM）。

    拆描述模板（observed / expected / steps）、取 L2 标题括注、归一 L1
    测试模块，并标记空模板 / 重复单。

    Args:
        raw: Ingest 之后的原始缺陷。

    Returns:
        供筛选与分簇使用的 ``DefectDigest``。
    """
    description = raw.description or ""
    observed, expected, steps = split_description(description)
    title = raw.title.strip()
    title_tag = extract_title_tag(title)

    # Code-review tickets: body often empty/template; lift detail from title.
    if title_tag == "_code_review" and not observed:
        observed = _observed_from_code_review_title(title)

    empty_template = is_empty_template(description, observed, expected, steps)
    # If title carries the only real signal, don't treat as empty for screening of code reviews
    if title_tag == "_code_review" and observed:
        empty_template = False

    test_module, semantic_free = normalize_test_module(raw.testModule)
    full_text = "\n".join(x for x in [title, description] if x)
    return DefectDigest(
        defectId=raw.defectId,
        title=title,
        description=description,
        status=raw.status,
        flowStatus=raw.flowStatus,
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
        emptyTemplate=empty_template,
    )


def distill_all(raws: list[RawDefect]) -> list[DefectDigest]:
    """批量蒸馏 ``RawDefect`` → ``DefectDigest``。

    Args:
        raws: 原始缺陷列表。

    Returns:
        与输入等长的 ``DefectDigest`` 列表。
    """
    return [distill_defect(r) for r in raws]
