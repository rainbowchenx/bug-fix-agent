"""分簇形态的两条硬约束。

都来自实测暴露的问题，不是假想：

1. 相对过肥阈值没有绝对下限 → 小批次数学上无法成簇。
   ``fat = len/strict > 0.25`` 在 strict=4 时把任何 2 票簇都切开，簇大小上限
   只剩 ``floor(strict/4)``；5 票批次实测 4 票全部落单。``fat_min`` 是下限，
   取 4：只在 strict ≤ 16 的小批次里生效，大批次行为与原来一致。
2. 短英文模块名曾被当噪声丢弃：``[WEB]``/``[ACS]``/``[NVR]`` 因「纯 ASCII 且
   ≤3 字符」被判为垃圾 → ``_untagged``。实测某海外项目 26 票里 4 票的 L2 丢失。

这两条直接测簇函数本身，绕开筛选器——筛选器有自己的用例。
"""

from __future__ import annotations

import csv
from pathlib import Path

from bugfix_agent1.defect_batch.cluster import rebuild_clusters_from_tickets
from bugfix_agent1.defect_batch.distill import extract_title_tag
from bugfix_agent1.defect_batch.run import run_defect_batch_prepare

PRODUCT_LINE = "PJ01PM20260711040"
HEADER = ["缺陷单号", "缺陷标题", "缺陷状态", "所属模块", "缺陷描述"]


def _base_batch(tmp_path: Path):
    """一张能进 strict 的真实形态票，作为克隆模板。"""
    p = tmp_path / "PJ01PM20260711040-x.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerow(
            [
                "A0",
                "[门禁应用] 按钮被遮挡",
                "Open",
                "门禁应用",
                "实际结果：列表页上方的操作按钮被右侧面板遮挡，无法点击预期结果：按钮完整可见",
            ]
        )
    batch = run_defect_batch_prepare(
        product_line=PRODUCT_LINE, source=str(p), posture="beta"
    )
    assert batch.funnel["strict"] == 1
    return batch


def _clone(tpl, defect_id: str, title: str, module: str, tag: str):
    return tpl.model_copy(
        update={
            "defectId": defect_id,
            "title": title,
            "testModule": module,
            "titleTag": tag,
            "clusterId": None,
            "priority": None,
        }
    )


def _sizes(clusters) -> list[int]:
    return sorted((len(c.defectIds) for c in clusters), reverse=True)


def _same_module_tickets(tpl, n: int, module: str = "门禁应用") -> list:
    """同一模块、同一意图、标题 token 各不相同的 n 张票。"""
    words = ["遮挡", "间距", "截断", "溢出", "偏移", "边框", "重叠", "错位", "挤压", "缺失", "对不齐", "越界"]
    return [
        _clone(tpl, f"A{i}", f"[{module}] 界面{words[i % len(words)]}{i}", module, module)
        for i in range(n)
    ]


def test_small_batch_keeps_a_multi_ticket_cluster(tmp_path: Path):
    """strict=4 里 3 张同模块同意图 → 一个 size 3 的簇，而不是 3 个单票簇。"""
    tpl = _base_batch(tmp_path).tickets[0]
    tickets = _same_module_tickets(tpl, 3)
    tickets.append(_clone(tpl, "B0", "[人员管理] 列表显示错位", "人员管理", "人员管理"))

    clusters = rebuild_clusters_from_tickets(tickets, PRODUCT_LINE)
    assert _sizes(clusters)[0] == 3, _sizes(clusters)
    assert len(clusters) == 2


def test_fat_cluster_is_still_split_in_a_large_batch(tmp_path: Path):
    """下限只救小批次：20 票里 8 张挤一簇（40%）仍要按标题 token 切开。"""
    tpl = _base_batch(tmp_path).tickets[0]
    tickets = _same_module_tickets(tpl, 8)
    tickets += [
        _clone(tpl, f"B{i}", f"[子系统{i}] 界面遮挡{i}", f"子系统{i}", f"子系统{i}")
        for i in range(12)
    ]

    clusters = rebuild_clusters_from_tickets(tickets, PRODUCT_LINE)
    assert _sizes(clusters)[0] < 8, _sizes(clusters)


def test_floor_does_not_change_large_batch_behaviour(tmp_path: Path):
    """关掉下限（fat_min=0）在 20 票批次里应给出完全相同的簇形态。"""
    tpl = _base_batch(tmp_path).tickets[0]
    tickets = _same_module_tickets(tpl, 8)
    tickets += [
        _clone(tpl, f"B{i}", f"[子系统{i}] 界面遮挡{i}", f"子系统{i}", f"子系统{i}")
        for i in range(12)
    ]
    with_floor = _sizes(rebuild_clusters_from_tickets(tickets, PRODUCT_LINE))
    without = _sizes(rebuild_clusters_from_tickets(tickets, PRODUCT_LINE, fat_min=0))
    assert with_floor == without


# ── 短英文标签 ───────────────────────────────────────────────


def test_short_ascii_module_tags_are_not_treated_as_noise():
    for title, want in [
        ("[WEB]iot文案溢出", "WEB"),
        ("[ACS] 权限报错", "ACS"),
        ("[NVR] 通道添加失败", "NVR"),
        ("[IPC] 分辨率保存失败", "IPC"),
        ("[AA02_门禁应用] 图标不展示", "AA02_门禁应用"),
        ("【公共】基本功能检查表-视频", "公共"),
    ]:
        assert extract_title_tag(title) == want, title


def test_real_noise_is_still_dropped():
    """纯数字/符号与代码式的 [Number, String] 仍要丢，否则 L2 全是噪声。"""
    for title in ("[1] 编号重复", "[32] 车道数不对", "[Number, String] 代码标题", "[0] 空"):
        assert extract_title_tag(title) == "_untagged", title
