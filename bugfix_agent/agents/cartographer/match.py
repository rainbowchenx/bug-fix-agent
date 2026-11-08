from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from bugfix_agent.contracts.code_knowledge import DefectCodeMatch, MatchCandidate, RepoRoot
from bugfix_agent.contracts.defect_batch import BatchTicket

SKIP_DIRS = {
    "node_modules",
    "dist",
    "build",
    "out",
    "target",
    "vendor",
    "third_party",
    "third-party",
    "coverage",
    ".bugfix-runs",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".turbo",
    ".yarn",
    "Pods",
}
SRC_EXT = re.compile(r"\.(ts|tsx|js|jsx|vue|py|go|java|kt|cs)$", re.I)
MAX_CANDIDATES = 3  # A3
# Soft ceiling only — real product repos are often >>800 files; ranking handles noise.
MAX_FILES_DEFAULT = 50_000

# Path segments / basename patterns that are usually tests or fixtures.
_TEST_PATH_RE = re.compile(
    r"(?:^|/)(?:tests?|testing|__tests__|e2e|spec|fixtures?|mocks?|testdata)(?:/|$)"
    r"|(?:^|/).*[._-](?:test|spec|tests)(?:\.[^/]+)?$"
    r"|(?:^|/)integrations?(?:/|$)",
    re.I,
)
_SRC_HINT_RE = re.compile(
    r"(?:^|/)(?:src|lib|pkg|packages?|app|apps|cmd|internal|server|core|components?)(?:/|$)",
    re.I,
)

# Intent / filler tokens that match too many paths if used as substrings.
_STOP_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "通用",
    "问题描述",
    "缺陷",
    "unclear",
    "config",
    "logic",
    "compat",
    "crash",
    "data_wrong",
    "ui_layout",
    "security_scan",
    "i18n",
    "perf",
}


def _walk_files(root: Path, max_files: int = MAX_FILES_DEFAULT) -> list[str]:
    """Collect source paths with preferred dirs first so large repos still surface src/pkg."""
    preferred: list[str] = []
    rest: list[str] = []

    def walk(dir_path: Path, rel_base: str, bucket: list[str]) -> None:
        if len(preferred) + len(rest) >= max_files:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        # Prefer source-like children before test-like siblings at each level.
        entries.sort(key=lambda p: (0 if _is_src_hint(p.name) else 1, p.name.lower()))
        for p in entries:
            if p.name in SKIP_DIRS or p.name.startswith("."):
                continue
            rel = f"{rel_base}/{p.name}" if rel_base else p.name
            rel = rel.replace("\\", "/")
            if p.is_dir():
                child_bucket = preferred if _is_src_hint(rel) and not _is_test_path(rel) else bucket
                walk(p, rel, child_bucket)
            elif SRC_EXT.search(p.name):
                target = preferred if _is_src_hint(rel) and not _is_test_path(rel) else rest
                if len(preferred) + len(rest) < max_files:
                    target.append(rel)

    walk(root, "", rest)
    # Preferred first, then the remainder — ranking still reorders matches.
    return preferred + rest


def _is_test_path(rel: str) -> bool:
    return bool(_TEST_PATH_RE.search(rel.replace("\\", "/")))


def _is_src_hint(rel: str) -> bool:
    return bool(_SRC_HINT_RE.search(rel.replace("\\", "/")))


def _tokens(ticket: BatchTicket) -> list[str]:
    """Query tokens: title + titleTag / testModule / intent（不灌蒸馏全文，见 C8）。"""
    title = ticket.title or ""
    title = re.sub(r"【[^】]+】|\[[^\]]+\]", " ", title)
    raw = " ".join(
        x for x in [title, ticket.titleTag, ticket.testModule, ticket.intent] if x
    )
    parts = re.split(r"[\s/|_\-【】\[\]（）():：,.@]+", raw)
    toks: list[str] = []
    for s in parts:
        t = s.strip().lower()
        if not t or t in _STOP_TOKENS:
            continue
        # ASCII: require length ≥3 to avoid "down"⊂downloads / "css"⊂postcss noise.
        if re.fullmatch(r"[a-z0-9_\-]+", t):
            if len(t) < 3:
                continue
        elif len(t) < 2:
            continue
        toks.append(t)
    # Chinese runs from title (cheap signal); keep short phrases only.
    for m in re.finditer(r"[\u4e00-\u9fff]{2,6}", title):
        toks.append(m.group(0).lower())

    # Prefer distinctive tokens first: testModule / titleTag, then longer ascii.
    priority: list[str] = []
    for key in (ticket.testModule, ticket.titleTag):
        if not key:
            continue
        k = key.strip().lower()
        if k and k not in _STOP_TOKENS and k not in priority:
            if re.fullmatch(r"[a-z0-9_\-]+", k) and len(k) < 3:
                continue
            priority.append(k)

    seen: set[str] = set()
    out: list[str] = []
    for t in priority + sorted(
        (x for x in toks if x not in priority),
        key=lambda x: (-len(x), x),
    ):
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 12:
            break
    return out


def _basename_pieces(stem: str) -> set[str]:
    pieces = {stem}
    for piece in re.split(r"[_\-.]+", stem):
        if piece:
            pieces.add(piece)
    return pieces


def _dir_piece_hit(rel: str, tok: str) -> tuple[int, str] | None:
    """Match token against directory / package folder names (e.g. @tailwindcss-vite)."""
    fl = rel.replace("\\", "/").lower()
    parts = fl.split("/")[:-1]  # parents only
    for part in parts:
        name = part.lower()
        if name.startswith("@"):
            name = name[1:]
        pieces = _basename_pieces(name)
        if tok == name or tok in pieces:
            # packages/@scope-name/src/index.ts — strong package localization
            return 125 + len(tok), f'package/dir "{tok}"'
        if f"-{tok}" in f"-{name}" or f"_{tok}" in f"_{name}":
            return 115 + len(tok), f'package/dir contains "{tok}"'
    if f"/{tok}/" in f"/{'/'.join(parts)}/" or (parts and parts[-1] == tok):
        return 55 + len(tok), f'dir segment "{tok}"'
    return None


def _token_hit_strength(rel: str, tok: str) -> tuple[int, str] | None:
    """Return (strength, why) if tok matches path; higher is better.

    Basename / filename stem beats parent-dir segment matches so that
    ``pkg/session/session_store.go`` outranks ``pkg/session/allocator.go``
    for token ``session``.
    """
    fl = rel.replace("\\", "/").lower()
    stem = Path(fl).stem
    if tok not in fl:
        return None

    base_pieces = _basename_pieces(stem)
    if stem == tok:
        return 140 + len(tok), f'exact basename "{tok}"'
    if tok in base_pieces:
        return 110 + len(tok), f'basename piece "{tok}"'
    if tok in stem and (
        stem.startswith(tok)
        or stem.endswith(tok)
        or f"-{tok}" in stem
        or f"_{tok}" in stem
        or f".{tok}" in stem
    ):
        return 90 + len(tok), f'basename contains "{tok}"'

    dir_hit = _dir_piece_hit(fl, tok)
    if dir_hit is not None:
        return dir_hit

    if tok in stem:
        # weak: css ⊂ postcss
        return 15 + len(tok) // 2, f'weak basename substring "{tok}"'
    return 10 + len(tok) // 2, f'path substring "{tok}"'


def _score_file(rel: str, toks: list[str]) -> tuple[int, str] | None:
    hits: list[tuple[int, str]] = []
    for i, tok in enumerate(toks):
        hit = _token_hit_strength(rel, tok)
        if hit is None:
            continue
        strength, why = hit
        # testModule / first query token dominates secondary title words (plugin/loader).
        if i == 0:
            strength += 45
        hits.append((strength, why))
    if not hits:
        return None
    hits.sort(key=lambda x: -x[0])
    strength, why = hits[0]
    # Multi-token agreement is a strong localization signal.
    if len(hits) >= 2:
        strength += 35 + min(30, hits[1][0] // 4)
        why = f"{why}+{hits[1][1]}"
    if _is_src_hint(rel):
        strength += 25
    # Prefer package entrypoints lightly when the package dir already matched.
    base = Path(rel.replace("\\", "/")).name.lower()
    if base in {"index.ts", "index.tsx", "index.js", "index.jsx", "mod.go", "main.go"}:
        strength += 12
    if _is_test_path(rel):
        strength -= 90
    return strength, why


def match_tickets(
    work_dir: str | Path,
    repo_roots: list[RepoRoot],
    tickets: list[BatchTicket],
    *,
    code_graph: bool = False,
    max_files: int = MAX_FILES_DEFAULT,
) -> list[DefectCodeMatch]:
    """Soft-localize tickets by ranked path tokens (large-repo safe).

    Does **not** stop after the first walk hits — scores all scanned files and
    keeps the top ``MAX_CANDIDATES``. Test/fixture paths are penalized; src/pkg
    layouts are preferred. File scan soft-cap defaults to 50k (not 800).
    """
    root = Path(work_dir)
    files_by_root = {
        rr.path: _walk_files(root / rr.path, max_files=max_files) for rr in repo_roots
    }
    results: list[DefectCodeMatch] = []
    for t in tickets:
        toks = _tokens(t)
        scored: list[tuple[int, str, MatchCandidate]] = []
        if toks:
            for rr in repo_roots:
                for f in files_by_root.get(rr.path, []):
                    hit = _score_file(f, toks)
                    if hit is None:
                        continue
                    strength, why = hit
                    scored.append(
                        (
                            strength,
                            f,
                            MatchCandidate(
                                repoPath=rr.path,
                                path=f,
                                why=f"{why} from title/titleTag/testModule/intent",
                                source="grep",
                            ),
                        )
                    )
        scored.sort(key=lambda x: (-x[0], x[1]))
        # Dedupe by path while taking top scores.
        seen_paths: set[str] = set()
        candidates: list[MatchCandidate] = []
        for _strength, path, cand in scored:
            key = f"{cand.repoPath}:{path}"
            if key in seen_paths:
                continue
            seen_paths.add(key)
            candidates.append(cand)
            if len(candidates) >= MAX_CANDIDATES:
                break
        confidence = _score_confidence(candidates, code_graph=code_graph, ticket=t)
        results.append(
            DefectCodeMatch(
                defectId=t.defectId,
                clusterId=t.clusterId,
                title=t.title,
                candidates=candidates,
                confidence=confidence,
            )
        )
    return results


def filter_existing_candidates(
    work_dir: str | Path,
    matches: list[DefectCodeMatch],
    *,
    code_graph: bool = False,
) -> list[DefectCodeMatch]:
    """Drop candidates whose files do not exist; re-score confidence."""
    root = Path(work_dir)
    out: list[DefectCodeMatch] = []
    for m in matches:
        kept: list[MatchCandidate] = []
        for c in m.candidates[:MAX_CANDIDATES]:
            rel = Path(c.path)
            abs_path = root / c.repoPath / rel if c.repoPath not in (".", "") else root / rel
            try:
                if abs_path.resolve().is_file():
                    kept.append(c)
            except OSError:
                continue
        ticket_stub = BatchTicket(
            defectId=m.defectId,
            title=m.title or "",
            pool="strict",
            expectQuality="explicit",
            clusterId=m.clusterId,
        )
        conf = _score_confidence(kept, code_graph=code_graph, ticket=ticket_stub)
        out.append(m.model_copy(update={"candidates": kept, "confidence": conf}))
    return out


def _score_confidence(
    candidates: list[MatchCandidate],
    *,
    code_graph: bool,
    ticket: BatchTicket,
) -> Literal["high", "medium", "low"]:
    """Confidence from match strength (no CodeGraph capability ceiling).

    - no candidates → low
    - codegraph hit, or ≥2 path hits → high
    - single path/grep hit → medium
    - missing suggested ticket fields (A1) → at most medium
    """
    if not candidates:
        return "low"

    sources = {c.source for c in candidates}
    has_codegraph = "codegraph" in sources
    if has_codegraph or len(candidates) >= 2:
        conf: Literal["high", "medium", "low"] = "high"
    else:
        conf = "medium"

    # A1: clusterId/testModule/titleTag/intent recommended; missing → ≤ medium.
    rich = bool(ticket.testModule and ticket.titleTag and ticket.intent)
    if not rich and conf == "high":
        conf = "medium"

    # code_graph flag reserved for future boosts; intentionally not a high-cap.
    _ = code_graph
    return conf
