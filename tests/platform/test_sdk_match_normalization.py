"""T2：字段/候选/身份隔离。局部坏输入不得拖走合法调查。"""

from __future__ import annotations

import json

import pytest

from bugfix_contracts.code_knowledge import InvestigationFact
from bugfix_platform.sdk.match_payload import (
    find_business_envelope,
    normalize_group_matches,
    normalize_sdk_match,
)


def test_string_facts_coerce_to_unverified_claims():
    result = normalize_sdk_match(
        {
            "defectId": "A",
            "facts": ["handler reads pageId", {"claim": "ok object"}],
            "candidates": [{"path": "src/a.ts", "source": "grep"}],
        },
        requested_ids={"A"},
        raw_ref="r#A",
    )
    assert result.accepted is not None
    claims = [f.claim for f in result.accepted.facts]
    assert "handler reads pageId" in claims
    assert "ok object" in claims
    assert all(f.validity == "unverified" for f in result.accepted.facts)
    assert all(f.source == "model_reported" for f in result.accepted.facts)
    assert any(i.reason == "facts_coerced" for i in result.issues)


@pytest.mark.parametrize(
    "bad",
    [1, True, "", None, ["nested"], {"no_claim": True}],
)
def test_bad_fact_elements_are_isolated(bad):
    result = normalize_sdk_match(
        {
            "defectId": "A",
            "facts": ["keep me", bad],
            "candidates": [{"path": "src/a.ts", "source": "grep"}],
        },
        requested_ids={"A"},
        raw_ref="r#A",
    )
    assert result.accepted is not None
    assert [f.claim for f in result.accepted.facts] == ["keep me"]
    assert any("facts" in i.fieldPath for i in result.issues)


def test_bad_candidate_does_not_drop_facts():
    result = normalize_sdk_match(
        {
            "defectId": "A",
            "facts": [{"claim": "seen in route"}],
            "candidates": [
                {"path": "src/good.ts", "source": "grep"},
                {"path": "src/bad.ts", "source": "made_up"},
                {"symbol": "NoPath", "source": "grep"},
            ],
        },
        requested_ids={"A"},
        raw_ref="r#A",
    )
    assert result.accepted is not None
    assert [c.path for c in result.accepted.candidates] == ["src/good.ts"]
    assert result.accepted.facts[0].claim == "seen in route"


def test_missing_source_becomes_model_reported_not_grep():
    result = normalize_sdk_match(
        {"defectId": "A", "candidates": [{"path": "src/x.ts"}]},
        requested_ids={"A"},
        raw_ref="r#A",
    )
    assert result.accepted.candidates[0].source == "model_reported"


def test_illegal_confidence_drops_to_low():
    result = normalize_sdk_match(
        {"defectId": "A", "confidence": "ultra", "candidates": [{"path": "src/x.ts", "source": "grep"}]},
        requested_ids={"A"},
        raw_ref="r#A",
    )
    assert result.accepted.confidence == "low"
    assert any("confidence" in i.fieldPath for i in result.issues)


def test_identity_isolation_keeps_unique_legal_ticket():
    parsed = {
        "defectCodeMatches": [
            {"defectId": "A", "candidates": [{"path": "src/a.ts", "source": "grep"}], "facts": [{"claim": "ok"}]},
            {"defectId": "B", "candidates": [{"path": "src/b1.ts", "source": "grep"}]},
            {"defectId": "B", "candidates": [{"path": "src/b2.ts", "source": "grep"}]},
            {"defectId": "C", "candidates": [{"path": "src/c.ts", "source": "grep"}]},
            {"candidates": [{"path": "src/d.ts", "source": "grep"}]},
        ]
    }
    group = normalize_group_matches(parsed, requested_ids={"A", "B", "D"})
    ids = [m.defectId for m in group.accepted]
    assert ids == ["A"]
    assert any(i.reason == "duplicate_ticket" for i in group.issues)
    assert any(i.reason == "outside_group" for i in group.issues)
    assert any(i.reason == "missing_defect_id" for i in group.issues)
    assert group.accepted[0].facts[0].claim == "ok"


def test_out_of_range_candidate_keeps_facts():
    result = normalize_sdk_match(
        {
            "defectId": "A",
            "facts": [{"claim": "fact stays"}],
            "candidates": [{"path": "../etc/passwd", "source": "grep"}],
        },
        requested_ids={"A"},
        raw_ref="r#A",
        existing_paths=set(),
    )
    assert result.accepted is not None
    assert result.accepted.facts[0].claim == "fact stays"


def test_empty_structured_output_does_not_hide_later_envelope():
    envelope, ref = find_business_envelope(
        structured={},
        texts=[
            '{"ok": true}',
            '{"defectCodeMatches":[{"defectId":"A","candidates":[{"path":"src/a.ts","source":"grep"}]}]}',
        ],
    )
    assert envelope is not None
    assert envelope["defectCodeMatches"][0]["defectId"] == "A"
    assert "texts[" in ref


def test_tool_json_does_not_beat_business_envelope():
    envelope, _ = find_business_envelope(
        structured={"content": "tool"},
        texts=['{"type":"tool_result","content":"{}"}', '{"architecture":{"summary":"real"},"defectCodeMatches":[]}'],
    )
    assert envelope is not None
    assert envelope["architecture"]["summary"] == "real"


def test_model_cannot_declare_tool_observed_or_verified():
    result = normalize_sdk_match(
        {
            "defectId": "A",
            "facts": [{"claim": "x", "source": "tool_observed", "validity": "reference_verified"}],
        },
        requested_ids={"A"},
        raw_ref="r#A",
    )
    fact = result.accepted.facts[0]
    assert fact.source == "model_reported"
    assert fact.validity == "unverified"
    assert isinstance(fact, InvestigationFact)


def test_unhashable_confidence_and_bool_lists_do_not_drop_neighbor():
    parsed = {
        "architecture": {"modules": [{"id": "m", "role": {}}]},
        "defectCodeMatches": [
            {
                "defectId": "A",
                "confidence": {},
                "hypotheses": True,
                "title": {},
                "facts": [{"claim": "keep A", "reference": {"path": "src/a.ts", "snippet": "pageId"}}],
                "candidates": [{"path": "src/a.ts", "source": "grep", "symbol": 42}],
            },
            {
                "defectId": "B",
                "facts": [{"claim": "keep B"}],
                "candidates": [{"path": "src/b.ts", "source": "grep"}],
            },
        ],
    }
    group = normalize_group_matches(parsed, requested_ids={"A", "B"})
    by_id = {m.defectId: m for m in group.accepted}
    assert set(by_id) == {"A", "B"}
    assert by_id["A"].facts[0].reference is not None
    assert by_id["A"].facts[0].reference.path == "src/a.ts"
    assert by_id["A"].candidates[0].symbol is None
    assert by_id["A"].hypotheses == []
    assert "modules" in (group.shared.get("architecture") or {})
    assert group.shared["architecture"]["modules"] == []


def test_json_scanner_advances_on_braces_inside_strings():
    payload = {
        "defectCodeMatches": [
            {"defectId": "A", "facts": [{"claim": 'handler checks value == "}"'}]}
        ]
    }
    text = "prefix " + json.dumps(payload) + " suffix {not-json"
    envelope, _ = find_business_envelope(structured=None, texts=[text])
    assert envelope is not None
    assert envelope["defectCodeMatches"][0]["defectId"] == "A"


def test_verify_fact_references_upgrades_only_when_snippet_exists(tmp_path):
    from bugfix_contracts.code_knowledge import CodeReference, DefectCodeMatch, InvestigationFact
    from bugfix_platform.sdk.match_payload import verify_fact_references

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ts").write_text("const pageId = 1;\n", encoding="utf-8")
    matches = [
        DefectCodeMatch(
            defectId="A",
            facts=[
                InvestigationFact(
                    claim="reads pageId",
                    source="model_reported",
                    validity="unverified",
                    reference=CodeReference(repoId=".", path="src/a.ts", snippet="pageId"),
                )
            ],
            candidates=[{"path": "src/a.ts", "source": "grep", "why": "name"}],
        )
    ]
    out = verify_fact_references(str(tmp_path), matches, observed_paths=["src/a.ts"])
    assert out[0].facts[0].validity == "reference_verified"
    assert "src/a.ts" in out[0].observedScopes
