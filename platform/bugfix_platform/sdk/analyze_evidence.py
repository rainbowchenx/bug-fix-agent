"""Select the ticket-specific Agent-2 evidence shown to Agent-3."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bugfix_contracts.code_knowledge import InvestigationFact
from bugfix_platform.sdk.match_payload import verify_code_reference

_LIMIT = 3
_VERIFIED = "reference_verified"


def select_investigation(
    work_dir: str, investigation: dict[str, Any], routed: dict[str, Any],
) -> dict[str, Any]:
    candidates = investigation.get("candidates") or (routed.get("localization") or {}).get("candidates") or []
    facts = [item for item in investigation.get("facts", []) if isinstance(item, dict) and item.get("claim")]
    root = Path(work_dir).resolve()
    verified = []
    checked_count = 0
    for item in facts:
        reference = item.get("reference") or {}
        if item.get("validity") != _VERIFIED or not isinstance(reference, dict) or not reference.get("contentDigest"):
            continue
        try:
            fact = InvestigationFact.model_validate(item)
        except ValidationError:
            continue
        if fact.reference is None or len(fact.reference.contentDigest or "") != 64:
            continue
        checked = verify_code_reference(root, fact.reference)
        checked_count += 1
        if checked is not None:
            verified.append(fact.model_copy(update={"reference": checked}))
        if checked_count == _LIMIT:
            break

    def candidate_rank(item: dict[str, Any]) -> tuple[bool, bool, bool]:
        repo = item.get("repoPath", ".")
        path = item.get("path")
        matching = any(fact.reference.repoId == repo and fact.reference.path == path for fact in verified)
        return (not matching, item.get("source") in {None, "heuristic"}, not item.get("symbol"))

    ranked = sorted((item for item in candidates if isinstance(item, dict) and item.get("path")), key=candidate_rank)
    packet: dict[str, Any] = {
        key: investigation[key] for key in ("investigationStatus", "confidence", "gap") if investigation.get(key)
    }
    if ranked:
        keys = ("repoPath", "path", "symbol", "source", "why")
        packet["candidates"] = [
            {key: str(item[key])[:400 if key == "why" else 1024] for key in keys if item.get(key)}
            for item in ranked[:_LIMIT]
        ]
    if verified:
        packet["verifiedReferences"] = [
            {
                "claim": fact.claim[:400],
                "repoPath": fact.reference.repoId,
                "path": fact.reference.path,
                "snippet": "\n".join((fact.reference.snippet or "").splitlines()[:8])[:1000],
            }
            for fact in verified
        ]
    claims = {fact.claim for fact in verified}
    hypotheses = [item["claim"] for item in facts if item["claim"] not in claims and item.get("validity") != "rejected"]
    if hypotheses:
        packet["unverifiedClaims"] = [str(claim)[:400] for claim in hypotheses[:_LIMIT]]
    for key in ("ruledOut", "nextChecks", "openQuestions", "hypotheses"):
        if values := investigation.get(key):
            packet[key] = [str(value)[:400] for value in values[:_LIMIT]]
    return packet
