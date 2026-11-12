import json
from pathlib import Path

from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_contracts import DefectBatch
from bugfix_platform.sdk.cartography import (
    CARTOGRAPHY_TOOLS,
    DEFAULT_CARTOGRAPHY_MAX_TURNS,
    DISALLOWED_TOOLS,
    MAX_WEAK_PROMPT_TICKETS,
    CartographyRequest,
    CartographyResult,
    _SYSTEM_PROMPT,
    _build_prompt,
    bash_command_allowed,
    cartography_mode_from_env,
    heuristic_cartography,
    is_weak_match,
    resolve_cartography_max_turns,
)
from bugfix_platform.workflow import run_three_agent_workflow

ROOT = Path(__file__).resolve().parents[2]
HC1 = ROOT / "test" / "fixtures" / "defect-batch" / "hc1-raw.json"


def _batch() -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
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


def test_heuristic_cartography_annotates(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_MODE", raising=False)
    assert cartography_mode_from_env() == "heuristic"

    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"electron": "1"}}), encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "preview-player.ts").write_text("export {}\n", encoding="utf-8")

    knowledge = run_cartographer(
        work_dir=work,
        defect_batch=_batch(),
        cartography_mode="heuristic",
        cartography_profile="electron_node",
    )
    assert "heuristic mode" in knowledge.architecture.summary
    assert knowledge.cartographyProfile == "electron_node"


def test_cartographer_uses_injected_enricher(tmp_path: Path):
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"electron": "1"}}), encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "preview-player.ts").write_text("export {}\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_enrich(req: CartographyRequest) -> CartographyResult:
        calls["n"] += 1
        data = req.baseline.model_dump()
        data["architecture"] = {
            **data["architecture"],
            "summary": "SDK thickened electron map",
            "entryPoints": ["src/main.ts"],
        }
        data["defectCodeMatches"] = [
            {
                "defectId": "D1",
                "candidates": [
                    {
                        "repoPath": ".",
                        "path": "src/preview-player.ts",
                        "why": "sdk refined",
                        "source": "grep",
                    }
                ],
                "confidence": "high",
            }
        ]
        from bugfix_contracts import validate_code_knowledge

        return CartographyResult(
            ok=True,
            knowledge=validate_code_knowledge(data),
            source="sdk",
        )

    knowledge = run_cartographer(
        work_dir=work,
        defect_batch=_batch(),
        cartography_fn=fake_enrich,
    )
    assert calls["n"] == 1
    assert knowledge.architecture.summary == "SDK thickened electron map"
    assert knowledge.architecture.entryPoints == ["src/main.ts"]
    assert knowledge.defectCodeMatches[0].confidence == "high"


def test_workflow_cartography_heuristic(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    work = tmp_path / "mini"
    (work / "src").mkdir(parents=True)
    (work / "package.json").write_text(
        json.dumps({"name": "mini-hc", "version": "0.0.1", "dependencies": {"electron": "30.0.0"}}),
        encoding="utf-8",
    )
    (work / "CLAUDE.md").write_text("# Mini\nUse CodeGraph for search.\n", encoding="utf-8")
    (work / "src" / "preview-player.ts").write_text("export const preview = 1;\n", encoding="utf-8")
    (work / "src" / "回放.ts").write_text("export {}\n", encoding="utf-8")

    from tests.helpers import defect_batch_from_hc1

    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        cartography_mode="heuristic",
        analyze_mode="heuristic",
    )
    assert result.ok is True
    assert result.artifacts.code_knowledge is not None
    assert "heuristic mode" in result.artifacts.code_knowledge.architecture.summary


def test_heuristic_cartography_direct(tmp_path: Path):
    from bugfix_contracts import validate_code_knowledge

    baseline = validate_code_knowledge(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "workDir": str(tmp_path),
            "partial": True,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repoRoots": [{"path": "."}],
            "cartographyProfile": "unknown",
            "architecture": {"summary": "base", "entryPoints": [], "modules": []},
            "defectCodeMatches": [],
        }
    )
    out = heuristic_cartography(
        CartographyRequest(work_dir=str(tmp_path), defect_batch=_batch(), baseline=baseline)
    )
    assert out.source == "heuristic"
    assert "heuristic mode" in out.knowledge.architecture.summary


def test_cartography_tools_allow_bash_forbid_writes():
    assert "Bash" in CARTOGRAPHY_TOOLS
    assert "Read" in CARTOGRAPHY_TOOLS
    for blocked in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        assert blocked in DISALLOWED_TOOLS
    assert "Bash" not in DISALLOWED_TOOLS


def test_resolve_cartography_max_turns_defaults_to_24(monkeypatch):
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", raising=False)
    assert DEFAULT_CARTOGRAPHY_MAX_TURNS == 24
    assert resolve_cartography_max_turns() == 24
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "unlimited")
    assert resolve_cartography_max_turns() is None
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "0")
    assert resolve_cartography_max_turns() is None
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "64")
    assert resolve_cartography_max_turns() == 64
    assert resolve_cartography_max_turns(12) == 12
    assert resolve_cartography_max_turns(0) is None


def test_bash_command_allowed_readonly_vs_mutating():
    assert bash_command_allowed("rg -n login src")[0] is True
    assert bash_command_allowed("git blame src/node/routes/login.ts")[0] is True
    assert bash_command_allowed("git push origin HEAD")[0] is False
    assert bash_command_allowed("rm -rf src")[0] is False
    assert bash_command_allowed("curl https://example.com")[0] is False
    assert bash_command_allowed("npm install lodash")[0] is False


def test_system_prompt_forbids_per_ticket_call_flow():
    assert "For EACH match-pool ticket" not in _SYSTEM_PROMPT
    assert "likely fix locus" not in _SYSTEM_PROMPT
    assert "Do not follow imports/callers per ticket" in _SYSTEM_PROMPT
    assert "weak" in _SYSTEM_PROMPT.lower() or "empty" in _SYSTEM_PROMPT.lower()
    assert "0 is valid" in _SYSTEM_PROMPT.lower() or "do not pad" in _SYSTEM_PROMPT.lower()
    assert "not fix loci" in _SYSTEM_PROMPT.lower() or "catalog" in _SYSTEM_PROMPT.lower()


def _knowledge_with_matches(tmp_path: Path, matches: list[dict]):
    from bugfix_contracts import validate_code_knowledge

    return validate_code_knowledge(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "workDir": str(tmp_path),
            "partial": False,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repoRoots": [{"path": "."}],
            "cartographyProfile": "device_web",
            "architecture": {
                "summary": "dual-entry",
                "entryPoints": [
                    "src/main-pc.js",
                    "src/main-mobile.js",
                    "src/Router/pc.js",
                    "src/Router/mobile.js",
                ],
                "modules": [],
            },
            "defectCodeMatches": matches,
        }
    )


def test_is_weak_match_includes_entry_only_false_medium():
    from bugfix_contracts.code_knowledge import DefectCodeMatch

    strong = DefectCodeMatch.model_validate(
        {
            "defectId": "S",
            "candidates": [
                {
                    "path": "src/Config/snap.vue",
                    "why": 'basename "snap"',
                    "source": "grep",
                }
            ],
            "confidence": "medium",
        }
    )
    empty = DefectCodeMatch.model_validate(
        {"defectId": "E", "candidates": [], "confidence": "low"}
    )
    fake = DefectCodeMatch.model_validate(
        {
            "defectId": "F",
            "candidates": [
                {
                    "path": "src/Router/mobile.js",
                    "why": "dual-entry from title/titleTag/testModule/intent",
                    "source": "grep",
                },
                {
                    "path": "src/main-mobile.js",
                    "why": "dual-entry from title/titleTag/testModule/intent",
                    "source": "grep",
                },
            ],
            "confidence": "medium",
        }
    )
    entries = [
        "src/main-pc.js",
        "src/main-mobile.js",
        "src/Router/pc.js",
        "src/Router/mobile.js",
    ]
    assert is_weak_match(strong, entries) is False
    assert is_weak_match(empty, entries) is True
    assert is_weak_match(fake, entries) is True
    assert MAX_WEAK_PROMPT_TICKETS == 8


def test_prompt_only_includes_weak_tickets(tmp_path: Path):
    tickets = []
    matches = []
    for i in range(12):
        tickets.append(
            {
                "defectId": f"W{i}",
                "title": f"weak {i}",
                "pool": "strict",
                "expectQuality": "explicit",
                "intentRationale": "OSD 拖动后消失" if i == 0 else None,
            }
        )
        matches.append(
            {"defectId": f"W{i}", "candidates": [], "confidence": "low"}
        )
    tickets.append(
        {
            "defectId": "STRONG",
            "title": "snap overlay",
            "pool": "strict",
            "expectQuality": "explicit",
            "testModule": "Config",
            "titleTag": "snap",
            "intent": "ui_layout",
        }
    )
    matches.append(
        {
            "defectId": "STRONG",
            "candidates": [
                {
                    "path": "src/Config/snap.vue",
                    "why": 'basename "snap"',
                    "source": "grep",
                }
            ],
            "confidence": "medium",
        }
    )
    batch = DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": len(tickets), "strict": len(tickets)},
            "clusters": [],
            "tickets": tickets,
        }
    )
    req = CartographyRequest(
        work_dir=str(tmp_path),
        defect_batch=batch,
        baseline=_knowledge_with_matches(tmp_path, matches),
    )
    prompt = _build_prompt(req)
    assert "STRONG" not in prompt
    assert '"defectId": "W7"' in prompt
    assert '"defectId": "W8"' not in prompt
    assert "OSD 拖动后消失" in prompt
    assert "do not pad" in prompt.lower() or "0 is valid" in prompt.lower()


def test_merge_falls_back_to_baseline_when_sdk_candidates_all_drop(tmp_path: Path):
    from bugfix_platform.sdk.cartography import _merge_enrichment

    src = tmp_path / "src"
    src.mkdir()
    (src / "mixin.js").write_text("export default {}\n", encoding="utf-8")
    baseline = _knowledge_with_matches(
        tmp_path,
        [
            {
                "defectId": "D1",
                "candidates": [],
                "confidence": "low",
                "gap": "no_path_token_overlap",
            }
        ],
    )
    merged = _merge_enrichment(
        baseline,
        {
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "path": "src/mixin.js",
                            "why": "osd overlay mixin",
                            "source": "grep",
                        }
                    ],
                    "confidence": "high",
                }
            ]
        },
    )
    match = next(m for m in merged["defectCodeMatches"] if m["defectId"] == "D1")
    assert match["candidates"] == []
    assert match["confidence"] == "low"
    assert match.get("gap") == "no_path_token_overlap"


def test_merge_keeps_real_file_and_caps_sdk_confidence(tmp_path: Path):
    from bugfix_platform.sdk.cartography import _merge_enrichment

    src = tmp_path / "src" / "Config"
    src.mkdir(parents=True)
    (src / "snapOverlay.vue").write_text(
        "<script>export default { methods: { dragOsd() {} } }</script>\n",
        encoding="utf-8",
    )
    (src / "other.vue").write_text(
        "<script>export default { methods: { save() {} } }</script>\n",
        encoding="utf-8",
    )
    baseline = _knowledge_with_matches(
        tmp_path,
        [{"defectId": "D1", "candidates": [], "confidence": "low"}],
    )
    merged = _merge_enrichment(
        baseline,
        {
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "path": "src/Config/snapOverlay.vue",
                            "why": "osd page",
                            "source": "codegraph",
                        },
                        {
                            "path": "src/Config/other.vue",
                            "why": "pad",
                            "source": "grep",
                        },
                    ],
                    "confidence": "high",
                }
            ]
        },
    )
    match = next(m for m in merged["defectCodeMatches"] if m["defectId"] == "D1")
    assert len(match["candidates"]) == 2
    assert match["confidence"] == "medium"


def test_merge_rescues_candidate_whose_repo_path_is_the_file(tmp_path: Path):
    """peitao 02 轮的真实形状：repoPath 与 path 都填成文件路径。"""
    from bugfix_platform.sdk.cartography import _merge_enrichment

    rel = "src/view/portal/login/pc/components/loginOne.vue"
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_text("export default { methods: { doActive() {} } };\n", encoding="utf-8")
    baseline = _knowledge_with_matches(
        tmp_path, [{"defectId": "D1", "candidates": [], "confidence": "low"}]
    )
    merged = _merge_enrichment(
        baseline,
        {
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "repoPath": rel,
                            "path": rel,
                            "symbol": "doActive",
                            "why": "activation button state",
                            "source": "grep",
                        }
                    ],
                    "confidence": "high",
                }
            ]
        },
    )
    match = next(m for m in merged["defectCodeMatches"] if m["defectId"] == "D1")
    assert [c["path"] for c in match["candidates"]] == [rel]
    assert match["candidates"][0]["repoPath"] == "."
    assert match["confidence"] == "medium"  # SDK 覆盖的票封顶 medium


def test_merge_reports_dropped_candidates(tmp_path: Path):
    """丢弃必须留痕，否则「模型给了 3 个、交付 0 个」在产物里查不出。"""
    from bugfix_platform.sdk.cartography import _merge_enrichment, _with_drop_detail

    baseline = _knowledge_with_matches(
        tmp_path, [{"defectId": "D1", "candidates": [], "confidence": "low"}]
    )
    stats: dict[str, int] = {}
    _merge_enrichment(
        baseline,
        {
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [{"path": "src/ghost.vue", "why": "x", "source": "grep"}],
                    "confidence": "high",
                }
            ]
        },
        stats=stats,
    )
    assert stats == {"missing": 1}
    assert _with_drop_detail("turns=26; cost=$3.05", stats) == (
        "turns=26; cost=$3.05; dropped=missing:1"
    )
    assert _with_drop_detail("turns=26", {}) == "turns=26"
    assert _with_drop_detail(None, {"missing": 2}) == "dropped=missing:2"
