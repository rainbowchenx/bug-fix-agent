import json
import pytest
from pathlib import Path

from bugfix_platform.agents.analyst import run_analyst
from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_platform.sdk.analyze import (
    ANALYZE_TOOLS,
    AnalyzeRequest,
    AnalyzeResult,
    _SYSTEM_PROMPT,
    _build_prompt,
    analyze_allowed_tools,
    analyze_mode_from_env,
    heuristic_analyze,
    parse_analyze_payload,
    run_claude_analyze,
    select_ticket_spec_dirs,
)
from bugfix_platform.sdk.codegraph import ensure_codegraph
from bugfix_platform.workflow import run_three_agent_workflow

ROOT = Path(__file__).resolve().parents[2]
HC1 = ROOT / "tests" / "fixtures" / "defect-batch" / "hc1-raw.json"


def test_analyze_prompt_includes_architecture_map():
    from bugfix_contracts.defect_batch import BatchTicket

    ticket = BatchTicket(
        defectId="1",
        title="osd overlay",
        pool="strict",
        expectQuality="explicit",
        intentRationale="小图上拖动 OSD 后消失，是叠加位置交互问题",
    )
    req = AnalyzeRequest(
        work_dir="/tmp",
        ticket=ticket,
        routed={"outcome": "plan_only", "localization": {"candidates": []}},
        cartography_profile="device_web",
        architecture={
            "summary": "Device-web dual-entry map",
            "entryPoints": ["src/main-pc.js"],
            "modules": [{"id": "Config", "path": "src/Config", "role": "route_module"}],
        },
        reading_playbook="device_web read order: split PC vs mobile",
    )
    prompt = _build_prompt(req)
    assert "Device-web dual-entry map" in prompt
    assert "src/Config" in prompt
    assert "device_web" in prompt
    assert "叠加位置交互" in prompt
    assert "Start with the ticket's upstreamInvestigation" in _SYSTEM_PROMPT
    assert ANALYZE_TOOLS == ["Read", "Glob", "Grep"]
    assert "Reuse verifiedReferences as live source quotations" in _SYSTEM_PROMPT
    assert "Read only the needed range" in _SYSTEM_PROMPT
    assert "newEvidenceRefs" in _SYSTEM_PROMPT
    assert "candidate:1" in _SYSTEM_PROMPT


def test_analyze_prompt_uses_effective_observed_not_legacy_duplicate():
    from bugfix_contracts.defect_batch import BatchTicket

    ticket = BatchTicket(
        defectId="1",
        title="osd overlay",
        pool="strict",
        expectQuality="explicit",
        observed="蒸馏后的现象",
        sourceObserved="原始现象全文XYZ",
    )
    prompt = _build_prompt(
        AnalyzeRequest(
            work_dir="/tmp",
            ticket=ticket,
            routed={"outcome": "plan_only", "localization": {"candidates": []}},
        )
    )
    assert "蒸馏后的现象" in prompt
    assert "sourceDocument:" in prompt
    assert "原始现象全文XYZ" not in prompt


def test_analyze_prompt_includes_only_ticket_spec_dirs():
    from bugfix_contracts.defect_batch import BatchTicket

    ticket = BatchTicket(
        defectId="1",
        title="回放灰屏",
        pool="strict",
        expectQuality="explicit",
    )
    req = AnalyzeRequest(
        work_dir="/tmp",
        ticket=ticket,
        routed={
            "outcome": "plan_only",
            "localization": {
                "candidates": [
                    {"repoPath": ".", "path": "src/HCBVideo/player.vue", "why": "token"}
                ]
            },
        },
        architecture={
            "summary": "mf",
            "modules": [
                {
                    "id": "HCBVideo",
                    "path": "src/HCBVideo",
                    "notes": "回放; spec: .trellis/spec/src/HCBVideo/frontend",
                }
            ],
        },
        spec_atlas={
            "frameworkId": "trellis",
            "entries": [
                {"path": ".trellis/spec/src/HCBVideo/frontend", "kind": "doc_ref"},
                {"path": ".trellis/spec/src/HCBPortal/frontend", "kind": "doc_ref"},
            ],
        },
    )
    prompt = _build_prompt(req)
    assert "specAtlas" not in prompt
    assert "HCBPortal/frontend" not in prompt
    assert "HCBVideo/frontend" in prompt
    assert "ticketSpecDirs" in prompt
    dirs = select_ticket_spec_dirs(
        req.spec_atlas, req.architecture, req.routed
    )
    assert dirs
    assert any("HCBVideo/frontend" in p for p in dirs)
    assert not any("HCBPortal" in p for p in dirs)


def test_analyze_tools_include_codegraph_only_when_ready():
    from bugfix_platform.sdk.codegraph import CodeGraphStatus

    assert analyze_allowed_tools(None) == ["Read", "Glob", "Grep"]
    assert "codegraph_explore" not in analyze_allowed_tools(
        CodeGraphStatus(ready=False, bin="/usr/bin/codegraph")
    )
    ready = analyze_allowed_tools(CodeGraphStatus(ready=True, bin="/usr/bin/codegraph"))
    assert ready[:3] == ["Read", "Glob", "Grep"]
    assert "codegraph_explore" in ready
    assert "codegraph_callers" in ready


def test_analyze_system_prompt_uses_codegraph_first():
    text = _SYSTEM_PROMPT.lower()
    assert "codegraph_explore" in text
    assert "grep" in text
    assert "spec" in text


def test_parse_analyze_payload_fence():
    text = """Here is the analysis:
```json
{"outcome":"plan_only","rootCause":{"summary":"null deref","ruledOut":[],"openQuestions":[],"questions":[],"claims":[]},"proposedFix":{"summary":"guard null","steps":["add check"],"targetFiles":["a.ts"]},"confidence":"medium"}
```
"""
    parsed = parse_analyze_payload(text)
    assert parsed is not None
    assert parsed["outcome"] == "plan_only"
    assert parsed["proposedFix"]["summary"] == "guard null"


def test_parse_keeps_candidate_snippet_and_prompt_requires_it():
    from bugfix_contracts.analysis_report import LocCandidate
    from bugfix_platform.sdk.analyze import _merge_with_routed

    assert "snippet" in _SYSTEM_PROMPT.lower() or "excerpt" in _SYSTEM_PROMPT.lower()
    text = """```json
{"outcome":"plan_only","rootCause":{"summary":"handleFail swallows","ruledOut":[],"openQuestions":[],"questions":[],"claims":[]},"proposedFix":{"summary":"rethrow","steps":[],"targetFiles":["src/a.ts"]},"localization":{"candidates":[{"repoPath":".","path":"src/a.ts","symbol":"handleFail","why":"empty catch","snippet":"function handleFail() { return; }"}],"notes":""},"confidence":"medium"}
```"""
    parsed = parse_analyze_payload(text)
    assert parsed is not None
    cand = parsed["localization"]["candidates"][0]
    assert cand.get("snippet") == "function handleFail() { return; }"
    merged = _merge_with_routed(
        {"outcome": "plan_only", "localization": {"candidates": []}},
        parsed,
        apply_fix=True,
    )
    kept = LocCandidate.model_validate(merged["localization"]["candidates"][0])
    assert kept.snippet == "function handleFail() { return; }"


def test_heuristic_analyze_annotates(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert analyze_mode_from_env() == "heuristic"

    from bugfix_contracts.defect_batch import BatchTicket

    ticket = BatchTicket(
        defectId="1",
        title="t",
        pool="strict",
        expectQuality="explicit",
    )
    routed = {
        "outcome": "plan_only",
        "proposedFix": {"summary": "s", "steps": [], "targetFiles": ["a.ts"]},
        "rootCause": {"summary": "pending", "ruledOut": [], "openQuestions": [], "questions": [], "claims": []},
        "localization": {"candidates": [{"repoPath": ".", "path": "a.ts"}]},
        "confidence": "medium",
        "verifyStatus": "skipped",
        "suggestedVerify": {"steps": [], "executed": False},
        "blockers": None,
        "patch": None,
    }
    result = heuristic_analyze(AnalyzeRequest(work_dir="/tmp", ticket=ticket, routed=routed))
    assert result.source == "heuristic"
    assert "heuristic mode" in " ".join(result.payload["rootCause"]["openQuestions"])


def test_analyst_uses_injected_analyze_fn(tmp_path: Path):
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"electron": "1"}}), encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "preview-player.ts").write_text("export {}\n", encoding="utf-8")

    batch = DefectBatch.model_validate(
        {
            "schemaVersion": "0.4.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "[回放] preview glitch",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "testModule": "回放",
                    "titleTag": "回放",
                    "intent": "ui_layout",
                    "observed": "glitch",
                    "expected": "smooth",
                    "steps": "open preview",
                }
            ],
        }
    )
    knowledge = CodeKnowledge.model_validate(
        {
            "schemaVersion": "0.4.0",
            "productLine": "hc",
            "workDir": str(work),
            "partial": False,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repoRoots": [{"path": "."}],
            "cartographyProfile": "electron_node",
            "secondaryHints": [],
            "techStack": {"languages": ["ts"], "frameworks": ["electron"]},
            "architecture": {"summary": "mini", "entryPoints": [], "modules": []},
            "conventions": {"fromClaudeMd": [], "fromRules": []},
            "boundSkills": [],
            "specAtlas": {"frameworkId": "unknown", "entries": []},
            "capabilities": {"codeGraph": False, "runtimeVerify": False},
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/preview-player.ts",
                            "why": "token",
                            "source": "heuristic",
                        }
                    ],
                    "confidence": "medium",
                }
            ],
        }
    )

    calls = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        calls["n"] += 1
        assert req.cartography_profile == "electron_node"
        assert req.architecture is not None
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "Race in preview player init",
                    "ruledOut": ["network"],
                    "openQuestions": [], "questions": [], "claims": [],
                },
                "proposedFix": {
                    "summary": "Serialize init before play()",
                    "steps": ["guard re-entry"],
                    "targetFiles": ["src/preview-player.ts"],
                },
                "confidence": "high",
            },
        )

    report = run_analyst(
        work_dir=work,
        defect_batch=batch,
        code_knowledge=knowledge,
        analyze_fn=fake_analyze,
    )
    assert calls["n"] == 1
    assert report.tickets[0].rootCause.summary == "Race in preview player init"
    assert report.tickets[0].confidence == "high"
    assert "analyze=sdk" in (report.tickets[0].localization.notes or "")


def test_analyst_forwards_spec_atlas_and_codegraph(tmp_path: Path, monkeypatch):
    from bugfix_platform.sdk.codegraph import CodeGraphStatus

    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    (work / "src").mkdir()
    (work / "src" / "HCBVideo").mkdir()
    (work / "src" / "HCBVideo" / "player.vue").write_text("<template></template>\n", encoding="utf-8")

    batch = DefectBatch.model_validate(
        {
            "schemaVersion": "0.4.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "回放灰屏",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "intent": "logic",
                    "observed": "grey",
                    "expected": "ok",
                    "steps": "play",
                }
            ],
        }
    )
    knowledge = CodeKnowledge.model_validate(
        {
            "schemaVersion": "0.4.0",
            "productLine": "hc",
            "workDir": str(work),
            "partial": False,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repoRoots": [{"path": "."}],
            "cartographyProfile": "micro_frontend",
            "secondaryHints": [],
            "techStack": {"languages": ["js"], "frameworks": ["vue"]},
            "architecture": {
                "summary": "mf",
                "entryPoints": [],
                "modules": [{"id": "HCBVideo", "path": "src/HCBVideo"}],
            },
            "conventions": {"fromClaudeMd": [], "fromRules": []},
            "boundSkills": [],
            "specAtlas": {
                "frameworkId": "trellis",
                "entries": [
                    {
                        "path": ".trellis/spec/src/HCBVideo/frontend",
                        "kind": "doc_ref",
                    }
                ],
            },
            "capabilities": {"codeGraph": True, "runtimeVerify": False},
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/HCBVideo/player.vue",
                            "why": "token",
                            "source": "codegraph",
                        }
                    ],
                    "confidence": "medium",
                }
            ],
        }
    )
    ready = CodeGraphStatus(ready=True, bin="/usr/bin/codegraph", roots=[str(work)])
    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.ensure_codegraph",
        lambda *a, **k: ready,
    )
    seen: dict = {}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        seen["spec"] = req.spec_atlas
        seen["cg"] = req.codegraph
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "decoder stall",
                    "ruledOut": [],
                    "openQuestions": [], "questions": [], "claims": [],
                },
                "proposedFix": {
                    "summary": "reset decoder",
                    "steps": [],
                    "targetFiles": ["src/HCBVideo/player.vue"],
                },
                "confidence": "medium",
            },
        )

    report = run_analyst(
        work_dir=work,
        defect_batch=batch,
        code_knowledge=knowledge,
        analyze_fn=fake_analyze,
    )
    assert report.tickets[0].outcome == "plan_only"
    assert seen["spec"]["frameworkId"] == "trellis"
    assert seen["cg"] is ready


def test_workflow_heuristic_analyze_mode(tmp_path: Path, monkeypatch):
    from tests.helpers import ensure_git_repo

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    work = ensure_git_repo(tmp_path / "mini")
    (work / "src").mkdir(parents=True, exist_ok=True)
    (work / "package.json").write_text(
        json.dumps({"name": "mini-hc", "version": "0.0.1", "dependencies": {"electron": "30.0.0"}}),
        encoding="utf-8",
    )
    (work / "CLAUDE.md").write_text("# Mini\nUse CodeGraph for search.\n", encoding="utf-8")
    (work / "src" / "preview-player.ts").write_text("export const preview = 1;\n", encoding="utf-8")
    (work / "src" / "回放.ts").write_text("export {}\n", encoding="utf-8")
    (work / "src" / "检索.ts").write_text("export {}\n", encoding="utf-8")

    from tests.helpers import defect_batch_from_hc1

    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        analyze_mode="heuristic",
    )
    assert result.ok is True
    assert result.artifacts.analysis_report is not None
    planish = [t for t in result.artifacts.analysis_report.tickets if t.outcome == "plan_only"]
    assert planish
    assert any("heuristic" in (t.localization.notes or "") for t in planish)


def _sdk_ticket():
    from bugfix_contracts.defect_batch import BatchTicket

    return BatchTicket(
        defectId="D1",
        title="t",
        pool="strict",
        expectQuality="explicit",
        observed="preview glitch",
    )


def _sdk_routed() -> dict:
    return {
        "outcome": "plan_only",
        "proposedFix": {"summary": "inspect", "steps": [], "targetFiles": []},
        "rootCause": {"summary": "pending", "ruledOut": [], "openQuestions": [], "questions": [], "claims": []},
        "localization": {"candidates": [], "notes": ""},
        "confidence": "low",
        "verifyStatus": "skipped",
        "suggestedVerify": {"steps": [], "executed": False},
        "blockers": None,
        "patch": None,
    }


def _install_fake_sdk(monkeypatch, options_cls, query_fn, result_message_cls):
    import sys
    import types

    fake = types.ModuleType("claude_agent_sdk")
    fake.ClaudeAgentOptions = options_cls
    fake.ResultMessage = result_message_cls
    fake.query = query_fn
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)


def test_analyze_success_prints_final_trace_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("BUGFIX_TRACE", "1")
    ticket = _sdk_ticket()

    class AssistantMessage:
        content = []

    class ResultMessage:
        session_id = "test-session"
        structured_output = _sdk_routed()
        result = ""
        subtype = ""
        terminal_reason = ""
        is_error = False

    async def fake_query(*, prompt, options):
        yield AssistantMessage()
        yield ResultMessage()

    _install_fake_sdk(monkeypatch, dict, fake_query, ResultMessage)
    result = run_claude_analyze(AnalyzeRequest(
        work_dir=str(tmp_path), ticket=ticket, routed=_sdk_routed(), artifact_dir=str(tmp_path),
    ))

    assert result.ok
    assert capsys.readouterr().out.splitlines() == ["[agent3] turn 1"]
    trace = tmp_path / "logs" / f"agent3-{ticket.defectId}.jsonl"
    assert json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])["kind"] == "result"


@pytest.mark.parametrize("salvage", [False, True])
def test_analyze_drains_sdk_error_before_returning_failure(tmp_path, monkeypatch, salvage):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    drained = []

    class ResultMessage:
        session_id = "test-session"
        structured_output = None
        result = ""
        subtype = ""
        terminal_reason = ""
        is_error = True
        errors = ["model service rejected the request"]

    async def fake_query(*, prompt, options):
        result = ResultMessage()
        if salvage and "resume" not in options:
            result.subtype = "error_max_turns"
            yield result
            return
        yield result
        # Code after the terminal frame runs only if the caller drains the stream.
        drained.append(True)

    _install_fake_sdk(monkeypatch, dict, fake_query, ResultMessage)
    result = run_claude_analyze(AnalyzeRequest(
        work_dir=str(tmp_path), ticket=_sdk_ticket(), routed=_sdk_routed(),
    ))
    assert drained == [True]
    assert result.source == "sdk_fallback"
    if not salvage:
        assert "model service rejected the request" in result.detail


def test_detailed_analyze_records_salvage(tmp_path, monkeypatch, capsys):
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock

    from bugfix_platform.sdk.trace import trace_output

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    ticket = _sdk_ticket()
    payload = _sdk_routed()
    payload["rootCause"]["summary"] = "Salvaged root cause"

    async def query(*, prompt, options):
        assert options.include_partial_messages
        if options.resume:
            yield AssistantMessage(content=[TextBlock(text="Reformatting the report")], model="m")
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id="s1", structured_output=payload if options.resume else None,
        )

    _install_fake_sdk(monkeypatch, ClaudeAgentOptions, query, ResultMessage)
    with trace_output("detailed"):
        result = run_claude_analyze(AnalyzeRequest(
            work_dir=str(tmp_path), ticket=ticket, routed=_sdk_routed(), artifact_dir=str(tmp_path),
        ))

    assert result.ok and "salvaged" in result.detail
    live = capsys.readouterr()
    assert f"analysis salvage [{ticket.defectId}]" in live.err
    assert "Reformatting the report" in live.err
    path = tmp_path / "logs" / f"agent3-{ticket.defectId}.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [event["phase"] for event in events if event["kind"] == "request"] == [
        "analysis", "analysis salvage",
    ]
    assert events[-1]["structuredOutput"] == payload


def test_resume_unsupported_records_degrade_and_starts_new(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("BUGFIX_CODEGRAPH", "0")
    payload = {
        "outcome": "plan_only",
        "rootCause": {"summary": "race in preview", "ruledOut": [], "openQuestions": [], "questions": [], "claims": []},
        "proposedFix": {"summary": "serialize init", "steps": [], "targetFiles": []},
        "localization": {"candidates": []},
    }

    class ResultMessage:
        pass

    class Result(ResultMessage):
        session_id = "new-sess"
        structured_output = payload
        result = json.dumps(payload)
        is_error = False
        errors: list[str] = []
        subtype = ""
        terminal_reason = ""

    class Opts:
        def __init__(self, **kwargs):
            if "resume" in kwargs:
                raise TypeError("resume not supported")
            self.kwargs = kwargs

    async def fake_query(*, prompt, options):
        assert "resume" not in options.kwargs
        assert options.kwargs["strict_mcp_config"] is True
        assert json.loads(options.kwargs["mcp_servers"]) == {"mcpServers": {}}
        yield Result()

    _install_fake_sdk(monkeypatch, Opts, fake_query, ResultMessage)
    result = run_claude_analyze(
        AnalyzeRequest(
            work_dir=str(tmp_path),
            ticket=_sdk_ticket(),
            routed=_sdk_routed(),
            codegraph=ensure_codegraph(tmp_path),
            resume_session_id="old-sess",
        )
    )
    assert result.source == "sdk"
    assert result.detail and "resume unsupported" in result.detail
    assert "starting new session" in (result.detail or "")
    assert result.payload.get("rootCause", {}).get("summary") == "race in preview"


def test_inaccessible_session_starts_new_with_ticket_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    payload = {
        "outcome": "plan_only",
        "rootCause": {"summary": "loaded current defect", "ruledOut": [], "openQuestions": [], "questions": [], "claims": []},
        "proposedFix": {"summary": "retry path", "steps": [], "targetFiles": []},
        "localization": {"candidates": []},
    }
    seen_resume: list[bool] = []

    class ResultMessage:
        pass

    class Result(ResultMessage):
        session_id = "fresh-sess"
        structured_output = payload
        result = json.dumps(payload)
        is_error = False
        errors: list[str] = []
        subtype = ""
        terminal_reason = ""

    class Opts:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def fake_query(*, prompt, options):
        resumed = bool((getattr(options, "kwargs", {}) or {}).get("resume"))
        seen_resume.append(resumed)
        if resumed:
            raise RuntimeError("session not found")
        assert "preview glitch" in prompt
        yield Result()

    _install_fake_sdk(monkeypatch, Opts, fake_query, ResultMessage)
    result = run_claude_analyze(
        AnalyzeRequest(
            work_dir=str(tmp_path),
            ticket=_sdk_ticket(),
            routed=_sdk_routed(),
            resume_session_id="dead-sess",
        )
    )
    assert seen_resume == [True, False]
    assert result.source == "sdk"
    assert result.detail and "session inaccessible" in result.detail
    assert "starting new session" in (result.detail or "")
    assert result.payload.get("rootCause", {}).get("summary") == "loaded current defect"


def test_missing_claims_gets_one_format_repair_then_incomplete(tmp_path,monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-key')
    payload={'outcome':'plan_only','rootCause':{'summary':'known partial fact','questions':[]},
        'proposedFix':{'summary':'investigate'},'localization':{'candidates':[]}}
    calls=[]
    class ResultMessage: pass
    class Result(ResultMessage):
        session_id='s';structured_output=payload;result='';is_error=False;errors=[];subtype='';terminal_reason=''
    class Opts:
        def __init__(self,**kwargs): self.kwargs=kwargs
    async def query(*,prompt,options):
        calls.append(prompt);yield Result()
    _install_fake_sdk(monkeypatch,Opts,query,ResultMessage)
    result=run_claude_analyze(AnalyzeRequest(str(tmp_path),_sdk_ticket(),_sdk_routed()))
    assert len(calls)==2 and result.payload['outcome']=='other_blocked'
    assert 'incomplete' in result.detail
    assert 'known partial fact' in result.payload['rootCause']['summary']


def test_image_configuration_error_not_retried_as_budget_or_session_failure(tmp_path,monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-key')
    calls=[]
    class ResultMessage: pass
    class Opts:
        def __init__(self,**kwargs): self.kwargs=kwargs
    async def query(*,prompt,options):
        calls.append(prompt)
        raise RuntimeError('model only supports text; image input is unsupported')
        yield
    _install_fake_sdk(monkeypatch,Opts,query,ResultMessage)
    result=run_claude_analyze(AnalyzeRequest(str(tmp_path),_sdk_ticket(),_sdk_routed(),resume_session_id='old'))
    assert len(calls)==1 and 'modality configuration' in result.detail
    assert 'max_turns' not in result.detail


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("complete", [False, True])
def test_skill_read_requires_successful_tool_result(tmp_path,monkeypatch,relative,complete):
    from types import SimpleNamespace
    from bugfix_platform.sdk.skill_inject import InjectedSkill
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-key')
    skill_path=tmp_path/'SKILL.md';skill_path.write_text('Read business setup.')
    skill=InjectedSkill('business',skill_path,'explicit','setup','Read business setup.',('analyze',))
    payload={'outcome':'plan_only','rootCause':{'summary':'hypothesis','questions':[],'claims':[]},
        'proposedFix':{'summary':'investigate'},'localization':{'candidates':[]}}
    class ResultMessage: pass
    class Result(ResultMessage):
        session_id='s';structured_output=payload if complete else None;result='';is_error=False;errors=[];subtype='';terminal_reason=''
    class Opts:
        def __init__(self,**kwargs): self.kwargs=kwargs
    failed=[True]
    async def query(*,prompt,options):
        yield SimpleNamespace(content=[SimpleNamespace(name='Read',id='r1',input={'file_path':'SKILL.md' if relative else str(skill_path)})])
        yield SimpleNamespace(content=[SimpleNamespace(tool_use_id='r1',is_error=failed[0],content='tool response')])
        yield Result()
    _install_fake_sdk(monkeypatch,Opts,query,ResultMessage)
    req=AnalyzeRequest(str(tmp_path),_sdk_ticket(),_sdk_routed(),injected_skills=(skill,))
    assert run_claude_analyze(req).skill_reads==[]
    failed[0]=False
    assert run_claude_analyze(req).skill_reads==[str(skill_path.resolve())]


def test_parse_reports_contract_rejection_reason():
    """JSON 合法但违反契约时，要把原因说出来。

    以前 `_normalize_payload` 抛的 ValueError 被吞成 None，上层统一报
    "sdk returned no parseable JSON analysis" —— 明明解析到了合法 JSON，
    查日志却往"模型没输出 JSON"这个错误方向走。
    """
    dup = {
        "rootCause": {
            "summary": "x",
            "claims": [
                {"claimId": "c1", "statement": "a", "role": "fact",
                 "status": "supported", "evidenceRefs": ["candidate:1"]},
                {"claimId": "c1", "statement": "b", "role": "fact",
                 "status": "supported", "evidenceRefs": ["candidate:1"]},
            ],
            "questions": [],
        }
    }
    notes: list[str] = []
    assert parse_analyze_payload(dup, notes) is None
    assert len(notes) == 1
    assert "duplicate claimId" in notes[0]
    # 明确说是"被契约拒绝"，不是"没解析到 JSON"
    assert "rejected by contract" in notes[0]


def test_parse_no_note_when_input_is_not_json():
    """非 JSON 输入不产生契约拒绝记录 —— 两者必须能区分开。"""
    notes: list[str] = []
    assert parse_analyze_payload("这里没有任何 JSON", notes) is None
    assert notes == []


def test_parse_unknown_claim_reference_reported():
    bad = {
        "rootCause": {
            "summary": "x",
            "claims": [],
            "questions": [
                {"id": "q1", "kind": "verification", "reason": "r",
                 "relatedClaimIds": ["c9"], "requestedEvidence": "e",
                 "category": "fact", "status": "open",
                 "predecessorId": None, "newEvidenceRefs": []}
            ],
        }
    }
    notes: list[str] = []
    assert parse_analyze_payload(bad, notes) is None
    assert "question references unknown claim" in notes[0]


def test_ticket_usage_and_bounded_tool_policy_include_salvage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from claude_agent_sdk import HookMatcher
    from bugfix_platform.sdk.analyze import DEFAULT_ANALYZE_MAX_TURNS
    from bugfix_platform.sdk.codegraph import CodeGraphStatus

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    graph_tool = "mcp__codegraph__codegraph_explore"
    attempts = []

    class ResultMessage:
        session_id = "test-session"
        result = ""
        terminal_reason = ""
        is_error = False

        def __init__(self, *, usage, turns, structured_output=None, subtype=""):
            self.usage = usage
            self.num_turns = turns
            self.structured_output = structured_output
            self.subtype = subtype

    def event(**block):
        return SimpleNamespace(content=[SimpleNamespace(**block)])

    async def query(*, prompt, options):
        attempts.append(options["max_turns"])
        hook = options["hooks"]["PreToolUse"][-1].hooks[0]

        async def use(tool, params, tool_id):
            result = await hook({"tool_name": tool, "tool_input": params}, tool_id, None)
            return result.get("hookSpecificOutput", {})

        read = {"file_path": "src/a.py", "offset": 30}
        if options.get("resume"):
            assert (await use("Read", read, "salvage-denied"))["permissionDecision"] == "deny"
            yield ResultMessage(usage={"prompt_tokens": 5, "completion_tokens": 7}, turns=1,
                                structured_output=_sdk_routed())
            return

        fallback = {"path": "src", "pattern": "save"}
        assert (await use("Grep", fallback, "grep-denied"))["permissionDecision"] == "deny"
        search = {"task": "Locate save"}
        assert await use(graph_tool, search, "g") == {}
        yield event(name=graph_tool, id="g", input=search)
        yield event(tool_use_id="g", is_error=False, content="No match")
        assert (await use(graph_tool, search, "g-duplicate"))["permissionDecision"] == "deny"
        assert await use("Grep", fallback, "grep") == {}
        yield event(tool_use_id="grep", is_error=False, content="src/a.py")

        effective = (await use("Read", read, "r"))["updatedInput"]
        assert effective == {**read, "limit": 80}
        yield event(name="Read", id="r", input=effective)
        body = "first\n第二行"
        yield event(tool_use_id="r", is_error=False, content=[{"type": "text", "text": body}])
        assert (await use("Read", effective, "r-duplicate"))["permissionDecision"] == "deny"
        assert await use("Read", {**effective, "offset": 120}, "r-pending") == {}
        yield ResultMessage(usage={"input_tokens": 20, "output_tokens": 4, "cache_read_input_tokens": 100},
                            turns=4, subtype="error_max_turns")

    _install_fake_sdk(monkeypatch, dict, query, ResultMessage)
    import claude_agent_sdk
    claude_agent_sdk.HookMatcher = HookMatcher
    result = run_claude_analyze(AnalyzeRequest(
        str(tmp_path), _sdk_ticket(), _sdk_routed(),
        codegraph=CodeGraphStatus(ready=True, roots=[str(tmp_path)]),
    ))
    assert result.ok
    assert attempts == [DEFAULT_ANALYZE_MAX_TURNS, 2]
    usage = result.usage
    assert (usage.sdkResults, usage.turns, usage.inputTokens, usage.outputTokens, usage.cacheReadTokens) == (2, 5, 25, 11, 100)
    assert (usage.readCalls, usage.readResultLines, usage.readResultBytes) == (1, 2, len("first\n第二行".encode()))
    assert usage.duplicateReadsBlocked == 1
    assert (usage.readRequests, usage.readBlocked, usage.readCalls) == (4, 2, 1)
    assert (usage.codeGraphRequests, usage.codeGraphBlocked, usage.codeGraphCalls) == (2, 1, 1)
    assert (usage.grepGlobRequests, usage.grepGlobBlocked, usage.grepGlobCalls) == (2, 1, 1)


def test_disconnected_codegraph_allows_scoped_search(tmp_path):
    from types import SimpleNamespace
    from bugfix_platform.sdk.analyze_tools import AnalysisTools

    tools = AnalysisTools(str(tmp_path), graph_ready=True, full_read_paths=["attachment.png"])
    tools.observe(SimpleNamespace(subtype="init", data={"mcp_servers": [{"name": "codegraph", "status": "failed"}]}))
    assert tools.before_tool({"tool_name": "Glob", "tool_input": {"path": "src", "pattern": "*.py"}}) == {}
    assert tools.before_tool({"tool_name": "Read", "tool_input": {"file_path": "attachment.png"}}) == {}
