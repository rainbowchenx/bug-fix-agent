"""preflight 的假绿灯回归。

平台实测：`testModule present 42/42` + `looks healthy`，而其中 17/42 是
【公共】/用例集名（无语义模块），最终 27 个簇里 22 个是单票簇。列「有值」不等于
「有意义」，而这是 agent 判断分簇价值的唯一依据。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bugfix_agent1.ingest.preflight import main

HEADER = "\ufeff缺陷单号,缺陷标题,缺陷状态,测试模块,缺陷描述\n"


def _row(i: int, module: str) -> str:
    return f'A{i},[{module}] 问题{i},Open,{module},"实际结果：x预期结果：y"\n'


def _run(tmp_path: Path, name: str, rows: list[str], capsys) -> str:
    src = tmp_path / name
    src.write_text(HEADER + "".join(rows), encoding="utf-8")
    argv = sys.argv
    sys.argv = ["preflight", "--source", str(src)]
    try:
        main()
    finally:
        sys.argv = argv
    return capsys.readouterr().out


def test_semantic_free_modules_are_reported_and_verdict_warns(tmp_path: Path, capsys):
    rows = [
        _row(1, "【公共】基本功能检查表-抓拍参数"),
        _row(2, "【公共】基本功能检查表-视频"),
        _row(3, "控件用例合集"),
        _row(4, "基本功能检查表-卡警模式"),
        _row(5, "基本功能检查表-卡警模式"),
    ]
    out = _run(tmp_path, "PJ01PM20260711040-x.csv", rows, capsys)

    assert "testModule semantic-free : 3/5 (60%)" in out
    assert "distinct modules (L1)    : 4" in out
    assert "carry no product semantics" in out
    assert "looks healthy: rows map, description present, module present\n" not in out


def test_healthy_export_does_not_warn(tmp_path: Path, capsys):
    rows = [
        _row(1, "基本功能检查表-卡警模式"),
        _row(2, "基本功能检查表-抓拍参数"),
        _row(3, "卡口混合车道"),
    ]
    out = _run(tmp_path, "PJ01PM20260711040-y.csv", rows, capsys)
    assert "semantic-free : 0/3 (0%)" in out
    assert "looks healthy" in out
    assert "carry no product semantics" not in out


def test_missing_module_column_keeps_its_own_verdict(tmp_path: Path, capsys):
    src = tmp_path / "PJ01PM20260711040-z.csv"
    src.write_text(
        "\ufeff缺陷单号,缺陷标题,缺陷状态,缺陷描述\n"
        'A1,[卡警模式] 问题,Open,"实际结果：x预期结果：y"\n',
        encoding="utf-8",
    )
    argv = sys.argv
    sys.argv = ["preflight", "--source", str(src)]
    try:
        main()
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "testModule present       : 0/1" in out
    assert "no module column mapped" in out
