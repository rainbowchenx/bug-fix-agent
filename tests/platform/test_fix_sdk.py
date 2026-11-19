"""SDK fixer 必须返回执行和复核结果，不靠工作副本里的 Git diff。"""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_contracts.defect_batch import BatchTicket
from bugfix_platform.sdk.fix import FixRequest, run_claude_fix


def _ticket() -> BatchTicket:
    return BatchTicket(
        defectId="D1",
        title="preview glitch",
        pool="strict",
        expectQuality="explicit",
        observed="silent fail",
        expected="show error toast",
    )


def _install_fake_sdk(monkeypatch, options_cls, query_fn, result_message_cls):
    import sys
    import types

    fake = types.ModuleType("claude_agent_sdk")
    fake.ClaudeAgentOptions = options_cls
    fake.ResultMessage = result_message_cls
    fake.query = query_fn
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)


def test_run_claude_fix_keeps_edits_and_review_without_git(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    work = tmp_path / "copy"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("function handleFail() { return; }\n", encoding="utf-8")
    assert not (work / ".git").exists()
    review = {
        "semanticReview": "rethrow restores toast; fail path still visible in handleFail",
        "semanticReviewStatus": "passed",
        "semanticReviewExecuted": True,
        "commitMessage": "fix: surface handleFail errors (D1)",
    }

    class ResultMessage:
        pass

    class Result(ResultMessage):
        is_error = False
        result = json.dumps(review)
        errors: list[str] = []

    class Opts:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.cwd = kwargs.get("cwd")

    async def fake_query(*, prompt, options):
        Path(options.cwd, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        yield Result()

    _install_fake_sdk(monkeypatch, Opts, fake_query, ResultMessage)
    result = run_claude_fix(
        FixRequest(
            work_dir=str(tmp_path / "repo"),
            ticket=_ticket(),
            analysis={"proposedFix": {"summary": "rethrow"}},
            worktree_path=str(work),
            artifact_dir=str(tmp_path / "art"),
        )
    )
    assert result.ok
    assert result.source == "sdk"
    assert result.detail != "fix session produced empty diff"
    assert "rethrow restores toast" in str(result.payload.get("semanticReview") or "")
    assert result.payload.get("semanticReviewStatus") == "passed"
    assert result.payload.get("commitMessage") == review["commitMessage"]
    assert "throw e" in (work / "src" / "a.ts").read_text(encoding="utf-8")
    assert result.payload, "git-less work copy must not drop the SDK payload"


def _run_fix_with_review(tmp_path: Path, monkeypatch, review: dict) -> object:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    work = tmp_path / "copy"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("function handleFail() { return; }\n", encoding="utf-8")

    class ResultMessage:
        pass

    class Result(ResultMessage):
        is_error = False
        result = json.dumps(review)
        errors: list[str] = []

    class Opts:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.cwd = kwargs.get("cwd")

    async def fake_query(*, prompt, options):
        Path(options.cwd, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        yield Result()

    _install_fake_sdk(monkeypatch, Opts, fake_query, ResultMessage)
    return run_claude_fix(
        FixRequest(
            work_dir=str(tmp_path / "repo"),
            ticket=_ticket(),
            analysis={"proposedFix": {"summary": "rethrow"}},
            worktree_path=str(work),
            artifact_dir=str(tmp_path / "art"),
        )
    )


def test_negative_review_without_status_is_not_executed(tmp_path: Path, monkeypatch):
    result = _run_fix_with_review(
        tmp_path,
        monkeypatch,
        {"semanticReview": "修改仍未解决问题"},
    )
    assert result.payload.get("semanticReviewStatus") == "not_executed"
    blob = str(result.payload.get("semanticReview") or "")
    assert "修改仍未解决问题" in blob
    assert "missing" in blob.lower() or "status" in blob.lower()


def test_unknown_review_status_is_not_executed(tmp_path: Path, monkeypatch):
    result = _run_fix_with_review(
        tmp_path,
        monkeypatch,
        {
            "semanticReview": "looks fine",
            "semanticReviewStatus": "ok",
            "semanticReviewExecuted": True,
        },
    )
    assert result.payload.get("semanticReviewStatus") == "not_executed"
    blob = str(result.payload.get("semanticReview") or "")
    assert "ok" in blob.lower() or "unknown" in blob.lower()
