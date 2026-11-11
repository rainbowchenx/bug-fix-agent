"""Agent-2 读码评测：夹具建图 + hit@k（关闭 SDK）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_platform.agents.cartographer.detect import normalize_cartography_profile
from bugfix_contracts.defect_batch import BatchTicket, DefectBatch
from bugfix_platform.sdk.cartography import PROFILE_READING_PLAYBOOK, profile_reading_playbook

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "test" / "fixtures" / "repos"
EVAL_CASES = json.loads((FIXTURES / "eval-cases.json").read_text(encoding="utf-8"))


def _batch(tickets: list[dict] | None = None) -> DefectBatch:
    payload = {
        "schemaVersion": "0.1.0",
        "productLine": "hc",
        "posture": "alpha",
        "generatedAt": "2026-01-01T00:00:00Z",
        "funnel": {"total": len(tickets or []), "strict": len(tickets or [])},
        "clusters": [],
        "tickets": tickets or [],
    }
    return DefectBatch.model_validate(payload)


def _knowledge(fixture: str, profile: str, tickets: list[dict] | None = None):
    return run_cartographer(
        work_dir=FIXTURES / fixture,
        defect_batch=_batch(tickets),
        cartography_mode="heuristic",
        cartography_profile=profile,
    )


def _roles(knowledge) -> set[str]:
    return {m.role for m in knowledge.architecture.modules if m.role}


def _ids(knowledge) -> set[str]:
    return {m.id for m in knowledge.architecture.modules}


def _hit_at_k(knowledge, defect_id: str, prefix: str, k: int = 3) -> bool:
    prefix = prefix.replace("\\", "/").rstrip("/")
    for match in knowledge.defectCodeMatches:
        if match.defectId != defect_id:
            continue
        for cand in match.candidates[:k]:
            rel = cand.path.replace("\\", "/")
            if cand.repoPath not in (".", "", None):
                rel = f"{cand.repoPath.rstrip('/')}/{rel.lstrip('/')}"
            path = rel.replace("\\", "/")
            if path == prefix or path.startswith(prefix) or path.endswith(prefix):
                return True
        return False
    return False


def test_normalize_profile_rejects_unknown_values():
    assert normalize_cartography_profile(None) == "unknown"
    assert normalize_cartography_profile("micro_frontend") == "micro_frontend"
    with pytest.raises(ValueError, match="unsupported cartographyProfile"):
        normalize_cartography_profile("qiankun")


def test_without_profile_stays_unknown():
    knowledge = run_cartographer(
        work_dir=FIXTURES / "micro-frontend",
        defect_batch=_batch(),
        cartography_mode="heuristic",
    )
    assert knowledge.cartographyProfile == "unknown"
    assert knowledge.partial is True


def test_caller_profile_not_overridden_by_asp_host():
    knowledge = _knowledge("device-web-host-mf", "micro_frontend")
    assert knowledge.cartographyProfile == "micro_frontend"
    assert "Preview" in _ids(knowledge)
    assert "Playback" in _ids(knowledge)
    roles = {m.id: m.role for m in knowledge.architecture.modules}
    assert roles.get("Preview") == "micro_app"
    assert roles.get("Common") == "shared_kernel"


def test_micro_frontend_catalog_from_gitmodules():
    knowledge = _knowledge("micro-frontend", "micro_frontend")
    ids = _ids(knowledge)
    assert {"Person", "AppA", "AppB"} <= ids
    assert "VehicleManage" not in ids  # decoy dir, no vue.app.js / gitmodule
    roles = {m.id: m.role for m in knowledge.architecture.modules}
    assert roles["Person"] == "micro_app"
    assert roles["Common"] == "shared_kernel"
    assert any(ep.endswith("root-application.js") for ep in knowledge.architecture.entryPoints)


def test_micro_frontend_in_repo_uses_mount_divs():
    knowledge = _knowledge("micro-frontend-in-repo", "micro_frontend")
    ids = _ids(knowledge)
    assert {"Preview", "Playback", "Portal"} <= ids
    assert knowledge.cartographyProfile == "micro_frontend"


def test_device_web_dual_entry_and_device_js():
    knowledge = _knowledge("device-web", "device_web")
    entries = [e.replace("\\", "/") for e in knowledge.architecture.entryPoints]
    assert any(e.endswith("src/main-pc.js") for e in entries)
    assert any(e.endswith("src/main-mobile.js") for e in entries)
    roles = _roles(knowledge)
    assert "device_capability" in roles
    assert "device_bridge" in roles
    assert "route_module" in roles
    assert "route_table" in roles
    assert "micro_app" not in roles
    assert {"Config", "Preview"} <= _ids(knowledge)
    assert any(i.startswith("Config.") for i in _ids(knowledge))
    paths = [m.path or "" for m in knowledge.architecture.modules]
    assert any(p.replace("\\", "/").endswith("device.js") for p in paths)
    assert any("jsWebControl" in (p.replace("\\", "/")) for p in paths)


def test_electron_roles_do_not_mark_vue_main_as_process():
    knowledge = _knowledge("electron", "electron_node")
    by_role = {}
    for mod in knowledge.architecture.modules:
        by_role.setdefault(mod.role, []).append((mod.path or "").replace("\\", "/"))
    assert "main" in by_role
    assert "preload" in by_role
    assert "renderer" in by_role
    assert all("/views/" not in p for p in by_role["main"])
    assert all(not p.endswith("web/src/main.ts") for p in by_role["main"])
    assert any(p.endswith("web/src/main.ts") for p in by_role["renderer"])
    assert any("Message/main.vue" not in p for p in by_role["main"])
    assert any(p.endswith("preload/index.ts") for p in by_role["preload"])
    assert "driver_asset" in by_role
    prefixes = {b.get("prefix") for b in knowledge.specAtlas.bindings if b.get("kind") == "ipc"}
    assert "BoxManage" in prefixes
    ids = _ids(knowledge)
    assert "boxCalibration" in ids


def test_electron_container_ignores_vite_plugin_only_service():
    knowledge = _knowledge("electron-container", "electron_node")
    paths = [(m.path or "").replace("\\", "/") for m in knowledge.architecture.modules]
    assert any("calibrationtool" in p or p.startswith("electron/") or "web/src" in p for p in paths)
    joined = " ".join(paths)
    assert "calibration-subsystem/src/index.ts" not in joined
    assert knowledge.cartographyProfile == "electron_node"


@pytest.mark.parametrize("case", EVAL_CASES["cases"], ids=lambda c: c["id"])
def test_eval_hit_at_3(case: dict):
    knowledge = _knowledge(case["fixture"], case["profile"], [case["ticket"]])
    assert knowledge.cartographyProfile == case["profile"]
    assert _hit_at_k(knowledge, case["ticket"]["defectId"], case["expectPathPrefix"], k=3), (
        f"{case['id']} missed {case['expectPathPrefix']!r} in "
        f"{[c.path for m in knowledge.defectCodeMatches for c in m.candidates]}"
    )


def test_eval_hit_at_1_for_primary_anchors():
    """主锚点（子应用 / device.js / controller）要求 hit@1。"""
    primary = {"mf-person-module", "dw-wiper-capability", "el-ipc-box"}
    for case in EVAL_CASES["cases"]:
        if case["id"] not in primary:
            continue
        knowledge = _knowledge(case["fixture"], case["profile"], [case["ticket"]])
        assert _hit_at_k(
            knowledge, case["ticket"]["defectId"], case["expectPathPrefix"], k=1
        ), case["id"]


def test_profile_reading_playbook_covers_all_types():
    for profile in ("micro_frontend", "device_web", "electron_node", "unknown"):
        text = profile_reading_playbook(profile)
        assert profile.split("_")[0] in text or "unknown" in text
        assert profile in PROFILE_READING_PLAYBOOK
    assert "vue.app.js" in profile_reading_playbook("micro_frontend")
    assert "device.js" in profile_reading_playbook("device_web")
    assert "contextBridge" in profile_reading_playbook("electron_node")
    assert "do not guess" in profile_reading_playbook("unknown")
