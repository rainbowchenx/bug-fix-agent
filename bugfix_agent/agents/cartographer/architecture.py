"""形态化架构探测：填 architecture.entryPoints / modules。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from bugfix_agent.contracts.code_knowledge import ArchModule, CartographyProfile, RepoRoot

ELECTRON_MAIN = re.compile(
    r"(?:^|/)(?:electron/)?(?:main|background)(?:[/.-]|\.(?:ts|js|mjs|cjs)$)",
    re.I,
)
ELECTRON_PRELOAD = re.compile(r"(?:^|/)preload(?:[/.-]|\.(?:ts|js|mjs|cjs)$)", re.I)
ELECTRON_RENDERER = re.compile(
    r"(?:^|/)(?:renderer|src/(?:renderer|pages|views)|apps?/renderer)",
    re.I,
)
SPA_APP = re.compile(r"(?:^|/)(?:apps?|packages?|micro)/([^/]+)/", re.I)
BRIDGE = re.compile(r"(?:bridge|jsbridge|device-web|webview|native-?api)", re.I)


def map_architecture(
    work_dir: str | Path,
    repo_roots: list[RepoRoot],
    profile: CartographyProfile,
) -> tuple[str, list[str], list[ArchModule]]:
    """按 cartographyProfile 填 summary 片段、entryPoints、modules。"""
    root = Path(work_dir)
    entry_points: list[str] = []
    modules: list[ArchModule] = []

    for rr in repo_roots:
        abs_path = (root / rr.path).resolve() if rr.path not in (".", "") else root.resolve()
        pkg = _read_json(abs_path / "package.json") or {}
        main_field = pkg.get("main")
        if isinstance(main_field, str) and main_field.strip():
            ep = _join(rr.path, main_field.strip())
            if ep not in entry_points:
                entry_points.append(ep)

        files = _list_src_rel(abs_path, limit=400)
        if profile == "electron_node":
            _map_electron(rr.path, files, entry_points, modules)
        elif profile == "micro_frontend":
            _map_micro_frontend(rr.path, files, entry_points, modules)
        elif profile == "device_web":
            _map_device_web(rr.path, files, entry_points, modules)
        else:
            modules.append(
                ArchModule(id=rr.path or "root", path=rr.path or ".", role="repo_root")
            )

    if not modules:
        for rr in repo_roots:
            modules.append(
                ArchModule(id=rr.path or "root", path=rr.path or ".", role="repo_root")
            )

    summary = {
        "electron_node": "Electron process-boundary map (main/preload/renderer heuristics)",
        "micro_frontend": "Micro-frontend shell/app map (apps|packages heuristics)",
        "device_web": "Device-web / bridge surface map",
        "unknown": "Profile unknown; architecture map deferred",
    }.get(profile, "Profile unknown; architecture map deferred")

    return summary, entry_points[:40], modules[:60]


def _map_electron(
    repo_path: str,
    files: list[str],
    entry_points: list[str],
    modules: list[ArchModule],
) -> None:
    roles: dict[str, list[str]] = {"main": [], "preload": [], "renderer": []}
    for f in files:
        if ELECTRON_MAIN.search(f):
            roles["main"].append(f)
        elif ELECTRON_PRELOAD.search(f):
            roles["preload"].append(f)
        elif ELECTRON_RENDERER.search(f):
            roles["renderer"].append(f)

    for role, paths in roles.items():
        for p in paths[:5]:
            ep = _join(repo_path, p)
            if ep not in entry_points:
                entry_points.append(ep)
            modules.append(
                ArchModule(
                    id=f"{repo_path}:{role}:{Path(p).stem}",
                    path=ep,
                    role=role,
                    notes="electron heuristic",
                )
            )
    if not any(roles.values()):
        modules.append(
            ArchModule(id=f"{repo_path}:electron", path=repo_path or ".", role="electron_app")
        )


def _map_micro_frontend(
    repo_path: str,
    files: list[str],
    entry_points: list[str],
    modules: list[ArchModule],
) -> None:
    apps: dict[str, str] = {}
    for f in files:
        m = SPA_APP.search(f)
        if m:
            name = m.group(1)
            if name in {"node_modules", "dist", "shared", "common"}:
                continue
            apps.setdefault(name, _join(repo_path, f.split(name)[0] + name))
        if "registerApplication" in f or f.endswith("root-config.ts") or f.endswith("root-config.js"):
            ep = _join(repo_path, f)
            if ep not in entry_points:
                entry_points.append(ep)
            modules.append(
                ArchModule(id=f"{repo_path}:shell", path=ep, role="shell", notes="single-spa heuristic")
            )
    for name, base in list(apps.items())[:20]:
        modules.append(
            ArchModule(
                id=f"{repo_path}:app:{name}",
                path=base,
                role="micro_app",
                shared=False,
                notes="path heuristic",
            )
        )
    if not apps and not modules:
        modules.append(
            ArchModule(id=f"{repo_path}:mf", path=repo_path or ".", role="micro_frontend_root")
        )


def _map_device_web(
    repo_path: str,
    files: list[str],
    entry_points: list[str],
    modules: list[ArchModule],
) -> None:
    bridges = [f for f in files if BRIDGE.search(f)]
    for f in bridges[:15]:
        ep = _join(repo_path, f)
        if ep not in entry_points:
            entry_points.append(ep)
        modules.append(
            ArchModule(
                id=f"{repo_path}:bridge:{Path(f).stem}",
                path=ep,
                role="device_bridge",
                notes="bridge path heuristic",
            )
        )
    if not bridges:
        modules.append(
            ArchModule(id=f"{repo_path}:device_web", path=repo_path or ".", role="device_web_root")
        )


def _join(repo_path: str, rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("./")
    if repo_path in (".", ""):
        return rel
    return f"{repo_path}/{rel}".replace("//", "/")


def _list_src_rel(abs_path: Path, *, limit: int = 400) -> list[str]:
    skip = {"node_modules", "dist", ".git", "coverage", ".bugfix-runs", ".venv", "__pycache__"}
    out: list[str] = []

    def walk(dir_path: Path, rel_base: str) -> None:
        if len(out) >= limit:
            return
        try:
            entries = list(dir_path.iterdir())
        except OSError:
            return
        for p in entries:
            if p.name in skip or p.name.startswith("."):
                continue
            rel = f"{rel_base}/{p.name}" if rel_base else p.name
            rel = rel.replace("\\", "/")
            if p.is_dir():
                walk(p, rel)
            elif re.search(r"\.(ts|tsx|js|jsx|vue|mjs|cjs)$", p.name, re.I):
                out.append(rel)

    walk(abs_path, "")
    return out


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
