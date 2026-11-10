"""CLI 输出契约：能被机器读、能被人读、能自查。

三条都来自平台实跑暴露的问题，不是假想：

1. exe 在 Windows 上按 cp936 写 stdout，平台按 UTF-8 解码 → `--help` 里
   `ingest → defect-batch.json` 变成 `ingest ?? defect-batch.json`，argparse 的
   中文报错同样遭殃。只有 preflight 单独 reconfigure 过，于是同一支 CLI 两套编码。
2. agent 找 `agent1 validate` 做产物自查，命令不存在，白跑一次工具调用，然后
   手写检查——手写检查正是数字出错的地方。
3. 复核报告要把「补了 N 张 unclear」和「纠了 M 张启发式」混成一句话，实测二者
   被报成 36 张全部来自 unclear + 3 张启发式，实际是 18 + 18。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from bugfix_agent1.cli import _intent_transitions, main
from bugfix_contracts.console import force_utf8_console


# ── 1. 控制台编码 ────────────────────────────────────────────────


def _cp936_stream():
    raw = io.BytesIO()
    return io.TextIOWrapper(raw, encoding="cp936", newline=""), raw


def test_console_is_switched_to_utf8(monkeypatch):
    out, raw = _cp936_stream()
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setattr("sys.stdout", out)
    force_utf8_console()
    assert out.encoding.lower().replace("-", "") == "utf8"
    out.write("缺陷 → defect-batch\n")
    out.flush()
    assert raw.getvalue().decode("utf-8").startswith("缺陷 →")


def test_explicit_pythonioencoding_wins(monkeypatch):
    """用户显式设了编码就别改他的。"""
    out, _ = _cp936_stream()
    monkeypatch.setenv("PYTHONIOENCODING", "cp936")
    monkeypatch.setattr("sys.stdout", out)
    force_utf8_console()
    assert out.encoding.lower() == "cp936"


def test_help_text_survives_utf8(capsys):
    """`--help` 里那个箭头必须原样出来；以前它是 GBK 字节。"""
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "ingest → defect-batch.json" in capsys.readouterr().out


# ── 2. validate 子命令 ───────────────────────────────────────────


def _export(tmp_path: Path) -> Path:
    p = tmp_path / "PJ01PM20260711040-a.csv"
    p.write_text(
        "\ufeff缺陷单号,缺陷标题,缺陷状态,所属模块,缺陷描述\n"
        'A1,[x] 抓拍后无图,Open,抓拍参数,"实际结果：抓拍后没有图片预期结果：抓拍成功"\n',
        encoding="utf-8",
    )
    return p


def test_validate_accepts_rule_output(tmp_path, capsys):
    batch = tmp_path / "b.json"
    main(["prepare-batch", "--source", str(_export(tmp_path)), "--out", str(batch)])
    capsys.readouterr()
    assert main(["validate", "--batch", str(batch)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["tickets"] == 1
    assert payload["clusters"] == {"total": 1, "singleton": 1, "largest": 1}
    assert payload["schemaVersion"]


def test_validate_reports_errors_and_fails(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schemaVersion": "0.1.0",
                "productLine": "x",
                "posture": "beta",
                "generatedAt": "2026-11-10T00:00:00Z",
                "funnel": {},
                "clusters": [],
                "tickets": [{"defectId": "A1"}],
            }
        ),
        encoding="utf-8",
    )
    assert main(["validate", "--batch", str(bad)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "title" in payload["error"]


# ── 3. 复核改动要能分类计数 ──────────────────────────────────────


class _T:
    def __init__(self, defectId, pool="strict", intent=None, intentSource=None):
        self.defectId, self.pool = defectId, pool
        self.intent, self.intentSource = intent, intentSource


class _B:
    def __init__(self, tickets):
        self.tickets = tickets


def test_transitions_separate_unclear_from_heuristic():
    before = _B(
        [
            _T("U1", intent="unclear", intentSource="unclear"),
            _T("U2", intent="unclear", intentSource="unclear"),
            _T("H1", intent="config", intentSource="heuristic"),
            _T("H2", intent="i18n", intentSource="heuristic"),
            _T("N1", pool="needs_info"),
        ]
    )
    after = _B(
        [
            _T("U1", intent="logic", intentSource="ai"),
            _T("U2", intent="logic", intentSource="ai"),
            _T("H1", intent="ui_layout", intentSource="ai"),
            _T("H2", intent="i18n", intentSource="heuristic"),
            _T("N1", pool="needs_info"),
        ]
    )
    assert _intent_transitions(before, after) == {
        "changedIntent": 3,
        "fromUnclear": 2,
        "fromHeuristic": 1,
        "fromNone": 0,
        "keptHeuristic": 1,
        "changedPool": 0,
    }


def test_transitions_count_pool_changes_separately():
    got = _intent_transitions(
        _B([_T("A", pool="needs_info")]),
        _B([_T("A", pool="strict", intent="logic", intentSource="ai")]),
    )
    assert got["changedPool"] == 1
    assert got["fromNone"] == 1
