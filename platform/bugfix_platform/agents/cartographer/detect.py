from __future__ import annotations

import json
import re
from pathlib import Path

from bugfix_contracts.code_knowledge import CartographyProfile, RepoRoot, SpecEntry


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

    return roots or [
        RepoRoot(path=".", gitHead=_git_head(root), fingerprint=_fingerprint(root))
    ]


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


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def detect_cartography_profile(
    work_dir: str | Path,
    repo_roots: list[RepoRoot],
) -> tuple[CartographyProfile, list[str], dict]:
    frameworks: set[str] = set()
    languages: set[str] = set()
    hints: list[str] = []
    profile: CartographyProfile = "unknown"
    root = Path(work_dir)

    for rr in repo_roots:
        abs_path = root / rr.path
        pkg = _read_json(abs_path / "package.json") or {}
        deps = {}
        if isinstance(pkg.get("dependencies"), dict):
            deps.update(pkg["dependencies"])
        if isinstance(pkg.get("devDependencies"), dict):
            deps.update(pkg["devDependencies"])

        if pkg:
            languages.update({"typescript", "javascript"})
        if "electron" in deps or "electron-builder" in deps or "electron-vite" in deps:
            profile = "electron_node"
            frameworks.add("electron")
            hints.append(f"{rr.path}:electron")
        if "single-spa" in deps or "@single-spa/devtools" in deps:
            if profile == "unknown":
                profile = "micro_frontend"
            frameworks.add("single-spa")
            hints.append(f"{rr.path}:single-spa")
        if "vue" in deps or "vue-router" in deps:
            frameworks.add("vue")
        if "react" in deps or "react-dom" in deps:
            frameworks.add("react")
        if (abs_path / "pyproject.toml").exists() or (abs_path / "requirements.txt").exists():
            languages.add("python")

        try:
            names = [p.name for p in abs_path.iterdir()]
        except OSError:
            continue
        if any(re.search(r"bridge|jsbridge|device-web|webview", n, re.I) for n in names):
            if profile == "unknown":
                profile = "device_web"
            hints.append(f"{rr.path}:device-bridge-path")

    if not languages:
        languages.add("unknown")

    return (
        profile,
        hints,
        {
            "languages": sorted(languages),
            "frameworks": sorted(frameworks),
            "notes": "no strong cartography signal" if profile == "unknown" else "",
        },
    )


def read_conventions(work_dir: str | Path, repo_roots: list[RepoRoot]) -> dict:
    root = Path(work_dir)
    from_claude: list[str] = []
    from_rules: list[str] = []
    bound_skills: list[str] = []
    entries: list[SpecEntry] = []
    code_graph = False
    framework_id = "unknown"

    for rr in repo_roots:
        abs_path = root / rr.path
        claude = abs_path / "CLAUDE.md"
        if claude.exists():
            entries.append(SpecEntry(path=f"{rr.path}/CLAUDE.md".replace("./", ""), kind="guide", source="repo_root"))
            try:
                text = claude.read_text(encoding="utf-8")
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:40]
                from_claude.extend(re.sub(r"^#+\s*", "", ln)[:200] for ln in lines)
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
