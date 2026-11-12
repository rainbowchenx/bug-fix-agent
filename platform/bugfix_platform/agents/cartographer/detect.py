from __future__ import annotations

import json
import os
import re
from pathlib import Path

from bugfix_contracts.code_knowledge import CartographyProfile, RepoRoot, SpecEntry

_ALLOWED_PROFILES = {"electron_node", "micro_frontend", "device_web", "unknown"}


def normalize_cartography_profile(value: str | None) -> CartographyProfile:
    """调用方给定的仓型；空值视为 ``unknown``，不猜测。"""
    if value is None:
        return "unknown"
    text = str(value).strip()
    if not text:
        return "unknown"
    if text not in _ALLOWED_PROFILES:
        raise ValueError(
            "unsupported cartographyProfile "
            f"{value!r}; expected electron_node|micro_frontend|device_web|unknown"
        )
    return text  # type: ignore[return-value]


def discover_repo_roots(work_dir: str | Path) -> list[RepoRoot]:
    root = Path(work_dir)
    roots: list[RepoRoot] = []
    if (root / "package.json").exists() or (root / ".git").exists() or (root / "pyproject.toml").exists():
        roots.append(
            RepoRoot(path=".", gitHead=_git_head(root), fingerprint=_fingerprint(root))
        )

    try:
        entries = list(root.iterdir())
    except OSError:
        return roots or [RepoRoot(path=".", gitHead=None, fingerprint="empty")]

    for child in entries:
        if not child.is_dir() or child.name.startswith(".") or child.name in {"node_modules", "dist", ".venv"}:
            continue
        if (child / "package.json").exists() or (child / ".git").exists() or (child / "pyproject.toml").exists():
            roots.append(
                RepoRoot(
                    path=child.name,
                    gitHead=_git_head(child),
                    fingerprint=_fingerprint(child),
                )
            )

    _add_container_roots(root, roots)

    return roots or [
        RepoRoot(path=".", gitHead=_git_head(root), fingerprint=_fingerprint(root))
    ]


def _add_container_roots(root: Path, roots: list[RepoRoot]) -> None:
    """容器目录：自身不是仓、但直接子目录是仓／带清单。

    仅在 ``work_dir`` 本身不是仓时启用（否则单仓里的 ``src/`` 也会被当成扫描根，
    而它的子目录恰好都有 ``package.json``）。``led`` 就属于这种情形：
    ``led/calibrationtool/{electron,web}/package.json``，而 ``led/calibrationtool``
    自己没有清单——不补的话 match 完全不扫这棵树。
    """
    if any(r.path in (".", "") for r in roots):
        return
    known = {r.path for r in roots}
    try:
        children = [c for c in root.iterdir() if c.is_dir()]
    except OSError:
        return
    for child in children:
        if child.name.startswith(".") or child.name in {"node_modules", "dist", ".venv"}:
            continue
        if child.name in known:
            continue
        if (child / "package.json").exists() or (child / ".git").exists():
            continue
        if not _readable(child):
            continue
        nested = [
            g
            for g in child.iterdir()
            if g.is_dir()
            and not g.name.startswith(".")
            and g.name not in {"node_modules", "dist", ".venv"}
            and (
                (g / "package.json").exists()
                or (g / ".git").exists()
                or (g / "pyproject.toml").exists()
            )
        ]
        if len(nested) >= 2:
            roots.append(
                RepoRoot(
                    path=child.name,
                    gitHead=_git_head(child),
                    fingerprint=f"{child.name}@container",
                )
            )
            known.add(child.name)


_TS_SCAN_SKIP = {"node_modules", "dist", "build", "coverage", "vendor", "out", "target"}
_TS_SCAN_LIMIT = 20_000


def _has_typescript(dir_path: Path, files: list[str] | None = None) -> bool:
    """仓里真有 TypeScript 才算：``tsconfig.json`` 或存在 ``.ts`` / ``.tsx`` 源文件。

    旧实现只看 ``package.json`` 存在就断言 TS —— transport 与 peitao 的 ``.ts``
    文件数是 **0**，产物里却写着 ``typescript``，下游据此给一个纯 JS/Vue 仓注入
    TS 规则。判据必须是磁盘事实，不是"用了 npm"这个前提。

    ``files``（可选）：调用方已有的仓相对文件表；给了就查表，不走盘。没给才自己
    扫（有 ``_TS_SCAN_LIMIT`` 上限并剪掉依赖/产物目录）。
    """
    if (dir_path / "tsconfig.json").is_file():
        return True
    if files is not None:
        return any(f.endswith((".ts", ".tsx")) for f in files)
    seen = 0
    for base, dirs, files in os.walk(dir_path):
        dirs[:] = [
            d
            for d in dirs
            if d not in _TS_SCAN_SKIP and not d.startswith(".")
        ]
        for name in files:
            if name.endswith((".ts", ".tsx")):
                return True
            seen += 1
            if seen >= _TS_SCAN_LIMIT:
                return False
    return False


def _readable(path: Path) -> bool:
    try:
        next(path.iterdir(), None)
        return True
    except OSError:
        return False


def _git_head(dir_path: Path) -> str | None:
    head = dir_path / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.startswith("ref:"):
        ref = text.split(":", 1)[1].strip()
        ref_path = dir_path / ".git" / ref
        try:
            return ref_path.read_text(encoding="utf-8").strip()[:40] or None
        except OSError:
            return ref
    return text[:40] or None


def _fingerprint(dir_path: Path) -> str:
    pkg = _read_json(dir_path / "package.json")
    if pkg:
        name = str(pkg.get("name") or dir_path.name)
        ver = str(pkg.get("version") or "0")
        return f"{name}@{ver}"
    py = dir_path / "pyproject.toml"
    if py.exists():
        return f"{dir_path.name}@py"
    return dir_path.name


_DEP_KEYS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
    "autoDependencies",
)


def _package_deps(pkg: dict) -> dict:
    """Merge public and private package.json dependency tables."""
    deps: dict = {}
    for key in _DEP_KEYS:
        val = pkg.get(key)
        if isinstance(val, dict):
            deps.update(val)
    return deps


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def detect_cartography_profile(
    work_dir: str | Path,
    repo_roots: list[RepoRoot],
    files_by_root: dict[str, list[str]] | None = None,
) -> tuple[CartographyProfile, list[str], dict]:
    """记录技术栈与线索；**不判型**（第一个返回值恒为 ``unknown``）。

    ``files_by_root``（可选）：调用方已经为 match 建好的仓相对文件表。传进来的话
    判 TypeScript 时直接查表，不再自己走一趟盘——慢盘上那是几秒的重复开销。
    """
    frameworks: set[str] = set()
    languages: set[str] = set()
    hints: list[str] = []
    root = Path(work_dir)

    for rr in repo_roots:
        abs_path = root / rr.path
        pkg = _read_json(abs_path / "package.json") or {}
        deps = _package_deps(pkg)

        if pkg:
            languages.add("javascript")
        if _has_typescript(abs_path, (files_by_root or {}).get(rr.path)):
            languages.add("typescript")
        if "electron" in deps:
            frameworks.add("electron")
            hints.append(f"{rr.path}:electron")
        elif "vite-plugin-electron" in deps:
            hints.append(f"{rr.path}:vite-plugin-electron-only")
        if "single-spa" in deps or "@single-spa/devtools" in deps:
            frameworks.add("single-spa")
            hints.append(f"{rr.path}:single-spa")
        if "vue" in deps or "vue-router" in deps:
            frameworks.add("vue")
        if "react" in deps or "react-dom" in deps:
            frameworks.add("react")
        private = [
            name
            for name in deps
            if name.startswith("@hc-ui/") or name in {"hui-intl", "hui"}
        ]
        if private:
            frameworks.add("vue")
            frameworks.update(private[:6])
            hints.append(f"{rr.path}:autoDependencies")
        if (abs_path / "pyproject.toml").exists() or (abs_path / "requirements.txt").exists():
            languages.add("python")

        try:
            names = [p.name for p in abs_path.iterdir()]
        except OSError:
            continue
        if any(re.search(r"bridge|jsbridge|device-web|webview", n, re.I) for n in names):
            hints.append(f"{rr.path}:device-bridge-path")
        if (abs_path / "src" / "main-pc.js").is_file() and (
            abs_path / "src" / "main-mobile.js"
        ).is_file():
            hints.append(f"{rr.path}:dual-entry")

    if not languages:
        languages.add("unknown")

    return (
        "unknown",
        hints,
        {
            "languages": sorted(languages),
            "frameworks": sorted(frameworks),
            "notes": "cartographyProfile is caller-supplied; detect only records stack hints",
        },
    )


def read_conventions(work_dir: str | Path, repo_roots: list[RepoRoot]) -> dict:
    root = Path(work_dir)
    from_claude: list[str] = []  # 契约保留字段；不再填 CLAUDE.md 截取
    from_rules: list[str] = []
    bound_skills: list[str] = []
    entries: list[SpecEntry] = []
    code_graph = False
    framework_id = "unknown"

    for rr in repo_roots:
        abs_path = root / rr.path
        # 本地索引优先于文档提及：有 .codegraph/codegraph.db 即视为可用。
        cg_db = abs_path / ".codegraph" / "codegraph.db"
        if cg_db.is_file() and cg_db.stat().st_size > 0:
            code_graph = True
        mcp_json = abs_path / ".mcp.json"
        if mcp_json.is_file():
            try:
                if "codegraph" in mcp_json.read_text(encoding="utf-8", errors="ignore").lower():
                    code_graph = True
            except OSError:
                pass

        claude = abs_path / "CLAUDE.md"
        if claude.exists():
            entries.append(SpecEntry(path=f"{rr.path}/CLAUDE.md".replace("./", ""), kind="guide", source="repo_root"))
            try:
                text = claude.read_text(encoding="utf-8")
                # 只取判据，不抄正文：产物里带 CLAUDE.md 截取就是 30 行标题+首句的噪声，
                # 对定位零贡献。文件本身记在 specAtlas.entries 里，要读的人按路径读原文。
                if re.search(r"codegraph|code.?graph", text, re.I):
                    code_graph = True
                if re.search(r"superpowers", text, re.I):
                    framework_id = "superpowers"
                elif re.search(r"openspec", text, re.I):
                    framework_id = "openspec"
                elif re.search(r"trellis", text, re.I):
                    framework_id = "trellis"
            except OSError:
                pass

        skills_dir = abs_path / ".claude" / "skills"
        if skills_dir.is_dir():
            for name in skills_dir.iterdir():
                bound_skills.append(name.name)
                entries.append(
                    SpecEntry(
                        path=f"{rr.path}/.claude/skills/{name.name}",
                        kind="skill",
                        source="claude_dir",
                    )
                )

        rules_dir = abs_path / ".claude" / "rules"
        if rules_dir.is_dir():
            for name in rules_dir.iterdir():
                from_rules.append(name.name)
                entries.append(
                    SpecEntry(
                        path=f"{rr.path}/.claude/rules/{name.name}",
                        kind="rule",
                        source="claude_dir",
                    )
                )

    return {
        "fromClaudeMd": from_claude,
        "fromRules": from_rules,
        "boundSkills": bound_skills,
        "codeGraph": code_graph,
        "frameworkId": framework_id,
        "entries": entries,
    }
