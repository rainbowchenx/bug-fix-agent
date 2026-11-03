from __future__ import annotations

import re

from bugfix_agent.contracts.defect_batch import ExpectQuality
from bugfix_agent.defect_batch.distill import DefectDigest

GENERIC_PASS = re.compile(r"^(?:界面正常加载|显示正确|无异常|符合预期|正常|通过|ok|pass)[.。!！\s]*$", re.I)
BENCHMARK = re.compile(r"插件下有|与\s*550\s*基线|与(?!预期).+?(?:一致|不一致|不一样)|设计稿|CS端|对照|基线")
DIRECTION = re.compile(
    r"应(?:该)?(?:显示|为|置灰|禁用|隐藏|保留|对齐|重置|改成|提示)|需要|要改成|应显示为|不显示|不应|不可以|必须"
)
OBJECT_PHENOMENON = re.compile(r"显示|展示|按钮|页面|列表|弹窗|配置|下发|播放|登录|保存")


def _effective_expected(expected: str, title: str) -> str:
    t = expected.strip()
    if not t:
        return ""
    if GENERIC_PASS.match(t):
        return ""
    if t == title.strip() or t.replace(" ", "") == title.replace(" ", ""):
        return ""
    return t


def classify_expect_quality(d: DefectDigest) -> ExpectQuality:
    expect = _effective_expected(d.expected, d.title)
    sig = f"{d.title}\n{d.observed}"
    all_text = f"{d.title}\n{d.observed}\n{d.expected}"

    if expect or BENCHMARK.search(all_text):
        return "explicit"
    if DIRECTION.search(d.title) or DIRECTION.search(expect):
        return "inferred"

    has_object = bool(OBJECT_PHENOMENON.search(sig))
    vague_only = bool(
        re.search(r"显示异常|展示异常|有\d+处异常|异常展示|有点问题", sig) and not DIRECTION.search(sig)
    )
    if vague_only and not has_object:
        return "absent"
    if has_object and (
        ("不一致" in sig and not BENCHMARK.search(sig))
        or ("没有" in sig and not DIRECTION.search(sig))
    ):
        return "ambiguous"
    if not d.observed.strip() and not expect and not DIRECTION.search(d.title):
        return "absent"
    if has_object:
        return "ambiguous"
    return "absent"
