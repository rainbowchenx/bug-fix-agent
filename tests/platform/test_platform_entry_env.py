"""平台入口必须自己读 zip 里的 .env。

平台只 `import graph`，不会替我们读那个文件。修之前实测：zip 里放着
`ANTHROPIC_API_KEY=…`，import 完 `os.environ` 里依然没有，mode 解析成
`heuristic` —— 配置写了等于没写。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_PROBE = textwrap.dedent(
    """
    import os
    import graph                       # 平台就是这么加载的
    import bugfix_platform
    from bugfix_platform.sdk.analyze import analyze_mode_from_env
    from bugfix_platform.sdk.cartography import cartography_mode_from_env

    assert "bugfix_platform" in bugfix_platform.__file__.replace("\\\\", "/").split("/")[-2:]
    print(bugfix_platform.__file__)
    print(os.environ.get("ANTHROPIC_AUTH_TOKEN") or "")
    print(os.environ.get("ANTHROPIC_MODEL") or "")
    print(cartography_mode_from_env(None))
    print(analyze_mode_from_env(None))
    """
)


def _stage_zip_layout(tmp_path: Path) -> Path:
    """复刻平台包布局：graph.py + 两个包在根级。"""
    import shutil

    shutil.copytree(ROOT / "platform" / "bugfix_platform", tmp_path / "bugfix_platform")
    shutil.copytree(ROOT / "contracts" / "bugfix_contracts", tmp_path / "bugfix_contracts")
    shutil.copy2(ROOT / "packaging" / "platform" / "graph.py", tmp_path / "graph.py")
    return tmp_path


def _run(root: Path, extra_env: dict[str, str]) -> list[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    env.pop("BUGFIX_CARTOGRAPHY_MODE", None)
    env.pop("BUGFIX_ANALYZE_MODE", None)
    env.pop("BUGFIX_ENV_FILE", None)
    env["PYTHONPATH"] = str(root)
    env["PYTHONUTF8"] = "1"
    env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().splitlines()


def test_graph_entry_reads_dotenv(tmp_path: Path):
    root = _stage_zip_layout(tmp_path)
    (root / ".env").write_text(
        "ANTHROPIC_AUTH_TOKEN=bearer-from-env-file\n"
        "ANTHROPIC_MODEL=model-from-env-file\n",
        encoding="utf-8",
    )
    module_path, token, model, cartography, analyze = _run(root, {})
    assert module_path.startswith(str(root)), module_path
    assert token == "bearer-from-env-file"
    assert model == "model-from-env-file"
    # bearer token 也算凭据 → 自动 sdk
    assert cartography == "sdk"
    assert analyze == "sdk"


def test_real_environment_wins_over_dotenv(tmp_path: Path):
    """平台「模型管理」注入的真实变量不能被仓里的 .env 覆盖。"""
    root = _stage_zip_layout(tmp_path)
    (root / ".env").write_text(
        "ANTHROPIC_AUTH_TOKEN=from-file\nANTHROPIC_MODEL=from-file\n", encoding="utf-8"
    )
    _, token, model, _, _ = _run(
        root, {"ANTHROPIC_AUTH_TOKEN": "from-platform", "ANTHROPIC_MODEL": "from-platform"}
    )
    assert token == "from-platform"
    assert model == "from-platform"


def test_missing_dotenv_is_not_an_error(tmp_path: Path):
    root = _stage_zip_layout(tmp_path)
    module_path, token, model, cartography, analyze = _run(root, {})
    assert module_path.startswith(str(root))
    assert (token, model) == ("", "")
    assert cartography == "heuristic"
    assert analyze == "heuristic"
