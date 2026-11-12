import json
from pathlib import Path

from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_contracts import DefectBatch
from bugfix_platform.sdk.cartography import (
    CARTOGRAPHY_TOOLS,
    DEFAULT_CARTOGRAPHY_BASE_TURNS,
    DEFAULT_CARTOGRAPHY_MAX_TURNS,
    DEFAULT_CARTOGRAPHY_TURNS_PER_TICKET,
    DISALLOWED_TOOLS,
    MAX_PROMPT_TICKETS,
    MAX_WEAK_PROMPT_TICKETS,
    CartographyRequest,
    CartographyResult,
    _SYSTEM_PROMPT,
    _build_prompt,
    bash_command_allowed,
    cartography_mode_from_env,
    cartography_turns_for_tickets,
    heuristic_cartography,
    is_weak_match,
    resolve_cartography_max_turns,
    select_prompt_tickets,
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
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_BASE_TURNS", raising=False)
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_TURNS_PER_TICKET", raising=False)
    assert DEFAULT_CARTOGRAPHY_MAX_TURNS == 24
    # No ticket count → compat fallback.
    assert resolve_cartography_max_turns() == 24
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "unlimited")
    assert resolve_cartography_max_turns() is None
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "0")
    assert resolve_cartography_max_turns() is None
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "64")
    assert resolve_cartography_max_turns() == 64
    assert resolve_cartography_max_turns(12) == 12
    assert resolve_cartography_max_turns(0) is None


def test_cartography_turns_scale_with_ticket_count(monkeypatch):
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", raising=False)
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_BASE_TURNS", raising=False)
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_TURNS_PER_TICKET", raising=False)
    assert DEFAULT_CARTOGRAPHY_BASE_TURNS == 6
    assert DEFAULT_CARTOGRAPHY_TURNS_PER_TICKET == 2
    assert cartography_turns_for_tickets(0) == 6
    assert cartography_turns_for_tickets(1) == 8
    assert cartography_turns_for_tickets(8) == 22
    assert resolve_cartography_max_turns(ticket_count=8) == 22
    assert resolve_cartography_max_turns(weak_ticket_count=8) == 22  # alias
    # Absolute env still wins over ticket budget.
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "40")
    assert resolve_cartography_max_turns(ticket_count=8) == 40
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", raising=False)
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_BASE_TURNS", "4")
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_TURNS_PER_TICKET", "5")
    assert cartography_turns_for_tickets(3) == 19


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
    assert "shallow" in _SYSTEM_PROMPT.lower()
    assert "unverified" in _SYSTEM_PROMPT.lower()
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
    assert MAX_PROMPT_TICKETS == 16
    assert MAX_WEAK_PROMPT_TICKETS == MAX_PROMPT_TICKETS


def test_prompt_includes_heuristic_medium_tickets(tmp_path: Path):
    """启发式 medium 也要进 prompt（降权 + heuristicUnverified），不能跳过。"""
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
    assert '"defectId": "STRONG"' in prompt
    assert "heuristicUnverified" in prompt
    assert '"heuristicUnverified": true' in prompt
    # 进 prompt 时把 baseline medium 降成 low，避免模型照抄。
    assert '"defectId": "STRONG"' in prompt and '"confidence": "low"' in prompt
    assert '"defectId": "W7"' in prompt
    assert '"defectId": "W11"' in prompt  # 12 弱 + 1 强 ≤ 16，全进
    assert "OSD 拖动后消失" in prompt
    assert "shallow-pass" in prompt.lower() or "do not pad" in prompt.lower()


def test_prompt_caps_at_max_and_prefers_weak(tmp_path: Path):
    tickets = []
    matches = []
    for i in range(MAX_PROMPT_TICKETS + 4):
        tickets.append(
            {
                "defectId": f"H{i}",
                "title": f"hit {i}",
                "pool": "strict",
                "expectQuality": "explicit",
            }
        )
        matches.append(
            {
                "defectId": f"H{i}",
                "candidates": [
                    {
                        "path": f"src/mod{i}.vue",
                        "why": "basename",
                        "source": "grep",
                    }
                ],
                "confidence": "medium",
            }
        )
    tickets.append(
        {
            "defectId": "EMPTY",
            "title": "empty last",
            "pool": "strict",
            "expectQuality": "explicit",
        }
    )
    matches.append({"defectId": "EMPTY", "candidates": [], "confidence": "low"})
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
    pairs = select_prompt_tickets(req)
    assert len(pairs) == MAX_PROMPT_TICKETS
    assert pairs[0][0].defectId == "EMPTY"
    prompt = _build_prompt(req, prompt_pairs=pairs)
    assert '"defectId": "EMPTY"' in prompt
    assert f'"defectId": "H{MAX_PROMPT_TICKETS + 3}"' not in prompt


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


def test_merge_keeps_sdk_answer_when_gap_is_prose(tmp_path: Path):
    """led 13 轮的真实形状：模型答对了，却在 gap 里写了一句解释。

    `gap` 是枚举 `no_path_token_overlap`，整条 `DefectCodeMatch` 校验失败后
    以前会把这张票连 baseline 原件一起静默丢掉（40 → 39）。只丢这个字段。
    """
    from bugfix_platform.sdk.cartography import _merge_enrichment

    rel = "web/src/layout/projectDialog/list/factorSimulationDialog.vue"
    # 真实形状：仓在 workDir 下的子目录 calibrationtool/，模型把仓名又写进了 path
    target = tmp_path / "calibrationtool" / rel
    target.parent.mkdir(parents=True)
    target.write_text("<script>export default { methods: { handlePick() {} } }</script>\n")
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
    stats: dict[str, int] = {}
    merged = _merge_enrichment(
        baseline,
        {
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "repoPath": "calibrationtool",
                            "path": f"calibrationtool/{rel}",
                            "symbol": "handlePick",
                            "why": "系数仿真弹窗本体",
                            "source": "grep",
                        }
                    ],
                    "confidence": "medium",
                    "gap": "症状为未最大化时左侧列表不可点，可能落在布局或尺寸计算",
                }
            ]
        },
        stats=stats,
    )
    match = next(m for m in merged["defectCodeMatches"] if m["defectId"] == "D1")
    assert match["candidates"][0]["path"] == f"calibrationtool/{rel}"
    assert match["candidates"][0]["repoPath"] == "."  # 回退命中后归一，不再重复前缀
    assert match.get("gap") is None
    assert match["confidence"] == "medium"
    assert stats == {"gap_coerced": 1}


def test_merge_keeps_baseline_when_sdk_entry_is_invalid(tmp_path: Path):
    """不合 schema 的条目不能先顶掉 baseline 那条，再自己消失。"""
    from bugfix_platform.sdk.cartography import _merge_enrichment, _with_drop_detail

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
    stats: dict[str, int] = {}
    merged = _merge_enrichment(
        baseline,
        {"defectCodeMatches": [{"defectId": "D1", "candidates": "not-a-list"}]},
        stats=stats,
    )
    match = next(m for m in merged["defectCodeMatches"] if m["defectId"] == "D1")
    assert match["gap"] == "no_path_token_overlap"
    assert match["confidence"] == "low"
    assert stats == {"invalid_match": 1}
    assert "dropped=invalid_match:1" in _with_drop_detail("turns=7", stats)


def test_merge_modules_keeps_structural_ids(tmp_path: Path):
    """整段替换会把规则算的 controller 域 / ipc:<Prefix> 节点换成散文。"""
    from bugfix_platform.sdk.cartography import _merge_enrichment

    from bugfix_contracts import validate_code_knowledge

    baseline = validate_code_knowledge(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "workDir": str(tmp_path),
            "partial": False,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repoRoots": [{"path": "."}],
            "cartographyProfile": "electron_node",
            "architecture": {
                "summary": "electron",
                "entryPoints": [],
                "modules": [
                    {"id": "camera", "path": "electron/controller/camera", "notes": "IPC 域"},
                    {
                        "id": "ipc:Camera",
                        "path": "electron/controller/camera",
                        "notes": "Camera_* → controller/camera",
                    },
                ],
            },
            "defectCodeMatches": [],
        }
    )
    merged = _merge_enrichment(
        baseline,
        {
            "architecture": {
                "modules": [
                    {"id": "camera", "path": "electron/controller/camera", "notes": "相机控制与预览"},
                    {"id": "controller-devices", "path": "electron/controller", "notes": "设备类域汇总"},
                ]
            }
        },
    )
    modules = {m["id"]: m for m in merged["architecture"]["modules"]}
    assert set(modules) == {"camera", "ipc:Camera", "controller-devices"}
    assert modules["camera"]["notes"] == "相机控制与预览"  # 同 id 覆盖 notes
    assert modules["ipc:Camera"]["notes"] == "Camera_* → controller/camera"  # 结构节点保留


def test_prompt_treats_shared_candidate_sets_as_weak(tmp_path: Path):
    """多张票候选集完全相同 = 并列分，不是定位；必须进 prompt，且示例里不带 gap。"""
    tickets = []
    matches = []
    for i in range(4):
        tickets.append(
            {
                "defectId": f"B{i}",
                "title": f"缺陷 {i}",
                "pool": "strict",
                "expectQuality": "explicit",
                "testModule": "结构,校正工具",
                "titleTag": "校正工具",
                "intent": "logic",
            }
        )
        matches.append(
            {
                "defectId": f"B{i}",
                "candidates": [
                    {"path": "electron/controller/camera/index.ts", "why": "x", "source": "grep"},
                    {"path": "electron/controller/luxMeter/index.ts", "why": "x", "source": "grep"},
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
    assert '"defectId": "B0"' in prompt
    assert '"gap"' not in prompt
    assert "gap" in _SYSTEM_PROMPT  # 提示词明确禁止模型自己写 gap


def test_merge_overridden_ticket_keeps_baseline_title(tmp_path: Path):
    """模型只回 defectId/candidates/confidence；title/clusterId 要继承 baseline。"""
    from bugfix_platform.sdk.cartography import _merge_enrichment

    src = tmp_path / "src"
    src.mkdir()
    (src / "cfg.vue").write_text("<script>export default {}</script>\n", encoding="utf-8")
    baseline = _knowledge_with_matches(
        tmp_path,
        [
            {
                "defectId": "D1",
                "title": "[校正工具] 分区配置按钮文案不一致",
                "clusterId": "hc::结构::校正工具::ui_layout",
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
                    "candidates": [{"path": "src/cfg.vue", "why": "x", "source": "grep"}],
                    "confidence": "medium",
                }
            ]
        },
    )
    match = next(m for m in merged["defectCodeMatches"] if m["defectId"] == "D1")
    assert match["title"] == "[校正工具] 分区配置按钮文案不一致"
    assert match["clusterId"] == "hc::结构::校正工具::ui_layout"


def test_prompt_gives_genuinely_weak_tickets_priority(tmp_path: Path):
    """并列候选票不能把空候选那张挤出名额（led 轮 2981 被挤掉）。"""
    tickets = []
    matches = []
    # 超过上限：真弱仍应优先占第一席。
    for i in range(MAX_PROMPT_TICKETS + 2):
        tickets.append(
            {
                "defectId": f"S{i}",
                "title": f"并列 {i}",
                "pool": "strict",
                "expectQuality": "explicit",
                "testModule": "结构,校正工具",
                "titleTag": "校正工具",
                "intent": "logic",
            }
        )
        matches.append(
            {
                "defectId": f"S{i}",
                "candidates": [
                    {"path": "electron/controller/camera/index.ts", "why": "x", "source": "grep"},
                    {"path": "electron/controller/luxMeter/index.ts", "why": "x", "source": "grep"},
                ],
                "confidence": "medium",
            }
        )
    # 排最后的那张：真弱（空候选）
    tickets.append(
        {
            "defectId": "EMPTY",
            "title": "系数仿真界面左侧图像框无法选择",
            "pool": "locatable_only",
            "expectQuality": "ambiguous",
        }
    )
    matches.append(
        {"defectId": "EMPTY", "candidates": [], "confidence": "low", "gap": "no_path_token_overlap"}
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
    pairs = select_prompt_tickets(req)
    assert len(pairs) == MAX_PROMPT_TICKETS
    assert pairs[0][0].defectId == "EMPTY"
    prompt = _build_prompt(req, prompt_pairs=pairs)
    assert '"defectId": "EMPTY"' in prompt  # 真弱票一定在
    assert '"defectId": "S0"' in prompt
    assert f'"defectId": "S{MAX_PROMPT_TICKETS}"' not in prompt
