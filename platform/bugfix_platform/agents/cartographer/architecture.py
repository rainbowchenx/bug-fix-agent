"""按调用方给定的 cartographyProfile 定点读清单，填 architecture。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from bugfix_contracts.code_knowledge import ArchModule, CartographyProfile, RepoRoot

_SKIP_DIR = {
    "node_modules",
    "dist",
    "dist-electron",
    ".git",
    "coverage",
    ".bugfix-runs",
    ".venv",
    "__pycache__",
}
_MF_SKIP_APPS = {"common", "node_modules", "dist", "shared", "components", "assets"}
_IPC_PREFIX_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*)_[A-Za-z0-9_]+")
_MODULE_KEY_RE = re.compile(r"^\s*([A-Za-z][\w]*)\s*:", re.M)
_GITMODULE_PATH_RE = re.compile(r"^\s*path\s*=\s*(\S+)", re.M)
_MOUNT_ID_RE = re.compile(r"""id\s*=\s*["']([A-Za-z][\w-]*)["']""", re.I)


@dataclass
class MappedArchitecture:
    """``map_architecture`` 的结构化产出。"""

    summary: str
    entry_points: list[str] = field(default_factory=list)
    modules: list[ArchModule] = field(default_factory=list)
    bindings: list[dict[str, Any]] = field(default_factory=list)


def map_architecture(
    work_dir: str | Path,
    repo_roots: list[RepoRoot],
    profile: CartographyProfile,
) -> MappedArchitecture:
    """按已给定的 profile 读清单；不猜测类型。"""
    root = Path(work_dir)
    if profile == "micro_frontend":
        mapped = _map_micro_frontend(root, repo_roots)
    elif profile == "device_web":
        mapped = _map_device_web(root, repo_roots)
    elif profile == "electron_node":
        mapped = _map_electron(root, repo_roots)
    else:
        mapped = MappedArchitecture(
            summary="Profile unknown; architecture map deferred",
            modules=[
                ArchModule(id=rr.path or "root", path=rr.path or ".", role="repo_root")
                for rr in repo_roots
            ]
            or [ArchModule(id="root", path=".", role="repo_root")],
        )

    mapped.entry_points = _dedupe(mapped.entry_points)[:40]
    mapped.modules = _dedupe_modules(mapped.modules)[:60]
    if not mapped.modules:
        for rr in repo_roots:
            mapped.modules.append(
                ArchModule(id=rr.path or "root", path=rr.path or ".", role="repo_root")
            )
    return mapped


def _map_micro_frontend(root: Path, repo_roots: list[RepoRoot]) -> MappedArchitecture:
    search = _search_roots(root, repo_roots)
    modules: list[ArchModule] = []
    entries: list[str] = []
    seen: set[str] = set()

    for base in search:
        rel_base = _rel_to(root, base)
        gitmodules = _read_text(base / ".gitmodules")
        catalog: dict[str, str] = {}
        if gitmodules:
            for raw in _GITMODULE_PATH_RE.findall(gitmodules):
                path = raw.replace("\\", "/").strip()
                name = Path(path).name
                if name.lower() in _MF_SKIP_APPS:
                    continue
                catalog[name] = _join(rel_base, path)

        html = _first_existing(base, ("src/index.html", "index.html"))
        mount_ids = set()
        if html is not None:
            mount_ids = {m.lower() for m in _MOUNT_ID_RE.findall(_read_text(html))}

        for vue_app in _glob_depth(base / "src", "vue.app.js", max_depth=3):
            if vue_app.parent.name.lower() == "mobile":
                app_dir = vue_app.parent.parent
            else:
                app_dir = vue_app.parent
            name = app_dir.name
            if name.lower() in _MF_SKIP_APPS:
                continue
            catalog.setdefault(name, _join(rel_base, _rel_to(base, app_dir)))

        modules_js = _first_existing(
            base, ("build/config/modules.js", "build/config/modules.ts")
        )
        listed: set[str] = set()
        empty_embed: set[str] = set()
        if modules_js is not None:
            text = _read_text(modules_js)
            for key in _MODULE_KEY_RE.findall(text):
                listed.add(key)
                block = _module_block(text, key)
                if block is not None and re.search(r"\[\s*\]", block):
                    empty_embed.add(key)

        for name, path in catalog.items():
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            vue = root / path / "vue.app.js"
            notes_parts = []
            if gitmodules and f"src/{name}" in gitmodules.replace("\\", "/"):
                notes_parts.append("from=.gitmodules")
            if name.lower() in mount_ids or name[:1].lower() + name[1:] in mount_ids:
                notes_parts.append("from=mount-div")
            if name in empty_embed:
                notes_parts.append("CsEmbed empty — nested app, not a regular micro-app")
                modules.append(
                    ArchModule(
                        id=name,
                        path=path,
                        role="embedded_app",
                        notes="; ".join(notes_parts),
                    )
                )
                continue
            if vue.is_file():
                notes_parts.append("entry=vue.app.js")
            modules.append(
                ArchModule(
                    id=name,
                    path=path,
                    role="micro_app",
                    shared=False,
                    notes="; ".join(notes_parts) or "micro-app catalog",
                )
            )

        shell = _first_existing(base, ("src/root-application.js", "src/root-application.ts"))
        if shell is not None and shell.stat().st_size > 0:
            ep = _join(rel_base, _rel_to(base, shell))
            entries.append(ep)
            modules.append(
                ArchModule(id=f"{rel_base or 'root'}:shell", path=ep, role="shell")
            )

        common = None
        for candidate in (base / "src" / "Common", base / "src" / "common"):
            if candidate.is_dir():
                common = candidate
                break
        if common is not None:
            modules.append(
                ArchModule(
                    id="Common",
                    path=_join(rel_base, _rel_to(base, common)),
                    role="shared_kernel",
                    shared=True,
                    notes="shared kernel — not a micro-app",
                )
            )

    summary = "Micro-frontend catalog (gitmodules / mount div / vue.app.js)"
    return MappedArchitecture(
        summary=summary, entry_points=entries, modules=modules
    )


def _map_device_web(root: Path, repo_roots: list[RepoRoot]) -> MappedArchitecture:
    search = _search_roots(root, repo_roots)
    entries: list[str] = []
    modules: list[ArchModule] = []
    for base in search:
        rel_base = _rel_to(root, base)
        for name in ("src/main-pc.js", "src/main-mobile.js", "src/mobile.js"):
            hit = _first_existing(base, (name,))
            if hit is not None:
                entries.append(_join(rel_base, _rel_to(base, hit)))
        for name in ("src/Router/pc.js", "src/Router/mobile.js"):
            hit = _first_existing(base, (name,))
            if hit is not None:
                entries.append(_join(rel_base, _rel_to(base, hit)))
        device = None
        for candidate in (
            base / "src" / "Common" / "service" / "device.js",
            base / "src" / "common" / "service" / "device.js",
        ):
            if candidate.is_file():
                device = candidate
                break
        if device is not None:
            modules.append(
                ArchModule(
                    id="device.js",
                    path=_join(rel_base, _rel_to(base, device)),
                    role="device_capability",
                    notes="capability object — prefer over views for greyed-out features",
                )
            )
        bridge = None
        for candidate in (
            base / "src" / "Common" / "libs" / "jsWebControl",
            base / "src" / "common" / "libs" / "jsWebControl",
        ):
            if candidate.exists():
                bridge = candidate
                break
        if bridge is not None:
            path = _join(rel_base, _rel_to(base, bridge))
            if bridge.is_dir():
                index = next(
                    (
                        p
                        for p in (bridge / "index.js", bridge / "index.ts")
                        if p.is_file()
                    ),
                    None,
                )
                if index is not None:
                    path = _join(rel_base, _rel_to(base, index))
            modules.append(
                ArchModule(
                    id="jsWebControl",
                    path=path,
                    role="device_bridge",
                    notes="real bridge (jsWebControl), not a path named bridge",
                )
            )
        asp = _first_existing(base, ("src/index.asp", "index.asp"))
        if asp is not None:
            modules.append(
                ArchModule(
                    id="host-asp",
                    path=_join(rel_base, _rel_to(base, asp)),
                    role="host",
                    notes="host=device-asp — not an architecture type",
                )
            )
    return MappedArchitecture(
        summary="Device-web dual-entry map (pc/mobile + device.js)",
        entry_points=entries,
        modules=modules,
    )


def _map_electron(root: Path, repo_roots: list[RepoRoot]) -> MappedArchitecture:
    search = _search_roots(root, repo_roots)
    entries: list[str] = []
    modules: list[ArchModule] = []
    bindings: list[dict[str, Any]] = []
    electron_projects: list[Path] = []

    for pkg_path in _rglob_files(root, "package.json", max_depth=5, limit=30):
        pkg = _read_json(pkg_path) or {}
        deps = _deps(pkg)
        if "electron" not in deps and "electron-builder" not in deps:
            continue
        if "electron" not in deps and "vite-plugin-electron" in deps:
            continue
        electron_projects.append(pkg_path.parent)

    if not electron_projects:
        electron_projects = list(search)

    for pkg_dir in electron_projects:
        product = pkg_dir
        parent = pkg_dir.parent
        if parent.resolve() != pkg_dir.resolve() and (
            (parent / "web").is_dir() or (parent / "electron").is_dir()
        ):
            product = parent
        rel = _rel_to(root, product)
        pkg = _read_json(pkg_dir / "package.json") or {}
        main_field = pkg.get("main")
        if isinstance(main_field, str) and main_field.strip():
            # main is relative to the package.json that declared it.
            entries.append(_join(_rel_to(root, pkg_dir), main_field.strip()))

        main_dir = _first_existing_dir(
            product,
            (
                "electron/electron/main",
                "electron/main",
                "src/main",
            ),
        )
        if main_dir is not None:
            main_file = _first_existing(
                main_dir, ("index.ts", "index.js", "main.ts", "main.js")
            )
            path = _join(rel, _rel_to(product, main_file or main_dir))
            entries.append(path)
            modules.append(ArchModule(id="main", path=path, role="main", notes="main process"))

        preload = _find_preload(product) or _find_preload(pkg_dir)
        if preload is not None:
            path = _join(rel, _rel_to(product, preload))
            entries.append(path)
            modules.append(
                ArchModule(
                    id="preload",
                    path=path,
                    role="preload",
                    notes="contextBridge.exposeInMainWorld",
                )
            )
            prefixes = _IPC_PREFIX_RE.findall(_read_text(preload))
            controller_root = _first_existing_dir(
                product,
                ("electron/electron/controller", "electron/controller", "src/controller"),
            )
            if controller_root is not None:
                for child in sorted(controller_root.iterdir(), key=lambda p: p.name.lower()):
                    if not child.is_dir():
                        continue
                    modules.append(
                        ArchModule(
                            id=child.name,
                            path=_join(rel, _rel_to(product, child)),
                            role="ipc_domain",
                            notes=f"controller/{child.name}",
                        )
                    )
            seen_prefix: set[str] = set()
            for prefix in prefixes:
                if prefix in seen_prefix:
                    continue
                seen_prefix.add(prefix)
                ctrl = _controller_for_prefix(controller_root, prefix) if controller_root else None
                ctrl_path = (
                    _join(rel, _rel_to(product, ctrl)) if ctrl is not None else None
                )
                bindings.append(
                    {
                        "kind": "ipc",
                        "prefix": prefix,
                        "path": ctrl_path,
                    }
                )
                if ctrl_path:
                    modules.append(
                        ArchModule(
                            id=f"ipc:{prefix}",
                            path=ctrl_path,
                            role="ipc_domain",
                            notes=f"prefix={prefix}",
                        )
                    )

        renderer = _first_existing(
            product,
            (
                "web/src/main.ts",
                "web/src/main.js",
                "src/renderer/main.ts",
            ),
        )
        # Renderer boot is web/src/main.ts — never views/** or Message/main.vue.
        if renderer is not None and "/views/" not in renderer.as_posix():
            path = _join(rel, _rel_to(product, renderer))
            entries.append(path)
            modules.append(
                ArchModule(id="renderer", path=path, role="renderer", notes="renderer boot")
            )

        web_src = _first_existing_dir(product, ("web/src",))
        if web_src is not None:
            modules.append(
                ArchModule(
                    id="web",
                    path=_join(rel, _rel_to(product, web_src)),
                    role="renderer",
                    notes="renderer tree; not a standalone deployable frontend",
                )
            )

        driver = _first_existing_dir(product, ("electron/driver", "driver"))
        if driver is not None:
            modules.append(
                ArchModule(
                    id="driver",
                    path=_join(rel, _rel_to(product, driver)),
                    role="driver_asset",
                    notes="native driver assets — keep for device-connect defects",
                )
            )

        fork_hint = _find_fork(product)
        if fork_hint is not None:
            bindings.append(
                {
                    "kind": "fork",
                    "path": _join(rel, _rel_to(product, fork_hint)),
                    "via": "fork(subsystem)",
                }
            )

    if not modules:
        modules.append(ArchModule(id="electron", path=".", role="electron_app"))
    return MappedArchitecture(
        summary="Electron process-boundary map (main/preload/renderer + IPC)",
        entry_points=entries,
        modules=modules,
        bindings=bindings,
    )


def _controller_for_prefix(controller_root: Path, prefix: str) -> Path | None:
    if not controller_root.is_dir():
        return None
    compact = re.sub(r"[^a-z0-9]", "", prefix.lower())
    best: Path | None = None
    for child in controller_root.iterdir():
        if not child.is_dir():
            continue
        name = re.sub(r"[^a-z0-9]", "", child.name.lower())
        if name == compact or compact in name or name in compact:
            return child
        if best is None and (prefix.lower() in child.name.lower()):
            best = child
    return best


def _find_preload(proj: Path) -> Path | None:
    for rel in (
        "electron/electron/preload/index.ts",
        "electron/electron/preload/index.js",
        "electron/preload/index.ts",
        "electron/preload.ts",
        "src/preload.ts",
    ):
        candidate = proj / rel
        if candidate.is_file() and "exposeInMainWorld" in _read_text(candidate):
            return candidate
    for path in _rglob_files(proj, "preload", max_depth=6, limit=20, suffix=True):
        if path.suffix.lower() in {".ts", ".js", ".mjs", ".cjs"} and "exposeInMainWorld" in _read_text(
            path
        ):
            return path
    return None


def _find_fork(proj: Path) -> Path | None:
    for path in _rglob_files(proj, "*.ts", max_depth=7, limit=80):
        text = _read_text(path)
        if "fork(" in text and "subsystem" in text.lower():
            return path
    return None


def _search_roots(root: Path, repo_roots: list[RepoRoot]) -> list[Path]:
    out: list[Path] = [root]
    for rr in repo_roots:
        if rr.path in (".", ""):
            continue
        abs_path = (root / rr.path).resolve()
        if abs_path not in {p.resolve() for p in out} and abs_path.is_dir():
            out.append(abs_path)
    return out


def _module_block(text: str, key: str) -> str | None:
    match = re.search(rf"{re.escape(key)}\s*:\s*(\[[^\]]*\])", text)
    return match.group(1) if match else None


def _deps(pkg: dict) -> dict:
    deps: dict = {}
    for key in ("dependencies", "devDependencies"):
        val = pkg.get(key)
        if isinstance(val, dict):
            deps.update(val)
    return deps


def _glob_depth(start: Path, filename: str, *, max_depth: int) -> list[Path]:
    found: list[Path] = []

    def walk(dir_path: Path, depth: int) -> None:
        if depth > max_depth or len(found) >= 80:
            return
        try:
            entries = list(dir_path.iterdir())
        except OSError:
            return
        for item in entries:
            if item.name in _SKIP_DIR or item.name.startswith("."):
                continue
            if item.is_file() and item.name == filename:
                found.append(item)
            elif item.is_dir():
                walk(item, depth + 1)

    if start.is_dir():
        walk(start, 1)
    return found


def _rglob_files(
    root: Path,
    pattern: str,
    *,
    max_depth: int,
    limit: int,
    suffix: bool = False,
) -> list[Path]:
    found: list[Path] = []

    def walk(dir_path: Path, depth: int) -> None:
        if depth > max_depth or len(found) >= limit:
            return
        try:
            entries = list(dir_path.iterdir())
        except OSError:
            return
        for item in entries:
            if item.name in _SKIP_DIR or item.name.startswith("."):
                continue
            if item.is_dir():
                walk(item, depth + 1)
                continue
            if suffix and pattern in item.stem:
                found.append(item)
            elif item.name == pattern or (
                "*" in pattern and item.match(pattern)
            ):
                found.append(item)

    if root.is_dir():
        walk(root, 0)
    return found


def _first_existing(base: Path, rels: Iterable[str]) -> Path | None:
    for rel in rels:
        path = base / rel
        if path.is_file():
            return path
    return None


def _first_existing_dir(base: Path, rels: Iterable[str]) -> Path | None:
    for rel in rels:
        path = base / rel
        if path.is_dir():
            return path
    return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _rel_to(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _join(repo_path: str, rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("./")
    if repo_path in (".", ""):
        return rel
    return f"{repo_path}/{rel}".replace("//", "/")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.replace("\\", "/")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _dedupe_modules(modules: list[ArchModule]) -> list[ArchModule]:
    seen: set[tuple[str, str | None]] = set()
    out: list[ArchModule] = []
    for mod in modules:
        key = (mod.id, (mod.path or "").replace("\\", "/"))
        if key in seen:
            continue
        seen.add(key)
        out.append(mod)
    return out
