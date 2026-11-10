"""L3 启发式的两条硬约束（来自平台实测的成批误判）。

这份数据里 compat 5/5 全错、config 吞掉 data_wrong。两个机制都不是随机噪声，
是判据本身踩在平台模板的固定成分上，所以用真实串钉死。
"""

from __future__ import annotations

import dataclasses

import pytest

from bugfix_agent1.defect_batch.distill import DefectDigest
from bugfix_agent1.defect_batch.intent import COMPAT_RE, heuristic_classify_intent


def digest(title: str, description: str = "") -> DefectDigest:
    kw = {f.name: "" for f in dataclasses.fields(DefectDigest)}
    kw.update(
        defectId="X",
        title=title,
        description=description,
        fullText=title + description,
        fieldType="缺陷",
        duplicate=False,
        semanticFree=False,
    )
    return DefectDigest(**kw)


def intent(title: str, description: str = "") -> str:
    return heuristic_classify_intent(digest(title, description)).intent


# ── compat：不再吃模板成分 ────────────────────────────────────────


def test_model_name_in_precondition_is_not_compat():
    """平台导出的【前置条件】几乎每张都写「设备机型为…」。"""
    assert intent(
        "[【公共】基本功能检查表-按前端区分] 偶现web预览取流失败，重启后恢复",
        "前置条件：设备机型为电警机型（型号中不带E的机型）操作步骤：1.调节白天切换夜晚阈值。",
    ) != "compat"


def test_compat_mode_is_a_mode_name_not_compatibility():
    """「兼容模式」是产品里的模式名，与兼容性无关。"""
    assert intent("[HSL-041 新增证书校验功能] TLS认证由安全模式切换到兼容模式无安全风险提醒") != "compat"


def test_model_prefix_in_title_is_not_compat():
    for title in (
        "[基本功能检查表-卡警模式] 9396-HL机型，启用【大货车占用超车道】时保存报错",
        "[卡口混合车道] 97C6HEMS/25切ECO机型，抓拍计划页名称变成英文",
        "[【公共】基本功能检查表-快速配置] 98C6-HLS 上一步查看时无法显示预览画面",
    ):
        assert intent(title) != "compat", title


def test_real_compatibility_still_classified():
    assert intent("[卡警模式] 该版本与火狐浏览器不兼容，页面无法加载") == "compat"
    assert intent("[卡警模式] 火狐下预览黑场") == "compat"
    assert intent("[卡警模式] 与 Chrome 版本存在兼容性问题") == "compat"


def test_ios_does_not_match_inside_other_words():
    assert COMPAT_RE.search("iOS端预览黑场")
    assert not COMPAT_RE.search("bios 版本查看失败")


# ── data_wrong 必须排在 config 之前 ────────────────────────────


def test_mismatch_between_web_and_device_is_data_wrong():
    """日志里这条被判成 config：`配置` 命中，`不一致` 永远轮不到。"""
    assert (
        intent(
            "[基本功能检查表-卡警模式] 可变车道设置为空时点击保存，web或取结果与实际下发不一致",
            "用例名称：可变车道支持按星期按时间配置操作步骤：1.配置正确的起始时间",
        )
        == "data_wrong"
    )


def test_ui_does_not_update_is_data_wrong():
    assert intent("[卡警模式] 切总车道数，web只更新了行人线，未更新车道线") == "data_wrong"


def test_pure_config_ticket_still_config():
    assert intent("[HSL-034 敏感信息须加密存储] 格式化磁盘的权限配置缺失") == "config"
    assert intent("[卡警模式] 高级参数里没有启用采集模式的开关") == "config"


def test_unknown_language_stays_unclear_rather_than_guessing():
    """宁可 unclear（诚实），也不制造 config/compat 假阳性。"""
    assert intent("[【公共】基本功能检查表-无插件] 录像回放界面的剪辑接口丢失") == "unclear"
