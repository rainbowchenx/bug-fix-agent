"""检索 token 的取舍：目录名不能当模块信号。

P0-b 修好 `[WEB]` / `[ACS]` / `[NVR]` 这类短英文标签之后，`titleTag` 会变成
一个**真实可命中**的 token —— 而 `web` 在夹具里出现在 device-web 100%、
electron 33% 的文件路径中，毫无区分力。实测的退化（模糊标题票）：

    tag=_untagged（P0-b 之前） → 0 候选, confidence=low
    tag=WEB（P0-b 之后、未修） → 3 候选, confidence=medium, top1 是错的

所以 `web` 进停用表，两处都要：它既会被当作优先 token 放在最前
（`_score_file` 对 index 0 有 +45 加成），也会从标题词里分裂出来。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bugfix_contracts.defect_batch import BatchTicket, DefectBatch
from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_platform.agents.cartographer.match import _tokens

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "repos"


def _ticket(**kw) -> BatchTicket:
    payload = {
        "defectId": "D1",
        "title": "[WEB] 保存失败",
        "pool": "strict",
        "testModule": "_unmoduled",
        "titleTag": "WEB",
        "intent": "unclear",
        "expectQuality": "explicit",
        "fieldType": "缺陷",
    }
    payload.update(kw)
    return BatchTicket.model_validate(payload)


def _batch(ticket: BatchTicket) -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1},
            "clusters": [],
            "tickets": [ticket.model_dump()],
        }
    )


def test_directory_word_is_not_a_query_token():
    toks = _tokens(_ticket(title="[WEB] web端预览黑屏", titleTag="WEB"))
    assert "web" not in toks, toks


def test_vague_web_tag_does_not_invent_candidates():
    """模糊标题 + [WEB] 标签：宁可 0 候选 / low，也不要一堆 web/ 文件 / medium。"""
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(_ticket()),
        cartography_mode="heuristic",
        cartography_profile="electron_node",
    )
    match = knowledge.defectCodeMatches[0]
    assert not "web" in {c.path.split("/")[0] for c in match.candidates}
    assert match.confidence == "low", [c.path for c in match.candidates]


def test_cjk_ascii_boundary_and_chinese_punct():
    """中英边界 + 中文逗号切开；osd 这类短缩写放行；不再吞掉「导流带」。"""
    osd = _tokens(
        _ticket(
            title="[基本功能检查表-按前端区分] 抓拍OSD设置时，拖动osd消失",
            testModule="基本功能检查表-按前端区分",
            titleTag="基本功能检查表-按前端区分",
            intent="ui_layout",
        )
    )
    assert "osd" in osd, osd
    assert all("，" not in t for t in osd), osd
    assert not any(len(t) > 24 for t in osd), osd

    lane = _tokens(
        _ticket(
            title="绘制完压导流带行驶区域后，车道线自动绘制报错未绘制导流带区域",
            testModule="卡警模式",
            titleTag="卡警模式",
            intent="logic",
        )
    )
    assert "导流带" in lane, lane


def test_real_tag_still_reaches_candidates():
    """停用表只针对目录名，不误伤真实模块名（boxCalibration 仍要能命中）。"""
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(
            _ticket(title="[WEB] 盒子校准失败", testModule="boxCalibration", intent="logic")
        ),
        cartography_mode="heuristic",
        cartography_profile="electron_node",
    )
    paths = [c.path for c in knowledge.defectCodeMatches[0].candidates]
    assert paths and "boxCalibration" in paths[0], paths[:3]
