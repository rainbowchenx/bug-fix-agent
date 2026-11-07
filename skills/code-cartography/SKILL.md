---
name: code-cartography
description: Agent-2 Code Cartographer SOP — read CLAUDE.md, detect cartography profile, map architecture, match defects to code paths into code-knowledge. Use when preparing or enriching code-knowledge for Agent-3; never freestyle schema fields or invent paths.
profiles: cartography
---

# Code Cartography（Agent-2）

SOP for building `code-knowledge`. Prefer the Python entrypoint; use this skill to guide Claude Code / SDK sessions.

## Do / Don't

| Do | Don't |
|---|---|
| Read target `CLAUDE.md` / `.claude` first | Invent file paths that do not exist |
| Call `run_cartographer` / heuristic detect+match | Dump full ticket observed/expected/steps into matching queries |
| Cap candidates at **3** per defect; empty OK with `confidence=low` | Exceed candidate cap or invent non-existent paths |
| Follow profile biases (electron / micro_frontend / device_web) | Write `CODEBASE_MAP.md` or edit target repo by default |

## Pipeline

```text
workDir + defect-batch
  → discover repoRoots
  → detect cartographyProfile + techStack
  → map architecture (entryPoints / modules by profile)
  → match tickets (title + titleTag/testModule/intent tokens → paths)
  → optional SDK enrich (Read/Glob/Grep only)
  → validate_code_knowledge → code-knowledge.json
```

### Code entrypoint

```python
from bugfix_agent import run_cartographer, run_defect_batch_prepare

batch = run_defect_batch_prepare(product_line="hc", source="./raw.json", posture="alpha")
knowledge = run_cartographer(
    work_dir="./repos",
    defect_batch=batch,
    cartography_mode="heuristic",  # or "sdk"
)
```

## Confidence

| Situation | Level |
|---|---|
| No candidates | `low` |
| Single path/grep hit | `medium` |
| ≥2 path hits, or CodeGraph hit | `high`（**不**因缺少 CodeGraph 能力而封顶） |
| Missing titleTag/testModule/intent (A1) | ≤ `medium` |

## Profile biases

- **electron_node**: crash/tray/IPC → main/preload; UI copy → renderer
- **micro_frontend**: testModule/titleTag → micro-app package, then search
- **device_web**: device/bridge tokens → bridge modules before pure H5

## Output contract

See `docs/contracts/v0.1/code-knowledge.md` (Pydantic SSOT: `bugfix_agent/contracts/code_knowledge.py`).

## Related package skills

- `electron-process-boundary` — electron process roles
- `monorepo-workspace` — multi-root layout
- `hierarchical-localization` — localization hierarchy when matching UI defects
