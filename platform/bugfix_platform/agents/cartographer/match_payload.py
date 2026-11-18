"""Normalize and verify Agent2 handoff evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from bugfix_contracts.code_knowledge import (
    ArchModule,
    Architecture,
    CodeReference,
    DefectCodeMatch,
    InvestigationFact,
    MatchCandidate,
    MatchParseResult,
    ParseIssue,
    TechStack,
)
from bugfix_contracts.common import Confidence

from bugfix_platform.sdk.match_payload import normalize_observed_path

_ALLOWED_SOURCE = {"codegraph", "grep", "heuristic", "claude_md", "model_reported"}
_ALLOWED_CONF: set[str] = {"high", "medium", "low"}
_ALLOWED_GAPS = {"no_path_token_overlap"}


@dataclass
class GroupParseResult:
    accepted: list[DefectCodeMatch] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    shared: dict[str, Any] = field(default_factory=dict)
    envelope_ref: str = ""


def normalize_group_matches(
    parsed: dict[str, Any],
    *,
    requested_ids: set[str],
    raw_ref: str = "envelope",
) -> GroupParseResult:
    out = GroupParseResult(envelope_ref=raw_ref)
    items = parsed.get("defectCodeMatches")
    if items is not None and not isinstance(items, list):
        out.issues.append(
            ParseIssue(fieldPath="defectCodeMatches", reason="not_a_list", action="reject", rawRef=raw_ref)
        )
        return out
    seen: dict[str, list[int]] = {}
    for index, item in enumerate(items or []):
        path = f"{raw_ref}.defectCodeMatches[{index}]"
        if not isinstance(item, dict):
            out.issues.append(ParseIssue(fieldPath=path, reason="not_an_object", action="isolate", rawRef=path))
            continue
        defect_id = item.get("defectId")
        if not defect_id:
            out.issues.append(ParseIssue(fieldPath=path, reason="missing_defect_id", action="isolate", rawRef=path))
            continue
        defect_id = str(defect_id)
        if defect_id not in requested_ids:
            out.issues.append(ParseIssue(fieldPath=path, reason="outside_group", action="isolate", rawRef=path))
            continue
        seen.setdefault(defect_id, []).append(index)
    duplicates = {did for did, idxs in seen.items() if len(idxs) > 1}
    for did in duplicates:
        out.issues.append(
            ParseIssue(fieldPath=f"{raw_ref}.{did}", reason="duplicate_ticket", action="isolate", rawRef=raw_ref)
        )
    for index, item in enumerate(items or []):
        if not isinstance(item, dict) or not item.get("defectId"):
            continue
        did = str(item["defectId"])
        if did not in requested_ids or did in duplicates:
            continue
        try:
            result = normalize_sdk_match(item, requested_ids=requested_ids, raw_ref=f"{raw_ref}[{did}]")
        except Exception as err:  # noqa: BLE001
            out.issues.append(
                ParseIssue(
                    fieldPath=f"{raw_ref}[{did}]",
                    reason=f"isolate_exception:{type(err).__name__}",
                    action="isolate",
                    rawRef=f"{raw_ref}[{did}]",
                )
            )
            continue
        out.issues.extend(result.issues)
        if result.accepted is not None:
            out.accepted.append(result.accepted)
    out.shared = _normalize_shared(parsed, out.issues, raw_ref)
    return out


def _normalize_shared(parsed: dict[str, Any], issues: list[ParseIssue], raw_ref: str) -> dict[str, Any]:
    shared: dict[str, Any] = {}
    for key in ("secondaryHints", "boundSkills", "partial"):
        if key in parsed:
            shared[key] = parsed[key]
    tech = parsed.get("techStack")
    if isinstance(tech, dict):
        try:
            shared["techStack"] = TechStack.model_validate(tech).model_dump()
        except Exception:  # noqa: BLE001
            issues.append(ParseIssue(fieldPath=f"{raw_ref}.techStack", reason="bad_type", action="isolate", rawRef=raw_ref))
    elif tech is not None:
        issues.append(ParseIssue(fieldPath=f"{raw_ref}.techStack", reason="bad_type", action="isolate", rawRef=raw_ref))
    arch = parsed.get("architecture")
    if isinstance(arch, dict):
        modules = arch.get("modules")
        clean = {k: v for k, v in arch.items() if k != "modules"}
        if modules is not None and not isinstance(modules, list):
            issues.append(
                ParseIssue(fieldPath=f"{raw_ref}.architecture.modules", reason="bad_type", action="isolate", rawRef=raw_ref)
            )
        elif isinstance(modules, list):
            kept = []
            for i, mod in enumerate(modules):
                try:
                    kept.append(ArchModule.model_validate(mod).model_dump())
                except Exception:  # noqa: BLE001
                    issues.append(
                        ParseIssue(
                            fieldPath=f"{raw_ref}.architecture.modules[{i}]",
                            reason="bad_module",
                            action="isolate",
                            rawRef=raw_ref,
                        )
                    )
            clean["modules"] = kept
        try:
            shared["architecture"] = Architecture.model_validate(clean).model_dump()
        except Exception:  # noqa: BLE001
            issues.append(ParseIssue(fieldPath=f"{raw_ref}.architecture", reason="bad_type", action="isolate", rawRef=raw_ref))
            if "modules" in clean:
                shared["architecture"] = {"summary": str(clean.get("summary") or ""), "entryPoints": [], "modules": clean.get("modules") or []}
    elif arch is not None:
        issues.append(ParseIssue(fieldPath=f"{raw_ref}.architecture", reason="bad_type", action="isolate", rawRef=raw_ref))
    conv = parsed.get("conventions")
    if isinstance(conv, dict):
        shared["conventions"] = conv
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

    facts, fact_issues, fact_rejected = _normalize_facts(item.get("facts"), f"{raw_ref}.facts")
    issues.extend(fact_issues)
    rejected_fields.extend(fact_rejected)
    if facts:
        accepted_fields.append("facts")

    candidates, cand_issues, cand_rejected = _normalize_candidates(
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
            ParseIssue(fieldPath=f"{raw_ref}.confidence", reason="illegal_confidence", action="coerce", rawRef=raw_ref)
        )
        rejected_fields.append("confidence")

    gap = item.get("gap")
    if gap is not None and not (isinstance(gap, str) and gap in _ALLOWED_GAPS):
        issues.append(ParseIssue(fieldPath=f"{raw_ref}.gap", reason="gap_coerced", action="drop", rawRef=raw_ref))
        gap = None
        rejected_fields.append("gap")

    scopes = item.get("searchedScopes")
    searched = [str(s) for s in scopes if str(s).strip()] if isinstance(scopes, list) else []
    title = item.get("title") if isinstance(item.get("title"), str) else None
    if item.get("title") is not None and title is None:
        issues.append(ParseIssue(fieldPath=f"{raw_ref}.title", reason="bad_type", action="drop", rawRef=raw_ref))
        rejected_fields.append("title")
    cluster_id = item.get("clusterId") if isinstance(item.get("clusterId"), str) else None

    payload = {
        "defectId": str(defect_id),
        "clusterId": cluster_id,
        "title": title,
        "candidates": [c.model_dump() for c in candidates],
        "confidence": confidence,
        "gap": gap,
        "searchedScopes": searched,
        "facts": [f.model_dump() for f in facts],
        "hypotheses": _string_list(item.get("hypotheses")),
        "ruledOut": _string_list(item.get("ruledOut")),
        "openQuestions": _string_list(item.get("openQuestions")),
        "nextChecks": _string_list(item.get("nextChecks")),
        "investigationSource": "model_reported",
        "acceptanceStatus": "accepted",
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
    )


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, str) and x.strip()]


def _normalize_facts(
    raw: Any, field_path: str
) -> tuple[list[InvestigationFact], list[ParseIssue], list[str]]:
    if raw is None:
        return [], [], []
    if not isinstance(raw, list):
        return [], [ParseIssue(fieldPath=field_path, reason="bad_type", action="isolate", rawRef=field_path)], [field_path]
    out: list[InvestigationFact] = []
    issues: list[ParseIssue] = []
    rejected: list[str] = []
    for i, item in enumerate(raw):
        path = f"{field_path}[{i}]"
        if isinstance(item, str) and item.strip():
            out.append(InvestigationFact(claim=item.strip(), source="model_reported", validity="unverified"))
            issues.append(ParseIssue(fieldPath=path, reason="facts_coerced", action="coerce", rawRef=path))
            continue
        if isinstance(item, dict) and isinstance(item.get("claim"), str) and item["claim"].strip():
            reference = None
            raw_ref_obj = item.get("reference")
            if isinstance(raw_ref_obj, dict):
                try:
                    reference = CodeReference.model_validate(
                        {
                            "repoId": raw_ref_obj.get("repoId") or ".",
                            "path": raw_ref_obj.get("path"),
                            "revision": raw_ref_obj.get("revision"),
                            "contentDigest": raw_ref_obj.get("contentDigest"),
                            "snippet": raw_ref_obj.get("snippet") if isinstance(raw_ref_obj.get("snippet"), str) else None,
                            "startLine": raw_ref_obj.get("startLine") if isinstance(raw_ref_obj.get("startLine"), int) else None,
                            "endLine": raw_ref_obj.get("endLine") if isinstance(raw_ref_obj.get("endLine"), int) else None,
                        }
                    )
                except Exception:  # noqa: BLE001
                    issues.append(ParseIssue(fieldPath=f"{path}.reference", reason="bad_reference", action="drop", rawRef=path))
                    rejected.append(f"{path}.reference")
            out.append(
                InvestigationFact(
                    claim=item["claim"].strip(),
                    source="model_reported",
                    validity="unverified",
                    reference=reference,
                )
            )
            continue
        issues.append(ParseIssue(fieldPath=path, reason="bad_fact_element", action="isolate", rawRef=path))
        rejected.append(path)
    return out, issues, rejected


def _normalize_candidates(
    raw: Any,
    field_path: str,
    existing_paths: Optional[set[str]],
) -> tuple[list[MatchCandidate], list[ParseIssue], list[str]]:
    if raw is None:
        return [], [], []
    if not isinstance(raw, list):
        return [], [ParseIssue(fieldPath=field_path, reason="bad_type", action="isolate", rawRef=field_path)], [field_path]
    out: list[MatchCandidate] = []
    issues: list[ParseIssue] = []
    rejected: list[str] = []
    for i, item in enumerate(raw):
        path = f"{field_path}[{i}]"
        if not isinstance(item, dict):
            issues.append(ParseIssue(fieldPath=path, reason="not_an_object", action="isolate", rawRef=path))
            rejected.append(path)
            continue
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
        elif not isinstance(raw_source, str) or raw_source not in _ALLOWED_SOURCE:
            issues.append(ParseIssue(fieldPath=path, reason="illegal_source", action="isolate", rawRef=path))
            rejected.append(path)
            continue
        else:
            source = raw_source
        symbol = item.get("symbol") if isinstance(item.get("symbol"), str) else None
        if item.get("symbol") is not None and symbol is None:
            issues.append(ParseIssue(fieldPath=f"{path}.symbol", reason="bad_type", action="drop", rawRef=path))
        try:
            out.append(
                MatchCandidate(
                    repoPath=str(item.get("repoPath") or "."),
                    path=file_path,
                    symbol=symbol,
                    why=str(item.get("why") or "") if item.get("why") is None or isinstance(item.get("why"), str) else "",
                    source=source,  # type: ignore[arg-type]
                )
            )
        except Exception:  # noqa: BLE001
            issues.append(ParseIssue(fieldPath=path, reason="bad_candidate", action="isolate", rawRef=path))
            rejected.append(path)
    return out, issues, rejected


def verify_fact_references(
    work_dir: str,
    matches: list[DefectCodeMatch],
    observed_paths: list[str] | None = None,
    repo_roots: list[Any] | None = None,
) -> list[DefectCodeMatch]:
    """保留引用；仅当仓内当前版本片段命中时由程序升级 reference_verified。"""
    root = Path(work_dir).resolve()
    observed = {normalize_observed_path(p) for p in (observed_paths or []) if str(p).strip()}
    heads = _repo_heads(root, repo_roots)
    out: list[DefectCodeMatch] = []
    for match in matches:
        facts: list[InvestigationFact] = []
        for fact in match.facts or []:
            ref = fact.reference
            validity = "unverified"
            if ref is not None and ref.snippet and ref.path:
                path = _safe_repo_file(root, ref.repoId, ref.path)
                if path is not None:
                    try:
                        body = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        body = ""
                    if body and ref.snippet in body and _version_matches(path, ref, heads, root=root):
                        validity = "reference_verified"
            facts.append(fact.model_copy(update={"validity": validity, "source": "model_reported"}))
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


def _safe_repo_file(root: Path, repo_id: str, rel: str) -> Path | None:
    base = root if repo_id in {".", ""} else (root / str(repo_id)).resolve()
    if repo_id not in {".", ""}:
        try:
            base.relative_to(root)
        except ValueError:
            return None
    try:
        candidate = (base / rel).resolve()
        candidate.relative_to(base)
    except (OSError, ValueError):
        return None
    if not candidate.is_file():
        return None
    return candidate


def _version_matches(
    path: Path,
    ref: CodeReference,
    heads: dict[str, str],
    *,
    root: Path,
) -> bool:
    if ref.revision:
        repo_key = "." if ref.repoId in {".", ""} else normalize_observed_path(ref.repoId)
        expected = heads.get(repo_key)
        if expected is None:
            repo_base = root if repo_key == "." else (root / repo_key)
            expected = _git_head(repo_base)
        if expected is None or ref.revision != expected:
            return False
    if ref.contentDigest:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        declared = str(ref.contentDigest)
        if declared not in {digest, digest[: len(declared)]}:
            return False
    return True


def _repo_heads(root: Path, repo_roots: list[Any] | None) -> dict[str, str]:
    heads: dict[str, str] = {}
    root_head = _git_head(root)
    if root_head:
        heads["."] = root_head
    for item in repo_roots or []:
        path = getattr(item, "path", None) or (item.get("path") if isinstance(item, dict) else None)
        git_head = getattr(item, "gitHead", None) or (item.get("gitHead") if isinstance(item, dict) else None)
        if path and git_head:
            heads[normalize_observed_path(str(path)) or "."] = str(git_head)
        elif path:
            repo_path = root / str(path)
            discovered = _git_head(repo_path)
            if discovered:
                heads[normalize_observed_path(str(path)) or "."] = discovered
    return heads


def _git_head(start: Path) -> str | None:
    cur = start
    for _ in range(8):
        git = cur / ".git" / "HEAD"
        if git.is_file():
            text = git.read_text(encoding="utf-8").strip()
            if text.startswith("ref:"):
                ref = cur / ".git" / text.split(":", 1)[1].strip()
                if ref.is_file():
                    return ref.read_text(encoding="utf-8").strip()[:40]
                return text
            return text[:40]
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _candidate_rel(repo_id: str, path: str) -> str:
    rel = normalize_observed_path(path)
    repo = normalize_observed_path(repo_id)
    if repo in {"", "."}:
        return rel
    return f"{repo}/{rel}"
