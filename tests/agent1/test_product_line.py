"""productLine 必须能自己定，不能为了它打断用户。

它是 clusterId 的前缀，所以真正要钉住的是**稳定性与唯一性**：同一项目两批要同名，
不同项目不能撞名。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bugfix_agent1.ingest.project import (
    FALLBACK_PRODUCT_LINE,
    PRODUCT_LINE_ENV,
    project_code_from_name,
    resolve_product_line,
)


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv(PRODUCT_LINE_ENV, raising=False)


def test_project_code_from_real_export_names():
    # 两个真实拉取文件名
    assert (
        project_code_from_name("PJ01PM20260711040-当前处理人-xudeng-Open-42条.csv")
        == "PJ01PM20260711040"
    )
    assert project_code_from_name("PJ14PD20260423284-当前处理人-xudeng-Open-19.csv") == (
        "PJ14PD20260423284"
    )
    assert project_code_from_name("export.csv") is None


def test_two_projects_do_not_collide():
    """取首字母 PJ 会撞；完整项目号不会。"""
    a = project_code_from_name("PJ01PM20260711040-….csv")
    b = project_code_from_name("PJ14PD20260423284-….csv")
    assert a != b
    assert a[:2] == b[:2] == "PJ"  # 这就是为什么不能用首字母


def test_explicit_wins(tmp_path: Path):
    src = tmp_path / "PJ01PM20260711040-export.csv"
    src.write_text("x", encoding="utf-8")
    assert resolve_product_line(src, "kajing") == ("kajing", "--product-line")


def test_env_wins_over_derivation(tmp_path: Path, monkeypatch):
    src = tmp_path / "PJ01PM20260711040-export.csv"
    src.write_text("x", encoding="utf-8")
    monkeypatch.setenv(PRODUCT_LINE_ENV, "line-from-env")
    assert resolve_product_line(src) == ("line-from-env", PRODUCT_LINE_ENV)


def test_raw_defects_product_line_is_honored(tmp_path: Path):
    """旧版是死字段：xlsx-to-raw 写进去，prepare 从不读。"""
    src = tmp_path / "export.json"
    src.write_text(
        json.dumps({"productLine": "FROM_FILE", "defects": [{"defectId": "D1", "title": "t"}]}),
        encoding="utf-8",
    )
    assert resolve_product_line(src) == ("FROM_FILE", "raw-defects productLine")


def test_raw_defects_defect_level_fallback(tmp_path: Path):
    src = tmp_path / "export.json"
    src.write_text(
        json.dumps({"defects": [{"defectId": "D1", "title": "t", "productLine": "FROM_DEFECT"}]}),
        encoding="utf-8",
    )
    assert resolve_product_line(src) == ("FROM_DEFECT", "raw-defects defect productLine")


def test_filename_derivation_for_csv(tmp_path: Path):
    src = tmp_path / "PJ01PM20260711040-当前处理人-xudeng-Open-42条.csv"
    src.write_text("缺陷单号,缺陷标题\n", encoding="utf-8")
    assert resolve_product_line(src) == ("PJ01PM20260711040", "filename")


def test_fallback_warns_but_does_not_raise(tmp_path: Path, capsys):
    src = tmp_path / "export.csv"
    src.write_text("缺陷单号,缺陷标题\n", encoding="utf-8")
    assert resolve_product_line(src) == (FALLBACK_PRODUCT_LINE, "fallback")
    err = capsys.readouterr().err
    assert FALLBACK_PRODUCT_LINE in err
    assert PRODUCT_LINE_ENV in err  # 告诉人怎么消掉这个兜底


def test_cli_prepare_derives_without_flag(tmp_path: Path, capsys):
    """端到端：命令里没有 --product-line，产物里也有可用的前缀。"""
    from bugfix_agent1.cli import main

    src = tmp_path / "PJ01PM20260711040-当前处理人-xudeng-Open-2条.csv"
    src.write_text(
        "\ufeff缺陷单号,缺陷标题,缺陷状态,测试模块,缺陷描述\n"
        'BGCM1,[卡警模式] 抓拍计划车道数不对,Open,基本功能检查表-卡警模式,'
        '"实际结果：显示4个车道预期结果：显示1个车道"\n',
        encoding="utf-8",
    )
    out = tmp_path / "b.json"
    assert main(["prepare-batch", "--source", str(src), "--out", str(out)]) == 0

    batch = json.loads(out.read_text(encoding="utf-8"))
    assert batch["productLine"] == "PJ01PM20260711040"
    assert batch["tickets"][0]["clusterId"].startswith("PJ01PM20260711040::")
    assert "via filename" in capsys.readouterr().err


def test_posture_defaults_to_beta(tmp_path: Path):
    from bugfix_agent1.cli import main

    src = tmp_path / "PJ01PM20260711040-x.csv"
    src.write_text(
        "\ufeff缺陷单号,缺陷标题,缺陷状态,缺陷描述\n"
        'A,[卡警模式] 已关单,已解决,"实际结果：x预期结果：y"\n'
        'B,[卡警模式] 还开着,Open,"实际结果：x预期结果：y"\n',
        encoding="utf-8",
    )
    out = tmp_path / "b.json"
    main(["prepare-batch", "--source", str(src), "--out", str(out)])
    batch = json.loads(out.read_text(encoding="utf-8"))

    assert batch["posture"] == "beta"          # 不给就是 beta，不需要问
    assert batch["funnel"]["excluded"] == 1    # 已解决单不归我们处理
    assert batch["funnel"]["total"] == 2
