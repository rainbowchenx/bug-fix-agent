from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from bugfix_agent.contracts.code_knowledge import DefectCodeMatch, MatchCandidate, RepoRoot
from bugfix_agent.contracts.defect_batch import BatchTicket

SKIP = {"node_modules", "dist", ".git", "coverage", ".bugfix-runs", ".venv", "__pycache__"}
SRC_EXT = re.compile(r"\.(ts|tsx|js|jsx|vue|py|go|java|kt|cs)$", re.I)
MAX_CANDIDATES = 3  # A3


def _walk_files(root: Path, max_files: int = 800) -> list[str]:
    out: list[str] = []

    def walk(dir_path: Path, rel_base: str) -> None:
        if len(out) >= max_files:
            return
        try:
            entries = list(dir_path.iterdir())
        except OSError:
            return
        for p in entries:
            if p.name in SKIP or p.name.startswith("."):
                continue
            rel = f"{rel_base}/{p.name}" if rel_base else p.name
            rel = rel.replace("\\", "/")
            if p.is_dir():
                walk(p, rel)
            elif SRC_EXT.search(p.name):
                out.append(rel)

    walk(root, "")
    return out


def _tokens(ticket: BatchTicket) -> list[str]:
    """Query tokens: title + titleTag / testModule / intent（不灌蒸馏全文，见 C8）。"""
    title = ticket.title or ""
    title = re.sub(r"【[^】]+】|\[[^\]]+\]", " ", title)
    raw = " ".join(
        x for x in [title, ticket.titleTag, ticket.testModule, ticket.intent] if x
    )
    parts = re.split(r"[\s/|_\-【】\[\]（）():：,.]+", raw)
    toks = [
        s.strip().lower()
        for s in parts
        if len(s.strip()) >= 2
        and not re.match(
            r"^(?:the|and|for|with|from|this|that|通用|问题描述|缺陷)$",
            s.strip(),
            re.I,
        )
    ]
    # Chinese bigrams from leftover continuous CJK in title (cheap signal).
    for m in re.finditer(r"[\u4e00-\u9fff]{2,8}", title):
        toks.append(m.group(0).lower())

    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 12:
            break
    return out


def match_tickets(
    work_dir: str | Path,
    repo_roots: list[RepoRoot],
    tickets: list[BatchTicket],
    *,
    code_graph: bool = False,
) -> list[DefectCodeMatch]:
    root = Path(work_dir)
    files_by_root = {rr.path: _walk_files(root / rr.path) for rr in repo_roots}
    results: list[DefectCodeMatch] = []
    for t in tickets:
        toks = _tokens(t)
        candidates: list[MatchCandidate] = []
        if toks:
            for rr in repo_roots:
                for f in files_by_root.get(rr.path, []):
                    fl = f.lower()
                    hit = next((tok for tok in toks if tok in fl), None)
                    if hit:
                        candidates.append(
                            MatchCandidate(
                                repoPath=rr.path,
                                path=f,
                                why=f'path contains token "{hit}" from title/titleTag/testModule/intent',
                                source="grep",
                            )
                        )
                        if len(candidates) >= MAX_CANDIDATES:
                            break
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
    """Drop candidates whose files do not exist; re-apply A4 confidence caps."""
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
    """A4 + A1 field-quality caps.

    - no candidates → low
    - codegraph hit + path kept → may be high
    - grep/heuristic only → at most medium
    - codeGraph capability false → all capped at medium
    - missing suggested ticket fields (A1) → at most medium
    """
    if not candidates:
        return "low"

    sources = {c.source for c in candidates}
    has_codegraph = "codegraph" in sources and code_graph
    if has_codegraph:
        conf: Literal["high", "medium", "low"] = "high"
    elif len(candidates) >= 2:
        conf = "medium"
    else:
        conf = "low"

    # Path/grep/heuristic alone never high (A4).
    if not has_codegraph and conf == "high":
        conf = "medium"
    if not code_graph and conf == "high":
        conf = "medium"

    # A1: clusterId/testModule/titleTag/intent recommended; missing → ≤ medium.
    rich = bool(ticket.testModule and ticket.titleTag and ticket.intent)
    if not rich and conf == "high":
        conf = "medium"

    return conf
