"""构建自证。

团队连续三轮拿着旧包跑，日志里看不出区别——唯一能证明版本的是 ``self-check``，
而它三轮只被想起一次。所以版本要打在每次运行的常规输出里。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from bugfix_agent1.ingest.preflight import main as preflight_main
from bugfix_agent1.provenance import build_stamp


def test_stamp_reports_commit_and_vendor_count(tmp_path: Path, monkeypatch):
    manifest = tmp_path / "VENDOR.json"
    manifest.write_text(
        json.dumps({"commit": "e07dcaf", "files": {"a.py": "x", "b.py": "y"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("bugfix_agent1.provenance.manifest_path", lambda: manifest)
    assert build_stamp().startswith("e07dcaf · vendor 2 files ·")


def test_stamp_says_so_when_not_packaged(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "bugfix_agent1.provenance.manifest_path", lambda: tmp_path / "nope.json"
    )
    assert "no VENDOR.json" in build_stamp()


def test_preflight_prints_the_build_first(tmp_path: Path, capsys):
    """版本必须在第一屏 —— 否则日志无法自证跑的是哪份构建。"""
    src = tmp_path / "PJ01PM20260711040-x.csv"
    src.write_text(
        "\ufeff缺陷单号,缺陷标题,缺陷状态,所属模块,缺陷描述\n"
        'A1,[x] 抓拍后无图,Open,抓拍参数,"实际结果：抓拍后没有图片预期结果：抓拍成功"\n',
        encoding="utf-8",
    )
    saved = sys.argv
    sys.argv = ["preflight", "--source", str(src)]
    try:
        preflight_main()
    finally:
        sys.argv = saved
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("build       :"), lines[:3]
