"""T3：complete 不是 facts 非空；进度/停止原因可追。"""

from __future__ import annotations

from bugfix_contracts.code_knowledge import DefectCodeMatch, InvestigationFact, CodeReference
from bugfix_platform.sdk.cartography import annotate_investigation_coverage


def test_string_facts_without_reference_are_not_complete():
    match = DefectCodeMatch(
        defectId="D1",
        facts=[InvestigationFact(claim="maybe", source="model_reported", validity="unverified")],
        searchedScopes=["src/"],
    )
    out = annotate_investigation_coverage([match], prompt_ids=["D1"], investigated_ids=["D1"])
    assert out[0].investigationStatus == "partial"


def test_path_only_candidate_is_not_complete():
    match = DefectCodeMatch(
        defectId="D1",
        candidates=[{"path": "src/a.ts", "source": "grep", "why": "name"}],
    )
    out = annotate_investigation_coverage([match], prompt_ids=["D1"], investigated_ids=["D1"])
    assert out[0].investigationStatus == "partial"


def test_reference_verified_snippet_is_complete_not_root_cause():
    match = DefectCodeMatch(
        defectId="D1",
        facts=[
            InvestigationFact(
                claim="reads pageId",
                source="model_reported",
                validity="reference_verified",
                reference=CodeReference(repoId=".", path="src/a.ts", snippet="pageId"),
            )
        ],
    )
    out = annotate_investigation_coverage([match], prompt_ids=["D1"], investigated_ids=["D1"])
    assert out[0].investigationStatus == "complete"
    assert out[0].facts[0].validity == "reference_verified"


def test_model_scopes_are_not_tool_observations():
    match = DefectCodeMatch(defectId="D1", searchedScopes=["src/"], observedScopes=[])
    out = annotate_investigation_coverage([match], prompt_ids=["D1"], investigated_ids=["D1"])
    assert out[0].investigationStatus == "partial"
    observed = DefectCodeMatch(defectId="D1", searchedScopes=["src/"], observedScopes=["src/"])
    out2 = annotate_investigation_coverage([observed], prompt_ids=["D1"], investigated_ids=["D1"])
    assert out2[0].investigationStatus == "complete"


def test_missing_returned_ticket_is_not_not_investigated():
    matches = [
        DefectCodeMatch(defectId="D1"),
        DefectCodeMatch(defectId="D2"),
    ]
    out = annotate_investigation_coverage(matches, prompt_ids=["D1", "D2"], investigated_ids=["D1"])
    by_id = {m.defectId: m for m in out}
    assert by_id["D2"].investigationStatus != "not_investigated"


def test_artifact_error_cannot_be_complete():
    match = DefectCodeMatch(
        defectId="D1",
        observedScopes=["src/"],
        storageStatus="artifact_error",
    )
    out = annotate_investigation_coverage([match], prompt_ids=["D1"], investigated_ids=["D1"])
    assert out[0].investigationStatus == "partial"


def test_resume_skips_complete_journal_not_partial(tmp_path):
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from tests.platform.test_investigation_batches import request, complete

    req = request(tmp_path / "repo", 17)
    calls = []

    def runner(r):
        calls.append([t.defectId for t in r.defect_batch.tickets])
        return complete(r)

    artifacts = tmp_path / "art"
    first = investigate_groups(req, runner, max_groups=1, artifact_dir=artifacts, resume_dir=artifacts)
    assert sum(m.investigationStatus == "complete" for m in first.knowledge.defectCodeMatches) == 8
    second = investigate_groups(req, runner, max_groups=1, artifact_dir=artifacts, resume_dir=artifacts)
    assert len(calls) == 2
    assert calls[1][0] == "8"
    assert sum(m.investigationStatus == "complete" for m in second.knowledge.defectCodeMatches) == 16
    journal = (artifacts / "agent2" / "progress.json").read_text(encoding="utf-8")
    assert "complete" in journal
    assert "cacheKey" in journal


def test_journal_does_not_resume_complete_group_after_ticket_text_changes(tmp_path):
    from dataclasses import replace
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from tests.platform.test_investigation_batches import request, complete

    req = request(tmp_path / "repo", 8)
    calls = []

    def runner(r):
        calls.append([t.defectId for t in r.defect_batch.tickets])
        return complete(r)

    artifacts = tmp_path / "art"
    investigate_groups(req, runner, artifact_dir=artifacts, resume_dir=artifacts)
    assert len(calls) == 1
    tickets = []
    for ticket in req.defect_batch.tickets:
        tickets.append(ticket.model_copy(update={"title": ticket.title + " changed"}))
    changed = replace(req, defect_batch=req.defect_batch.model_copy(update={"tickets": tickets}))
    investigate_groups(changed, runner, artifact_dir=artifacts, resume_dir=artifacts)
    assert len(calls) == 2


def test_ticket_ids_rerun_keeps_other_tickets(tmp_path):
    from dataclasses import replace
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from tests.platform.test_investigation_batches import request, complete

    req = request(tmp_path / "repo", 9)
    calls = []

    def runner(r):
        ids = [t.defectId for t in r.defect_batch.tickets]
        calls.append(ids)
        if ids == ["8"] and len(calls) == 2:
            raise RuntimeError("provider timeout")
        return complete(r)

    first = investigate_groups(req, runner, group_size=8)
    failed = [m.defectId for m in first.knowledge.defectCodeMatches if m.investigationStatus == "failed"]
    assert failed == ["8"]
    second = investigate_groups(
        replace(req, baseline=first.knowledge),
        runner,
        ticket_ids=failed,
        group_size=8,
    )
    assert calls[-1] == ["8"]
    assert all(
        m.investigationStatus == "complete" for m in second.knowledge.defectCodeMatches
    )


def test_subset_resume_keeps_historical_journal_groups(tmp_path):
    from dataclasses import replace
    import json
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from tests.platform.test_investigation_batches import request, complete

    req = request(tmp_path / "repo", 9)
    calls = []

    def runner(r):
        calls.append([t.defectId for t in r.defect_batch.tickets])
        return complete(r)

    artifacts = tmp_path / "art"
    investigate_groups(req, runner, group_size=8, artifact_dir=artifacts, resume_dir=artifacts)
    first_groups = len(json.loads((artifacts / "agent2" / "progress.json").read_text(encoding="utf-8"))["groups"])
    assert first_groups >= 2
    investigate_groups(
        replace(req, baseline=req.baseline),
        runner,
        ticket_ids=["8"],
        group_size=8,
        artifact_dir=artifacts,
        resume_dir=artifacts,
    )
    journal = json.loads((artifacts / "agent2" / "progress.json").read_text(encoding="utf-8"))
    assert len(journal["groups"]) >= first_groups
    before = len(calls)
    investigate_groups(req, runner, group_size=8, artifact_dir=artifacts, resume_dir=artifacts)
    assert len(calls) == before


def test_sdk_partial_group_is_not_resumed_as_complete(tmp_path):
    import json
    from bugfix_contracts.code_knowledge import InvestigationFact, CodeReference
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from bugfix_platform.sdk.cartography import CartographyResult
    from tests.platform.test_investigation_batches import request

    req = request(tmp_path / "repo", 1)
    calls = []

    def runner(r):
        calls.append([t.defectId for t in r.defect_batch.tickets])
        match = r.baseline.defectCodeMatches[0].model_copy(
            update={
                "investigationStatus": "complete",
                "searchedScopes": ["src"],
                "observedScopes": ["src/a.ts"],
                "facts": [
                    InvestigationFact(
                        claim="reads pageId",
                        source="model_reported",
                        validity="reference_verified",
                        reference=CodeReference(repoId=".", path="src/a.ts", snippet="pageId"),
                    )
                ],
            }
        )
        return CartographyResult(
            True,
            r.baseline.model_copy(update={"partial": True, "defectCodeMatches": [match]}),
            "sdk",
            "sdk marked partial",
        )

    artifacts = tmp_path / "art"
    first = investigate_groups(req, runner, artifact_dir=artifacts, resume_dir=artifacts)
    assert first.knowledge.partial is True
    journal = json.loads((artifacts / "agent2" / "progress.json").read_text(encoding="utf-8"))
    assert journal["groups"][0]["status"] == "partial"
    assert journal["groups"][0]["partial"] is True
    before = len(calls)
    second = investigate_groups(req, runner, artifact_dir=artifacts, resume_dir=artifacts)
    assert len(calls) == before + 1
    assert second.knowledge.partial is True


def test_zero_budget_resume_keeps_group_partial(tmp_path):
    from bugfix_contracts.code_knowledge import InvestigationFact, CodeReference
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from bugfix_platform.sdk.cartography import CartographyResult
    from tests.platform.test_investigation_batches import request

    req = request(tmp_path / "repo", 1)
    calls = []

    def runner(r):
        calls.append([t.defectId for t in r.defect_batch.tickets])
        match = r.baseline.defectCodeMatches[0].model_copy(
            update={
                "investigationStatus": "complete",
                "searchedScopes": ["src"],
                "observedScopes": ["src/a.ts"],
                "facts": [
                    InvestigationFact(
                        claim="reads pageId",
                        source="model_reported",
                        validity="reference_verified",
                        reference=CodeReference(repoId=".", path="src/a.ts", snippet="pageId"),
                    )
                ],
            }
        )
        return CartographyResult(
            True,
            r.baseline.model_copy(update={"partial": True, "defectCodeMatches": [match]}),
            "sdk",
            "sdk marked partial",
        )

    artifacts = tmp_path / "art"
    first = investigate_groups(req, runner, artifact_dir=artifacts, resume_dir=artifacts)
    assert first.knowledge.partial is True
    before = len(calls)
    second = investigate_groups(
        req, runner, max_groups=0, artifact_dir=artifacts, resume_dir=artifacts
    )
    assert len(calls) == before
    assert second.knowledge.partial is True
    assert "budget_exhausted" in (second.detail or "")
    assert second.knowledge.defectCodeMatches[0].facts == first.knowledge.defectCodeMatches[0].facts

    from tests.platform.test_investigation_batches import complete

    def finish(r):
        assert r.baseline.defectCodeMatches[0].facts == first.knowledge.defectCodeMatches[0].facts
        result = complete(r)
        match = result.knowledge.defectCodeMatches[0].model_copy(update={"facts": []})
        result.knowledge = result.knowledge.model_copy(update={"defectCodeMatches": [match]})
        return result

    cache = tmp_path / "cache"
    completed = investigate_groups(req, finish, artifact_dir=artifacts, resume_dir=artifacts, cache_dir=cache)
    assert completed.knowledge.partial is False
    assert completed.knowledge.defectCodeMatches[0].facts == first.knowledge.defectCodeMatches[0].facts
    cached = investigate_groups(req, runner, max_groups=0, cache_dir=cache)
    assert len(calls) == before
    assert cached.knowledge.partial is False
    assert cached.knowledge.defectCodeMatches[0].facts == first.knowledge.defectCodeMatches[0].facts


def test_journal_restores_matches_from_verified_input_version(tmp_path):
    from dataclasses import replace
    from bugfix_contracts.code_knowledge import InvestigationFact
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from bugfix_platform.sdk.cartography import CartographyResult
    from tests.platform.test_investigation_batches import request, complete

    req = request(tmp_path / "repo", 9)
    calls = []

    def runner(r):
        calls.append([t.defectId for t in r.defect_batch.tickets])
        result = complete(r)
        tagged = []
        for match, ticket in zip(result.knowledge.defectCodeMatches, r.defect_batch.tickets):
            tagged.append(
                match.model_copy(
                    update={
                        "facts": [
                            InvestigationFact(
                                claim=f"from:{ticket.title}",
                                source="model_reported",
                                validity="unverified",
                            )
                        ]
                    }
                )
            )
        return CartographyResult(
            True,
            result.knowledge.model_copy(update={"defectCodeMatches": tagged}),
            "sdk",
        )

    artifacts = tmp_path / "art"
    investigate_groups(req, runner, group_size=8, artifact_dir=artifacts, resume_dir=artifacts)
    tickets = [
        t.model_copy(update={"title": "changed target"}) if t.defectId == "0" else t
        for t in req.defect_batch.tickets
    ]
    changed = replace(req, defect_batch=req.defect_batch.model_copy(update={"tickets": tickets}))
    investigate_groups(
        changed, runner, ticket_ids=["0"], group_size=8, artifact_dir=artifacts, resume_dir=artifacts
    )
    restore_tickets = [
        t.model_copy(update={"title": "failure"}) if t.defectId == "0" else t
        for t in req.defect_batch.tickets
    ]
    restored_req = replace(
        req, defect_batch=req.defect_batch.model_copy(update={"tickets": restore_tickets})
    )
    before = len(calls)
    out = investigate_groups(
        restored_req,
        runner,
        ticket_ids=["8"],
        group_size=8,
        artifact_dir=artifacts,
        resume_dir=artifacts,
    )
    by_id = {m.defectId: m for m in out.knowledge.defectCodeMatches}
    assert by_id["0"].facts[0].claim == "from:failure"
    assert by_id["0"].investigationStatus == "complete"
    assert all(c != ["0"] for c in calls[before:])


def test_zero_budget_restores_groups_after_first_pending_group(tmp_path):
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from tests.platform.test_investigation_batches import complete, request

    req = request(tmp_path / "repo", 2)
    calls = []

    def runner(group):
        result = complete(group)
        did = group.defect_batch.tickets[0].defectId
        calls.append(did)
        if did == "0":
            result.knowledge = result.knowledge.model_copy(update={"partial": True})
        return result

    artifacts = tmp_path / "art"
    options = dict(group_size=1, artifact_dir=artifacts, resume_dir=artifacts)
    investigate_groups(req, runner, **options)
    resumed = investigate_groups(req, runner, max_groups=0, **options)
    assert calls == ["0", "1"]
    assert resumed.knowledge.partial is True
    assert resumed.knowledge.investigationRuns[0]["status"] == "complete"
    assert resumed.knowledge.defectCodeMatches[1].investigationStatus == "complete"
