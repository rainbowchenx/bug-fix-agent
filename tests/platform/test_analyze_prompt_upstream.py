"""Agent-3 的 prompt 要以上游调查为起点，但不能把它当既定事实。

首轮实测撞 24 轮上限：5 次 codegraph 探索、3 次重读上游已点名的同一个文件，
全部是在重做 Agent-2 已经做过的事。三处根因：

1. codeGraph 那行写着 "MUST use codegraph_explore first" —— 无条件命令
2. softStartLocalization 与 upstreamInvestigation.candidates 逐字重复
3. 首轮 previousAttempt 为空，却仍输出一条指向它的指令
"""

from __future__ import annotations

from hashlib import sha256

from bugfix_platform.sdk.analyze import _SYSTEM_PROMPT, _build_prompt, _select_investigation, AnalyzeRequest
from bugfix_platform.sdk.codegraph import CodeGraphStatus


def _req(**overrides) -> AnalyzeRequest:
    base = dict(
        ticket=_ticket(),
        work_dir=".",
        routed={"outcome": "plan_only", "localization": {"candidates": [], "notes": ""}},
        investigation={},
        codegraph=None,
        cartography_profile="device_web",
        reading_playbook="",
        architecture={},
        spec_atlas={},
        injected_skills=[],
        apply_fix=False,
        previous_attempt=None,
    )
    base.update(overrides)
    return AnalyzeRequest(**base)


def _ticket():
    """复用真实契约，避免手搓字段和 ApplyRequest 定义漂移。"""
    from tests.helpers import ensure_git_repo  # noqa: F401  (保持导入路径一致)
    from bugfix_contracts.defect_batch import BatchTicket
    return BatchTicket(
        defectId="D1", title="t", pool="strict", testModule="m", titleTag="g",
        intent="ui_layout", intentRationale="r", observed="o", expected="e",
        steps="s", expectQuality="explicit", sourceDocument=None,
    )


def test_upstream_investigation_is_framed_as_starting_point():
    req = _req(investigation={"candidates": [{"path": "a.vue", "symbol": "save"}]})
    text = _build_prompt(req)
    assert "upstreamInvestigation:" in text
    assert "a.vue" in text and "save" in text
    assert "Heuristic paths and unverified claims are leads" in _SYSTEM_PROMPT


def test_empty_investigation_omits_the_block():
    assert "upstreamInvestigation:" not in _build_prompt(_req(investigation={}))


def test_soft_start_candidates_are_not_duplicated():
    """两个字段的 candidates 逐字相同，只应保留上游那一份。"""
    candidates = [{"path": "a.vue", "symbol": "save", "why": "w"}]
    req = _req(
        investigation={"candidates": candidates},
        routed={"outcome": "plan_only", "localization": {"candidates": candidates, "notes": "soft"}},
    )
    text = _build_prompt(req)
    assert "softStartLocalization:" not in text
    # 它独有的 notes 仍要保留
    assert "matchGap: soft" in text


def test_previous_attempt_block_only_when_present():
    assert "previousAttempt:" not in _build_prompt(_req(previous_attempt=None))
    text = _build_prompt(_req(previous_attempt={"analysisRef": {"path": "x.json"}}))
    assert "previousAttempt:" in text
    assert "x.json" in text
    assert "Only investigate evidence affected by the new feedback" in text
    assert "Carry forward unaffected conclusions" in text


def test_agent2_verified_reference_is_reused_only_while_current(tmp_path):
    repo = tmp_path / "app"
    repo.mkdir()
    path = repo / "store.py"
    snippet = "return state.pending"
    path.write_text(snippet, encoding="utf-8")
    req = _req(work_dir=str(tmp_path), investigation={
        "candidates": [
            {"path": f"heuristic{i}.py", "source": "heuristic"} for i in range(4)
        ] + [{"repoPath": "app", "path": "store.py", "symbol": "save", "source": "codegraph"}],
        "facts": [{"claim": "Uses pending state", "validity": "reference_verified", "reference": {
            "repoId": "app", "path": "store.py", "snippet": snippet,
            "contentDigest": sha256(path.read_bytes()).hexdigest(),
        }}],
        "nextChecks": ["Check who calls save"],
        "ruledOut": ["CSS"],
    }, architecture={"entryPoints": ["unrelated-entry.py"]}, spec_atlas={"bindings": ["unrelated-binding"]})
    packet = _select_investigation(req)
    assert len(packet["candidates"]) == 3
    assert packet["candidates"][0]["path"] == "store.py"
    assert packet["verifiedReferences"][0]["snippet"] == snippet
    assert packet["nextChecks"] == ["Check who calls save"]
    assert packet["ruledOut"] == ["CSS"]
    prompt = _build_prompt(req)
    assert "unrelated-entry.py" not in prompt
    assert "unrelated-binding" not in prompt
    path.write_text(f"# Changed since Agent2\n{snippet}", encoding="utf-8")
    stale = _select_investigation(req)
    assert "verifiedReferences" not in stale
    assert stale["unverifiedClaims"] == ["Uses pending state"]


def test_codegraph_hint_keeps_explore_mandatory():
    """措辞必须明确 codegraph_explore 是主路径。

    曾经把它改成「需要搜的时候先用 codegraph」这种条件式，模型读成
    「Grep/Read 也行」，于是 Grep 从 2 次涨到 23 次、Glob 到 10 次，
    轮次从 25 涨到 46。所以这里锁死强制措辞。
    """
    cg = CodeGraphStatus(ready=True, version="1.6.2", roots=["/repo"], root_stats={"/repo": {"files": 10}})
    line = cg.prompt_roots_line()
    assert "ALWAYS use codegraph_explore" in line
    assert "never replace it with a series of Grep/Glob" in line
    assert "Grep/Glob are a fallback only" in line
    # 上游已定位时直接读，这条例外要保留
    assert "upstreamInvestigation already located" in line
