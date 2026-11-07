from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from bugfix_agent.contracts import CodeKnowledge, validate_code_knowledge
from bugfix_agent.evals.agent2.gold import Agent2Gold, GoldTicket, parse_gold


@dataclass
class TicketScore:
    defectId: str
    expectEmpty: bool
    candidateCount: int
    candidates: list[str]
    hitAt1: Optional[bool]
    hitAt3: Optional[bool]
    pathRecall: Optional[float]
    negativeOk: Optional[bool]
    notes: str = ""


@dataclass
class EvalReport:
    passed: bool
    dataset: str
    generatedAt: str
    schemaValid: bool
    profile: Optional[str]
    profileHit: bool
    languageHit: Optional[bool]
    pathsExistRate: Optional[float]
    candidateCapOk: bool
    hitAt1: Optional[float]
    hitAt3: Optional[float]
    pathRecall: Optional[float]
    negativeAccuracy: Optional[float]
    gates: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    perTicket: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_gold(source: Union[str, Path, dict[str, Any], Agent2Gold]) -> Agent2Gold:
    if isinstance(source, Agent2Gold):
        return source
    if isinstance(source, dict):
        return parse_gold(source)
    path = Path(source)
    return parse_gold(json.loads(path.read_text(encoding="utf-8")))


def score_code_knowledge(
    *,
    work_dir: str | Path,
    knowledge: Union[CodeKnowledge, dict[str, Any], str, Path],
    gold: Union[Agent2Gold, dict[str, Any], str, Path],
) -> EvalReport:
    """Score an Agent-2 code-knowledge artifact against gold labels."""
    work = Path(work_dir)
    gold_model = load_gold(gold)

    schema_valid = True
    knowledge_model: Optional[CodeKnowledge] = None
    schema_error = ""
    try:
        if isinstance(knowledge, CodeKnowledge):
            knowledge_model = knowledge
        elif isinstance(knowledge, dict):
            knowledge_model = validate_code_knowledge(knowledge)
        else:
            knowledge_model = validate_code_knowledge(
                json.loads(Path(knowledge).read_text(encoding="utf-8"))
            )
    except Exception as err:  # noqa: BLE001
        schema_valid = False
        schema_error = str(err)

    gates_cfg = gold_model.gates
    failures: list[str] = []

    if gates_cfg.requireSchemaValid and not schema_valid:
        failures.append(f"G1 schemaValid failed: {schema_error}")

    profile = knowledge_model.cartographyProfile if knowledge_model else None
    profile_hit = bool(profile and profile in gold_model.expectedProfile)

    language_hit: Optional[bool] = None
    if knowledge_model and gold_model.expectedLanguagesAnyOf:
        langs = {x.lower() for x in knowledge_model.techStack.languages}
        want = {x.lower() for x in gold_model.expectedLanguagesAnyOf}
        language_hit = bool(langs & want)

    match_by_id = {
        m.defectId: m for m in (knowledge_model.defectCodeMatches if knowledge_model else [])
    }

    existing = 0
    total_c = 0
    cap_ok = True
    ticket_scores: list[TicketScore] = []

    for gt in gold_model.tickets:
        match = match_by_id.get(gt.defectId)
        cands = list(match.candidates) if match else []
        if len(cands) > gates_cfg.maxCandidates:
            cap_ok = False
        paths = [_cand_path(c.repoPath, c.path) for c in cands]
        for p in paths:
            total_c += 1
            if _exists(work, p):
                existing += 1

        if gt.expectEmpty:
            ticket_scores.append(
                TicketScore(
                    defectId=gt.defectId,
                    expectEmpty=True,
                    candidateCount=len(cands),
                    candidates=paths,
                    hitAt1=None,
                    hitAt3=None,
                    pathRecall=None,
                    negativeOk=len(cands) == 0,
                )
            )
            continue

        if not gt.goldPaths:
            ticket_scores.append(
                TicketScore(
                    defectId=gt.defectId,
                    expectEmpty=False,
                    candidateCount=len(cands),
                    candidates=paths,
                    hitAt1=None,
                    hitAt3=None,
                    pathRecall=None,
                    negativeOk=None,
                    notes="skipped: empty goldPaths without expectEmpty",
                )
            )
            continue

        hit1 = _hit_at_k(paths, gt, k=1)
        hit3 = _hit_at_k(paths, gt, k=3)
        recall = _path_recall(paths, gt)
        ticket_scores.append(
            TicketScore(
                defectId=gt.defectId,
                expectEmpty=False,
                candidateCount=len(cands),
                candidates=paths,
                hitAt1=hit1,
                hitAt3=hit3,
                pathRecall=recall,
                negativeOk=None,
            )
        )

    paths_exist_rate = (existing / total_c) if total_c else 1.0
    if gates_cfg.requirePathsExist and paths_exist_rate < 1.0:
        failures.append(f"G2 pathsExistRate={paths_exist_rate:.3f} < 1.0")
    if not cap_ok:
        failures.append(f"G3 candidateCapOk failed (max={gates_cfg.maxCandidates})")

    loc = [t for t in ticket_scores if t.hitAt1 is not None]
    neg = [t for t in ticket_scores if t.negativeOk is not None]
    hit_at_1 = (sum(1 for t in loc if t.hitAt1) / len(loc)) if loc else None
    hit_at_3 = (sum(1 for t in loc if t.hitAt3) / len(loc)) if loc else None
    path_recall = (
        sum(t.pathRecall or 0.0 for t in loc) / len(loc) if loc else None
    )
    negative_accuracy = (
        sum(1 for t in neg if t.negativeOk) / len(neg) if neg else None
    )

    if hit_at_1 is not None and hit_at_1 < gates_cfg.minHitAt1:
        failures.append(f"L1 hitAt1={hit_at_1:.3f} < {gates_cfg.minHitAt1}")
    if hit_at_3 is not None and hit_at_3 < gates_cfg.minHitAt3:
        failures.append(f"L2 hitAt3={hit_at_3:.3f} < {gates_cfg.minHitAt3}")
    if negative_accuracy is not None and negative_accuracy < gates_cfg.minNegativeAccuracy:
        failures.append(
            f"G4 negativeAccuracy={negative_accuracy:.3f} < {gates_cfg.minNegativeAccuracy}"
        )
    if gates_cfg.requireProfileHit and not profile_hit:
        failures.append(
            f"P1 profileHit failed: got {profile!r}, expected one of {gold_model.expectedProfile}"
        )

    passed = not failures
    report = EvalReport(
        passed=passed,
        dataset=gold_model.name,
        generatedAt=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        schemaValid=schema_valid,
        profile=profile,
        profileHit=profile_hit,
        languageHit=language_hit,
        pathsExistRate=paths_exist_rate,
        candidateCapOk=cap_ok,
        hitAt1=hit_at_1,
        hitAt3=hit_at_3,
        pathRecall=path_recall,
        negativeAccuracy=negative_accuracy,
        gates={
            "requireSchemaValid": gates_cfg.requireSchemaValid,
            "requirePathsExist": gates_cfg.requirePathsExist,
            "maxCandidates": gates_cfg.maxCandidates,
            "minHitAt1": gates_cfg.minHitAt1,
            "minHitAt3": gates_cfg.minHitAt3,
            "minNegativeAccuracy": gates_cfg.minNegativeAccuracy,
            "requireProfileHit": gates_cfg.requireProfileHit,
        },
        metrics={
            "labeledTickets": len(loc),
            "negativeTickets": len(neg),
            "candidateCount": total_c,
        },
        perTicket=[asdict(t) for t in ticket_scores],
        failures=failures,
    )
    return report


def _cand_path(repo_path: str, path: str) -> str:
    path = path.replace("\\", "/").lstrip("./")
    if repo_path in (".", ""):
        return path
    return f"{repo_path.rstrip('/')}/{path}"


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _path_match(candidate: str, gold: str) -> bool:
    c = _norm(candidate)
    g = _norm(gold)
    if c == g:
        return True
    if c.endswith("/" + g) or g.endswith("/" + c):
        return True
    # allow gold as path suffix without leading slash edge cases
    if c.endswith(g) and (len(c) == len(g) or c[: -len(g)].endswith("/")):
        return True
    # directory gold: candidate under that prefix
    if "." not in Path(g).name and (c.startswith(g.rstrip("/") + "/") or c == g):
        return True
    return False


def _hit_at_k(paths: list[str], gt: GoldTicket, *, k: int) -> bool:
    top = paths[:k]
    if gt.matchMode == "all":
        return all(any(_path_match(p, g) for p in top) for g in gt.goldPaths)
    return any(any(_path_match(p, g) for g in gt.goldPaths) for p in top)


def _path_recall(paths: list[str], gt: GoldTicket) -> float:
    if not gt.goldPaths:
        return 0.0
    hit = sum(1 for g in gt.goldPaths if any(_path_match(p, g) for p in paths))
    return hit / len(gt.goldPaths)


def _exists(work: Path, rel: str) -> bool:
    try:
        return (work / rel).resolve().is_file()
    except OSError:
        return False
