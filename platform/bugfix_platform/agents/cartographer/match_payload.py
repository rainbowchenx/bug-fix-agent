"""Normalize and verify Agent2 handoff evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from bugfix_contracts.code_knowledge import (
    ArchModule,
    CodeReference,
    DefectCodeMatch,
    InvestigationFact,
    MatchCandidate,
    MatchParseResult,
    ParseAction,
    ParseIssue,
)
from bugfix_contracts.common import Confidence

from bugfix_platform.sdk.match_payload import git_head, normalize_observed_path, verify_code_reference

_ALLOWED_SOURCE = {"codegraph", "grep", "heuristic", "claude_md", "model_reported"}
_ALLOWED_CONF: set[str] = {"high", "medium", "low"}
_ALLOWED_GAPS = {"no_path_token_overlap"}


@dataclass
class GroupParseResult:
    accepted: list[DefectCodeMatch] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    shared: dict[str, Any] = field(default_factory=dict)
    envelope_ref: str = ""
    field_refs: dict[str, dict[str, str]] = field(default_factory=dict)
    candidate_refs: dict[str, list[str]] = field(default_factory=dict)
    fact_refs: dict[str, list[str]] = field(default_factory=dict)


def _issue(issues: list[ParseIssue], path: str, reason: str, action: ParseAction = "isolate") -> None:
    issues.append(ParseIssue(fieldPath=path, reason=reason, action=action, rawRef=path))


def _unknown_fields(raw: dict, known: set[str], issues: list[ParseIssue], path: str) -> None:
    for key in sorted(raw.keys() - known):
        _issue(issues, f"{path}.{key}", "unknown_field", "record")


def normalize_group_matches(
    parsed: dict[str, Any],
    *,
    requested_ids: set[str],
    raw_ref: str = "envelope",
) -> GroupParseResult:
    out = GroupParseResult(envelope_ref=raw_ref)
    items = parsed.get("defectCodeMatches")
    if items is not None and not isinstance(items, list):
        _issue(out.issues, f"{raw_ref}.defectCodeMatches", "not_a_list", "reject")
        items = []
    seen: dict[str, list[int]] = {}
    for index, item in enumerate(items or []):
        path = f"{raw_ref}.defectCodeMatches[{index}]"
        if not isinstance(item, dict):
            out.issues.append(ParseIssue(fieldPath=path, reason="not_an_object", action="isolate", rawRef=path))
            continue
        defect_id = item.get("defectId")
        if not isinstance(defect_id, str) or not defect_id:
            _issue(out.issues, f"{path}.defectId", "missing_defect_id" if defect_id is None else "invalid_defect_id")
            continue
        if defect_id not in requested_ids:
            out.issues.append(ParseIssue(fieldPath=path, reason="outside_group", action="isolate", rawRef=path))
            continue
        seen.setdefault(defect_id, []).append(index)
    duplicates = {did for did, idxs in seen.items() if len(idxs) > 1}
    for did in sorted(duplicates):
        for index in seen[did]:
            _issue(out.issues, f"{raw_ref}.defectCodeMatches[{index}].defectId", "duplicate_ticket")
    for did in sorted(requested_ids - seen.keys()):
        out.issues.append(ParseIssue(fieldPath=f"defectCodeMatches[{did}]", reason="missing_ticket",
                                     action="record", rawRef=raw_ref))
    for index, item in enumerate(items or []):
        if not isinstance(item, dict) or not isinstance(item.get("defectId"), str):
            continue
        did = item["defectId"]
        if did not in requested_ids or did in duplicates:
            continue
        try:
            row_ref = f"{raw_ref}.defectCodeMatches[{index}]"
            result = normalize_sdk_match(item, requested_ids=requested_ids, raw_ref=row_ref)
        except Exception as err:  # noqa: BLE001
            out.issues.append(
                ParseIssue(
                    fieldPath=row_ref,
                    reason=f"isolate_exception:{type(err).__name__}",
                    action="isolate",
                    rawRef=row_ref,
                )
            )
            continue
        out.issues.extend(result.issues)
        if result.accepted is not None:
            out.accepted.append(result.accepted)
            out.field_refs[did] = {key: f"{row_ref}.{key}" for key in ["defectId", *result.acceptedFields]}
            out.candidate_refs[did] = result.candidateRefs
            out.fact_refs[did] = result.factRefs
    out.shared = _normalize_shared(parsed, out.issues, raw_ref)
    return out


def _normalize_shared(parsed: dict[str, Any], issues: list[ParseIssue], raw_ref: str) -> dict[str, Any]:
    shared: dict[str, Any] = {}
    list_fields = {"secondaryHints", "boundSkills"}
    sections = {"techStack": {"languages", "frameworks", "notes"},
                "architecture": {"entryPoints", "summary", "modules"}, "conventions": {"fromRules"}}
    _unknown_fields(parsed, list_fields | sections.keys() | {"partial", "defectCodeMatches"}, issues, raw_ref)
    for key in sorted(list_fields & parsed.keys()):
        shared[key] = _string_list(parsed[key], f"{raw_ref}.{key}", issues)
    if isinstance(parsed.get("partial"), bool):
        shared["partial"] = parsed["partial"]
    elif "partial" in parsed:
        _issue(issues, f"{raw_ref}.partial", "bad_type")
    for section, fields in sections.items():
        if section not in parsed:
            continue
        raw = parsed[section]
        path = f"{raw_ref}.{section}"
        if not isinstance(raw, dict):
            _issue(issues, path, "null_field" if raw is None else "bad_type")
            continue
        _unknown_fields(raw, fields, issues, path)
        clean = {}
        for key in sorted(fields & raw.keys()):
            value = raw[key]
            field_path = f"{path}.{key}"
            if key == "modules" and isinstance(value, list):
                clean[key] = []
                for index, module in enumerate(value):
                    item_path = f"{field_path}[{index}]"
                    try:
                        clean[key].append(ArchModule.model_validate(module).model_dump())
                    except ValueError:
                        _issue(issues, item_path, "bad_module")
                    if isinstance(module, dict):
                        _unknown_fields(module, set(ArchModule.model_fields), issues, item_path)
            elif key in {"notes", "summary", "modules"}:
                if key != "modules" and isinstance(value, str):
                    clean[key] = value
                else:
                    _issue(issues, field_path, "null_field" if value is None else "bad_type")
            else:
                clean[key] = _string_list(value, field_path, issues)
        shared[section] = clean
    return shared


def normalize_sdk_match(
    item: dict[str, Any],
    *,
    requested_ids: set[str],
    raw_ref: str,
    existing_paths: Optional[set[str]] = None,
) -> MatchParseResult:
    issues: list[ParseIssue] = []
    accepted_fields: list[str] = []
    rejected_fields: list[str] = []
    defect_id = item.get("defectId")
    if not defect_id or str(defect_id) not in requested_ids:
        issues.append(ParseIssue(fieldPath=f"{raw_ref}.defectId", reason="identity", action="reject", rawRef=raw_ref))
        return MatchParseResult(accepted=None, issues=issues, acceptedFields=[], rejectedFields=["defectId"])

    facts, fact_issues, fact_rejected, fact_refs = _normalize_facts(item.get("facts"), f"{raw_ref}.facts")
    issues.extend(fact_issues)
    rejected_fields.extend(fact_rejected)
    if facts:
        accepted_fields.append("facts")

    candidates, cand_issues, cand_rejected, candidate_refs = _normalize_candidates(
        item.get("candidates"), f"{raw_ref}.candidates", existing_paths
    )
    issues.extend(cand_issues)
    rejected_fields.extend(cand_rejected)
    if candidates:
        accepted_fields.append("candidates")

    confidence: Confidence = "low"
    raw_conf = item.get("confidence")
    if isinstance(raw_conf, str) and raw_conf in _ALLOWED_CONF:
        confidence = raw_conf  # type: ignore[assignment]
        accepted_fields.append("confidence")
    elif raw_conf is not None:
        confidence = "low"
        issues.append(
            ParseIssue(fieldPath=f"{raw_ref}.confidence", reason="illegal_confidence", action="coerce", rawRef=f"{raw_ref}.confidence")
        )
        rejected_fields.append("confidence")

    gap = item.get("gap")
    if gap is not None and not (isinstance(gap, str) and gap in _ALLOWED_GAPS):
        _issue(issues, f"{raw_ref}.gap", "gap_coerced", "drop")
        gap = None
        rejected_fields.append("gap")

    list_fields = ("searchedScopes", "hypotheses", "ruledOut", "openQuestions", "nextChecks")
    optional = ("facts", "candidates", "confidence", *list_fields)
    for key in optional:
        if item.get(key) is None:
            _issue(issues, f"{raw_ref}.{key}", "null_field" if key in item else "missing_field", "record")
    text_lists = {key: _string_list(item[key], f"{raw_ref}.{key}", issues)
                  for key in list_fields if item.get(key) is not None}
    accepted_fields.extend(key for key, values in text_lists.items() if values or item[key] == [])
    accepted_fields.extend(key for key in ("facts", "candidates") if item.get(key) == [])
    scalars = {}
    for key in ("title", "clusterId"):
        raw_scalar = item.get(key)
        if isinstance(raw_scalar, str):
            scalars[key] = raw_scalar
            accepted_fields.append(key)
        elif raw_scalar is not None:
            _issue(issues, f"{raw_ref}.{key}", "bad_type", "drop")
    if gap is not None:
        accepted_fields.append("gap")
    _unknown_fields(item, {"defectId", "title", "clusterId", "gap", *optional}, issues, raw_ref)

    payload = {
        "defectId": str(defect_id),
        **scalars,
        "candidates": [c.model_dump() for c in candidates],
        "confidence": confidence,
        "gap": gap,
        **text_lists,
        "facts": [f.model_dump() for f in facts],
        "investigationSource": "model_reported",
        "acceptanceStatus": "accepted" if any((facts, candidates, *text_lists.values())) else "rejected",
        "storageStatus": "saved",
        "observedScopes": [],
    }
    try:
        match = DefectCodeMatch.model_validate(payload)
    except Exception as err:  # noqa: BLE001
        issues.append(
            ParseIssue(
                fieldPath=raw_ref,
                reason=f"isolate_exception:{type(err).__name__}",
                action="isolate",
                rawRef=raw_ref,
            )
        )
        payload.pop("title", None)
        payload.pop("clusterId", None)
        try:
            match = DefectCodeMatch.model_validate(payload)
        except Exception:  # noqa: BLE001
            return MatchParseResult(accepted=None, issues=issues, acceptedFields=accepted_fields, rejectedFields=rejected_fields)
    return MatchParseResult(
        accepted=match,
        issues=issues,
        acceptedFields=accepted_fields,
        rejectedFields=rejected_fields,
        candidateRefs=candidate_refs,
        factRefs=fact_refs,
    )


def _string_list(raw: Any, path: str, issues: list[ParseIssue]) -> list[str]:
    if not isinstance(raw, list):
        _issue(issues, path, "null_field" if raw is None else "bad_type")
        return []
    out = []
    for index, value in enumerate(raw):
        if isinstance(value, str) and value.strip():
            out.append(value)
        else:
            _issue(issues, f"{path}[{index}]", "bad_string_element")
    return out


def _normalize_facts(
    raw: Any, field_path: str
) -> tuple[list[InvestigationFact], list[ParseIssue], list[str], list[str]]:
    if raw is None:
        return [], [], [], []
    if not isinstance(raw, list):
        return [], [ParseIssue(fieldPath=field_path, reason="bad_type", action="isolate", rawRef=field_path)], [field_path], []
    out: list[InvestigationFact] = []
    issues: list[ParseIssue] = []
    rejected: list[str] = []
    refs: list[str] = []
    for i, item in enumerate(raw):
        path = f"{field_path}[{i}]"
        if isinstance(item, str) and item.strip():
            out.append(InvestigationFact(claim=item.strip(), source="model_reported", validity="unverified"))
            issues.append(ParseIssue(fieldPath=path, reason="facts_coerced", action="coerce", rawRef=path))
            refs.append(path)
            continue
        if isinstance(item, dict) and isinstance(item.get("claim"), str) and item["claim"].strip():
            reference = None
            invalid_binding = False
            raw_ref_obj = item.get("reference")
            _unknown_fields(item, set(InvestigationFact.model_fields), issues, path)
            for key, default in (("source", "model_reported"), ("validity", "unverified")):
                if key in item and item[key] != default:
                    _issue(issues, f"{path}.{key}", "program_owned_field", "coerce")
            if raw_ref_obj is not None and not isinstance(raw_ref_obj, dict):
                _issue(issues, f"{path}.reference", "bad_reference", "drop")
            if isinstance(raw_ref_obj, dict):
                ref_path = f"{path}.reference"
                ref_fields = set(CodeReference.model_fields)
                _unknown_fields(raw_ref_obj, ref_fields, issues, ref_path)
                ref_payload: dict[str, Any] = {"repoId": "."}
                for key in sorted(ref_fields & raw_ref_obj.keys()):
                    value = raw_ref_obj[key]
                    if value is None:
                        continue
                    expected = int if key in {"startLine", "endLine"} else str
                    if type(value) is not expected:
                        _issue(issues, f"{ref_path}.{key}", "bad_type", "drop")
                        invalid_binding |= key in {"repoId", "revision", "contentDigest"}
                    else:
                        ref_payload[key] = value
                try:
                    reference = CodeReference.model_validate(ref_payload)
                except ValueError:
                    _issue(issues, ref_path, "bad_reference", "drop")
                    rejected.append(ref_path)
            out.append(
                InvestigationFact(
                    claim=item["claim"].strip(),
                    source="model_reported",
                    validity="rejected" if invalid_binding else "unverified",
                    reference=reference,
                )
            )
            refs.append(path)
            continue
        issues.append(ParseIssue(fieldPath=path, reason="bad_fact_element", action="isolate", rawRef=path))
        rejected.append(path)
    return out, issues, rejected, refs


def _normalize_candidates(
    raw: Any,
    field_path: str,
    existing_paths: Optional[set[str]],
) -> tuple[list[MatchCandidate], list[ParseIssue], list[str], list[str]]:
    if raw is None:
        return [], [], [], []
    if not isinstance(raw, list):
        return [], [ParseIssue(fieldPath=field_path, reason="bad_type", action="isolate", rawRef=field_path)], [field_path], []
    out: list[MatchCandidate] = []
    issues: list[ParseIssue] = []
    rejected: list[str] = []
    refs: list[str] = []
    for i, item in enumerate(raw):
        path = f"{field_path}[{i}]"
        if not isinstance(item, dict):
            issues.append(ParseIssue(fieldPath=path, reason="not_an_object", action="isolate", rawRef=path))
            rejected.append(path)
            continue
        _unknown_fields(item, set(MatchCandidate.model_fields), issues, path)
        file_path = item.get("path")
        if not isinstance(file_path, str) or not file_path.strip():
            issues.append(ParseIssue(fieldPath=path, reason="missing_path", action="isolate", rawRef=path))
            rejected.append(path)
            continue
        if existing_paths is not None and file_path not in existing_paths:
            issues.append(ParseIssue(fieldPath=path, reason="path_not_found", action="isolate", rawRef=path))
            rejected.append(path)
            continue
        raw_source = item.get("source")
        if raw_source in (None, ""):
            source = "model_reported"
            _issue(issues, f"{path}.source", "default_source", "record")
        elif not isinstance(raw_source, str) or raw_source not in _ALLOWED_SOURCE:
            issues.append(ParseIssue(fieldPath=path, reason="illegal_source", action="isolate", rawRef=f"{path}.source"))
            rejected.append(path)
            continue
        else:
            source = raw_source
        symbol = item.get("symbol") if isinstance(item.get("symbol"), str) else None
        if item.get("symbol") is not None and symbol is None:
            issues.append(ParseIssue(fieldPath=f"{path}.symbol", reason="bad_type", action="drop", rawRef=path))
        repo_path = item.get("repoPath")
        if repo_path is not None and not isinstance(repo_path, str):
            _issue(issues, f"{path}.repoPath", "bad_type")
            rejected.append(path)
            continue
        why = item.get("why")
        if why is not None and not isinstance(why, str):
            _issue(issues, f"{path}.why", "bad_type", "drop")
        try:
            out.append(
                MatchCandidate(
                    repoPath=repo_path or ".",
                    path=file_path,
                    symbol=symbol,
                    why=why if isinstance(why, str) else "",
                    source=source,  # type: ignore[arg-type]
                )
            )
            refs.append(path)
        except Exception:  # noqa: BLE001
            issues.append(ParseIssue(fieldPath=path, reason="bad_candidate", action="isolate", rawRef=path))
            rejected.append(path)
    return out, issues, rejected, refs


def verify_fact_references(
    work_dir: str,
    matches: list[DefectCodeMatch],
    observed_paths: list[str] | None = None,
    repo_roots: list[Any] | None = None,
    on_unverified: Callable[[str, int], None] | None = None,
) -> list[DefectCodeMatch]:
    """保留引用；仅当仓内当前版本片段命中时由程序升级 reference_verified。"""
    root = Path(work_dir).resolve()
    observed = {normalize_observed_path(p) for p in (observed_paths or []) if str(p).strip()}
    heads = _repo_heads(root, repo_roots)
    out: list[DefectCodeMatch] = []
    for match in matches:
        facts: list[InvestigationFact] = []
        for index, fact in enumerate(match.facts):
            ref = fact.reference
            validity = "rejected" if fact.validity == "rejected" else "unverified"
            if validity != "rejected" and ref is not None:
                checked = verify_code_reference(root, ref, heads=heads)
                if checked is not None:
                    validity = "reference_verified"
                    ref = checked
            if ref is not None and validity == "unverified" and on_unverified is not None:
                on_unverified(match.defectId, index)
            facts.append(fact.model_copy(update={"validity": validity, "reference": ref, "source": "model_reported"}))
        scopes = []
        for cand in match.candidates or []:
            rel = _candidate_rel(cand.repoPath if hasattr(cand, "repoPath") else ".", cand.path)
            if rel in observed:
                scopes.append(cand.path)
        for fact in facts:
            if fact.reference and fact.reference.path:
                rel = _candidate_rel(fact.reference.repoId, fact.reference.path)
                if rel in observed:
                    scopes.append(fact.reference.path)
        out.append(match.model_copy(update={"facts": facts, "observedScopes": list(dict.fromkeys(scopes))}))
    return out


def _repo_heads(root: Path, repo_roots: list[Any] | None) -> dict[str, str]:
    heads: dict[str, str] = {}
    root_head = git_head(root)
    if root_head:
        heads["."] = root_head
    for item in repo_roots or []:
        path = getattr(item, "path", None) or (item.get("path") if isinstance(item, dict) else None)
        declared_head = getattr(item, "gitHead", None) or (item.get("gitHead") if isinstance(item, dict) else None)
        if path and declared_head:
            heads[normalize_observed_path(str(path)) or "."] = str(declared_head)
        elif path:
            repo_path = root / str(path)
            discovered = git_head(repo_path)
            if discovered:
                heads[normalize_observed_path(str(path)) or "."] = discovered
    return heads


def _candidate_rel(repo_id: str, path: str) -> str:
    rel = normalize_observed_path(path)
    repo = normalize_observed_path(repo_id)
    if repo in {"", "."}:
        return rel
    return f"{repo}/{rel}"
