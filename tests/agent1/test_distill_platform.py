from bugfix_contracts.defect_batch import RawDefect
from bugfix_agent1.defect_batch.distill import distill_defect, split_description
from bugfix_agent1.defect_batch.screen import screen_digest


def test_split_glued_single_line_template():
    desc = (
        "用例名称：上传消息详情展示设备信息与外观一致_室内PIR127"
        "前置条件：子设备实际外观参考交互https://pixso.example.com/x"
        "操作步骤：1.触发以下设备的任意事件，查看键盘消息"
        "测试数据：类型：PSU电源模块"
        "预期结果：1.上传消息详情会展示设备号等信息与实际保持一致"
        "实际结果：web的psu图标不带hikvision字样，7寸键盘上带有该字样，建议统一"
        "问题：1.2.初步定位：无"
    )
    observed, expected, steps = split_description(desc)
    assert "psu图标" in observed
    assert "设备号" in expected
    assert "触发以下设备" in steps


def test_empty_glued_template_needs_info():
    raw = RawDefect(
        defectId="1",
        title="[移动执法] gis地图配置，点击取消弹窗不会自动关闭",
        description="用例名称：前置条件：操作步骤：测试数据：预期结果：实际结果：问题：如其他项目或产品中存同样缺陷，请说明",
        status="Open",
        testModule="移动执法",
    )
    d = distill_defect(raw)
    assert d.emptyTemplate is True
    s = screen_digest(d, posture="alpha")
    assert s.pool == "needs_info"
    assert s.reasonCode == "C1a"


def test_code_review_title_lifts_observed_and_tag():
    raw = RawDefect(
        defectId="2",
        title="问题描述:`.capture-text` 样式块为死代码：模板中该元素已被替换为 `.capture-meta`",
        description="用例名称：前置条件：操作步骤：测试数据：预期结果：实际结果：问题：",
        status="Open",
        testModule="",
    )
    d = distill_defect(raw)
    assert d.titleTag == "_code_review"
    assert "capture-text" in d.observed
    assert d.emptyTemplate is False
    s = screen_digest(d, posture="alpha")
    assert s.pool in {"strict", "locatable_only"}
