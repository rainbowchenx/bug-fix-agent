#!/usr/bin/env python3
"""把同一个仓库打成两个互不依赖的产品。

    python packaging/build.py            # 两个都打
    python packaging/build.py agent1     # 只打 Agent-1
    python packaging/build.py platform   # 只打平台包

产物：

    dist/agent1-standalone/
        defect-batch-prepare/           skill（SKILL.md + references + scripts）
        defect-batch-prepare/scripts/agent1.exe    零依赖单文件 CLI
        defect-batch-prepare/scripts/agent1.py     同功能源码版
    dist/agent1-standalone.zip

    dist/bugfix-agent-platform.zip      平台包（根级 graph.py + 源码 + skills）

代码边界（两侧只共享 5 个 contracts 文件，见 AGENT1_FILES / PLATFORM_FILES）：

    Agent-1     contracts + ingest + defect_batch      → 图外，独立 CLI
    Platform    contracts + agents + workflow + sdk    → LangGraph 管控

两侧都不导入对方的其余模块。打包时会各生成一份裁剪过的
``bugfix_agent/__init__.py``——仓库里那份是给整仓开发用的，会 import 全部三方。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

# --------------------------------------------------------------------------- #
# 代码边界。显式列出而不是动态推导：动态发现会把 ingest/ 悄悄带进平台包。
# 新增文件必须手动加进来，否则打包测试会失败（见 verify_*）。
# --------------------------------------------------------------------------- #

_SHARED_CONTRACTS = [
    "contracts/__init__.py",
    "contracts/common.py",
    "contracts/defect_batch.py",
    "contracts/analysis_report.py",
    "contracts/code_knowledge.py",
]

AGENT1_FILES = _SHARED_CONTRACTS + [
    "ingest/__init__.py",
    "ingest/field_map.py",
    "ingest/csv_source.py",
    "ingest/preloaded.py",
    "defect_batch/__init__.py",
    "defect_batch/run.py",
    "defect_batch/prepare.py",
    "defect_batch/distill.py",
    "defect_batch/screen.py",
    "defect_batch/rules.py",
    "defect_batch/expect_quality.py",
    "defect_batch/intent.py",
    "defect_batch/cluster.py",
    "defect_batch/review.py",
]

PLATFORM_FILES = _SHARED_CONTRACTS + [
    "agents/__init__.py",
    "agents/analyst/__init__.py",
    "agents/analyst/route.py",
    "agents/analyst/run.py",
    "agents/cartographer/__init__.py",
    "agents/cartographer/architecture.py",
    "agents/cartographer/detect.py",
    "agents/cartographer/match.py",
    "agents/cartographer/run.py",
    "sdk/__init__.py",
    "sdk/analyze.py",
    "sdk/cartography.py",
    "sdk/parse.py",
    "sdk/skills.py",
    "sdk/skill_inject.py",
    "workflow/__init__.py",
    "workflow/graph.py",
    "workflow/gates.py",
    "workflow/persist.py",
    "workflow/run.py",
    "workflow/state.py",
    "workflow/langgraph_app.py",
]

# Agent-1 的 skill 不上平台；平台只需要 Agent-2/3 分析向 skill。
AGENT1_SKILL = "defect-batch-prepare"
PLATFORM_SKILLS = [
    "code-cartography",
    "electron-process-boundary",
    "hierarchical-localization",
    "monorepo-workspace",
    "systematic-debugging",
    "test-triage",
    "typescript-null-safety",
    "vue-debug",
]

AGENT1_INIT = '''"""Agent-1 standalone: defect-batch only. No agents / workflow / sdk / langgraph."""

from bugfix_agent.contracts import (
    CONTRACT_SCHEMA_VERSION,
    DEFECT_BATCH_SCHEMA_VERSION,
    DefectBatch,
    validate_defect_batch,
)
from bugfix_agent.defect_batch import prepare_defect_batch, run_defect_batch_prepare

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "DEFECT_BATCH_SCHEMA_VERSION",
    "DefectBatch",
    "validate_defect_batch",
    "prepare_defect_batch",
    "run_defect_batch_prepare",
]
'''

PLATFORM_INIT = '''"""Platform build: Agent-2/3 under LangGraph. Agent-1 lives outside this graph."""

from bugfix_agent.contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    CONTRACT_SCHEMA_VERSION,
    DEFECT_BATCH_SCHEMA_VERSION,
    AnalysisReport,
    CodeKnowledge,
    DefectBatch,
    validate_analysis_report,
    validate_code_knowledge,
    validate_defect_batch,
)
from bugfix_agent.agents.analyst import run_analyst
from bugfix_agent.agents.cartographer import run_cartographer
from bugfix_agent.workflow import create_three_agent_graph, run_three_agent_workflow

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "DEFECT_BATCH_SCHEMA_VERSION",
    "CODE_KNOWLEDGE_SCHEMA_VERSION",
    "ANALYSIS_REPORT_SCHEMA_VERSION",
    "DefectBatch",
    "CodeKnowledge",
    "AnalysisReport",
    "validate_defect_batch",
    "validate_code_knowledge",
    "validate_analysis_report",
    "run_cartographer",
    "run_analyst",
    "run_three_agent_workflow",
    "create_three_agent_graph",
]
'''


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def strip_pycache(root: Path) -> int:
    """删掉 __pycache__ / *.pyc：验证步骤会 import 暂存树，留下字节码缓存。"""
    n = 0
    for d in root.rglob("__pycache__"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    for p in root.rglob("*.pyc"):
        p.unlink(missing_ok=True)
    return n


def copy_package(files: list[str], dest: Path, init_src: str) -> None:
    """把指定文件拷成 dest/bugfix_agent/...，并把 __init__.py 换成裁剪版。"""
    if dest.exists():
        shutil.rmtree(dest)
    for rel in files:
        src = ROOT / "bugfix_agent" / rel
        if not src.is_file():
            raise SystemExit(f"missing source file: {src}")
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    (dest / "__init__.py").write_text(init_src, encoding="utf-8")


def write_manifest(vendor: Path, label: str) -> None:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - 不是 git 仓库也能打包
        commit = "unknown"
    files = {
        str(p.relative_to(vendor)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(vendor.rglob("*.py"))
    }
    (vendor / "VENDOR.json").write_text(
        json.dumps(
            {
                "source": f"bugfix_agent ({label})",
                "repo": "bugfix-agent",
                "commit": commit,
                "copiedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "note": "generated by packaging/build.py; do not edit by hand",
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# 产品 1：Agent-1 独立包
# --------------------------------------------------------------------------- #

def build_agent1(skip_exe: bool = False) -> Path:
    """产出**只有 exe** 的 skill；源码不进交付包（单一真源在仓库里）。"""
    skill_src = ROOT / "skills" / AGENT1_SKILL
    stage = BUILD / "agent1-stage" / AGENT1_SKILL
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    # --- 构建树：编译 exe 需要完整源码，但这棵树不交付 ---
    log("agent1: staging build tree (not shipped)")
    for name in ("SKILL.md", "requirements.txt"):
        shutil.copy2(skill_src / name, stage / name)
    for sub in ("references", "evals"):
        shutil.copytree(skill_src / sub, stage / sub)
    scripts = stage / "scripts"
    scripts.mkdir()
    for name in ("agent1.py", "preflight.py", "xlsx_to_raw_defects.py"):
        shutil.copy2(skill_src / "scripts" / name, scripts / name)

    vendor = scripts / "_vendor" / "bugfix_agent"
    copy_package(AGENT1_FILES, vendor, AGENT1_INIT)
    write_manifest(vendor.parent, "Agent-1 subset: contracts + ingest + defect_batch")
    log(f"agent1: vendored {len(AGENT1_FILES)} files for the build")

    exe_name = "agent1.exe" if os.name == "nt" else "agent1"
    if skip_exe:
        if not (scripts / exe_name).exists():
            raise SystemExit("agent1: --skip-exe but the staging tree has no prebuilt exe")
    else:
        log("agent1: running PyInstaller (30-60s)")
        stamp = BUILD / "pyinstaller"
        env = dict(os.environ, PYTHONPATH=str(scripts / "_vendor"))
        # 排除清单实测省下约 5.2 MB（16.6 -> 11.4），且已验证 CLI 全子命令仍正常：
        #   libcrypto/libssl 7.6 MB  <- hashlib->_hashlib->OpenSSL；排除后走内置 _sha256
        #   setuptools 1.95 MB + packaging 0.38 MB <- pydantic hook 捎带
        #   pydoc_data 0.61 MB / asyncio / unittest / tkinter 等
        excludes: list[str] = []
        for mod in (
            "setuptools", "pkg_resources", "packaging",
            "pydoc_data", "ssl", "_ssl", "_hashlib",
            "asyncio", "tkinter", "unittest", "lib2to3", "distutils", "xmlrpc",
        ):
            excludes += ["--exclude-module", mod]
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller", "--onefile", "--name", "agent1",
                "--noconfirm", "--clean",
                "--add-data", f"{scripts / '_vendor' / 'VENDOR.json'}{os.pathsep}.",
                "--hidden-import", "openpyxl",
                *excludes,
                "--distpath", str(stamp / "dist"),
                "--workpath", str(stamp / "work"),
                "--specpath", str(stamp),
                str(scripts / "agent1.py"),
            ],
            cwd=scripts, env=env, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        built = stamp / "dist" / exe_name
        shutil.copy2(built, scripts / exe_name)
        log(f"agent1: {exe_name} {(scripts / exe_name).stat().st_size / 1e6:.1f} MB")

    _verify_agent1(scripts)

    # --- 交付包：只放 exe + 文档，源码不进 ---
    log("agent1: assembling exe-only package")
    out = BUILD / "agent1-standalone" / AGENT1_SKILL
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy2(stage / "SKILL.md", out / "SKILL.md")
    for sub in ("references", "evals"):
        shutil.copytree(stage / sub, out / sub)
    (out / "scripts").mkdir()
    shutil.copy2(scripts / exe_name, out / "scripts" / exe_name)
    shutil.copy2(PKG / "agent1" / "README.md", out.parent / "README.md")

    strip_pycache(out.parent)
    _verify_package(out)

    zip_path = DIST / "agent1-standalone.zip"
    zip_tree(out.parent, zip_path)
    log(f"agent1: -> {zip_path.name} {zip_path.stat().st_size / 1e6:.1f} MB")
    return zip_path


def _verify_agent1(scripts: Path) -> None:
    """确认裁剪后的源码树能独立导入（不碰仓库里的 bugfix_agent）。"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "from bugfix_agent.defect_batch import run_defect_batch_prepare;"
        "import bugfix_agent;"
        "assert not hasattr(bugfix_agent, 'run_three_agent_workflow'), 'platform leaked into agent1 build';"
        "assert 'langgraph' not in sys.modules, 'agent1 build pulled langgraph';"
        "print('  ok: agent1 imports clean, no langgraph')"
    ) % (scripts / "_vendor")
    subprocess.run([sys.executable, "-B", "-c", code], check=True, cwd=ROOT, env=env)
    exe = scripts / ("agent1.exe" if os.name == "nt" else "agent1")
    if exe.exists():
        subprocess.run([str(exe), "self-check"], check=True)


def _verify_package(out: Path) -> None:
    """交付包必须只有 exe，且 exe 能在没有源码的目录里对着真实夹具跑完 Step 1。"""
    log("agent1: verifying exe-only package")
    survivors = [p for p in out.rglob("*") if p.is_file()]
    leaked = [
        p for p in survivors
        if p.suffix in (".py", ".pyc") or p.name == "requirements.txt"
    ]
    if leaked:
        raise SystemExit(f"source leaked into the shipped package: {[str(p) for p in leaked]}")
    if not (out / "SKILL.md").is_file():
        raise SystemExit("shipped package is missing SKILL.md")

    exe = out / "scripts" / ("agent1.exe" if os.name == "nt" else "agent1")
    fixture = ROOT / "test" / "fixtures" / "defect-batch" / "hc1-raw.json"
    if not fixture.is_file():
        raise SystemExit(f"missing smoke fixture: {fixture}")
    smoke = BUILD / "smoke"
    smoke.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(exe), "prepare-batch", "--product-line", "smoke",
            "--source", str(fixture), "--out", str(smoke / "batch.json"),
        ],
        check=True, cwd=out, stdout=subprocess.DEVNULL,
    )
    data = json.loads((smoke / "batch.json").read_text(encoding="utf-8"))
    if not data.get("tickets"):
        raise SystemExit("shipped exe produced an empty batch")
    log(f"  ok: {len(survivors)} files, exe made {len(data['tickets'])} tickets from a real fixture")



# --------------------------------------------------------------------------- #
# 产品 2：平台包
# --------------------------------------------------------------------------- #

def build_platform() -> Path:
    log("platform: staging")
    out = BUILD / "platform"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    copy_package(PLATFORM_FILES, out / "bugfix_agent", PLATFORM_INIT)
    log(f"platform: {len(PLATFORM_FILES)} package files")

    for name in PLATFORM_SKILLS:
        shutil.copytree(ROOT / "skills" / name, out / "skills" / name)
    log(f"platform: {len(PLATFORM_SKILLS)} skills")

    for name in ("graph.py", "langgraph.json", "requirements.txt"):
        shutil.copy2(PKG / "platform" / name, out / name)
    shutil.copy2(ROOT / ".env.example", out / ".env.example")
    shutil.copy2(PKG / "platform" / "README.md", out / "README.md")
    (out / ".env").write_text("# 平台复用「模型管理」，这里留空即可。\n", encoding="utf-8")

    log("platform: verifying graph builds from the staged tree alone")
    _verify_platform(out)
    strip_pycache(out)

    zip_path = DIST / "bugfix-agent-platform.zip"
    zip_tree(out, zip_path)
    log(f"platform: -> {zip_path.name} {zip_path.stat().st_size / 1024:.0f} KB")
    return zip_path


def _verify_platform(staging: Path) -> None:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "from graph import graph, build_graph;"
        "assert build_graph() is graph, 'build_graph() must return the same compiled graph';"
        "assert hasattr(graph, 'invoke'), 'graph is not compiled (missing invoke)';"
        "nodes = set(graph.get_graph().nodes);"
        "assert {'agent2', 'agent3'} <= nodes, f'unexpected nodes: {sorted(nodes)}';"
        "assert 'agent1' not in nodes, 'agent1 must stay outside the graph';"
        "print('  ok: graph builds, nodes =', sorted(nodes))"
    ) % staging
    subprocess.run([sys.executable, "-B", "-c", code], check=True, cwd=ROOT, env=env)


# --------------------------------------------------------------------------- #

def zip_tree(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, p.relative_to(src).as_posix())
                n += 1
    log(f"  zipped {n} files")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", choices=["all", "agent1", "platform"], default="all")
    ap.add_argument("--skip-exe", action="store_true", help="agent1: 只组装脚本，不跑 PyInstaller")
    args = ap.parse_args(argv)

    DIST.mkdir(exist_ok=True)
    if args.target in ("all", "agent1"):
        build_agent1(skip_exe=args.skip_exe)
    if args.target in ("all", "platform"):
        build_platform()
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
