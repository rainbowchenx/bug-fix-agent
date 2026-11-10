"""交付的 Agent-1 skill 必须自洽：装到 agent 里后，文档里的引用都得打得开。

回归的起因：`SKILL.md` 指向 `docs/contracts/v0.1/defect-batch-guide.md`（仓库内路径），
而这个文件不随 skill 走 → 装到 agent 里就是死链，产物契约那一段等于没写。
现在构建时复制进 `references/`，并用这里的测试钉住。
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_SRC = ROOT / "agent1" / "skills" / "defect-batch-prepare"


def _build_module():
    """直接加载 packaging/build.py，复用它的 bundle / 门禁逻辑，不复制一份规则。"""
    spec = importlib.util.spec_from_file_location(
        "_packaging_build", ROOT / "packaging" / "build.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_mod():
    return _build_module()


def test_bundled_docs_exist_in_repo(build_mod):
    assert build_mod.SKILL_BUNDLED_DOCS, "SKILL.md links the contract doc; it must be bundled"
    for rel, src in build_mod.SKILL_BUNDLED_DOCS.items():
        assert src.is_file(), f"bundled doc missing in repo: {src} ({rel})"


def test_skill_is_self_contained_after_bundling(tmp_path: Path, build_mod):
    """模拟打包：仓库 skill + bundle → 所有引用都能解析。"""
    stage = tmp_path / "defect-batch-prepare"
    shutil.copytree(SKILL_SRC, stage)
    build_mod._bundle_skill_docs(stage)
    build_mod._verify_skill_docs(stage)  # 失败即 SystemExit

    for rel in build_mod.SKILL_BUNDLED_DOCS:
        assert (stage / rel).is_file(), f"not bundled: {rel}"


def test_repo_skill_has_no_dangling_links(build_mod):
    """仓库内那份也不能有断链（否则在里面改文档时看不到目标）。"""
    build_mod._verify_skill_docs(SKILL_SRC)


def test_skill_does_not_ship_python_sources():
    """交付物只有 exe + 文档；skill 目录里不该再出现 .py。"""
    assert not [p for p in SKILL_SRC.rglob("*.py")]
    assert (SKILL_SRC / "SKILL.md").is_file()


def test_bundled_copies_are_byte_identical(tmp_path: Path, build_mod):
    """复制的必须与 docs/contracts/ 下那份逐字节一致，不能是手抄的副本。"""
    stage = tmp_path / "defect-batch-prepare"
    shutil.copytree(SKILL_SRC, stage)
    build_mod._bundle_skill_docs(stage)
    for rel, src in build_mod.SKILL_BUNDLED_DOCS.items():
        shipped = stage / rel
        assert shipped.is_file(), rel
        assert shipped.read_bytes() == src.read_bytes(), f"drifted: {rel}"
        assert shipped.stat().st_size > 0, rel
