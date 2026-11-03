from __future__ import annotations

import re
from pathlib import Path

from bugfix_agent.contracts.code_knowledge import DefectCodeMatch, MatchCandidate, RepoRoot
from bugfix_agent.contracts.defect_batch import BatchTicket

SKIP = {"node_modules", "dist", ".git", "coverage", ".bugfix-runs", ".venv", "__pycache__"}
SRC_EXT = re.compile(r"\.(ts|tsx|js|jsx|vue|py|go|java|kt|cs)$", re.I)


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
    raw = " ".join(x for x in [ticket.titleTag, ticket.testModule, ticket.intent] if x)
    parts = re.split(r"[\s/|_\-【】\[\]（）()]+", raw)
    toks = [
        s.strip().lower()
        for s in parts
        if len(s.strip()) >= 2 and not re.match(r"^(?:the|and|for|with|通用)$", s.strip(), re.I)
    ]
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 8:
            break
    return out


def match_tickets(
    work_dir: str | Path,
    repo_roots: list[RepoRoot],
    tickets: list[BatchTicket],
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
                                why=f'path contains token "{hit}" from titleTag/testModule/intent',
                                source="heuristic",
                            )
                        )
                        if len(candidates) >= 5:
                            break
                if len(candidates) >= 5:
                    break
        confidence = "medium" if len(candidates) >= 3 else "low"
        results.append(
            DefectCodeMatch(
                defectId=t.defectId,
                clusterId=t.clusterId,
                title=t.title,
                candidates=candidates,
                confidence=confidence,  # type: ignore[arg-type]
            )
        )
    return results
