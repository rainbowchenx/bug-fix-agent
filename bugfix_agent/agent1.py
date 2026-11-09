"""Agent-1 独立入口：只注册图外的子命令（供打包 exe 用）。

胶水层，不重复定义任何命令——命令、参数、实现全在 :mod:`bugfix_agent.cli`。
``standalone=True`` 让 ``run`` / ``serve`` 不注册，exe 的 ``--help`` 因此不会
列出这个构建带不出去的子命令。

打包时由一个包外的极短入口调 :func:`entry`：包内目录若直接当 script 运行，
``bugfix_agent/http/`` 会遮蔽标准库 ``http``（进而把 ``requests`` 弄崩）。
仓库内请用 ``python -m bugfix_agent.agent1 <subcommand>`` 或 ``bugfix-agent``。
"""

from __future__ import annotations

import sys

from bugfix_agent.cli import main


def entry() -> int:
    """打包入口：只挂 Agent-1 子命令。"""
    return main(standalone=True)


if __name__ == "__main__":
    sys.exit(entry())
