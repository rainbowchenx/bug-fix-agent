"""T9：正式入口控制链。假 SDK 证明隔离/反馈/授权，不证明真实模型理解。"""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_platform.agents.analyst.analysis_store import load_analysis_snapshot
from bugfix_platform.agents.analyst.feedback_document import parse_feedback_form
from bugfix_platform.agents.analyst.feedback import import_feedback
from bugfix_platform.cli import main as platform_main
from bugfix_platform.sdk.analyze import AnalyzeResult
from bugfix_platform.sdk.cartography import CartographyResult
from bugfix_platform.sdk.fix import FixResult
from bugfix_platform.workflow import run_three_agent_workflow
from tests.helpers import ensure_git_repo
from tests.platform.test_analysis_snapshots import _entry


def _mini_repo(root: Path) -> Path:
    ensure_git_repo(root)
    src = root / "src"
    src.mkdir()
    (src / "add.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    return root


def _batch(product="hc") -> DefectBatch:
    return DefectBatch.model_validate({
        "schemaVersion": "0.4.0",
        "productLine": product,
        "posture": "alpha",
        "generatedAt": "2026-01-01T00:00:00Z",
        "funnel": {"total": 1, "strict": 1},
        "clusters": [],
        "tickets": [{
            "defectId": "D1",
            "title": "add returns difference",
            "pool": "strict",
            "expectQuality": "explicit",
            "observed": "add(1,2) == -1",
            "expected": "add(1,2) == 3",
        }],
    })


def test_report_only_keeps_legal_match_and_writes_form(tmp_path, monkeypatch):
    from bugfix_platform.sdk.codegraph import CodeGraphStatus
    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.ensure_codegraph",
        lambda *a, **k: CodeGraphStatus(ready=False),
    )
    work = _mini_repo(tmp_path / "repo")
    out = tmp_path / "out"
    batch = _batch()
    (tmp_path / "batch.json").write_text(batch.model_dump_json(), encoding="utf-8")

    def agent2(**kwargs):
        baseline = kwargs["defect_batch"]
        knowledge = CodeKnowledge.model_validate({
            "schemaVersion": "0.4.0",
            "productLine": "hc",
            "workDir": str(work),
            "generatedAt": "2026-01-01T00:00:00Z",
            "partial": False,
            "defectCodeMatches": [{
                "defectId": "D1",
                "candidates": [{"path": "src/add.py", "source": "grep", "why": "add"}],
                "facts": [{"claim": "bad", "source": "model_reported"}],
                "confidence": "medium",
                "observedScopes": ["src/add.py"],
                "investigationStatus": "complete",
            }],
        })
        return knowledge

    def agent3(**kwargs):
        from bugfix_platform.agents.analyst.run import run_analyst
        def analyze(req):
            payload = dict(req.routed)
            payload.update(_entry())
            payload["previousAttemptSeen"] = bool(req.previous_attempt)
            return AnalyzeResult(ok=True, payload=payload, source="sdk")
        return run_analyst(
            work_dir=kwargs["work_dir"],
            defect_batch=kwargs["defect_batch"],
            code_knowledge=kwargs["code_knowledge"],
            analyze_fn=analyze,
            artifact_dir=kwargs.get("artifact_dir"),
            apply_fix=False,
        )

    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        defect_batch=batch,
        apply_fix=False,
        artifact_dir=out,
        agent2=agent2,
        agent3=agent3,
    )
    assert result.ok
    form = out / "defects" / "D1" / "feedback-form.md"
    assert form.is_file()
    filled = form.read_text(encoding="utf-8").replace(
        "<!-- ANSWER:q1 -->\n\n<!-- /ANSWER:q1 -->",
        "<!-- ANSWER:q1 -->\naddition a+b\n<!-- /ANSWER:q1 -->",
    )
    form.write_text(filled, encoding="utf-8")
    assert platform_main(["feedback", "--root", str(out), "--file", str(form)]) == 0
    before = (work / "src" / "add.py").read_text(encoding="utf-8")
    seen = {"previous": False}

    def analyze2(req):
        seen["previous"] = bool(req.previous_attempt) and "addition a+b" in json.dumps(
            req.previous_attempt or {}, ensure_ascii=False
        )
        payload = dict(req.routed)
        payload.update(_entry())
        payload["rootCause"]["questions"] = []
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    from bugfix_platform.agents.analyst.run import run_analyst
    from bugfix_contracts.defect_batch import load_defect_batch
    from bugfix_contracts.code_knowledge import validate_code_knowledge
    from bugfix_platform.agents.analyst.sessions import load_revision
    batch = load_defect_batch(out / "defect-batch.json")
    knowledge = validate_code_knowledge(json.loads((out / "code-knowledge.json").read_text(encoding="utf-8")))
    revision = load_revision(out, "D1")
    report2 = run_analyst(
        work_dir=work,
        defect_batch=batch,
        code_knowledge=knowledge,
        analyze_fn=analyze2,
        artifact_dir=out,
        apply_fix=False,
        ticket_ids=["D1"],
        revisions={"D1": revision} if revision is not None else {},
    )
    assert seen["previous"] is True
    assert report2.applyFix is False
    assert (work / "src" / "add.py").read_text(encoding="utf-8") == before


def test_apply_fix_control_chain_writes_real_file(tmp_path, monkeypatch):
    from bugfix_platform.sdk.codegraph import CodeGraphStatus
    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.ensure_codegraph",
        lambda *a, **k: CodeGraphStatus(ready=False),
    )
    work = _mini_repo(tmp_path / "repo")
    out = tmp_path / "out"
    batch = _batch()
    knowledge = CodeKnowledge.model_validate({
        "schemaVersion": "0.4.0",
        "productLine": "hc",
        "workDir": str(work),
        "generatedAt": "2026-01-01T00:00:00Z",
        "partial": False,
        "defectCodeMatches": [{
            "defectId": "D1",
            "candidates": [{"path": "src/add.py", "source": "grep", "why": "add"}],
            "confidence": "high",
            "observedScopes": ["src/add.py"],
        }],
    })

    def analyze(req):
        payload = dict(req.routed)
        payload.update({
            "outcome": "plan_only",
            "proposedFix": {
                "summary": "return a+b",
                "steps": ["edit add"],
                "targetFiles": ["src/add.py"],
            },
            "rootCause": {
                "summary": "add subtracts instead of adding",
                "ruledOut": [],
                "openQuestions": [],
                "questions": [],
                "claims": [{
                    "claimId": "c1",
                    "statement": "operands swapped",
                    "role": "conclusion",
                    "status": "unverified",
                    "evidenceRefs": ["candidate:1"],
                    "assumptions": [],
                }],
            },
            "localization": {
                "candidates": [{
                    "repoPath": ".",
                    "path": "src/add.py",
                    "why": "add implementation",
                    "snippet": "return a - b",
                    "source": "grep",
                }],
            },
            "blockers": None,
            "confidence": "high",
            "verifyStatus": "skipped",
            "suggestedVerify": {"steps": ["python -c"], "executed": False},
        })
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    calls = {"n": 0}

    def fixer(req):
        calls["n"] += 1
        target = Path(req.worktree_path) / "src" / "add.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        return FixResult(ok=True, source="sdk", payload={
            "semanticReviewStatus": "passed",
            "semanticReview": "operands restored",
        })

    from bugfix_platform.agents.analyst.run import run_analyst
    report = run_analyst(
        work_dir=work,
        defect_batch=batch,
        code_knowledge=knowledge,
        analyze_fn=analyze,
        fix_fn=fixer,
        apply_fix=True,
        artifact_dir=out,
    )
    assert report.applyFix is True
    assert calls["n"] == 1
    assert report.tickets[0].defectId == "D1"


def test_closing_pass_cannot_wipe_unanswered_questions(tmp_path, monkeypatch):
    from bugfix_platform.sdk.codegraph import CodeGraphStatus
    from bugfix_platform.agents.analyst.run import run_analyst
    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.ensure_codegraph",
        lambda *a, **k: CodeGraphStatus(ready=False),
    )
    work = _mini_repo(tmp_path / "repo")
    out = tmp_path / "out"
    knowledge = CodeKnowledge.model_validate({
        "schemaVersion": "0.4.0",
        "productLine": "hc",
        "workDir": str(work),
        "generatedAt": "2026-01-01T00:00:00Z",
        "partial": False,
        "defectCodeMatches": [{
            "defectId": "D1",
            "candidates": [{"path": "src/add.py", "source": "grep", "why": "add"}],
            "confidence": "medium",
        }],
    })

    def analyze1(req):
        payload = dict(req.routed)
        payload.update(_entry())
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    run_analyst(
        work_dir=work, defect_batch=_batch(), code_knowledge=knowledge,
        analyze_fn=analyze1, artifact_dir=out, apply_fix=False,
    )

    def analyze2(req):
        payload = dict(req.routed)
        payload.update(_entry())
        payload["rootCause"]["questions"] = []
        payload["outcome"] = "patch_ready"
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    report2 = run_analyst(
        work_dir=work, defect_batch=_batch(), code_knowledge=knowledge,
        analyze_fn=analyze2, artifact_dir=out, apply_fix=True,
        fix_fn=lambda req: FixResult(ok=True, source="sdk", payload={}),
    )
    ticket = report2.tickets[0]
    assert ticket.actionability["allowed"] is False
    assert any(q.id == "q1" for q in (ticket.rootCause.questions or []))


def test_candidate_alias_converges_implementation_question(tmp_path, monkeypatch):
    from bugfix_platform.sdk.codegraph import CodeGraphStatus
    from bugfix_platform.agents.analyst.run import run_analyst
    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.ensure_codegraph",
        lambda *a, **k: CodeGraphStatus(ready=False),
    )
    work = _mini_repo(tmp_path / "repo")
    out = tmp_path / "out"
    knowledge = CodeKnowledge.model_validate({
        "schemaVersion": "0.4.0",
        "productLine": "hc",
        "workDir": str(work),
        "generatedAt": "2026-01-01T00:00:00Z",
        "partial": False,
        "defectCodeMatches": [{
            "defectId": "D1",
            "candidates": [{"path": "src/add.py", "source": "grep", "why": "add"}],
            "confidence": "medium",
            "observedScopes": ["src/add.py"],
        }],
    })

    def analyze1(req):
        payload = dict(req.routed)
        payload.update(_entry())
        payload["rootCause"]["questions"] = [{
            "id": "q2",
            "kind": "choice",
            "reason": "map or for?",
            "category": "implementation",
            "relatedClaimIds": ["c1"],
        }]
        payload["localization"]["candidates"] = [{
            "path": "src/add.py",
            "why": "add implementation here",
            "snippet": "return a - b",
            "source": "grep",
        }]
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    run_analyst(
        work_dir=work, defect_batch=_batch(), code_knowledge=knowledge,
        analyze_fn=analyze1, artifact_dir=out, apply_fix=False,
    )

    def analyze2(req):
        payload = dict(req.routed)
        payload.update(_entry())
        payload["rootCause"]["questions"] = [{
            "id": "q2",
            "kind": "choice",
            "reason": "use for-loop",
            "category": "implementation",
            "status": "resolved",
            "newEvidenceRefs": ["candidate:1"],
            "relatedClaimIds": ["c1"],
        }]
        payload["localization"]["candidates"] = [{
            "path": "src/add.py",
            "why": "add implementation here",
            "snippet": "return a - b",
            "source": "grep",
        }]
        payload["outcome"] = "plan_only"
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    report2 = run_analyst(
        work_dir=work, defect_batch=_batch(), code_knowledge=knowledge,
        analyze_fn=analyze2, artifact_dir=out, apply_fix=False,
    )
    ticket = report2.tickets[0]
    assert ticket.actionability.get("allowed") is True
    assert not any(q.id == "q2" and q.status != "resolved" for q in (ticket.rootCause.questions or []))


def test_closing_rebuilds_evidence_after_source_change(tmp_path, monkeypatch):
    from bugfix_platform.sdk.codegraph import CodeGraphStatus
    from bugfix_platform.agents.analyst.run import run_analyst
    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.ensure_codegraph",
        lambda *a, **k: CodeGraphStatus(ready=False),
    )
    work = _mini_repo(tmp_path / "repo")
    out = tmp_path / "out"
    knowledge = CodeKnowledge.model_validate({
        "schemaVersion": "0.4.0",
        "productLine": "hc",
        "workDir": str(work),
        "generatedAt": "2026-01-01T00:00:00Z",
        "partial": False,
        "defectCodeMatches": [{
            "defectId": "D1",
            "candidates": [{"path": "src/add.py", "source": "grep", "why": "add"}],
            "confidence": "medium",
        }],
    })

    def analyze1(req):
        payload = dict(req.routed)
        payload.update(_entry())
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    run_analyst(
        work_dir=work, defect_batch=_batch(), code_knowledge=knowledge,
        analyze_fn=analyze1, artifact_dir=out, apply_fix=False,
    )

    def analyze2(req):
        payload = dict(req.routed)
        payload.update(_entry())
        if (req.previous_attempt or {}).get("closingPass"):
            (work / "src" / "add.py").write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")
            payload["localization"]["candidates"] = [{
                "path": "src/add.py",
                "why": "add implementation here",
                "snippet": "return a - b",
                "source": "grep",
            }]
            payload["rootCause"]["questions"] = [{
                "id": "q1",
                "kind": "choice",
                "reason": "user confirmed a+b",
                "category": "product",
                "status": "resolved",
                "relatedClaimIds": ["c1"],
                "newEvidenceRefs": ["read-D1-1"],
            }]
            payload["outcome"] = "patch_ready"
        else:
            payload["rootCause"]["questions"] = []
            payload["outcome"] = "patch_ready"
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    report2 = run_analyst(
        work_dir=work, defect_batch=_batch(), code_knowledge=knowledge,
        analyze_fn=analyze2, artifact_dir=out, apply_fix=True,
        fix_fn=lambda req: FixResult(ok=True, source="sdk", payload={}),
    )
    ticket = report2.tickets[0]
    assert ticket.actionability["allowed"] is False
