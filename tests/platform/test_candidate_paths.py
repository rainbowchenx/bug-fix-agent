"""候选路径解析：`repoPath` 填错不能让一个正确答案凭空消失。

现场两次都栽在这里（transport 09 轮、peitao 02 轮）：模型把同一个文件路径同时
填进 `repoPath` 和 `path`，`root / repoPath / path` 拼成 `<file>/<file>`，不存在
→ 静默 `continue` → 模型答对的 3 个候选全丢，产物回落成启发式原样，而自证行还
照写 `enrich=sdk`。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bugfix_contracts.code_knowledge import DefectCodeMatch, MatchCandidate
from bugfix_platform.agents.cartographer.match import (
    _resolve_candidate_path,
    filter_existing_candidates,
)

_PEITAO = Path("E:/working_code_webfront/bug-fix-demo-project/peitao")
_LOGIN = "src/view/portal/login/pc/components/loginOne.vue"


def _cand(path: str, repo_path: str = ".", symbol: str | None = None) -> MatchCandidate:
    return MatchCandidate(
        path=path, repoPath=repo_path, why="sdk", source="grep", symbol=symbol
    )


def _match(defect_id: str, *candidates: MatchCandidate) -> DefectCodeMatch:
    return DefectCodeMatch(
        defectId=defect_id, candidates=list(candidates), confidence="high"
    )


def _write(repo: Path, rel: str, body: str = "export function f() { return 1; }\n") -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def test_repo_path_filled_with_the_file_is_recovered(tmp_path: Path):
    """peitao/transport 的真实错法：repoPath 与 path 都是同一个文件路径。"""
    _write(tmp_path, _LOGIN, "export default { methods: { doActive() {} } };\n")
    out = filter_existing_candidates(tmp_path, [_match("D1", _cand(_LOGIN, _LOGIN, "doActive"))])

    assert [c.path for c in out[0].candidates] == [_LOGIN]
    # 归一成 "."：否则下游再按 repoPath/path 拼一次，又拼不出文件。
    assert out[0].candidates[0].repoPath == "."


def test_multi_repo_layout_still_resolves_through_repo_path(tmp_path: Path):
    """正常情况不能被"回退"弄坏：repoPath 指向仓根时原样保留。"""
    _write(tmp_path, "packages/app/src/a.vue")
    out = filter_existing_candidates(
        tmp_path, [_match("D1", _cand("src/a.vue", "packages/app", "a"))]
    )
    assert [c.path for c in out[0].candidates] == ["src/a.vue"]
    assert out[0].candidates[0].repoPath == "packages/app"


def test_unknown_repo_path_is_dropped_not_guessed(tmp_path: Path):
    """两条路都拼不出文件 → 丢，不许凭 path 猜别的仓。"""
    _write(tmp_path, "packages/app/src/a.vue")
    stats: dict[str, int] = {}
    out = filter_existing_candidates(
        tmp_path,
        [_match("D1", _cand("src/other.vue", "packages/app"))],
        stats=stats,
    )
    assert out[0].candidates == []
    assert stats == {"missing": 1}


def test_same_file_spelled_two_ways_is_deduped(tmp_path: Path):
    """一份文件两种写法（repoPath 对 / repoPath 填成文件）只留一条。"""
    _write(tmp_path, "src/a.vue")
    stats: dict[str, int] = {}
    out = filter_existing_candidates(
        tmp_path,
        [_match("D1", _cand("src/a.vue"), _cand("src/a.vue", "src/a.vue"))],
        stats=stats,
    )
    assert [c.path for c in out[0].candidates] == ["src/a.vue"]
    assert stats == {"duplicate": 1}


def test_drop_reasons_are_counted_so_the_loss_is_visible(tmp_path: Path):
    """被丢弃的原因必须能报出来，否则「给了 3 个、交付 0 个」查无实据。"""
    _write(tmp_path, "src/ok.vue", "export default { name: 'ok' };\n")
    _write(tmp_path, "src/vacuum.js", "// nothing\n/* todo */\n")
    (tmp_path / "src" / "stub.js").write_text("", encoding="utf-8")
    stats: dict[str, int] = {}
    # 每票候选上限 3 条，第 4 条起不评估——按票分开造，才能把四种原因都踩到。
    matches = [
        _match("D1", _cand("src/ok.vue", ".", "ok")),
        _match("D2", _cand("src/vacuum.js")),
        _match("D3", _cand("src/stub.js")),
        _match("D4", _cand("src/missing.vue")),
        _match("D5", _cand("src/ok.vue", ".", "noSuchSymbol")),
    ]
    out = filter_existing_candidates(tmp_path, matches, profile="device_web", stats=stats)
    kept = {m.defectId: [c.path for c in m.candidates] for m in out}
    assert kept == {"D1": ["src/ok.vue"], "D2": [], "D3": [], "D4": [], "D5": []}
    assert stats == {"vacuum": 2, "missing": 1, "symbol": 1}


def test_resolver_does_not_mutate_the_incoming_candidate(tmp_path: Path):
    """``_resolve_candidate_path`` 只返回归一后的副本（要能重放原始产物）。"""
    _write(tmp_path, "src/a.vue")
    original = _cand("src/a.vue", "src/a.vue")
    found = _resolve_candidate_path(tmp_path, original)
    assert found is not None
    resolved, normalised = found
    assert resolved == (tmp_path / "src/a.vue").resolve()
    assert normalised.repoPath == "."
    assert original.repoPath == "src/a.vue"


def test_real_peitao_sample_regression():
    """真实样本：模型给的 3 个候选全部能解析回原文件（仓不在则跳过）。"""
    if not _PEITAO.is_dir():
        pytest.skip("peitao repo not present")
    sdk_candidates = [
        _LOGIN,
        "src/common/vue/service/request/webAuth.js",
        "src/common/vue/service/request/otap.js",
    ]
    out = filter_existing_candidates(
        _PEITAO,
        [_match("BGCM2026102702747", *[_cand(p, p) for p in sdk_candidates])],
        profile="device_web",
    )
    assert [c.path for c in out[0].candidates] == sdk_candidates
    assert all(c.repoPath == "." for c in out[0].candidates)
