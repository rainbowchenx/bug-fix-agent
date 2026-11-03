from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from bugfix_agent.contracts.defect_batch import ExpectQuality, Pool
from bugfix_agent.defect_batch.distill import DefectDigest
from bugfix_agent.defect_batch.expect_quality import classify_expect_quality
from bugfix_agent.defect_batch.rules import (
    SCANNER_RE,
    ScreenProfile,
    is_excluded_status,
    is_open_like,
    is_security_title,
    match_design_undefined,
    match_not_code,
    match_runtime_attach,
    match_sca_cve,
    match_vague,
)

Verdict = Literal["FIXABLE", "UNFIXABLE", "EXCLUDED", "SECURITY"]


@dataclass
class ScreenedTicket:
    digest: DefectDigest
    pool: Pool
    verdict: Verdict
    expectQuality: ExpectQuality
    ruleIds: list[str] = field(default_factory=list)
    reasonCode: Optional[str] = None
    reasonDetail: Optional[str] = None


def screen_digest(
    d: DefectDigest,
    *,
    posture: Literal["alpha", "beta"] = "beta",
    profile: Optional[ScreenProfile] = None,
) -> ScreenedTicket:
    profile = profile or ScreenProfile()
    expect_quality = classify_expect_quality(d)
    rule_ids: list[str] = []

    if is_excluded_status(d.status):
        return ScreenedTicket(d, "excluded", "EXCLUDED", expect_quality, rule_ids, "R1", "Cancel / Not a bug / void")

    # Code-review tickets often mention scanners/controls in diff text — do not bypass.
    if d.titleTag != "_code_review" and (
        is_security_title(d.title) or SCANNER_RE.search(d.fullText)
    ):
        return ScreenedTicket(d, "security", "SECURITY", expect_quality, rule_ids, "R1", "security / SCA bypass")

    if posture == "beta" and d.status and not is_open_like(d.status):
        return ScreenedTicket(
            d, "excluded", "EXCLUDED", expect_quality, rule_ids, "R1:beta", "beta posture skips non-Open/New"
        )

    sca = match_sca_cve(d, profile)
    if sca:
        rule_ids.append(sca.id)
        return ScreenedTicket(d, "hard_reject", "UNFIXABLE", expect_quality, rule_ids, sca.id, sca.detail)

    notcode = match_not_code(d, profile)
    if notcode:
        rule_ids.append(notcode.id)
        return ScreenedTicket(d, "hard_reject", "UNFIXABLE", expect_quality, rule_ids, notcode.id, notcode.detail)

    design = match_design_undefined(d)
    if design:
        rule_ids.append(design.id)
        return ScreenedTicket(d, "needs_info", "UNFIXABLE", expect_quality, rule_ids, design.id, design.detail)

    runtime = match_runtime_attach(d)
    if runtime:
        rule_ids.append(runtime.id)
        return ScreenedTicket(d, "needs_info", "UNFIXABLE", expect_quality, rule_ids, runtime.id, runtime.detail)

    vague = match_vague(d, profile)
    if vague:
        rule_ids.append(vague.id)
        return ScreenedTicket(d, "needs_info", "UNFIXABLE", expect_quality, rule_ids, vague.id, vague.detail)

    if expect_quality in ("explicit", "inferred"):
        return ScreenedTicket(d, "strict", "FIXABLE", expect_quality, rule_ids)
    return ScreenedTicket(
        d, "locatable_only", "FIXABLE", expect_quality, rule_ids, "R3b", "FIXABLE but expect not unique"
    )


def screen_all(
    digests: list[DefectDigest],
    *,
    posture: Literal["alpha", "beta"] = "beta",
    profile: Optional[ScreenProfile] = None,
) -> list[ScreenedTicket]:
    return [screen_digest(d, posture=posture, profile=profile) for d in digests]


def funnel_counts(tickets: list[ScreenedTicket]) -> dict[str, int]:
    out = {
        "total": len(tickets),
        "strict": 0,
        "locatable_only": 0,
        "needs_info": 0,
        "hard_reject": 0,
        "security": 0,
        "excluded": 0,
        "duplicate": 0,
    }
    for t in tickets:
        out[t.pool] = out.get(t.pool, 0) + 1
        if t.digest.duplicate:
            out["duplicate"] += 1
    return out
