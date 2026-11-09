"""Agent-1 打包入口。

胶水层：命令、参数、实现全在 :mod:`bugfix_agent1.cli`。
打包时由一个包外的极短入口调 :func:`entry`。
仓库内请用 ``python -m bugfix_agent1.cli <subcommand>`` 或 ``bugfix-agent``。
"""

from __future__ import annotations

import sys

from bugfix_agent1.cli import main


def entry() -> int:
    """打包 exe 入口。"""
    return main()


if __name__ == "__main__":
    sys.exit(entry())
